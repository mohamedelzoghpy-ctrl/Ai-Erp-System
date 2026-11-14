"""المرحلة 1: مزامنة تطبيق المندوبين — سحب دلتا + دفع أوردرات مجمعة idempotent.

دقة الثانية في SQLite (راجع docstring test_shifts): ننتظر ثانية قبل تعديل
السعر لضمان تقدم updated_at عن ركيزة المزامنة — على Postgres الإنتاجي بلا حاجة."""
from time import sleep

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
    client.post("/auth/setup", json={"username": "sync-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "sync-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_bootstrap_returns_products_customers_and_price_lists():
    client, engine = _client()
    try:
        w1, _ = make_warehouses(client)
        product = make_product(client, "SY1", 10, w1["id"], sale_price="25")
        customer = client.post("/customers", json={"name": "عميل مزامنة"}).json()
        pl = client.post("/price-lists", json={"name": "قائمة الجملة", "items": [
            {"product_id": product["id"], "unit_price": "22"},
        ]}).json()
        assert pl["id"], pl

        boot = client.get("/sync/bootstrap").json()
        assert boot["server_time"]
        assert any(p["id"] == product["id"] and float(p["sale_price"]) == 25.0 for p in boot["products"])
        assert any(c["id"] == customer["id"] for c in boot["customers"])
        assert any(pl_["id"] == pl["id"] and float(pl_["items"][0]["unit_price"]) == 22.0 for pl_ in boot["price_lists"])
        # التكلفة الحساسة لا تُسرب في المزامنة
        assert all("cost_price" not in p for p in boot["products"])

        # متاح المخزن الافتراضي يُرسل كاملًا مع كل مزامنة (المندوب أوفلاين يرى الكميات)
        stock_map = {s["product_id"]: s["quantity"] for s in boot["stock"]}
        assert stock_map.get(product["id"]) == 10.0

        # دلتا: since الآن → لا شيء جديد
        cursor = boot["server_time"]
        boot2 = client.get("/sync/bootstrap", params={"since": cursor}).json()
        assert boot2["products"] == [] and boot2["customers"] == []
        # لكن الكميات تظل كاملة حتى في الدلتا (المخزون يتغير بأي قناة)
        assert {s["product_id"]: s["quantity"] for s in boot2["stock"]}.get(product["id"]) == 10.0

        # خصم مخزوني 4 وحدات → يظهر في الكميات القادمة فورًا (بلا اعتبار للدلتا)
        reasons = client.get("/products/adjustment-reasons").json()
        reason_id = reasons[0]["id"] if reasons else client.post(
            "/products/adjustment-reasons", json={"name": "تسوية اختبار المزامنة"}
        ).json()["id"]
        client.post(f"/products/{product['id']}/adjust-stock", json={
            "reason_id": reason_id, "change": -4, "warehouse_id": w1["id"],
        })
        boot_adj = client.get("/sync/bootstrap", params={"since": cursor}).json()
        assert {s["product_id"]: s["quantity"] for s in boot_adj["stock"]}.get(product["id"]) == 6.0

        # تعديل سعر المنتج → يظهر في الدلتا القادمة
        sleep(1.1)  # تجاوز دقة الثانية في SQLite
        client.patch(f"/products/{product['id']}", json={"sale_price": "30"})
        boot3 = client.get("/sync/bootstrap", params={"since": cursor}).json()
        changed = [p for p in boot3["products"] if p["id"] == product["id"]]
        assert changed and float(changed[0]["sale_price"]) == 30.0
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_push_orders_creates_drafts_idempotently():
    client, engine = _client()
    try:
        w1, _ = make_warehouses(client)
        product = make_product(client, "SY2", 50, w1["id"])
        customer = client.post("/customers", json={"name": "عميل أوفلاين"}).json()

        batch = {"orders": [{
            "client_ref": "offline-abc-0001",
            "customer_id": customer["id"], "warehouse_id": w1["id"],
            "notes": "أوردر من الميدان",
            "items": [{"product_id": product["id"], "quantity": 3, "unit_price": 25}],
        }]}
        r1 = client.post("/sync/orders", json=batch)
        assert r1.status_code == 200, r1.text
        res1 = r1.json()["results"][0]
        assert res1["status"] == "created" and res1["order_id"]

        # الأوردر مسودة بأصله الرسمي (قوائم/تجميع) ويحمل client_ref
        detail = client.get(f"/sales-orders/{res1['order_id']}").json()
        assert detail["status"] == "draft"
        assert float(detail["total_amount"]) == 75.0

        # إعادة المحاولة (نفس الشبكة تكررت) → duplicate بنفس الأوردر بلا تكرار
        r2 = client.post("/sync/orders", json=batch)
        res2 = r2.json()["results"][0]
        assert res2["status"] == "duplicate" and res2["order_id"] == res1["order_id"]

        # دفعة فيها عنصر صحيح وعنصر فاشل (عميل غير موجود) → الفاشل لا يُسقط الصحيح
        mixed = {"orders": [
            {"client_ref": "offline-ok-0002", "customer_id": customer["id"], "warehouse_id": w1["id"],
             "items": [{"product_id": product["id"], "quantity": 1}]},
            {"client_ref": "offline-bad-0003", "customer_id": 999999, "warehouse_id": w1["id"],
             "items": [{"product_id": product["id"], "quantity": 1}]},
        ]}
        r3 = client.post("/sync/orders", json=mixed).json()["results"]
        by_ref = {r["client_ref"]: r for r in r3}
        assert by_ref["offline-ok-0002"]["status"] == "created"
        assert by_ref["offline-bad-0003"]["status"] == "failed" and by_ref["offline-bad-0003"]["error"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
