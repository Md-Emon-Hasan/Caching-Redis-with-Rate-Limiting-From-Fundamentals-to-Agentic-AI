#!/usr/bin/env bash
# ============================================================================
#  restore.sh - restore a Redis instance from a backup RDB file.
#  Concept 6 (disaster recovery). PRACTICE this regularly - an untested
#  backup is just a hope.
#
#  Usage:   ./restore.sh <backup.rdb> [data_dir] [port]
#  Example: ./restore.sh /var/backups/redis/dump-20260731-120000.rdb
# ============================================================================
set -euo pipefail

BACKUP_FILE="${1:?usage: restore.sh <backup.rdb> [data_dir] [port]}"
DATA_DIR="${2:-/var/lib/redis}"
PORT="${3:-6379}"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "[restore] ERROR: backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

echo "[restore] stopping any Redis on port $PORT ..."
redis-cli -p "$PORT" SHUTDOWN NOSAVE 2>/dev/null || true
sleep 1

echo "[restore] placing backup into $DATA_DIR/dump.rdb"
mkdir -p "$DATA_DIR"
cp "$BACKUP_FILE" "$DATA_DIR/dump.rdb"

echo "[restore] starting Redis (it loads dump.rdb on boot) ..."
redis-server --port "$PORT" --dir "$DATA_DIR" --dbfilename dump.rdb --daemonize yes
sleep 1

COUNT="$(redis-cli -p "$PORT" DBSIZE)"
echo "[restore] done. Redis on :$PORT now holds $COUNT keys."
echo "[restore] VERIFY a few known keys before declaring success!"
