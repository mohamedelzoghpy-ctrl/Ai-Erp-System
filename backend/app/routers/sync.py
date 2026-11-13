"""مزامنة تطبيق المندوبين (الموبايل): سحب دلتا + دفع أوردرات مجمعة.

- GET /sync/bootstrap?since=<ISO>: كل ما تغيّر منذ آخر مزامنة (منتجات نشطة،
  عملاء، قوائم الأسعار كاملة — صغيرة) مع server_time كركيزة (cursor) للمرة القادمة.
- POST /sync/orders: رفع أوردرات أنشئت أوفلاين — إنشاء كمسودات عبر نفس مسار
  إنشاء الأوردرات الرسمي (أسعار القوائم/التجميع/التحقق)، idempotent بالـclient_ref:
  إعادة المحاولة تعيد الأوردر الأصلي ولا تنشئ مكرراً. فشل عنصر لا يُسقط الدفعة.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..routers.orders import create_sales_order

router = APIRouter(prefix="/sync", tags=["sync"])


def _iso(dt) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@router.get("/bootstrap")
def bootstrap(
    since: Optional[str] = Query(None, description="ISO datetime — أعد فقط ما تغيّر بعده"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """سحب بيانات المندوب: دلتا للمنتجات/العملاء + قوائم الأسعار كاملة."""
    company_id = db.info["company_id"]
    server_time = datetime.now(timezone.utc)

    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            from fastapi import HTTPException, status
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "since يجب أن يكون ISO datetime صالحاً")

    # المنتجات النشطة (دلتا أو كاملة) — بدون التكلفة (حقل حساس مُقنَّع لأقل من مدير)
    pq = db.query(models.Product).filter(
        models.Product.company_id == company_id, models.Product.is_active.is_(True)  # type: ignore[attr-defined]
    )
    if since_dt is not None:
        pq = pq.filter(models.Product.updated_at > since_dt)  # type: ignore[attr-defined]
    products = [
        {
            "id": p.id, "sku": p.sku, "name": p.name, "unit": p.unit,
            "sale_price": str(p.sale_price), "updated_at": _iso(p.updated_at),
        }
        for p in pq.order_by(models.Product.id).all()
    ]

    cq = db.query(models.Customer).filter(models.Customer.company_id == company_id)  # type: ignore[attr-defined]
    if since_dt is not None:
        cq = cq.filter(models.Customer.updated_at > since_dt)  # type: ignore[attr-defined]
    customers_rows = cq.order_by(models.Customer.id).all()
    from ..accounts import party_balances
    from ..permissions.engine import can

    balances = party_balances(db, "customer", [c.id for c in customers_rows] or [0])
    # أقنعة الحقول الحساسة — الرصيد وحد الائتمان لا يُرسلان إلا لمن يملك صلاحية
    # عرض أرصدة المندوب (سُحبت من قسم المستخدم؟ لا تصل) أو صلاحية عرض الرصيد الكاملة.
    _view_balance = can("sales.customer.rep_mobile_balance", "sales.customer.balance_view")
    customers = [
        {
            "id": c.id, "name": c.name, "phone": c.phone,
            "credit_limit": (str(c.credit_limit) if c.credit_limit is not None else None) if _view_balance else None,
            "price_list_id": c.price_list_id,
            "balance": str(balances.get(c.id, 0)) if _view_balance else None,
            "updated_at": _iso(c.updated_at),
        }
        for c in customers_rows
    ]

    price_lists = [
        {
            "id": pl.id, "name": pl.name,
            "items": [{"product_id": it.product_id, "unit_price": str(it.unit_price)} for it in pl.items],
        }
        for pl in db.query(models.PriceList).filter(models.PriceList.company_id == company_id).all()  # type: ignore[attr-defined]
    ]

    # عملاء المندوب المحتملون (CRM ميداني أوفلاين) — المسندون إليه فقط
    rep_for_leads = db.query(models.SalesRep).filter(
        models.SalesRep.company_id == company_id, models.SalesRep.user_id == user.id  # type: ignore[attr-defined]
    ).first()
    leads_payload = []
    if rep_for_leads is not None:
        lq = db.query(models.CrmLead).filter(
            models.CrmLead.company_id == company_id,
            models.CrmLead.assigned_rep_id == rep_for_leads.id,
        )
        if since_dt is not None:
            lq = lq.filter(models.CrmLead.updated_at > since_dt)  # type: ignore[attr-defined]
        leads_payload = [
            {
                "id": l.id, "code": l.code, "name": l.name,
                "company_name": l.company_name, "phone": l.phone,
                "address": l.address, "source": l.source,
                "status": l.status, "expected_value": str(l.expected_value),
                "next_follow_up_at": _iso(l.next_follow_up_at) if l.next_follow_up_at else None,
                "notes": l.notes,
                "updated_at": _iso(l.updated_at),
            }
            for l in lq.order_by(models.CrmLead.id).all()
        ]
        # إشعارات المتابعة المستحقة (مرة يومياً لكل قائد) + دفع FCM
        from ..crm_followups import ensure_followup_notifications
        try:
            ensure_followup_notifications(db, rep_for_leads)
        except Exception:
            pass  # الإشعار لا يفشل المزامنة

    return {
        "server_time": server_time.isoformat(),
        "default_warehouse_id": next(
            (
                w.id
                for w in db.query(models.Warehouse)
                .filter(models.Warehouse.company_id == company_id, models.Warehouse.is_active.is_(True))  # type: ignore[attr-defined]
                .order_by(models.Warehouse.id)
                .all()
            ),
            None,
        ),
        "products": products,
        "customers": customers,
        "price_lists": price_lists,
        "crm_leads": leads_payload,
    }


class SyncOrderItem(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    unit_price: Optional[float] = Field(default=None, ge=0, description="فارغة = سعر البيع/قائمة العميل")


class SyncOrderIn(BaseModel):
    client_ref: str = Field(min_length=8, max_length=64, description="معرف فريد يولده التطبيق")
    customer_id: int
    warehouse_id: int
    notes: Optional[str] = None
    tax_rate: float = Field(default=0, ge=0, le=100)
    items: List[SyncOrderItem] = Field(min_length=1)


class SyncOrdersIn(BaseModel):
    orders: List[SyncOrderIn] = Field(min_length=1, max_length=100)


@router.post("/orders")
def push_orders(
    payload: SyncOrdersIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """رفع أوردرات أوفلاين: تُنشأ كمسودات عبر مسار الأوردرات الرسمي — idempotent."""
    company_id = db.info["company_id"]

    # ربط المندوب بالحساب (نفس منطق /reps/me)
    rep = (
        db.query(models.SalesRep)
        .filter(models.SalesRep.company_id == company_id, models.SalesRep.user_id == user.id)  # type: ignore[attr-defined]
        .first()
    )

    results = []
    for order_in in payload.orders:
        existing = (
            db.query(models.SalesOrder)
            .filter(
                models.SalesOrder.company_id == company_id,  # type: ignore[attr-defined]
                models.SalesOrder.client_ref == order_in.client_ref,
            )
            .one_or_none()
        )
        if existing is not None:
            results.append({"client_ref": order_in.client_ref, "order_id": existing.id, "status": "duplicate", "error": None})
            continue
        try:
            created = create_sales_order(
                schemas.SalesOrderCreate(
                    customer_id=order_in.customer_id,
                    warehouse_id=order_in.warehouse_id,
                    notes=order_in.notes,
                    rep_id=rep.id if rep else None,
                    tax_rate=order_in.tax_rate,
                    items=[
                        schemas.SalesItemIn(product_id=it.product_id, quantity=it.quantity, unit_price=it.unit_price)
                        for it in order_in.items
                    ],
                ),
                request,
                db,
                user,
            )
            created.client_ref = order_in.client_ref  # type: ignore[assignment]
            db.commit()
            results.append({"client_ref": order_in.client_ref, "order_id": created.id, "status": "created", "error": None})
        except Exception as exc:  # عنصر فاشل لا يُسقط الدفعة
            db.rollback()
            detail = getattr(exc, "detail", None) or str(exc)
            results.append({"client_ref": order_in.client_ref, "order_id": None, "status": "failed", "error": str(detail)[:300]})
    return {"results": results}


# ---------------- CRM ميداني أوفلاين (المرحلة 3) ----------------
def _rep_for_mobile(db, company_id: int, user):
    rep = db.query(models.SalesRep).filter(
        models.SalesRep.company_id == company_id, models.SalesRep.user_id == user.id  # type: ignore[attr-defined]
    ).first()
    if rep is None:
        from fastapi import HTTPException, status
        raise HTTPException(status.HTTP_403_FORBIDDEN, "الحساب غير مرتبط بمندوب")
    return rep


class SyncCrmActivityIn(BaseModel):
    client_ref: str = Field(min_length=8, max_length=64)
    lead_id: int
    kind: str = Field(pattern="^(note|call|meeting)$")
    body: str = Field(min_length=1, max_length=2000)
    occurred_at: Optional[datetime] = None


class SyncCrmActivitiesIn(BaseModel):
    activities: List[SyncCrmActivityIn] = Field(min_length=1, max_length=200)


class SyncCrmStageIn(BaseModel):
    lead_id: int
    status: str = Field(pattern="^(new|contacted|qualified|won|lost)$")
    lost_reason: Optional[str] = Field(default=None, max_length=200)


class SyncCrmStagesIn(BaseModel):
    updates: List[SyncCrmStageIn] = Field(min_length=1, max_length=200)


@router.post("/crm/activities")
def push_crm_activities(payload: SyncCrmActivitiesIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """رفع أنشطة متابعة مسجلة أوفلاين — idempotent بـ client_ref (رفع مكرر = تخطٍ بلا أثر)."""
    company_id = db.info["company_id"]
    rep = _rep_for_mobile(db, company_id, user)
    results = []
    for item in payload.activities:
        lead = db.get(models.CrmLead, item.lead_id)
        if lead is None or lead.company_id != company_id or lead.assigned_rep_id != rep.id:
            results.append({"client_ref": item.client_ref, "ok": False, "reason": "القائد غير مسند إليك"})
            continue
        existing = db.query(models.CrmActivity).filter(
            models.CrmActivity.company_id == company_id,
            models.CrmActivity.client_ref == item.client_ref,
        ).first()
        if existing is not None:
            results.append({"client_ref": item.client_ref, "ok": True, "id": existing.id, "duplicate": True})
            continue
        row = models.CrmActivity(
            company_id=company_id, lead_id=lead.id, kind=item.kind,
            body=item.body.strip(), created_by=user.id, client_ref=item.client_ref,
        )
        db.add(row)
        db.flush()
        results.append({"client_ref": item.client_ref, "ok": True, "id": row.id})
    from ..audit import audit
    audit(db, user, "create", "crm_activity", None, f"رفع {len(payload.activities)} نشاط من الموبايل")
    db.commit()
    return {"results": results}


@router.post("/crm/stages")
def push_crm_stage_updates(payload: SyncCrmStagesIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """تغيير مراحل القادة من الموبايل — آخر حالة تفوز (idempotent بطبيعته).
    won من الميدان = تحويل كامل لعميل فعلي. lost يتطلب سبباً."""
    from ..routers.crm import _get_lead, STAGE_AR
    from ..routers.crm import convert_lead as _convert_lead
    company_id = db.info["company_id"]
    rep = _rep_for_mobile(db, company_id, user)
    results = []
    for item in payload.updates:
        try:
            lead = _get_lead(db, item.lead_id)
        except Exception:
            results.append({"lead_id": item.lead_id, "ok": False, "reason": "القائد غير موجود"})
            continue
        if lead.assigned_rep_id != rep.id:
            results.append({"lead_id": item.lead_id, "ok": False, "reason": "القائد غير مسند إليك"})
            continue
        if lead.converted_customer_id is not None:
            results.append({"lead_id": item.lead_id, "ok": True, "status": lead.status, "already_final": True})
            continue
        if item.status == "lost" and not (item.lost_reason or "").strip():
            results.append({"lead_id": item.lead_id, "ok": False, "reason": "سبب الفقد مطلوب"})
            continue
        old_status = lead.status
        lead.status = item.status
        if item.status == "lost":
            lead.lost_reason = (item.lost_reason or "").strip()
        if item.status == "won":
            try:
                _convert_lead(obj_id=lead.id, db=db, user=user)
                customer_id = lead.converted_customer_id
                results.append({"lead_id": item.lead_id, "ok": True, "status": "won", "converted_customer_id": customer_id})
                continue
            except Exception:
                results.append({"lead_id": item.lead_id, "ok": False, "reason": "تعذر التحويل لعميل"})
                db.rollback()
                continue
        db.add(models.CrmActivity(
            company_id=company_id, lead_id=lead.id, kind="system",
            body=f"تغيّرت المرحلة من الميدان: {STAGE_AR.get(old_status, old_status)} ← {STAGE_AR.get(item.status, item.status)}",
            created_by=user.id,
        ))
        db.commit()
        db.refresh(lead)
        results.append({"lead_id": item.lead_id, "ok": True, "status": lead.status})
    return {"results": results}
