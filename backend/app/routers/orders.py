"""Purchase orders (stock in) and sales orders (stock out).

Lifecycle
  purchases: draft -> received            (received adds stock)      | draft -> cancelled
  sales:     draft -> confirmed           (confirmed removes stock)  | draft -> cancelled
Stock is only touched on the transition, inside one transaction, with row locks.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..accounts import attach_settlement
from ..audit import audit
from ..deps import get_current_user
from ..pagination import paginate
from ..permissions import user_has_permission
from .. import exports, models, schemas, stock
from ..database import get_db
from ..accounting import AccountingEngine

purchases = APIRouter(prefix="/purchase-orders", tags=["purchases"], dependencies=[Depends(get_current_user)])
sales = APIRouter(prefix="/sales-orders", tags=["sales"], dependencies=[Depends(get_current_user)])


def _require(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(422, f"{label} {obj_id} does not exist")
    return obj


def _order_or_404(db: Session, model, order_id: int, label: str):
    order = db.get(model, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} {order_id} not found")
    return order


def _locked_order_or_404(db: Session, model, order_id: int, label: str):
    """Fetch the order with a row lock (SELECT ... FOR UPDATE) so concurrent
    lifecycle transitions of the same order are serialized before the status
    is checked and mutated. Ignored gracefully on SQLite (tests)."""
    if db.info.get("company_id") is not None and hasattr(model, "company_id"):
        query = db.query(model).filter(model.id == order_id, model.company_id == db.info["company_id"])  # type: ignore[attr-defined]
    else:
        query = db.query(model).filter(model.id == order_id)
    order = query.with_for_update().first()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} {order_id} not found")
    return order


def _locked_product(db: Session, product_id: int) -> models.Product:
    product = (
        db.query(models.Product).filter(models.Product.id == product_id).with_for_update().one_or_none()
    )
    if product is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Product {product_id} no longer exists")
    return product


def _require_draft(order, action: str):
    if order.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Cannot {action}: order is already '{order.status}'"
        )


# ======================= Purchases =======================
@purchases.post("/from-suggestions", response_model=schemas.PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
def create_purchase_order_from_suggestions(
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """مسودة أمر شراء من اقتراحات الشراء: كميات مقترحة بتكلفة المتوسط المرجح — بلا حركة مخزون حتى الاستلام."""

    supplier = db.query(models.Supplier).filter(
        models.Supplier.id == payload.get("supplier_id"), models.Supplier.company_id == db.info["company_id"]
    ).first()
    if supplier is None:
        raise HTTPException(422, "المورد غير موجود")
    from .reports import _purchase_suggestion_rows  # مصدر الحقيقة نفسه (استيراد متأخر لتفادي الدورية)
    warehouse = db.query(models.Warehouse).filter(
        models.Warehouse.id == payload.get("warehouse_id"), models.Warehouse.company_id == db.info["company_id"]
    ).first()
    if warehouse is None:
        raise HTTPException(422, "المخزن غير موجود")
    wanted_ids = set(payload.get("product_ids") or [])
    rows = _purchase_suggestion_rows(db, warehouse_id=warehouse.id, supplier_id=supplier.id)
    rows = [r for r in rows if not wanted_ids or r["product_id"] in wanted_ids]
    if not rows:
        raise HTTPException(409, "لا اقتراحات مطابقة لهذا المورد/المخزن")

    order = models.PurchaseOrder(
        supplier_id=supplier.id, warehouse_id=warehouse.id,  # type: ignore
        notes="مسودة من اقتراحات الشراء", status="draft",
    )
    total = Decimal("0")
    for r in rows:
        qty = Decimal(str(r["suggested_qty"])).quantize(Decimal("0.001"))
        cost = Decimal(str(r["cost_price"]))
        order.items.append(models.PurchaseOrderItem(
            product_id=r["product_id"], quantity=qty, unit_cost=cost,  # type: ignore
        ))
        total += cost * qty
    order.total_amount = total.quantize(Decimal("0.01"))  # type: ignore
    db.add(order)
    db.flush()
    audit(db, user, "create", "purchase_order", order,
          f"مسودة من اقتراحات الشراء · {len(rows)} صنف · الإجمالي {order.total_amount}")
    db.commit()
    db.refresh(order)
    return order


@purchases.post("", response_model=schemas.PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
def create_purchase_order(payload: schemas.PurchaseOrderCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    supplier = _require(db, models.Supplier, payload.supplier_id, "Supplier")
    _require(db, models.Warehouse, payload.warehouse_id, "Warehouse")
    safe = None
    if payload.payment_mode == "cash":
        if payload.safe_id is None:
            raise HTTPException(422, "Choose a safe for a cash purchase")
        safe = db.get(models.Safe, payload.safe_id)
        if safe is None or safe.company_id != db.info["company_id"] or not safe.is_active:
            raise HTTPException(422, "Safe not found or inactive")

    order = models.PurchaseOrder(
        supplier_id=payload.supplier_id, warehouse_id=payload.warehouse_id, notes=payload.notes  # type: ignore
    )
    total = Decimal("0")
    products = {}
    for item in payload.items:
        product = _require(db, models.Product, item.product_id, "Product")
        products[product.id] = product
        order.items.append(
            models.PurchaseOrderItem(
                product_id=product.id, quantity=item.quantity, unit_cost=item.unit_cost  # type: ignore
            )
        )
        total += item.unit_cost * Decimal(str(item.quantity))
    discount = total * payload.discount_value / Decimal("100") if payload.discount_mode == "percent" else payload.discount_value
    if discount > total:
        raise HTTPException(422, "Purchase discount cannot exceed the subtotal")
    taxable = total - discount
    tax = (taxable * payload.tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    total = taxable + tax
    order.total_amount = total  # type: ignore
    from ..pricing import resolve_currency
    _currency, _rate = resolve_currency(db, getattr(payload, "currency_id", None))
    if _currency is not None:
        order.currency_id = _currency.id  # type: ignore
        order.exchange_rate = _rate  # type: ignore
        order.foreign_total = (total / _rate).quantize(Decimal("0.01"))  # type: ignore
    if payload.discount_value or payload.tax_rate:
        discount_note = f"الخصم: {discount:.2f}" + (f" ({payload.discount_value}%)" if payload.discount_mode == "percent" else "")
        tax_note = f"ضريبة القيمة المضافة {payload.tax_rate}%: {tax:.2f}"
        order.notes = " · ".join(x for x in (payload.notes, discount_note, tax_note) if x)  # type: ignore
    db.add(order)
    db.flush()

    # Receipt is immediate; stock, cost, payable, and cash settlement commit atomically.
    # المتوسط المرجح: تكلفة الاستلام تُحتسب مرة واحدة لكل منتج (بنوده مجتمعة)
    received_qty: dict = {}
    received_value: dict = {}
    for item in order.items:
        received_qty[item.product_id] = received_qty.get(item.product_id, Decimal("0")) + Decimal(str(item.quantity))
        received_value[item.product_id] = received_value.get(item.product_id, Decimal("0")) + item.unit_cost * Decimal(str(item.quantity))
    for pid, qty in received_qty.items():
        product = products[pid]
        old_qty = max(Decimal(str(product.quantity or 0)), Decimal("0"))
        old_cost = Decimal(str(product.cost_price or 0))
        new_qty = old_qty + qty
        product.cost_price = ((old_qty * old_cost + received_value[pid]) / new_qty).quantize(Decimal("0.01")) if new_qty > 0 else product.cost_price
    for item in order.items:
        product = products[item.product_id]
        stock.move_stock(db, product, order.warehouse_id, item.quantity, "purchase_receipt", f"PO-{order.id}")  # type: ignore
        # لوط تلقائي لكل استلام شراء — كود اللوط = رقم أمر الشراء (التتبع العكسي)
        lot = (
            db.query(models.StockLot)
            .filter(
                models.StockLot.company_id == db.info["company_id"],
                models.StockLot.product_id == item.product_id,
                models.StockLot.warehouse_id == order.warehouse_id,
                models.StockLot.lot_code == f"PO-{order.id}",
            )
            .first()
        )
        if lot is None:
            db.add(models.StockLot(
                company_id=db.info["company_id"],  # type: ignore
                product_id=item.product_id,  # type: ignore
                warehouse_id=order.warehouse_id,  # type: ignore
                lot_code=f"PO-{order.id}",  # type: ignore
                source="purchase",  # type: ignore
                reference=f"PO-{order.id}",  # type: ignore
                qty_received=item.quantity,  # type: ignore
                qty_remaining=item.quantity,  # type: ignore
            ))
        else:
            lot.qty_received = Decimal(str(lot.qty_received)) + item.quantity  # type: ignore
            lot.qty_remaining = Decimal(str(lot.qty_remaining)) + item.quantity  # type: ignore
    order.status = "received"  # type: ignore

    from ..accounting import VAT_INPUT_CODE, link_party_coa, link_safe_coa, seed_default_coa
    company_id = db.info["company_id"]
    seed_default_coa(db, company_id)
    link_party_coa(db, supplier, company_id, is_customer=False)
    inventory_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1101").first()
    if not inventory_acc or not supplier.chart_account_id:
        db.rollback()
        raise HTTPException(409, "Purchase accounting accounts could not be initialized")
    # فصل ضريبة المدخلات: مدين المخزون (صافي) + مدين 1145 (ضريبة) · دائن المورد (إجمالي)
    po_tax = tax if payload.tax_rate else Decimal("0")  # ضريبة أمر الشراء المحسوبة أعلاه
    po_items = [
        {"account_id": inventory_acc.id, "debit": total - po_tax, "credit": 0},
        {"account_id": supplier.chart_account_id, "debit": 0, "credit": total},
    ]
    if po_tax > 0:
        vat_in_acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == company_id, models.ChartAccount.code == VAT_INPUT_CODE
        ).first()
        if vat_in_acc is None or vat_in_acc.is_group:
            db.rollback()
            raise HTTPException(409, "حساب ضريبة المشتريات (1145) غير موجود — حدّث شجرة الحسابات")
        po_items.insert(1, {"account_id": vat_in_acc.id, "debit": po_tax, "credit": 0})
    AccountingEngine.create_entry(
        db=db,
        company_id=company_id,
        user_id=user.id,
        description=f"Purchase Receipt PO-{order.id}",
        items=po_items,
        reference=f"PO-{order.id}",
    )

    payment = None
    if payload.payment_mode == "cash":
        link_safe_coa(db, safe, company_id)
        if not safe.chart_account_id:
            db.rollback()
            raise HTTPException(409, "Safe accounting account could not be initialized")
        payment = models.Payment(
            supplier_id=supplier.id,
            safe_id=safe.id,
            amount=total,
            method="cash",
            reference=f"PO-{order.id}",
            paid_on=datetime.now(exports.LOCAL_TZ).date(),
            created_by=user.id,
        )
        db.add(payment)
        db.flush()
        AccountingEngine.create_entry(
            db=db,
            company_id=company_id,
            user_id=user.id,
            description=f"Cash purchase payment PO-{order.id}",
            items=[
                {"account_id": supplier.chart_account_id, "debit": total, "credit": 0},
                {"account_id": safe.chart_account_id, "debit": 0, "credit": total},
            ],
            reference=f"PO-{order.id}",
        )
        safe.balance = (safe.balance or 0) - total

    audit(db, user, "create", "purchase_order", order, f"{'نقدي' if payment else 'آجل'} · استلام فوري · الإجمالي {total}")
    if payment:
        audit(db, user, "create", "payment", payment, f"دفع نقدي للمورد {supplier.name} · {total}")
    db.commit()
    db.refresh(order)
    attach_settlement(db, "supplier", order)
    return order


@purchases.get("", response_model=List[schemas.PurchaseOrderOut])
def list_purchase_orders(
    response: Response,
    status_filter: Optional[str] = None,
    supplier_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(models.PurchaseOrder)
    if status_filter:
        query = query.filter(models.PurchaseOrder.status == status_filter)
    if supplier_id is not None:
        query = query.filter(models.PurchaseOrder.supplier_id == supplier_id)
    rows = paginate(query, response, skip, limit, models.PurchaseOrder.id.desc())
    attach_settlement(db, "supplier", rows)
    return rows


@purchases.get("/{order_id}", response_model=schemas.PurchaseOrderOut)
def get_purchase_order(order_id: int, db: Session = Depends(get_db)):
    order = _order_or_404(db, models.PurchaseOrder, order_id, "Purchase order")
    attach_settlement(db, "supplier", order)
    return order


@purchases.post("/{order_id}/receive", response_model=schemas.PurchaseOrderOut)
def receive_purchase_order(order_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Mark goods as received: adds stock, updates each product's cost price, logs movements."""
    order = _locked_order_or_404(db, models.PurchaseOrder, order_id, "Purchase order")
    _require_draft(order, "receive")
    # فحص سقف المديونية للمورد قبل استلام المشتريات وتوليد التزام الدفع
    from ..accounts import check_supplier_credit_limit
    check_supplier_credit_limit(db, order.supplier_id, Decimal(str(order.total_amount)), perms=getattr(request.state, "permissions", None))
    for item in order.items:
        product = _locked_product(db, item.product_id)
        stock.move_stock(db, product, order.warehouse_id, item.quantity, "purchase_receipt", f"PO-{order.id}")  # type: ignore
        product.cost_price = item.unit_cost
        # لوط تلقائي لكل استلام شراء — أساس التتبع العكسي (كود اللوط = رقم أمر الشراء)
        lot = (
            db.query(models.StockLot)
            .filter(
                models.StockLot.company_id == db.info["company_id"],
                models.StockLot.product_id == item.product_id,
                models.StockLot.warehouse_id == order.warehouse_id,
                models.StockLot.lot_code == f"PO-{order.id}",
            )
            .first()
        )
        if lot is None:
            db.add(models.StockLot(
                company_id=db.info["company_id"],  # type: ignore
                product_id=item.product_id,  # type: ignore
                warehouse_id=order.warehouse_id,  # type: ignore
                lot_code=f"PO-{order.id}",  # type: ignore
                source="purchase",  # type: ignore
                reference=f"PO-{order.id}",  # type: ignore
                qty_received=item.quantity,  # type: ignore
                qty_remaining=item.quantity,  # type: ignore
            ))
        else:
            lot.qty_received = Decimal(str(lot.qty_received)) + item.quantity  # type: ignore
            lot.qty_remaining = Decimal(str(lot.qty_remaining)) + item.quantity  # type: ignore
    order.status = "received"  # type: ignore

    # Accounting: Debit Inventory, Credit Supplier
    from ..accounting import seed_default_coa, link_party_coa
    seed_default_coa(db, db.info["company_id"])
    supplier = db.get(models.Supplier, order.supplier_id)
    if supplier is not None:
        link_party_coa(db, supplier, db.info["company_id"], is_customer=False)
    inventory_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == "1101").first()
    if not inventory_acc or not supplier or not supplier.chart_account_id:
        db.rollback()
        raise HTTPException(409, "Purchase accounting accounts could not be initialized")
    AccountingEngine.create_entry(
        db=db,
        company_id=db.info["company_id"],
        user_id=user.id,
        description=f"Purchase Receipt PO-{order.id}",
        items=[
            {"account_id": inventory_acc.id, "debit": order.total_amount, "credit": 0},
            {"account_id": supplier.chart_account_id, "debit": 0, "credit": order.total_amount},
        ],
        reference=f"PO-{order.id}"
    )

    audit(db, user, 'receive', 'purchase_order', order, f"إجمالي {order.total_amount}")
    db.commit()
    db.refresh(order)
    return order


