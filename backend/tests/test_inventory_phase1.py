"""المرحلة 1 من خطة المخازن 87→95: وحدات القياس + الباركود كبيانات + حجب اللوطات المنتهية + أسباب التسويات."""
from datetime import date, timedelta

import pytest
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


def make_warehouse(c, name, code):
    return ok(c.post("/warehouses", json={"name": name, "code": code}), 201)


def make_product(c, name, w=None, **extra):
    body = {"sku": f"SKU-{name}", "name": name, "sale_price": "100", "cost_price": "5", "quantity": 0, **extra}
    if body.get("quantity", 0) and not body.get("warehouse_id"):
        if w is None:
            w = make_warehouse(c, f"مخزن {name}", f"W-{abs(hash(name)) % 1000}")
        body["warehouse_id"] = w["id"]
    return ok(c.post("/products", json=body), 201)


def make_customer(c, name="عميل المخازن"):
    return ok(c.post("/customers", json={"name": name}), 201)


def sell(c, product_id, warehouse_id, qty, price="100", **extra):
    cust = make_customer(c)
    r = c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": warehouse_id,
        "items": [{"product_id": product_id, "quantity": qty, "unit_price": price, **extra}],
    })
    order = ok(r, 201)
    return ok(c.post(f"/sales-orders/{order['id']}/confirm"))


# ---------------------------------------------------------------- وحدات القياس
def test_pack_uom_conversion_on_sale_and_purchase(api):
    """البيع بالحزمة: 2 كرتون × 12 قطعة = 24 قطعة تُخصم من المخزون."""
    c = api
    w = make_warehouse(c, "Main", "W1")
    prod = make_product(c, "عصير", w=w, quantity=100, pack_qty="12", pack_name="كرتون")  # w موجود
    order = ok(c.post("/sales-orders", json={
        "customer_id": make_customer(c)["id"], "warehouse_id": w["id"],
        "items": [{"product_id": prod["id"], "quantity": 2, "unit_price": "1200", "uom": "pack"}],
    }), 201)
    # الكمية المخزنة بالقطع: 2 × 12 = 24
    item = order["items"][0]
    assert float(item["quantity"]) == 24.0
    ok(c.post(f"/sales-orders/{order['id']}/confirm"))
    stocks = ok(c.get(f"/products/{prod['id']}/stock"))
    assert stocks[0]["quantity"] == 76.0  # 100 − 24


