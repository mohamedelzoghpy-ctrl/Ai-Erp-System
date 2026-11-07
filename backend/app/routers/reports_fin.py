from typing import List, Optional
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models, schemas, deps

router = APIRouter(prefix="/reports/financial", tags=["Financial Reports"])


def _parse_date(value: Optional[str], default: Optional[date] = None) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date: {value}")
    return default or date.today()


def _balance_as_of(db: Session, company_id: int, account: models.ChartAccount, as_of: date):
    """Account balance considering only journal entries dated <= as_of."""
    d, c = db.query(
        func.coalesce(func.sum(models.JournalItem.debit), 0),
        func.coalesce(func.sum(models.JournalItem.credit), 0),
    ).join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id).filter(
        models.JournalItem.company_id == company_id,
        models.JournalItem.account_id == account.id,
        models.JournalEntry.date <= as_of,
    ).one()
    delta = (d or 0) - (c or 0)
    if account.type in ("liability", "equity", "revenue"):
        return -(delta)
    return delta


@router.get("/trial-balance")
def get_trial_balance(
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    cutoff = _parse_date(as_of)
    accounts = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id).all()
    return [
        {"code": a.code, "name": a.name, "balance": _balance_as_of(db, company_id, a, cutoff), "type": a.type}
        for a in accounts
    ]


@router.get("/profit-loss")
def get_profit_loss(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    start = _parse_date(date_from, date(1900, 1, 1))
    end = _parse_date(date_to, date.today())

    # Revenue = sum(credit - debit) for revenue accounts in period
    rev_q = db.query(func.coalesce(func.sum(models.JournalItem.credit - models.JournalItem.debit), 0)).join(
        models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id
    ).join(models.ChartAccount, models.ChartAccount.id == models.JournalItem.account_id).filter(
        models.JournalItem.company_id == company_id,
        models.ChartAccount.type == "revenue",
        models.JournalEntry.date >= start,
        models.JournalEntry.date <= end,
    ).scalar() or 0

    exp_q = db.query(func.coalesce(func.sum(models.JournalItem.debit - models.JournalItem.credit), 0)).join(
        models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id
    ).join(models.ChartAccount, models.ChartAccount.id == models.JournalItem.account_id).filter(
        models.JournalItem.company_id == company_id,
        models.ChartAccount.type == "expense",
        models.JournalEntry.date >= start,
        models.JournalEntry.date <= end,
    ).scalar() or 0

    return {
        "total_revenue": rev_q,
        "total_expenses": exp_q,
        "net_profit": rev_q - exp_q,
        "date_from": str(start),
        "date_to": str(end),
    }


@router.get("/balance-sheet")
def get_balance_sheet(
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    cutoff = _parse_date(as_of)
    accounts = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id).all()
    assets = sum(_balance_as_of(db, company_id, a, cutoff) for a in accounts if a.type == "asset")
    liabilities = sum(_balance_as_of(db, company_id, a, cutoff) for a in accounts if a.type == "liability")
    equity = sum(_balance_as_of(db, company_id, a, cutoff) for a in accounts if a.type == "equity")
    return {
        "total_assets": assets,
        "total_liabilities": liabilities,
        "total_equity": equity,
        "is_balanced": assets == (liabilities + equity),
        "as_of": str(cutoff),
    }


@router.get("/profit-loss-detail")
def get_profit_loss_detail(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    start = _parse_date(date_from, date(1900, 1, 1))
    end = _parse_date(date_to, date.today())

    # Per-account revenue/expense in the period (all accounts, including zero)
    accounts = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id,
        models.ChartAccount.type.in_(["revenue", "expense"]),
    ).order_by(models.ChartAccount.code).all()

    result = []
    for acc in accounts:
        rev, exp = db.query(
            func.coalesce(func.sum(models.JournalItem.credit - models.JournalItem.debit), 0),
            func.coalesce(func.sum(models.JournalItem.debit - models.JournalItem.credit), 0),
        ).join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id).filter(
            models.JournalItem.company_id == company_id,
            models.JournalItem.account_id == acc.id,
            models.JournalEntry.date >= start,
            models.JournalEntry.date <= end,
        ).one()
        amount = (rev if acc.type == "revenue" else exp) or 0
        result.append({"code": acc.code, "name": acc.name, "type": acc.type, "amount": amount})
    return result
