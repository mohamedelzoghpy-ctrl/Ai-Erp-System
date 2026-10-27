"""Payments (receipts from customers, payments to suppliers) and account statements.

Payments are append-only: a wrong entry is voided (manager/admin), never edited or deleted, so the
audit trail stays intact. Voided payments no longer count towards balances.
"""

from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from .. import accounts, exports, models, schemas
from ..pagination import paginate
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager

payments = APIRouter(prefix="/payments", tags=["payments"], dependencies=[Depends(get_current_user)])
customer_accounts = APIRouter(
    prefix="/customers", tags=["customer accounts"], dependencies=[Depends(get_current_user)]
)
supplier_accounts = APIRouter(
    prefix="/suppliers", tags=["supplier accounts"], dependencies=[Depends(get_current_user)]
)


def _today() -> date:
    return datetime.now(exports.LOCAL_TZ).date()


def _out(p: models.Payment) -> models.Payment:
    party = p.customer if p.customer_id is not None else p.supplier
    p.party_name = party.name if party else None  # type: ignore[attr-defined]
    return p


def _get_or_404(db: Session, payment_id: int) -> models.Payment:
    p = db.get(models.Payment, payment_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Payment {payment_id} not found")
    return p


@payments.post("", response_model=schemas.PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: schemas.PaymentCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    if payload.customer_id is not None and db.get(models.Customer, payload.customer_id) is None:
        raise HTTPException(422, f"Customer {payload.customer_id} does not exist")
    if payload.supplier_id is not None and db.get(models.Supplier, payload.supplier_id) is None:
        raise HTTPException(422, f"Supplier {payload.supplier_id} does not exist")
    paid_on = payload.paid_on or _today()
    if paid_on > _today():
        raise HTTPException(422, "paid_on cannot be in the future")
    p = models.Payment(
        customer_id=payload.customer_id,  # type: ignore
        supplier_id=payload.supplier_id,  # type: ignore
        safe_id=payload.safe_id,  # type: ignore
        bank_id=payload.bank_id,  # type: ignore
        amount=payload.amount,  # type: ignore
        method=payload.method,  # type: ignore
        reference=(payload.reference or "").strip() or None,  # type: ignore
        notes=payload.notes,  # type: ignore
        paid_on=paid_on,  # type: ignore
        created_by=user.id,  # type: ignore
    )
    db.add(p)
    # Update safe/bank balance: receipt (customer) increases, payment (supplier) decreases.
    delta = payload.amount if payload.customer_id is not None else -payload.amount
    if payload.safe_id is not None:
        safe = db.get(models.Safe, payload.safe_id)
        if safe is None or safe.company_id != db.info["company_id"]:
            raise HTTPException(422, "Safe not found")
        safe.balance = (safe.balance or 0) + delta  # type: ignore
    if payload.bank_id is not None:
        bank = db.get(models.Bank, payload.bank_id)
        if bank is None or bank.company_id != db.info["company_id"]:
            raise HTTPException(422, "Bank not found")
        bank.balance = (bank.balance or 0) + delta  # type: ignore
    audit(db, user, "create", "payment", p, f"{'قبض' if p.customer_id else 'دفع'} {p.amount}")  # type: ignore
    db.commit()
    db.refresh(p)
    return _out(p)


@payments.get("", response_model=List[schemas.PaymentOut])
def list_payments(
    response: Response,
    customer_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    kind: Optional[str] = Query(None, pattern="^(receipt|payment)$"),
    status_filter: Optional[str] = Query(None, pattern="^(posted|voided)$"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(models.Payment)
    if customer_id is not None:
        q = q.filter(models.Payment.customer_id == customer_id)
    if supplier_id is not None:
        q = q.filter(models.Payment.supplier_id == supplier_id)
    if kind == "receipt":
        q = q.filter(models.Payment.customer_id.isnot(None))
    elif kind == "payment":
        q = q.filter(models.Payment.supplier_id.isnot(None))
    if status_filter:
        q = q.filter(models.Payment.status == status_filter)
    if date_from:
        q = q.filter(models.Payment.paid_on >= date_from)
    if date_to:
        q = q.filter(models.Payment.paid_on <= date_to)
    rows = paginate(q, response, skip, limit, models.Payment.paid_on.desc(), models.Payment.id.desc())
    return [_out(p) for p in rows]


@payments.get("/{payment_id}", response_model=schemas.PaymentOut)
def get_payment(payment_id: int, db: Session = Depends(get_db)):
    return _out(_get_or_404(db, payment_id))


@payments.post("/{payment_id}/void", response_model=schemas.PaymentOut)
def void_payment(payment_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    p = _get_or_404(db, payment_id)
    if p.status == "voided":  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "Payment is already voided")
    p.status = "voided"  # type: ignore
    p.voided_by = user.id
    p.voided_at = datetime.now(timezone.utc)  # type: ignore
    # Reverse safe/bank balance.
    delta = p.amount if p.customer_id is not None else -p.amount
    if p.safe_id is not None:
        safe = db.get(models.Safe, p.safe_id)
        if safe is not None:
            safe.balance = (safe.balance or 0) - delta  # type: ignore
    if p.bank_id is not None:
        bank = db.get(models.Bank, p.bank_id)
        if bank is not None:
            bank.balance = (bank.balance or 0) - delta  # type: ignore
    audit(db, user, "void", "payment", p, f"{p.amount}")
    db.commit()
    db.refresh(p)
    return _out(p)


# ----------------------------------------------------------------------------- statements
def _statement(db: Session, kind: str, party_id: int, date_from: Optional[date], date_to: Optional[date]) -> schemas.Statement:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    stmt = accounts.build_statement(db, kind, party_id, date_from, date_to)
    if stmt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{kind.capitalize()} {party_id} not found")
    return stmt


def _file(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


def _register_statement_routes(router: APIRouter, kind: str) -> None:
    @router.get("/{party_id}/statement", response_model=schemas.Statement)
    def statement(party_id: int, date_from: Optional[date] = None, date_to: Optional[date] = None, db: Session = Depends(get_db)):
        return _statement(db, kind, party_id, date_from, date_to)

    @router.get("/{party_id}/statement/pdf")
    def statement_pdf(party_id: int, date_from: Optional[date] = None, date_to: Optional[date] = None, db: Session = Depends(get_db)):
        s = _statement(db, kind, party_id, date_from, date_to)
        return _file(exports.build_statement_pdf(s.model_dump()), exports.PDF_MIME, f"statement-{kind}-{party_id}.pdf")

    @router.get("/{party_id}/statement/xlsx")
    def statement_xlsx(party_id: int, date_from: Optional[date] = None, date_to: Optional[date] = None, db: Session = Depends(get_db)):
        s = _statement(db, kind, party_id, date_from, date_to)
        return _file(exports.build_statement_xlsx(s.model_dump()), exports.XLSX_MIME, f"statement-{kind}-{party_id}.xlsx")


_register_statement_routes(customer_accounts, "customer")
_register_statement_routes(supplier_accounts, "supplier")
