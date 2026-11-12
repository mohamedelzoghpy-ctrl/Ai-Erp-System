"""اختبارات S2: الورديات والحضور والعطلات أنواع الإجازات والأرصدة وطلباتها."""
from datetime import date, timedelta

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
    client.post("/auth/setup", json={"username": "hr-admin", "password": "strong-password-123"})
    token = client.post("/auth/login", data={"username": "hr-admin", "password": "strong-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_shifts_and_assignments_with_calculated_late():
    client, engine = _client()
    try:
        shift = client.post("/hr/shifts", json={"name": "صباحي", "start_time": "09:00", "end_time": "17:00"}).json()
        assert shift["cross_midnight"] is False
        night = client.post("/hr/shifts", json={"name": "ليلي", "start_time": "22:00", "end_time": "06:00"}).json()
        assert night["cross_midnight"] is True

        emp = client.post("/hr/employees", json={"full_name": "موظف الوردية"}).json()
        assigned = client.post("/hr/shift-assignments", json={"employee_id": emp["id"], "shift_id": shift["id"]})
        assert assigned.status_code == 201, assigned.text
        rows = client.get("/hr/shift-assignments").json()
        assert len(rows) == 1 and rows[0]["shift_name"] == "صباحي"

        # تأخير 40 دقيقة بعد سماح 15 → تأخير مسجل 25 دقيقة
        att = client.post("/hr/attendance", json={
            "employee_id": emp["id"], "work_date": "2026-11-01", "status": "late",
            "check_in": "09:40", "check_out": "17:05",
        })
        assert att.status_code == 201, att.text
        assert att.json()["late_minutes"] == 25
        assert att.json()["overtime_minutes"] == 5

        # سجل مزدوج لنفس اليوم مرفوض
        dup = client.post("/hr/attendance", json={
            "employee_id": emp["id"], "work_date": "2026-11-01", "status": "absent",
        })
        assert dup.status_code == 409

        # إزالة الإسناد
        removed = client.post("/hr/shift-assignments", json={"employee_id": emp["id"], "shift_id": None})
        assert removed.status_code == 201
        assert client.get("/hr/shift-assignments").json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_leave_flow_approve_deducts_balance_and_blocks_overlap():
    client, engine = _client()
    try:
        lt = client.post("/hr/leave-types", json={"name": "سنوية", "days_per_year": "20", "carry_over_days": "5"}).json()
        emp = client.post("/hr/employees", json={"full_name": "صاحب الرصيد"}).json()

        # الرصيد يُنشأ لازماً بقيمة المصارف من النوع
        balances = client.get(f"/hr/leave-balances?employee_id={emp['id']}").json()
        assert len(balances) == 1
        assert balances[0]["entitled_days"] == "20.0"
        assert balances[0]["remaining_days"] == "20.0"

        # طلب إجازة 3 أيام (شامل) — دافع behavior: days = to - from + 1
        req = client.post("/hr/leave-requests", json={
            "employee_id": emp["id"], "leave_type_id": lt["id"],
            "from_date": "2026-11-10", "to_date": "2026-11-12",
        })
        assert req.status_code == 201, req.text
        assert req.json()["days"] == "3.0"
        rid = req.json()["id"]

        # موافقة تنقص الرصيد إلى 17
        approved = client.post(f"/hr/leave-requests/{rid}/approve", json={"decision_note": "تم"})
        assert approved.status_code == 200, approved.text
        balances = client.get(f"/hr/leave-balances?employee_id={emp['id']}").json()
        assert balances[0]["used_days"] == "3.0" and balances[0]["remaining_days"] == "17.0"

        # طلب يتقاطع مع المعتمد مرفوض
        overlap = client.post("/hr/leave-requests", json={
            "employee_id": emp["id"], "leave_type_id": lt["id"],
            "from_date": "2026-11-11", "to_date": "2026-11-14",
        })
        assert overlap.status_code == 409

        # طلب يتجاوز الرصيد يُرفض عند الموافقة
        big = client.post("/hr/leave-requests", json={
            "employee_id": emp["id"], "leave_type_id": lt["id"],
            "from_date": "2027-10-01", "to_date": "2027-12-30",
        })
        assert big.status_code == 201
        big_id = big.json()["id"]
        denied = client.post(f"/hr/leave-requests/{big_id}/approve", json={})
        assert denied.status_code == 409

        # رفض معلّق لا يمس الرصيد
        rejected = client.post(f"/hr/leave-requests/{big_id}/reject", json={"decision_note": "ضغط العمل"})
        assert rejected.status_code == 200
        balances = client.get(f"/hr/leave-balances?employee_id={emp['id']}").json()
        assert balances[0]["used_days"] == "3.0"

        # إلغاء معتمد يعيد الرصيد
        cancelled = client.post(f"/hr/leave-requests/{rid}/cancel")
        assert cancelled.status_code == 200
        balances = client.get(f"/hr/leave-balances?employee_id={emp['id']}").json()
        assert balances[0]["used_days"] == "0.0" and balances[0]["remaining_days"] == "20.0"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_holidays_and_attendance_listing_filters():
    client, engine = _client()
    try:
        holiday = client.post("/hr/holidays", json={"name": "عيد الأضحى", "holiday_date": "2026-05-27"}).json()
        assert holiday["holiday_date"] == "2026-05-27"
        dup = client.post("/hr/holidays", json={"name": "مكرر", "holiday_date": "2026-05-27"})
        assert dup.status_code == 409
        listed = client.get("/hr/holidays?year=2026").json()
        assert len(listed) == 1
        assert client.delete(f"/hr/holidays/{holiday['id']}").status_code == 204
        assert client.get("/hr/holidays").json() == []

        emp1 = client.post("/hr/employees", json={"full_name": "أ"}).json()
        emp2 = client.post("/hr/employees", json={"full_name": "ب"}).json()
        client.post("/hr/attendance", json={"employee_id": emp1["id"], "work_date": "2026-11-01", "status": "absent"})
        client.post("/hr/attendance", json={"employee_id": emp2["id"], "work_date": "2026-11-02", "status": "present", "check_in": "08:55", "check_out": "17:00"})
        only = client.get(f"/hr/attendance?employee_id={emp1['id']}").json()
        assert len(only) == 1 and only[0]["status"] == "absent"
        ranged = client.get("/hr/attendance?date_from=2026-11-01&date_to=2026-11-02").json()
        assert len(ranged) == 2
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_leave_type_delete_blocked_when_used_and_inactive_alternative():
    client, engine = _client()
    try:
        lt = client.post("/hr/leave-types", json={"name": "مرضية", "days_per_year": "30"}).json()
        emp = client.post("/hr/employees", json={"full_name": "مريض"}).json()
        req = client.post("/hr/leave-requests", json={
            "employee_id": emp["id"], "leave_type_id": lt["id"],
            "from_date": "2026-11-01", "to_date": "2026-11-02",
        })
        assert req.status_code == 201
        blocked = client.delete(f"/hr/leave-types/{lt['id']}")
        assert blocked.status_code == 409
        deactivated = client.patch(f"/hr/leave-types/{lt['id']}", json={"is_active": False})
        assert deactivated.status_code == 200
        # نوع غير مفعّل يُرفض في الطلبات الجديدة
        new_req = client.post("/hr/leave-requests", json={
            "employee_id": emp["id"], "leave_type_id": lt["id"],
            "from_date": "2026-12-01", "to_date": "2026-12-02",
        })
        assert new_req.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
