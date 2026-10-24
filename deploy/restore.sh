#!/usr/bin/env bash
# Restore a backup made by backup.sh. DESTRUCTIVE: replaces the contents of the target database.
#   ./deploy/restore.sh backups/erp_20261024_020000.sql.gz            # production stack
#   RESTORE_PG_URL=postgresql://u:p@host:5432/db ./deploy/restore.sh FILE   # any reachable PostgreSQL (needs psql)
# Stop the backend first so nothing writes during the restore:  docker compose -f deploy/docker-compose.prod.yml stop backend
set -euo pipefail
cd "$(dirname "$0")/.."
file="${1:?usage: restore.sh BACKUP.sql.gz}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.prod.yml}"
[[ -f "$file" ]] || { echo "no such file: $file" >&2; exit 1; }
gzip -t "$file"
if [[ "${CONFIRM:-}" != "yes" ]]; then
  read -r -p "This will ERASE the target database and load $file. Type 'yes' to continue: " a
  [[ "$a" == "yes" ]] || { echo "aborted"; exit 1; }
fi
reset_sql='DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
if [[ -n "${RESTORE_PG_URL:-}" ]]; then
  psql -v ON_ERROR_STOP=1 -q "$RESTORE_PG_URL" -c "$reset_sql"
  gzip -dc "$file" | psql -v ON_ERROR_STOP=1 -q "$RESTORE_PG_URL" >/dev/null
else
  docker compose -f "$COMPOSE_FILE" exec -T db psql -v ON_ERROR_STOP=1 -q -U erp -d erp_db -c "$reset_sql"
  gzip -dc "$file" | docker compose -f "$COMPOSE_FILE" exec -T db psql -v ON_ERROR_STOP=1 -q -U erp -d erp_db >/dev/null
fi
echo "Restored $file. Start the backend again (it applies pending migrations on boot)."
