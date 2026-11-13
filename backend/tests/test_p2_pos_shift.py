"""المرحلة 2: بوابة POS_REQUIRE_SHIFT — الفواتير تتطلب وردية مفتوحة عند التفعيل،
والكاش يظهر في النقد المتوقع للوردية. الثغرة الموثقة في التقييم: بوابة بلا اختبارات."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.routers.pos as pos_module
from app.database import Base, get_db
from app.main import app
from tests.test_warehouse_stock import make_product, make_warehouses


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
    client.post("/auth/setup", json={"username": "pos-admin", "password": "strong-password-123"})
    token = client.post("/auth/login", data={"username": "pos-admin", "password": "strong-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    app.dependency_overrides.pop(get_db, None)


def _checkout(api, product_id, qty=2, price="50"):
    w = api.get("/warehouses").json()[0]["id"]
    return api.post("/pos/checkout", json={
        "warehouse_id": w,
        "items": [{"product_id": product_id, "quantity": qty, "unit_price": price}],
        "amount_paid": str(float(price) * qty),
        "tax_rate": "0",
        "method": "cash",
    })


def test_checkout_blocked_without_shift_when_gate_enabled(api, monkeypatch):
    try:
        w1, _ = make_warehouses(api)
        product = make_product(api, "P2A", 10, w1["id"])
        monkeypatch.setattr(pos_module, "REQUIRE_SHIFT", True)

        r = _checkout(api, product["id"])
        assert r.status_code == 409, r.text
        assert "shift" in r.json()["detail"].lower()

        # فتح وردية → البيع يمر
        opened = api.post("/shifts/open", json={"opening_cash": "100"})
        assert opened.status_code == 201, opened.text
        ok = _checkout(api, product["id"])
        assert ok.status_code == 201, ok.text

        # مبيعات الكاش ظهرت في النقد المتوقع للوردية (100 افتتاحي + 100 بيع)
        current = api.get("/shifts/current").json()
        assert float(current["cash_in"]) == 100.0
        assert float(current["expected_cash"]) == 200.0
    finally:
        monkeypatch.setattr(pos_module, "REQUIRE_SHIFT", False)


def test_checkout_without_gate_works_without_shift(api, monkeypatch):
    monkeypatch.setattr(pos_module, "REQUIRE_SHIFT", False)
    try:
        w1, _ = make_warehouses(api)
        product = make_product(api, "P2B", 10, w1["id"])
        r = _checkout(api, product["id"])
        assert r.status_code == 201, r.text
        # لا وردية مفتوحة
        assert api.get("/shifts/current").json() is None
    finally:
        monkeypatch.setattr(pos_module, "REQUIRE_SHIFT", False)


def test_gate_never_blocks_manager_when_disabled_by_default(api):
    """الافتراضي: POS_REQUIRE_SHIFT=false — لا وردية ولا حجب (سلوك محفوظ)."""
    w1, _ = make_warehouses(api)
    product = make_product(api, "P2C", 10, w1["id"])
    r = _checkout(api, product["id"])
    assert r.status_code == 201, r.text
