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
    return {pid: _dec(op) + _dec(charges.get(pid)) - _dec(paid.get(pid)) for pid, op in opening}


def _local_day(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ).date()


def build_statement(
    db: Session, kind: str, party_id: int, date_from: Optional[date], date_to: Optional[date]
) -> Optional[schemas.Statement]:
    """Chronological account statement with running balance. Returns None if the party does not exist."""
    if kind == "customer":
        party = db.get(models.Customer, party_id)
    else:
        party = db.get(models.Supplier, party_id)
    if party is None:
        return None

    # (day, group, id, type, ref, description, charge, payment); group orders charges before payments on a day
    entries: List[Tuple[date, int, int, str, str, str, Decimal, Decimal]] = []
    if kind == "customer":
        orders = (
            db.query(models.SalesOrder)
            .filter(models.SalesOrder.customer_id == party_id, models.SalesOrder.status == "confirmed")
            .all()
        )
        for o in orders:
            entries.append((_local_day(o.updated_at), 0, o.id, "sale", f"SO-{o.id}", "فاتورة بيع", _dec(o.total_amount), ZERO))
        pays = db.query(models.Payment).filter(models.Payment.customer_id == party_id, models.Payment.status == "posted").all()
        pay_type, pay_prefix, pay_word = "receipt", "RC", "سند قبض"
    else:
        orders = (
            db.query(models.PurchaseOrder)
            .filter(models.PurchaseOrder.supplier_id == party_id, models.PurchaseOrder.status == "received")
            .all()
        )
        for o in orders:
            entries.append((_local_day(o.updated_at), 0, o.id, "purchase", f"PO-{o.id}", "أمر شراء مستلم", _dec(o.total_amount), ZERO))
        pays = db.query(models.Payment).filter(models.Payment.supplier_id == party_id, models.Payment.status == "posted").all()
        pay_type, pay_prefix, pay_word = "payment", "PY", "سند دفع"
    for p in pays:
        detail = " · ".join(x for x in (METHOD_LABEL.get(p.method, p.method), p.reference) if x)
        entries.append((p.paid_on, 1, p.id, pay_type, f"{pay_prefix}-{p.id}", f"{pay_word} ({detail})", ZERO, _dec(p.amount)))

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
            schemas.StatementLine(date=day, type=typ, ref=ref, description=desc, charge=charge, payment=payment, balance=running)
        )
    return schemas.Statement(
        kind=kind,
        party_id=party.id,
        party_name=party.name,
        date_from=date_from,
        date_to=date_to,
        opening=opening,
        lines=lines,
        total_charges=total_charges,
        total_payments=total_payments,
        closing=running,
    )
