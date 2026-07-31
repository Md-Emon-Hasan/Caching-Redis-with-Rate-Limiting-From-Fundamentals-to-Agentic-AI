"""
============================================================================
 PHASE 7 - CONCEPT 1: PERSISTENCE (RDB + AOF)
============================================================================

THE PROBLEM
-----------
Redis keeps data in RAM. RAM is wiped when the process restarts or the
machine reboots. Without persistence, every restart = total data loss. For a
pure cache that might be fine, but for sessions, queues, agent memory, and
checkpoints (Phases 3-6) it is a disaster.

Redis offers TWO persistence mechanisms. You should understand both.

RDB (Redis Database) - point-in-time SNAPSHOTS
----------------------------------------------
Periodically, Redis forks and writes the ENTIRE dataset to one compact file
(dump.rdb). Think of it as a photograph taken every few minutes.
    + tiny files, fast restarts, great for backups
    - you can LOSE the writes since the last snapshot (e.g. last 5 min)

AOF (Append Only File) - a LOG of every write
---------------------------------------------
Redis appends every write command to a log file. On restart it replays the
log to rebuild the exact state. Think of it as a security-camera recording.
    + far less data loss (can fsync every second, or every write)
    - bigger files, slightly slower writes, longer restarts

THE PRODUCTION ANSWER: USE BOTH
-------------------------------
Most production setups enable AOF (for durability) AND keep RDB (for fast
backups/restores). AOF gives you "lose at most ~1 second"; RDB gives you a
compact file you can copy off-box for disaster recovery (Concept 6).

THIS DEMO
---------
We start a Redis with AOF enabled, write data, restart the process, and prove
the data survived - something a non-persistent Redis could never do.
============================================================================
"""

import subprocess
import time
import os
import shutil

import redis

# --- A dedicated port + data directory so we don't touch your real Redis ---
PORT = 7101
DATA_DIR = "/tmp/phase7_persistence"


def start_redis_with_aof() -> subprocess.Popen:
    """
    Launch a Redis instance with persistence turned on.

    Key config flags (these are the ones you'd put in redis.conf):
      --appendonly yes         -> enable AOF (the write log)
      --appendfsync everysec   -> flush the log to disk once per second
                                  (the sweet spot: lose <= ~1s on a crash)
      --save "60 100"          -> also take an RDB snapshot if >=100 keys
                                  changed within 60 seconds
      --dir <path>             -> where dump.rdb and the AOF live
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    proc = subprocess.Popen(
        ["redis-server",
         "--port", str(PORT),
         "--dir", DATA_DIR,
         "--appendonly", "yes",
         "--appendfsync", "everysec",
         "--save", "60 100",
         "--daemonize", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1)  # give it a moment to boot
    return proc


def main():
    # Clean any leftovers from a previous run.
    shutil.rmtree(DATA_DIR, ignore_errors=True)

    print("--- 1. Start Redis WITH persistence (AOF + RDB) ---")
    proc = start_redis_with_aof()
    r = redis.Redis(port=PORT, decode_responses=True)

    print("--- 2. Write some important data ---")
    r.set("user:1:session", "logged-in")
    r.set("agent:checkpoint", "step-18-of-20")
    r.rpush("job:queue", "task-a", "task-b", "task-c")
    print("    wrote a session, a checkpoint, and a 3-item queue")

    print("--- 3. Force everything to disk right now ---")
    # BGSAVE writes an RDB snapshot in the background.
    r.bgsave()
    # BGREWRITEAOF compacts the AOF. Together these guarantee it's on disk.
    time.sleep(1)
    print("    files on disk:", os.listdir(DATA_DIR))

    print("--- 4. Simulate a crash: kill the Redis process ---")
    proc.terminate()
    proc.wait()
    print("    Redis process killed (RAM wiped)")

    print("--- 5. Restart Redis from the SAME data directory ---")
    proc = start_redis_with_aof()  # reads the AOF/RDB and rebuilds state
    r = redis.Redis(port=PORT, decode_responses=True)

    print("--- 6. Verify the data survived the restart ---")
    print("    user:1:session   =", r.get("user:1:session"))
    print("    agent:checkpoint =", r.get("agent:checkpoint"))
    print("    job:queue        =", r.lrange("job:queue", 0, -1))

    survived = (r.get("user:1:session") == "logged-in"
                and r.get("agent:checkpoint") == "step-18-of-20"
                and r.lrange("job:queue", 0, -1) == ["task-a", "task-b", "task-c"])
    print("\n    RESULT:", "DATA SURVIVED (persistence works!)" if survived
          else "DATA LOST")

    # --- Cleanup ---
    proc.terminate()
    proc.wait()
    shutil.rmtree(DATA_DIR, ignore_errors=True)

    print("\nTAKEAWAY:")
    print("  Without persistence, step 6 would return None for everything.")
    print("  AOF (everysec) = lose at most ~1s. RDB = compact backup file.")
    print("  Production: enable BOTH.")


if __name__ == "__main__":
    main()
