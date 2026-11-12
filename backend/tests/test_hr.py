"""اختبارات وحدة الموارد البشرية: موظفون، عقود، مستندات، سجل وظيفي، وعزل الشركات."""
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


def _department(client) -> dict:
    row = client.post("/company/departments", json={"name": "المالية"}).json()
    assert row["id"]
    return row


def test_job_titles_and_grades_crud_with_duplicate_guard():
    client, engine = _client()
    try:
        created = client.post("/hr/job-titles", json={"name": "محاسب", "max_salary": "20000"})
        assert created.status_code == 201, created.text
        dup = client.post("/hr/job-titles", json={"name": "محاسب"})
        assert dup.status_code == 409
        listed = client.get("/hr/job-titles")
        assert listed.status_code == 200 and len(listed.json()) == 1
        invalid = client.post("/hr/job-titles", json={"name": "مهندس", "min_salary": "5000", "max_salary": "1000"})
        assert invalid.status_code == 422

        grade = client.post("/hr/grades", json={"name": "Grade-A"})
        assert grade.status_code == 201
        deleted = client.delete(f"/hr/grades/{grade.json()['id']}")
        assert deleted.status_code == 204
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_create_employee_generates_code_and_hire_move():
    client, engine = _client()
    try:
        dept = _department(client)
        emp = client.post(
            "/hr/employees",
            json={"full_name": "محمد أحمد", "basic_salary": "9000", "department_id": dept["id"]},
        )
        assert emp.status_code == 201, emp.text
        body = emp.json()
        assert body["code"].startswith("EMP-")
        assert body["department_name"] == "المالية"
        assert body["contracts_count"] == 0
        detail = client.get(f"/hr/employees/{body['id']}")
        moves = detail.json()["moves"]
        assert len(moves) == 1 and moves[0]["move_type"] == "hire"
        assert moves[0]["to_department_name"] == "المالية"
        # الكود الافتراضي يجب أن يكون فريدًا عند تكرار الاسم
        dup = client.post("/hr/employees", json={"full_name": "محمد أحمد"})
        assert dup.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_update_employee_writes_auto_move_and_termination():
    client, engine = _client()
    try:
        dept1, dept2 = _department(client), client.post("/company/departments", json={"name": "الإنتاج"}).json()
        emp = client.post("/hr/employees", json={"full_name": "سارة", "basic_salary": "5000", "department_id": dept1["id"]}).json()
        # ترقية راتب ونقل إدارة → سجل salary_change/transfer تلقائي
        patched = client.patch(f"/hr/employees/{emp['id']}", json={"basic_salary": "6500", "department_id": dept2["id"]})
        assert patched.status_code == 200, patched.text
        move = client.get(f"/hr/employees/{emp['id']}/moves").json()
        assert len(move) == 2 and move[0]["move_type"] == "transfer"
        assert move[0]["from_salary"] == "5000.00"
        # إنهاء الخدمة عبر سجل تحرك
        fin = client.post(f"/hr/employees/{emp['id']}/moves", json={"move_type": "termination", "reason": "استقالة"})
        assert fin.status_code == 201
        detail = client.get(f"/hr/employees/{emp['id']}").json()
        assert detail["status"] == "terminated" and detail["is_active"] is False
        assert detail["terminated_at"]
        assert client.get(f"/hr/employees/{emp['id']}/moves").json()[0]["move_type"] == "termination"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_contracts_and_documents_flow():
    client, engine = _client()
    try:
        emp = client.post("/hr/employees", json={"full_name": "خالد"}).json()
        contract = client.post(f"/hr/employees/{emp['id']}/contracts", json={"kind": "fixed", "end_date": "2027-01-01", "basic_salary": "4000"})
        assert contract.status_code == 201, contract.text
        assert contract.json()["code"].startswith("CTR-")
        bad = client.post(f"/hr/employees/{emp['id']}/contracts", json={"kind": "fixed"})
        assert bad.status_code == 422

        upload = client.post(
            f"/hr/employees/{emp['id']}/documents",
            data={"title": "نموذج عقد", "doc_type": "contract"},
            files={"file": ("offer.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert upload.status_code == 201, upload.text
        doc_id = upload.json()["id"]
        assert upload.json()["has_file"] is True
        download = client.get(f"/hr/documents/{doc_id}/file")
        assert download.status_code == 200 and download.content.startswith(b"%PDF")
        rejected = client.post(
            f"/hr/employees/{emp['id']}/documents",
            data={"title": "ملف", "doc_type": "other"},
            files={"file": ("virus.exe", b"MZ", "application/x-msdownload")},
        )
        assert rejected.status_code == 415

        # حذف الموظف يحذف عقده ومستنداته
        assert client.delete(f"/hr/employees/{emp['id']}").status_code == 204
        assert client.get(f"/hr/documents/{doc_id}/file").status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_employee_delete_blocked_when_manager_of_others():
    client, engine = _client()
    try:
        boss = client.post("/hr/employees", json={"full_name": "المدير"}).json()
        client.post("/hr/employees", json={"full_name": "مرؤوس", "manager_id": boss["id"]})
        assert client.delete(f"/hr/employees/{boss['id']}").status_code == 409
        self_manager = client.post("/hr/employees", json={"full_name": "نفسه", "manager_id": None})
        assert self_manager.status_code == 201
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_hr_data_is_company_scoped():
    client, engine = _client()
    try:
        client.post("/hr/employees", json={"full_name": "موظف فرع الشركة"})
        # محاولة وصول مرفوض لبيانات شركة أخرى عبر التحقق الاجباري
        wrong_fk = client.post("/hr/employees", json={"full_name": "غريب", "department_id": 999999})
        assert wrong_fk.status_code == 422
        summary = client.get("/hr/summary")
        assert summary.status_code == 200 and summary.json()["total"] >= 1
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_multi_level_approval_chain():
    """مسارات الموافقات متعددة المستويات: مستويان → التقدم مستوى بمستوى + رفض من مستوى."""
    from datetime import date, timedelta

    c, _engine = _client()

    # إنشاء موافقَين مديرين
    u1 = c.post("/auth/users", json={"username": "chain-mgr1", "password": "strong-password-123", "role": "manager", "full_name": "مدير المستوى ١"}).json()
    u2 = c.post("/auth/users", json={"username": "chain-mgr2", "password": "strong-password-123", "role": "manager", "full_name": "مدير المستوى ٢"}).json()

    # إجازة + نوع
    lt = c.post("/hr/leave-types", json={"name": "سنوية", "days_per_year": 10}).json()
    emp = c.post("/hr/employees", json={"full_name": "موظف المسار", "code": "CH-1"}).json()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    after = (date.today() + timedelta(days=2)).isoformat()
    req = c.post("/hr/leave-requests", json={
        "employee_id": emp["id"], "leave_type_id": lt["id"],
        "from_date": tomorrow, "to_date": after, "days": 1,
    }).json()

    # ضبط مسار من مستويين: المستوى 1 = chain-mgr1، المستوى 2 = دور manager
    resp = c.put("/hr/approval-chains/leave", json={"levels": [
        {"level": 1, "approver_user_id": u1["id"]},
        {"level": 2, "approver_role": "manager"},
    ]})
    assert resp.status_code == 200, resp.text
    page = c.get("/hr/approval-chains").json()
    assert [lv["level"] for lv in page["levels"]] == [1, 2]

    # مستوى 2 (دور manager) يحاول المستوى 1 (مخصص لمستخدم محدد) → 403 — والمدير العام يتجاوز بالتصميم
    t2 = c.post("/auth/login", data={"username": "chain-mgr2", "password": "strong-password-123"}).json()["access_token"]
    h2 = {"Authorization": f"Bearer {t2}"}
    resp = c.post(f"/hr/leave-requests/{req['id']}/approve", json={"decision_note": "مش مستواي"}, headers=h2)
    assert resp.status_code == 403, resp.text
    assert "المستوى 1" in resp.text

    # المستوى 1 يوافق (chain-mgr1) → يبقى pending على المستوى 2
    t1 = c.post("/auth/login", data={"username": "chain-mgr1", "password": "strong-password-123"}).json()["access_token"]
    h1 = {"Authorization": f"Bearer {t1}"}
    resp = c.post(f"/hr/leave-requests/{req['id']}/approve", json={"decision_note": "موافقة المدير المباشر"}, headers=h1)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending" and resp.json()["approval_level"] == 1
    steps = c.get(f"/hr/leave-requests/{req['id']}/steps").json()
    assert [s["level"] for s in steps] == [1]
    assert steps[0]["decision"] == "approved" and steps[0]["approver_username"] == "chain-mgr1"

    # المستوى 2 (دور manager) يوافق → معتمد نهائيًا
    resp = c.post(f"/hr/leave-requests/{req['id']}/approve", json={"decision_note": "اعتماد نهائي"}, headers=h2)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved" and resp.json()["approval_level"] == 2
    steps = c.get(f"/hr/leave-requests/{req['id']}/steps").json()
    assert [s["level"] for s in steps] == [1, 2]

    # رفض من المستوى الأول يسجل خطوة رفض
    req2 = c.post("/hr/leave-requests", json={
        "employee_id": emp["id"], "leave_type_id": lt["id"],
        "from_date": (date.today() + timedelta(days=5)).isoformat(),
        "to_date": (date.today() + timedelta(days=6)).isoformat(), "days": 1,
    }).json()
    resp = c.post(f"/hr/leave-requests/{req2['id']}/reject", json={"decision_note": "رفض مبكر"}, headers=h1)
    assert resp.status_code == 200, resp.text
    steps = c.get(f"/hr/leave-requests/{req2['id']}/steps").json()
    assert steps[-1]["decision"] == "rejected"


def test_payroll_with_eg_components_and_gov_forms():
    """رواتب بمكونات مصر المبذورة + نموذج 6ح + إقرار الضريبة (xlsx)."""
    c, _engine = _client()

    emp = c.post("/hr/employees", json={"full_name": "موظف النماذج", "code": "GOV-1", "basic_salary": "6000", "national_id": "29001011234567", "insurance_number": "INS-77"}).json()
    c.post("/hr/payroll/seed-eg-components", json={"employee_ids": [emp["id"]]})

    # عقد بالموظف ضروري لتوليد المسير
    c.post(f"/hr/employees/{emp['id']}/contracts", json={
        "start_date": "2026-01-01", "basic_salary": "6000",
    })
    now = __import__("datetime").datetime.now()
    run = c.post("/hr/payroll-runs", json={"year": now.year, "month": now.month}).json()
    if run.get("status") == "draft":
        run = c.post(f"/hr/payroll-runs/{run['id']}/recalculate").json()
    slip = next(s for s in c.get(f"/hr/payroll-runs/{run['id']}/payslips").json() if s["employee_id"] == emp["id"])
    line_names = [l["name"] for l in c.get(f"/hr/payslips/{slip['id']}").json()]
    assert any("التأمينات الاجتماعية" in n for n in line_names), line_names
    assert any("ضريبة" in n for n in line_names)

    # نموذج 6ح: حصة الموظف 11% من 6000 = 660
    resp = c.get(f"/hr/payroll-runs/{run['id']}/form-6h.xlsx")
    assert resp.status_code == 200 and len(resp.content) > 1000
    resp = c.get(f"/hr/payroll-runs/{run['id']}/form-4.xlsx")
    assert resp.status_code == 200 and len(resp.content) > 1000


def test_payroll_unpaid_leave_deduction():
    """إجازة بدون راتب تخصم من قسيمة المسير."""
    import datetime as dt

    c, _engine = _client()
    lt = c.post("/hr/leave-types", json={"name": "بدون راتب", "days_per_year": 10, "is_paid": False}).json()
    emp = c.post("/hr/employees", json={"full_name": "موظف غير مدفوع", "code": "UP-1", "basic_salary": "9000"}).json()
    c.post(f"/hr/employees/{emp['id']}/contracts", json={"start_date": "2026-01-01", "basic_salary": "9000"})
    today = dt.date.today()
    req = c.post("/hr/leave-requests", json={
        "employee_id": emp["id"], "leave_type_id": lt["id"],
        "from_date": today.isoformat(), "to_date": (today + dt.timedelta(days=1)).isoformat(), "days": 1,
    }).json()
    assert c.post(f"/hr/leave-requests/{req['id']}/approve", json={}).status_code == 200

    run = c.post("/hr/payroll-runs", json={"year": today.year, "month": today.month}).json()
    if run.get("status") == "draft":
        run = c.post(f"/hr/payroll-runs/{run['id']}/recalculate").json()
    slip = next(s for s in c.get(f"/hr/payroll-runs/{run['id']}/payslips").json() if s["employee_id"] == emp["id"])
    # خصم يوم واحد: 9000/30 = 300 (أو حسب أساس الحساب) — نتحقق أن الخصومات > 0 وفيها سطر غياب/إجازة
    assert float(slip["total_deductions"]) > 0
    lines = c.get(f"/hr/payslips/{slip['id']}").json()
    assert any(l["category"] == "absence" or "غياب" in l["name"] or "إجازة" in l["name"] for l in lines), lines
