"""اختبارات تطويرات المحاسبة 2026-11 (المرحلة الثانية):
VAT على البيع/الشراء/POS + إقرار الضريبة · قيد الإقفال السنوي · الأشهر المالية ·
تنبيهات الشيكات · القيود المتكررة · Maker-Checker · المرفقات · المطابقة البنكية ·
أداء التقارير (استبعاد المجموعات) · ETA JSON.
"""
import io
import json as _json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from tests.test_warehouse_stock import make_warehouses


@pytest.fixture()
def api():
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
    client = TestClient(app)
    assert client.post("/auth/setup", json={"username": "boss", "password": "long-password"}).status_code == 201
    token = client.post("/auth/login", data={"username": "boss", "password": "long-password"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    app.dependency_overrides.pop(get_db, None)


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


_WH_CACHE: dict = {}


def _wh(c):
    key = id(c)
    if key not in _WH_CACHE:
        w1, _ = make_warehouses(c)
        _WH_CACHE.clear()  # عميل واحد نشط في كل اختبار (fixture جديد)
        _WH_CACHE[key] = w1
    return _WH_CACHE[key]


def mk_product(c, name, wh=None, qty=0, cost="30", price="100"):
    return ok(c.post("/products", json={
        "sku": f"SKU-{name}", "name": name, "sale_price": price, "cost_price": cost,
        "quantity": qty, "warehouse_id": wh["id"] if wh else None,
    }), 201)


def _coa(c):
    return {a["code"]: a for a in ok(c.get("/chart-of-accounts"))}


def _bal(c, code):
    return Decimal(str(_coa(c)[code]["balance"]))


def _branch(c, name="فرع"):
    return ok(c.post("/company/branches", json={"name": name}), 201)


def _bank(c, name="بنك رئيسي"):
    return ok(c.post("/banks", json={"name": name, "branch_id": _branch(c)["id"]}), 201)


def _tb_balanced(c):
    tb = ok(c.get("/reports/financial/trial-balance"))
    d = sum(Decimal(str(r["balance"])) for r in tb if r["type"] in ("asset", "expense"))
    cr = sum(Decimal(str(r["balance"])) for r in tb if r["type"] in ("liability", "equity", "revenue"))
    return d == cr, d, cr


# ================================================== 1) VAT على البيع والشراء والـ POS
def test_sales_order_tax_splits_vat_in_journal(api):
    c = api
    p = mk_product(c, "T1", wh=_wh(c), qty=10, price="100")
    cust = ok(c.post("/customers", json={"name": "عميل VAT"}), 201)
    wh = _wh(c)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"], "tax_rate": "14",
        "items": [{"product_id": p["id"], "quantity": 2}],
    }), 201)
    assert Decimal(str(so["subtotal"])) == Decimal("200")
    assert Decimal(str(so["tax_amount"])) == Decimal("28")
    assert Decimal(str(so["total_amount"])) == Decimal("228")
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    # العميل مدينة بالإجمالي 228 · الإيراد صافي 200 · VAT مخرجات 28
    assert _bal(c, "1120") == Decimal("228")
    assert _bal(c, "4101") == Decimal("200")
    assert _bal(c, "2130") == Decimal("28")
    balanced, d, cr = _tb_balanced(c)
    assert balanced, f"ميزان غير متوازن: {d} != {cr}"


def test_pos_checkout_with_tax_posts_vat_and_receipt_total(api):
    c = api
    p = mk_product(c, "PT", wh=_wh(c), qty=10, price="50")
    safe_branch = _branch(c, "فرع خزينة")
    safe = ok(c.post("/safes", json={"name": "POS خزينة", "branch_id": safe_branch["id"]}), 201)
    r = ok(c.post("/pos/checkout", json={
        "warehouse_id": ok(c.get("/warehouses"), 200)[0]["id"],
        "items": [{"product_id": p["id"], "quantity": 2, "unit_price": "50"}],
        "safe_id": safe["id"], "tax_rate": "14",
    }), 201)
    assert Decimal(str(r["total"])) == Decimal("114")  # 100 + 14%
    assert _bal(c, "2130") == Decimal("14")
    assert _bal(c, "4101") == Decimal("100")
    balanced, _, _ = _tb_balanced(c)
    assert balanced


