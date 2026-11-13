"""المرحلة 4 من خطة CRM: مهام مجدولة + عمليات جماعية + استيراد Excel + مرفقات القائد."""
import io

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


def make_lead(c, name, phone=None, **extra):
    return ok(c.post("/crm/leads", json={"name": name, "phone": phone, **extra}), 201)


# ---------------------------------------------------------------- مهام مجدولة
def test_tasks_create_complete_and_filter(api):
    from datetime import datetime, timedelta, timezone
    c = api
    lead = make_lead(c, "قائد مهام", "01500000001")
    now = datetime.now(timezone.utc)
    # مهمة بلا استحقاق → 422
    r = c.post(f"/crm/leads/{lead['id']}/activities", json={"kind": "task", "body": "بلا موعد"})
    assert r.status_code == 422 and "استحقاق" in r.json()["detail"]
    # إنشاء مهمتين: واحدة مستحقة وأخرى لاحقة
    t1 = ok(c.post(f"/crm/leads/{lead['id']}/activities", json={
        "kind": "task", "body": "اتصل بالمدير", "due_at": (now - timedelta(days=1)).isoformat(),
    }), 201)
    t2 = ok(c.post(f"/crm/leads/{lead['id']}/activities", json={
        "kind": "task", "body": "أرسل الكتالوج", "due_at": (now + timedelta(days=2)).isoformat(),
    }), 201)
    # القائمة المفتوحة مرتبة بالاستحقاق (المتأخرة أولًا)
    open_tasks = ok(c.get("/crm/tasks?status=open"))
    assert [t["id"] for t in open_tasks] == [t1["id"], t2["id"]]
    assert open_tasks[0]["lead_name"] == "قائد مهام" and open_tasks[0]["lead_code"].startswith("LEAD-")
    # إتمام المتأخرة
    done = ok(c.post(f"/crm/activities/{t1['id']}/complete"))
    assert done["done_at"] is not None
    open2 = ok(c.get("/crm/tasks?status=open"))
    assert [t["id"] for t in open2] == [t2["id"]]
    done_list = ok(c.get("/crm/tasks?status=done"))
    assert [t["id"] for t in done_list] == [t1["id"]]
    # الإتمام على مكالمة → 422
    call_act = ok(c.post(f"/crm/leads/{lead['id']}/activities", json={"kind": "call", "body": "مكالمة"}), 201)
    assert c.post(f"/crm/activities/{call_act['id']}/complete").status_code == 422
    # الأنشطة العادية تعرض due_at
    acts = ok(c.get(f"/crm/leads/{lead['id']}/activities"))
    assert all(("due_at" in a and "done_at" in a) for a in acts)


