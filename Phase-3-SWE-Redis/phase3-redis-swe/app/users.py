"""
users.py
========
A deliberately tiny "database" so the project runs with only Redis.

READ THIS BEFORE COPYING TO PRODUCTION
    Users are *durable* business data. They belong in Postgres/MySQL, not in a
    cache. Redis here plays the role your real DB would play, only so that
    Phase 3 needs one container instead of two.

    What IS legitimate Redis usage for users:
        - caching a user row that is read on every request (Phase 4/5 topic)
        - the email -> user_id unique index shown below, as a cache in front of
          a DB-level unique constraint

ATOMIC UNIQUENESS
    `SET key value NX` = "set only if it does not exist" and returns whether it
    won. That single command is a distributed lock on the email address: two
    concurrent signups with the same email cannot both succeed. Doing
    EXISTS-then-SET instead would be a race.
"""

from __future__ import annotations

import time
import uuid

from redis.asyncio import Redis

from app.security import hash_password, verify_password


def user_key(user_id: str) -> str:
    return f"user:{user_id}"


def email_index_key(email: str) -> str:
    # Normalise before indexing, otherwise "A@x.com" and "a@x.com" are 2 users.
    return f"user:byemail:{email.strip().lower()}"


class UserRepo:
    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def create(self, email: str, password: str) -> str | None:
        """Returns the new user_id, or None if the email is already taken."""
        email = email.strip().lower()
        user_id = uuid.uuid4().hex

        # NX makes this the atomic "claim the email" step.
        won = await self.r.set(email_index_key(email), user_id, nx=True)
        if not won:
            return None

        await self.r.hset(
            user_key(user_id),
            mapping={
                "id": user_id,
                "email": email,
                "password_hash": hash_password(password),
                "created_at": int(time.time()),
            },
        )
        return user_id

    async def authenticate(self, email: str, password: str) -> dict | None:
        """
        Returns the user dict on success, None on wrong email OR wrong password.

        Notice we do the same amount of work in both failure cases (see the
        dummy verify below): otherwise response timing tells an attacker which
        email addresses exist - a user-enumeration leak.
        """
        user_id = await self.r.get(email_index_key(email))
        if not user_id:
            verify_password(password, "pbkdf2$200000$00$00")  # burn equivalent time
            return None

        user = await self.r.hgetall(user_key(user_id))
        if not user or not verify_password(password, user["password_hash"]):
            return None
        return user

    async def get(self, user_id: str) -> dict | None:
        user = await self.r.hgetall(user_key(user_id))
        return user or None
