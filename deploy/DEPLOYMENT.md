# Production deployment

Stack: **Caddy** (HTTPS, certificates renewed automatically) → **frontend** (nginx, SPA + `/api` proxy) → **backend** → **PostgreSQL**. Only ports 80/443 are published; the database and API are reachable inside the Docker network only.

## 1. Prepare
1. Use a server with Docker and the Compose plugin, and point a DNS record at it. Ports 80 and 443 must be open.
2. Copy `deploy/.env.prod.example` to `.env` and set `DOMAIN`, `ACME_EMAIL`, `POSTGRES_PASSWORD`, and a long random `SECRET_KEY`.

## 2. Start
```bash
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build
```
Open `https://your-domain` and create the first admin account on the setup screen. Migrations run automatically when the backend starts.

## 3. Database connection budget
`DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW` configure SQLAlchemy per backend process. Defaults are 5 and 10. Estimate the maximum application connections as:

```text
backend replicas × worker processes × (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)
```

Reserve additional PostgreSQL connections for migrations, monitoring, administration, and other services. Keep the total below PostgreSQL's configured connection limit. Increasing these values does not by itself increase throughput; select them from measured workload and available database capacity. The current in-memory login rate limiter requires one backend worker and one replica; do not scale workers or replicas until that limiter is made shared.

These settings make the pool tunable; they are not a capacity certification. The target of 100+ users and 2,000 invoices/day with about 50 lines each needs load testing against the intended server and database before it can be claimed as supported.

## 4. Backups (before storing real data)
```bash
./deploy/backup.sh
# Daily at 02:00:
# 0 2 * * * cd /opt/erp && ./deploy/backup.sh >> backups/backup.log 2>&1
```
Backups are written to `backups/erp_YYYYmmdd_HHMMSS.sql.gz` and kept for 14 days by default (`KEEP_DAYS`). Copy them off-server regularly; a backup on the same disk does not survive disk loss.

Restore replaces the database contents:
```bash
docker compose -f deploy/docker-compose.prod.yml stop backend
./deploy/restore.sh backups/erp_20261024_020000.sql.gz
docker compose -f deploy/docker-compose.prod.yml start backend
```
Test a restore on a spare machine regularly. The backup/restore scripts were verified against PostgreSQL 16, but the Docker/Caddy deployment path itself has not yet been run in the build environment.

## 5. Checklist
- [ ] `SECRET_KEY` and `POSTGRES_PASSWORD` are long and random; `.env` is not committed and is readable only by you (`chmod 600 .env`).
- [ ] `ENABLE_DOCS=false` (already set in the production Compose file).
- [ ] Login brute-force limiting is enabled (10 failures / 15 min per IP + username); it is in-memory, so keep one backend worker and replica.
- [ ] The configured connection pool fits within the PostgreSQL connection budget.
- [ ] Firewall allows only 22, 80, and 443.
- [ ] Backups are scheduled and copied off-server; restore has been tested.
- [ ] Before updates, take a backup, then run `git pull && docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build`.
