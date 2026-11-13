"""Stock transfers between warehouses with an in-transit stage:
approval moves goods out of the source into a per-company transit warehouse,
receipt (partial or full) at the destination completes the move."""

from decimal import Decimal
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

TRANSIT_WAREHOUSE_NAME = "مخزن عابر (In-Transit)"
TRANSIT_WAREHOUSE_CODE = "TRANSIT"
IN_TRANSIT_ACC_CODE = "1103"  # مخزون تحت النقل
INVENTORY_ACC_CODE = "1101"


def _get(db: Session, transfer_id: int) -> models.StockTransfer:
    # Session.get يتجاوز فلتر العزل التلقائي — التصفية الصريحة بالشركة خط الدفاع (تدقيق 2026-11-14)
    company_id = db.info.get("company_id")
    t = (
        db.query(models.StockTransfer).filter(
            models.StockTransfer.id == transfer_id,
            models.StockTransfer.company_id == company_id,  # type: ignore[attr-defined]
        ).first()
        if company_id is not None
        else db.get(models.StockTransfer, transfer_id)
    )
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Transfer {transfer_id} not found")
    return t


def _get_locked(db: Session, transfer_id: int) -> models.StockTransfer:
    """Fetch the transfer with a row lock (SELECT ... FOR UPDATE) so concurrent
    approve/reject calls are serialized before the status is checked."""
    t = (
        db.query(models.StockTransfer)
        .filter(models.StockTransfer.id == transfer_id)
        .with_for_update()
        .first()
    )
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Transfer {transfer_id} not found")
    return t


def _transit_warehouse(db: Session) -> models.Warehouse:
    """المخزن العابر للشركة — يُنشأ آليًا عند أول اعتماد تحويل (وعاء «مخزون في الطريق»)."""
    company_id = db.info["company_id"]
    w = (
        db.query(models.Warehouse)
        .filter(models.Warehouse.company_id == company_id, models.Warehouse.is_transit.is_(True))
        .first()
    )
    if w is not None:
        return w
    branch_id = (
        db.query(models.Branch.id)
        .filter(models.Branch.company_id == company_id)
        .order_by(models.Branch.id)
        .limit(1)
        .scalar()
    )
    if branch_id is None:
        raise HTTPException(409, "لا يوجد فرع لإنشاء المخزن العابر")
    w = models.Warehouse(  # type: ignore
        company_id=company_id, name=TRANSIT_WAREHOUSE_NAME, code=TRANSIT_WAREHOUSE_CODE,
        branch_id=branch_id, is_active=True, is_transit=True,
    )
    db.add(w)
    db.flush()
    return w


def _in_transit_account(db: Session) -> models.ChartAccount:
    """حساب «مخزون تحت النقل» (1103) — يُنشأ آليًا للشركات القائمة (الـseed لا يعيد التهيئة)."""
    company_id = db.info["company_id"]
    acc = (
        db.query(models.ChartAccount)
        .filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == IN_TRANSIT_ACC_CODE)
        .first()
    )
    if acc is not None:
        return acc
    parent = (
        db.query(models.ChartAccount)
        .filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1100")
        .first()
    )
    if parent is None:
        raise HTTPException(409, "شجرة الحسابات غير مهيأة (1100 مفقود)")
    acc = models.ChartAccount(  # type: ignore
        company_id=company_id, name="مخزون تحت النقل (In-Transit)",
        code=IN_TRANSIT_ACC_CODE, type="asset", parent_id=parent.id, is_group=False,
    )
    db.add(acc)
    db.flush()
    return acc


def _booked_value(transfer: models.StockTransfer) -> Decimal:
    return stock.dec(transfer.booked_value)


def _value_share(transfer: models.StockTransfer, qty: Decimal) -> Decimal:
    """حصة كمية من القيمة الدفترية المحجوزة (يوازن حساب 1103 حتى يصفّر عند الاكتمال)."""
    total = sum((stock.dec(i.quantity) for i in transfer.items), Decimal("0"))
    if total <= 0 or _booked_value(transfer) <= 0:
        return Decimal("0")
    return (_booked_value(transfer) * qty / total).quantize(Decimal("0.01"))


