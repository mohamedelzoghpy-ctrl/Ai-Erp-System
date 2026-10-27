"""Safes (cash boxes) and bank accounts (company-scoped master data)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager


safes = APIRouter(prefix="/safes", tags=["safes & banks"], dependencies=[Depends(get_current_user)])
banks = APIRouter(prefix="/banks", tags=["safes & banks"], dependencies=[Depends(get_current_user)])


# ---------- Safes ----------
@safes.get("", response_model=List[schemas.SafeOut])
def list_safes(db: Session = Depends(get_db)):
    return db.query(models.Safe).order_by(models.Safe.id).all()


@safes.post("", response_model=schemas.SafeOut, status_code=status.HTTP_201_CREATED)
def create_safe(payload: schemas.SafeCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    if db.query(models.Safe).filter(models.Safe.company_id == company_id, models.Safe.code == payload.code.strip()).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Safe code already exists")
    s = models.Safe(company_id=company_id, name=payload.name.strip(), code=payload.code.strip(), balance=payload.opening_balance, is_active=payload.is_active)  # type: ignore
    db.add(s)
    db.commit()
    db.refresh(s)
    audit(db, user, "create", "safe", s, f"{s.code} · {s.name}")
    return s


@safes.delete("/{safe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_safe(safe_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    s = db.get(models.Safe, safe_id)
    if s is None or s.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Safe not found")
    db.delete(s)
    db.commit()
    audit(db, user, "delete", "safe", safe_id, f"safe {safe_id}")


# ---------- Banks ----------
@banks.get("", response_model=List[schemas.BankOut])
def list_banks(db: Session = Depends(get_db)):
    return db.query(models.Bank).order_by(models.Bank.id).all()


@banks.post("", response_model=schemas.BankOut, status_code=status.HTTP_201_CREATED)
def create_bank(payload: schemas.BankCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    if db.query(models.Bank).filter(models.Bank.company_id == company_id, models.Bank.code == payload.code.strip()).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Bank code already exists")
    b = models.Bank(company_id=company_id, name=payload.name.strip(), code=payload.code.strip(), account_number=payload.account_number, balance=payload.opening_balance, is_active=payload.is_active)  # type: ignore
    db.add(b)
    db.commit()
    db.refresh(b)
    audit(db, user, "create", "bank", b, f"{b.code} · {b.name}")
    return b


@banks.delete("/{bank_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank(bank_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    b = db.get(models.Bank, bank_id)
    if b is None or b.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank not found")
    db.delete(b)
    db.commit()
    audit(db, user, "delete", "bank", bank_id, f"bank {bank_id}")