"""مخازن م3: حجز المخزون (ATP) + التحليلات (دوران/راكد/ABC) + حد أدنى/أقصى ذكي."""

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
    yield client
    app.dependency_overrides.pop(get_db, None)


def ok(resp, code=200):
    assert resp.status_code == code, (resp.status_code, resp.text)
    return resp.json() if resp.content else None


def make_warehouses(c):
    w1 = ok(c.post("/warehouses", json={"name": "Main", "code": "W1"}), 201)
    w2 = ok(c.post("/warehouses", json={"name": "Shop", "code": "W2"}), 201)
    return w1, w2


def make_product(c, sku, qty, wid, **extra):
    return ok(c.post("/products", json={"sku": sku, "name": f"Item {sku}", "sale_price": "10", "cost_price": "5", "quantity": qty, "warehouse_id": wid, **extra}), 201)


def draft_so(c, customer_id, warehouse_id, product_id, qty, price="10"):
    return ok(c.post("/sales-orders", json={
        "customer_id": customer_id, "warehouse_id": warehouse_id,
        "items": [{"product_id": product_id, "quantity": qty, "unit_price": price}],
    }), 201)


def card(c, pid):
    return ok(c.get(f"/products/{pid}"))


# ================================================== 1) الحجز و«متاح للبيع»

def test_reservation_deducts_from_available_to_promise(api):
    c = api
    w1, _ = make_warehouses(c)
    p = make_product(c, "RSV-A", 10, w1["id"])
    cust = ok(c.post("/customers", json={"name": "C1"}), 201)

    assert card(c, p["id"])["available_to_promise"] == 10.0

    so = draft_so(c, cust["id"], w1["id"], p["id"], 3)
    assert so["reserved"] is False
    ok(c.post(f"/sales-orders/{so['id']}/reserve"))
    got = card(c, p["id"])
    assert got["reserved"] == 3.0 and got["available_to_promise"] == 7.0
    assert ok(c.get(f"/sales-orders/{so['id']}"))["reserved"] is True

    # أمر مسودة ثانٍ لا يستطيع حجز أكثر من المتاح
    so2 = draft_so(c, cust["id"], w1["id"], p["id"], 8)
    r = c.post(f"/sales-orders/{so2['id']}/reserve")
    assert r.status_code == 409 and "Insufficient stock to reserve" in r.text, r.text

    # التحرير يعيد المتاح
    ok(c.delete(f"/sales-orders/{so['id']}/reserve"))
    assert card(c, p["id"])["available_to_promise"] == 10.0


def test_reservation_conflicts_and_lifecycle(api):
    c = api
    w1, _ = make_warehouses(c)
    p = make_product(c, "RSV-B", 5, w1["id"])
    cust = ok(c.post("/customers", json={"name": "C2"}), 201)

    # حجز أكبر من الرصيد ممنوع
    so_big = draft_so(c, cust["id"], w1["id"], p["id"], 6)
    assert c.post(f"/sales-orders/{so_big['id']}/reserve").status_code == 409

    so = draft_so(c, cust["id"], w1["id"], p["id"], 3)
    ok(c.post(f"/sales-orders/{so['id']}/reserve"))

    # الحجز على أمر مؤكد ممنوع، والتحرير بلا حجوزات مرفوض
    ok(c.post(f"/sales-orders/{so['id']}/confirm"))
    assert c.post(f"/sales-orders/{so['id']}/reserve").status_code == 409
    assert c.delete(f"/sales-orders/{so['id']}/reserve").status_code == 409

    # التأكيد استهلك الحجز: المخزون خرج فعليًا و«بانتظار التسليم» يظهر
    got = card(c, p["id"])
    assert got["quantity"] == 2 and got["reserved"] == 0.0 and got["awaiting_delivery"] == 3.0
    assert got["available_to_promise"] == 2.0

    # الإلغاء يحرر الحجز آليًا
    so3 = draft_so(c, cust["id"], w1["id"], p["id"], 1)
    ok(c.post(f"/sales-orders/{so3['id']}/reserve"))
    assert card(c, p["id"])["reserved"] == 1.0
    ok(c.post(f"/sales-orders/{so3['id']}/cancel"))
    assert card(c, p["id"])["reserved"] == 0.0 and card(c, p["id"])["available_to_promise"] == 2.0


