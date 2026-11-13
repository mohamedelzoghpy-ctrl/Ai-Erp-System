"""CRM خفيف — العملاء المحتملون: CRUD، مراحل، أنشطة، تحويل لعميل فعلي، عزل tenants،
وملخص المدير في تطبيق المندوبين (شاشات الموبايل)."""
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


def make_company_client(client, name, code, admin):
    r = client.post("/platform/companies", json={
        "name": name, "code": code, "admin_username": admin, "admin_password": f"{admin}-pass-123",
    })
    assert r.status_code == 201, r.text
    tok = client.post("/auth/login", data={"username": admin, "password": f"{admin}-pass-123"}).json()["access_token"]
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {tok}"
    return c


def test_lead_crud_and_pipeline(api):
    lead = ok(api.post("/crm/leads", json={
        "name": "أحمد محمود", "company_name": "مؤسسة النور", "phone": "01001234567",
        "source": "referral", "expected_value": "50000", "notes": "مهتم بباقة الجملة",
    }), 201)
    assert lead["code"].startswith("LEAD-") and lead["status"] == "new"
    assert lead["company_name"] == "مؤسسة النور"

    # بحث وفلترة
    assert len(ok(api.get("/crm/leads?search=النور"))) == 1
    assert ok(api.get("/crm/leads?status=qualified")) == []

    # ترقية عبر المراحل
    upd = ok(api.patch(f"/crm/leads/{lead['id']}", json={"status": "contacted"}))
    assert upd["status"] == "contacted"
    ok(api.patch(f"/crm/leads/{lead['id']}", json={"status": "qualified", "expected_value": "65000"}))
    rows = ok(api.get("/crm/leads?status=qualified"))
    assert len(rows) == 1 and float(rows[0]["expected_value"]) == 65000

    # حالة غير معروفة → 422 (Literal)
    assert api.patch(f"/crm/leads/{lead['id']}", json={"status": "flying"}).status_code == 422

    # حذف
    other = ok(api.post("/crm/leads", json={"name": "زائر معرض"}), 201)
    ok(api.delete(f"/crm/leads/{other['id']}"), 204)
    assert api.get(f"/crm/leads/{other['id']}").status_code == 404


def test_lead_rep_assignment_validation(api):
    rep = ok(api.post("/reps", json={"name": "مندوب CRM", "code": "RC1", "commission_percent": "3"}), 201)
    lead = ok(api.post("/crm/leads", json={"name": "عميل محتمل", "assigned_rep_id": rep["id"]}), 201)
    assert lead["assigned_rep_id"] == rep["id"]
    # مندوب غير موجود → 422
    assert api.post("/crm/leads", json={"name": "تاني", "assigned_rep_id": 99999}).status_code == 422
    assert api.patch(f"/crm/leads/{lead['id']}", json={"assigned_rep_id": 99999}).status_code == 422


def test_lead_activities(api):
    lead = ok(api.post("/crm/leads", json={"name": "منى سمير", "phone": "01111111111"}), 201)
    ok(api.post(f"/crm/leads/{lead['id']}/activities", json={"kind": "call", "body": "مكالمة أولى — طلبت عرض"}), 201)
    ok(api.post(f"/crm/leads/{lead['id']}/activities", json={"kind": "meeting", "body": "اجتماع معرض الجمعة"}), 201)
    acts = ok(api.get(f"/crm/leads/{lead['id']}/activities"))
    assert len(acts) == 2 and acts[0]["body"] == "اجتماع معرض الجمعة"  # الأحدث أولًا
    assert {a["kind"] for a in acts} == {"call", "meeting"}
    assert api.post(f"/crm/leads/{lead['id']}/activities", json={"kind": "note", "body": ""}).status_code == 422
    assert api.post(f"/crm/leads/{lead['id']}/activities", json={"kind": "sms", "body": "نوع غير معروف"}).status_code == 422


def test_convert_creates_customer_and_marks_won(api):
    lead = ok(api.post("/crm/leads", json={
        "name": "سيد المهندس", "company_name": "شركة الفتح للتوريدات", "phone": "01234567890",
        "email": "sayed@fath.example", "address": "المنصورة",
    }), 201)
    conv = ok(api.post(f"/crm/leads/{lead['id']}/convert"))
    assert conv["status"] == "won" and conv["converted_customer_id"]

    customers = ok(api.get("/customers"))
    match = [c for c in customers if c["id"] == conv["converted_customer_id"]]
    assert len(match) == 1
    cust = match[0]
    assert cust["name"] == "شركة الفتح للتوريدات"      # اسم الشركة هو اسم العميل
    assert cust["contact_person"] == "سيد المهندس"     # واسم الشخص مسؤول الاتصال
    assert cust["code"].startswith("CUS")
    assert cust["phone"] == "01234567890"

    # تحويل مزدوج → 409
    assert api.post(f"/crm/leads/{lead['id']}/convert").status_code == 409

    # قائد بلا اسم شركة: اسم العميل = اسم الشخص
    lead2 = ok(api.post("/crm/leads", json={"name": "هدى رشدي"}), 201)
    conv2 = ok(api.post(f"/crm/leads/{lead2['id']}/convert"))
    cust2 = [c for c in ok(api.get("/customers")) if c["id"] == conv2["converted_customer_id"]][0]
    assert cust2["name"] == "هدى رشدي"


