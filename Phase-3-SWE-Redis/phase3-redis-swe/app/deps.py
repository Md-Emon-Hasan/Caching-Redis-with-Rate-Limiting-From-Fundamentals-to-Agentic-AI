"""
deps.py
=======
FastAPI dependencies: the glue that turns the Redis modules into reusable
request-level behaviour.

TWO IDEAS TO TAKE AWAY
 1) Auth as a dependency: the handler receives a `Session` or the request is
    rejected before the handler ever runs. No `if not logged_in` copy-paste.
 2) Rate limiting as a dependency FACTORY: `rate_limit("login", 5, 60)` returns
    a dependency, so each route declares its own budget declaratively.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.config import settings
from app.rate_limit import RateLimiter
from app.redis_client import get_client
from app.sessions import Session, SessionStore
from app.users import UserRepo


# ---------------------------------------------------------------- plumbing
def redis_dep():
    return get_client()


def session_store(r=Depends(redis_dep)) -> SessionStore:
    return SessionStore(r)


def user_repo(r=Depends(redis_dep)) -> UserRepo:
    return UserRepo(r)


def limiter(r=Depends(redis_dep)) -> RateLimiter:
    return RateLimiter(r)


def client_ip(request: Request) -> str:
    """
    Behind a proxy, request.client.host is the PROXY's IP - so every user shares
    one rate-limit bucket. Read X-Forwarded-For instead, but only trust it if
    your own load balancer sets it (a client can forge this header).
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# -------------------------------------------------------------------- auth
async def current_session(
    request: Request,
    store: SessionStore = Depends(session_store),
) -> Session:
    """
    Resolve the caller's session or raise 401.

    We accept the session id from either
      * an HttpOnly cookie  (browsers - immune to JS/XSS token theft)
      * `Authorization: Bearer <sid>`  (mobile apps, curl, service clients)
    """
    sid = request.cookies.get(settings.session_cookie_name)
    if not sid:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            sid = auth[7:].strip()

    session = await store.get(sid or "")  # touch=True slides the TTL
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated (missing, expired or revoked session)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session


# ------------------------------------------------------------ rate limiting
def rate_limit(bucket: str, limit: int, window: int, *, per: str = "ip"):
    """
    Dependency factory. Usage:

        @app.get("/search", dependencies=[Depends(rate_limit("search", 30, 60))])

    `per="ip"`   -> one budget per client IP  (works for anonymous endpoints)
    `per="user"` -> one budget per logged-in user (fairer, needs a session)
    """

    async def _dep(
        request: Request,
        rl: RateLimiter = Depends(limiter),
        store: SessionStore = Depends(session_store),
    ) -> None:
        if per == "user":
            sid = request.cookies.get(settings.session_cookie_name, "")
            s = await store.get(sid, touch=False) if sid else None
            identity = f"user:{s.user_id}" if s else f"ip:{client_ip(request)}"
        else:
            identity = f"ip:{client_ip(request)}"

        result = await rl.sliding_window(f"{bucket}:{identity}", limit, window)
        if not result.allowed:
            # 429 + Retry-After is the correct, well-behaved response. Good
            # clients back off instead of hammering you harder.
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {limit} requests per {window}s",
                headers={
                    "Retry-After": str(result.retry_after_seconds),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

    return _dep
