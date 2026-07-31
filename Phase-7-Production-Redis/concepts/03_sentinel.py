"""
============================================================================
 PHASE 7 - CONCEPT 3: SENTINEL (High Availability & Automatic Failover)
============================================================================

THE PROBLEM REPLICATION ALONE DOESN'T SOLVE
-------------------------------------------
Concept 2 gave us replicas with copies of the data. But if the MASTER dies,
who promotes a replica to be the new master? Who tells your app the new
address? Doing this by hand at 3am is how outages become disasters.

REDIS SENTINEL = automatic supervision
--------------------------------------
Sentinel is a separate process whose whole job is to watch your master and
replicas and, when the master fails, AUTOMATICALLY:
    1. detect the failure,
    2. elect a replica to promote,
    3. reconfigure the other replicas to follow the new master,
    4. tell clients the new master's address.

You run an ODD number of sentinels (usually 3) on separate machines so they
can vote. A "quorum" (e.g. 2 of 3) must agree the master is down before a
failover starts - this prevents one confused sentinel from causing chaos.

    Sentinel 1 ─┐
    Sentinel 2 ─┼─ watch ─► MASTER ─► REPLICA(s)
    Sentinel 3 ─┘           (dies)     (one gets promoted)

HOW YOUR APP USES IT
--------------------
Instead of hard-coding the master's address, your client ASKS a sentinel
"who is the master right now?" (SENTINEL get-master-addr-by-name). After a
failover, the sentinel returns the NEW address automatically - your app keeps
working with no manual change.

THIS DEMO
---------
We start a master, a replica, and 3 sentinels with quorum 2. Then we KILL the
master and watch the sentinels promote the replica to master all by themselves.
============================================================================
"""

import subprocess
import time
import os
import shutil

import redis

MASTER_PORT = 7301
REPLICA_PORT = 7302
SENTINEL_PORTS = [7401, 7402, 7403]
MASTER_NAME = "mymaster"
BASE = "/tmp/phase7_sentinel"


def start_node(port, replicaof=None):
    data_dir = f"{BASE}/{port}"
    os.makedirs(data_dir, exist_ok=True)
    args = ["redis-server", "--port", str(port), "--dir", data_dir]
    if replicaof:
        args += ["--replicaof", replicaof[0], str(replicaof[1])]
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    return p


def start_sentinel(port):
    """
    Write a minimal sentinel.conf and launch a sentinel.

    The key directive:
      sentinel monitor <name> <ip> <port> <quorum>
    means: watch the master called <name> at <ip:port>; <quorum> sentinels
    must agree it's down to trigger a failover.

    The down-after / failover-timeout values are set LOW here so the demo
    fails over in a few seconds (production values are higher).
    """
    data_dir = f"{BASE}/sentinel-{port}"
    os.makedirs(data_dir, exist_ok=True)
    conf = f"{data_dir}/sentinel.conf"
    with open(conf, "w") as f:
        f.write(f"port {port}\n")
        f.write(f"dir {data_dir}\n")
        f.write(f"sentinel monitor {MASTER_NAME} 127.0.0.1 {MASTER_PORT} 2\n")
        f.write(f"sentinel down-after-milliseconds {MASTER_NAME} 2000\n")
        f.write(f"sentinel failover-timeout {MASTER_NAME} 6000\n")
        f.write(f"sentinel parallel-syncs {MASTER_NAME} 1\n")
    p = subprocess.Popen(["redis-server", conf, "--sentinel"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    return p


def ask_sentinel_for_master(sentinel_port):
    """This is exactly what a real client does to find the current master."""
    s = redis.Redis(port=sentinel_port, decode_responses=True)
    host, port = s.sentinel_get_master_addr_by_name(MASTER_NAME)
    return host, int(port)


def main():
    shutil.rmtree(BASE, ignore_errors=True)
    procs = []

    print("--- 1. Start master + replica + 3 sentinels (quorum 2) ---")
    procs.append(start_node(MASTER_PORT))
    procs.append(start_node(REPLICA_PORT, replicaof=("127.0.0.1", MASTER_PORT)))
    time.sleep(1)
    sentinels = [start_sentinel(p) for p in SENTINEL_PORTS]
    procs.extend(sentinels)
    time.sleep(2)

    print("--- 2. Write data to the master ---")
    master = redis.Redis(port=MASTER_PORT, decode_responses=True)
    master.set("critical:data", "must-survive-failover")
    time.sleep(1)  # let it replicate

    print("--- 3. Ask a sentinel: who is the master? ---")
    host, port = ask_sentinel_for_master(SENTINEL_PORTS[0])
    print(f"    sentinel says master is at {host}:{port}  (should be {MASTER_PORT})")

    print("--- 4. KILL THE MASTER (simulate a hardware failure) ---")
    procs[0].terminate()
    procs[0].wait()
    print("    master process killed. Sentinels should now notice and fail over...")

    print("--- 5. Wait for the sentinels to promote the replica ---")
    new_host, new_port = host, port
    for i in range(30):
        time.sleep(1)
        try:
            new_host, new_port = ask_sentinel_for_master(SENTINEL_PORTS[0])
        except Exception:
            continue
        if new_port != MASTER_PORT:
            print(f"    FAILOVER COMPLETE after ~{i+1}s: "
                  f"new master is {new_host}:{new_port}")
            break
        print(f"    ...still {new_port} (waiting) [{i+1}s]")

    print("--- 6. Verify the new master has our data and accepts writes ---")
    if new_port != MASTER_PORT:
        new_master = redis.Redis(port=new_port, decode_responses=True)
        print("    critical:data on new master =", new_master.get("critical:data"))
        new_master.set("written:after:failover", "yes")  # was read-only replica
        print("    new master now accepts writes:",
              new_master.get("written:after:failover"))
        print("\n    RESULT: AUTOMATIC FAILOVER WORKED - zero manual action")
    else:
        print("\n    RESULT: failover did not complete in time (try again)")

    # --- Cleanup ---
    for p in procs[1:]:      # procs[0] (master) already dead
        p.terminate(); p.wait()
    shutil.rmtree(BASE, ignore_errors=True)

    print("\nTAKEAWAY:")
    print("  Replication gives you copies; SENTINEL gives you self-healing.")
    print("  Clients ask a sentinel for the current master, so failover is")
    print("  transparent. Use 3+ sentinels on separate hosts with a quorum.")


if __name__ == "__main__":
    main()
