"""
============================================================================
 PHASE 7 - CONCEPT 5: MONITORING & OBSERVABILITY
============================================================================

"YOU CAN'T OPERATE WHAT YOU CAN'T SEE"
-------------------------------------
In production, Redis will eventually misbehave: memory fills up, the hit rate
drops, a slow command blocks everything, clients pile up. Monitoring is how
you SEE these problems - ideally before your users do.

Redis exposes everything you need through a few commands:
    INFO       -> hundreds of live metrics (memory, stats, clients, ...)
    SLOWLOG    -> a log of commands that took too long
    DBSIZE     -> how many keys exist
    CLIENT LIST-> who is connected

THE METRICS THAT ACTUALLY MATTER
--------------------------------
1. MEMORY        used_memory vs maxmemory. If you hit maxmemory, Redis starts
                 evicting (or rejecting writes). This is the #1 thing to watch.
2. HIT RATE      keyspace_hits / (hits + misses). A cache with a low hit rate
                 isn't earning its keep - investigate your TTLs and keys.
3. THROUGHPUT    instantaneous_ops_per_sec - your load right now.
4. CLIENTS       connected_clients - leaks or spikes show up here.
5. SLOW COMMANDS the SLOWLOG catches O(N) commands like KEYS that block Redis.
6. EVICTIONS     evicted_keys climbing = you're out of memory for your workload.

PRODUCTION TOOLING (beyond this script)
---------------------------------------
Teams usually export these metrics to Prometheus (via redis_exporter) and
graph them in Grafana, with alerts (e.g. "memory > 80%", "hit rate < 0.8").
The docker/ folder in this package includes a ready monitoring stack. This
script shows the raw signals those dashboards are built on.

THIS DEMO
---------
We start a Redis, generate some load (hits AND misses), then print a health
report computed from INFO - the same logic a real health check would run.
============================================================================
"""

import subprocess
import time
import os
import shutil

import redis

PORT = 7601
BASE = "/tmp/phase7_monitoring"


def start_redis():
    os.makedirs(BASE, exist_ok=True)
    # maxmemory + an eviction policy so we can observe memory behaviour.
    p = subprocess.Popen(
        ["redis-server", "--port", str(PORT), "--dir", BASE,
         "--maxmemory", "50mb", "--maxmemory-policy", "allkeys-lru",
         "--slowlog-log-slower-than", "0"],  # log ALL commands for the demo
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    return p


def generate_load(r):
    """Create realistic activity: writes, cache hits, and cache misses."""
    for i in range(1000):
        r.set(f"key:{i}", f"value-{i}")
    for i in range(2000):
        r.get(f"key:{i % 1500}")   # ~1000 hits, ~500 misses
    # A deliberately slow command so the SLOWLOG has something to show.
    r.keys("key:*")                # KEYS is O(N) - never use it in prod!


def health_report(r) -> dict:
    """Pull INFO and turn raw numbers into an operational health report."""
    info = r.info()

    used = info["used_memory"]
    maxmem = info.get("maxmemory") or 0
    mem_pct = (used / maxmem * 100) if maxmem else 0

    hits = info["keyspace_hits"]
    misses = info["keyspace_misses"]
    hit_rate = hits / (hits + misses) if (hits + misses) else 0

    return {
        "used_memory_mb": round(used / 1024 / 1024, 2),
        "maxmemory_mb": round(maxmem / 1024 / 1024, 2) if maxmem else "unlimited",
        "memory_used_pct": round(mem_pct, 1),
        "hit_rate": round(hit_rate, 3),
        "keyspace_hits": hits,
        "keyspace_misses": misses,
        "evicted_keys": info["evicted_keys"],
        "connected_clients": info["connected_clients"],
        "ops_per_sec": info["instantaneous_ops_per_sec"],
        "total_keys": r.dbsize(),
        "uptime_sec": info["uptime_in_seconds"],
    }


def check_alerts(report: dict) -> list[str]:
    """The rules a real alerting system would evaluate."""
    alerts = []
    if isinstance(report["memory_used_pct"], (int, float)) and report["memory_used_pct"] > 80:
        alerts.append(f"HIGH MEMORY: {report['memory_used_pct']}% of maxmemory used")
    if report["hit_rate"] < 0.8 and (report["keyspace_hits"] + report["keyspace_misses"]) > 100:
        alerts.append(f"LOW HIT RATE: {report['hit_rate']} (cache underperforming)")
    if report["evicted_keys"] > 0:
        alerts.append(f"EVICTIONS: {report['evicted_keys']} keys evicted (memory pressure)")
    return alerts


def main():
    shutil.rmtree(BASE, ignore_errors=True)
    proc = start_redis()
    r = redis.Redis(port=PORT, decode_responses=True)

    print("--- 1. Generate load (writes, hits, misses, a slow command) ---")
    generate_load(r)
    time.sleep(0.5)

    print("--- 2. Health report (computed from INFO) ---")
    report = health_report(r)
    for k, v in report.items():
        print(f"    {k:20}: {v}")

    print("\n--- 3. Alerts (what a monitoring system would fire) ---")
    alerts = check_alerts(report)
    if alerts:
        for a in alerts:
            print(f"    [ALERT] {a}")
    else:
        print("    no alerts - all metrics within healthy thresholds")

    print("\n--- 4. SLOWLOG: the slowest recent commands ---")

    def _fmt(cmd):
        # Depending on the client version, the command comes back as a string,
        # bytes, or a list of character codes - normalise all of them to text.
        if isinstance(cmd, bytes):
            return cmd.decode(errors="replace")
        if isinstance(cmd, str):
            return cmd
        parts = []
        for a in cmd:
            parts.append(chr(a) if isinstance(a, int) else
                         a.decode(errors="replace") if isinstance(a, bytes) else str(a))
        return "".join(parts)

    # Each entry has: id, start_time, duration (microseconds), command.
    for entry in r.slowlog_get(3):
        print(f"    {entry['duration']:>6} microsec  ->  {_fmt(entry['command'])[:40]}")
    print("    (watch for KEYS, FLUSHALL, big SORT, etc. - they block Redis)")

    # --- Cleanup ---
    proc.terminate(); proc.wait()
    shutil.rmtree(BASE, ignore_errors=True)

    print("\nTAKEAWAY:")
    print("  Watch: memory %, hit rate, ops/sec, clients, evictions, slowlog.")
    print("  Export these to Prometheus + Grafana and alert on thresholds.")
    print("  A cache you can't observe is a cache you can't trust.")


if __name__ == "__main__":
    main()
