"""محاسبة م1 — دفاتر المراجعة: ميزان تفصيلي 4 أعمدة + شجري، كشف أستاذ برصيد جاري، إقرار الضريبة بالفواتير."""

import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


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
    assert client.post("/auth/setup", json={"username": "boss", "password": "long-password-123"}).status_code == 201
    token = client.post("/auth/login", data={"username": "boss", "password": "long-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    ok(client.post("/chart-of-accounts/seed", json={}), 201)
    yield client
    app.dependency_overrides.pop(get_db, None)


def ok(resp, code=200):
    assert resp.status_code == code, (resp.status_code, resp.text)
    return resp.json() if resp.content else None


def acc_id(c, code):
    rows = ok(c.get("/chart-of-accounts"))
    return next(a["id"] for a in rows if a["code"] == code)


def make_je(c, date, description, lines, reference=None):
    payload = {"date": date, "description": description, "items": [
        {"account_id": acc_id(c, code), "debit": d, "credit": cr} for code, d, cr in lines
    ]}
    if reference:
        payload["reference"] = reference
    return ok(c.post("/journal-entries", json=payload), 201)


def make_warehouses(c):
    return ok(c.post("/warehouses", json={"name": "Main", "code": "W1"}), 201)


# ================================================== 1) ميزان المراجعة التفصيلي

def test_trial_balance_detail_four_columns(api):
    c = api
    cash, capital, supplies = acc_id(c, "1111"), acc_id(c, "3100"), acc_id(c, "5260")
    make_je(c, "2026-01-10", "رأس مال افتتاحي", [("1111", 1000, 0), ("3100", 0, 1000)])
    make_je(c, "2026-03-05", "شراء لوازم نقدًا", [("5260", 200, 0), ("1111", 0, 200)])

    r = ok(c.get("/reports/financial/trial-balance/detail?date_from=2026-02-01&date_to=2026-03-31"))
    rows = {r_["code"]: r_ for r_ in r["rows"]}
    cash_row, cap_row, sup_row = rows["1111"], rows["3100"], rows["5260"]
    # النقدية: افتتاحي 1000 → صرف 200 في الفترة → ختامي 800
    assert cash_row["opening"] == 1000.0 and cash_row["debit"] == 0.0 and cash_row["credit"] == 200.0 and cash_row["closing"] == 800.0
    # رأس المال: افتتاحي دائن — بالإشارة المحاسبية موجب (خصوم/حقوق دائن = موجب)
    assert cap_row["opening"] == 1000.0 and cap_row["closing"] == 1000.0
    # اللوازم: صفر افتتاحي + مدين 200
    assert sup_row["opening"] == 0.0 and sup_row["debit"] == 200.0 and sup_row["closing"] == 200.0
    # إجماليات متوازنة
    t = r["totals"]
    assert t["debit"] == 200.0 and t["credit"] == 200.0
    assert t["opening_debit"] == 1000.0 and t["opening_credit"] == 1000.0
    assert t["closing_debit"] == 1000.0 and t["closing_credit"] == 1000.0
    # عمود الرصيد القديم يظل متسقًا: ختامي التفصيلي = رصيد as_of نهاية الفترة
    legacy = {r_["code"]: r_ for r_ in ok(c.get("/reports/financial/trial-balance?as_of=2026-03-31"))}
    assert Decimal(str(legacy["1111"]["balance"])) == Decimal("800")


def test_trial_balance_detail_tree_and_exports(api):
    c = api
    make_je(c, "2026-02-10", "لوازم", [("5260", 300, 0), ("1111", 0, 300)])
    r = ok(c.get("/reports/financial/trial-balance/detail?date_from=2026-02-01&date_to=2026-02-28"))
    groups = {g["code"]: g for g in r["groups"]}
    # 5260 (لوازم) تحت 5200 (تشغيلية) تحت 5000 (مصاريف) — التراكم يصل الجد
    assert groups["5200"]["debit"] == 300.0 and groups["5000"]["debit"] == 300.0
    # الأصل 1100 يرصد إجمالي الائتمان في النقدية
    assert groups["1100"]["credit"] == 300.0
    x = c.get("/reports/financial/trial-balance/detail/xlsx?date_from=2026-02-01&date_to=2026-02-28")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    p = c.get("/reports/financial/trial-balance/detail/pdf?date_from=2026-02-01&date_to=2026-02-28")
    assert p.status_code == 200 and p.content[:4] == b"%PDF"


# ================================================== 2) كشف الأستاذ العام برصيد جاري

def test_general_ledger_statement_running_balance(api):
    c = api
    make_je(c, "2026-01-10", "افتتاحي نقدية", [("1111", 1000, 0), ("3100", 0, 1000)])
    make_je(c, "2026-02-01", "مصروف نقدًا", [("5260", 100, 0), ("1111", 0, 100)])
    make_je(c, "2026-02-20", "إيداع", [("1111", 500, 0), ("3100", 0, 500)])
    cash = acc_id(c, "1111")

    r = ok(c.get(f"/reports/financial/general-ledger/statement?account_id={cash}&date_from=2026-02-01&date_to=2026-02-28"))
    assert r["account"]["code"] == "1111"
    assert r["opening"] == 1000.0  # رصيد ما قبل الفترة
    running = [row["running"] for row in r["rows"]]
    assert running == [900.0, 1400.0]  # −100 ثم +500 متسلسلة
    assert r["totals"]["debit"] == 500.0 and r["totals"]["credit"] == 100.0
    assert r["totals"]["closing"] == 1400.0
    # التسلسل زمني والمراجع تظهر
    assert r["rows"][0]["date"] <= r["rows"][1]["date"]

    x = c.get(f"/reports/financial/general-ledger/statement/xlsx?account_id={cash}")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    p = c.get(f"/reports/financial/general-ledger/statement/pdf?account_id={cash}")
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
    ok(c.get(f"/reports/financial/general-ledger/statement?account_id=999999"), 404)


# ================================================== 3) إقرار الضريبة بالفواتير

def test_vat_return_invoices_output_and_input(api):
    c = api
    w = make_warehouses(c)
    prod = ok(c.post("/products", json={"sku": "VAT-P", "name": "صنف", "sale_price": "100", "cost_price": "50", "quantity": 0, "warehouse_id": w["id"]}), 201)
    sup = ok(c.post("/suppliers", json={"name": "مورد ضريبي"}), 201)
    cust = ok(c.post("/customers", json={"name": "عميل ضريبي"}), 201)

    # مدخلات: أمر شراء بضريبة 14% (استلام فوري)
    po = ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w["id"], "tax_rate": "14",
        "items": [{"product_id": prod["id"], "quantity": 10, "unit_cost": "50"}],
    }), 201)
    # ناتج: فاتورة بيع مؤكدة بضريبة 14%
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": w["id"], "tax_rate": "14",
        "items": [{"product_id": prod["id"], "quantity": 6, "unit_price": "100"}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"))

    r = ok(c.get(f"/reports/financial/vat-return/invoices?date_from=2026-01-01&date_to=2026-12-31"))
    out = [x for x in r["output"] if x["doc"] == f"SO-{so['id']}"]
    inp = [x for x in r["input"] if x["doc"] == f"PO-{po['id']}"]
    assert len(out) == 1 and out[0]["party"] == "عميل ضريبي"
    assert Decimal(str(out[0]["vat"])) == Decimal("84.00")    # 600 × 14%
    assert Decimal(str(out[0]["net"])) == Decimal("600.00") and Decimal(str(out[0]["total"])) == Decimal("684.00")
    assert len(inp) == 1 and inp[0]["party"] == "مورد ضريبي"
    assert Decimal(str(inp[0]["vat"])) == Decimal("70.00")   # 500 × 14%
    # الملخص مطابق للإقرار المجمع
    summary = ok(c.get("/reports/financial/vat-return?date_from=2026-01-01&date_to=2026-12-31"))
    assert Decimal(str(r["summary"]["output_vat"])) == Decimal(str(summary["output_vat"]))
    assert Decimal(str(r["summary"]["input_vat"])) == Decimal(str(summary["input_vat"]))
    x = c.get("/reports/financial/vat-return/invoices/xlsx?date_from=2026-01-01&date_to=2026-12-31")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    p = c.get("/reports/financial/vat-return/invoices/pdf?date_from=2026-01-01&date_to=2026-12-31")
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
