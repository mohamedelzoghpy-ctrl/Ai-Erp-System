"""Purchase orders (stock in) and sales orders (stock out).

Lifecycle
  purchases: draft -> received            (received adds stock)      | draft -> cancelled
  sales:     draft -> confirmed           (confirmed removes stock)  | draft -> cancelled
Stock is only touched on the transition, inside one transaction, with row locks.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..accounts import attach_settlement
from ..audit import audit
from ..deps import get_current_user
from ..pagination import paginate
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
        total += item.unit_cost * item.quantity
    discount = total * payload.discount_value / Decimal("100") if payload.discount_mode == "percent" else payload.discount_value
    if discount > total:
        raise HTTPException(422, "Purchase discount cannot exceed the subtotal")
    taxable = total - discount
    tax = (taxable * payload.tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    total = taxable + tax
    order.total_amount = total  # type: ignore
    if payload.discount_value or payload.tax_rate:
        discount_note = f"الخصم: {discount:.2f}" + (f" ({payload.discount_value}%)" if payload.discount_mode == "percent" else "")
        tax_note = f"ضريبة القيمة المضافة {payload.tax_rate}%: {tax:.2f}"
        order.notes = " · ".join(x for x in (payload.notes, discount_note, tax_note) if x)  # type: ignore
    db.add(order)
    db.flush()

    # Receipt is immediate; stock, cost, payable, and cash settlement commit atomically.
    for item in order.items:
        product = products[item.product_id]
        stock.move_stock(db, product, order.warehouse_id, item.quantity, "purchase_receipt", f"PO-{order.id}")  # type: ignore
        product.cost_price = item.unit_cost
    order.status = "received"  # type: ignore

    from ..accounting import link_party_coa, link_safe_coa, seed_default_coa
    company_id = db.info["company_id"]
    seed_default_coa(db, company_id)
    link_party_coa(db, supplier, company_id, is_customer=False)
    inventory_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1101").first()
    if not inventory_acc or not supplier.chart_account_id:
        db.rollback()
        raise HTTPException(409, "Purchase accounting accounts could not be initialized")
    AccountingEngine.create_entry(
        db=db,
        company_id=company_id,
        user_id=user.id,
        description=f"Purchase Receipt PO-{order.id}",
        items=[
            {"account_id": inventory_acc.id, "debit": total, "credit": 0},
            {"account_id": supplier.chart_account_id, "debit": 0, "credit": total},
        ],
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
def receive_purchase_order(order_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Mark goods as received: adds stock, updates each product's cost price, logs movements."""
    order = _locked_order_or_404(db, models.PurchaseOrder, order_id, "Purchase order")
    _require_draft(order, "receive")
    for item in order.items:
        product = _locked_product(db, item.product_id)
        stock.move_stock(db, product, order.warehouse_id, item.quantity, "purchase_receipt", f"PO-{order.id}")  # type: ignore
        product.cost_price = item.unit_cost
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

    for pid, qty in needed.items():
        stock.move_stock(db, products[pid], order.warehouse_id, -qty, "sale", f"SO-{order.id}")


@sales.post("", response_model=schemas.SalesOrderOut, status_code=status.HTTP_201_CREATED)
def create_sales_order(payload: schemas.SalesOrderCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _require(db, models.Customer, payload.customer_id, "Customer")
    _require(db, models.Warehouse, payload.warehouse_id, "Warehouse")
    order = models.SalesOrder(
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
        price = item.unit_price if item.unit_price is not None else product.sale_price
        order.items.append(
            models.SalesOrderItem(
                product_id=product.id, quantity=item.quantity, unit_price=price, unit_cost=product.cost_price  # type: ignore
            )
        )
        total += price * item.quantity
    order.total_amount = total  # type: ignore
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
def confirm_sales_order(order_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Confirm the sale: removes stock (all-or-nothing) and logs movements."""
    order = _locked_order_or_404(db, models.SalesOrder, order_id, "Sales order")
    _require_draft(order, "confirm")
    apply_sale_stock(db, order)
    order.status = "confirmed"  # type: ignore

    # Accounting: Debit Customer, Credit Sales Revenue
    from ..accounting import seed_default_coa, link_party_coa
    seed_default_coa(db, db.info["company_id"])
    customer = db.get(models.Customer, order.customer_id)
    if customer is not None:
        link_party_coa(db, customer, db.info["company_id"], is_customer=True)
    revenue_acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == "4101").first()
    if not revenue_acc or not customer or not customer.chart_account_id:
        db.rollback()
        raise HTTPException(409, "Sales accounting accounts could not be initialized")
    AccountingEngine.create_entry(
        db=db,
        company_id=db.info["company_id"],
        user_id=user.id,
        description=f"Sales Confirmation SO-{order.id}",
        items=[
            {"account_id": customer.chart_account_id, "debit": order.total_amount, "credit": 0},
            {"account_id": revenue_acc.id, "debit": 0, "credit": order.total_amount},
        ],
        reference=f"SO-{order.id}"
    )

    audit(db, user, 'confirm', 'sales_order', order, f"إجمالي {order.total_amount}")
    db.commit()
    db.refresh(order)
    return order


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
    return _export("sales", "pdf", _order_or_404(db, models.SalesOrder, order_id, "Sales order"), "invoice")


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
