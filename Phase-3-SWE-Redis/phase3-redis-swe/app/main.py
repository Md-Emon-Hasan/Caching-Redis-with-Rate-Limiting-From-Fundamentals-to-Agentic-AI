"""
main.py
=======
PROJECT 2: AUTHENTICATION SERVICE  (the Phase 3 deliverable)

Everything the phase teaches, wired into one service:

    POST /auth/register     create user      -> queue welcome email
    POST /auth/login        sliding-window rate limit -> session -> cookie
    GET  /auth/me           session lookup (protected)
    GET  /auth/sessions     list my devices
    POST /auth/logout       revoke this session      -> publish event
    POST /auth/logout-all   revoke every session     -> publish event
    POST /auth/forgot       enqueue reset email (always 200, no user leak)
    GET  /api/expensive     token-bucket limited endpoint
    GET  /health            liveness + Redis check
    GET  /admin/queue       queue depth metrics

Run:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.config import settings
from app.deps import (
    client_ip,
    current_session,
    limiter,
    rate_limit,
    redis_dep,
    session_store,
    user_repo,
)
from app.pubsub.events import publish_session_event
from app.queue.producer import enqueue, queue_stats
from app.rate_limit import RateLimiter
from app.redis_client import close_redis, create_redis
from app.security import new_session_id
from app.sessions import Session, SessionStore
from app.users import UserRepo


# ---------------------------------------------------------------- lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Connection pool is built ONCE here and torn down on shutdown.
    This is the single most important structural habit: never build a Redis
    client inside a request handler.
    """
    create_redis()
    yield
    await close_redis()


app = FastAPI(title="Phase 3 - Redis Auth Service", version="1.0.0", lifespan=lifespan)


# ------------------------------------------------------------------ schemas
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class EmailOnly(BaseModel):
    email: EmailStr


# -------------------------------------------------------------------- routes
@app.post("/auth/register", status_code=201)
async def register(
    body: Credentials,
    request: Request,
    users: UserRepo = Depends(user_repo),
    r=Depends(redis_dep),
    _=Depends(rate_limit("register", 3, 3600)),  # 3 signups per IP per hour
):
    user_id = await users.create(body.email, body.password)
    if user_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    # Slow side effects go on the queue - the response does not wait for them.
    job_id = await enqueue(
        r, settings.queue_name, "welcome_email", {"email": body.email, "user_id": user_id}
    )
    return {"user_id": user_id, "welcome_email_job": job_id}


@app.post("/auth/login")
async def login(
    body: Credentials,
    request: Request,
    response: Response,
    users: UserRepo = Depends(user_repo),
    store: SessionStore = Depends(session_store),
    rl: RateLimiter = Depends(limiter),
    r=Depends(redis_dep),
):
    """
    TWO-DIMENSIONAL RATE LIMITING - the pattern real login endpoints use.

      per IP    stops one host brute-forcing many accounts
      per email stops a botnet (many IPs) brute-forcing ONE account

    Both must pass. And we only consume the *email* budget on FAILURE, so a
    legitimate user logging in repeatedly is never locked out.
    """
    ip = client_ip(request)

    ip_check = await rl.sliding_window(
        f"login:ip:{ip}", settings.login_limit * 4, settings.login_window_seconds
    )
    if not ip_check.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many login attempts from this IP",
            headers={"Retry-After": str(ip_check.retry_after_seconds)},
        )

    email_key = f"login:email:{body.email.lower()}"
    email_check = await rl.sliding_window(
        email_key, settings.login_limit, settings.login_window_seconds
    )
    if not email_check.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed attempts for this account. Try again later.",
            headers={"Retry-After": str(email_check.retry_after_seconds)},
        )

    user = await users.authenticate(body.email, body.password)
    if user is None:
        # Generic message: never reveal whether the email exists.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    # Success -> refund the failed-attempt budget for this account.
    await r.delete(f"rl:slide:{email_key}")

    session = await store.create(
        user_id=user["id"],
        email=user["email"],
        ip=ip,
        user_agent=request.headers.get("user-agent", ""),
    )

    # HttpOnly  -> JavaScript cannot read it (blocks XSS token theft)
    # SameSite=lax -> not sent on cross-site POSTs (basic CSRF defence)
    # secure=True -> HTTPS only; set False for local http testing
    response.set_cookie(
        settings.session_cookie_name,
        session.sid,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=False,
    )

    await publish_session_event(r, "login", user_id=user["id"], ip=ip)
    return {
        "session_id": session.sid,  # returned for curl/mobile clients
        "csrf_token": session.csrf,
        "expires_in": settings.session_ttl_seconds,
    }


