"""Login, first-run setup and user management."""

from typing import List, Optional

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_admin
from ..security import DUMMY_HASH, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _make_user(
    db: Session,
    payload: schemas.SetupAdmin,
    role: str,
    actor: Optional[models.User] = None,
    branch_ids: Optional[List[int]] = None,
    warehouse_ids: Optional[List[int]] = None,
) -> models.User:
    company_id = db.info.get("company_id")
    if company_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No company is configured for user creation")
    user = models.User(
        username=payload.username.strip().lower(),
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    try:
        db.flush()
        db.add(
            models.UserCompanyMembership(
                user_id=user.id,
                company_id=company_id,
                role=role,
            )
        )
        user.active_company_id = company_id
        if branch_ids is None:
            branch_ids = [
                branch_id
                for (branch_id,) in db.query(models.Branch.id)
                .filter(models.Branch.company_id == company_id)
                .all()
            ]
        if warehouse_ids is None:
            warehouse_ids = [
                warehouse_id
                for (warehouse_id,) in db.query(models.Warehouse.id)
                .filter(models.Warehouse.company_id == company_id)
                .all()
            ]
        db.add_all(models.UserBranchAccess(user_id=user.id, branch_id=branch_id) for branch_id in branch_ids)
        db.add_all(
            models.UserWarehouseAccess(user_id=user.id, warehouse_id=warehouse_id)
            for warehouse_id in warehouse_ids
        )
        audit(db, actor, "create", "user", user, f"{user.username} ({role})")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Username '{payload.username}' already exists")
    db.refresh(user)
    return user


@router.post("/setup", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def first_run_setup(payload: schemas.SetupAdmin, db: Session = Depends(get_db)):
    """Creates the first admin. Only works while there are no users at all."""
    if db.query(models.User).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup already completed")
    company = db.query(models.Company).filter(models.Company.code == "default").one_or_none()
    if company is None:
        company = models.Company(name="Default Company", code="default")
        db.add(company)
        db.flush()
        db.add(models.Branch(company_id=company.id, name="Main Branch", code="main"))  # type: ignore
        db.flush()
    db.info["company_id"] = company.id
    user = _make_user(db, payload, role="admin")
    user.is_platform_admin = True  # type: ignore
    user.active_company_id = company.id
    db.commit()
    db.refresh(user)
    return user


# --- brute-force protection: too many failed logins per (client IP, username) -> 429 for a while.
# In-memory, so it is per worker process (the container runs a single worker); behind a proxy set
# FORWARDED_ALLOW_IPS so request.client.host is the real client address.
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "10"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "900"))
_failures: "defaultdict[str, deque]" = defaultdict(deque)
_failures_lock = threading.Lock()


def _recent_failures(key: str, now: float) -> deque:
    q = _failures[key]
    while q and now - q[0] > LOGIN_WINDOW_SECONDS:
        q.popleft()
    if not q:
        _failures.pop(key, None)
    return q


def _check_login_allowed(key: str) -> None:
    if LOGIN_MAX_FAILURES <= 0:
        return
    now = time.monotonic()
    with _failures_lock:
        q = _recent_failures(key, now)
        if len(q) >= LOGIN_MAX_FAILURES:
            retry = max(1, int(LOGIN_WINDOW_SECONDS - (now - q[0])))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many failed login attempts, try again later",
                headers={"Retry-After": str(retry)},
            )


def _record_login_failure(key: str) -> None:
    with _failures_lock:
        if len(_failures) > 10000:  # bound memory under a spray attack
            _failures.clear()
        _failures[key].append(time.monotonic())


@router.post("/login", response_model=schemas.Token)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else '?'}|{form.username.strip().lower()}"
    _check_login_allowed(key)
    user = db.query(models.User).filter(models.User.username == form.username.strip().lower()).one_or_none()
    # Always run one hash verification so response time doesn't reveal whether the user exists.
    valid = verify_password(form.password, user.hashed_password if user else DUMMY_HASH)  # type: ignore
    if user is None or not valid or not user.is_active:  # type: ignore
        _record_login_failure(key)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    membership = (
        db.query(models.UserCompanyMembership)
        .join(models.Company)
        .filter(models.UserCompanyMembership.user_id == user.id)
        .filter(models.Company.is_active.is_(True))
        .one_or_none()
    )
    if membership is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "User is not assigned to a company; contact the platform administrator",
        )
    db.info["company_id"] = membership.company_id
    with _failures_lock:
        _failures.pop(key, None)
    audit(db, user, "login", "user", user.id, None)
    db.commit()
    return schemas.Token(access_token=create_access_token(user.id))  # type: ignore


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


