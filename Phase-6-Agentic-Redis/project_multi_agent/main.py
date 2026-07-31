"""
============================================================================
 MAIN - FastAPI app exposing the multi-agent system
============================================================================
Run it:
    uvicorn main:app --reload
Then open:
    http://localhost:8000/docs

Endpoints:
    GET  /health              -> app + Redis status
    POST /run                 -> run a task through the agent graph
    GET  /run/{run_id}/state  -> inspect the shared state
    GET  /run/{run_id}/board  -> inspect the blackboard (what agents shared)
    GET  /run/{run_id}/trace  -> the checkpoint history (every node)
    POST /run/{run_id}/resume -> resume a crashed/interrupted run
============================================================================
"""

import uuid

from fastapi import FastAPI
from pydantic import BaseModel

import graph
import state as state_store
import shared_memory as bb
import checkpointer
import memory
import redis_client

app = FastAPI(title="Multi-Agent System on Redis (Phase 6)")


class RunRequest(BaseModel):
    task: str


@app.get("/health")
def health():
    return {"status": "ok", "redis_connected": redis_client.ping()}


@app.post("/run")
def run_task(req: RunRequest):
    """
    Run a task through the full agent graph (Planner -> ... -> Reviewer).
    Returns the final answer plus which nodes executed.
    """
    run_id = "run-" + uuid.uuid4().hex[:8]
    memory.add_message(run_id, "user", req.task)     # short-term memory
    final = graph.run(run_id, req.task)
    memory.add_message(run_id, "assistant", final["result"])
    return {
        "run_id": run_id,
        "result": final["result"],
        "nodes_executed": final["completed"],
        "review": final.get("review", {}),
    }


@app.get("/run/{run_id}/state")
def get_state(run_id: str):
    """Inspect the shared AgentState for a run."""
    return state_store.load(run_id)


@app.get("/run/{run_id}/board")
def get_board(run_id: str):
    """Inspect the blackboard - what each agent shared with the others."""
    return bb.read(run_id)


@app.get("/run/{run_id}/trace")
def get_trace(run_id: str):
    """The checkpoint history: the state after every node (time travel)."""
    return [{"node": cp["node"], "completed": cp["state"]["completed"]}
            for cp in checkpointer.history(run_id)]


@app.post("/run/{run_id}/resume")
def resume(run_id: str):
    """
    Resume an interrupted run from its last checkpoint. Useful if a run
    crashed or the server restarted mid-task.
    """
    cp = checkpointer.latest(run_id)
    if not cp:
        return {"error": "no checkpoint found for this run_id"}
    task = cp["state"]["task"]
    final = graph.run(run_id, task)   # resumes automatically
    return {"run_id": run_id, "result": final["result"],
            "nodes_executed": final["completed"]}
