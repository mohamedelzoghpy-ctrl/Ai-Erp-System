"""Payments (receipts from customers, payments to suppliers) and account statements.

Payments are append-only: a wrong entry is voided (manager/admin), never edited or deleted, so the
audit trail stays intact. Voided payments no longer count towards balances.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
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
    p.currency_code = p.currency.code if getattr(p, "currency", None) else None  # type: ignore[attr-defined]
    p.withholding_code_name = (p.withholding_code.name if getattr(p, "withholding_code", None) else None)  # type: ignore[attr-defined]
    return p


def _get_or_404(db: Session, payment_id: int) -> models.Payment:
    p = db.get(models.Payment, payment_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Payment {payment_id} not found")
    return p


def _party_in_company(db: Session, model, party_id: int, label: str):
    """جلب طرف (عميل/مورد) مقيّدًا بالشركة الحالية — Session.get يتجاوز فلتر العزل."""
    obj = (
        db.query(model)
        .filter(model.id == party_id, model.company_id == db.info["company_id"])
        .first()
    )
    if obj is None:
        raise HTTPException(422, f"{label} {party_id} does not exist")
    return obj


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
    if payload.customer_id is not None:
        _party_in_company(db, models.Customer, payload.customer_id, "Customer")
    if payload.supplier_id is not None:
        _party_in_company(db, models.Supplier, payload.supplier_id, "Supplier")
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

    # ---- ضريبة الخصم والإضافة: سندات الدفع للموردين فقط (بالجنيه) ----
    withholding_amount = Decimal("0")
    withholding_code_id = None
    if not (payload.customer_id is not None) and payload.supplier_id is not None:
        w = Decimal(str(payload.withholding_amount or 0)).quantize(Decimal("0.01"))
        if w > 0:
            if getattr(payload, "currency_id", None):
                raise HTTPException(422, "ضريبة الخصم والإضافة متاحة لسندات الدفع بالجنيه فقط")
            if w >= Decimal(str(payload.amount)):
                raise HTTPException(422, "المحتجز للخصم والإضافة يجب أن يكون أقل من قيمة السند")
            if payload.withholding_code_id is not None:
                wcode = db.query(models.WithholdingCode).filter(
                    models.WithholdingCode.id == payload.withholding_code_id,
                    models.WithholdingCode.company_id == db.info["company_id"],
                ).first()
                if wcode is None or not wcode.is_active:
                    raise HTTPException(422, "كود الخصم والإضافة غير موجود أو غير نشط")
                withholding_code_id = wcode.id
            withholding_amount = w

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
        cust = _party_in_company(db, models.Customer, payload.customer_id, "Customer")
        link_party_coa(db, cust, company_id, is_customer=True)
        counter_acc_id = cust.chart_account_id
    elif payload.supplier_id is not None:
        supp = _party_in_company(db, models.Supplier, payload.supplier_id, "Supplier")
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
        cash_location_expected = payload.method == "cheque" or payload.safe_id is not None or payload.bank_id is not None
        if cash_location_expected:
            # نقدية فعلية ستتحرك دون قيد = دفاتر كاذبة — نفشل بصوت عالٍ بدل التخطي الصامت
            raise HTTPException(status.HTTP_409_CONFLICT, "تعذّر تجهيز حسابات شجرة الحسابات لهذا السند — أكمل ربط الخزينة/البنك/الطرف بشجرة الحسابات ثم أعد المحاولة")
        import logging
        logging.getLogger(__name__).warning("Payment: party balance-only voucher (no cash location); JE skipped (party=%s)", payload.customer_id or payload.supplier_id)

    # ---- العملة الأجنبية ----
    # currency معطاة → amount الوارد يُتجاهل ويُحسب: settle_base (تسوية الطرف بالسعر الموزون)
    # و cash_base (النقدية الفعلية بالسعر الحالي) — والفرق فرق صرف يُرحّل داخل قيد السند نفسه.
    currency = rate = None
    foreign_amount = None
    settle_base = cash_base = payload.amount
    fx_gain_loss = Decimal("0")
    if getattr(payload, "currency_id", None):
        from ..pricing import resolve_currency
        currency, rate = resolve_currency(db, payload.currency_id)
        if currency is None:
            raise HTTPException(422, "عملة غير صالحة أو غير نشطة")
        foreign_amount = payload.foreign_amount or (Decimal(str(payload.amount)) / rate).quantize(Decimal("0.01"))
        foreign_amount = Decimal(str(foreign_amount)).quantize(Decimal("0.01"))
        cash_base = (foreign_amount * rate).quantize(Decimal("0.01"))
        settle_base = cash_base
        if payload.customer_id is not None or payload.supplier_id is not None:
            PartyOrder = models.SalesOrder if is_receipt else models.PurchaseOrder
            party_col = PartyOrder.customer_id if is_receipt else PartyOrder.supplier_id
            party_orders = db.query(PartyOrder).filter(
                PartyOrder.company_id == company_id,
                party_col == (payload.customer_id or payload.supplier_id),
                PartyOrder.status == ("confirmed" if is_receipt else "received"),
                PartyOrder.currency_id == currency.id,  # type: ignore
            ).all()
            foreign_invoiced = sum((Decimal(str(o.foreign_total or 0)) for o in party_orders), Decimal("0"))
            prev_pays = db.query(models.Payment).filter(
                models.Payment.company_id == company_id,
                models.Payment.status == "posted",
                models.Payment.currency_id == currency.id,  # type: ignore
                (models.Payment.customer_id == payload.customer_id) if is_receipt else (models.Payment.supplier_id == payload.supplier_id),
            ).all()
            foreign_paid = sum((Decimal(str(pp.foreign_amount or 0)) for pp in prev_pays), Decimal("0"))
            party_foreign = foreign_invoiced - foreign_paid
            if party_foreign > 0:
                from ..accounts import party_balances as _pb
                party_base = _pb(db, "customer" if is_receipt else "supplier",
                                 [payload.customer_id or payload.supplier_id]).get(payload.customer_id or payload.supplier_id, 0)
                weighted = Decimal(str(party_base)) / party_foreign
                applied = min(foreign_amount, party_foreign)
                settle_base = (applied * weighted + (foreign_amount - applied) * rate).quantize(Decimal("0.01"))
                # اتجاه الربح يتبع الجهة: قبض (العميل يسدد لنا) → صعود السعر ربح؛
                # دفع (نحن نسدد لمورد) → هبوط السعر ربح.
                fx_gain_loss = (applied * ((rate - weighted) if is_receipt else (weighted - rate))).quantize(Decimal("0.01"))
                cash_base = (foreign_amount * rate).quantize(Decimal("0.01"))

    p = models.Payment(
        kind="receipt" if is_receipt else "payment",  # type: ignore
        customer_id=payload.customer_id,  # type: ignore
        supplier_id=payload.supplier_id,  # type: ignore
        safe_id=payload.safe_id,  # type: ignore
        bank_id=payload.bank_id,  # type: ignore
        category_id=payload.category_id,  # type: ignore
        amount=settle_base,  # type: ignore
        method=payload.method,  # type: ignore
        reference=(payload.reference or "").strip() or None,  # type: ignore
        notes=payload.notes,  # type: ignore
        paid_on=paid_on,  # type: ignore
        currency_id=(currency.id if currency else None),  # type: ignore
        exchange_rate=(rate if currency else None),  # type: ignore
        foreign_amount=foreign_amount,  # type: ignore
        withholding_amount=(withholding_amount if not is_receipt else Decimal("0")),  # type: ignore
        withholding_code_id=(withholding_code_id if not is_receipt else None),  # type: ignore
        created_by=user.id,  # type: ignore
    )
    db.add(p)
    db.flush()

    # Double Entry Logic
    amount = payload.amount
    cash_out = amount - withholding_amount  # الخصم والإضافة: النقدية الفعلية = amount − المحتجز
    if is_receipt:  # Receipt: Debit Cash, Credit counter (customer / other income)
        items = [
            {"account_id": cash_acc_id, "debit": amount, "credit": 0},
            {"account_id": counter_acc_id, "debit": 0, "credit": amount},
        ]
    elif withholding_amount > 0:
        # Payment with withholding: Debit supplier (full), Credit cash (net), Credit withholding payable
        from ..accounting import seed_default_coa as _seed_coa
        _seed_coa(db, company_id)
        wh_acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == company_id, models.ChartAccount.code == "2135"
        ).first()
        if wh_acc is None or wh_acc.is_group:
            raise HTTPException(409, "حساب ضريبة الخصم والإضافة (2135) غير موجود — حدّث شجرة الحسابات")
        items = [
            {"account_id": counter_acc_id, "debit": amount, "credit": 0},
            {"account_id": cash_acc_id, "debit": 0, "credit": cash_out},
            {"account_id": wh_acc.id, "debit": 0, "credit": withholding_amount},
        ]
    else:  # Payment: Debit counter (supplier / misc expense), Credit Cash
        items = [
            {"account_id": counter_acc_id, "debit": amount, "credit": 0},
            {"account_id": cash_acc_id, "debit": 0, "credit": amount},
        ]

    if post_je:
        # الدفع بعملة أجنبية: النقدية بسعر السداد الفعلي، وتسوية الطرف بالسعر الموزون،
        # والفرق سطر ثالث في القيد نفسه (ربح صرف 4240 / خسارة 5350) — القيد موزون دائمًا.
        description = f"Payment {p.id}: {p.reference or 'No Ref'}"
        if currency is not None and fx_gain_loss != 0:
            items = [dict(it) for it in items]
            for it in items:
                it["debit"] = cash_base if it.get("debit") else it.get("debit", 0)
                it["credit"] = cash_base if it.get("credit") else it.get("credit", 0)
            # تصحيح الاتجاهات: سطر النقدية بالسعر الفعلي، وسطر الطرف بالتسوية
            for it in items:
                if it["account_id"] == cash_acc_id:
                    if it.get("debit"):
                        it["debit"] = cash_base; it["credit"] = 0
                    else:
                        it["credit"] = cash_base; it["debit"] = 0
                else:
                    if it.get("debit"):
                        it["debit"] = settle_base; it["credit"] = 0
                    else:
                        it["credit"] = settle_base; it["debit"] = 0
            diff = sum((it["debit"] for it in items), Decimal("0")) - sum((it["credit"] for it in items), Decimal("0"))
            fx_code = "4240" if fx_gain_loss > 0 else "5350"
            fx_acc = db.query(models.ChartAccount).filter(
                models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == fx_code
            ).first()
            if fx_acc is None or fx_acc.is_group:
                raise HTTPException(409, f"حساب فرق الصرف ({fx_code}) غير موجود — حدّث شجرة الحسابات")
            if diff > 0:
                items.append({"account_id": fx_acc.id, "debit": 0, "credit": diff})
            elif diff < 0:
                items.append({"account_id": fx_acc.id, "debit": -diff, "credit": 0})
            description = f"Payment {p.id}: {p.reference or 'No Ref'} (FX {currency.code} @{rate})"
        if currency is not None:
            description = f"{description} (FX {currency.code} @{rate})"
        AccountingEngine.create_entry(
            db=db,
            company_id=db.info["company_id"],
            user_id=user.id,
            description=description,
            items=items,
            # مرجع deterministic فريد: الإلغاء يجد القيد الأصلي به بدقة بدل مطابقة نص الوصف
            reference=f"PAY-{p.id}",
            date=paid_on,
        )
        if currency is not None and fx_gain_loss:
            audit(db, user, "create", "fx_adjustment", p,
                  f"فرق صرف {'ربح' if fx_gain_loss > 0 else 'خسارة'} {fx_gain_loss} ({currency.code} @{rate})")

    # Keep legacy balance update for backward compatibility if needed,
    # though AccountingEngine now handles ChartAccount.balance
    # (بعملة أجنبية: النقدية الفعلية cash_base قد تختلف عن التسوية settle_base)
    # (مع خصم وإضافة: النقدية الفعلية = amount − المحتجز)
    effective_cash = cash_base if currency is not None else cash_out
    delta = effective_cash if is_receipt else -effective_cash
    if payload.safe_id is not None:
        safe = db.get(models.Safe, payload.safe_id)
        if safe: safe.balance = (safe.balance or 0) + delta
    if payload.bank_id is not None:
        bank = db.get(models.Bank, payload.bank_id)
        if bank: bank.balance = (bank.balance or 0) + delta

    audit(db, user, "create", "payment", p, f"{'قبض' if is_receipt else 'دفع'} {p.amount}")  # type: ignore
    db.commit()
    db.refresh(p)
    # تنبيه تطبيق المندوب: تحصيل من عميل فاتورته الأخيرة بمندوب (صندوق + Push إن ضُبط FCM)
    if is_receipt and payload.customer_id is not None:
        try:
            last_order = (
                db.query(models.SalesOrder)
                .filter(
                    models.SalesOrder.customer_id == payload.customer_id,
                    models.SalesOrder.company_id == company_id,
                    models.SalesOrder.status == "confirmed",
                    models.SalesOrder.rep_id.isnot(None),
                )
                .order_by(models.SalesOrder.id.desc())
                .first()
            )
            if last_order and last_order.rep_id:
                from ..push import notify_rep
                cust = db.get(models.Customer, payload.customer_id)
                notify_rep(db, last_order.rep_id, kind="payment_collected",
                           title=f"تحصيل {p.amount} ج.م",
                           body=f"العميل {cust.name if cust else payload.customer_id} — سند #{p.id}",
                           ref_id=p.id)
        except Exception:
            pass  # الإشعار لا يعطل السند أبدًا
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
        cust = (
            db.query(models.Customer)
            .filter(models.Customer.id == p.customer_id, models.Customer.company_id == db.info["company_id"])
            .first()
        )
        counter_acc_id = cust.chart_account_id if cust else None
    elif p.supplier_id is not None:
        supp = (
            db.query(models.Supplier)
            .filter(models.Supplier.id == p.supplier_id, models.Supplier.company_id == db.info["company_id"])
            .first()
        )
        counter_acc_id = supp.chart_account_id if supp else None
    else:
        # Party-less voucher: reverse against the general income / misc expense account.
        code = "4200" if p.kind == "receipt" else "5600"
        acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == code
        ).first()
        counter_acc_id = acc.id if acc else None

    if cash_acc_id and counter_acc_id:
        # القيد الأصلي يحمل مرجع PAY-{id} الفريد؛ للسندات القديمة (قبل المرجع) نallback
        # على مطابقة الوصف مع استبعاد قيود الإلغاء نفسها.
        existing_je = db.query(models.JournalEntry).filter(
            models.JournalEntry.company_id == db.info["company_id"],
            models.JournalEntry.reference == f"PAY-{p.id}",
        ).first()
        if existing_je is None:
            existing_je = db.query(models.JournalEntry).filter(
                models.JournalEntry.company_id == db.info["company_id"],
                models.JournalEntry.description.like(f"Payment {p.id}:%"),
                ~models.JournalEntry.reference.like("VOID-%"),
            ).first()
        if existing_je is not None:
            # اقلب أسطر القيد الأصلي حرفيًا — يشمل سندات الخصم والإضافة (3 أسطر) والأجنبية موحّدًا
            items = [
                {"account_id": ji.account_id, "debit": ji.credit, "credit": ji.debit}
                for ji in existing_je.items
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
    # (سند أجنبي: النقدية الفعلية = الأجنبي × سعره — قد تختلف عن amount التسوية)
    # (مع خصم وإضافة: النقدية الفعلية = amount − المحتجز)
    if p.currency_id is not None:
        p_cash = (Decimal(str(p.foreign_amount)) * Decimal(str(p.exchange_rate))).quantize(Decimal("0.01"))
    else:
        p_cash = Decimal(str(p.amount)) - Decimal(str(p.withholding_amount or 0))
    delta = p_cash if p.kind == "receipt" else -p_cash
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
    stmt = accounts.build_statement(db, kind, party_id, date_from, date_to, company_id=db.info["company_id"])
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
