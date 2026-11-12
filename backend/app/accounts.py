"""Customer / supplier balances and account statements.

Single source of truth for the sign convention:

  customer balance = opening_balance + confirmed sales      - posted receipts   (what they owe us)
  supplier balance = opening_balance + received purchases   - posted payments   (what we owe them)

A positive balance is therefore money still owed; a negative one is a credit (overpayment).
Voided payments, draft/cancelled orders never count.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, schemas
from .exports import LOCAL_TZ

ZERO = Decimal("0")

METHOD_LABEL = {"cash": "نقداً", "bank": "تحويل بنكي", "wallet": "محفظة إلكترونية", "cheque": "شيك"}


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def _credits(db: Session, kind: str, ids: Optional[Iterable[int]] = None) -> Dict[int, Decimal]:
    """Net value of returns per party: goods returned minus the cash handed back at the time.
    It lowers the balance exactly like a payment does, so it is counted with the payments everywhere."""
    ret = models.SalesReturn if kind == "customer" else models.PurchaseReturn
    col = ret.customer_id if kind == "customer" else ret.supplier_id
    q = db.query(col, func.sum(ret.total_amount - ret.refund_amount)).group_by(col)
    if ids is not None:
        q = q.filter(col.in_(list(ids) or [0]))
    return {pid: _dec(v) for pid, v in q.all()}


def party_balances(db: Session, kind: str, ids: Optional[Iterable[int]] = None) -> Dict[int, Decimal]:
    """Balance of every customer ('customer') or supplier ('supplier'), or only of `ids`."""
    if kind == "customer":
        party, order, order_party, status = models.Customer, models.SalesOrder, models.SalesOrder.customer_id, "confirmed"
        pay_party = models.Payment.customer_id
    else:
        party, order, order_party, status = models.Supplier, models.PurchaseOrder, models.PurchaseOrder.supplier_id, "received"
        pay_party = models.Payment.supplier_id
    id_list = None if ids is None else list(ids)
    if id_list is not None and not id_list:
        return {}

    def restrict(q, col):
        return q if id_list is None else q.filter(col.in_(id_list))

    opening = restrict(db.query(party.id, party.opening_balance), party.id).all()
    charges = dict(
        restrict(
            db.query(order_party, func.sum(order.total_amount)).filter(order.status == status).group_by(order_party),
            order_party,
        ).all()
    )
    paid = dict(
        restrict(
            db.query(pay_party, func.sum(models.Payment.amount))
            .filter(models.Payment.status == "posted", pay_party.isnot(None))
            .group_by(pay_party),
            pay_party,
        ).all()
    )
    credits = _credits(db, kind, id_list)
    return {pid: _dec(op) + _dec(charges.get(pid)) - _dec(paid.get(pid)) - credits.get(pid, ZERO) for pid, op in opening}


def _local_day(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ).date()


def _return_entries(entries: list, r, typ: str, prefix: str) -> None:
    """A return lowers the balance by its total; any cash handed back at the time is shown as a separate line."""
    day = _local_day(r.created_at)
    entries.append((day, 0, r.id, typ, f"{prefix}-{r.id}", "مرتجع", ZERO, _dec(r.total_amount)))
    if _dec(r.refund_amount) > 0:
        entries.append((day, 1, r.id, typ, f"{prefix}-{r.id}", f"رد نقدي ({METHOD_LABEL.get(r.method, r.method)})", _dec(r.refund_amount), ZERO))


def build_statement(
    db: Session, kind: str, party_id: int, date_from: Optional[date], date_to: Optional[date],
    company_id: Optional[int] = None,
) -> Optional[schemas.Statement]:
    """Chronological account statement with running balance. Returns None if the party does not exist.

    company_id يقيد الطرف بشركته — Session.get يتجاوز فلتر العزل التلقائي، فالتصفية
    الصريحة هي خط الدفاع ضد قراءة كشف حساب شركة أخرى."""
    party_model = models.Customer if kind == "customer" else models.Supplier
    party_q = db.query(party_model).filter(party_model.id == party_id)
    if kind == "customer":
        order_model, order_party, order_status = models.SalesOrder, models.SalesOrder.customer_id, "confirmed"
        ret_model, ret_party = models.SalesReturn, models.SalesReturn.customer_id
        pay_party = models.Payment.customer_id
    else:
        order_model, order_party, order_status = models.PurchaseOrder, models.PurchaseOrder.supplier_id, "received"
        ret_model, ret_party = models.PurchaseReturn, models.PurchaseReturn.supplier_id
        pay_party = models.Payment.supplier_id
    if company_id is not None:
        party_q = party_q.filter(party_model.company_id == company_id)
    party = party_q.first()
    if party is None:
        return None

    # (day, group, id, type, ref, description, charge, payment); group orders charges before payments on a day
    entries: List[Tuple[date, int, int, str, str, str, Decimal, Decimal]] = []
    orders = (
        db.query(order_model)
        .filter(order_party == party_id, order_model.status == order_status)
        .all()
    )
    label = "sale" if kind == "customer" else "purchase"
    ref_prefix = "SO" if kind == "customer" else "PO"
    desc = "فاتورة بيع" if kind == "customer" else "أمر شراء مستلم"
    for o in orders:
        entries.append((_local_day(o.updated_at), 0, o.id, label, f"{ref_prefix}-{o.id}", desc, _dec(o.total_amount), ZERO))  # type: ignore
    pays = db.query(models.Payment).filter(pay_party == party_id, models.Payment.status == "posted").all()
    pay_type, pay_prefix, pay_word = ("receipt", "RC", "سند قبض") if kind == "customer" else ("payment", "PY", "سند دفع")
    ret_prefix = "SR" if kind == "customer" else "PR"
    for r in db.query(ret_model).filter(ret_party == party_id).all():
        _return_entries(entries, r, f"{label}_return", ret_prefix)
    for p in pays:
        detail = " · ".join(x for x in (METHOD_LABEL.get(p.method, p.method), p.reference) if x)  # type: ignore
        entries.append((p.paid_on, 1, p.id, pay_type, f"{pay_prefix}-{p.id}", f"{pay_word} ({detail})", ZERO, _dec(p.amount)))  # type: ignore

    entries.sort(key=lambda e: (e[0], e[1], e[2]))
    opening = _dec(party.opening_balance)
    if date_from is not None:
        opening += sum((e[6] - e[7] for e in entries if e[0] < date_from), ZERO)

    lines: List[schemas.StatementLine] = []
    running, total_charges, total_payments = opening, ZERO, ZERO
    for day, _, _, typ, ref, desc, charge, payment in entries:
        if (date_from is not None and day < date_from) or (date_to is not None and day > date_to):
            continue
        running += charge - payment
        total_charges += charge
        total_payments += payment
        lines.append(
            schemas.StatementLine(date=day, type=typ, ref=ref, description=desc, charge=charge, payment=payment, balance=running)  # type: ignore
        )
    return schemas.Statement(
        kind=kind,  # type: ignore
        party_id=party.id,  # type: ignore
        party_name=party.name,  # type: ignore
        date_from=date_from,
        date_to=date_to,
        opening=opening,
        lines=lines,
        total_charges=total_charges,
        total_payments=total_payments,
        closing=running,
    )


# ----------------------------------------------------------------------------- invoice settlement
def order_settlements(db: Session, kind: str, party_id: int) -> Dict[int, Tuple[Decimal, Decimal]]:
    """{order_id: (paid, remaining)} for the party's committed orders.

    Payments are not tied to a specific invoice. They are applied oldest-first (FIFO): first to the opening
    balance, then to confirmed sales / received purchases in the order they were committed. Because it is
    derived, voiding a payment or changing an opening balance re-computes everything consistently.
    """
    if kind == "customer":
        party, order, order_party, done = models.Customer, models.SalesOrder, models.SalesOrder.customer_id, "confirmed"
        pay_party = models.Payment.customer_id
    else:
        party, order, order_party, done = models.Supplier, models.PurchaseOrder, models.PurchaseOrder.supplier_id, "received"
        pay_party = models.Payment.supplier_id
    p = db.get(party, party_id)
    if p is None:
        return {}
    paid = db.query(func.coalesce(func.sum(models.Payment.amount), 0)).filter(pay_party == party_id, models.Payment.status == "posted").scalar()
    pool = max(_dec(paid) + _credits(db, kind, [party_id]).get(party_id, ZERO) - _dec(p.opening_balance), ZERO)
    out: Dict[int, Tuple[Decimal, Decimal]] = {}
    for oid, total in (
        db.query(order.id, order.total_amount).filter(order_party == party_id, order.status == done).order_by(order.updated_at, order.id).all()
    ):
        total = _dec(total)
        applied = min(pool, total)
        pool -= applied
        out[oid] = (applied, total - applied)
    return out


def attach_settlement(db: Session, kind: str, orders) -> None:
    """Sets paid_amount / balance_due / payment_status on each order (None for draft or cancelled ones)."""
    items = orders if isinstance(orders, list) else [orders]
    cache: Dict[int, Dict[int, Tuple[Decimal, Decimal]]] = {}
    for o in items:
        pid = o.customer_id if kind == "customer" else o.supplier_id
        if pid not in cache:
            cache[pid] = order_settlements(db, kind, pid)
        entry = cache[pid].get(o.id)
        if entry is None:
            o.paid_amount = o.balance_due = o.payment_status = None
            continue
        paid, rest = entry
        o.paid_amount, o.balance_due = paid, rest
        o.payment_status = "paid" if rest == 0 else ("partial" if paid > 0 else "unpaid")


# ----------------------------------------------------------------------------- aging
BUCKETS = ("current", "d31_60", "d61_90", "d90_plus")


def _bucket(days: int) -> str:
    return "current" if days <= 30 else "d31_60" if days <= 60 else "d61_90" if days <= 90 else "d90_plus"


def build_aging(db: Session, kind: str, as_of: Optional[date] = None) -> schemas.AgingReport:
    """Unpaid amounts by age of the invoice (days since it was committed), using the same FIFO settlement as
    invoice status: payments clear the opening balance first, then the oldest invoices. Credits are ignored."""
    as_of = as_of or datetime.now(LOCAL_TZ).date()
    if kind == "customer":
        party, order, order_party, done = models.Customer, models.SalesOrder, models.SalesOrder.customer_id, "confirmed"
        pay_party = models.Payment.customer_id
    else:
        party, order, order_party, done = models.Supplier, models.PurchaseOrder, models.PurchaseOrder.supplier_id, "received"
        pay_party = models.Payment.supplier_id
    paid = dict(
        db.query(pay_party, func.sum(models.Payment.amount)).filter(models.Payment.status == "posted", pay_party.isnot(None)).group_by(pay_party).all()
    )
    credits = _credits(db, kind)
    by_party: Dict[int, List] = {}
    for pid, total, stamp in db.query(order_party, order.total_amount, order.updated_at).filter(order.status == done).order_by(order.updated_at, order.id).all():
        by_party.setdefault(pid, []).append((_dec(total), _local_day(stamp)))
    rows: List[schemas.AgingRow] = []
    for p in db.query(party).order_by(party.id).all():
        pool = _dec(paid.get(p.id)) + credits.get(p.id, ZERO)  # type: ignore
        opening = max(_dec(p.opening_balance), ZERO)
        cleared = min(pool, _dec(p.opening_balance)) if _dec(p.opening_balance) > 0 else ZERO
        pool = max(pool - _dec(p.opening_balance), ZERO)
        b = {k: ZERO for k in BUCKETS}
        for total, day in by_party.get(p.id, []):  # type: ignore
            applied = min(pool, total)
            pool -= applied
            if total - applied > 0:
                b[_bucket(max((as_of - day).days, 0))] += total - applied
        open_left = opening - cleared
        total_due = open_left + sum(b.values(), ZERO)
        if total_due > 0:
            rows.append(schemas.AgingRow(party_id=p.id, name=p.name, phone=p.phone, opening=open_left, total=total_due, **b))  # type: ignore
    rows.sort(key=lambda r: (-r.total, r.party_id))
    tot = {k: sum((getattr(r, k) for r in rows), ZERO) for k in ("opening", *BUCKETS, "total")}
    return schemas.AgingReport(as_of=as_of, rows=rows, **{f"total_{k}": v for k, v in tot.items()})


# ----------------------------------------------------------------------------- credit limit
def check_credit_limit(
    db: Session,
    customer_id: int,
    additional: Decimal,
    perms=None,
) -> None:
    """الحد الائتماني: المديونية الحالية + دين جديد مسموحة ضمن الحد فقط.

    additional = الدين الجديد الذي سيُسجّل بهذه العملية (بعد أي مدفوعات فورية).
    التجاوز مسموح لمن يملك "*" (admin/manager) أو صلاحية sales.order.credit_exceed،
    أو حين يكون نظام الصلاحيات غير مفعّل (perms=None). العملاء بلا حد (NULL) غير مقيدين."""
    from decimal import Decimal as _D

    from fastapi import HTTPException, status as _status

    from .permissions import user_has_permission

    if additional <= 0:
        return
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == customer_id, models.Customer.company_id == db.info["company_id"])
        .first()
    )
    if customer is None or customer.credit_limit is None:
        return
    if perms is not None and "*" not in perms and not user_has_permission(perms, "sales.order.credit_exceed"):
        # الحد الائتماني يُقاس على دين الشركة الحقيقي — لا على الشريحة المرئية للموظف
        # (فلتر الفروع يخفي سندات خزائن الفروع الأخرى عن الموظفين) — نتجاوزه مؤقتًا.
        prev_scope = db.info.get("ignore_tenant_scope", False)
        db.info["ignore_tenant_scope"] = True
        try:
            current = party_balances(db, "customer", [customer_id]).get(customer_id, ZERO)
        finally:
            db.info["ignore_tenant_scope"] = prev_scope
        remaining = _D(str(customer.credit_limit)) - _D(str(current))
        if _D(str(additional)) > remaining:
            raise HTTPException(
                _status.HTTP_409_CONFLICT,
                f"تجاوز الحد الائتماني للعميل «{customer.name}»: الحد {_D(str(customer.credit_limit)):.2f} "
                f"· المستحق حاليًا {_D(str(current)):.2f} · المتبقي {max(remaining, _D('0')):.2f} · "
                f"المطلوب {_D(str(additional)):.2f}",
            )
