"""
config.py
=========
All tunable knobs in one place. Real services read these from environment
variables so the same image can run in dev / staging / prod unchanged.

Key naming convention used across this project (learn this - it matters more
than any single command):

    <domain>:<entity>:<id>[:<sub>]

    sess:{sid}                  HASH   one login session
    user:sessions:{user_id}     ZSET   sid -> expiry timestamp (device list)
    user:byemail:{email}        STRING email -> user_id  (unique index)
    user:{user_id}              HASH   the "database" row (fake DB)
    rl:fixed:{scope}:{window}   STRING counter for fixed-window limiter
    rl:slide:{scope}            ZSET   request log for sliding-window limiter
    rl:bucket:{scope}           HASH   token-bucket state
    q:{name}                    LIST   job queue
    q:{name}:processing:{wid}   LIST   in-flight jobs of one worker
    q:{name}:delayed            ZSET   retry-at timestamp -> job
    q:{name}:dead               LIST   dead letter queue
    events:sessions             CHANNEL Pub/Sub session events

WHY THE CONVENTION MATTERS
    Redis is one flat keyspace. Prefixes are your only "tables". A consistent
    scheme lets you: SCAN by prefix, reason about memory per feature, and set
    per-feature TTL policy. Never use random ad-hoc key names in production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    # ---- Redis ----------------------------------------------------------
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_max_connections: int = _int("REDIS_MAX_CONNECTIONS", 50)

    # ---- Sessions -------------------------------------------------------
    # Absolute lifetime is NOT set here on purpose: this project uses a
    # *sliding* session (TTL refreshed on activity) with a hard cap.
    session_ttl_seconds: int = _int("SESSION_TTL_SECONDS", 30 * 60)      # 30 min idle
    session_absolute_max_seconds: int = _int("SESSION_ABS_MAX", 12 * 3600)  # 12 h hard cap
    session_cookie_name: str = os.getenv("SESSION_COOKIE", "sid")
    max_sessions_per_user: int = _int("MAX_SESSIONS_PER_USER", 5)

    # ---- Rate limiting --------------------------------------------------
    login_limit: int = _int("LOGIN_LIMIT", 5)              # 5 login attempts
    login_window_seconds: int = _int("LOGIN_WINDOW", 60)   # per 60 seconds
    api_bucket_capacity: int = _int("API_BUCKET_CAPACITY", 20)   # burst size
    api_bucket_refill_per_sec: float = float(os.getenv("API_BUCKET_REFILL", "2"))

    # ---- Queue ----------------------------------------------------------
    queue_name: str = os.getenv("QUEUE_NAME", "emails")
    job_max_attempts: int = _int("JOB_MAX_ATTEMPTS", 3)
    job_visibility_timeout: int = _int("JOB_VISIBILITY_TIMEOUT", 60)  # sec


settings = Settings()
