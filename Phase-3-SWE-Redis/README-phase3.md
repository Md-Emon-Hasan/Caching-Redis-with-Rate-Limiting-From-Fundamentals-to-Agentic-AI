# Phase 3 — SWE Redis (end to end)

Session Management · Rate Limiting · Message Queue · Pub/Sub
→ all wired into **Project 2: Authentication Service**.

Every file is commented in English, written to be read top-to-bottom.

---

## 1. Run it

```bash
# Redis
docker compose up -d          # or: redis-server --appendonly yes

# Python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# API
uvicorn app.main:app --reload            # http://localhost:8000/docs

# Background worker (separate terminal)
python -m app.queue.worker

# Pub/Sub subscriber (separate terminal)
python -m app.pubsub.events
```

Then, to see every concept fire at once:

```bash
python -m scripts.smoke_test     # narrated end-to-end walkthrough
bash scripts/demo.sh             # the same thing with curl
python -m app.queue.streams_demo # bonus: the Streams version of the queue
```

---

## 2. Read the code in this order

| # | File | What it teaches |
|---|------|-----------------|
| 1 | `app/config.py` | Key-naming convention — the "schema" of your Redis |
| 2 | `app/redis_client.py` | Connection pooling, why blocking clients are separate |
| 3 | `app/sessions.py` | HASH + ZSET session store, sliding TTL, device limit, revocation |
| 4 | `app/rate_limit.py` | Fixed window vs sliding window vs token bucket, in atomic Lua |
| 5 | `app/queue/producer.py` | Why you queue slow work; job envelope design |
| 6 | `app/queue/worker.py` | Reliable queue (BLMOVE + ACK), retries, DLQ, crash recovery |
| 7 | `app/pubsub/events.py` | Fire-and-forget fan-out and its exact failure mode |
| 8 | `app/deps.py` | Auth + rate limit as reusable FastAPI dependencies |
| 9 | `app/main.py` | Project 2: the full auth service |
| 10 | `app/queue/streams_demo.py` | Streams: consumer groups, XACK, XAUTOCLAIM |

---

## 3. Redis keyspace used

```text
sess:{sid}                    HASH   session fields          TTL 30m (sliding)
user:sessions:{user_id}       ZSET   sid -> expiry           TTL 12h
user:{user_id}                HASH   fake DB row             no TTL
user:byemail:{email}          STRING email -> user_id        no TTL
pwreset:{token}               STRING one-time token          TTL 15m
rl:fixed:{scope}:{window}     STRING fixed-window counter    TTL = window
rl:slide:{scope}              ZSET   request timestamps      TTL = window
rl:bucket:{scope}             HASH   tokens + last refill    TTL = refill time
q:emails                      LIST   pending jobs            no TTL
q:emails:processing:{worker}  LIST   in-flight jobs          no TTL
q:emails:delayed              ZSET   run_at -> job           no TTL
q:emails:dead                 LIST   dead letter queue       no TTL
events:sessions               CHANNEL pub/sub events         n/a
```

Inspect it live:

```bash
redis-cli --scan --pattern 'sess:*'
redis-cli hgetall sess:<sid>
redis-cli ttl sess:<sid>
redis-cli zrange user:sessions:<user_id> 0 -1 WITHSCORES
redis-cli llen q:emails
redis-cli monitor          # watch every command (dev only, it is loud)
```

---

## 4. Exercises (do these — reading is not learning)

1. Add `POST /auth/change-password`: verify old password, update hash, then
   `destroy_all()` + publish `logout_all`. Confirm every device gets 401.
2. Make the reset token single-use: `GET`+`DEL` in one Lua script, and prove a
   replay attempt fails.
3. Switch `/api/expensive` from token bucket to fixed window and demonstrate the
   window-boundary burst (2× the limit in one second).
4. Add per-plan limits: `free = 10/min`, `pro = 200/min`, read from the user hash.
5. Kill the worker with `kill -9` mid-job and watch `requeue_stuck_jobs()`
   recover it. Then break it: set `job_visibility_timeout` to 1s and observe
   duplicate execution — this is why handlers must be idempotent.
6. Add an idempotency guard: `SET job:done:{id} 1 NX EX 86400` in each handler.
7. Run two workers and confirm jobs are split, not duplicated.
8. Stop the Pub/Sub subscriber, trigger `logout-all`, restart it — the event is
   gone forever. Redo it with a Stream and see the difference.
