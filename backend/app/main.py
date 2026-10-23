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
from .routers import auth, masterdata, orders, products, reports


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Create missing tables automatically at startup (handy for development).
    # Set AUTO_CREATE_TABLES=false when the schema is managed with Alembic migrations.
    if os.getenv("AUTO_CREATE_TABLES", "true").lower() not in ("0", "false", "no"):
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="AI ERP System",
    description="ERP: inventory, purchasing, customers, suppliers and sales.",
    version="0.5.0",
    lifespan=lifespan,
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
    )

app.include_router(auth.router)  # login / setup are public; user admin is protected inside

# Every business route requires a logged-in user.
_protected = [Depends(get_current_user)]
app.include_router(masterdata.warehouses, dependencies=_protected)
app.include_router(masterdata.suppliers, dependencies=_protected)
app.include_router(masterdata.customers, dependencies=_protected)
app.include_router(products.router, dependencies=_protected)
app.include_router(orders.purchases, dependencies=_protected)
app.include_router(orders.sales, dependencies=_protected)
app.include_router(reports.router)  # protected per endpoint (financial reports need manager/admin)


@app.get("/", tags=["system"])
def root():
    return {"name": "AI ERP System", "status": "running", "docs": "/docs"}


@app.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    """Liveness check that also verifies the database connection."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
