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

## Run with Docker (PostgreSQL + backend)

From the repository root:

```bash
cp .env.example .env        # then edit POSTGRES_PASSWORD and SECRET_KEY
docker compose up --build
```

The backend container applies Alembic migrations on start, then serves on http://localhost:8000
(docs at `/docs`). Data lives in the `pgdata` volume, so it survives restarts.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/erp_db` | Database connection |
| `SECRET_KEY` | random per start | JWT signing key — **set it in production** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Token lifetime |
| `CORS_ORIGINS` | empty (no cross-origin) | Comma-separated browser origins allowed to call the API |
| `COMPANY_NAME` | `AI ERP System` | Printed on exported invoices, purchase orders and reports |
| `COMPANY_PHONE`, `COMPANY_ADDRESS` | empty | Printed under the company name on PDFs |
| `CURRENCY_LABEL` | `ج.م` | Currency shown next to totals |
| `EXPORT_TIMEZONE` | `Africa/Cairo` | Timezone of dates printed in exports |
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

## PDF and Excel export

| Endpoint | Output |
|---|---|
| `GET /sales-orders/{id}/pdf` · `/xlsx` | Invoice |
| `GET /purchase-orders/{id}/pdf` · `/xlsx` | Purchase order |
| `GET /reports/sales-summary/xlsx?date_from=&date_to=` | Sales report (summary, daily, products, customers) |
| `GET /reports/purchases-summary/xlsx?date_from=&date_to=` | Purchases report (summary, daily, products, suppliers) |
| `GET /reports/inventory-valuation/xlsx` | Stock value per warehouse and per product |
| `GET /reports/low-stock/xlsx` | Products at or below their reorder level |

Invoices and purchase orders can be exported by any logged-in user; financial reports need manager/admin.
PDFs are RTL Arabic, drawn with the bundled Amiri font (SIL OFL, `app/assets/fonts/OFL.txt`). Text in Excel
files is always stored as text, so a product named `=HYPERLINK(...)` cannot run as a formula.

Reports date an order by when it was confirmed (sales) or received (purchases), not when the draft was created.
