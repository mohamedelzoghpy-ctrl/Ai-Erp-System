"""قوائم الأسعار: CRUD + بنودها (أسعار بديلة لصنف معين تُطبَّق على عملاء حاملين القائمة)."""
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager
from ..pagination import paginate

router = APIRouter(prefix="/price-lists", tags=["price lists"], dependencies=[Depends(get_current_user)])


class PriceListItemIn(BaseModel):
    product_id: int
    unit_price: Decimal = Field(ge=0)


class PriceListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    notes: Optional[str] = Field(default=None, max_length=255)
    is_active: bool = True
    items: List[PriceListItemIn] = Field(default_factory=list)


class PriceListUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    notes: Optional[str] = Field(default=None, max_length=255)
    is_active: Optional[bool] = None
    items: Optional[List[PriceListItemIn]] = None  # إن حُددت: تُستبدل البنود كاملة


def _out(db: Session, pl: models.PriceList) -> dict:
    items = (
        db.query(models.PriceListItem, models.Product.sku, models.Product.name)
        .join(models.Product, models.Product.id == models.PriceListItem.product_id)
        .filter(models.PriceListItem.price_list_id == pl.id)
        .order_by(models.Product.name)
        .all()
    )
    customers_count = db.query(models.Customer).filter(models.Customer.price_list_id == pl.id).count()
    return {
        "id": pl.id,
        "name": pl.name,
        "notes": pl.notes,
        "is_active": pl.is_active,
        "customers_count": customers_count,
        "items": [
            {"product_id": it.product_id, "sku": sku, "name": name, "unit_price": it.unit_price}
            for it, sku, name in items
        ],
    }


def _get(db: Session, price_list_id: int) -> models.PriceList:
    pl = db.query(models.PriceList).filter(
        models.PriceList.id == price_list_id, models.PriceList.company_id == db.info["company_id"]
    ).first()
    if pl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "قائمة الأسعار غير موجودة")
    return pl


def _validate_products(db: Session, items: List[PriceListItemIn]) -> None:
    if not items:
        return
    ids = {it.product_id for it in items}
    found = {
        pid for (pid,) in db.query(models.Product.id).filter(
            models.Product.id.in_(ids), models.Product.company_id == db.info["company_id"]
        ).all()
    }
    missing = ids - found
    if missing:
        raise HTTPException(422, f"منتجات غير موجودة: {sorted(missing)[:5]}")
    dupes = [it.product_id for it in items if list(map(lambda x: x.product_id, items)).count(it.product_id) > 1]
    if dupes:
        raise HTTPException(422, f"منتجات مكررة في القائمة: {sorted(set(dupes))[:5]}")


def _apply_items(db: Session, pl: models.PriceList, items: List[PriceListItemIn]) -> None:
    _validate_products(db, items)
    db.query(models.PriceListItem).filter(models.PriceListItem.price_list_id == pl.id).delete()
    for it in items:
        db.add(models.PriceListItem(
            company_id=pl.company_id, price_list_id=pl.id,
            product_id=it.product_id, unit_price=it.unit_price,
        ))
    db.flush()


@router.get("")
def list_price_lists(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.PriceList).filter(models.PriceList.company_id == db.info["company_id"]).order_by(models.PriceList.id)
    rows = paginate(q, response, skip, min(limit, 200), models.PriceList.id)
    return [_out(db, pl) for pl in rows]


@router.get("/{price_list_id}")
def get_price_list(price_list_id: int, db: Session = Depends(get_db)):
    return _out(db, _get(db, price_list_id))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_price_list(
    payload: PriceListCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    dup = db.query(models.PriceList).filter(
        models.PriceList.company_id == company_id, models.PriceList.name == payload.name.strip()
    ).first()
    if dup is not None:
        raise HTTPException(409, "توجد قائمة باسم «" + payload.name.strip() + "» — اختر اسمًا مختلفًا")
    pl = models.PriceList(company_id=company_id, name=payload.name.strip(), notes=payload.notes, is_active=payload.is_active)
    db.add(pl)
    db.flush()
    _apply_items(db, pl, payload.items)
    audit(db, user, "create", "price_list", pl, f"{pl.name} · {len(payload.items)} سعر")
    db.commit()
    db.refresh(pl)
    return _out(db, pl)


@router.put("/{price_list_id}")
def update_price_list(
    price_list_id: int,
    payload: PriceListUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    pl = _get(db, price_list_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        dup = db.query(models.PriceList).filter(
            models.PriceList.company_id == db.info["company_id"],
            models.PriceList.name == data["name"].strip(),
            models.PriceList.id != pl.id,
        ).first()
        if dup is not None:
            raise HTTPException(409, "الاسم مستخدم بالفعل")
        pl.name = data["name"].strip()
    if "notes" in data:
        pl.notes = data["notes"]
    if "is_active" in data and data["is_active"] is not None:
        pl.is_active = data["is_active"]
    if data.get("items") is not None:
        _apply_items(db, pl, payload.items)  # type: ignore[arg-type]
    audit(db, user, "update", "price_list", pl, ", ".join(data.keys()))
    db.commit()
    db.refresh(pl)
    return _out(db, pl)


@router.delete("/{price_list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_price_list(
    price_list_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    pl = _get(db, price_list_id)
    linked = db.query(models.Customer).filter(models.Customer.price_list_id == price_list_id).count()
    if linked:
        raise HTTPException(409, f"القائمة مرتبطة بـ {linked} عميل — افصل العملاء أولًا")
    audit(db, user, "delete", "price_list", pl.id, f"قائمة {pl.name}")
    db.delete(pl)
    db.commit()
    return None
