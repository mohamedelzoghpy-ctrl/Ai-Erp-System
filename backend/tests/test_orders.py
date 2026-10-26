from types import SimpleNamespace

import pytest
from fastapi import status

from app import models
from app.routers import orders


class FakeSession:
    def __init__(self, stock=None):
        self.added = []
        self.rolled_back = False
        self.stock = stock if stock is not None else {}  # {(product_id, warehouse_id): ProductStock-like}

    def get(self, model, key):
        return self.stock.get(key) if model is models.ProductStock else None

    def add(self, item):
        self.added.append(item)

    def rollback(self):
        self.rolled_back = True


def make_item(product_id, quantity):
    return SimpleNamespace(product_id=product_id, quantity=quantity)


def test_apply_sale_stock_aggregates_duplicate_lines_and_locks_in_order(monkeypatch):
    products = {
        2: SimpleNamespace(id=2, name="Product 2", quantity=6),
        7: SimpleNamespace(id=7, name="Product 7", quantity=10),
    }
    locked_ids = []

    def lock_product(_db, product_id):
        locked_ids.append(product_id)
        return products[product_id]

    monkeypatch.setattr(orders, "_locked_product", lock_product)
    db = FakeSession({(2, 3): SimpleNamespace(quantity=6), (7, 3): SimpleNamespace(quantity=10)})
    order = SimpleNamespace(
        id=42,
        warehouse_id=3,
        items=[make_item(7, 2), make_item(2, 1), make_item(7, 3)],
    )

    orders.apply_sale_stock(db, order)

    assert locked_ids == [2, 7]
    assert products[2].quantity == 5
    assert products[7].quantity == 5
    assert db.stock[(2, 3)].quantity == 5 and db.stock[(7, 3)].quantity == 5  # the warehouse's own quantity moves too
    movements = [item for item in db.added if isinstance(item, models.StockMovement)]
    assert {(item.product_id, item.change, item.reason, item.reference) for item in movements} == {
        (2, -1, "sale", "SO-42"),
        (7, -5, "sale", "SO-42"),
    }
    assert not db.rolled_back


def test_apply_sale_stock_rolls_back_without_deducting_any_stock_on_shortage(monkeypatch):
    products = {
        2: SimpleNamespace(id=2, name="Product 2", quantity=6),
        7: SimpleNamespace(id=7, name="Product 7", quantity=4),
    }
    monkeypatch.setattr(orders, "_locked_product", lambda _db, product_id: products[product_id])
    db = FakeSession({(2, 3): SimpleNamespace(quantity=6), (7, 3): SimpleNamespace(quantity=4)})
    order = SimpleNamespace(
        id=43,
        warehouse_id=3,
        items=[make_item(7, 5), make_item(2, 1)],
    )

    with pytest.raises(orders.HTTPException) as exc_info:
        orders.apply_sale_stock(db, order)

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "need 5, have 4" in exc_info.value.detail
    assert products[2].quantity == 6
    assert products[7].quantity == 4
    assert db.stock[(2, 3)].quantity == 6 and db.stock[(7, 3)].quantity == 4
    assert db.rolled_back
    assert db.added == []
