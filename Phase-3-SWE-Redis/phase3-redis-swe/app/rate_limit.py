"""
rate_limit.py
=============
RATE LIMITING WITH REDIS  (Phase 3, topic 2)

WHY REDIS AND NOT AN IN-PROCESS COUNTER?
    You run 4 API pods behind a load balancer. An in-memory dict per pod means
    a limit of "100/min" silently becomes 400/min, and it resets on every
    deploy. Rate limiting is *shared* state -> it belongs in Redis: single
    threaded (no races), in-memory (sub-ms), and TTL cleans up for you.

WHY LUA?
    "Read the counter, decide, then write" is a classic race condition: two
    requests read 99 at the same time and both are allowed. Redis executes a
    Lua script atomically - nothing runs in between - so check-and-increment
    becomes one indivisible operation. This is the correct fix, not a lock.

    Keep scripts SHORT. Redis is single threaded: a slow script blocks every
    other client. No loops over unbounded data, no network calls.

THREE ALGORITHMS, THREE TRADE-OFFS

    1) FIXED WINDOW      INCR + EXPIRE
       Cheapest (1 key, ~8 bytes). Flaw: burst at the window edge. With
       "100/min", a client can send 100 at 11:59:59 and 100 at 12:00:00 =
       200 requests in one second. Good enough for coarse abuse protection.

    2) SLIDING WINDOW LOG    ZSET of timestamps
       Exact: counts requests in the last N ms, no edge burst. Cost: stores one
       member per request, so memory = limit x active clients. Great for
       login/OTP endpoints where the limit is small (5/min).

    3) TOKEN BUCKET      HASH {tokens, last_refill}
       Allows a controlled burst (capacity) then settles to a steady rate
       (refill/sec). Constant memory per client. This is what most public APIs
       and LLM gateways use, because bursty clients are normal and you only
       care about average throughput.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis.asyncio import Redis

# ---------------------------------------------------------------------------
# Lua scripts
# ---------------------------------------------------------------------------
# All KEYS are passed as KEYS[...] (never string-concatenated into the script)
# so the script stays cluster-safe: Redis Cluster routes a script by its keys.

# --- 1. FIXED WINDOW -------------------------------------------------------
# KEYS[1] = counter key (already contains the window id)
# ARGV[1] = window length in ms
# returns { count, ttl_ms }
FIXED_WINDOW_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  -- First hit in this window: attach the TTL so the key self-destructs.
  -- Doing INCR and EXPIRE in Lua guarantees we never create an immortal key
  -- (which is what happens if the process dies between the two commands).
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return { count, redis.call('PTTL', KEYS[1]) }
"""

# --- 2. SLIDING WINDOW LOG -------------------------------------------------
# KEYS[1] = zset key
# ARGV[1] = now_ms, ARGV[2] = window_ms, ARGV[3] = limit, ARGV[4] = unique member
# returns { allowed(0|1), remaining, retry_after_ms }
SLIDING_WINDOW_LUA = """
local now      = tonumber(ARGV[1])
local window   = tonumber(ARGV[2])
local limit    = tonumber(ARGV[3])
local member   = ARGV[4]

-- Step 1: forget everything older than the window (this is the "sliding" part).
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)

local used = redis.call('ZCARD', KEYS[1])
if used < limit then
  -- Step 2: record this request. Member must be unique or ZADD would just
  -- update the score of an existing member and under-count.
  redis.call('ZADD', KEYS[1], now, member)
  redis.call('PEXPIRE', KEYS[1], window)
  return { 1, limit - used - 1, 0 }
end

-- Denied: the caller may retry when the OLDEST request leaves the window.
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local retry  = (tonumber(oldest[2]) + window) - now
if retry < 0 then retry = 0 end
return { 0, 0, retry }
"""

