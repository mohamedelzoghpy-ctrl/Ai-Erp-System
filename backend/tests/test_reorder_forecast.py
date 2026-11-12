"""اختبارات محرك التنبؤ الذكي بحد الطلب ونقاط إعادة التموين (ROP Forecast):
1. حساب سرعة السحب اليومي الفعلي من أوامر البيع المؤكدة.
2. حساب مخزون الأمان (Safety Stock) ونقطة الطلب الديناميكية ROP.
3. تصنيف الأصناف حسب درجة الخطورة وحساب الأيام المتبقية لنفاد الرصيد.
"""
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
    client.post("/auth/setup", json={"username": "rop-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "rop-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_reorder_forecast_math_and_urgency():
    client, engine = _client()
    try:
        w1, _ = make_warehouses(client)
        # صنف 1: رصيد 50 وحدة بتكلفة 10 جنيه
        p1 = make_product(client, "ITEM-1", 50, w1["id"], cost_price="10.00")
        # صنف 2: رصيد 20 وحدة بتكلفة 20 جنيه
        p2 = make_product(client, "ITEM-2", 20, w1["id"], cost_price="20.00")

        cust = client.post("/customers", json={"name": "عميل تجريبي"}).json()

        # إنشاء وتأكيد أمر بيع: بيع 30 وحدة من الصنف 1، و 18 وحدة من الصنف 2
        so = client.post(
            "/sales-orders",
            json={
                "customer_id": cust["id"],
                "warehouse_id": w1["id"],
                "items": [
                    {"product_id": p1["id"], "quantity": 30, "unit_price": "20"},
                    {"product_id": p2["id"], "quantity": 18, "unit_price": "40"},
                ],
            },
        ).json()
        conf = client.post(f"/sales-orders/{so['id']}/confirm")
        assert conf.status_code == 200, conf.text

        # طلب تقرير التنبؤ الذكي لفترة 30 يوماً وزمن توريد 7 أيام وأمان 3 أيام
        resp = client.get("/reports/reorder-forecast?days_analyzed=30&default_lead_time=7&safety_days=3")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["days_analyzed"] == 30
        assert data["total_items_analyzed"] == 2

        it1 = next(i for i in data["items"] if i["product_id"] == p1["id"])
        # بيع 30 وحدة / 30 يوم = 1.0 وحدة يومياً
        assert it1["daily_sales"] == 1.0
        # مخزون الأمان = 1.0 × 3 = 3.0
        assert it1["safety_stock"] == 3.0
        # نقطة الطلب ROP = (1.0 × 7) + 3.0 = 10.0
        assert it1["suggested_rop"] == 10.0
        # الرصيد المتبقي = 50 - 30 = 20 وحدة (أعلى من ROP 10.0) ⇒ healthy
        assert it1["current_stock"] == 20.0
        assert it1["reorder_urgency"] == "healthy"

        it2 = next(i for i in data["items"] if i["product_id"] == p2["id"])
        # الرصيد المتبقي 20 - 18 = 2 وحدة فقط، ومعدل السحب 18/30 = 0.6، والأمان 1.8، وROP = 6.0
        # الرصيد (2.0) أقل من ROP (6.0) ⇒ critical أو warning
        assert it2["current_stock"] == 2.0
        assert it2["reorder_urgency"] in ("critical", "warning")
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
