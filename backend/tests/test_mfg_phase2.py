"""المرحلة 2 من خطة التصنيع: MRP التنفيذي + ربط أمر البيع + تكلفة BOM المجمّعة + سريان الإصدار."""
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


def make_product(c, name, **extra):
    body = {"sku": f"SKU-{name}", "name": name, "sale_price": "100", "cost_price": "5", "quantity": 0, **extra}
    return ok(c.post("/products", json=body), 201)


def make_bom(c, product_id, items, output_qty=1, active=True, version="v1", **extra):
    return ok(c.post("/boms", json={
        "product_id": product_id, "version": version, "output_qty": output_qty,
        "is_active": active, "items": items, "operations": [], **extra,
    }), 201)


# ---------------------------------------------------------------- MRP التنفيذي
def test_mrp_execute_creates_draft_production_order(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price="10", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    make_bom(c, fin["id"], [{"component_id": raw["id"], "qty_per_output": 2}])
    out = ok(c.post("/production-orders/mrp/execute", json={
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
        "items": [{"product_id": fin["id"], "qty": 10, "action": "produce"}],
    }))
    assert len(out["created"]) == 1 and out["skipped"] == []
    mo = ok(c.get(f"/production-orders/{out['created'][0]['order_id']}"))
    assert mo["status"] == "draft" and float(mo["qty_planned"]) == 10.0
    assert float(mo["std_unit_cost"]) == 20.0  # 2 × 10
    # الأمر ظاهر في قائمة الأوامر كمسودة من التنفيذ
    codes = [o["code"] for o in ok(c.get("/production-orders?limit=50"))]
    assert mo["code"] in codes


def test_mrp_execute_buy_creates_draft_purchase_order(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    supp = ok(c.post("/suppliers", json={"name": "مورد MRP"}), 201)
    comp = make_product(c, "C1", cost_price="7")
    out = ok(c.post("/production-orders/mrp/execute", json={
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
        "items": [{"product_id": comp["id"], "qty": 30, "action": "buy", "supplier_id": supp["id"], "purchase_price": "6.5"}],
    }))
    assert len(out["created"]) == 1
    po = ok(c.get(f"/purchase-orders/{out['created'][0]['order_id']}"))
    assert po["status"] == "draft" and po["supplier_id"] == supp["id"]
    assert float(po["items"][0]["quantity"]) == 30.0 and float(po["items"][0]["unit_cost"]) == 6.5
    assert float(po["total_amount"]) == 195.0


def test_mrp_execute_mixed_with_invalid_falls_back_to_skipped(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price="10", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    make_bom(c, fin["id"], [{"component_id": raw["id"], "qty_per_output": 1}])
    supp = ok(c.post("/suppliers", json={"name": "مورد ٢"}), 201)
    orphan = make_product(c, "NO-BOM")
    out = ok(c.post("/production-orders/mrp/execute", json={
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
        "items": [
            {"product_id": fin["id"], "qty": 5, "action": "produce"},
            {"product_id": orphan["id"], "qty": 5, "action": "produce"},          # بلا BOM → skipped
            {"product_id": orphan["id"], "qty": 3, "action": "buy"},              # بلا مورد → skipped
            {"product_id": raw["id"], "qty": 40, "action": "buy", "supplier_id": supp["id"]},
        ],
    }))
    assert len(out["created"]) == 2 and len(out["skipped"]) == 2
    reasons = {s["reason"] for s in out["skipped"]}
    assert any("قائمة مواد" in r for r in reasons) and any("المورد" in r for r in reasons)


# ---------------------------------------------------------------- ربط أمر البيع
def test_sales_order_link_and_scoped_aggregate(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price="10", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    make_bom(c, fin["id"], [{"component_id": raw["id"], "qty_per_output": 1}])
    cust = ok(c.post("/customers", json={"name": "عميل MTO"}), 201)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": w["id"],
        "items": [{"product_id": fin["id"], "quantity": 5, "unit_price": "100"}],
    }), 201)

    agg = ok(c.get("/production-orders/mrp/aggregate"))
    assert any(r["product_id"] == fin["id"] and float(r["shortfall"]) == 5.0 for r in agg["lines"])
    agg2 = ok(c.get(f"/production-orders/mrp/aggregate?sales_order_id={so['id']}"))
    assert any(r["product_id"] == fin["id"] and float(r["open_demand"]) == 5.0 for r in agg2["lines"])
    # أمر بيع غير موجود → 404
    assert c.get("/production-orders/mrp/aggregate?sales_order_id=999999").status_code == 404

    mo = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 5,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
        "sales_order_id": so["id"], "notes": "MTO",
    }), 201)
    detail = ok(c.get(f"/production-orders/{mo['id']}"))
    assert detail["sales_order_id"] == so["id"]
    # ربط بأمر بيع غير موجود → 422
    r = c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 1,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
        "sales_order_id": 999999,
    })
    assert r.status_code == 422


