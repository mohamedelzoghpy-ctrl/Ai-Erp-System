"""FastAPI entry point. Run from the backend/ folder:

    uvicorn app.main:app --reload
"""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models  # noqa: F401  (importing registers the tables on Base.metadata)
from .database import Base, engine, get_db
from .deps import get_current_user
from .permissions import permission_gate, seed_all
from .routers import access, attachments, backups, currencies, price_lists, audit as audit_router, auth, bank_statements, eta as eta_router, cheques, coa, cost_centers, data_io, departments, fixed_assets, fiscal_years, general_ledger, hr, journal_entries, lots, manufacturing, pos, qc, recurring_journals, reports, reports_fin, returns, reps, shifts, stocktakes, taxes, transfers, masterdata, orders, payments, products, tenancy, safes_banks, sync


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Create missing tables automatically at startup (handy for development).
    # Set AUTO_CREATE_TABLES=false when the schema is managed with Alembic migrations.
    if os.getenv("AUTO_CREATE_TABLES", "true").lower() not in ("0", "false", "no"):
        Base.metadata.create_all(bind=engine)
    # بذر كتالوج الصلاحيات والأقسام النظامية لكل شركة (idempotent).
    try:
        seed_all(engine)
    except Exception as exc:  # noqa: BLE001 — البذر لا يُسقط الإقلاع
        print(f"[permissions] seed skipped: {exc}")
    yield


_docs = os.getenv("ENABLE_DOCS", "true").lower() not in ("0", "false", "no")

app = FastAPI(
    title="MOZAD ERP",
    description="ERP: inventory, purchasing, customers, suppliers and sales.",
    version="0.7.0",
    lifespan=lifespan,
    # البوابة المركزية للصلاحيات: تعمل على كل مسار — المصادقة + صلاحية المسار المعلنة.
    dependencies=[Depends(permission_gate)],
    # Interactive docs are handy in development; set ENABLE_DOCS=false in production.
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

# Browser origins allowed to call the API, e.g. CORS_ORIGINS="http://localhost:5173,https://erp.example.com".
# Unset = no cross-origin access (same-origin / server-to-server only).
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count", "Content-Disposition"],
    )

app.include_router(auth.router)  # login / setup are public; user admin is protected inside
app.include_router(products.image_router)  # GET /products/{id}/image is public (serves <img> sources)
app.include_router(tenancy.platform)
app.include_router(tenancy.company)
app.include_router(departments.router)
app.include_router(reps.router)
app.include_router(sync.router)  # مزامنة تطبيق المندوبين — محمية بصلاحية sales.rep.mobile

# Every business route requires a logged-in user.
_protected = [Depends(get_current_user)]
app.include_router(hr.router, dependencies=_protected)
app.include_router(masterdata.warehouses, dependencies=_protected)
app.include_router(masterdata.suppliers, dependencies=_protected)
app.include_router(masterdata.customers, dependencies=_protected)
app.include_router(products.router, dependencies=_protected)
app.include_router(data_io.router, dependencies=_protected)
app.include_router(orders.purchases, dependencies=_protected)
app.include_router(orders.sales, dependencies=_protected)
app.include_router(pos.router, dependencies=_protected)
app.include_router(shifts.router, dependencies=_protected)
app.include_router(stocktakes.router, dependencies=_protected)
app.include_router(lots.router, dependencies=_protected)
app.include_router(qc.router, dependencies=_protected)
app.include_router(transfers.router, dependencies=_protected)
app.include_router(returns.sales_returns, dependencies=_protected)
app.include_router(returns.purchase_returns, dependencies=_protected)
app.include_router(audit_router.router, dependencies=_protected)
app.include_router(payments.payments, dependencies=_protected)
app.include_router(payments.categories, dependencies=_protected)
app.include_router(cheques.router, dependencies=_protected)
app.include_router(manufacturing.boms, dependencies=_protected)
app.include_router(manufacturing.production_orders, dependencies=_protected)
app.include_router(manufacturing.lines, dependencies=_protected)
app.include_router(manufacturing.work_centers, dependencies=_protected)
app.include_router(payments.customer_accounts, dependencies=_protected)
app.include_router(payments.supplier_accounts, dependencies=_protected)
app.include_router(coa.router, dependencies=_protected)
app.include_router(safes_banks.safes, dependencies=_protected)
app.include_router(safes_banks.banks, dependencies=_protected)
app.include_router(reports.router)
app.include_router(reports_fin.router, dependencies=_protected)
app.include_router(cost_centers.router, dependencies=_protected)
app.include_router(fiscal_years.router, dependencies=_protected)
app.include_router(recurring_journals.router, dependencies=_protected)
app.include_router(attachments.router, dependencies=_protected)
app.include_router(bank_statements.router, dependencies=_protected)
app.include_router(eta_router.router, dependencies=_protected)
app.include_router(taxes.router, dependencies=_protected)
app.include_router(backups.router, dependencies=_protected)
app.include_router(price_lists.router, dependencies=_protected)
app.include_router(currencies.router, dependencies=_protected)
app.include_router(general_ledger.router, dependencies=_protected)
app.include_router(journal_entries.router, dependencies=_protected)
app.include_router(fixed_assets.router, dependencies=_protected)
app.include_router(access.router)  # إدارة الصلاحيات — محمي داخلياً بـ permissions_manage


@app.get("/", tags=["system"])
def root():
    return {"name": "MOZAD ERP", "status": "running", "docs": "/docs"}


@app.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    """Liveness check that also verifies the database connection."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
