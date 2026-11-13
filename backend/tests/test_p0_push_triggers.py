"""المرحلة 0: مشغلات إشعارات المندوبين — تأكيد الأوردر (قائم)، المرتجع، والتحصيل (جديدان).
وضع Pull: بدون FCM يُسجَّل الصندوق فقط ويمكن قراءته من /reps/me/notifications."""
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
    client.post("/auth/setup", json={"username": "push-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "push-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def _make_rep_with_customer(client):
    rep = client.post("/reps", json={"name": "مندوب الإشعارات", "code": "R-N1", "commission_percent": "5"}).json()
    assert rep.get("id"), rep
    customer = client.post("/customers", json={"name": "عميل الإشعارات"}).json()
    return rep, customer


def test_push_triggers_on_confirm_return_and_collection():
    client, engine = _client()
    try:
        w1, _ = make_warehouses(client)
        product = make_product(client, "PU1", 50, w1["id"])
        rep, customer = _make_rep_with_customer(client)

        # أوردر بمندوب → تأكيد → إشعار order_confirmed
        order = client.post("/sales-orders", json={
            "customer_id": customer["id"], "warehouse_id": w1["id"], "rep_id": rep["id"],
            "items": [{"product_id": product["id"], "quantity": 3, "unit_price": "100"}],
        })
        assert order.status_code == 201, order.text
        confirmed = client.post(f"/sales-orders/{order.json()['id']}/confirm")
        assert confirmed.status_code == 200, confirmed.text

        notifs = client.get(f"/reps/{rep['id']}/notifications").json() if client.get(f"/reps/{rep['id']}/notifications").status_code == 200 else None
        if notifs is None:
            # المسار الإداري غير متاح؟ نقرأ عبر /reps (لا يوجد inbox إداري) — نتحقق عبر قاعدة بيانات الاختبار نفسها لاحقًا
            notifs = []
        kinds = [n["kind"] for n in (notifs or [])]

        # مرتجع منسوب للمندوب → return_recorded (سطر مرتبط ببند الأوردر)
        order_detail = client.get(f"/sales-orders/{order.json()['id']}").json()
        order_item_id = order_detail["items"][0]["id"]
        ret = client.post("/sales-returns", json={
            "order_id": order.json()["id"],
            "items": [{"order_item_id": order_item_id, "product_id": product["id"], "quantity": 1}],
            "refund_amount": "0",
        })
        assert ret.status_code == 201, ret.text

        # تحصيل من العميل → payment_collected
        pay = client.post("/payments", json={
            "customer_id": customer["id"], "amount": "150", "method": "cash",
        })
        assert pay.status_code == 201, pay.text

        # التحقق النهائي من الصندوق عبر طبقة البيانات مباشرة (المسار الإداري للقراءة قد لا يعرض الكل)
        from sqlalchemy import select
        with engine.connect() as conn:
            rows = conn.execute(
                select(__import__("app.models", fromlist=["RepNotification"]).RepNotification.kind)
            ).fetchall()
        kinds_all = [r[0] for r in rows]
        assert "order_confirmed" in kinds_all, kinds_all
        assert "return_recorded" in kinds_all, kinds_all
        assert "payment_collected" in kinds_all, kinds_all
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_collection_without_rep_creates_no_notification():
    client, engine = _client()
    try:
        customer = client.post("/customers", json={"name": "عميل بلا مندوب"}).json()
        pay = client.post("/payments", json={"customer_id": customer["id"], "amount": "50", "method": "cash"})
        assert pay.status_code == 201, pay.text
        from sqlalchemy import select, func
        import app.models as m
        with engine.connect() as conn:
            n = conn.execute(select(func.count()).select_from(m.RepNotification)).scalar()
        assert n == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
