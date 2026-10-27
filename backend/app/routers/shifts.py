"""Cashier shifts: open the drawer with a starting float, close it with a cash count.

Expected cash = opening cash + cash the user took in - cash the user paid out, between opening and closing
(receipts, supplier payments and cash refunds on returns recorded by that user). Closing freezes the figures.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import exports, models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, user_role
from ..pagination import paginate

router = APIRouter(prefix="/shifts", tags=["shifts"])
ZERO = Decimal("0")


def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else ZERO


def _sum(db: Session, col, *conds) -> Decimal:
    return _dec(db.query(func.coalesce(func.sum(col), 0)).filter(*conds).scalar())


STALE_HOURS = float(os.getenv("SHIFT_STALE_HOURS", "16"))


def stale_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=STALE_HOURS)


def _is_stale(s: models.Shift) -> bool:
    if s.status != "open":  # type: ignore
        return False
    opened = s.opened_at if s.opened_at.tzinfo else s.opened_at.replace(tzinfo=timezone.utc)  # SQLite drops the zone
    return opened < stale_cutoff()  # type: ignore


def _totals(db: Session, s: models.Shift) -> dict:
    """Live cash movements of the shift's user inside its time window."""
    P, SR, PR = models.Payment, models.SalesReturn, models.PurchaseReturn
    end = s.closed_at if s.closed_at is not None else func.now()

    def window(model):
        return (model.created_by == s.user_id, model.created_at >= s.opened_at, model.created_at <= end)

    receipts_cash = _sum(db, P.amount, *window(P), P.status == "posted", P.customer_id.isnot(None), P.method == "cash")
    receipts_other = _sum(db, P.amount, *window(P), P.status == "posted", P.customer_id.isnot(None), P.method != "cash")
    supplier_cash = _sum(db, P.amount, *window(P), P.status == "posted", P.supplier_id.isnot(None), P.method == "cash")
    sales_refunds = _sum(db, SR.refund_amount, *window(SR), SR.method == "cash")
    purchase_refunds = _sum(db, PR.refund_amount, *window(PR), PR.method == "cash")
    return {
        "cash_in": receipts_cash,
        "cash_out": supplier_cash,
        "cash_refunds_in": purchase_refunds,
        "cash_refunds_out": sales_refunds,
        "other_methods_in": receipts_other,
        "expected_cash": _dec(s.opening_cash) + receipts_cash + purchase_refunds - supplier_cash - sales_refunds,
    }


def _out(db: Session, s: models.Shift) -> schemas.ShiftOut:
    base = dict(
        id=s.id, user_id=s.user_id, username=s.username, status=s.status, opened_at=s.opened_at, closed_at=s.closed_at,
        opening_cash=s.opening_cash, counted_cash=s.counted_cash, difference=s.difference, notes=s.notes, is_stale=_is_stale(s),
    )
    if s.status == "closed":  # type: ignore
        # Shifts closed before refunds were split out have NULL refund columns (their cash_in/out already include them).
        return schemas.ShiftOut(
            **base, cash_in=s.cash_in, cash_out=s.cash_out, cash_refunds_in=s.cash_refunds_in or 0, cash_refunds_out=s.cash_refunds_out or 0,  # type: ignore
            other_methods_in=s.other_methods_in, expected_cash=s.expected_cash,  # type: ignore
        )
    return schemas.ShiftOut(**base, **_totals(db, s))


def open_shift_of(db: Session, user_id: int) -> Optional[models.Shift]:
    return db.query(models.Shift).filter(models.Shift.user_id == user_id, models.Shift.status == "open").first()


@router.get("/current", response_model=Optional[schemas.ShiftOut])
def current(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    s = open_shift_of(db, user.id)  # type: ignore
    return _out(db, s) if s else None


@router.post("/open", response_model=schemas.ShiftOut, status_code=status.HTTP_201_CREATED)
def open_shift(payload: schemas.ShiftOpen, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if open_shift_of(db, user.id):  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have an open shift")
    s = models.Shift(user_id=user.id, username=user.username, opening_cash=payload.opening_cash)  # type: ignore
    db.add(s)
    try:
        audit(db, user, "open", "shift", s, f"رصيد افتتاحي {payload.opening_cash}")
        db.commit()
    except Exception:  # unique index: a concurrent open request won
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have an open shift")
    db.refresh(s)
    return _out(db, s)


@router.post("/{shift_id}/close", response_model=schemas.ShiftOut)
def close_shift(shift_id: int, payload: schemas.ShiftClose, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    s = db.query(models.Shift).filter(models.Shift.id == shift_id).with_for_update().one_or_none()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Shift {shift_id} not found")
    if s.user_id != user.id and user_role(user) not in ("admin", "manager"):  # type: ignore
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the cashier or a manager can close this shift")
    if s.status != "open":  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "Shift is already closed")
    s.closed_at = datetime.now(timezone.utc)  # type: ignore
    s.closed_by = user.id
    t = _totals(db, s)
    s.cash_in, s.cash_out, s.other_methods_in, s.expected_cash = t["cash_in"], t["cash_out"], t["other_methods_in"], t["expected_cash"]
    s.cash_refunds_in, s.cash_refunds_out = t["cash_refunds_in"], t["cash_refunds_out"]
    s.counted_cash = payload.counted_cash  # type: ignore
    s.difference = payload.counted_cash - t["expected_cash"]
    s.notes = payload.notes  # type: ignore
    s.status = "closed"  # type: ignore
    audit(db, user, "close", "shift", s, f"متوقع {s.expected_cash} · معدود {s.counted_cash} · فرق {s.difference}")
    db.commit()
    db.refresh(s)
    return _out(db, s)


@router.get("", response_model=List[schemas.ShiftOut])
def list_shifts(
    response: Response,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.Shift)
    if user_role(user) not in ("admin", "manager"):
        q = q.filter(models.Shift.user_id == user.id)  # a cashier sees only their own shifts
    if status_filter:
        q = q.filter(models.Shift.status == status_filter)
    return [_out(db, s) for s in paginate(q, response, skip, limit, models.Shift.id.desc())]


@router.get("/{shift_id}/pdf")
def shift_pdf(shift_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    s = db.query(models.Shift).filter(models.Shift.id == shift_id).one_or_none()
    # Someone else's shift is reported as missing for cashiers, like the list endpoint hides it.
    if s is None or (s.user_id != user.id and user_role(user) not in ("admin", "manager")):  # type: ignore
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Shift {shift_id} not found")
    data = _out(db, s).model_dump()
    return Response(
        content=exports.build_shift_pdf(data),
        media_type=exports.PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="shift-{s.id}.pdf"', "Cache-Control": "no-store"},
    )
