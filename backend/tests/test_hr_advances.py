"""اختبارات S4: السلف بأقساط شهرية ضمن المسير، التسوية النهائية (EOSB/إجازات/سلف)، وملف WPS."""
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
    client.post("/auth/setup", json={"username": "adv-admin", "password": "strong-password-123"})
    token = client.post("/auth/login", data={"username": "adv-admin", "password": "strong-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_advance_installments_appear_in_runs_until_exhausted():
    client, engine = _client()
    try:
        emp = client.post("/hr/employees", json={"full_name": "خاطم بورهن", "basic_salary": "6000"}).json()
        adv = client.post("/hr/advances", json={
            "employee_id": emp["id"], "amount": "1200", "installments_count": 4,
            "start_year": 2026, "start_month": 3,
        })
        assert adv.status_code == 201, adv.text
        aid = adv.json()["id"]

        # مسير مارس: قسط 300
        run1 = client.post("/hr/payroll-runs", json={"year": 2026, "month": 3})
        assert run1.status_code == 201, run1.text
        slips1 = client.get(f"/hr/payroll-runs/{run1.json()['id']}/payslips").json()
        adv_lines1 = [l for l in client.get(f"/hr/payslips/{slips1[0]['id']}").json() if l["category"] == "deduction" and "سلفة" in l["name"]]
        assert len(adv_lines1) == 1 and Decimal(adv_lines1[0]["amount"]) == Decimal("300.00")

        # مسير أبريل: قسط ثانٍ؛ يناير (قبل البدء): بلا قسط
        run2 = client.post("/hr/payroll-runs", json={"year": 2026, "month": 4}).json()
        slips2 = client.get(f"/hr/payroll-runs/{run2['id']}/payslips").json()
        adv_lines2 = [l for l in client.get(f"/hr/payslips/{slips2[0]['id']}").json() if "سلفة" in l["name"]]
        assert len(adv_lines2) == 1 and Decimal(adv_lines2[0]["amount"]) == Decimal("300.00")

        run0 = client.post("/hr/payroll-runs", json={"year": 2026, "month": 1}).json()
        slips0 = client.get(f"/hr/payroll-runs/{run0['id']}/payslips").json()
        adv_lines0 = [l for l in client.get(f"/hr/payslips/{slips0[0]['id']}").json() if "سلفة" in l["name"]]
        assert adv_lines0 == []

        # مسيرات 3 و4 و5 و6 = 4 أقساط؛ المسير الخامس (7) بلا قسط
        for m in (5, 6, 7):
            r = client.post("/hr/payroll-runs", json={"year": 2026, "month": m}).json()
            lines = [l for l in client.get(f"/hr/payslips/{client.get(f'/hr/payroll-runs/{r['id']}/payslips').json()[0]['id']}").json() if "سلفة" in l["name"]]
            assert (len(lines) == 1) == (m <= 6), (m, lines)

        # حذف سلفة مُقسّطة مرفوض؛ تعطيلها مسموح
        assert client.delete(f"/hr/advances/{aid}").status_code == 409
        assert client.patch(f"/hr/advances/{aid}", json={"status": "cancelled"}).status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_settlement_eosb_unused_leave_and_advances_after_termination():
    client, engine = _client()
    try:
        # تعيين مبكر: 2020-01-01، إنهاء 2024-06-30 → 4.5 سنة تقريباً
        emp = client.post("/hr/employees", json={
            "full_name": "منهي الخدمة", "basic_salary": "9000",
            "hire_date": "2020-01-01", "bank_account": "SA0380000000608010167519", "national_id": "1020304050",
        }).json()
        # عقد نشط براتب (يحجب أساسي الموظف؟ نفس القيمة هنا)
        c = client.post(f"/hr/employees/{emp['id']}/contracts", json={
            "basic_salary": "9000", "start_date": "2020-01-01", "contract_type": "unlimited",
        })
        assert c.status_code == 201, c.text

        # سلفة 1000 على 10 أقساط بدأت مارس 2026 — لم تُقسَّط (بلا مسير) → تُخصم كاملة
        adv = client.post("/hr/advances", json={
            "employee_id": emp["id"], "amount": "1000", "installments_count": 10,
            "start_year": 2026, "start_month": 3,
        }).json()

        # رصيد إجازة مدفوعة متبقٍ 12 يوم + نوع غير مدفوع متبقٍ (لا يُعوَّض)
        lt = client.post("/hr/leave-types", json={"name": "سنوية", "days_per_year": "30"}).json()
        unpaid_lt = client.post("/hr/leave-types", json={"name": "غير مدفوعة", "days_per_year": "5", "is_paid": False}).json()
        client.get(f"/hr/leave-balances?employee_id={emp['id']}")
        bal_rows = client.get(f"/hr/leave-balances?year=2026&employee_id={emp['id']}").json()
        bal = next(b for b in bal_rows if b["leave_type_id"] == lt["id"])
        client.patch(f"/hr/leave-balances/{bal['id']}", json={"entitled_days": "15", "carried_days": "0"})
        # 3 أيام مستخدمة → متبقٍ 12
        req = client.post("/hr/leave-requests", json={
            "employee_id": emp["id"], "leave_type_id": lt["id"],
            "from_date": "2026-02-01", "to_date": "2026-02-03",
        }).json()
        client.post(f"/hr/leave-requests/{req['id']}/approve", json={})

        # تدخل طلب منتهي الخدمة قبل التسوية
        b4 = client.post(f"/hr/employees/{emp['id']}/settlement", json={})
        assert b4.status_code == 409

        # إنهاء الخدمة بتح moving وtermination
        move = client.post(f"/hr/employees/{emp['id']}/moves", json={
            "move_type": "termination",
            "effective_date": "2024-06-30",
            "reason": "استقالة",
        })
        assert move.status_code == 201, move.text

        # السلفة النشطة بلا مسير: التسوية تخصم كامل 1000
        s = client.post(f"/hr/employees/{emp['id']}/settlement", json={"note": "تسوية"}).json()
        service_days = (2049492064150 - 0) if False else None  # حساب مستقل أدناه
        from datetime import date
        expected_days = (date(2024, 6, 30) - date(2020, 1, 1)).days + 1
        assert s["service_days"] == expected_days
        years = Decimal(expected_days) / Decimal("365.25")
        expected_eosb_days = (min(years, Decimal(5)) * 21 + max(Decimal(0), years - 5) * 30).quantize(
            Decimal("0.1")
        )
        expected_eosb = (Decimal("9000") / 30 * expected_eosb_days).quantize(Decimal("0.01"))
        assert Decimal(s["eosb_days"]) == expected_eosb_days
        assert Decimal(s["eosb_amount"]) == expected_eosb
        # رصيد المتبقي من الإجازات المدفوعة: 15 - 3 = 12 يوم → 3600
        assert Decimal(s["unused_leave_days"]) == Decimal("12.0")
        assert Decimal(s["unused_leave_amount"]) == Decimal("3600.00")
        # متبقٍ سلفة: 1000 (لم تُقسَّط)
        assert Decimal(s["advances_remaining"]) == Decimal("1000.00")
        assert Decimal(s["total_due"]) == expected_eosb + Decimal("3600.00") - Decimal("1000.00")

        # تسوية ثانية لنفس الموظف مرفوضة
        again = client.post(f"/hr/employees/{emp['id']}/settlement", json={})
        assert again.status_code == 409

        # قائمة التسويات تحوي السجل
        listed = client.get("/hr/settlements").json()
        assert len(listed) == 1 and listed[0]["total_due"] == s["total_due"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_wps_download_after_posting_only():
    client, engine = _client()
    try:
        emp = client.post("/hr/employees", json={
            "full_name": "موظف WPS", "basic_salary": "8000",
            "bank_account": "SA03 8000 0000 6080 1016 7519", "national_id": "1098765432",
        }).json()
        r = client.post("/hr/payroll-runs", json={"year": 2026, "month": 6}).json()

        # قبل الترحيل مرفوض
        assert client.get(f"/hr/payroll-runs/{r['id']}/wps.csv").status_code == 409

        posted = client.post(f"/hr/payroll-runs/{r['id']}/post", json={})
        assert posted.status_code == 200, posted.text

        resp = client.get(f"/hr/payroll-runs/{r['id']}/wps.csv")
        assert resp.status_code == 200
        assert "attachment" in resp.headers["content-disposition"] and resp.headers["content-disposition"].endswith(".csv\"")
        body = resp.text
        assert "EMP_CODE" in body and "NET_AMOUNT" in body
        assert emp["code"] in body and "8000.00" in body
        assert "TOTAL" in body and "WPS,2026-06" in body
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_hr_efficiency_features():
    """حدود السلف + استيراد الحضور + بذر مكونات مصر."""
    from datetime import date, timedelta

    c, _engine = _client()
    h = {}  # الـ client مضبوط بالتوكن من _client

    # 1) بذر مكونات مصر: لأول موظف — 2 مكونات، والاستدعاء الثاني يتخطاها
    emp = c.post("/hr/employees", headers=h, json={"full_name": "موظف الخصومات", "basic_salary": "6000", "code": "EG-1"}).json()
    resp = c.post("/hr/payroll/seed-eg-components", headers=h, json={"employee_ids": [emp["id"]]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["created_count"] == 2 and resp.json()["employees"] == 1
    resp = c.post("/hr/payroll/seed-eg-components", headers=h, json={"employee_ids": [emp["id"]]})
    assert resp.json()["created_count"] == 0 and resp.json()["skipped_count"] == 2

    # 2) استيراد حضور: سطران صحيحان + سطر بكود خاطئ
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    resp = c.post("/hr/attendance/import", headers=h, json={"rows": [
        {"employee_code": "EG-1", "work_date": date.today().isoformat(), "check_in": "08:00", "check_out": "16:00"},
        {"employee_code": "EG-1", "work_date": tomorrow, "check_in": "08:30", "check_out": "16:30", "status": "late"},
        {"employee_code": "UNKNOWN", "work_date": tomorrow},
    ]})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 2 and len(data["errors"]) == 1 and "UNKNOWN" in data["errors"][0]

    # upsert: نفس اليوم مرة أخرى → تحديث لا إنشاء
    resp = c.post("/hr/attendance/import", headers=h, json={"rows": [
        {"employee_code": "EG-1", "work_date": date.today().isoformat(), "check_in": "08:05", "check_out": "16:10", "status": "late"},
    ]})
    assert resp.json()["updated"] == 1 and resp.json()["created"] == 0

    # 3) حدود السلف: مدير عادي بحد 1000 — ما يزيد يُرفض، ومدير المنصة يتجاوز دائمًا
    mgr = c.post("/auth/users", headers=h, json={
        "username": "adv-mgr", "password": "manager-pass-123", "role": "manager", "full_name": "مدير السلف",
    }).json()
    resp = c.put(f"/hr/approval-limits/{mgr['id']}", headers=h, json={"max_amount": 1000})
    assert resp.status_code == 200, resp.text
    page = c.get("/hr/approval-limits", headers=h).json()
    assert any(l["user_id"] == mgr["id"] and l["max_amount"] == 1000 for l in page["limits"])

    mgr_token = c.post("/auth/login", data={"username": "adv-mgr", "password": "manager-pass-123"}).json()["access_token"]
    mh = {"Authorization": f"Bearer {mgr_token}"}
    emp2 = c.post("/hr/employees", headers=mh, json={"full_name": "موظف سلفة", "code": "EG-2"}).json()

    over = c.post("/hr/advances", headers=mh, json={
        "employee_id": emp2["id"], "amount": 2500, "installments_count": 2,
        "start_year": date.today().year, "start_month": date.today().month,
    })
    assert over.status_code == 403, over.text
    assert "تتجاوز حد الموافقة" in over.text

    # داخل الحد → ينشئ عادي
    ok_adv = c.post("/hr/advances", headers=mh, json={
        "employee_id": emp2["id"], "amount": 900, "installments_count": 2,
        "start_year": date.today().year, "start_month": date.today().month,
    })
    assert ok_adv.status_code == 201, ok_adv.text

    # مدير المنصة يتجاوز الحد (سلفة أكبر على نفس الموظف)
    plat_adv = c.post("/hr/advances", headers=h, json={
        "employee_id": emp2["id"], "amount": 9000, "installments_count": 3,
        "start_year": date.today().year, "start_month": date.today().month,
    })
    assert plat_adv.status_code == 201, plat_adv.text

    # إلغاء الحد → المدير يعود غير محدود
    c.put(f"/hr/approval-limits/{mgr['id']}", headers=h, json={"max_amount": None})
    ok_adv2 = c.post("/hr/advances", headers=mh, json={
        "employee_id": emp2["id"], "amount": 5000, "installments_count": 3,
        "start_year": date.today().year, "start_month": date.today().month,
    })
    assert ok_adv2.status_code == 201, ok_adv2.text


def test_bulk_salary_component_update():
    """التحديث الجماعي: تعديل نسبة التأمينات لكل الموظفين من مكان واحد بعد البذر."""
    from datetime import date

    c, _engine = _client()
    h = {}

    # بذر لاثنين من الموظفين
    e1 = c.post("/hr/employees", headers=h, json={"full_name": "بذر ١", "code": "BULK-1", "basic_salary": "5000"}).json()
    e2 = c.post("/hr/employees", headers=h, json={"full_name": "بذر ٢", "code": "BULK-2", "basic_salary": "7000"}).json()
    c.post("/hr/payroll/seed-eg-components", headers=h, json={"employee_ids": [e1["id"], e2["id"]]})

    # تحديث جماعي: نسبة التأمينات 11 → 13
    resp = c.patch("/hr/salary-components/bulk", headers=h, json={
        "name": "التأمينات الاجتماعية (حصة الموظف)", "category": "deduction", "percent_value": 13.0,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated_count"] == 2

    # القيم تغيرت فعلًا
    rows = c.get(f"/hr/salary-components?employee_id={e1['id']}", headers=h).json()
    ins = next(r for r in rows if r["name"] == "التأمينات الاجتماعية (حصة الموظف)")
    assert float(ins["percent_value"]) == 13.0
    rows2 = c.get(f"/hr/salary-components?employee_id={e2['id']}", headers=h).json()
    ins2 = next(r for r in rows2 if r["name"] == "التأمينات الاجتماعية (حصة الموظف)")
    assert float(ins2["percent_value"]) == 13.0

    # اسم غير موجود → صفر تحديث
    resp = c.patch("/hr/salary-components/bulk", headers=h, json={"name": "غير موجود", "percent_value": 5})
    assert resp.json()["updated_count"] == 0

    # تعطيل جماعي ثم إعادة تفعيل
    resp = c.patch("/hr/salary-components/bulk", headers=h, json={"name": "ضريبة الدخل المصري", "is_active": False})
    assert resp.json()["updated_count"] == 2
    rows = c.get(f"/hr/salary-components?employee_id={e1['id']}", headers=h).json()
    tax = next(r for r in rows if r["name"] == "ضريبة الدخل المصري")
    assert tax["is_active"] is False
    resp = c.patch("/hr/salary-components/bulk", headers=h, json={"name": "ضريبة الدخل المصري", "is_active": True})
    assert resp.json()["updated_count"] == 2
