"""لوطات الخامات: استلام يدوي/افتتاحي، رصيد، وتتبع — الصرف يخصص FIFO تلقائيًا."""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user
from ..pagination import paginate

router = APIRouter(prefix="/lots", tags=["lots"])


class LotIn(BaseModel):
    product_id: int
    warehouse_id: Optional[int] = None
    lot_code: str = Field(min_length=1, max_length=60)
    qty: float = Field(gt=0)
    expiry_date: Optional[date] = None
    reference: Optional[str] = Field(default=None, max_length=80)


class LotOut(BaseModel):
    id: int
    product_id: int
    product_name: str
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    lot_code: str
    source: str
    reference: Optional[str] = None
    expiry_date: Optional[date] = None
    qty_received: float
    qty_remaining: float
    created_at: Optional[str] = None


def _lot_out(db: Session, lot: models.StockLot) -> LotOut:
    product = db.get(models.Product, lot.product_id)
    warehouse = db.get(models.Warehouse, lot.warehouse_id) if lot.warehouse_id else None
    return LotOut(
        id=lot.id,
        product_id=lot.product_id,
        product_name=product.name if product else f"#{lot.product_id}",
        warehouse_id=lot.warehouse_id,
        warehouse_name=warehouse.name if warehouse else None,
        lot_code=lot.lot_code,
        source=lot.source,
        reference=lot.reference,
        expiry_date=lot.expiry_date,
        qty_received=float(lot.qty_received or 0),
        qty_remaining=float(lot.qty_remaining or 0),
        created_at=lot.created_at.isoformat() if lot.created_at else None,
    )


@router.get("", response_model=List[LotOut])
def list_lots(
    response: Response,
    product_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.StockLot).filter(models.StockLot.company_id == db.info["company_id"])
    if product_id is not None:
        q = q.filter(models.StockLot.product_id == product_id)
    if warehouse_id is not None:
        q = q.filter(models.StockLot.warehouse_id == warehouse_id)
    rows = paginate(q, response, skip, limit, models.StockLot.id.desc())
    return [_lot_out(db, lot) for lot in rows]


@router.post("", response_model=LotOut, status_code=status.HTTP_201_CREATED)
def receive_lot(
    payload: LotIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """استلام لوط: ينشئ لوطًا جديدًا أو يزيد رصيد لوط قائم بنفس الكود لنفس المنتج والمخزن."""
    company_id = db.info["company_id"]
    product = db.get(models.Product, payload.product_id)
    if product is None or product.company_id != company_id:
        raise HTTPException(422, "المنتج غير موجود")
    if payload.warehouse_id is not None:
        warehouse = db.get(models.Warehouse, payload.warehouse_id)
        if warehouse is None or warehouse.company_id != company_id:
            raise HTTPException(422, "المخزن غير موجود")

    lot_code = payload.lot_code.strip()
    if not lot_code:
        raise HTTPException(422, "كود اللوط مطلوب")

    lot = (
        db.query(models.StockLot)
        .filter(
            models.StockLot.company_id == company_id,
            models.StockLot.product_id == payload.product_id,
            models.StockLot.warehouse_id == payload.warehouse_id,
            models.StockLot.lot_code == lot_code,
        )
        .first()
    )
    if lot is None:
        lot = models.StockLot(
            company_id=company_id,  # type: ignore
            product_id=payload.product_id,  # type: ignore
            warehouse_id=payload.warehouse_id,  # type: ignore
            lot_code=lot_code,  # type: ignore
            source="manual",  # type: ignore
            reference=payload.reference,
            expiry_date=payload.expiry_date,
            qty_received=payload.qty,  # type: ignore
            qty_remaining=payload.qty,  # type: ignore
        )
        db.add(lot)
        db.flush()
        action = "create"
    else:
        lot.qty_received = (lot.qty_received or 0) + payload.qty  # type: ignore
        lot.qty_remaining = (lot.qty_remaining or 0) + payload.qty  # type: ignore
        if payload.expiry_date is not None:
            lot.expiry_date = payload.expiry_date
        if payload.reference:
            lot.reference = payload.reference
        action = "receive"
    audit(db, user, "update" if action == "receive" else "create", "stock_lot", lot, f"لوط {lot_code} · {product.name} · +{payload.qty}")
    db.commit()
    db.refresh(lot)
    return _lot_out(db, lot)
