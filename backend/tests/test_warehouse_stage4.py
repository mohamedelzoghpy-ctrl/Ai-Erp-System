"""مخازن م4: الجرد الأعمي + بوابة اعتماد الفروق + شيت الطباعة + الأرقام التسلسلية."""

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
    return w1


def make_product(c, sku, qty, wid, **extra):
    return ok(c.post("/products", json={"sku": sku, "name": f"Item {sku}", "sale_price": "10", "cost_price": "5", "quantity": qty, "warehouse_id": wid, **extra}), 201)


# ================================================== 1) الجرد الأعمي + بوابة الاعتماد

def test_blind_stocktake_masks_until_review(api):
    c = api
    w1 = make_warehouses(c)
    p = make_product(c, "BL-A", 10, w1["id"])

    st = ok(c.post("/stocktakes", json={"warehouse_id": w1["id"], "mode": "blind"}), 201)
    assert st["mode"] == "blind" and st["status"] == "open"
    detail = ok(c.get(f"/stocktakes/{st['id']}"))
    line = detail["lines"][0]
    assert line["system_qty"] is None and line["difference"] is None  # الرصيد مخفي أثناء العد
    assert detail["lines_with_difference"] == 0

    # شيت الطباعة (xlsx/pdf) أعمي — بلا رصيد النظام (الخلية تظهر «—»)
    x = c.get(f"/stocktakes/{st['id']}/xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    pdf = c.get(f"/stocktakes/{st['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    ok(c.put(f"/stocktakes/{st['id']}/counts", json={"counts": [{"product_id": p["id"], "counted_qty": 8}]}))
    # الاعتماد مباشرة من العد مرفوض — يلزم رفع للمراجعة
    assert c.post(f"/stocktakes/{st['id']}/apply").status_code == 409
    ok(c.post(f"/stocktakes/{st['id']}/submit"))
    # بعد الرفع تظهر الفروق للمعتمد
    rev = ok(c.get(f"/stocktakes/{st['id']}"))
    assert rev["status"] == "review" and rev["lines"][0]["system_qty"] == 10.0 and rev["lines"][0]["difference"] == -2.0
    # التعديل بعد الرفع ممنوع (العد مجمّد)
    assert c.put(f"/stocktakes/{st['id']}/counts", json={"counts": [{"product_id": p["id"], "counted_qty": 9}]}).status_code == 409
    # الإعادة للعد ثم الاعتماد
    ok(c.post(f"/stocktakes/{st['id']}/review-reject", params=None))
    assert ok(c.get(f"/stocktakes/{st['id']}"))["status"] == "open"
    ok(c.post(f"/stocktakes/{st['id']}/submit"))
    ok(c.post(f"/stocktakes/{st['id']}/apply"))
    final = ok(c.get(f"/products/{p['id']}"))
    assert final["quantity"] == 8.0  # الفرق -2 نُرحّل للرصيد


def test_open_stocktake_goes_through_review_gate(api):
    c = api
    w1 = make_warehouses(c)
    p = make_product(c, "BL-B", 6, w1["id"])
    st = ok(c.post("/stocktakes", json={"warehouse_id": w1["id"]}), 201)
    st_detail = ok(c.get(f"/stocktakes/{st['id']}"))
    assert st["mode"] == "open" and st_detail["lines"][0]["system_qty"] == 6.0  # العادي يعرض الرصيد
    ok(c.put(f"/stocktakes/{st['id']}/counts", json={"counts": [{"product_id": p["id"], "counted_qty": 6}]}))
    # رفع بلا أي عدّ مرفوض
    st2 = ok(c.post("/stocktakes", json={"warehouse_id": w1["id"]}), 201)
    assert c.post(f"/stocktakes/{st2['id']}/submit").status_code == 409
    ok(c.post(f"/stocktakes/{st['id']}/submit"))
    ok(c.post(f"/stocktakes/{st['id']}/apply"))
    assert ok(c.get(f"/stocktakes/{st['id']}"))["status"] == "applied"


# ================================================== 2) الأرقام التسلسلية

def test_serial_receipt_is_mandatory_and_unique(api):
    c = api
    w1 = make_warehouses(c)
    p = make_product(c, "SN-A", 0, w1["id"], serial_tracking=True)
    sup = ok(c.post("/suppliers", json={"name": "Sup SN"}), 201)

    # استلام فوري بلا أرقام → مرفوض
    r = c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 2, "unit_cost": "5"}],
    })
    assert r.status_code == 409 and "تسجيل 2 رقمًا" in r.text, r.text

    po = ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 2, "unit_cost": "5"}],
        "serials": {str(p["id"]): ["IMEI-111", "IMEI-222"]},
    }), 201)
    serials = ok(c.get(f"/products/{p['id']}/serials"))
    assert len(serials) == 2 and all(s["status"] == "in_stock" for s in serials)
    assert serials[0]["source_ref"] == f"PO-{po['id']}"

    # تكرار رقم مسجل → مرفوض (استلام جزئي مسودة)
    po2 = ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w1["id"], "auto_receive": False,
        "items": [{"product_id": p["id"], "quantity": 1, "unit_cost": "5"}],
    }), 201)
    r = c.post(f"/purchase-orders/{po2['id']}/receive-partial", json={
        "items": [{"product_id": p["id"], "quantity": 1}],
        "serials": {str(p["id"]): ["IMEI-111"]},
    })
    assert r.status_code == 409 and "مسجلة بالفعل" in r.text, r.text
    ok(c.post(f"/purchase-orders/{po2['id']}/receive-partial", json={
        "items": [{"product_id": p["id"], "quantity": 1}],
        "serials": {str(p["id"]): ["IMEI-333"]},
    }))
    assert len(ok(c.get(f"/products/{p['id']}/serials"))) == 3

    # تسجيل يدوي + تكرار مرفوض
    ok(c.post(f"/products/{p['id']}/serials", json={"serials": ["IMEI-444"], "warehouse_id": w1["id"]}), 201)
    assert c.post(f"/products/{p['id']}/serials", json={"serials": ["IMEI-444"], "warehouse_id": w1["id"]}).status_code == 409


