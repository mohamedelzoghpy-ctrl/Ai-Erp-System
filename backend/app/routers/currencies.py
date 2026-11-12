"""العملات: إدارة العملات الأجنبية وأسعار صرفها مقابل الجنيه (العملة الأساسية).

القواعد:
- الجنيه (EGP) هو العملة الأساسية للنظام — لا يُخزن ولا يُعدل.
- كل مبالغ الدفاتر والتقارير بالجنيه دائمًا.
- سعر الصرف يُثبَّت على المستند لحظة إصداره؛ فروق السداد تُرحّل آليًا (4240/5350).
"""
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(prefix="/currencies", tags=["currencies"], dependencies=[Depends(get_current_user)])

BASE_CURRENCY = "EGP"


class CurrencyIn(BaseModel):
    code: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=60)
    rate: Decimal = Field(gt=0, description="كم جنيهًا يساوي 1 وحدة من هذه العملة")


class CurrencyRateIn(BaseModel):
    rate: Decimal = Field(gt=0)


def _out(c: models.Currency) -> dict:
    return {
        "id": c.id, "code": c.code, "name": c.name,
        "rate": c.rate, "is_active": c.is_active,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _get(db: Session, currency_id: int) -> models.Currency:
    c = db.query(models.Currency).filter(
        models.Currency.id == currency_id, models.Currency.company_id == db.info["company_id"]
    ).first()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العملة غير موجودة")
    return c


@router.get("")
def list_currencies(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.query(models.Currency).filter(models.Currency.company_id == db.info["company_id"]).order_by(models.Currency.code).all()
    return [_out(c) for c in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_currency(
    payload: CurrencyIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    if payload.code == BASE_CURRENCY:
        raise HTTPException(422, "الجنيه هو عملة النظام الأساسية ولا تُنشأ عملة بهذا الرمز")
    dup = db.query(models.Currency).filter(
        models.Currency.company_id == db.info["company_id"], models.Currency.code == payload.code
    ).first()
    if dup is not None:
        raise HTTPException(409, f"العملة {payload.code} موجودة بالفعل")
    c = models.Currency(company_id=db.info["company_id"], code=payload.code, name=payload.name.strip(),
                        rate=payload.rate, updated_by=user.id)
    db.add(c)
    audit(db, user, "create", "currency", c, f"{c.code} · سعر {c.rate}")
    db.commit()
    db.refresh(c)
    return _out(c)


@router.patch("/{currency_id}/rate", response_model=None)
def update_rate(
    currency_id: int,
    payload: CurrencyRateIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """تحديث سعر الصرف الحالي (للمستندات الجديدة) — النسخ القديمة محفوظة عليها."""
    c = _get(db, currency_id)
    old = c.rate
    c.rate = payload.rate
    c.updated_by = user.id
    audit(db, user, "update", "currency", c, f"{c.code}: {old} → {c.rate}")
    db.commit()
    db.refresh(c)
    return _out(c)


@router.patch("/{currency_id}", response_model=None)
def update_currency(
    currency_id: int,
    payload: CurrencyRateIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    return update_rate(currency_id, payload, db, user)  # alias (rate-only update)


@router.delete("/{currency_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_currency(
    currency_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """إيقاف العملة (تختفي من القوائم؛ المستندات التاريخية محفوظة). حذف نهائي ممنوع."""
    c = _get(db, currency_id)
    used = db.query(models.SalesOrder.id).filter(models.SalesOrder.currency_id == currency_id).first() \
        or db.query(models.PurchaseOrder.id).filter(models.PurchaseOrder.currency_id == currency_id).first() \
        or db.query(models.Payment.id).filter(models.Payment.currency_id == currency_id).first()
    if used:
        c.is_active = False
        audit(db, user, "update", "currency", c, f"{c.code}: إيقاف (عليها مستندات)")
        db.commit()
        return None
    audit(db, user, "delete", "currency", c.id, f"{c.code}")
    db.delete(c)
    db.commit()
    return None
