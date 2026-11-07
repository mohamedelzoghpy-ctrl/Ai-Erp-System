"""Fixed Assets — manage company assets, depreciation, and disposals."""
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(
    prefix="/fixed-assets",
    tags=["fixed assets"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=List[schemas.FixedAssetOut])
def list_assets(
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    company_id = db.info["company_id"]
    q = db.query(models.FixedAsset).filter(models.FixedAsset.company_id == company_id)
    if is_active is not None:
        q = q.filter(models.FixedAsset.is_active == is_active)
    return q.order_by(models.FixedAsset.id).all()


@router.get("/{asset_id}", response_model=schemas.FixedAssetOut)
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(models.FixedAsset, asset_id)
    if asset is None or asset.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    return asset


@router.post("", response_model=schemas.FixedAssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(
    payload: schemas.FixedAssetCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    code = (payload.code or "").strip() or unique_code(db, models.FixedAsset, company_id, payload.name, "AST", max_length=50)
    if db.query(models.FixedAsset).filter(
        models.FixedAsset.company_id == company_id,
        models.FixedAsset.code == code,
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Asset code already exists")
    asset = models.FixedAsset(
        company_id=company_id,
        name=payload.name.strip(),
        code=code,
        asset_type=payload.asset_type,
        purchase_date=payload.purchase_date,
        cost=payload.cost,
        accumulated_depreciation=payload.accumulated_depreciation,
        current_book_value=payload.current_book_value,
        depreciation_method=payload.depreciation_method,
        useful_life_years=payload.useful_life_years,
        salvage_value=payload.salvage_value,
        is_active=payload.is_active,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    audit(db, user, "create", "fixed_asset", asset, f"{asset.code} · {asset.name}")
    return asset


@router.patch("/{asset_id}", response_model=schemas.FixedAssetOut)
def update_asset(
    asset_id: int,
    payload: schemas.FixedAssetUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    asset = db.get(models.FixedAsset, asset_id)
    if asset is None or asset.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if value is not None:
            setattr(asset, key, value)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Asset code already exists or update violates a constraint",
        ) from exc
    db.refresh(asset)
    audit(db, user, "update", "fixed_asset", asset, ", ".join(data.keys()))
    return asset


@router.post("/{asset_id}/depreciate", response_model=schemas.FixedAssetOut)
def post_depreciation(
    asset_id: int,
    amount: Decimal,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """Record a depreciation entry for an asset."""
    asset = db.get(models.FixedAsset, asset_id)
    if asset is None or asset.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    if amount <= 0:
        raise HTTPException(422, "Depreciation amount must be positive")
    if asset.current_book_value - amount < asset.salvage_value:
        raise HTTPException(422, "Depreciation exceeds salvage value")

    asset.accumulated_depreciation += amount
    asset.current_book_value -= amount
    db.commit()
    db.refresh(asset)
    audit(db, user, "depreciate", "fixed_asset", asset, f"Depreciation: {amount}")
    return asset


@router.post("/{asset_id}/dispose", response_model=schemas.FixedAssetOut)
def dispose_asset(
    asset_id: int,
    disposal_proceeds: Decimal,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """Dispose of an asset at the end of its useful life."""
    asset = db.get(models.FixedAsset, asset_id)
    if asset is None or asset.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    asset.is_active = False
    db.commit()
    db.refresh(asset)
    audit(
        db,
        user,
        "dispose",
        "fixed_asset",
        asset,
        f"Disposed. Proceeds: {disposal_proceeds}",
    )
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    asset = db.get(models.FixedAsset, asset_id)
    if asset is None or asset.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    db.delete(asset)
    db.commit()
    audit(db, user, "delete", "fixed_asset", asset_id, f"asset {asset_id}")