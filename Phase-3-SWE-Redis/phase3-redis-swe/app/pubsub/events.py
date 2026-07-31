"""
pubsub/events.py
================
PUB/SUB WITH REDIS  (Phase 3, topic 4)

Run the subscriber:  python -m app.pubsub.events

THE MENTAL MODEL
    PUBLISH events:sessions '{"type":"logout_all","user_id":"..."}'

        Publisher --> Redis --> every currently SUBSCRIBEd client

    Delivery is FIRE AND FORGET, at-most-once:
      * a subscriber that is offline at publish time NEVER gets the message
      * there is no ACK, no retry, no history
      * PUBLISH returns the number of subscribers that received it - if that is
        0, the message is simply gone

    So the rule is: Pub/Sub is for EPHEMERAL NOTIFICATIONS, never for work that
    must not be lost. If losing it would corrupt state, use a List or a Stream.

WHAT IT IS PERFECT FOR (and why we use it here)
    Cache/state invalidation across app instances. Suppose each API pod keeps a
    tiny in-process cache of sessions to save Redis round trips. When a user
    clicks "log out everywhere", pod #1 deletes the Redis keys - but pods #2..#4
    still hold stale copies in local memory. One PUBLISH tells all of them to
    drop it immediately. Losing that message is survivable (the local cache has
    a short TTL anyway), which is exactly the right risk profile for Pub/Sub.

    Other classic uses: WebSocket fan-out to whichever pod holds the socket,
    live dashboards, "someone typed" indicators, config hot-reload signals.

CONNECTION RULE
    A subscribed connection is in a special mode - it can only run
    SUBSCRIBE/UNSUBSCRIBE/PING/QUIT. So a subscriber ALWAYS needs its own
    connection, never the shared request pool.

PATTERNS
    PSUBSCRIBE 'events:*' matches many channels, but Redis has to match the
    pattern for every publish, so keep the number of patterns small.
"""

from __future__ import annotations

import asyncio
import json
import time

from redis.asyncio import Redis

from app.redis_client import new_client

CHANNEL_SESSIONS = "events:sessions"


# ------------------------------------------------------------------ publisher
async def publish_session_event(redis: Redis, event_type: str, **data) -> int:
    """
    Returns how many subscribers received it. Log it: a persistent 0 means your
    consumers are dead and nobody noticed - the classic Pub/Sub silent failure.
    """
    message = json.dumps({"type": event_type, "at": time.time(), **data})
    return await redis.publish(CHANNEL_SESSIONS, message)


# ----------------------------------------------------------------- subscriber
# Stands in for a per-pod in-memory cache that must be invalidated.
LOCAL_SESSION_CACHE: dict[str, dict] = {}


async def handle_event(event: dict) -> None:
    etype = event.get("type")
    if etype == "logout_all":
        user_id = event["user_id"]
        killed = [sid for sid, s in LOCAL_SESSION_CACHE.items() if s.get("user_id") == user_id]
        for sid in killed:
            LOCAL_SESSION_CACHE.pop(sid, None)
        print(f"[subscriber] logout_all user={user_id[:8]} -> dropped {len(killed)} cached")
    elif etype == "login":
        print(f"[subscriber] login user={event['user_id'][:8]} ip={event.get('ip')}")
    elif etype == "logout":
        LOCAL_SESSION_CACHE.pop(event.get("sid", ""), None)
        print(f"[subscriber] logout sid={event.get('sid', '')[:8]}")
    else:
        print(f"[subscriber] unknown event: {event}")


async def run_subscriber() -> None:
    r = new_client()
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(CHANNEL_SESSIONS)
    print(f"[subscriber] listening on {CHANNEL_SESSIONS} (Ctrl+C to stop)")

    try:
        # timeout lets the loop breathe so the process stays interruptible.
        while True:
            msg = await pubsub.get_message(timeout=1.0)
            if msg is None:
                continue
            try:
                await handle_event(json.loads(msg["data"]))
            except json.JSONDecodeError:
                print(f"[subscriber] bad payload: {msg['data']!r}")
    except asyncio.CancelledError:
        pass
    finally:
        # Always unsubscribe + close, or Redis keeps the client until timeout.
        await pubsub.unsubscribe(CHANNEL_SESSIONS)
        await pubsub.aclose()
        await r.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(run_subscriber())
    except KeyboardInterrupt:
        print("\n[subscriber] bye")
