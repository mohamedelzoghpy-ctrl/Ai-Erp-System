"""CRUD for warehouses, suppliers and customers (parties also expose their current balance)."""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..accounts import party_balances
from ..audit import audit
from ..pagination import paginate
from ..database import get_db
from ..deps import get_current_user, require_manager, user_role

warehouses = APIRouter(prefix="/warehouses", tags=["warehouses"], dependencies=[Depends(get_current_user)])
suppliers = APIRouter(prefix="/suppliers", tags=["suppliers"], dependencies=[Depends(get_current_user)])
customers = APIRouter(prefix="/customers", tags=["customers"], dependencies=[Depends(get_current_user)])


def _get_or_404(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} {obj_id} not found")
    return obj


def _default_branch_id(db: Session) -> int:
    company_id = db.info.get("company_id")
    if company_id is None:
        company = db.query(models.Company).filter(models.Company.code == "default").one_or_none()
        if company is None:
            company = models.Company(name="Default Company", code="default")
            db.add(company)
            db.flush()
        company_id = company.id
        db.info["company_id"] = company_id
    branch = (
        db.query(models.Branch)
        .filter(models.Branch.company_id == company_id, models.Branch.is_active.is_(True))
        .order_by(models.Branch.id)
        .first()
    )
    if branch is None:
        branch = models.Branch(company_id=company_id, name="Main Branch", code="main")
        db.add(branch)
        db.flush()
    return branch.id


def _commit(db: Session, obj=None, before=None):
    try:
        if before:
            before()  # may flush, so constraint errors surface here and are reported as 409
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
    if user_role(user) not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can set an opening balance")


def _crud(router: APIRouter, model, label: str, create_s, update_s, out_s, kind: Optional[str] = None):
    entity = model.__tablename__.rstrip("s") if model.__tablename__ != "warehouses" else "warehouse"

    @router.post("", response_model=out_s, status_code=status.HTTP_201_CREATED)
    def create(payload: create_s, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):  # type: ignore[valid-type]
        data = payload.model_dump()
        if model is models.Warehouse:
            if user_role(user) not in ("admin", "manager"):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can create warehouses")
            branch_id = data.get("branch_id") or _default_branch_id(db)
            branch = (
                db.query(models.Branch)
                .filter(
                    models.Branch.id == branch_id,
                    models.Branch.company_id == db.info["company_id"],
                    models.Branch.is_active.is_(True),
                )
                .with_for_update()
                .one_or_none()
            )
            if branch is None:
                raise HTTPException(422, f"Branch {branch_id} does not exist in this company")
            company = db.get(models.Company, db.info["company_id"])
            if company is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
            if company.max_warehouses_per_branch is not None:
                count = (
                    db.query(models.Warehouse)
                    .filter(models.Warehouse.branch_id == branch.id)
                    .count()
                )
                if count >= company.max_warehouses_per_branch:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        f"Branch warehouse limit reached ({company.max_warehouses_per_branch})",
                    )
            data["branch_id"] = branch.id
        if Decimal(str(data.get("opening_balance") or 0)) != 0:
            _ensure_manager_for_balance(user)
        obj = model(**data)
        db.add(obj)
        _commit(db, obj, before=lambda: audit(db, user, "create", entity, obj, obj.name))
        _attach_balances(db, kind, obj)
        return obj

    @router.get("", response_model=List[out_s])
    def list_all(response: Response, search: Optional[str] = None, is_active: Optional[bool] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
        query = db.query(model)
        if search:
            like = f"%{search.strip()}%"
            cols = [getattr(model, c) for c in ("name", "phone", "contact_person", "email", "code") if hasattr(model, c)]
            query = query.filter(or_(*[c.ilike(like) for c in cols]))
        if is_active is not None and hasattr(model, "is_active"):
            query = query.filter(model.is_active == is_active)
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
            audit(db, user, "opening_balance", entity, obj, f"{obj.opening_balance} → {new_opening}")
            obj.opening_balance = new_opening
        for key, value in data.items():
            setattr(obj, key, value)
        _commit(db, obj, before=lambda: audit(db, user, "update", entity, obj, "، ".join(data) or None))
        _attach_balances(db, kind, obj)
        return obj

    @router.delete("/{obj_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete(obj_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
        obj = _get_or_404(db, model, obj_id, label)
        audit(db, user, "delete", entity, obj.id, obj.name)
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
