"""The 0012 migration spreads each product's quantity over warehouses using the movement history."""

import importlib.util
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0012_warehouse_stock.py"
_spec = importlib.util.spec_from_file_location("migration_0012", _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
distribute = _mod.distribute


@pytest.mark.parametrize(
    "quantity, sums, home, expected",
    [
        (10, {1: 10}, 1, {1: 10}),
        (10, {1: 6, 2: 4}, 1, {1: 6, 2: 4}),                      # history says it all
        (10, {}, 3, {3: 10}),                                        # no history: the product's own warehouse
        (10, {1: 4}, 3, {1: 4, 3: 6}),                               # history explains part, the rest goes home
        (10, {1: 15, 2: -5}, 1, {1: 10}),                            # sold from 2 what was received in 1: netted
        (5, {1: 8}, 1, {1: 5}),                                      # history overstates: trimmed to the real total
        (7, {None: 7}, 2, {2: 7}),                                   # movement without a warehouse: home
        (0, {1: 3}, 1, {}),                                          # nothing in stock, nothing to place
    ],
)
def test_distribute(quantity, sums, home, expected):
    assert distribute(quantity, sums, home) == expected


def test_distribute_always_adds_up_and_never_goes_negative():
    import random

    rng = random.Random(7)
    for _ in range(500):
        quantity = rng.randint(0, 50)
        sums = {rng.choice([None, 1, 2, 3]): rng.randint(-30, 40) for _ in range(rng.randint(0, 4))}
        result = distribute(quantity, sums, 1)
        assert sum(result.values()) == quantity, (quantity, sums, result)
        assert all(v > 0 for v in result.values())
