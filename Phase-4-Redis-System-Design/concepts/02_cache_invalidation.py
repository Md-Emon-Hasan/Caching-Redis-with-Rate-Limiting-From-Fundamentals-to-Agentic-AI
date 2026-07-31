"""
PHASE 4.2 — CACHE INVALIDATION
------------------------------
Run:      python 02_cache_invalidation.py
Requires: a local Redis server on localhost:6379   (pip install redis)

"There are only two hard things in Computer Science: cache
invalidation and naming things." Three strategies below:
  1. Explicit invalidation (delete on write)
  2. Versioned keys (bump a counter to invalidate a whole group)
  3. Event-driven invalidation (pub/sub — for multi-service setups)
"""
import os
import time
import threading
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

FAKE_DB = {"1": {"price": 19.99}}
FAKE_CATALOG_DB = {"electronics": "Mouse, Keyboard, Hub"}


# ================================================================
# STRATEGY 1 — Explicit (active) invalidation
# The moment the DB changes, immediately delete the stale cache key.
# ================================================================
def update_product_in_db(product_id: str, new_price: float):
    FAKE_DB[product_id]["price"] = new_price

def update_product_price(product_id: str, new_price: float):
    update_product_in_db(product_id, new_price)   # 1. update source of truth
    r.delete(f"product:{product_id}")             # 2. drop the stale copy
    # next read is a guaranteed MISS -> refetches the fresh price


# ================================================================
# STRATEGY 2 — Versioned keys
# Instead of deleting many related keys one by one, bump a version
# number. Old keys become orphaned and simply expire via TTL.
# ================================================================
def query_catalog_from_db(category: str) -> str:
    return FAKE_CATALOG_DB.get(category, "")

def get_catalog(category: str):
    r.setnx("catalog:version", "1")   # make sure a version counter exists
    version = r.get("catalog:version")
    cache_key = f"catalog:{category}:v{version}"   # version baked into the key
    cached = r.get(cache_key)
    if cached:
        print(f"[CACHE HIT]  {cache_key}")
        return cached
    print(f"[CACHE MISS] {cache_key}")
    data = query_catalog_from_db(category)
    r.set(cache_key, data, ex=3600)
    return data

def invalidate_entire_catalog():
    r.incr("catalog:version")   # one INCR invalidates every catalog:* key at once
    print("Catalog version bumped -> all old catalog:* keys are now orphaned")


# ================================================================
# STRATEGY 3 — Event-driven invalidation (Pub/Sub)
# Useful when MULTIPLE services share one cache and need to be told
# "this key changed" in real time, without polling.
# ================================================================
def publish_invalidation_event(key: str):
    r.publish("cache-invalidation-channel", key)

def cache_invalidation_listener(stop_after: int = 1):
    pubsub = r.pubsub()
    pubsub.subscribe("cache-invalidation-channel")
    received = 0
    for message in pubsub.listen():
        if message["type"] == "message":
            stale_key = message["data"]
            r.delete(stale_key)
            print(f"[LISTENER] invalidated stale key from another service: {stale_key}")
            received += 1
            if received >= stop_after:
                break


if __name__ == "__main__":
    r.flushdb()

    print("=== Strategy 1: Explicit invalidation ===")
    r.set("product:1", "cached-old-price:19.99")
    print("Before update:", r.get("product:1"))
    update_product_price("1", 24.99)
    print("After update (should be None -> cache miss forced):", r.get("product:1"))

    print("\n=== Strategy 2: Versioned keys ===")
    get_catalog("electronics")   # MISS, then cached
    get_catalog("electronics")   # HIT
    invalidate_entire_catalog()
    get_catalog("electronics")   # MISS again, new version key

    print("\n=== Strategy 3: Event-driven invalidation (Pub/Sub) ===")
    r.set("session:42", "logged-in")
    listener_thread = threading.Thread(target=cache_invalidation_listener, args=(1,))
    listener_thread.start()
    time.sleep(0.3)  # give the subscriber a moment to connect
    publish_invalidation_event("session:42")
    listener_thread.join(timeout=2)
    print("session:42 after event:", r.get("session:42"))
