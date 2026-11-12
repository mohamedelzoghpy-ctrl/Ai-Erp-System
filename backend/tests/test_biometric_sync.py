"""اختبارات تكامل أجهزة البصمة (Biometric Device & Push Integration):
1. تسجيل وتعديل وفحص جاهزية أجهزة البصمة (/hr/biometric-devices).
2. استقبال حركات البصمة الفورية (/hr/biometric-devices/push-punches).
3. التجميع التلقائي لحركات الدخول والخروج في سجل الحضور والغياب اليومي.
"""
from datetime import datetime, timezone
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
    client.post("/auth/setup", json={"username": "bio-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "bio-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_biometric_device_lifecycle_and_push_punches():
    client, engine = _client()
    try:
        # 1. إنشاء موظف بكود "BIO-101"
        emp = client.post(
            "/hr/employees",
            json={"full_name": "سامح علي", "code": "BIO-101", "basic_salary": "7000"},
        ).json()

        # 2. تسجيل جهاز بصمة جديد
        dev_resp = client.post(
            "/hr/biometric-devices",
            json={
                "name": "بصمة الباب الرئيسي",
                "device_model": "ZKTeco K40",
                "ip_address": "192.168.1.200",
                "port": 4370,
            },
        )
        assert dev_resp.status_code == 201, dev_resp.text
        device = dev_resp.json()
        assert device["name"] == "بصمة الباب الرئيسي"

        # 3. دفع دفعة حركات بصمة (دخول الساعة 08:50 وخروج 17:15 في نفس اليوم)
        push_resp = client.post(
            "/hr/biometric-devices/push-punches",
            json={
                "device_id": device["id"],
                "punches": [
                    {"employee_code": "BIO-101", "timestamp": "2026-11-12T08:50:00Z"},
                    {"employee_code": "BIO-101", "timestamp": "2026-11-12T17:15:00Z"},
                    {"employee_code": "UNKNOWN-99", "timestamp": "2026-11-12T09:00:00Z"},
                ],
            },
        )
        assert push_resp.status_code == 200, push_resp.text
        summary = push_resp.json()
        assert summary["total_received"] == 3
        assert summary["matched_punches"] == 2
        assert summary["attendance_records_created"] == 1
        assert "UNKNOWN-99" in summary["unmatched_employee_codes"]

        # 4. التحقق من سجل الحضور والانصراف المولد آلياً
        att_list = client.get(f"/hr/attendance?employee_id={emp['id']}").json()
        assert len(att_list) == 1
        att = att_list[0]
        assert att["check_in"] == "08:50"
        assert att["check_out"] == "17:15"
        assert att["source"] == "device"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
