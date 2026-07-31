"""
============================================================================
 run_cli.py - run the multi-agent graph from the command line
============================================================================
Three demos in one file:
  1. A full run (watch all six agents + the review loop).
  2. A crash midway, then an automatic resume from the last checkpoint.
  3. A peek at the blackboard and checkpoint history in Redis.

Run:
    python run_cli.py
============================================================================
"""

import uuid

import graph
import shared_memory as bb
import checkpointer
import memory
from redis_client import r, ping


def demo_full_run():
    print("\n" + "=" * 70)
    print(" DEMO 1: full multi-agent run (with a review loop)")
    print("=" * 70)
    run_id = "run-" + uuid.uuid4().hex[:6]
    task = "Explain how Redis powers AI agents"

    # Record the user's request in short-term conversation memory.
    memory.add_message(run_id, "user", task)

    final = graph.run(run_id, task)

    # Save the assistant's final answer to conversation memory too.
    memory.add_message(run_id, "assistant", final["result"])

    print("\n   FINAL RESULT:")
    print("   " + final["result"])
    print("\n   Nodes executed (note executor/reviewer appear twice - the loop):")
    print("   " + " -> ".join(final["completed"]))

    print("\n   Blackboard (what each agent shared):")
    for agent, finding in bb.read(run_id).items():
        print(f"     {agent:11}: {finding}")
    return run_id


def demo_crash_and_resume():
    print("\n" + "=" * 70)
    print(" DEMO 2: crash after 'retriever', then resume automatically")
    print("=" * 70)
    run_id = "run-" + uuid.uuid4().hex[:6]
    task = "Summarize the latest Redis features"

    print("\n   -- First attempt (will crash) --")
    try:
        graph.run(run_id, task, crash_after="retriever")
    except RuntimeError as e:
        print(f"   caught: {e}")

    print("\n   -- Second attempt (same run_id -> resumes) --")
    final = graph.run(run_id, task)  # picks up right after 'retriever'
    print("\n   Completed after resume:")
    print("   " + " -> ".join(final["completed"]))

    print("\n   Checkpoint history (time travel):")
    for cp in checkpointer.history(run_id):
        print(f"     after '{cp['node']:11}' -> completed: {cp['state']['completed']}")


if __name__ == "__main__":
    print("Redis connected:", ping())
    r.flushall()  # clean slate for a clear demo

    demo_full_run()
    demo_crash_and_resume()

    print("\nDone. Everything above used Redis for memory, state, shared")
    print("memory, and checkpointing - the four pillars of Phase 6.\n")
