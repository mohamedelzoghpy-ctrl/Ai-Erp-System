#!/usr/bin/env bash
# Compressed PostgreSQL backup with retention.
#   ./deploy/backup.sh                       # production stack: dumps from the "db" container
#   BACKUP_PG_URL=postgresql://u:p@host:5432/db ./deploy/backup.sh   # any reachable PostgreSQL (needs pg_dump)
# Env: BACKUP_DIR (default ./backups), KEEP_DAYS (default 14), COMPOSE_FILE.
# Schedule daily with cron, e.g.:  0 2 * * * cd /opt/erp && ./deploy/backup.sh >> backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.prod.yml}"
mkdir -p "$BACKUP_DIR"
umask 077
out="$BACKUP_DIR/erp_$(date +%Y%m%d_%H%M%S).sql.gz"
tmp="$out.partial"
trap 'rm -f "$tmp"' EXIT

if [[ -n "${BACKUP_PG_URL:-}" ]]; then
  pg_dump --no-owner --no-privileges "$BACKUP_PG_URL" | gzip -9 > "$tmp"
else
  docker compose -f "$COMPOSE_FILE" exec -T db sh -c 'pg_dump -U erp --no-owner --no-privileges erp_db' | gzip -9 > "$tmp"
fi
gzip -t "$tmp"                                   # refuse to keep a corrupt archive
[[ "$(gzip -dc "$tmp" | head -c 200 | grep -c 'PostgreSQL database dump')" -ge 1 ]] || { echo "backup looks empty" >&2; exit 1; }
mv "$tmp" "$out"
find "$BACKUP_DIR" -name 'erp_*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "OK $out ($(du -h "$out" | cut -f1))"
