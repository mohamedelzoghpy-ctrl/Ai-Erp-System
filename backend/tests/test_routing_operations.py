"""مراحل التشغيل (Routing & Operations) + الكميات العشرية: مسار BOM بمراحل، صرف مرحلي، تقدم مراحل، مراكز تشغيل — عبر الـ API (SQLite في الذاكرة)."""

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


# ---------------------------------------------------------------- helpers
def setup_world(c):
    ok(c.post("/company/branches", json={"name": "Main", "location": None}), 201)
    ok(c.post("/chart-of-accounts/seed", json={}), 201)
    branch = ok(c.get("/company/branches"))[0]
    return ok(c.post("/warehouses", json={"name": "W1", "code": "W1"}), 201), branch


def make_product(c, name, qty=0, price="10"):
    return ok(c.post("/products", json={
        "sku": f"SKU-{name}", "name": name, "sale_price": "100", "cost_price": price,
        "quantity": qty,
    }), 201)


def make_bom(c, product_id, items, operations=None, output_qty=1):
    body = {"product_id": product_id, "output_qty": output_qty, "items": items}
    if operations:
        body["operations"] = operations
    return ok(c.post("/boms", json=body), 201)


def make_order(c, product_id, qty, wh_id):
    return ok(c.post("/production-orders", json={
        "product_id": product_id, "qty_planned": qty,
        "raw_warehouse_id": wh_id, "output_warehouse_id": wh_id,
    }), 201)


def stock_of(c, product_id, wh_id):
    rows = ok(c.get(f"/products/{product_id}/stock"))
    return next((float(r["quantity"]) for r in rows if r["warehouse_id"] == wh_id), 0.0)


# ---------------------------------------------------------------- work centers
def test_work_center_crud(api):
    wc = ok(api.post("/work-centers", json={"name": "قسم القص", "capacity_per_hour": 50.5, "hourly_cost": "120"}), 201)
    assert wc["name"] == "قسم القص"
    assert api.post("/work-centers", json={"name": "قسم القص"}).status_code == 409  # اسم مكرر
    updated = ok(api.patch(f"/work-centers/{wc['id']}", json={"name": "القص", "capacity_per_hour": 60.0}))
    assert updated["name"] == "القص"
    assert api.delete(f"/work-centers/{wc['id']}").status_code == 204
    assert api.delete(f"/work-centers/{wc['id']}").status_code == 404


# ---------------------------------------------------------------- BOM with routing
def test_bom_with_operations_and_staged_components(api):
    wh, _branch = setup_world(api)
    raw = make_product(api, "R1", qty=100)
    fin = make_product(api, "F1")
    bom = make_bom(api, fin["id"], [
        {"component_id": raw["id"], "qty_per_output": "2"},
    ], operations=[
        {"seq": 1, "name": "تقطيع", "work_center_id": None, "run_minutes_per_unit": 2.5},
        {"seq": 2, "name": "تجميع"},
    ])
    assert len(bom["operations"]) == 2
    assert bom["operations"][0]["run_minutes_per_unit"] == 2.5
    # مرجع مركز تشغيل غير موجود يرفض
    r = api.post("/boms", json={"product_id": fin["id"], "items": [], "operations": [{"seq": 1, "name": "x", "work_center_id": 999999}]})
    assert r.status_code == 422
    # مكوّن بمرحلة غير موجودة يرفض
    r = api.post("/boms", json={"product_id": fin["id"], "items": [{"component_id": raw["id"], "qty_per_output": "1", "operation_seq": 7}]})
    assert r.status_code == 422


# ---------------------------------------------------------------- decimal quantities
def test_fractional_issue_and_produce(api):
    wh, _branch = setup_world(api)
    raw = make_product(api, "R1", qty=10, price="10")
    fin = make_product(api, "F1")
    make_bom(api, fin["id"], [{"component_id": raw["id"], "qty_per_output": "1.5"}])
    po = make_order(api, fin["id"], 3, wh["id"])
    ok(api.post(f"/production-orders/{po['id']}/issue"))
    # 1.5 × 3 = 4.5 كجم — كسري
    assert stock_of(api, raw["id"], wh["id"]) == 5.5
    po = ok(api.post(f"/production-orders/{po['id']}/produce", json={"qty": 1.5}))
    assert float(po["qty_produced"]) == 1.5
    assert stock_of(api, fin["id"], wh["id"]) == 1.5
    # إنتاج أكبر من المتبقي يرفض
    assert api.post(f"/production-orders/{po['id']}/produce", json={"qty": 2}).status_code == 422
    po = ok(api.post(f"/production-orders/{po['id']}/produce", json={"qty": 1.5}))
    assert po["status"] == "completed"


