"""
============================================================================
 MEMORY - short-term conversation memory  (Concept 1 as project code)
============================================================================
Stores the user<->assistant conversation as a Redis LIST, one per
conversation_id, with a sliding window and idle-TTL. This is the agent's
"short-term memory": it lets the system remember earlier turns even though
the underlying LLM is stateless.
============================================================================
"""

import json
import time

import config
from redis_client import r


def _key(conversation_id: str) -> str:
    return f"conv:{conversation_id}:messages"


def add_message(conversation_id: str, role: str, content: str) -> None:
    """Append a turn, trim to the window, and refresh the idle-TTL."""
    turn = json.dumps({"role": role, "content": content, "ts": time.time()})
    key = _key(conversation_id)
    r.rpush(key, turn)                              # append newest at the tail
    r.ltrim(key, -config.CONVERSATION_WINDOW, -1)  # keep only last N (window)
    r.expire(key, config.CONVERSATION_TTL)         # forget idle conversations


def get_history(conversation_id: str, last_n: int | None = None) -> list[dict]:
    """Return the conversation, oldest first."""
    key = _key(conversation_id)
    raw = r.lrange(key, 0, -1) if last_n is None else r.lrange(key, -last_n, -1)
    return [json.loads(item) for item in raw]
