"""المرحلة 0: توكن التجديد (refresh) + سياسة كلمات السر — أساس جلسات الموبايل."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
    client.post("/auth/setup", json={"username": "p0-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "p0-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_login_issues_refresh_token_and_refresh_flow_works():
    client, engine = _client()
    try:
        # تسجيل الدخول يعيد توكني وصول وتجديد
        login = client.post(
            "/auth/login", data={"username": "p0-admin", "password": "strong-password-123"}
        )
        assert login.status_code == 200, login.text
        tokens = login.json()
        assert tokens.get("refresh_token"), "يجب أن يعيد الدخول توكن تجديد"

        # التجديد يعمل ويعيد زوجًا جديدًا
        refreshed = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert refreshed.status_code == 200, refreshed.text
        new_tokens = refreshed.json()
        assert new_tokens["access_token"] and new_tokens.get("refresh_token")

        # توكن الوصول الجديد يعمل على /auth/me
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {new_tokens['access_token']}"})
        assert me.status_code == 200 and me.json()["username"] == "p0-admin"

        # توكن الوصول لا يصلح توكن تجديد (فصل الأنواع)
        as_refresh = client.post("/auth/refresh", json={"refresh_token": new_tokens["access_token"]})
        assert as_refresh.status_code == 401

        # قيمة عشوائية مرفوضة
        garbage = client.post("/auth/refresh", json={"refresh_token": "x" * 40})
        assert garbage.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_logout_all_revokes_refresh_token():
    client, engine = _client()
    try:
        tokens = client.post(
            "/auth/login", data={"username": "p0-admin", "password": "strong-password-123"}
        ).json()
        # إبطال كل الجلسات يرفع إصدار التوكن
        assert client.post("/auth/logout-all").status_code == 204

        # توكن الوصول القديم بطل
        assert client.get("/auth/me").status_code == 401
        # وتوكن التجديد القديم بطل أيضًا (نفس الإصدار)
        revoked = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert revoked.status_code == 401

        # الدخول من جديد يعطي جلسة صالحة قابلة للتجديد
        fresh = client.post(
            "/auth/login", data={"username": "p0-admin", "password": "strong-password-123"}
        ).json()
        again = client.post("/auth/refresh", json={"refresh_token": fresh["refresh_token"]})
        assert again.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_password_policy_blocks_weak_and_allows_strong():
    client, engine = _client()
    try:
        branches = client.get("/company/branches").json()

        # بلا أرقام → 422
        r = client.post("/auth/users", json={
            "username": "weak1", "password": "letters-only-pass", "role": "staff",
            "full_name": "ضعيف", "branch_ids": [branches[0]["id"]],
        })
        assert r.status_code == 422 and "أرقام" in r.json()["detail"]

        # قصيرة → 422
        r = client.post("/auth/users", json={
            "username": "weak2", "password": "ab1", "role": "staff",
            "full_name": "قصير", "branch_ids": [branches[0]["id"]],
        })
        assert r.status_code == 422

        # شائعة → 422
        r = client.post("/auth/users", json={
            "username": "weak3", "password": "password123", "role": "staff",
            "full_name": "شائعة", "branch_ids": [branches[0]["id"]],
        })
        assert r.status_code == 422

        # قوية → 201 ويمكنه الدخول
        r = client.post("/auth/users", json={
            "username": "strong1", "password": "solid-pass-77", "role": "staff",
            "full_name": "قوي", "branch_ids": [branches[0]["id"]],
        })
        assert r.status_code == 201, r.text
        assert client.post(
            "/auth/login", data={"username": "strong1", "password": "solid-pass-77"}
        ).status_code == 200

        # تغيير كلمة السر ذاتيًا يخضع للسياسة أيضًا
        r = client.post("/auth/change-password", json={
            "old_password": "strong-password-123", "new_password": "nodigits-here",
        })
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
