# MOZAD ERP

Web ERP for inventory, purchasing, sales, customers and suppliers. Arabic (RTL) interface.

| Part | Stack | Folder |
|---|---|---|
| API | Python, FastAPI, SQLAlchemy, PostgreSQL, Alembic, JWT | [`backend/`](backend/README.md) |
| Web app | React, TypeScript, Vite | [`frontend/`](frontend/) |

## Quick start (Docker)

```bash
cp .env.example .env     # set POSTGRES_PASSWORD and SECRET_KEY
docker compose up --build
```

- Web app: http://localhost:8080
- API docs: http://localhost:8000/docs

On first run open the web app and choose **إنشاء المدير العام** to create the first admin account.

## Local development (without Docker)

```bash
# terminal 1: API (needs a PostgreSQL database, see backend/README.md)
cd backend && pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@localhost:5432/erp_db
uvicorn app.main:app --reload

# terminal 2: web app (dev server proxies /api to http://localhost:8000)
cd frontend && npm install && npm run dev      # http://localhost:5173
```

Set `VITE_BACKEND_URL` if the API runs elsewhere.

## Features

- Warehouses, suppliers, customers, products with stock levels and reorder alerts
- Purchase orders (stock in on receipt) and sales orders (stock out on confirmation, never oversells)
- Stock movement history and manual adjustments
- Dashboard and detailed reports with a custom date range: sales, purchases, inventory valuation, low stock
- Profit report (gross profit and margin per product, cost taken at time of sale, net of returns)
- Export invoices and purchase orders as PDF or Excel; export every report to Excel
- Accounts: customer receipts and supplier payments, opening balances, account statements (PDF/Excel), receivables and payables reports
- Per-warehouse stock and warehouse-to-warehouse transfers (with PDF transfer note)
- Periodic stock-take (count sheet, differences, applied as stock adjustments)
- Cashier shifts: open the drawer with a float, close against a cash count, expected vs counted difference
- Sales and purchase returns (stock, balances, statements and aging stay consistent)
- Point of sale screen: scan SKU, cart, cash change, credit or partial sales, invoice PDF
- Audit log of who changed what and when (managers and admins)
- Receivables/payables aging report (0–30 / 31–60 / 61–90 / 90+ days)
- Paid / partial / unpaid status on every invoice (payments applied oldest-first)
- Server-side pagination (50 per page) and search on products, customers, suppliers, orders and payments
- Roles: staff / manager / admin; user management for admins

## Production deployment

`deploy/` contains a production stack (Caddy with automatic HTTPS, database and API not exposed), backup and restore scripts,
and a checklist. See [deploy/DEPLOYMENT.md](deploy/DEPLOYMENT.md).
