"""القيود المتكررة: قوالب (إيجار/رواتب/أقساط) تُرحّل عند استحقاقها بضغطة زر أو دفعةً.

/run يرحّل كل القوالب المستحقة (next_run_date <= اليوم) ويقدّم next_run_date شهرًا،
فيظل القالب يعمل شهر بعد شهر دون تكرار القيد لنفس الشهر."""
import calendar
from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..accounting import AccountingEngine
from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager
from ..pagination import paginate

router = APIRouter(prefix="/recurring-journals", tags=["recurring journals"], dependencies=[Depends(get_current_user)])


def _get(db: Session, template_id: int) -> models.RecurringJournal:
    rj = db.query(models.RecurringJournal).filter(
        models.RecurringJournal.id == template_id,
        models.RecurringJournal.company_id == db.info["company_id"],
    ).first()
    if rj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recurring journal not found")
    return rj


def _validate_items(db: Session, company_id: int, items) -> list:
    """تسطيح البنود والتأكد من توازنها (نفس عقد بنود القيد العادي)."""
    flat = []
    for it in items:
        flat.append({
            "account_id": it.account_id,
            "debit": str(it.debit or Decimal("0")),
            "credit": str(it.credit or Decimal("0")),
            "cost_center_id": it.cost_center_id,
            "notes": it.notes,
        })
    total_d = sum((Decimal(i["debit"]) for i in flat), Decimal("0"))
    total_c = sum((Decimal(i["credit"]) for i in flat), Decimal("0"))
    if total_d != total_c:
        raise HTTPException(422, f"القالب غير موزون: مدين {total_d} ≠ دائن {total_c}")
    if total_d == 0:
        raise HTTPException(422, "لا يمكن قالب بمبالغ صفرية")
    return flat


def _next_month(d: date, day_of_month: int) -> date:
    month = d.month + 1 if d.month < 12 else 1
    year = d.year + (1 if d.month == 12 else 0)
    return date(year, month, min(day_of_month, calendar.monthrange(year, month)[1]))


@router.get("", response_model=List[schemas.RecurringJournalOut])
def list_recurring(response: Response, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(models.RecurringJournal).filter(
        models.RecurringJournal.company_id == db.info["company_id"]
    ).order_by(models.RecurringJournal.next_run_date)
    return paginate(q, response, skip, limit, models.RecurringJournal.next_run_date)


@router.get("/due", response_model=List[schemas.RecurringJournalOut])
def list_due(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """القوالب المستحقة الآن (next_run_date <= اليوم) — تغذي شارة «قيود مستحقة» في الداشبورد."""
    return db.query(models.RecurringJournal).filter(
        models.RecurringJournal.company_id == db.info["company_id"],
        models.RecurringJournal.is_active.is_(True),
        models.RecurringJournal.next_run_date <= date.today(),
    ).order_by(models.RecurringJournal.next_run_date).all()


@router.post("", response_model=schemas.RecurringJournalOut, status_code=status.HTTP_201_CREATED)
def create_recurring(
    payload: schemas.RecurringJournalCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    rj = models.RecurringJournal(
        company_id=db.info["company_id"],
        name=payload.name.strip(),
        description=payload.description,
        reference=payload.reference,
        frequency="monthly",
        day_of_month=payload.day_of_month,
        next_run_date=payload.next_run_date,
        is_active=payload.is_active,
        items=_validate_items(db, db.info["company_id"], payload.items),
        created_by=user.id,
    )
    db.add(rj)
    db.commit()
    db.refresh(rj)
    audit(db, user, "create", "recurring_journal", rj, f"{rj.name} · استحقاق {rj.next_run_date}")
    return rj


@router.patch("/{template_id}", response_model=schemas.RecurringJournalOut)
def update_recurring(
    template_id: int,
    payload: schemas.RecurringJournalUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    rj = _get(db, template_id)
    data = payload.model_dump(exclude_unset=True)
    if "items" in data and data["items"] is not None:
        rj.items = _validate_items(db, db.info["company_id"], payload.items)  # type: ignore[arg-type]
        data.pop("items")
    for key, value in data.items():
        setattr(rj, key, value)
    db.commit()
    db.refresh(rj)
    audit(db, user, "update", "recurring_journal", rj, ", ".join(payload.model_dump(exclude_unset=True).keys()))
    return rj


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring(
    template_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    rj = _get(db, template_id)
    audit(db, user, "delete", "recurring_journal", rj.id, f"قالب {rj.name}")
    db.delete(rj)
    db.commit()
    return None


@router.post("/run")
def run_due(
    template_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """ترحيل المستحق: قالب واحد إن حُدد template_id، أو كل المستحق (للزر الجماعي)."""
    company_id = db.info["company_id"]
    today = date.today()
    q = db.query(models.RecurringJournal).filter(
        models.RecurringJournal.company_id == company_id,
        models.RecurringJournal.is_active.is_(True),
        models.RecurringJournal.next_run_date <= today,
    )
    if template_id is not None:
        q = q.filter(models.RecurringJournal.id == template_id)
    due = q.order_by(models.RecurringJournal.next_run_date).all()
    if template_id is not None and not due:
        raise HTTPException(status.HTTP_409_CONFLICT, "القالب غير مستحق بعد — استحقاقه لاحقًا")

    ran = []
    for rj in due:
        entry = AccountingEngine.create_entry(
            db=db, company_id=company_id, user_id=user.id,
            description=f"{rj.description} ({rj.next_run_date.strftime('%Y-%m')})",
            reference=rj.reference,
            items=[dict(i) for i in (rj.items or [])],
            date=rj.next_run_date,
        )
        rj.last_run_entry_id = entry.id  # type: ignore
        rj.next_run_date = _next_month(rj.next_run_date, rj.day_of_month)  # type: ignore
        audit(db, user, "run", "recurring_journal", rj, f"ترحيل قالب {rj.name} → قيد JE-{entry.id} · الاستحقاق القادم {rj.next_run_date}")
        ran.append({"template_id": rj.id, "entry_id": entry.id})
    db.commit()
    return {"ran": ran, "count": len(ran)}
