"""
queue/streams_demo.py
=====================
BONUS (still Phase 3): the same queue built on REDIS STREAMS.

Run:  python -m app.queue.streams_demo

WHY STREAMS EXIST
    Lists give you a queue, but you have to hand-build acknowledgements,
    in-flight tracking and recovery (that is what worker.py does). Streams put
    all of that INSIDE Redis:

      XADD          append an entry (immutable log, auto ID = timestamp-seq)
      XGROUP        create a consumer group ("workers of this queue")
      XREADGROUP    read new entries AND record them as pending for you
      XACK          mark done -> removed from the Pending Entries List (PEL)
      XAUTOCLAIM    steal entries whose consumer died (idle > N ms)

    So: at-least-once delivery, per-consumer load balancing, and crash recovery
    with no application logic. Streams are also *retained*: multiple different
    consumer groups can each read the whole history independently, which
    Pub/Sub cannot do.

WHEN TO USE WHAT
    Pub/Sub   fire-and-forget fan-out, offline subscribers miss messages
    List      simplest FIFO job queue, you own reliability
    Stream    durable log + consumer groups + ACKs  <- default for new work
    Kafka     multi-datacentre, days of retention, huge throughput -> outgrow Redis
"""

from __future__ import annotations

import asyncio

from app.redis_client import new_client

STREAM = "stream:emails"
GROUP = "mailers"


async def ensure_group(r) -> None:
    """
    MKSTREAM creates the stream if it does not exist yet.
    '$' means "this group starts from new messages only"; use '0' to replay
    everything already in the stream.
    """
    try:
        await r.xgroup_create(STREAM, GROUP, id="$", mkstream=True)
        print(f"created group {GROUP}")
    except Exception as exc:  # BUSYGROUP = already exists, which is fine
        if "BUSYGROUP" not in str(exc):
            raise


async def produce(r, n: int = 5) -> None:
    for i in range(n):
        # Stream entries are flat field/value maps, not JSON blobs (though you
        # may store a JSON string in one field if the payload is nested).
        msg_id = await r.xadd(STREAM, {"task": "welcome_email", "email": f"user{i}@test.dev"})
        print(f"[producer] XADD {msg_id}")
    # Cap memory: keep only the newest 10k entries. Without MAXLEN a stream
    # grows forever - this is the #1 Streams production mistake.
    await r.xtrim(STREAM, maxlen=10_000, approximate=True)


async def consume(r, consumer: str, rounds: int = 3) -> None:
    for _ in range(rounds):
        # '>' = give me entries never delivered to this group.
        resp = await r.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=10, block=2000)
        if not resp:
            continue
        for _stream, entries in resp:
            for msg_id, fields in entries:
                print(f"[{consumer}] processing {msg_id} {fields}")
                await asyncio.sleep(0.1)
                # ACK removes it from the group's PEL. Skip this and the entry
                # stays pending forever, waiting to be claimed by someone else.
                await r.xack(STREAM, GROUP, msg_id)


async def recover(r, consumer: str) -> None:
    """Take over entries pending for >30s (their consumer probably crashed)."""
    cursor, claimed, _ = await r.xautoclaim(STREAM, GROUP, consumer, min_idle_time=30_000, count=10)
    for msg_id, fields in claimed:
        print(f"[{consumer}] claimed abandoned {msg_id} {fields}")
        await r.xack(STREAM, GROUP, msg_id)


async def main() -> None:
    r = new_client()
    await ensure_group(r)
    await produce(r)
    # Two consumers in the same group => entries are split between them.
    await asyncio.gather(consume(r, "worker-A"), consume(r, "worker-B"))
    await recover(r, "worker-A")
    info = await r.xinfo_groups(STREAM)
    print("group info:", info)
    await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())
