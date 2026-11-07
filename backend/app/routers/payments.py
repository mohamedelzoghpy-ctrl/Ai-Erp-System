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
from ..accounting import AccountingEngine

payments = APIRouter(prefix="/payments", tags=["payments"], dependencies=[Depends(get_current_user)])
categories = APIRouter(prefix="/payment-categories", tags=["payments"], dependencies=[Depends(get_current_user)])
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
    p.company_name = p.company.name if p.company else None  # type: ignore[attr-defined]
    p.safe_branch_name = (p.safe.branch.name if p.safe and p.safe.branch else None)  # type: ignore[attr-defined]
    return p


def _get_or_404(db: Session, payment_id: int) -> models.Payment:
    p = db.get(models.Payment, payment_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Payment {payment_id} not found")
    return p


# ------------------------------------------------------------ بنود القبض والصرف
@categories.get("", response_model=List[schemas.PaymentCategoryOut])
def list_payment_categories(
    kind: Optional[str] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.PaymentCategory).filter(models.PaymentCategory.company_id == db.info["company_id"])
    if kind:
        q = q.filter(models.PaymentCategory.kind == kind)
    return q.order_by(models.PaymentCategory.name).all()


@categories.post("", response_model=schemas.PaymentCategoryOut, status_code=status.HTTP_201_CREATED)
def create_payment_category(
    payload: schemas.PaymentCategoryCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    name = payload.name.strip()
    existing = (
        db.query(models.PaymentCategory)
        .filter(
            models.PaymentCategory.company_id == db.info["company_id"],
            models.PaymentCategory.kind == payload.kind,
            models.PaymentCategory.name == name,
        )
        .first()
    )
    if existing is not None:  # idempotent: picking an existing name just selects it
        return existing
    cat = models.PaymentCategory(company_id=db.info["company_id"], name=name, kind=payload.kind, requires_party=payload.requires_party)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    audit(db, user, "create", "payment_category", cat, f"{payload.kind}: {name}")
    return cat


@payments.post("", response_model=schemas.PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: schemas.PaymentCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    if payload.customer_id is not None and db.get(models.Customer, payload.customer_id) is None:
        raise HTTPException(422, f"Customer {payload.customer_id} does not exist")
    if payload.supplier_id is not None and db.get(models.Supplier, payload.supplier_id) is None:
        raise HTTPException(422, f"Supplier {payload.supplier_id} does not exist")
    category = None
    if payload.category_id is not None:
        category = db.get(models.PaymentCategory, payload.category_id)
        if category is None or category.company_id != db.info["company_id"]:
            raise HTTPException(422, "البند غير موجود")
    # Direction: from the party when present, otherwise from the بند (party-less voucher).
    if payload.customer_id is not None:
        is_receipt = True
    elif payload.supplier_id is not None:
        is_receipt = False
    else:
        is_receipt = category is not None and category.kind == "receipt"
    expected_kind = "receipt" if is_receipt else "payment"
    if category is not None and category.kind != expected_kind:
        raise HTTPException(422, "نوع البند لا يطابق نوع السند")
    if payload.customer_id is None and payload.supplier_id is None:
        # Party-less voucher: the بند must allow no party, and the money must land in a safe/bank.
        if category is None:
            raise HTTPException(422, "السند بدون طرف يتطلب اختيار البند")
        if category.requires_party:
            raise HTTPException(422, f"بند «{category.name}» يتطلب اختيار {'العميل' if is_receipt else 'المورد'}")
        if payload.safe_id is None and payload.bank_id is None:
            raise HTTPException(422, "السند بدون طرف يتطلب اختيار خزينة أو بنك")
    paid_on = payload.paid_on or _today()
    if paid_on > _today():
        raise HTTPException(422, "paid_on cannot be in the future")

    from ..accounting import link_safe_coa, link_bank_coa, link_party_coa, seed_default_coa, ensure_company_coa

    # Identify Accounts (lazy-provision CoA links so JE always posts)
    company_id = db.info["company_id"]
    ensure_company_coa(db, company_id)

    cash_acc_id = None
    if payload.method == "cheque":
        # Cheques park in the portfolio, not the drawer/bank: debit 1115 (received) or credit 2111 (issued).
        seed_default_coa(db, company_id)
        code = "1115" if is_receipt else "2111"
        acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == company_id, models.ChartAccount.code == code
        ).first()
        if acc is None:
            raise HTTPException(422, f"حساب {code} غير موجود في شجرة الحسابات")
        cash_acc_id = acc.id
    elif payload.safe_id is not None:
        safe = db.get(models.Safe, payload.safe_id)
        if safe is None or safe.company_id != company_id:
            raise HTTPException(422, "Safe not found")
        link_safe_coa(db, safe, company_id)
        cash_acc_id = safe.chart_account_id
    elif payload.bank_id is not None:
        bank = db.get(models.Bank, payload.bank_id)
        if bank is None or bank.company_id != company_id:
            raise HTTPException(422, "Bank not found")
        link_bank_coa(db, bank, company_id)
        cash_acc_id = bank.chart_account_id

    counter_acc_id = None
    if payload.customer_id is not None:
        cust = db.get(models.Customer, payload.customer_id)
        if cust is None:
            raise HTTPException(422, "Customer not found")
        link_party_coa(db, cust, company_id, is_customer=True)
        counter_acc_id = cust.chart_account_id
    elif payload.supplier_id is not None:
        supp = db.get(models.Supplier, payload.supplier_id)
        if supp is None:
            raise HTTPException(422, "Supplier not found")
        link_party_coa(db, supp, company_id, is_customer=False)
        counter_acc_id = supp.chart_account_id
    else:
        # General income / general expense: post against the seeded 4200 / 5600 leaf account.
        code = "4200" if is_receipt else "5600"
        acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == company_id, models.ChartAccount.code == code
        ).first()
        if acc is None:
            raise HTTPException(422, f"حساب {code} غير موجود في شجرة الحسابات")
        counter_acc_id = acc.id

    # Party payments may legitimately carry no cash location (money moves between
    # balances only); only log that the JE was skipped — orders hard-fail instead.
    post_je = bool(cash_acc_id and counter_acc_id)
    if not post_je:
        import logging
        logging.getLogger(__name__).warning("Payment: could not provision CoA links (safe=%s party=%s); skipping double-entry", payload.safe_id or payload.bank_id, payload.customer_id or payload.supplier_id)

    p = models.Payment(
        kind="receipt" if is_receipt else "payment",  # type: ignore
        customer_id=payload.customer_id,  # type: ignore
        supplier_id=payload.supplier_id,  # type: ignore
        safe_id=payload.safe_id,  # type: ignore
        bank_id=payload.bank_id,  # type: ignore
        category_id=payload.category_id,  # type: ignore
        amount=payload.amount,  # type: ignore
        method=payload.method,  # type: ignore
        reference=(payload.reference or "").strip() or None,  # type: ignore
        notes=payload.notes,  # type: ignore
        paid_on=paid_on,  # type: ignore
        created_by=user.id,  # type: ignore
    )
    db.add(p)
    db.flush()

    # Double Entry Logic
    amount = payload.amount
    if is_receipt:  # Receipt: Debit Cash, Credit counter (customer / other income)
        items = [
            {"account_id": cash_acc_id, "debit": amount, "credit": 0},
            {"account_id": counter_acc_id, "debit": 0, "credit": amount},
        ]
    else:  # Payment: Debit counter (supplier / misc expense), Credit Cash
        items = [
            {"account_id": counter_acc_id, "debit": amount, "credit": 0},
            {"account_id": cash_acc_id, "debit": 0, "credit": amount},
        ]

    if post_je:
        AccountingEngine.create_entry(
            db=db,
            company_id=db.info["company_id"],
            user_id=user.id,
            description=f"Payment {p.id}: {p.reference or 'No Ref'}",
            items=items,
            reference=p.reference,
            date=paid_on,
        )

    # Keep legacy balance update for backward compatibility if needed,
    # though AccountingEngine now handles ChartAccount.balance
    delta = payload.amount if is_receipt else -payload.amount
    if payload.safe_id is not None:
        safe = db.get(models.Safe, payload.safe_id)
        if safe: safe.balance = (safe.balance or 0) + delta
    if payload.bank_id is not None:
        bank = db.get(models.Bank, payload.bank_id)
        if bank: bank.balance = (bank.balance or 0) + delta

    audit(db, user, "create", "payment", p, f"{'قبض' if is_receipt else 'دفع'} {p.amount}")  # type: ignore
    db.commit()
    db.refresh(p)
    return _out(p)


@payments.get("", response_model=List[schemas.PaymentOut])
def list_payments(
    response: Response,
    customer_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    safe_id: Optional[int] = None,  # vouchers that moved money in/out of this safe
    bank_id: Optional[int] = None,
    branch_id: Optional[int] = None,  # vouchers whose safe belongs to this branch
    category_id: Optional[int] = None,  # بند السند (نوع السند)
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
    if safe_id is not None:
        q = q.filter(models.Payment.safe_id == safe_id)
    if bank_id is not None:
        q = q.filter(models.Payment.bank_id == bank_id)
    if category_id is not None:
        q = q.filter(models.Payment.category_id == category_id)
    if branch_id is not None:
        # تصفية بالفرع: فرع الخزينة المرتبطة بالسند
        q = q.join(models.Safe, models.Safe.id == models.Payment.safe_id, isouter=True).filter(
            models.Safe.branch_id == branch_id
        )
    if kind == "receipt":
        q = q.filter(models.Payment.kind == "receipt")
    elif kind == "payment":
        q = q.filter(models.Payment.kind == "payment")
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
    linked_cheque = db.query(models.Cheque).filter(models.Cheque.payment_id == p.id).first()
    if linked_cheque is not None and linked_cheque.status in ("collected", "cashed"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "لا يمكن إلغاء سند شيك تم تحصيله أو صرفه — ارجع الشيك من حافظة الشيكات أولًا",
        )
    p.status = "voided"  # type: ignore
    p.voided_by = user.id
    p.voided_at = datetime.now(timezone.utc)  # type: ignore

    # Double Entry: Reverse the original entry
    cash_acc_id = None
    if p.method == "cheque":
        # Cheque voucher: the original entry hit the portfolio accounts (1115 / 2111).
        code = "1115" if p.kind == "receipt" else "2111"
        acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == code
        ).first()
        cash_acc_id = acc.id if acc else None
    elif p.safe_id is not None:
        safe = db.get(models.Safe, p.safe_id)
        cash_acc_id = safe.chart_account_id if safe else None
    elif p.bank_id is not None:
        bank = db.get(models.Bank, p.bank_id)
        cash_acc_id = bank.chart_account_id if bank else None

    counter_acc_id = None
    if p.customer_id is not None:
        cust = db.get(models.Customer, p.customer_id)
        counter_acc_id = cust.chart_account_id if cust else None
    elif p.supplier_id is not None:
        supp = db.get(models.Supplier, p.supplier_id)
        counter_acc_id = supp.chart_account_id if supp else None
    else:
        # Party-less voucher: reverse against the general income / misc expense account.
        code = "4200" if p.kind == "receipt" else "5600"
        acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == code
        ).first()
        counter_acc_id = acc.id if acc else None

    if cash_acc_id and counter_acc_id:
        existing_je = db.query(models.JournalEntry).filter(
            models.JournalEntry.company_id == db.info["company_id"],
            models.JournalEntry.description.like(f"Payment {p.id}:%"),
        ).first()
        if existing_je is not None:
            amount = p.amount
            if p.kind == "receipt":  # reversal: Debit counter, Credit cash
                items = [
                    {"account_id": counter_acc_id, "debit": amount, "credit": 0},
                    {"account_id": cash_acc_id, "debit": 0, "credit": amount},
                ]
            else:  # reversal: Debit cash, Credit counter
                items = [
                    {"account_id": cash_acc_id, "debit": amount, "credit": 0},
                    {"account_id": counter_acc_id, "debit": 0, "credit": amount},
                ]
            AccountingEngine.create_entry(
                db=db,
                company_id=db.info["company_id"],
                user_id=user.id,
                description=f"Voiding Payment {p.id}",
                items=items,
                reference=f"VOID-{p.id}",
                date=p.paid_on,
            )

    # Reverse legacy safe/bank balance.
    delta = p.amount if p.kind == "receipt" else -p.amount
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
