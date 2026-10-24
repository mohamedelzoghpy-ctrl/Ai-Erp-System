"""CRUD for warehouses, suppliers and customers (parties also expose their current balance)."""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..accounts import party_balances
from ..pagination import paginate
from ..database import get_db
from ..deps import get_current_user, require_manager

warehouses = APIRouter(prefix="/warehouses", tags=["warehouses"])
suppliers = APIRouter(prefix="/suppliers", tags=["suppliers"])
customers = APIRouter(prefix="/customers", tags=["customers"])


def _get_or_404(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} {obj_id} not found")
    return obj


def _commit(db: Session, obj=None):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate or invalid value (name/code must be unique)")
    if obj is not None:
        db.refresh(obj)


def _attach_balances(db: Session, kind: Optional[str], objs) -> None:
    """Parties carry a computed `balance`; warehouses (kind None) have none."""
    if kind is None:
        return
    items = objs if isinstance(objs, list) else [objs]
    balances = party_balances(db, kind, [o.id for o in items])
    for o in items:
        o.balance = balances.get(o.id, Decimal("0"))


def _ensure_manager_for_balance(user: models.User) -> None:
    """Opening balances change what a party owes, so only managers/admins may set them."""
    if user.role not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can set an opening balance")


def _crud(router: APIRouter, model, label: str, create_s, update_s, out_s, kind: Optional[str] = None):
    @router.post("", response_model=out_s, status_code=status.HTTP_201_CREATED)
    def create(payload: create_s, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):  # type: ignore[valid-type]
        data = payload.model_dump()
        if Decimal(str(data.get("opening_balance") or 0)) != 0:
            _ensure_manager_for_balance(user)
        obj = model(**data)
        db.add(obj)
        _commit(db, obj)
        _attach_balances(db, kind, obj)
        return obj

    @router.get("", response_model=List[out_s])
    def list_all(response: Response, search: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
        query = db.query(model)
        if search:
            like = f"%{search.strip()}%"
            cols = [getattr(model, c) for c in ("name", "phone", "contact_person", "email", "code") if hasattr(model, c)]
            query = query.filter(or_(*[c.ilike(like) for c in cols]))
        rows = paginate(query, response, skip, limit, model.id)
        _attach_balances(db, kind, rows)
        return rows

    @router.get("/{obj_id}", response_model=out_s)
    def read(obj_id: int, db: Session = Depends(get_db)):
        obj = _get_or_404(db, model, obj_id, label)
        _attach_balances(db, kind, obj)
        return obj

    @router.patch("/{obj_id}", response_model=out_s)
    def update(obj_id: int, payload: update_s, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):  # type: ignore[valid-type]
        obj = _get_or_404(db, model, obj_id, label)
        data = payload.model_dump(exclude_unset=True)
        new_opening = data.pop("opening_balance", None)
        if new_opening is not None and Decimal(str(new_opening)) != Decimal(str(obj.opening_balance)):
            _ensure_manager_for_balance(user)
            obj.opening_balance = new_opening
        for key, value in data.items():
            setattr(obj, key, value)
        _commit(db, obj)
        _attach_balances(db, kind, obj)
        return obj

    @router.delete("/{obj_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete(obj_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
        obj = _get_or_404(db, model, obj_id, label)
        db.delete(obj)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{label} is referenced by existing orders or payments; deactivate it instead (is_active=false)",
            )


_crud(warehouses, models.Warehouse, "Warehouse", schemas.WarehouseCreate, schemas.WarehouseUpdate, schemas.WarehouseOut)
_crud(suppliers, models.Supplier, "Supplier", schemas.SupplierCreate, schemas.SupplierUpdate, schemas.SupplierOut, kind="supplier")
_crud(customers, models.Customer, "Customer", schemas.CustomerCreate, schemas.CustomerUpdate, schemas.CustomerOut, kind="customer")
