"""
============================================================================
 PHASE 7 - CONCEPT 6: DISASTER RECOVERY (Backup & Restore)
============================================================================

WHAT "DISASTER" MEANS HERE
--------------------------
Persistence (Concept 1) protects you from a process restart. Replication and
Sentinel (Concepts 2-3) protect you from a single node dying. But some
disasters take out EVERYTHING at once:
    - a whole data center / cloud region goes down,
    - a bad deploy runs FLUSHALL and deletes all keys,
    - ransomware or a corrupted volume.

For these you need BACKUPS stored somewhere separate from the live system,
and a tested procedure to RESTORE from them.

THE BACKUP: it's just the RDB file
----------------------------------
Redis's RDB snapshot (dump.rdb) IS your backup - a single compact file
containing the entire dataset at a point in time. The recipe is:
    1. trigger a fresh snapshot with BGSAVE,
    2. copy the resulting dump.rdb to safe, OFF-BOX storage
       (S3 / GCS / another region) on a schedule (e.g. hourly),
    3. keep several generations (so you can roll back past a bad write).

THE RESTORE: drop the file in and start
---------------------------------------
To recover, you place a backed-up dump.rdb into a fresh Redis's data dir and
start it - Redis loads the file on boot and the data is back.

THE GOLDEN RULE
---------------
A backup you have never restored is not a backup - it's a hope. Practice the
restore regularly so it works when you're under pressure.

THIS DEMO
---------
We fill a Redis, back up its RDB to a separate "off-site" folder, simulate a
total loss, then restore into a BRAND NEW Redis from the backup and verify.
============================================================================
"""

import subprocess
import time
import os
import shutil

import redis

PRIMARY_PORT = 7701
RESTORE_PORT = 7702
PRIMARY_DIR = "/tmp/phase7_dr/primary"
RESTORE_DIR = "/tmp/phase7_dr/restored"
BACKUP_DIR = "/tmp/phase7_dr/offsite_backups"   # "another region / S3"


def start_redis(port, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    p = subprocess.Popen(
        ["redis-server", "--port", str(port), "--dir", data_dir,
         "--dbfilename", "dump.rdb"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    return p


def take_backup(r, source_dir, backup_dir) -> str:
    """
    Create a consistent snapshot and copy it to off-site storage.
    Returns the path of the backup file.
    """
    # LASTSAVE returns the timestamp of the last successful save. We watch it
    # change so we KNOW the BGSAVE finished before we copy the file.
    before = r.lastsave()
    r.bgsave()
    while r.lastsave() == before:      # wait for the background save to complete
        time.sleep(0.1)

    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = f"{backup_dir}/dump-{stamp}.rdb"
    # In real life this copy targets S3/GCS in a DIFFERENT region.
    shutil.copy(f"{source_dir}/dump.rdb", backup_path)
    return backup_path


def main():
    shutil.rmtree("/tmp/phase7_dr", ignore_errors=True)

    print("--- 1. Start the PRIMARY and load important data ---")
    primary_proc = start_redis(PRIMARY_PORT, PRIMARY_DIR)
    primary = redis.Redis(port=PRIMARY_PORT, decode_responses=True)
    for i in range(500):
        primary.set(f"order:{i}", f"amount-{i * 10}")
    primary.set("config:critical", "do-not-lose-me")
    print(f"    loaded {primary.dbsize()} keys")

    print("--- 2. Take a backup and copy it OFF-SITE ---")
    backup_path = take_backup(primary, PRIMARY_DIR, BACKUP_DIR)
    size_kb = round(os.path.getsize(backup_path) / 1024, 1)
    print(f"    backup saved off-site: {backup_path} ({size_kb} KB)")

    print("--- 3. DISASTER: the entire primary is destroyed ---")
    primary_proc.terminate(); primary_proc.wait()
    shutil.rmtree(PRIMARY_DIR, ignore_errors=True)   # data dir gone too
    print("    primary process AND its data directory are gone")

    print("--- 4. RESTORE into a brand-new Redis from the off-site backup ---")
    os.makedirs(RESTORE_DIR, exist_ok=True)
    # The restore = put the backup file where the new Redis will look for it.
    shutil.copy(backup_path, f"{RESTORE_DIR}/dump.rdb")
    restore_proc = start_redis(RESTORE_PORT, RESTORE_DIR)  # loads dump.rdb on boot
    restored = redis.Redis(port=RESTORE_PORT, decode_responses=True)

    print("--- 5. Verify the recovered data ---")
    print(f"    restored key count: {restored.dbsize()} (expected 501)")
    print(f"    config:critical   = {restored.get('config:critical')}")
    print(f"    order:42          = {restored.get('order:42')}")

    ok = (restored.dbsize() == 501
          and restored.get("config:critical") == "do-not-lose-me")
    print("\n    RESULT:", "DISASTER RECOVERY SUCCESSFUL" if ok else "restore incomplete")

    # --- Cleanup ---
    restore_proc.terminate(); restore_proc.wait()
    shutil.rmtree("/tmp/phase7_dr", ignore_errors=True)

    print("\nTAKEAWAY:")
    print("  Your RDB file IS your backup. Copy it off-box on a schedule and")
    print("  keep several generations. Then PRACTICE the restore - an untested")
    print("  backup is just a hope.")


if __name__ == "__main__":
    main()
