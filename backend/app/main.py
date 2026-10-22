"""FastAPI entry point. Run from the backend/ folder:

    uvicorn app.main:app --reload
"""

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models  # noqa: F401  (importing registers the tables on Base.metadata)
from .database import Base, engine, get_db

# Create all tables automatically at startup if they don't exist yet.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI ERP System",
    description="ERP: inventory, purchasing, customers, suppliers and sales.",
    version="0.1.0",
)


@app.get("/", tags=["system"])
def root():
    return {"name": "AI ERP System", "status": "running", "docs": "/docs"}


@app.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    """Liveness check that also verifies the database connection."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
