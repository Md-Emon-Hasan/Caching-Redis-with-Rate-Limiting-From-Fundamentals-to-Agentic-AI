"""
============================================================================
 CHECKPOINTER - save/resume the graph after each node  (Concept 3)
============================================================================
After every node (agent) finishes, the graph saves a checkpoint here. If the
process crashes or is restarted, the graph reloads the latest checkpoint and
continues from the next node instead of starting over.

This is the same idea as LangGraph's Redis checkpointer. We store an
append-only LIST of checkpoints per thread so we also get time-travel and
debugging for free.
============================================================================
"""

import json
import time

from redis_client import r


def _key(thread_id: str) -> str:
    return f"thread:{thread_id}:checkpoints"


def save_checkpoint(thread_id: str, node: str, state: dict) -> None:
    """Append a snapshot of the state after completing `node`."""
    checkpoint = json.dumps({"node": node, "state": state, "ts": time.time()})
    r.rpush(_key(thread_id), checkpoint)


def latest(thread_id: str) -> dict | None:
    """Most recent checkpoint, or None if this thread never ran."""
    item = r.lindex(_key(thread_id), -1)
    return json.loads(item) if item else None


def history(thread_id: str) -> list[dict]:
    """All checkpoints in order (time-travel / debugging)."""
    return [json.loads(c) for c in r.lrange(_key(thread_id), 0, -1)]
