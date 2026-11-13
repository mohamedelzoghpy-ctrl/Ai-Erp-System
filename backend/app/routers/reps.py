"""Company-scoped sales reps (مندوبي المبيعات): list / create / update / delete."""

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(prefix="/reps", tags=["reps"])


def _rep_query(db: Session, company_id: int):
    return db.query(models.SalesRep).filter(models.SalesRep.company_id == company_id)


@router.get("", response_model=List[schemas.SalesRepOut])
def list_reps(
    active_only: bool = False,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = _rep_query(db, db.info["company_id"])
    if active_only:
        q = q.filter(models.SalesRep.is_active.is_(True))
    if search:
        s = f"%{search.strip()}%"
        q = q.filter((models.SalesRep.name.ilike(s)) | (models.SalesRep.code.ilike(s)) | (models.SalesRep.phone.ilike(s)))
    RBA, RA = models.SalesRepBranchAccess, models.SalesRep
    branch_map: dict = {}
    for rid, bid in db.query(RBA.rep_id, RBA.branch_id).join(RA, RA.id == RBA.rep_id).filter(RA.company_id == db.info["company_id"]).all():
        branch_map.setdefault(rid, []).append(bid)
    out = []
    for r in q.order_by(RA.id).all():
        item = schemas.SalesRepOut.model_validate(r)
        item.branch_ids = branch_map.get(r.id, [])  # type: ignore[union-attr]
        if r.user_id:
            item.user_id = r.user_id  # type: ignore[union-attr]
            linked = db.get(models.User, r.user_id)
            if linked is not None:
                item.username = linked.username  # type: ignore[union-attr]
        out.append(item)
    return out


def _assign_branches(db: Session, rep: models.SalesRep, company_id: int, branch_ids: List[int]) -> None:
    if not branch_ids:
        unique_ids = []
    else:
        unique_ids = sorted(set(branch_ids))
        valid = (
            db.query(models.Branch.id)
            .filter(models.Branch.company_id == company_id, models.Branch.id.in_(unique_ids))
            .all()
        )
        if len(valid) != len(unique_ids):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "فرع غير موجود في هذه الشركة")
    # Replace access rows explicitly (avoid unique violations on re-assignment)
    db.query(models.SalesRepBranchAccess).filter(models.SalesRepBranchAccess.rep_id == rep.id).delete(synchronize_session=False)
    for bid in unique_ids:
        db.add(models.SalesRepBranchAccess(rep_id=rep.id, branch_id=bid))


