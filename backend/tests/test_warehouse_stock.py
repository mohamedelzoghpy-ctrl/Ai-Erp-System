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


def give_section(c, user_id: int, codes):
    """نظام الصلاحيات: قسم مؤقت للاختبار + إسناده للمستخدم."""
    sec = ok(c.post("/access-sections", json={"code": f"t{user_id}", "name": "قسم اختبار"}), 201)
    ok(c.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": codes}))
    ok(c.put(f"/auth/users/{user_id}/section", json={"section_id": sec["id"]}))
    return sec


def by_wh(c, pid):
    return {r["warehouse_id"]: r["quantity"] for r in ok(c.get(f"/products/{pid}/stock"))}


def total(c, pid):
    return ok(c.get(f"/products/{pid}"))["quantity"]




def _reason_id(c):
    r = c.get("/products/adjustment-reasons")
    rows = r.json() if r.status_code == 200 else []
    if rows:
        return rows[0]["id"]
    return c.post("/products/adjustment-reasons", json={"name": "تسوية اختبار"}).json()["id"]


def test_data_io_warehouse_stock_export_and_undo_routes(api):
    from io import BytesIO
    import openpyxl

    warehouse, _ = make_warehouses(api)
    product = make_product(api, "DATA-IO", 5, warehouse["id"])

    export_response = api.get(f"/data-io/warehouses/stock/xlsx?warehouse_id={warehouse['id']}")
    assert export_response.status_code == 200, export_response.text
    assert export_response.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert export_response.content[:2] == b"PK"
    workbook = openpyxl.load_workbook(BytesIO(export_response.content))
    sheet = workbook.active
    header_row = next(row for row in range(1, sheet.max_row + 1) if sheet.cell(row, 1).value == "الكود (SKU)")
    data_row = next(row for row in range(header_row + 1, sheet.max_row + 1) if sheet.cell(row, 1).value == "DATA-IO")
    sheet.cell(data_row, 5).value = 7
    edited = BytesIO()
    workbook.save(edited)

    upload = api.post(
        f"/data-io/warehouses/stock/xlsx?warehouse_id={warehouse['id']}",
        files={"file": ("stock.xlsx", edited.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["applied"] == 1
    assert total(api, product["id"]) == 7

    undo = api.post(f"/data-io/warehouses/stock/undo?warehouse_id={warehouse['id']}")
    assert undo.status_code == 200, undo.text
    assert undo.json()["products"] == 1
    assert total(api, product["id"]) == 5


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


def test_price_quotation_checkout_records_payment_and_deducts_stock(api):
    warehouse, _ = make_warehouses(api)
    product = make_product(api, "QUOTE-A", 8, warehouse["id"])
    customer = ok(api.post("/customers", json={"name": "Quotation Customer"}), 201)

    receipt = ok(api.post("/pos/checkout", json={
        "customer_id": customer["id"],
        "warehouse_id": warehouse["id"],
        "items": [{"product_id": product["id"], "quantity": 3, "unit_price": "12.50"}],
        "amount_paid": "20.00",
        "method": "cash",
        "notes": "Quotation-style sale",
    }), 201)

    order = ok(api.get(f"/sales-orders/{receipt['order_id']}"))
    assert order["status"] == "confirmed"
    assert receipt["total"] == "37.50"
    assert receipt["paid"] == "20.00"
    assert receipt["balance_due"] == "17.50"
    assert total(api, product["id"]) == 5
    payments = ok(api.get("/payments?kind=receipt"))
    assert any(p["customer_id"] == customer["id"] and p["amount"] == "20.00" for p in payments)

    quotation = api.get(f"/sales-orders/{receipt['order_id']}/quotation.pdf")
    assert quotation.status_code == 200, quotation.text
    assert quotation.headers["content-type"].startswith("application/pdf")
    assert "quotation-SO-" in quotation.headers["content-disposition"]


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


def test_purchase_credit_invoice_is_received_immediately_and_remains_unpaid(api):
    warehouse, _ = make_warehouses(api)
    product = make_product(api, "CREDIT-A", 0, warehouse["id"])
    supplier = ok(api.post("/suppliers", json={"name": "Credit Supplier"}), 201)

    purchase = ok(api.post("/purchase-orders", json={
        "supplier_id": supplier["id"],
        "warehouse_id": warehouse["id"],
        "payment_mode": "credit",
        "items": [{"product_id": product["id"], "quantity": 4, "unit_cost": "6.25"}],
    }), 201)

    assert purchase["status"] == "received"
    assert purchase["payment_status"] == "unpaid"
    assert purchase["paid_amount"] == "0.00"
    assert purchase["balance_due"] == "28.50"
    assert by_wh(api, product["id"]) == {warehouse["id"]: 4}
    assert ok(api.get("/payments?supplier_id=%d" % supplier["id"])) == []


def test_purchase_invoice_can_disable_vat(api):
    warehouse, _ = make_warehouses(api)
    product = make_product(api, "NO-VAT-A", 0, warehouse["id"])
    supplier = ok(api.post("/suppliers", json={"name": "No VAT Supplier"}), 201)

    purchase = ok(api.post("/purchase-orders", json={
        "supplier_id": supplier["id"],
        "warehouse_id": warehouse["id"],
        "payment_mode": "credit",
        "discount_mode": "amount",
        "discount_value": "5",
        "tax_rate": "0",
        "items": [{"product_id": product["id"], "quantity": 2, "unit_cost": "20"}],
    }), 201)

    assert purchase["status"] == "received"
    assert purchase["total_amount"] == "35.00"
    assert purchase["balance_due"] == "35.00"
    assert by_wh(api, product["id"]) == {warehouse["id"]: 2}


def test_purchase_cash_invoice_is_received_and_paid_immediately(api):
    w1, w2 = make_warehouses(api)
    p = make_product(api, "A", 0, w1["id"])
    sup = ok(api.post("/suppliers", json={"name": "S"}), 201)
    safe = ok(api.post("/safes", json={"name": "Purchase Cash", "branch_id": w2["branch_id"]}), 201)
    po = ok(api.post("/purchase-orders", json={"supplier_id": sup["id"], "warehouse_id": w2["id"], "payment_mode": "cash", "safe_id": safe["id"], "items": [{"product_id": p["id"], "quantity": 8, "unit_cost": "4"}]}), 201)
    assert po["status"] == "received"
    assert po["payment_status"] == "paid"
    assert po["paid_amount"] == "36.48"
    assert by_wh(api, p["id"]) == {w2["id"]: 8}  # received where the order says, immediately on creation
    assert {r["warehouse_id"]: r["quantity"] for r in ok(api.get(f"/products/{p['id']}/stock"))} == {w2["id"]: 8}
    payments = ok(api.get("/payments?supplier_id=%d" % sup["id"]))
    assert len(payments) == 1 and payments[0]["amount"] == "36.48" and payments[0]["safe_id"] == safe["id"]
    line = ok(api.get(f"/purchase-orders/{po['id']}"))["items"][0]["id"]
    ok(api.post("/purchase-returns", json={"order_id": po["id"], "items": [{"order_item_id": line, "quantity": 3}]}), 201)
    assert by_wh(api, p["id"]) == {w2["id"]: 5}
    ok(api.post(f"/products/{p['id']}/adjust-stock", json={"reason_id": _reason_id(api), "change": 2, "warehouse_id": w1["id"]}))
    ok(api.post(f"/products/{p['id']}/adjust-stock", json={"reason_id": _reason_id(api), "change": -3}), 409)  # default is the product's warehouse (Main): only 2 there
    ok(api.post(f"/products/{p['id']}/adjust-stock", json={"reason_id": _reason_id(api), "change": -2, "warehouse_id": w2["id"]}))
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
    ok(api.post("/company/employees", json={"username": "clerk", "password": "clerk-password-123", "role": "staff", "warehouse_ids": [w2["id"]]}), 201)
    clerk_id = ok(api.get("/auth/users"))[0]["id"] if ok(api.get("/auth/users"))[0]["username"] == "clerk" else [u for u in ok(api.get("/auth/users")) if u["username"] == "clerk"][0]["id"]
    give_section(api, clerk_id, ["inventory.product.view", "inventory.product.stock", "inventory.transfer.view", "inventory.transfer.create"])
    tok = ok(api.post("/auth/login", data={"username": "clerk", "password": "clerk-password-123"}))["access_token"]
    staff = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    assert by_wh(staff, p["id"]) == {w2["id"]: 4}  # the Main warehouse row is not theirs to see
    assert len(ok(staff.get("/stock-transfers"))) == 1  # but the transfer into their warehouse is
    r = staff.post("/stock-transfers", json={"from_warehouse_id": w2["id"], "to_warehouse_id": w1["id"], "items": [{"product_id": p["id"], "quantity": 1}]})
    assert r.status_code == 422, r.text  # cannot send to a warehouse they have no access to
    assert by_wh(api, p["id"]) == {w1["id"]: 6, w2["id"]: 4}
    del me, branch