@purchases.post("/{order_id}/cancel", response_model=schemas.PurchaseOrderOut)
def cancel_purchase_order(order_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    order = _locked_order_or_404(db, models.PurchaseOrder, order_id, "Purchase order")
    _require_draft(order, "cancel")
    order.status = "cancelled"  # type: ignore
    audit(db, user, 'cancel', 'purchase_order', order, None)
    db.commit()
    db.refresh(order)
    return order


# ======================= Sales =======================
def apply_sale_stock(db: Session, order) -> None:
    """Locks the products, verifies stock for the whole order and deducts it (all-or-nothing).
    Does not commit. On a shortage the session is rolled back and a 409 is raised."""
    # Aggregate per product so duplicate lines are validated together.
    needed: dict = {}
    for item in order.items:
        needed[item.product_id] = needed.get(item.product_id, 0) + item.quantity

    products = {pid: _locked_product(db, pid) for pid in sorted(needed)}
    shortages = [
        stock.shortage_message(db, p, order.warehouse_id, needed[pid])
        for pid, p in products.items()
        if stock.available(db, pid, order.warehouse_id) < needed[pid]
    ]
    if shortages:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + "; ".join(shortages))

    # بوابة فحص الجودة (QC_GATE): تمنع صرف دفعات إنتاج بانتظار الفحص —
    # قبل أي خصم حتى يفشل الطلب كله ذريًا إن وُجدت دفعة معلقة
    for pid, qty in needed.items():
        company_id = getattr(db, "info", {}).get("company_id") or getattr(products[pid], "company_id", None)
        stock.assert_no_pending_qc_lots(db, company_id, products[pid], order.warehouse_id, qty)

    for pid, qty in needed.items():
        stock.move_stock(db, products[pid], order.warehouse_id, -qty, "sale", f"SO-{order.id}")
        stock.consume_lots(db, products[pid], order.warehouse_id, qty)  # FEFO: أقرب انتهاءً أولًا


