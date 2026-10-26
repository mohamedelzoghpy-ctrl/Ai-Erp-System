"""Products and inventory (stock levels, adjustments, movement history)."""

from decimal import Decimal

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..pagination import paginate
from ..audit import audit
from ..deps import get_current_user, require_manager, user_role
from .. import models, schemas, stock
from ..database import get_db

router = APIRouter(prefix="/products", tags=["products & inventory"], dependencies=[Depends(get_current_user)])


def _product_or_404(db: Session, product_id: int) -> models.Product:
    product = db.get(models.Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product {product_id} not found")
    return product


def _check_refs(db: Session, warehouse_id: Optional[int], supplier_id: Optional[int]):
    if warehouse_id is not None and db.get(models.Warehouse, warehouse_id) is None:
        raise HTTPException(422, f"Warehouse {warehouse_id} does not exist")
    if supplier_id is not None and db.get(models.Supplier, supplier_id) is None:
        raise HTTPException(422, f"Supplier {supplier_id} does not exist")


@router.post("", response_model=schemas.ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: schemas.ProductCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    # Cost price and opening stock are manager-only (mirrors opening balances for parties).
    if user_role(user) not in ("admin", "manager"):
        if Decimal(str(payload.cost_price)) != 0:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can set a cost price")
        if payload.quantity != 0:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can set an opening stock balance")
    _check_refs(db, payload.warehouse_id, payload.supplier_id)
    data = payload.model_dump()
    opening = data.pop("quantity", 0)
    product = models.Product(**data)
    db.add(product)
    try:
        db.flush()
        if opening:
            home = stock.home_warehouse_id(db, product)
            if home is None:
                db.rollback()
                raise HTTPException(422, "Create a warehouse before adding opening stock")
            stock.move_stock(db, product, home, opening, "adjustment", "opening balance")
        audit(db, user, "create", "product", product, f"{product.sku} · {product.name}")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"SKU '{payload.sku}' already exists")
    db.refresh(product)
    return product


@router.get("", response_model=List[schemas.ProductOut])
def list_products(
    response: Response,
    search: Optional[str] = None,
    warehouse_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    low_stock: bool = False,
    is_active: Optional[bool] = None,
    stock_warehouse_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """`stock_warehouse_id` adds `warehouse_quantity` (what is on the shelf in that warehouse) to each row."""
    query = db.query(models.Product)
    if search:
        like = f"%{search}%"
        query = query.filter(models.Product.name.ilike(like) | models.Product.sku.ilike(like))
    if warehouse_id is not None:
        query = query.filter(models.Product.warehouse_id == warehouse_id)
    if supplier_id is not None:
        query = query.filter(models.Product.supplier_id == supplier_id)
    if is_active is not None:
        query = query.filter(models.Product.is_active == is_active)
    if low_stock:
        query = query.filter(models.Product.quantity <= models.Product.reorder_level)
    rows = paginate(query, response, skip, limit, models.Product.id)
    if stock_warehouse_id is not None and rows:
        have = dict(
            db.query(models.ProductStock.product_id, models.ProductStock.quantity)
            .filter(models.ProductStock.warehouse_id == stock_warehouse_id, models.ProductStock.product_id.in_([p.id for p in rows]))
            .all()
        )
        for p in rows:
            p.warehouse_quantity = have.get(p.id, 0)
    return rows


@router.get("/{product_id}", response_model=schemas.ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    return _product_or_404(db, product_id)


@router.patch("/{product_id}", response_model=schemas.ProductOut)
def update_product(product_id: int, payload: schemas.ProductUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    product = _product_or_404(db, product_id)
    data = payload.model_dump(exclude_unset=True)
    # Cost price changes are manager-only (mirrors opening balances for parties).
    if "cost_price" in data and user_role(user) not in ("admin", "manager"):
        if Decimal(str(data["cost_price"])) != Decimal(str(product.cost_price)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can change the cost price")
    _check_refs(db, data.get("warehouse_id"), data.get("supplier_id"))
    for key, value in data.items():
        setattr(product, key, value)
    audit(db, user, "update", "product", product, "، ".join(data) or None)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)
):
    product = _product_or_404(db, product_id)
    audit(db, user, "delete", "product", product.id, f"{product.sku} · {product.name}")
    db.delete(product)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Product has order or stock history; deactivate it instead (is_active=false)",
        )


@router.post("/{product_id}/adjust-stock", response_model=schemas.ProductOut)
def adjust_stock(product_id: int, payload: schemas.StockAdjustment, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Manual correction (stock-take, damage, etc.). Never lets quantity go negative."""
    if payload.change == 0:
        raise HTTPException(422, "change must not be zero")
    product = (
        db.query(models.Product).filter(models.Product.id == product_id).with_for_update().one_or_none()
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product {product_id} not found")
    warehouse_id = payload.warehouse_id if payload.warehouse_id is not None else stock.home_warehouse_id(db, product)
    if warehouse_id is None or db.get(models.Warehouse, warehouse_id) is None:
        raise HTTPException(422, "Choose an existing warehouse for this adjustment")
    stock.move_stock(db, product, warehouse_id, payload.change, "adjustment", payload.reference)
    audit(db, user, "adjust_stock", "product", product, f"{payload.change:+d} → {product.quantity}" + (f" ({payload.reference})" if payload.reference else ""))
    db.commit()
    db.refresh(product)
    return product


@router.get("/{product_id}/stock", response_model=List[schemas.ProductStockOut])
def product_stock(product_id: int, db: Session = Depends(get_db)):
    """Where this product's stock sits, one row per warehouse that holds some."""
    _product_or_404(db, product_id)
    rows = (
        db.query(models.ProductStock)
        .filter(models.ProductStock.product_id == product_id, models.ProductStock.quantity > 0)
        .order_by(models.ProductStock.warehouse_id)
        .all()
    )
    return [schemas.ProductStockOut(warehouse_id=r.warehouse_id, warehouse_name=r.warehouse.name, quantity=r.quantity) for r in rows]


@router.get("/{product_id}/movements", response_model=List[schemas.StockMovementOut])
def product_movements(product_id: int, db: Session = Depends(get_db)):
    _product_or_404(db, product_id)
    return (
        db.query(models.StockMovement)
        .filter(models.StockMovement.product_id == product_id)
        .order_by(models.StockMovement.id.desc())
        .all()
    )
