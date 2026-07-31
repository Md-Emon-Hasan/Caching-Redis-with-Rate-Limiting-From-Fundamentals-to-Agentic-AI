"""
PHASE 4.1 — DISTRIBUTED CACHE
-----------------------------
Run:      python 01_distributed_cache.py
Requires: a local Redis server on localhost:6379   (pip install redis)

Concept: once you have more than one app server, Redis stops being
"your" cache and becomes SHARED infrastructure. Every app instance
(App1, App2, App3...) talks to the exact same Redis, so a value
cached by one request is instantly visible to a request served by
a totally different server.
"""
import os
import time
import redis

# --------------------------------------------------------------
# Stand-in for a real database (Postgres/MySQL/Mongo...). We fake
# it with a dict + an artificial delay, just so this file runs
# standalone and you can SEE the cache hit/miss behaviour.
# --------------------------------------------------------------
FAKE_DB = {
    "1": "Wireless Mouse:19.99",
    "2": "Mechanical Keyboard:89.99",
    "3": "USB-C Hub:34.50",
}

def query_product_from_db(product_id: str) -> str:
    time.sleep(0.5)  # simulate a slow DB round trip
    return FAKE_DB.get(product_id, "unknown:0.00")


# --------------------------------------------------------------
# DISTRIBUTED CACHE: the connection POOL is created once per app
# process and reused for every request — never open a fresh TCP
# connection per request, it kills throughput under real traffic.
# --------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

redis_pool = redis.ConnectionPool(
    host=REDIS_HOST,        # could be a single node OR a Cluster endpoint
    port=6379,
    db=0,
    max_connections=50,     # cap so one app instance can't starve the others
    decode_responses=True
)

def get_redis_client():
    # App1, App2, App3 ... every instance calls this, and all of them
    # end up talking to the SAME Redis brain.
    return redis.Redis(connection_pool=redis_pool)

r = get_redis_client()


def get_product(product_id: str):
    cache_key = f"product:{product_id}"
    cached = r.get(cache_key)
    if cached:
        print(f"[CACHE HIT]  product:{product_id} -> {cached}")
        return cached

    print(f"[CACHE MISS] product:{product_id} -> hitting DB...")
    data = query_product_from_db(product_id)
    r.set(cache_key, data, ex=300)   # cache for 5 minutes (TTL)
    return data


if __name__ == "__main__":
    try:
        r.ping()
    except redis.exceptions.ConnectionError:
        print("Could not reach Redis. Make sure a Redis server is running "
              "on localhost:6379 (e.g. `redis-server` in another terminal).")
        raise SystemExit(1)

    r.flushdb()  # clean slate so this demo is repeatable

    print("=== First call (expect MISS, ~0.5s delay) ===")
    get_product("1")

    print("\n=== Second call (expect HIT, instant) ===")
    get_product("1")

    print("\nTry running this script twice from two different terminals — "
          "both processes share the SAME cached value. That's the whole "
          "point of a distributed cache.")