@sales.post("", response_model=schemas.SalesOrderOut, status_code=status.HTTP_201_CREATED)
def create_sales_order(payload: schemas.SalesOrderCreate, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    customer = _require(db, models.Customer, payload.customer_id, "Customer")
    _require(db, models.Warehouse, payload.warehouse_id, "Warehouse")
    # خريطة أسعار قائمة العميل (مرة واحدة للأمر كله)
    from ..pricing import list_price_map
    list_prices = list_price_map(db, getattr(customer, "price_list_id", None) or 0)
    # صلاحية تعديل سعر البيع: بدونها يُباع بسعر البيع المعتمد فقط، ومعها الزيادة فقط.
    perms = getattr(request.state, "permissions", None)
    price_edit_locked = perms is not None and "*" not in perms
    doc_type = getattr(payload, "document_type", "order") or "order"
    order = models.SalesOrder(
        status="quotation" if doc_type == "quotation" else "draft",
        customer_id=payload.customer_id, warehouse_id=payload.warehouse_id, notes=payload.notes, created_by=user.id,  # type: ignore
        rep_id=payload.rep_id if payload.rep_id and db.get(models.SalesRep, payload.rep_id) else None,
    )
    if payload.safe_id:
        safe = db.get(models.Safe, payload.safe_id)
        company_id = db.info["company_id"]
        if safe is not None and safe.company_id == company_id and safe.is_active:
            order.safe_id = safe.id  # type: ignore
    total = Decimal("0")
    for item in payload.items:
        product = _require(db, models.Product, item.product_id, "Product")
        # السعر المعتمد: قائمة العميل إن ورد الصنف فيها — وإلا سعر البيع العام
        base_price = list_prices.get(product.id) or product.sale_price
        if price_edit_locked and item.unit_price is not None and base_price is not None:
            if item.unit_price > base_price:
                if not user_has_permission(perms, "sales.order.price_increase"):
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "لا تملك صلاحية تعديل سعر البيع (الزيادة فقط)")
            elif item.unit_price < base_price:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "تعديل سعر البيع مسموح بالزيادة فقط")
        price = item.unit_price if item.unit_price is not None else base_price
        order.items.append(
            models.SalesOrderItem(
                product_id=product.id, quantity=item.quantity, unit_price=price, unit_cost=product.cost_price  # type: ignore
            )
        )
        total += price * Decimal(str(item.quantity))
    # خصم على مستوى الأوردر (يُخصم قبل الضريبة) — يُوثق عموداً لشفافية ETA والتقارير
    discount_amount = Decimal("0")
    if getattr(payload, "discount_value", None):
        dv = Decimal(str(payload.discount_value))
        if payload.discount_mode == "percent":
            if dv < 0 or dv > 100:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نسبة الخصم يجب أن تكون بين 0 و 100")
            discount_amount = (total * dv / Decimal("100")).quantize(Decimal("0.01"))
        else:
            discount_amount = dv.quantize(Decimal("0.01"))
        if discount_amount < 0 or discount_amount > total:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الخصم لا يمكن أن يتجاوز الإجمالي")

    # ضريبة القيمة المضافة على البيع: total_amount = الصافي بعد الخصم + الضريبة
    subtotal = total.quantize(Decimal("0.01"))
    taxable = (subtotal - discount_amount).quantize(Decimal("0.01"))
    tax_rate = Decimal(str(payload.tax_rate or 0))
    tax_amount = (taxable * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    order.subtotal = taxable  # type: ignore
    order.discount_amount = discount_amount  # type: ignore
    order.tax_rate = tax_rate  # type: ignore
    order.tax_amount = tax_amount  # type: ignore
    order.total_amount = taxable + tax_amount  # type: ignore
    # عملة الفاتورة (اختياري): تُثبّت على المستند — الدفاتر تبقى بالجنيه
    from ..pricing import resolve_currency
    currency, rate = resolve_currency(db, getattr(payload, "currency_id", None))
    if currency is not None:
        order.currency_id = currency.id  # type: ignore
        order.exchange_rate = rate  # type: ignore
        order.foreign_total = (Decimal(str(order.total_amount)) / rate).quantize(Decimal("0.01"))  # type: ignore
    db.add(order)
    audit(db, user, 'create', 'sales_order', order, f"{len(order.items)} بند · {order.total_amount}")
    db.commit()
    db.refresh(order)
    return order


@sales.get("", response_model=List[schemas.SalesOrderOut])
def list_sales_orders(
    response: Response,
    status_filter: Optional[str] = None,
    customer_id: Optional[int] = None,
    cashier: Optional[str] = None,
    rep_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(models.SalesOrder)
    if cashier:  # username of whoever created the order
        query = query.join(models.User, models.User.id == models.SalesOrder.created_by).filter(
            func.lower(models.User.username) == cashier.strip().lower()
        )
    if status_filter:
        query = query.filter(models.SalesOrder.status == status_filter)
    if customer_id is not None:
        query = query.filter(models.SalesOrder.customer_id == customer_id)
    if rep_id is not None:  # invoices handled by a sales rep
        query = query.filter(models.SalesOrder.rep_id == rep_id)
    rows = paginate(query, response, skip, limit, models.SalesOrder.id.desc())
    attach_settlement(db, "customer", rows)
    return rows


@sales.get("/{order_id}", response_model=schemas.SalesOrderOut)
def get_sales_order(order_id: int, db: Session = Depends(get_db)):
    order = _order_or_404(db, models.SalesOrder, order_id, "Sales order")
    attach_settlement(db, "customer", order)
    return order


@sales.post("/{order_id}/confirm", response_model=schemas.SalesOrderOut)
def confirm_sales_order(order_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Confirm the sale: removes stock (all-or-nothing) and logs movements."""
    order = _locked_order_or_404(db, models.SalesOrder, order_id, "Sales order")
    _require_draft(order, "confirm")
    # الحد الائتماني: الدين الجديد كامل الفاتورة (المديونية تُسجّل هنا)
    from ..accounts import check_credit_limit
    check_credit_limit(db, order.customer_id, Decimal(str(order.total_amount)), perms=getattr(request.state, "permissions", None))
    apply_sale_stock(db, order)
    order.status = "confirmed"  # type: ignore

    # Accounting: Debit Customer (gross), Credit Sales Revenue (net), Credit VAT output (tax)
    from ..accounting import VAT_OUTPUT_CODE, seed_default_coa, link_party_coa
    seed_default_coa(db, db.info["company_id"])
    customer = db.get(models.Customer, order.customer_id)
    if customer is not None:
        link_party_coa(db, customer, db.info["company_id"], is_customer=True)
    revenue_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == "4101").first()
    if not revenue_acc or not customer or not customer.chart_account_id:
        db.rollback()
        raise HTTPException(409, "Sales accounting accounts could not be initialized")
    sale_items = [
        {"account_id": customer.chart_account_id, "debit": order.total_amount, "credit": 0},
        {"account_id": revenue_acc.id, "debit": 0, "credit": order.subtotal if order.subtotal is not None else order.total_amount},
    ]
    if (order.tax_amount or Decimal("0")) > 0:
        vat_acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == VAT_OUTPUT_CODE
        ).first()
        if vat_acc is None or vat_acc.is_group:
            db.rollback()
            raise HTTPException(409, "حساب ضريبة القيمة المضافة (2130) غير موجود — حدّث شجرة الحسابات")
        sale_items.append({"account_id": vat_acc.id, "debit": 0, "credit": order.tax_amount})
    AccountingEngine.create_entry(
        db=db,
        company_id=db.info["company_id"],
        user_id=user.id,
        description=f"Sales Confirmation SO-{order.id}",
        items=sale_items,
        reference=f"SO-{order.id}"
    )

    # Accounting: Debit COGS, Credit Inventory — relieve stock value at the cost frozen on the order lines.
    cogs_total = sum(((it.unit_cost or Decimal("0")) * it.quantity for it in order.items), Decimal("0"))
    if cogs_total > 0:
        inventory_acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == "1101"
        ).first()
        cogs_acc = db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == "5100"
        ).first()
        if not inventory_acc or not cogs_acc:
            db.rollback()
            raise HTTPException(409, "COGS accounting accounts could not be initialized")
        AccountingEngine.create_entry(
            db=db,
            company_id=db.info["company_id"],
            user_id=user.id,
            description=f"COGS SO-{order.id}",
            items=[
                {"account_id": cogs_acc.id, "debit": cogs_total, "credit": 0},
                {"account_id": inventory_acc.id, "debit": 0, "credit": cogs_total},
            ],
            reference=f"SO-{order.id}"
        )

    audit(db, user, 'confirm', 'sales_order', order, f"إجمالي {order.total_amount}")
    db.commit()
    db.refresh(order)
    # تنبيه تطبيق المندوب: فاتورته اتأكدت (صندوق + Push إن ضُبط FCM)
    if order.rep_id:
        from ..push import notify_rep
        try:
            notify_rep(db, order.rep_id, kind="order_confirmed",
                       title=f"تم تأكيد فاتورتك SO-{order.id}",
                       body=f"الإجمالي {order.total_amount} ج.م — العميل {order.party_name or ''}",
                       ref_id=order.id)
        except Exception:
            pass  # الإشعار لا يعطل التأكيد أبدًا
    return order


@sales.post("/{order_id}/convert", response_model=schemas.SalesOrderOut)
def convert_quotation_to_order(order_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """تحويل عرض سعر إلى أوردر فعلي: status quotation → draft — ثم يُؤكد كأي أوردر."""
    order = _order_or_404(db, models.SalesOrder, order_id, "Sales order")
    if order.status != "quotation":  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only quotations can be converted (current: {order.status})")
    order.status = "draft"  # type: ignore[assignment]
    audit(db, user, "convert", "sales_order", order, f"تحويل عرض السعر SO-{order.id} إلى أوردر")
    db.commit()
    db.refresh(order)
    return order


class DeliveryLineIn(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)


class DeliveryIn(BaseModel):
    items: List[DeliveryLineIn] = Field(min_length=1)
    notes: Optional[str] = None


@sales.post("/{order_id}/deliveries", response_model=schemas.SalesOrderOut, status_code=status.HTTP_201_CREATED)
def create_delivery(
    order_id: int,
    payload: DeliveryIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تسليم جزئي: يخصم الكمية المسلَّمة من المخزن (بأقفال ومنع النقص) ويزيد delivered_quantity.

    المحاسبة بقيت كاملة عند التأكيد (الإيراد والـ COGS) — التسليم لوجستي فقط.
    عند اكتمال كل البنود تُعلَّم الفاتورة «مُسلَّمة كاملة» في الملاحظات."""
    order = _locked_order_or_404(db, models.SalesOrder, order_id, "Sales order")
    if order.status != "confirmed":  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "التسليم يتطلب فاتورة مؤكدة")
    items_by_pid: dict = {}
    for it in order.items:
        items_by_pid[it.product_id] = it
    wanted: dict = {}
    for ln in payload.items:
        wanted[ln.product_id] = wanted.get(ln.product_id, 0) + Decimal(str(ln.quantity))
    for pid, qty in wanted.items():
        item = items_by_pid.get(pid)
        if item is None:
            raise HTTPException(422, f"الصنف {pid} ليس في الفاتورة")
        remaining = Decimal(str(item.quantity)) - Decimal(str(item.delivered_quantity or 0))
        if qty > remaining:
            raise HTTPException(409, f"الصنف {pid}: المتبقي للتسليم {remaining} فقط")
    # حركة المخزون all-or-nothing (أقفال + منع النقص) ثم خصم لوطات FEFO
    for pid, qty in wanted.items():
        product = _locked_product(db, pid)
        if stock.available(db, pid, order.warehouse_id) < qty:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + stock.shortage_message(db, product, order.warehouse_id, qty))
        stock.move_stock(db, product, order.warehouse_id, -qty, "delivery", f"DLV-SO-{order.id}")
        stock.consume_lots(db, product, order.warehouse_id, qty)
    delivered_note_lines = []
    for it in order.items:
        if it.product_id in wanted:
            it.delivered_quantity = Decimal(str(it.delivered_quantity or 0)) + wanted[it.product_id]  # type: ignore
        delivered_note_lines.append(f"{it.product_id}:{it.delivered_quantity or 0}/{it.quantity}")
    fully = all(
        Decimal(str(it.delivered_quantity or 0)) >= Decimal(str(it.quantity))
        for it in order.items
    )
    if fully and "مُسلَّمة كاملة" not in (order.notes or ""):
        order.notes = ((order.notes or "") + " · مُسلَّمة كاملة").strip(" ·")  # type: ignore
    audit(db, user, "deliver", "sales_order", order,
          f"تسليم جزئي: " + "، ".join(f"{p}×{q}" for p, q in wanted.items()) + (" — اكتمل" if fully else ""))
    db.commit()
    db.refresh(order)
    return order


@sales.get("/{order_id}/deliveries")
def list_deliveries(
    order_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """سجل حركات تسليم هذه الفاتورة (من سجل حركة المخزون بمرجع DLV-SO-{id})."""
    moves = (
        db.query(models.StockMovement, models.Product.sku, models.Product.name, models.Warehouse.name)
        .join(models.Product, models.Product.id == models.StockMovement.product_id)
        .outerjoin(models.Warehouse, models.Warehouse.id == models.StockMovement.warehouse_id)
        .filter(
            models.StockMovement.company_id == db.info["company_id"],
            models.StockMovement.reference == f"DLV-SO-{order_id}",
        )
        .order_by(models.StockMovement.id.desc())
        .all()
    )
    return [
        {
            "id": m.id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "product_id": m.product_id, "sku": sku, "product_name": name,
            "warehouse_name": wname, "change": float(m.change),
        }
        for m, sku, name, wname in moves
    ]


@sales.post("/{order_id}/cancel", response_model=schemas.SalesOrderOut)
def cancel_sales_order(order_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    order = _locked_order_or_404(db, models.SalesOrder, order_id, "Sales order")
    _require_draft(order, "cancel")
    order.status = "cancelled"  # type: ignore
    audit(db, user, 'cancel', 'sales_order', order, None)
    db.commit()
    db.refresh(order)
    return order


# ======================= Document export (PDF / Excel) =======================
def _document(kind: str, order) -> dict:
    """Plain-dict snapshot of an order for the PDF/Excel builders."""
    if kind == "sales":
        party, number, price_label = order.customer, f"SO-{order.id}", "سعر الوحدة"
        party_label, price_attr = "العميل", "unit_price"
    else:
        party, number, price_label = order.supplier, f"PO-{order.id}", "تكلفة الوحدة"
        party_label, price_attr = "المورد", "unit_cost"
    items = []
    for it in order.items:
        price = getattr(it, price_attr)
        items.append(
            {
                "name": it.product.name,
                "sku": it.product.sku,
                "unit": it.product.unit,
                "quantity": it.quantity,
                "price": price,
                "total": price * it.quantity,
            }
        )
    return {
        "kind": kind,
        "number": number,
        "date": order.created_at,
        "status": order.status,
        "party_label": party_label,
        "party": {"name": party.name, "phone": party.phone, "email": party.email, "address": party.address},
        "warehouse": order.warehouse.name if order.warehouse else None,
        "price_label": price_label,
        "items": items,
        "total": order.total_amount,
        "notes": order.notes,
    }


def _download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


def _export(kind: str, fmt: str, order, stem: str) -> Response:
    doc = _document(kind, order)
    if fmt == "pdf":
        return _download(exports.build_document_pdf(doc), exports.PDF_MIME, f"{stem}-{doc['number']}.pdf")
    return _download(exports.build_document_xlsx(doc), exports.XLSX_MIME, f"{stem}-{doc['number']}.xlsx")


@purchases.get("/{order_id}/pdf")
def purchase_order_pdf(order_id: int, db: Session = Depends(get_db)):
    return _export("purchase", "pdf", _order_or_404(db, models.PurchaseOrder, order_id, "Purchase order"), "purchase-order")


@purchases.get("/{order_id}/xlsx")
def purchase_order_xlsx(order_id: int, db: Session = Depends(get_db)):
    return _export("purchase", "xlsx", _order_or_404(db, models.PurchaseOrder, order_id, "Purchase order"), "purchase-order")


@sales.get("/{order_id}/pdf")
def sales_order_invoice_pdf(order_id: int, db: Session = Depends(get_db)):
    order = _order_or_404(db, models.SalesOrder, order_id, "Sales order")
    doc = _document("sales", order)
    # حقول المنظومة على المطبوع (متطلب ETA): UUID + Long ID + QR
    valid_sub = (
        db.query(models.EtaSubmission)
        .filter(
            models.EtaSubmission.company_id == db.info["company_id"],
            models.EtaSubmission.order_id == order.id,
            models.EtaSubmission.document_type == "I",
            models.EtaSubmission.status == "valid",
        )
        .order_by(models.EtaSubmission.id.desc())
        .first()
    )
    if valid_sub is not None:
        doc["eta_uuid"] = valid_sub.eta_uuid
        doc["eta_long_id"] = valid_sub.eta_long_id
    # العملة الأجنبية على المطبوع (إن وجدت)
    if order.currency_id is not None:
        doc["currency_code"] = order.currency_code
        doc["exchange_rate"] = order.exchange_rate
        doc["foreign_total"] = order.foreign_total
    content = exports.build_document_pdf(doc)
    return _download(content, exports.PDF_MIME, f"invoice-SO-{order.id}.pdf")


@sales.get("/{order_id}/quotation.pdf")
def sales_order_quotation_pdf(order_id: int, db: Session = Depends(get_db)):
    order = _order_or_404(db, models.SalesOrder, order_id, "Sales order")
    doc = _document("sales", order)
    doc["kind"] = "quotation"
    return _download(exports.build_document_pdf(doc), exports.PDF_MIME, f"quotation-SO-{order.id}.pdf")


@sales.get("/{order_id}/receipt")
def sales_order_receipt(order_id: int, db: Session = Depends(get_db)):
    """80 mm thermal-printer receipt for a sale."""
    order = _order_or_404(db, models.SalesOrder, order_id, "Sales order")
    attach_settlement(db, "customer", order)
    doc = _document("sales", order)
    doc["paid"], doc["remaining"] = order.paid_amount, order.balance_due
    doc["cashier"] = order.created_by_name
    return _download(exports.build_receipt_pdf(doc), exports.PDF_MIME, f"receipt-{doc['number']}.pdf")


@sales.get("/{order_id}/xlsx")
def sales_order_invoice_xlsx(order_id: int, db: Session = Depends(get_db)):
    return _export("sales", "xlsx", _order_or_404(db, models.SalesOrder, order_id, "Sales order"), "invoice")


@sales.get("/{order_id}/eta-json")
def sales_order_eta_json(order_id: int, db: Session = Depends(get_db)):
    """تصدير الفاتورة بصيغة منظومة الضرائب المصرية (ETA e-invoice JSON, documentType=I).

    مسودة جاهزة للرفع على بيئة ETA التجريبية — الربط الحي يحتاج تسجيل الشركة
    (client_id/secret + تسجيل الأجهزة)، وهذه البنية تختصر الطريق إليه."""
    import json as _json
    from ..accounting import local_today

    order = _order_or_404(db, models.SalesOrder, order_id, "Sales order")
    if order.status != "confirmed":  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "الفاتورة الإلكترونية تتطلب أمر بيع مؤكدًا")
    company = db.get(models.Company, db.info["company_id"])
    customer = db.get(models.Customer, order.customer_id)
    product_rows = {
        p.id: p for p in db.query(models.Product).filter(
            models.Product.id.in_([it.product_id for it in order.items])
        ).all()
    } if order.items else {}
    lines = []
    for i, it in enumerate(order.items, 1):
        unit_price = Decimal(str(it.unit_price or 0))
        qty = Decimal(str(it.quantity))
        product = product_rows.get(it.product_id)
        lines.append({
            "description": it.product_name or (product.name if product else f"صنف #{it.product_id}"),
            "itemType": "GS1",
            "unitType": "EA",
            "quantity": float(qty),
            "internalCode": (product.sku if product else None) or str(it.product_id),
            "salesTotal": float((unit_price * qty).quantize(Decimal("0.01"))),
            "total": float((unit_price * qty).quantize(Decimal("0.01"))),
            "valueDifference": 0,
            "unitValue": {"currencySold": "EGP", "amountEGP": float(unit_price)},
        })
    doc = {
        "documentType": "I",
        "documentTypeVersion": "1.0",
        "dateTimeIssued": datetime.now(exports.LOCAL_TZ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "taxpayerActivityCode": "4690",
        "internalID": f"SO-{order.id}",
        "issuer": {
            "type": "B", "id": "", "name": company.name if company else "",
            "address": {
                "country": "EG", "governate": "", "regionCity": "", "street": "",
                "buildingNumber": "0", "postalCode": "", "floor": "", "room": "", "landmark": "",
            },
        },
        "receiver": {
            "type": "P", "id": "", "name": order.party_name or (customer.name if customer else ""),
            "address": {"country": "EG", "governate": "", "regionCity": "", "street": "", "buildingNumber": "0"},
        },
        "invoiceLines": lines,
        "totalDiscountAmount": 0,
        "totalSalesAmount": float(order.subtotal if order.subtotal is not None else order.total_amount),
        "netAmount": float(order.subtotal if order.subtotal is not None else order.total_amount),
        "taxTotals": [{"taxType": "T1", "amount": float(order.tax_amount or 0)}],
        "totalAmount": float(order.total_amount),
        "extraDiscountAmount": 0,
        "totalItemsDiscountAmount": 0,
    }
    return _download(_json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8"),
                     "application/json", f"eta-SO-{order.id}.json")
