#!/usr/bin/env bash
# Phase 12.1: nightly Postgres backup with rotation.
# Run via host crontab — `pg_dump` lives inside the postgres container and we
# avoid mounting docker.sock into the celery worker.
#
# Install:
#   chmod +x /opt/quant/scripts/backup_db.sh
#   (crontab -l 2>/dev/null; echo '0 3 * * * /opt/quant/scripts/backup_db.sh >> /opt/quant/backups/cron.log 2>&1') | crontab -
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/opt/quant/backups}
RETENTION_DAYS=${RETENTION_DAYS:-14}
CONTAINER=${CONTAINER:-quant-postgres-1}
DB_USER=${DB_USER:-quant}
DB_NAME=${DB_NAME:-quant}

mkdir -p "$BACKUP_DIR"

TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$BACKUP_DIR/quant_${TS}.sql.gz"
TMP="$BACKUP_DIR/.quant_${TS}.sql.gz.partial"

echo "[$(date -u +%FT%TZ)] backup start -> $OUT"

# Stream pg_dump through gzip; if either side fails, scrub the partial file
trap 'rm -f "$TMP"' EXIT
if docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-privileges \
   | gzip -9 > "$TMP"; then
    mv "$TMP" "$OUT"
    SIZE=$(stat -c %s "$OUT" 2>/dev/null || echo 0)
    echo "[$(date -u +%FT%TZ)] backup ok size=${SIZE}B path=$OUT"
else
    echo "[$(date -u +%FT%TZ)] backup FAILED"
    exit 1
fi
trap - EXIT

# Rotate — drop *.sql.gz older than RETENTION_DAYS
find "$BACKUP_DIR" -maxdepth 1 -name 'quant_*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -print -delete \
    | while read -r p; do echo "[$(date -u +%FT%TZ)] rotated $p"; done

echo "[$(date -u +%FT%TZ)] backup done"
