"""POS and COGS ledger integration: every sale path posts a complete, balanced double-entry.

Covers the two accounting gaps that used to exist:
- POS checkout never posted to the ledger (no revenue, no COGS, no cash leg);
- Sales confirmation posted revenue but never relieved inventory (no COGS entry).
"""

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


# ---------------------------------------------------------------- shared builders
def make_branch(c, name="Main"):
    return ok(c.post("/company/branches", json={"name": name, "location": None}), 201)


def make_safe(c, name, branch_id):
    return ok(c.post("/safes", json={"name": name, "branch_id": branch_id}), 201)


def make_warehouse(c, name, code):
    return ok(c.post("/warehouses", json={"name": name, "code": code}), 201)


def make_product(c, name, cost, price, qty=0):
    return ok(c.post("/products", json={
        "sku": f"SKU-{name}", "name": name, "sale_price": price, "cost_price": cost, "quantity": qty,
    }), 201)


def make_customer(c, name):
    return ok(c.post("/customers", json={"name": name, "code": f"C-{name}"}), 201)


def make_supplier(c, name):
    return ok(c.post("/suppliers", json={"name": name, "code": f"S-{name}"}), 201)


def trial(c):
    return {row["code"]: row for row in ok(c.get("/reports/financial/trial-balance"))}


def entries(c):
    return ok(c.get("/journal-entries"))


def assert_every_entry_balances(jes):
    for je in jes:
        debit = sum(Decimal(str(i.get("debit") or 0)) for i in je["items"])
        credit = sum(Decimal(str(i.get("credit") or 0)) for i in je["items"])
        assert debit == credit and debit > 0, (je["description"], debit, credit)


def balance_of(trial_map, code):
    assert code in trial_map, f"account {code} missing from trial balance"
    return Decimal(str(trial_map[code]["balance"]))


# ---------------------------------------------------------------- POS ledger
def test_pos_cash_sale_posts_full_ledger(api):
    c = api
    branch = make_branch(c)
    safe = make_safe(c, "Main Safe", branch["id"])
    wh = make_warehouse(c, "Main", "W1")
    product = make_product(c, "P1", "30", "100", qty=10)

    receipt = ok(c.post("/pos/checkout", json={
        "warehouse_id": wh["id"],
        "items": [{"product_id": product["id"], "quantity": 1}],
        "safe_id": safe["id"],
        "method": "cash",
    }), 201)
    assert Decimal(str(receipt["total"])) == Decimal("100")
    assert receipt["payment_id"] is not None

    # The three expected journals, each internally balanced.
    jes = entries(c)
    descriptions = [je["description"] for je in jes]
    assert any(d.startswith("POS Sale SO-") for d in descriptions)
    assert any(d.startswith("COGS SO-") for d in descriptions)
    assert any(d.startswith("POS Receipt SO-") for d in descriptions)
    assert_every_entry_balances(jes)

    # Ledger effects: revenue 100, COGS 30, inventory relieved 30, cash in the safe 100, AR settled.
    t = trial(c)
    assert balance_of(t, "4101") == Decimal("100")   # sales revenue
    assert balance_of(t, "5100") == Decimal("30")    # COGS
    assert balance_of(t, "1101") == Decimal("-30")   # inventory relieved
    # link_safe_coa gives each safe its own child account under 1111 ("Safe: <name>").
    safe_rows = [row for row in t.values() if row["name"] == "Safe: Main Safe"]
    assert safe_rows, "safe cash account missing from trial balance"
    assert sum(Decimal(str(row["balance"])) for row in safe_rows) == Decimal("100")
    assert balance_of(t, "1120") == Decimal("0")     # walk-in customer paid in full

    # The P&L now shows the margin, not just the revenue.
    pl = ok(c.get("/reports/financial/profit-loss"))
    assert Decimal(str(pl["total_revenue"])) == Decimal("100")
    assert Decimal(str(pl["net_profit"])) == Decimal("70")

    # The voucher is a real receipt tied to the safe, and the safe moved.
    payments = ok(c.get("/payments", params={"safe_id": safe["id"]}))
    assert len(payments) == 1 and payments[0]["kind"] == "receipt"
    safes = {s["id"]: s for s in ok(c.get("/safes"))}
    assert Decimal(str(safes[safe["id"]]["balance"])) == Decimal("100")


