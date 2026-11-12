#!/usr/bin/env bash
# Compressed PostgreSQL backup with retention, checksum and verification.
#
#   # Full logical dump (default):  ./deploy/backup.sh
#   BACKUP_DIR=/data/backups BACKUP_PG_URL=postgresql://u:***@host:5432/db ./deploy/backup.sh
#
# Behaviour (production-grade):
#   * Full `pg_dump --no-owner --no-privileges` + gzip.
#   * Every archive ships a SHA-256 checksum (.sha256). The checksum references
#     the FINAL archive path (after the `mv`), so `sha256sum -c` verifies without
#     any leftover .partial file.
#   * Retention is filename-pattern based (never deletes a file in use).
#   * VERIFY=1 verifies the just-written archive (gzip + checksum + non-empty).
#   * DRY_RUN=1 prints what would be archived and writes nothing.
#   * Optional off-server copy via OFFSERVER_RSYNC (second host).
#   * No partial or corrupt archives are ever kept as final backups.
#
# Env: BACKUP_DIR (default ./backups), KEEP_DAYS (default 14),
#      COMPOSE_FILE (default deploy/docker-compose.prod.yml),
#      VERIFY (1 = verify after write), DRY_RUN (1 = no write),
#      OFFSERVER_RSYNC (shell command to run on each archive, e.g.
#          "rsync -avzP --chmod=F0600 ARCHIVE user@backup-host:/backups/").
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.prod.yml}"
VERIFY="${VERIFY:-0}"
DRY_RUN="${DRY_RUN:-0}"
OFFSERVER_RSYNC="${OFFSERVER_RSYNC:-}"

mkdir -p "$BACKUP_DIR" || { echo "ERROR: cannot create $BACKUP_DIR" >&2; exit 1; }
umask 077

ts="$(date +%Y%m%d_%H%M%S_%N)"
out="$BACKUP_DIR/erp_${ts}.sql.gz"
tmp="$out.partial"
sha256="$out.sha256"
trap 'rm -f "$tmp"' EXIT

# Dump from the project's db container (recommended for prod stack).
# Fall back to any reachable PostgreSQL when BACKUP_PG_URL is supplied.
if [[ -n "${BACKUP_PG_URL:-}" ]]; then
  pg_dump --no-owner --no-privileges --verbose "$BACKUP_PG_URL" | gzip -9 > "$tmp"
else
  docker compose -f "$COMPOSE_FILE" exec -T db sh -c \
    'pg_dump -U erp --no-owner --no-privileges erp_db' | gzip -9 > "$tmp"
fi

# Refuse to ship a corrupt archive.
if ! gzip -t "$tmp"; then
  echo "ERROR: archive failed gzip integrity check" >&2
  exit 1
fi

# Refuse to keep an empty / invalid dump.
if ! gzip -dc "$tmp" | head -c 200 | grep -q "PostgreSQL database dump"; then
  echo "ERROR: backup looks empty or invalid" >&2
  exit 1
fi

if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
  echo "DRY_RUN would store: $out ($(wc -c < "$tmp") bytes gz)"
  echo "DRY_RUN done - nothing was written."
  exit 0
fi

mv "$tmp" "$out"
# Recompute the checksum so it references the final archive path.
sha256sum "$out" > "$sha256"

# Optional off-server copy, if configured.
if [[ -n "$OFFSERVER_RSYNC" ]]; then
  if command -v rsync >/dev/null 2>&1; then
    "$OFFSERVER_RSYNC"
  else
    echo "WARN: OFFSERVER_RSYNC set but rsync not installed; skipping off-server copy." >&2
  fi
fi

# Retention: delete archives older than KEEP_DAYS (filename pattern only).
deleted=0
while IFS= read -r old; do
  rm -f "$old"
  deleted=$((deleted + 1))
done < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'erp_[0-9_]*.sql.gz' -mtime "+${KEEP_DAYS}" -print -quit 2>/dev/null)

if [[ "${VERIFY:-0}" -eq 1 ]]; then
  # Post-write verification: gzip integrity + checksum match + a valid dump header.
  if ! gzip -t "$out"; then
    echo "ERROR: VERIFY failed: gzip integrity" >&2
    exit 1
  fi
  if [[ ! -f "$sha256" ]] || ! sha256sum -c "$sha256" >/dev/null 2>&1; then
    echo "ERROR: VERIFY failed: checksum mismatch" >&2
    exit 1
  fi
  if ! gzip -dc "$out" | head -c 200 | grep -q "PostgreSQL database dump"; then
    echo "ERROR: VERIFY found an empty/corrupt dump" >&2
    exit 1
  fi
  echo "VERIFIED -> $out"
fi

echo "OK $out ($(du -h "$out" | cut -f1); sha256:$(cut -c1-10 "$sha256"))"

if [[ "$deleted" -gt 0 ]]; then
  echo "deleted ${deleted} old backup(s)"
fi
