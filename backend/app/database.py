"""PostgreSQL connection setup: engine, session factory, declarative Base, and get_db."""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://erp:erp@localhost:5432/erp_db",
)


def _pool_int_setting(name: str, default: int, minimum: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


DATABASE_POOL_SIZE = _pool_int_setting("DATABASE_POOL_SIZE", 5, 1)
DATABASE_MAX_OVERFLOW = _pool_int_setting("DATABASE_MAX_OVERFLOW", 10, 0)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=DATABASE_POOL_SIZE,
    max_overflow=DATABASE_MAX_OVERFLOW,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