def test_purchase_order_tax_splits_vat_input(api):
    c = api
    p = mk_product(c, "PU")
    sup = ok(c.post("/suppliers", json={"name": "مورد VAT"}), 201)
    wh = _wh(c)
    po = ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": wh["id"], "payment_mode": "credit",
        "tax_rate": "14",
        "items": [{"product_id": p["id"], "quantity": 10, "unit_cost": "30"}],
    }), 201)
    assert Decimal(str(po["total_amount"])) == Decimal("342")  # 300 + 14%
    # المخزون بالصافي 300 وضريبة المدخلات 42
    assert _bal(c, "1101") == Decimal("300")
    assert _bal(c, "1145") == Decimal("42")
    assert _bal(c, "2110") == Decimal("342")
    balanced, _, _ = _tb_balanced(c)
    assert balanced


def test_vat_return_report_aggregates_period(api):
    c = api
    p = mk_product(c, "VR", wh=_wh(c), qty=10, price="100")
    cust = ok(c.post("/customers", json={"name": "عميل إقرار"}), 201)
    sup = ok(c.post("/suppliers", json={"name": "مورد إقرار"}), 201)
    wh = _wh(c)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"], "tax_rate": "14",
        "items": [{"product_id": p["id"], "quantity": 2}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": wh["id"], "payment_mode": "credit", "tax_rate": "14",
        "items": [{"product_id": p["id"], "quantity": 5, "unit_cost": "30"}],
    }), 201)
    r = ok(c.get("/reports/financial/vat-return"), 200)
    assert Decimal(str(r["output_vat"])) == Decimal("28")
    assert Decimal(str(r["input_vat"])) == Decimal("21")
    assert Decimal(str(r["net_payable"])) == Decimal("7")
    # xlsx يُبنى دون خطأ
    x = c.get("/reports/financial/vat-return/xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


# ================================================== 2) قيد الإقفال السنوي
def test_fiscal_year_close_posts_closing_entry_and_creates_periods(api):
    c = api
    p = mk_product(c, "CL", wh=_wh(c), qty=5, price="100")
    cust = ok(c.post("/customers", json={"name": "عميل إقفال"}), 201)
    wh = _wh(c)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 1}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    # مصروف إيجار 40
    leaf_cash = _coa(c)["1111"]
    leaf_rent = _coa(c)["5220"]
    ok(c.post("/journal-entries", json={"description": "إيجار", "items": [
        {"account_id": leaf_rent["id"], "debit": "40", "credit": "0"},
        {"account_id": leaf_cash["id"], "debit": "0", "credit": "40"},
    ]}), 201)
    profit_before = _bal(c, "3200")
    fys = ok(c.get("/fiscal-years"))
    fy = fys[0]
    # الأشهر تتولد تلقائيًا عند الطلب
    periods = ok(c.get(f"/fiscal-years/{fy['id']}/periods"))
    assert len(periods) == 12
    ok(c.patch(f"/fiscal-years/{fy['id']}", json={"is_closed": True}), 200)
    # قيد الإقفال موجود
    entries = ok(c.get("/journal-entries?limit=100"))
    closing = [e for e in entries if e.get("reference") == f"FY-CLOSE-{fy['id']}"]
    assert len(closing) == 1, "قيد الإقفال مفقود"
    # الإيراد صفّر والمصاريف صفّرت، والأرباح المبقاة +30
    # (ربح صافٍ = مبيع 100 − إيجار 40 − COGS 30)
    assert _bal(c, "4101") == Decimal("0")
    assert _bal(c, "5220") == Decimal("0")
    assert _bal(c, "5100") == Decimal("0")
    assert _bal(c, "3200") == profit_before + Decimal("30")
    # السنة التالية اتولدت بأشهرها
    fys2 = ok(c.get("/fiscal-years"))
    nxt = [f for f in fys2 if f["start_date"] == f"{date.today().year + 1}-01-01"]
    assert nxt, "السنة التالية لم تتولد"
    assert len(ok(c.get(f"/fiscal-years/{nxt[0]['id']}/periods"))) == 12
    # ميزانية متوازنة بعد الإقفال
    bs = ok(c.get("/reports/financial/balance-sheet"))
    assert bs["is_balanced"] is True


