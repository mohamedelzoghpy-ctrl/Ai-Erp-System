"""Manufacturing (BOMs + production orders) and payment vouchers, end to end through the API (in-memory SQLite)."""

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


# ---------------------------------------------------------------- shared builders
def make_branch(c, name="Main"):
    return ok(c.post("/company/branches", json={"name": name, "location": None}), 201)


def make_warehouse(c, name, code):
    return ok(c.post("/warehouses", json={"name": name, "code": code}), 201)


def make_safe(c, name, branch_id):
    return ok(c.post("/safes", json={"name": name, "branch_id": branch_id}), 201)


def make_product(c, name, **extra):
    body = {"sku": f"SKU-{name}", "name": name, "sale_price": "100", "cost_price": "5", "quantity": 0, **extra}
    return ok(c.post("/products", json=body), 201)


def make_bom(c, product_id, items, output_qty=1, active=True, version="v1"):
    return ok(c.post("/boms", json={
        "product_id": product_id,
        "version": version,
        "output_qty": output_qty,
        "is_active": active,
        "items": items,
    }), 201)


def make_order(c, product_id, qty, raw_wh, out_wh, **extra):
    return ok(c.post("/production-orders", json={
        "product_id": product_id,
        "qty_planned": qty,
        "raw_warehouse_id": raw_wh,
        "output_warehouse_id": out_wh,
        **extra,
    }), 201)


def stock_of(c, product_id, warehouse_id):
    for row in ok(c.get(f"/products/{product_id}/stock")):
        if row["warehouse_id"] == warehouse_id:
            return row["quantity"]
    return 0


# ---------------------------------------------------------------- manufacturing: BOMs
def test_bom_creation_and_active_version_exclusivity(api):
    p1 = make_product(api, "F1")
    r1 = make_product(api, "R1")
    b1 = make_bom(api, p1["id"], [{"component_id": r1["id"], "qty_per_output": "2"}])
    assert b1["is_active"] is True
    assert b1["items"][0]["component_name"] == r1["name"]

    b2 = make_bom(api, p1["id"], [{"component_id": r1["id"], "qty_per_output": "3"}], version="v2")
    # activating v2 must deactivate v1
    assert b2["is_active"] is True
    assert ok(api.get(f"/boms/{b1['id']}"))["is_active"] is False

    # finished product cannot be its own component
    resp = api.post("/boms", json={"product_id": p1["id"], "items": [{"component_id": p1["id"], "qty_per_output": "1"}]})
    assert resp.status_code == 422

    # duplicate components rejected
    resp = api.post("/boms", json={"product_id": p1["id"], "items": [
        {"component_id": r1["id"], "qty_per_output": "1"},
        {"component_id": r1["id"], "qty_per_output": "2"},
    ]})
    assert resp.status_code == 422

    # delete guarded when used by an order — order not created yet, delete works
    assert api.delete(f"/boms/{b2['id']}").status_code == 204


def test_bom_delete_guarded_when_used_by_order(api):
    p1 = make_product(api, "F1")
    r1 = make_product(api, "R1")
    w = make_warehouse(api, "Main", "W1")
    bom = make_bom(api, p1["id"], [{"component_id": r1["id"], "qty_per_output": "2"}])
    make_order(api, p1["id"], 5, w["id"], w["id"])
    assert api.delete(f"/boms/{bom['id']}").status_code == 409


