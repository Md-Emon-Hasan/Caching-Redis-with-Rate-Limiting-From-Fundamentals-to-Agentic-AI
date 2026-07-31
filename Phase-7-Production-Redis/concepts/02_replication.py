"""
============================================================================
 PHASE 7 - CONCEPT 2: REPLICATION (Master - Replica)
============================================================================

WHY REPLICATE?
--------------
One Redis server is a single point of failure and a single point of load.
Replication solves both:

  1. READ SCALING : replicas hold a live COPY of the master's data. You can
     send all your read traffic to replicas and let the master handle writes.
     A read-heavy app (like a cache) scales by adding more replicas.

  2. REDUNDANCY : if the master dies, a replica already has the data, so you
     can promote it (Concept 3 automates this with Sentinel).

HOW IT WORKS
------------
    Writes ─────────────►  MASTER
                             │  (async stream of changes)
                 ┌───────────┼───────────┐
                 ▼           ▼           ▼
              REPLICA 1   REPLICA 2   REPLICA 3   ◄──── Reads
             (read-only)  (read-only) (read-only)

A replica connects to the master with `REPLICAOF <host> <port>`, does an
initial full sync, then receives every subsequent write as a live stream.

THE ONE GOTCHA: ASYNC = EVENTUAL CONSISTENCY
--------------------------------------------
Replication is ASYNCHRONOUS. A write on the master reaches replicas a moment
later (usually sub-millisecond, but not instant). So a read from a replica
can very briefly return slightly stale data. This is fine for caches; be
careful when you need read-your-own-writes.

THIS DEMO
---------
We start one master and one replica, write on the master, and read the same
key from the replica - proving the data replicated automatically.
============================================================================
"""

import subprocess
import time
import os
import shutil

import redis

MASTER_PORT = 7201
REPLICA_PORT = 7202
BASE = "/tmp/phase7_replication"


def start_node(port: int, replicaof: tuple[str, int] | None = None):
    """Start a Redis node; if replicaof is given, it becomes a replica."""
    data_dir = f"{BASE}/{port}"
    os.makedirs(data_dir, exist_ok=True)
    args = ["redis-server", "--port", str(port), "--dir", data_dir]
    if replicaof:
        # This single directive turns a normal Redis into a replica of another.
        args += ["--replicaof", replicaof[0], str(replicaof[1])]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    time.sleep(1)
    return proc


def main():
    shutil.rmtree(BASE, ignore_errors=True)

    print("--- 1. Start the MASTER ---")
    master_proc = start_node(MASTER_PORT)
    master = redis.Redis(port=MASTER_PORT, decode_responses=True)

    print("--- 2. Start a REPLICA pointed at the master ---")
    replica_proc = start_node(REPLICA_PORT, replicaof=("127.0.0.1", MASTER_PORT))
    replica = redis.Redis(port=REPLICA_PORT, decode_responses=True)

    # Wait until the replica reports the link to the master is fully UP.
    # (master_link_status flips to "up" once the initial sync completes.)
    for _ in range(20):
        if replica.info("replication").get("master_link_status") == "up":
            break
        time.sleep(0.25)

    print("--- 3. Confirm the replication link ---")
    info = master.info("replication")
    print(f"    master role: {info['role']}, connected_replicas: "
          f"{info['connected_slaves']}")
    rinfo = replica.info("replication")
    print(f"    replica role: {rinfo['role']}, link: {rinfo['master_link_status']}")

    print("--- 4. WRITE on the master only ---")
    master.set("product:42:price", "199")
    master.hset("user:7", mapping={"name": "Karim", "tier": "gold"})
    print("    wrote product:42:price and user:7 on the MASTER")

    # Give the async stream a moment to propagate (poll until it arrives).
    for _ in range(20):
        if replica.get("product:42:price") is not None:
            break
        time.sleep(0.1)

    print("--- 5. READ the same data from the REPLICA ---")
    print("    (replica) product:42:price =", replica.get("product:42:price"))
    print("    (replica) user:7           =", replica.hgetall("user:7"))

    print("--- 6. Prove the replica is READ-ONLY ---")
    try:
        replica.set("should:fail", "nope")
        print("    unexpected: write to replica succeeded")
    except redis.exceptions.ResponseError as e:
        # Replicas reject writes by default - reads go to replicas, writes to master.
        print(f"    write to replica correctly rejected: {str(e)[:50]}...")

    ok = replica.get("product:42:price") == "199"
    print("\n    RESULT:", "REPLICATION WORKS (replica has the data)" if ok
          else "replication failed")

    # --- Cleanup ---
    for p in (replica_proc, master_proc):
        p.terminate(); p.wait()
    shutil.rmtree(BASE, ignore_errors=True)

    print("\nTAKEAWAY:")
    print("  Point reads at replicas to scale; send writes to the master.")
    print("  Replication is async, so replicas can be a hair behind (eventual")
    print("  consistency). Next concept (Sentinel) uses replicas for failover.")


if __name__ == "__main__":
    main()
