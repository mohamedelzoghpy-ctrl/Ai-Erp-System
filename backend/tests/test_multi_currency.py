"""اختبارات العملة المتعددة (2026-11-12):
CRUD العملات · فاتورة بالدولار (الدفاتر بالجنيه) · سداد بسعر أعلى → ربح صرف 4240 ·
سداد بسعر أقل → خسارة 5350 · تصفير رصيد الطرف · إبطال سند أجنبي يقلب القيد كاملًا.
"""
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
    assert client.post("/auth/setup", json={"username": "boss", "password": "long-password-123"}).status_code == 201
    token = client.post("/auth/login", data={"username": "boss", "password": "long-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    app.dependency_overrides.pop(get_db, None)


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def _usd(c, rate="48.50"):
    currencies = ok(c.get("/currencies"))
    usd = [x for x in currencies if x["code"] == "USD"]
    if usd:
        return usd[0]
    return ok(c.post("/currencies", json={"code": "USD", "name": "دولار أمريكي", "rate": rate}), 201)


def _foreign_sale(c, customer, rate_qty=10, unit_base="48500"):
    """فاتورة مؤكدة بقيمة 10,000$ (بالجنيه حسب سعر الوارد)."""
    wh, _ = make_warehouses(c)
    p = ok(c.post("/products", json={
        "sku": "FX-P", "name": "صنف تصدير", "sale_price": unit_base, "cost_price": "20000", "quantity": 50,
    }), 201)
    total_base = Decimal(str(unit_base)) * rate_qty
    so = ok(c.post("/sales-orders", json={
        "customer_id": customer["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": rate_qty, "unit_price": str(unit_base)}],
    }), 201)
    return so, Decimal(str(so["total_amount"]))


def _bal(c, code):
    return Decimal(str({a["code"]: a for a in ok(c.get("/chart-of-accounts"))}[code]["balance"]))


# ================================================== 1) CRUD العملات
def test_currency_crud_and_validation(api):
    c = api
    usd = _usd(c)
    assert usd["code"] == "USD" and Decimal(str(usd["rate"])) == Decimal("48.50")
    # تكرار
    assert c.post("/currencies", json={"code": "USD", "name": "دولار", "rate": "50"}).status_code == 409
    # EGP ممنوعة
    assert c.post("/currencies", json={"code": "EGP", "name": "جنيه", "rate": "1"}).status_code == 422
    # تحديث سعر
    r = ok(c.patch(f"/currencies/{usd['id']}/rate", json={"rate": "49.20"}))
    assert Decimal(str(r["rate"])) == Decimal("49.20")
    ok(c.patch(f"/currencies/{usd['id']}/rate", json={"rate": "48.50"}))


# ================================================== 2) فاتورة بالدولار: الدفاتر بالجنيه
def test_foreign_sales_order_books_in_base(api):
    c = api
    _usd(c)
    cust = ok(c.post("/customers", json={"name": "عميل تصدير"}), 201)
    wh, _ = make_warehouses(c)
    p = ok(c.post("/products", json={"sku": "EXP", "name": "تصدير", "sale_price": "485000", "cost_price": "200000", "quantity": 50}), 201)
    usd = ok(c.get("/currencies"))[0]
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"], "currency_id": usd["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "485000"}],  # = 10,000$ @48.5
    }), 201)
    assert Decimal(str(so["total_amount"])) == Decimal("485000.00")   # بالجنيه
    assert so["currency_code"] == "USD"
    assert Decimal(str(so["exchange_rate"])) == Decimal("48.500000")
    assert Decimal(str(so["foreign_total"])) == Decimal("10000.00")   # بالدولار
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    # العميل مدينة 485,000 بالجنيه (الدفاتر كما هي)
    assert _bal(c, "1120") == Decimal("485000.00")


