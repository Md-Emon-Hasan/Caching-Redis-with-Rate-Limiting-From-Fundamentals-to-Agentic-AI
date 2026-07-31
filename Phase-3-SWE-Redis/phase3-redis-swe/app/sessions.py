"""
sessions.py
===========
SESSION MANAGEMENT WITH REDIS  (Phase 3, topic 1)

THE PROBLEM
    HTTP is stateless. After a user logs in, the next request must be
    recognised as "the same logged-in user". Two common answers:

    A) Stateless JWT
         + no server storage, scales trivially
         - you CANNOT revoke a token before it expires (logout is a lie),
           and any change to permissions is delayed until expiry

    B) Server-side session (what we build here)
         + instant revocation: DEL the key and the user is out
         + you can list/kill devices, store arbitrary session data
         - needs a fast shared store -> exactly Redis' job
         (Redis makes the "downside" disappear: O(1) lookup, sub-ms, shared by
          every app instance, and TTL-based expiry is built in.)

DATA MODEL
    sess:{sid}                HASH  -> user_id, email, ip, ua, created_at,
                                       last_seen_at, csrf
    user:sessions:{user_id}   ZSET  -> member=sid, score=expires_at (epoch sec)

    Why a HASH and not one JSON string?
        With a HASH you can read/update a single field (HGET / HSET) without
        deserialising the whole blob. Cheaper, and no read-modify-write race.

    Why a ZSET for the per-user index?
        A SET would work for "list my devices", but SET members do not expire
        individually, so it slowly fills with dead session IDs. With a ZSET
        scored by expiry we can prune in O(log N) using ZREMRANGEBYSCORE, and
        also enforce "max 5 devices" by evicting the OLDEST session.

EXPIRY STRATEGY: SLIDING WINDOW + ABSOLUTE CAP
    Every authenticated request refreshes the TTL (EXPIRE) so an active user is
    never logged out mid-work. But `created_at` is checked against an absolute
    maximum, so a stolen session cannot live forever by being kept warm.

    Never store sessions without a TTL. A session key with no TTL is a memory
    leak that grows with every login for the lifetime of your service.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis.asyncio import Redis

from app.config import settings
from app.security import new_csrf_token, new_session_id


def session_key(sid: str) -> str:
    return f"sess:{sid}"


def user_sessions_key(user_id: str) -> str:
    return f"user:sessions:{user_id}"


@dataclass
class Session:
    """Plain object the rest of the app works with (no Redis types leak out)."""

    sid: str
    user_id: str
    email: str
    ip: str
    user_agent: str
    created_at: int
    last_seen_at: int
    csrf: str

    @property
    def age_seconds(self) -> int:
        return int(time.time()) - self.created_at


class SessionStore:
    """All session reads/writes go through this class - one place to audit."""

    def __init__(self, redis: Redis) -> None:
        self.r = redis
        self.ttl = settings.session_ttl_seconds
        self.abs_max = settings.session_absolute_max_seconds
        self.max_devices = settings.max_sessions_per_user

    # ------------------------------------------------------------------ create
    async def create(
        self, *, user_id: str, email: str, ip: str, user_agent: str
    ) -> Session:
        """
        Create a session for a successful login.

        Everything happens inside a PIPELINE with transaction=True, i.e. Redis
        MULTI/EXEC: all commands are queued client-side, sent in ONE round trip,
        and executed atomically by the single-threaded Redis server. Two wins:
            * latency: 4 commands = 1 RTT instead of 4
            * atomicity: no other client sees a half-created session
        """
        sid = new_session_id()
        now = int(time.time())
        expires_at = now + self.ttl

        fields = {
            "user_id": user_id,
            "email": email,
            "ip": ip,
            "user_agent": user_agent[:200],  # cap attacker-controlled input
            "created_at": now,
            "last_seen_at": now,
            "csrf": new_csrf_token(),
        }

        async with self.r.pipeline(transaction=True) as pipe:
            pipe.hset(session_key(sid), mapping=fields)
            # EXPIRE is what makes cleanup automatic. Redis deletes the key for
            # us - no cron job, no DELETE FROM sessions WHERE expired.
            pipe.expire(session_key(sid), self.ttl)
            # Index this session under the user so we can list / revoke devices.
            pipe.zadd(user_sessions_key(user_id), {sid: expires_at})
            # The index itself gets a TTL too: if the user never returns, the
            # whole key disappears instead of lingering forever.
            pipe.expire(user_sessions_key(user_id), self.abs_max)
            await pipe.execute()

        await self._enforce_device_limit(user_id)
        return Session(sid=sid, **{**fields, "created_at": now, "last_seen_at": now})

    async def _enforce_device_limit(self, user_id: str) -> None:
        """
        Keep at most N live sessions per user ("logged in on too many devices").

        Step 1: drop already-expired entries (score < now) - cheap housekeeping.
        Step 2: if still over the limit, remove the oldest ones (lowest score).
        """
        key = user_sessions_key(user_id)
        now = int(time.time())
        await self.r.zremrangebyscore(key, 0, now)

        overflow = await self.r.zcard(key) - self.max_devices
        if overflow > 0:
            oldest = await self.r.zrange(key, 0, overflow - 1)
            async with self.r.pipeline(transaction=True) as pipe:
                for sid in oldest:
                    pipe.delete(session_key(sid))  # kill the session itself
                pipe.zrem(key, *oldest)            # and its index entry
                await pipe.execute()

    # -------------------------------------------------------------------- read
    async def get(self, sid: str, *, touch: bool = True) -> Session | None:
        """
        Load a session. Returns None if it does not exist, has expired, or has
        exceeded the absolute max age.

        `touch=True` implements the sliding window: we extend the TTL and update
        last_seen_at on every authenticated request.
        """
        if not sid:
            return None

        data = await self.r.hgetall(session_key(sid))
        if not data:
            # Either never existed or Redis already expired it. Same answer to
            # the caller: not authenticated. This is why TTL is your friend.
            return None

        now = int(time.time())
        created_at = int(data["created_at"])

        # Absolute cap: a session cannot be kept alive forever by activity.
        if now - created_at > self.abs_max:
            await self.destroy(sid)
            return None

        if touch:
            async with self.r.pipeline(transaction=True) as pipe:
                pipe.hset(session_key(sid), "last_seen_at", now)
                pipe.expire(session_key(sid), self.ttl)  # slide the window
                # Keep the index score in sync with the real expiry.
                pipe.zadd(user_sessions_key(data["user_id"]), {sid: now + self.ttl})
                await pipe.execute()

        return Session(
            sid=sid,
            user_id=data["user_id"],
            email=data["email"],
            ip=data.get("ip", ""),
            user_agent=data.get("user_agent", ""),
            created_at=created_at,
            last_seen_at=now if touch else int(data["last_seen_at"]),
            csrf=data.get("csrf", ""),
        )

    async def list_for_user(self, user_id: str) -> list[dict]:
        """
        "Where am I logged in?" - one ZSET read + one pipelined HGETALL burst.

        NOTE: N+1 lookups are fine here because we pipeline them into a single
        round trip. Never loop with `await` per key in a hot path.
        """
        key = user_sessions_key(user_id)
        now = int(time.time())
        await self.r.zremrangebyscore(key, 0, now)  # prune dead entries first
        sids = await self.r.zrange(key, 0, -1)
        if not sids:
            return []

        async with self.r.pipeline(transaction=False) as pipe:
            for sid in sids:
                pipe.hgetall(session_key(sid))
            rows = await pipe.execute()

        out = []
        for sid, row in zip(sids, rows):
            if not row:
                continue
            out.append(
                {
                    "sid_preview": sid[:8] + "...",  # never leak the full secret
                    "ip": row.get("ip"),
                    "user_agent": row.get("user_agent"),
                    "created_at": int(row["created_at"]),
                    "last_seen_at": int(row["last_seen_at"]),
                }
            )
        return out

    # ------------------------------------------------------------------ delete
    async def destroy(self, sid: str) -> bool:
        """Logout of ONE device. DEL is O(1) and revocation is instant."""
        user_id = await self.r.hget(session_key(sid), "user_id")
        async with self.r.pipeline(transaction=True) as pipe:
            pipe.delete(session_key(sid))
            if user_id:
                pipe.zrem(user_sessions_key(user_id), sid)
            results = await pipe.execute()
        return bool(results[0])

    async def destroy_all(self, user_id: str) -> int:
        """
        Logout everywhere - what you run after a password change or a breach.
        This is the feature stateless JWTs cannot give you for free.
        """
        key = user_sessions_key(user_id)
        sids = await self.r.zrange(key, 0, -1)
        async with self.r.pipeline(transaction=True) as pipe:
            for sid in sids:
                pipe.delete(session_key(sid))
            pipe.delete(key)
            await pipe.execute()
        return len(sids)
