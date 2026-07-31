"""
============================================================================
 STATE - the shared AgentState that flows through the graph (Concept 2)
============================================================================
Every agent (node) in the graph reads this state, does its job, and writes
its results back. The state lives in a Redis HASH keyed by run_id, so it is
durable, inspectable, and shareable across processes/machines.

This mirrors LangGraph's "State" object - the single source of truth that
moves from node to node.
============================================================================
"""

import json

from redis_client import r


def _key(run_id: str) -> str:
    return f"run:{run_id}:state"


# The starting shape of the state for a new task. Each field is filled in by
# a specific agent as the graph runs (noted in comments).
def initial_state(run_id: str, task: str) -> dict:
    return {
        "run_id": run_id,
        "task": task,
        "plan": [],            # <- Planner
        "research": [],        # <- Researcher
        "documents": [],       # <- Retriever
        "tool_plan": [],       # <- Tool Router
        "tool_results": [],    # <- Executor
        "draft": "",           # <- Executor assembles this
        "review": {},          # <- Reviewer verdict {approved, notes}
        "result": "",          # <- final answer once approved
        "completed": [],       # <- which nodes have run (used for resume)
        "revision": 0,         # <- how many review loops we've done
    }


def save(run_id: str, state: dict) -> None:
    """Persist the whole state (each field JSON-encoded)."""
    mapping = {field: json.dumps(value) for field, value in state.items()}
    r.hset(_key(run_id), mapping=mapping)


def load(run_id: str) -> dict:
    """Load and decode the full state."""
    raw = r.hgetall(_key(run_id))
    return {field: json.loads(value) for field, value in raw.items()}


def exists(run_id: str) -> bool:
    return r.exists(_key(run_id)) == 1