def test_closed_month_blocks_posting(api):
    c = api
    fys = ok(c.get("/fiscal-years"))
    fy = fys[0]
    periods = ok(c.get(f"/fiscal-years/{fy['id']}/periods"))
    today = date.today()
    target = [p for p in periods if p["start_date"].startswith(str(today.year)) and
              int(p["start_date"][5:7]) == today.month][0]
    ok(c.patch(f"/fiscal-years/{fy['id']}/periods/{target['id']}", json={"is_closed": True}), 200)
    leaf_a = _coa(c)["1111"]
    leaf_b = _coa(c)["1112"]
    r = c.post("/journal-entries", json={"description": "قيد في شهر مقفول", "items": [
        {"account_id": leaf_a["id"], "debit": "5", "credit": "0"},
        {"account_id": leaf_b["id"], "debit": "0", "credit": "5"},
    ]})
    assert r.status_code == 409 and "مقفول" in r.json()["detail"]


# ================================================== 3) تنبيهات الشيكات
def test_dashboard_counts_cheques_due_soon(api):
    c = api
    bank = _bank(c)
    cust = ok(c.post("/customers", json={"name": "عميل شيك مستحق"}), 201)
    # شيك يستحق اليوم + شيك بعيد
    ok(c.post("/cheques", json={
        "direction": "received", "number": "DUE1", "bank_id": bank["id"], "amount": "500",
        "customer_id": cust["id"], "cheque_date": str(date.today()),
        "due_date": str(date.today() + timedelta(days=3)),
    }), 201)
    ok(c.post("/cheques", json={
        "direction": "received", "number": "FAR1", "bank_id": bank["id"], "amount": "100",
        "customer_id": cust["id"], "cheque_date": str(date.today()),
        "due_date": str(date.today() + timedelta(days=90)),
    }), 201)
    dash = ok(c.get("/reports/dashboard"), 200)
    assert dash["cheques_due_soon"] == 1


# ================================================== 5) القيود المتكررة
def test_recurring_journal_run_posts_and_advances(api):
    c = api
    cash = _coa(c)["1111"]
    rent = _coa(c)["5220"]
    tpl = ok(c.post("/recurring-journals", json={
        "name": "إيجار المقر", "description": "إيجار شهري", "day_of_month": 1,
        "next_run_date": str(date.today()),
        "items": [
            {"account_id": rent["id"], "debit": "1000", "credit": "0"},
            {"account_id": cash["id"], "debit": "0", "credit": "1000"},
        ],
    }), 201)
    due = ok(c.get("/recurring-journals/due"))
    assert [t["id"] for t in due] == [tpl["id"]]
    r = ok(c.post("/recurring-journals/run"), 200)
    assert r["count"] == 1 and r["ran"][0]["template_id"] == tpl["id"]
    je = ok(c.get(f"/journal-entries/{r['ran'][0]['entry_id']}"))
    assert "إيجار شهري" in je["description"]
    assert _bal(c, "5220") == Decimal("1000")
    # الاستحقاق قُدّم شهرًا — لم يعد مستحقًا
    assert ok(c.get("/recurring-journals/due")) == []
    with pytest.raises(AssertionError):
        ok(c.post(f"/recurring-journals/{tpl['id']}/run"), 200)
    # قالب غير موزون مرفوض
    r2 = c.post("/recurring-journals", json={
        "name": "غلط", "description": "غير موزون", "next_run_date": str(date.today()),
        "items": [
            {"account_id": rent["id"], "debit": "100", "credit": "0"},
            {"account_id": cash["id"], "debit": "0", "credit": "50"},
        ],
    })
    assert r2.status_code == 422


