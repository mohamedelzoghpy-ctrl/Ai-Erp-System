"""المرحلة 1: تحصيلات المندوب من التطبيق — سند قبض رسمي عبر مسار السندات الكامل."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models as m
from app.database import Base, get_db
from app.main import app


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
    client.post("/auth/setup", json={"username": "col-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "col-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def _linked_rep_client(client, engine):
    """مندوب مربوط بحساب دخول — يعيد TestClient بجلسة المندوب."""
    rep = client.post("/reps", json={"name": "مندوب التحصيل", "code": "R-C1", "commission_percent": "5"}).json()
    link = client.put(f"/reps/{rep['id']}/link-user", json={
        "username": "rep-collector", "password": "rep-pass-1234",
    })
    assert link.status_code == 200, link.text
    login = client.post("/auth/login", data={"username": "rep-collector", "password": "rep-pass-1234"})
    assert login.status_code == 200, login.text
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    return c, rep


def test_rep_collection_creates_real_payment_and_notification():
    client, engine = _client()
    try:
        branch = client.post("/company/branches", json={"name": "فرع التحصيل"}).json()
        safe = client.post("/safes", json={"name": "خزينة المندوب", "opening_balance": "0", "branch_id": branch["id"]}).json()
        client.post("/warehouses", json={"name": "مخزن التحصيل", "code": "WC1"})
        customer = client.post("/customers", json={"name": "عميل تحصيل ميداني"}).json()

        rep_client, rep = _linked_rep_client(client, engine)

        # تحصيل بلا خزينة محددة → الافتراضي أول خزينة نشطة
        r = rep_client.post("/reps/me/collections", json={
            "customer_id": customer["id"], "amount": "250", "notes": "قشش جمعته من العميل",
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["safe_id"] == safe["id"]
        assert float(body["amount"]) == 250.0

        # سند قبض حقيقي posted بالشركة
        with engine.connect() as conn:
            row = conn.execute(
                select(m.Payment.kind, m.Payment.method, m.Payment.status, m.Payment.safe_id)
                .where(m.Payment.id == body["payment_id"])
            ).first()
        assert row == ("receipt", "cash", "posted", safe["id"])

        # إشعار التحصيل وصل صندوق المندوب (مشغل P0.6 عبر مسار السندات)
        with engine.connect() as conn:
            kinds = [k for (k,) in conn.execute(select(m.RepNotification.kind)).fetchall()]
        assert "collection_recorded" in kinds

        # عميل غير موجود → 404 ولا سند
        bad = rep_client.post("/reps/me/collections", json={"customer_id": 999999, "amount": "10"})
        assert bad.status_code == 404

        # التسوية البنكية للسند عبر bootstrap: default_warehouse_id موجود
        boot = rep_client.get("/sync/bootstrap").json()
        assert boot["default_warehouse_id"] is not None
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_rep_without_link_is_blocked():
    client, engine = _client()
    try:
        customer = client.post("/customers", json={"name": "عميل عادي"}).json()
        r = client.post("/reps/me/collections", json={"customer_id": customer["id"], "amount": "10"})
        # المدير ليس مندوباً مرتبطاً → 403 من _rep_for_user
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
