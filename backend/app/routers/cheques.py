"""حافظة الشيكات: cheques received from customers / issued to suppliers, with lifecycle actions.

Every cheque is backed by a Payment voucher (method='cheque') created via create_payment, so
party balances, statements and the vouchers table stay consistent. The cheque row itself only
tracks the lifecycle; the money moves between the portfolio accounts (1115 حافظة الشيكات /
2111 شيكات مصروفة) and the safe/bank when the lifecycle actions run.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..accounting import AccountingEngine, link_bank_coa, link_safe_coa, seed_default_coa
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager
from .payments import create_payment, void_payment

router = APIRouter(prefix="/cheques", tags=["cheques"], dependencies=[Depends(get_current_user)])


def _out(c: models.Cheque) -> models.Cheque:
    c.bank_name = c.bank.name if c.bank else None  # type: ignore[attr-defined]
    c.bank_branch_name = (c.bank.branch.name if c.bank and c.bank.branch else None)  # type: ignore[attr-defined]
    c.company_name = c.company.name if c.company else None  # type: ignore[attr-defined]
    return c


def _get_or_404(db: Session, cheque_id: int) -> models.Cheque:
    c = db.get(models.Cheque, cheque_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Cheque {cheque_id} not found")
    return c


def _portfolio_acc_id(db: Session, direction: str) -> int:
    code = "1115" if direction == "received" else "2111"
    acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == code
    ).first()
    if acc is None:
        raise HTTPException(422, f"حساب {code} غير موجود في شجرة الحسابات")
    return acc.id


@router.get("", response_model=List[schemas.ChequeOut])
def list_cheques(
    direction: Optional[str] = Query(None, pattern="^(received|issued)$"),
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(under_collection|issued|collected|cashed|returned)$"),
    bank_id: Optional[int] = None,
    branch_id: Optional[int] = None,  # شيكات بنك مرتبط بهذا الفرع
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.Cheque).filter(models.Cheque.company_id == db.info["company_id"])
    if direction:
        q = q.filter(models.Cheque.direction == direction)
    if status_filter:
        q = q.filter(models.Cheque.status == status_filter)
    if bank_id:
        q = q.filter(models.Cheque.bank_id == bank_id)
    if branch_id:
        # تصفية بالفرع: فرع البنك المسحوب عليه
        q = q.join(models.Bank, models.Bank.id == models.Cheque.bank_id, isouter=True).filter(
            models.Bank.branch_id == branch_id
        )
    if date_from:
        q = q.filter(models.Cheque.cheque_date >= date_from)
    if date_to:
        q = q.filter(models.Cheque.cheque_date <= date_to)
    rows = q.order_by(models.Cheque.id.desc()).all()
    return [_out(c) for c in rows]


@router.post("", response_model=schemas.ChequeOut, status_code=status.HTTP_201_CREATED)
def create_cheque(
    payload: schemas.ChequeCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    company_id = db.info["company_id"]
    bank = db.get(models.Bank, payload.bank_id)
    if bank is None or bank.company_id != company_id:
        raise HTTPException(422, "البنك غير موجود")
    if payload.direction == "received":
        if db.get(models.Customer, payload.customer_id) is None:
            raise HTTPException(422, "العميل غير موجود")
    else:
        if db.get(models.Supplier, payload.supplier_id) is None:
            raise HTTPException(422, "المورد غير موجود")
    cheque_date = payload.cheque_date or date.today()

    # The voucher: a Payment with method='cheque' so balances/statements stay consistent.
    payment_payload = schemas.PaymentCreate(
        customer_id=payload.customer_id,
        supplier_id=payload.supplier_id,
        amount=payload.amount,
        method="cheque",
        reference=f"شيك {payload.number.strip()}",
        paid_on=cheque_date,
        notes=payload.notes,
    )
    payment_out = create_payment(payment_payload, db=db, user=user)

    cheque = models.Cheque(
        company_id=company_id,  # type: ignore
        direction=payload.direction,  # type: ignore
        number=payload.number.strip(),  # type: ignore
        bank_id=payload.bank_id,  # type: ignore
        amount=payload.amount,  # type: ignore
        customer_id=payload.customer_id,  # type: ignore
        supplier_id=payload.supplier_id,  # type: ignore
        cheque_date=cheque_date,  # type: ignore
        due_date=payload.due_date,  # type: ignore
        status="under_collection" if payload.direction == "received" else "issued",  # type: ignore
        payment_id=payment_out.id,  # type: ignore
        notes=payload.notes,  # type: ignore
        created_by=user.id,  # type: ignore
    )
    db.add(cheque)
    db.commit()
    db.refresh(cheque)
    audit(db, user, "create", "cheque", cheque, f"{'استلام' if payload.direction == 'received' else 'صرف'} شيك {cheque.number} — {cheque.amount}")
    return _out(cheque)


@router.post("/{cheque_id}/collect", response_model=schemas.ChequeOut)
def collect_cheque(
    cheque_id: int,
    payload: schemas.ChequeCollectIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تحصيل شيك مقبوض نقدًا في خزينة: مدين الخزينة / دائن حافظة الشيكات."""
    c = _get_or_404(db, cheque_id)
    if c.direction != "received" or c.status != "under_collection":
        raise HTTPException(status.HTTP_409_CONFLICT, "يمكن تحصيل الشيكات المقبوضة فقط وهي تحت التحصيل")
    safe = db.get(models.Safe, payload.safe_id)
    if safe is None or safe.company_id != db.info["company_id"]:
        raise HTTPException(422, "الخزينة غير موجودة")
    link_safe_coa(db, safe, db.info["company_id"])
    if safe.chart_account_id is None:
        raise HTTPException(422, "لا يوجد حساب محاسبي مرتبط بالخزينة")
    AccountingEngine.create_entry(
        db=db,
        company_id=db.info["company_id"],
        user_id=user.id,
        description=f"Cheque {c.number} collected (cash)",
        items=[
            {"account_id": safe.chart_account_id, "debit": c.amount, "credit": 0},
            {"account_id": _portfolio_acc_id(db, "received"), "debit": 0, "credit": c.amount},
        ],
        reference=f"CHQ-{c.id}",
    )
    safe.balance = (safe.balance or 0) + c.amount
    c.status = "collected"  # type: ignore
    audit(db, user, "update", "cheque", c, f"تحصيل شيك {c.number} نقدًا — {c.amount}")
    db.commit()
    db.refresh(c)
    return _out(c)


