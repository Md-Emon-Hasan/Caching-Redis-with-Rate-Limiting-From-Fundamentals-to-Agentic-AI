"""
PHASE 4.3 — CACHE STAMPEDE
--------------------------
Run:      python 03_cache_stampede.py
Requires: a local Redis server on localhost:6379   (pip install redis)

The problem: a hot key expires while traffic is high -> thousands of
concurrent requests miss the cache AT THE SAME INSTANT -> all of them
hit the DB together -> the DB falls over.

This script proves the fix by firing 20 concurrent "requests" at an
expired key and counting how many times the (fake) DB actually gets hit.
"""
import os
import time
import uuid
import random
import math
import threading
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

db_hit_counter = {"count": 0}
db_lock = threading.Lock()

def query_product_from_db(product_id: str) -> str:
    with db_lock:
        db_hit_counter["count"] += 1
    time.sleep(0.3)  # simulate an expensive DB query
    return f"product-{product_id}-data"


# ================================================================
# SOLUTION 1 — Distributed lock (mutex)
# Only ONE request is allowed to rebuild the cache; everyone else waits.
# ================================================================
def get_with_lock(product_id: str):
    cache_key = f"product:{product_id}"
    lock_key = f"lock:{cache_key}"

    cached = r.get(cache_key)
    if cached:
        return cached

    lock_id = str(uuid.uuid4())
    # NX = only set if the lock doesn't already exist, PX = auto-expire in ms
    got_lock = r.set(lock_key, lock_id, nx=True, px=5000)

    if got_lock:
        try:
            data = query_product_from_db(product_id)   # only WE do this
            r.set(cache_key, data, ex=300)
            return data
        finally:
            r.delete(lock_key)   # release the lock when done
    else:
        time.sleep(0.05)                    # someone else is already rebuilding
        return get_with_lock(product_id)     # brief retry


# ================================================================
# SOLUTION 2 — Probabilistic early expiration (the "xfetch" idea)
# Refresh slightly BEFORE hard expiry, only for a small % of requests,
# so the rebuild happens smoothly instead of all at once.
# ================================================================
def get_with_early_refresh(product_id: str, original_ttl: int = 300):
    cache_key = f"product:{product_id}"
    cached = r.get(cache_key)
    ttl = r.ttl(cache_key)      # seconds remaining before expiry
    beta = 1.0                  # tuning knob: higher = refresh earlier

    if cached and ttl > 0:
        should_refresh_early = (original_ttl * beta * math.log(random.random())) < -ttl
        if not should_refresh_early:
            return cached
        # else: fall through and refresh now, slightly early, on purpose

    data = query_product_from_db(product_id)
    r.set(cache_key, data, ex=original_ttl)
    return data


def simulate_stampede(target_fn, label, concurrent_requests=20):
    db_hit_counter["count"] = 0
    r.flushdb()  # start with an empty (i.e. "just expired") cache

    threads = [threading.Thread(target=target_fn, args=("42",)) for _ in range(concurrent_requests)]
    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start

    print(f"[{label}] {concurrent_requests} concurrent requests -> "
          f"DB was hit {db_hit_counter['count']} time(s) in {elapsed:.2f}s")


if __name__ == "__main__":
    print("=== WITHOUT protection (naive cache-aside) ===")
    def naive_get(product_id):
        cache_key = f"product:{product_id}"
        cached = r.get(cache_key)
        if cached:
            return cached
        data = query_product_from_db(product_id)   # every miss hits the DB
        r.set(cache_key, data, ex=300)
        return data
    simulate_stampede(naive_get, "NAIVE")

    print("\n=== WITH distributed lock ===")
    simulate_stampede(get_with_lock, "LOCK-PROTECTED")

    print("\nNotice: the naive version hits the DB many times under 20 "
          "concurrent requests, while the lock-protected version hits it "
          "only ONCE — that's the entire point of stampede protection.")
