"""
queue/producer.py
=================
MESSAGE QUEUE WITH REDIS - the producer side  (Phase 3, topic 3)

WHY QUEUE AT ALL?
    Sending a welcome email takes 800ms and can fail. If you do it inside the
    HTTP handler, the user waits 800ms and a mail-provider outage becomes a 500
    on your signup endpoint. Instead:

        POST /register  ->  write user  ->  LPUSH job  ->  201 in 5ms
                                              |
                                     worker process (separate box)
                                              |
                                        sends the email, retries on failure

    That is the single most common backend refactor in the industry, and Redis
    is the default first queue because you already have it.

LIST-BASED QUEUE MECHANICS
    LPUSH pushes on the left, the worker pops from the right (BRMOVE/BLMOVE)
    -> FIFO. Push and pop are O(1) no matter how deep the queue is.

    LPUSH + BRPOP is "at-most-once": if the worker crashes after popping, the
    job is gone. We fix that in worker.py with BLMOVE into a processing list
    ("reliable queue" pattern), which upgrades us to at-least-once delivery.

AT-LEAST-ONCE => YOUR HANDLERS MUST BE IDEMPOTENT
    A job can run twice (worker died after doing the work but before ACKing).
    Include a stable `job_id` and let the handler skip work it already did -
    e.g. `SET job:done:{id} 1 NX EX 86400` before acting.
"""

from __future__ import annotations

import json
import time
import uuid

from redis.asyncio import Redis


def queue_key(name: str) -> str:
    return f"q:{name}"


def delayed_key(name: str) -> str:
    return f"q:{name}:delayed"


def dead_key(name: str) -> str:
    return f"q:{name}:dead"


def processing_key(name: str, worker_id: str) -> str:
    return f"q:{name}:processing:{worker_id}"


async def enqueue(
    redis: Redis,
    queue: str,
    task: str,
    payload: dict,
    *,
    delay_seconds: int = 0,
) -> str:
    """
    Put one job on the queue. Returns the job id so the caller can trace it.

    A job is JSON because it must survive process boundaries and language
    changes. Never push pickled Python objects onto a shared queue.
    """
    job = {
        "id": uuid.uuid4().hex,
        "task": task,           # which handler should run
        "payload": payload,     # handler arguments
        "attempts": 0,          # incremented by the worker on each failure
        "enqueued_at": time.time(),
    }
    body = json.dumps(job)

    if delay_seconds > 0:
        # Scheduled/"run later" jobs live in a ZSET scored by their run time.
        # A scheduler moves them into the real queue when they become due.
        await redis.zadd(delayed_key(queue), {body: time.time() + delay_seconds})
    else:
        await redis.lpush(queue_key(queue), body)

    return job["id"]


async def queue_stats(redis: Redis, queue: str) -> dict:
    """Depth metrics you should graph in production (a rising queue = trouble)."""
    async with redis.pipeline(transaction=False) as pipe:
        pipe.llen(queue_key(queue))
        pipe.zcard(delayed_key(queue))
        pipe.llen(dead_key(queue))
        pending, delayed, dead = await pipe.execute()
    return {"pending": pending, "delayed": delayed, "dead_letter": dead}