# ---------------------------------------------------------------- staged issue
def test_staged_issue_and_operation_progress(api):
    wh, _branch = setup_world(api)
    cut = make_product(api, "قماش", qty=100, price="10")
    glue = make_product(api, "صمغ", qty=100, price="5")
    fin = make_product(api, "F1")
    make_bom(api, fin["id"], [
        {"component_id": cut["id"], "qty_per_output": "2", "operation_seq": 1},
        {"component_id": glue["id"], "qty_per_output": "0.5", "operation_seq": 2},
    ], operations=[
        {"seq": 1, "name": "قص"},
        {"seq": 2, "name": "لصق"},
    ])
    po = make_order(api, fin["id"], 10, wh["id"])
    po = ok(api.post(f"/production-orders/{po['id']}/issue"))
    # الصرف المجمّع لم يصرف شيئًا (كل المكوّنات مربوطة بمراحل)
    assert stock_of(api, cut["id"], wh["id"]) == 100
    assert len(po["operations"]) == 2
    assert po["operations"][0]["issued"] is False

    # صرف مرحلة 1 (قماش): 2 × 10 = 20
    po = ok(api.post(f"/production-orders/{po['id']}/operations/1/issue"))
    assert stock_of(api, cut["id"], wh["id"]) == 80
    assert stock_of(api, glue["id"], wh["id"]) == 100  # المرحلة 2 لسه
    # صرف مكرر يرفض
    assert api.post(f"/production-orders/{po['id']}/operations/1/issue").status_code == 409

    # صرف مرحلة 2 (صمغ): 0.5 × 10 = 5
    ok(api.post(f"/production-orders/{po['id']}/operations/2/issue"))
    assert stock_of(api, glue["id"], wh["id"]) == 95

    # تقدم مرحلة 1: مكتمل 6 + هالك 1 ثم المتبقي 3 → بعد التكرار يتجاوز → ثم تكتمل
    po = ok(api.post(f"/production-orders/{po['id']}/operations/1/progress", json={"qty_done": 6, "qty_scrapped": 1}))
    op1 = next(o for o in po["operations"] if o["seq"] == 1)
    assert op1["status"] == "in_progress"
    # تجاوز المخطط يرفض
    assert api.post(f"/production-orders/{po['id']}/operations/1/progress", json={"qty_done": 10}).status_code == 422
    po = ok(api.post(f"/production-orders/{po['id']}/operations/1/progress", json={"qty_done": 3}))
    op1 = next(o for o in po["operations"] if o["seq"] == 1)
    assert op1["status"] == "done"
    # مرحلة مكتملة ترفض المزيد
    assert api.post(f"/production-orders/{po['id']}/operations/1/progress", json={"qty_done": 1}).status_code == 409

    # إنتاج نهائي عادي بعد اكتمال المراحل
    po = ok(api.post(f"/production-orders/{po['id']}/produce", json={"qty": 10}))
    assert po["status"] == "completed"


# ---------------------------------------------------------------- batch idempotency
def test_batch_no_unique_backstop(api):
    wh, _branch = setup_world(api)
    raw = make_product(api, "R1", qty=50)
    fin = make_product(api, "F1")
    make_bom(api, fin["id"], [{"component_id": raw["id"], "qty_per_output": "1"}])
    po = make_order(api, fin["id"], 5, wh["id"])
    ok(api.post(f"/production-orders/{po['id']}/issue"))
    ok(api.post(f"/production-orders/{po['id']}/produce", json={"qty": 2}))
    po = ok(api.get(f"/production-orders/{po['id']}"))
    nos = [b["batch_no"] for b in po["batches"]]
    assert len(nos) == len(set(nos)) == 1  # الدفعات بأرقام فريدة


# ---------------------------------------------------------------- production line link
def test_order_with_production_line(api):
    wh, _branch = setup_world(api)
    raw = make_product(api, "R1", qty=50)
    fin = make_product(api, "F1")
    make_bom(api, fin["id"], [{"component_id": raw["id"], "qty_per_output": "1"}])
    lines = ok(api.post("/production-lines", json={"name": "خط A", "capacity_per_hour": 10}), 201)
    line = lines
    po = ok(api.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 5,
        "raw_warehouse_id": wh["id"], "output_warehouse_id": wh["id"],
        "production_line_id": line["id"],
    }), 201)
    assert po["production_line_id"] == line["id"]
    assert po["production_line_name"] == "خط A"
    # خط غير موجود يرفض
    r = api.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 5,
        "raw_warehouse_id": wh["id"], "output_warehouse_id": wh["id"],
        "production_line_id": 999999,
    })
    assert r.status_code == 422
