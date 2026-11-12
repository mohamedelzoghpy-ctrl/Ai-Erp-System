"""اختبارات تحسينات المخزون 2026-11:
حد الطلب الأدنى لكل مخزن · اقتراحات الشراء + مسودة PO منها · لوطات تنتهي قريبًا ·
سجل حركات المخزون المركزي.
"""
import io
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


# ================================================== 1) حد الطلب الأدنى لكل مخزن
def test_per_warehouse_min_level_overrides_low_stock(api):
    c = api
    w1, w2 = make_warehouses(c)
    p = ok(c.post("/products", json={
        "sku": "MN1", "name": "منتج الحدود", "sale_price": "100", "cost_price": "50", "quantity": 0,
    }), 201)
    ok(c.post(f"/products/{p['id']}/adjust-stock", json={"change": 8, "warehouse_id": w1["id"]}))
    ok(c.post(f"/products/{p['id']}/adjust-stock", json={"change": 8, "warehouse_id": w2["id"]}))
    # الحد العام 5 → المخزنان آمنان
    low_global = ok(c.get(f"/reports/low-stock?warehouse_id={w1['id']}"))
    assert [r["id"] for r in low_global if r["id"] == p["id"]] == []
    # ضبط حد خاص 10 للمخزن الأول → يظهر منخفضًا هناك فقط
    stocks = ok(c.post(f"/products/{p['id']}/min-level", json={"warehouse_id": w1["id"], "min_level": "10"}))
    row = [s for s in stocks if s["warehouse_id"] == w1["id"]][0]
    assert row["min_level"] == 10.0
    low_w1 = ok(c.get(f"/reports/low-stock?warehouse_id={w1['id']}"))
    mine = [r for r in low_w1 if r["id"] == p["id"]]
    assert len(mine) == 1 and mine[0]["min_source"] == "warehouse" and mine[0]["shortfall"] == 2.0
    low_w2 = ok(c.get(f"/reports/low-stock?warehouse_id={w2['id']}"))
    assert [r for r in low_w2 if r["id"] == p["id"]] == []
    # إلغاء الخاص → يرجع العام
    ok(c.post(f"/products/{p['id']}/min-level", json={"warehouse_id": w1["id"], "min_level": None}))
    assert ok(c.get(f"/reports/low-stock?warehouse_id={w1['id']}")) == []


