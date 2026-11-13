"""Read-only reports. All figures are computed in SQL.

Only *confirmed* sales and *received* purchases count towards totals; drafts and cancelled
orders never do. An order is dated by when it was confirmed / received (its `updated_at`, which
is stamped by that transition and never changes afterwards), not by when the draft was created.
Dates are interpreted as UTC. Each report is also available as an Excel download (`.../xlsx`).
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import accounts, exports, models, schemas
from ..database import get_db
from .shifts import stale_cutoff
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


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=exports.XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


def _range_label(summary) -> str:
    return f"الفترة: {summary.date_from.date()} إلى {summary.date_to.date()}"


def _file_range(summary) -> str:
    return f"{summary.date_from.date()}_{summary.date_to.date()}"


# ---------------------------------------------------------------- low stock
def _low_stock_rows(db: Session, warehouse_id: Optional[int] = None, branch_id: Optional[int] = None, supplier_id: Optional[int] = None) -> List[schemas.LowStockItem]:
    """Scopes: company-wide by default, or per branch (all its warehouses), or one warehouse.

    The quantity compared against the reorder level is the stock across the selected scope;
    products with no stock record in that scope count as zero.
    """
    PS = models.ProductStock
    compared: dict = {}
    warehouse_mins: dict = {}
    if warehouse_id or branch_id:
        WH = models.Warehouse
        q = db.query(PS.product_id, func.coalesce(func.sum(PS.quantity), 0)).join(WH, WH.id == PS.warehouse_id)
        if warehouse_id:
            q = q.filter(WH.id == warehouse_id)
        else:
            q = q.filter(WH.branch_id == branch_id)
        compared = dict(q.group_by(PS.product_id).all())
        # حد المخزن الخاص (min_level) يتجاوز العام عند ضبطه — في نطاق مخزن واحد فقط يُطبق بدقة
        if warehouse_id:
            warehouse_mins = {
                pid: mn for pid, mn in db.query(PS.product_id, PS.min_level)
                .filter(PS.warehouse_id == warehouse_id, PS.min_level.isnot(None)).all()
            }
            _scope = warehouse_id
        else:
            _scope = None
        products = db.query(models.Product).filter(models.Product.is_active.is_(True)).all()
        def _effective_min(p):
            if _scope is not None and p.id in warehouse_mins:
                return warehouse_mins[p.id], "warehouse"
            return p.reorder_level, "product"
        products = [
            p for p in products
            if compared.get(p.id, 0) <= _effective_min(p)[0]  # type: ignore[union-attr,operator]
        ]
    else:
        products = (
            db.query(models.Product)
            .filter(models.Product.is_active.is_(True), models.Product.quantity <= models.Product.reorder_level)
            .all()
        )
    if supplier_id:
        products = [p for p in products if p.supplier_id == supplier_id]
    sup_ids = {p.supplier_id for p in products if p.supplier_id}  # type: ignore[union-attr]
    supplier_map = (
        dict(db.query(models.Supplier.id, models.Supplier.name).filter(models.Supplier.id.in_(sup_ids)).all())
        if sup_ids
        else {}
    )
    rows = [
        schemas.LowStockItem(
            id=p.id,  # type: ignore
            sku=p.sku,  # type: ignore
            name=p.name,  # type: ignore
            quantity=(compared.get(p.id, 0) if compared else p.quantity),  # type: ignore
            reorder_level=(int(warehouse_mins[p.id]) if (warehouse_id and p.id in warehouse_mins) else p.reorder_level),  # type: ignore[union-attr,operator]
            shortfall=(
                (float(warehouse_mins[p.id]) if (warehouse_id and p.id in warehouse_mins) else float(p.reorder_level))  # type: ignore[union-attr,operator]
                - float(compared.get(p.id, 0) if compared else p.quantity or 0)  # type: ignore
            ),
            min_source=("warehouse" if (warehouse_id and p.id in warehouse_mins) else "product"),  # type: ignore[union-attr,operator]
            image_url=p.image_url,  # type: ignore
            image_uploaded=p.image_uploaded,  # type: ignore
            warehouse_id=p.warehouse_id,  # type: ignore
            supplier_id=p.supplier_id,  # type: ignore
            supplier_name=supplier_map.get(p.supplier_id),  # type: ignore[union-attr]
        )
        for p in products
    ]
    return sorted(rows, key=lambda r: (-r.shortfall, r.id))


@router.get("/low-stock", response_model=List[schemas.LowStockItem])
def low_stock(
    warehouse_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Active products at or below their reorder level, most urgent first. Scope: company, branch, warehouse, or supplier."""
    return _low_stock_rows(db, warehouse_id=warehouse_id, branch_id=branch_id, supplier_id=supplier_id)


