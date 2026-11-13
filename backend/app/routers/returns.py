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


def _post_refund_cash_entry(db: Session, company_id: int, user: models.User, ret, kind: str, prefix: str) -> None:
    """المرتجع المردود نقداً: النقد يخرج/يدخل الصندوق فعلياً — قيد إلزامي.

    مرتجع البيع: دائن العميل (الإجمالي) ثم مدين العميل × دائن الصندوق (1111) بقيمة المردود
    → صافي أثر العميل (الإجمالي − المردود) كما تحسبه دفترية الأطراف في accounts.py.
    مرتجع الشراء: العكس (مدين الصندوق × دائن المورد). بدون هذا القيد يبقى النقد
    خارج الدفاتر وكشف حساب الطرف يخالف القيود.
    """
    refund = Decimal(str(ret.refund_amount or 0))
    if refund <= 0:
        return
    party = db.get(models.Customer if kind == "sales" else models.Supplier, ret.customer_id if kind == "sales" else ret.supplier_id)  # type: ignore
    if party is None or not party.chart_account_id:
        return  # نفس قاعدة التدهور: مرتجع بلا طرف/حساب دفتري لا يُرحّل
    cash_acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1111"
    ).first()
    if cash_acc is None or cash_acc.is_group:
        # seed_default_coa يضمن وجوده — غيابه يعني شجرة محذوفة: نفشل بدل صمت محاسبي
        raise HTTPException(409, "حساب الصندوق (1111) غير موجود — حدّث شجرة الحسابات")
    from ..accounting import AccountingEngine
    if kind == "sales":
        items = [
            {"account_id": party.chart_account_id, "debit": refund, "credit": 0},
            {"account_id": cash_acc.id, "debit": 0, "credit": refund},
        ]
        desc = f"Sales Return Cash Refund {prefix}-{ret.id}"
    else:
        items = [
            {"account_id": cash_acc.id, "debit": refund, "credit": 0},
            {"account_id": party.chart_account_id, "debit": 0, "credit": refund},
        ]
        desc = f"Purchase Return Cash Refund {prefix}-{ret.id}"
    AccountingEngine.create_entry(
        db=db, company_id=company_id, user_id=user.id,
        description=desc, items=items,
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
    # الضريبة وحصة الخصم من المستند الأصلي بنسبة المرتجع — إصلاح تدقيق 2026-11-14:
    # الإشعار الدائن يعكس ضريبة 2130/1145 وحصة الطرف كما في فاتورة الأصل (لا مرتجع بلا ضريبة صامت)
    if kind == "sales":
        # أساس التوزيع = إجمالي بنود الأصل الخام (قبل الخصم) — order.subtotal صافٍ بعد الخصم
        order_gross = sum((Decimal(str(it.quantity)) * it.unit_price for it in order.items), Decimal("0"))
        order_discount = Decimal(str(order.discount_amount or 0))
        discount_share = (order_discount * total / order_gross) if order_gross > 0 and order_discount else Decimal("0")
        tax_rate = Decimal(str(order.tax_rate or 0))
        net_after = total - discount_share
        tax = (net_after * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    else:
        order_gross = sum((Decimal(str(it.quantity)) * it.unit_cost for it in order.items), Decimal("0"))
        order_discount = Decimal(str(order.discount_amount or 0))
        discount_share = (order_discount * total / order_gross) if order_gross > 0 and order_discount else Decimal("0")
        order_net = order_gross - order_discount
        tax_rate = (Decimal(str(order.tax_amount or 0)) / order_net * Decimal("100")).quantize(Decimal("0.01")) if order_net > 0 else Decimal("0")
        net_after = total - discount_share
        tax = (Decimal(str(order.tax_amount or 0)) * net_after / order_net).quantize(Decimal("0.01")) if order_net > 0 else Decimal("0")
    ret.discount_share = discount_share
    ret.tax_rate = tax_rate
    ret.tax_amount = tax
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
        net_after = total - discount_share
        gross = net_after + tax
        if kind == "sales":
            revenue_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "4101").first()
            if revenue_acc and party and party.chart_account_id:
                from ..accounting import AccountingEngine
                # عكس فاتورة البيع: مدين الإيراد (الصافي بعد حصة الخصم) + مدين ضريبة المخرجات 2130
                # / دائن العميل بالإجمالي — كما في قيد الأصل بالضبط
                items = [
                    {"account_id": revenue_acc.id, "debit": net_after, "credit": 0},
                    {"account_id": party.chart_account_id, "debit": 0, "credit": gross},
                ]
                if tax > 0:
                    vat_out_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "2130").first()
                    if vat_out_acc is None or vat_out_acc.is_group:
                        raise HTTPException(409, "حساب ضريبة المخرجات (2130) غير موجود — حدّث شجرة الحسابات")
                    items.insert(1, {"account_id": vat_out_acc.id, "debit": tax, "credit": 0})
                AccountingEngine.create_entry(
                    db=db, company_id=company_id, user_id=user.id,
                    description=f"Sales Return {c['prefix']}-{ret.id}",
                    items=items,
                    reference=f"{c['prefix']}-{ret.id}", date=ret.created_at.date() if hasattr(ret, "created_at") and ret.created_at else None,
                )
            # Goods are back in stock: relieve the COGS recorded on the original sale.
            _post_cogs_reversal(db, company_id, user, ret, cogs_total, c["prefix"])
        else:
            inventory_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1101").first()
            if inventory_acc and party and party.chart_account_id:
                from ..accounting import AccountingEngine
                # عكس استلام الشراء: مدين المورد بالإجمالي / دائن المخزون (الصافي) + دائن مدخلات 1145
                items = [
                    {"account_id": party.chart_account_id, "debit": gross, "credit": 0},
                    {"account_id": inventory_acc.id, "debit": 0, "credit": net_after},
                ]
                if tax > 0:
                    vat_in_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1145").first()
                    if vat_in_acc is None or vat_in_acc.is_group:
                        raise HTTPException(409, "حساب ضريبة المدخلات (1145) غير موجود — حدّث شجرة الحسابات")
                    items.insert(1, {"account_id": vat_in_acc.id, "debit": 0, "credit": tax})
                AccountingEngine.create_entry(
                    db=db, company_id=company_id, user_id=user.id,
                    description=f"Purchase Return {c['prefix']}-{ret.id}",
                    items=items,
                    reference=f"{c['prefix']}-{ret.id}", date=None,
                )
        # المردود النقدي: قيد صندوق إلزامي (بيع: صادر — شراء: وارد)
        _post_refund_cash_entry(db, company_id, user, ret, kind, c["prefix"])
    except Exception:
        # القيد إلزامي: فشل الترحيل (فترة مغلقة/حساب مفقود) يُفشل المرتجع كله —
        # لا مرتجع بلا قيد؛ المعاملة تُرجع ذريًا (لا commit بعد هذه النقطة)
        raise

    audit(db, user, "return", f"{kind}_return", ret, f"{c['prefix']}-{ret.id} · إجمالي {total} · مردود نقداً {ret.refund_amount} · أمر {order.id}")
    db.commit()
    db.refresh(ret)
    # تنبيه تطبيق المندوب: مرتجع على فاتورته (صندوق + Push إن ضُبط FCM)
    if kind == "sales" and ret.rep_id:
        from ..push import notify_rep
        try:
            notify_rep(db, ret.rep_id, kind="return_recorded",
                       title=f"مرتجع {c['prefix']}-{ret.id}",
                       body=f"إجمالي {total} ج.م — مردود نقداً {ret.refund_amount} — العميل {getattr(order, 'party_name', '') or ''}",
                       ref_id=ret.id)
        except Exception:
            pass  # الإشعار لا يعطل المرتجع أبدًا
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
        qty_dec = stock.q3(it.quantity)
        ret.items.append(c["ret_item"](order_item_id=None, product_id=product.id, quantity=it.quantity, unit_price=price))
        total += price * qty_dec
        if kind == "sales":
            cogs_total += (product.cost_price or Decimal("0")) * qty_dec
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
            if revenue_acc and party and party.chart_account_id:
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
            inventory_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1101").first()
            if inventory_acc and party and party.chart_account_id:
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
        # المردود النقدي: قيد صندوق إلزامي (بيع: صادر — شراء: وارد)
        _post_refund_cash_entry(db, company_id, user, ret, kind, c["prefix"])
    except Exception:
        # القيد إلزامي هنا أيضاً — نفس منطق المرتجع المرتبط بأمر
        raise

    party_txt = f" · {c['party_col'][:-3]} {party.id}" if party is not None else " · بدون طرف"
    audit(db, user, "return", f"{kind}_return", ret, f"{c['prefix']}-{ret.id} · إجمالي {total} · مردود نقداً {ret.refund_amount} · مرتجع مستقل{party_txt}")
    db.commit()
    db.refresh(ret)
    # تنبيه تطبيق المندوب: مرتجع مستقل منسوب له
    if kind == "sales" and ret.rep_id:
        from ..push import notify_rep
        try:
            notify_rep(db, ret.rep_id, kind="return_recorded",
                       title=f"مرتجع {c['prefix']}-{ret.id}",
                       body=f"إجمالي {total} ج.م — مردود نقداً {ret.refund_amount} · مرتجع مستقل",
                       ref_id=ret.id)
        except Exception:
            pass
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
        # Session.get يتجاوز فلتر العزل التلقائي — تصفية صريحة بالشركة (تدقيق 2026-11-14)
        company_id = db.info.get("company_id")
        r = (
            db.query(c["ret"]).filter(
                c["ret"].id == return_id,
                c["ret"].company_id == company_id,  # type: ignore[attr-defined]
            ).first()
            if company_id is not None
            else db.get(c["ret"], return_id)
        )
        if r is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Return {return_id} not found")
        return r


_register(sales_returns, "sales")
_register(purchase_returns, "purchase")
