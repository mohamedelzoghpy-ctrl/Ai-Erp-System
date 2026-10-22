"""Purchase orders (stock in) and sales orders (stock out).

Lifecycle
  purchases: draft -> received            (received adds stock)      | draft -> cancelled
  sales:     draft -> confirmed           (confirmed removes stock)  | draft -> cancelled
Stock is only touched on the transition, inside one transaction, with row locks.
"""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
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
def create_purchase_order(payload: schemas.PurchaseOrderCreate, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(order)
    return order


@purchases.get("", response_model=List[schemas.PurchaseOrderOut])
def list_purchase_orders(
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
    return query.order_by(models.PurchaseOrder.id.desc()).offset(skip).limit(min(limit, 500)).all()


@purchases.get("/{order_id}", response_model=schemas.PurchaseOrderOut)
def get_purchase_order(order_id: int, db: Session = Depends(get_db)):
    return _order_or_404(db, models.PurchaseOrder, order_id, "Purchase order")


@purchases.post("/{order_id}/receive", response_model=schemas.PurchaseOrderOut)
def receive_purchase_order(order_id: int, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(order)
    return order


@purchases.post("/{order_id}/cancel", response_model=schemas.PurchaseOrderOut)
def cancel_purchase_order(order_id: int, db: Session = Depends(get_db)):
    order = _order_or_404(db, models.PurchaseOrder, order_id, "Purchase order")
    _require_draft(order, "cancel")
    order.status = "cancelled"
    db.commit()
    db.refresh(order)
    return order


# ======================= Sales =======================
@sales.post("", response_model=schemas.SalesOrderOut, status_code=status.HTTP_201_CREATED)
def create_sales_order(payload: schemas.SalesOrderCreate, db: Session = Depends(get_db)):
    _require(db, models.Customer, payload.customer_id, "Customer")
    _require(db, models.Warehouse, payload.warehouse_id, "Warehouse")
    order = models.SalesOrder(
        customer_id=payload.customer_id, warehouse_id=payload.warehouse_id, notes=payload.notes
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
    db.commit()
    db.refresh(order)
    return order


@sales.get("", response_model=List[schemas.SalesOrderOut])
def list_sales_orders(
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
    return query.order_by(models.SalesOrder.id.desc()).offset(skip).limit(min(limit, 500)).all()


@sales.get("/{order_id}", response_model=schemas.SalesOrderOut)
def get_sales_order(order_id: int, db: Session = Depends(get_db)):
    return _order_or_404(db, models.SalesOrder, order_id, "Sales order")


@sales.post("/{order_id}/confirm", response_model=schemas.SalesOrderOut)
def confirm_sales_order(order_id: int, db: Session = Depends(get_db)):
    """Confirm the sale: removes stock (all-or-nothing) and logs movements."""
    order = _order_or_404(db, models.SalesOrder, order_id, "Sales order")
    _require_draft(order, "confirm")

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
    order.status = "confirmed"
    db.commit()
    db.refresh(order)
    return order


@sales.post("/{order_id}/cancel", response_model=schemas.SalesOrderOut)
def cancel_sales_order(order_id: int, db: Session = Depends(get_db)):
    order = _order_or_404(db, models.SalesOrder, order_id, "Sales order")
    _require_draft(order, "cancel")
    order.status = "cancelled"
    db.commit()
    db.refresh(order)
    return order
