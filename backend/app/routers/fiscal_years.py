"""Fiscal Years — company-scoped master data, with monthly periods and year-end closing."""
import calendar
from typing import List, Optional
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..accounting import AccountingEngine
from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(
    prefix="/fiscal-years",
    tags=["fiscal years"],
    dependencies=[Depends(get_current_user)],
)

PERIOD_NAMES = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def _ensure_periods(db: Session, fy: models.FiscalYear) -> None:
    """توليد 12 شهرًا ماليًا للسنة إن لم تكن موجودة (idempotent)."""
    existing = db.query(models.FiscalPeriod).filter(models.FiscalPeriod.fiscal_year_id == fy.id).count()
    if existing:
        return
    for month in range(1, 13):
        last_day = calendar.monthrange(fy.start_date.year, month)[1]
        db.add(models.FiscalPeriod(
            company_id=fy.company_id,
            fiscal_year_id=fy.id,
            name=PERIOD_NAMES[month - 1],
            start_date=date(fy.start_date.year, month, 1),
            end_date=date(fy.start_date.year, month, last_day),
            is_closed=False,
        ))
    db.flush()


def post_closing_entry(db: Session, company_id: int, user_id: int, fy: models.FiscalYear) -> Optional[int]:
    """قيد إقفال السنة: تصفير الإيرادات والمصاريف في حساب الأرباح المبقاة 3200.

    يُرحّل بتاريخ آخر يوم في السنة (قبل تعليم is_closed حتى يمر من حارس السنة)."""
    revenue_accs = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id,
        models.ChartAccount.type == "revenue",
        models.ChartAccount.is_group.is_(False),
    ).all()
    expense_accs = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id,
        models.ChartAccount.type == "expense",
        models.ChartAccount.is_group.is_(False),
    ).all()

    def period_net(acc) -> Decimal:
        d, c = db.query(
            func.coalesce(func.sum(models.JournalItem.debit), 0),
            func.coalesce(func.sum(models.JournalItem.credit), 0),
        ).join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id).filter(
            models.JournalItem.company_id == company_id,
            models.JournalItem.account_id == acc.id,
            models.JournalEntry.date >= fy.start_date,
            models.JournalEntry.date <= fy.end_date,
        ).one()
        return (Decimal(str(d or 0)) - Decimal(str(c or 0))).quantize(Decimal("0.01"))

    items: list = []
    for acc in revenue_accs:
        net = -period_net(acc)  # رصيد إيراد موجب = دائن → نقفله بمدين
        if net > 0:
            items.append({"account_id": acc.id, "debit": net, "credit": 0, "notes": "إقفال إيراد"})
    for acc in expense_accs:
        net = period_net(acc)  # رصيد مصروف موجب = مدين → نقفله بدائن
        if net > 0:
            items.append({"account_id": acc.id, "debit": 0, "credit": net, "notes": "إقفال مصروف"})
    if not items:
        return None
    total = sum((i["debit"] for i in items), Decimal("0")) - sum((i["credit"] for i in items), Decimal("0"))
    retained = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code == "3200"
    ).first()
    if retained is None or retained.is_group:
        raise HTTPException(409, "حساب الأرباح المبقاة (3200) غير موجود — لا يمكن الإقفال")
    if total > 0:  # صافي ربح → دائن الأرباح المبقاة
        items.append({"account_id": retained.id, "debit": 0, "credit": total})
    elif total < 0:  # صافي خسارة → مدين الأرباح المبقاة
        items.append({"account_id": retained.id, "debit": -total, "credit": 0})
    entry = AccountingEngine.create_entry(
        db=db, company_id=company_id, user_id=user_id,
        description=f"Closing entry FY {fy.name}",
        items=items, reference=f"FY-CLOSE-{fy.id}", date=fy.end_date,
    )
    return entry.id


