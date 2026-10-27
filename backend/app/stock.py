"""Per-warehouse stock. Every quantity change goes through `move_stock` so that

    Product.quantity  ==  sum(ProductStock.quantity of that product)

always holds, a warehouse can never go negative, and each change leaves a StockMovement row.
Callers must hold the product's row lock (SELECT ... FOR UPDATE) before calling.
"""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import models


def default_warehouse_id(db: Session) -> Optional[int]:
    """Where stock goes when nothing says otherwise: the oldest warehouse."""
    return db.query(models.Warehouse.id).order_by(models.Warehouse.id).limit(1).scalar()


def home_warehouse_id(db: Session, product: models.Product) -> Optional[int]:
    return product.warehouse_id if product.warehouse_id is not None else default_warehouse_id(db)  # type: ignore


def available(db: Session, product_id: int, warehouse_id: int) -> int:
    row = db.get(models.ProductStock, (product_id, warehouse_id))
    return row.quantity if row else 0  # type: ignore


def _warehouse_name(db: Session, warehouse_id: int) -> str:
    w = db.get(models.Warehouse, warehouse_id)
    return w.name if w else str(warehouse_id)  # type: ignore


def shortage_message(db: Session, product: models.Product, warehouse_id: int, needed: int) -> str:
    return f"product {product.id} ('{product.name}'): need {needed}, have {available(db, product.id, warehouse_id)} in warehouse '{_warehouse_name(db, warehouse_id)}'"  # type: ignore


def move_stock(db: Session, product: models.Product, warehouse_id: int, change: int, reason: str, reference: Optional[str] = None) -> None:
    """Applies `change` (+in / -out) to the product's stock in one warehouse. Raises 409 instead of going negative."""
    if change == 0:
        return
    row = db.get(models.ProductStock, (product.id, warehouse_id))
    if row is None:
        if change < 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + shortage_message(db, product, warehouse_id, -change))
        company_id = getattr(product, "company_id", None)
        row = models.ProductStock(product_id=product.id, warehouse_id=warehouse_id, company_id=company_id, quantity=0)  # type: ignore
        db.add(row)
    if row.quantity + change < 0:  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + shortage_message(db, product, warehouse_id, -change))
    row.quantity += change  # type: ignore
    product.quantity += change  # type: ignore
    company_id = getattr(product, "company_id", None)
    db.add(models.StockMovement(product_id=product.id, warehouse_id=warehouse_id, company_id=company_id, change=change, reason=reason, reference=reference))  # type: ignore
