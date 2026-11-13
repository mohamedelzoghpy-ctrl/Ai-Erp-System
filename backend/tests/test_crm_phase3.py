"""المرحلة 3 من خطة CRM: الميدان — مزامنة القادة للموبايل + دفع أنشطة/مراحل أوفلاين + إشعارات المتابعة."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def env():
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
    client.post("/auth/setup", json={"username": "boss", "password": "long-password-123"})
    tok = client.post("/auth/login", data={"username": "boss", "password": "long-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {tok}"
    yield client, factory
    app.dependency_overrides.pop(get_db, None)


def ok(resp, code=200):
    assert resp.status_code == code, (resp.status_code, resp.text)
    return resp.json() if resp.content else None


def linked_rep_client(client, rep_name="مندوب CRM ميداني"):
    """مندوب مربوط بحساب دخول — يعيد TestClient بجلسته."""
    rep = ok(client.post("/reps", json={"name": rep_name, "code": "RC-M3", "commission_percent": "3"}), 201)
    ok(client.put(f"/reps/{rep['id']}/link-user", json={"username": "rep-crm-m3", "password": "rep-pass-1234"}))
    login = client.post("/auth/login", data={"username": "rep-crm-m3", "password": "rep-pass-1234"})
    assert login.status_code == 200
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    return c, rep


# ---------------------------------------------------------------- سحب القادة
def test_bootstrap_pulls_only_own_leads_with_delta(env):
    client, _factory = env
    rep_client, rep = linked_rep_client(client)
    other_rep = ok(client.post("/reps", json={"name": "مندوب آخر", "code": "RC-O3", "commission_percent": "0"}), 201)
    # الإنشاء من المدير والإسناد للمندوب (crm.lead.create للمدير)
    mine = ok(client.post("/crm/leads", json={"name": "قائدي الميداني", "phone": "01000000300", "expected_value": "5000", "assigned_rep_id": rep["id"]}), 201)
    not_mine = ok(client.post("/crm/leads", json={"name": "قائد زميله", "phone": "01000000301", "assigned_rep_id": other_rep["id"]}), 201)

    boot = ok(rep_client.get("/sync/bootstrap"))
    ids = [l["id"] for l in boot["crm_leads"]]
    assert mine["id"] in ids and not_mine["id"] not in ids
    # دلتا: since مستقبلي = لا شيء
    from urllib.parse import quote
    future = quote((datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), safe="")
    boot2 = ok(rep_client.get(f"/sync/bootstrap?since={future}"))
    assert boot2["crm_leads"] == []


# ---------------------------------------------------------------- رفع الأنشطة أوفلاين
def test_push_activities_idempotent_and_ownership(env):
    client, _factory = env
    rep_client, rep = linked_rep_client(client, "مندوب أنشطة")
    lead = ok(client.post("/crm/leads", json={"name": "قائد أنشطة", "phone": "01000000310", "assigned_rep_id": rep["id"]}), 201)

    payload = {"activities": [{
        "client_ref": "mob-act-0001-xyz", "lead_id": lead["id"],
        "kind": "call", "body": "مكالمة من الميدان — طلب عرض",
    }]}
    r1 = ok(rep_client.post("/sync/crm/activities", json=payload))
    assert r1["results"][0]["ok"] is True and not r1["results"][0].get("duplicate")
    # رفع مكرر بنفس client_ref → تخطٍ بلا صف ثانٍ
    r2 = ok(rep_client.post("/sync/crm/activities", json=payload))
    assert r2["results"][0]["ok"] is True and r2["results"][0].get("duplicate") is True
    acts = ok(client.get(f"/crm/leads/{lead['id']}/activities"))
    assert len([a for a in acts if a["kind"] == "call"]) == 1
    # قائد زميله → مرفوض
    other_rep = ok(client.post("/reps", json={"name": "زميل", "code": "RC-Z3", "commission_percent": "0"}), 201)
    foreign = ok(client.post("/crm/leads", json={"name": "قائد غريب", "phone": "01000000311", "assigned_rep_id": other_rep["id"]}), 201)
    r3 = ok(rep_client.post("/sync/crm/activities", json={"activities": [{
        "client_ref": "mob-act-0002-xyz", "lead_id": foreign["id"], "kind": "note", "body": "محاولة",
    }]}))
    assert r3["results"][0]["ok"] is False and "مسند" in r3["results"][0]["reason"]
    # غير مرتبط بمندوب → 403
    boss = TestClient(app)
    boss.headers["Authorization"] = client.headers["Authorization"]
    r4 = client.post("/auth/login", data={"username": "boss", "password": "long-password-123"})
    boss2 = TestClient(app)
    boss2.headers["Authorization"] = f"Bearer {r4.json()['access_token']}"
    resp = boss2.post("/sync/crm/activities", json=payload)
    assert resp.status_code == 403


# ---------------------------------------------------------------- رفع المراحل من الميدان
def test_push_stage_updates_and_won_converts(env):
    client, _factory = env
    rep_client, rep = linked_rep_client(client, "مندوب مراحل")
    lead = ok(client.post("/crm/leads", json={"name": "قائد مراحل", "phone": "01000000320", "assigned_rep_id": rep["id"]}), 201)
    # ترقية عادية
    r1 = ok(rep_client.post("/sync/crm/stages", json={"updates": [{"lead_id": lead["id"], "status": "contacted"}]}))
    assert r1["results"][0]["ok"] is True and r1["results"][0]["status"] == "contacted"
    # lost بلا سبب → مرفوض
    r2 = ok(rep_client.post("/sync/crm/stages", json={"updates": [{"lead_id": lead["id"], "status": "lost"}]}))
    assert r2["results"][0]["ok"] is False and "سبب" in r2["results"][0]["reason"]
    # won من الميدان → تحويل كامل لعميل
    r3 = ok(rep_client.post("/sync/crm/stages", json={"updates": [{"lead_id": lead["id"], "status": "won"}]}))
    res3 = r3["results"][0]
    assert res3["ok"] is True and res3.get("converted_customer_id")
    customers = ok(client.get("/customers"))
    assert any(cu["id"] == res3["converted_customer_id"] for cu in customers)
    # إعادة الرفع لنفس الحالة → already_final (idempotent)
    r4 = ok(rep_client.post("/sync/crm/stages", json={"updates": [{"lead_id": lead["id"], "status": "won"}]}))
    assert r4["results"][0].get("already_final") is True
    # سجل نظامي من الميدان
    acts = ok(client.get(f"/crm/leads/{lead['id']}/activities"))
    assert any("من الميدان" in a["body"] for a in acts)


# ---------------------------------------------------------------- إشعارات المتابعة
def test_followup_notifications_deduped_daily(env):
    from app.crm_followups import ensure_followup_notifications
    client, factory = env
    rep_client, rep = linked_rep_client(client, "مندوب تنبيهات")
    now = datetime.now(timezone.utc)
    # متابعة متأخرة + مستحقة اليوم + مستقبلية (لا تُنبَّه)
    late = ok(client.post("/crm/leads", json={"name": "متأخر", "phone": "01000000330", "assigned_rep_id": rep["id"], "next_follow_up_at": (now - timedelta(days=1)).isoformat()}), 201)
    today_l = ok(client.post("/crm/leads", json={"name": "اليوم", "phone": "01000000331", "assigned_rep_id": rep["id"], "next_follow_up_at": now.isoformat()}), 201)
    ok(client.post("/crm/leads", json={"name": "لاحق", "phone": "01000000332", "assigned_rep_id": rep["id"], "next_follow_up_at": (now + timedelta(days=5)).isoformat()}), 201)

    from app import models as m
    db = factory()
    rep_orm = db.query(m.SalesRep).get(rep["id"])
    created1 = ensure_followup_notifications(db, rep_orm)
    db.close()
    assert created1 == 2  # المتأخرة + اليوم، لا اللاحقة
    # استدعاء ثانٍ في نفس اليوم = صفر (dedup)
    db = factory()
    created2 = ensure_followup_notifications(db, db.query(m.SalesRep).get(rep["id"]))
    db.close()
    assert created2 == 0
    # صندوق الإشعارات فيه الاثنان
    notifs = ok(rep_client.get("/reps/me/notifications"))
    fu = [n for n in notifs if n["kind"] == "crm_followup"]
    assert len(fu) == 2
    assert any("متأخرة" in n["title"] for n in fu) and any("اليوم" in n["title"] for n in fu)