@router.get("/low-stock/xlsx")
def low_stock_xlsx(
    warehouse_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    rows = _low_stock_rows(db, warehouse_id=warehouse_id, branch_id=branch_id, supplier_id=supplier_id)
    wh = {w.id: w.name for w in db.query(models.Warehouse).all()}
    if warehouse_id:
        scope = wh.get(warehouse_id, f"مخزن #{warehouse_id}")
    elif branch_id:
        br = db.get(models.Branch, branch_id)  # type: ignore[arg-type]
        scope = getattr(br, "name", None) or f"فرع #{branch_id}"
    else:
        scope = "الشركة ككل"
    sup = {s.id: s.name for s in db.query(models.Supplier).all()}
    if supplier_id:
        scope += f" — مورد: {sup.get(supplier_id, '#' + str(supplier_id))}"
    table = (
        f"نقص المخزون — نطاق: {scope}",
        ["الكود", "المنتج", "المخزن", "المورد", "المتاح", "حد إعادة الطلب", "العجز"],
        [
            [
                ("text", r.sku),
                ("text", r.name),
                ("text", wh.get(r.warehouse_id, "—")),  # type: ignore
                ("text", sup.get(r.supplier_id, "—")),  # type: ignore
                ("int", r.quantity),
                ("int", r.reorder_level),
                ("int", r.shortfall),
            ]
            for r in rows
        ],
    )
    content = exports.build_tables_xlsx("تقرير نقص المخزون", exports.fmt_dt(datetime.now(timezone.utc)), [table])
    return _xlsx_response(content, "report-low-stock.xlsx")


# ---------------------------------------------------------------- التنبؤ الذكي بحد الطلب ونقاط إعادة التموين
@router.get("/reorder-forecast", response_model=schemas.ReorderForecastOut)
def reorder_forecast(
    days_analyzed: int = Query(default=30, ge=7, le=180, description="فترة تحليل المبيعات السابقة بالأيام"),
    default_lead_time: int = Query(default=7, ge=1, le=90, description="زمن التوريد الافتراضي بالأيام"),
    safety_days: int = Query(default=3, ge=0, le=30, description="أيام مخزون الأمان الإضافية"),
    warehouse_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """محرك التنبؤ الذكي بحد الطلب:
    يحسب معدل السحب اليومي الفعلي ومخزون الأمان ونقطة إعادة الطلب الديناميكية ROP
    مع تقدير الأيام المتبقية لنفاد الرصيد واقتراح الكمية وتكلفتها."""
    company_id = db.info["company_id"]
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_analyzed)

    # 1. إجمالي كميات المبيعات المؤكدة خلال فترة التحليل
    SOI = models.SalesOrderItem
    SO = models.SalesOrder
    sales_query = (
        db.query(
            SOI.product_id,
            func.coalesce(func.sum(SOI.quantity), 0).label("qty_sold"),
        )
        .join(SO, SO.id == SOI.order_id)
        .filter(
            SO.company_id == company_id,
            SO.status.in_(["confirmed", "delivered"]),
            SO.created_at >= cutoff,
        )
    )
    if warehouse_id:
        sales_query = sales_query.filter(SO.warehouse_id == warehouse_id)
    sales_data = dict(sales_query.group_by(SOI.product_id).all())

    # 2. جلب المنتجات النشطة
    prod_q = db.query(models.Product).filter(
        models.Product.company_id == company_id,
        models.Product.is_active.is_(True),
    )
    if supplier_id:
        prod_q = prod_q.filter(models.Product.supplier_id == supplier_id)
    products = prod_q.all()

    # خريطة أسماء الموردين
    sup_ids = {p.supplier_id for p in products if p.supplier_id}
    suppliers = dict(db.query(models.Supplier.id, models.Supplier.name).filter(models.Supplier.id.in_(sup_ids)).all()) if sup_ids else {}

    # الأرصدة الحالية في المخزن المحدد أو الإجمالي
    PS = models.ProductStock
    if warehouse_id:
        stock_map = dict(db.query(PS.product_id, PS.quantity).filter(PS.warehouse_id == warehouse_id).all())
    else:
        stock_map = {p.id: float(p.quantity or 0) for p in products}

    items = []
    critical_count = 0
    warning_count = 0
    total_suggested_investment = Decimal("0")

    for p in products:
        current_stock = float(stock_map.get(p.id, 0))
        total_sold = float(sales_data.get(p.id, 0))
        daily_sales = round(total_sold / days_analyzed, 3)

        lead_time = default_lead_time
        # مخزون الأمان = متوسط السحب اليومي × أيام الأمان
        safety_stock = round(daily_sales * safety_days, 2)
        # نقطة الطلب الديناميكية ROP = (السحب اليومي × زمن التوريد) + مخزون الأمان
        suggested_rop = round((daily_sales * lead_time) + safety_stock, 2)

        # في حال عدم وجود مبيعات سابقة، نعتمد على الحد الثابت كمرجع
        if suggested_rop == 0 and p.reorder_level:
            suggested_rop = float(p.reorder_level)

        # حساب الأيام المتبقية لنفاد الرصيد
        days_left = round(current_stock / daily_sales, 1) if daily_sales > 0 else (999.0 if current_stock > 0 else 0.0)

        # حالة الإلحاح والكمية المقترحة
        if current_stock <= safety_stock or (days_left <= lead_time and daily_sales > 0):
            urgency = "critical"
            critical_count += 1
        elif current_stock <= suggested_rop:
            urgency = "warning"
            warning_count += 1
        else:
            urgency = "healthy"

        # كمية الطلب المقترحة: تغطية زمن التوريد + مخزون الأمان + دورة تشغيل 15 يوماً
        cycle_days = 15
        target_stock = (daily_sales * (lead_time + cycle_days)) + safety_stock
        suggested_qty = round(max(0.0, target_stock - current_stock), 2)
        if suggested_qty == 0 and urgency in ("critical", "warning"):
            suggested_qty = round(max(float(p.reorder_level or 10), daily_sales * 14), 2)

        unit_cost = float(p.cost_price or 0)
        est_cost = round(suggested_qty * unit_cost, 2)
        if urgency in ("critical", "warning"):
            total_suggested_investment += Decimal(str(est_cost))

        items.append(schemas.ReorderForecastItem(
            product_id=p.id,
            sku=p.sku,
            name=p.name,
            current_stock=current_stock,
            daily_sales=daily_sales,
            lead_time_days=lead_time,
            safety_stock=safety_stock,
            suggested_rop=suggested_rop,
            reorder_urgency=urgency,
            days_left=days_left if days_left < 999 else None,
            suggested_order_qty=suggested_qty,
            unit_cost=unit_cost,
            estimated_cost=est_cost,
            supplier_id=p.supplier_id,
            supplier_name=suppliers.get(p.supplier_id),
            warehouse_id=warehouse_id or p.warehouse_id,
        ))

    # ترتيب حسب الأكثر إلحاحاً (critical أولاً ثم warning ثم الأقل أيام متبقية)
    urgency_weight = {"critical": 0, "warning": 1, "healthy": 2}
    items.sort(key=lambda x: (urgency_weight[x.reorder_urgency], x.days_left if x.days_left is not None else 999))

    return schemas.ReorderForecastOut(
        days_analyzed=days_analyzed,
        total_items_analyzed=len(products),
        critical_count=critical_count,
        warning_count=warning_count,
        total_suggested_investment=float(total_suggested_investment),
        items=items,
    )


# ---------------------------------------------------------------- inventory valuation
def _valuation_rows(db: Session) -> List[schemas.InventoryValuationRow]:
    P, W, S = models.Product, models.Warehouse, models.ProductStock
    rows = (
        db.query(
            S.warehouse_id,
            W.name,
            func.count(P.id),
            func.coalesce(func.sum(S.quantity), 0),
            func.coalesce(func.sum(S.quantity * P.cost_price), 0),
            func.coalesce(func.sum(S.quantity * P.sale_price), 0),
        )
        .join(P, P.id == S.product_id)
        .join(W, W.id == S.warehouse_id)
        .filter(P.is_active.is_(True), S.quantity > 0)
        .group_by(S.warehouse_id, W.name)
        .order_by(S.warehouse_id)
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


@router.get("/inventory-valuation", response_model=List[schemas.InventoryValuationRow])
def inventory_valuation(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    """Stock value per warehouse at cost price and at sale price (active products only)."""
    return _valuation_rows(db)


@router.get("/inventory-valuation/xlsx")
def inventory_valuation_xlsx(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    rows = _valuation_rows(db)
    P, S = models.Product, models.ProductStock
    products = (
        db.query(P, models.Warehouse.name, S.quantity)
        .join(S, S.product_id == P.id)
        .join(models.Warehouse, models.Warehouse.id == S.warehouse_id)
        .filter(P.is_active.is_(True), S.quantity > 0)
        .order_by(P.name, models.Warehouse.name)
        .all()
    )
    tables = [
        (
            "حسب المخزن",
            ["المخزن", "عدد المنتجات", "الوحدات", "القيمة بالتكلفة", "القيمة بسعر البيع"],
            [
                [
                    ("text", r.warehouse_name or "بدون مخزن"),
                    ("int", r.products),
                    ("int", r.units),
                    ("money", r.cost_value),
                    ("money", r.sale_value),
                ]
                for r in rows
            ],
        ),
        (
            "حسب المنتج",
            ["الكود", "المنتج", "المخزن", "الكمية", "التكلفة", "سعر البيع", "القيمة بالتكلفة", "القيمة بسعر البيع"],
            [
                [
                    ("text", p.sku),
                    ("text", p.name),
                    ("text", wname),
                    ("int", qty),
                    ("money", p.cost_price),
                    ("money", p.sale_price),
                    ("money", p.cost_price * qty),
                    ("money", p.sale_price * qty),
                ]
                for p, wname, qty in products
            ],
        ),
    ]
    content = exports.build_tables_xlsx("تقرير قيمة المخزون", exports.fmt_dt(datetime.now(timezone.utc)), tables)
    return _xlsx_response(content, "report-inventory-valuation.xlsx")


# ---------------------------------------------------------------- sales
def _sales_summary(
    db: Session,
    date_from,
    date_to,
    top: int,
    customer_id: Optional[int] = None,
    product_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    user_id: Optional[int] = None,
    rep_id: Optional[int] = None,
) -> schemas.SalesSummary:
    start, end = _period(date_from, date_to)
    SO, SI, P, C = models.SalesOrder, models.SalesOrderItem, models.Product, models.Customer
    in_period = (SO.status == "confirmed", SO.updated_at >= start, SO.updated_at < end)

    # classification filters: narrow the report to selected customer / product / product's supplier / sales rep / user
    extra = []
    if customer_id:
        extra.append(SO.customer_id == customer_id)
    if user_id:
        extra.append(SO.created_by == user_id)
    if rep_id:
        extra.append(SO.rep_id == rep_id)
    if product_id:
        extra.append(SO.id.in_(db.query(SI.order_id).filter(SI.product_id == product_id)))
    if supplier_id:
        extra.append(SO.id.in_(db.query(SI.order_id).join(P, P.id == SI.product_id).filter(P.supplier_id == supplier_id)))

    orders, total = db.query(func.count(SO.id), func.coalesce(func.sum(func.coalesce(SO.subtotal, SO.total_amount)), 0)).filter(*in_period, *extra).one()

    day = func.date(SO.updated_at)
    by_day = (
        db.query(day, func.count(SO.id), func.coalesce(func.sum(func.coalesce(SO.subtotal, SO.total_amount)), 0))
        .filter(*in_period, *extra)
        .group_by(day)
        .order_by(day)
        .all()
    )

    revenue = func.sum(SI.quantity * SI.unit_price)
    top_rows = (
        db.query(P.id, P.sku, P.name, func.sum(SI.quantity), revenue)
        .join(SI, SI.product_id == P.id)
        .join(SO, SO.id == SI.order_id)
        .filter(*in_period, *extra)
        .group_by(P.id, P.sku, P.name)
        .order_by(revenue.desc(), P.id)
        .limit(top)
        .all()
    )

    cust_total = func.sum(func.coalesce(SO.subtotal, SO.total_amount))  # الصافي بدون الضريبة
    cust_rows = (
        db.query(C.id, C.name, func.count(SO.id), cust_total)
        .join(SO, SO.customer_id == C.id)
        .filter(*in_period, *extra)
        .group_by(C.id, C.name)
        .order_by(cust_total.desc(), C.id)
        .limit(top)
        .all()
    )
    U = models.User
    cashier_total = func.sum(func.coalesce(SO.subtotal, SO.total_amount))
    cashier_rows = (
        db.query(U.username, func.count(SO.id), cashier_total)
        .select_from(SO)
        .outerjoin(U, U.id == SO.created_by)
        .filter(*in_period, *extra)
        .group_by(U.username)
        .order_by(cashier_total.desc(), U.username)
        .all()
    )
    S = models.Supplier
    sup_total = func.sum(SI.quantity * SI.unit_price)
    sup_rows = (
        db.query(S.id, S.name, func.count(func.distinct(SO.id)), sup_total)
        .select_from(SI)
        .join(SO, SO.id == SI.order_id)
        .join(P, P.id == SI.product_id)
        .outerjoin(S, S.id == P.supplier_id)
        .filter(*in_period, *extra)
        .group_by(S.id, S.name)
        .order_by(sup_total.desc(), S.id)
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
        by_customer=[
            schemas.SalesByCustomer(customer_id=cid, customer_name=cname, orders=n, total=_money(t))
            for cid, cname, n, t in cust_rows
        ],
        by_cashier=[schemas.SalesByCashier(username=u, orders=n, total=_money(t)) for u, n, t in cashier_rows],
        by_product_supplier=[
            schemas.SalesByProductSupplier(supplier_id=sid, supplier_name=sname or "بدون مورد", orders=n, total=_money(t))
            for sid, sname, n, t in sup_rows
        ],
    )


@router.get("/sales-summary", response_model=schemas.SalesSummary)
def sales_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    days: Optional[int] = Query(None, ge=1, le=366),
    top: int = Query(5, ge=1, le=50),
    customer_id: Optional[int] = None,
    product_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    user_id: Optional[int] = None,
    rep_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """Confirmed sales in a period (default: last `days`=30 days): totals, per-day series, top products and customers."""
    if days and date_from is None and date_to is None:
        date_from = date.today() - timedelta(days=days - 1)
    return _sales_summary(db, date_from, date_to, top, customer_id=customer_id, product_id=product_id, supplier_id=supplier_id, user_id=user_id, rep_id=rep_id)


@router.get("/sales-summary/xlsx")
def sales_summary_xlsx(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    top: int = Query(50, ge=1, le=50),
    customer_id: Optional[int] = None,
    product_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    user_id: Optional[int] = None,
    rep_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    s = _sales_summary(db, date_from, date_to, top, customer_id=customer_id, product_id=product_id, supplier_id=supplier_id, user_id=user_id, rep_id=rep_id)
    tables = [
        ("الملخص", ["البند", "القيمة"], [[("text", "عدد الأوامر المؤكدة"), ("int", s.orders)], [("text", "إجمالي المبيعات"), ("money", s.total)]]),
        ("المبيعات اليومية", ["اليوم", "عدد الأوامر", "الإجمالي"], [[("text", d.day), ("int", d.orders), ("money", d.total)] for d in s.by_day]),
        (
            "المنتجات",
            ["الكود", "المنتج", "الكمية المباعة", "الإيراد"],
            [[("text", p.sku), ("text", p.name), ("int", p.quantity_sold), ("money", p.revenue)] for p in s.top_products],
        ),
        (
            "العملاء",
            ["العميل", "عدد الأوامر", "الإجمالي"],
            [[("text", c.customer_name), ("int", c.orders), ("money", c.total)] for c in s.by_customer],
        ),
        (
            "الكاشير",
            ["الكاشير", "عدد الأوامر", "الإجمالي"],
            [[("text", c.username or "غير مسجّل"), ("int", c.orders), ("money", c.total)] for c in s.by_cashier],
        ),
        (
            "مورد الصنف",
            ["المورد", "عدد الأوامر", "الإجمالي"],
            [[("text", c.supplier_name), ("int", c.orders), ("money", c.total)] for c in s.by_product_supplier],
        ),
    ]
    content = exports.build_tables_xlsx("تقرير المبيعات", _range_label(s), tables)
    return _xlsx_response(content, f"report-sales-{_file_range(s)}.xlsx")


# ---------------------------------------------------------------- profit
def _profit_summary(db: Session, date_from, date_to) -> schemas.ProfitSummary:
    """Gross profit = sales - returns - cost of the goods actually kept.

    Cost comes from the unit cost recorded on each sales line when it was sold, so later edits to a
    product's cost price don't rewrite history. Returns are dated by when they were made.
    """
    start, end = _period(date_from, date_to)
    SO, SI, P = models.SalesOrder, models.SalesOrderItem, models.Product
    RT, RI = models.SalesReturn, models.SalesReturnItem

    sold = (
        db.query(
            SI.product_id,
            func.sum(SI.quantity),
            func.sum(SI.quantity * SI.unit_price),
            func.sum(SI.quantity * SI.unit_cost),
        )
        .join(SO, SO.id == SI.order_id)
        .filter(SO.status == "confirmed", SO.updated_at >= start, SO.updated_at < end)
        .group_by(SI.product_id)
        .all()
    )
    returned = (
        db.query(
            RI.product_id,
            func.sum(RI.quantity),
            func.sum(RI.quantity * RI.unit_price),
            func.sum(RI.quantity * SI.unit_cost),
        )
        .join(RT, RT.id == RI.return_id)
        .join(SI, SI.id == RI.order_item_id)
        .filter(RT.created_at >= start, RT.created_at < end)
        .group_by(RI.product_id)
        .all()
    )
    agg = {}
    sales_total = returns_total = ZERO
    for pid, qty, rev, cost in sold:
        a = agg.setdefault(pid, [0, ZERO, ZERO])
        a[0] += int(qty); a[1] += _money(rev); a[2] += _money(cost)
        sales_total += _money(rev)
    for pid, qty, rev, cost in returned:
        a = agg.setdefault(pid, [0, ZERO, ZERO])
        a[0] -= int(qty); a[1] -= _money(rev); a[2] -= _money(cost)
        returns_total += _money(rev)

    names = {
        r.id: r for r in db.query(P.id, P.sku, P.name).filter(P.id.in_(list(agg) or [-1])).all()
    }

    def margin(profit, revenue):
        return (profit * 100 / revenue).quantize(Decimal("0.1")) if revenue else None

    rows = [
        schemas.ProfitRow(
            product_id=pid,
            sku=names[pid].sku,
            name=names[pid].name,
            quantity=qty,
            revenue=rev,
            cost=cost,
            profit=rev - cost,
            margin_pct=margin(rev - cost, rev),
        )
        for pid, (qty, rev, cost) in agg.items()
        if pid in names
    ]
    rows.sort(key=lambda r: (-r.profit, r.product_id))
    revenue = sum((r.revenue for r in rows), ZERO)
    cost = sum((r.cost for r in rows), ZERO)
    return schemas.ProfitSummary(
        date_from=start,
        date_to=end - timedelta(microseconds=1),
        sales=sales_total,
        returns=returns_total,
        revenue=revenue,
        cost=cost,
        profit=revenue - cost,
        margin_pct=margin(revenue - cost, revenue),
        by_product=rows,
    )


@router.get("/profit", response_model=schemas.ProfitSummary)
def profit_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """Gross profit for a period (default: last 30 days), total and per product."""
    return _profit_summary(db, date_from, date_to)


@router.get("/profit/xlsx")
def profit_xlsx(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    s = _profit_summary(db, date_from, date_to)
    tables = [
        (
            "الملخص",
            ["البند", "القيمة"],
            [
                [("text", "المبيعات"), ("money", s.sales)],
                [("text", "المرتجعات"), ("money", s.returns)],
                [("text", "صافي الإيراد"), ("money", s.revenue)],
                [("text", "تكلفة البضاعة المباعة"), ("money", s.cost)],
                [("text", "مجمل الربح"), ("money", s.profit)],
                [("text", "هامش الربح %"), ("text", "—" if s.margin_pct is None else str(s.margin_pct))],
            ],
        ),
        (
            "حسب المنتج",
            ["الكود", "المنتج", "الكمية", "الإيراد", "التكلفة", "الربح", "الهامش %"],
            [
                [
                    ("text", r.sku),
                    ("text", r.name),
                    ("int", r.quantity),
                    ("money", r.revenue),
                    ("money", r.cost),
                    ("money", r.profit),
                    ("text", "—" if r.margin_pct is None else str(r.margin_pct)),
                ]
                for r in s.by_product
            ],
        ),
    ]
    content = exports.build_tables_xlsx("تقرير الأرباح", _range_label(s), tables)
    return _xlsx_response(content, f"report-profit-{_file_range(s)}.xlsx")


# ---------------------------------------------------------------- purchases
def _purchases_summary(db: Session, date_from, date_to, top: int) -> schemas.PurchasesSummary:
    start, end = _period(date_from, date_to)
    PO, PI, P, S = models.PurchaseOrder, models.PurchaseOrderItem, models.Product, models.Supplier
    in_period = (PO.status == "received", PO.updated_at >= start, PO.updated_at < end)

    orders, total = db.query(func.count(PO.id), func.coalesce(func.sum(PO.total_amount), 0)).filter(*in_period).one()

    day = func.date(PO.updated_at)
    by_day = (
        db.query(day, func.count(PO.id), func.coalesce(func.sum(PO.total_amount), 0))
        .filter(*in_period)
        .group_by(day)
        .order_by(day)
        .all()
    )

    spend = func.sum(PI.quantity * PI.unit_cost)
    top_rows = (
        db.query(P.id, P.sku, P.name, func.sum(PI.quantity), spend)
        .join(PI, PI.product_id == P.id)
        .join(PO, PO.id == PI.order_id)
        .filter(*in_period)
        .group_by(P.id, P.sku, P.name)
        .order_by(spend.desc(), P.id)
        .limit(top)
        .all()
    )

    sup_total = func.sum(PO.total_amount)
    sup_rows = (
        db.query(S.id, S.name, func.count(PO.id), sup_total)
        .join(PO, PO.supplier_id == S.id)
        .filter(*in_period)
        .group_by(S.id, S.name)
        .order_by(sup_total.desc(), S.id)
        .limit(top)
        .all()
    )
    return schemas.PurchasesSummary(
        date_from=start,
        date_to=end - timedelta(microseconds=1),
        orders=orders,
        total=_money(total),
        by_day=[schemas.SalesByDay(day=str(d), orders=n, total=_money(t)) for d, n, t in by_day],
        top_products=[
            schemas.PurchaseTopProduct(product_id=pid, sku=sku, name=name, quantity_bought=int(q), spend=_money(sp))
            for pid, sku, name, q, sp in top_rows
        ],
        by_supplier=[
            schemas.PurchaseBySupplier(supplier_id=sid, supplier_name=sname, orders=n, total=_money(t))
            for sid, sname, n, t in sup_rows
        ],
    )


@router.get("/purchases-summary", response_model=schemas.PurchasesSummary)
def purchases_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    top: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """Received purchases in a period (default: last 30 days): totals, per-day series, top products and suppliers."""
    return _purchases_summary(db, date_from, date_to, top)


@router.get("/purchases-summary/xlsx")
def purchases_summary_xlsx(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    top: int = Query(50, ge=1, le=50),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    s = _purchases_summary(db, date_from, date_to, top)
    tables = [
        ("الملخص", ["البند", "القيمة"], [[("text", "عدد الأوامر المستلمة"), ("int", s.orders)], [("text", "إجمالي المشتريات"), ("money", s.total)]]),
        ("المشتريات اليومية", ["اليوم", "عدد الأوامر", "الإجمالي"], [[("text", d.day), ("int", d.orders), ("money", d.total)] for d in s.by_day]),
        (
            "المنتجات",
            ["الكود", "المنتج", "الكمية المشتراة", "الإنفاق"],
            [[("text", p.sku), ("text", p.name), ("int", p.quantity_bought), ("money", p.spend)] for p in s.top_products],
        ),
        (
            "الموردون",
            ["المورد", "عدد الأوامر", "الإجمالي"],
            [[("text", x.supplier_name), ("int", x.orders), ("money", x.total)] for x in s.by_supplier],
        ),
    ]
    content = exports.build_tables_xlsx("تقرير المشتريات", _range_label(s), tables)
    return _xlsx_response(content, f"report-purchases-{_file_range(s)}.xlsx")


# ---------------------------------------------------------------- receivables / payables
def _balances_report(db: Session, kind: str) -> schemas.BalancesReport:
    """Parties with a non-zero balance, largest first. `total` counts only money still owed (positive
    balances); credits (negative balances) are listed but not netted against it."""
    party = models.Customer if kind == "customer" else models.Supplier
    balances = accounts.party_balances(db, kind)
    info = {p.id: p for p in db.query(party).filter(party.id.in_(list(balances) or [0])).all()}
    rows = [
        schemas.BalanceRow(party_id=pid, name=info[pid].name, phone=info[pid].phone, balance=bal)  # type: ignore
        for pid, bal in balances.items()
        if bal != 0 and pid in info
    ]
    rows.sort(key=lambda r: (-r.balance, r.party_id))
    return schemas.BalancesReport(total=sum((r.balance for r in rows if r.balance > 0), ZERO), rows=rows)


def _balances_xlsx(report: schemas.BalancesReport, title: str, party_label: str, filename: str) -> Response:
    table = (
        title,
        [party_label, "الهاتف", "الرصيد"],
        [[("text", r.name), ("text", r.phone or ""), ("money", r.balance)] for r in report.rows]
        + [[("text", "إجمالي المستحق"), ("text", ""), ("money", report.total)]],
    )
    return _xlsx_response(exports.build_tables_xlsx(title, exports.fmt_dt(datetime.now(timezone.utc)), [table]), filename)


@router.get("/receivables", response_model=schemas.BalancesReport)
def receivables(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    """What customers owe us (opening balance + confirmed sales - receipts)."""
    return _balances_report(db, "customer")


@router.get("/receivables/xlsx")
def receivables_xlsx(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    return _balances_xlsx(_balances_report(db, "customer"), "الذمم المدينة (مستحقات العملاء)", "العميل", "report-receivables.xlsx")


@router.get("/payables", response_model=schemas.BalancesReport)
def payables(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    """What we owe suppliers (opening balance + received purchases - payments)."""
    return _balances_report(db, "supplier")


@router.get("/payables/xlsx")
def payables_xlsx(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    return _balances_xlsx(_balances_report(db, "supplier"), "الذمم الدائنة (مستحقات الموردين)", "المورد", "report-payables.xlsx")


def _aging_xlsx(report: schemas.AgingReport, title: str, party_label: str, filename: str) -> Response:
    head = [party_label, "الهاتف", "أول المدة", "0-30 يوماً", "31-60 يوماً", "61-90 يوماً", "أكثر من 90", "الإجمالي"]
    body = [
        [("text", r.name), ("text", r.phone or ""), ("money", r.opening), ("money", r.current), ("money", r.d31_60), ("money", r.d61_90), ("money", r.d90_plus), ("money", r.total)]
        for r in report.rows
    ]
    foot = [("text", "الإجمالي"), ("text", ""), ("money", report.total_opening), ("money", report.total_current), ("money", report.total_d31_60), ("money", report.total_d61_90), ("money", report.total_d90_plus), ("money", report.total_total)]
    return _xlsx_response(exports.build_tables_xlsx(f"{title} — حتى {report.as_of}", exports.fmt_dt(datetime.now(timezone.utc)), [(title, head, body + [foot])]), filename)


@router.get("/receivables/aging", response_model=schemas.AgingReport)
def receivables_aging(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    return accounts.build_aging(db, "customer")


@router.get("/receivables/aging/xlsx")
def receivables_aging_xlsx(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    return _aging_xlsx(accounts.build_aging(db, "customer"), "أعمار ديون العملاء", "العميل", "report-receivables-aging.xlsx")


@router.get("/payables/aging", response_model=schemas.AgingReport)
def payables_aging(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    return accounts.build_aging(db, "supplier")


@router.get("/payables/aging/xlsx")
def payables_aging_xlsx(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    return _aging_xlsx(accounts.build_aging(db, "supplier"), "أعمار ديون الموردين", "المورد", "report-payables-aging.xlsx")


# ---------------------------------------------------------------- اقتراحات الشراء
def _purchase_suggestion_rows(db: Session, warehouse_id: Optional[int] = None, supplier_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """ما ينبغي طلبه الآن: الهدف (حد المخزن الخاص أو العام) − المتاح، بتكلفة المتوسط المرجح."""
    PS = models.ProductStock
    products = db.query(models.Product).filter(models.Product.is_active.is_(True)).all()
    supplier_names = dict(db.query(models.Supplier.id, models.Supplier.name).all())
    warehouse_mins: dict = {}
    compared: Dict[int, float] = {}
    if warehouse_id:
        warehouse_mins = {
            pid: float(mn) for pid, mn in db.query(PS.product_id, PS.min_level)
            .filter(PS.warehouse_id == warehouse_id, PS.min_level.isnot(None)).all()
        }
        compared = dict(db.query(PS.product_id, PS.quantity).filter(PS.warehouse_id == warehouse_id).all())
    rows: List[Dict[str, Any]] = []
    for p in products:
        if supplier_id and p.supplier_id != supplier_id:
            continue
        available = float(compared.get(p.id, 0)) if warehouse_id else float(p.quantity or 0)
        target = warehouse_mins.get(p.id) if (warehouse_id and p.id in warehouse_mins) else float(p.reorder_level or 0)
        suggested = max(target - available, 0.0)
        if suggested <= 0:
            continue
        rows.append({
            "product_id": p.id,
            "sku": p.sku,
            "name": p.name,
            "unit": p.unit,
            "available": available,
            "target": target,
            "suggested_qty": suggested,
            "cost_price": float(p.cost_price or 0),
            "estimated_cost": round(suggested * float(p.cost_price or 0), 2),
            "supplier_id": p.supplier_id,
            "supplier_name": supplier_names.get(p.supplier_id),
        })
    rows.sort(key=lambda r: -r["estimated_cost"])
    return rows


@router.get("/purchase-suggestions")
def purchase_suggestions(
    warehouse_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """اقتراحات الشراء: ما دون حد الطلب (يحترم حد المخزن الخاص) بكمية مقترحة وتكلفة تقديرية."""
    return _purchase_suggestion_rows(db, warehouse_id, supplier_id)


@router.get("/purchase-suggestions/xlsx")
def purchase_suggestions_xlsx(
    warehouse_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    rows = _purchase_suggestion_rows(db, warehouse_id, supplier_id)
    tables = [(
        "اقتراحات الشراء",
        ["الكود", "الصنف", "المتاح", "حد الطلب", "الكمية المقترحة", "التكلفة", "التكلفة التقديرية", "المورد"],
        [[
            ("text", r["sku"]), ("text", r["name"]), ("int", r["available"]), ("int", r["target"]),
            ("int", r["suggested_qty"]), ("money", r["cost_price"]), ("money", r["estimated_cost"]),
            ("text", r["supplier_name"] or "—"),
        ] for r in rows],
    )]
    total = sum(r["estimated_cost"] for r in rows)
    content = exports.build_tables_xlsx("اقتراحات الشراء", f"إجمالي تقديري: {total:,.2f}", tables)
    return _xlsx_response(content, "report-purchase-suggestions.xlsx")


# ---------------------------------------------------------------- لوطات تنتهي قريبًا
@router.get("/lots-expiring")
def lots_expiring(
    days: int = Query(30, ge=1, le=365),
    warehouse_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """لوطات كميتها المتبقية > 0 وتاريخ انتهائها خلال `days` يومًا (أو انتهت بالفعل)."""
    L, P, WH = models.StockLot, models.Product, models.Warehouse
    from ..accounting import local_today
    cutoff = local_today() + timedelta(days=days)
    q = (
        db.query(L, P.sku, P.name, WH.name)
        .join(P, P.id == L.product_id)
        .outerjoin(WH, WH.id == L.warehouse_id)
        .filter(
            L.company_id == db.info["company_id"],
            L.expiry_date.isnot(None),
            L.expiry_date <= cutoff,
            L.qty_remaining > 0,
        )
    )
    if warehouse_id:
        q = q.filter(L.warehouse_id == warehouse_id)
    rows = []
    for lot, sku, pname, wname in q.order_by(L.expiry_date).all():
        rows.append({
            "lot_id": lot.id,
            "product_id": lot.product_id,
            "sku": sku,
            "product_name": pname,
            "warehouse_name": wname,
            "lot_code": lot.lot_code,
            "expiry_date": str(lot.expiry_date),
            "days_left": (lot.expiry_date - local_today()).days,
            "qty_remaining": float(lot.qty_remaining),
            "expired": bool(lot.expiry_date < local_today()),
        })
    return rows


@router.get("/lots-expiring/xlsx")
def lots_expiring_xlsx(
    days: int = Query(30, ge=1, le=365),
    warehouse_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    from fastapi import Query as _Q
    rows = lots_expiring(days=days, warehouse_id=warehouse_id, db=db)
    tables = [(
        "لوطات تنتهي قريبًا",
        ["الكود", "الصنف", "المخزن", "اللوط", "تاريخ الانتهاء", "أيام متبقية", "الحالة", "الكمية المتبقية"],
        [[
            ("text", r["sku"]), ("text", r["product_name"]), ("text", r["warehouse_name"] or "—"),
            ("text", r["lot_code"]), ("text", r["expiry_date"]),
            ("int", r["days_left"]), ("text", "منتهي ⚠️" if r["expired"] else "ساري"),
            ("int", r["qty_remaining"]),
        ] for r in rows],
    )]
    content = exports.build_tables_xlsx("لوطات تنتهي قريبًا", f"خلال {days} يوم", tables)
    return _xlsx_response(content, "report-lots-expiring.xlsx")


# ---------------------------------------------------------------- حركات المخزون
def _stock_movement_rows(db: Session, product_id, warehouse_id, reason, date_from, date_to, skip=0, limit=100):
    """سجل حركات المخزون المركزي بفلاتر (صنف/مخزن/سبب/فترة) — الأحدث أولًا."""
    M, P, WH = models.StockMovement, models.Product, models.Warehouse
    q = db.query(M, P.sku, P.name, WH.name).join(P, P.id == M.product_id).outerjoin(WH, WH.id == M.warehouse_id)
    q = q.filter(M.company_id == db.info["company_id"])
    if product_id:
        q = q.filter(M.product_id == product_id)
    if warehouse_id:
        q = q.filter(M.warehouse_id == warehouse_id)
    if reason:
        q = q.filter(M.reason == reason)
    if date_from:
        q = q.filter(M.created_at >= datetime(date_from.year, date_from.month, date_from.day))
    if date_to:
        q = q.filter(M.created_at < datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1))
    total = q.count()
    rows = []
    for m, sku, pname, wname in q.order_by(M.id.desc()).offset(skip).limit(limit).all():
        rows.append({
            "id": m.id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "product_id": m.product_id,
            "sku": sku,
            "product_name": pname,
            "warehouse_id": m.warehouse_id,
            "warehouse_name": wname,
            "reason": m.reason,
            "reference": m.reference,
            "change": float(m.change),
        })
    return rows, total


@router.get("/writeoffs")
def writeoffs_report(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """تقرير الهالك/الإعدام: حركات lot-writeoff مجمعة بالصنف للفترة —
    الكمية وعدد الحركات والقيمة بتكلفة الصنف."""
    M, P = models.StockMovement, models.Product
    start_day = date_from or date.today().replace(day=1)
    end_day = date_to or date.today()
    if start_day > end_day:
        raise HTTPException(422, "date_from must not be after date_to")
    start = datetime(start_day.year, start_day.month, start_day.day)
    end = datetime(end_day.year, end_day.month, end_day.day) + timedelta(days=1)

    rows_q = (
        db.query(M.product_id, P.sku, P.name, P.cost_price,
                 func.sum(-M.change).label("qty"), func.count(M.id).label("moves"))
        .join(P, P.id == M.product_id)
        .filter(
            M.company_id == db.info["company_id"],
            M.reason == "lot-writeoff",
            M.change < 0,
            M.created_at >= start,
            M.created_at < end,
        )
        .group_by(M.product_id, P.sku, P.name, P.cost_price)
        .order_by(func.sum(-M.change).desc())
        .all()
    )
    rows = []
    total_value = 0.0
    total_qty = 0.0
    for pid, sku, name, cost, qty_sum, moves in rows_q:
        unit_cost = float(cost or 0)
        q = float(qty_sum or 0)
        value = q * unit_cost
        total_value += value
        total_qty += q
        rows.append({
            "product_id": pid, "sku": sku, "product_name": name,
            "unit_cost": unit_cost, "qty": q, "movements": int(moves or 0),
            "value": round(value, 2),
        })
    return {
        "date_from": str(start_day), "date_to": str(end_day),
        "rows": rows, "total_qty": round(total_qty, 3), "total_value": round(total_value, 2),
    }


@router.get("/writeoffs/xlsx")
def writeoffs_xlsx(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    r = writeoffs_report(date_from, date_to, db, None)  # المعامل الرابع غير مستخدم داخل الدالة
    tables = [(
        "الهالك/الإعدام",
        ["الكود", "الصنف", "تكلفة الوحدة", "الكمية", "عدد الحركات", "القيمة"],
        [
            [("text", row["sku"]), ("text", row["product_name"]), ("money", row["unit_cost"]),
             ("int", row["qty"]), ("int", row["movements"]), ("money", row["value"])]
            for row in r["rows"]
        ] + [
            [("text", ""), ("text", "الإجمالي"), ("text", ""), ("int", r["total_qty"]), ("text", ""), ("money", r["total_value"])],
        ],
    )]
    return _xlsx_response(
        exports.build_tables_xlsx("تقرير الهالك", f"{r['date_from']} → {r['date_to']}", tables),
        f"report-writeoffs-{r['date_from']}_{r['date_to']}.xlsx",
    )


@router.get("/stock-movements")
def stock_movements(
    response: Response,
    product_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    reason: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = 0,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    rows, total = _stock_movement_rows(db, product_id, warehouse_id, reason, date_from, date_to, skip, limit)
    response.headers["X-Total-Count"] = str(total)
    return rows


@router.get("/stock-movements/xlsx")
def stock_movements_xlsx(
    product_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    reason: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    rows, _total = _stock_movement_rows(db, product_id, warehouse_id, reason, date_from, date_to, 0, 5000)
    tables = [(
        "حركات المخزون",
        ["التاريخ", "الكود", "الصنف", "المخزن", "السبب", "المرجع", "التغيير"],
        [[
            ("text", (r["created_at"] or "")[:16]), ("text", r["sku"]), ("text", r["product_name"]),
            ("text", r["warehouse_name"] or "—"), ("text", r["reason"]), ("text", r["reference"] or "—"),
            ("int", r["change"]),
        ] for r in rows],
    )]
    content = exports.build_tables_xlsx("حركات المخزون", f"{len(rows)} حركة", tables)
    return _xlsx_response(content, "report-stock-movements.xlsx")


# ---------------------------------------------------------------- dashboard
# ---------------------------------------------------------------- عمولات المندوبين
@router.get("/reps-commissions")
def reps_commissions(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """عمولات المندوبين للفترة: صافي المبيعات (بعد المرتجعات) × نسبة العمولة.

    المرتجع يُخصم من مندوب الفاتورة الأصلية (rep_id محفوظ على المرتجع)."""
    if date_from is None and date_to is None:
        date_from = date.today() - timedelta(days=days - 1)
    SO, SI = models.SalesOrder, models.SalesOrderItem
    SR = models.SalesReturn
    in_period = (SO.status == "confirmed", SO.updated_at >= _period(date_from, date_to, default_days=days)[0],
                 SO.updated_at < _period(date_from, date_to, default_days=days)[1])
    reps = {r.id: r for r in db.query(models.SalesRep).filter(models.SalesRep.company_id == db.info["company_id"]).all()}
    # المبيعات: (rep_id → صافي مبيعات مُجمّعة من بنود الأوامر المؤكدة)
    sales_q = (
        db.query(SO.rep_id, func.coalesce(func.sum(func.coalesce(SI.quantity * SI.unit_price, 0)), 0))
        .join(SI, SI.order_id == SO.id)
        .filter(*in_period, SO.rep_id.isnot(None))
        .group_by(SO.rep_id)
        .all()
    )
    # المرتجعات في نفس الفترة (على مندوب الفاتورة)
    ret_start, ret_end = _period(date_from, date_to, default_days=days)
    returns_q = (
        db.query(SR.rep_id, func.coalesce(func.sum(SR.total_amount - SR.refund_amount), 0))
        .filter(
            SR.company_id == db.info["company_id"],
            SR.created_at >= ret_start, SR.created_at < ret_end,
            SR.rep_id.isnot(None),
        )
        .group_by(SR.rep_id)
        .all()
    )
    returns_map = {rid: float(v) for rid, v in returns_q}
    rows = []
    for rid, gross in sales_q:
        rep = reps.get(rid)
        if rep is None:
            continue
        gross_f = float(gross)
        net = gross_f - returns_map.get(rid, 0.0)
        pct = float(rep.commission_percent or 0)
        rows.append({
            "rep_id": rid,
            "rep_name": rep.name,
            "commission_percent": pct,
            "gross_sales": round(gross_f, 2),
            "returns": round(returns_map.get(rid, 0.0), 2),
            "net_sales": round(net, 2),
            "commission_amount": round(net * pct / 100.0, 2),
        })
    rows.sort(key=lambda r: -r["commission_amount"])
    return rows


@router.get("/reps-commissions/xlsx")
def reps_commissions_xlsx(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    rows = reps_commissions(date_from, date_to, days, db)
    tables = [(
        "عمولات المندوبين",
        ["المندوب", "النسبة %", "المبيعات", "المرتجعات", "الصافي", "العمولة المستحقة"],
        [[
            ("text", r["rep_name"]), ("int", r["commission_percent"]),
            ("money", r["gross_sales"]), ("money", r["returns"]),
            ("money", r["net_sales"]), ("money", r["commission_amount"]),
        ] for r in rows],
    )]
    total = sum(r["commission_amount"] for r in rows)
    content = exports.build_tables_xlsx("عمولات المندوبين", f"إجمالي مستحق: {total:,.2f}", tables)
    return _xlsx_response(content, "report-reps-commissions.xlsx")


# ---------------------------------------------------------------- أرصدة العملاء الدائنة
@router.get("/customer-credits")
def customer_credits(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """عملاء عندهم رصيد دائن (دفعوا زيادة / دفعة مقدمة غير مستهلكة) — مرشح للسداد أو الخصم من فاتورة قادمة."""
    from ..accounts import party_balances
    customers = db.query(models.Customer).filter(models.Customer.company_id == db.info["company_id"], models.Customer.is_active.is_(True)).all()
    balances = party_balances(db, "customer", [c.id for c in customers] or [0])
    rows = []
    for c in customers:
        bal = float(balances.get(c.id, 0) or 0)
        if bal < -0.009:
            rows.append({
                "customer_id": c.id, "name": c.name, "code": c.code,
                "credit_balance": round(-bal, 2),
                "price_list": (c.price_list.name if getattr(c, "price_list", None) else None),
            })
    rows.sort(key=lambda r: -r["credit_balance"])
    return rows


@router.get("/customer-credits/xlsx")
def customer_credits_xlsx(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    rows = customer_credits(db)
    tables = [(
        "أرصدة العملاء الدائنة",
        ["الكود", "العميل", "قائمة الأسعار", "الرصيد الدائن"],
        [[("text", r["code"] or "—"), ("text", r["name"]), ("text", r["price_list"] or "—"), ("money", r["credit_balance"])] for r in rows],
    )]
    total = sum(r["credit_balance"] for r in rows)
    content = exports.build_tables_xlsx("أرصدة العملاء الدائنة", f"الإجمالي: {total:,.2f}", tables)
    return _xlsx_response(content, "report-customer-credits.xlsx")


@router.get("/dashboard", response_model=schemas.Dashboard)
def dashboard(
    days: int = Query(30, ge=1, le=366),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """Headline numbers for the home screen. Sales/purchase totals cover the last `days` days,
    or the explicit range [date_from, date_to] when provided."""
    if date_from is not None or date_to is not None:
        start, end = _period(date_from, date_to, default_days=days)
        span_days = max((end.date() - start.date()).days, 1)
    else:
        start, end = _period(None, None, default_days=days)
        span_days = days
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

    # Base queries
    so_q = db.query(SO).filter(SO.status == "confirmed", SO.updated_at >= start, SO.updated_at < end)
    po_q = db.query(PO).filter(PO.status == "received", PO.updated_at >= start, PO.updated_at < end)
    # Note: branch_id filtering is not supported (SalesOrder/PurchaseOrder have no branch_id column);
    # the parameter is accepted for API compatibility but ignored.

    s_orders = so_q.with_entities(func.count(SO.id)).scalar() or 0
    s_total = so_q.with_entities(func.coalesce(func.sum(func.coalesce(SO.subtotal, SO.total_amount)), 0)).scalar() or 0
    p_orders = po_q.with_entities(func.count(PO.id)).scalar() or 0
    p_total = po_q.with_entities(func.coalesce(func.sum(PO.total_amount), 0)).scalar() or 0

    # Previous period for growth % calculation
    prev_start = start - timedelta(days=span_days)
    prev_so_q = db.query(SO).filter(SO.status == "confirmed", SO.updated_at >= prev_start, SO.updated_at < start)
    prev_po_q = db.query(PO).filter(PO.status == "received", PO.updated_at >= prev_start, PO.updated_at < start)
    prev_s_total = prev_so_q.with_entities(func.coalesce(func.sum(func.coalesce(SO.subtotal, SO.total_amount)), 0)).scalar() or 0
    prev_p_total = prev_po_q.with_entities(func.coalesce(func.sum(PO.total_amount), 0)).scalar() or 0

    def growth_pct(current, prev):
        c, p = float(current), float(prev)
        if p > 0:
            return round(((c - p) / p) * 100, 1)
        return None

    s_ret = db.query(func.coalesce(func.sum(models.SalesReturn.total_amount), 0)).filter(models.SalesReturn.created_at >= start, models.SalesReturn.created_at < end).scalar()
    p_ret = db.query(func.coalesce(func.sum(models.PurchaseReturn.total_amount), 0)).filter(models.PurchaseReturn.created_at >= start, models.PurchaseReturn.created_at < end).scalar()

    # Cash liquidity: sum of all safe & bank balances
    safes_total = db.query(func.coalesce(func.sum(models.Safe.balance), 0)).scalar() or 0
    banks_total = db.query(func.coalesce(func.sum(models.Bank.balance), 0)).scalar() or 0

    # Pending stock transfers
    pending_transfers = (
        db.query(func.count(models.StockTransfer.id))
        .filter(models.StockTransfer.status == "pending")
        .scalar() or 0
    )

    # شيكات تستحق قريبًا (مقبوضة تحت التحصيل خلال CHEQUES_DUE_DAYS أيام)
    from datetime import timedelta as _td
    from ..accounting import local_today
    due_limit = local_today() + _td(days=7)
    cheques_due_soon = (
        db.query(func.count(models.Cheque.id))
        .filter(
            models.Cheque.status == "under_collection",
            models.Cheque.due_date.isnot(None),
            models.Cheque.due_date <= due_limit,
        )
        .scalar() or 0
    )
    lots_expiring_soon = (
        db.query(func.count(models.StockLot.id))
        .filter(
            models.StockLot.expiry_date.isnot(None),
            models.StockLot.expiry_date <= local_today() + _td(days=30),
            models.StockLot.qty_remaining > 0,
        )
        .scalar() or 0
    )
    recurring_journals_due = (
        db.query(func.count(models.RecurringJournal.id))
        .filter(
            models.RecurringJournal.is_active.is_(True),
            models.RecurringJournal.next_run_date <= local_today(),
        )
        .scalar() or 0
    )
    pending_journal_approvals = (
        db.query(func.count(models.JournalEntry.id))
        .filter(models.JournalEntry.status == "pending_approval")
        .scalar() or 0
    )

    return schemas.Dashboard(
        period_days=span_days,
        sales_returns_total=_money(s_ret),
        purchase_returns_total=_money(p_ret),
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
        receivables_total=_balances_report(db, "customer").total,
        payables_total=_balances_report(db, "supplier").total,
        stale_shifts=db.query(func.count(models.Shift.id)).filter(models.Shift.status == "open", models.Shift.opened_at < stale_cutoff()).scalar() or 0,
        sales_growth_pct=growth_pct(s_total, prev_s_total),
        purchases_growth_pct=growth_pct(p_total, prev_p_total),
        pending_transfers=pending_transfers,
        safes_balance_total=_money(safes_total),
        banks_balance_total=_money(banks_total),
        cash_liquidity_total=_money(float(safes_total) + float(banks_total)),
        lots_expiring_soon=lots_expiring_soon,
        cheques_due_soon=cheques_due_soon,
        recurring_journals_due=recurring_journals_due,
        pending_journal_approvals=pending_journal_approvals,
    )