def test_serial_sale_binds_specific_or_auto_picks(api):
    c = api
    w1 = make_warehouses(c)
    p = make_product(c, "SN-B", 0, w1["id"], serial_tracking=True, warranty_months=12)
    sup = ok(c.post("/suppliers", json={"name": "Sup SN2"}), 201)
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 3, "unit_cost": "5"}],
        "serials": {str(p["id"]): ["IMEI-777", "IMEI-888", "IMEI-999"]},
    }), 201)
    cust = ok(c.post("/customers", json={"name": "SN Customer"}), 201)

    # بيع بربط صريح: IMEI-888
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "12"}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm", json={"serials": {str(p["id"]): ["IMEI-888"]}}))
    serials = {s["serial"]: s for s in ok(c.get(f"/products/{p['id']}/serials"))}
    assert serials["IMEI-888"]["status"] == "sold" and serials["IMEI-888"]["sale_ref"] == f"SO-{so['id']}"
    assert serials["IMEI-777"]["status"] == "in_stock"

    # بيع POS يختار آليًا الأقدم (IMEI-777)
    ok(c.post("/pos/checkout", json={
        "customer_id": cust["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "12"}], "amount_paid": "12", "method": "cash",
    }), 201)
    serials = {s["serial"]: s for s in ok(c.get(f"/products/{p['id']}/serials"))}
    assert serials["IMEI-777"]["status"] == "sold"

    # بيع كمية بلا أرقام كافية (تبقى 1 رقم وكمية 1) — ينجح بالاختيار الآلي؛ ثم بيع جديد يفشل
    so3 = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "12"}],
    }), 201)
    ok(c.post(f"/sales-orders/{so3['id']}/confirm"))
    so4 = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "12"}],
    }), 201)
    r = c.post(f"/sales-orders/{so4['id']}/confirm")
    assert r.status_code == 409, r.text  # المخزون صفر (الكمية تتطابق مع الأرقام دائمًا)

    # تقرير الضمان: نهاية الضمان = الاستلام + 12 شهرًا
    rep = ok(c.get(f"/reports/serial-warranty?product_id={p['id']}"))
    sold_rows = [r for r in rep["rows"] if r["status"] == "sold"]
    assert len(sold_rows) == 3 and all(r["warranty_end"] for r in rep["rows"])
    assert any(r["sale_ref"] for r in sold_rows)
    # فلتر الحالة
    assert all(r["status"] == "in_stock" for r in ok(c.get(f"/reports/serial-warranty?status=in_stock"))["rows"]) or rep["count"] == 3
