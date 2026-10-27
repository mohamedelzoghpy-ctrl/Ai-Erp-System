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
        valuation=payload.valuation or "cost",
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
        if payload.valuation:
            t.valuation = payload.valuation
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
def delete_transfer(transfer_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    from ..deps import user_role
    t = _get(db, transfer_id)
    if t.status == "pending":
        if t.created_by != user.id and user_role(user) not in ("admin", "manager"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    elif t.status == "approved":
        if user_role(user) not in ("admin", "manager"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can delete an approved transfer")
        # reverse stock movement
        products = {p.id: p for p in db.query(models.Product).filter(models.Product.id.in_([i.product_id for i in t.items])).all()}
        ref = f"TR-{t.id}"
        for i in t.items:
            p = products.get(i.product_id)
            if p is None:
                continue
            try:
                stock.move_stock(db, p, t.from_warehouse_id, i.quantity, "transfer_delete_revert", ref)
                stock.move_stock(db, p, t.to_warehouse_id, -i.quantity, "transfer_delete_revert", ref)
            except Exception:
                pass
    else:  # rejected
        if user_role(user) not in ("admin", "manager"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can delete a rejected transfer")
    db.delete(t)
    audit(db, user, "delete", "stock_transfer", transfer_id, f"deleted {t.status} transfer")
    db.commit()


@router.put("/{transfer_id}/edit", response_model=schemas.TransferOut)
def edit_transfer(transfer_id: int, payload: schemas.TransferCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    from ..deps import user_role
    if user_role(user) not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can edit an approved transfer")
    t = _get(db, transfer_id)
    if t.status != "approved":
        raise HTTPException(409, f"Only approved transfers can be edited (current: {t.status})")
    if payload.from_warehouse_id == payload.to_warehouse_id:
        raise HTTPException(422, "Source and destination warehouses must differ")
    for wid in (payload.from_warehouse_id, payload.to_warehouse_id):
        w = db.get(models.Warehouse, wid)
        if w is None or not w.is_active:
            raise HTTPException(422, f"Warehouse {wid} is invalid or inactive")
    # merge new items
    new_wanted = {}
    for it in payload.items:
        new_wanted[it.product_id] = new_wanted.get(it.product_id, 0) + it.quantity
    # old items
    old_wanted = {}
    for i in t.items:
        old_wanted[i.product_id] = old_wanted.get(i.product_id, 0) + i.quantity

    # fetch products
    all_pids = sorted(set(new_wanted) | set(old_wanted))
    products = {}
    for pid in all_pids:
        p = db.query(models.Product).filter(models.Product.id == pid).with_for_update().one_or_none()
        if p is None:
            raise HTTPException(422, f"Product {pid} does not exist")
        products[pid] = p

    # validate stock for new items in NEW source warehouse
    new_src = payload.from_warehouse_id
    new_dst = payload.to_warehouse_id
    old_src = t.from_warehouse_id
    old_dst = t.to_warehouse_id
    shortages = []
    for pid, qty in new_wanted.items():
        # available = current + what we'll get back from reversing old (if same warehouse)
        base_avail = stock.available(db, pid, new_src)
        if old_src == new_src:
            base_avail += old_wanted.get(pid, 0)  # reversed back
        if base_avail < qty:
            shortages.append(stock.shortage_message(db, products[pid], new_src, qty))
    if shortages:
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + "; ".join(shortages))

    ref = f"TR-{t.id}"
    # reverse old movement
    for pid, qty in old_wanted.items():
        stock.move_stock(db, products[pid], old_src, qty, "transfer_edit_revert", ref)
        stock.move_stock(db, products[pid], old_dst, -qty, "transfer_edit_revert", ref)
    # apply new movement
    try:
        for pid, qty in new_wanted.items():
            stock.move_stock(db, products[pid], new_src, -qty, "transfer_edit", ref)
            stock.move_stock(db, products[pid], new_dst, qty, "transfer_edit", ref)
    except Exception:
        # restore old
        for pid, qty in new_wanted.items():
            try:
                stock.move_stock(db, products[pid], new_src, qty, "transfer_edit_revert", ref)
                stock.move_stock(db, products[pid], new_dst, -qty, "transfer_edit_revert", ref)
            except Exception:
                pass
        for pid, qty in old_wanted.items():
            try:
                stock.move_stock(db, products[pid], old_src, -qty, "transfer_edit", ref)
                stock.move_stock(db, products[pid], old_dst, qty, "transfer_edit", ref)
            except Exception:
                pass
        raise

    # update transfer
    t.from_warehouse_id = new_src
    t.to_warehouse_id = new_dst
    if payload.notes is not None:
        t.notes = payload.notes
    if payload.valuation:
        t.valuation = payload.valuation
    t.items.clear()
    db.flush()
    for pid, qty in new_wanted.items():
        t.items.append(models.StockTransferItem(product_id=pid, quantity=qty))
    audit(db, user, "update", "stock_transfer", t, f"edited after approval · {len(new_wanted)} صنف")
    db.commit()
    db.refresh(t)
    return t


@router.get("/{transfer_id}/pdf")
def transfer_pdf(transfer_id: int, db: Session = Depends(get_db)):
    t = _get(db, transfer_id)
    # enrich items with product prices for valuation
    pids = [i.product_id for i in t.items]
    products = {p.id: p for p in db.query(models.Product).filter(models.Product.id.in_(pids)).all()} if pids else {}
    use_sale = (t.valuation or "cost") == "sale"
    total_value = 0.0
    item_rows = []
    for i in t.items:
        p = products.get(i.product_id)
        price = float(p.sale_price if (use_sale and p) else (p.cost_price if p else 0))
        total_value += price * i.quantity
        item_rows.append({"sku": i.sku, "name": i.product_name, "quantity": i.quantity, "price": price})
    content = exports.build_transfer_pdf(
        {
            "id": t.id, "date": t.created_at, "from": t.from_warehouse_name, "to": t.to_warehouse_name, "notes": t.notes, "user": t.username,
            "valuation": t.valuation or "cost",
            "total_value": total_value,
            "items": item_rows,
        }
    )
    return Response(
        content=content,
        media_type=exports.PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="transfer-TR-{t.id}.pdf"', "Cache-Control": "no-store"},
    )