@router.post("", response_model=schemas.TransferOut, status_code=status.HTTP_201_CREATED)
def create_transfer(payload: schemas.TransferCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if payload.from_warehouse_id == payload.to_warehouse_id:
        raise HTTPException(422, "Source and destination warehouses must differ")
    for wid in (payload.from_warehouse_id, payload.to_warehouse_id):
        w = db.get(models.Warehouse, wid)
        if w is None:
            raise HTTPException(422, f"Warehouse {wid} does not exist")
        if not w.is_active:  # type: ignore
            raise HTTPException(422, f"Warehouse '{w.name}' is inactive")
        if w.is_transit:  # type: ignore
            raise HTTPException(422, f"المخزن العابر '{w.name}' ليس مصدرًا أو هدفًا للتحويلات")
    wanted: dict = {}
    for it in payload.items:  # duplicate lines are merged so they are validated together
        wanted[it.product_id] = wanted.get(it.product_id, 0) + it.quantity

    transfer = models.StockTransfer(
        from_warehouse_id=payload.from_warehouse_id, to_warehouse_id=payload.to_warehouse_id,  # type: ignore
        notes=payload.notes, created_by=user.id, username=user.username, status="pending",  # type: ignore
        valuation=payload.valuation or "cost",  # type: ignore
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
        transfer.items.append(models.StockTransferItem(product_id=pid, quantity=qty))  # type: ignore
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
    t = _get_locked(db, transfer_id)
    if t.status != "pending":  # type: ignore
        raise HTTPException(409, f"Transfer is already {t.status}")
    # optional modification of items/warehouses/notes
    if payload is not None:
        if payload.from_warehouse_id != t.from_warehouse_id or payload.to_warehouse_id != t.to_warehouse_id:
            t.from_warehouse_id = payload.from_warehouse_id  # type: ignore
            t.to_warehouse_id = payload.to_warehouse_id  # type: ignore
        if payload.notes is not None:
            t.notes = payload.notes  # type: ignore
        if payload.valuation:
            t.valuation = payload.valuation  # type: ignore
        # replace items
        t.items.clear()
        db.flush()
        wanted = {}
        for it in payload.items:
            wanted[it.product_id] = wanted.get(it.product_id, 0) + it.quantity
        for pid, qty in wanted.items():
            t.items.append(models.StockTransferItem(product_id=pid, quantity=qty))  # type: ignore
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
        stock.shortage_message(db, products[pid], t.from_warehouse_id, qty)  # type: ignore
        for pid, qty in merged.items()
        if stock.available(db, pid, t.from_warehouse_id) < qty  # type: ignore
    ]
    if shortages:
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + "; ".join(shortages))
    ref = f"TR-{t.id}"
    # مرحلة النقل: الخروج من المصدر إلى المخزن العابر + قيد «مخزون تحت النقل» —
    # الاستلام في مخزن الهدف (جزئيًا أو كليًا) يكمل الحركة ويصفّر 1103 تدريجيًا
    from ..accounting import AccountingEngine
    transit = _transit_warehouse(db)
    transit_acc = _in_transit_account(db)
    inventory_acc = (
        db.query(models.ChartAccount)
        .filter(models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == INVENTORY_ACC_CODE)
        .first()
    )
    if inventory_acc is None:
        raise HTTPException(409, "حساب المخزون (1101) غير موجود — حدّث شجرة الحسابات")
    booked = Decimal("0")
    for pid, qty in merged.items():
        booked += (stock.dec(products[pid].cost_price) * qty).quantize(Decimal("0.01"))
        stock.move_stock(db, products[pid], t.from_warehouse_id, -qty, "transfer_out", ref, user_id=user.id)  # type: ignore
        stock.move_stock(db, products[pid], transit.id, qty, "transfer_in_transit", ref, user_id=user.id)  # type: ignore
    t.booked_value = booked  # type: ignore
    if booked > 0:
        AccountingEngine.create_entry(
            db=db,
            company_id=db.info["company_id"],
            user_id=user.id,
            description=f"تحويل مخزون TR-{t.id}: {t.from_warehouse_name} → {t.to_warehouse_name} (في الطريق)",
            items=[
                {"account_id": transit_acc.id, "debit": booked, "credit": 0},
                {"account_id": inventory_acc.id, "debit": 0, "credit": booked},
            ],
            reference=ref,
        )
    t.status = "in_transit"  # type: ignore
    t.approved_by = user.id
    from datetime import datetime, timezone
    t.approved_at = datetime.now(timezone.utc)  # type: ignore
    audit(db, user, "apply", "stock_transfer", t, f"approved · في الطريق · {len(merged)} صنف · قيمة {booked}")
    db.commit()
    db.refresh(t)
    return t


