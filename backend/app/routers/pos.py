"""Point of sale: one request creates the sale, takes the stock and records the payment atomically."""

import os
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import exports, models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user
from .orders import _require, apply_sale_stock
from .shifts import open_shift_of

router = APIRouter(prefix="/pos", tags=["pos"])

WALK_IN_NAME = "عميل نقدي"
# Set POS_REQUIRE_SHIFT=true to force cashiers to open a drawer shift before selling.
REQUIRE_SHIFT = os.getenv("POS_REQUIRE_SHIFT", "false").lower() in ("1", "true", "yes")


def _walk_in(db: Session) -> models.Customer:
    c = db.query(models.Customer).filter(models.Customer.name == WALK_IN_NAME).order_by(models.Customer.id).first()
    if c is None:
        c = models.Customer(name=WALK_IN_NAME)  # type: ignore
        db.add(c)
        db.flush()
    return c


def _load_checkout_products(db: Session, items) -> dict[int, models.Product]:
    product_ids = list(dict.fromkeys(item.product_id for item in items))
    if not product_ids:
        return {}

    products = db.query(models.Product).filter(models.Product.id.in_(product_ids)).all()
    products_by_id = {product.id: product for product in products}
    missing_id = next((product_id for product_id in product_ids if product_id not in products_by_id), None)
    if missing_id is not None:
        raise HTTPException(422, f"Product {missing_id} does not exist")
    return products_by_id  # type: ignore


@router.post("/checkout", response_model=schemas.PosReceipt, status_code=status.HTTP_201_CREATED)
def checkout(payload: schemas.PosCheckout, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if REQUIRE_SHIFT and open_shift_of(db, user.id) is None:  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "Open a shift before selling")
    _require(db, models.Warehouse, payload.warehouse_id, "Warehouse")
    if payload.customer_id is not None:
        customer = _require(db, models.Customer, payload.customer_id, "Customer")
        if not customer.is_active:  # type: ignore
            raise HTTPException(422, "Customer is inactive")
    else:
        customer = _walk_in(db)

    products = _load_checkout_products(db, payload.items)
    order = models.SalesOrder(customer_id=customer.id, warehouse_id=payload.warehouse_id, notes=payload.notes, created_by=user.id)  # type: ignore
    total = Decimal("0")
    for item in payload.items:
        product = products[item.product_id]
        if not product.is_active:  # type: ignore
            raise HTTPException(422, f"Product '{product.name}' is inactive")
        price = item.unit_price if item.unit_price is not None else product.sale_price
        order.items.append(
            models.SalesOrderItem(product_id=product.id, quantity=item.quantity, unit_price=price, unit_cost=product.cost_price)  # type: ignore
        )
        total += price * item.quantity
    order.total_amount = total  # type: ignore

    paid = total if payload.amount_paid is None else payload.amount_paid
    if paid > total:  # type: ignore
        raise HTTPException(422, "amount_paid cannot exceed the total (give change at the till)")
    if payload.customer_id is None and paid != total:  # type: ignore
        raise HTTPException(422, "A walk-in customer must pay in full; choose a customer to sell on credit")

    db.add(order)
    db.flush()
    apply_sale_stock(db, order)  # rolls back and raises 409 on a shortage: nothing is saved
    order.status = "confirmed"  # type: ignore
    payment = None
    if paid > 0:  # type: ignore
        payment = models.Payment(
            customer_id=customer.id,  # type: ignore
            amount=paid,  # type: ignore
            method=payload.method,  # type: ignore
            reference=f"SO-{order.id}",  # type: ignore
            paid_on=datetime.now(exports.LOCAL_TZ).date(),  # type: ignore
            created_by=user.id,  # type: ignore
        )
        db.add(payment)
        db.flush()
    audit(db, user, "pos_sale", "sales_order", order, f"إجمالي {total} · مدفوع {paid} · {customer.name}")
    db.commit()
    return schemas.PosReceipt(
        order_id=order.id,  # type: ignore
        customer_id=customer.id,  # type: ignore
        customer_name=customer.name,  # type: ignore
        total=total,  # type: ignore
        paid=paid,  # type: ignore
        balance_due=total - paid,  # type: ignore
        payment_id=payment.id if payment else None,  # type: ignore
    )
