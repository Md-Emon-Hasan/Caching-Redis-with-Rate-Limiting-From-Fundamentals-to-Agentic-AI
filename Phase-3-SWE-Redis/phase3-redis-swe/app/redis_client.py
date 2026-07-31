"""
redis_client.py
===============
ONE place that owns the Redis connection for the whole application.

WHY A SINGLE SHARED CLIENT?
    Opening a new TCP connection per request is expensive (~1 RTT for the
    handshake + auth). redis-py ships with a *connection pool*: the client
    object is created once, and every command borrows a free connection from
    the pool and returns it immediately after. So:

        1 client object  ->  N pooled connections  ->  many concurrent requests

    Rule of thumb: create the client at application startup, close it at
    shutdown, never inside a request handler.

BLOCKING COMMANDS WARNING
    Commands like BLPOP / BLMOVE hold a connection for their whole timeout.
    A worker that blocks for 5s occupies one pooled connection for 5s. That is
    why the worker process in app/queue/worker.py builds its OWN client instead
    of sharing the web app's pool.
"""

from __future__ import annotations

import redis.asyncio as redis

from app.config import settings

# Module-level singleton. `None` until create_redis() is called on startup.
_client: redis.Redis | None = None


def create_redis() -> redis.Redis:
    """Build the shared async Redis client (called once, from FastAPI lifespan)."""
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.redis_url,
            # decode_responses=True makes redis-py return `str` instead of `bytes`.
            # Convenient for JSON/text payloads. Turn it OFF if you store binary
            # blobs (e.g. pickled ML features, protobuf, embeddings).
            decode_responses=True,
            # Cap the pool so a traffic spike cannot exhaust Redis' `maxclients`.
            max_connections=settings.redis_max_connections,
            # Fail fast instead of hanging a request forever if Redis is sick.
            socket_connect_timeout=2,
            socket_timeout=2,
            # Detect dead TCP connections behind load balancers / NAT.
            health_check_interval=30,
            retry_on_timeout=True,
        )
    return _client


def get_client() -> redis.Redis:
    """Return the already-created client (raises if startup did not run)."""
    if _client is None:  # pragma: no cover - programming error guard
        raise RuntimeError("Redis client not initialised. Did the app start up?")
    return _client


async def close_redis() -> None:
    """Close the pool on shutdown so Redis does not keep half-open sockets."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def new_client(**overrides) -> redis.Redis:
    """
    Build a SEPARATE client + pool.

    Use this for anything that holds a connection for a long time:
      * blocking queue consumers (BLMOVE / BLPOP)
      * Pub/Sub subscribers (a subscribed connection can only run
        SUBSCRIBE/UNSUBSCRIBE/PING, so it must not be shared)
    """
    kwargs = dict(
        decode_responses=True,
        socket_connect_timeout=2,
        health_check_interval=30,
    )
    kwargs.update(overrides)
    return redis.from_url(settings.redis_url, **kwargs)
