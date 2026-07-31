#!/usr/bin/env bash
# ============================================================================
#  backup.sh - take a consistent Redis snapshot and copy it off-box.
#  Concept 6 (disaster recovery) as a real, cron-able script.
#
#  Usage:   ./backup.sh [host] [port] [backup_dir]
#  Cron:    0 * * * * /path/to/backup.sh   # hourly
# ============================================================================
set -euo pipefail

HOST="${1:-127.0.0.1}"
PORT="${2:-6379}"
BACKUP_DIR="${3:-/var/backups/redis}"     # in prod, sync this to S3/GCS
KEEP=24                                    # keep the last 24 backups

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/dump-$STAMP.rdb"

echo "[backup] triggering BGSAVE on $HOST:$PORT ..."
# Record the last save time, trigger a background save, and WAIT for it to
# finish (lastsave timestamp changes) so we copy a complete file.
BEFORE="$(redis-cli -h "$HOST" -p "$PORT" LASTSAVE)"
redis-cli -h "$HOST" -p "$PORT" BGSAVE >/dev/null
while [ "$(redis-cli -h "$HOST" -p "$PORT" LASTSAVE)" = "$BEFORE" ]; do
  sleep 1
done

# Find the live dump.rdb via the server's configured dir + dbfilename.
DIR="$(redis-cli -h "$HOST" -p "$PORT" CONFIG GET dir | tail -1)"
FILE="$(redis-cli -h "$HOST" -p "$PORT" CONFIG GET dbfilename | tail -1)"

echo "[backup] copying $DIR/$FILE -> $DEST"
cp "$DIR/$FILE" "$DEST"

# Retention: delete all but the newest $KEEP backups.
echo "[backup] pruning old backups (keeping last $KEEP)"
ls -1t "$BACKUP_DIR"/dump-*.rdb | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "[backup] done: $DEST ($(du -h "$DEST" | cut -f1))"
# In production, add here:  aws s3 cp "$DEST" s3://my-bucket/redis/
