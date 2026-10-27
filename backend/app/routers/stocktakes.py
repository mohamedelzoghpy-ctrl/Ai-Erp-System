"""Stock-take (جرد): print a count sheet, enter what was counted, then apply the differences as stock adjustments."""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from .. import exports, models, schemas, stock
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager, user_role
from ..pagination import paginate

router = APIRouter(prefix="/stocktakes", tags=["stock-take"])


def _out(s: models.Stocktake, detail: bool = False) -> schemas.StocktakeOut:
    counted = [l for l in s.lines if l.counted_qty is not None]
    return schemas.StocktakeOut(
        id=s.id,
        status=s.status,
        warehouse_id=s.warehouse_id,
        warehouse_name=s.warehouse.name if s.warehouse else None,
        notes=s.notes,
        username=s.username,
        created_at=s.created_at,
        applied_at=s.applied_at,
        lines_total=len(s.lines),
        lines_counted=len(counted),
        lines_with_difference=sum(1 for l in counted if l.difference != 0),
        lines=[schemas.StocktakeLineOut.model_validate(l) for l in s.lines] if detail else None,
    )


def _get(db: Session, stocktake_id: int, lock: bool = False) -> models.Stocktake:
    q = db.query(models.Stocktake).filter(models.Stocktake.id == stocktake_id)
    if lock:
        q = q.with_for_update()
    s = q.one_or_none()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Stock-take {stocktake_id} not found")
    return s


