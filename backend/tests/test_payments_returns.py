"""Payments + returns accounting flows and lifecycle race guards, end to end through the API."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from tests.test_warehouse_stock import make_warehouses, make_product


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


def make_staff_with_branch(client, branch_id: int, username: str, warehouse_id=None):
    payload = {
        "username": username,
        "password": "long-password-123",
        "role": "staff",
        "branch_ids": [branch_id],
        "warehouse_ids": [warehouse_id] if warehouse_id else [],
    }
    r = client.post("/auth/users", json=payload)
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]
    # نظام الصلاحيات: منح الموظف صلاحيات السندات لاختبار نطاق الفروع
    sec = client.post("/access-sections", json={"code": f"t{user_id}", "name": "قسم اختبار"}).json()
    client.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": ["accounting.payment.view", "accounting.payment.create"]})
    client.put(f"/auth/users/{user_id}/section", json={"section_id": sec["id"]})
    token = client.post("/auth/login", data={"username": username, "password": "long-password-123"}).json()["access_token"]
    staff = TestClient(app)
    staff.headers["Authorization"] = f"Bearer {token}"
    return staff


def test_customer_receipt_without_safe_is_recorded_and_listed(api):
    customer = api.post("/customers", json={"name": "C1"}).json()
    r = api.post("/payments", json={"customer_id": customer["id"], "amount": "50", "method": "cash"})
    assert r.status_code == 201, r.text
    rows = api.get("/payments").json()
    assert [p["customer_id"] for p in rows] == [customer["id"]]
    assert rows[0]["kind"] == "receipt" and rows[0]["status"] == "posted"


def test_partyless_voucher_requires_category_and_cash_location(api):
    assert api.post("/payments", json={"amount": "10"}).status_code == 422
    cat = api.post("/payment-categories", json={"name": "rent", "kind": "payment", "requires_party": False}).json()
    r = api.post("/payments", json={"category_id": cat["id"], "amount": "10"})
    assert r.status_code == 422, r.text  # still needs a safe or bank to hold the money


def branch_id(client, name: str) -> int:
    r = client.post("/company/branches", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_voiding_a_payment_reverses_balance_once(api):
    branch = branch_id(api, "B1")
    safe = api.post("/safes", json={"name": "Main drawer", "branch_id": branch}).json()
    supplier = api.post("/suppliers", json={"name": "S1"}).json()
    p = api.post("/payments", json={"supplier_id": supplier["id"], "safe_id": safe["id"], "amount": "100"}).json()
    balance_before = api.get(f"/safes/{safe['id']}").json()["balance"]
    assert balance_before == "-100.00" or balance_before == -100
    assert api.post(f"/payments/{p['id']}/void").status_code == 200
    row = [x for x in api.get("/payments").json() if x["id"] == p["id"]][0]
    assert row["status"] == "voided"
    balance_after = api.get(f"/safes/{safe['id']}").json()["balance"]
    assert balance_after in ("0.00", 0, "0")


def test_staff_cannot_void_a_payment(api):
    branch = branch_id(api, "B1")
    staff = make_staff_with_branch(api, branch, "clerk")
    r = staff.post("/payments/1/void")
    assert r.status_code == 403, r.text


def test_staff_sees_own_branch_vouchers_not_others(api):
    b1, b2 = branch_id(api, "B1"), branch_id(api, "B2")
    safe1 = api.post("/safes", json={"name": "B1 drawer", "branch_id": b1}).json()
    safe2 = api.post("/safes", json={"name": "B2 drawer", "branch_id": b2}).json()
    c1 = api.post("/customers", json={"name": "C-b1"}).json()
    c2 = api.post("/customers", json={"name": "C-b2"}).json()

    staff = make_staff_with_branch(api, b1, "clerk")
    own = staff.post("/payments", json={"customer_id": c1["id"], "safe_id": safe1["id"], "amount": "30"}).json()
    assert own["id"] >= 1
    theirs = api.post("/payments", json={"customer_id": c2["id"], "safe_id": safe2["id"], "amount": "70"}).json()

    ids = [p["id"] for p in staff.get("/payments").json()]
    assert own["id"] in ids       # vouchers the staff member recorded
    assert theirs["id"] not in ids  # other branches' money is manager-only

    manager_ids = [p["id"] for p in api.get("/payments").json()]
    assert own["id"] in manager_ids and theirs["id"] in manager_ids


def test_confirm_then_reconfirm_is_rejected(api):
    warehouse, _ = make_warehouses(api)
    product = make_product(api, "RACE", 5, warehouse["id"])
    customer = api.post("/customers", json={"name": "C"}).json()
    order = api.post(
        "/sales-orders",
        json={"customer_id": customer["id"], "warehouse_id": warehouse["id"], "items": [{"product_id": product["id"], "quantity": 1, "unit_price": "10"}]},
    ).json()
    assert api.post(f"/sales-orders/{order['id']}/confirm").status_code == 200
    assert api.post(f"/sales-orders/{order['id']}/confirm").status_code == 409
    # the stock was deducted exactly once
    assert api.get(f"/products/{product['id']}").json()["quantity"] == 4
    # a confirmed order cannot be cancelled either
    assert api.post(f"/sales-orders/{order['id']}/cancel").status_code == 409


def test_sales_return_restores_stock(api):
    warehouse, _ = make_warehouses(api)
    product = make_product(api, "RET", 10, warehouse["id"])
    customer = api.post("/customers", json={"name": "C"}).json()
    order = api.post(
        "/sales-orders",
        json={"customer_id": customer["id"], "warehouse_id": warehouse["id"], "items": [{"product_id": product["id"], "quantity": 3, "unit_price": "10"}]},
    ).json()
    assert api.post(f"/sales-orders/{order['id']}/confirm").status_code == 200
    assert api.get(f"/products/{product['id']}").json()["quantity"] == 7

    item = order["items"][0]
    r = api.post("/sales-returns", json={"order_id": order["id"], "items": [{"order_item_id": item["id"], "quantity": 1}], "refund_amount": "0"})
    assert r.status_code == 201, r.text
    assert api.get(f"/products/{product['id']}").json()["quantity"] == 8


def test_purchase_order_ships_received_and_cannot_flip_states(api):
    warehouse, _ = make_warehouses(api)
    supplier = api.post("/suppliers", json={"name": "S"}).json()
    product = make_product(api, "PO-DUP", 0, warehouse["id"])
    po = api.post(
        "/purchase-orders",
        json={"supplier_id": supplier["id"], "warehouse_id": warehouse["id"], "items": [{"product_id": product["id"], "quantity": 2, "unit_cost": "5"}], "payment_mode": "credit"},
    )
    assert po.status_code == 201, po.text
    po = po.json()
    assert po["status"] == "received"  # stock lands at creation time
    assert api.get(f"/products/{product['id']}").json()["quantity"] == 2
    # a received order cannot be received again or cancelled afterwards
    assert api.post(f"/purchase-orders/{po['id']}/receive").status_code == 409
    assert api.post(f"/purchase-orders/{po['id']}/cancel").status_code == 409
