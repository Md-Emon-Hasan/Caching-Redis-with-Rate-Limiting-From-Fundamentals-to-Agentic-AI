"""
============================================================================
 PHASE 6 - CONCEPT 4: SHARED MEMORY (multi-agent blackboard + coordination)
============================================================================

THE SCENARIO
------------
A multi-agent system has several specialists working on ONE task:
    Researcher  finds facts
    Retriever   pulls documents
    Executor    runs tools
    Reviewer    checks the result

They need to SHARE what they discover. The classic pattern is a
"BLACKBOARD": a shared memory space that every agent can read from and
write to. Redis is a natural blackboard - fast, central, visible to all.

    Researcher --writes--> [ BLACKBOARD in Redis ] <--reads-- Reviewer
    Retriever  --writes--> [                     ] <--reads-- Executor

THREE THINGS THIS CONCEPT TEACHES
---------------------------------
1. SHARED STATE  - a Redis HASH all agents read/write (the blackboard).
2. COORDINATION  - Pub/Sub so agents can react to each other's progress
                   ("Researcher is done -> Reviewer, your turn").
3. SAFETY (LOCKS)- when two agents might write the same slot at once, a
                   distributed LOCK ensures only one wins (no lost updates).

You already met Pub/Sub and locks conceptually in earlier phases; here they
become the glue that lets independent agents cooperate without stepping on
each other.
============================================================================
"""

import json
import time
import uuid

import redis


r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


# ===========================================================================
# PART 1: THE BLACKBOARD (shared hash all agents read/write)
# ===========================================================================
def _blackboard_key(task_id: str) -> str:
    return f"task:{task_id}:blackboard"


def post_finding(task_id: str, agent: str, finding) -> None:
    """An agent writes something it discovered onto the shared blackboard."""
    key = _blackboard_key(task_id)
    # Field = agent name, value = its finding (JSON). Now every other agent
    # can see it. HSET is atomic per field.
    r.hset(key, agent, json.dumps(finding))
    print(f"   [{agent}] posted a finding to the blackboard")


def read_blackboard(task_id: str) -> dict:
    """Any agent can read everything posted so far."""
    raw = r.hgetall(_blackboard_key(task_id))
    return {agent: json.loads(value) for agent, value in raw.items()}


# ===========================================================================
# PART 2: A DISTRIBUTED LOCK (prevent two agents clobbering each other)
# ===========================================================================
# Sometimes two agents want to update the SAME shared slot at the same time.
# Without a lock, one update can overwrite the other ("lost update"). A lock
# lets only one agent into the critical section at a time.
def acquire_lock(resource: str, ttl_ms: int = 3000) -> str | None:
    """
    Try to grab a lock. Returns a unique token if successful, else None.

    SET key value NX PX ttl:
      NX  -> only set if the key does NOT already exist (that's the lock)
      PX  -> auto-expire after ttl_ms so a crashed holder can't lock forever
    The random token proves WE own the lock when we release it.
    """
    token = str(uuid.uuid4())
    # nx=True + px=ttl is the standard, safe single-node Redis lock.
    acquired = r.set(f"lock:{resource}", token, nx=True, px=ttl_ms)
    return token if acquired else None


def release_lock(resource: str, token: str) -> None:
    """
    Release the lock, but ONLY if we still own it (our token matches).
    We use a Lua script so the check-and-delete is ATOMIC - otherwise the
    lock could expire between our check and delete and we'd delete someone
    else's lock.
    """
    lua = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    else
        return 0
    end
    """
    r.eval(lua, 1, f"lock:{resource}", token)


# ===========================================================================
# PART 3: COORDINATION VIA PUB/SUB (agents react to each other)
# ===========================================================================
# Instead of agents constantly polling ("are you done yet?"), an agent can
# PUBLISH an event when it finishes, and interested agents SUBSCRIBE and
# react instantly. This is event-driven agent coordination.
def announce(task_id: str, event: str) -> None:
    """Broadcast an event to anyone listening on this task's channel."""
    r.publish(f"task:{task_id}:events", event)
    print(f"   [event published] {event}")


# ---------------------------------------------------------------------------
# DEMO  ->  run:  python 04_shared_memory.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    task = "report-007"
    r.delete(_blackboard_key(task))

    # --- Part 1: agents post findings to the shared blackboard ---
    print("--- Blackboard: agents share findings ---")
    post_finding(task, "Researcher", {"fact": "Redis is in-memory"})
    post_finding(task, "Retriever", {"docs": ["d1", "d2"]})
    post_finding(task, "Executor", {"tool_result": 42})

    print("\n   Reviewer reads the whole blackboard:")
    for agent, finding in read_blackboard(task).items():
        print(f"     {agent:11}: {finding}")

    # --- Part 2: a lock protects a shared counter from two agents ---
    print("\n--- Distributed lock: safe shared update ---")
    token = acquire_lock("blackboard-write")
    if token:
        print("   Agent A acquired the lock, doing a safe update...")
        # (critical section: only one agent can be here at a time)
        # Meanwhile another agent trying to lock the same resource fails:
        other = acquire_lock("blackboard-write")
        print("   Agent B tried to acquire the same lock ->",
              "GOT IT" if other else "BLOCKED (as expected)")
        release_lock("blackboard-write", token)
        print("   Agent A released the lock")

    # --- Part 3: coordination event ---
    print("\n--- Pub/Sub: announce progress so others can react ---")
    announce(task, "Researcher_done")
    # In a real system a Reviewer process would be SUBSCRIBED to
    # task:report-007:events and would start the moment it sees this.

    # TAKEAWAY:
    # Blackboard (shared hash) = what agents know.
    # Locks = safe concurrent writes (no lost updates).
    # Pub/Sub = event-driven coordination (no wasteful polling).
    # Together they let many specialised agents cooperate reliably.