@router.post("", response_model=schemas.StocktakeOut, status_code=status.HTTP_201_CREATED)
def create(payload: schemas.StocktakeCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if db.get(models.Warehouse, payload.warehouse_id) is None:
        raise HTTPException(422, f"Warehouse {payload.warehouse_id} does not exist")
    # Lines: every active product that has stock in this warehouse or belongs to it, with that warehouse's quantity.
    held = dict(db.query(models.ProductStock.product_id, models.ProductStock.quantity).filter(models.ProductStock.warehouse_id == payload.warehouse_id).all())
    q = db.query(models.Product).filter(models.Product.is_active.is_(True))
    products = [
        p for p in q.order_by(models.Product.name, models.Product.id).all()
        if held.get(p.id, 0) > 0 or p.warehouse_id == payload.warehouse_id
    ]
    if not products:
        raise HTTPException(status.HTTP_409_CONFLICT, "No active products to count in this warehouse")
    s = models.Stocktake(warehouse_id=payload.warehouse_id, notes=payload.notes, created_by=user.id, username=user.username)
    s.lines = [models.StocktakeLine(product_id=p.id, system_qty=held.get(p.id, 0)) for p in products]
    db.add(s)
    audit(db, user, "create", "stocktake", s, f"{len(products)} صنف")
    db.commit()
    db.refresh(s)
    return _out(s)


@router.get("", response_model=List[schemas.StocktakeOut])
def list_stocktakes(response: Response, status_filter: Optional[str] = None, skip: int = 0, limit: int = 50, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    q = db.query(models.Stocktake).options(joinedload(models.Stocktake.lines))
    if status_filter:
        q = q.filter(models.Stocktake.status == status_filter)
    return [_out(s) for s in paginate(q, response, skip, limit, models.Stocktake.id.desc())]


@router.get("/{stocktake_id}", response_model=schemas.StocktakeOut)
def detail(stocktake_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return _out(_get(db, stocktake_id), detail=True)


@router.put("/{stocktake_id}/counts", response_model=schemas.StocktakeOut)
def save_counts(stocktake_id: int, payload: schemas.StocktakeCounts, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    s = _get(db, stocktake_id, lock=True)
    if s.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Stock-take is {s.status}")
    by_product = {l.product_id: l for l in s.lines}
    unknown = [c.product_id for c in payload.counts if c.product_id not in by_product]
    if unknown:
        raise HTTPException(422, f"Products not on this count sheet: {sorted(set(unknown))}")
    for c in payload.counts:
        by_product[c.product_id].counted_qty = c.counted_qty
    db.commit()
    db.refresh(s)
    return _out(s, detail=True)


@router.post("/{stocktake_id}/lines", response_model=schemas.StocktakeOut)
def add_line(stocktake_id: int, payload: schemas.StocktakeAddLine, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    s = _get(db, stocktake_id, lock=True)
    if s.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Stock-take is already {s.status}")
    p = db.get(models.Product, payload.product_id)
    if p is None or not p.is_active:
        raise HTTPException(422, "Product not found or inactive")
    if any(l.product_id == payload.product_id for l in s.lines):
        raise HTTPException(409, "Product already in this stock-take")
    held = dict(db.query(models.ProductStock.product_id, models.ProductStock.quantity).filter(models.ProductStock.warehouse_id == s.warehouse_id).all())
    s.lines.append(models.StocktakeLine(product_id=p.id, system_qty=held.get(p.id, 0)))
    audit(db, user, "update", "stocktake", s, f"added {p.sku}")
    db.commit()
    db.refresh(s)
    return _out(s, detail=True)


@router.post("/{stocktake_id}/apply", response_model=schemas.StocktakeOut)
def apply(stocktake_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """Adds (counted - system at sheet time) to each counted product's *current* stock, so sales made during the count are kept."""
    s = _get(db, stocktake_id, lock=True)
    if s.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Stock-take is already {s.status}")
    counted = [l for l in s.lines if l.counted_qty is not None]
    if not counted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing counted yet")
    products = {
        p.id: p
        for p in db.query(models.Product).filter(models.Product.id.in_([l.product_id for l in counted])).order_by(models.Product.id).with_for_update().all()
    }
    wid = s.warehouse_id
    # (a legacy count without a warehouse adjusts each product in its own warehouse)
    problems = []
    for l in counted:
        delta = l.counted_qty - l.system_qty
        target = wid if wid is not None else stock.home_warehouse_id(db, products[l.product_id])
        if delta < 0 and stock.available(db, l.product_id, target) + delta < 0:
            problems.append(f"{products[l.product_id].name}: الكمية الحالية {stock.available(db, l.product_id, target)} والتسوية {delta:+d}")
    if problems:
        raise HTTPException(status.HTTP_409_CONFLICT, "Would make stock negative (stock moved since the sheet was created): " + "; ".join(problems))
    changed = 0
    for l in counted:
        delta = l.counted_qty - l.system_qty
        if delta == 0:
            continue
        target = wid if wid is not None else stock.home_warehouse_id(db, products[l.product_id])
        stock.move_stock(db, products[l.product_id], target, delta, "stocktake", f"ST-{s.id}")
        changed += 1
    s.status = "applied"
    s.applied_at = datetime.now(timezone.utc)
    s.applied_by = user.id
    audit(db, user, "apply", "stocktake", s, f"{len(counted)} صنف معدود · {changed} تسوية")
    db.commit()
    db.refresh(s)
    return _out(s, detail=True)


@router.post("/{stocktake_id}/cancel", response_model=schemas.StocktakeOut)
def cancel(stocktake_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    s = _get(db, stocktake_id, lock=True)
    if s.created_by != user.id and user_role(user) not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the creator or a manager can cancel this stock-take")
    if s.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Stock-take is already {s.status}")
    s.status = "cancelled"
    audit(db, user, "cancel", "stocktake", s, None)
    db.commit()
    db.refresh(s)
    return _out(s)


@router.get("/{stocktake_id}/xlsx")
def sheet_xlsx(stocktake_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """Count sheet to print: the counted column is blank while open and filled in afterwards."""
    s = _get(db, stocktake_id)
    rows = [
        [
            ("text", l.sku or ""),
            ("text", l.product_name or ""),
            ("int", l.system_qty),
            ("text", "" if l.counted_qty is None else str(l.counted_qty)),
            ("text", "" if l.difference is None else f"{l.difference:+d}"),
        ]
        for l in s.lines
    ]
    scope = s.warehouse.name if s.warehouse else "كل المنتجات"
    content = exports.build_tables_xlsx(f"ورقة جرد #{s.id}", f"{scope} · {exports.fmt_dt(s.created_at)}", [("الجرد", ["الكود", "المنتج", "كمية النظام", "الكمية المعدودة", "الفرق"], rows)])
    return Response(
        content=content,
        media_type=exports.XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="stocktake-{s.id}.xlsx"', "Cache-Control": "no-store"},
    )
