"""اختبار انحدار أمني: تفاصيل قسائم الرواتب لموظفين آخرين لا تُقرأ إلا
لمن يملك hr.payslip.view (مدير/إدارة أو منح قسم) — الخدمة الذاتية /me
تبقى كما هي لبقية المستخدمين (baseline)."""
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
    client.post("/auth/setup", json={"username": "pay-sec-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "pay-sec-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def _make_staff(client, username):
    branches = client.get("/company/branches").json()
    resp = client.post(
        "/auth/users",
        json={
            "username": username,
            "password": "staff-password-123",
            "role": "staff",
            "full_name": username,
            "branch_ids": [branches[0]["id"]],
        },
    )
    assert resp.status_code == 201, resp.text
    login = client.post(
        "/auth/login", data={"username": username, "password": "staff-password-123"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_staff_cannot_read_others_payslips():
    client, engine = _client()
    try:
        # موظف بمسير رواتب فيه قسيمة
        emp = client.post("/hr/employees", json={"full_name": "موظف رواتب", "basic_salary": "9000"}).json()
        run = client.post("/hr/payroll-runs", json={"year": 2026, "month": 11})
        assert run.status_code == 201, run.text
        run_id = run.json()["id"]
        slips = client.get(f"/hr/payroll-runs/{run_id}/payslips").json()
        assert len(slips) == 1
        slip_id = slips[0]["id"]

        staff_headers = _make_staff(client, "salary-snooper")

        # الموظف العادي محجوب من قسائم مسير ومن تفاصيل قسيمة زميله
        assert client.get(f"/hr/payroll-runs/{run_id}/payslips", headers=staff_headers).status_code == 403
        assert client.get(f"/hr/payslips/{slip_id}", headers=staff_headers).status_code == 403

        # بينما الخدمة الذاتية (baseline) لم تتأثر — 404 = حساب غير مرتبط بموظف، وليس حجباً
        me_slips = client.get("/hr/me/payslips", headers=staff_headers)
        assert me_slips.status_code == 404 or me_slips.json() == []

        # المدير يرى كالمعتاد
        assert client.get(f"/hr/payroll-runs/{run_id}/payslips").status_code == 200
        assert client.get(f"/hr/payslips/{slip_id}").status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
