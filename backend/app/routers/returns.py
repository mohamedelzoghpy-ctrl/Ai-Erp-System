"""Sales returns (customer sends goods back) and purchase returns (we send goods back to a supplier).

A return is final (no edit/void): it is tied to the original order lines, can never exceed what was sold/received
minus what was already returned, moves stock and changes the party's balance by (total - refund_amount).
"""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from .. import models, schemas
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


def _create(kind: str, payload: schemas.ReturnCreate, db: Session, user: models.User):
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
    ret = c["ret"](
        order_id=order.id,
        warehouse_id=order.warehouse_id,
        method=payload.method,
        notes=payload.notes,
        created_by=user.id,
        **{c["party_col"]: getattr(order, c["order_party"])},
    )
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
        total += price * qty
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
        change = c["sign"] * per_product[pid]
        if product.quantity + change < 0:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Insufficient stock to return '{product.name}': have {product.quantity}, returning {per_product[pid]}",
            )
        product.quantity += change
        db.add(models.StockMovement(product_id=pid, warehouse_id=order.warehouse_id, change=change, reason=c["reason"], reference=f"{c['prefix']}-{ret.id}"))
    audit(db, user, "return", f"{kind}_return", ret, f"{c['prefix']}-{ret.id} · إجمالي {total} · مردود نقداً {ret.refund_amount} · أمر {order.id}")
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
