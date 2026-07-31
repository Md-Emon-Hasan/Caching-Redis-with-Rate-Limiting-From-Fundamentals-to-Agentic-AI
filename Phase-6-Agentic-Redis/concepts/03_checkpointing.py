"""
============================================================================
 PHASE 6 - CONCEPT 3: CHECKPOINTING (make agent runs resumable)
============================================================================

THE PROBLEM
-----------
Agent tasks are LONG and FRAGILE. A single run might:
    - call an LLM 20 times (each can time out or hit a rate limit),
    - call external tools/APIs (which can fail),
    - take minutes to finish.

If the process crashes at step 18 of 20 and you have to start over from
step 1, you waste time AND money re-doing the expensive earlier steps.

THE SOLUTION: CHECKPOINTS
-------------------------
After EACH step, save a snapshot of the full state to Redis. If the run
crashes, you reload the LATEST snapshot and resume from exactly where it
stopped - no repeated work.

    step 1 done -> save checkpoint #1
    step 2 done -> save checkpoint #2
    step 3 CRASH
    ...restart...
    load checkpoint #2 -> resume at step 3

This is exactly how LangGraph's "checkpointer" works. LangGraph even ships a
Redis checkpointer for production. Here we build a tiny one from scratch so
you understand the mechanism.

WHY KEEP A HISTORY OF CHECKPOINTS (not just the latest)?
--------------------------------------------------------
Storing EVERY checkpoint (not just overwriting one) gives you:
    - resume-from-latest (crash recovery),
    - "time travel" debugging (inspect state at any past step),
    - the ability to fork/branch a run from an earlier point.

We use a Redis LIST as an append-only log of checkpoints per thread.
============================================================================
"""

import json
import time

import redis


r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


# ---------------------------------------------------------------------------
# 1. KEYS  (a "thread" = one resumable run)
# ---------------------------------------------------------------------------
def _checkpoints_key(thread_id: str) -> str:
    return f"thread:{thread_id}:checkpoints"


# ---------------------------------------------------------------------------
# 2. SAVE A CHECKPOINT
# ---------------------------------------------------------------------------
def save_checkpoint(thread_id: str, step: str, state: dict) -> None:
    """
    Append a snapshot of the state after completing `step`.

    Each checkpoint records:
      - step  : which step just finished (so we know where to resume)
      - state : a full copy of the working state at this moment
      - ts    : timestamp (useful for debugging / ordering)
    """
    checkpoint = json.dumps({"step": step, "state": state, "ts": time.time()})
    # RPUSH appends -> the list is an ordered, append-only checkpoint log.
    r.rpush(_checkpoints_key(thread_id), checkpoint)
    print(f"   [CHECKPOINT] saved after '{step}'")


# ---------------------------------------------------------------------------
# 3. LOAD THE LATEST CHECKPOINT (for resuming)
# ---------------------------------------------------------------------------
def load_latest(thread_id: str) -> dict | None:
    """Return the most recent checkpoint, or None if the run never started."""
    # LINDEX -1 reads the LAST element without loading the whole list.
    latest = r.lindex(_checkpoints_key(thread_id), -1)
    return json.loads(latest) if latest else None


def load_all(thread_id: str) -> list[dict]:
    """Return every checkpoint in order (for time-travel / debugging)."""
    raw = r.lrange(_checkpoints_key(thread_id), 0, -1)
    return [json.loads(c) for c in raw]


# ---------------------------------------------------------------------------
# 4. A CHECKPOINTED, RESUMABLE AGENT RUN
# ---------------------------------------------------------------------------
# We define the pipeline as an ordered list of steps. Each step does some
# "work" (mocked) and updates the state.
STEPS = ["research", "analyze", "draft", "review", "finalize"]


def do_work(step: str, state: dict) -> dict:
    """Mock the expensive work of one step and return the updated state."""
    time.sleep(0.3)  # pretend this step is slow (LLM/tool call)
    state = dict(state)                      # copy so we don't mutate in place
    state[step] = f"output of {step}"
    state["completed_steps"] = state.get("completed_steps", []) + [step]
    return state


def run(thread_id: str, crash_at: str | None = None) -> dict:
    """
    Run the pipeline with checkpointing.

    RESUME LOGIC:
      - Look for the latest checkpoint.
      - If found, restore its state and SKIP every already-completed step.
      - Otherwise start fresh.

    crash_at : for the demo, simulate a crash right BEFORE this step runs.
    """
    latest = load_latest(thread_id)

    if latest:
        state = latest["state"]
        done = set(state.get("completed_steps", []))
        print(f"   [RESUME] found checkpoint after '{latest['step']}', "
              f"skipping {len(done)} completed step(s)")
    else:
        state = {"completed_steps": []}
        done = set()
        print("   [START] no checkpoint found, starting fresh")

    for step in STEPS:
        if step in done:
            continue  # already finished in a previous (crashed) run - skip it

        if step == crash_at:
            # Simulate a crash: stop abruptly WITHOUT finishing this step.
            print(f"   [CRASH]  process died before finishing '{step}'!")
            raise RuntimeError(f"simulated crash at {step}")

        state = do_work(step, state)         # do the expensive work
        save_checkpoint(thread_id, step, state)  # persist progress immediately

    print("   [DONE] all steps complete")
    return state


# ---------------------------------------------------------------------------
# DEMO  ->  run:  python 03_checkpointing.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    thread = "job-42"
    r.delete(_checkpoints_key(thread))  # fresh start

    print("--- First run: crashes at 'draft' (step 3 of 5) ---")
    try:
        run(thread, crash_at="draft")
    except RuntimeError as e:
        print(f"   caught: {e}")

    print("\n--- Second run: resumes automatically from the last checkpoint ---")
    final = run(thread)   # no crash this time -> resumes at 'draft'
    print("\nFinal completed steps:", final["completed_steps"])

    print("\n--- Time travel: every checkpoint we recorded ---")
    for cp in load_all(thread):
        print(f"  after '{cp['step']:8}' -> completed: {cp['state']['completed_steps']}")

    # TAKEAWAY:
    # The second run did NOT repeat research/analyze - it picked up at 'draft'.
    # In production this saves huge amounts of time and API cost, and makes
    # long-running agents robust against crashes, restarts, and deploys.