# ================================================== 3) سداد بسعر أعلى → ربح صرف
def test_fx_gain_on_higher_settlement_rate(api):
    c = api
    usd = _usd(c, rate="48.50")
    cust = ok(c.post("/customers", json={"name": "عميل ربح صرف"}), 201)
    wh, _ = make_warehouses(c)
    p = ok(c.post("/products", json={"sku": "EXP2", "name": "تصدير", "sale_price": "485000", "cost_price": "200000", "quantity": 50}), 201)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"], "currency_id": usd["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "485000"}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    br = ok(c.post("/company/branches", json={"name": "فرع صرف"}), 201)
    safe = ok(c.post("/safes", json={"name": "خزينة دولار", "branch_id": br["id"]}), 201)
    gain_before = _bal(c, "4240")
    # سداد 10,000$ بسعر 49.20 → نقدية 492,000 / تسوية 485,000 / ربح 7,000
    ok(c.patch(f"/currencies/{usd['id']}/rate", json={"rate": "49.20"}))
    pay = ok(c.post("/payments", json={
        "customer_id": cust["id"], "safe_id": safe["id"], "amount": "492000",
        "method": "cash", "currency_id": usd["id"], "foreign_amount": "10000",
    }), 201)
    assert Decimal(str(pay["amount"])) == Decimal("485000.00")      # التسوية بالجنيه
    assert Decimal(str(pay["foreign_amount"])) == Decimal("10000")
    assert _bal(c, "4240") == gain_before + Decimal("7000.00")
    # رصيد العميل التشغيلي صفر تمامًا (سُوّي بالسعر الموزون)
    assert Decimal(str(ok(c.get("/customers"))[0]["balance"])) == Decimal("0.00")
    # النقدية الفعلية دخلت الخزينة
    assert Decimal(str(ok(c.get(f"/safes/{safe['id']}"))["balance"])) == Decimal("492000.00")
    # القيد موزون بثلاثة أسطر (نقدية/عميل/فرق)
    jes = [e for e in ok(c.get("/journal-entries?limit=50")) if e["reference"] == f"PAY-{pay['id']}"]
    assert len(jes) == 1 and "FX" in jes[0]["description"]
    # إبطال السند الأجنبي يقلب القيد كاملًا ويعيد كل شيء
    ok(c.post(f"/payments/{pay['id']}/void"), 200)
    assert _bal(c, "4240") == gain_before
    assert Decimal(str(ok(c.get("/customers"))[0]["balance"])) == Decimal("485000.00")
    assert Decimal(str(ok(c.get(f"/safes/{safe['id']}"))["balance"])) == Decimal("0.00")


# ================================================== 4) سداد بسعر أقل → خسارة صرف
def test_fx_loss_on_lower_settlement_rate(api):
    c = api
    usd = _usd(c, rate="48.50")
    sup = ok(c.post("/suppliers", json={"name": "مورد استيراد"}), 201)
    wh, _ = make_warehouses(c)
    p = ok(c.post("/products", json={"sku": "IMP", "name": "استيراد", "sale_price": "100", "cost_price": "485000", "quantity": 0}), 201)
    po = ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": wh["id"], "payment_mode": "credit", "tax_rate": "0",
        "currency_id": usd["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_cost": "485000"}],
    }), 201)
    assert Decimal(str(po["foreign_total"])) == Decimal("10000.00")
    br = ok(c.post("/company/branches", json={"name": "فرع خسارة"}), 201)
    safe = ok(c.post("/safes", json={"name": "خزينة خسارة", "branch_id": br["id"]}), 201)
    loss_before = _bal(c, "5350")
    # المورد: صعود السعر = ندفع جنيهًا أكثر = خسارة صرف
    ok(c.patch(f"/currencies/{usd['id']}/rate", json={"rate": "49.20"}))
    pay = ok(c.post("/payments", json={
        "supplier_id": sup["id"], "safe_id": safe["id"], "amount": "492000",
        "method": "cash", "currency_id": usd["id"], "foreign_amount": "10000",
    }), 201)
    assert Decimal(str(pay["amount"])) == Decimal("485000.00")  # تسوية بالسعر الموزون (= سعر الفاتورة)
    assert _bal(c, "5350") == loss_before + Decimal("7000.00")
    assert Decimal(str(ok(c.get(f"/suppliers"))[0]["balance"])) == Decimal("0.00")
    # النقدية الفعلية 492,000 خرجت من الخزينة
    assert Decimal(str(ok(c.get(f"/safes/{safe['id']}"))["balance"])) == Decimal("-492000.00")


# ================================================== 5) دفعة مقدمة بالعملة (بلا فواتير)
def test_advance_in_foreign_currency_no_fx(api):
    c = api
    usd = _usd(c)
    cust = ok(c.post("/customers", json={"name": "عميل دفعة مقدمة"}), 201)
    br = ok(c.post("/company/branches", json={"name": "فرع مقدمة"}), 201)
    safe = ok(c.post("/safes", json={"name": "خزينة مقدمة", "branch_id": br["id"]}), 201)
    pay = ok(c.post("/payments", json={
        "customer_id": cust["id"], "safe_id": safe["id"], "amount": "4850",
        "method": "cash", "currency_id": usd["id"], "foreign_amount": "100",
    }), 201)
    assert Decimal(str(pay["amount"])) == Decimal("4850.00")
    # بلا فواتير أجنبية → لا فرق صرف؛ الرصيد دائن 4,850
    assert Decimal(str(ok(c.get("/customers"))[0]["balance"])) == Decimal("-4850.00")