# ---------------------------------------------------------------- manufacturing: production orders
def test_production_order_full_cycle_with_labor_cost(api):
    c = api
    w = make_warehouse(api, "Main", "W1")
    raw = make_product(api, "R1", quantity=50, warehouse_id=w["id"])
    fin = make_product(api, "F1")
    make_bom(api, fin["id"], [{"component_id": raw["id"], "qty_per_output": "2"}])

    po = make_order(api, fin["id"], 10, w["id"], w["id"])
    assert po["status"] == "draft"
    assert po["code"].startswith("MO-")

    # issue: consumes 20 raw, posts WIP JE, status -> in_progress
    po = ok(api.post(f"/production-orders/{po['id']}/issue"))
    assert po["status"] == "in_progress"
    assert po["consumptions"][0]["qty"] == 20
    assert stock_of(api, raw["id"], w["id"]) == 30

    # labor cost 50: JE Dr WIP 50 / Cr salaries payable 50
    po = ok(api.post(f"/production-orders/{po['id']}/costs", json={"cost_type": "labor", "amount": "50", "description": "wages"}))
    assert po["costs_total"] == "50.00"
    assert po["costs"][0]["cost_type"] == "labor"

    # produce 10: finished stock in, JE Dr inventory / Cr WIP, cost = (100+50)/10 = 15
    po = ok(api.post(f"/production-orders/{po['id']}/produce", json={"qty": 10}))
    assert po["status"] == "completed"
    assert stock_of(api, fin["id"], w["id"]) == 10
    assert ok(api.get(f"/products/{fin['id']}"))["cost_price"] == "15.00"

    # batches created per produce call with pending QC
    details = ok(api.get(f"/production-orders/{po['id']}"))
    assert details["batches"][0]["batch_no"].endswith("-B1")
    assert details["batches"][0]["qc_status"] == "pending"

    # WIP account back to zero (zero-zero accounts are omitted from the reconcile report)
    wip = ok(api.get("/chart-of-accounts/reconcile"))
    wip_line = next((l for l in wip["lines"] if l["code"] == "1130"), None)
    assert wip_line is None or (float(wip_line["stored"]) == 0.0 and float(wip_line["drift"]) == 0.0)


def test_scrape_flow_records_loss_and_blocks_over(api):
    c = api
    w = make_warehouse(api, "Main", "W1")
    raw = make_product(api, "R1", quantity=50, warehouse_id=w["id"])
    fin = make_product(api, "F1")
    make_bom(api, fin["id"], [{"component_id": raw["id"], "qty_per_output": "2"}])

    po = ok(api.post("/production-orders", json={"product_id": fin["id"], "qty_planned": 5, "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"]}), 201)
    po = ok(api.post(f"/production-orders/{po['id']}/issue"))
    raw_left = stock_of(api, raw["id"], w["id"])  # 40

    # over-scrape blocked
    resp = api.post(f"/production-orders/{po['id']}/scrape", json={"qty": 6})
    assert resp.status_code == 422

    # scrape 2: JE Dr scrap expense 2×10=20 / Cr WIP 20, raw untouched
    po = ok(api.post(f"/production-orders/{po['id']}/scrape", json={"qty": 2, "notes": "damaged"}))
    assert po["qty_scrapped"] == 2
    assert stock_of(api, raw["id"], w["id"]) == raw_left  # raw already issued

    # remaining for production shrank: produce max 3 now
    resp = api.post(f"/production-orders/{po['id']}/produce", json={"qty": 4})
    assert resp.status_code == 422
    po = ok(api.post(f"/production-orders/{po['id']}/produce", json={"qty": 3}))
    assert po["status"] == "completed"

    # close with zero produced-minus-scrapped variance handled (zero-zero accounts omitted)
    wip = ok(api.get("/chart-of-accounts/reconcile"))
    wip_line = next((l for l in wip["lines"] if l["code"] == "1130"), None)
    assert wip_line is None or float(wip_line["stored"]) == 0.0


def test_child_mo_auto_created_for_component_with_own_bom(api):
    c = api
    w = make_warehouse(api, "Main", "W1")
    raw = make_product(api, "R1", quantity=100, warehouse_id=w["id"])
    semi = make_product(api, "S1")  # نصف مصنّع له قائمة مواد خاصة
    fin = make_product(api, "F1")
    make_bom(api, semi["id"], [{"component_id": raw["id"], "qty_per_output": "1"}])
    make_bom(api, fin["id"], [{"component_id": semi["id"], "qty_per_output": "2"}])

    po = ok(api.post("/production-orders", json={"product_id": fin["id"], "qty_planned": 3, "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"]}), 201)
    po = ok(api.post(f"/production-orders/{po['id']}/issue"))

    # child MO auto-created for the semi-finished component (draft, linked)
    children = ok(api.get(f"/production-orders/{po['id']}/children"))
    assert len(children) == 1
    assert children[0]["product_id"] == semi["id"]
    assert children[0]["qty_planned"] == 6  # ceil(2 × 3)
    assert children[0]["status"] == "draft"
    assert children[0]["parent_order_id"] == po["id"]

    # parent consumes 6 semi from stock — blocked (none produced yet)
    assert stock_of(api, semi["id"], w["id"]) == 0


