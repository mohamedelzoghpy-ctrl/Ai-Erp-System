"""اختبارات S3: مكونات الرواتب، مسير شهر بقسائم محسوبة من الحضور والإجازات،
وترحيل محاسبي متوازن في دفتر الأستاذ."""
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
    client.post("/auth/setup", json={"username": "pay-admin", "password": "strong-password-123"})
    token = client.post("/auth/login", data={"username": "pay-admin", "password": "strong-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_salary_components_validation_and_uniqueness():
    client, engine = _client()
    try:
        emp = client.post("/hr/employees", json={"full_name": "محتاج بنك", "basic_salary": "10000"}).json()
        comp = client.post("/hr/salary-components", json={
            "employee_id": emp["id"], "name": "بدل سكن", "category": "earning",
            "amount_mode": "fixed", "fixed_amount": "2000",
        })
        assert comp.status_code == 201, comp.text
        # فرادة الاسم لنفس الموظف
        dup = client.post("/hr/salary-components", json={
            "employee_id": emp["id"], "name": "بدل سكن", "category": "earning", "amount_mode": "fixed", "fixed_amount": "1",
        })
        assert dup.status_code == 409
        # مكوّن نسبة بلا نسبة مرفوض
        bad = client.post("/hr/salary-components", json={
            "employee_id": emp["id"], "name": "تأمينات", "category": "deduction", "amount_mode": "percent_of_base",
        })
        assert bad.status_code == 422
        # قيمة اختراق ليست موجبة مرفوضة
        negative = client.post("/hr/salary-components", json={
            "employee_id": emp["id"], "name": "خصم", "category": "deduction", "amount_mode": "fixed", "fixed_amount": "-5",
        })
        assert negative.status_code == 422
        listed = client.get(f"/hr/salary-components?employee_id={emp['id']}").json()
        assert len(listed) == 1 and listed[0]["name"] == "بدل سكن"
        # تعطيل وإعادة تفعيل
        assert client.patch(f"/hr/salary-components/{comp.json()['id']}", json={"is_active": False}).status_code == 200
        assert client.delete(f"/hr/salary-components/{comp.json()['id']}").status_code == 204
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_payroll_run_generation_with_absence_and_unpaid_leave():
    client, engine = _client()
    try:
        emp = client.post("/hr/employees", json={"full_name": "ر بتسقى بونص", "basic_salary": "9000"}).json()
        client.post("/hr/salary-components", json={
            "employee_id": emp["id"], "name": "بونص ثابت", "category": "earning", "amount_mode": "fixed", "fixed_amount": "1000",
        })
        client.post("/hr/salary-components", json={
            "employee_id": emp["id"], "name": "تأمينات", "category": "deduction", "amount_mode": "percent_of_base", "percent_value": "10",
        })
        # 3 أيام غياب في نوفمبر 2026
        for d in ("03", "04", "05",):
            client.post("/hr/attendance", json={"employee_id": emp["id"], "work_date": f"2026-11-{d}", "status": "absent"})
        # إجازة غير مدفوعة معتمدة 10-12 نوفمبر (3 أيام)
        unpaid = client.post("/hr/leave-types", json={"name": "بدون راتب", "days_per_year": "10", "is_paid": False}).json()
        req = client.post("/hr/leave-requests", json={
            "employee_id": emp["id"], "leave_type_id": unpaid["id"],
            "from_date": "2026-11-10", "to_date": "2026-11-12",
        })
        assert req.status_code == 201, req.text
        # موافقة على الإجازة
        assert client.post(f"/hr/leave-requests/{req.json()['id']}/approve", json={}).status_code == 200

        run = client.post("/hr/payroll-runs", json={"year": 2026, "month": 11})
        assert run.status_code == 201, run.text
        run_data = run.json()
        assert run_data["status"] == "draft"
        assert run_data["employees_count"] == 1

        slips = client.get(f"/hr/payroll-runs/{run_data['id']}/payslips").json()
        assert len(slips) == 1
        s = slips[0]
        assert s["base_salary"] == "9000.00"
        assert s["absent_days"] == 3
        assert s["unpaid_leave_days"] == "3.0"
        # معدل يومي = 9000/30 = 300؛ خصم غياب = 300×6 = 1800
        assert s["absence_deduction"] == "1800.00"
        الإجمالي = Decimal(s["base_salary"]) + Decimal(s["total_earnings"])
        assert الإجمالي == Decimal("10000.00")  # 9000 + 1000 بونص
        # تأمينات = 10% من الأساس فقط (900)؛ الخصومات = 900 + غياب/إجازة 1800 = 2700
        assert s["total_deductions"] == "2700.00"
        # تأمينات = 10% من 9000 = 900; خصومات = 900 + 1800 = 2700 (تحقق حسابي أدق)
        lines = client.get(f"/hr/payslips/{s['id']}").json()
        cats = {l["category"]: [l["name"] for l in lines].count(l["name"]) for l in lines}
        assert any(l["category"] == "absence" for l in lines)
        assert any("تأمينات" in l["name"] for l in lines)
        net_expected = Decimal("10000.00") - (Decimal("900.00") + Decimal("1800.00"))
        assert Decimal(s["net_pay"]) == net_expected
        assert Decimal(run_data["total_net"]) == net_expected
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_payroll_post_creates_balanced_journal_and_locks_run():
    client, engine = _client()
    try:
        emp = client.post("/hr/employees", json={"full_name": "موظف القيد", "basic_salary": "5000"}).json()
        client.post("/hr/attendance", json={"employee_id": emp["id"], "work_date": "2026-10-01", "status": "absent"})

        first = client.post("/hr/payroll-runs", json={"year": 2026, "month": 10})
        assert first.status_code == 201, first.text
        rid = first.json()["id"]

        # تكرار نفس الشهر مرفوض
        dup = client.post("/hr/payroll-runs", json={"year": 2026, "month": 10})
        assert dup.status_code == 409

        posted = client.post(f"/hr/payroll-runs/{rid}/post", json={"note": "أكتوبر"})
        assert posted.status_code == 200, posted.text
        pj = posted.json()
        assert pj["status"] == "posted" and pj["journal_entry_id"] is not None

        # القيد في دفتر الأستاذ متوازن
        entry_id = pj["journal_entry_id"]
        # متاح عبر مسارات المحاسبة العامة (journal-entries)
        entry = client.get(f"/journal-entries/{entry_id}").json()
        debit = sum(Decimal(str(i["debit"])) for i in entry["items"])
        credit = sum(Decimal(str(i["credit"])) for i in entry["items"])
        assert debit == credit

        # لا حذف ولا إعادة حساب بعد الترحيل
        assert client.delete(f"/hr/payroll-runs/{rid}").status_code == 409
        assert client.post(f"/hr/payroll-runs/{rid}/recalculate").status_code == 409

        # مسير شهر آخر قابل للإنشاء والحذف كمسودّة
        other = client.post("/hr/payroll-runs", json={"year": 2026, "month": 9})
        assert other.status_code == 201
        assert client.delete(f"/hr/payroll-runs/{other.json()['id']}").status_code == 204
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_empty_payroll_run_or_skips_zero_salary_and_lists():
    client, engine = _client()
    try:
        # موظف بلا راتب: لا قسيمة له
        nosalary = client.post("/hr/employees", json={"full_name": "بلا راتب"}).json()
        run = client.post("/hr/payroll-runs", json={"year": 2026, "month": 1})
        assert run.status_code == 201
        rd = run.json()
        assert rd["employees_count"] == 0 and rd["total_net"] == "0.00"
        assert client.get(f"/hr/payroll-runs/{rd['id']}/payslips").json() == []

        # ترحيل مسير فارغ مرفوض
        assert client.post(f"/hr/payroll-runs/{rd['id']}/post", json={}).status_code == 422

        empty_list = client.get("/hr/payroll-runs?year=2030").json()
        assert empty_list == []
        runs = client.get("/hr/payroll-runs").json()
        assert len(runs) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