@app.get("/auth/me")
async def me(session: Session = Depends(current_session)):
    """Protected route. Reaching the body means the session was valid."""
    return {
        "user_id": session.user_id,
        "email": session.email,
        "session_age_seconds": session.age_seconds,
        "last_seen_at": session.last_seen_at,
    }


@app.get("/auth/sessions")
async def my_sessions(
    session: Session = Depends(current_session),
    store: SessionStore = Depends(session_store),
):
    """"Where am I logged in?" - powered by the per-user ZSET index."""
    return {"sessions": await store.list_for_user(session.user_id)}


@app.post("/auth/logout")
async def logout(
    response: Response,
    session: Session = Depends(current_session),
    store: SessionStore = Depends(session_store),
    r=Depends(redis_dep),
):
    await store.destroy(session.sid)
    response.delete_cookie(settings.session_cookie_name)
    await publish_session_event(r, "logout", sid=session.sid, user_id=session.user_id)
    return {"ok": True}


@app.post("/auth/logout-all")
async def logout_all(
    response: Response,
    session: Session = Depends(current_session),
    store: SessionStore = Depends(session_store),
    r=Depends(redis_dep),
):
    """
    Instant global revocation - the killer feature of server-side sessions.
    The Pub/Sub event tells other pods to drop any locally cached copy.
    """
    count = await store.destroy_all(session.user_id)
    response.delete_cookie(settings.session_cookie_name)
    await publish_session_event(r, "logout_all", user_id=session.user_id)
    return {"revoked_sessions": count}


@app.post("/auth/forgot")
async def forgot_password(
    body: EmailOnly,
    users: UserRepo = Depends(user_repo),
    r=Depends(redis_dep),
    _=Depends(rate_limit("forgot", 3, 900)),  # 3 per IP per 15 min
):
    """
    Always returns 200 whether or not the email exists (no enumeration).
    The token lives in Redis with a TTL - the perfect one-time-secret store:
    short lived, single use (DEL on use), and automatically cleaned up.
    """
    user_id = await r.get(f"user:byemail:{body.email.strip().lower()}")
    if user_id:
        token = new_session_id()
        await r.setex(f"pwreset:{token}", 900, user_id)  # 15 minute validity
        await enqueue(
            r, settings.queue_name, "password_reset", {"email": body.email, "token": token}
        )
    return {"message": "If that account exists, a reset link has been sent."}


@app.get("/api/expensive")
async def expensive_endpoint(
    request: Request,
    session: Session = Depends(current_session),
    rl: RateLimiter = Depends(limiter),
):
    """
    TOKEN BUCKET in action, per user, with a cost of 5 tokens per call.
    Capacity 20 => a client may burst 4 calls instantly, then must wait for the
    bucket to refill at 2 tokens/sec. This is exactly how you protect an
    expensive resource (an LLM call, a report generator) from a hot client.
    """
    result = await rl.token_bucket(
        f"expensive:{session.user_id}",
        capacity=settings.api_bucket_capacity,
        refill_per_sec=settings.api_bucket_refill_per_sec,
        cost=5,
    )
    if not result.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Bucket empty - slow down",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    return {"result": "expensive work done", "tokens_left": round(result.remaining, 2)}


@app.get("/health")
async def health(r=Depends(redis_dep)):
    """
    Liveness probes must be cheap AND must actually test the dependency.
    A health check that returns 200 while Redis is down is worse than none.
    """
    started = time.perf_counter()
    try:
        await r.ping()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"redis down: {exc}")
    return {"status": "ok", "redis_ping_ms": round((time.perf_counter() - started) * 1000, 2)}


@app.get("/admin/queue")
async def queue_depth(r=Depends(redis_dep)):
    return await queue_stats(r, settings.queue_name)
