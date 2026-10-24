"""Point of sale: one request creates the sale, takes the stock and records the payment atomically."""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import exports, models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user
from .orders import _require, apply_sale_stock

router = APIRouter(prefix="/pos", tags=["pos"])

WALK_IN_NAME = "عميل نقدي"


def _walk_in(db: Session) -> models.Customer:
    c = db.query(models.Customer).filter(models.Customer.name == WALK_IN_NAME).order_by(models.Customer.id).first()
    if c is None:
        c = models.Customer(name=WALK_IN_NAME)
        db.add(c)
        db.flush()
    return c


@router.post("/checkout", response_model=schemas.PosReceipt, status_code=status.HTTP_201_CREATED)
def checkout(payload: schemas.PosCheckout, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    warehouse = _require(db, models.Warehouse, payload.warehouse_id, "Warehouse")
    if not warehouse.is_active:
        raise HTTPException(422, "Warehouse is inactive")
    if payload.customer_id is not None:
        customer = _require(db, models.Customer, payload.customer_id, "Customer")
        if not customer.is_active:
            raise HTTPException(422, "Customer is inactive")
    else:
        customer = _walk_in(db)

    order = models.SalesOrder(customer_id=customer.id, warehouse_id=payload.warehouse_id, notes=payload.notes)
    total = Decimal("0")
    for item in payload.items:
        product = _require(db, models.Product, item.product_id, "Product")
        if not product.is_active:
            raise HTTPException(422, f"Product '{product.name}' is inactive")
        if item.unit_price is not None and user.role not in {"admin", "manager"}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only managers and admins may override sale prices")
        price = item.unit_price if item.unit_price is not None else product.sale_price
        order.items.append(models.SalesOrderItem(product_id=product.id, quantity=item.quantity, unit_price=price))
        total += price * item.quantity
    order.total_amount = total

    paid = total if payload.amount_paid is None else payload.amount_paid
    if paid > total:
        raise HTTPException(422, "amount_paid cannot exceed the total (give change at the till)")
    if payload.customer_id is None and paid != total:
        raise HTTPException(422, "A walk-in customer must pay in full; choose a customer to sell on credit")

    db.add(order)
    db.flush()
    apply_sale_stock(db, order)  # rolls back and raises 409 on a shortage: nothing is saved
    order.status = "confirmed"
    payment = None
    if paid > 0:
        payment = models.Payment(
            customer_id=customer.id,
            amount=paid,
            method=payload.method,
            reference=f"SO-{order.id}",
            paid_on=datetime.now(exports.LOCAL_TZ).date(),
            created_by=user.id,
        )
        db.add(payment)
        db.flush()
    audit(db, user, "pos_sale", "sales_order", order, f"إجمالي {total} · مدفوع {paid} · {customer.name}")
    db.commit()
    return schemas.PosReceipt(
        order_id=order.id,
        customer_id=customer.id,
        customer_name=customer.name,
        total=total,
        paid=paid,
        balance_due=total - paid,
        payment_id=payment.id if payment else None,
    )
