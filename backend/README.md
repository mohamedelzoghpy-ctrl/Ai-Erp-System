# AI ERP — Backend

FastAPI + SQLAlchemy + PostgreSQL. Modules: warehouses, suppliers, customers, products & inventory,
purchase orders (stock in), sales orders (stock out), reports, users/roles (JWT).

## Run locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql+psycopg2://USER:PASSWORD@localhost:5432/erp_db"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"

uvicorn app.main:app --reload
```

Open http://localhost:8000/docs. First run: call `POST /auth/setup` to create the first admin
(works only while there are no users), then click **Authorize** and log in.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/erp_db` | Database connection |
| `SECRET_KEY` | random per start | JWT signing key — **set it in production** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Token lifetime |
| `AUTO_CREATE_TABLES` | `true` | Create missing tables at startup. Set `false` when using Alembic |

## Database migrations (Alembic)

```bash
cd backend
export AUTO_CREATE_TABLES=false

alembic upgrade head                                   # apply migrations to an empty/new database
alembic revision --autogenerate -m "describe change"   # after editing app/models.py
alembic upgrade head
```

If your database was already created by `AUTO_CREATE_TABLES=true`, mark it as up to date instead of
re-creating tables: `alembic stamp head`.

## Roles

| Role | Can do |
|---|---|
| `staff` | Day-to-day work: products, orders, customers, suppliers, low-stock report |
| `manager` | Everything staff can + delete master data/products + financial reports |
| `admin` | Everything + manage users |
