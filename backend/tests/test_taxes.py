"""اختبارات موديول الضرائب: إقرار القيمة المضافة المطوّر، ضريبة الخصم والإضافة
(قيود السندات 3 أسطر + إلغاؤها + التقرير)، وضريبة كسب العمل بالشرائح التصاعدية."""
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from tests.test_warehouse_stock import make_warehouses


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    assert c.post("/auth/setup", json={"username": "boss", "password": "long-password"}).status_code == 201
    token = c.post("/auth/login", data={"username": "boss", "password": "long-password"}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c, engine, factory


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def test_vat_return_totals_and_breakdown():
    c, engine, _ = _client()
    try:
        wh, _ = make_warehouses(c)
        cust = ok(c.post("/customers", json={"name": "عميل"}), 201)
        p = ok(c.post("/products", json={"sku": "V1", "name": "صنف", "sale_price": "100",
                                         "cost_price": "50", "quantity": 100}), 201)
        # بيع بضريبة 14% → مخرجات 14
        so = ok(c.post("/sales-orders", json={
            "customer_id": cust["id"], "warehouse_id": wh["id"], "tax_rate": "14",
            "items": [{"product_id": p["id"], "quantity": 1}],
        }), 201)
        assert Decimal(str(so["tax_amount"])) == Decimal("14.00")
        ok(c.post(f"/sales-orders/{so['id']}/confirm"))
        r = ok(c.get("/taxes/vat-return"))
        assert Decimal(str(r["output_vat"])) == Decimal("14.00")
        assert r["net_payable"] == Decimal(str(r["output_vat"])) - Decimal(str(r["input_vat"]))
        rate_rows = [b for b in r["sales_by_rate"] if Decimal(str(b["rate"])) == Decimal("14.00")]
        assert len(rate_rows) == 1 and rate_rows[0]["invoices"] == 1
        assert Decimal(str(rate_rows[0]["taxable_base"])) == Decimal("100.00")
        assert Decimal(str(rate_rows[0]["tax_amount"])) == Decimal("14.00")
        # المشتريات بضريبة → مدخلات (أمر الشراء يُستلم تلقائيًا عند الإنشاء)
        supp = ok(c.post("/suppliers", json={"name": "مورد"}), 201)
        po = ok(c.post("/purchase-orders", json={
            "supplier_id": supp["id"], "warehouse_id": wh["id"], "tax_rate": "14",
            "items": [{"product_id": p["id"], "quantity": 2, "unit_cost": "50"}],
        }), 201)
        assert po["status"] == "received"
        r2 = ok(c.get("/taxes/vat-return"))
        assert Decimal(str(r2["input_vat"])) == Decimal("14.00")
        assert len(r2["monthly"]) >= 1
        # تصدير
        assert c.get("/taxes/vat-return/xlsx").status_code == 200
        assert c.get("/taxes/vat-return/pdf").status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_withholding_codes_crud_and_seed():
    c, engine, _ = _client()
    try:
        codes = ok(c.get("/taxes/withholding/codes"))
        names = [x["name"] for x in codes]
        assert any("الخدمات" in n for n in names) and len(codes) >= 8
        # بذر idempotent
        assert len(ok(c.get("/taxes/withholding/codes"))) == len(codes)
        code = ok(c.post("/taxes/withholding/codes", json={"name": "أتعاب استشارات", "rate": "5"}), 201)
        assert Decimal(str(code["rate"])) == Decimal("5.00")
        ok(c.patch(f"/taxes/withholding/codes/{code['id']}", json={"rate": "4.5"}), 200)
        assert Decimal(str(ok(c.get("/taxes/withholding/codes"))[0]["rate"])) >= 0
        dup = c.post("/taxes/withholding/codes", json={"name": "أتعاب استشارات", "rate": "5"})
        assert dup.status_code == 409
        assert c.delete(f"/taxes/withholding/codes/{code['id']}").status_code == 204
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_withholding_payment_gl_and_void():
    c, engine, factory = _client()
    try:
        branch = ok(c.post("/company/branches", json={"name": "فرع"}), 201)
        safe = ok(c.post("/safes", json={"name": "خزينة", "branch_id": branch["id"]}), 201)
        supp = ok(c.post("/suppliers", json={"name": "مورد خدمات"}), 201)
        code = ok(c.get("/taxes/withholding/codes"))
        svc = next(x for x in code if "الخدمات" in x["name"])
        # سند دفع 10,000 مع محتجز 300 (3%)
        pay = ok(c.post("/payments", json={
            "supplier_id": supp["id"], "amount": "10000", "safe_id": safe["id"],
            "method": "cash", "withholding_amount": "300", "withholding_code_id": svc["id"],
        }), 201)
        assert Decimal(str(pay["withholding_amount"])) == Decimal("300.00")
        assert pay["withholding_code_name"] and "الخدمات" in pay["withholding_code_name"]
        # القيد: مورد مدين 10,000 · نقدية دائن 9,700 · محتجز دائن 300
        db = factory()
        safe_code = db.execute(text(
            "SELECT ca.code FROM chart_accounts ca WHERE ca.name = :n"
        ), {"n": "Safe: خزينة"}).scalar()
        assert safe_code, "حساب الخزينة غير موجود"
        je = db.execute(text(
            "SELECT je.id FROM journal_entries je WHERE je.reference = :r"
        ), {"r": f"PAY-{pay['id']}"}).scalar()
        assert je is not None
        lines = db.execute(text(
            "SELECT ca.code, ji.debit, ji.credit FROM journal_items ji "
            "JOIN chart_accounts ca ON ca.id = ji.account_id WHERE ji.entry_id = :e ORDER BY ji.id"
        ), {"e": je}).all()
        codes = {row[0]: (Decimal(str(row[1] or 0)), Decimal(str(row[2] or 0))) for row in lines}
        assert len(lines) == 3
        assert codes["2110"][0] == Decimal("10000.00")          # المورد بالكامل
        assert codes[safe_code][1] == Decimal("9700.00")        # النقدية بالصافي
        assert codes["2135"][1] == Decimal("300.00")            # الخصم والإضافة
        assert sum(l[1] for l in lines) == sum(l[2] for l in lines)
        db.close()
        # رصيد الخزينة نقص 9,700 فقط (بدون رصيد افتتاحي)
        assert Decimal(str(ok(c.get("/safes"))[0]["balance"])) == Decimal("-9700.00")
        # التقرير
        rep = ok(c.get("/taxes/withholding"))
        assert len(rep["rows"]) == 1 and Decimal(str(rep["rows"][0]["withholding"])) == Decimal("300.00")
        assert Decimal(str(rep["total_withheld"])) == Decimal("300.00")
        assert any(b["code"].startswith("الخدمات") for b in rep["by_code"])
        assert c.get("/taxes/withholding/xlsx").status_code == 200
        assert c.get("/taxes/withholding/pdf").status_code == 200
        # الإلغاء يعكس كل الأسطر الثلاثة ويرد الخزينة 9,700
        ok(c.post(f"/payments/{pay['id']}/void"))
        db = factory()
        void_lines = db.execute(text(
            "SELECT ca.code, ji.debit, ji.credit FROM journal_items ji "
            "JOIN chart_accounts ca ON ca.id = ji.account_id "
            "JOIN journal_entries je ON je.id = ji.entry_id "
            "WHERE je.reference = :r ORDER BY ji.id"
        ), {"r": f"VOID-{pay['id']}"}).all()
        v = {row[0]: (Decimal(str(row[1] or 0)), Decimal(str(row[2] or 0))) for row in void_lines}
        assert v["2110"][1] == Decimal("10000.00") and v[safe_code][0] == Decimal("9700.00") and v["2135"][0] == Decimal("300.00")
        db.close()
        assert Decimal(str(ok(c.get("/safes"))[0]["balance"])) == Decimal("0.00")
        rep2 = ok(c.get("/taxes/withholding"))
        assert len(rep2["rows"]) == 0
        # مرفوضات: محتجز ≥ القيمة، وعملة أجنبية مع محتجز
        bad = c.post("/payments", json={
            "supplier_id": supp["id"], "amount": "100", "safe_id": safe["id"],
            "withholding_amount": "200",
        })
        assert bad.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_official_forms_vat_and_withholding():
    """النماذج الرسمية: خانات الإقرار الربعي + سجل الخصم والإضافة الشهري ببيانات الممول."""
    c, engine, _ = _client()
    try:
        wh, _ = make_warehouses(c)
        cust = ok(c.post("/customers", json={"name": "عميل"}), 201)
        p = ok(c.post("/products", json={"sku": "F1", "name": "صنف", "sale_price": "100",
                                         "cost_price": "50", "quantity": 50}), 201)
        supp = ok(c.post("/suppliers", json={
            "name": "مورد رسمي", "tax_registration_number": "123-456-789",
        }), 201)
        assert supp["tax_registration_number"] == "123-456-789"
        so = ok(c.post("/sales-orders", json={
            "customer_id": cust["id"], "warehouse_id": wh["id"], "tax_rate": "14",
            "items": [{"product_id": p["id"], "quantity": 1}],
        }), 201)
        ok(c.post(f"/sales-orders/{so['id']}/confirm"))
        # نموذج القيمة المضافة الربعي: ملف + pdf
        for path in ["/taxes/vat-return/form-xlsx?period_type=quarter&period=1&year=2026",
                     "/taxes/vat-return/form-pdf?period_type=quarter&period=1&year=2026",
                     "/taxes/vat-return/form-xlsx?period_type=month&period=11&year=2026"]:
            r = c.get(path)
            assert r.status_code == 200 and len(r.content) > 500, path
        # فترة غير صالحة → 422
        assert c.get("/taxes/vat-return/form-xlsx?period_type=quarter&period=7").status_code == 422
        # نموذج الخصم والإضافة الشهري: سند بمورد له ملف ضريبي ثم نموذج الشهر
        branch = ok(c.post("/company/branches", json={"name": "فرع نموذج"}), 201)
        safe = ok(c.post("/safes", json={"name": "خزينة نموذج", "branch_id": branch["id"]}), 201)
        codes = ok(c.get("/taxes/withholding/codes"))
        svc = next(x for x in codes if "الخدمات" in x["name"])
        ok(c.post("/payments", json={
            "supplier_id": supp["id"], "amount": "5000", "safe_id": safe["id"],
            "withholding_amount": "150", "withholding_code_id": svc["id"],
        }), 201)
        # شهر الفترة الفعلي (اليوم) — النموذج الشهري للشهر الحالي
        from datetime import date as _date
        today = _date.today()
        rep = ok(c.get("/taxes/withholding"))
        assert len(rep["rows"]) == 1
        assert rep["rows"][0]["supplier_name"] == "مورد رسمي"
        for path in [f"/taxes/withholding/form-xlsx?year={today.year}&month={today.month}",
                     f"/taxes/withholding/form-pdf?year={today.year}&month={today.month}"]:
            r = c.get(path)
            assert r.status_code == 200 and len(r.content) > 500, path
        # شهر بلا سندات → نموذج شاغر 200
        assert c.get("/taxes/withholding/form-xlsx?year=2030&month=1").status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_payroll_tax_progressive_calculation_and_settings():
    c, engine, _ = _client()
    try:
        # الإعدادات الافتراضية تُبذر عند أول قراءة
        s = ok(c.get("/taxes/payroll-tax/settings"))
        assert Decimal(str(s["personal_exemption"])) == Decimal("20000.00")
        assert len(s["brackets"]) >= 5
        # موظف راتبه الشهري 20,000 مع تأمينات 11%
        emp = ok(c.post("/hr/employees", json={"full_name": "موظف ضريبي", "basic_salary": "20000"}), 201)
        ok(c.post("/hr/salary-components", json={
            "employee_id": emp["id"], "name": "تأمينات اجتماعية", "category": "deduction",
            "amount_mode": "percent_of_base", "percent_value": "11",
        }, ), 201)
        run = ok(c.post("/hr/payroll-runs", json={"year": 2026, "month": 11}), 201)
        assert run["employees_count"] == 1
        rep = ok(c.get(f"/taxes/payroll-tax/{run['id']}"))
        row = rep["rows"][0]
        # سنوي: 240,000 − تأمينات 26,400 − اعفاء 20,000 = وعاء 193,600
        assert Decimal(str(row["annual_gross"])) == Decimal("240000.00")
        assert Decimal(str(row["annual_si"])) == Decimal("26400.00")
        assert Decimal(str(row["annual_taxable"])) == Decimal("193600.00")
        # شرائح: (95,000−40,000)×15% + (165,000−95,000)×20% + (193,600−165,000)×22.5%
        expected_annual = (Decimal("55000") * Decimal("0.15") + Decimal("70000") * Decimal("0.20")
                           + Decimal("28600") * Decimal("0.225")).quantize(Decimal("0.01"))
        assert Decimal(str(row["annual_tax"])) == expected_annual
        assert Decimal(str(row["monthly_tax"])) == (expected_annual / 12).quantize(Decimal("0.01"))
        # المقطوع فعليًا من القسيمة (بند ضريبة) قد يختلف → الفرق متسق
        assert Decimal(str(row["difference"])) == Decimal(str(row["actual_withheld"])) - Decimal(str(row["monthly_tax"]))
        assert Decimal(str(rep["total_difference"])) == Decimal(str(rep["total_actual"])) - Decimal(str(rep["total_monthly_tax"]))
        # تعديل الإعدادات: تخفيض 10% للمرتبات
        ok(c.put("/taxes/payroll-tax/settings", json={"wage_reduction_percent": "10"}), 200)
        rep2 = ok(c.get(f"/taxes/payroll-tax/{run['id']}"))
        row2 = rep2["rows"][0]
        assert Decimal(str(row2["annual_tax"])) == (expected_annual * Decimal("0.9")).quantize(Decimal("0.01"))
        # شرائح مخصصة: 0% حتى 100,000 ثم 20%
        ok(c.put("/taxes/payroll-tax/settings", json={"brackets": [
            {"min_amount": "0", "max_amount": "100000", "rate": "0", "sort": 0},
            {"min_amount": "100000", "max_amount": None, "rate": "20", "sort": 1},
        ]}), 200)
        rep3 = ok(c.get(f"/taxes/payroll-tax/{run['id']}"))
        # وعاء 193,600 → (193,600−100,000)×20% × 0.9 (التخفيض ما زال 10%)
        expected3 = (Decimal("93600") * Decimal("0.20") * Decimal("0.9")).quantize(Decimal("0.01"))
        assert Decimal(str(rep3["rows"][0]["annual_tax"])) == expected3
        # شرائح متقاطعة مرفوضة
        bad = c.put("/taxes/payroll-tax/settings", json={"brackets": [
            {"min_amount": "0", "max_amount": "100000", "rate": "0", "sort": 0},
            {"min_amount": "50000", "max_amount": None, "rate": "20", "sort": 1},
        ]})
        assert bad.status_code == 422
        assert c.get(f"/taxes/payroll-tax/{run['id']}/xlsx").status_code == 200
        assert c.get(f"/taxes/payroll-tax/{run['id']}/pdf").status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
