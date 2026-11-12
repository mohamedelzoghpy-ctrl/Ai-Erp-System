"""اختبارات S5: الخدمة الذاتية للموظف — ملفي، أرصدتي، حضوري، قسائمي، طلبات ذاتية."""
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
    client.post("/auth/setup", json={"username": "ess-admin", "password": "strong-password-123"})
    token = client.post("/auth/login", data={"username": "ess-admin", "password": "strong-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_me_requires_linked_employee_and_links_via_update():
    client, engine = _client()
    try:
        me = client.get("/hr/me")
        assert me.status_code == 404  # غير مرتبط بعد

        emp = client.post("/hr/employees", json={"full_name": "موظف إس إس"}).json()
        # ربط الحساب الحالي (المستخدم 1 — المدير) بالموظف
        upd = client.patch(f"/hr/employees/{emp['id']}", json={"user_id": 1})
        assert upd.status_code == 200, upd.text

        me = client.get("/hr/me")
        assert me.status_code == 200, me.text
        assert me.json()["code"] == emp["code"]

        # ربط نفس الحساب بموظف آخر مرفوض
        emp2 = client.post("/hr/employees", json={"full_name": "موظف ثانٍ"}).json()
        dup = client.patch(f"/hr/employees/{emp2['id']}", json={"user_id": 1})
        assert dup.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_self_leave_request_and_own_scopes():
    client, engine = _client()
    try:
        emp = client.post("/hr/employees", json={"full_name": "طالب إجازة ذاتية", "basic_salary": "7000"}).json()
        client.patch(f"/hr/employees/{emp['id']}", json={"user_id": 1})

        lt = client.post("/hr/leave-types", json={"name": "سنوية إس", "days_per_year": "20"}).json()
        req = client.post("/hr/me/leave-requests", json={
            "leave_type_id": lt["id"],
            "from_date": "2026-12-01", "to_date": "2026-12-02",
            "reason": "ظروف خاصة",
        })
        assert req.status_code == 201, req.text
        assert req.json()["status"] == "pending" and req.json()["days"] == "2.0"

        # قائمة «طلباتي» وحدها
        mine = client.get("/hr/me/leave-requests").json()
        assert len(mine) == 1

        # المدير يوافق من المسار المديري — الرصيد ينقص ويسيطل بطلب التقاطع
        rid = req.json()["id"]
        assert client.post(f"/hr/leave-requests/{rid}/approve", json={}).status_code == 200
        bal = client.get("/hr/me/leave-balances?year=2026").json()
        assert len(bal) == 1 and bal[0]["used_days"] == "2.0" and bal[0]["remaining_days"] == "18.0"

        overlap = client.post("/hr/me/leave-requests", json={
            "leave_type_id": lt["id"], "from_date": "2026-12-01", "to_date": "2026-12-01",
        })
        assert overlap.status_code == 409

        # طلب قبل تاريخ المباشرة مرفوض
        before = client.post("/hr/me/leave-requests", json={
            "leave_type_id": lt["id"],
            "from_date": "1999-01-01", "to_date": "1999-01-02",
        })
        assert before.status_code == 422

        # قسائمي: فارغة قبل أي مسير؛ تظهر بعد إنشاء مسير وترحيل؟ ترحيل يحتاج راتب مبين بلا غياب
        assert client.get("/hr/me/payslips").json() == []
        run = client.post("/hr/payroll-runs", json={"year": 2026, "month": 1}).json()
        assert client.post(f"/hr/payroll-runs/{run['id']}/post", json={}).status_code == 200
        slips = client.get("/hr/me/payslips").json()
        assert len(slips) == 1 and slips[0]["year"] == 2026 and slips[0]["month"] == 1
        assert slips[0]["run_status"] == "posted" and slips[0]["base_salary"] == "7000.00"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_attendance_correction_apply_and_reject():
    client, engine = _client()
    try:
        emp = client.post("/hr/employees", json={"full_name": "داخل ATT ظن", "basic_salary": "6000"}).json()
        client.patch(f"/hr/employees/{emp['id']}", json={"user_id": 1})
        # وردية للموظف (دخول 09:00 سماح 15)
        shift = client.post("/hr/shifts", json={"name": "صباحي إس", "start_time": "09:00", "end_time": "17:00"}).json()
        client.post("/hr/shift-assignments", json={"employee_id": emp["id"], "shift_id": shift["id"]})

        yesterday = str(date.today() - timedelta(days=3))
        # طلب تصحيح يوم الغياب بدخول 09:40
        corr = client.post("/hr/me/attendance-corrections", json={
            "work_date": yesterday, "requested_check_in": "09:40", "requested_check_out": "17:00",
            "reason": "نسيس تسجيل البصمة",
        })
        assert corr.status_code == 201, corr.text
        cid = corr.json()["id"]

        # طلب معلّق ثانٍ لنفس اليوم مرفوض
        dup = client.post("/hr/me/attendance-corrections", json={
            "work_date": yesterday, "requested_check_in": "10:00", "reason": "مكرر للتحقق",
        })
        assert dup.status_code == 409
        # يوم مستقبلي مرفوض
        future = client.post("/hr/me/attendance-corrections", json={
            "work_date": str(date.today() + timedelta(days=3)), "requested_check_in": "10:00", "reason": "عهدة تجربة",
        })
        assert future.status_code == 422

        # الموظف يرى طلبه؛ المدير يراه في القائمة المعّلنة
        assert len(client.get("/hr/me/attendance-corrections").json()) == 1
        pending = client.get("/hr/attendance-corrections?correction_status=pending")
        assert pending.status_code == 200 and any(
            approval["id"] == cid for approval in pending.json()
        ), pending.text

        # موافقة تطبق على سجل الحضور: سجل جديد + تأخير 25 (09:40 - 09:00 - 15)
        approved = client.post(f"/hr/attendance-corrections/{cid}/approve", json={"decision_note": "تمام"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        att = client.get("/hr/attendance?employee_id=" + str(emp["id"])).json()
        assert len(att) == 1 and att[0]["check_in"] == "09:40" and att[0]["late_minutes"] == 25

        # طلب الرفض بعد الموافقة مرفوض
        assert client.post(f"/hr/attendance-corrections/{cid}/reject", json={}).status_code == 409

        # سيناريو رفض
        corr2 = client.post("/hr/me/attendance-corrections", json={
            "work_date": str(date.today() - timedelta(days=2)), "requested_check_in": "10:00", "reason": "تجربة ثانية زيادة",
        })
        assert corr2.status_code == 201
        rejected = client.post(f"/hr/attendance-corrections/{corr2.json()['id']}/reject", json={"decision_note": "لا دليل"})
        assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
        att = client.get("/hr/attendance?employee_id=" + str(emp["id"])).json()
        assert len(att) == 1  # لم يُنشئ سجلاً رغم الطلب
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
