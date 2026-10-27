"""Per-warehouse stock and transfers, end to end through the API (in-memory SQLite)."""

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
    assert client.post("/auth/setup", json={"username": "boss", "password": "long-password"}).status_code == 201
    token = client.post("/auth/login", data={"username": "boss", "password": "long-password"}).json()["access_token"]
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


def by_wh(c, pid):
    return {r["warehouse_id"]: r["quantity"] for r in ok(c.get(f"/products/{pid}/stock"))}


def total(c, pid):
    return ok(c.get(f"/products/{pid}"))["quantity"]


def test_opening_stock_sits_in_the_products_warehouse(api):
    w1, w2 = make_warehouses(api)
    p = make_product(api, "A", 10, w1["id"])
    assert by_wh(api, p["id"]) == {w1["id"]: 10} and total(api, p["id"]) == 10
    # without a warehouse of its own the opening stock goes to the oldest warehouse
    q = ok(api.post("/products", json={"sku": "B", "name": "B", "quantity": 3}), 201)
    assert by_wh(api, q["id"]) == {w1["id"]: 3}


def test_sales_can_only_take_what_the_warehouse_holds(api):
    w1, w2 = make_warehouses(api)
    p = make_product(api, "A", 10, w1["id"])
    cust = ok(api.post("/customers", json={"name": "C"}), 201)
    order = ok(api.post("/sales-orders", json={"customer_id": cust["id"], "warehouse_id": w2["id"], "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "10"}]}), 201)
    r = api.post(f"/sales-orders/{order['id']}/confirm")
    assert r.status_code == 409 and "Shop" in r.text, r.text  # 10 in total, but none of it in this warehouse
    assert total(api, p["id"]) == 10


def test_transfer_moves_stock_between_warehouses_and_keeps_the_total(api):
    w1, w2 = make_warehouses(api)
    p = make_product(api, "A", 10, w1["id"])
    t = ok(api.post("/stock-transfers", json={"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"], "notes": "restock shop",
                                              "items": [{"product_id": p["id"], "quantity": 3}, {"product_id": p["id"], "quantity": 1}]}), 201)
    ok(api.post(f"/stock-transfers/{t['id']}/approve"))  # approval executes the movement
    assert [(i["product_id"], i["quantity"]) for i in t["items"]] == [(p["id"], 4)]  # duplicate lines merged
    assert t["from_warehouse_name"] == "Main" and t["to_warehouse_name"] == "Shop"
    assert by_wh(api, p["id"]) == {w1["id"]: 6, w2["id"]: 4} and total(api, p["id"]) == 10
    moves = ok(api.get(f"/products/{p['id']}/movements"))
    assert {(m["reason"], m["change"], m["warehouse_id"], m["reference"]) for m in moves if m["reason"].startswith("transfer")} == {
        ("transfer_out", -4, w1["id"], f"TR-{t['id']}"), ("transfer_in", 4, w2["id"], f"TR-{t['id']}"),
    }
    assert ok(api.get(f"/stock-transfers/{t['id']}"))["notes"] == "restock shop"
    assert len(ok(api.get(f"/stock-transfers?warehouse_id={w2['id']}"))) == 1
    pdf = api.get(f"/stock-transfers/{t['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_transfer_validation_is_all_or_nothing(api):
    w1, w2 = make_warehouses(api)
    a, b = make_product(api, "A", 5, w1["id"]), make_product(api, "B", 1, w1["id"])
    base = {"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"]}
    ok(api.post("/stock-transfers", json={**base, "to_warehouse_id": w1["id"], "items": [{"product_id": a["id"], "quantity": 1}]}), 422)
    ok(api.post("/stock-transfers", json={**base, "to_warehouse_id": 999, "items": [{"product_id": a["id"], "quantity": 1}]}), 422)
    ok(api.post("/stock-transfers", json={**base, "items": [{"product_id": 999, "quantity": 1}]}), 422)
    ok(api.post("/stock-transfers", json={**base, "items": [{"product_id": a["id"], "quantity": 0}]}), 422)
    ok(api.post("/stock-transfers", json={**base, "items": []}), 422)
    r = api.post("/stock-transfers", json={**base, "items": [{"product_id": a["id"], "quantity": 2}, {"product_id": b["id"], "quantity": 2}]})
    assert r.status_code == 409 and "Item B" in r.text, r.text
    assert by_wh(api, a["id"]) == {w1["id"]: 5} and by_wh(api, b["id"]) == {w1["id"]: 1}  # nothing moved
    assert ok(api.get("/stock-transfers")) == []
    ok(api.get("/stock-transfers/999"), 404)


def test_purchase_return_and_adjustment_use_the_right_warehouse(api):
    w1, w2 = make_warehouses(api)
    p = make_product(api, "A", 0, w1["id"])
    sup = ok(api.post("/suppliers", json={"name": "S"}), 201)
    po = ok(api.post("/purchase-orders", json={"supplier_id": sup["id"], "warehouse_id": w2["id"], "items": [{"product_id": p["id"], "quantity": 8, "unit_cost": "4"}]}), 201)
    ok(api.post(f"/purchase-orders/{po['id']}/receive"))
    assert by_wh(api, p["id"]) == {w2["id"]: 8}  # received where the order says, not in the product's own warehouse
    line = ok(api.get(f"/purchase-orders/{po['id']}"))["items"][0]["id"]
    ok(api.post("/purchase-returns", json={"order_id": po["id"], "items": [{"order_item_id": line, "quantity": 3}]}), 201)
    assert by_wh(api, p["id"]) == {w2["id"]: 5}
    ok(api.post(f"/products/{p['id']}/adjust-stock", json={"change": 2, "warehouse_id": w1["id"]}))
    ok(api.post(f"/products/{p['id']}/adjust-stock", json={"change": -3}), 409)  # default is the product's warehouse (Main): only 2 there
    ok(api.post(f"/products/{p['id']}/adjust-stock", json={"change": -2, "warehouse_id": w2["id"]}))
    assert by_wh(api, p["id"]) == {w1["id"]: 2, w2["id"]: 3} and total(api, p["id"]) == 5


def test_stocktake_counts_one_warehouse_and_adjusts_only_it(api):
    w1, w2 = make_warehouses(api)
    p = make_product(api, "A", 10, w1["id"])
    ok(api.post("/stock-transfers", json={"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"], "items": [{"product_id": p["id"], "quantity": 4}]}), 201)
    _ts = ok(api.get("/stock-transfers?status=pending"))[0]
    ok(api.post(f"/stock-transfers/{_ts['id']}/approve"))
    ok(api.post("/stocktakes", json={}), 422)  # a count needs a warehouse now
    st = ok(api.post("/stocktakes", json={"warehouse_id": w2["id"]}), 201)
    sheet = ok(api.get(f"/stocktakes/{st['id']}"))["lines"]
    assert [(l["product_id"], l["system_qty"]) for l in sheet] == [(p["id"], 4)]  # the shop's quantity, not the total
    ok(api.put(f"/stocktakes/{st['id']}/counts", json={"counts": [{"product_id": p["id"], "counted_qty": 3}]}))
    ok(api.post(f"/stocktakes/{st['id']}/apply"))
    assert by_wh(api, p["id"]) == {w1["id"]: 6, w2["id"]: 3} and total(api, p["id"]) == 9


def test_staff_only_see_and_move_stock_of_their_own_warehouses(api):
    w1, w2 = make_warehouses(api)
    p = make_product(api, "A", 10, w1["id"])
    ok(api.post("/stock-transfers", json={"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"], "items": [{"product_id": p["id"], "quantity": 4}]}), 201)
    _ts = ok(api.get("/stock-transfers?status=pending"))[0]
    ok(api.post(f"/stock-transfers/{_ts['id']}/approve"))
    me = ok(api.get("/auth/me"))
    branch = ok(api.get("/warehouses"))[0]["branch_id"]
    ok(api.post("/company/employees", json={"username": "clerk", "password": "clerk-password", "role": "staff", "warehouse_ids": [w2["id"]]}), 201)
    tok = ok(api.post("/auth/login", data={"username": "clerk", "password": "clerk-password"}))["access_token"]
    staff = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    assert by_wh(staff, p["id"]) == {w2["id"]: 4}  # the Main warehouse row is not theirs to see
    assert len(ok(staff.get("/stock-transfers"))) == 1  # but the transfer into their warehouse is
    r = staff.post("/stock-transfers", json={"from_warehouse_id": w2["id"], "to_warehouse_id": w1["id"], "items": [{"product_id": p["id"], "quantity": 1}]})
    assert r.status_code == 422, r.text  # cannot send to a warehouse they have no access to
    assert by_wh(api, p["id"]) == {w1["id"]: 6, w2["id"]: 4}
    del me, branch
