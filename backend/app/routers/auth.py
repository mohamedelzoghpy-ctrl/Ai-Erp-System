"""Login, first-run setup and user management."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user, require_admin
from ..security import DUMMY_HASH, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _make_user(db: Session, payload: schemas.UserCreate, role: str) -> models.User:
    user = models.User(
        username=payload.username.strip().lower(),
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    try:
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


@router.post("/login", response_model=schemas.Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form.username.strip().lower()).one_or_none()
    # Always run one hash verification so response time doesn't reveal whether the user exists.
    valid = verify_password(form.password, user.hashed_password if user else DUMMY_HASH)
    if user is None or not valid or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return schemas.Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


@router.post("/users", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.UserCreate, db: Session = Depends(get_db), _: models.User = Depends(require_admin)
):
    return _make_user(db, payload, role=payload.role)


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
    if "password" in data:
        user.hashed_password = hash_password(data.pop("password"))
    for key, value in data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user
