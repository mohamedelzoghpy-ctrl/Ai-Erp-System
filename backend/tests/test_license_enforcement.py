"""إنفورسمنت الترخيص: حظر الدخول والاستخدام عند انتهاء الرخصة لكل مستخدمي الشركة العميل —
مالك التطبيق (platform admin) فقط يتجاوز ويجدد بكلمة السر المحفوظة."""
from datetime import date, timedelta

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

    r = client.post("/platform/companies", json={
        "name": "شركة الترخيص", "code": "lic-co", "admin_username": "licadmin", "admin_password": "licadmin-pass-123",
    })
    assert r.status_code == 201, r.text
    company_id = r.json()["id"]
    lic_admin = TestClient(app)
    ltok = client.post("/auth/login", data={"username": "licadmin", "password": "licadmin-pass-123"}).json()["access_token"]
    lic_admin.headers["Authorization"] = f"Bearer {ltok}"
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


def test_expired_company_blocks_everyone_including_company_admin(env):
    client, lic_admin, company_id = env
    set_license(client, company_id, date.today() - timedelta(days=1))
    # الموظف محجوب
    r = client.post("/auth/login", data={"username": "licstaff", "password": "licstaff-pass-123"})
    assert r.status_code == 403 and "انتهت رخصة" in r.json()["detail"]
    # أدمن الشركة العميل محجوب أيضاً — هو ليس مالك التطبيق
    r = client.post("/auth/login", data={"username": "licadmin", "password": "licadmin-pass-123"})
    assert r.status_code == 403 and "انتهت رخصة" in r.json()["detail"]


def test_gate_blocks_all_company_users_but_platform_admin_passes(env):
    client, lic_admin, company_id = env
    admin_token = lic_admin.headers["Authorization"].split(" ", 1)[1]
    staff_pre = staff_token(client)
    set_license(client, company_id, date.today() - timedelta(days=1))
    # جلسة أدمن الشركة القائمة: محجوبة
    r = client.get("/company/branches", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 403 and "انتهت رخصة" in r.json()["detail"]
    # جلسة الموظف القائمة: محجوبة حتى صلاحياتها الأساسية
    r = client.get("/sync/bootstrap", headers={"Authorization": f"Bearer {staff_pre}"})
    assert r.status_code == 403 and "انتهت رخصة" in r.json()["detail"]
    # مالك التطبيق (platform admin) يتجاوز: يبدّل لشركة العميل ويعمل عليها
    ok(client.post("/auth/switch-company", json={"company_id": company_id}))
    assert client.get("/company/branches").status_code == 200


def test_platform_owner_renews_with_saved_password_unblocks_everything(env):
    client, lic_admin, company_id = env
    set_license(client, company_id, date.today() - timedelta(days=1))
    # تجديد من مالك التطبيق بكلمة السر المحفوظة
    new_until = (date.today() + timedelta(days=365)).isoformat()
    res = ok(client.put(f"/platform/companies/{company_id}/license", json={
        "license_password": RENEW_KEY, "license_until": new_until,
    }))
    assert res["license_until"] == new_until
    # الموظف وأدمن الشركة يعودون للدخول
    r = client.post("/auth/login", data={"username": "licstaff", "password": "licstaff-pass-123"})
    assert r.status_code == 200
    r = client.post("/auth/login", data={"username": "licadmin", "password": "licadmin-pass-123"})
    assert r.status_code == 200


def test_wrong_renew_password_rejected_and_logged(env):
    client, lic_admin, company_id = env
    r = client.put(f"/platform/companies/{company_id}/license", json={
        "license_password": "wrong-key", "license_until": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert r.status_code == 403 and "غير صحيحة" in r.json()["detail"]


def test_company_scope_renew_is_platform_admin_only(env):
    """PATCH /company/license — بعد تبديل المالك لشركة العميل؛ أدمن الشركة مرفوض."""
    client, lic_admin, company_id = env
    # أدمن الشركة (غير مالك التطبيق) → مرفوض
    r = lic_admin.patch("/company/license", json={
        "license_password": RENEW_KEY, "license_until": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert r.status_code == 403 and "مالك التطبيق" in r.json()["detail"]
    # مالك التطبيق بعد التبديل → نجاح
    ok(client.post("/auth/switch-company", json={"company_id": company_id}))
    new_until = (date.today() + timedelta(days=60)).isoformat()
    res = ok(client.patch("/company/license", json={"license_password": RENEW_KEY, "license_until": new_until}))
    assert res["license_until"] == new_until


def test_null_license_never_blocks(env):
    client, lic_admin, company_id = env
    r = client.post("/auth/login", data={"username": "platform", "password": "long-password-123"})
    assert r.status_code == 200
    set_license(client, company_id, date.today() + timedelta(days=7))
    r = client.post("/auth/login", data={"username": "licadmin", "password": "licadmin-pass-123"})
    assert r.status_code == 200
    stok = staff_token(client)
    assert client.get("/sync/bootstrap", headers={"Authorization": f"Bearer {stok}"}).status_code == 200
