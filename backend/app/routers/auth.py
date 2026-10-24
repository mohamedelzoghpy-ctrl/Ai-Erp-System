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


def _make_user(db: Session, payload: schemas.UserCreate, role: str, actor: Optional[models.User] = None) -> models.User:
    user = models.User(
        username=payload.username.strip().lower(),
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    try:
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
    return _make_user(db, payload, role="admin")


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
    valid = verify_password(form.password, user.hashed_password if user else DUMMY_HASH)
    if user is None or not valid or not user.is_active:
        _record_login_failure(key)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    with _failures_lock:
        _failures.pop(key, None)
    audit(db, user, "login", "user", user.id, None)
    db.commit()
    return schemas.Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


@router.post("/users", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.UserCreate, db: Session = Depends(get_db), admin: models.User = Depends(require_admin)
):
    return _make_user(db, payload, role=payload.role, actor=admin)


@router.get("/users", response_model=List[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    return db.query(models.User).order_by(models.User.id).all()


@router.patch("/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")
    data = payload.model_dump(exclude_unset=True)
    # An admin must not lock themselves out by demoting or deactivating their own account.
    if user.id == admin.id and (data.get("role", "admin") != "admin" or data.get("is_active") is False):
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot demote or deactivate your own account")
    if (
        user.role == "admin"
        and user.is_active
        and (data.get("role", "admin") != "admin" or data.get("is_active") is False)
    ):
        active_admins = (
            db.query(models.User)
            .filter(models.User.role == "admin", models.User.is_active.is_(True))
            .with_for_update()
            .all()
        )
        if len(active_admins) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "At least one active admin account must remain")

    password_changed = "password" in data
    if "password" in data:
        user.hashed_password = hash_password(data.pop("password"))
    changed = [k for k in data] + (['password'] if password_changed else [])
    for key, value in data.items():
        setattr(user, key, value)
    audit(db, admin, "update", "user", user, f"{user.username}: " + "، ".join(changed))
    db.commit()
    db.refresh(user)
    return user