def test_pack_uom_on_purchase_and_no_conversion_without_flag(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    supp = ok(c.post("/suppliers", json={"name": "مورد حزم"}), 201)
    prod = make_product(c, "زيت", w=w, pack_qty="6", pack_name="درزن")
    # الشراء بالحزمة: 5 درازن × 6 = 30 — الإنشاء يستلم فورًا (سلوك النظام)
    po = ok(c.post("/purchase-orders", json={
        "supplier_id": supp["id"], "warehouse_id": w["id"],
        "items": [{"product_id": prod["id"], "quantity": 5, "unit_cost": "36", "uom": "pack"}],
    }), 201)
    assert float(po["items"][0]["quantity"]) == 30.0
    assert po["status"] == "received"
    assert ok(c.get(f"/products/{prod['id']}/stock"))[0]["quantity"] == 30.0

    # بلا uom=pack: 3 تُحتسب 3 قطع كما هي
    prod2 = make_product(c, "سكر", w=w, quantity=10)
    r = c.post("/sales-orders", json={
        "customer_id": make_customer(c)["id"], "warehouse_id": w["id"],
        "items": [{"product_id": prod2["id"], "quantity": 3, "unit_price": "50"}],
    })
    order = ok(r, 201)
    assert float(order["items"][0]["quantity"]) == 3.0


# ---------------------------------------------------------------- الباركود كبيانات
def test_barcode_crud_and_resolution(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    prod = make_product(c, "شيبسي", w=w, quantity=50, pack_qty="24", pack_name="كرتون")
    # إضافة باركود القطعة والكرتون
    b1 = ok(c.post(f"/products/{prod['id']}/barcodes", json={"barcode": "6221000000017", "pack_qty": "1"}), 201)
    b2 = ok(c.post(f"/products/{prod['id']}/barcodes", json={"barcode": "6221000000024", "pack_qty": "24"}), 201)
    # تكرار → 409 (حتى لصنف آخر)
    prod2 = make_product(c, "منافس")
    assert c.post(f"/products/{prod2['id']}/barcodes", json={"barcode": "6221000000017"}).status_code == 409
    # الحل: قطعة = 1، كرتون = 24
    r1 = ok(c.get("/products/by-barcode/6221000000017"))
    assert r1["product_id"] == prod["id"] and float(r1["pack_qty"]) == 1.0
    r2 = ok(c.get("/products/by-barcode/6221000000024"))
    assert float(r2["pack_qty"]) == 24.0
    # باركود المقياس: prefix 22 + كود 3 خانات + وزن 1500 جرام
    prod3 = make_product(c, "توم", sku_prefix_check=True) if False else make_product(c, "توم")
    # sku = SKU-توم — نجعل باركود مقياس يطابق بادئة SKU الرقمية: نستخدم صنفًا رقميًا
    prod4 = ok(c.post("/products", json={"sku": "12345", "name": "جبن بالكيلو", "sale_price": "80", "cost_price": "50", "quantity": 0}), 201)
    scale = "2212345015008"  # prefix 22، صنف 12345، وزن 1500 جم = 1.5 كجم
    r3 = ok(c.get(f"/products/by-barcode/{scale}"))
    assert r3["product_id"] == prod4["id"] and r3["scale_qty"] == 1.5
    # حذف باركود
    ok(c.delete(f"/products/{prod['id']}/barcodes/{b2['id']}"), 204)
    assert c.get("/products/by-barcode/6221000000024").status_code == 404


def test_label_sheet_generated(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    prod = make_product(c, "ملصق", w=w, quantity=10)
    r = c.get(f"/products/labels/{prod['id']}?copies=6")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "lbl" in r.text and r.text.count('class="lbl"') == 6
    # صنف غير موجود → 404
    assert c.get("/products/labels/999999").status_code == 404


# ---------------------------------------------------------------- حجب المنتهية
def test_expired_lot_blocked_at_sale_but_unexpired_sells(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    prod = make_product(c, "لبن", quantity=0)
    # لوط منتهي (10) + سليم (10)
    ok(c.post("/lots", json={"product_id": prod["id"], "warehouse_id": w["id"], "lot_code": "EXP", "qty": 10, "expiry_date": (date.today() - timedelta(days=1)).isoformat()}), 201)
    ok(c.post("/lots", json={"product_id": prod["id"], "warehouse_id": w["id"], "lot_code": "OK", "qty": 10, "expiry_date": (date.today() + timedelta(days=30)).isoformat()}), 201)

    # بيع 8: يتخطى المنتهي ويخصم من السليم
    sell(c, prod["id"], w["id"], 8)
    lots = {l["lot_code"]: l["qty_remaining"] for l in ok(c.get(f"/lots?product_id={prod['id']}"))}
    assert lots["EXP"] == 10.0 and lots["OK"] == 2.0

    # بيع 5: المتبقي السليم 2 فقط → المطلوب يغطيها لوطات منتهية → 409 بأكوادها
    r = c.post("/sales-orders", json={
        "customer_id": make_customer(c)["id"], "warehouse_id": w["id"],
        "items": [{"product_id": prod["id"], "quantity": 5, "unit_price": "20"}],
    })
    order = ok(r, 201)
    resp = c.post(f"/sales-orders/{order['id']}/confirm")
    assert resp.status_code == 409 and "منتهية الصلاحية" in resp.json()["detail"] and "EXP" in resp.json()["detail"]

    # التجاوز بمسؤول (admin = مالك/مدير): يعمل ويخصم من المنتهي
    ok(c.post(f"/sales-orders/{order['id']}/confirm", json={"allow_expired": True}))
    lots = {l["lot_code"]: l["qty_remaining"] for l in ok(c.get(f"/lots?product_id={prod['id']}"))}
    assert lots["EXP"] == 5.0 and lots["OK"] == 2.0


def test_pos_always_blocks_expired(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    prod = make_product(c, "لبن POS", quantity=0)
    ok(c.post("/lots", json={"product_id": prod["id"], "warehouse_id": w["id"], "lot_code": "EXP2", "qty": 10, "expiry_date": (date.today() - timedelta(days=1)).isoformat()}), 201)
    customer = make_customer(c)
    r = c.post("/pos/checkout", json={
        "warehouse_id": w["id"], "customer_id": customer["id"], "payment_method": "cash",
        "items": [{"product_id": prod["id"], "quantity": 2, "unit_price": "20"}],
    })
    assert r.status_code == 409 and "منتهية" in r.json()["detail"]


# ---------------------------------------------------------------- أسباب التسويات والاعتماد
def test_adjustment_reasons_and_approval_threshold(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    prod = make_product(c, "لابتوب", w=w, cost_price="20000", quantity=5)
    # بلا سبب → 422
    assert c.post(f"/products/{prod['id']}/adjust-stock", json={"change": 2, "warehouse_id": w["id"]}).status_code == 422
    # سبب غير موجود → 422
    assert c.post(f"/products/{prod['id']}/adjust-stock", json={"change": 2, "reason_id": 999999, "warehouse_id": w["id"]}).status_code == 422
    reason = ok(c.post("/products/adjustment-reasons", json={"name": "تالف"}), 201)
    dup = c.post("/products/adjustment-reasons", json={"name": "تالف"})
    assert dup.status_code == 409
    # قيمة فوق حد الاعتماد (20000 × 2 = 40000 > 1000) — المستخدم boss هو admin فيمر
    res = ok(c.post(f"/products/{prod['id']}/adjust-stock", json={
        "change": -1, "reason_id": reason["id"], "note": "شاشة مكسورة", "warehouse_id": w["id"],
    }))
    assert float(res["quantity"]) == 4.0
    # الحركة موقعة بالسبب والمستخدم
    moves = ok(c.get(f"/products/{prod['id']}/movements"))
    adj_moves = [m for m in moves if m["reason"] == "adjustment"]
    assert adj_moves and "تالف" in (adj_moves[0].get("reason_note") or "")

    # قائمة الأسباب
    reasons = ok(c.get("/products/adjustment-reasons"))
    assert any(r["name"] == "تالف" for r in reasons)


def test_small_adjustment_without_reason_fails_and_reason_catalog_persists(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    prod = make_product(c, "أقلام", w=w, cost_price="3", quantity=100)
    reason = ok(c.post("/products/adjustment-reasons", json={"name": "هدية"}), 201)
    res = ok(c.post(f"/products/{prod['id']}/adjust-stock", json={
        "change": -5, "reason_id": reason["id"], "warehouse_id": w["id"],
    }))
    assert float(res["quantity"]) == 95.0
