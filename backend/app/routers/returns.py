"""Sales returns (customer sends goods back) and purchase returns (we send goods back to a supplier).

A return is final (no edit/void): it is tied to the original order lines, can never exceed what was sold/received
minus what was already returned, moves stock and changes the party's balance by (total - refund_amount).
"""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from .. import models, schemas, stock
from ..accounting import seed_default_coa, link_party_coa
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user
from ..pagination import paginate
from .orders import _locked_product

sales_returns = APIRouter(prefix="/sales-returns", tags=["returns"], dependencies=[Depends(get_current_user)])
purchase_returns = APIRouter(
    prefix="/purchase-returns", tags=["returns"], dependencies=[Depends(get_current_user)]
)

# kind -> the models and field names that differ between the two directions
CFG = {
    "sales": dict(
        ret=models.SalesReturn, ret_item=models.SalesReturnItem, order=models.SalesOrder, order_item=models.SalesOrderItem,
        party_col="customer_id", order_party="customer_id", done="confirmed", price="unit_price", prefix="SR", reason="sales_return", sign=1,
    ),
    "purchase": dict(
        ret=models.PurchaseReturn, ret_item=models.PurchaseReturnItem, order=models.PurchaseOrder, order_item=models.PurchaseOrderItem,
        party_col="supplier_id", order_party="supplier_id", done="received", price="unit_cost", prefix="PR", reason="purchase_return", sign=-1,
    ),
}


def _post_cogs_reversal(db: Session, company_id: int, user: models.User, ret, cogs_total: Decimal, prefix: str) -> None:
    """A sales return puts goods back in stock: relieve the COGS recorded at sale time
    (Debit Inventory 1101, Credit COGS 5100). Runs inside the caller's try/except, and
    stays silent when either ledger account is missing (same degrade rule as the
    credit-note entries)."""
    if cogs_total <= 0:
        return
    from ..accounting import AccountingEngine
    inventory_acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1101"
    ).first()
    cogs_acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code == "5100"
    ).first()
    if inventory_acc and cogs_acc:
        AccountingEngine.create_entry(
            db=db, company_id=company_id, user_id=user.id,
            description=f"COGS Reversal {prefix}-{ret.id}",
            items=[
                {"account_id": inventory_acc.id, "debit": cogs_total, "credit": 0},
                {"account_id": cogs_acc.id, "debit": 0, "credit": cogs_total},
            ],
            reference=f"{prefix}-{ret.id}",
        )


