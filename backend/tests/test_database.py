import pytest

from app.database import _pool_int_setting


def test_pool_int_setting_reads_configured_value(monkeypatch):
    monkeypatch.setenv("DATABASE_POOL_SIZE", "24")

    assert _pool_int_setting("DATABASE_POOL_SIZE", 5, 1) == 24


@pytest.mark.parametrize("raw_value", ["zero", "0", "-3"])
def test_pool_int_setting_rejects_invalid_or_too_small_values(monkeypatch, raw_value):
    monkeypatch.setenv("DATABASE_POOL_SIZE", raw_value)

    with pytest.raises(ValueError, match="DATABASE_POOL_SIZE"):
        _pool_int_setting("DATABASE_POOL_SIZE", 5, 1)


def test_pool_int_setting_allows_zero_when_configured_minimum_is_zero(monkeypatch):
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "0")

    assert _pool_int_setting("DATABASE_MAX_OVERFLOW", 10, 0) == 0
