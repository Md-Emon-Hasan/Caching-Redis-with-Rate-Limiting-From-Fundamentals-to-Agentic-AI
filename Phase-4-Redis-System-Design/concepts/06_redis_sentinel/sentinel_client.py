"""
PHASE 4.6 — REDIS SENTINEL
--------------------------
Prerequisites: a master + at least 1 replica running (see the
05_redis_replication folder), plus at least one Sentinel process:
  redis-sentinel sentinel.conf
Then run:      python sentinel_client.py

Concept: Sentinel processes constantly watch the master. If enough
of them (the quorum) agree it's down, they automatically promote a
replica to be the new master — your app never hardcodes a host.
"""
from redis.sentinel import Sentinel

sentinel = Sentinel(
    [("127.0.0.1", 26379)],   # add more (26380, 26381...) for a real quorum
    socket_timeout=0.5
)

if __name__ == "__main__":
    try:
        # discover_master() asks Sentinel "who is master right now?"
        master = sentinel.master_for("mymaster", socket_timeout=0.5)
        replica = sentinel.slave_for("mymaster", socket_timeout=0.5)

        master.set("order:1001", "paid")
        print("Wrote via Sentinel-discovered master.")
        print("Read via Sentinel-discovered replica:", replica.get("order:1001"))

        print("\nTry this: kill the master process (Ctrl+C in its terminal), "
              "wait ~10s, then run this script again — Sentinel should have "
              "already promoted the replica, and this script keeps working "
              "without any code changes.")
    except Exception as e:
        print("Could not reach Sentinel. Make sure `redis-sentinel sentinel.conf` "
              "is running, and that a master/replica pair exists (see the "
              "05_redis_replication folder).")
        print("Error:", e)
