"""Safes (cash boxes) and bank accounts (company-scoped master data)."""
from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_manager


safes = APIRouter(prefix="/safes", tags=["safes & banks"], dependencies=[Depends(get_current_user)])
banks = APIRouter(prefix="/banks", tags=["safes & banks"], dependencies=[Depends(get_current_user)])


def _account_statement(db: Session, acc: models.ChartAccount, title: str, code: str, date_from: Optional[date], date_to: Optional[date]) -> schemas.AccountStatementOut:
    """كشف حساب الخزينة/البنك من دفتر الأستاذ: كل الحركات على الحساب المحاسبي (سندات + شيكات + غيرها)."""
    base = (
        db.query(models.JournalItem, models.JournalEntry)
        .join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id)
        .filter(
            models.JournalItem.account_id == acc.id,
            models.JournalEntry.company_id == db.info["company_id"],
        )
    )
    if date_from:
        base = base.filter(models.JournalEntry.date >= date_from)
    if date_to:
        base = base.filter(models.JournalEntry.date <= date_to)
    period = base.order_by(models.JournalEntry.date, models.JournalItem.id).all()

    # رصيد ما قبل الفترة = الرصيد الحالي للحساب − حركات الفترة وما بعدها (أصل: مدين − دائن)
    later_sum = Decimal("0")
    if date_from:
        later_sum = (
            db.query(func.coalesce(func.sum(models.JournalItem.debit - models.JournalItem.credit), 0))
            .join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id)
            .filter(
                models.JournalItem.account_id == acc.id,
                models.JournalEntry.company_id == db.info["company_id"],
                models.JournalEntry.date >= date_from,
            )
            .scalar()
        )
    running = Decimal("0") if date_from is None else (acc.balance or 0) - (later_sum or 0)
    opening = running
    lines: List[schemas.AccountStatementLine] = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for item, entry in period:
        running += (item.debit or 0) - (item.credit or 0)
        total_debit += item.debit or 0
        total_credit += item.credit or 0
        lines.append(
            schemas.AccountStatementLine(
                entry_id=entry.id,
                date=entry.date,
                description=entry.description,
                reference=entry.reference,
                debit=item.debit or 0,
                credit=item.credit or 0,
                balance=running,
            )
        )
    return schemas.AccountStatementOut(
        account_name=title,
        account_code=code,
        opening=opening,
        closing=running,
        total_debit=total_debit,
        total_credit=total_credit,
        lines=lines,
    )


def _company_object_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None or obj.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} {obj_id} not found")
    return obj


# ---------- Safes ----------
@safes.get("", response_model=List[schemas.SafeOut])
def list_safes(branch_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.Safe)
    if branch_id is not None:
        q = q.filter(models.Safe.branch_id == branch_id)
    return q.order_by(models.Safe.id).all()


@safes.get("/{safe_id}", response_model=schemas.SafeOut)
def get_safe(safe_id: int, db: Session = Depends(get_db)):
    safe = db.get(models.Safe, safe_id)
    if safe is None or safe.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Safe not found")
    return safe


