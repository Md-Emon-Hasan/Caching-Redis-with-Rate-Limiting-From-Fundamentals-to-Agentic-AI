"""
queue/worker.py
===============
THE CONSUMER SIDE - a production-shaped worker.

Run it:  python -m app.queue.worker

WHAT MAKES THIS "RELIABLE"
    BLMOVE q RIGHT -> processing LEFT
    ...is a single atomic operation: the job leaves the queue and lands in this
    worker's private processing list at the same instant. If the process is
    SIGKILLed mid-job, the payload is still sitting in the processing list, and
    the recovery loop (`requeue_stuck_jobs`) pushes it back.

    Compare:
        BRPOP            -> job lives only in worker RAM  -> lost on crash
        BLMOVE + LREM    -> job is always in Redis somewhere -> recoverable

    "LREM processing 1 <payload>" is the ACK. Until it runs, the job is in
    flight.

FAILURE POLICY
    attempt 1 fails -> retry in 2s
    attempt 2 fails -> retry in 4s
    attempt 3 fails -> move to q:{name}:dead   (dead letter queue)

    EXPONENTIAL BACKOFF matters: retrying a failing downstream immediately just
    turns your worker into a DDoS against it. The dead letter queue matters
    because a poison message must never block the queue forever - you want it
    parked somewhere a human can inspect it.

GRACEFUL SHUTDOWN
    On SIGTERM we stop accepting new jobs, finish the current one, then exit.
    Kubernetes sends SIGTERM before SIGKILL; handling it prevents half-done work
    on every deploy.
"""

from __future__ import annotations

import asyncio
import json
import signal
import socket
import time

from redis.asyncio import Redis

from app.config import settings
from app.queue.producer import (
    dead_key,
    delayed_key,
    processing_key,
    queue_key,
)
from app.redis_client import new_client

# --- Lua: atomically move all DUE delayed jobs into the live queue ----------
# Without Lua, another worker could pop the same member between our
# ZRANGEBYSCORE and ZREM, and the job would be executed twice.
PROMOTE_DUE_LUA = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], 0, ARGV[1], 'LIMIT', 0, 100)
for _, job in ipairs(due) do
  redis.call('ZREM', KEYS[1], job)
  redis.call('LPUSH', KEYS[2], job)
