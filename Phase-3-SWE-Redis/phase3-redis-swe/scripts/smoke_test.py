"""
scripts/smoke_test.py
=====================
Runs the whole Phase 3 surface against a real Redis and the real FastAPI app,
printing what happens at each step. This is your "did I understand it?" check.

Run:  python -m scripts.smoke_test      (needs Redis on localhost:6379)

It uses httpx.ASGITransport, so no server process is needed - requests are fed
straight into the ASGI app in-process.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from app.config import settings
from app.main import app
from app.pubsub.events import CHANNEL_SESSIONS
from app.queue.producer import enqueue, queue_key, queue_stats
from app.rate_limit import RateLimiter
from app.redis_client import close_redis, create_redis, new_client


def head(title: str) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


async def main() -> None:
    # httpx's ASGITransport does NOT run FastAPI's lifespan events, so the
    # shared client that `lifespan` normally builds must be created by hand.
    create_redis()
    r = new_client()
    await r.flushdb()  # clean slate (NEVER run this against production)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:

        # ------------------------------------------------------------------
        head("1. HEALTH")
        print((await c.get("/health")).json())

        # ------------------------------------------------------------------
        head("2. REGISTER  (+ welcome email job goes on the queue)")
        creds = {"email": "dev@example.com", "password": "supersecret123"}
        res = await c.post("/auth/register", json=creds)
        print(res.status_code, res.json())
        print("duplicate signup ->", (await c.post("/auth/register", json=creds)).status_code, "(409 expected)")
        print("queue stats:", await queue_stats(r, settings.queue_name))

        # ------------------------------------------------------------------
        head("3. LOGIN  -> session in Redis")
        res = await c.post("/auth/login", json=creds)
        sid = res.json()["session_id"]
        print("session_id:", sid[:12] + "...")
        print("HASH sess:{sid} =", json.dumps(await r.hgetall(f"sess:{sid}"), indent=2)[:400])
        print("TTL seconds:", await r.ttl(f"sess:{sid}"))

        # ------------------------------------------------------------------
        head("4. PROTECTED ROUTE")
        print("cookie auth   ->", (await c.get("/auth/me")).json())
        bearer = {"Authorization": f"Bearer {sid}"}
        print("bearer auth   ->", (await c.get("/auth/me", headers=bearer)).status_code)
        no_cookie = httpx.AsyncClient(transport=transport, base_url="http://test")
        print("no credentials->", (await no_cookie.get("/auth/me")).status_code, "(401 expected)")

        # ------------------------------------------------------------------
        head("5. WRONG PASSWORD + LOGIN RATE LIMIT (sliding window, 5/60s)")
        bad = {**creds, "password": "wrongpassword"}
        for i in range(1, 8):
            code = (await no_cookie.post("/auth/login", json=bad)).status_code
            print(f"  attempt {i}: HTTP {code}")
        print("ZSET rl:slide:login:email:... size =", await r.zcard("rl:slide:login:email:dev@example.com"))

        # ------------------------------------------------------------------
        head("6. MULTI-DEVICE SESSIONS + max_sessions_per_user")
        # Step 5 just burned this account's login budget, so clear it - proof
        # that the limiter is real and that it is keyed per account.
        await r.delete("rl:slide:login:email:dev@example.com")
        user_id = await r.get("user:byemail:dev@example.com")
        index = f"user:sessions:{user_id}"

        fresh = httpx.AsyncClient(transport=transport, base_url="http://test")
        for i in range(5):  # 1 existing + 5 new = 6 > limit of 5
            await fresh.post("/auth/login", json=creds)
            fresh.cookies.clear()  # pretend each login is a different device
            print(f"  login {i + 1}: ZSET {index[:22]}... size = {await r.zcard(index)}")

        # The OLDEST session (the one from step 3) was evicted to keep the cap.
        print("original session now ->", (await c.get("/auth/me")).status_code, "(401: evicted)")

        await c.post("/auth/login", json=creds)  # log this client back in
        listed = await c.get("/auth/sessions")
        print("GET /auth/sessions ->", len(listed.json()["sessions"]), "device(s) listed")

        # ------------------------------------------------------------------
        head("7. TOKEN BUCKET  (capacity 20, cost 5 -> 4 fast calls then 429)")
        for i in range(1, 7):
            res = await c.get("/api/expensive")
            body = res.json()
            print(f"  call {i}: HTTP {res.status_code} {body.get('tokens_left', body.get('detail'))}")

        # ------------------------------------------------------------------
        head("8. FORGOT PASSWORD  (one-time token with TTL)")
        print((await c.post("/auth/forgot", json={"email": creds["email"]})).json())
        token_keys = [k async for k in r.scan_iter(match="pwreset:*")]
        print("token key:", token_keys[0][:20] + "...", "TTL:", await r.ttl(token_keys[0]))

        # ------------------------------------------------------------------
        head("9. PUB/SUB  (logout-all fan-out)")
        sub = new_client()
        ps = sub.pubsub(ignore_subscribe_messages=True)
        await ps.subscribe(CHANNEL_SESSIONS)
        await asyncio.sleep(0.2)  # give the subscription time to register
        res = await c.post("/auth/logout-all")
        print("revoked:", res.json())
        # get_message() also returns the subscribe confirmation, and returns
        # None while nothing is buffered -> always poll in a loop.
        received = None
        for _ in range(20):
            msg = await ps.get_message(timeout=0.2)
            if msg and msg.get("type") == "message":
                received = msg["data"]
                break
        print("subscriber received:", received or "NOTHING (subscriber was late!)")
        await ps.aclose()
        await sub.aclose()

        print("session after logout-all ->", (await c.get("/auth/me")).status_code, "(401 expected)")

        # ------------------------------------------------------------------
        head("10. QUEUE: retries + dead letter (run the worker to watch it)")
        await enqueue(r, settings.queue_name, "flaky", {"note": "always fails"})
        print("pending jobs:", await r.llen(queue_key(settings.queue_name)))
        print("stats:", await queue_stats(r, settings.queue_name))
        print("\nNow run in another terminal:  python -m app.queue.worker")

        await no_cookie.aclose()
        await fresh.aclose()

    await r.aclose()
    await close_redis()
    print("\nSmoke test finished.")


if __name__ == "__main__":
    asyncio.run(main())