@safes.get("/{safe_id}/statement", response_model=schemas.AccountStatementOut)
def safe_statement(
    safe_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """كشف حركة الخزينة من دفتر الأستاذ (يشمل السندات والشيكات وكل الحركات)."""
    safe = _company_object_or_404(db, models.Safe, safe_id)
    if safe.chart_account_id is None:
        raise HTTPException(422, "لا يوجد حساب محاسبي مرتبط بالخزينة")
    acc = db.get(models.ChartAccount, safe.chart_account_id)
    return _account_statement(db, acc, safe.name, safe.code, date_from, date_to)


@safes.post("", response_model=schemas.SafeOut, status_code=status.HTTP_201_CREATED)
def create_safe(payload: schemas.SafeCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    branch = db.query(models.Branch).filter(
        models.Branch.id == payload.branch_id,
        models.Branch.company_id == company_id,
        models.Branch.is_active.is_(True),
    ).one_or_none()
    if branch is None:
        raise HTTPException(422, "Choose an active branch belonging to this company")
    company = db.get(models.Company, company_id)
    if company and company.max_safes_per_branch is not None:
        count = db.query(models.Safe).filter(models.Safe.branch_id == branch.id).count()
        if count >= company.max_safes_per_branch:
            raise HTTPException(status.HTTP_409_CONFLICT, "Branch safe limit reached")
    code = (payload.code or "").strip() or unique_code(db, models.Safe, company_id, payload.name, "SAFE", max_length=50)
    if db.query(models.Safe).filter(models.Safe.company_id == company_id, models.Safe.code == code).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Safe code already exists")
    s = models.Safe(company_id=company_id, branch_id=branch.id, name=payload.name.strip(), code=code, balance=payload.opening_balance, is_active=payload.is_active)  # type: ignore
    # Auto-link a Chart of Accounts entry (cash) for this safe
    cash_parent = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code.in_(("1011", "1111"))).first()
    if cash_parent is not None:
        acc = models.ChartAccount(company_id=company_id, code=unique_code(db, models.ChartAccount, company_id, payload.name, "CASH", max_length=50), name=f"Safe: {payload.name.strip()}", type="asset", parent_id=cash_parent.id, is_group=False, balance=payload.opening_balance, is_active=payload.is_active)
        db.add(acc)
        db.flush()
        s.chart_account_id = acc.id
    db.add(s)
    audit(db, user, "create", "safe", s, f"{s.code} · {s.name}")
    db.commit()
    db.refresh(s)
    return s


@safes.patch("/{safe_id}", response_model=schemas.SafeOut)
def update_safe(
    safe_id: int,
    payload: schemas.SafeUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    safe = db.get(models.Safe, safe_id)
    if safe is None or safe.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Safe not found")
    data = payload.model_dump(exclude_unset=True)
    branch_id = data.pop("branch_id", None)
    if branch_id is not None:
        branch = db.query(models.Branch).filter(
            models.Branch.id == branch_id,
            models.Branch.company_id == db.info["company_id"],
        ).one_or_none()
        if branch is None:
            raise HTTPException(422, "Branch does not belong to this company")
        safe.branch_id = branch_id
    if "code" in data and data["code"] is not None:
        data["code"] = data["code"].strip() or unique_code(db, models.Safe, db.info["company_id"], data.get("name", safe.name), "SAFE")
    for key, value in data.items():
        setattr(safe, key, value)
    audit(db, user, "update", "safe", safe, "، ".join(data.keys()))
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Safe code already exists or update violates a constraint") from exc
    db.refresh(safe)
    return safe


def _ensure_cash_location_deletable(db: Session, label: str, chart_account_id=None, safe_id=None, bank_id=None):
    """حاجز دفتر الأستاذ: موقع نقدية عليه حركة لا يُحذف — يُعطَّل بدلاً من حذفه.

    الحركة: سندات قبض/صرف مُرحّلة عليه، شيكات مسحوبة عليه (للبنوك)، أو قيود
    محاسبية على الحساب المرتبط به في شجرة الحسابات."""
    company_id = db.info["company_id"]
    reasons: List[str] = []
    posted = db.query(models.Payment.id).filter(
        models.Payment.company_id == company_id, models.Payment.status == "posted"
    )
    if safe_id is not None and posted.filter(models.Payment.safe_id == safe_id).first() is not None:
        reasons.append("سندات قبض/صرف مسجلة عليه")
    if bank_id is not None:
        if posted.filter(models.Payment.bank_id == bank_id).first() is not None:
            reasons.append("سندات قبض/صرف مسجلة عليه")
        if db.query(models.Cheque.id).filter(
            models.Cheque.company_id == company_id, models.Cheque.bank_id == bank_id
        ).first() is not None:
            reasons.append("شيكات مسحوبة عليه")
    if chart_account_id is not None and db.query(models.JournalItem.id).filter(
        models.JournalItem.account_id == chart_account_id
    ).first() is not None:
        reasons.append("قيود محاسبية على حسابه المرتبط بشجرة الحسابات")
    if reasons:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"لا يمكن حذف {label}: " + " و".join(sorted(set(reasons))) + " — عطّله بدلاً من حذفه",
        )


@safes.delete("/{safe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_safe(safe_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    s = db.get(models.Safe, safe_id)
    if s is None or s.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Safe not found")
    _ensure_cash_location_deletable(db, "الخزينة", chart_account_id=s.chart_account_id, safe_id=safe_id)
    audit(db, user, "delete", "safe", safe_id, f"safe {safe_id}")
    db.delete(s)
    db.commit()


# ---------- Banks ----------
@banks.get("", response_model=List[schemas.BankOut])
def list_banks(branch_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.Bank)
    if branch_id is not None:
        q = q.filter(models.Bank.branch_id == branch_id)
    return q.order_by(models.Bank.id).all()


@banks.get("/{bank_id}", response_model=schemas.BankOut)
def get_bank(bank_id: int, db: Session = Depends(get_db)):
    bank = (
        db.query(models.Bank)
        .filter(models.Bank.id == bank_id, models.Bank.company_id == db.info["company_id"])
        .first()
    )
    if bank is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Bank {bank_id} not found")
    return bank


@banks.get("/{bank_id}/statement", response_model=schemas.AccountStatementOut)
def bank_statement(
    bank_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """كشف حركة البنك من دفتر الأستاذ (يشمل السندات والشيكات وكل الحركات)."""
    bank = _company_object_or_404(db, models.Bank, bank_id)
    if bank.chart_account_id is None:
        raise HTTPException(422, "لا يوجد حساب محاسبي مرتبط بالبنك")
    acc = db.get(models.ChartAccount, bank.chart_account_id)
    return _account_statement(db, acc, bank.name, bank.code, date_from, date_to)


@banks.post("", response_model=schemas.BankOut, status_code=status.HTTP_201_CREATED)
def create_bank(payload: schemas.BankCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    code = (payload.code or "").strip() or unique_code(db, models.Bank, company_id, payload.name, "BANK", max_length=50)
    if db.query(models.Bank).filter(models.Bank.company_id == company_id, models.Bank.code == code).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Bank code already exists")
    branch_id = payload.branch_id
    if branch_id is not None:
        branch = db.query(models.Branch).filter(
            models.Branch.id == branch_id,
            models.Branch.company_id == company_id,
            models.Branch.is_active.is_(True),
        ).first()
        if branch is None:
            raise HTTPException(422, "فرع غير موجود في هذه الشركة")
    b = models.Bank(company_id=company_id, name=payload.name.strip(), code=code, account_number=payload.account_number, balance=payload.opening_balance, is_active=payload.is_active, branch_id=branch_id)  # type: ignore
    # Auto-link a Chart of Accounts entry (bank) for this bank
    bank_parent = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code.in_(("1010", "1112"))).first()
    if bank_parent is not None:
        acc = models.ChartAccount(company_id=company_id, code=unique_code(db, models.ChartAccount, company_id, payload.name, "BANK", max_length=50), name=f"Bank: {payload.name.strip()}", type="asset", parent_id=bank_parent.id, is_group=False, balance=payload.opening_balance, is_active=payload.is_active)
        db.add(acc)
        db.flush()
        b.chart_account_id = acc.id
    db.add(b)
    audit(db, user, "create", "bank", b, f"{b.code} · {b.name}")
    db.commit()
    db.refresh(b)
    return b


@banks.patch("/{bank_id}", response_model=schemas.BankOut)
def update_bank(
    bank_id: int,
    payload: schemas.BankUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    b = db.get(models.Bank, bank_id)
    if b is None or b.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        b.name = data["name"].strip()
    if "code" in data and data["code"] is not None:
        b.code = data["code"].strip() or unique_code(db, models.Bank, db.info["company_id"], b.name, "BANK")
    if "account_number" in data:
        b.account_number = data["account_number"].strip() if data["account_number"] else None
    if "is_active" in data and data["is_active"] is not None:
        b.is_active = data["is_active"]
    audit(db, user, "update", "bank", b, "، ".join(data.keys()))
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Bank code already exists or update violates a constraint") from exc
    db.refresh(b)
    return b


@banks.delete("/{bank_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank(bank_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    b = db.get(models.Bank, bank_id)
    if b is None or b.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank not found")
    _ensure_cash_location_deletable(db, "البنك", chart_account_id=b.chart_account_id, bank_id=bank_id)
    audit(db, user, "delete", "bank", bank_id, f"bank {bank_id}")
    db.delete(b)
    db.commit()