def test_products_list_with_availability(api):
    c = api
    w1, _ = make_warehouses(c)
    p = make_product(c, "RSV-C", 9, w1["id"])
    cust = ok(c.post("/customers", json={"name": "C3"}), 201)
    so = draft_so(c, cust["id"], w1["id"], p["id"], 4)
    ok(c.post(f"/sales-orders/{so['id']}/reserve"))
    rows = {r["id"]: r for r in ok(c.get("/products?with_availability=true&limit=500"))}
    assert rows[p["id"]]["available_to_promise"] == 5.0 and rows[p["id"]]["reserved"] == 4.0
    # بدون العلم: الحقول غائبة (بلا استعلامات زائدة)
    plain = {r["id"]: r for r in ok(c.get("/products?limit=500"))}
    assert plain[p["id"]]["available_to_promise"] is None


# ================================================== 2) تحليلات المخزون

def test_stock_analytics_turnover_dead_and_abc(api):
    c = api
    w1, _ = make_warehouses(c)
    fast = make_product(c, "ANA-A", 20, w1["id"])   # يُبع كثيرًا
    slow = make_product(c, "ANA-B", 5, w1["id"])    # يُبع قليلًا
    dead = make_product(c, "ANA-C", 8, w1["id"])    # لا يُبع إطلاقًا
    cust = ok(c.post("/customers", json={"name": "C4"}), 201)
    ok(c.post(f"/sales-orders/{draft_so(c, cust['id'], w1['id'], fast['id'], 12)['id']}/confirm"))
    ok(c.post(f"/sales-orders/{draft_so(c, cust['id'], w1['id'], slow['id'], 1)['id']}/confirm"))

    rep = ok(c.get("/reports/stock-analytics?days=30&dead_days=90"))
    rows = {r["product_id"]: r for r in rep["rows"]}
    assert rows[fast["id"]]["sold_qty"] == 12 and rows[fast["id"]]["turnover"] == 1.5  # 12 بيع ÷ رصيد 8
    assert rows[slow["id"]]["sold_qty"] == 1
    assert rows[dead["id"]]["sold_qty"] == 0 and rows[dead["id"]]["is_dead"] is True
    assert rows[fast["id"]]["is_dead"] is False
    # ABC: أغلى رصيد يتصدر الفئة A
    assert rows[fast["id"]]["abc_class"] == "A" and rows[dead["id"]]["abc_class"] in ("A", "B", "C")
    assert rep["summary"]["dead_count"] == 1 and rep["summary"]["dead_value"] == 40.0
    x = c.get("/reports/stock-analytics/xlsx?days=30")
    assert x.status_code == 200 and x.content[:2] == b"PK"

    # فلتر المخزن يعمل
    rep_w = ok(c.get(f"/reports/stock-analytics?warehouse_id={w1['id']}"))
    assert any(r["product_id"] == fast["id"] for r in rep_w["rows"])


# ================================================== 3) حد أدنى/أقصى ذكي للاقتراحات

def test_min_max_levels_drive_purchase_suggestions(api):
    c = api
    w1, _ = make_warehouses(c)
    p = make_product(c, "MM-A", 5, w1["id"], reorder_level=0)
    # بلا حدود: لا اقتراح
    assert ok(c.get(f"/reports/purchase-suggestions?warehouse_id={w1['id']}")) == []
    # حد أدنى 10 → اقترح 5 (سياسة min)
    ok(c.post(f"/products/{p['id']}/min-level", json={"warehouse_id": w1["id"], "min_level": 10}))
    rows = ok(c.get(f"/reports/purchase-suggestions?warehouse_id={w1['id']}"))
    assert rows[0]["suggested_qty"] == 5.0 and rows[0]["policy"] == "min"
    # حد أقصى 20 يطغى → اقترح 15 (سياسة max)
    ok(c.post(f"/products/{p['id']}/min-level", json={"warehouse_id": w1["id"], "max_level": 20}))
    rows = ok(c.get(f"/reports/purchase-suggestions?warehouse_id={w1['id']}"))
    assert rows[0]["suggested_qty"] == 15.0 and rows[0]["policy"] == "max"
    # الحجز يُخصم من المتاح فيزيد الاقتراح
    cust = ok(c.post("/customers", json={"name": "C5"}), 201)
    so = draft_so(c, cust["id"], w1["id"], p["id"], 5)
    ok(c.post(f"/sales-orders/{so['id']}/reserve"))
    rows = ok(c.get(f"/reports/purchase-suggestions?warehouse_id={w1['id']}"))
    assert rows[0]["suggested_qty"] == 20.0  # الرصيد كله محجوز
    # min > max مرفوض
    r = c.post(f"/products/{p['id']}/min-level", json={"warehouse_id": w1["id"], "min_level": 25, "max_level": 20})
    assert r.status_code == 422, r.text
    # قراءة الحدود من بطاقة الصنف
    stock = {s["warehouse_id"]: s for s in ok(c.get(f"/products/{p['id']}/stock"))}
    assert stock[w1["id"]]["min_level"] == 10.0 and stock[w1["id"]]["max_level"] == 20.0