# ---------------------------------------------------------------- تكلفة BOM المجمّعة
def test_bom_cost_rollup_flat(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", cost_price="10")
    fin = make_product(c, "F1")
    bom = make_bom(c, fin["id"], [{"component_id": raw["id"], "qty_per_output": 2, "scrap_pct": "10"}])
    r = ok(c.get(f"/boms/{bom['id']}/cost-rollup"))
    assert len(r["lines"]) == 1 and r["lines"][0]["source"] == "cost_price"
    assert float(r["lines"][0]["unit_cost"]) == 10.0
    # 2 × (1 + 10%) × 10 = 22
    assert float(r["unit_cost"]) == 22.0


def test_bom_cost_rollup_nested_uses_child_rollup(api):
    """المكوّن له قائمة سارية خاصة → تُستخدم تكلفته المجمّعة لا تكلفة الشراء المسجلة.
    قائمة الوسيط تنتج 10 وحدات من خامة بتكلفة 99 → تكلفة الوحدة المجمّعة 9.9 ≠ أي تكلفة مسجلة."""
    c = api
    w = make_warehouse(c, "Main", "W1")
    sub_raw = make_product(c, "SRAW", cost_price="99")   # تكلفة الخامة الورقية
    sub = make_product(c, "SUB", cost_price="99")        # الوسيط — تكلفته المسجلة لا تُستخدم
    make_bom(c, sub["id"], [{"component_id": sub_raw["id"], "qty_per_output": 1}], version="s1", output_qty=10)
    fin = make_product(c, "F1")
    bom = make_bom(c, fin["id"], [{"component_id": sub["id"], "qty_per_output": 1}])
    r = ok(c.get(f"/boms/{bom['id']}/cost-rollup"))
    assert r["lines"][0]["source"] == "own_bom"
    assert float(r["lines"][0]["unit_cost"]) == 9.9 and float(r["unit_cost"]) == 9.9


def test_bom_cost_rollup_cycle_detected(api):
    c = api
    a = make_product(c, "A")
    b = make_product(c, "B")
    bom_a = make_bom(c, a["id"], [{"component_id": b["id"], "qty_per_output": 1}])
    make_bom(c, b["id"], [{"component_id": a["id"], "qty_per_output": 1}], version="v1")
    assert c.get(f"/boms/{bom_a['id']}/cost-rollup").status_code == 422


# ---------------------------------------------------------------- سريان الإصدار
def test_bom_effectivity_window_selects_valid_version(api):
    """قائمتان لنفس المنتج: الأولى انتهت أمس والثانية تبدأ اليوم — إنشاء الأمر يختار السارية."""
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price="10", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    old_bom = make_bom(c, fin["id"], [{"component_id": raw["id"], "qty_per_output": 5}],
                       version="old", active=True,
                       valid_from=str(date.today() - timedelta(days=30)),
                       valid_to=str(date.today() - timedelta(days=1)))
    new_bom = make_bom(c, fin["id"], [{"component_id": raw["id"], "qty_per_output": 1}],
                       version="new", active=True,
                       valid_from=str(date.today()))
    mo = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 2,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
    }), 201)
    detail = ok(c.get(f"/production-orders/{mo['id']}"))
    assert detail["bom_id"] == new_bom["id"] and detail["bom_id"] != old_bom["id"]
    assert float(detail["std_unit_cost"]) == 10.0  # من القائمة الجديدة 1×10

    # قائمة مستقبلية فقط → لا قائمة سارية → 422
    fin2 = make_product(c, "F2")
    make_bom(c, fin2["id"], [{"component_id": raw["id"], "qty_per_output": 1}],
             version="future", valid_from=str(date.today() + timedelta(days=7)))
    r = c.post("/production-orders", json={
        "product_id": fin2["id"], "qty_planned": 1,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
    })
    assert r.status_code == 422 and "سارية" in r.json()["detail"]

    # تاريخ بداية بعد النهاية → 422
    r2 = c.post("/boms", json={
        "product_id": fin["id"], "version": "bad", "output_qty": 1, "is_active": False,
        "valid_from": str(date.today()), "valid_to": str(date.today() - timedelta(days=1)),
        "items": [],
    })
    assert r2.status_code == 422