@router.get("/companies", response_model=List[schemas.CompanyOut])
def my_companies(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Companies the current user belongs to (for the company switcher)."""
    memberships = db.query(models.UserCompanyMembership).filter(models.UserCompanyMembership.user_id == user.id).all()
    ids = [m.company_id for m in memberships]
    return db.query(models.Company).filter(models.Company.id.in_(ids), models.Company.is_active.is_(True)).all()


@router.post("/switch-company", response_model=schemas.UserOut)
def switch_company(payload: schemas.SwitchCompany, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Switch the active company for the current user."""
    company = db.get(models.Company, payload.company_id)
    if company is None or not company.is_active:  # type: ignore
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    membership = db.query(models.UserCompanyMembership).filter(
        models.UserCompanyMembership.user_id == user.id,
        models.UserCompanyMembership.company_id == payload.company_id,
    ).one_or_none()
    if membership is None:
        if not user.is_platform_admin:  # type: ignore
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of that company")
        # Platform admins can switch to any active company; auto-create membership.
        membership = models.UserCompanyMembership(user_id=user.id, company_id=payload.company_id, role="admin")  # type: ignore
        db.add(membership)
    user.active_company_id = payload.company_id  # type: ignore
    db.commit()
    db.refresh(user)
    return user


@router.post("/users", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.UserCreate, db: Session = Depends(get_db), admin: models.User = Depends(require_admin)
):
    company_id = db.info["company_id"]
    if payload.role == "staff" and not payload.branch_ids and not payload.warehouse_ids:
        raise HTTPException(422, "Assign at least one branch or warehouse to a staff member")
    branch_count = (
        db.query(models.Branch.id)
        .filter(models.Branch.company_id == company_id, models.Branch.id.in_(payload.branch_ids or [-1]))
        .count()
    )
    warehouse_count = (
        db.query(models.Warehouse.id)
        .filter(
            models.Warehouse.company_id == company_id,
            models.Warehouse.id.in_(payload.warehouse_ids or [-1]),
        )
        .count()
    )
    if branch_count != len(set(payload.branch_ids)) or warehouse_count != len(set(payload.warehouse_ids)):
        raise HTTPException(422, "One or more access targets do not belong to this company")
    return _make_user(
        db,
        payload,
        role=payload.role,
        actor=admin,
        branch_ids=payload.branch_ids,
        warehouse_ids=payload.warehouse_ids,
    )


@router.get("/users", response_model=List[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    return (
        db.query(models.User)
        .join(models.UserCompanyMembership)
        .filter(models.UserCompanyMembership.company_id == db.info["company_id"])
        .order_by(models.User.id)
        .all()
    )


@router.patch("/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    membership = (
        db.query(models.UserCompanyMembership)
        .filter(
            models.UserCompanyMembership.user_id == user_id,
            models.UserCompanyMembership.company_id == db.info["company_id"],
        )
        .one_or_none()
    )
    user = db.get(models.User, user_id)
    if user is None or membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")
    if user.is_platform_admin and user.id != admin.id:  # type: ignore
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The platform administrator cannot be managed as a company employee")
    data = payload.model_dump(exclude_unset=True)
    # An admin must not lock themselves out by demoting or deactivating their own account.
    if user.id == admin.id and (data.get("role", "admin") != "admin" or data.get("is_active") is False):  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot demote or deactivate your own account")
    password_changed = "password" in data
    if "password" in data:
        user.hashed_password = hash_password(data.pop("password"))  # type: ignore
    if "role" in data:
        membership.role = data["role"]
    changed = [k for k in data] + (['password'] if password_changed else [])
    for key, value in data.items():
        setattr(user, key, value)
    audit(db, admin, "update", "user", user, f"{user.username}: " + "، ".join(changed))
    db.commit()
    db.refresh(user)
    return user