def test_issue_blocked_on_insufficient_raw_stock(api):
    c = api
    w = make_warehouse(api, "Main", "W1")
    raw = make_product(api, "R1", quantity=5, warehouse_id=w["id"])
    fin = make_product(api, "F1")
    make_bom(api, fin["id"], [{"component_id": raw["id"], "qty_per_output": "2"}])
    po = ok(api.post("/production-orders", json={"product_id": fin["id"], "qty_planned": 10, "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"]}), 201)
    resp = api.post(f"/production-orders/{po['id']}/issue")
    assert resp.status_code == 409
    assert "Insufficient stock" in resp.json()["detail"]


def test_cancel_and_delete_guarded_after_issue(api):
    c = api
    w = make_warehouse(api, "Main", "W1")
    raw = make_product(api, "R1", quantity=50, warehouse_id=w["id"])
    fin = make_product(api, "F1")
    make_bom(api, fin["id"], [{"component_id": raw["id"], "qty_per_output": "2"}])
    po = ok(api.post("/production-orders", json={"product_id": fin["id"], "qty_planned": 1, "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"]}), 201)
    ok(api.post(f"/production-orders/{po['id']}/issue"))

    assert api.post(f"/production-orders/{po['id']}/cancel").status_code == 409
    assert api.delete(f"/production-orders/{po['id']}").status_code == 409


# ---------------------------------------------------------------- manufacturing: batches + QC
def test_batch_qc_reject_writes_off_stock(api):
    c = api
    w = make_warehouse(api, "Main", "W1")
    raw = make_product(api, "R1", quantity=50, warehouse_id=w["id"])
    fin = make_product(api, "F1")
    make_bom(api, fin["id"], [{"component_id": raw["id"], "qty_per_output": "2"}])
    po = ok(api.post("/production-orders", json={"product_id": fin["id"], "qty_planned": 4, "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"]}), 201)
    po = ok(api.post(f"/production-orders/{po['id']}/issue"))
    po = ok(api.post(f"/production-orders/{po['id']}/produce", json={"qty": 4}))

    batch = po["batches"][0]
    assert batch["qc_status"] == "pending"
    assert batch["batch_no"].startswith(po["code"])

    # reject requires a reason now; finished stock written off, JE Dr scrap expense / Cr inventory
    resp = api.post(f"/production-orders/{po['id']}/batches/{batch['id']}/qc", json={"result": "rejected"})
    assert resp.status_code == 422  # without a reason it is refused
    ok(api.post(f"/production-orders/{po['id']}/batches/{batch['id']}/qc", json={"result": "rejected", "notes": "damaged"}))
    assert stock_of(api, fin["id"], w["id"]) == 0
    details = ok(api.get(f"/production-orders/{po['id']}"))
    assert details["batches"][0]["qc_status"] == "rejected"

    # double QC blocked
    resp = api.post(f"/production-orders/{po['id']}/batches/{batch['id']}/qc", json={"result": "passed"})
    assert resp.status_code == 409

    # approve path on a second order
    po2 = ok(api.post("/production-orders", json={"product_id": fin["id"], "qty_planned": 2, "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"]}), 201)
    ok(api.post(f"/production-orders/{po2['id']}/issue"))
    po2 = ok(api.post(f"/production-orders/{po2['id']}/produce", json={"qty": 2}))
    b2 = po2["batches"][0]
    ok(api.post(f"/production-orders/{po2['id']}/batches/{b2['id']}/qc", json={"result": "passed"}))
    details2 = ok(api.get(f"/production-orders/{po2['id']}"))
    assert details2["batches"][0]["qc_status"] == "passed"
    assert stock_of(api, fin["id"], w["id"]) == 2  # approved batch stays in stock


