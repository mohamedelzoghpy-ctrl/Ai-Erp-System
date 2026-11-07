"""Fiscal Years — company-scoped master data."""
from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(
    prefix="/fiscal-years",
    tags=["fiscal years"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=List[schemas.FiscalYearOut])
def list_fiscal_years(
    is_closed: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    company_id = db.info["company_id"]
    q = db.query(models.FiscalYear).filter(models.FiscalYear.company_id == company_id)
    if is_closed is not None:
        q = q.filter(models.FiscalYear.is_closed == is_closed)
    return q.order_by(models.FiscalYear.start_date.desc()).all()


@router.get("/{fy_id}", response_model=schemas.FiscalYearOut)
def get_fiscal_year(fy_id: int, db: Session = Depends(get_db)):
    fy = db.get(models.FiscalYear, fy_id)
    if fy is None or fy.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fiscal year not found")
    return fy


@router.post("", response_model=schemas.FiscalYearOut, status_code=status.HTTP_201_CREATED)
def create_fiscal_year(
    payload: schemas.FiscalYearCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    # Check for overlap with existing fiscal years
    overlap = db.query(models.FiscalYear).filter(
        models.FiscalYear.company_id == company_id,
        models.FiscalYear.start_date <= payload.end_date,
        models.FiscalYear.end_date >= payload.start_date,
    ).first()
    if overlap:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Fiscal year overlaps with existing year '{overlap.name}'",
        )
    fy = models.FiscalYear(
        company_id=company_id,
        name=payload.name.strip(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_closed=payload.is_closed,
    )
    db.add(fy)
    db.commit()
    db.refresh(fy)
    audit(db, user, "create", "fiscal_year", fy, f"{fy.name} · {fy.start_date} → {fy.end_date}")
    return fy


@router.patch("/{fy_id}", response_model=schemas.FiscalYearOut)
def update_fiscal_year(
    fy_id: int,
    payload: schemas.FiscalYearUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    fy = db.get(models.FiscalYear, fy_id)
    if fy is None or fy.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fiscal year not found")
    data = payload.model_dump(exclude_unset=True)
    # Closing/reopening is always allowed; other edits are blocked once closed.
    only_toggle = set(data.keys()) <= {"is_closed"}
    if fy.is_closed and not only_toggle:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot modify a closed fiscal year")
    if "name" in data and data["name"] is not None:
        fy.name = data["name"].strip()
    if "start_date" in data:
        fy.start_date = data["start_date"]
    if "end_date" in data:
        fy.end_date = data["end_date"]
    if "is_closed" in data:
        fy.is_closed = data["is_closed"]
    # Re-check overlap after changes
    overlap = db.query(models.FiscalYear).filter(
        models.FiscalYear.id != fy_id,
        models.FiscalYear.company_id == db.info["company_id"],
        models.FiscalYear.start_date <= fy.end_date,
        models.FiscalYear.end_date >= fy.start_date,
    ).first()
    if overlap:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Updated fiscal year overlaps with existing year '{overlap.name}'",
        )
    # Auto-create the next fiscal year when closing this one.
    created_next = None
    if data.get("is_closed") is True:
        next_year = fy.end_date.year + 1
        exists = db.query(models.FiscalYear).filter(
            models.FiscalYear.company_id == db.info["company_id"],
            models.FiscalYear.start_date == date(next_year, 1, 1),
        ).first()
        if exists is None:
            created_next = models.FiscalYear(
                company_id=db.info["company_id"],
                name=f"FY {next_year}",
                start_date=date(next_year, 1, 1),
                end_date=date(next_year, 12, 31),
                is_closed=False,
            )
            db.add(created_next)
    db.commit()
    db.refresh(fy)
    if created_next is not None:
        db.refresh(created_next)
    audit(db, user, "update", "fiscal_year", fy, ", ".join(data.keys()))
    return fy


@router.delete("/{fy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fiscal_year(fy_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    fy = db.get(models.FiscalYear, fy_id)
    if fy is None or fy.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fiscal year not found")
    if fy.is_closed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot delete a closed fiscal year")
    db.delete(fy)
    db.commit()
    audit(db, user, "delete", "fiscal_year", fy_id, f"fiscal year {fy_id}")