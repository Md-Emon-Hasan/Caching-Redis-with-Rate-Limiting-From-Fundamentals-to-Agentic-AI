# Caching, Redis & Rate Limiting — From Fundamentals to Agentic AI

A project-based learning path covering **caching concepts, Redis, and rate limiting** — from basic cache theory to agent memory and production deployment, completed across **7 phases**.

<p align="left">
  <img src="https://img.shields.io/badge/Redis-7.x-DC382D?logo=redis&logoColor=white" alt="Redis" />
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/LangGraph-Agentic-1C3C3C" alt="LangGraph" />
  <img src="https://img.shields.io/badge/Phases-7%2F7%20Complete-brightgreen" alt="Progress" />
  <img src="https://img.shields.io/badge/License-MIT-blue" alt="License" />
</p>

---

## About

Most people learn Redis as a list of commands (`SET`, `GET`, `DEL`) and stop there. This repository takes the opposite approach: **70% of the focus is on concepts** — caching strategy, invalidation, rate limiting algorithms, distributed behavior — and **30% on commands**. Commands are searchable; architecture is not.

**Three tracks covered:**

| Track | What it covers |
| --- | --- |
| **Caching** | Cache hit/miss, TTL, eviction policies, cache-aside / write-through / write-back, invalidation, stampede protection |
| **Redis** | Data structures, atomic operations, Pub/Sub, Streams, replication, Sentinel, Cluster, persistence |
| **Rate Limiting** | Fixed window, sliding window log, token bucket, Lua-based atomic limiters, per-user and per-API-key quotas |

---

## Roadmap

```text
Caching Concepts → Redis Fundamentals → SWE Use Cases → System Design
        → AI/ML Use Cases → Agentic AI → Production Deployment
```

| Phase | Topic | Duration | Project |
| --- | --- | --- | --- |
| 1 | Caching Fundamentals | 1 week | Caching lab (notebooks) |
| 2 | Redis Fundamentals | 1 week | Simple Cache Server |
| 3 | SWE Use Cases | 2 weeks | Authentication + Rate Limiting Service |
| 4 | System Design | 2 weeks | High-Traffic API |
| 5 | AI/ML Use Cases | 2 weeks | RAG Chatbot with caching |
| 6 | Agentic AI | 2 weeks | LangGraph Multi-Agent System |
| 7 | Production | Advanced | Cluster, HA, monitoring, DR |
| — | **Capstone** | — | **AI Research Assistant** |

---

## Phase Breakdown

### Phase 1 — Caching Fundamentals
Cache hit/miss, TTL, expiration vs eviction, LRU / LFU / FIFO, and the four write patterns (cache-aside, write-through, write-back, write-around). Built from scratch in plain Python so nothing hides behind a client library.

**Takeaway:** a cache is a deliberate trade of consistency for latency.

### Phase 2 — Redis Fundamentals
Strings, Hashes, Lists, Sets, Sorted Sets — and when each is the right choice. Core commands (`SET`, `GET`, `EXPIRE`, `TTL`, `INCR`, `LPUSH`, `HSET`, `ZADD`), key naming conventions, atomicity, pipelining, and why `KEYS` is banned in production.

**Project 1 — Simple Cache Server:** FastAPI → Redis → simulated database, with a `/metrics` endpoint reporting hit rate and latency.

### Phase 3 — SWE Use Cases
- **Session management** — Redis-backed sessions with TTL, enabling stateless app servers
- **Rate limiting** — fixed window (`INCR` + `EXPIRE`), sliding window log (Sorted Set), and token bucket (Hash + Lua); atomicity is the whole problem
- **Message queues** — `LPUSH`/`BRPOP`, reliable queues with `LMOVE`, Streams with consumer groups
- **Pub/Sub** — fan-out for notifications and cache invalidation, plus its no-persistence limitation

**Project 2 — Authentication Service:** login, session store, refresh-token rotation, token denylist, and brute-force rate limiting on login.