# ================================================== 8) Maker-Checker
def _staff_client(c, username="clerk1"):
    branch = _branch(c, "فرع موظف")
    r = c.post("/auth/users", json={"username": username, "password": "long-password", "role": "staff", "branch_ids": [branch["id"]]})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    sec = ok(c.post("/access-sections", json={"code": f"s{uid}", "name": "قسم قيود"}), 201)
    ok(c.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": ["accounting.journal.create", "accounting.account.view"]}))
    ok(c.put(f"/auth/users/{uid}/section", json={"section_id": sec["id"]}))
    tok = c.post("/auth/login", data={"username": username, "password": "long-password"}).json()["access_token"]
    staff = TestClient(app)
    staff.headers["Authorization"] = f"Bearer {tok}"
    return staff


def test_maker_checker_parks_entry_until_approved(api, monkeypatch):
    from app.routers import journal_entries as je_mod
    monkeypatch.setattr(je_mod, "APPROVAL_THRESHOLD", Decimal("500"))
    c = api
    staff = _staff_client(c)
    cash = _coa(c)["1111"]
    other = _coa(c)["1112"]
    # قيد فوق الحد → معلّق والأرصدة لم تُلمس
    r = ok(staff.post("/journal-entries", json={"description": "قيد كبير", "items": [
        {"account_id": cash["id"], "debit": "900", "credit": "0"},
        {"account_id": other["id"], "debit": "0", "credit": "900"},
    ]}), 201)
    assert r["status"] == "pending_approval"
    assert _bal(c, "1111") == Decimal("0")
    # قيد تحت الحد → يُرحّل فورًا
    r2 = ok(staff.post("/journal-entries", json={"description": "قيد صغير", "items": [
        {"account_id": cash["id"], "debit": "10", "credit": "0"},
        {"account_id": other["id"], "debit": "0", "credit": "10"},
    ]}), 201)
    assert r2["status"] == "posted"
    assert _bal(c, "1111") == Decimal("10")
    # المدير يعتمد → الأرصدة تُطبق
    pending = ok(c.get("/journal-entries/pending"))
    assert [p["id"] for p in pending] == [r["id"]]
    ok(c.post(f"/journal-entries/{r['id']}/approve"), 200)
    assert _bal(c, "1111") == Decimal("910")
    # رفض: يُحذف بلا أثر
    r3 = ok(staff.post("/journal-entries", json={"description": "قيد مرفوض", "items": [
        {"account_id": cash["id"], "debit": "800", "credit": "0"},
        {"account_id": other["id"], "debit": "0", "credit": "800"},
    ]}), 201)
    ok(c.post(f"/journal-entries/{r3['id']}/reject"), 200)
    assert c.get(f"/journal-entries/{r3['id']}").status_code == 404
    assert _bal(c, "1111") == Decimal("910")


# ================================================== 7) المرفقات
def test_attachments_roundtrip_on_payment(api):
    c = api
    safe = ok(c.post("/safes", json={"name": "خزينة مرفقات", "branch_id": _branch(c)["id"]}), 201)
    cust = ok(c.post("/customers", json={"name": "عميل مرفق"}), 201)
    pay = ok(c.post("/payments", json={"customer_id": cust["id"], "safe_id": safe["id"], "amount": "25"}), 201)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    up = c.post(f"/attachments/payment/{pay['id']}",
                files={"file": ("invoice.png", io.BytesIO(png), "image/png")})
    assert up.status_code == 201, up.text
    att = up.json()
    assert att["size"] == len(png)
    lst = ok(c.get(f"/attachments/payment/{pay['id']}"))
    assert [a["id"] for a in lst] == [att["id"]]
    dl = c.get(f"/attachments/{att['id']}/download")
    assert dl.status_code == 200 and dl.content == png
    # مرفق على كيان غير موجود → 404
    assert c.post("/attachments/payment/99999", files={"file": ("x.png", io.BytesIO(png), "image/png")}).status_code == 404
    # حذف (مدير)
    assert c.delete(f"/attachments/{att['id']}").status_code == 204
    assert c.get(f"/attachments/{att['id']}/download").status_code == 404
    # نوع غير مسموح
    bad = c.post(f"/attachments/payment/{pay['id']}", files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/x-msdownload")})
    assert bad.status_code == 422


# ================================================== 9) المطابقة البنكية
def test_bank_statement_import_match_and_summary(api):
    c = api
    bank = _bank(c)
    cust = ok(c.post("/customers", json={"name": "عميل بنك"}), 201)
    today = date.today()
    # سند قبض بنكي 1000 على نفس البنك
    ok(c.post("/payments", json={"customer_id": cust["id"], "bank_id": bank["id"], "amount": "1000", "method": "bank"}), 201)
    payments = ok(c.get(f"/payments?bank_id={bank['id']}"))
    pay_id = payments[0]["id"]
    csv_text = (
        "date,description,amount,reference\n"
        f"{today.isoformat()},تحويل عميل,1000.00,تحويل رقم 1\n"
        f"{today.isoformat()},رسوم بنكية,-50.00,\n"
        "bad-date,سطر غلط,10,\n"
    )
    imp = c.post(f"/banks/{bank['id']}/statements/import",
                 files={"file": ("statement.csv", io.BytesIO(csv_text.encode()), "text/csv")})
    assert imp.status_code == 201, imp.text
    lines = imp.json()
    assert len(lines) == 2  # السطر الغلط استُبعد
    inside = [l for l in lines if Decimal(str(l["amount"])) == Decimal("1000.00")][0]
    fees = [l for l in lines if Decimal(str(l["amount"])) == Decimal("-50.00")][0]
    # مطابقة سطر 1000 مع السند
    matched = ok(c.post(f"/banks/{bank['id']}/statements/{inside['id']}/match", json={"payment_id": pay_id}), 200)
    assert matched["matched_payment_id"] == pay_id
    # مطابقة نفس السند لسطر آخر ممنوعة
    r = c.post(f"/banks/{bank['id']}/statements/{fees['id']}/match", json={"payment_id": pay_id})
    assert r.status_code == 409
    # مطابقة بمبلغ مختلف ممنوعة
    other_bank_pay = ok(c.post("/payments", json={"customer_id": cust["id"], "bank_id": bank["id"], "amount": "77", "method": "bank"}), 201)
    r = c.post(f"/banks/{bank['id']}/statements/{fees['id']}/match", json={"payment_id": other_bank_pay["id"]})
    assert r.status_code == 422
    # الملخص
    s = ok(c.get(f"/banks/{bank['id']}/statements/summary"))
    assert Decimal(str(s["statement_balance"])) == Decimal("950.00")
    assert Decimal(str(s["matched_total"])) == Decimal("1000.00")
    assert s["unmatched_count"] == 1
    # فك المطابقة
    ok(c.post(f"/banks/{bank['id']}/statements/{inside['id']}/match", json={"payment_id": None}), 200)
    s2 = ok(c.get(f"/banks/{bank['id']}/statements/summary"))
    assert Decimal(str(s2["matched_total"])) == Decimal("0.00")


# ================================================== 4) أداء + استبعاد المجموعات + PDF
def test_trial_balance_excludes_groups_and_pdfs_work(api):
    c = api
    cash = _coa(c)["1111"]
    other = _coa(c)["1112"]
    ok(c.post("/journal-entries", json={"description": "حركة", "items": [
        {"account_id": cash["id"], "debit": "70", "credit": "0"},
        {"account_id": other["id"], "debit": "0", "credit": "70"},
    ]}), 201)
    tb = ok(c.get("/reports/financial/trial-balance"))
    codes = [r["code"] for r in tb]
    assert "1110" not in codes  # المجموعية مستبعدة
    assert "1111" in codes
    for path in ("/reports/financial/trial-balance/pdf", "/reports/financial/profit-loss/pdf", "/reports/financial/balance-sheet/pdf"):
        r = c.get(path)
        assert r.status_code == 200, f"{path}: {r.text}"
        assert r.content[:4] == b"%PDF"


# ================================================== 10) ETA JSON
def test_eta_json_export_shape(api):
    c = api
    p = mk_product(c, "ETA1", wh=_wh(c), qty=5, price="200")
    cust = ok(c.post("/customers", json={"name": "شركة العميل"}), 201)
    wh = _wh(c)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"], "tax_rate": "14",
        "items": [{"product_id": p["id"], "quantity": 3}],
    }), 201)
    # مسودة مرفوضة قبل التأكيد
    assert c.get(f"/sales-orders/{so['id']}/eta-json").status_code == 409
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    r = c.get(f"/sales-orders/{so['id']}/eta-json")
    assert r.status_code == 200
    doc = _json.loads(r.content)
    assert doc["documentType"] == "I" and doc["internalID"] == f"SO-{so['id']}"
    assert len(doc["invoiceLines"]) == 1
    assert doc["totalSalesAmount"] == 600.0
    assert doc["totalAmount"] == 684.0
    assert doc["taxTotals"][0]["amount"] == 84.0