@router.post("/{transfer_id}/reject", response_model=schemas.TransferOut)
def reject_transfer(transfer_id: int, reason: Optional[str] = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    from ..deps import user_role
    if user_role(user) not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can reject transfers")
    t = _get_locked(db, transfer_id)
    if t.status != "pending":  # type: ignore
        raise HTTPException(409, f"Transfer is already {t.status}")
    t.status = "rejected"  # type: ignore
    t.rejection_reason = reason  # type: ignore
    t.approved_by = user.id
    from datetime import datetime, timezone
    t.approved_at = datetime.now(timezone.utc)  # type: ignore
    audit(db, user, "cancel", "stock_transfer", t, f"rejected: {reason or '—'}")
    db.commit()
    db.refresh(t)
    return t


@router.post("/{transfer_id}/receive", response_model=schemas.TransferOut)
def receive_transfer(
    transfer_id: int,
    payload: Optional[schemas.TransferReceiveIn] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """استلام تحويل عابر في مخزن الهدف (جزئيًا أو كليًا) — يكمل الحركة من المخزن العابر
    ويصرّف حصة الكمية المستلمة من «مخزون تحت النقل» (1103)."""
    t = _get_locked(db, transfer_id)
    if t.status != "in_transit":  # type: ignore
        raise HTTPException(409, f"الاستلام يتطلب تحويلًا في الطريق (الحالة: {t.status})")
    transit = _transit_warehouse(db)
    items_by_pid: dict = {}
    for it in t.items:
        items_by_pid.setdefault(it.product_id, []).append(it)
    wanted: dict = {}
    if payload is not None and payload.items:
        for ln in payload.items:
            wanted[ln.product_id] = wanted.get(ln.product_id, Decimal("0")) + stock.dec(ln.quantity)
    else:
        for it in t.items:
            wanted[it.product_id] = wanted.get(it.product_id, Decimal("0")) + (stock.dec(it.quantity) - stock.dec(it.received_quantity))
    wanted = {pid: q for pid, q in wanted.items() if q > 0}
    if not wanted:
        raise HTTPException(409, "لا كمية متبقية للاستلام")
    products: dict = {}
    for pid in sorted(wanted):
        lines = items_by_pid.get(pid)
        if not lines:
            raise HTTPException(422, f"الصنف {pid} ليس في التحويل")
        remaining = sum((stock.dec(i.quantity) - stock.dec(i.received_quantity) for i in lines), Decimal("0"))
        if wanted[pid] > remaining:
            raise HTTPException(409, f"الصنف {pid}: المتبقي في الطريق {remaining} فقط")
        products[pid] = _locked_product(db, pid)
        transit_qty = stock.available(db, pid, transit.id)
        if transit_qty < wanted[pid]:
            raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + stock.shortage_message(db, products[pid], transit.id, wanted[pid]))
    ref = f"TR-{t.id}"
    for pid, qty in wanted.items():
        stock.move_stock(db, products[pid], transit.id, -qty, "transfer_receipt", ref, user_id=user.id)
        stock.move_stock(db, products[pid], t.to_warehouse_id, qty, "transfer_in", ref, user_id=user.id)  # type: ignore
    # توزيع المُستلم على البنود بالترتيب
    left = dict(wanted)
    for it in t.items:
        qty = left.get(it.product_id, Decimal("0"))
        if qty <= 0:
            continue
        take = min(qty, stock.dec(it.quantity) - stock.dec(it.received_quantity))
        if take > 0:
            it.received_quantity = stock.dec(it.received_quantity) + take  # type: ignore
            left[it.product_id] = qty - take
    received_total = sum(wanted.values())
    value = _value_share(t, received_total)
    if value > 0:
        from ..accounting import AccountingEngine
        transit_acc = _in_transit_account(db)
        inventory_acc = (
            db.query(models.ChartAccount)
            .filter(models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == INVENTORY_ACC_CODE)
            .first()
        )
        if inventory_acc is None:
            raise HTTPException(409, "حساب المخزون (1101) غير موجود — حدّث شجرة الحسابات")
        AccountingEngine.create_entry(
            db=db,
            company_id=db.info["company_id"],
            user_id=user.id,
            description=f"استلام تحويل TR-{t.id} في {t.to_warehouse_name}",
            items=[
                {"account_id": inventory_acc.id, "debit": value, "credit": 0},
                {"account_id": transit_acc.id, "debit": 0, "credit": value},
            ],
            reference=ref,
        )
    fully = all(stock.dec(it.received_quantity) >= stock.dec(it.quantity) for it in t.items)
    t.status = "completed" if fully else "in_transit"  # type: ignore
    audit(db, user, "receive", "stock_transfer", t, f"استلام {received_total} بقيمة {value} — الحالة {t.status}")
    db.commit()
    db.refresh(t)
    return t


@router.post("/{transfer_id}/cancel", response_model=schemas.TransferOut)
def cancel_in_transit_transfer(transfer_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """إلغاء تحويل في الطريق: يُعيد الكمية المتبقية (غير المستلمة) إلى المخزن المصدر بقيد عكسي."""
    from ..deps import user_role
    if user_role(user) not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can cancel an in-transit transfer")
    t = _get_locked(db, transfer_id)
    if t.status != "in_transit":  # type: ignore
        raise HTTPException(409, f"الإلغاء يتطلب تحويلًا في الطريق (الحالة: {t.status})")
    transit = _transit_warehouse(db)
    remaining: dict = {}
    for it in t.items:
        rem = stock.dec(it.quantity) - stock.dec(it.received_quantity)
        if rem > 0:
            remaining[it.product_id] = remaining.get(it.product_id, Decimal("0")) + rem
    products: dict = {}
    for pid in sorted(remaining):
        p = _locked_product(db, pid)
        products[pid] = p
        transit_qty = stock.available(db, pid, transit.id)
        if transit_qty < remaining[pid]:
            raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + stock.shortage_message(db, p, transit.id, remaining[pid]))
    ref = f"TR-{t.id}"
    for pid, qty in remaining.items():
        stock.move_stock(db, products[pid], transit.id, -qty, "transfer_cancel", ref, user_id=user.id)
        stock.move_stock(db, products[pid], t.from_warehouse_id, qty, "transfer_cancel", ref, user_id=user.id)  # type: ignore
    value = _value_share(t, sum(remaining.values()))
    if value > 0:
        from ..accounting import AccountingEngine
        transit_acc = _in_transit_account(db)
        inventory_acc = (
            db.query(models.ChartAccount)
            .filter(models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == INVENTORY_ACC_CODE)
            .first()
        )
        if inventory_acc is None:
            raise HTTPException(409, "حساب المخزون (1101) غير موجود — حدّث شجرة الحسابات")
        AccountingEngine.create_entry(
            db=db,
            company_id=db.info["company_id"],
            user_id=user.id,
            description=f"إلغاء تحويل TR-{t.id}: عودة المتبقي إلى {t.from_warehouse_name}",
            items=[
                {"account_id": inventory_acc.id, "debit": value, "credit": 0},
                {"account_id": transit_acc.id, "debit": 0, "credit": value},
            ],
            reference=ref,
        )
    t.status = "cancelled"  # type: ignore
    audit(db, user, "cancel", "stock_transfer", t, f"إلغاء في الطريق — عودة {sum(remaining.values())} إلى المصدر")
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
    if t.status == "pending":  # type: ignore
        if t.created_by != user.id and user_role(user) not in ("admin", "manager"):  # type: ignore
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    elif t.status in ("approved", "completed"):  # type: ignore  # approved = بيانات قديمة سابقة للمرحلة العابرة
        if user_role(user) not in ("admin", "manager"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can delete a completed transfer")
        # reverse stock movement (القيد صفُر صافيًا — المصدر والهدف كلاهما 1101)
        products = {p.id: p for p in db.query(models.Product).filter(models.Product.id.in_([i.product_id for i in t.items])).all()}
        ref = f"TR-{t.id}"
        for i in t.items:
            p = products.get(i.product_id)
            if p is None:
                continue
            # كل الحركات في معاملة واحدة: أي فشل (مثلاً بيع جزء من الكمية في مخزن
            # الوصول) يرفع 409 ويُرجع المعاملة كاملة — لا حذف بديالة مخزنية ناقصة
            stock.move_stock(db, p, t.from_warehouse_id, i.quantity, "transfer_delete_revert", ref)  # type: ignore
            stock.move_stock(db, p, t.to_warehouse_id, -i.quantity, "transfer_delete_revert", ref)  # type: ignore
    elif t.status == "in_transit":  # type: ignore
        if user_role(user) not in ("admin", "manager"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can delete an in-transit transfer")
        if any(stock.dec(i.received_quantity) > 0 for i in t.items):  # type: ignore
            raise HTTPException(409, "لا يمكن حذف تحويل استُلم منه جزئيًا — ألغِ المتبقي (إلغاء) أو أكمل الاستلام")
        # عودة كل الكمية من العابر إلى المصدر بقيد عكسي ثم الحذف
        transit = _transit_warehouse(db)
        remaining: dict = {}
        for it in t.items:
            rem = stock.dec(it.quantity) - stock.dec(it.received_quantity)
            if rem > 0:
                remaining[it.product_id] = remaining.get(it.product_id, Decimal("0")) + rem
        ref = f"TR-{t.id}"
        for pid, qty in remaining.items():
            p = _locked_product(db, pid)
            stock.move_stock(db, p, transit.id, -qty, "transfer_delete_revert", ref, user_id=user.id)
            stock.move_stock(db, p, t.from_warehouse_id, qty, "transfer_delete_revert", ref, user_id=user.id)  # type: ignore
        value = _value_share(t, sum(remaining.values()))
        if value > 0:
            from ..accounting import AccountingEngine
            transit_acc = _in_transit_account(db)
            inventory_acc = (
                db.query(models.ChartAccount)
                .filter(models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == INVENTORY_ACC_CODE)
                .first()
            )
            AccountingEngine.create_entry(
                db=db,
                company_id=db.info["company_id"],
                user_id=user.id,
                description=f"حذف تحويل TR-{t.id}: عودة المتبقي إلى {t.from_warehouse_name}",
                items=[
                    {"account_id": inventory_acc.id, "debit": value, "credit": 0},
                    {"account_id": transit_acc.id, "debit": 0, "credit": value},
                ],
                reference=ref,
            )
    else:  # rejected / cancelled
        if user_role(user) not in ("admin", "manager"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can delete a rejected transfer")
    db.delete(t)
    audit(db, user, "delete", "stock_transfer", transfer_id, f"deleted {t.status} transfer")
    db.commit()


@router.put("/{transfer_id}/edit", response_model=schemas.TransferOut)
def edit_transfer(transfer_id: int, payload: schemas.TransferCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    from ..deps import user_role
    if user_role(user) not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can edit an in-transit transfer")
    t = _get(db, transfer_id)
    if t.status != "in_transit":  # type: ignore
        raise HTTPException(409, f"Only in-transit transfers can be edited (current: {t.status})")
    if any(stock.dec(i.received_quantity) > 0 for i in t.items):  # type: ignore
        raise HTTPException(409, "لا يمكن تعديل تحويل استُلم منه جزئيًا")
    if payload.from_warehouse_id == payload.to_warehouse_id:
        raise HTTPException(422, "Source and destination warehouses must differ")
    for wid in (payload.from_warehouse_id, payload.to_warehouse_id):
        w = db.get(models.Warehouse, wid)
        if w is None or not w.is_active:  # type: ignore
            raise HTTPException(422, f"Warehouse {wid} is invalid or inactive")
        if w.is_transit:  # type: ignore
            raise HTTPException(422, f"المخزن العابر '{w.name}' ليس مصدرًا أو هدفًا للتحويلات")
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
    transit = _transit_warehouse(db)
    shortages = []
    for pid, qty in new_wanted.items():
        # available = current + what we'll get back from reversing old (if same warehouse)
        base_avail = stock.available(db, pid, new_src)
        if old_src == new_src:  # type: ignore
            base_avail += old_wanted.get(pid, 0)  # reversed back
        if base_avail < qty:
            shortages.append(stock.shortage_message(db, products[pid], new_src, qty))
    if shortages:
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock: " + "; ".join(shortages))

    ref = f"TR-{t.id}"
    # عكس مرحلة النقل القديمة: العابر يعود إلى المصدر القديم + تصفير حصة 1103
    old_booked = _booked_value(t)
    for pid, qty in old_wanted.items():
        stock.move_stock(db, products[pid], transit.id, -qty, "transfer_edit_revert", ref)  # type: ignore
        stock.move_stock(db, products[pid], old_src, qty, "transfer_edit_revert", ref)  # type: ignore
    # apply new movement — كل الحركات (عكس القديم + تطبيق الجديد) معاملة واحدة:
    # أي فشل يرفع 409 ويُرجع كل شيء ذريًا، فلا حاجة لتراجع يدوي يبتلع الأخطاء
    new_booked = Decimal("0")
    for pid, qty in new_wanted.items():
        new_booked += (stock.dec(products[pid].cost_price) * Decimal(str(qty))).quantize(Decimal("0.01"))
        stock.move_stock(db, products[pid], new_src, -Decimal(str(qty)), "transfer_edit", ref)
        stock.move_stock(db, products[pid], transit.id, Decimal(str(qty)), "transfer_edit", ref)

    # قيدا العكس وإعادة الحجز (صافي الفرق بين القيمتين على 1103)
    if old_booked > 0 or new_booked > 0:
        from ..accounting import AccountingEngine
        transit_acc = _in_transit_account(db)
        inventory_acc = (
            db.query(models.ChartAccount)
            .filter(models.ChartAccount.company_id == db.info["company_id"], models.ChartAccount.code == INVENTORY_ACC_CODE)
            .first()
        )
        if inventory_acc is None:
            raise HTTPException(409, "حساب المخزون (1101) غير موجود — حدّث شجرة الحسابات")
        delta = new_booked - old_booked
        AccountingEngine.create_entry(
            db=db,
            company_id=db.info["company_id"],
            user_id=user.id,
            description=f"تعديل تحويل TR-{t.id} في الطريق",
            items=[
                {"account_id": transit_acc.id, "debit": max(delta, Decimal("0")), "credit": max(-delta, Decimal("0"))},
                {"account_id": inventory_acc.id, "debit": max(-delta, Decimal("0")), "credit": max(delta, Decimal("0"))},
            ],
            reference=ref,
        )

    # update transfer
    t.from_warehouse_id = new_src  # type: ignore
    t.to_warehouse_id = new_dst  # type: ignore
    t.booked_value = new_booked  # type: ignore
    if payload.notes is not None:
        t.notes = payload.notes  # type: ignore
    if payload.valuation:
        t.valuation = payload.valuation  # type: ignore
    t.items.clear()
    db.flush()
    for pid, qty in new_wanted.items():
        t.items.append(models.StockTransferItem(product_id=pid, quantity=qty))  # type: ignore
    audit(db, user, "update", "stock_transfer", t, f"edited in transit · {len(new_wanted)} صنف")
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
        price = float(p.sale_price if (use_sale and p) else (p.cost_price if p else 0))  # type: ignore
        total_value += price * float(i.quantity)  # الكمية Decimal والسعر float — نوحّد النوع
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