def test_pos_credit_sale_posts_revenue_and_cogs_without_cash(api):
    c = api
    wh = make_warehouse(c, "Main", "W1")
    product = make_product(c, "P1", "30", "100", qty=5)
    customer = make_customer(c, "CT")

    receipt = ok(c.post("/pos/checkout", json={
        "warehouse_id": wh["id"],
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "quantity": 2}],
        "amount_paid": "0",
    }), 201)
    assert receipt["payment_id"] is None

    jes = entries(c)
    descriptions = [je["description"] for je in jes]
    assert any(d.startswith("POS Sale SO-") for d in descriptions)
    assert any(d.startswith("COGS SO-") for d in descriptions)
    assert not any(d.startswith("POS Receipt") for d in descriptions)
    assert_every_entry_balances(jes)

    t = trial(c)
    assert balance_of(t, "1120") == Decimal("200")   # customer owes the full total (leaf, not group 1100)
    assert balance_of(t, "5100") == Decimal("60")
    assert balance_of(t, "1101") == Decimal("-60")


def test_pos_checkout_rejects_foreign_or_missing_safe(api):
    c = api
    branch = make_branch(c)
    safe = make_safe(c, "Main Safe", branch["id"])
    wh = make_warehouse(c, "Main", "W1")
    product = make_product(c, "P1", "30", "100", qty=5)

    r = c.post("/pos/checkout", json={
        "warehouse_id": wh["id"],
        "items": [{"product_id": product["id"], "quantity": 1}],
        "safe_id": 999999,
    })
    assert r.status_code == 422, r.text
    # Nothing was saved: no order, no ledger rows.
    assert ok(c.get("/pos/invoices")) == []


# ---------------------------------------------------------------- full cycle: purchase → sale → return
def test_full_cycle_keeps_ledger_consistent(api):
    c = api
    wh = make_warehouse(c, "Main", "W1")
    product = make_product(c, "P1", "30", "100", qty=0)
    supplier = make_supplier(c, "SUP")
    customer = make_customer(c, "CT")

    # 1) Purchase 10 @ 30 on credit: inventory in, payable up.
    po = ok(c.post("/purchase-orders", json={
        "supplier_id": supplier["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": product["id"], "quantity": 10, "unit_cost": "30"}],
        "payment_mode": "credit", "tax_rate": "0",
    }), 201)
    assert po["status"] == "received"
    assert_every_entry_balances(entries(c))

    # 2) Sell 2 @ 100: revenue + COGS both posted.
    so = ok(c.post("/sales-orders", json={
        "customer_id": customer["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": product["id"], "quantity": 2}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)

    t = trial(c)
    assert balance_of(t, "1101") == Decimal("300") - Decimal("60")   # 10 in, 2 out at cost
    assert balance_of(t, "5100") == Decimal("60")
    assert balance_of(t, "4101") == Decimal("200")
    assert balance_of(t, "2110") == Decimal("300")   # payable for the purchase (leaf, not group 2100)
    assert balance_of(t, "1120") == Decimal("200")   # receivable for the sale (leaf 1120)
    assert_every_entry_balances(entries(c))

    # 3) Return 1 of the 2 sold units (no cash back): revenue and COGS both reversed.
    line_id = so["items"][0]["id"]
    ret = ok(c.post("/sales-returns", json={
        "order_id": so["id"],
        "items": [{"order_item_id": line_id, "quantity": 1}],
        "refund_amount": "0",
    }), 201)
    assert ret["total_amount"] == "100.00"

    jes = entries(c)
    descriptions = [je["description"] for je in jes]
    assert any(d.startswith("Sales Return SR-") for d in descriptions)
    assert any(d.startswith("COGS Reversal SR-") for d in descriptions)
    assert_every_entry_balances(jes)

    t = trial(c)
    assert balance_of(t, "4101") == Decimal("100")   # one sale stands
    assert balance_of(t, "5100") == Decimal("30")    # COGS relieved by half
    assert balance_of(t, "1101") == Decimal("300") - Decimal("60") + Decimal("30")  # goods back
    assert balance_of(t, "1120") == Decimal("100")   # customer owes for the remaining unit (leaf 1120)

    # The P&L reflects the true margin of the one remaining sale.
    pl = ok(c.get("/reports/financial/profit-loss"))
    assert Decimal(str(pl["total_revenue"])) == Decimal("100")
    assert Decimal(str(pl["net_profit"])) == Decimal("70")
