"""المرحلة 5: أساس SaaS — عزل tenants شامل عبر كل الكيانات الرئيسية × شركتين،
والتسجيل الذاتي المحمي بمفتاح مع ترخيص تجريبي."""
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
    client.post("/auth/setup", json={"username": "platform", "password": "strong-password-123"})
    ptok = client.post("/auth/login", data={"username": "platform", "password": "strong-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {ptok}"

    def make_company_client(name, code, admin):
        r = client.post("/platform/companies", json={
            "name": name, "code": code, "admin_username": admin, "admin_password": f"{admin}-pass-123",
        })
        assert r.status_code == 201, r.text
        tok = client.post("/auth/login", data={"username": admin, "password": f"{admin}-pass-123"}).json()["access_token"]
        c = TestClient(app)
        c.headers["Authorization"] = f"Bearer {tok}"
        return c

    yield client, make_company_client, engine
    app.dependency_overrides.pop(get_db, None)


def test_full_tenant_isolation_matrix(env):
    """شركة A تُنشئ بيانات في كل كيان رئيسي — شركة B لا ترى ولا تعدّل شيئاً منها."""
    client, make_company_client, engine = env
    a = make_company_client("شركة أ", "comp-a", "admina")
    b = make_company_client("شركة ب", "comp-b", "adminb")

    # بيانات الشركة أ في كل كيان (الشركات المنشأة تبدأ بفرع بلا مخزن)
    a.post("/warehouses", json={"name": "مخزن أ", "code": "WA"})
    b.post("/warehouses", json={"name": "مخزن ب", "code": "WB"})
    product = a.post("/products", json={"sku": "A-1", "name": "صنف أ", "sale_price": "10", "cost_price": "5", "quantity": 10, "warehouse_id": a.get("/warehouses").json()[0]["id"]}).json()
    customer = a.post("/customers", json={"name": "عميل أ"}).json()
    supplier = a.post("/suppliers", json={"name": "مورد أ"}).json()
    warehouse = a.get("/warehouses").json()[0]
    safe = a.post("/safes", json={"name": "خزينة أ", "opening_balance": "0"}).json()
    pricelist = a.post("/price-lists", json={"name": "قائمة أ", "items": [{"product_id": product["id"], "unit_price": "9"}]}).json()
    rep = a.post("/reps", json={"name": "مندوب أ", "code": "RA1", "commission_percent": "3"}).json()
    order = a.post("/sales-orders", json={
        "customer_id": customer["id"], "warehouse_id": warehouse["id"], "rep_id": rep["id"],
        "items": [{"product_id": product["id"], "quantity": 2}],
    }).json()
    je = a.post("/journal-entries", json={
        "description": "قيد أ",
        "items": a.get("/chart-of-accounts").json() and [
            {"account_id": next(x["id"] for x in a.get("/chart-of-accounts").json() if x["code"] == "1111"), "debit": "5", "credit": "0"},
            {"account_id": next(x["id"] for x in a.get("/chart-of-accounts").json() if x["code"] == "4101"), "debit": "0", "credit": "5"},
        ],
    }).json()
    emp = a.post("/hr/employees", json={"full_name": "موظف أ"}).json()
    lot = a.post("/lots", json={"product_id": product["id"], "warehouse_id": warehouse["id"], "lot_code": "A-LOT", "qty": 5}).json()

    # شركة ب: قوائمها فارغة من بيانات أ + الوصول المباشر 404 + التعديل 404
    checks = [
        ("/products", "id", product["id"]),
        ("/customers", "id", customer["id"]),
        ("/suppliers", "id", supplier["id"]),
        ("/price-lists", "id", pricelist["id"]),
        ("/reps", "id", rep["id"]),
        ("/hr/employees", "id", emp["id"]),
        ("/lots", "id", lot["id"]),
    ]
    for path, key, value in checks:
        rows = b.get(path).json()
        assert all(row[key] != value for row in rows), f"تسريب في {path}: شركة ب ترى بيانات أ"
    # المخازن والخزائن: ب sees only its own (auto-created)
    assert all(w["id"] != warehouse["id"] for w in b.get("/warehouses").json())
    assert all(s["id"] != safe["id"] for s in b.get("/safes").json())

    # وصول مباشر + تعديل + حذف → 404
    gettable = [
        f"/products/{product['id']}", f"/customers/{customer['id']}",
        f"/journal-entries/{je['id']}", f"/hr/employees/{emp['id']}", f"/sales-orders/{order['id']}",
    ]
    for path in gettable:
        assert b.get(path).status_code == 404, f"GET {path} عبرت العزل"
    # reps بلا GET مفرد (405 لأي شركة) — PATCH الموجود هو إثبات العزل
    for path in [f"/products/{product['id']}", f"/customers/{customer['id']}",
                 f"/journal-entries/{je['id']}", f"/reps/{rep['id']}", f"/hr/employees/{emp['id']}"]:
        assert b.patch(path, json={"name": "اختراق"}).status_code == 404, f"PATCH {path} عبرت العزل"
    assert b.delete(f"/reps/{rep['id']}").status_code == 404

    # حركات ب على كياناتها لا تمس أ: ب تنشئ صنفاً — أ لا تراه
    b_product = b.post("/products", json={"sku": "B-1", "name": "صنف ب", "sale_price": "8", "cost_price": "4", "quantity": 3, "warehouse_id": b.get("/warehouses").json()[0]["id"]}).json()
    assert all(p["id"] != b_product["id"] for p in a.get("/products").json())

    # شجرة الحسابات منفصلة: قيد أ لم يمس أرصدة ب (ب سليمة صفر)
    b_tb = b.get("/reports/financial/trial-balance").json()
    assert all(abs(float(r["balance"])) < 0.01 for r in b_tb), "أرصدة ب تأثرت بقيد أ!"


def test_self_registration_flow(env, monkeypatch):
    client, make_company_client, engine = env

    # معطل بلا مفتاح
    monkeypatch.delenv("REGISTRATION_KEY", raising=False)
    r = client.post("/platform/register", json={
        "company_name": "شركة تسجيل", "admin_username": "regadmin", "admin_password": "reg-pass-123",
        "registration_key": "anything",
    })
    assert r.status_code == 403

    # مفتاح خاطئ → 403
    monkeypatch.setenv("REGISTRATION_KEY", "secret-launch-key")
    r = client.post("/platform/register", json={
        "company_name": "شركة تسجيل", "admin_username": "regadmin", "admin_password": "reg-pass-123",
        "registration_key": "wrong",
    })
    assert r.status_code == 403

    # مفتاح صحيح → شركة + ترخيص تجريبي 14 يوم + دخول يعمل + بذر كامل
    r = client.post("/platform/register", json={
        "company_name": "شركة تسجيل", "company_code": "reg-co", "admin_username": "regadmin",
        "admin_password": "reg-pass-123", "admin_full_name": "مدير التسجيل",
        "registration_key": "secret-launch-key",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["trial_days"] == 14 and body["license_until"]
    assert body["code"] == "reg-co"  # الكود المطلوب هو المُعتمد فعلاً

    tok = client.post("/auth/login", data={"username": "regadmin", "password": "reg-pass-123"}).json()["access_token"]
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {tok}"
    me = c.get("/auth/me")
    assert me.status_code == 200
    # البذر الكامل: شجرة حسابات + فرع + فترات مالية
    assert len(c.get("/chart-of-accounts").json()) > 10
    assert len(c.get("/company/branches").json()) >= 1
    # كلمة سر ضعيفة → 422
    r2 = client.post("/platform/register", json={
        "company_name": "شركة ثانية", "admin_username": "weakadmin", "admin_password": "nodigits-here",
        "registration_key": "secret-launch-key",
    })
    assert r2.status_code == 422
    # كود مكرر → 409
    r3 = client.post("/platform/register", json={
        "company_name": "شركة تسجيل", "company_code": "reg-co", "admin_username": "otheradmin",
        "admin_password": "reg-pass-123", "registration_key": "secret-launch-key",
    })
    assert r3.status_code == 409