def _create(kind: str, payload: schemas.ReturnCreate, db: Session, user: models.User):
    if payload.order_id is None:
        return _create_standalone(kind, payload, db, user)
    c = CFG[kind]
    order = db.get(c["order"], payload.order_id)
    if order is None:
        raise HTTPException(422, f"Order {payload.order_id} does not exist")
    if order.status != c["done"]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only a {c['done']} order can have returns (this one is {order.status})")

    # Lock the order lines so two simultaneous returns cannot both take the last returnable units.
    wanted: dict = {}
    for it in payload.items:
        wanted[it.order_item_id] = wanted.get(it.order_item_id, 0) + it.quantity
    lines = {
        l.id: l
        for l in db.query(c["order_item"]).filter(c["order_item"].id.in_(list(wanted))).with_for_update().all()
    }
    total = Decimal("0")
    cogs_total = Decimal("0")  # sales only: cost frozen on the returned order lines
    ret = c["ret"](
        order_id=order.id,
        warehouse_id=order.warehouse_id,
        method=payload.method,
        notes=payload.notes,
        created_by=user.id,
        **{c["party_col"]: getattr(order, c["order_party"])},
    )
    if kind == "sales":
        # The rep comes from the original invoice unless the client overrides it — only valid sales reps are stored.
        chosen_rep = payload.rep_id if payload.rep_id is not None else getattr(order, "rep_id", None)
        ret.rep_id = chosen_rep if chosen_rep and db.get(models.SalesRep, chosen_rep) else None
    for line_id, qty in wanted.items():
        line = lines.get(line_id)
        if line is None or line.order_id != order.id:
            raise HTTPException(422, f"Line {line_id} does not belong to order {order.id}")
        db.refresh(line)  # fresh returned quantity after taking the lock
        left = line.quantity - line.returned_quantity
        if qty > left:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Line {line_id}: only {left} unit(s) can still be returned")
        price = getattr(line, c["price"])
        ret.items.append(c["ret_item"](order_item_id=line.id, product_id=line.product_id, quantity=qty, unit_price=price))
        total += price * Decimal(str(qty))
        if kind == "sales":
            cogs_total += (line.unit_cost or Decimal("0")) * Decimal(str(qty))
    if payload.refund_amount > total:
        raise HTTPException(422, "refund_amount cannot exceed the return total")
    ret.total_amount = total
    ret.refund_amount = payload.refund_amount
    db.add(ret)
    db.flush()

    # Stock: a sales return puts goods back; a purchase return takes them out (never below zero).
    per_product: dict = {}
    for it in ret.items:
        per_product[it.product_id] = per_product.get(it.product_id, 0) + it.quantity
    for pid in sorted(per_product):
        product = _locked_product(db, pid)
        change = stock.q3(c["sign"] * per_product[pid])  # توحيد إلى Decimal (الكمية قد تأتي float من الـ API)
        if change < 0 and stock.available(db, pid, order.warehouse_id) + change < 0:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Insufficient stock to return: " + stock.shortage_message(db, product, order.warehouse_id, -change),
            )
        stock.move_stock(db, product, order.warehouse_id, change, c["reason"], f"{c['prefix']}-{ret.id}")
        if change < 0:
            stock.consume_lots(db, product, order.warehouse_id, -change)  # FEFO على مرتجع الشراء
    # Auto-post a journal entry reversing the original transaction (credit note).
    company_id = db.info["company_id"]
    seed_default_coa(db, company_id)
    party = db.get(models.Customer if kind == "sales" else models.Supplier, getattr(order, c["order_party"]))
    if party is not None:
        link_party_coa(db, party, company_id, is_customer=(kind == "sales"))
    try:
        if kind == "sales":
            revenue_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "4101").first()
            ar_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1100").first()
            if revenue_acc and ar_acc and party and party.chart_account_id and ret.refund_amount == 0:
                from ..accounting import AccountingEngine
                AccountingEngine.create_entry(
                    db=db, company_id=company_id, user_id=user.id,
                    description=f"Sales Return {c['prefix']}-{ret.id}",
                    items=[
                        {"account_id": revenue_acc.id, "debit": total, "credit": 0},
                        {"account_id": party.chart_account_id, "debit": 0, "credit": total},
                    ],
                    reference=f"{c['prefix']}-{ret.id}", date=ret.created_at.date() if hasattr(ret, "created_at") and ret.created_at else None,
                )
            # Goods are back in stock: relieve the COGS recorded on the original sale.
            _post_cogs_reversal(db, company_id, user, ret, cogs_total, c["prefix"])
        else:
            ap_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "2100").first()
            inventory_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1101").first()
            if ap_acc and inventory_acc and party and party.chart_account_id and ret.refund_amount == 0:
                from ..accounting import AccountingEngine
                AccountingEngine.create_entry(
                    db=db, company_id=company_id, user_id=user.id,
                    description=f"Purchase Return {c['prefix']}-{ret.id}",
                    items=[
                        {"account_id": party.chart_account_id, "debit": total, "credit": 0},
                        {"account_id": inventory_acc.id, "debit": 0, "credit": total},
                    ],
                    reference=f"{c['prefix']}-{ret.id}", date=None,
                )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Return %s: JE skipped: %s", ret.id, exc)

    audit(db, user, "return", f"{kind}_return", ret, f"{c['prefix']}-{ret.id} · إجمالي {total} · مردود نقداً {ret.refund_amount} · أمر {order.id}")
    db.commit()
    db.refresh(ret)
    return ret