# ================================================== الحد الائتماني للعملاء
def _sales_staff(c, username: str, extra_perms: list, warehouse_id=None):
    branch = _branch(c, f"فرع {username}")
    r = c.post("/auth/users", json={"username": username, "password": "long-password", "role": "staff",
                                    "branch_ids": [branch["id"]], "warehouse_ids": [warehouse_id] if warehouse_id else []})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    sec = ok(c.post("/access-sections", json={"code": f"cl{uid}", "name": f"قسم {username}"}), 201)
    ok(c.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": [
        "sales.order.view", "sales.order.create", "sales.order.confirm", *extra_perms,
    ]}))
    ok(c.put(f"/auth/users/{uid}/section", json={"section_id": sec["id"]}))
    tok = c.post("/auth/login", data={"username": username, "password": "long-password"}).json()["access_token"]
    staff = TestClient(app)
    staff.headers["Authorization"] = f"Bearer {tok}"
    return staff


def test_credit_limit_blocks_staff_confirm_and_payments_free_space(api):
    c = api
    wh = _wh(c)
    p = mk_product(c, "CR1", wh=wh, qty=100, price="100")
    cust = ok(c.post("/customers", json={"name": "عميل محدود", "credit_limit": "150"}), 201)
    assert Decimal(str(cust["credit_limit"])) == Decimal("150")
    staff = _sales_staff(c, "creditclerk", [], warehouse_id=wh["id"])
    # أمر 200 > الحد 150 → مرفوض للموظف
    so = ok(staff.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 2}],
    }), 201)
    r = staff.post(f"/sales-orders/{so['id']}/confirm")
    assert r.status_code == 409, r.text
    assert "الحد الائتماني" in r.json()["detail"]
    # أمر 100 ≤ الحد → يُقبل
    so2 = ok(staff.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 1}],
    }), 201)
    ok(staff.post(f"/sales-orders/{so2['id']}/confirm"), 200)
    # المديونية 100 والمتبقي 50: أمر 100 → مرفوض
    so3 = ok(staff.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 1}],
    }), 201)
    assert staff.post(f"/sales-orders/{so3['id']}/confirm").status_code == 409
    # سداد 80 (المدير) يفتح مساحة: متبقي 130 → أمر 100 يُقبل
    safe = ok(c.post("/safes", json={"name": "خزينة ائتمان", "branch_id": _branch(c, "فرع ائتمان")["id"]}), 201)
    ok(c.post("/payments", json={"customer_id": cust["id"], "safe_id": safe["id"], "amount": "80"}), 201)
    ok(staff.post(f"/sales-orders/{so3['id']}/confirm"), 200)


