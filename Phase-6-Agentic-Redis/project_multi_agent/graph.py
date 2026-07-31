"""
============================================================================
 GRAPH - the orchestrator that runs the agents (LangGraph-style)
============================================================================
This is a tiny, from-scratch version of a LangGraph "StateGraph". It shows
the machinery so you understand what frameworks do under the hood, and how
Redis provides the four things an agentic system needs:

    1. shared STATE      (state.py)        - the object that flows between nodes
    2. CHECKPOINTING     (checkpointer.py) - resume after a crash
    3. SHARED MEMORY     (shared_memory.py)- the blackboard between agents
    4. conversation MEMORY(memory.py)      - what the user and agent said

HOW THE GRAPH WORKS
-------------------
- NODES are the agent functions from agents.py.
- EDGES define what runs next. Most edges are fixed ("after A run B").
- A CONDITIONAL edge lets the graph branch/loop: the Reviewer either ends
  the run (approved) or loops back to the Executor (needs revision).
- After EVERY node we save a checkpoint, so a crash can be resumed.

    planner -> researcher -> retriever -> tool_router -> executor -> reviewer
                                                             ^            |
                                                             |   approved?|
                                                        (revise) <--- no  / yes -> END
============================================================================
"""

import agents
import state as state_store
import checkpointer

# The fixed part of the graph: node name -> function, and the "normal" next node.
NODES = {
    "planner": agents.planner,
    "researcher": agents.researcher,
    "retriever": agents.retriever,
    "tool_router": agents.tool_router,
    "executor": agents.executor,
    "reviewer": agents.reviewer,
}

# Linear edges (the happy path). The reviewer's next step is decided
# dynamically by the conditional router below, so it's not listed here.
LINEAR_NEXT = {
    "planner": "researcher",
    "researcher": "retriever",
    "retriever": "tool_router",
    "tool_router": "executor",
    "executor": "reviewer",
}


def _route_after_reviewer(state: dict) -> str:
    """
    CONDITIONAL EDGE: decide where to go after the Reviewer.
    - approved      -> "END" (stop)
    - not approved  -> "executor" (loop back and try again)
    A safety cap on revisions prevents an infinite loop.
    """
    verdict = state.get("review", {})
    if verdict.get("approved"):
        return "END"
    if state.get("revision", 0) >= 3:      # hard cap: don't loop forever
        return "END"
    return "executor"                       # revise: re-run executor -> reviewer


def _next_node(current: str, state: dict) -> str:
    """Given the node that just finished, return the next node (or 'END')."""
    if current == "reviewer":
        return _route_after_reviewer(state)
    return LINEAR_NEXT.get(current, "END")


# ---------------------------------------------------------------------------
# RUN THE GRAPH  (with automatic checkpoint + resume)
# ---------------------------------------------------------------------------
def run(run_id: str, task: str, thread_id: str | None = None,
        crash_after: str | None = None) -> dict:
    """
    Execute the whole graph for `task`.

    thread_id   : the checkpoint thread (defaults to run_id). Re-running with
                  the same thread_id RESUMES from the last checkpoint.
    crash_after : for the demo - simulate a crash right after this node runs,
                  so you can then resume and see checkpointing work.
    """
    thread_id = thread_id or run_id

    # --- Resume if a checkpoint exists, else start fresh ---
    cp = checkpointer.latest(thread_id)
    if cp:
        state = cp["state"]
        # Figure out where to continue from: the node AFTER the last one saved.
        start = _next_node(cp["node"], state)
        print(f"   [RESUME] last checkpoint after '{cp['node']}', "
              f"continuing at '{start}'")
    else:
        state = state_store.initial_state(run_id, task)
        state_store.save(run_id, state)
        start = "planner"
        print(f"   [START]  new run, beginning at '{start}'")

    # --- Walk the graph node by node ---
    current = start
    while current != "END":
        node_fn = NODES[current]

        # 1. Run the agent; it returns only the fields it changed.
        changes = node_fn(state)

        # 2. Merge those changes into the shared state and record progress.
        state.update(changes)
        state["completed"] = state.get("completed", []) + [current]
        state_store.save(run_id, state)          # keep Redis state current

        # 3. Checkpoint AFTER the node so we can resume from here on a crash.
        checkpointer.save_checkpoint(thread_id, current, state)

        # 4. Optional demo crash.
        if current == crash_after:
            print(f"   [CRASH]  simulated crash after '{current}'")
            raise RuntimeError(f"crash after {current}")

        # 5. Decide what runs next (this is where the review loop happens).
        current = _next_node(current, state)

    print("   [END]    graph complete")
    return state