def _create_standalone(kind: str, payload: schemas.ReturnCreate, db: Session, user: models.User):
    """A return not tied to any original order: pick products directly.

    Sales: stock goes up. Purchase: stock goes down (never below zero).
    The party (customer/supplier) is optional; when chosen the balance and the
    credit-note journal entry follow the same rules as order-bound returns.
    """
    c = CFG[kind]
    warehouse = db.get(models.Warehouse, payload.warehouse_id) if payload.warehouse_id else None
    if warehouse is None:
        raise HTTPException(422, "اختر المخزن للمرتجع")
    if kind == "sales":
        party = db.get(models.Customer, payload.customer_id) if payload.customer_id else None
        if payload.customer_id and party is None:
            raise HTTPException(422, f"Customer {payload.customer_id} does not exist")
    else:
        party = db.get(models.Supplier, payload.supplier_id) if payload.supplier_id else None
        if payload.supplier_id and party is None:
            raise HTTPException(422, f"Supplier {payload.supplier_id} does not exist")

    total = Decimal("0")
    cogs_total = Decimal("0")  # sales only: current cost price of the returned products
    ret = c["ret"](
        order_id=None,
        warehouse_id=warehouse.id,
        method=payload.method,
        notes=payload.notes,
        created_by=user.id,
        **({c["party_col"]: party.id} if party is not None else {c["party_col"]: None}),
    )
    if kind == "sales" and payload.rep_id and db.get(models.SalesRep, payload.rep_id):
        ret.rep_id = payload.rep_id
    for it in payload.items:
        if not it.product_id:
            raise HTTPException(422, "اختر منتجًا لكل سطر مرتجع")
        product = db.get(models.Product, it.product_id)
        if product is None:
            raise HTTPException(422, f"Product {it.product_id} does not exist")
        if it.unit_price is not None and it.unit_price < 0:
            raise HTTPException(422, "السعر لا يمكن أن يكون سالبًا")
        price = it.unit_price if it.unit_price is not None else getattr(product, c["price"])
        ret.items.append(c["ret_item"](order_item_id=None, product_id=product.id, quantity=it.quantity, unit_price=price))
        total += price * it.quantity
        if kind == "sales":
            cogs_total += (product.cost_price or Decimal("0")) * it.quantity
    if payload.refund_amount > total:
        raise HTTPException(422, "refund_amount cannot exceed the return total")
    ret.total_amount = total
    ret.refund_amount = payload.refund_amount
    db.add(ret)
    db.flush()

    # Stock: a sales return puts goods back; a purchase return takes them out (never below zero).
    per_product: dict = {}
    for it in ret.items:
        per_product[it.product_id] = per_product.get(it.product_id, 0) + it.quantity
    for pid in sorted(per_product):
        product = _locked_product(db, pid)
        change = stock.q3(c["sign"] * per_product[pid])  # توحيد إلى Decimal (الكمية قد تأتي float من الـ API)
        if change < 0 and stock.available(db, pid, warehouse.id) + change < 0:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Insufficient stock to return: " + stock.shortage_message(db, product, warehouse.id, -change),
            )
        stock.move_stock(db, product, warehouse.id, change, c["reason"], f"{c['prefix']}-{ret.id}")
        if change < 0:
            stock.consume_lots(db, product, warehouse.id, -change)  # FEFO على مرتجع الشراء

    # Credit note journal entry — same rules as order-bound returns.
    company_id = db.info["company_id"]
    seed_default_coa(db, company_id)
    if party is not None:
        link_party_coa(db, party, company_id, is_customer=(kind == "sales"))
    try:
        if kind == "sales":
            revenue_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "4101").first()
            ar_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1100").first()
            if revenue_acc and ar_acc and party and party.chart_account_id and ret.refund_amount == 0:
                from ..accounting import AccountingEngine
                AccountingEngine.create_entry(
                    db=db, company_id=company_id, user_id=user.id,
                    description=f"Sales Return {c['prefix']}-{ret.id}",
                    items=[
                        {"account_id": revenue_acc.id, "debit": total, "credit": 0},
                        {"account_id": party.chart_account_id, "debit": 0, "credit": total},
                    ],
                    reference=f"{c['prefix']}-{ret.id}", date=ret.created_at.date() if hasattr(ret, "created_at") and ret.created_at else None,
                )
            # Goods are back in stock: relieve the COGS recorded on the original sale.
            _post_cogs_reversal(db, company_id, user, ret, cogs_total, c["prefix"])
        else:
            ap_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "2100").first()
            inventory_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1101").first()
            if ap_acc and inventory_acc and party and party.chart_account_id and ret.refund_amount == 0:
                from ..accounting import AccountingEngine
                AccountingEngine.create_entry(
                    db=db, company_id=company_id, user_id=user.id,
                    description=f"Purchase Return {c['prefix']}-{ret.id}",
                    items=[
                        {"account_id": party.chart_account_id, "debit": total, "credit": 0},
                        {"account_id": inventory_acc.id, "debit": 0, "credit": total},
                    ],
                    reference=f"{c['prefix']}-{ret.id}", date=None,
                )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Standalone return %s: JE skipped: %s", ret.id, exc)

    party_txt = f" · {c['party_col'][:-3]} {party.id}" if party is not None else " · بدون طرف"
    audit(db, user, "return", f"{kind}_return", ret, f"{c['prefix']}-{ret.id} · إجمالي {total} · مردود نقداً {ret.refund_amount} · مرتجع مستقل{party_txt}")
    db.commit()
    db.refresh(ret)
    return ret


def _register(router: APIRouter, kind: str) -> None:
    c = CFG[kind]
    party_filter = c["party_col"]

    @router.post("", response_model=schemas.ReturnOut, status_code=status.HTTP_201_CREATED)
    def create(payload: schemas.ReturnCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
        return _create(kind, payload, db, user)

    @router.get("", response_model=List[schemas.ReturnOut])
    def list_returns(
        response: Response,
        order_id: Optional[int] = None,
        party_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50,
        db: Session = Depends(get_db),
    ):
        q = db.query(c["ret"])
        if order_id is not None:
            q = q.filter(c["ret"].order_id == order_id)
        if party_id is not None:
            q = q.filter(getattr(c["ret"], party_filter) == party_id)
        return paginate(q, response, skip, limit, c["ret"].id.desc())

    @router.get("/{return_id}", response_model=schemas.ReturnOut)
    def get_return(return_id: int, db: Session = Depends(get_db)):
        r = db.get(c["ret"], return_id)
        if r is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Return {return_id} not found")
        return r


_register(sales_returns, "sales")
_register(purchase_returns, "purchase")
