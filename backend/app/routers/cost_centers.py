"""Cost Centers — company-scoped master data."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(
    prefix="/cost-centers",
    tags=["cost centers"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=List[schemas.CostCenterOut])
def list_cost_centers(
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    company_id = db.info["company_id"]
    q = db.query(models.CostCenter).filter(models.CostCenter.company_id == company_id)
    if is_active is not None:
        q = q.filter(models.CostCenter.is_active == is_active)
    return q.order_by(models.CostCenter.id).all()


@router.get("/{cc_id}", response_model=schemas.CostCenterOut)
def get_cost_center(cc_id: int, db: Session = Depends(get_db)):
    cc = db.get(models.CostCenter, cc_id)
    if cc is None or cc.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cost center not found")
    return cc


@router.post("", response_model=schemas.CostCenterOut, status_code=status.HTTP_201_CREATED)
def create_cost_center(
    payload: schemas.CostCenterCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    code = (payload.code or "").strip() or unique_code(
        db, models.CostCenter, company_id, payload.name, "CC", max_length=50
    )
    if db.query(models.CostCenter).filter(
        models.CostCenter.company_id == company_id,
        models.CostCenter.code == code,
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Cost center code already exists")
    cc = models.CostCenter(
        company_id=company_id,
        name=payload.name.strip(),
        code=code,
        is_active=payload.is_active,
    )
    db.add(cc)
    db.commit()
    db.refresh(cc)
    audit(db, user, "create", "cost_center", cc, f"{cc.code} · {cc.name}")
    return cc


@router.patch("/{cc_id}", response_model=schemas.CostCenterOut)
def update_cost_center(
    cc_id: int,
    payload: schemas.CostCenterUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    cc = db.get(models.CostCenter, cc_id)
    if cc is None or cc.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cost center not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        cc.name = data["name"].strip()
    if "code" in data and data["code"] is not None:
        cc.code = data["code"].strip() or unique_code(
            db, models.CostCenter, db.info["company_id"], cc.name, "CC"
        )
    if "is_active" in data and data["is_active"] is not None:
        cc.is_active = data["is_active"]
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cost center code already exists or update violates a constraint",
        ) from exc
    db.refresh(cc)
    audit(db, user, "update", "cost_center", cc, ", ".join(data.keys()))
    return cc


@router.delete("/{cc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cost_center(cc_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    cc = db.get(models.CostCenter, cc_id)
    if cc is None or cc.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cost center not found")
    db.delete(cc)
    db.commit()
    audit(db, user, "delete", "cost_center", cc_id, f"cost center {cc_id}")