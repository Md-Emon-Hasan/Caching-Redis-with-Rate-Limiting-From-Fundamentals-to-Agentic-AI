# Phase 4 — System Design with Redis

Everything from Phase 4 of the *Redis for AI Engineers* roadmap, in one package:
runnable concept scripts, a full capstone project, and the handbook PDF.

## What's inside

```
Phase4_Redis_System_Design/
├── README.md                      <- you are here
├── concepts/                      <- one script per Phase 4 topic, all runnable
│   ├── 01_distributed_cache.py
│   ├── 02_cache_invalidation.py
│   ├── 03_cache_stampede.py
│   ├── 04_cache_warming.py
│   ├── 05_redis_replication/      <- master/replica configs + client
│   ├── 06_redis_sentinel/         <- sentinel config + client
│   └── 07_redis_cluster/          <- cluster client + setup notes
├── project-high-traffic-api/      <- Project 3, full working app
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── init.sql
│   ├── main.py
│   └── requirements.txt
└── handbook/
    └── Phase4_System_Design_Redis_Handbook.pdf
```

## Quick reference — what each concept solves

| # | Concept | Problem it solves | Core mechanism |
|---|---------|-------------------|-----------------|
| 1 | Distributed Cache | Many app servers need one consistent cache | Shared Redis + connection pooling |
| 2 | Cache Invalidation | Stale data outliving a DB change | Explicit delete / versioned keys / pub-sub |
| 3 | Cache Stampede | Many requests miss a hot key at once | Distributed lock / probabilistic early refresh |
| 4 | Cache Warming | Empty cache at deploy time or before a spike | Pipelined preload on startup |
| 5 | Replication | Scaling reads, redundancy | One master, N replicas, async copy |
| 6 | Sentinel | Automatic failover on master death | Quorum-based monitoring + auto-promotion |
| 7 | Cluster | Scaling writes, huge datasets | 16,384 hash slots sharded across masters |

Read the PDF in `handbook/` for the full explanation of each one — diagrams,
common mistakes, and interview tips included.

---

## Part A — Running the concept scripts (01–04)

These four are fully self-contained: they simulate the database in-memory,
so you only need Redis itself.

```bash
# 1. Make sure Redis is installed and running locally
redis-server            # in its own terminal, leave it running

# 2. Install the Python client
pip install redis

# 3. Run any concept script
cd concepts
python 01_distributed_cache.py
python 02_cache_invalidation.py
python 03_cache_stampede.py
python 04_cache_warming.py
```

Each script prints exactly what's happening (`CACHE HIT`, `CACHE MISS`,
how many times the fake DB got hit, etc.) so you can watch the concept
work in real time.

## Part B — Replication / Sentinel / Cluster (05–07)

These need more than one Redis node running, so they're set up as
reference labs rather than one-command scripts. Each folder's `.py` file
has the exact setup steps in its own docstring at the top — open the
file and follow them in order:

- `concepts/05_redis_replication/` — start a master + a replica, then run `replication_client.py`
- `concepts/06_redis_sentinel/` — needs the replication pair above, plus `redis-sentinel sentinel.conf`
- `concepts/07_redis_cluster/` — needs 6 cluster-enabled nodes (steps in the docstring)

Don't worry about running these perfectly on the first try — the goal is
to see the *shape* of each setup (config files + client code), not to
run a production cluster on your laptop.

## Part C — Running Project 3 (the capstone)

This is a full stack: NGINX load balancer → 2 FastAPI instances → Redis → Postgres.

```bash
cd project-high-traffic-api
docker compose up --build
```

Once it's up, test it from a new terminal:

```bash
# First call -> should say "source": "db"  (cache was empty for this key... 
# unless it was warmed on startup — try product_id 6+ to force a real miss)
curl http://localhost/products/1

# Second call -> should say "source": "cache"
curl http://localhost/products/1

# Update the price
curl -X PUT "http://localhost/products/1?price=15.00"

# Call again -> back to "source": "db", proving invalidation worked
curl http://localhost/products/1
```

Call `curl http://localhost/` a few times in a row — the `"instance"`
field in the response will flip between `api1` and `api2`, proving
NGINX is actually load-balancing between them, and that both instances
share the exact same Redis cache.

### Stopping / resetting

```bash
docker compose down -v   # -v also wipes the Postgres + Redis data volumes
```

---

## Next

Phase 5 (AI/ML Redis) builds directly on everything here — LLM response
caching, embedding caches, and RAG retrieval caching all reuse the exact
patterns from this phase.
