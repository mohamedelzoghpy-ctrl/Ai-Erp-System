"""CRUD for warehouses, suppliers and customers."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import require_manager

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


def _crud(router: APIRouter, model, label: str, create_s, update_s, out_s):
    @router.post("", response_model=out_s, status_code=status.HTTP_201_CREATED)
    def create(payload: create_s, db: Session = Depends(get_db)):  # type: ignore[valid-type]
        obj = model(**payload.model_dump())
        db.add(obj)
        _commit(db, obj)
        return obj

    @router.get("", response_model=List[out_s])
    def list_all(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
        return db.query(model).order_by(model.id).offset(skip).limit(min(limit, 500)).all()

    @router.get("/{obj_id}", response_model=out_s)
    def read(obj_id: int, db: Session = Depends(get_db)):
        return _get_or_404(db, model, obj_id, label)

    @router.patch("/{obj_id}", response_model=out_s)
    def update(obj_id: int, payload: update_s, db: Session = Depends(get_db)):  # type: ignore[valid-type]
        obj = _get_or_404(db, model, obj_id, label)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        _commit(db, obj)
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
                f"{label} is referenced by existing orders; deactivate it instead (is_active=false)",
            )


_crud(warehouses, models.Warehouse, "Warehouse", schemas.WarehouseCreate, schemas.WarehouseUpdate, schemas.WarehouseOut)
_crud(suppliers, models.Supplier, "Supplier", schemas.SupplierCreate, schemas.SupplierUpdate, schemas.SupplierOut)
_crud(customers, models.Customer, "Customer", schemas.CustomerCreate, schemas.CustomerUpdate, schemas.CustomerOut)
