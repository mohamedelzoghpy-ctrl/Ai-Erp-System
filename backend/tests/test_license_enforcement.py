"""إنفورسمنت الترخيص: حظر الدخول والاستخدام عند انتهاء الرخصة — إلا أدمن الشركة (يدخل ويجدد بكلمة السر المحفوظة)."""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

RENEW_KEY = "renew-key-test-123"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LICENSE_RENEWAL_PASSWORD", RENEW_KEY)
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
    client.post("/auth/setup", json={"username": "platform", "password": "long-password-123"})
    tok = client.post("/auth/login", data={"username": "platform", "password": "long-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {tok}"

    # شركة تجريبية بأدمن وموظف
    r = client.post("/platform/companies", json={
        "name": "شركة الترخيص", "code": "lic-co", "admin_username": "licadmin", "admin_password": "licadmin-pass-123",
    })
    assert r.status_code == 201, r.text
    company_id = r.json()["id"]
    lic_admin = TestClient(app)
    ltok = client.post("/auth/login", data={"username": "licadmin", "password": "licadmin-pass-123"}).json()["access_token"]
    lic_admin.headers["Authorization"] = f"Bearer {ltok}"
    # موظف في الشركة — يحتاج فرعًا ومخزنًا (متطلب إنشاء الموظفين)
    branch = lic_admin.post("/company/branches", json={"name": "فرع الترخيص"}).json()
    warehouse = lic_admin.post("/warehouses", json={"name": "مخزن الترخيص", "code": "LW1", "branch_id": branch["id"]}).json()
    r = lic_admin.post("/auth/users", json={
        "username": "licstaff", "password": "licstaff-pass-123", "role": "staff",
        "branch_ids": [branch["id"]], "warehouse_ids": [warehouse["id"]],
    })
    assert r.status_code in (200, 201), r.text

    yield client, lic_admin, company_id
    app.dependency_overrides.pop(get_db, None)


def ok(resp, code=200):
    assert resp.status_code == code, (resp.status_code, resp.text)
    return resp.json() if resp.content else None


def staff_token(client):
    return client.post("/auth/login", data={"username": "licstaff", "password": "licstaff-pass-123"}).json()["access_token"]


def set_license(platform_client, company_id, when: date):
    return ok(platform_client.put(f"/platform/companies/{company_id}/license", json={
        "license_password": RENEW_KEY,
        "license_until": when.isoformat(),
    }))


def test_expired_company_blocks_staff_login_but_allows_admin(env):
    client, lic_admin, company_id = env
    yesterday = date.today() - timedelta(days=1)
    set_license(client, company_id, yesterday)

    # الموظف: الدخول محجوب برسالة الترخيص
    r = client.post("/auth/login", data={"username": "licstaff", "password": "licstaff-pass-123"})
    assert r.status_code == 403 and "انتهت رخصة" in r.json()["detail"]

    # أدمن الشركة: يدخل عادي
    r = client.post("/auth/login", data={"username": "licadmin", "password": "licadmin-pass-123"})
    assert r.status_code == 200 and "access_token" in r.json()


def test_gate_blocks_staff_api_but_admin_works_after_expiry(env):
    client, lic_admin, company_id = env
    # توكن الموظف قبل انتهاء الرخصة (جلسة قائمة)
    pre_token = staff_token(client)
    staff_headers = {"Authorization": f"Bearer {pre_token}"}
    assert client.get("/sync/bootstrap", headers=staff_headers).status_code == 200  # صلاحية أساسية للموظف

    set_license(client, company_id, date.today() - timedelta(days=1))

    # الجلسة القائمة للموظف: كل مسارات العمل محجوبة برسالة الترخيص (حتى صلاحياته الأساسية)
    r = client.get("/sync/bootstrap", headers=staff_headers)
    assert r.status_code == 403 and "انتهت رخصة" in r.json()["detail"]

    # أدمن الشركة: يعمل بالكامل (يستطيع التجديد)
    r = lic_admin.get("/products")
    assert r.status_code == 200


def test_self_renew_with_saved_password_unblocks_everything(env):
    client, lic_admin, company_id = env
    set_license(client, company_id, date.today() - timedelta(days=1))

    # كلمة سر خاطئة → 403
    r = lic_admin.patch("/company/license", json={
        "license_password": "wrong-key", "license_until": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert r.status_code == 403 and "غير صحيحة" in r.json()["detail"]

    # الموظف ما زال محجوبًا قبل التجديد
    r = client.post("/auth/login", data={"username": "licstaff", "password": "licstaff-pass-123"})
    assert r.status_code == 403

    # التجديد الصحيح بكلمة السر المحفوظة
    new_until = (date.today() + timedelta(days=30)).isoformat()
    res = ok(lic_admin.patch("/company/license", json={"license_password": RENEW_KEY, "license_until": new_until}))
    assert res["license_until"] == new_until

    # الموظف يعود للدخول والعمل، والأدمن مستمر
    r = client.post("/auth/login", data={"username": "licstaff", "password": "licstaff-pass-123"})
    assert r.status_code == 200
    stok = r.json()["access_token"]
    assert client.get("/sync/bootstrap", headers={"Authorization": f"Bearer {stok}"}).status_code == 200


def test_renew_self_restricted_to_admin_role(env):
    client, lic_admin, company_id = env
    stok = staff_token(client)
    staff_client = TestClient(app)
    staff_client.headers["Authorization"] = f"Bearer {stok}"
    r = staff_client.patch("/company/license", json={
        "license_password": RENEW_KEY, "license_until": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert r.status_code == 403


def test_null_license_never_blocks(env):
    client, _lic_admin, company_id = env
    # شركة الـ setup بلا license_until → الدخول والعمل طبيعيان
    r = client.post("/auth/login", data={"username": "platform", "password": "long-password-123"})
    assert r.status_code == 200
    # رخصة مستقبلية أيضًا لا تحجب
    set_license(client, company_id, date.today() + timedelta(days=7))
    r = client.post("/auth/login", data={"username": "licadmin", "password": "licadmin-pass-123"})
    assert r.status_code == 200
    stok = staff_token(client)
    assert client.get("/sync/bootstrap", headers={"Authorization": f"Bearer {stok}"}).status_code == 200