### Phase 4 — System Design
Distributed caching and hash slots, **cache invalidation** strategies (TTL, write-through, event-driven, versioned keys), **cache stampede** and its mitigations (distributed locks with `SET NX PX`, TTL jitter, early recomputation, stale-while-revalidate), cache warming, replication, Sentinel failover, and Redis Cluster.

**Project 3 — High-Traffic API:** NGINX → FastAPI → Redis → Postgres, load-tested to compare no cache vs naive cache vs stampede-protected cache.

### Phase 5 — AI/ML Use Cases
- **LLM response cache** — deterministic keys from prompt + model + params
- **Semantic cache** — vector similarity so paraphrased questions hit the cache
- **Embedding cache** — never recompute a deterministic vector
- **RAG cache** — layered caching for retrieval, context, and response
- **Feature store cache** — Redis as the online serving layer

**Project 4 — RAG Chatbot:** three cache layers with measured hit rate, latency, and cost savings.

### Phase 6 — Agentic AI
Agent short-term / working / long-term memory, LangGraph state stored in Redis (making agents restartable and scalable), checkpointing for resumable runs, and shared memory for multi-agent coordination.

**Project 5 — LangGraph Multi-Agent System:** Planner, Researcher, Retriever, Tool Router, Executor, Reviewer — with Redis handling conversation state, checkpoints, shared memory, and Pub/Sub coordination.

### Phase 7 — Production
Redis Cluster and Sentinel deployment, monitoring the metrics that matter (hit rate, `used_memory`, `evicted_keys`, `SLOWLOG`, replication lag), Prometheus + Grafana observability, scaling and memory optimization, persistence (RDB vs AOF vs both), high availability, and disaster recovery runbooks.

---

## Capstone — AI Research Assistant

```text
User → NGINX → FastAPI → Redis → LangGraph → Vector DB → Postgres → LLM
```

**Redis usage:** LLM cache · embedding cache · semantic cache · session store · rate limiter · agent memory · checkpointing · Pub/Sub · task queue · distributed locks

---

## Quick Start

**Requirements:** Python 3.10+, Docker, Redis 7.x (Redis Stack for Phase 5), PostgreSQL 14+, an LLM API key from Phase 5 onward.

```bash
git clone https://github.com/Md-Emon-Hasan/Caching-Redis-with-Rate-Limiting-From-Fundamentals-to-Agentic-AI.git
cd Caching-Redis-with-Rate-Limiting-From-Fundamentals-to-Agentic-AI

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Redis Stack includes vector search + RedisInsight GUI on :8001
docker run -d --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest
redis-cli ping                   # PONG

cp .env.example .env             # add REDIS_URL, POSTGRES_URL, API keys
```

Each phase folder has its own `README.md` with run instructions. Start at Phase 1 and move forward.

---

## Resources

1. [Redis University](https://university.redis.io) — free structured courses
2. [Redis Documentation](https://redis.io/docs/latest/)
3. [System Design Primer](https://github.com/donnemartin/system-design-primer)
4. [FastAPI Documentation](https://fastapi.tiangolo.com/)
5. [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)

---

## Contributing

Fork → branch → commit → pull request. For larger architectural suggestions, please open an issue first.

## License

MIT — see [`LICENSE`](LICENSE).

---

## **Developed By**

**Md Emon Hasan**
**Email:** emon.mlengineer@gmail.com
**WhatsApp:** [+8801834363533](https://wa.me/8801834363533)
**Portfolio:** [Md-Emon-Hasan](https://emonlabs-ai.hitechparks.com/)
**GitHub:** [Md-Emon-Hasan](https://github.com/Md-Emon-Hasan)
**LinkedIn:** [Md Emon Hasan](https://www.linkedin.com/in/md-emon-hasan-695483237/)
**Facebook:** [Md Emon Hasan](https://www.facebook.com/mdemon.hasan2001/)

---