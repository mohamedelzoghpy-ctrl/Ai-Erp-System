"""Purchase orders (stock in) and sales orders (stock out).

Lifecycle
  purchases: draft -> received            (received adds stock)      | draft -> cancelled
  sales:     draft -> confirmed           (confirmed removes stock)  | draft -> cancelled
Stock is only touched on the transition, inside one transaction, with row locks.
"""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..accounts import attach_settlement
from ..audit import audit
from ..deps import get_current_user
from ..pagination import paginate
from .. import exports, models, schemas
from ..database import get_db

purchases = APIRouter(prefix="/purchase-orders", tags=["purchases"])
sales = APIRouter(prefix="/sales-orders", tags=["sales"])


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
    _require(db, models.Supplier, payload.supplier_id, "Supplier")
    _require(db, models.Warehouse, payload.warehouse_id, "Warehouse")
    order = models.PurchaseOrder(
        supplier_id=payload.supplier_id, warehouse_id=payload.warehouse_id, notes=payload.notes
    )
    total = Decimal("0")
    for item in payload.items:
        _require(db, models.Product, item.product_id, "Product")
        order.items.append(
            models.PurchaseOrderItem(
                product_id=item.product_id, quantity=item.quantity, unit_cost=item.unit_cost
            )
        )
        total += item.unit_cost * item.quantity
    order.total_amount = total
    db.add(order)
    audit(db, user, 'create', 'purchase_order', order, f"{len(order.items)} بند · {order.total_amount}")
    db.commit()
    db.refresh(order)
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
    order = _order_or_404(db, models.PurchaseOrder, order_id, "Purchase order")
    _require_draft(order, "receive")
    for item in order.items:
        product = _locked_product(db, item.product_id)
        product.quantity += item.quantity
        product.cost_price = item.unit_cost
        db.add(
            models.StockMovement(
                product_id=product.id,
                warehouse_id=order.warehouse_id,
                change=item.quantity,
                reason="purchase_receipt",
                reference=f"PO-{order.id}",
            )
        )
    order.status = "received"
    audit(db, user, 'receive', 'purchase_order', order, f"إجمالي {order.total_amount}")
    db.commit()
    db.refresh(order)
    return order


@purchases.post("/{order_id}/cancel", response_model=schemas.PurchaseOrderOut)
def cancel_purchase_order(order_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    order = _order_or_404(db, models.PurchaseOrder, order_id, "Purchase order")
    _require_draft(order, "cancel")
    order.status = "cancelled"
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
        f"product {pid} ('{p.name}'): need {needed[pid]}, have {p.quantity}"
        for pid, p in products.items()
        if p.quantity < needed[pid]
    ]
    if shortages:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + "; ".join(shortages))

    for pid, qty in needed.items():
        products[pid].quantity -= qty
        db.add(
            models.StockMovement(
                product_id=pid,
                warehouse_id=order.warehouse_id,
                change=-qty,
                reason="sale",
                reference=f"SO-{order.id}",
            )
        )


@sales.post("", response_model=schemas.SalesOrderOut, status_code=status.HTTP_201_CREATED)
def create_sales_order(payload: schemas.SalesOrderCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _require(db, models.Customer, payload.customer_id, "Customer")
    _require(db, models.Warehouse, payload.warehouse_id, "Warehouse")
    order = models.SalesOrder(
        customer_id=payload.customer_id, warehouse_id=payload.warehouse_id, notes=payload.notes, created_by=user.id
    )
    total = Decimal("0")
    for item in payload.items:
        product = _require(db, models.Product, item.product_id, "Product")
        price = item.unit_price if item.unit_price is not None else product.sale_price
        order.items.append(
            models.SalesOrderItem(product_id=product.id, quantity=item.quantity, unit_price=price)
        )
        total += price * item.quantity
    order.total_amount = total
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
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(models.SalesOrder)
    if status_filter:
        query = query.filter(models.SalesOrder.status == status_filter)
    if customer_id is not None:
        query = query.filter(models.SalesOrder.customer_id == customer_id)
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
    order = _order_or_404(db, models.SalesOrder, order_id, "Sales order")
    _require_draft(order, "confirm")
    apply_sale_stock(db, order)
    order.status = "confirmed"
    audit(db, user, 'confirm', 'sales_order', order, f"إجمالي {order.total_amount}")
    db.commit()
    db.refresh(order)
    return order


@sales.post("/{order_id}/cancel", response_model=schemas.SalesOrderOut)
def cancel_sales_order(order_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    order = _order_or_404(db, models.SalesOrder, order_id, "Sales order")
    _require_draft(order, "cancel")
    order.status = "cancelled"
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
