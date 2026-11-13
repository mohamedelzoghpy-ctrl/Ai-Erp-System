"""Financial reports — fast single-query versions + VAT return + PDF exports."""
from typing import List, Optional
from datetime import date, datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response as FastResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import exports, models, schemas, deps

router = APIRouter(prefix="/reports/financial", tags=["Financial Reports"])

_TWO_PLACES = Decimal("0.01")


def _q(value) -> Decimal:
    """تقريب مبلغ إلى منزلتين — SQLite قد يرجع float وPostgres يرجع Decimal."""
    return Decimal(str(value or 0)).quantize(_TWO_PLACES)


def _parse_date(value: Optional[str], default: Optional[date] = None) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date: {value}")
    return default or date.today()


def _balances_up_to(db: Session, company_id: int, as_of: date, types: Optional[List[str]] = None) -> dict:
    """صافي (مدين − دائن) لكل حساب حتى تاريخ معين — استعلام واحد مجمّع لكل الحسابات."""
    q = (
        db.query(
            models.JournalItem.account_id,
            func.coalesce(func.sum(models.JournalItem.debit), 0).label("d"),
            func.coalesce(func.sum(models.JournalItem.credit), 0).label("c"),
        )
        .join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id)
        .filter(models.JournalItem.company_id == company_id, models.JournalEntry.date <= as_of)
        .group_by(models.JournalItem.account_id)
    )
    if types:
        q = q.join(models.ChartAccount, models.ChartAccount.id == models.JournalItem.account_id).filter(
            models.ChartAccount.type.in_(types)
        )
    return {row.account_id: (Decimal(str(row.d)) - Decimal(str(row.c))) for row in q.all()}


def _signed(net: Decimal, acc_type: str) -> Decimal:
    """الرصيد بالإشارة المحاسبية: أصول/مصاريف موجبة مدينة، والباقي دائن."""
    return -net if acc_type in ("liability", "equity", "revenue") else net


@router.get("/trial-balance")
def get_trial_balance(
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    cutoff = _parse_date(as_of)
    accounts = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id,
        models.ChartAccount.is_group.is_(False),  # المجموعيات بلا ترحيل مباشر — تُستبعد
    ).all()
    nets = _balances_up_to(db, company_id, cutoff)
    return [
        {"code": a.code, "name": a.name, "balance": _q(_signed(nets.get(a.id, Decimal("0")), a.type)), "type": a.type}
        for a in accounts
    ]