@router.post("/{cheque_id}/deposit", response_model=schemas.ChequeOut)
def deposit_cheque(
    cheque_id: int,
    payload: schemas.ChequeDepositIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """إيداع شيك مقبوض وتحصيله بالبنك: مدين البنك / دائن حافظة الشيكات."""
    c = _get_or_404(db, cheque_id)
    if c.direction != "received" or c.status != "under_collection":
        raise HTTPException(status.HTTP_409_CONFLICT, "يمكن إيداع الشيكات المقبوضة فقط وهي تحت التحصيل")
    bank = db.get(models.Bank, payload.bank_id)
    if bank is None or bank.company_id != db.info["company_id"]:
        raise HTTPException(422, "البنك غير موجود")
    link_bank_coa(db, bank, db.info["company_id"])
    if bank.chart_account_id is None:
        raise HTTPException(422, "لا يوجد حساب محاسبي مرتبط بالبنك")
    AccountingEngine.create_entry(
        db=db,
        company_id=db.info["company_id"],
        user_id=user.id,
        description=f"Cheque {c.number} deposited",
        items=[
            {"account_id": bank.chart_account_id, "debit": c.amount, "credit": 0},
            {"account_id": _portfolio_acc_id(db, "received"), "debit": 0, "credit": c.amount},
        ],
        reference=f"CHQ-{c.id}",
    )
    bank.balance = (bank.balance or 0) + c.amount
    c.status = "collected"  # type: ignore
    audit(db, user, "update", "cheque", c, f"إيداع شيك {c.number} بالبنك — {c.amount}")
    db.commit()
    db.refresh(c)
    return _out(c)


@router.post("/{cheque_id}/cash-out", response_model=schemas.ChequeOut)
def cash_out_cheque(
    cheque_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تم صرف شيك مصروف من البنك: مدين شيكات مصروفة / دائن البنك."""
    c = _get_or_404(db, cheque_id)
    if c.direction != "issued" or c.status != "issued":
        raise HTTPException(status.HTTP_409_CONFLICT, "يمكن صرف الشيكات المصروفة فقط قبل تحصيلها")
    bank = db.get(models.Bank, c.bank_id)
    if bank is None or bank.company_id != db.info["company_id"]:
        raise HTTPException(422, "البنك غير موجود")
    link_bank_coa(db, bank, db.info["company_id"])
    if bank.chart_account_id is None:
        raise HTTPException(422, "لا يوجد حساب محاسبي مرتبط بالبنك")
    AccountingEngine.create_entry(
        db=db,
        company_id=db.info["company_id"],
        user_id=user.id,
        description=f"Cheque {c.number} cashed by bank",
        items=[
            {"account_id": _portfolio_acc_id(db, "issued"), "debit": c.amount, "credit": 0},
            {"account_id": bank.chart_account_id, "debit": 0, "credit": c.amount},
        ],
        reference=f"CHQ-{c.id}",
    )
    bank.balance = (bank.balance or 0) - c.amount
    c.status = "cashed"  # type: ignore
    audit(db, user, "update", "cheque", c, f"صرف شيك {c.number} من البنك — {c.amount}")
    db.commit()
    db.refresh(c)
    return _out(c)


@router.post("/{cheque_id}/return", response_model=schemas.ChequeOut)
def return_cheque(
    cheque_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """ارتجاع شيك (قبل التحصيل/الصرف): إلغاء السند المرتبط فينعكس قيده ويرجع رصيد الطرف."""
    c = _get_or_404(db, cheque_id)
    if c.status not in ("under_collection", "issued"):
        raise HTTPException(status.HTTP_409_CONFLICT, "يمكن ارتجاع الشيك قبل تحصيله أو صرفه فقط")
    if c.payment_id is not None:
        void_payment(c.payment_id, db=db, user=user)  # reverses the voucher JE + party balance
    c.status = "returned"  # type: ignore
    audit(db, user, "update", "cheque", c, f"ارتجاع شيك {c.number} — {c.amount}")
    db.commit()
    db.refresh(c)
    return _out(c)
