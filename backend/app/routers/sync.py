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
