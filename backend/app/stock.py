"""Per-warehouse stock. Every quantity change goes through `move_stock` so that

    Product.quantity  ==  sum(ProductStock.quantity of that product)

always holds, a warehouse can never go negative, and each change leaves a StockMovement row.
Quantities are Decimal (NUMERIC(12,3)) — fractional units like 0.5 كجم are supported.
Callers must hold the product's row lock (SELECT ... FOR UPDATE) before calling.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import models

ZERO = Decimal("0")
_THREE_PLACES = Decimal("0.001")


def dec(value: Union[int, float, str, Decimal, None]) -> Decimal:
    """توحيد أي كمية واردة (float من الـ API / Decimal من الـ DB) إلى Decimal."""
    if value is None:
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def q3(value: Union[int, float, str, Decimal, None]) -> Decimal:
    """تقريب الكمية إلى 3 منازل عشرية (دقة تخزين العمود)."""
    return dec(value).quantize(_THREE_PLACES, rounding=ROUND_HALF_UP)


def default_warehouse_id(db: Session) -> Optional[int]:
    """Where stock goes when nothing says otherwise: the oldest warehouse."""
    return db.query(models.Warehouse.id).order_by(models.Warehouse.id).limit(1).scalar()


def home_warehouse_id(db: Session, product: models.Product) -> Optional[int]:
    return product.warehouse_id if product.warehouse_id is not None else default_warehouse_id(db)  # type: ignore


def available(db: Session, product_id: int, warehouse_id: int) -> Decimal:
    row = db.get(models.ProductStock, (product_id, warehouse_id))
    return dec(row.quantity) if row else ZERO  # type: ignore


def _warehouse_name(db: Session, warehouse_id: int) -> str:
    w = db.get(models.Warehouse, warehouse_id)
    return w.name if w else str(warehouse_id)  # type: ignore


def shortage_message(db: Session, product: models.Product, warehouse_id: int, needed: Union[int, float, Decimal]) -> str:
    return f"product {product.id} ('{product.name}'): need {q3(needed)}, have {available(db, product.id, warehouse_id)} in warehouse '{_warehouse_name(db, warehouse_id)}'"  # type: ignore


def move_stock(db: Session, product: models.Product, warehouse_id: int, change: Union[int, float, Decimal], reason: str, reference: Optional[str] = None) -> None:
    """Applies `change` (+in / -out) to the product's stock in one warehouse. Raises 409 instead of going negative.

    Quantities are Decimal (3 places). Floats/ints from callers are normalized — no float drift.
    """
    change = q3(change)
    if change == 0:
        return
    row = db.get(models.ProductStock, (product.id, warehouse_id))
    if row is None and change < 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + shortage_message(db, product, warehouse_id, -change))
    if row is not None and dec(row.quantity) + change < 0:  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + shortage_message(db, product, warehouse_id, -change))
    if row is None:
        # First movement for this (product, warehouse). Two concurrent transactions
        # can both see no row; create it inside a savepoint so the loser re-fetches
        # the winner's row and applies its change instead of failing with a 500.
        from sqlalchemy.exc import IntegrityError
        company_id = getattr(product, "company_id", None)
        for _ in range(2):
            try:
                with db.begin_nested():
                    db.add(models.ProductStock(product_id=product.id, warehouse_id=warehouse_id, company_id=company_id, quantity=change))  # type: ignore
                db.add(models.StockMovement(product_id=product.id, warehouse_id=warehouse_id, company_id=company_id, change=change, reason=reason, reference=reference))  # type: ignore
                product.quantity = dec(product.quantity) + change  # type: ignore
                return
            except IntegrityError:
                row = db.get(models.ProductStock, (product.id, warehouse_id))
                if row is None:
                    raise
    row.quantity = dec(row.quantity) + change  # type: ignore
    product.quantity = dec(product.quantity) + change  # type: ignore
    company_id = getattr(product, "company_id", None)
    db.add(models.StockMovement(product_id=product.id, warehouse_id=warehouse_id, company_id=company_id, change=change, reason=reason, reference=reference))  # type: ignore


def consume_lots(db: Session, product: models.Product, warehouse_id: int, qty: Union[int, float, Decimal]) -> Decimal:
    """خصم اللوطات عند الخروج من المخزون بنظام FEFO (الأقرب انتهاءً أولًا ثم الأقدم).

    يخصم ما استطاع من اللوطات المتاحة؛ الكمية الزائدة على اللوطات (مخزون افتتاحي
    قديم بلا لوطات) تُترك دون خصم — لا ترفع خطأ لأن move_stock هو بوابة الكمية.
    يعيد ما خُصم فعليًا."""
    remaining = q3(qty)
    if remaining <= 0:
        return ZERO
    deducted = ZERO
    lots = (
        db.query(models.StockLot)
        .filter(
            models.StockLot.company_id == getattr(product, "company_id", None),
            models.StockLot.product_id == product.id,
            models.StockLot.warehouse_id == warehouse_id,
            models.StockLot.qty_remaining > 0,
        )
        .order_by(
            models.StockLot.expiry_date.is_(None).asc(),   # ذات الانتهاء أولًا (بلا انتهاء لاحقًا)
            models.StockLot.expiry_date.asc().nulls_last(),  # الأقرب انتهاءً
            models.StockLot.id.asc(),                        # ثم الأقدم
        )
        .with_for_update()
        .all()
    )
    for lot in lots:
        if remaining <= 0:
            break
        available = dec(lot.qty_remaining)
        take = min(available, remaining)
        if take > 0:
            lot.qty_remaining = available - take
            remaining -= take
            deducted += take
    return deducted
