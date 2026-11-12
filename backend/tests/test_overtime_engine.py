"""اختبارات محرك ساعات العمل الإضافي المتقدمة (Advanced Overtime Engine):
1. حساب دقائق وتصنيف الإضافي (نهاري 1.35x، ليلي 1.70x، عطلات 2.0x).
2. استبعاد الإضافي غير المعتمد (overtime_approved=False).
3. الاحتساب الآلي لبند الاستحقاق في مسير الراتب وقسيمة الموظف.
"""
from decimal import Decimal
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
    client.post("/auth/setup", json={"username": "ot-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "ot-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_overtime_calculation_and_payslip_integration():
    client, engine = _client()
    try:
        # 1. إنشاء موظف براتب أساسي 6000 جنيه وعقد ساري
        emp = client.post(
            "/hr/employees",
            json={
                "code": "EMP-OT-1",
                "full_name": "محمود إبراهيم",
                "basic_salary": "6000.00",
            },
        ).json()
        client.post(
            f"/hr/employees/{emp['id']}/contracts",
            json={"start_date": "2026-01-01", "basic_salary": "6000.00"},
        )

        # 2. إنشاء وردية صباحية (09:00 إلى 17:00 = 8 ساعات)
        shift = client.post(
            "/hr/shifts",
            json={"name": "صباحي", "start_time": "09:00", "end_time": "17:00"},
        ).json()
        client.post("/hr/shift-assignments", json={"employee_id": emp["id"], "shift_id": shift["id"]})

        # 3. تسجيل سجلات حضور مع إضافي:
        # اليوم 1: خروج 19:00 (ساعتان إضافي نهاري 120 دقيقة @ 1.35x)
        r1 = client.post(
            "/hr/attendance",
            json={
                "employee_id": emp["id"],
                "work_date": "2026-11-01",
                "check_in": "09:00",
                "check_out": "19:00",
                "overtime_type": "day",
                "overtime_approved": True,
            },
        )
        assert r1.status_code == 201, r1.text
        assert r1.json()["overtime_minutes"] == 120

        # اليوم 2: خروج 18:00 (ساعة إضافي ليلي 60 دقيقة @ 1.70x)
        r2 = client.post(
            "/hr/attendance",
            json={
                "employee_id": emp["id"],
                "work_date": "2026-11-02",
                "check_in": "09:00",
                "check_out": "18:00",
                "overtime_type": "night",
                "overtime_approved": True,
            },
        )
        assert r2.status_code == 201, r2.text
        assert r2.json()["overtime_minutes"] == 60

        # اليوم 3: خروج 18:00 مع رفض الإضافي (غير معتمد overtime_approved=False)
        r3 = client.post(
            "/hr/attendance",
            json={
                "employee_id": emp["id"],
                "work_date": "2026-11-03",
                "check_in": "09:00",
                "check_out": "18:00",
                "overtime_type": "day",
                "overtime_approved": False,
            },
        )
        assert r3.status_code == 201, r3.text

        # 4. تشغيل مسير رواتب شهر نوفمبر 2026
        run = client.post("/hr/payroll-runs", json={"year": 2026, "month": 11}).json()
        slips = client.get(f"/hr/payroll-runs/{run['id']}/payslips").json()
        assert len(slips) == 1
        slip = slips[0]

        # فحص بنود قسيمة الراتب
        lines = client.get(f"/hr/payslips/{slip['id']}").json()
        ot_line = next((line for line in lines if "ساعات عمل إضافية" in line["name"]), None)
        assert ot_line is not None, f"لم يتم العثور على بند الساعات الإضافية في: {lines}"

        # التحقق الحسابي:
        # راتب 6000 / 30 يوم = 200 جنيه/يوم.
        # أجر الساعة = 200 / 8 ساعات = 25 جنيه/ساعة.
        # اليوم الأول (نهاري): ساعتان × 25 × 1.35 = 67.50 جنيه.
        # اليوم الثاني (ليلي): ساعة × 25 × 1.70 = 42.50 جنيه.
        # اليوم الثالث: مستبعد لعدم الاعتماد.
        # الإجمالي المتوقع للإضافي = 67.50 + 42.50 = 110.00 جنيه.
        assert Decimal(ot_line["amount"]) == Decimal("110.00")
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
