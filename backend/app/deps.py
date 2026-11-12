"""Authentication / authorization dependencies."""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

ROLES = ("admin", "manager", "staff")


def get_current_user(
    request: Request = None,  # type: ignore[assignment]
    token_header: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    # البوابة المركزية (permission_gate) تصادق مسبقاً وتخزّن النتيجة — نعيد استخدامها
    # بدل فكّ التوكن والاستعلام عن المستخدم مرة ثانية في كل طلب.
    cached = getattr(request.state, "_current_user", None) if request is not None else None
    if cached is not None:
        return cached

    token = token_header
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_access_token(token)
    user = db.get(models.User, claims["id"]) if claims is not None else None
    if user is not None and claims.get("ver", 1) != int(getattr(user, "token_version", 1) or 1):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "انتهت الجلسة — سُجّل خروجك من هذا الجهاز، سجّل الدخول من جديد",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user is None or not user.is_active:  # type: ignore
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if request is not None:
        request.state._current_user = user

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
    if membership.all_branches:
        branch_ids = [
            branch_id
            for (branch_id,) in db.query(models.Branch.id)
            .filter(models.Branch.company_id == company_id, models.Branch.is_active.is_(True))
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
    if role in ("admin", "manager") or user.is_platform_admin:  # type: ignore
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
    return getattr(user, "_company_role", user.role)  # type: ignore


def require_permission_or_role(permission: str, *roles: str):
    """يسمح لحامل الصلاحية (حتى لو staff بمنح فردي) أو لأحد الأدوار المحددة."""

    def checker(
        request: Request,
        user: models.User = Depends(get_current_user),
    ) -> models.User:
        if user_role(user) in roles or user.is_platform_admin:  # type: ignore
            return user
        from .permissions import current_permissions, user_has_permission

        perms = getattr(request.state, "permissions", None) or current_permissions.get() or set()
        if user_has_permission(perms, permission):
            return user
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No permission")

    return checker


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
    if not user.is_platform_admin:  # type: ignore
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform administrator permission required")
    return user
