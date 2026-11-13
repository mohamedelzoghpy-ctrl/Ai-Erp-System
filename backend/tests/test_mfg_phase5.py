"""المرحلة 5 من خطة التصنيع: توقفات الخطوط + OEE مبسط."""
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


def make_line(c, name="خط التعبئة", capacity=100, cost="50"):
    return ok(c.post("/production-lines", json={"name": name, "capacity_per_hour": capacity, "hourly_cost": cost}), 201)


def test_downtime_crud_and_validation(api):
    c = api
    line = make_line(c)
    now = datetime.now(timezone.utc)
    # نهاية قبل البداية → 422
    r = c.post(f"/production-lines/{line['id']}/downtimes", json={
        "started_at": now.isoformat(), "ended_at": (now - timedelta(minutes=30)).isoformat(), "reason": "عطل",
    })
    assert r.status_code == 422
    # بلا نهاية وبلا دقائق → 422
    r2 = c.post(f"/production-lines/{line['id']}/downtimes", json={
        "started_at": now.isoformat(), "reason": "صيانة",
    })
    assert r2.status_code == 422
    # بالدقائق مباشرة → 201
    dt1 = ok(c.post(f"/production-lines/{line['id']}/downtimes", json={
        "started_at": now.isoformat(), "minutes": 45, "reason": "نقص خامات",
    }), 201)
    assert dt1["minutes"] == 45 and dt1["ended_at"] is None
    # بالتواريخ → الدقائق تُحسب
    dt2 = ok(c.post(f"/production-lines/{line['id']}/downtimes", json={
        "started_at": (now - timedelta(hours=2)).isoformat(),
        "ended_at": (now - timedelta(hours=1, minutes=15)).isoformat(),
        "reason": "عطل ماكينة",
    }), 201)
    assert dt2["minutes"] == 45
    # القائمة + الحذف
    rows = ok(c.get(f"/production-lines/{line['id']}/downtimes"))
    assert len(rows) == 2
    ok(c.delete(f"/production-lines/{line['id']}/downtimes/{dt2['id']}"), 204)
    assert len(ok(c.get(f"/production-lines/{line['id']}/downtimes"))) == 1
    # خط غير موجود → 404
    assert c.post("/production-lines/999999/downtimes", json={
        "started_at": now.isoformat(), "minutes": 10, "reason": "x",
    }).status_code == 404


def test_oee_report_availability_and_reasons(api):
    c = api
    line = make_line(c, "خط التعبئة ٢")
    now = datetime.now(timezone.utc)
    ok(c.post(f"/production-lines/{line['id']}/downtimes", json={
        "started_at": (now - timedelta(days=1)).isoformat(),
        "ended_at": (now - timedelta(days=1) + timedelta(hours=2)).isoformat(),  # مُغلق — 120 دقيقة
        "reason": "عطل",
    }), 201)
    ok(c.post(f"/production-lines/{line['id']}/downtimes", json={
        "started_at": (now - timedelta(days=1, hours=2)).isoformat(),
        "ended_at": (now - timedelta(days=1, hours=1)).isoformat(),   # مُغلق — 60 دقيقة محسوبة
        "reason": "عطل",
    }), 201)
    ok(c.post(f"/production-lines/{line['id']}/downtimes", json={
        "started_at": now.isoformat(), "minutes": 30, "reason": "نقص خامات",  # توقف مستمر (بلا نهاية)
    }), 201)
    rows = ok(c.get("/production-lines/oee?hours_per_day=16"))
    mine = next(r for r in rows if r["line_id"] == line["id"])
    assert mine["downtime_minutes"] == 210
    assert mine["open_downtimes"] == 1
    reasons = {d["reason"]: d["minutes"] for d in mine["downtime_by_reason"]}
    assert reasons["عطل"] == 180 and reasons["نقص خامات"] == 30
    # التوافر: فترة 31 يوم × 16 ساعة × 60 = 29760 دقيقة → (29760−210)/29760 ≈ 99.3
    assert mine["availability_pct"] is not None and 99.0 < mine["availability_pct"] < 99.6
    # خط ثانٍ بلا توقفات = توافر 100%
    other = make_line(c, "خط نظيف")
    rows2 = ok(c.get("/production-lines/oee?hours_per_day=16"))
    clean = next(r for r in rows2 if r["line_id"] == other["id"])
    assert clean["downtime_minutes"] == 0 and clean["availability_pct"] == 100.0
