"""المرحلة 1 من خطة التصنيع 82→95: التتبع الأمامي (سحب استدعاء) + إعادة فحص QC + بوابة القياسات."""
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


def receive_raw_lot(c, product_id, warehouse_id, qty=50, lot_code="LOT-R1"):
    return ok(c.post("/lots", json={
        "product_id": product_id, "warehouse_id": warehouse_id,
        "lot_code": lot_code, "qty": qty,
    }), 201)


def produce_one_batch(c, raw_id, lot_id, w=None):
    """دورة كاملة: BOM ← أمر ← صرف خامات (تُخصص على اللوط) ← إنتاج دفعة. يعيد (الأمر، الدفعة، المخزن)."""
    if w is None:
        w = make_warehouse(c, "Main", "W1")
    fin = make_product(c, "F1")
    ok(c.post("/boms", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw_id, "qty_per_output": 1}],
    }), 201)
    po = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 5,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
    }), 201)
    po = ok(c.post(f"/production-orders/{po['id']}/issue"))
    po = ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 5}))
    batches = [b for b in po["batches"]]
    assert len(batches) == 1
    return po, batches[0], w


def make_qc_template_with_range(c, name="PH", min_v=1.0, max_v=5.0):
    tpl = ok(c.post("/qc/templates", json={
        "name": name, "parameters": [{"name": "pH", "param_type": "number", "min_value": min_v, "max_value": max_v}],
    }), 201)
    return tpl


def first_qc_parameter_id(c):
    tpl = ok(c.get("/qc/templates"))[0]
    return tpl["parameters"][0]["id"]


def record_measurement(c, batch_id, param_id, value, expect=200):
    return c.post(f"/qc/batches/{batch_id}/results", json={"results": [{"parameter_id": param_id, "value_num": value}]}), expect


# ---------------------------------------------------------------- التتبع الأمامي
def test_forward_trace_raw_lot_to_finished_batches(api):
    """لوط خام ← الأمر الذي استهلكه ← الدفعة النهائية ورصيدها الحالي في المخزن."""
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price="10", warehouse_id=w["id"])
    lot = receive_raw_lot(c, raw["id"], w["id"], qty=50, lot_code="LOT-R1")
    po, batch, _ = produce_one_batch(c, raw["id"], lot["id"], w=w)

    tr = ok(c.get(f"/production-orders/lots/{lot['id']}/trace-forward"))
    assert tr["lot_code"] == "LOT-R1" and tr["product_name"] == "R1"
    assert len(tr["orders"]) == 1
    o = tr["orders"][0]
    assert o["order_id"] == po["id"] and float(o["consumed_qty"]) == 5.0
    assert len(o["batches"]) == 1
    b = o["batches"][0]
    assert b["batch_no"] == batch["batch_no"] and b["qc_status"] == "pending"
    assert float(b["finished_lot_qty"]) == 5.0


def test_forward_trace_multiple_consumers_and_unknown_lot(api):
    """لوط واحد يغذي أمرين → صفان بالترتيب؛ ولوط غير موجود → 404."""
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price="10", warehouse_id=w["id"])
    lot = receive_raw_lot(c, raw["id"], w["id"], qty=100, lot_code="LOT-R1")
    fin = make_product(c, "F1")
    ok(c.post("/boms", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": 1}],
    }), 201)
    for _ in range(2):
        po = ok(c.post("/production-orders", json={
            "product_id": fin["id"], "qty_planned": 3,
            "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
        }), 201)
        ok(c.post(f"/production-orders/{po['id']}/issue"))
    tr = ok(c.get(f"/production-orders/lots/{lot['id']}/trace-forward"))
    assert len(tr["orders"]) == 2 and float(tr["orders"][0]["consumed_qty"]) == 3.0
    assert c.get("/production-orders/lots/999999/trace-forward").status_code == 404


