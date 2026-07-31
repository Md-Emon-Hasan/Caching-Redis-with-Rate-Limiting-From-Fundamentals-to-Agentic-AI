"""
PHASE 4.5 — REDIS REPLICATION
-----------------------------
Prerequisites (2 terminals, from this folder):
  Terminal 1: redis-server redis-master.conf
  Terminal 2: redis-server redis-replica.conf
Then run:      python replication_client.py

Concept: the MASTER accepts all writes; REPLICAS keep an almost
real-time copy and can serve read traffic, spreading load out.
"""
import time
import redis

master = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
replica = redis.Redis(host="127.0.0.1", port=6380, decode_responses=True)


def write_data(key, value):
    master.set(key, value)      # ALL writes go to the master, always


def read_data(key):
    value = replica.get(key)    # reads are offloaded to the replica
    if value is None:
        # rare edge case: replica hasn't caught up yet (replication lag)
        value = master.get(key)
    return value


if __name__ == "__main__":
    try:
        master.ping()
        replica.ping()
    except redis.exceptions.ConnectionError:
        print("Could not reach both nodes. Start them first:\n"
              "  redis-server redis-master.conf\n"
              "  redis-server redis-replica.conf")
        raise SystemExit(1)

    print("Writing to MASTER...")
    write_data("order:1001", "paid")

    time.sleep(0.1)  # give replication a brief moment to propagate

    print("Reading from REPLICA:", read_data("order:1001"))
    print("\nCheck info replication on each node with:")
    print("  redis-cli -p 6379 info replication   # should show role:master")
    print("  redis-cli -p 6380 info replication   # should show role:slave")
