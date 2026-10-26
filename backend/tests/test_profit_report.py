"""Profit report and per-warehouse inventory valuation (in-memory SQLite, through the API)."""

from decimal import Decimal

from tests.test_warehouse_stock import api, by_wh, make_product, make_warehouses, ok  # noqa: F401


def sell(c, pid, wid, qty, price="10"):
    cust = ok(c.post("/customers", json={"name": "C"}), 201)
    order = ok(c.post("/sales-orders", json={"customer_id": cust["id"], "warehouse_id": wid, "items": [{"product_id": pid, "quantity": qty, "unit_price": price}]}), 201)
    ok(c.post(f"/sales-orders/{order['id']}/confirm"))
    return order


def test_profit_uses_cost_at_time_of_sale_and_nets_returns(api):
    w1, w2 = make_warehouses(api)
    p = make_product(api, "A", 20, w1["id"])  # cost 5, price 10
    order = sell(api, p["id"], w1["id"], 4)  # revenue 40, cost 20
    ok(api.patch(f"/products/{p['id']}", json={"cost_price": "8"}))  # later cost edit must not rewrite history
    sell(api, p["id"], w1["id"], 1)  # revenue 10, cost 8

    r = ok(api.get("/reports/profit"))
    assert (Decimal(r["sales"]), Decimal(r["cost"]), Decimal(r["profit"])) == (Decimal("50"), Decimal("28"), Decimal("22"))

    item = ok(api.get(f"/sales-orders/{order['id']}"))["items"][0]
    ok(api.post("/sales-returns", json={"order_id": order["id"], "items": [{"order_item_id": item["id"], "quantity": 1}]}), 201)
    r = ok(api.get("/reports/profit"))
    assert Decimal(r["returns"]) == Decimal("10")
    assert (Decimal(r["revenue"]), Decimal(r["cost"]), Decimal(r["profit"])) == (Decimal("40"), Decimal("23"), Decimal("17"))
    row = r["by_product"][0]
    assert row["sku"] == "A" and row["quantity"] == 4 and Decimal(row["margin_pct"]) == Decimal("42.5")
    assert api.get("/reports/profit/xlsx").status_code == 200


def test_profit_empty_period_and_bad_range(api):
    r = ok(api.get("/reports/profit"))
    assert r["by_product"] == [] and r["margin_pct"] is None
    assert api.get("/reports/profit?date_from=2026-02-01&date_to=2026-01-01").status_code == 422


def test_valuation_follows_the_stock_in_each_warehouse(api):
    w1, w2 = make_warehouses(api)
    p = make_product(api, "A", 10, w1["id"])
    ok(api.post("/stock-transfers", json={"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"], "items": [{"product_id": p["id"], "quantity": 4}]}), 201)
    rows = {r["warehouse_id"]: r for r in ok(api.get("/reports/inventory-valuation"))}
    assert rows[w1["id"]]["units"] == 6 and Decimal(rows[w1["id"]]["cost_value"]) == Decimal("30")
    assert rows[w2["id"]]["units"] == 4 and Decimal(rows[w2["id"]]["sale_value"]) == Decimal("40")
    assert api.get("/reports/inventory-valuation/xlsx").status_code == 200