@router.get("/profit-loss")
def get_profit_loss(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    start = _parse_date(date_from, date(1900, 1, 1))
    end = _parse_date(date_to, date.today())

    # استعلامان مجمّعان بدل حساب لكل حساب
    rev_q = db.query(func.coalesce(func.sum(models.JournalItem.credit - models.JournalItem.debit), 0)).join(
        models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id
    ).join(models.ChartAccount, models.ChartAccount.id == models.JournalItem.account_id).filter(
        models.JournalItem.company_id == company_id,
        models.ChartAccount.type == "revenue",
        models.ChartAccount.is_group.is_(False),
        models.JournalEntry.date >= start,
        models.JournalEntry.date <= end,
    ).scalar() or 0

    exp_q = db.query(func.coalesce(func.sum(models.JournalItem.debit - models.JournalItem.credit), 0)).join(
        models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id
    ).join(models.ChartAccount, models.ChartAccount.id == models.JournalItem.account_id).filter(
        models.JournalItem.company_id == company_id,
        models.ChartAccount.type == "expense",
        models.ChartAccount.is_group.is_(False),
        models.JournalEntry.date >= start,
        models.JournalEntry.date <= end,
    ).scalar() or 0

    return {
        "total_revenue": _q(rev_q),
        "total_expenses": _q(exp_q),
        "net_profit": _q(rev_q) - _q(exp_q),
        "date_from": str(start),
        "date_to": str(end),
    }


@router.get("/balance-sheet")
def get_balance_sheet(
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    cutoff = _parse_date(as_of)
    accounts = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.is_group.is_(False)
    ).all()
    nets = _balances_up_to(db, company_id, cutoff)
    assets = sum((_signed(nets.get(a.id, Decimal("0")), a.type) for a in accounts if a.type == "asset"), Decimal("0"))
    liabilities = sum((_signed(nets.get(a.id, Decimal("0")), a.type) for a in accounts if a.type == "liability"), Decimal("0"))
    equity = sum((_signed(nets.get(a.id, Decimal("0")), a.type) for a in accounts if a.type == "equity"), Decimal("0"))
    # صافي ربح الفترة (حتى تاريخ التقرير) يُضاف لحقوق الملكية حتى تتوازن المعادلة
    rev_q = db.query(func.coalesce(func.sum(models.JournalItem.credit - models.JournalItem.debit), 0)).join(
        models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id
    ).join(models.ChartAccount, models.ChartAccount.id == models.JournalItem.account_id).filter(
        models.JournalItem.company_id == company_id,
        models.ChartAccount.type == "revenue",
        models.ChartAccount.is_group.is_(False),
        models.JournalEntry.date <= cutoff,
    ).scalar() or 0
    exp_q = db.query(func.coalesce(func.sum(models.JournalItem.debit - models.JournalItem.credit), 0)).join(
        models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id
    ).join(models.ChartAccount, models.ChartAccount.id == models.JournalItem.account_id).filter(
        models.JournalItem.company_id == company_id,
        models.ChartAccount.type == "expense",
        models.ChartAccount.is_group.is_(False),
        models.JournalEntry.date <= cutoff,
    ).scalar() or 0
    net_profit = _q(rev_q) - _q(exp_q)
    total_equity = _q(equity) + net_profit
    return {
        "total_assets": _q(assets),
        "total_liabilities": _q(liabilities),
        "total_equity": total_equity,
        "net_profit": net_profit,
        "is_balanced": _q(assets) == (_q(liabilities) + total_equity),
        "as_of": str(cutoff),
    }


@router.get("/profit-loss-detail")
def get_profit_loss_detail(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    start = _parse_date(date_from, date(1900, 1, 1))
    end = _parse_date(date_to, date.today())

    # استعلام واحد مجمّع لكل الحسابات (بدل استعلام لكل حساب)
    rows = (
        db.query(
            models.ChartAccount.code,
            models.ChartAccount.name,
            models.ChartAccount.type,
            func.coalesce(func.sum(models.JournalItem.debit), 0),
            func.coalesce(func.sum(models.JournalItem.credit), 0),
        )
        .join(models.JournalItem, models.JournalItem.account_id == models.ChartAccount.id)
        .join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id)
        .filter(
            models.ChartAccount.company_id == company_id,
            models.ChartAccount.type.in_(["revenue", "expense"]),
            models.ChartAccount.is_group.is_(False),
            models.JournalEntry.date >= start,
            models.JournalEntry.date <= end,
        )
        .group_by(models.ChartAccount.id, models.ChartAccount.code, models.ChartAccount.name, models.ChartAccount.type)
        .order_by(models.ChartAccount.code)
        .all()
    )
    result = []
    for code, name, typ, d, c in rows:
        amount = _q(c - d) if typ == "revenue" else _q(d - c)
        result.append({"code": code, "name": name, "type": typ, "amount": amount})
    return result


@router.get("/profit-loss-by-cost-center")
def get_profit_loss_by_cost_center(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    """قائمة الدخل موزعة على مراكز التكلفة + سطر «بلا مركز» للبنود العامة."""
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    start = _parse_date(date_from, date(1900, 1, 1))
    end = _parse_date(date_to, date.today())

    rows = (
        db.query(
            models.JournalItem.cost_center_id,
            models.ChartAccount.type,
            func.coalesce(func.sum(models.JournalItem.debit), 0),
            func.coalesce(func.sum(models.JournalItem.credit), 0),
        )
        .join(models.ChartAccount, models.ChartAccount.id == models.JournalItem.account_id)
        .join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id)
        .filter(
            models.JournalItem.company_id == company_id,
            models.ChartAccount.type.in_(["revenue", "expense"]),
            models.ChartAccount.is_group.is_(False),
            models.JournalEntry.date >= start,
            models.JournalEntry.date <= end,
        )
        .group_by(models.JournalItem.cost_center_id, models.ChartAccount.type)
        .all()
    )
    centers = {c.id: c.name for c in db.query(models.CostCenter).filter(models.CostCenter.company_id == company_id).all()}
    agg: dict = {}
    for cc_id, acc_type, d, c in rows:
        bucket = agg.setdefault(cc_id, {"revenue": Decimal("0"), "expenses": Decimal("0")})
        if acc_type == "revenue":
            bucket["revenue"] += Decimal(str(c)) - Decimal(str(d))
        else:
            bucket["expenses"] += Decimal(str(d)) - Decimal(str(c))
    result = []
    for cc_id, b in agg.items():
        result.append({
            "cost_center_id": cc_id,
            "name": centers.get(cc_id) if cc_id is not None else "بلا مركز",
            "revenue": _q(b["revenue"]),
            "expenses": _q(b["expenses"]),
            "net_profit": _q(b["revenue"] - b["expenses"]),
        })
    result.sort(key=lambda r: (r["cost_center_id"] is not None, r["cost_center_id"] or 0))
    return result


# ---------------------------------------------------------------- توقعات التدفق النقدي والسيولة (Cash Flow Forecast)
@router.get("/cash-flow-forecast")
def get_cash_flow_forecast(
    days: int = Query(default=30, ge=7, le=180, description="أفق التنبؤ بالأيام"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    """توقعات التدفقات النقدية والسيولة المستقبلية:
    السيولة النقدية الحالية + مقبوضات العملاء المتوقعة + شيكات واردة
    - التزامات الموردين المستحقة - شيكات صادرة = صافي المركز المالي المستقبلي."""
    company_id = user.active_company_id

    # 1. السيولة الحالية الحية في الخزائن والبنوك
    safes_sum = db.query(func.coalesce(func.sum(models.Safe.balance), 0)).filter(
        models.Safe.company_id == company_id, models.Safe.is_active.is_(True)
    ).scalar() or Decimal("0")

    banks_sum = db.query(func.coalesce(func.sum(models.Bank.balance), 0)).filter(
        models.Bank.company_id == company_id, models.Bank.is_active.is_(True)
    ).scalar() or Decimal("0")

    current_cash_pool = Decimal(str(safes_sum)) + Decimal(str(banks_sum))

    # 2. مستحقات متوقعة من العملاء (أرصدة مدينة قائمة)
    from ..accounts import party_balances
    cust_balances = party_balances(db, "customer")
    total_receivables = sum((b for b in cust_balances.values() if b > 0), Decimal("0"))

    # 3. التزامات مؤكدة للموردين (أرصدة دائنة قائمة)
    sup_balances = party_balances(db, "supplier")
    total_payables = sum((b for b in sup_balances.values() if b > 0), Decimal("0"))

    # 4. أوراق القبض والدفع (الشيكات تحت التحصيل والشيكات الصادرة)
    from datetime import date as _d, timedelta as _td
    max_due = _d.today() + _td(days=days)

    cheques_in = db.query(func.coalesce(func.sum(models.Cheque.amount), 0)).filter(
        models.Cheque.company_id == company_id,
        models.Cheque.direction == "incoming",
        models.Cheque.status.in_(["received", "deposited"]),
        models.Cheque.due_date <= max_due,
    ).scalar() or Decimal("0")

    cheques_out = db.query(func.coalesce(func.sum(models.Cheque.amount), 0)).filter(
        models.Cheque.company_id == company_id,
        models.Cheque.direction == "outgoing",
        models.Cheque.status.in_(["issued", "delivered"]),
        models.Cheque.due_date <= max_due,
    ).scalar() or Decimal("0")

    expected_inflows = total_receivables + Decimal(str(cheques_in))
    expected_outflows = total_payables + Decimal(str(cheques_out))
    net_projected_cash = current_cash_pool + expected_inflows - expected_outflows

    # مؤشر الخطر: نسبة تغطية السيولة الحالية للالتزامات العاجلة
    quick_ratio = round(float(current_cash_pool / expected_outflows), 2) if expected_outflows > 0 else 999.0
    liquidity_status = "safe" if quick_ratio >= 1.0 or net_projected_cash >= 0 else "deficit_warning"

    return {
        "as_of": _d.today().isoformat(),
        "forecast_days": days,
        "current_cash_pool": _q(current_cash_pool),
        "safes_balance": _q(Decimal(str(safes_sum))),
        "banks_balance": _q(Decimal(str(banks_sum))),
        "expected_inflows": _q(expected_inflows),
        "receivables_projected": _q(total_receivables),
        "cheques_incoming_projected": _q(Decimal(str(cheques_in))),
        "expected_outflows": _q(expected_outflows),
        "payables_projected": _q(total_payables),
        "cheques_outgoing_projected": _q(Decimal(str(cheques_out))),
        "net_projected_cash": _q(net_projected_cash),
        "quick_coverage_ratio": quick_ratio if quick_ratio < 999 else None,
        "liquidity_status": liquidity_status,
    }


# ---------------------------------------------------------------- إقرار ضريبة القيمة المضافة
@router.get("/vat-return")
def get_vat_return(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    """إقرار ضريبة القيمة المضافة للفترة: مخرجات 2130 − مدخلات 1145 = المستحق للضريبة."""
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    start = _parse_date(date_from, date.today().replace(day=1))
    end = _parse_date(date_to, date.today())

    def period_net(code: str) -> Decimal:
        d, c = db.query(
            func.coalesce(func.sum(models.JournalItem.debit), 0),
            func.coalesce(func.sum(models.JournalItem.credit), 0),
        ).join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id).join(
            models.ChartAccount, models.ChartAccount.id == models.JournalItem.account_id
        ).filter(
            models.JournalItem.company_id == company_id,
            models.ChartAccount.code == code,
            models.JournalEntry.date >= start,
            models.JournalEntry.date <= end,
        ).one()
        return (Decimal(str(d or 0)) - Decimal(str(c or 0))).quantize(_TWO_PLACES)

    output_vat = -period_net("2130")   # حساب خصوم: رصيده الدائن هو المخرجات
    input_vat = period_net("1145")     # حساب أصول: رصيده المدين هو المدخلات
    return {
        "date_from": str(start),
        "date_to": str(end),
        "output_vat": output_vat,            # ضريبة المبيعات المحصلة
        "input_vat": input_vat,              # ضريبة المشتريات القابلة للخصم
        "net_payable": output_vat - input_vat,  # المستحق للبترول/الضريبة
    }


@router.get("/vat-return/xlsx")
def vat_return_xlsx(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    r = get_vat_return(date_from, date_to, db, user)
    tables = [(
        "إقرار ضريبة القيمة المضافة",
        ["البند", "القيمة"],
        [
            [("text", "من"), ("text", r["date_from"])],
            [("text", "إلى"), ("text", r["date_to"])],
            [("text", "ضريبة المخرجات (المبيعات)"), ("money", r["output_vat"])],
            [("text", "ضريبة المدخلات (المشتريات)"), ("money", r["input_vat"])],
            [("text", "الصافي المستحق للسداد"), ("money", r["net_payable"])],
        ],
    )]
    return FastResponse(
        content=exports.build_tables_xlsx("إقرار ضريبة القيمة المضافة", f"{r['date_from']} → {r['date_to']}", tables),
        media_type=exports.XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="vat-return-{r["date_from"]}_{r["date_to"]}.xlsx"'},
    )


# ---------------------------------------------------------------- قائمة التدفقات النقدية (الطريقة المباشرة)
_CASH_CODES = ("1111", "1112", "1113")


def _cash_account_ids(db: Session, company_id: int) -> set:
    """حسابات النقدية: الأكواد الأساسية 1111/1112/1113 + حسابات الخزائن والبنوك المرتبطة."""
    ids = {
        a.id for a in db.query(models.ChartAccount).filter(
            models.ChartAccount.company_id == company_id,
            models.ChartAccount.code.in_(_CASH_CODES),
        ).all()
    }
    for model in (models.Safe, models.Bank):
        for row in db.query(model.chart_account_id).filter(
            model.company_id == company_id, model.chart_account_id.isnot(None)  # type: ignore[attr-defined]
        ).all():
            ids.add(row[0])
    return ids


def _classify_flow(code: str) -> str:
    """تصنيف الحساب المقابل: أصول ثابتة 12xx استثماري، خصوم وحقوق 2xxx/3xxx تمويلي،
    وما عداهما (ذمم، مخزون، إيرادات، مصروفات، ضريبة) تشغيلي."""
    if code.startswith("12"):
        return "investing"
    if code.startswith(("2", "3")):
        return "financing"
    return "operating"


@router.get("/cash-flow", response_model=schemas.CashFlowStatement)
def get_cash_flow(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD — الافتراضي أول الشهر الحالي"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD — الافتراضي اليوم"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    """قائمة التدفقات النقدية — الطريقة المباشرة: حركة حسابات النقدية (خزائن/بنوك/صناديق)
    في الفترة مجمّعة على الحسابات المقابلة لها في كل قيد."""
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    start = _parse_date(date_from, date.today().replace(day=1))
    end = _parse_date(date_to, date.today())
    if end < start:
        raise HTTPException(status_code=422, detail="نهاية الفترة قبل بدايتها")

    cash_ids = _cash_account_ids(db, company_id)

    # رصيد أول الفترة: صافي حركة حسابات النقدية قبل تاريخ البداية
    opening = Decimal("0")
    if cash_ids:
        d, c = db.query(
            func.coalesce(func.sum(models.JournalItem.debit), 0),
            func.coalesce(func.sum(models.JournalItem.credit), 0),
        ).join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id).filter(
            models.JournalItem.company_id == company_id,
            models.JournalItem.account_id.in_(cash_ids),
            models.JournalEntry.date < start,
        ).one()
        opening = (Decimal(str(d or 0)) - Decimal(str(c or 0))).quantize(_TWO_PLACES)

    # أطراف الفترة: لكل قيد متوازن، أثر الطرف المقابل على النقدية = (دائن − مدين)؛
    # بنود النقدية نفسها تُتخطى — التحويل بين خزينة وبنك لا يغير إجمالي النقدية
    flows: dict = {}
    if cash_ids:
        items = (
            db.query(models.JournalItem, models.ChartAccount)
            .join(models.JournalEntry, models.JournalEntry.id == models.JournalItem.entry_id)
            .join(models.ChartAccount, models.ChartAccount.id == models.JournalItem.account_id)
            .filter(
                models.JournalItem.company_id == company_id,
                models.ChartAccount.is_group.is_(False),
                models.JournalEntry.date >= start,
                models.JournalEntry.date <= end,
            )
            .all()
        )
        for item, acc in items:
            if item.account_id in cash_ids:
                continue
            amount = (Decimal(str(item.credit or 0)) - Decimal(str(item.debit or 0))).quantize(_TWO_PLACES)
            if amount == 0:
                continue
            entry = flows.setdefault(acc.id, {"code": acc.code, "name": acc.name, "amount": Decimal("0"), "section": _classify_flow(acc.code or "")})
            entry["amount"] += amount

    sections: dict = {"operating": [], "investing": [], "financing": []}
    for f in sorted(flows.values(), key=lambda x: (-abs(x["amount"]), x["code"])):
        sections[f["section"]].append(schemas.CashFlowRow(code=f["code"], name=f["name"], amount=f["amount"].quantize(_TWO_PLACES)))

    operating_total = _q(sum((r.amount for r in sections["operating"]), Decimal("0")))
    investing_total = _q(sum((r.amount for r in sections["investing"]), Decimal("0")))
    financing_total = _q(sum((r.amount for r in sections["financing"]), Decimal("0")))
    net_change = (operating_total + investing_total + financing_total).quantize(_TWO_PLACES)
    return schemas.CashFlowStatement(
        date_from=start,
        date_to=end,
        opening=opening,
        closing=(opening + net_change).quantize(_TWO_PLACES),
        net_change=net_change,
        operating=sections["operating"],
        operating_total=operating_total,
        investing=sections["investing"],
        investing_total=investing_total,
        financing=sections["financing"],
        financing_total=financing_total,
    )


@router.get("/cash-flow/xlsx")
def cash_flow_xlsx(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    r = get_cash_flow(date_from, date_to, db, user)

    def section_table(title: str, rows: List[schemas.CashFlowRow], total: Decimal):
        body = [[("text", row.code), ("text", row.name), ("money", row.amount)] for row in rows]
        body.append([("text", ""), ("text", "الإجمالي — " + title), ("money", total)])
        return (title, ["الكود", "الحساب", "الأثر على النقدية"], body)

    tables = [
        ("ملخص", ["البند", "القيمة"], [
            [("text", "من"), ("text", str(r.date_from))],
            [("text", "إلى"), ("text", str(r.date_to))],
            [("text", "رصيد أول الفترة"), ("money", r.opening)],
            [("text", "التدفقات التشغيلية"), ("money", r.operating_total)],
            [("text", "التدفقات الاستثمارية"), ("money", r.investing_total)],
            [("text", "التدفقات التمويلية"), ("money", r.financing_total)],
            [("text", "صافي التغير في النقدية"), ("money", r.net_change)],
            [("text", "رصيد آخر الفترة"), ("money", r.closing)],
        ]),
        section_table("تشغيلي", r.operating, r.operating_total),
        section_table("استثماري", r.investing, r.investing_total),
        section_table("تمويلي", r.financing, r.financing_total),
    ]
    return FastResponse(
        content=exports.build_tables_xlsx("قائمة التدفقات النقدية", f"{r.date_from} → {r.date_to}", tables),
        media_type=exports.XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="cash-flow-{r.date_from}_{r.date_to}.xlsx"'},
    )


@router.get("/inventory-reconcile")
def inventory_reconcile(
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    """مطابقة تقييم المخزون المحسوب (الكميات × التكلفة) مع رصيد حساب المخزون 1101 بالدفاتر."""
    company_id = user.active_company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    cutoff = _parse_date(as_of)
    P, S = models.Product, models.ProductStock
    rows_q = (
        db.query(P.id, P.sku, P.name, P.cost_price, func.coalesce(func.sum(S.quantity), 0))
        .join(S, S.product_id == P.id, isouter=True)
        .filter(P.company_id == company_id, P.is_active.is_(True))
        .group_by(P.id, P.sku, P.name, P.cost_price)
        .order_by(P.sku)
        .all()
    )
    computed = Decimal("0")
    lines = []
    for pid, sku, name, cost, qty in rows_q:
        value = _q(Decimal(str(cost)) * Decimal(str(qty)))
        computed += value
        lines.append({"product_id": pid, "sku": sku, "name": name,
                      "quantity": float(Decimal(str(qty))), "cost_price": _q(cost), "value": value})
    inventory_acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1101"
    ).first()
    ledger = _q(_balances_up_to(db, company_id, cutoff).get(inventory_acc.id, Decimal("0")) if inventory_acc else 0)
    wip_acc = db.query(models.ChartAccount).filter(
        models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1130"
    ).first()
    wip = _q(_balances_up_to(db, company_id, cutoff).get(wip_acc.id, Decimal("0")) if wip_acc else 0)
    ledger_total = ledger + wip
    return {
        "as_of": str(cutoff),
        "computed_value": _q(computed),
        "ledger_inventory": ledger,
        "ledger_wip": wip,
        "ledger_total": ledger_total,
        "difference": _q(computed - ledger_total),
        "lines": lines,
    }


@router.get("/inventory-reconcile/xlsx")
def inventory_reconcile_xlsx(
    as_of: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    r = inventory_reconcile(as_of, db, user)
    from ..exports import build_tables_xlsx, XLSX_MIME
    from fastapi.responses import Response as _R
    tables = [(
        "مطابقة المخزون مع الدفاتر",
        ["الكود", "الصنف", "الكمية", "التكلفة", "القيمة"],
        [[("text", l["sku"]), ("text", l["name"]), ("int", l["quantity"]), ("money", l["cost_price"]), ("money", l["value"])] for l in r["lines"]],
    ), (
        "الملخص",
        ["البند", "القيمة"],
        [
            [("text", "تقييم المخزون المحسوب"), ("money", r["computed_value"])],
            [("text", "رصيد المخزون 1101 بالدفاتر"), ("money", r["ledger_inventory"])],
            [("text", "رصيد إنتاج تحت التشغيل 1130"), ("money", r["ledger_wip"])],
            [("text", "الفرق (محسوب − دفاتر)"), ("money", r["difference"])],
        ],
    )]
    return _R(
        content=build_tables_xlsx("مطابقة المخزون", r["as_of"], tables),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="inventory-reconcile.xlsx"'},
    )


# ---------------------------------------------------------------- PDF exports
def _pdf_response(title: str, subtitle: str, tables, filename: str) -> FastResponse:
    return FastResponse(
        content=exports.build_tables_pdf(title, subtitle, tables),
        media_type=exports.PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.get("/trial-balance/pdf")
def trial_balance_pdf(
    as_of: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    rows = get_trial_balance(as_of, db, user)
    tables = [(
        "ميزان المراجعة",
        ["الكود", "الحساب", "النوع", "الرصيد"],
        [[("text", r["code"]), ("text", r["name"]), ("text", r["type"]), ("money", r["balance"])] for r in rows],
    )]
    return _pdf_response("التقارير المالية", f"ميزان المراجعة حتى {as_of or date.today()}", tables, "trial-balance.pdf")


@router.get("/profit-loss/pdf")
def profit_loss_pdf(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    r = get_profit_loss(date_from, date_to, db, user)
    tables = [(
        "الأرباح والخسائر",
        ["البند", "القيمة"],
        [
            [("text", "إجمالي الإيرادات"), ("money", r["total_revenue"])],
            [("text", "إجمالي المصاريف"), ("money", r["total_expenses"])],
            [("text", "صافي الربح/(الخسارة)"), ("money", r["net_profit"])],
        ],
    )]
    return _pdf_response("التقارير المالية", f"{r['date_from']} → {r['date_to']}", tables, "profit-loss.pdf")


@router.get("/balance-sheet/pdf")
def balance_sheet_pdf(
    as_of: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    user=Depends(deps.get_current_user),
):
    r = get_balance_sheet(as_of, db, user)
    tables = [(
        "الميزانية العمومية",
        ["البند", "القيمة"],
        [
            [("text", "إجمالي الأصول"), ("money", r["total_assets"])],
            [("text", "إجمالي الخصوم"), ("money", r["total_liabilities"])],
            [("text", "إجمالي حقوق الملكية (شاملة صافي الربح)"), ("money", r["total_equity"])],
            [("text", "متوازنة؟"), ("text", "نعم" if r["is_balanced"] else "لا")],
        ],
    )]
    return _pdf_response("التقارير المالية", f"حتى {r['as_of']}", tables, "balance-sheet.pdf")
