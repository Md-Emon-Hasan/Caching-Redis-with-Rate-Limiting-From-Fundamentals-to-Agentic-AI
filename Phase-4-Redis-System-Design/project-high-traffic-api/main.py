"""
PROJECT 3 — HIGH TRAFFIC API (Phase 4 Capstone)
------------------------------------------------
Client -> NGINX Load Balancer -> FastAPI #1 / #2 -> Redis -> Postgres

Every concept from Phase 4 is labeled inline below:
  - Distributed Cache  (4.1) : one Redis pool, shared by every app instance
  - Cache Invalidation (4.2) : delete on write (PUT /products/{id})
  - Cache Stampede     (4.3) : distributed lock around the DB fetch
  - Cache Warming      (4.4) : preload popular products on startup
"""
import asyncio
import os
import time
import redis
import asyncpg
from fastapi import FastAPI

app = FastAPI(title="High Traffic Product API")

# ------------------------------------------------------------------
# DISTRIBUTED CACHE (4.1): one connection pool per app instance
# (api1, api2, ...). All instances point at the SAME Redis, so a
# value cached by api1 is instantly visible to api2.
# ------------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
redis_pool = redis.ConnectionPool(host=REDIS_HOST, port=6379, decode_responses=True, max_connections=50)
r = redis.Redis(connection_pool=redis_pool)

db_pool = None
CACHE_TTL = 60  # seconds


async def wait_for_redis(max_attempts: int = 30, delay_seconds: float = 1.0):
    for attempt in range(1, max_attempts + 1):
        try:
            r.ping()
            return
        except redis.exceptions.ConnectionError:
            if attempt == max_attempts:
                raise
            print(f"[startup] waiting for redis ({attempt}/{max_attempts})...")
            await asyncio.sleep(delay_seconds)


async def create_db_pool(max_attempts: int = 30, delay_seconds: float = 1.0):
    for attempt in range(1, max_attempts + 1):
        try:
            return await asyncpg.create_pool(
                user=os.getenv("POSTGRES_USER", "app"),
                password=os.getenv("POSTGRES_PASSWORD", "app"),
                database=os.getenv("POSTGRES_DB", "appdb"),
                host=os.getenv("POSTGRES_HOST", "postgres"),
            )
        except Exception:
            if attempt == max_attempts:
                raise
            print(f"[startup] waiting for postgres ({attempt}/{max_attempts})...")
            await asyncio.sleep(delay_seconds)


async def get_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = await create_db_pool()
    return db_pool


async def bootstrap_services():
    global db_pool
    try:
        db_pool = await create_db_pool()
        await wait_for_redis()
        await warm_cache()
    except Exception as exc:
        print(f"[startup] bootstrap skipped or incomplete: {exc}")


@app.on_event("startup")
async def startup():
    asyncio.create_task(bootstrap_services())


async def warm_cache():
    """Preload the most popular products so the FIRST real requests
    are already cache hits instead of cache misses."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, price FROM products ORDER BY views DESC LIMIT 50"
        )
    pipeline = r.pipeline()   # batch every SET into one network round-trip
    for row in rows:
        pipeline.set(f"product:{row['id']}", f"{row['name']}:{row['price']}", ex=CACHE_TTL)
    pipeline.execute()
    print(f"[startup] warmed {len(rows)} products into cache")


@app.get("/")
async def root():
    return {"status": "ok", "instance": os.getenv("INSTANCE_NAME", "unknown")}


@app.get("/products/{product_id}")
async def get_product(product_id: int):
    cache_key = f"product:{product_id}"

    # 1. Cache-Aside: try the cache first
    cached = r.get(cache_key)
    if cached:
        return {"source": "cache", "instance": os.getenv("INSTANCE_NAME"), "data": cached}

    # 2. CACHE STAMPEDE protection (4.3): only ONE request rebuilds a hot key
    lock_key = f"lock:{cache_key}"
    got_lock = r.set(lock_key, "1", nx=True, px=3000)

    if not got_lock:
        time.sleep(0.05)
        return await get_product(product_id)   # someone else is rebuilding — retry

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name, price FROM products WHERE id = $1", product_id
            )
        if not row:
            return {"error": "not found"}

        data = f"{row['name']}:{row['price']}"
        r.set(cache_key, data, ex=CACHE_TTL)   # 3. populate cache for next request
        return {"source": "db", "instance": os.getenv("INSTANCE_NAME"), "data": data}
    finally:
        r.delete(lock_key)


@app.put("/products/{product_id}")
async def update_product(product_id: int, price: float):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE products SET price = $1 WHERE id = $2", price, product_id
        )
    if result == "UPDATE 0":
        return {"error": "not found"}

    # CACHE INVALIDATION (4.2): DB is the source of truth, so the moment
    # it changes, immediately drop the now-stale cache entry.
    r.delete(f"product:{product_id}")
    return {"status": "updated", "product_id": product_id, "new_price": price}
