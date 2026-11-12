"""موديول الضرائب المصري الشامل:
1) إقرار ضريبة القيمة المضافة — إجماليات من دفتر الأستاذ + تفصيل بنسب الفواتير + شهري
2) ضريبة الخصم والإضافة (المادة 62) — أكواد نسب قابلة للتعديل + تقرير السندات المحتجزة
3) ضريبة كسب العمل — شرائح تصاعدية قابلة للتعديل + حساب الخصم الشهري من مسير الرواتب
كل النسب والشرائح إعدادات لكل شركة — القانون يتغير والإعداد يتغير معه.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import Response as FastResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user, require_manager
from ..exports import PDF_MIME, XLSX_MIME, build_tables_pdf, build_tables_xlsx

router = APIRouter(prefix="/taxes", tags=["taxes"])

TWO = Decimal("0.01")

VAT_OUTPUT_CODE = "2130"
VAT_INPUT_CODE = "1145"
WITHHOLDING_CODE = "2135"

# بذر أكواد الخصم والإضافة الافتراضية (الجدول الشائع — قابل للتعديل)
DEFAULT_WITHHOLDING_CODES = [
    ("سلع ومواد وتوريدات", "1"),
    ("مقاولات وتوريدات", "1"),
    ("مواد ومستلزمات إنتاج (من المصنع مباشرة)", "1"),
    ("الورق ومنتجاته", "0.5"),
    ("الخدمات (صيانة/نقل/استشارات)", "3"),
    ("خدمات استثمارية", "3"),
    ("عمولات — أنشطة تجارية", "1"),
    ("عمولات — خدمات", "3"),
    ("المهن الحرة وأتعاب (محاماة/محاسبة/هندسية)", "5"),
    ("الشتلات والزهور", "2"),
]

# بذر شرائح ضريبة كسب العمل (قانون 30/2023 — سنوي، تصاعدي)
DEFAULT_PAYROLL_BRACKETS = [
    (0, 40000, "0"),
    (40000, 95000, "15"),
    (95000, 165000, "20"),
    (165000, 365000, "22.5"),
    (365000, 765000, "25"),
    (765000, None, "27.5"),
]


def _company_id(user) -> int:
    if not user.active_company_id:
        raise HTTPException(status_code=400, detail="No active company selected")
    return user.active_company_id


def _q(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(TWO)


# ==================================================================== 1) القيمة المضافة
def _period_net(db: Session, company_id: int, code: str, start, end) -> Decimal:
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
    return (Decimal(str(d or 0)) - Decimal(str(c or 0))).quantize(TWO)


def _vat_return(db: Session, company_id: int, start: date, end: date) -> dict:
    output_vat = -_period_net(db, company_id, VAT_OUTPUT_CODE, start, end)
    input_vat = _period_net(db, company_id, VAT_INPUT_CODE, start, end)
    # تفصيل مبيعات الفترة بنسبة الضريبة من أوامر البيع المؤكدة (يشمل نقاط البيع)
    rows = db.query(
        models.SalesOrder.tax_rate,
        func.count(models.SalesOrder.id),
        func.coalesce(func.sum(models.SalesOrder.subtotal), 0),
        func.coalesce(func.sum(models.SalesOrder.tax_amount), 0),
    ).filter(
        models.SalesOrder.company_id == company_id,
        models.SalesOrder.status == "confirmed",
        models.SalesOrder.updated_at >= datetime.combine(start, datetime.min.time()) - timedelta(hours=2),
        models.SalesOrder.updated_at < datetime.combine(end, datetime.min.time()) + timedelta(days=1) + timedelta(hours=2),
    ).group_by(models.SalesOrder.tax_rate).order_by(models.SalesOrder.tax_rate).all()
    by_rate = [
        {
            "rate": _q(r[0]),
            "invoices": int(r[1]),
            "taxable_base": _q(r[2]),
            "tax_amount": _q(r[3]),
        }
        for r in rows
    ]
    # تفصيل شهري من دفتر الأستاذ (مخرجات − مدخلات لكل شهر داخل الفترة)
    months: List[dict] = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
        out_m = -_period_net(db, company_id, VAT_OUTPUT_CODE, cur, min(nxt - timedelta(days=1), end))
        in_m = _period_net(db, company_id, VAT_INPUT_CODE, cur, min(nxt - timedelta(days=1), end))
        months.append({"month": cur.isoformat()[:7], "output_vat": out_m, "input_vat": in_m, "net": out_m - in_m})
        cur = nxt
    return {
        "date_from": str(start),
        "date_to": str(end),
        "output_vat": output_vat,
        "input_vat": input_vat,
        "net_payable": output_vat - input_vat,
        "sales_by_rate": by_rate,
        "monthly": months,
        "taxable_sales_total": sum((b["taxable_base"] for b in by_rate), Decimal("0")),
    }


@router.get("/vat-return")
def vat_return(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """إقرار القيمة المضافة للفترة: مخرجات − مدخلات + تفصيل بنسب الفواتير وشهريًا."""
    start = _parse_date(date_from, date.today().replace(day=1))
    end = _parse_date(date_to, date.today())
    if start > end:
        raise HTTPException(422, "date_from يجب أن يكون قبل date_to")
    return _vat_return(db, _company_id(user), start, end)


def _parse_date(value: Optional[str], default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid date")


def _vat_tables(r: dict) -> list:
    tables = [(
        "الإجماليات",
        ["البند", "القيمة"],
        [
            [("text", "من"), ("text", r["date_from"])],
            [("text", "إلى"), ("text", r["date_to"])],
            [("text", "ضريبة المخرجات (المبيعات)"), ("money", r["output_vat"])],
            [("text", "ضريبة المدخلات (المشتريات)"), ("money", r["input_vat"])],
            [("text", "الصافي المستحق للسداد"), ("money", r["net_payable"])],
        ],
    )]
    if r["sales_by_rate"]:
        tables.append((
            "تفصيل المبيعات بنسبة الضريبة",
            ["النسبة %", "عدد الفواتير", "الوعاء", "الضريبة"],
            [
                [("money", b["rate"]), ("int", b["invoices"]), ("money", b["taxable_base"]), ("money", b["tax_amount"])]
                for b in r["sales_by_rate"]
            ],
        ))
    if r["monthly"]:
        tables.append((
            "تفصيل شهري",
            ["الشهر", "مخرجات", "مدخلات", "صافي"],
            [[("text", m["month"]), ("money", m["output_vat"]), ("money", m["input_vat"]), ("money", m["net"])] for m in r["monthly"]],
        ))
    return tables


@router.get("/vat-return/xlsx")
def vat_return_xlsx(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = vat_return(date_from, date_to, db, user)
    return FastResponse(
        content=build_tables_xlsx("إقرار ضريبة القيمة المضافة", f"{r['date_from']} → {r['date_to']}", _vat_tables(r)),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="vat-return-{r["date_from"]}_{r["date_to"]}.xlsx"'},
    )


@router.get("/vat-return/pdf")
def vat_return_pdf(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = vat_return(date_from, date_to, db, user)
    return FastResponse(
        content=build_tables_pdf("إقرار ضريبة القيمة المضافة", f"{r['date_from']} → {r['date_to']}", _vat_tables(r)),
        media_type=PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="vat-return-{r["date_from"]}_{r["date_to"]}.pdf"'},
    )


# ==================================================================== 2) الخصم والإضافة
def _seed_defaults(db: Session, company_id: int) -> None:
    """بذر أكواد الخصم والإضافة (idempotent) عند أول استخدام."""
    if db.query(models.WithholdingCode).filter(models.WithholdingCode.company_id == company_id).count() == 0:
        for name, rate in DEFAULT_WITHHOLDING_CODES:
            db.add(models.WithholdingCode(company_id=company_id, name=name, rate=Decimal(rate)))
        db.flush()
        db.commit()


@router.get("/withholding/codes")
def list_withholding_codes(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    company_id = _company_id(user)
    _seed_defaults(db, company_id)
    q = db.query(models.WithholdingCode).filter(models.WithholdingCode.company_id == company_id)
    if not include_inactive:
        q = q.filter(models.WithholdingCode.is_active.is_(True))
    return q.order_by(models.WithholdingCode.rate, models.WithholdingCode.name).all()


@router.post("/withholding/codes", response_model=schemas.WithholdingCodeOut, status_code=status.HTTP_201_CREATED)
def create_withholding_code(
    payload: schemas.WithholdingCodeCreate,
    db: Session = Depends(get_db),
    user=Depends(require_manager),
):
    company_id = _company_id(user)
    _seed_defaults(db, company_id)
    if db.query(models.WithholdingCode).filter(
        models.WithholdingCode.company_id == company_id, models.WithholdingCode.name == payload.name.strip()
    ).first():
        raise HTTPException(409, "كود بنفس الاسم موجود بالفعل")
    row = models.WithholdingCode(
        company_id=company_id, name=payload.name.strip(), rate=Decimal(str(payload.rate)),
        is_active=payload.is_active is not False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/withholding/codes/{code_id}", response_model=schemas.WithholdingCodeOut)
def update_withholding_code(
    code_id: int,
    payload: schemas.WithholdingCodeUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_manager),
):
    row = db.query(models.WithholdingCode).filter(
        models.WithholdingCode.id == code_id, models.WithholdingCode.company_id == _company_id(user)
    ).first()
    if row is None:
        raise HTTPException(404, "الكود غير موجود")
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.rate is not None:
        row.rate = Decimal(str(payload.rate))
    if payload.is_active is not None:
        row.is_active = payload.is_active
    db.commit()
    db.refresh(row)
    return row


@router.delete("/withholding/codes/{code_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_withholding_code(
    code_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_manager),
):
    company_id = _company_id(user)
    row = db.query(models.WithholdingCode).filter(
        models.WithholdingCode.id == code_id, models.WithholdingCode.company_id == company_id
    ).first()
    if row is None:
        raise HTTPException(404, "الكود غير موجود")
    used = db.query(models.Payment).filter(
        models.Payment.company_id == company_id,
        models.Payment.withholding_code_id == code_id,
        models.Payment.status == "posted",
    ).count()
    if used:
        # مقيّد بسندات — يُعطَّل بدل الحذف حفاظًا على سندات التاريخ
        row.is_active = False
        db.commit()
        raise HTTPException(409, "الكود مقيّد بسندات مقطوعة — تم تعطيله بدلًا من الحذف")
    db.delete(row)
    db.commit()


def _withholding_report(db: Session, company_id: int, start: date, end: date) -> dict:
    pays = (
        db.query(models.Payment)
        .filter(
            models.Payment.company_id == company_id,
            models.Payment.status == "posted",
            models.Payment.kind == "payment",
            models.Payment.withholding_amount > 0,
            models.Payment.paid_on >= start,
            models.Payment.paid_on <= end,
        )
        .order_by(models.Payment.paid_on, models.Payment.id)
        .all()
    )
    rows = []
    by_code: dict = {}
    by_supplier: dict = {}
    for p in pays:
        code_name = p.withholding_code.name if p.withholding_code else "بدون كود"
        w = _q(p.withholding_amount)
        rows.append({
            "id": p.id,
            "paid_on": str(p.paid_on),
            "supplier_id": p.supplier_id,
            "supplier_name": p.supplier.name if p.supplier else None,
            "reference": p.reference,
            "method": p.method,
            "amount": _q(p.amount),
            "withholding": w,
            "net_cash": _q(Decimal(str(p.amount)) - w),
            "code_name": code_name,
        })
        by_code[code_name] = by_code.get(code_name, Decimal("0")) + w
        sname = rows[-1]["supplier_name"] or "—"
        by_supplier[sname] = by_supplier.get(sname, Decimal("0")) + w
    total = sum((r["withholding"] for r in rows), Decimal("0"))
    return {
        "date_from": str(start),
        "date_to": str(end),
        "rows": rows,
        "by_code": [{"code": k, "total": v} for k, v in sorted(by_code.items())],
        "by_supplier": [{"supplier": k, "total": v} for k, v in sorted(by_supplier.items())],
        "total_withheld": total,
    }


@router.get("/withholding")
def withholding_report(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """سندات الخصم والإضافة للفترة: تفصيل + إجماليات بالكود والمورد."""
    start = _parse_date(date_from, date.today().replace(day=1))
    end = _parse_date(date_to, date.today())
    return _withholding_report(db, _company_id(user), start, end)


def _withholding_tables(r: dict) -> list:
    tables = [(
        "سندات الخصم والإضافة",
        ["التاريخ", "المورد", "المرجع", "قيمة السند", "المحتجز", "النقدية المدفوعة", "الكود"],
        [
            [
                ("text", row["paid_on"]), ("text", row["supplier_name"] or "—"), ("text", row["reference"] or ""),
                ("money", row["amount"]), ("money", row["withholding"]), ("money", row["net_cash"]),
                ("text", row["code_name"]),
            ]
            for row in r["rows"]
        ] or [[("text", "لا توجد سندات"), ("text", ""), ("text", ""), ("money", 0), ("money", 0), ("money", 0), ("text", "")]],
    )]
    tables.append((
        "الإجماليات بالكود",
        ["الكود", "إجمالي المحتجز"],
        [[("text", b["code"]), ("money", b["total"])] for b in r["by_code"]]
        or [[("text", "—"), ("money", 0)]],
    ))
    tables.append((
        "الإجماليات بالمورد",
        ["المورد", "إجمالي المحتجز"],
        [[("text", b["supplier"]), ("money", b["total"])] for b in r["by_supplier"]]
        or [[("text", "—"), ("money", 0)]],
    ))
    tables.append((
        "الإجمالي العام",
        ["البند", "القيمة"],
        [
            [("text", "من"), ("text", r["date_from"])],
            [("text", "إلى"), ("text", r["date_to"])],
            [("text", "إجمالي المحتجز للفترة"), ("money", r["total_withheld"])],
        ],
    ))
    return tables


@router.get("/withholding/xlsx")
def withholding_xlsx(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = withholding_report(date_from, date_to, db, user)
    return FastResponse(
        content=build_tables_xlsx("ضريبة الخصم والإضافة", f"{r['date_from']} → {r['date_to']}", _withholding_tables(r)),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="withholding-{r["date_from"]}_{r["date_to"]}.xlsx"'},
    )


@router.get("/withholding/pdf")
def withholding_pdf(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = withholding_report(date_from, date_to, db, user)
    return FastResponse(
        content=build_tables_pdf("ضريبة الخصم والإضافة", f"{r['date_from']} → {r['date_to']}", _withholding_tables(r)),
        media_type=PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="withholding-{r["date_from"]}_{r["date_to"]}.pdf"'},
    )


# ==================================================================== 3) ضريبة كسب العمل
def _payroll_settings(db: Session, company_id: int) -> models.TaxSetting:
    """إعدادات ضريبة المرتبات + شرائحها — تُبذر افتراضيًا عند أول استخدام."""
    s = db.query(models.TaxSetting).filter(
        models.TaxSetting.company_id == company_id, models.TaxSetting.kind == "payroll"
    ).first()
    if s is None:
        s = models.TaxSetting(company_id=company_id, kind="payroll")
        db.add(s)
        db.flush()
    if db.query(models.TaxBracket).filter(
        models.TaxBracket.company_id == company_id, models.TaxBracket.kind == "payroll"
    ).count() == 0:
        for i, (mn, mx, rate) in enumerate(DEFAULT_PAYROLL_BRACKETS):
            db.add(models.TaxBracket(
                company_id=company_id, kind="payroll", min_amount=Decimal(mn),
                max_amount=(Decimal(mx) if mx is not None else None), rate=Decimal(rate), sort=i,
            ))
        db.flush()
        db.commit()
    return s


def _brackets(db: Session, company_id: int) -> List[models.TaxBracket]:
    return db.query(models.TaxBracket).filter(
        models.TaxBracket.company_id == company_id, models.TaxBracket.kind == "payroll"
    ).order_by(models.TaxBracket.sort, models.TaxBracket.min_amount).all()


def progressive_tax(taxable: Decimal, brackets: List[models.TaxBracket]) -> Decimal:
    """ضريبة تصاعدية على الشرائح — الشريحة المفتوحة (max NULL) تمتد لما لا نهاية."""
    tax = Decimal("0")
    for b in brackets:
        lo = Decimal(str(b.min_amount))
        hi = Decimal(str(b.max_amount)) if b.max_amount is not None else None
        if taxable <= lo:
            break
        portion = taxable - lo
        if hi is not None:
            portion = min(portion, hi - lo)
        tax += portion * Decimal(str(b.rate)) / Decimal("100")
    return tax.quantize(TWO)


@router.get("/payroll-tax/settings")
def payroll_tax_settings(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """إعدادات ضريبة كسب العمل: الاعفاء الشخصي + تخفيض الضريبة + نسبة التأمينات + الشرائح."""
    company_id = _company_id(user)
    s = _payroll_settings(db, company_id)
    return {
        "personal_exemption": _q(s.personal_exemption),
        "wage_reduction_percent": _q(s.wage_reduction_percent),
        "social_insurance_percent": _q(s.social_insurance_percent),
        "brackets": [
            {
                "id": b.id, "min_amount": _q(b.min_amount),
                "max_amount": (_q(b.max_amount) if b.max_amount is not None else None),
                "rate": _q(b.rate), "sort": b.sort,
            }
            for b in _brackets(db, company_id)
        ],
    }


@router.put("/payroll-tax/settings")
def update_payroll_tax_settings(
    payload: schemas.PayrollTaxSettingsUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_manager),
):
    company_id = _company_id(user)
    s = _payroll_settings(db, company_id)
    if payload.personal_exemption is not None:
        if payload.personal_exemption < 0:
            raise HTTPException(422, "الاعفاء الشخصي لا يكون سالبًا")
        s.personal_exemption = Decimal(str(payload.personal_exemption))
    if payload.wage_reduction_percent is not None:
        if not (0 <= payload.wage_reduction_percent <= 100):
            raise HTTPException(422, "نسبة التخفيض بين 0 و 100")
        s.wage_reduction_percent = Decimal(str(payload.wage_reduction_percent))
    if payload.social_insurance_percent is not None:
        if not (0 <= payload.social_insurance_percent <= 100):
            raise HTTPException(422, "نسبة التأمينات بين 0 و 100")
        s.social_insurance_percent = Decimal(str(payload.social_insurance_percent))
    if payload.brackets is not None:
        if len(payload.brackets) == 0:
            raise HTTPException(422, "مطلوب شريحة واحدة على الأقل")
        rows = sorted(payload.brackets, key=lambda b: b.sort)
        prev_max = Decimal("-1")
        for i, b in enumerate(rows):
            mn = Decimal(str(b.min_amount))
            mx = Decimal(str(b.max_amount)) if b.max_amount is not None else None
            if mn < 0 or (b.rate is not None and not (0 <= b.rate <= 100)):
                raise HTTPException(422, "الشرائح: نسب 0–100 وحدود غير سالبة")
            if mx is not None and mx <= mn:
                raise HTTPException(422, "حد الشريحة الأعلى يجب أن يتجاوز الأدنى")
            if mn < prev_max:
                raise HTTPException(422, "الشرائح متتابعة ومتصاعدة — راجع الحدود")
            prev_max = (mx if mx is not None else Decimal("Infinity"))
        db.query(models.TaxBracket).filter(
            models.TaxBracket.company_id == company_id, models.TaxBracket.kind == "payroll"
        ).delete()
        for i, b in enumerate(rows):
            db.add(models.TaxBracket(
                company_id=company_id, kind="payroll",
                min_amount=Decimal(str(b.min_amount)),
                max_amount=(Decimal(str(b.max_amount)) if b.max_amount is not None else None),
                rate=Decimal(str(b.rate)), sort=i,
            ))
    db.commit()
    db.refresh(s)
    return payroll_tax_settings(db=db, user=user)


def _run_or_404(db: Session, company_id: int, run_id: int) -> models.HrPayrollRun:
    run = db.get(models.HrPayrollRun, run_id)
    if run is None or run.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسير غير موجود")
    return run


def _payroll_tax_rows(db: Session, company_id: int, run: models.HrPayrollRun) -> dict:
    s = _payroll_settings(db, company_id)
    brackets = _brackets(db, company_id)
    slips = (
        db.query(models.HrPayslip, models.HrEmployee)
        .join(models.HrEmployee, models.HrEmployee.id == models.HrPayslip.employee_id)
        .filter(models.HrPayslip.run_id == run.id)
        .order_by(models.HrEmployee.code)
        .all()
    )
    slip_ids = [slip.id for slip, _e in slips]
    si_by_slip: dict = {}
    tax_by_slip: dict = {}
    if slip_ids:
        lines = db.query(models.HrPayslipLine).filter(models.HrPayslipLine.payslip_id.in_(slip_ids)).all()
        for line in lines:
            name = line.name or ""
            if line.category != "deduction":
                continue
            if "تأمينات" in name:
                si_by_slip[line.payslip_id] = si_by_slip.get(line.payslip_id, Decimal("0")) + Decimal(str(line.amount or 0))
            elif "ضريبة" in name:
                tax_by_slip[line.payslip_id] = tax_by_slip.get(line.payslip_id, Decimal("0")) + Decimal(str(line.amount or 0))
    rows = []
    for slip, emp in slips:
        # الإجمالي الشهري = الأساسي + بدائل ومكافآت القسيمة (total_earnings = البدائل فقط)
        gross_m = Decimal(str(slip.base_salary or 0)) + Decimal(str(slip.total_earnings or 0))
        si_m = si_by_slip.get(slip.id, Decimal("0"))
        if si_m == 0 and Decimal(str(s.social_insurance_percent)) > 0:
            si_m = (gross_m * Decimal(str(s.social_insurance_percent)) / Decimal("100")).quantize(TWO)
        annual_gross = (gross_m * Decimal("12")).quantize(TWO)
        annual_si = (si_m * Decimal("12")).quantize(TWO)
        taxable = annual_gross - annual_si - Decimal(str(s.personal_exemption))
        taxable = max(taxable, Decimal("0")).quantize(TWO)
        annual_tax = progressive_tax(taxable, brackets)
        if Decimal(str(s.wage_reduction_percent)) > 0:
            annual_tax = (annual_tax * (Decimal("100") - Decimal(str(s.wage_reduction_percent))) / Decimal("100")).quantize(TWO)
        monthly_tax = (annual_tax / Decimal("12")).quantize(TWO)
        actual = tax_by_slip.get(slip.id, Decimal("0"))
        rows.append({
            "employee_id": emp.id, "code": emp.code, "name": emp.full_name,
            "monthly_gross": _q(gross_m), "monthly_si": _q(si_m),
            "annual_gross": annual_gross, "annual_si": annual_si,
            "personal_exemption": _q(s.personal_exemption),
            "annual_taxable": taxable,
            "annual_tax": annual_tax, "monthly_tax": monthly_tax,
            "actual_withheld": _q(actual),
            "difference": _q(actual - monthly_tax),
        })
    total_monthly = sum((r["monthly_tax"] for r in rows), Decimal("0"))
    total_actual = sum((r["actual_withheld"] for r in rows), Decimal("0"))
    return {
        "run_id": run.id, "period": run.period_label,
        "status": run.status,
        "personal_exemption": _q(s.personal_exemption),
        "wage_reduction_percent": _q(s.wage_reduction_percent),
        "rows": rows,
        "total_monthly_tax": total_monthly,
        "total_actual": total_actual,
        "total_difference": _q(total_actual - total_monthly),
    }


@router.get("/payroll-tax/{run_id}")
def payroll_tax_report(
    run_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """حساب ضريبة كسب العمل لمسير: سنوية × شرائح − اعفاء − تأمينات، والشهري = السنوي ÷ 12."""
    company_id = _company_id(user)
    run = _run_or_404(db, company_id, run_id)
    return _payroll_tax_rows(db, company_id, run)


def _payroll_tables(r: dict) -> list:
    rows = r["rows"]
    tables = [(
        f"ضريبة كسب العمل — مسير {r['period']}",
        ["الكود", "الاسم", "الشهري", "تأمينات/شهر", "الوعاء السنوي", "الضريبة السنوية", "الخصم الشهري", "المقطوع فعليًا", "الفرق"],
        [
            [
                ("text", row["code"]), ("text", row["name"]), ("money", row["monthly_gross"]),
                ("money", row["monthly_si"]), ("money", row["annual_taxable"]), ("money", row["annual_tax"]),
                ("money", row["monthly_tax"]), ("money", row["actual_withheld"]), ("money", row["difference"]),
            ]
            for row in rows
        ] or [[("text", "لا يوجد موظفون"), ("text", "")] + [("money", 0)] * 7],
    )]
    tables.append((
        "الإجماليات",
        ["البند", "القيمة"],
        [
            [("text", "الاعفاء الشخصي السنوي"), ("money", r["personal_exemption"])],
            [("text", f"تخفيض قيمة الضريبة ({r['wage_reduction_percent']}%)"), ("text", "مطبق" if r["wage_reduction_percent"] else "غير مطبق")],
            [("text", "إجمالي الضريبة الشهرية المحسبة"), ("money", r["total_monthly_tax"])],
            [("text", "إجمالي المقطوع فعليًا"), ("money", r["total_actual"])],
            [("text", "فرق التسوية"), ("money", r["total_difference"])],
        ],
    ))
    return tables


@router.get("/payroll-tax/{run_id}/xlsx")
def payroll_tax_xlsx(
    run_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    company_id = _company_id(user)
    run = _run_or_404(db, company_id, run_id)
    r = _payroll_tax_rows(db, company_id, run)
    return FastResponse(
        content=build_tables_xlsx("ضريبة كسب العمل", f"مسير {r['period']}", _payroll_tables(r)),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="payroll-tax-{r["period"]}.xlsx"'},
    )


@router.get("/payroll-tax/{run_id}/pdf")
def payroll_tax_pdf(
    run_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    company_id = _company_id(user)
    run = _run_or_404(db, company_id, run_id)
    r = _payroll_tax_rows(db, company_id, run)
    return FastResponse(
        content=build_tables_pdf("ضريبة كسب العمل", f"مسير {r['period']}", _payroll_tables(r)),
        media_type=PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="payroll-tax-{r["period"]}.pdf"'},
    )


# ============================================ 3ب) الإقرار السنوي الموحد للمرتبات — نموذج خ السنوي
def _payroll_annual(db: Session, company_id: int, year: int) -> dict:
    """إقرار سنوي موحّد (نموذج خ السنوي): تجميع مسيرات السنة كلها لكل موظف.

    الفرق عن تقرير المسير الشهري: الوعاء السنوي هنا **فعلي** (مجموع 12 شهر)
    وليس تقديريًا (شهري × 12) — فالترقيات والبدائل المتغيرة خلال السنة
    تُحتسب على حقيقتها، مع مقارنة الضريبة السنوية بما اقتُطع فعليًا شهريًا."""
    s = _payroll_settings(db, company_id)
    brackets = _brackets(db, company_id)
    runs = (
        db.query(models.HrPayrollRun)
        .filter(models.HrPayrollRun.company_id == company_id, models.HrPayrollRun.year == year)
        .order_by(models.HrPayrollRun.month)
        .all()
    )
    run_ids = [r.id for r in runs]
    slips = (
        db.query(models.HrPayslip, models.HrEmployee, models.HrPayrollRun.month)
        .join(models.HrEmployee, models.HrEmployee.id == models.HrPayslip.employee_id)
        .join(models.HrPayrollRun, models.HrPayrollRun.id == models.HrPayslip.run_id)
        .filter(models.HrPayslip.run_id.in_(run_ids))
        .all()
    ) if run_ids else []
    slip_ids = [slip.id for slip, _e, _m in slips]
    si_by_slip: dict = {}
    tax_by_slip: dict = {}
    if slip_ids:
        lines = db.query(models.HrPayslipLine).filter(models.HrPayslipLine.payslip_id.in_(slip_ids)).all()
        for line in lines:
            name = line.name or ""
            if line.category != "deduction":
                continue
            if "تأمينات" in name:
                si_by_slip[line.payslip_id] = si_by_slip.get(line.payslip_id, Decimal("0")) + Decimal(str(line.amount or 0))
            elif "ضريبة" in name:
                tax_by_slip[line.payslip_id] = tax_by_slip.get(line.payslip_id, Decimal("0")) + Decimal(str(line.amount or 0))

    months: List[dict] = []
    per_emp: dict = {}
    for r in runs:
        m_slips = [(slip, emp) for slip, emp, m in slips if m == r.month]
        m_gross = m_si = m_tax = Decimal("0")
        for slip, emp in m_slips:
            gross = Decimal(str(slip.base_salary or 0)) + Decimal(str(slip.total_earnings or 0))
            si = si_by_slip.get(slip.id, Decimal("0"))
            if si == 0 and Decimal(str(s.social_insurance_percent)) > 0:
                si = (gross * Decimal(str(s.social_insurance_percent)) / Decimal("100")).quantize(TWO)
            actual = tax_by_slip.get(slip.id, Decimal("0"))
            m_gross += gross
            m_si += si
            m_tax += actual
            acc = per_emp.setdefault(emp.id, {
                "employee_id": emp.id, "code": emp.code, "name": emp.full_name,
                "gross": Decimal("0"), "si": Decimal("0"), "actual": Decimal("0"), "months": 0,
            })
            acc["gross"] += gross
            acc["si"] += si
            acc["actual"] += actual
            acc["months"] += 1
        months.append({
            "month": r.month, "period": f"{year}-{r.month:02d}", "status": r.status,
            "employees": len(m_slips),
            "gross": _q(m_gross), "si": _q(m_si), "actual_withheld": _q(m_tax),
        })
    rows = []
    for acc in per_emp.values():
        taxable = acc["gross"] - acc["si"] - Decimal(str(s.personal_exemption))
        taxable = max(taxable, Decimal("0")).quantize(TWO)
        annual_tax = progressive_tax(taxable, brackets)
        if Decimal(str(s.wage_reduction_percent)) > 0:
            annual_tax = (annual_tax * (Decimal("100") - Decimal(str(s.wage_reduction_percent))) / Decimal("100")).quantize(TWO)
        rows.append({
            "employee_id": acc["employee_id"], "code": acc["code"], "name": acc["name"],
            "months": acc["months"],
            "annual_gross": _q(acc["gross"]), "annual_si": _q(acc["si"]),
            "personal_exemption": _q(s.personal_exemption),
            "annual_taxable": taxable, "annual_tax": annual_tax,
            "actual_withheld": _q(acc["actual"]),
            "difference": _q(acc["actual"] - annual_tax),
        })
    rows.sort(key=lambda x: str(x["code"]))
    total_tax = sum((r["annual_tax"] for r in rows), Decimal("0"))
    total_actual = sum((r["actual_withheld"] for r in rows), Decimal("0"))
    return {
        "year": year, "months_count": len(runs),
        "posted_months": sum(1 for r in runs if r.status == "posted"),
        "personal_exemption": _q(s.personal_exemption),
        "wage_reduction_percent": _q(s.wage_reduction_percent),
        "months": months, "rows": rows,
        "total_annual_gross": _q(sum((r["annual_gross"] for r in rows), Decimal("0"))),
        "total_annual_taxable": _q(sum((r["annual_taxable"] for r in rows), Decimal("0"))),
        "total_annual_tax": total_tax,
        "total_actual": total_actual,
        "total_difference": _q(total_actual - total_tax),
    }


def _payroll_annual_tables(r: dict) -> list:
    rows = r["rows"]
    tables = [(
        f"الإقرار السنوي الموحد للمرتبات {r['year']} — نموذج خ السنوي",
        ["الكود", "الاسم", "الشهور", "الإجمالي السنوي", "التأمينات السنوية", "الاعفاء الشخصي",
         "الوعاء السنوي", "الضريبة السنوية", "المقطوع فعليًا", "الفرق"],
        [
            [
                ("text", row["code"]), ("text", row["name"]), ("text", str(row["months"])),
                ("money", row["annual_gross"]), ("money", row["annual_si"]),
                ("money", row["personal_exemption"]), ("money", row["annual_taxable"]),
                ("money", row["annual_tax"]), ("money", row["actual_withheld"]), ("money", row["difference"]),
            ]
            for row in rows
        ] or [[("text", "لا يوجد موظفون في السنة"), ("text", "")] + [("money", 0)] * 8],
    ), (
        "تفصيل الشهور",
        ["الشهر", "الحالة", "الموظفون", "الإجمالي", "التأمينات", "المقطوع فعليًا"],
        [
            [
                ("text", m["period"]),
                ("text", "مُرحَّل" if m["status"] == "posted" else "مسودة"),
                ("text", str(m["employees"])),
                ("money", m["gross"]), ("money", m["si"]), ("money", m["actual_withheld"]),
            ]
            for m in r["months"]
        ] or [[("text", "لا مسيرات في السنة"), ("text", ""), ("text", "")] + [("money", 0)] * 3],
    ), (
        "الإجماليات",
        ["البند", "القيمة"],
        [
            [("text", "عدد الشهور المعالجة (منها مُرحّلة)"), ("text", f"{r['months_count']} ({r['posted_months']} مُرحّلة)")],
            [("text", "الاعفاء الشخصي السنوي"), ("money", r["personal_exemption"])],
            [("text", f"تخفيض قيمة الضريبة ({r['wage_reduction_percent']}%)"), ("text", "مطبق" if r["wage_reduction_percent"] else "غير مطبق")],
            [("text", "إجمالي الدخل السنوي"), ("money", r["total_annual_gross"])],
            [("text", "إجمالي الوعاء السنوي"), ("money", r["total_annual_taxable"])],
            [("text", "إجمالي الضريبة السنوية المستحقة"), ("money", r["total_annual_tax"])],
            [("text", "إجمالي المقطوع فعليًا خلال السنة"), ("money", r["total_actual"])],
            [("text", "فرق التسوية السنوي (يُسوّى من راتب ديسمبر أو نموذج تعديل)"), ("money", r["total_difference"])],
        ],
    )]
    return tables


@router.get("/payroll-tax/annual/{year}")
def payroll_tax_annual_report(
    year: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """الإقرار السنوي الموحد للمرتبات: وعاء فعلي لكل موظف عبر كل مسيرات السنة."""
    company_id = _company_id(user)
    return _payroll_annual(db, company_id, year)


@router.get("/payroll-tax/annual/{year}/xlsx")
def payroll_tax_annual_xlsx(
    year: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    company_id = _company_id(user)
    r = _payroll_annual(db, company_id, year)
    return FastResponse(
        content=build_tables_xlsx("الإقرار السنوي الموحد للمرتبات", f"السنة {r['year']} — نموذج خ السنوي", _payroll_annual_tables(r)),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="payroll-tax-annual-{r["year"]}.xlsx"'},
    )


@router.get("/payroll-tax/annual/{year}/pdf")
def payroll_tax_annual_pdf(
    year: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    company_id = _company_id(user)
    r = _payroll_annual(db, company_id, year)
    return FastResponse(
        content=build_tables_pdf("الإقرار السنوي الموحد للمرتبات", f"السنة {r['year']} — نموذج خ السنوي", _payroll_annual_tables(r)),
        media_type=PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="payroll-tax-annual-{r["year"]}.pdf"'},
    )


# ==================================================== 4) النماذج الرسمية لمصلحة الضرائب
QUARTER_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}


def _period_range(year: int, period_type: str, period: int) -> tuple[date, date]:
    """فترة الإقرار: ربع سنوي (1–4) أو شهري (1–12) — الإقرار الربعي هو الأصل (مادة 61)."""
    if period_type == "quarter":
        if period not in QUARTER_MONTHS:
            raise HTTPException(422, "الربع يجب أن يكون من 1 إلى 4")
        m1, m2 = QUARTER_MONTHS[period]
    else:
        if not (1 <= period <= 12):
            raise HTTPException(422, "الشهر يجب أن يكون من 1 إلى 12")
        m1 = m2 = period
    start = date(year, m1, 1)
    end = date(year + (m2 // 12), (m2 % 12) + 1, 1) - timedelta(days=1)
    return start, end


def _period_label(period_type: str, period: int, year: int) -> str:
    if period_type == "quarter":
        return f"الربع {period} {year}"
    return f"شهر {period} {year}"


def _vat_form_tables(db: Session, company_id: int, start: date, end: date, period_type: str, period: int, year: int) -> list:
    """خانات إقرار القيمة المضافة الربعي بترتيب النموذج الرسمي.

    النسبة العامة 14% خانة مستقلة، وبقية النسب تُجمَّع تحت خانة «نسب الجدول»
    مع تفصيلها — الصادرات والمعفاة لا تتبعنا من البيانات الحالية فلا تُعرض.
    """
    r = _vat_return(db, company_id, start, end)
    company = db.get(models.Company, company_id)
    general = next((b for b in r["sales_by_rate"] if b["rate"] == Decimal("14.00")), None)
    other_rates = [b for b in r["sales_by_rate"] if b["rate"] != Decimal("14.00")]
    other_base = sum((b["taxable_base"] for b in other_rates), Decimal("0"))
    other_tax = sum((b["tax_amount"] for b in other_rates), Decimal("0"))

    def box(no: str, label: str, base, tax=None) -> list:
        row = [("text", f"({no}) {label}")]
        if tax is None:
            row.append(("money", base))
        else:
            row.append(("money", base))
            row.append(("money", tax))
        return row

    head = [(
        "بيانات الممول والإقرار",
        ["البند", "البيان"],
        [
            [("text", "اسم الممول"), ("text", company.name if company else "")],
            [("text", "الملف الضريبي"), ("text", (company.eta_tin if company and company.eta_tin else ""))],
            [("text", "نوع الفترة"), ("text", _period_label(period_type, period, year))],
            [("text", "من"), ("text", str(start))],
            [("text", "إلى"), ("text", str(end))],
        ],
    )]
    boxes = [(
        "خانات الإقرار",
        ["البند", "الوعاء / القيمة", "الضريبة"],
        [
            box("1", "مبيعات خاضعة للنسبة العامة 14%", general["taxable_base"] if general else Decimal("0"), general["tax_amount"] if general else Decimal("0")),
            box("2", "مبيعات خاضعة لنسب الجدول (أخرى)", other_base, other_tax),
            box("3", "إجمالي ضريبة المخرجات", r["output_vat"]),
            box("4", "ضريبة المدخلات على المشتريات", r["input_vat"]),
            box("5", "صافي الضريبة المستحقة للسداد", r["net_payable"]),
            box("6", "إجمالي الوعاء الخاضع", r["taxable_sales_total"]),
        ],
    )]
    detail = [(
        "تفصيل المبيعات بكل نسبة",
        ["النسبة %", "عدد الفواتير", "الوعاء", "الضريبة"],
        [[("money", b["rate"]), ("int", b["invoices"]), ("money", b["taxable_base"]), ("money", b["tax_amount"])] for b in r["sales_by_rate"]],
    )]
    monthly = [(
        "التفصيل الشهري داخل الفترة",
        ["الشهر", "مخرجات", "مدخلات", "صافي"],
        [[("text", m["month"]), ("money", m["output_vat"]), ("money", m["input_vat"]), ("money", m["net"])] for m in r["monthly"]],
    )]
    return head + boxes + detail + monthly


@router.get("/vat-return/form-xlsx")
def vat_return_form_xlsx(
    year: Optional[int] = Query(None),
    period_type: str = Query("quarter", pattern="^(month|quarter)$"),
    period: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """نموذج إقرار القيمة المضافة الربعي/الشهري بترتيب خانات النموذج الرسمي."""
    company_id = _company_id(user)
    y = year or date.today().year
    p = period or (1 if period_type == "quarter" else date.today().month)
    start, end = _period_range(y, period_type, p)
    tables = _vat_form_tables(db, company_id, start, end, period_type, p, y)
    fname = f"vat-form-{period_type}{p}-{y}"
    return FastResponse(
        content=build_tables_xlsx("إقرار ضريبة القيمة المضافة", _period_label(period_type, p, y), tables),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'},
    )


@router.get("/vat-return/form-pdf")
def vat_return_form_pdf(
    year: Optional[int] = Query(None),
    period_type: str = Query("quarter", pattern="^(month|quarter)$"),
    period: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    company_id = _company_id(user)
    y = year or date.today().year
    p = period or (1 if period_type == "quarter" else date.today().month)
    start, end = _period_range(y, period_type, p)
    tables = _vat_form_tables(db, company_id, start, end, period_type, p, y)
    fname = f"vat-form-{period_type}{p}-{y}"
    return FastResponse(
        content=build_tables_pdf("إقرار ضريبة القيمة المضافة", _period_label(period_type, p, y), tables),
        media_type=PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="{fname}.pdf"'},
    )


def _withholding_form_tables(db: Session, company_id: int, start: date, end: date, year: int, month: int) -> list:
    """نموذج الخصم والإضافة الشهري (المادة 62) — سجل لكل مورد/كود ببيانات الممول."""
    company = db.get(models.Company, company_id)
    rep = _withholding_report(db, company_id, start, end)
    # تجميع (مورد، كود): الوعاء = قيمة السندات، النسبة من الأكواد
    groups: dict = {}
    for row in rep["rows"]:
        key = (row["supplier_id"], row["code_name"])
        g = groups.setdefault(key, {"supplier_id": row["supplier_id"], "supplier": row["supplier_name"], "code": row["code_name"], "count": 0, "base": Decimal("0"), "tax": Decimal("0"), "cash": Decimal("0")})
        g["count"] += 1
        g["base"] += row["amount"]
        g["tax"] += row["withholding"]
        g["cash"] += row["net_cash"]
    rate_by_name = {c.name: c.rate for c in db.query(models.WithholdingCode).filter(models.WithholdingCode.company_id == company_id)}
    rows = []
    for g in sorted(groups.values(), key=lambda x: (x["supplier"] or "", x["code"])):
        supp = db.get(models.Supplier, g["supplier_id"]) if g["supplier_id"] else None
        tin = supp.tax_registration_number if supp else None
        rate = rate_by_name.get(g["code"])
        rows.append([
            ("text", g["supplier"] or "—"),
            ("text", tin or ""),
            ("text", g["code"]),
            ("int", g["count"]),
            ("money", g["base"]),
            ("money", rate if rate is not None else Decimal("0")),
            ("money", g["tax"]),
            ("money", g["cash"]),
        ])
    head = [(
        "بيانات الممول",
        ["البند", "البيان"],
        [
            [("text", "اسم الممول (صاحب المنبع)"), ("text", company.name if company else "")],
            [("text", "الملف الضريبي"), ("text", (company.eta_tin if company and company.eta_tin else ""))],
            [("text", "الفترة"), ("text", f"شهر {month} {year}")],
            [("text", "إجمالي ما خصمنا وأضفنا خلال الفترة"), ("money", rep["total_withheld"])],
            [("text", "إقرار"), ("text", "نقر بأننا خصمنا الضريبة وفق المادة (62) وسنوردها في موعدها")],
        ],
    )]
    body = [(
        "سجل الخصم والإضافة للفترة",
        ["المورد (الممول)", "الملف الضريبي", "نوع التوريد", "عدد السندات", "إجمالي الوعاء", "النسبة %", "الضريبة المحتجزة", "النقدية المدفوعة"],
        rows or [[("text", "لا توجد سندات في هذه الفترة")] + [("text", "")] * 7],
    )]
    return head + body


@router.get("/withholding/form-xlsx")
def withholding_form_xlsx(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """نموذج الخصم والإضافة الشهري — سجل الموردين ببياناتهم الضريبية للورود للمصلحة."""
    company_id = _company_id(user)
    y = year or date.today().year
    m = month or date.today().month
    start = date(y, m, 1)
    end = date(y + (m // 12), (m % 12) + 1, 1) - timedelta(days=1)
    tables = _withholding_form_tables(db, company_id, start, end, y, m)
    return FastResponse(
        content=build_tables_xlsx("ضريبة الخصم والإضافة — النموذج الشهري", f"شهر {m} {y}", tables),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="withholding-form-{y}-{m:02d}.xlsx"'},
    )


@router.get("/withholding/form-pdf")
def withholding_form_pdf(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    company_id = _company_id(user)
    y = year or date.today().year
    m = month or date.today().month
    start = date(y, m, 1)
    end = date(y + (m // 12), (m % 12) + 1, 1) - timedelta(days=1)
    tables = _withholding_form_tables(db, company_id, start, end, y, m)
    return FastResponse(
        content=build_tables_pdf("ضريبة الخصم والإضافة — النموذج الشهري", f"شهر {m} {y}", tables),
        media_type=PDF_MIME,
        headers={"Content-Disposition": f'attachment; filename="withholding-form-{y}-{m:02d}.pdf"'},
    )
