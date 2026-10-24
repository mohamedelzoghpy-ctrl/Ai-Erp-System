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
| `ENABLE_DOCS` | `true` | Serve `/docs` and `/openapi.json`; set `false` in production |
| `LOGIN_MAX_FAILURES`, `LOGIN_WINDOW_SECONDS` | `10`, `900` | Failed logins per client IP + username before HTTP 429 (`0` disables). In-memory, per worker process |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxy addresses trusted for `X-Forwarded-For` (so the limiter sees real client IPs) |
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

## Accounts (receivables / payables)

- Each customer and supplier has an **opening balance** (manager/admin only) and a computed **balance**:
  customer = opening + confirmed sales − receipts; supplier = opening + received purchases − payments.
  Positive means money owed; negative is a credit.
- `POST /payments` records a receipt (`customer_id`) or a supplier payment (`supplier_id`); payments are never edited,
  only voided (`POST /payments/{id}/void`, manager/admin) and voided ones stop counting.
- `GET /customers/{id}/statement` and `/suppliers/{id}/statement` (+ `/pdf`, `/xlsx`, optional `date_from`/`date_to`).
- `GET /reports/receivables` and `/reports/payables` (+ `/xlsx`, manager/admin); the dashboard shows both totals.
- Upgrading a database created by `AUTO_CREATE_TABLES=true`: run `alembic stamp 0001` then `alembic upgrade head`
  (the `opening_balance` columns are added by migration `0002`; `create_all` never alters existing tables).

## Pagination

List endpoints (`/products`, `/customers`, `/suppliers`, `/purchase-orders`, `/sales-orders`, `/payments`) take `skip` and `limit`
(max 500) and return the number of matches in the `X-Total-Count` response header. `/customers` and `/suppliers` also accept `search`.

## Invoice settlement

Payments are recorded per customer/supplier, not per invoice. Orders returned by the API carry `paid_amount`, `balance_due` and
`payment_status` (`paid` / `partial` / `unpaid`; `null` for drafts and cancelled orders), computed FIFO: payments first cover the
opening balance, then confirmed sales (or received purchases) in the order they were committed. Voiding a payment re-computes it.

## Aging reports

`GET /reports/receivables/aging` and `/reports/payables/aging` (+ `/xlsx`, manager/admin) split what is still unpaid by invoice age
(0–30, 31–60, 61–90, 90+ days since commit) plus the unpaid opening balance, using the same oldest-first settlement as invoice status.

## Audit log

Every change that matters (orders created/confirmed/received/cancelled, payments recorded/voided, stock adjustments, opening-balance
changes, creates/updates/deletes of products, parties and users, and logins) writes a row to `audit_logs` in the same transaction as
the change, so a rolled-back change leaves no entry. `GET /audit-logs` (manager/admin; filters `entity`, `action`, `username`,
`date_from`, `date_to`; paginated) is read-only. Failed login attempts are limited but not logged.

## Point of sale

`POST /pos/checkout` (any logged-in user) creates a sales order, takes the stock and records the payment in one transaction:
if stock is short, nothing is saved (409). Without `customer_id` the sale goes to the shared "عميل نقدي" customer and must be paid in
full; with a customer, `amount_paid` may be lower (credit sale, `0` = fully on account) but never above the total.
The web app's "نقطة البيع" screen uses it (barcode/SKU + Enter, cart, change calculation, invoice PDF). Custom sale prices can only be set by managers/admins at the API level; staff requests use each product's current sale price.

## Returns

`POST /sales-returns` and `POST /purchase-returns` (any logged-in user) record goods coming back from a customer / going back to a supplier,
always against a confirmed sale / received purchase order: `{order_id, items: [{order_item_id, quantity}], refund_amount, method, notes}`.
- Quantity per line is capped at sold/received minus already returned (checked under a row lock, so simultaneous returns can't exceed it).
- Sales returns add stock; purchase returns remove it and fail with 409 if the stock is no longer there.
- The party's balance drops by `total - refund_amount` (`refund_amount` is cash exchanged at the time). Statements, invoice settlement and
  aging all include returns; the dashboard shows the period's returns next to sales.
- Returns are final: no edit or void. `GET /sales-returns`, `/purchase-returns` (filters `order_id`, `party_id`; paginated) list them.
- Sales/purchase summary reports are not reduced by returns; they are shown separately on the dashboard.
