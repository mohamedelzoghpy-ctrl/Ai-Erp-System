"""المرحلة 0: تشفير أسرار ETA في السكون — بضبط ETA_ENC_KEY تُخزَّن الأسرار مشفرة
(enc:v1:) وتُفك شفافياً عند الاستخدام، والقناع يعرض آخر 4 محارف من القيمة الحقيقية.
بدون المفتاح يعمل النظام بالنص الصريح كما كان (توافق)."""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def encrypted_client(monkeypatch):
    monkeypatch.setenv("ETA_ENC_KEY", "cDAtZXRhLWVuY3J5cHRpb24tdGVzdC1rZXktMzJiISE=")  # 32 بايت base64
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
    client.post("/auth/setup", json={"username": "eta-enc", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "eta-enc", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client, engine
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_eta_secrets_stored_encrypted_and_decrypted_transparently(encrypted_client):
    client, engine = encrypted_client
    # ضبط الإعداد بسر حقيقي (بيئة mock تسمح بالسير كاملاً)
    r = client.put("/eta/config", json={
        "enabled": True, "env": "mock", "tin": "100-200-300",
        "client_id": "c-id", "client_secret": "super-secret-value-9876",
        "activity_code": "4690",
        "address": {"governate": "القاهرة", "region_city": "مدينة نصر", "street": "شارع التسعين", "building_number": "12"},
    })
    assert r.status_code == 200, r.text

    # في القاعدة: مشفر بالبادئة وليس نصًا صريحًا
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT eta_client_secret FROM companies")).scalar()
    assert stored.startswith("enc:v1:"), stored[:20]
    assert "super-secret" not in stored

    # القناع يعرض آخر 4 محارف من القيمة الحقيقية المفكوكة
    masked = client.get("/eta/config").json()
    assert masked["client_secret_masked"].endswith("9876")
    assert "super-secret-value" not in masked["client_secret_masked"]

    # توليد المفاتيح → المفتاح الخاص مشفر في القاعدة
    keys = client.post("/eta/config/generate-keys")
    assert keys.status_code == 200, keys.text
    with engine.connect() as conn:
        stored_key = conn.execute(text("SELECT eta_private_key FROM companies")).scalar()
    assert stored_key.startswith("enc:v1:")
    assert "PRIVATE KEY" not in stored_key

    # اختبار الجاهزية يعمل (يفك التشفير شفافياً ويوقّع)
    probe = client.post("/eta/config/test-connection")
    assert probe.status_code == 200, probe.text
    assert probe.json()["signature_works"] is True

    # سيناريو mock كامل: إرسال فاتورة يمر بالتوقيع المشفر دون خلل
    cust = client.post("/customers", json={"name": "عميل ETA"}).json()
    wh = client.post("/warehouses", json={"name": "المخزن الرئيسي", "code": "W1"}).json()
    prod = client.post("/products", json={"sku": "E1", "name": "صنف", "sale_price": "100", "cost_price": "50", "quantity": 10, "warehouse_id": wh["id"]}).json()
    order = client.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": prod["id"], "quantity": 1, "unit_price": "100"}],
    })
    assert order.status_code == 201, order.text
    assert client.post(f"/sales-orders/{order.json()['id']}/confirm").status_code == 200
    submit = client.post(f"/eta/submit/{order.json()['id']}")
    assert submit.status_code == 200, submit.text
    assert submit.json().get("status") in ("valid", "submitted", "Accepted")


def test_without_key_plaintext_mode_unchanged(monkeypatch):
    # يحاكي بيئة بلا مفتاح حتى لو كان ETA_ENC_KEY مضبوطاً في البيئة الفعلية
    monkeypatch.delenv("ETA_ENC_KEY", raising=False)
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
    try:
        client.post("/auth/setup", json={"username": "eta-plain", "password": "strong-password-123"})
        token = client.post("/auth/login", data={"username": "eta-plain", "password": "strong-password-123"}).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        r = client.put("/eta/config", json={
            "enabled": True, "env": "mock", "tin": "100-200-300",
            "client_id": "c-id", "client_secret": "plain-secret-5555",
        })
        assert r.status_code == 200, r.text
        with engine.connect() as conn:
            stored = conn.execute(text("SELECT eta_client_secret FROM companies")).scalar()
        # بلا مفتاح: نص صريح كما في السلوك القديم
        assert stored == "plain-secret-5555"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
