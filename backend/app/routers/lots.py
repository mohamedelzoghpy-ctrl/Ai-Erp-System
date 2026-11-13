"""لوطات الخامات: استلام يدوي/افتتاحي، رصيد، وتتبع — الصرف يخصص FIFO تلقائيًا.

الاستلام اليدوي حركة مخزنية كاملة: يمر عبر move_stock (دفتر الحركة + منع
السالب) ثم يُنشئ/يزيد اللوط — لا يجوز زيادة رصيد لوط دون أثر مخزني حتى لا
ينحرف دفتر اللوطات عن المخزون الفعلي، فالصرف كله مقيّد بمخزن."""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models, stock
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager
from ..pagination import paginate

router = APIRouter(prefix="/lots", tags=["lots"])


class LotIn(BaseModel):
    product_id: int
    warehouse_id: int = Field(description="المخزن إلزامي — الصرف من اللوطات مقيّد بمخزن")
    lot_code: str = Field(min_length=1, max_length=60)
    qty: float = Field(gt=0)
    expiry_date: Optional[date] = None
    reference: Optional[str] = Field(default=None, max_length=80)


class LotWriteOff(BaseModel):
    """إعدام/هالك من لوط — حركة مخزنية معكوسة موثقة بالسبب."""
    qty: float = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)


class LotPatch(BaseModel):
    expiry_date: Optional[date] = None


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
    qc_status: str = "passed"  # passed | pending | failed (فحص جودة الاستلام)
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
        qc_status=getattr(lot, "qc_status", "passed") or "passed",
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
    """استلام لوط: حركة مخزنية داخلية (+qty عبر move_stock) تُقترن بإنشاء اللوط
    أو زيادة رصيد لوط قائم بنفس الكود لنفس المنتج والمخزن."""
    company_id = db.info["company_id"]
    product = db.get(models.Product, payload.product_id)
    if product is None or product.company_id != company_id:
        raise HTTPException(422, "المنتج غير موجود")
    warehouse = db.get(models.Warehouse, payload.warehouse_id)
    if warehouse is None or warehouse.company_id != company_id:
        raise HTTPException(422, "المخزن غير موجود")

    lot_code = payload.lot_code.strip()
    if not lot_code:
        raise HTTPException(422, "كود اللوط مطلوب")

    # الحركة المخزنية أولًا: بوابة move_stock هي المرجع (دفتر حركة + منع سالب) —
    # واللوط مجرد تتبع فوقها؛ فشل الحركة يلغي كل شيء قبل إنشاء أي لوط.
    stock.move_stock(db, product, payload.warehouse_id, payload.qty, "lot-receive", lot_code)

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
        # أرصدة Numeric تعود Decimal من القاعدة — نوحّد قبل الجمع (كان يفشل Decimal+float)
        from decimal import Decimal
        add_qty = Decimal(str(payload.qty))
        lot.qty_received = Decimal(str(lot.qty_received or 0)) + add_qty  # type: ignore
        lot.qty_remaining = Decimal(str(lot.qty_remaining or 0)) + add_qty  # type: ignore
        if payload.expiry_date is not None:
            lot.expiry_date = payload.expiry_date
        if payload.reference:
            lot.reference = payload.reference
        action = "receive"
    audit(db, user, "update" if action == "receive" else "create", "stock_lot", lot, f"لوط {lot_code} · {product.name} · +{payload.qty}")
    db.commit()
    db.refresh(lot)
    return _lot_out(db, lot)


@router.patch("/{lot_id}", response_model=LotOut)
def update_lot(lot_id: int, payload: LotPatch, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """تعديل بيانات لوط — تاريخ الصلاحية فقط (بيانات تتبع لا تمس الأرصدة)."""
    lot = db.get(models.StockLot, lot_id)
    if lot is None or lot.company_id != db.info["company_id"]:
        raise HTTPException(404, "اللوط غير موجود")
    if payload.expiry_date is not None:
        lot.expiry_date = payload.expiry_date  # type: ignore[assignment]
        audit(db, user, "update", "stock_lot", lot, f"تعديل صلاحية لوط {lot.lot_code} → {payload.expiry_date}")
        db.commit()
        db.refresh(lot)
    return _lot_out(db, lot)


@router.post("/{lot_id}/write-off", response_model=LotOut)
def write_off_lot(lot_id: int, payload: LotWriteOff, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """إعدام كمية من لوط (هالك/انتهاء صلاحية/تلف): حركة مخزنية سالبة عبر move_stock
    تقترن بخصم رصيد اللوط — لا إعدام خارج الدفترين."""
    company_id = db.info["company_id"]
    lot = db.get(models.StockLot, lot_id)
    if lot is None or lot.company_id != company_id:
        raise HTTPException(404, "اللوط غير موجود")
    if lot.warehouse_id is None:
        raise HTTPException(422, "لوط قديم بلا مخزن — عدّل رصيده بالجرد بدلاً من الإعدام")
    product = db.get(models.Product, lot.product_id)
    if product is None:
        raise HTTPException(422, "منتج اللوط غير موجود")
    from decimal import Decimal
    qty = Decimal(str(payload.qty))
    remaining = Decimal(str(lot.qty_remaining or 0))
    if qty > remaining:
        raise HTTPException(409, f"رصيد اللوط لا يكفي للإعدام: المتبقي {remaining} والمطلوب {qty}")

    # الحركة المخزنية أولًا (بوابة منع السالب للمنتج كله) ثم خصم اللوط — ذريًا
    stock.move_stock(db, product, lot.warehouse_id, -qty, "lot-writeoff", lot.lot_code)
    lot.qty_remaining = remaining - qty  # type: ignore[assignment]
    audit(db, user, "update", "stock_lot", lot, f"إعدام من لوط {lot.lot_code} · {product.name} · -{qty} · السبب: {payload.reason}")
    db.commit()
    db.refresh(lot)
    return _lot_out(db, lot)
