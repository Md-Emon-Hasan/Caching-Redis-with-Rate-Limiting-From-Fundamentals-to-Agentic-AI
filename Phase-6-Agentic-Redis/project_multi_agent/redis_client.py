"""
============================================================================
 REDIS CLIENT - one shared connection for every agent and component
============================================================================
"""

import redis
import config

r = redis.Redis(
    host=config.REDIS_HOST,
    port=config.REDIS_PORT,
    db=config.REDIS_DB,
    decode_responses=True,
)


def ping() -> bool:
    try:
        return r.ping()
    except redis.exceptions.ConnectionError:
        return False
