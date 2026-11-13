"""اختبارات الاستلام اليدوي للوطات: الاستلام حركة مخزنية كاملة عبر move_stock —
دفتر اللوطات لا ينحرف عن المخزون، واللوط اليدوي قابل للاستهلاك FEFO كغيره."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from tests.test_warehouse_stock import make_product, make_warehouses


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    client.post("/auth/setup", json={"username": "lot-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "lot-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def _stock_rows(client, product_id):
    product = client.get(f"/products/{product_id}").json()
    movements = client.get(f"/products/{product_id}/movements").json()
    return product, movements


def test_manual_lot_receive_updates_stock_ledger():
    client, engine = _client()
    try:
        w1, _ = make_warehouses(client)
        product = make_product(client, "LOT1", 0, w1["id"])

        # استلام لوط يدوي 10 وحدات
        received = client.post("/lots", json={
            "product_id": product["id"], "warehouse_id": w1["id"],
            "lot_code": "MAN-01", "qty": 10,
        })
        assert received.status_code == 201, received.text

        # رصيد المنتج والمخزن ارتفع فعلاً (وليس اللوط وحده)
        refreshed = client.get(f"/products/{product['id']}").json()
        assert float(refreshed["quantity"]) == 10.0

        # الحركة مسجلة في دفتر الحركة
        movements = client.get(f"/products/{product['id']}/movements").json()
        lot_moves = [m for m in movements if m.get("reason") == "lot-receive"]
        assert len(lot_moves) == 1 and float(lot_moves[0]["change"]) == 10.0

        # استلام إضافي على نفس الكود يزيد الاثنين معاً
        again = client.post("/lots", json={
            "product_id": product["id"], "warehouse_id": w1["id"],
            "lot_code": "MAN-01", "qty": 5,
        })
        assert again.status_code == 201, again.text
        assert float(again.json()["qty_remaining"]) == 15.0
        refreshed = client.get(f"/products/{product['id']}").json()
        assert float(refreshed["quantity"]) == 15.0

        # بلا مخزن → 422 (الصرف من اللوطات مقيّد بمخزن)
        missing = client.post("/lots", json={
            "product_id": product["id"], "lot_code": "NO-WH", "qty": 1,
        })
        assert missing.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_manual_lot_is_consumable_fefo_on_sale():
    client, engine = _client()
    try:
        w1, _ = make_warehouses(client)
        customer = client.post("/customers", json={"name": "عميل لوطات"}).json()
        product = make_product(client, "LOT2", 0, w1["id"], sale_price="100", cost_price="50")

        received = client.post("/lots", json={
            "product_id": product["id"], "warehouse_id": w1["id"],
            "lot_code": "CONSUME-01", "qty": 10,
        })
        assert received.status_code == 201, received.text

        # بيع 4 وحدات من المخزن نفسه → الاوط يُخصم FEFO
        order = client.post("/sales-orders", json={
            "customer_id": customer["id"], "warehouse_id": w1["id"],
            "items": [{"product_id": product["id"], "quantity": 4, "unit_price": "100"}],
        })
        assert order.status_code == 201, order.text
        confirmed = client.post(f"/sales-orders/{order.json()['id']}/confirm")
        assert confirmed.status_code == 200, confirmed.text

        lots = client.get(f"/lots?product_id={product['id']}").json()
        assert len(lots) == 1 and float(lots[0]["qty_remaining"]) == 6.0

        refreshed = client.get(f"/products/{product['id']}").json()
        assert float(refreshed["quantity"]) == 6.0
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
