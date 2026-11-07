"""General Ledger — read-only view of all journal entries with account details."""
from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(
    prefix="/general-ledger",
    tags=["general ledger"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=List[schemas.LedgerEntryOut])
def get_general_ledger(
    account_id: Optional[int] = None,
    cost_center_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db),
):
    company_id = db.info["company_id"]
    q = (
        db.query(models.JournalItem)
        .join(models.JournalEntry, models.JournalItem.entry_id == models.JournalEntry.id)
        .filter(models.JournalEntry.company_id == company_id)
    )
    if account_id is not None:
        q = q.filter(models.JournalItem.account_id == account_id)
    if cost_center_id is not None:
        q = q.filter(models.JournalItem.cost_center_id == cost_center_id)
    if date_from is not None:
        q = q.filter(models.JournalEntry.date >= date_from)
    if date_to is not None:
        q = q.filter(models.JournalEntry.date <= date_to)
    q = q.order_by(models.JournalEntry.date, models.JournalEntry.id, models.JournalItem.id)
    items = q.offset(skip).limit(limit).all()
    return [schemas.LedgerEntryOut.from_journal_item(item.entry, item) for item in items]


@router.get("/account/{account_id}", response_model=List[schemas.LedgerEntryOut])
def get_account_ledger(
    account_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db),
):
    """Get all transactions for a specific account."""
    company_id = db.info["company_id"]
    acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.id == account_id,
        models.ChartAccount.company_id == company_id,
    ).first()
    if not acc:
        raise HTTPException(404, "Account not found")

    q = (
        db.query(models.JournalItem)
        .join(models.JournalEntry, models.JournalItem.entry_id == models.JournalEntry.id)
        .filter(models.JournalItem.account_id == account_id)
    )
    if date_from is not None:
        q = q.filter(models.JournalEntry.date >= date_from)
    if date_to is not None:
        q = q.filter(models.JournalEntry.date <= date_to)
    q = q.order_by(models.JournalEntry.date, models.JournalEntry.id, models.JournalItem.id)
    items = q.offset(skip).limit(limit).all()
    return [schemas.LedgerEntryOut.from_journal_item(item.entry, item) for item in items]


@router.get("/cost-center/{cost_center_id}", response_model=List[schemas.LedgerEntryOut])
def get_cost_center_ledger(
    cost_center_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = 0,
    limit: int = 500,
    db: Session = Depends(get_db),
):
    """Get all transactions for a specific cost center."""
    company_id = db.info["company_id"]
    cc = db.query(models.CostCenter).filter(
        models.CostCenter.id == cost_center_id,
        models.CostCenter.company_id == company_id,
    ).first()
    if not cc:
        raise HTTPException(404, "Cost center not found")

    q = (
        db.query(models.JournalItem)
        .join(models.JournalEntry, models.JournalItem.entry_id == models.JournalEntry.id)
        .filter(models.JournalItem.cost_center_id == cost_center_id)
    )
    if date_from is not None:
        q = q.filter(models.JournalEntry.date >= date_from)
    if date_to is not None:
        q = q.filter(models.JournalEntry.date <= date_to)
    q = q.order_by(models.JournalEntry.date, models.JournalEntry.id, models.JournalItem.id)
    items = q.offset(skip).limit(limit).all()
    return [schemas.LedgerEntryOut.from_journal_item(item.entry, item) for item in items]