"""
============================================================================
 PHASE 7 - CONCEPT 4: REDIS CLUSTER (Horizontal Scaling / Sharding)
============================================================================

WHEN REPLICATION ISN'T ENOUGH
-----------------------------
Replication scales READS (add replicas) but every node still holds the WHOLE
dataset, and all WRITES still go to one master. Two limits appear:
    - your data no longer fits in one machine's RAM, and/or
    - one master can't handle the write throughput.

REDIS CLUSTER = split the data across many masters (SHARDING)
------------------------------------------------------------
A cluster spreads your keys across multiple masters ("shards"). Each master
owns a slice of the data, so total capacity and write throughput grow as you
add shards. Each master can also have its own replica for HA.

HOW KEYS ARE ASSIGNED: HASH SLOTS
---------------------------------
The keyspace is divided into 16384 "hash slots". Each key maps to a slot via
    slot = CRC16(key) % 16384
and each master owns a RANGE of slots. So a key deterministically belongs to
exactly one shard. Example with 3 masters:

    Master A: slots     0 - 5460     ┐
    Master B: slots  5461 - 10922    ├─ every key lands in exactly one
    Master C: slots 10923 - 16383    ┘

When a client asks the "wrong" node for a key, the node replies with a
redirect (MOVED) telling it which node actually owns that slot. A cluster-aware
client caches this map so it usually talks straight to the right node.

MULTI-KEY OPERATIONS & HASH TAGS
--------------------------------
Because keys live on different shards, a command touching multiple keys only
works if they're on the SAME shard. To force related keys onto one shard, wrap
the shared part in curly braces - a "hash tag":
    user:{123}:profile  and  user:{123}:orders   -> same slot (only {123} is hashed)

THIS DEMO
---------
We create a real 3-master + 3-replica cluster, write many keys, and show they
distribute across the shards - proving horizontal scaling works.
============================================================================
"""

import subprocess
import time
import os
import shutil

from redis.cluster import RedisCluster, ClusterNode

# 6 nodes: 3 masters + 3 replicas (the recommended minimum for a real cluster)
PORTS = [7501, 7502, 7503, 7504, 7505, 7506]
BASE = "/tmp/phase7_cluster"


def start_cluster_node(port):
    """
    Start a Redis in CLUSTER mode.
      --cluster-enabled yes         -> this node participates in a cluster
      --cluster-config-file ...     -> where the node records cluster topology
      --cluster-node-timeout 5000   -> ms before a node is considered failing
    """
    data_dir = f"{BASE}/{port}"
    os.makedirs(data_dir, exist_ok=True)
    p = subprocess.Popen(
        ["redis-server", "--port", str(port), "--dir", data_dir,
         "--cluster-enabled", "yes",
         "--cluster-config-file", f"nodes-{port}.conf",
         "--cluster-node-timeout", "5000",
         "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


def main():
    shutil.rmtree(BASE, ignore_errors=True)

    print("--- 1. Start 6 nodes in cluster mode ---")
    procs = [start_cluster_node(p) for p in PORTS]
    time.sleep(2)

    print("--- 2. Form the cluster (3 masters, each with 1 replica) ---")
    # redis-cli --cluster create wires the nodes together and assigns the
    # 16384 hash slots across the 3 masters. --cluster-replicas 1 means each
    # master gets one replica (so 6 nodes = 3 shards, each HA).
    addrs = [f"127.0.0.1:{p}" for p in PORTS]
    result = subprocess.run(
        ["redis-cli", "--cluster", "create", *addrs,
         "--cluster-replicas", "1", "--cluster-yes"],
        capture_output=True, text=True)
    ok = "[OK] All 16384 slots covered" in result.stdout
    print("    cluster created:", "YES" if ok else "check output")
    time.sleep(2)

    print("--- 3. Connect a cluster-aware client and inspect the shards ---")
    rc = RedisCluster(startup_nodes=[ClusterNode("127.0.0.1", PORTS[0])],
                      decode_responses=True)
    # Show which masters exist and the slot range each one owns.
    masters = [n for n in rc.get_nodes() if n.server_type == "primary"]
    print(f"    the cluster has {len(masters)} master shards")

    print("--- 4. Write 12 keys and see them spread across shards ---")
    for i in range(12):
        rc.set(f"key:{i}", f"value-{i}")

    # Ask each master how many keys it holds - the data is DISTRIBUTED.
    print("    key distribution across shards:")
    total = 0
    for m in masters:
        node_client = rc.get_redis_connection(m)
        count = node_client.dbsize()
        total += count
        print(f"      master {m.host}:{m.port}  ->  {count} keys")
    print(f"    total keys stored across the cluster: {total}")

    print("--- 5. Hash tags: force related keys onto the SAME shard ---")
    # Only the text inside {} is hashed, so these three share a slot.
    rc.set("cart:{user42}:items", "3")
    rc.set("cart:{user42}:total", "150")
    rc.set("cart:{user42}:coupon", "SAVE10")
    slot = rc.keyslot("cart:{user42}:items")
    print(f"    all three cart:{{user42}}:* keys map to slot {slot} (same shard)")
    print("    -> multi-key ops on this user's cart are now possible")

    ok_final = total == 12
    print("\n    RESULT:", "CLUSTER WORKS (data sharded across masters)"
          if ok_final else "unexpected key count")

    # --- Cleanup ---
    rc.close()
    for p in procs:
        p.terminate(); p.wait()
    shutil.rmtree(BASE, ignore_errors=True)

    print("\nTAKEAWAY:")
    print("  Cluster = shard data across many masters to scale writes + memory.")
    print("  Keys map to 1 of 16384 slots via CRC16; each master owns a range.")
    print("  Use {hash tags} to keep related keys on one shard for multi-key ops.")


if __name__ == "__main__":
    main()