@router.get("", response_model=List[schemas.FiscalYearOut])
def list_fiscal_years(
    is_closed: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    company_id = db.info["company_id"]
    q = db.query(models.FiscalYear).filter(models.FiscalYear.company_id == company_id)
    if is_closed is not None:
        q = q.filter(models.FiscalYear.is_closed == is_closed)
    return q.order_by(models.FiscalYear.start_date.desc()).all()


@router.get("/{fy_id}", response_model=schemas.FiscalYearOut)
def get_fiscal_year(fy_id: int, db: Session = Depends(get_db)):
    fy = db.get(models.FiscalYear, fy_id)
    if fy is None or fy.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fiscal year not found")
    return fy


@router.post("", response_model=schemas.FiscalYearOut, status_code=status.HTTP_201_CREATED)
def create_fiscal_year(
    payload: schemas.FiscalYearCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    # Check for overlap with existing fiscal years
    overlap = db.query(models.FiscalYear).filter(
        models.FiscalYear.company_id == company_id,
        models.FiscalYear.start_date <= payload.end_date,
        models.FiscalYear.end_date >= payload.start_date,
    ).first()
    if overlap:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Fiscal year overlaps with existing year '{overlap.name}'",
        )
    fy = models.FiscalYear(
        company_id=company_id,
        name=payload.name.strip(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_closed=payload.is_closed,
    )
    db.add(fy)
    db.flush()
    _ensure_periods(db, fy)
    db.commit()
    db.refresh(fy)
    audit(db, user, "create", "fiscal_year", fy, f"{fy.name} · {fy.start_date} → {fy.end_date}")
    return fy


@router.patch("/{fy_id}", response_model=schemas.FiscalYearOut)
def update_fiscal_year(
    fy_id: int,
    payload: schemas.FiscalYearUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    fy = db.get(models.FiscalYear, fy_id)
    if fy is None or fy.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fiscal year not found")
    data = payload.model_dump(exclude_unset=True)
    # Closing/reopening is always allowed; other edits are blocked once closed.
    only_toggle = set(data.keys()) <= {"is_closed"}
    if fy.is_closed and not only_toggle:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot modify a closed fiscal year")
    if "name" in data and data["name"] is not None:
        fy.name = data["name"].strip()
    if "start_date" in data:
        fy.start_date = data["start_date"]
    if "end_date" in data:
        fy.end_date = data["end_date"]
    if "is_closed" in data:
        fy.is_closed = data["is_closed"]
    # Re-check overlap after changes
    overlap = db.query(models.FiscalYear).filter(
        models.FiscalYear.id != fy_id,
        models.FiscalYear.company_id == db.info["company_id"],
        models.FiscalYear.start_date <= fy.end_date,
        models.FiscalYear.end_date >= fy.start_date,
    ).first()
    if overlap:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Updated fiscal year overlaps with existing year '{overlap.name}'",
        )
    created_next = None
    closing = data.get("is_closed") is True
    if closing:
        # 1) قيد الإقفال: تصفير الإيرادات والمصاريف في الأرباح المبقاة
        closing_entry_id = post_closing_entry(db, db.info["company_id"], user.id, fy)
        # 2) إغلاق كل أشهر السنة
        db.query(models.FiscalPeriod).filter(
            models.FiscalPeriod.fiscal_year_id == fy.id
        ).update({"is_closed": True}, synchronize_session=False)
        # 3) توليد السنة التالية تلقائيًا (بأشهرها)
        next_year = fy.end_date.year + 1
        exists = db.query(models.FiscalYear).filter(
            models.FiscalYear.company_id == db.info["company_id"],
            models.FiscalYear.start_date == date(next_year, 1, 1),
        ).first()
        if exists is None:
            created_next = models.FiscalYear(
                company_id=db.info["company_id"],
                name=f"FY {next_year}",
                start_date=date(next_year, 1, 1),
                end_date=date(next_year, 12, 31),
                is_closed=False,
            )
            db.add(created_next)
            db.flush()
            _ensure_periods(db, created_next)
    db.commit()
    db.refresh(fy)
    if created_next is not None:
        db.refresh(created_next)
    audit(db, user, "update", "fiscal_year", fy,
          ", ".join(data.keys()) + (" · قيد إقفال " + str(closing_entry_id) if closing and closing_entry_id else ""))
    return fy


@router.delete("/{fy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fiscal_year(fy_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    fy = db.get(models.FiscalYear, fy_id)
    if fy is None or fy.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fiscal year not found")
    if fy.is_closed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot delete a closed fiscal year")
    db.delete(fy)
    db.commit()
    audit(db, user, "delete", "fiscal_year", fy_id, f"fiscal year {fy_id}")


# ---------------------------------------------------------------- الأشهر المالية
@router.get("/{fy_id}/periods", response_model=List[schemas.FiscalPeriodOut])
def list_periods(fy_id: int, db: Session = Depends(get_db)):
    fy = db.get(models.FiscalYear, fy_id)
    if fy is None or fy.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fiscal year not found")
    _ensure_periods(db, fy)
    db.commit()
    return db.query(models.FiscalPeriod).filter(
        models.FiscalPeriod.fiscal_year_id == fy_id
    ).order_by(models.FiscalPeriod.start_date).all()


@router.patch("/{fy_id}/periods/{period_id}", response_model=schemas.FiscalPeriodOut)
def toggle_period(
    fy_id: int,
    period_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """إقفال/فتح شهر مالي: الإقفال يمنع الترحيل في نطاقه عبر حارس المحرك."""
    fy = db.get(models.FiscalYear, fy_id)
    if fy is None or fy.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fiscal year not found")
    if fy.is_closed:
        raise HTTPException(status.HTTP_409_CONFLICT, "السنة المالية مقفولة بالكامل")
    period = db.query(models.FiscalPeriod).filter(
        models.FiscalPeriod.id == period_id,
        models.FiscalPeriod.fiscal_year_id == fy_id,
        models.FiscalPeriod.company_id == db.info["company_id"],
    ).first()
    if period is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Period not found")
    is_closed = payload.get("is_closed")
    if not isinstance(is_closed, bool):
        raise HTTPException(422, "is_closed مطلوب (true/false)")
    period.is_closed = is_closed
    db.commit()
    db.refresh(period)
    audit(db, user, "update", "fiscal_period", period,
          f"{'إقفال' if is_closed else 'فتح'} شهر {period.name} ({fy.name})")
    return period
