"""FastAPI entry point. Run from the backend/ folder:

    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models  # noqa: F401  (importing registers the tables on Base.metadata)
from .database import Base, engine, get_db
from .routers import masterdata, orders, products


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Create all tables automatically at startup if they don't exist yet.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="AI ERP System",
    description="ERP: inventory, purchasing, customers, suppliers and sales.",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(masterdata.warehouses)
app.include_router(masterdata.suppliers)
app.include_router(masterdata.customers)
app.include_router(products.router)
app.include_router(orders.purchases)
app.include_router(orders.sales)


@app.get("/", tags=["system"])
def root():
    return {"name": "AI ERP System", "status": "running", "docs": "/docs"}


@app.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    """Liveness check that also verifies the database connection."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