def test_lead_tenant_isolation(api):
    a = make_company_client(api, "شركة أ", "comp-a", "admina")
    b = make_company_client(api, "شركة ب", "comp-b", "adminb")

    lead = ok(a.post("/crm/leads", json={"name": "عميل أ المحتمل", "phone": "010"}), 201)
    ok(a.post(f"/crm/leads/{lead['id']}/activities", json={"kind": "note", "body": "خاص بشركة أ"}), 201)

    # ب لا ترى القائد ولا أنشطته، ولا تعدّله أو تحوّله
    assert ok(b.get("/crm/leads")) == []
    assert b.get(f"/crm/leads/{lead['id']}").status_code == 404
    assert b.get(f"/crm/leads/{lead['id']}/activities").status_code == 404
    assert b.patch(f"/crm/leads/{lead['id']}", json={"status": "won"}).status_code == 404
    assert b.post(f"/crm/leads/{lead['id']}/convert").status_code == 404
    assert b.delete(f"/crm/leads/{lead['id']}").status_code == 404

    # التحويل داخل أ يعمل ويبقى محصوراً فيها
    conv = ok(a.post(f"/crm/leads/{lead['id']}/convert"))
    assert [c for c in ok(a.get("/customers")) if c["id"] == conv["converted_customer_id"]]
    assert ok(b.get("/customers")) == []


def test_manager_summary_counts_sales_and_debtors(api):
    wh = ok(api.post("/warehouses", json={"name": "مخزن رئيسي", "code": "WM1"}), 201)
    product = ok(api.post("/products", json={
        "sku": "MGR-1", "name": "صنف الملخص", "sale_price": "100", "cost_price": "40",
        "quantity": 50, "warehouse_id": wh["id"],
    }), 201)
    customer = ok(api.post("/customers", json={"name": "عميل الملخص"}), 201)

    r = api.post("/sales-orders", json={
        "customer_id": customer["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": product["id"], "quantity": 2, "unit_price": "100"}],
    })
    order = ok(r, 201)
    assert order["status"] == "draft"
    s = ok(api.get("/reps/me/manager-summary"))
    assert s["pending_orders"] == 1 and s["today_orders"] == 0 and s["today_sales"] == 0.0

    ok(api.post(f"/sales-orders/{order['id']}/confirm"))
    s2 = ok(api.get("/reps/me/manager-summary"))
    assert s2["pending_orders"] == 0
    assert s2["today_orders"] == 1 and s2["today_sales"] == 200.0
    assert s2["month_sales"] == 200.0
    assert s2["top_products"] and s2["top_products"][0]["name"] == "صنف الملخص"
    assert s2["top_products"][0]["value"] == 200.0
    # العميل أصبح له مديونية 200 (بيع آجل) → أعلى مديونية
    assert s2["top_debtors"] and s2["top_debtors"][0]["name"] == "عميل الملخص"
    assert s2["top_debtors"][0]["balance"] == 200.0

    # سداد جزئي يخفض المديونية في الملخص
    branch = ok(api.post("/company/branches", json={"name": "فرع الملخص"}), 201)
    safe = ok(api.post("/safes", json={"name": "خزينة الملخص", "opening_balance": "0", "branch_id": branch["id"]}), 201)
    ok(api.post("/payments", json={
        "customer_id": customer["id"], "safe_id": safe["id"],
        "amount": "50", "method": "cash",
    }), 201)
    s3 = ok(api.get("/reps/me/manager-summary"))
    assert s3["top_debtors"][0]["balance"] == 150.0


def test_crm_rules_cover_all_routes(api):
    """التغطية المغلقة: كل مسارات CRM لها قاعدة صلاحيات (الجدار يرفض غير المسجل به)."""
    from app.permissions.rules import ROUTE_RULES, match_rule
    crm_paths = {
        ("GET", "/crm/leads"): "crm.lead.view",
        ("POST", "/crm/leads"): "crm.lead.create",
        ("POST", "/crm/leads/5/convert"): "crm.lead.convert",
        ("GET", "/crm/leads/5/activities"): "crm.lead.view",
        ("POST", "/crm/leads/5/activities"): "crm.lead.activity",
        ("GET", "/reps/me/manager-summary"): "reports.dashboard.view",
    }
    for (method, path), expected in crm_paths.items():
        rule = match_rule(method, path)
        assert rule is not None, f"no rule for {method} {path}"
        assert expected in rule.perms, f"{method} {path} → {rule.perms}"
