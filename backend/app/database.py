"""PostgreSQL connection setup: engine, session factory, declarative Base, and the get_db dependency."""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# Override with the DATABASE_URL environment variable in any real deployment.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/erp_db",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # drop stale connections instead of failing on them
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a DB session and always closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
