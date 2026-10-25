"""Read-only reports. All figures are computed in SQL.

Only *confirmed* sales and *received* purchases count towards totals; drafts and cancelled
orders never do. An order is dated by when it was confirmed / received (its `updated_at`, which
is stamped by that transition and never changes afterwards), not by when the draft was created.
Dates are interpreted as UTC. Each report is also available as an Excel download (`.../xlsx`).
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import accounts, exports, models, schemas
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
def _low_stock_rows(db: Session) -> List[schemas.LowStockItem]:
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


@router.get("/low-stock", response_model=List[schemas.LowStockItem])
def low_stock(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """Active products at or below their reorder level, most urgent first."""
    return _low_stock_rows(db)


@router.get("/low-stock/xlsx")
def low_stock_xlsx(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = _low_stock_rows(db)
    wh = {w.id: w.name for w in db.query(models.Warehouse).all()}
    sup = {s.id: s.name for s in db.query(models.Supplier).all()}
    table = (
        "نقص المخزون",
        ["الكود", "المنتج", "المخزن", "المورد", "المتاح", "حد إعادة الطلب", "العجز"],
        [
            [
                ("text", r.sku),
                ("text", r.name),
                ("text", wh.get(r.warehouse_id, "—")),
                ("text", sup.get(r.supplier_id, "—")),
                ("int", r.quantity),
                ("int", r.reorder_level),
                ("int", r.shortfall),
            ]
            for r in rows
        ],
    )
    content = exports.build_tables_xlsx("تقرير نقص المخزون", exports.fmt_dt(datetime.now(timezone.utc)), [table])
    return _xlsx_response(content, "report-low-stock.xlsx")


# ---------------------------------------------------------------- inventory valuation
def _valuation_rows(db: Session) -> List[schemas.InventoryValuationRow]:
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


@router.get("/inventory-valuation", response_model=List[schemas.InventoryValuationRow])
def inventory_valuation(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    """Stock value per warehouse at cost price and at sale price (active products only)."""
    return _valuation_rows(db)


@router.get("/inventory-valuation/xlsx")
def inventory_valuation_xlsx(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    rows = _valuation_rows(db)
    P = models.Product
    products = (
        db.query(P, models.Warehouse.name)
        .outerjoin(models.Warehouse, models.Warehouse.id == P.warehouse_id)
        .filter(P.is_active.is_(True))
        .order_by(P.name)
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
                    ("text", wname or "—"),
                    ("int", p.quantity),
                    ("money", p.cost_price),
                    ("money", p.sale_price),
                    ("money", p.cost_price * p.quantity),
                    ("money", p.sale_price * p.quantity),
                ]
                for p, wname in products
            ],
        ),
    ]
    content = exports.build_tables_xlsx("تقرير قيمة المخزون", exports.fmt_dt(datetime.now(timezone.utc)), tables)
    return _xlsx_response(content, "report-inventory-valuation.xlsx")


# ---------------------------------------------------------------- sales
def _sales_summary(db: Session, date_from, date_to, top: int) -> schemas.SalesSummary:
    start, end = _period(date_from, date_to)
    SO, SI, P, C = models.SalesOrder, models.SalesOrderItem, models.Product, models.Customer
    in_period = (SO.status == "confirmed", SO.updated_at >= start, SO.updated_at < end)

    orders, total = db.query(func.count(SO.id), func.coalesce(func.sum(SO.total_amount), 0)).filter(*in_period).one()

    day = func.date(SO.updated_at)
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

    cust_total = func.sum(SO.total_amount)
    cust_rows = (
        db.query(C.id, C.name, func.count(SO.id), cust_total)
        .join(SO, SO.customer_id == C.id)
        .filter(*in_period)
        .group_by(C.id, C.name)
        .order_by(cust_total.desc(), C.id)
        .limit(top)
        .all()
    )
    U = models.User
    cashier_total = func.sum(SO.total_amount)
    cashier_rows = (
        db.query(U.username, func.count(SO.id), cashier_total)
        .select_from(SO)
        .outerjoin(U, U.id == SO.created_by)
        .filter(*in_period)
        .group_by(U.username)
        .order_by(cashier_total.desc(), U.username)
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
    )


@router.get("/sales-summary", response_model=schemas.SalesSummary)
def sales_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    top: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    """Confirmed sales in a period (default: last 30 days): totals, per-day series, top products and customers."""
    return _sales_summary(db, date_from, date_to, top)


@router.get("/sales-summary/xlsx")
def sales_summary_xlsx(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    top: int = Query(50, ge=1, le=50),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    s = _sales_summary(db, date_from, date_to, top)
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
    ]
    content = exports.build_tables_xlsx("تقرير المبيعات", _range_label(s), tables)
    return _xlsx_response(content, f"report-sales-{_file_range(s)}.xlsx")


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
        schemas.BalanceRow(party_id=pid, name=info[pid].name, phone=info[pid].phone, balance=bal)
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


# ---------------------------------------------------------------- dashboard
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
        .filter(SO.status == "confirmed", SO.updated_at >= start, SO.updated_at < end)
        .one()
    )
    p_orders, p_total = (
        db.query(func.count(PO.id), func.coalesce(func.sum(PO.total_amount), 0))
        .filter(PO.status == "received", PO.updated_at >= start, PO.updated_at < end)
        .one()
    )
    s_ret = db.query(func.coalesce(func.sum(models.SalesReturn.total_amount), 0)).filter(models.SalesReturn.created_at >= start, models.SalesReturn.created_at < end).scalar()
    p_ret = db.query(func.coalesce(func.sum(models.PurchaseReturn.total_amount), 0)).filter(models.PurchaseReturn.created_at >= start, models.PurchaseReturn.created_at < end).scalar()
    return schemas.Dashboard(
        period_days=days,
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
    )
