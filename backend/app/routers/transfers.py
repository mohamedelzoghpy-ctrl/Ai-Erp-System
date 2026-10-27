"""Stock transfers between warehouses: one document moves several products atomically (out of one, into the other)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from .. import exports, models, schemas, stock
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user
from ..pagination import paginate
from .orders import _locked_product

router = APIRouter(prefix="/stock-transfers", tags=["stock-transfers"])


def _get(db: Session, transfer_id: int) -> models.StockTransfer:
    t = db.get(models.StockTransfer, transfer_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Transfer {transfer_id} not found")
    return t


@router.post("", response_model=schemas.TransferOut, status_code=status.HTTP_201_CREATED)
def create_transfer(payload: schemas.TransferCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if payload.from_warehouse_id == payload.to_warehouse_id:
        raise HTTPException(422, "Source and destination warehouses must differ")
    for wid in (payload.from_warehouse_id, payload.to_warehouse_id):
        w = db.get(models.Warehouse, wid)
        if w is None:
            raise HTTPException(422, f"Warehouse {wid} does not exist")
        if not w.is_active:
            raise HTTPException(422, f"Warehouse '{w.name}' is inactive")
    wanted: dict = {}
    for it in payload.items:  # duplicate lines are merged so they are validated together
        wanted[it.product_id] = wanted.get(it.product_id, 0) + it.quantity

    transfer = models.StockTransfer(
        from_warehouse_id=payload.from_warehouse_id, to_warehouse_id=payload.to_warehouse_id,
        notes=payload.notes, created_by=user.id, username=user.username, status="pending",
    )
    db.add(transfer)
    db.flush()  # the id is the movement reference

    products = {}
    for pid in sorted(wanted):  # fixed lock order: concurrent transfers cannot deadlock
        p = db.query(models.Product).filter(models.Product.id == pid).with_for_update().one_or_none()
        if p is None:
            db.rollback()
            raise HTTPException(422, f"Product {pid} does not exist")
        products[pid] = p
    shortages = [
        stock.shortage_message(db, products[pid], payload.from_warehouse_id, qty)
        for pid, qty in wanted.items()
        if stock.available(db, pid, payload.from_warehouse_id) < qty
    ]
    if shortages:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + "; ".join(shortages))

    ref = f"TR-{transfer.id}"
    for pid, qty in wanted.items():
        transfer.items.append(models.StockTransferItem(product_id=pid, quantity=qty))
    audit(db, user, "create", "stock_transfer", transfer, f"{len(wanted)} صنف · {payload.from_warehouse_id}→{payload.to_warehouse_id} (pending)")
    db.commit()
    db.refresh(transfer)
    return transfer


@router.get("", response_model=List[schemas.TransferOut])
def list_transfers(
    response: Response,
    warehouse_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """`warehouse_id` matches transfers going out of or into that warehouse."""
    q = db.query(models.StockTransfer).options(joinedload(models.StockTransfer.items))
    if warehouse_id is not None:
        q = q.filter((models.StockTransfer.from_warehouse_id == warehouse_id) | (models.StockTransfer.to_warehouse_id == warehouse_id))
    if status:
        q = q.filter(models.StockTransfer.status == status)
    return paginate(q, response, skip, limit, models.StockTransfer.id.desc())


@router.get("/pending-count")
def pending_count(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    # Only managers/admins care; non-managers get 0
    from ..deps import user_role
    if user_role(user) not in ("admin", "manager"):
        return {"count": 0}
    n = db.query(models.StockTransfer).filter(models.StockTransfer.status == "pending").count()
    return {"count": n}


@router.post("/{transfer_id}/approve", response_model=schemas.TransferOut)
def approve_transfer(transfer_id: int, payload: Optional[schemas.TransferCreate] = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    from ..deps import require_manager, user_role
    if user_role(user) not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can approve transfers")
    t = _get(db, transfer_id)
    if t.status != "pending":
        raise HTTPException(409, f"Transfer is already {t.status}")
    # optional modification of items/warehouses/notes
    if payload is not None:
        if payload.from_warehouse_id != t.from_warehouse_id or payload.to_warehouse_id != t.to_warehouse_id:
            t.from_warehouse_id = payload.from_warehouse_id
            t.to_warehouse_id = payload.to_warehouse_id
        if payload.notes is not None:
            t.notes = payload.notes
        # replace items
        t.items.clear()
        db.flush()
        wanted = {}
        for it in payload.items:
            wanted[it.product_id] = wanted.get(it.product_id, 0) + it.quantity
        for pid, qty in wanted.items():
            t.items.append(models.StockTransferItem(product_id=pid, quantity=qty))
    # validate stock
    products = {}
    wanted = {i.product_id: i.quantity for i in t.items}
    # merge duplicates
    merged = {}
    for pid, q in wanted.items():
        merged[pid] = merged.get(pid, 0) + q
    for pid in sorted(merged):
        p = db.query(models.Product).filter(models.Product.id == pid).with_for_update().one_or_none()
        if p is None:
            raise HTTPException(422, f"Product {pid} does not exist")
        products[pid] = p
    shortages = [
        stock.shortage_message(db, products[pid], t.from_warehouse_id, qty)
        for pid, qty in merged.items()
        if stock.available(db, pid, t.from_warehouse_id) < qty
    ]
    if shortages:
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + "; ".join(shortages))
    ref = f"TR-{t.id}"
    for pid, qty in merged.items():
        stock.move_stock(db, products[pid], t.from_warehouse_id, -qty, "transfer_out", ref)
        stock.move_stock(db, products[pid], t.to_warehouse_id, qty, "transfer_in", ref)
    t.status = "approved"
    t.approved_by = user.id
    from datetime import datetime, timezone
    t.approved_at = datetime.now(timezone.utc)
    audit(db, user, "apply", "stock_transfer", t, f"approved · {len(merged)} صنف")
    db.commit()
    db.refresh(t)
    return t


@router.post("/{transfer_id}/reject", response_model=schemas.TransferOut)
def reject_transfer(transfer_id: int, reason: Optional[str] = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    from ..deps import user_role
    if user_role(user) not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can reject transfers")
    t = _get(db, transfer_id)
    if t.status != "pending":
        raise HTTPException(409, f"Transfer is already {t.status}")
    t.status = "rejected"
    t.rejection_reason = reason
    t.approved_by = user.id
    from datetime import datetime, timezone
    t.approved_at = datetime.now(timezone.utc)
    audit(db, user, "cancel", "stock_transfer", t, f"rejected: {reason or '—'}")
    db.commit()
    db.refresh(t)
    return t


@router.get("/{transfer_id}", response_model=schemas.TransferOut)
def get_transfer(transfer_id: int, db: Session = Depends(get_db)):
    return _get(db, transfer_id)


@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pending_transfer(transfer_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    from ..deps import user_role
    t = _get(db, transfer_id)
    if t.status != "pending":
        raise HTTPException(409, "Only pending transfers can be deleted")
    if t.created_by != user.id and user_role(user) not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    db.delete(t)
    audit(db, user, "delete", "stock_transfer", transfer_id, "deleted pending transfer")
    db.commit()


@router.get("/{transfer_id}/pdf")
def transfer_pdf(transfer_id: int, db: Session = Depends(get_db)):
    t = _get(db, transfer_id)
    content = exports.build_transfer_pdf(
        {
            "id": t.id, "date": t.created_at, "from": t.from_warehouse_name, "to": t.to_warehouse_name, "notes": t.notes, "user": t.username,
            "items": [{"sku": i.sku, "name": i.product_name, "quantity": i.quantity} for i in t.items],
        }
    )
    return Response(
        content=content,
        media_type=exports.PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="transfer-TR-{t.id}.pdf"', "Cache-Control": "no-store"},
    )
