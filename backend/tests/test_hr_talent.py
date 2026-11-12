"""اختبارات S6: التوظيف (ATS) + الأداء + التدريب + لوحة التحليلية."""
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
    client.post("/auth/setup", json={"username": "talent-admin", "password": "strong-password-123"})
    token = client.post("/auth/login", data={"username": "talent-admin", "password": "strong-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_recruiting_lifecycle_and_hire():
    client, engine = _client()
    try:
        posting = client.post("/hr/job-postings", json={"title": "محاسب أول", "openings": 1}).json()
        assert posting["code"].startswith("JOB-") and posting["status"] == "open"

        a1 = client.post(f"/hr/job-postings/{posting['id']}/applicants", json={
            "full_name": "مرشح محاسبة", "email": "cand1@example.com", "source": "لينكدإن",
        })
        assert a1.status_code == 201, a1.text
        # بريد مكرر لنفس الإعلان
        assert client.post(f"/hr/job-postings/{posting['id']}/applicants", json={
            "full_name": "مرشح محاسبة ثانٍ", "email": "CAND1@example.com",
        }).status_code == 409

        aid = a1.json()["id"]
        # تدرّج: applied → screening → interview → offer
        for expected in ("screening", "interview", "offer"):
            adv = client.post(f"/hr/applicants/{aid}/advance")
            assert adv.status_code == 200 and adv.json()["stage"] == expected
        # التعيين قبل offer ممنوع — بعد offer يعمل
        assert client.post(f"/hr/applicants/{aid}/reject", json={}).status_code == 200

        # مرشح ثانٍ: تعيين من مرحلة غير offer مرفوض
        a2 = client.post(f"/hr/job-postings/{posting['id']}/applicants", json={
            "full_name": "مرشح مختصر", "email": "cand2@example.com",
        }).json()
        early = client.post(f"/hr/applicants/{a2['id']}/hire", json={})
        assert early.status_code == 409

        for expected in ("screening", "interview", "offer"):
            assert client.post(f"/hr/applicants/{a2['id']}/advance").status_code == 200
        hired = client.post(f"/hr/applicants/{a2['id']}/hire", json={"basic_salary": "8000"})
        assert hired.status_code == 200, hired.text
        assert hired.json()["stage"] == "hired" and hired.json()["hired_employee_id"]
        emp_id = hired.json()["hired_employee_id"]
        emp = client.get(f"/hr/employees/{emp_id}").json()
        assert emp["status"] == "probation" and emp["basic_salary"] == "8000.00"
        # الإعلان امتلأ (1 منصب)
        after = client.get("/hr/job-postings").json()
        assert after[0]["status"] == "filled" and after[0]["hired_count"] == 1
        # متقدم جديد على إعلان ممتلئ مرفوض
        assert client.post(f"/hr/job-postings/{posting['id']}/applicants", json={
            "full_name": "متقدم متأخر", "email": "late@example.com",
        }).status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_performance_reviews_guards():
    client, engine = _client()
    try:
        emp = client.post("/hr/employees", json={"full_name": "مُقيَّم أداء"}).json()
        cyc = client.post("/hr/review-cycles", json={
            "name": "دورة 2026 نصفية", "period_start": "2026-01-01", "period_end": "2026-06-30",
        }).json()
        # نهاية قبل بداية مرفوضة
        assert client.post("/hr/review-cycles", json={
            "name": "خاطئ", "period_start": "2026-06-01", "period_end": "2026-01-01",
        }).status_code == 422

        r1 = client.post(f"/hr/review-cycles/{cyc['id']}/reviews", json={
            "employee_id": emp["id"], "quality": 5, "commitment": 4, "teamwork": 4, "initiative": 3,
        })
        assert r1.status_code == 201, r1.text
        assert r1.json()["score"] == "4.00"
        # تقييم مكرر لنفس الموظف بالدورة
        assert client.post(f"/hr/review-cycles/{cyc['id']}/reviews", json={
            "employee_id": emp["id"], "quality": 3, "commitment": 3, "teamwork": 3, "initiative": 3,
        }).status_code == 409

        # إغلاق الدورة يقفل التعديل
        assert client.post(f"/hr/review-cycles/{cyc['id']}/close").status_code == 200
        assert client.post(f"/hr/review-cycles/{cyc['id']}/close").status_code == 409
        assert client.post(f"/hr/review-cycles/{cyc['id']}/reviews", json={
            "employee_id": emp["id"], "quality": 2, "commitment": 2, "teamwork": 2, "initiative": 2,
        }).status_code == 409
        rid = int(r1.json()["id"])
        assert client.patch(f"/hr/performance-reviews/{rid}", json={"quality": 4}).status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_training_enrollment_and_analytics():
    client, engine = _client()
    try:
        emp = client.post("/hr/employees", json={"full_name": "متدرب مواظب", "basic_salary": "5000"}).json()
        trn = client.post("/hr/trainings", json={
            "title": "سلامة أماكن العمل", "provider": "مزوّد خارجي", "from_date": "2026-02-01", "to_date": "2026-02-03",
        }).json()
        assert trn["code"].startswith("TRN-")
        # تاريخ مقلوب مرفوض
        assert client.post("/hr/trainings", json={
            "title": "دورة خاطئة", "from_date": "2026-03-10", "to_date": "2026-03-01",
        }).status_code == 422

        en = client.post(f"/hr/trainings/{trn['id']}/enrollments", json={"employee_id": emp["id"]})
        assert en.status_code == 201 and en.json()["status"] == "enrolled"
        # تكرار التسجيل
        assert client.post(f"/hr/trainings/{trn['id']}/enrollments", json={"employee_id": emp["id"]}).status_code == 409

        eid = en.json()["id"]
        done = client.post(f"/hr/enrollments/{eid}/complete", json={"certificate_note": "شهادة حضور"})
        assert done.status_code == 200 and done.json()["status"] == "completed"
        # قرارات بعد الإتمام مرفوضة
        assert client.post(f"/hr/enrollments/{eid}/no-show").status_code == 409

        # الحضور: سجلان هذان الشهر (حاضر + غياب) — عبر التسجيل اليدوي
        client.post("/hr/attendance", json={
            "employee_id": emp["id"], "work_date": str(date.today()), "status": "present",
            "check_in": "09:00", "check_out": "17:00",
        })
        client.post("/hr/attendance", json={
            "employee_id": emp["id"], "work_date": str(date.today() - timedelta(days=1)), "status": "absent",
        })

        analytics = client.get("/hr/analytics")
        assert analytics.status_code == 200, analytics.text
        data = analytics.json()
        assert data["attendance"]["records"] >= 2 and data["attendance"]["attendance_rate"] > 0
        assert data["talent"]["trainings"] >= 1 and data["talent"]["enrollments_completed"] >= 1
        assert data["recruiting"]["open_postings"] >= 0
        assert "headcount" in data["turnover"] and "net_total" in data["payroll"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