# ================================================== 2) اقتراحات الشراء + مسودة PO
def test_purchase_suggestions_and_draft_po(api):
    c = api
    w1, _ = make_warehouses(c)
    sup = ok(c.post("/suppliers", json={"name": "مورد الاقتراحات"}), 201)
    p = ok(c.post("/products", json={
        "sku": "SG1", "name": "صنف مقترح", "sale_price": "100", "cost_price": "40",
        "quantity": 0, "reorder_level": 25, "supplier_id": sup["id"],
    }), 201)
    ok(c.post(f"/products/{p['id']}/adjust-stock", json={"change": 5, "warehouse_id": w1["id"]}))
    # الاقتراح العام: 25 − 5 = 20
    sug = ok(c.get("/reports/purchase-suggestions"))
    mine = [r for r in sug if r["product_id"] == p["id"]]
    assert len(mine) == 1 and mine[0]["suggested_qty"] == 20.0 and mine[0]["estimated_cost"] == 800.0
    # اقتراح بمخزن محدد (متاح 5 نفسه هنا) + حد خاص 30 → مقترح 25
    ok(c.post(f"/products/{p['id']}/min-level", json={"warehouse_id": w1["id"], "min_level": "30"}))
    sug_w = ok(c.get(f"/reports/purchase-suggestions?warehouse_id={w1['id']}"))
    mine_w = [r for r in sug_w if r["product_id"] == p["id"]][0]
    assert mine_w["suggested_qty"] == 25.0
    # مسودة PO من الاقتراحات: بلا حركة مخزون وحالة draft
    po = ok(c.post("/purchase-orders/from-suggestions", json={
        "supplier_id": sup["id"], "warehouse_id": w1["id"],
    }), 201)
    assert po["status"] == "draft"
    assert Decimal(str(po["total_amount"])) == Decimal("1000.00")  # 25 × 40
    stocks = {r["warehouse_id"]: r["quantity"] for r in ok(c.get(f"/products/{p['id']}/stock"))}
    assert stocks.get(w1["id"], 0) == 5  # لم تُحرك الكمية بعد
    # الاستلام يحرك ويحدّث التكلفة (متوسط مرجح: 5×40 + 25×40 = 40)
    ok(c.post(f"/purchase-orders/{po['id']}/receive"), 200)
    stocks = {r["warehouse_id"]: r["quantity"] for r in ok(c.get(f"/products/{p['id']}/stock"))}
    assert stocks[w1["id"]] == 30
    # xlsx
    x = c.get("/reports/purchase-suggestions/xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


# ================================================== 3) لوطات تنتهي قريبًا
def test_lots_expiring_report(api):
    c = api
    w1, _ = make_warehouses(c)
    sup = ok(c.post("/suppliers", json={"name": "مورد لوطات"}), 201)
    p = ok(c.post("/products", json={"sku": "EX1", "name": "حليب", "sale_price": "20", "cost_price": "12", "quantity": 0}), 201)
    today = date.today()
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w1["id"], "payment_mode": "credit",
        "items": [{"product_id": p["id"], "quantity": 10, "unit_cost": "12"}],
    }), 201)
    # لوطان يدويان: واحد ينتهي قريبًا وواحد بعيد
    ok(c.post("/lots", json={
        "product_id": p["id"], "warehouse_id": w1["id"], "lot_code": "EXP-SOON",
        "qty": 5, "expiry_date": str(today + timedelta(days=7)),
    }), 201)
    ok(c.post("/lots", json={
        "product_id": p["id"], "warehouse_id": w1["id"], "lot_code": "EXP-FAR",
        "qty": 5, "expiry_date": str(today + timedelta(days=200)),
    }), 201)
    rows = ok(c.get("/reports/lots-expiring?days=30"))
    codes = {r["lot_code"] for r in rows}
    assert "EXP-SOON" in codes and "EXP-FAR" not in codes
    soon = [r for r in rows if r["lot_code"] == "EXP-SOON"][0]
    assert soon["days_left"] == 7 and soon["qty_remaining"] == 5.0 and soon["expired"] is False
    x = c.get("/reports/lots-expiring/xlsx?days=30")
    assert x.status_code == 200


# ================================================== 4) سجل حركات المخزون
def test_stock_movements_report_filters(api):
    c = api
    w1, w2 = make_warehouses(c)
    p = ok(c.post("/products", json={"sku": "MV1", "name": "متحرك", "sale_price": "10", "cost_price": "5", "quantity": 0}), 201)
    ok(c.post(f"/products/{p['id']}/adjust-stock", json={"change": 10, "warehouse_id": w1["id"], "reference": "افتتاحي"}))
    ok(c.post("/stock-transfers", json={
        "from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"],
        "items": [{"product_id": p["id"], "quantity": 4}],
    }), 201)
    transfers = ok(c.get("/stock-transfers"))
    ok(c.post(f"/stock-transfers/{transfers[0]['id']}/approve"))
    # بدون فلتر: حركتان على الأقل (adjustment + transfer_out + transfer_in)
    all_rows = ok(c.get("/reports/stock-movements"))
    reasons = {r["reason"] for r in all_rows}
    assert {"adjustment", "transfer_out", "transfer_in"} <= reasons
    # فلتر السبب
    adj_only = ok(c.get("/reports/stock-movements?reason=adjustment"))
    assert all(r["reason"] == "adjustment" for r in adj_only) and len(adj_only) == 1
    # فلتر المخزن
    w2_rows = ok(c.get(f"/reports/stock-movements?warehouse_id={w2['id']}"))
    assert all(r["warehouse_id"] == w2["id"] for r in w2_rows)
    assert {r["reason"] for r in w2_rows} == {"transfer_in"}
    # فلتر الصنف غير الموجود
    assert ok(c.get("/reports/stock-movements?product_id=99999")) == []
    # xlsx
    x = c.get("/reports/stock-movements/xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"
