# Production deployment

Stack: **Caddy** (HTTPS, certificates renewed automatically) → **frontend** (nginx, SPA + `/api` proxy) → **backend** → **PostgreSQL**.
Only ports 80/443 are published; the database and the API are reachable inside the Docker network only.

## 1. Prepare
1. A server with Docker + the compose plugin, and a DNS record for your domain pointing at it. Ports 80 and 443 must be open.
2. `cp deploy/.env.prod.example .env` and fill in `DOMAIN`, `ACME_EMAIL`, `POSTGRES_PASSWORD`, `SECRET_KEY` (long random), company details.

## 2. Start
```bash
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build
```
Open `https://your-domain`, create the first admin account on the setup screen. Migrations run automatically at backend start.

## 3. Backups (do this before storing real data)
```bash
./deploy/backup.sh                 # writes backups/erp_YYYYmmdd_HHMMSS.sql.gz, keeps 14 days (KEEP_DAYS)
# daily at 02:00:
# 0 2 * * * cd /opt/erp && ./deploy/backup.sh >> backups/backup.log 2>&1
```
Copy the `backups/` folder off the server regularly (another machine or object storage) — a backup on the same disk does not survive disk loss.

Restore (replaces the database contents):
```bash
docker compose -f deploy/docker-compose.prod.yml stop backend
./deploy/restore.sh backups/erp_20261024_020000.sql.gz
docker compose -f deploy/docker-compose.prod.yml start backend
```
**Test a restore on a spare machine at least once.** The scripts were verified against a real PostgreSQL 16 (backup → restore into a new database → identical data), but the Docker/Caddy path itself was not run in the build environment.

## 4. Checklist
- [ ] `SECRET_KEY` and `POSTGRES_PASSWORD` are long and random; `.env` is not committed and is readable only by you (`chmod 600 .env`).
- [ ] `ENABLE_DOCS=false` (already set in the prod compose file).
- [ ] Login brute-force limiting is on (10 failures / 15 min per IP + username). It is in-memory, so keep a single backend worker (the default).
- [ ] Firewall allows only 22, 80, 443.
- [ ] Backups scheduled and copied off-server; one restore tested.
- [ ] Update: `git pull && docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build` (take a backup first).
