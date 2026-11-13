"""المرحلة 4 من خطة التصنيع: منتجات ثانوية + خامة بديلة + مشغّل العمليات والدفعات."""
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


def make_product(c, name, **extra):
    body = {"sku": f"SKU-{name}", "name": name, "sale_price": "100", "cost_price": "5", "quantity": 0, **extra}
    return ok(c.post("/products", json=body), 201)


def stock_of(c, product_id, warehouse_id):
    for row in ok(c.get(f"/products/{product_id}/stock")):
        if row["warehouse_id"] == warehouse_id:
            return row["quantity"]
    return 0


def issued_order(c, raw_id, raw_qty, fin_qty_planned=10, bom_item_extra=None):
    """أمر مصروف: BOM من خامة واحدة. bom_item_extra يمرَّر لبند القائمة (مثل substitute_product_id)."""
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=raw_qty, cost_price="10", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    item = {"component_id": raw["id"], "qty_per_output": 1}
    item.update(bom_item_extra or {})
    ok(c.post("/boms", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [item],
    }), 201)
    po = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": fin_qty_planned,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
    }), 201)
    po = ok(c.post(f"/production-orders/{po['id']}/issue"))
    return po, raw, fin, w


# ---------------------------------------------------------------- منتجات ثانوية
def test_byproduct_reduces_main_cost_and_enters_stock(api):
    c = api
    po, raw, fin, w = issued_order(c, raw_id=0, raw_qty=20)  # خامات 10 × 10 = 100 WIP
    bp = make_product(c, "BP1", cost_price="2")  # قيمة الوحدة 2
    po2 = ok(c.post(f"/production-orders/{po['id']}/produce", json={
        "qty": 10,
        "byproducts": [{"product_id": bp["id"], "qty": 5}],  # قيمة 10 تخفّض تكلفة الرئيسي
    }))
    assert po2["status"] == "completed"
    # تكلفة الدفعة الفعلية = 100 − 10 = 90 → متوسط الرئيسي 9.0
    assert float(po2["batches"][0]["cost"]) == 90.0
    fin_after = ok(c.get(f"/products/{fin['id']}"))
    assert float(fin_after["cost_price"]) == 9.0
    # الثانوي دخل مخزن الناتج 5 وحدة وتكلفته 2
    assert stock_of(c, bp["id"], w["id"]) == 5.0
    bp_after = ok(c.get(f"/products/{bp['id']}"))
    assert float(bp_after["cost_price"]) == 2.0
    # سجل الثانوي على الأمر
    detail = ok(c.get(f"/production-orders/{po['id']}"))
    assert len(detail["byproducts"]) == 1
    assert detail["byproducts"][0]["product_id"] == bp["id"] and float(detail["byproducts"][0]["qty"]) == 5.0
    # WIP مصفّر (الرئيسي 90 + الثانوي 10 = 100 المصروفة)
    data = ok(c.get("/chart-of-accounts/reconcile"))
    wip_line = next((l for l in data["lines"] if l["code"] == "1130"), None)
    assert wip_line is None or float(wip_line["stored"]) == 0.0


def test_byproduct_without_cost_still_recorded_no_value(api):
    """ثانوي بلا تكلفة مسجلة: يدخل المخزون ويسجل لكن بلا قيمة تُخصم من الرئيسي."""
    c = api
    po, raw, fin, w = issued_order(c, raw_id=0, raw_qty=10)
    bp = make_product(c, "BP0", cost_price="0")
    po2 = ok(c.post(f"/production-orders/{po['id']}/produce", json={
        "qty": 10, "byproducts": [{"product_id": bp["id"], "qty": 3}],
    }))
    assert float(po2["batches"][0]["cost"]) == 100.0  # بلا خصم
    assert stock_of(c, bp["id"], w["id"]) == 3.0
    detail = ok(c.get(f"/production-orders/{po['id']}"))
    assert len(detail["byproducts"]) == 1 and float(detail["byproducts"][0]["unit_value"]) == 0.0


def test_byproduct_unknown_product_rejected(api):
    c = api
    po, raw, fin, w = issued_order(c, raw_id=0, raw_qty=10)
    r = c.post(f"/production-orders/{po['id']}/produce", json={
        "qty": 5, "byproducts": [{"product_id": 999999, "qty": 1}],
    })
    assert r.status_code == 422


# ---------------------------------------------------------------- خامة بديلة
def test_substitute_used_on_shortage(api):
    """الأساسية غير كافية + بديل معرّف ومتوفر → يُصرف البديل ويوثّق."""
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=3, cost_price="10", warehouse_id=w["id"])   # لا تكفي (المطلوب 5)
    sub = make_product(c, "SUB1", quantity=10, cost_price="7", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    ok(c.post("/boms", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": 1, "substitute_product_id": sub["id"]}],
    }), 201)
    po = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 5,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
    }), 201)
    po = ok(c.post(f"/production-orders/{po['id']}/issue"))
    # البديل حُسم 5 والأساسية كما هي 3
    assert stock_of(c, sub["id"], w["id"]) == 5.0
    assert stock_of(c, raw["id"], w["id"]) == 3.0
    # تكلفة الصرف بتكلفة البديل الفعلية 7 × 5 = 35
    assert float(po["std_unit_cost"]) == 7.0 or float(po["consumptions"][0]["unit_cost"]) == 7.0
    # التوثيق في حركات المخزون بسكن البديل
    mv_ok = any(m.get("reason") == "production_issue_substitute" for m in ok(c.get(f"/products/{sub['id']}/movements?limit=50")))
    assert mv_ok


def test_primary_preferred_when_enough(api):
    """الأساسية تكفي → البديل يبقى كما هو."""
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=10, cost_price="10", warehouse_id=w["id"])
    sub = make_product(c, "SUB1", quantity=10, cost_price="7", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    ok(c.post("/boms", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": 1, "substitute_product_id": sub["id"]}],
    }), 201)
    po = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 5,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
    }), 201)
    ok(c.post(f"/production-orders/{po['id']}/issue"))
    assert stock_of(c, raw["id"], w["id"]) == 5.0
    assert stock_of(c, sub["id"], w["id"]) == 10.0  # لم يُمس


def test_shortage_without_substitute_still_409(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=3, cost_price="10", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    ok(c.post("/boms", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": 1}],
    }), 201)
    po = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 5,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
    }), 201)
    assert c.post(f"/production-orders/{po['id']}/issue").status_code == 409


# ---------------------------------------------------------------- المشغّل
def test_operator_recorded_on_batch_and_operation(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=20, cost_price="10", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    ok(c.post("/boms", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": 1}],
        "operations": [{"seq": 1, "name": "خلط", "work_center_id": None, "run_minutes_per_unit": 2}],
    }), 201)
    po = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 6,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
    }), 201)
    ok(c.post(f"/production-orders/{po['id']}/issue"))
    ok(c.post(f"/production-orders/{po['id']}/operations/1/progress", json={
        "qty_done": 6, "operator_name": "محمد الأمين",
    }))
    detail = ok(c.get(f"/production-orders/{po['id']}"))
    op = detail["operations"][0]
    assert op["operator_name"] == "محمد الأمين"
    assert op["started_at"] is not None
    po2 = ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 6, "operator_name": "سيد الخط"}))
    assert po2["batches"][0]["operator_name"] == "سيد الخط"
