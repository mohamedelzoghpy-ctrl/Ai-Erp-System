"""Manual Journal Entries — company-scoped double-entry accounting."""
from typing import List, Optional

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..accounting import AccountingEngine
from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(
    prefix="/journal-entries",
    tags=["journal entries"],
    dependencies=[Depends(get_current_user)],
)


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
    if account_id is not None:
        q = q.join(models.JournalItem).filter(models.JournalItem.account_id == account_id)
    if cost_center_id is not None:
        q = q.join(models.JournalItem).filter(models.JournalItem.cost_center_id == cost_center_id)
    return q.offset(skip).limit(limit).all()


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
    user: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    je = AccountingEngine.create_entry(
        db=db,
        company_id=company_id,
        user_id=user.id,
        description=payload.description,
        reference=payload.reference,
        items=[
            {
                "account_id": item.account_id,
                "debit": item.debit,
                "credit": item.credit,
                "cost_center_id": item.cost_center_id,
                "notes": item.notes,
            }
            for item in payload.items
        ],
        date=payload.date,
    )
    db.refresh(je)
    audit(db, user, "create", "journal_entry", je, f"Ref: {je.reference or '—'}")
    db.commit()
    return je


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
    if "date" in data:
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
    je = db.get(models.JournalEntry, je_id)
    if je is None or je.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    # Reverse the account-balance deltas posted by this entry before deleting it
    for ji in je.items:
        acc = db.query(models.ChartAccount).get(ji.account_id)
        if acc is not None:
            delta = ji.debit - ji.credit
            if acc.type in ("liability", "equity", "revenue"):
                acc.balance += delta
            else:
                acc.balance -= delta
    db.delete(je)
    audit(db, user, "delete", "journal_entry", je_id, f"journal entry {je_id}")
    db.commit()
    return None