@router.post("", response_model=schemas.SalesRepOut, status_code=status.HTTP_201_CREATED)
def create_rep(
    payload: schemas.SalesRepCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    name = payload.name.strip()
    code = (payload.code or "").strip() or unique_code(db, models.SalesRep, company_id, name, "REP")
    if _rep_query(db, company_id).filter(
        (models.SalesRep.code == code) | (models.SalesRep.name == name)
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "اسم المندوب أو الكود مستخدم بالفعل")
    rep = models.SalesRep(
        company_id=company_id,
        name=name,
        code=code,
        phone=payload.phone.strip() if payload.phone else None,
        commission_percent=payload.commission_percent,
        is_active=payload.is_active,
    )
    db.add(rep)
    db.flush()
    _assign_branches(db, rep, company_id, payload.branch_ids)
    db.commit()
    db.refresh(rep)
    audit(db, user, "create", "sales_rep", rep, f"{rep.code}: {rep.name}")
    return _rep_out(db, rep)


def _rep_out(db: Session, rep: models.SalesRep) -> schemas.SalesRepOut:
    item = schemas.SalesRepOut.model_validate(rep)
    item.branch_ids = [a.branch_id for a in rep.branch_access]  # type: ignore[union-attr]
    if rep.user_id:
        item.user_id = rep.user_id  # type: ignore[union-attr]
        linked = db.get(models.User, rep.user_id)
        if linked is not None:
            item.username = linked.username  # type: ignore[union-attr]
    return item


@router.patch("/{rep_id}", response_model=schemas.SalesRepOut)
def update_rep(
    rep_id: int,
    payload: schemas.SalesRepUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    rep = _rep_query(db, db.info["company_id"]).filter(models.SalesRep.id == rep_id).one_or_none()
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sales rep {rep_id} not found")
    if "name" in payload.model_dump(exclude_unset=True):
        data = payload.model_dump(exclude_unset=True)
        new_name = (data["name"] or "").strip()
        if new_name and new_name != rep.name and _rep_query(db, db.info["company_id"]).filter(models.SalesRep.name == new_name).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "اسم المندوب مستخدم بالفعل")
    data = payload.model_dump(exclude_unset=True)
    if "phone" in data and data["phone"] is not None:
        data["phone"] = data["phone"].strip() or None
    data.pop("branch_ids", None)
    changed = list(data)
    for key, value in data.items():
        setattr(rep, key, value)
    if payload.branch_ids is not None:
        _assign_branches(db, rep, db.info["company_id"], payload.branch_ids)
        changed.append("branch_ids")
    audit(db, user, "update", "sales_rep", rep, f"{rep.code}: " + "، ".join(changed))
    db.commit()
    db.refresh(rep)
    return _rep_out(db, rep)


@router.delete("/{rep_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rep(
    rep_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    rep = _rep_query(db, db.info["company_id"]).filter(models.SalesRep.id == rep_id).one_or_none()
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sales rep {rep_id} not found")
    code, name = rep.code, rep.name
    db.delete(rep)
    audit(db, user, "delete", "sales_rep", None, f"deleted {code} ({name})")
    db.commit()
    return None


# ================================================================ تطبيق المندوبين
from fastapi import Body  # noqa: E402
from ..security import hash_password  # noqa: E402
from ..deps import get_current_user  # noqa: E402
from ..accounting import local_today  # noqa: E402
from sqlalchemy import func as _func  # noqa: E402
from datetime import timedelta as _td  # noqa: E402


def _rep_for_user(db, user) -> "models.SalesRep":
    rep = db.query(models.SalesRep).filter(
        models.SalesRep.company_id == db.info["company_id"],
        models.SalesRep.user_id == user.id,
        models.SalesRep.is_active.is_(True),
    ).first()
    if rep is None:
        raise HTTPException(403, "هذا الحساب غير مرتبط بمندوب — اطلب من الإدارة الربط")
    return rep


@router.put("/{rep_id}/link-user", status_code=200)
def link_rep_user(
    rep_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """ربط المندوب بحساب دخول لتطبيق الموبايل: ينشئ مستخدم staff بصلاحيات البيع
    (أو يربط مستخدمًا قائمًا بالاسم) ويعيد بيانات الدخول مرة واحدة."""
    rep = _rep_query(db, db.info["company_id"]).filter(models.SalesRep.id == rep_id).first()
    if rep is None:
        raise HTTPException(404, "المندوب غير موجود")
    if rep.user_id is not None and not payload.get("force"):
        raise HTTPException(409, "المندوب مرتبط بحساب بالفعل (force=true لإعادة الربط)")
    username = str(payload.get("username") or "").strip().lower()
    password = str(payload.get("password") or "")
    if not (username and len(password) >= 8):
        raise HTTPException(422, "اسم مستخدم وكلمة سر (8+ أحرف) مطلوبان")
    existing_user = db.query(models.User).filter(models.User.username == username).first()
    if existing_user is not None:
        if existing_user.is_platform_admin:  # type: ignore
            raise HTTPException(403, "لا يمكن ربط مدير المنصة بمندوب")
        # فك أي ربط سابق لنفس المستخدم ثم اربطه
        db.query(models.SalesRep).filter(models.SalesRep.user_id == existing_user.id).update({"user_id": None})
        target = existing_user
        created = False
    else:
        branch_ids = payload.get("branch_ids") or []
        target = models.User(username=username, full_name=rep.name,
                             hashed_password=hash_password(password), role="staff")
        db.add(target)
        db.flush()
        company_id = db.info["company_id"]
        # عضوية الشركة + شركة نشطة — شرطا الدخول عبر get_current_user
        db.add(models.UserCompanyMembership(user_id=target.id, company_id=company_id, role="staff"))
        target.active_company_id = company_id  # type: ignore
        # المندوب ميدانيه كل الشركة: يُمنح كل الفروع والمخازن النشطة — بدونها يقصّه
        # فلتر نطاق الموظف (database.py) ولا يرى مخزناً ولا أوامر إطلاقاً
        from sqlalchemy import select as _select
        active_branch_ids = db.execute(
            _select(models.Branch.id).where(
                models.Branch.company_id == company_id, models.Branch.is_active.is_(True)
            ).execution_options(ignore_tenant_scope=True)
        ).scalars().all()
        active_warehouse_ids = db.execute(
            _select(models.Warehouse.id).where(
                models.Warehouse.company_id == company_id, models.Warehouse.is_active.is_(True)
            ).execution_options(ignore_tenant_scope=True)
        ).scalars().all()
        for bid in (branch_ids or list(active_branch_ids)):
            db.add(models.UserBranchAccess(user_id=target.id, branch_id=bid))
        for wid in active_warehouse_ids:
            db.add(models.UserWarehouseAccess(user_id=target.id, warehouse_id=wid))
        created = True
    rep.user_id = target.id  # type: ignore
    audit(db, user, "update", "sales_rep", rep,
          f"ربط حساب دخول للتطبيق: {username}{' (جديد)' if created else ' (قائم)'}")
    db.commit()
    return {"rep_id": rep.id, "username": username, "created": created,
            "note": "أدخل هذه البيانات في تطبيق المندوب"}


@router.get("/me")
def me_profile(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    rep = _rep_for_user(db, user)
    return {
        "rep_id": rep.id, "name": rep.name, "code": rep.code, "phone": rep.phone,
        "commission_percent": rep.commission_percent,
    }


@router.get("/me/customers")
def me_customers(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """عملاء الشركة كما يراهم المندوب: الرصيد + الحد الائتماني + قائمة أسعار كل عميل."""
    from ..accounts import party_balances
    rep = _rep_for_user(db, user)
    customers = db.query(models.Customer).filter(
        models.Customer.company_id == db.info["company_id"], models.Customer.is_active.is_(True)
    ).order_by(models.Customer.name).all()
    balances = party_balances(db, "customer", [c.id for c in customers] or [0])
    lists = {pl.id: pl.name for pl in db.query(models.PriceList).filter(
        models.PriceList.company_id == db.info["company_id"]).all()}
    return [{
        "id": c.id, "name": c.name, "phone": c.phone, "code": c.code,
        "balance": balances.get(c.id, 0),
        "credit_limit": c.credit_limit,
        "price_list_id": c.price_list_id,
        "price_list_name": lists.get(c.price_list_id) if c.price_list_id else None,
    } for c in customers]


@router.get("/me/summary")
def me_summary(
    days: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """ملخص اليوم والشهر للمندوب: فواتير اليوم، تحصيلات اليوم، عمولة الفترة."""
    from ..accounts import party_balances
    rep = _rep_for_user(db, user)
    from ..accounting import local_today
    from ..exports import LOCAL_TZ
    from datetime import datetime as _dt, time as _time, timezone as _tz
    today = local_today()
    # حدود اليوم/الفترة بالتوقيت المحلي محوّلة إلى UTC ساذج — تطابق ما يخزنه السيرفر
    day_start_local = _dt.combine(today, _time.min, tzinfo=LOCAL_TZ)
    today_start_u = day_start_local.astimezone(_tz.utc).replace(tzinfo=None)
    today_end_u = (day_start_local + _td(days=1)).astimezone(_tz.utc).replace(tzinfo=None)
    period_start_u = (day_start_local - _td(days=days - 1)).astimezone(_tz.utc).replace(tzinfo=None)

    SO = models.SalesOrder
    # بيانات المندوب الخاصة به: مفلترة صراحةً بـ company_id و rep_id، فتتجاوز
    # نطاق الفروع (المندوب الميداني يرى أوامره حتى لو صُرفت من مخزن خارج فرعه).
    orders_today = db.query(_func.count(SO.id), _func.coalesce(_func.sum(SO.total_amount), 0)).filter(
        SO.company_id == db.info["company_id"], SO.rep_id == rep.id,
        SO.status == "confirmed",
        SO.updated_at >= today_start_u, SO.updated_at < today_end_u,
    ).execution_options(ignore_tenant_scope=True).one()
    P = models.Payment
    collected_today = db.query(_func.coalesce(_func.sum(P.amount), 0)).filter(
        P.company_id == db.info["company_id"], P.status == "posted",
        P.created_by == user.id,
        P.created_at >= today_start_u, P.created_at < today_end_u,
    ).execution_options(ignore_tenant_scope=True).scalar() or 0
    gross = db.query(_func.coalesce(_func.sum(SO.total_amount), 0)).filter(
        SO.company_id == db.info["company_id"], SO.rep_id == rep.id,
        SO.status == "confirmed", SO.updated_at >= period_start_u,
    ).execution_options(ignore_tenant_scope=True).scalar() or 0
    SR = models.SalesReturn
    returns_val = db.query(_func.coalesce(_func.sum(SR.total_amount - SR.refund_amount), 0)).filter(
        SR.company_id == db.info["company_id"], SR.rep_id == rep.id,
        SR.created_at >= period_start_u,
    ).execution_options(ignore_tenant_scope=True).scalar() or 0
    net = float(gross) - float(returns_val)
    return {
        "today_orders": orders_today[0] or 0,
        "today_sales": float(orders_today[1] or 0),
        "today_collected": float(collected_today),
        "period_days": days,
        "period_gross": float(gross),
        "period_returns": float(returns_val),
        "period_net": net,
        "commission_percent": float(rep.commission_percent or 0),
        "period_commission": round(net * float(rep.commission_percent or 0) / 100.0, 2),
    }


@router.get("/me/notifications")
def me_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    rep = _rep_for_user(db, user)
    q = db.query(models.RepNotification).filter(models.RepNotification.rep_id == rep.id)
    if unread_only:
        q = q.filter(models.RepNotification.read_at.is_(None))
    rows = q.order_by(models.RepNotification.id.desc()).limit(100).all()
    return [{
        "id": n.id, "kind": n.kind, "title": n.title, "body": n.body,
        "ref_id": n.ref_id, "read": n.read_at is not None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    } for n in rows]


@router.post("/me/notifications/{notification_id}/read", status_code=204)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    rep = _rep_for_user(db, user)
    n = db.query(models.RepNotification).filter(
        models.RepNotification.id == notification_id, models.RepNotification.rep_id == rep.id
    ).first()
    if n is None:
        raise HTTPException(404, "التنبيه غير موجود")
    if n.read_at is None:
        from datetime import datetime as _dt, timezone as _tz
        n.read_at = _dt.now(_tz.utc)
        db.commit()
    return None


class DeviceIn(BaseModel):
    fcm_token: str = Field(min_length=20, max_length=255)
    platform: str = Field(default="android", pattern="^(android|ios)$")


@router.post("/me/devices", status_code=201)
def register_device(
    payload: DeviceIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تسجيل/تجديد جهاز المندوب (توكن FCM) — idempotent لكل (مندوب، توكن)."""
    rep = _rep_for_user(db, user)
    dev = db.query(models.RepDevice).filter(
        models.RepDevice.rep_id == rep.id, models.RepDevice.fcm_token == payload.fcm_token
    ).first()
    if dev is None:
        dev = models.RepDevice(company_id=db.info["company_id"], rep_id=rep.id,
                               fcm_token=payload.fcm_token, platform=payload.platform)
        db.add(dev)
    dev.platform = payload.platform  # type: ignore
    from datetime import datetime as _dt, timezone as _tz
    dev.last_seen_at = _dt.now(_tz.utc)  # type: ignore
    db.commit()
    return {"device_id": dev.id, "registered": True}


class RepCollectionIn(BaseModel):
    """تحصيل ميداني من عميل — نقدية فقط في الإصدار الأول."""
    customer_id: int
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    safe_id: Optional[int] = None  # اختياري — الافتراضي: خزينة فاتورة العميل الأخيرة ثم أول خزينة نشطة
    notes: Optional[str] = Field(default=None, max_length=255)


@router.post("/me/collections", status_code=201)
def me_create_collection(
    payload: RepCollectionIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تحصيل نقدي من عميل عبر التطبيق — سند قبض رسمي عبر مسار السندات الكامل
    (قيود مزدوجة، رصيد خزينة، إشعار المندوب) — لا مسار جانبي للنقدية."""
    rep = _rep_for_user(db, user)
    company_id = db.info["company_id"]
    customer = db.get(models.Customer, payload.customer_id)
    if customer is None or customer.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العميل غير موجود")

    safe_id = payload.safe_id
    if safe_id is not None:
        safe = db.get(models.Safe, safe_id)
        if safe is None or safe.company_id != company_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الخزينة غير موجودة")
    else:
        # الافتراضي: خزينة فاتورة العميل الأخيرة المؤكدة، ثم أول خزينة نشطة بالشركة
        last_order = (
            db.query(models.SalesOrder)
            .filter(
                models.SalesOrder.company_id == company_id,
                models.SalesOrder.customer_id == payload.customer_id,
                models.SalesOrder.status == "confirmed",
                models.SalesOrder.safe_id.isnot(None),
            )
            .order_by(models.SalesOrder.id.desc())
            .first()
        )
        if last_order is not None and last_order.safe_id is not None:
            safe_id = last_order.safe_id
        else:
            first_safe = (
                db.query(models.Safe)
                .filter(models.Safe.company_id == company_id, models.Safe.is_active.is_(True))
                .order_by(models.Safe.id)
                .first()
            )
            safe_id = first_safe.id if first_safe else None
    if safe_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "لا خزينة متاحة للتحصيل — أنشئ خزينة أو حدد واحدة")

    from .payments import create_payment

    payment = create_payment(
        schemas.PaymentCreate(
            customer_id=payload.customer_id,
            amount=Decimal(str(payload.amount)),
            method="cash",
            safe_id=safe_id,
            reference=f"REP-{rep.id}",
            notes=payload.notes or f"تحصيل ميداني — مندوب {rep.name}",
        ),
        db,
        user,
    )
    audit(db, user, "create", "rep_collection", payment.id,
          f"تحصيل ميداني {payment.amount} من العميل {customer.name} — خزينة #{safe_id}")
    db.commit()
    # نشاط المندوب في صندوقه — نوع مميز عن payment_collected (التحصيل من الإدارة)
    from ..push import notify_rep
    try:
        notify_rep(db, rep.id, kind="collection_recorded",
                   title=f"سجلت تحصيلاً {payment.amount} ج.م",
                   body=f"العميل {customer.name} — سند #{payment.id}",
                   ref_id=payment.id)
    except Exception:
        pass
    return {
        "payment_id": payment.id,
        "amount": str(payment.amount),
        "customer_id": payload.customer_id,
        "safe_id": safe_id,
        "paid_on": str(payment.paid_on),
    }

class CommissionRunIn(BaseModel):
    period_from: date
    period_to: date

    @model_validator(mode="after")
    def _check_range(self):
        if self.period_from > self.period_to:
            raise ValueError("period_from must not be after period_to")
        return self


@router.post("/commission-runs", status_code=201)
def create_commission_run(
    payload: CommissionRunIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    """دورة صرف عمولات: تجميع صافي مبيعات كل مندوب للفترة (مؤكدة، بعد المرتجعات،
    وغير المدرجة في دورة سابقة) — وتقفل الأوردرات المدرجة (commission_run_id)."""
    from datetime import datetime as _dt, timezone as _tz
    from sqlalchemy import func

    company_id = db.info["company_id"]
    start = _dt.combine(payload.period_from, _dt.min.time(), tzinfo=_tz.utc)
    end = _dt.combine(payload.period_to + __import__("datetime").timedelta(days=1), _dt.min.time(), tzinfo=_tz.utc)

    reps = db.query(models.SalesRep).filter(
        models.SalesRep.company_id == company_id, models.SalesRep.is_active.is_(True)
    ).all()
    if not reps:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "لا مندوبين نشطين")

    # مبيعات مؤكدة خلال النافذة (لحظة التأكيد = updated_at) وغير مُدرجة في دورة سابقة
    sales_q = (
        db.query(
            models.SalesOrder.rep_id,
            func.count(models.SalesOrder.id).label("orders_count"),
            func.coalesce(func.sum(func.coalesce(models.SalesOrder.subtotal, models.SalesOrder.total_amount)), 0).label("gross"),
        )
        .filter(
            models.SalesOrder.company_id == company_id,
            models.SalesOrder.status == "confirmed",
            models.SalesOrder.rep_id.isnot(None),
            models.SalesOrder.commission_run_id.is_(None),
            models.SalesOrder.updated_at >= start,
            models.SalesOrder.updated_at < end,
        )
        .group_by(models.SalesOrder.rep_id)
        .all()
    )
    sales_map = {rid: (cnt, Decimal(str(g or 0))) for rid, cnt, g in sales_q}

    # مرتجعات منسوبة للمندوب خلال نفس النافذة
    returns_q = (
        db.query(models.SalesReturn.rep_id, func.coalesce(func.sum(models.SalesReturn.total_amount - models.SalesReturn.refund_amount), 0))
        .filter(
            models.SalesReturn.company_id == company_id,
            models.SalesReturn.rep_id.isnot(None),
            models.SalesReturn.commission_run_id.is_(None),
            models.SalesReturn.created_at >= start,
            models.SalesReturn.created_at < end,
        )
        .group_by(models.SalesReturn.rep_id)
        .all()
    )
    returns_map = {rid: Decimal(str(v or 0)) for rid, v in returns_q}

    run = models.RepCommissionRun(
        company_id=company_id, period_from=payload.period_from, period_to=payload.period_to,
        status="posted", created_by=user.id,
    )
    db.add(run)
    db.flush()

    lines = []
    total = Decimal("0")
    affected_orders = []
    for rep in reps:
        cnt, gross = sales_map.get(rep.id, (0, Decimal("0")))
        if cnt == 0:
            continue  # لا أوردرات غير مُقفلة في الفترة
        rets = returns_map.get(rep.id, Decimal("0"))
        net = (gross - rets).quantize(Decimal("0.01"))
        pct = Decimal(str(rep.commission_percent or 0))
        commission = (net * pct / Decimal("100")).quantize(Decimal("0.01"))
        line = models.RepCommissionRunLine(
            company_id=company_id, run_id=run.id, rep_id=rep.id,
            orders_count=cnt, gross=gross, returns_total=rets, net=net,
            percent=pct, commission=commission,
        )
        db.add(line)
        lines.append(line)
        total += commission

    run.total = total.quantize(Decimal("0.01"))  # type: ignore[assignment]
    db.flush()

    # قفل أوردرات كل مندوب مُدرج (فقط المؤكدة في النافذة وغير المقفلة)
    for line in lines:
        ids = [
            oid for (oid,) in db.query(models.SalesOrder.id).filter(
                models.SalesOrder.company_id == company_id,
                models.SalesOrder.rep_id == line.rep_id,
                models.SalesOrder.status == "confirmed",
                models.SalesOrder.commission_run_id.is_(None),
                models.SalesOrder.updated_at >= start,
                models.SalesOrder.updated_at < end,
            ).all()
        ]
        if ids:
            db.query(models.SalesOrder).filter(models.SalesOrder.id.in_(ids)).update(
                {models.SalesOrder.commission_run_id: run.id}, synchronize_session=False
            )
            affected_orders.extend(ids)
        # قفل مرتجعات المندوب في نفس النافذة — تصحيح العمولة يحدث مرة واحدة
        rids = [
            rid for (rid,) in db.query(models.SalesReturn.id).filter(
                models.SalesReturn.company_id == company_id,
                models.SalesReturn.rep_id == line.rep_id,
                models.SalesReturn.commission_run_id.is_(None),
                models.SalesReturn.created_at >= start,
                models.SalesReturn.created_at < end,
            ).all()
        ]
        if rids:
            db.query(models.SalesReturn).filter(models.SalesReturn.id.in_(rids)).update(
                {models.SalesReturn.commission_run_id: run.id}, synchronize_session=False
            )

    audit(db, user, "create", "rep_commission_run", run,
          f"دورة عمولات {payload.period_from}→{payload.period_to}: {len(lines)} مندوب · إجمالي {run.total} · {len(affected_orders)} أوردر")
    db.commit()
    db.refresh(run)
    return {
        "id": run.id, "period_from": str(run.period_from), "period_to": str(run.period_to),
        "total": str(run.total), "status": run.status,
        "lines": [{
            "rep_id": l.rep_id, "rep_name": l.rep.name, "orders_count": l.orders_count,
            "gross": str(l.gross), "returns_total": str(l.returns_total), "net": str(l.net),
            "percent": str(l.percent), "commission": str(l.commission),
        } for l in lines],
        "orders_locked": len(affected_orders),
    }


@router.get("/commission-runs")
def list_commission_runs(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    runs = (
        db.query(models.RepCommissionRun)
        .filter(models.RepCommissionRun.company_id == db.info["company_id"])
        .order_by(models.RepCommissionRun.id.desc())
        .limit(100)
        .all()
    )
    return [{
        "id": r.id, "period_from": str(r.period_from), "period_to": str(r.period_to),
        "total": str(r.total), "status": r.status, "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in runs]


@router.get("/me/manager-summary")
def me_manager_summary(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """ملخص إداري مختصر لشاشة المدير في تطبيق المندوبين:
    مبيعات اليوم/الشهر، تحصيلات اليوم، الأوردرات المعلقة، أفضل المنتجات، أعلى العملاء مديونية."""
    from ..accounting import local_today
    from ..exports import LOCAL_TZ
    from datetime import datetime as _dt, time as _time, timezone as _tz
    company_id = db.info["company_id"]
    today = local_today()
    day_start_local = _dt.combine(today, _time.min, tzinfo=LOCAL_TZ)
    today_start_u = day_start_local.astimezone(_tz.utc).replace(tzinfo=None)
    today_end_u = (day_start_local + _td(days=1)).astimezone(_tz.utc).replace(tzinfo=None)
    month_start_u = _dt.combine(today.replace(day=1), _time.min, tzinfo=LOCAL_TZ).astimezone(_tz.utc).replace(tzinfo=None)

    SO = models.SalesOrder
    # شاشة المدير تري الشركة كلها — يتجاوز نطاق مخازن المستخدم صراحةً
    today_agg = db.query(_func.count(SO.id), _func.coalesce(_func.sum(SO.total_amount), 0)).filter(
        SO.company_id == company_id, SO.status == "confirmed",
        SO.updated_at >= today_start_u, SO.updated_at < today_end_u,
    ).execution_options(ignore_tenant_scope=True).one()
    month_agg = db.query(_func.count(SO.id), _func.coalesce(_func.sum(SO.total_amount), 0)).filter(
        SO.company_id == company_id, SO.status == "confirmed",
        SO.updated_at >= month_start_u,
    ).execution_options(ignore_tenant_scope=True).one()
    pending = db.query(_func.count(SO.id)).filter(
        SO.company_id == company_id, SO.status == "draft",
    ).execution_options(ignore_tenant_scope=True).scalar() or 0

    P = models.Payment
    collected_today = db.query(_func.coalesce(_func.sum(P.amount), 0)).filter(
        P.company_id == company_id, P.status == "posted",
        P.created_at >= today_start_u, P.created_at < today_end_u,
    ).execution_options(ignore_tenant_scope=True).scalar() or 0

    # أفضل 5 منتجات مبيعة هذا الشهر (أوامر مؤكدة)
    top_rows = (
        db.query(models.SalesOrderItem.product_id, models.Product.name,
                 _func.coalesce(_func.sum(models.SalesOrderItem.quantity), 0),
                 _func.coalesce(_func.sum(models.SalesOrderItem.quantity * models.SalesOrderItem.unit_price), 0))
        .join(SO, SO.id == models.SalesOrderItem.order_id)
        .join(models.Product, models.Product.id == models.SalesOrderItem.product_id)
        .filter(
            SO.company_id == company_id, SO.status == "confirmed",
            SO.updated_at >= month_start_u,
        )
        .group_by(models.SalesOrderItem.product_id, models.Product.name)
        .order_by(_func.sum(models.SalesOrderItem.quantity * models.SalesOrderItem.unit_price).desc())
        .limit(5)
        .execution_options(ignore_tenant_scope=True)
        .all()
    )

    # أعلى 5 عملاء مديونية (رصيد موجب)
    from ..accounts import party_balances
    customers = db.query(models.Customer.id, models.Customer.name).filter(
        models.Customer.company_id == company_id, models.Customer.is_active.is_(True)
    ).execution_options(ignore_tenant_scope=True).all()
    balances = party_balances(db, "customer", [c.id for c in customers] or [0])
    top_debtors = sorted(
        ({"customer_id": cid, "name": name, "balance": float(balances.get(cid, 0))}
         for cid, name in customers if balances.get(cid, 0) > 0),
        key=lambda d: d["balance"], reverse=True,
    )[:5]

    return {
        "as_of": today.isoformat(),
        "today_orders": today_agg[0] or 0,
        "today_sales": float(today_agg[1] or 0),
        "month_orders": month_agg[0] or 0,
        "month_sales": float(month_agg[1] or 0),
        "collected_today": float(collected_today),
        "pending_orders": int(pending),
        "top_products": [
            {"product_id": pid, "name": name, "quantity": float(qty), "value": float(val)}
            for pid, name, qty, val in top_rows
        ],
        "top_debtors": top_debtors,
    }
