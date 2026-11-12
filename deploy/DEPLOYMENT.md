# Production deployment

Stack: **Caddy** (HTTPS, certificates renewed automatically) → **frontend** (nginx, SPA + `/api` proxy) → **backend** → **PostgreSQL**. Only ports 80/443 are published; the database and API are reachable inside the Docker network only.

## 1. Prepare
1. Use a server with Docker and the Compose plugin, and point a DNS record at it. Ports 80 and 443 must be open.
2. Copy `deploy/.env.prod.example` to `.env` and set `DOMAIN`, `ACME_EMAIL`, `POSTGRES_PASSWORD`, and a long random `SECRET_KEY`.

## 2. Start
```bash
# Note: use --env-file so Docker Compose picks up variables from the project root
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

## 4. Network and trust
- Only Caddy publishes ports 80/443; the backend and database are internal to the Docker network.
- The backend's `FORWARDED_ALLOW_IPS` is set to `127.0.0.1` (safe for a Docker stack where Caddy is a trusted internal peer). If you add more reverse proxies, add their Docker-IP/Subnet instead of `"*"`.
- Caddy handles Let's Encrypt certificates automatically (`ACME_EMAIL` must be set in `.env` for production certificates).

## 4. Backups (production-grade)
Backups are now **self-verifying**: each archive ships a SHA-256 checksum, refuses
corrupt/empty dumps, and can re-verify itself after writing (`VERIFY=1`).

```bash
./deploy/backup.sh            # full pg_dump + gzip + checksum
./deploy/backup.sh VERIFY=1   # validate the just-written archive
./deploy/backup.sh DRY_RUN=1  # preview the archive name/size without writing
```
Schedule daily (cron):

```cron
0 2 * * * cd /opt/erp && ./deploy/backup.sh VERIFY=1 >> backups/backup.log 2>&1
```

Policy notes (instead of "copy them off-server regularly"):
- **Checksums** are stored as `erp_<ts>.sql.gz.sha256` next to the archive.
- **Retention** is 14 days by default (`KEEP_DAYS`); retention is filename-pattern
  based, so a file that is currently being restored cannot be accidentally deleted.
- **Off-server copy** (the part that protects against disk loss): set `OFFSERVER_RSYNC`
  to an `rsync` command that ships each archive to a second host, e.g.
  `OFFSERVER_RSYNC="rsync -avzP --chmod=F0600 ARCHIVE deploy@backup-host:/srv/backups/"`.
  Install `rsync` on the production host if it is missing (second host preferred).

Restore replaces the database contents (**DANGEROUS — read the header first**):
```bash
# 1) stop the backend so nothing writes during the restore
docker compose -f deploy/docker-compose.prod.yml stop backend
# 2) restore an off-server / verified archive (interactive confirmation)
./deploy/restore.sh backups/erp_20261024_020000.sql.gz
# 3) start the backend again (it applies pending migrations on boot)
docker compose -f deploy/docker-compose.prod.yml start backend
```
`restore.sh` now verifies the archive checksum before restoring when `VERIFY=1`, and
reports the number of tables written afterwards. Always test a restore on a spare
machine/DB before restoring a real backup. The scripts were verified against
PostgreSQL 16, but the Docker/Caddy deployment path itself has not yet been run in the
build environment.

## 5. Monitoring and automated maintenance
- **Uptime:** `deploy/uptime-monitor.sh` probes the public URL over HTTPS (Caddy must be
  serving the SPA on port 443, with HSTS and security headers). Install it as a systemd
  timer (`sudo systemctl enable --now monitor.timer`) or your preferred cron.
- **Backend health:** `/health` is already exposed on the backend; the monitor also
  probes it on the internal Docker network when run inside the stack.
- **Restore rehearsals:** run `backup.sh` + `restore.sh` on a scratch database on a
  regular cadence (e.g. monthly) and log the result; a backup you never restored is not
  a backup.

## 6. Checklist
- [ ] `SECRET_KEY` and `POSTGRES_PASSWORD` are long and random; `.env` is not committed
      and is readable only by you (`chmod 600 .env`).
- [ ] `ENABLE_DOCS=false` (already set in the production Compose file).
- [ ] Login brute-force limiting is enabled (10 failures / 15 min per IP + username);
      it is in-memory, so keep one backend worker and replica.
- [ ] The configured connection pool fits within the PostgreSQL connection budget.
- [ ] Firewall allows only 22, 80, and 443.
- [ ] Backups are scheduled (`VERIFY=1`), copied off-server, and retain to a set period.
- [ ] The `POSTGRES_PASSWORD` reset flow works: `./backend/reset_admin_password.py`.
- [ ] Before updates, take a backup, then run `git pull && docker compose -f
      deploy/docker-compose.prod.yml --env-file .env up -d --build`.

