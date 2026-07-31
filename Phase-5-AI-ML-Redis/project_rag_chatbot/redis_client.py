"""
============================================================================
 REDIS CLIENT - one shared connection for the whole app
============================================================================
We create ONE Redis client and import it everywhere. Creating a new
connection per request is wasteful; the redis-py client is thread-safe and
uses a connection pool under the hood, so sharing one instance is the norm.
============================================================================
"""

import redis

import config


# A single, shared, app-wide Redis client.
# decode_responses=True -> we get Python str back instead of raw bytes.
r = redis.Redis(
    host=config.REDIS_HOST,
    port=config.REDIS_PORT,
    db=config.REDIS_DB,
    decode_responses=True,
)


def ping() -> bool:
    """Return True if Redis is reachable. Used by the /health endpoint."""
    try:
        return r.ping()
    except redis.exceptions.ConnectionError:
        return False
