"""المرحلة 2 من خطة CRM: عرض سعر من القائد + كشف التكرار + قمع التحويل + تحليل المصادر."""
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


def make_lead(c, name, phone, **extra):
    return ok(c.post("/crm/leads", json={"name": name, "phone": phone, **extra}), 201)


# ---------------------------------------------------------------- كشف التكرار
def test_duplicate_detection_on_phone(api):
    c = api
    make_lead(c, "أول", "01000000010")
    # إنشاء آخر بنفس الرقم → 409 مع المطابقات
    r = c.post("/crm/leads", json={"name": "ثانٍ", "phone": "01000000010"})
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["message"] and len(body["duplicates"]) == 1 and body["duplicates"][0]["kind"] == "lead"
    # force يتجاوز
    forced = ok(c.post("/crm/leads?force=true", json={"name": "ثانٍ", "phone": "01000000010"}), 201)
    assert forced["id"]
    # فحص حي يجد القائدين
    chk = ok(c.get("/crm/leads/check-duplicate?phone=01000000010"))
    assert len(chk["duplicates"]) == 2
    # عميل فعلي بنفس الرقم يُكتشف أيضًا
    ok(c.post("/customers", json={"name": "عميل مطابق", "phone": "01111111111"}), 201)
    chk2 = ok(c.get("/crm/leads/check-duplicate?phone=01111111111"))
    assert any(d["kind"] == "customer" for d in chk2["duplicates"])
    # قائد مفقود لا يُعد تكرارًا
    lost_lead = make_lead(c, "مفقود", "01222222222")
    ok(c.patch(f"/crm/leads/{lost_lead['id']}", json={"status": "lost", "lost_reason": "بلا استجابة"}))
    chk3 = ok(c.get("/crm/leads/check-duplicate?phone=01222222222"))
    assert chk3["duplicates"] == []
    # بلا تكرار → إنشاء طبيعي بلا 409
    make_lead(c, "جديد تمامًا", "01333333333")


# ---------------------------------------------------------------- عرض سعر من القائد
def test_quotation_from_lead_converts_and_links(api):
    c = api
    w = ok(c.post("/warehouses", json={"name": "W", "code": "W1"}), 201)
    prod = ok(c.post("/products", json={"sku": "Q1", "name": "صنف عرض", "sale_price": "100", "cost_price": "40", "quantity": 50, "warehouse_id": w["id"]}), 201)
    lead = make_lead(c, "قائد عرض", "01000000020", company_name="شركة العرض")

    res = ok(c.post(f"/crm/leads/{lead['id']}/quotation", json={
        "warehouse_id": w["id"],
        "items": [{"product_id": prod["id"], "quantity": 2, "unit_price": "100"}],
        "notes": "عرض أولي",
    }))
    # تحويل ضمني + عرض سعر مربوط
    assert res["lead_status"] == "won" and res["converted_customer_id"]
    q = res["quotation"]
    assert q["status"] == "quotation"
    # الأوردر مربوط بالقائد والعميل المحول
    order = ok(c.get(f"/sales-orders/{q['id']}"))
    assert order["lead_id"] == lead["id"] and order["customer_id"] == res["converted_customer_id"]
    # سجل نظامي بالعرض
    acts = ok(c.get(f"/crm/leads/{lead['id']}/activities"))
    assert any("سعر رقم" in a["body"] and a["kind"] == "system" for a in acts)
    # قائد محول مسبقًا: عرض ثانٍ على نفس العميل بلا تحويل جديد
    res2 = ok(c.post(f"/crm/leads/{lead['id']}/quotation", json={
        "warehouse_id": w["id"],
        "items": [{"product_id": prod["id"], "quantity": 1, "unit_price": "95"}],
    }))
    order2 = ok(c.get(f"/sales-orders/{res2['quotation']['id']}"))
    assert order2["customer_id"] == res["converted_customer_id"]
    # منتج غير موجود → 422
    assert c.post(f"/crm/leads/{lead['id']}/quotation", json={
        "warehouse_id": w["id"], "items": [{"product_id": 999999, "quantity": 1, "unit_price": "1"}],
    }).status_code == 422


# ---------------------------------------------------------------- التحليلات
def test_funnel_and_sources_analytics(api):
    c = api
    now = datetime.now(timezone.utc)
    # فائزان بمصادر مختلفة + مفقود + مفتوحان
    w1 = make_lead(c, "فائز 1", "01000000031", source="referral", expected_value="50000")
    ok(c.post(f"/crm/leads/{w1['id']}/convert"))
    w2 = make_lead(c, "فائز 2", "01000000032", source="referral", expected_value="30000")
    ok(c.post(f"/crm/leads/{w2['id']}/convert"))
    lost1 = make_lead(c, "مفقود", "01000000033", source="social", expected_value="20000")
    ok(c.patch(f"/crm/leads/{lost1['id']}", json={"status": "lost", "lost_reason": "سعر"}))
    make_lead(c, "مفتوح 1", "01000000034", source="social", expected_value="15000", status="contacted")
    make_lead(c, "مفتوح 2", "01000000035", source="exhibition", expected_value="25000")

    funnel = ok(c.get("/crm/reports/funnel"))
    stages = {s["stage"]: s for s in funnel["stages"]}
    assert stages["won"]["count"] == 2 and float(stages["won"]["expected_value"]) == 80000.0
    assert stages["new"]["count"] == 1 and float(stages["new"]["expected_value"]) == 25000.0
    assert stages["contacted"]["count"] == 1
    assert float(funnel["open_pipeline_value"]) == 40000.0
    assert funnel["won_count"] == 2 and float(funnel["won_value"]) == 80000.0
    assert funnel["lost_count"] == 1
    assert funnel["win_rate_pct"] == 66.7  # 2/3
    assert float(funnel["avg_won_value"]) == 40000.0
    assert funnel["avg_days_to_win"] is not None

    sources = {s["source"]: s for s in ok(c.get("/crm/reports/sources"))}
    assert sources["referral"]["won_count"] == 2 and float(sources["referral"]["won_value"]) == 80000.0
    assert sources["referral"]["win_rate_pct"] == 100.0
    assert sources["social"]["lost_count"] == 1 and sources["social"]["open_count"] == 1
    assert sources["exhibition"]["open_count"] == 1
    # الترتيب حسب قيمة الفوز: referral أولًا
    ordered = ok(c.get("/crm/reports/sources"))
    assert ordered[0]["source"] == "referral"