def test_credit_limit_bypass_rules(api):
    """موظف بصلاحية credit_exceed يتجاوز · المدير (*) يتجاوز تلقائيًا."""
    c = api
    wh = _wh(c)
    p = mk_product(c, "CR2", wh=wh, qty=100, price="100")
    cust = ok(c.post("/customers", json={"name": "عميل صلاحية", "credit_limit": "100"}), 201)
    staff = _sales_staff(c, "creditbypass", [], warehouse_id=wh["id"])  # بدون صلاحية التجاوز
    so = ok(staff.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 2}],
    }), 201)
    assert staff.post(f"/sales-orders/{so['id']}/confirm").status_code == 409
    # موظف بصلاحية credit_exceed يؤكد نفس الأمر بالتجاوز → يُقبل
    staff2 = _sales_staff(c, "creditbypass2", ["sales.order.credit_exceed"], warehouse_id=wh["id"])
    ok(staff2.post(f"/sales-orders/{so['id']}/confirm"), 200)
    # المدير يتجاوز الحد بلا صلاحية صريحة (أمر جديد فوق الحد)
    so2 = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 5}],
    }), 201)
    ok(c.post(f"/sales-orders/{so2['id']}/confirm"), 200)


def test_credit_limit_pos_partial_payment(api):
    c = api
    wh = _wh(c)
    p = mk_product(c, "CR3", wh=wh, qty=100, price="100")
    cust = ok(c.post("/customers", json={"name": "عميل نقاط بيع", "credit_limit": "60"}), 201)
    staff = _sales_staff(c, "posclerk", ["sales.pos.use"], warehouse_id=wh["id"])
    safe = ok(c.post("/safes", json={"name": "خزينة POS", "branch_id": _branch(c, "فرع POS")["id"]}), 201)
    # آجل كامل (amount_paid=0 → دين جديد 100) > الحد 60 → مرفوض
    r = staff.post("/pos/checkout", json={
        "warehouse_id": wh["id"], "customer_id": cust["id"],
        "items": [{"product_id": p["id"], "quantity": 1}],
        "amount_paid": "0",
    })
    assert r.status_code == 409 and "الحد الائتماني" in r.json()["detail"]
    # دفع 50 → آجل 50 ≤ 60 → يُقبل
    ok(staff.post("/pos/checkout", json={
        "warehouse_id": wh["id"], "customer_id": cust["id"],
        "items": [{"product_id": p["id"], "quantity": 1}],
        "amount_paid": "50", "safe_id": safe["id"],
    }), 201)


