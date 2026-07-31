"""
============================================================================
 PHASE 6 - CONCEPT 2: STATE MANAGEMENT (the shared "working memory")
============================================================================

MEMORY vs. STATE - what's the difference?
-----------------------------------------
Concept 1 (memory) = the CONVERSATION log (what was said).
This concept (state) = the TASK's working data (what the agent is doing).

Think of a research agent solving "Write a report on Redis":
    memory : the chat between user and agent
    state  : { plan: [...], findings: [...], current_step: 3, draft: "..." }

In agentic frameworks like LangGraph, this "state" object is the single
source of truth that flows from one step (node) to the next. Each agent:
    1. READS the current state,
    2. does its job,
    3. WRITES an updated state back.

    Planner  ->  writes plan into state
                     |
                     v (state lives in Redis)
    Executor ->  reads plan, executes, writes results into state

WHY PUT STATE IN REDIS INSTEAD OF A PYTHON VARIABLE?
----------------------------------------------------
1. DURABILITY : if the process crashes, the state survives (see Concept 3).
2. SHARING    : multiple agents / workers / machines can read the same state.
3. VISIBILITY : you can inspect a running task's state from redis-cli.
4. SCALING    : agent steps can run on different servers and still coordinate.

We store state as a Redis HASH keyed by run_id, so related fields live
together and can be read/updated field-by-field.
============================================================================
"""

import json

import redis


r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


# ---------------------------------------------------------------------------
# 1. KEY
# ---------------------------------------------------------------------------
def _state_key(run_id: str) -> str:
    # One hash per agent "run" (one task execution).
    return f"run:{run_id}:state"


# ---------------------------------------------------------------------------
# 2. INITIALISE STATE
# ---------------------------------------------------------------------------
def init_state(run_id: str, task: str) -> dict:
    """Create the starting state for a new task."""
    state = {
        "task": task,
        "plan": [],           # filled by the Planner
        "findings": [],       # filled by the Researcher / Retriever
        "current_step": 0,    # which plan step we're on
        "status": "created",  # created -> planning -> running -> done
        "result": None,       # final output
    }
    _write_state(run_id, state)
    return state


# ---------------------------------------------------------------------------
# 3. READ / WRITE STATE
# ---------------------------------------------------------------------------
def get_state(run_id: str) -> dict:
    """Load the full state and JSON-decode every field back to Python types."""
    key = _state_key(run_id)
    raw = r.hgetall(key)
    # Every value was JSON-encoded on write, so decode each one.
    return {field: json.loads(value) for field, value in raw.items()}


def _write_state(run_id: str, state: dict) -> None:
    """Overwrite the whole state hash. JSON-encode each field."""
    key = _state_key(run_id)
    mapping = {field: json.dumps(value) for field, value in state.items()}
    # HSET writes all fields in ONE round trip (atomic per-field).
    r.hset(key, mapping=mapping)


def update_state(run_id: str, **changes) -> dict:
    """
    Update only the fields you pass, leaving the rest untouched.

    Example:
        update_state(run_id, current_step=2, status="running")

    This is how each agent node "returns" its changes: it reads state,
    computes new values, and calls update_state with just the deltas.
    """
    key = _state_key(run_id)
    mapping = {field: json.dumps(value) for field, value in changes.items()}
    r.hset(key, mapping=mapping)     # updates/creates only these fields
    return get_state(run_id)


# ---------------------------------------------------------------------------
# 4. TWO AGENTS SHARING STATE VIA REDIS
# ---------------------------------------------------------------------------
def planner(run_id: str) -> None:
    """Planner agent: breaks the task into steps and writes them to state."""
    state = get_state(run_id)
    task = state["task"]
    # A real planner would call an LLM. We mock a 3-step plan.
    plan = [f"Research: {task}", f"Analyze findings", f"Write final answer"]
    update_state(run_id, plan=plan, status="planned")
    print(f"   [PLANNER]  wrote a {len(plan)}-step plan to shared state")


def executor(run_id: str) -> None:
    """Executor agent: READS the plan the planner wrote, then runs it."""
    state = get_state(run_id)
    plan = state["plan"]                 # <- reads what the planner produced
    if not plan:
        print("   [EXECUTOR] no plan found - planner must run first")
        return

    findings = []
    for i, step in enumerate(plan):
        findings.append(f"result of step {i}: '{step}'")
        # Persist progress after every step so state is always up to date.
        update_state(run_id, current_step=i + 1, findings=findings,
                     status="running")

    update_state(run_id, status="done",
                 result="Final answer assembled from: " + "; ".join(findings))
    print(f"   [EXECUTOR] executed {len(plan)} steps using the shared plan")


# ---------------------------------------------------------------------------
# DEMO  ->  run:  python 02_state_management.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_id = "task-001"
    r.delete(_state_key(run_id))  # fresh start

    print("--- Initialise shared state ---")
    init_state(run_id, task="Explain Redis for agents")

    print("\n--- Planner and Executor cooperate THROUGH Redis ---")
    planner(run_id)     # writes plan
    executor(run_id)    # reads plan, produces result

    print("\n--- Final state (as any other worker/machine would see it) ---")
    final = get_state(run_id)
    for field, value in final.items():
        print(f"  {field:13}: {value}")

    # TAKEAWAY:
    # The planner and executor never called each other directly. They
    # communicated ONLY through shared state in Redis. That decoupling is
    # what lets agent steps run independently, retry, and scale.
