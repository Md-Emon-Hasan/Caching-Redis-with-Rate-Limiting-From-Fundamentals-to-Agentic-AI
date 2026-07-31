"""
PHASE 4.7 — REDIS CLUSTER
-------------------------
Prerequisites: a running Redis Cluster. Quickest way to try one locally
(needs 6 free ports, 7000-7005), from 6 separate terminals:
  redis-server --port 7000 --cluster-enabled yes --cluster-config-file nodes-7000.conf --daemonize no
  redis-server --port 7001 --cluster-enabled yes --cluster-config-file nodes-7001.conf --daemonize no
  ... repeat for 7002-7005 ...
Then, from any terminal, create the cluster:
  redis-cli --cluster create \
    127.0.0.1:7000 127.0.0.1:7001 127.0.0.1:7002 \
    127.0.0.1:7003 127.0.0.1:7004 127.0.0.1:7005 \
    --cluster-replicas 1
Then run:      python cluster_client.py

Concept: data is SHARDED across masters using 16384 hash slots. Each
key hashes to exactly one slot, and that slot lives on one specific
master — so WRITES scale horizontally too, not just reads.
"""
from redis.cluster import RedisCluster

if __name__ == "__main__":
    try:
        rc = RedisCluster(host="127.0.0.1", port=7000, decode_responses=True)

        rc.set("user:1", "Alice")   # client auto-routes to the correct node
        rc.set("user:2", "Bob")     # might land on a completely different node

        print("user:1 ->", rc.get("user:1"))
        print("user:2 ->", rc.get("user:2"))

        # Use {hashtags} to force related keys onto the SAME slot/node —
        # required if you want to pipeline / MULTI-EXEC across them together.
        rc.set("cart:{user:1}:items", "sword,shield")
        rc.set("cart:{user:1}:total", "150")
        print("cart items ->", rc.get("cart:{user:1}:items"))
        print("cart total ->", rc.get("cart:{user:1}:total"))

        print("\nRun `redis-cli --cluster check 127.0.0.1:7000` to see which "
              "master node owns which key's slot.")
    except Exception as e:
        print("Could not reach the cluster. Follow the setup steps in the "
              "docstring at the top of this file first.")
        print("Error:", e)
