"""
============================================================================
 SHARED MEMORY - the multi-agent blackboard  (Concept 4)
============================================================================
A "blackboard" is a shared space every agent can read from and write to.
Here it's a Redis HASH keyed by run_id. Agents post findings; other agents
read them. We also expose:
  - a distributed LOCK (so two agents don't clobber the same slot), and
  - a publish() helper for event-driven coordination via Pub/Sub.
============================================================================
"""

import json
import uuid

from redis_client import r


def _bb_key(run_id: str) -> str:
    return f"run:{run_id}:blackboard"


# --- Blackboard read/write --------------------------------------------------
def post(run_id: str, agent: str, finding) -> None:
    """An agent writes a finding onto the shared blackboard."""
    r.hset(_bb_key(run_id), agent, json.dumps(finding))


def read(run_id: str) -> dict:
    """Read everything posted so far."""
    raw = r.hgetall(_bb_key(run_id))
    return {agent: json.loads(value) for agent, value in raw.items()}


# --- Distributed lock -------------------------------------------------------
def acquire_lock(resource: str, ttl_ms: int = 3000) -> str | None:
    """SET NX PX lock. Returns an owner token on success, else None."""
    token = str(uuid.uuid4())
    ok = r.set(f"lock:{resource}", token, nx=True, px=ttl_ms)
    return token if ok else None


_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def release_lock(resource: str, token: str) -> None:
    """Atomically release the lock only if we still own it."""
    r.eval(_RELEASE_LUA, 1, f"lock:{resource}", token)


# --- Coordination event -----------------------------------------------------
def publish(run_id: str, event: str) -> None:
    """Broadcast a progress event to any subscribers on this run's channel."""
    r.publish(f"run:{run_id}:events", event)
