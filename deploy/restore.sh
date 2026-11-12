#!/usr/bin/env bash
# Restore a backup made by backup.sh. DESTRUCTIVE: replaces the target database.
#
#   # Restore into the project's prod db (safe, interactive):
#   ./deploy/restore.sh backups/erp_20261024_020000.sql.gz
#   # Or restore into ANY reachable PostgreSQL (needs psql):
#   RESTORE_PG_URL=postgresql://u:***@host:5432/db ./deploy/restore.sh FILE
#   # Optional non-interactive run (set CONFIRM=yes first):
#   CONFIRM=yes ./deploy/restore.sh backup.sql.gz
#
# Important:
#   Stop the backend first so nothing writes during the restore:
#     docker compose -f deploy/docker-compose.prod.yml stop backend
#   Always have a verified off-server backup before starting a restore.
#
# Env: CONFIRM (1 = skip the interactive prompt), COMPOSE_FILE,
#      RESTORE_PG_URL, VERIFY (1 = checksum verify the archive first).
set -euo pipefail

cd "$(dirname "$0")/.."

file="${1:?usage: restore.sh BACKUP.sql.gz}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.prod.yml}"
VERIFY="${VERIFY:-0}"
CONFIRM="${CONFIRM:-}"

[[ -f "$file" ]] || { echo "ERROR: no such file: $file" >&2; exit 1; }
[[ -r "$file" ]] || { echo "ERROR: not readable: $file" >&2; exit 1; }

# Refuse to run an unreadable / mismatched checksum if VERIFY is on.
if [[ "$VERIFY" -eq 1 ]] && [[ -f "${file}.sha256" ]]; then
  if ! sha256sum -c "${file}.sha256" >/dev/null 2>&1; then
    echo "ERROR: VERIFY failed: checksum mismatch for $file" >&2
    exit 1
  fi
  echo "checksum OK: $file"
fi

gzip -t "$file" || { echo "ERROR: not a valid gzip archive: $file" >&2; exit 1; }

if [[ "${CONFIRM:-}" != "yes" ]]; then
  read -r -p "This will ERASE the target database and load $file. Type 'yes' to continue: " a
  [[ "$a" == "yes" ]] || { echo "aborted"; exit 1; }
fi

reset_sql='DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
if [[ -n "${RESTORE_PG_URL:-}" ]]; then
  # shellcheck disable=SC2086
  psql -v ON_ERROR_STOP=1 -q "$RESTORE_PG_URL" -c "$reset_sql"
  # shellcheck disable=SC2086
  gzip -dc "$file" | psql -v ON_ERROR_STOP=1 -q "$RESTORE_PG_URL" >/dev/null
else
  docker compose -f "$COMPOSE_FILE" exec -T db psql -v ON_ERROR_STOP=1 -q -U erp -d erp_db -c "$reset_sql"
  gzip -dc "$file" | docker compose -f "$COMPOSE_FILE" exec -T db psql -v ON_ERROR_STOP=1 -q -U erp -d erp_db >/dev/null
fi

tables="$(
  docker compose -f "$COMPOSE_FILE" exec -T db psql -t -A -U erp -d erp_db -c \
    "SELECT COUNT(*) FROM pg_class WHERE relkind='r' AND relpersistence='p';" | tr -d ' '
)"
echo "Restored $file -> $(wc -l < "$file") lines, ~${tables} tables."
echo "Start the backend again (it applies pending migrations on boot)."