end
return #due
"""


# ---------------------------------------------------------------------------
# Job handlers. In a real app each of these calls out to an email provider,
# an S3 bucket, an LLM, etc. Keep them idempotent.
# ---------------------------------------------------------------------------
async def send_welcome_email(payload: dict) -> None:
    await asyncio.sleep(0.3)  # pretend network I/O
    print(f"  [handler] welcome email -> {payload.get('email')}")


async def send_password_reset(payload: dict) -> None:
    await asyncio.sleep(0.3)
    print(f"  [handler] reset link -> {payload.get('email')} token={payload.get('token')}")


async def flaky_task(payload: dict) -> None:
    """Used by the demo to show retries + the dead letter queue."""
    raise RuntimeError("downstream provider is down")


HANDLERS = {
    "welcome_email": send_welcome_email,
    "password_reset": send_password_reset,
    "flaky": flaky_task,
}


class Worker:
    def __init__(self, queue: str | None = None) -> None:
        self.queue = queue or settings.queue_name
        # Worker id must be unique per process: it names this worker's private
        # processing list. host+pid is a simple scheme that survives restarts
        # of the same pod name (so its stuck jobs get picked up again).
        self.worker_id = f"{socket.gethostname()}-{time.time_ns() % 100000}"
        # Own client/pool: BLMOVE holds a connection for its whole timeout.
        self.r: Redis = new_client()
        self._promote = self.r.register_script(PROMOTE_DUE_LUA)
        self.running = True

    # ------------------------------------------------------------------- loops
    async def run(self) -> None:
        print(f"[worker {self.worker_id}] consuming '{self.queue}' (Ctrl+C to stop)")
        self._install_signal_handlers()
        # Two background loops + the main consume loop, cooperating in one
        # event loop. In production you would often split these into separate
        # processes so a slow job cannot delay the scheduler.
        await asyncio.gather(
            self._consume_loop(),
            self._scheduler_loop(),
            self._recovery_loop(),
        )
        await self.r.aclose()

    async def _consume_loop(self) -> None:
        pk = processing_key(self.queue, self.worker_id)
        while self.running:
            # timeout=2 -> returns None every 2s so we can re-check `running`.
            # Never use timeout=0 (block forever) in a process you want to
            # shut down cleanly.
            body = await self.r.blmove(queue_key(self.queue), pk, 2, "RIGHT", "LEFT")
            if body is None:
                continue
            await self._execute(body, pk)

    async def _scheduler_loop(self) -> None:
        """Promote delayed/retry jobs whose time has come."""
        while self.running:
            moved = await self._promote(
                keys=[delayed_key(self.queue), queue_key(self.queue)],
                args=[time.time()],
            )
            if moved:
                print(f"[scheduler] promoted {moved} delayed job(s)")
            await asyncio.sleep(1)

    async def _recovery_loop(self) -> None:
        """Every 30s, rescue jobs abandoned by dead workers."""
        while self.running:
            await asyncio.sleep(30)
            await self.requeue_stuck_jobs()

    # -------------------------------------------------------------- execution
    async def _execute(self, body: str, processing: str) -> None:
        try:
            job = json.loads(body)
        except json.JSONDecodeError:
            # Unparseable payload: ACK it and park it, or it loops forever.
            await self.r.lrem(processing, 1, body)
            await self.r.lpush(dead_key(self.queue), body)
            return

        handler = HANDLERS.get(job["task"])
        started = time.perf_counter()
        try:
            if handler is None:
                raise KeyError(f"no handler registered for task '{job['task']}'")
            await handler(job.get("payload", {}))
        except Exception as exc:  # noqa: BLE001 - a worker must never die on a job
            await self._handle_failure(job, body, processing, exc)
        else:
            # SUCCESS = remove from the processing list. This is the ACK.
            await self.r.lrem(processing, 1, body)
            ms = (time.perf_counter() - started) * 1000
            print(f"[worker] ok  task={job['task']} id={job['id'][:8]} {ms:.0f}ms")

    async def _handle_failure(self, job: dict, body: str, processing: str, exc: Exception) -> None:
        job["attempts"] = job.get("attempts", 0) + 1
        job["last_error"] = str(exc)[:300]
        new_body = json.dumps(job)

        if job["attempts"] < settings.job_max_attempts:
            backoff = 2 ** job["attempts"]  # 2s, 4s, 8s...
            async with self.r.pipeline(transaction=True) as pipe:
                pipe.zadd(delayed_key(self.queue), {new_body: time.time() + backoff})
                pipe.lrem(processing, 1, body)  # ACK the old copy
                await pipe.execute()
            print(f"[worker] retry #{job['attempts']} in {backoff}s task={job['task']}: {exc}")
        else:
            async with self.r.pipeline(transaction=True) as pipe:
                pipe.lpush(dead_key(self.queue), new_body)
                pipe.lrem(processing, 1, body)
                await pipe.execute()
            print(f"[worker] DEAD LETTER task={job['task']} after {job['attempts']} attempts")

    # ---------------------------------------------------------------- recovery
    async def requeue_stuck_jobs(self, older_than: int | None = None) -> int:
        """
        Scan every worker's processing list and requeue jobs that have been in
        flight longer than the visibility timeout - i.e. their worker died.

        Uses SCAN, never KEYS. KEYS blocks the single-threaded server while it
        walks the entire keyspace; SCAN returns a cursor in small batches.
        """
        older_than = older_than or settings.job_visibility_timeout
        requeued = 0
        pattern = f"q:{self.queue}:processing:*"

        async for key in self.r.scan_iter(match=pattern, count=100):
            for body in await self.r.lrange(key, 0, -1):
                try:
                    job = json.loads(body)
                except json.JSONDecodeError:
                    continue
                # `enqueued_at` is a rough proxy for "when did work start".
                # Streams-based queues track this properly via XPENDING idle time.
                if time.time() - job.get("enqueued_at", 0) > older_than:
                    async with self.r.pipeline(transaction=True) as pipe:
                        pipe.lpush(queue_key(self.queue), body)
                        pipe.lrem(key, 1, body)
                        await pipe.execute()
                    requeued += 1
        if requeued:
            print(f"[recovery] requeued {requeued} stuck job(s)")
        return requeued

    # ---------------------------------------------------------------- shutdown
    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop)
            except (NotImplementedError, RuntimeError):
                signal.signal(
                    sig,
                    lambda _signum, _frame: loop.call_soon_threadsafe(self._stop),
                )

    def _stop(self) -> None:
        print("[worker] shutdown signal received - finishing current job...")
        self.running = False


if __name__ == "__main__":
    asyncio.run(Worker().run())