# ---------------------------------------------------------------- payment vouchers
def make_voucher_setup(c):
    branch = make_branch(c)
    safe = make_safe(c, "Main Safe", branch["id"])
    customer = ok(c.post("/customers", json={"name": "عميل تجربة"}), 201)
    cat_party = ok(c.post("/payment-categories", json={"name": "تحصيل مديونية", "kind": "receipt", "requires_party": True}), 201)
    cat_noparty = ok(c.post("/payment-categories", json={"name": "إيجار محل", "kind": "receipt", "requires_party": False}), 201)
    return {"branch": branch, "safe": safe, "customer": customer, "cat_party": cat_party, "cat_noparty": cat_noparty}


def test_receipt_with_party_and_category(api):
    c = api
    s = make_voucher_setup(api)
    v = ok(c.post("/payments", json={
        "customer_id": s["customer"]["id"],
        "amount": "250",
        "method": "cash",
        "category_id": s["cat_party"]["id"],
        "safe_id": s["safe"]["id"],
    }), 201)
    assert v["category_id"] == s["cat_party"]["id"]
    assert v["category_name"] == "تحصيل مديونية"
    # safe received the money
    assert float(ok(api.get("/safes"))[0]["balance"]) == 250.0


def test_party_less_voucher_validation_chain(api):
    c = api
    s = make_voucher_setup(api)
    # no party + no category -> 422 (schema)
    resp = api.post("/payments", json={"amount": "100", "method": "cash", "safe_id": s["safe"]["id"]})
    assert resp.status_code == 422
    # category that requires a party but no party -> 422 (route)
    resp = api.post("/payments", json={
        "amount": "100", "method": "cash", "safe_id": s["safe"]["id"], "category_id": s["cat_party"]["id"],
    })
    assert resp.status_code == 422
    # party-less requires a place -> 422 without safe
    resp = api.post("/payments", json={
        "amount": "100", "method": "cash", "category_id": s["cat_noparty"]["id"],
    })
    assert resp.status_code == 422
    # valid party-less: category (no party) + safe -> 201
    v = ok(c.post("/payments", json={
        "amount": "300", "method": "cash", "safe_id": s["safe"]["id"], "category_id": s["cat_noparty"]["id"],
    }), 201)
    assert v["kind"] == "receipt"
    assert v["category_name"] == "إيجار محل"
    assert float(ok(api.get("/safes"))[0]["balance"]) == 300.0


def test_party_less_payment_requires_no_party_category(api):
    s = make_voucher_setup(api)
    # category with requires_party=True cannot be used party-less
    resp = api.post("/payments", json={
        "amount": "50", "method": "cash", "safe_id": s["safe"]["id"], "category_id": s["cat_party"]["id"],
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------- reconciliation tool
def test_reconcile_report_and_apply_restores_ledger_balances(api):
    c = api
    s = make_voucher_setup(api)
    # a safe provisioned with an opening balance and never used -> drift = its opening
    ok(c.post("/safes", json={"name": "Old Safe", "branch_id": s["branch"]["id"], "opening_balance": "121.80"}), 201)
    report = ok(api.get("/chart-of-accounts/reconcile"))
    drift_lines = [l for l in report["lines"] if float(l["drift"]) != 0]
    assert len(drift_lines) >= 1
    total_drift = float(report["total_drift"])
    assert total_drift != 0

    # apply: stored balances rebuilt from the ledger
    ok(api.post("/chart-of-accounts/reconcile/apply"))
    report2 = ok(api.get("/chart-of-accounts/reconcile"))
    assert float(report2["total_drift"]) == 0.0
    for line in report2["lines"]:
        assert float(line["stored"]) == float(line["ledger"])
