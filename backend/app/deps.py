"""Authentication / authorization dependencies."""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

ROLES = ("admin", "manager", "staff")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    user_id = decode_access_token(token)
    user = db.get(models.User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    membership = None
    if getattr(user, "active_company_id", None):
        membership = (
            db.query(models.UserCompanyMembership)
            .join(models.Company)
            .filter(
                models.UserCompanyMembership.user_id == user.id,
                models.UserCompanyMembership.company_id == user.active_company_id,
                models.Company.is_active.is_(True),
            )
            .one_or_none()
        )
    if membership is None:
        membership = (
            db.query(models.UserCompanyMembership)
            .join(models.Company)
            .filter(
                models.UserCompanyMembership.user_id == user.id,
                models.Company.is_active.is_(True),
            )
            .order_by(models.UserCompanyMembership.id)
            .first()
        )
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is not assigned to an active company")

    if getattr(user, "active_company_id", None) != membership.company_id:
        user.active_company_id = membership.company_id
        db.commit()

    company_id = membership.company_id
    role = membership.role
    branch_ids = [
        branch_id
        for (branch_id,) in db.query(models.UserBranchAccess.branch_id)
        .join(models.Branch, models.Branch.id == models.UserBranchAccess.branch_id)
        .filter(models.UserBranchAccess.user_id == user.id)
        .filter(models.Branch.company_id == company_id)
        .all()
    ]
    warehouse_ids = {
        warehouse_id
        for (warehouse_id,) in db.query(models.UserWarehouseAccess.warehouse_id)
        .join(models.Warehouse, models.Warehouse.id == models.UserWarehouseAccess.warehouse_id)
        .filter(models.UserWarehouseAccess.user_id == user.id)
        .filter(models.Warehouse.company_id == company_id)
        .all()
    }
    if role in ("admin", "manager") or user.is_platform_admin:
        warehouse_ids.update(
            warehouse_id
            for (warehouse_id,) in db.query(models.Warehouse.id)
            .filter(models.Warehouse.company_id == company_id)
            .all()
        )
    elif branch_ids:
        warehouse_ids.update(
            warehouse_id
            for (warehouse_id,) in db.query(models.Warehouse.id)
            .filter(models.Warehouse.branch_id.in_(branch_ids))
            .all()
        )
    visible_branch_ids = set(branch_ids)
    if warehouse_ids:
        visible_branch_ids.update(
            branch_id
            for (branch_id,) in db.query(models.Warehouse.branch_id)
            .filter(
                models.Warehouse.company_id == company_id,
                models.Warehouse.id.in_(warehouse_ids),
            )
            .all()
        )

    db.info.update(
        company_id=company_id,
        company_role=role,
        user_id=user.id,
        is_platform_admin=user.is_platform_admin,
        branch_ids=tuple(branch_ids),
        visible_branch_ids=tuple(visible_branch_ids),
        warehouse_ids=tuple(warehouse_ids),
    )
    user._company_role = role
    return user


def user_role(user: models.User) -> str:
    return getattr(user, "_company_role", user.role)


def require_roles(*allowed: str):
    """Dependency factory: only users whose role is in `allowed` may proceed."""

    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user_role(user) not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")
        return user

    return checker


require_admin = require_roles("admin")
require_manager = require_roles("admin", "manager")  # deleting master data / products


def require_platform_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform administrator permission required")
    return user