# ---------------------------------------------------------------- عمليات جماعية
def test_bulk_operations_with_system_log(api):
    c = api
    rep = ok(c.post("/reps", json={"name": "مندوب جماعي", "code": "RB1", "commission_percent": "2"}), 201)
    l1 = make_lead(c, "جماعي ١", "01500000011")
    l2 = make_lead(c, "جماعي ٢", "01500000012")
    l3 = make_lead(c, "جماعي ٣", "01500000013")
    # إسناد جماعي
    res = ok(c.post("/crm/leads/bulk", json={
        "ids": [l1["id"], l2["id"], l3["id"], 999999],
        "action": "assign_rep", "assigned_rep_id": rep["id"],
    }))
    assert res["updated"] == 3
    assert len(res["skipped"]) == 1 and res["skipped"][0]["id"] == 999999
    for l in (l1, l2, l3):
        detail = ok(c.get(f"/crm/leads/{l['id']}"))
        assert detail["assigned_rep_id"] == rep["id"]
        acts = ok(c.get(f"/crm/leads/{l['id']}/activities"))
        assert any("جماعي" in a["body"] and a["kind"] == "system" for a in acts)
    # مرحلة جماعية: lost بلا سبب → 422
    assert c.post("/crm/leads/bulk", json={
        "ids": [l1["id"], l2["id"]], "action": "set_stage", "status": "lost",
    }).status_code == 422
    res2 = ok(c.post("/crm/leads/bulk", json={
        "ids": [l1["id"], l2["id"]], "action": "set_stage", "status": "lost", "lost_reason": "سعر",
    }))
    assert res2["updated"] == 2
    assert ok(c.get(f"/crm/leads/{l1['id']}"))["lost_reason"] == "سعر"
    # متابعة جماعية
    from datetime import datetime, timedelta, timezone
    res3 = ok(c.post("/crm/leads/bulk", json={
        "ids": [l3["id"]], "action": "set_follow_up",
        "next_follow_up_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }))
    assert res3["updated"] == 1
    assert ok(c.get(f"/crm/leads/{l3['id']}"))["next_follow_up_at"] is not None
    # مندوب غير موجود → 422
    assert c.post("/crm/leads/bulk", json={
        "ids": [l3["id"]], "action": "assign_rep", "assigned_rep_id": 999999,
    }).status_code == 422


# ---------------------------------------------------------------- استيراد Excel
def _import_file(c, preview=False):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["الاسم", "الشركة", "الهاتف", "المصدر", "القيمة المتوقعة", "ملاحظات"])
    ws.append(["قائد مستورد ١", "شركة أ", "01400000005", "توصية", "10000", "من المعرض"])
    ws.append(["قائد مستورد ٢", None, "01400000002", "سوشيال", "5000", None])
    ws.append([None, None, None, None, None, None])
    ws.append(["مكرر محتمل", None, "01400000001", "زائر", "100", None])
    ws.append([None, "شركة بلا اسم", "01400000009", "هاتف", "200", None])  # بلا اسم → خطأ
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return c.post(
        f"/crm/leads/import/xlsx?preview={'true' if preview else 'false'}",
        files={"file": ("leads.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )


def test_import_xlsx_preview_and_commit(api):
    c = api
    # موجود مسبقًا بنفس رقم الصف الأول → تكرار
    make_lead(c, "موجود مسبقًا", "01400000001")
    p = ok(_import_file(c, preview=True))
    assert len(p["planned"]) == 3
    assert p["duplicates"] == 1 and p["errors"][0]["row"] == 6
    # preview لا ينشئ شيئًا
    assert len(ok(c.get("/crm/leads?limit=200"))) == 1
    res = ok(_import_file(c, preview=False))
    assert res["created"] == 2  # الصفان السليمان؛ المكرر تُخطى
    assert res["skipped"][0]["reason"] == "تكرار هاتف"
    leads = {l["name"]: l for l in ok(c.get("/crm/leads?limit=200"))}
    assert "قائد مستورد ١" in leads and "قائد مستورد ٢" in leads
    assert leads["قائد مستورد ١"]["source"] == "referral" and float(leads["قائد مستورد ١"]["expected_value"]) == 10000.0
    assert leads["قائد مستورد ٢"]["source"] == "social"
    assert "موجود مسبقًا" in leads  # الموجود لم يُمس
    # ملف تالف → 422
    r = c.post("/crm/leads/import/xlsx", files={"file": ("bad.xlsx", io.BytesIO(b"not excel"), "application/octet-stream")})
    assert r.status_code == 422


# ---------------------------------------------------------------- مرفقات القائد
def test_lead_attachments(api):
    c = api
    lead = make_lead(c, "قائد مرفقات", "01500000021")
    pdf = b"%PDF-1.4 fake content"
    up = ok(c.post(f"/attachments/crm_lead/{lead['id']}", files={
        "file": ("card.pdf", io.BytesIO(pdf), "application/pdf"),
    }), 201)
    assert up["entity_type"] == "crm_lead" and up["filename"] == "card.pdf"
    files = ok(c.get(f"/attachments/crm_lead/{lead['id']}"))
    assert len(files) == 1
    dl = c.get(f"/attachments/{up['id']}/download")
    assert dl.status_code == 200
    # كيان غير موجود → 404
    assert c.post("/attachments/crm_lead/999999", files={
        "file": ("x.pdf", io.BytesIO(pdf), "application/pdf"),
    }).status_code == 404
    # نوع غير مدعوم (نص) → 422
    r = c.post(f"/attachments/crm_lead/{lead['id']}", files={
        "file": ("x.txt", io.BytesIO(b"hello"), "text/plain"),
    })
    assert r.status_code == 422
