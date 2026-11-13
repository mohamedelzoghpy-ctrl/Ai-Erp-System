"""المرحلة 1 من خطة CRM 80→95: مواعيد المتابعة + سبب الفقد + السجل النظامي."""
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
    yield client
    app.dependency_overrides.pop(get_db, None)


def ok(resp, code=200):
    assert resp.status_code == code, (resp.status_code, resp.text)
    return resp.json() if resp.content else None


def make_lead(c, name="عميل متابعة", phone="01000000001", **extra):
    return ok(c.post("/crm/leads", json={"name": name, "phone": phone, **extra}), 201)


# ---------------------------------------------------------------- سبب الفقد
def test_lost_requires_reason_and_records_it(api):
    c = api
    lead = make_lead(c)
    # النقل إلى lost بلا سبب → 422
    r = c.patch(f"/crm/leads/{lead['id']}", json={"status": "lost"})
    assert r.status_code == 422 and "سبب الفقد" in r.json()["detail"]
    # مع السبب → مقبول ومسجل
    upd = ok(c.patch(f"/crm/leads/{lead['id']}", json={"status": "lost", "lost_reason": "سعر المنافس أقل"}))
    assert upd["status"] == "lost" and upd["lost_reason"] == "سعر المنافس أقل"
    # السجل النظامي يوثّق المرحلة والسبب
    acts = ok(c.get(f"/crm/leads/{lead['id']}/activities"))
    sys_acts = [a for a in acts if a["kind"] == "system"]
    assert len(sys_acts) == 1
    assert "مفقود" in sys_acts[0]["body"] and "سعر المنافس أقل" in sys_acts[0]["body"]


# ---------------------------------------------------------------- السجل النظامي
def test_system_activity_on_stage_change_and_convert(api):
    c = api
    lead = make_lead(c)
    ok(c.patch(f"/crm/leads/{lead['id']}", json={"status": "contacted"}))
    ok(c.patch(f"/crm/leads/{lead['id']}", json={"status": "qualified"}))
    ok(c.post(f"/crm/leads/{lead['id']}/convert"))
    acts = ok(c.get(f"/crm/leads/{lead['id']}/activities"))
    sys_acts = [a for a in acts if a["kind"] == "system"]
    # تحولان مرحليان + التحويل
    assert len(sys_acts) == 3
    assert any("جديد ← تم التواصل" in a["body"] for a in sys_acts)
    assert any("تم التواصل ← مؤهل" in a["body"] for a in sys_acts)
    assert any("تحوّل لعميل فعلي" in a["body"] for a in sys_acts)
    # بلا تغيير مرحلة = لا سجل نظامي جديد
    ok(c.patch(f"/crm/leads/{lead['id']}", json={"notes": "تحديث نصي فقط"}))
    acts2 = ok(c.get(f"/crm/leads/{lead['id']}/activities"))
    assert len([a for a in acts2 if a["kind"] == "system"]) == 3


# ---------------------------------------------------------------- مواعيد المتابعة
def test_follow_up_filters_today_and_overdue(api):
    c = api
    now = datetime.now(timezone.utc)
    # متابعة متأخرة (أمس)
    late = make_lead(c, "متأخر", "01000000002", next_follow_up_at=(now - timedelta(days=1)).isoformat())
    # متابعة اليوم
    today_lead = make_lead(c, "اليوم", "01000000003", next_follow_up_at=now.isoformat())
    # متابعة بعد أسبوع (لا تدخل الفلاتر)
    make_lead(c, "لاحقًا", "01000000004", next_follow_up_at=(now + timedelta(days=7)).isoformat())
    # بلا متابعة
    make_lead(c, "بلا موعد", "01000000005")
    # متابعة اليوم لكنه فاز — تُستبعد من الفلاتر
    won = make_lead(c, "فائز", "01000000006", next_follow_up_at=now.isoformat())
    ok(c.post(f"/crm/leads/{won['id']}/convert"))

    today_rows = ok(c.get("/crm/leads?follow_up=today"))
    assert [r["id"] for r in today_rows] == [today_lead["id"]]
    overdue_rows = ok(c.get("/crm/leads?follow_up=overdue"))
    assert [r["id"] for r in overdue_rows] == [late["id"]]
    # فلتر غير صالح → 422
    assert c.get("/crm/leads?follow_up=yesterday").status_code == 422


def test_follow_up_set_on_create_and_update(api):
    c = api
    now = datetime.now(timezone.utc)
    lead = make_lead(c, next_follow_up_at=now.isoformat())
    assert lead["next_follow_up_at"] is not None
    new_date = (now + timedelta(days=3)).isoformat()
    upd = ok(c.patch(f"/crm/leads/{lead['id']}", json={"next_follow_up_at": new_date}))
    assert upd["next_follow_up_at"] is not None
