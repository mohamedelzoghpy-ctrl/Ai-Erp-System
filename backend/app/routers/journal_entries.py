"""Manual Journal Entries — company-scoped double-entry accounting.

Maker-checker: when JE_APPROVAL_THRESHOLD > 0, a staff-created entry whose total
exceeds the threshold is parked as pending_approval (balances untouched) until a
manager/admin approves it."""
import os
from typing import List, Optional

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..accounting import AccountingEngine, ensure_fiscal_open
from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager, user_role

router = APIRouter(
    prefix="/journal-entries",
    tags=["journal entries"],
    dependencies=[Depends(get_current_user)],
)

# حد الاعتماد: 0 = معطّل (افتراضي). JE_APPROVAL_THRESHOLD=10000 → القيود فوق 10 آلاف تحتاج اعتماد مدير
APPROVAL_THRESHOLD = Decimal(os.getenv("JE_APPROVAL_THRESHOLD", "0") or "0")


@router.get("", response_model=List[schemas.JournalEntryOut])
def list_journal_entries(
    skip: int = 0,
    limit: int = 100,
    account_id: Optional[int] = None,
    cost_center_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    company_id = db.info["company_id"]
    q = db.query(models.JournalEntry).filter(models.JournalEntry.company_id == company_id)
    # join واحد بمسار الترشيح (بدل join مزدوج يعمل cross join بين البنود)
    filters = []
    if account_id is not None:
        filters.append(models.JournalItem.account_id == account_id)
    if cost_center_id is not None:
        filters.append(models.JournalItem.cost_center_id == cost_center_id)
    if filters:
        q = q.join(models.JournalItem).filter(and_(*filters)).distinct()
    return q.offset(skip).limit(limit).all()


@router.get("/pending", response_model=List[schemas.JournalEntryOut])
def list_pending(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    return db.query(models.JournalEntry).filter(
        models.JournalEntry.company_id == company_id,
        models.JournalEntry.status == "pending_approval",
    ).order_by(models.JournalEntry.id).all()


@router.get("/{je_id}", response_model=schemas.JournalEntryOut)
def get_journal_entry(je_id: int, db: Session = Depends(get_db)):
    je = db.get(models.JournalEntry, je_id)
    if je is None or je.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    return je


@router.post("", response_model=schemas.JournalEntryOut, status_code=status.HTTP_201_CREATED)
def create_journal_entry(
    payload: schemas.JournalEntryCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    company_id = db.info["company_id"]
    items = [
        {
            "account_id": item.account_id,
            "debit": item.debit,
            "credit": item.credit,
            "cost_center_id": item.cost_center_id,
            "notes": item.notes,
        }
        for item in payload.items
    ]
    # Maker-checker: حد الشركة (إن ضُبط) وإلا متغير البيئة — موظف + قيد فوق الحد → انتظار اعتماد
    company_threshold = db.query(models.Company.je_approval_threshold).filter(
        models.Company.id == company_id
    ).scalar()
    threshold = company_threshold if company_threshold is not None else APPROVAL_THRESHOLD
    needs_approval = (
        threshold is not None and Decimal(str(threshold)) > 0
        and user_role(user) not in ("admin", "manager")
        and sum((i["debit"] for i in items), Decimal("0")) > Decimal(str(threshold))
    )
    try:
        je = AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=payload.description,
            reference=payload.reference,
            items=items,
            date=payload.date,
            status="pending_approval" if needs_approval else "posted",
        )
    except ValueError as exc:
        # بند بطرفين أو قيد غير متوازن — مدخل مستخدم فيُرد 422 لا 500
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.refresh(je)
    audit(db, user, "create", "journal_entry", je,
          f"Ref: {je.reference or '—'}" + (" · بانتظار الاعتماد" if needs_approval else ""))
    db.commit()
    return je


@router.post("/{je_id}/approve", response_model=schemas.JournalEntryOut)
def approve_journal_entry(
    je_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """اعتماد قيد معلّق: تُطبق أرصدته وتُرحّل."""
    je = db.get(models.JournalEntry, je_id)
    if je is None or je.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    AccountingEngine.approve_entry(db, db.info["company_id"], je, user.id)
    audit(db, user, "approve", "journal_entry", je, f"اعتماد قيد {je.id} — {je.description}")
    db.commit()
    db.refresh(je)
    return je


@router.post("/{je_id}/reject")
def reject_journal_entry(
    je_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """رفض قيد معلّق: يُحذف (لم يُرحّل أصلًا فلا أثر دفتري)."""
    je = db.get(models.JournalEntry, je_id)
    if je is None or je.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    if je.status != "pending_approval":
        raise HTTPException(status.HTTP_409_CONFLICT, "القيد ليس في حالة انتظار اعتماد")
    audit(db, user, "reject", "journal_entry", je.id, f"رفض قيد {je.id} — {je.description}")
    db.delete(je)
    db.commit()
    return {"rejected": je_id, "detail": "تم رفض القيد وحذفه"}


@router.patch("/{je_id}", response_model=schemas.JournalEntryOut)
def update_journal_entry(
    je_id: int,
    payload: schemas.JournalEntryUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    je = db.get(models.JournalEntry, je_id)
    if je is None or je.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    data = payload.model_dump(exclude_unset=True)
    # قيد في سنة مقفولة مجمّد: لا تعديل (ولا تحويل تاريخه إلى سنة مقفولة)
    ensure_fiscal_open(db, db.info["company_id"], je.date)
    if "date" in data and data["date"] is not None:
        ensure_fiscal_open(db, db.info["company_id"], data["date"])
        je.date = data["date"]
    if "description" in data:
        je.description = data["description"]
    if "reference" in data:
        je.reference = data["reference"]
    audit(db, user, "update", "journal_entry", je, ", ".join(data.keys()))
    db.commit()
    db.refresh(je)
    return je


@router.delete("/{je_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_journal_entry(je_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """حذف قيد: المسودة/المرفوض/المعلق يُحذف نهائيًا (بلا أثر أرصدة)،
    أما المُرحّل (posted) فلا يُحذف أبدًا — يُعكَس بقيد معاكس مرجعيه VOID-{id}
    ويُوسم voided؛ الأثر الصافي صفر والدفاتر تحتفظ بالأثر الكامل."""
    je = db.get(models.JournalEntry, je_id)
    if je is None or je.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    # قيد في سنة مقفولة لا يُمس — الأرشيف المحاسبي غير قابل للطمس
    ensure_fiscal_open(db, db.info["company_id"], je.date)

    if je.status == "voided":
        raise HTTPException(status.HTTP_409_CONFLICT, f"القيد مُعكوس مسبقًا بالقيد VOID-{je_id} ولا يمكن عكسه مرتين")

    if je.status == "posted":
        # عكس آلي: قيد معاكس بنفس البنود معكوسة + وسم الأصل voided
        reversal = (
            db.query(models.JournalEntry)
            .filter(
                models.JournalEntry.company_id == db.info["company_id"],
                models.JournalEntry.reference == f"VOID-{je.id}",
            )
            .one_or_none()
        )
        if reversal is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"يوجد عكس سابق بالقيد #{reversal.id}")
        items = [
            {"account_id": ji.account_id, "debit": ji.credit, "credit": ji.debit, "cost_center_id": ji.cost_center_id}
            for ji in je.items
        ]
        AccountingEngine.create_entry(
            db=db,
            company_id=db.info["company_id"],
            user_id=user.id,
            description=f"عكس القيد #{je.id}: {je.description}",
            items=items,
            reference=f"VOID-{je.id}",
        )
        je.status = "voided"  # type: ignore[assignment]
        audit(db, user, "void", "journal_entry", je, f"عكس القيد #{je.id} بقيد VOID-{je.id}")
        db.commit()
        return None

    # pending_approval / rejected: أرصدتها لم تُطبق أصلًا — حذف مباشر بلا مساس بالأرصدة
    db.delete(je)
    audit(db, user, "delete", "journal_entry", je_id, f"journal entry {je_id} ({je.status})")
    db.commit()
    return None