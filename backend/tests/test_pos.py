from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import models
from app.routers.pos import _load_checkout_products


class FakeQuery:
    def __init__(self, products):
        self.products = products

    def filter(self, _criterion):
        return self

    def all(self):
        return self.products


class FakeSession:
    def __init__(self, products):
        self.products = products
        self.query_models = []

    def query(self, model):
        self.query_models.append(model)
        return FakeQuery(self.products)


def make_item(product_id):
    return SimpleNamespace(product_id=product_id)


def test_checkout_products_are_loaded_in_one_query_and_duplicate_ids_are_deduplicated():
    products = [
        SimpleNamespace(id=7, name="Product 7"),
        SimpleNamespace(id=2, name="Product 2"),
    ]
    db = FakeSession(products)

    result = _load_checkout_products(db, [make_item(7), make_item(2), make_item(7)])

    assert db.query_models == [models.Product]
    assert result == {2: products[1], 7: products[0]}


def test_checkout_products_report_first_missing_product():
    db = FakeSession([SimpleNamespace(id=2)])

    with pytest.raises(HTTPException) as exc_info:
        _load_checkout_products(db, [make_item(7), make_item(9)])

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Product 7 does not exist"
    assert db.query_models == [models.Product]


def test_checkout_without_product_lines_does_not_query_database():
    db = FakeSession([])

    assert _load_checkout_products(db, []) == {}
    assert db.query_models == []