def test_customer_without_limit_is_unrestricted(api):
    c = api
    wh = _wh(c)
    p = mk_product(c, "CR4", wh=wh, qty=100, price="1000")
    cust = ok(c.post("/customers", json={"name": "عميل حر"}), 201)
    assert cust["credit_limit"] is None
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 5}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)


# ================================================== 3) الإهلاك الآلي المجمع
def test_depreciate_all_bulk_run_idempotent(api):
    c = api
    a1 = ok(c.post("/fixed-assets", json={
        "name": "مكتب", "asset_type": "أثاث", "purchase_date": str(date.today()),
        "cost": "1200", "current_book_value": "1200", "depreciation_method": "straight_line",
        "useful_life_years": 5, "salvage_value": "0",
    }), 201)
    a2 = ok(c.post("/fixed-assets", json={
        "name": "مركبة", "asset_type": "مركبة", "purchase_date": str(date.today()),
        "cost": "6000", "current_book_value": "6000", "depreciation_method": "straight_line",
        "useful_life_years": 10, "salvage_value": "0",
    }), 201)
    before_5240 = _bal(c, "5240")
    r = ok(c.post("/fixed-assets/depreciate-all", json={}), 200)
    # مكتب: 1200/60 = 20 · مركبة: 6000/120 = 50 → إجمالي 70
    assert Decimal(str(r["total"])) == Decimal("70")
    assert r["assets"] == 2 and r["entry_id"]
    assert _bal(c, "5240") == before_5240 + Decimal("70")
    assert Decimal(str(ok(c.get(f"/fixed-assets/{a1['id']}"))["current_book_value"])) == Decimal("1180")
    assert Decimal(str(ok(c.get(f"/fixed-assets/{a2['id']}"))["current_book_value"])) == Decimal("5950")
    # idempotent: نفس الشهر مرفوض
    assert c.post("/fixed-assets/depreciate-all", json={}).status_code == 409
    # أصل نضِف عليه قيمة متبقية أقل من القسط → يُهلك بالمتبقي فقط
    a3 = ok(c.post("/fixed-assets", json={
        "name": "قديم", "asset_type": "أثاث", "purchase_date": str(date.today()),
        "cost": "30", "current_book_value": "15", "accumulated_depreciation": "15",
        "depreciation_method": "straight_line", "useful_life_years": 5, "salvage_value": "0",
    }), 201)
    # الشهر الجديد: نفتح سنة/شهر جديد بتعديل التاريخ؟ الـ idempotency بالمرجع الشهري — نمرر تاريخ الشهر القادم
    from datetime import timedelta as _td
    next_month = date.today().replace(day=1) + _td(days=32)
    r2 = ok(c.post("/fixed-assets/depreciate-all", json={"date": str(next_month)}), 200)
    # القسط الشهري 0.5 → مقرّب 0.01: (30/60)=0.5 · المتبقي 15 → يُهلك 0.5
    assert Decimal(str(r2["total"])) == Decimal("70.5")
    assert Decimal(str(ok(c.get(f"/fixed-assets/{a3['id']}"))["current_book_value"])) == Decimal("14.5")


