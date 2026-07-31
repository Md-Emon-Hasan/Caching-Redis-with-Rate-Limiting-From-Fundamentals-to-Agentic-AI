"""
PHASE 4.4 — CACHE WARMING
-------------------------
Run:      python 04_cache_warming.py
Requires: a local Redis server on localhost:6379   (pip install redis)

A freshly deployed service starts with an EMPTY cache. If real
traffic hits it immediately, the first wave of users causes a cache
stampede (see 03_cache_stampede.py). Cache warming avoids this by
populating the important keys BEFORE traffic arrives.
"""
import os
import time
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

FAKE_TOP_PRODUCTS = [
    {"id": 1, "data": "Wireless Mouse:19.99"},
    {"id": 2, "data": "Mechanical Keyboard:89.99"},
    {"id": 3, "data": "USB-C Hub:34.50"},
    {"id": 4, "data": "Laptop Stand:45.00"},
    {"id": 5, "data": "Webcam 1080p:59.99"},
]

def get_top_products_from_db():
    # In a real system: SELECT ... ORDER BY views DESC LIMIT 100
    return FAKE_TOP_PRODUCTS


def warm_cache_on_startup():
    top_products = get_top_products_from_db()
    pipeline = r.pipeline()   # batch every SET into ONE network round-trip

    for product in top_products:
        cache_key = f"product:{product['id']}"
        pipeline.set(cache_key, product["data"], ex=3600)

    pipeline.execute()
    print(f"Warmed {len(top_products)} products into cache")

    # Typically wired into a startup hook, e.g. in FastAPI:
    # @app.on_event("startup")
    # async def startup_event():
    #     warm_cache_on_startup()


if __name__ == "__main__":
    r.flushdb()

    print("=== Before warming ===")
    print("product:1 in cache?", r.get("product:1"))

    start = time.time()
    warm_cache_on_startup()
    elapsed = time.time() - start

    print(f"\n=== After warming ({elapsed*1000:.1f}ms for {len(FAKE_TOP_PRODUCTS)} keys, pipelined) ===")
    print("product:1 in cache?", r.get("product:1"))
    print("\nEvery one of these is now a CACHE HIT the moment real traffic arrives.")
