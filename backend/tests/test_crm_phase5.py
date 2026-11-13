"""المرحلة 5 من خطة CRM: لوحة أداء المندوبين + إنذار القادة الراكدين."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def api():
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
    assert client.post("/auth/setup", json={"username": "boss", "password": "long-password-123"}).status_code == 201
    token = client.post("/auth/login", data={"username": "boss", "password": "long-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client, factory
    app.dependency_overrides.pop(get_db, None)


def ok(resp, code=200):
    assert resp.status_code == code, (resp.status_code, resp.text)
    return resp.json() if resp.content else None


def make_lead(c, name, phone, **extra):
    return ok(c.post("/crm/leads", json={"name": name, "phone": phone, **extra}), 201)


def test_reps_performance_ranking(api):
    c, _f = api
    r1 = ok(c.post("/reps", json={"name": "مندوب بطل", "code": "R5A", "commission_percent": "5"}), 201)
    r2 = ok(c.post("/reps", json={"name": "مندوب صاعد", "code": "R5B", "commission_percent": "3"}), 201)
    # بطل: فاز بقيمة كبيرة + خط مفتوح
    w = make_lead(c, "فوز البطل", "01700000001", source="referral", expected_value="90000", assigned_rep_id=r1["id"])
    ok(c.post(f"/crm/leads/{w['id']}/convert"))
    make_lead(c, "خط البطل", "01700000002", expected_value="10000", assigned_rep_id=r1["id"], status="qualified")
    # صاعد: فوز أصغر + فقد
    w2 = make_lead(c, "فوز الصاعد", "01700000003", expected_value="20000", assigned_rep_id=r2["id"])
    ok(c.post(f"/crm/leads/{w2['id']}/convert"))
    lost = make_lead(c, "فقد الصاعد", "01700000004", expected_value="5000", assigned_rep_id=r2["id"])
    ok(c.patch(f"/crm/leads/{lost['id']}", json={"status": "lost", "lost_reason": "سعر"}))
    # بلا إسناد
    make_lead(c, "بلا راعي", "01700000005", expected_value="1000")

    rows = ok(c.get("/crm/reports/reps-performance"))
    by_name = {r["rep_name"]: r for r in rows}
    champ = by_name["مندوب بطل"]
    assert champ["won_count"] == 1 and float(champ["won_value"]) == 90000.0
    assert champ["open_leads"] == 1 and float(champ["open_pipeline_value"]) == 10000.0
    assert champ["win_rate_pct"] == 100.0
    rising = by_name["مندوب صاعد"]
    assert rising["won_count"] == 1 and rising["lost_count"] == 1
    assert rising["win_rate_pct"] == 50.0
    # الترتيب بقيمة الفوز: البطل أولًا
    assert rows[0]["rep_name"] == "مندوب بطل"
    # بلا إسناد → rep_id None موجود
    assert any(r["rep_id"] is None for r in rows)


def test_stale_leads_detection(api):
    c, factory = api
    rep = ok(c.post("/reps", json={"name": "مندوب راكد", "code": "R5C", "commission_percent": "1"}), 201)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    # راكد فعلاً: أنشئ ثم أرجع updated_at يدويًا؟ created_at server_default — يمكن التحايل:
    # قائد نشط حديثًا (نشاط مكالمة الآن) → ليس راكدًا
    active = make_lead(c, "نشط", "01700000011", assigned_rep_id=rep["id"])
    ok(c.post(f"/crm/leads/{active['id']}/activities", json={"kind": "call", "body": "مكالمة الآن"}), 201)
    # قائد بلا أنشطة إطلاقًا — راكد منذ الإنشاء (أدخل تاريخ إنشاء قديم عبر DB مباشرة في الاختبار التالي)
    stale = make_lead(c, "قديم بلا حركة", "01700000012", assigned_rep_id=rep["id"])
    won_lead = make_lead(c, "فائز قديم", "01700000013", assigned_rep_id=rep["id"])
    ok(c.post(f"/crm/leads/{won_lead['id']}/convert"))

    # اصنع راكدًا حقيقيًا: قائد قديم بلا نشاط — عدّل created_at في القاعدة عبر جلسة اختبار
    from app import models
    db = factory()
    lead_orm = db.query(models.CrmLead).get(stale["id"])
    lead_orm.created_at = now - timedelta(days=30)
    won_orm = db.query(models.CrmLead).get(won_lead["id"])
    won_orm.created_at = now - timedelta(days=60)
    db.commit()
    db.close()

    stale_rows = ok(c.get("/crm/reports/stale?days=14"))
    ids = [r["id"] for r in stale_rows]
    assert stale["id"] in ids
    # الفائز لا يُرصد (مستبعد من الراكدين)
    assert won_lead["id"] not in ids
    # النشط (مكالمة الآن) ليس راكدًا
    assert active["id"] not in ids
    row = next(r for r in stale_rows if r["id"] == stale["id"])
    assert row["stale_days"] >= 14 and row["rep_name"] == "مندوب راكد"
    # عتبة أعلى تستثني 30 يومًا؟ لا — الراكد 30 يومًا يظهر في 14 و45:
    stale_rows_60 = ok(c.get("/crm/reports/stale?days=60"))
    assert all(r["id"] != stale["id"] for r in stale_rows_60)
