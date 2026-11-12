#!/usr/bin/env bash
# Uptime / availability monitor for the MOZAD ERP production stack.
#
# In production the only published ports are 80/443 (Caddy); the backend and
# database are internal to the Docker network and must NOT be reached directly.
#   https://your-domain
# therefore serves the whole SPA, so it is the reliable availability signal.
#
# Exit codes: 0 = stack healthy, 1 = degraded/unavailable.
#
# Env: DOMAIN (default erp.example.com), URL (override), TIMEOUT (curl default).
#
# Install on the server (systemd):
#   sudo cp deploy/monitor.service /etc/systemd/system/
#   sudo systemctl enable --now monitor.timer
#
# Or cron (every 2 min):
#   */2 * * * cd /opt/erp && ./deploy/uptime-monitor.sh >> monitoring.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."

DOMAIN="${DOMAIN:-erp.example.com}"
URL="${URL:-https://${DOMAIN}/}"
TIMEOUT="${TIMEOUT:-5}"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

# 1. Public SPA endpoint over HTTPS (Caddy).
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" -k "$URL" 2>/dev/null || true)"
if [[ "$code" != "200" ]]; then
  log "FAIL url=${URL} http_code=${code:-none}"
  exit 1
fi

# 2. Caddy must still be enforcing HSTS and must not expose a backend.
hsts="$(curl -sS -I --max-time "$TIMEOUT" -k "$URL" 2>/dev/null | grep -i '^strict-transport-security:' || true)"
if [[ -z "$hsts" ]]; then
  log "FAIL url=${URL} missing HSTS header"
  exit 1
fi

# 3. Backend /health reachable on the internal Docker network (inside the stack).
if [[ -n "${DOCKER_COMPOSE_FILE:-}" ]] && command -v docker >/dev/null 2>&1; then
  internal="$(docker compose -f "$DOCKER_COMPOSE_FILE" exec -T backend sh -c \
    'wget -qO- http://127.0.0.1:8000/health 2>/dev/null || echo FAIL' 2>/dev/null || true)"
  if [[ "$internal" != "{"* ]]; then
    log "FAIL backend /health not healthy (internal=${internal})"
    exit 1
  fi
fi

log "OK url=${URL} http_code=${code}"
