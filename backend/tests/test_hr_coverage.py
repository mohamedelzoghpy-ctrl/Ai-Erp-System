"""تغطية السيناريوهات الحرجة للموارد البشرية: الرواتب (غياب/مكوّنات/سلف/نطاق)، التسوية، التصحيحات، الأرصدة، التحليلات، WPS.

كل اختبار يبني عالماً منفصلاً بمحرك SQLite خاص — بلا تلوث بين الاختبارات.
"""

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


def _client():
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
    client.post("/auth/setup", json={"username": "hr-admin", "password": "strong-password-123"})
    token = client.post("/auth/login", data={"username": "hr-admin", "password": "strong-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def _next_month(y: int, m: int):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _mk_emp(c, code, salary="6000", **extra):
    return c.post("/hr/employees", json={"full_name": f"موظف {code}", "code": code, "basic_salary": salary, **extra}).json()


def _mk_contract(c, emp_id, salary="6000"):
    return c.post(f"/hr/employees/{emp_id}/contracts", json={"start_date": "2026-01-01", "basic_salary": salary}).json()


def _mk_run(c, y, m):
    run = c.post("/hr/payroll-runs", json={"year": y, "month": m}).json()
    assert run["status"] == "draft", run
    return run


def _slip_for(c, run_id, emp_id):
    slips = c.get(f"/hr/payroll-runs/{run_id}/payslips").json()
    return next(s for s in slips if s["employee_id"] == emp_id)


# --------------------------------------------------------------- 1) خصم الغياب
def test_absent_days_deduction():
    """غياب موثق في الحضور → خصم = (الأساسي ÷ أيام الشهر) × أيام الغياب."""
    c, _engine = _client()
    today = dt.date.today()
    emp = _mk_emp(c, "ABS-1", "6000")
    _mk_contract(c, emp["id"], "6000")
    for d in (today - dt.timedelta(days=1), today):
        r = c.post("/hr/attendance", json={"employee_id": emp["id"], "work_date": d.isoformat(), "status": "absent"})
        assert r.status_code in (200, 201), r.text

    run = _mk_run(c, today.year, today.month)
    slip = _slip_for(c, run["id"], emp["id"])
    days_in_month = (dt.date(today.year, today.month, 28) - dt.date(today.year, today.month, 1)).days + 28 // 28
    days_in_month = 30 if today.month in (4, 6, 9, 11) else (31 if today.month != 2 else 28)
    expected = round(6000 / days_in_month * 2, 2)
    assert float(slip["absence_deduction"]) == expected, slip
    assert float(slip["net_pay"]) == round(6000 - expected, 2)
    lines = c.get(f"/hr/payslips/{slip['id']}").json()
    assert any(l["category"] == "absence" for l in lines)


# --------------------------------------------------------------- 2) مكون earning مئوي
def test_percent_earning_component_in_payslip():
    """مكافأة 10% من الأساسي → سطر earning + إجمالي المستحقات + الصافي."""
    c, _engine = _client()
    today = dt.date.today()
    emp = _mk_emp(c, "BON-1", "5000")
    _mk_contract(c, emp["id"], "5000")
    r = c.post("/hr/salary-components", json={
        "employee_id": emp["id"], "category": "earning", "name": "مكافأة أداء",
        "amount_mode": "percent_of_base", "percent_value": 10,
    })
    assert r.status_code == 201, r.text

    run = _mk_run(c, today.year, today.month)
    slip = _slip_for(c, run["id"], emp["id"])
    assert float(slip["total_earnings"]) == 500.0
    assert float(slip["net_pay"]) == 5500.0
    lines = c.get(f"/hr/payslips/{slip['id']}").json()
    assert any(l["name"] == "مكافأة أداء" and float(l["amount"]) == 500.0 for l in lines)


# --------------------------------------------------------------- 3) إجازة غير مدفوعة تعبر حدود الشهر
def test_unpaid_leave_month_overlap():
    """إجازة غير مدفوعة تعبر الشهرين → خصم أيام التداخل فقط في كل مسير."""
    c, _engine = _client()
    today = dt.date.today()
    lt = c.post("/hr/leave-types", json={"name": "بدون راتب-تغطية", "days_per_year": 15, "is_paid": False}).json()
    emp = _mk_emp(c, "UNP-1", "9000")
    _mk_contract(c, emp["id"], "9000")

    start = dt.date(today.year, today.month, 25)
    end = start + dt.timedelta(days=7)  # يمتد للشهر التالي
    req = c.post("/hr/leave-requests", json={
        "employee_id": emp["id"], "leave_type_id": lt["id"],
        "from_date": start.isoformat(), "to_date": end.isoformat(),
    })
    assert req.status_code == 201, req.text
    assert c.post(f"/hr/leave-requests/{req.json()['id']}/approve", json={}).status_code == 200

    run = _mk_run(c, today.year, today.month)
    slip = _slip_for(c, run["id"], emp["id"])
    assert float(slip["unpaid_leave_days"]) > 0
    assert float(slip["absence_deduction"]) > 0
    days_in_month = 30 if today.month in (4, 6, 9, 11) else (31 if today.month != 2 else 28)
    daily = round(9000 / days_in_month, 2)
    assert float(slip["absence_deduction"]) == round(daily * float(slip["unpaid_leave_days"]), 2)


# --------------------------------------------------------------- 4) أقساط السلف حتى النفاد
def test_advance_installments_exhaust_then_stop():
    """سلفة 900 على 3 أقساط → 300 في ثلاثة مسيرات ثم لا قسط في الرابع."""
    c, _engine = _client()
    today = dt.date.today()
    y, m = today.year, today.month
    emp = _mk_emp(c, "ADV-X", "6000")
    _mk_contract(c, emp["id"], "6000")
    adv = c.post("/hr/advances", json={
        "employee_id": emp["id"], "amount": 900, "installments_count": 3,
        "start_year": y, "start_month": m,
    }).json()

    for i in range(3):
        run = _mk_run(c, y, m)
        slip = _slip_for(c, run["id"], emp["id"])
        lines = c.get(f"/hr/payslips/{slip['id']}").json()
        adv_lines = [l for l in lines if l["name"].startswith("قسط سلفة")]
        assert len(adv_lines) == 1 and float(adv_lines[0]["amount"]) == 300.0, (i, lines)
        y, m = _next_month(y, m)
        if (y, m) > (dt.date.today().year + 1, dt.date.today().month):
            break

    run4 = _mk_run(c, y, m)
    slip4 = _slip_for(c, run4["id"], emp["id"])
    lines4 = c.get(f"/hr/payslips/{slip4['id']}").json()
    assert not [l for l in lines4 if l["name"].startswith("قسط سلفة")], lines4


# --------------------------------------------------------------- 5) منع تكرار شهر
def test_duplicate_run_month_blocked():
    c, _engine = _client()
    today = dt.date.today()
    assert c.post("/hr/payroll-runs", json={"year": today.year, "month": today.month}).status_code == 201
    dup = c.post("/hr/payroll-runs", json={"year": today.year, "month": today.month})
    assert dup.status_code == 409
    assert "بالفعل" in dup.text


# --------------------------------------------------------------- 6) المسير المُرحَّل مجمد
def test_posted_run_is_immutable():
    c, _engine = _client()
    today = dt.date.today()
    _mk_emp(c, "PST-1", "4000")
    run = _mk_run(c, today.year, today.month)
    posted = c.post(f"/hr/payroll-runs/{run['id']}/post", json={})
    assert posted.status_code == 200 and posted.json()["status"] == "posted"

    recalc = c.post(f"/hr/payroll-runs/{run['id']}/recalculate")
    assert recalc.status_code == 409 and "مُرحَّل" in recalc.text
    repost = c.post(f"/hr/payroll-runs/{run['id']}/post", json={})
    assert repost.status_code == 409


# --------------------------------------------------------------- 7) مسيران مستقلان لنفس الموظف
def test_two_runs_independent_payslips():
    c, _engine = _client()
    today = dt.date.today()
    y, m = today.year, today.month
    emp = _mk_emp(c, "TWO-1", "6000")
    _mk_contract(c, emp["id"], "6000")

    run1 = _mk_run(c, y, m)
    y2, m2 = _next_month(y, m)
    run2 = _mk_run(c, y2, m2)

    s1 = _slip_for(c, run1["id"], emp["id"])
    s2 = _slip_for(c, run2["id"], emp["id"])
    assert s1["id"] != s2["id"]
    assert float(s1["net_pay"]) == 6000.0 and float(s2["net_pay"]) == 6000.0
    assert run2["employees_count"] == run1["employees_count"] == 1


# --------------------------------------------------------------- 8) المنتهي خدمته يُستبعد من المسير التالي
def test_terminated_excluded_from_next_run():
    c, _engine = _client()
    today = dt.date.today()
    y, m = today.year, today.month
    emp = _mk_emp(c, "TRM-1", "6000")
    _mk_contract(c, emp["id"], "6000")

    run1 = _mk_run(c, y, m)
    assert run1["employees_count"] == 1

    move = c.post(f"/hr/employees/{emp['id']}/moves", json={
        "move_type": "termination", "effective_date": today.isoformat(), "reason": "استقالة",
    })
    assert move.status_code == 201, move.text

    y2, m2 = _next_month(y, m)
    run2 = _mk_run(c, y2, m2)
    slips = c.get(f"/hr/payroll-runs/{run2['id']}/payslips").json()
    assert all(s["employee_id"] != emp["id"] for s in slips)

    # التسوية النهائية بعد الإنهاء تعمل
    s = c.post(f"/hr/employees/{emp['id']}/settlement", json={"note": "تسوية منتصف الشهر"})
    assert s.status_code == 201, s.text
    assert s.json()["service_days"] >= 0


# --------------------------------------------------------------- 9) تصحيح الحضور (ESS → اعتماد → تحديث السجل)
def test_attendance_correction_flow():
    c, _engine = _client()
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    emp = _mk_emp(c, "COR-1", "5000")
    c.patch(f"/hr/employees/{emp['id']}", json={"user_id": 1})

    corr = c.post("/hr/me/attendance-corrections", json={
        "work_date": yesterday.isoformat(), "requested_check_in": "09:00", "requested_check_out": "17:30",
        "reason": "نسيت البصمة",
    })
    assert corr.status_code == 201, corr.text
    corr_id = corr.json()["id"]

    approved = c.post(f"/hr/attendance-corrections/{corr_id}/approve", json={})
    assert approved.status_code == 200, approved.text

    rows = c.get("/hr/attendance?employee_id=" + str(emp["id"])).json()
    row = next(r for r in rows if r["work_date"] == yesterday.isoformat())
    assert row["check_in"] == "09:00" and row["check_out"] == "17:30"


# --------------------------------------------------------------- 10) رصيد الإجازة: خصم عند الاعتماد وعودة عند الإلغاء
def test_leave_balance_deduct_and_restore():
    c, _engine = _client()
    today = dt.date.today()
    lt = c.post("/hr/leave-types", json={"name": "سنوية-رصيد", "days_per_year": 10}).json()
    emp = _mk_emp(c, "BAL-1", "5000")
    c.get(f"/hr/leave-balances?employee_id={emp['id']}&year={today.year}")
    bals = c.get(f"/hr/leave-balances?year={today.year}&employee_id={emp['id']}").json()
    bal = next(b for b in bals if b["leave_type_id"] == lt["id"])
    c.patch(f"/hr/leave-balances/{bal['id']}", json={"entitled_days": "10"})

    start = today + dt.timedelta(days=1)
    req = c.post("/hr/leave-requests", json={
        "employee_id": emp["id"], "leave_type_id": lt["id"],
        "from_date": start.isoformat(), "to_date": (start + dt.timedelta(days=2)).isoformat(),
    }).json()
    assert c.post(f"/hr/leave-requests/{req['id']}/approve", json={}).status_code == 200

    bals = c.get(f"/hr/leave-balances?year={today.year}&employee_id={emp['id']}").json()
    bal = next(b for b in bals if b["leave_type_id"] == lt["id"])
    assert float(bal["used_days"]) == 3.0 and float(bal["remaining_days"]) == 7.0

    c.post(f"/hr/leave-requests/{req['id']}/cancel")
    bals = c.get(f"/hr/leave-balances?year={today.year}&employee_id={emp['id']}").json()
    bal = next(b for b in bals if b["leave_type_id"] == lt["id"])
    assert float(bal["used_days"]) == 0.0 and float(bal["remaining_days"]) == 10.0


# --------------------------------------------------------------- 11) التحليلات: بنية سليمة
def test_analytics_endpoint_shape():
    c, _engine = _client()
    _mk_emp(c, "AN-1", "6000")
    d = c.get("/hr/analytics").json()
    assert d["attendance"]["attendance_rate"] >= 0
    assert d["turnover"]["headcount"] >= 1
    assert "pending_requests" in d["leaves"]
    assert "recruiting" in d and "talent" in d and "payroll" in d


# --------------------------------------------------------------- 12) WPS محتوى فعلي
def test_wps_csv_content():
    c, _engine = _client()
    today = dt.date.today()
    emp = _mk_emp(c, "WPS-C1", "4500")
    run = _mk_run(c, today.year, today.month)
    coa = c.get("/chart-of-accounts")
    assert coa.status_code == 200, coa.text[:200]
    posted = c.post(f"/hr/payroll-runs/{run['id']}/post", json={})
    assert posted.status_code == 200

    resp = c.get(f"/hr/payroll-runs/{run['id']}/wps.csv")
    assert resp.status_code == 200
    body = resp.text
    assert emp["full_name"] in body
    assert "4500" in body