# --- 3. TOKEN BUCKET ------------------------------------------------------
# KEYS[1] = hash key
# ARGV[1] = refill tokens per second
# ARGV[2] = capacity (max burst)
# ARGV[3] = now_ms
# ARGV[4] = cost of this request (usually 1; use N for expensive endpoints)
# returns { allowed(0|1), tokens_left_x1000, retry_after_ms }
TOKEN_BUCKET_LUA = """
local rate     = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now      = tonumber(ARGV[3])
local cost     = tonumber(ARGV[4])

local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts     = tonumber(state[2])

if tokens == nil then
  -- New client: start with a full bucket so first-time users are not punished.
  tokens = capacity
  ts = now
end

-- Lazy refill: instead of a background job topping up every bucket, we compute
-- how many tokens *would* have been added since the last request. O(1), and
-- idle clients cost nothing.
local elapsed = math.max(0, now - ts) / 1000.0
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed = 0
local retry = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry = math.ceil(((cost - tokens) / rate) * 1000)
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
-- TTL = time for an empty bucket to refill completely (+1s slack). After that
-- the state is equivalent to "new client", so keeping it wastes memory.
redis.call('PEXPIRE', KEYS[1], math.ceil((capacity / rate) * 1000) + 1000)

return { allowed, math.floor(tokens * 1000), retry }
"""


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: float
    retry_after_ms: int
    limit: int

    @property
    def retry_after_seconds(self) -> int:
        """Value for the HTTP `Retry-After` header (always >= 1 when denied)."""
        return max(1, -(-self.retry_after_ms // 1000))  # ceil division


class RateLimiter:
    """
    Wraps the three algorithms.

    IMPORTANT: scripts are registered with `register_script`, which uses
    EVALSHA under the hood - the script body travels over the wire once, then
    only its SHA1 is sent. redis-py automatically falls back to EVAL if Redis
    was restarted and lost its script cache.
    """

    def __init__(self, redis: Redis) -> None:
        self.r = redis
        self._fixed = redis.register_script(FIXED_WINDOW_LUA)
        self._sliding = redis.register_script(SLIDING_WINDOW_LUA)
        self._bucket = redis.register_script(TOKEN_BUCKET_LUA)

    # ------------------------------------------------------------ fixed window
    async def fixed_window(self, scope: str, limit: int, window_seconds: int) -> RateLimitResult:
        # The window id is part of the key, so a new window = a brand new key.
        window_id = int(time.time()) // window_seconds
        key = f"rl:fixed:{scope}:{window_id}"
        count, ttl_ms = await self._fixed(keys=[key], args=[window_seconds * 1000])
        return RateLimitResult(
            allowed=count <= limit,
            remaining=max(0, limit - count),
            retry_after_ms=ttl_ms if count > limit else 0,
            limit=limit,
        )

    # ---------------------------------------------------------- sliding window
    async def sliding_window(self, scope: str, limit: int, window_seconds: int) -> RateLimitResult:
        now_ms = int(time.time() * 1000)
        # Unique member: timestamp alone collides under concurrency.
        member = f"{now_ms}-{id(object())}"
        allowed, remaining, retry = await self._sliding(
            keys=[f"rl:slide:{scope}"],
            args=[now_ms, window_seconds * 1000, limit, member],
        )
        return RateLimitResult(bool(allowed), float(remaining), int(retry), limit)

    # ------------------------------------------------------------ token bucket
    async def token_bucket(
        self, scope: str, capacity: int, refill_per_sec: float, cost: int = 1
    ) -> RateLimitResult:
        now_ms = int(time.time() * 1000)
        allowed, tokens_x1000, retry = await self._bucket(
            keys=[f"rl:bucket:{scope}"],
            args=[refill_per_sec, capacity, now_ms, cost],
        )
        return RateLimitResult(bool(allowed), tokens_x1000 / 1000.0, int(retry), capacity)


# ---------------------------------------------------------------------------
# NOTE ON CLOCKS
#   We pass `now` from the application, not Redis' TIME command, because that
#   keeps the script deterministic and lets tests inject a fake clock. The cost
#   is that badly skewed app servers distort the limit - in production run NTP,
#   or read TIME once inside the script (Redis 5+ effect replication allows it).
# ---------------------------------------------------------------------------