# ---------------------------------------------------------------- إعادة فحص QC
def test_qc_retest_round_then_final_pass(api):
    """قياس فاشل → إعادة فحص (محاولة 2) → قياس مطابق → اعتماد نهائي، والسجل يحفظ المحاولتين."""
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price="10", warehouse_id=w["id"])
    lot = receive_raw_lot(c, raw["id"], w["id"])
    po, batch, _ = produce_one_batch(c, raw["id"], lot["id"], w=w)
    make_qc_template_with_range(c)
    param_id = first_qc_parameter_id(c)  # النطاق 1..5

    # محاولة 1: قياس خارج النطاق
    r = ok(c.post(f"/qc/batches/{batch['id']}/results", json={
        "results": [{"parameter_id": param_id, "value_num": 8.0}],
    }))
    assert r["attempt"] == 1 and r["overall_pass"] is False

    # إعادة فحص → محاولة جديدة فارغة
    r2 = ok(c.post(f"/qc/batches/{batch['id']}/retest"))
    assert r2["attempt"] == 2 and r2["results"] == []

    # محاولة 2: قياس مطابق + اعتماد
    r3 = ok(c.post(f"/qc/batches/{batch['id']}/results", json={
        "results": [{"parameter_id": param_id, "value_num": 4.0}],
    }))
    assert r3["attempt"] == 2 and r3["overall_pass"] is True
    rel = ok(c.post(f"/qc/batches/{batch['id']}/release?action=passed"))
    assert rel["qc_status"] == "passed"

    # السجل الكامل: محاولتان، وآخر محاولة فقط افتراضياً
    latest = ok(c.get(f"/qc/batches/{batch['id']}/results"))
    assert latest["attempts_count"] == 2 and len(latest["results"]) == 1 and latest["results"][0]["value_num"] == 4.0
    allr = ok(c.get(f"/qc/batches/{batch['id']}/results?all_attempts=true"))
    assert len(allr["results"]) == 2 and {x["attempt"] for x in allr["results"]} == {1, 2}


def test_retest_blocked_after_final_verdict(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price="10", warehouse_id=w["id"])
    lot = receive_raw_lot(c, raw["id"], w["id"])
    po, batch, _ = produce_one_batch(c, raw["id"], lot["id"], w=w)
    ok(c.post(f"/qc/batches/{batch['id']}/release?action=passed"))
    assert c.post(f"/qc/batches/{batch['id']}/retest").status_code == 409


# ---------------------------------------------------------------- بوابة القياسات
def test_measurement_gate_blocks_pass_with_failing_measurement(api, monkeypatch):
    """QC_MEASURE_GATE=1: اعتماد دفعة عليها قياس فاشل → 409 باسم المعيار؛ بعد إعادة فحص مطابقة → يعتمد."""
    monkeypatch.setenv("QC_MEASURE_GATE", "1")
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price="10", warehouse_id=w["id"])
    lot = receive_raw_lot(c, raw["id"], w["id"])
    po, batch, _ = produce_one_batch(c, raw["id"], lot["id"], w=w)
    make_qc_template_with_range(c)
    param_id = first_qc_parameter_id(c)

    ok(c.post(f"/qc/batches/{batch['id']}/results", json={
        "results": [{"parameter_id": param_id, "value_num": 8.0}],
    }))
    r = c.post(f"/qc/batches/{batch['id']}/release?action=passed")
    assert r.status_code == 409 and "pH" in r.json()["detail"]

    ok(c.post(f"/qc/batches/{batch['id']}/retest"))
    ok(c.post(f"/qc/batches/{batch['id']}/results", json={
        "results": [{"parameter_id": param_id, "value_num": 3.0}],
    }))
    rel = ok(c.post(f"/qc/batches/{batch['id']}/release?action=passed"))
    assert rel["qc_status"] == "passed"


def test_measurement_gate_off_by_default(api, monkeypatch):
    """بدون البوابة: قياس فاشل لا يمنع الاعتماد اليدوي (السلوك القديم محفوظ)."""
    monkeypatch.delenv("QC_MEASURE_GATE", raising=False)
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price="10", warehouse_id=w["id"])
    lot = receive_raw_lot(c, raw["id"], w["id"])
    po, batch, _ = produce_one_batch(c, raw["id"], lot["id"], w=w)
    make_qc_template_with_range(c)
    param_id = first_qc_parameter_id(c)
    ok(c.post(f"/qc/batches/{batch['id']}/results", json={
        "results": [{"parameter_id": param_id, "value_num": 8.0}],
    }))
    rel = ok(c.post(f"/qc/batches/{batch['id']}/release?action=passed"))
    assert rel["qc_status"] == "passed"
