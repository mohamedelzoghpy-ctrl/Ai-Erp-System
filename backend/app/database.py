"""PostgreSQL connection setup: engine, session factory, declarative Base, and get_db."""

import os
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.orm import with_loader_criteria

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


@event.listens_for(Session, "do_orm_execute")
def _scope_tenant_queries(execute_state) -> None:
    company_id = execute_state.session.info.get("company_id")
    if not execute_state.is_select or company_id is None:
        return

    from .models import TenantOwned
    from . import models

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantOwned,
            lambda entity: entity.company_id == company_id,
            include_aliases=True,
        )
    )
    company_role = execute_state.session.info.get("company_role")
    if company_role is not None and company_role not in ("admin", "manager") and not execute_state.session.info.get(
        "is_platform_admin", False
    ):
        branch_ids = execute_state.session.info.get("visible_branch_ids", ())
        warehouse_ids = execute_state.session.info.get("warehouse_ids", ())
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                models.Branch,
                lambda entity: entity.id.in_(branch_ids),
                include_aliases=True,
            ),
            with_loader_criteria(
                models.Warehouse,
                lambda entity: entity.id.in_(warehouse_ids),
                include_aliases=True,
            ),
            with_loader_criteria(
                models.Product,
                lambda entity: entity.warehouse_id.is_(None) | entity.warehouse_id.in_(warehouse_ids),
                include_aliases=True,
            ),
        )
        for model in (
            models.PurchaseOrder,
            models.SalesOrder,
            models.SalesReturn,
            models.PurchaseReturn,
        ):
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    model,
                    lambda entity: entity.warehouse_id.in_(warehouse_ids),
                    include_aliases=True,
                )
            )
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                models.StockMovement,
                lambda entity: entity.warehouse_id.is_(None) | entity.warehouse_id.in_(warehouse_ids),
                include_aliases=True,
            ),
            with_loader_criteria(
                models.Stocktake,
                lambda entity: entity.warehouse_id.in_(warehouse_ids),
                include_aliases=True,
            ),
        )


@event.listens_for(Session, "before_flush")
def _assign_tenant_to_new_rows(session: Session, _flush_context, _instances) -> None:
    company_id = session.info.get("company_id")
    if company_id is None:
        return

    from .models import TenantOwned

    for instance in session.new:
        if isinstance(instance, TenantOwned):
            if instance.company_id not in (None, company_id):
                if not session.info.get("allow_company_provisioning", False):
                    raise ValueError("Cannot create a record for another company")
            else:
                instance.company_id = company_id


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
