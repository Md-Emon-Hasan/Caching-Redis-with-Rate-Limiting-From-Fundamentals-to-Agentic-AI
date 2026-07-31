#!/usr/bin/env bash
# ============================================================================
#  healthcheck.sh - quick operational snapshot of a Redis instance.
#  A lightweight, dependency-free version of Concept 5's health report,
#  handy for a terminal check or a load-balancer probe.
#
#  Usage:  ./healthcheck.sh [host] [port]
#  Exit code 0 = healthy, 1 = a threshold was breached (useful in monitoring).
# ============================================================================
set -uo pipefail

HOST="${1:-127.0.0.1}"
PORT="${2:-6379}"
CLI="redis-cli -h $HOST -p $PORT"

# Is it even up?
if ! $CLI PING >/dev/null 2>&1; then
  echo "DOWN: cannot reach Redis at $HOST:$PORT"
  exit 1
fi

info() { $CLI INFO "$1"; }

# Pull the metrics that matter.
USED=$(info memory | awk -F: '/used_memory:/{print $2}' | tr -d '\r')
MAXMEM=$(info memory | awk -F: '/maxmemory:/{print $2}' | tr -d '\r')
HITS=$(info stats | awk -F: '/keyspace_hits:/{print $2}' | tr -d '\r')
MISSES=$(info stats | awk -F: '/keyspace_misses:/{print $2}' | tr -d '\r')
EVICTED=$(info stats | awk -F: '/evicted_keys:/{print $2}' | tr -d '\r')
CLIENTS=$(info clients | awk -F: '/connected_clients:/{print $2}' | tr -d '\r')
OPS=$(info stats | awk -F: '/instantaneous_ops_per_sec:/{print $2}' | tr -d '\r')

echo "Redis $HOST:$PORT  -  UP"
echo "  memory used     : $((USED / 1024 / 1024)) MB"
[ "${MAXMEM:-0}" -gt 0 ] && echo "  memory limit    : $((MAXMEM / 1024 / 1024)) MB"
echo "  connected clients: $CLIENTS"
echo "  ops/sec         : $OPS"
echo "  evicted keys    : $EVICTED"

# Hit rate (guard against divide-by-zero).
TOTAL=$((HITS + MISSES))
if [ "$TOTAL" -gt 0 ]; then
  RATE=$(awk "BEGIN{printf \"%.3f\", $HITS/$TOTAL}")
  echo "  hit rate        : $RATE"
fi

# --- Threshold checks (exit non-zero if breached) ---
STATUS=0
if [ "${MAXMEM:-0}" -gt 0 ]; then
  PCT=$((USED * 100 / MAXMEM))
  if [ "$PCT" -gt 80 ]; then
    echo "  [WARN] memory at ${PCT}% of limit"; STATUS=1
  fi
fi
if [ "${EVICTED:-0}" -gt 0 ]; then
  echo "  [WARN] keys are being evicted (memory pressure)"; STATUS=1
fi

exit $STATUS
