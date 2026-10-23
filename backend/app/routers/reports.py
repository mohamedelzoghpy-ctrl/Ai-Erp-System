"""Read-only reports. All figures are computed in SQL.

Only *confirmed* sales and *received* purchases count towards totals; drafts and cancelled
orders never do. Dates are interpreted as UTC.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(prefix="/reports", tags=["reports"])

ZERO = Decimal("0")


def _money(value) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def _period(date_from: Optional[date], date_to: Optional[date], default_days: int = 30):
    """Returns [start, end) as aware UTC datetimes; date_to is inclusive."""
    today = datetime.now(timezone.utc).date()
    end_day = date_to or today
    start_day = date_from or (end_day - timedelta(days=default_days - 1))
    if start_day > end_day:
        raise HTTPException(422, "date_from must not be after date_to")
    start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start, end


@router.get("/low-stock", response_model=List[schemas.LowStockItem])
def low_stock(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """Active products at or below their reorder level, most urgent first."""
    products = (
        db.query(models.Product)
        .filter(models.Product.is_active.is_(True), models.Product.quantity <= models.Product.reorder_level)
        .all()
    )
    rows = [
        schemas.LowStockItem(
            id=p.id,
            sku=p.sku,
            name=p.name,
            quantity=p.quantity,
            reorder_level=p.reorder_level,
            shortfall=p.reorder_level - p.quantity,
            warehouse_id=p.warehouse_id,
            supplier_id=p.supplier_id,
        )
        for p in products
    ]
    return sorted(rows, key=lambda r: (-r.shortfall, r.id))


@router.get("/inventory-valuation", response_model=List[schemas.InventoryValuationRow])
def inventory_valuation(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    """Stock value per warehouse at cost price and at sale price (active products only)."""
    P, W = models.Product, models.Warehouse
    rows = (
        db.query(
            P.warehouse_id,
            W.name,
            func.count(P.id),
            func.coalesce(func.sum(P.quantity), 0),
            func.coalesce(func.sum(P.quantity * P.cost_price), 0),
            func.coalesce(func.sum(P.quantity * P.sale_price), 0),
        )
        .outerjoin(W, W.id == P.warehouse_id)
        .filter(P.is_active.is_(True))
        .group_by(P.warehouse_id, W.name)
        .order_by(P.warehouse_id)
        .all()
    )
    return [
        schemas.InventoryValuationRow(
            warehouse_id=wid,
            warehouse_name=wname,
            products=count,
            units=int(units),
            cost_value=_money(cost),
            sale_value=_money(sale),
        )
        for wid, wname, count, units, cost, sale in rows
    ]


@router.get("/sales-summary", response_model=schemas.SalesSummary)
def sales_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    top: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """Confirmed sales in a period (default: last 30 days): totals, per-day series, top products."""
    start, end = _period(date_from, date_to)
    SO, SI, P = models.SalesOrder, models.SalesOrderItem, models.Product
    in_period = (SO.status == "confirmed", SO.created_at >= start, SO.created_at < end)

    orders, total = db.query(func.count(SO.id), func.coalesce(func.sum(SO.total_amount), 0)).filter(*in_period).one()

    day = func.date(SO.created_at)
    by_day = (
        db.query(day, func.count(SO.id), func.coalesce(func.sum(SO.total_amount), 0))
        .filter(*in_period)
        .group_by(day)
        .order_by(day)
        .all()
    )

    revenue = func.sum(SI.quantity * SI.unit_price)
    top_rows = (
        db.query(P.id, P.sku, P.name, func.sum(SI.quantity), revenue)
        .join(SI, SI.product_id == P.id)
        .join(SO, SO.id == SI.order_id)
        .filter(*in_period)
        .group_by(P.id, P.sku, P.name)
        .order_by(revenue.desc(), P.id)
        .limit(top)
        .all()
    )
    return schemas.SalesSummary(
        date_from=start,
        date_to=end - timedelta(microseconds=1),
        orders=orders,
        total=_money(total),
        by_day=[schemas.SalesByDay(day=str(d), orders=n, total=_money(t)) for d, n, t in by_day],
        top_products=[
            schemas.TopProduct(product_id=pid, sku=sku, name=name, quantity_sold=int(q), revenue=_money(r))
            for pid, sku, name, q, r in top_rows
        ],
    )


@router.get("/dashboard", response_model=schemas.Dashboard)
def dashboard(
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """Headline numbers for the home screen. Sales/purchase totals cover the last `days` days."""
    start, end = _period(None, None, default_days=days)
    P, SO, PO = models.Product, models.SalesOrder, models.PurchaseOrder

    def count(model):
        return db.query(func.count(model.id)).scalar() or 0

    low = (
        db.query(func.count(P.id)).filter(P.is_active.is_(True), P.quantity <= P.reorder_level).scalar() or 0
    )
    cost_value, sale_value = (
        db.query(
            func.coalesce(func.sum(P.quantity * P.cost_price), 0),
            func.coalesce(func.sum(P.quantity * P.sale_price), 0),
        )
        .filter(P.is_active.is_(True))
        .one()
    )
    s_orders, s_total = (
        db.query(func.count(SO.id), func.coalesce(func.sum(SO.total_amount), 0))
        .filter(SO.status == "confirmed", SO.created_at >= start, SO.created_at < end)
        .one()
    )
    # A purchase counts when it was received; updated_at is stamped at the receive transition.
    p_orders, p_total = (
        db.query(func.count(PO.id), func.coalesce(func.sum(PO.total_amount), 0))
        .filter(PO.status == "received", PO.updated_at >= start, PO.updated_at < end)
        .one()
    )
    return schemas.Dashboard(
        period_days=days,
        products=db.query(func.count(P.id)).filter(P.is_active.is_(True)).scalar() or 0,
        low_stock_products=low,
        warehouses=count(models.Warehouse),
        suppliers=count(models.Supplier),
        customers=count(models.Customer),
        inventory_cost_value=_money(cost_value),
        inventory_sale_value=_money(sale_value),
        sales_orders_confirmed=s_orders,
        sales_total=_money(s_total),
        purchase_orders_received=p_orders,
        purchases_total=_money(p_total),
        draft_sales_orders=db.query(func.count(SO.id)).filter(SO.status == "draft").scalar() or 0,
        draft_purchase_orders=db.query(func.count(PO.id)).filter(PO.status == "draft").scalar() or 0,
    )