# ================================================== 4) المتوسط المرجح
def test_weighted_average_costing(api):
    c = api
    sup = ok(c.post("/suppliers", json={"name": "مورد WA"}), 201)
    wh = _wh(c)
    p = ok(c.post("/products", json={"sku": "WA1", "name": "WA1", "sale_price": "100", "cost_price": "30", "quantity": 0}), 201)
    # استلام 10 @ 30 (بداية) — استخدم أول أمر شراء لتثبيت 10 قطع
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": wh["id"], "payment_mode": "credit",
        "items": [{"product_id": p["id"], "quantity": 10, "unit_cost": "30"}],
    }), 201)
    assert Decimal(str(c.get("/products").json()[0]["cost_price"])) == Decimal("30")
    # بيع 2 → يتبقى 18
    cust = ok(c.post("/customers", json={"name": "عميل WA"}), 201)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 2}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    # استلام 10 @ 50 → المتوسط = (8×30 + 10×50)/18 = 41.11 (المتبقي بعد البيع 8)
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": wh["id"], "payment_mode": "credit",
        "items": [{"product_id": p["id"], "quantity": 10, "unit_cost": "50"}],
    }), 201)
    assert Decimal(str(c.get("/products").json()[0]["cost_price"])) == Decimal("41.11")


# ================================================== 5أ) أرباح وخسائر حسب مركز التكلفة
def test_profit_loss_by_cost_center(api):
    c = api
    cc1 = ok(c.post("/cost-centers", json={"code": "CC-S", "name": "فرع سموحة"}), 201)
    cc2 = ok(c.post("/cost-centers", json={"code": "CC-D", "name": "فرع الدقي"}), 201)
    cash = _coa(c)["1111"]
    rev = _coa(c)["4101"]
    rent = _coa(c)["5220"]
    ok(c.post("/journal-entries", json={"description": "إيراد سموحة", "items": [
        {"account_id": cash["id"], "debit": "500", "credit": "0", "cost_center_id": cc1["id"]},
        {"account_id": rev["id"], "debit": "0", "credit": "500", "cost_center_id": cc1["id"]},
    ]}), 201)
    ok(c.post("/journal-entries", json={"description": "إيجار الدقي", "items": [
        {"account_id": rent["id"], "debit": "120", "credit": "0", "cost_center_id": cc2["id"]},
        {"account_id": cash["id"], "debit": "0", "credit": "120", "cost_center_id": cc2["id"]},
    ]}), 201)
    ok(c.post("/journal-entries", json={"description": "إيراد عام", "items": [
        {"account_id": cash["id"], "debit": "300", "credit": "0"},
        {"account_id": rev["id"], "debit": "0", "credit": "300"},
    ]}), 201)
    rows = ok(c.get("/reports/financial/profit-loss-by-cost-center"), 200)
    by_name = {r["name"]: r for r in rows}
    assert Decimal(str(by_name["فرع سموحة"]["net_profit"])) == Decimal("500")
    assert Decimal(str(by_name["فرع الدقي"]["net_profit"])) == Decimal("-120")
    assert Decimal(str(by_name["بلا مركز"]["revenue"])) == Decimal("300")


# ================================================== 6) المطابقة الآلية
def test_bank_auto_match_unique_and_ambiguous(api):
    c = api
    bank = _bank(c)
    cust = ok(c.post("/customers", json={"name": "عميل أوتو"}), 201)
    today = date.today()
    # سندان: 200 فريد و 100 مكرر
    ok(c.post("/payments", json={"customer_id": cust["id"], "bank_id": bank["id"], "amount": "200", "method": "bank"}), 201)
    ok(c.post("/payments", json={"customer_id": cust["id"], "bank_id": bank["id"], "amount": "100", "method": "bank"}), 201)
    ok(c.post("/payments", json={"customer_id": cust["id"], "bank_id": bank["id"], "amount": "100", "method": "bank"}), 201)
    csv_text = (
        "date,description,amount\n"
        f"{today.isoformat()},تحويل فريد,200.00\n"
        f"{today.isoformat()},مبلغ مكرر,100.00\n"
        f"{today.isoformat()},غير موجود,999.00\n"
    )
    lines = ok(c.post(f"/banks/{bank['id']}/statements/import",
                      files={"file": ("s.csv", io.BytesIO(csv_text.encode()), "text/csv")}), 201)
    r = ok(c.post(f"/banks/{bank['id']}/statements/auto-match"), 200)
    assert r["matched"] == 1 and r["ambiguous"] == 1 and r["unmatched_left"] == 1
    matched_line = [l for l in lines if Decimal(str(l["amount"])) == Decimal("200.00")][0]
    after = {l["id"]: l for l in ok(c.get(f"/banks/{bank['id']}/statements"))}
    assert after[matched_line["id"]]["matched_payment_id"] is not None
