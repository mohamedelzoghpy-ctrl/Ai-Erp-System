"""اختبارات نظام الصلاحيات: تغطية OpenAPI الكاملة + سيناريوهات القسم/الفرد."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.permissions import (
    ALL_PERMISSIONS,
    PUBLIC_ENDPOINTS,
    SELF_ENDPOINTS,
    match_rule,
    seed_company_sections,
    seed_permission_catalog,
)


# ---------- 1) التغطية: كل مسار OpenAPI له قاعدة معلنة ----------


def test_every_openapi_route_has_permission_rule():
    spec = app.openapi()
    uncovered = []
    for path, ops in spec["paths"].items():
        for method in ops:
            if method not in ("get", "post", "patch", "put", "delete"):
                continue
            M = method.upper()
            if (M, path) in PUBLIC_ENDPOINTS or (M, path) in SELF_ENDPOINTS:
                continue
            if match_rule(M, path) is None:
                uncovered.append(f"{M} {path}")
    assert not uncovered, f"مسارات بلا صلاحية معلنة: {uncovered}"


def test_no_rule_is_orphaned():
    """كل قاعدة معرفة تطابق مساراً حقيقياً في OpenAPI (لا قواعد ميتة)."""
    spec = app.openapi()
    real_routes = set()
    for path, ops in spec["paths"].items():
        for method in ops:
            if method in ("get", "post", "patch", "put", "delete"):
                real_routes.add((method.upper(), path))
    orphaned = []
    for rule in __import__("app.permissions", fromlist=["ROUTE_RULES"]).ROUTE_RULES:
        if (rule.method, rule.pattern) not in real_routes:
            orphaned.append(f"{rule.method} {rule.pattern}")
    assert not orphaned, f"قواعد بلا مسارات حقيقية: {orphaned}"


def test_rule_codes_exist_in_catalog():
    from app.permissions import ROUTE_RULES

    for rule in ROUTE_RULES:
        for code in rule.perms:
            assert code in ALL_PERMISSIONS, f"كود غير معروف في قاعدة {rule.method} {rule.pattern}: {code}"


# ---------- 2) سيناريوهات القسم + الفرد ----------

import pytest  # noqa: E402


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # بذر الكتالوج على قاعدة الاختبار (بدل بذر الإقلاع المرتبط بـ Postgres)
    db = factory()
    seed_permission_catalog(db)
    db.close()
    c = TestClient(app)

    def seed_sections_for_current_company():
        """بذر الأقسام النظامية بعد إنشاء الشركة في الاختبار."""
        db2 = factory()
        from app import models as _m

        company = db2.query(_m.Company).first()
        if company is not None:
            seed_company_sections(db2, company.id)
            db2.commit()
        db2.close()

    c.seed_sections_for_current_company = seed_sections_for_current_company
    yield c
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture()
def admin_token(client):
    setup = client.post("/auth/setup", json={"username": "perm-admin", "password": "strong-password-123"})
    assert setup.status_code == 201, setup.text
    login = client.post("/auth/login", data={"username": "perm-admin", "password": "strong-password-123"})
    token = login.json()["access_token"]
    client.seed_sections_for_current_company()
    # فرع لإنشاء الموظفين (شرط الواجهة: موظف بلا فرع/مخزن مرفوض) — الـ setup قد ينشئ فرعاً افتراضياً
    branches = client.get("/company/branches", headers=_auth(token)).json()
    if not branches:
        branch = client.post("/company/branches", json={"name": "فرع رئيسي", "code": "PM1"}, headers=_auth(token))
        assert branch.status_code in (200, 201), branch.text
    return token


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_staff(client, admin_token, username):
    branches = client.get("/company/branches", headers=_auth(admin_token)).json()
    resp = client.post(
        "/auth/users",
        json={
            "username": username,
            "password": "staff-password-123",
            "role": "staff",
            "full_name": username,
            "branch_ids": [branches[0]["id"]],
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _staff_token(client, username):
    login = client.post("/auth/login", data={"username": username, "password": "staff-password-123"})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def test_catalog_and_sections_crud(client, admin_token):
    cat = client.get("/permissions/catalog", headers=_auth(admin_token))
    assert cat.status_code == 200
    assert cat.json()["total"] == len(ALL_PERMISSIONS) >= 300

    # مرفوض لموظف بلا صلاحية
    _create_staff(client, admin_token, "nos sect")
    token = _staff_token(client, "nos sect")
    assert client.get("/permissions/catalog", headers=_auth(token)).status_code == 403

    # إنشاء قسم وتعيين صلاحيات
    created = client.post("/access-sections", json={"code": "test-sec", "name": "قسم اختبار"}, headers=_auth(admin_token))
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    perms = client.put(
        f"/access-sections/{sid}/permissions",
        json={"permission_codes": ["sales.customer.view", "sales.pos.use"]},
        headers=_auth(admin_token),
    )
    assert perms.status_code == 200, perms.text
    assert sorted(perms.json()["permission_codes"]) == ["sales.customer.view", "sales.pos.use"]

    # قسم نظامي لا يُحذف
    sections = client.get("/access-sections", headers=_auth(admin_token)).json()
    sys_sec = next(s for s in sections if s["is_system"])
    assert client.delete(f"/access-sections/{sys_sec['id']}", headers=_auth(admin_token)).status_code == 400


def test_section_grants_and_individual_deny(client, admin_token):
    uid = _create_staff(client, admin_token, "secstaff")
    staff = _staff_token(client, "secstaff")

    # قبل أي قسم: ممنوع من العملاء، وخدمتي مسموحة (baseline — 404 هنا لعدم ارتباط موظف، ليس 403)
    assert client.get("/customers", headers=_auth(staff)).status_code == 403
    assert client.get("/hr/me", headers=_auth(staff)).status_code != 403

    # قسم المبيعات المبذر بالنظام (نمنحه مباشرة عبر قسم جديد بمصفوفة مبيعات كاملة)
    sales_codes = [c for c in ALL_PERMISSIONS if c.startswith("sales.")]
    sec = client.post("/access-sections", json={"code": "sales2", "name": "مبيعات ٢"}, headers=_auth(admin_token)).json()
    assert client.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": sales_codes}, headers=_auth(admin_token)).status_code == 200
    assert client.put(f"/auth/users/{uid}/section", json={"section_id": sec["id"]}, headers=_auth(admin_token)).status_code == 200

    # الآن يرى العملاء
    assert client.get("/customers", headers=_auth(staff)).status_code == 200
    # لكن لا يرى المستخدمين
    assert client.get("/auth/users", headers=_auth(staff)).status_code == 403

    # سحب فردي (deny) يغللب صلاحية القسم
    resp = client.put(
        f"/auth/users/{uid}/overrides",
        json={"overrides": [{"permission_code": "sales.customer.view", "effect": "deny", "reason": "تحتاج مراجعة"}]},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert any(o["code"] == "sales.customer.view" and o["effect"] == "deny" for o in detail["overrides"])
    assert "sales.customer.view" not in detail["effective"]
    assert client.get("/customers", headers=_auth(staff)).status_code == 403


def test_individual_grant_above_no_section(client, admin_token):
    uid = _create_staff(client, admin_token, "lonely")
    staff = _staff_token(client, "lonely")
    assert client.get("/auth/users", headers=_auth(staff)).status_code == 403

    resp = client.put(
        f"/auth/users/{uid}/overrides",
        json={"overrides": [{"permission_code": "admin.user.view", "effect": "grant", "reason": "مساعدة في الإدخال"}]},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert "admin.user.view" in resp.json()["effective"]
    assert client.get("/auth/users", headers=_auth(staff)).status_code == 200


def test_me_returns_effective_permissions(client, admin_token):
    me = client.get("/auth/me", headers=_auth(admin_token))
    assert me.status_code == 200
    assert me.json()["permissions"] == ["*"]

    uid = _create_staff(client, admin_token, "mesect")
    staff_me = client.get("/auth/me", headers=_auth(_staff_token(client, "mesect")))
    assert staff_me.json()["permissions"] == ["hr.me.use", "sales.rep.mobile"]


def test_manager_bypasses_everything(client, admin_token):
    # مدير جديد في الشركة يتجاوز الكل
    resp = client.post(
        "/auth/users",
        json={"username": "mng", "password": "manager-pass-123", "role": "manager", "full_name": "مدير"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    token = client.post("/auth/login", data={"username": "mng", "password": "manager-pass-123"}).json()["access_token"]
    # المدير يتجاوز البوابة على كل نقاط الأعمال
    assert client.get("/products", headers=_auth(token)).status_code == 200
    assert client.get("/hr/employees", headers=_auth(token)).status_code == 200
    assert client.get("/reports/dashboard", headers=_auth(token)).status_code == 200
    # المدير يتجاوز البوابة على كل نقاط الأعمال — والمستخدمين أيضاً (bypass كامل بالقرار)
    assert client.get("/auth/users", headers=_auth(token)).status_code == 200


def test_unknown_permission_code_rejected(client, admin_token):
    sec = client.post("/access-sections", json={"code": "bad", "name": "خاطئ"}, headers=_auth(admin_token)).json()
    resp = client.put(
        f"/access-sections/{sec['id']}/permissions",
        json={"permission_codes": ["not.a.real.code"]},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 422


def test_sales_order_price_edit_increase_only(client, admin_token):
    """صلاحية تعديل سعر البيع (زيادة فقط): بدونها يُباع بسعر البيع المعتمد فقط،
    ومعها الزيادة فقط — النقص مرفوض حتى مع الصلاحية."""
    wh = client.post("/warehouses", json={"name": "W-Price", "code": "WP1"}, headers=_auth(admin_token))
    assert wh.status_code == 201, wh.text
    wh = wh.json()
    product = client.post(
        "/products",
        json={"sku": "PRICE-1", "name": "منتج السعر", "sale_price": "100", "cost_price": "5", "quantity": 50, "warehouse_id": wh["id"]},
        headers=_auth(admin_token),
    )
    assert product.status_code == 201, product.text
    product = product.json()
    customer = client.post("/customers", json={"name": "عميل السعر"}, headers=_auth(admin_token)).json()

    uid = _create_staff(client, admin_token, "price-staff")
    sec = client.post("/access-sections", json={"code": "price-sec", "name": "قسم الأسعار"}, headers=_auth(admin_token)).json()
    client.put(
        f"/access-sections/{sec['id']}/permissions",
        json={"permission_codes": ["sales.order.view", "sales.order.create"]},
        headers=_auth(admin_token),
    )
    client.put(f"/auth/users/{uid}/section", json={"section_id": sec["id"]}, headers=_auth(admin_token))
    token = _staff_token(client, "price-staff")

    def _order(price):
        return client.post(
            "/sales-orders",
            json={
                "customer_id": customer["id"], "warehouse_id": wh["id"],
                "items": [{"product_id": product["id"], "quantity": 1, "unit_price": price}],
            },
            headers=_auth(token),
        )

    # بدون الصلاحية: سعر البيع المعتمد مقبول، وأي تغيير مرفوض
    assert _order("100").status_code == 201
    resp = _order("120")
    assert resp.status_code == 403, resp.text   # زيادة بلا صلاحية
    assert _order("80").status_code == 403      # نقص مرفوض دائماً

    # منح الصلاحية للقسم: الزيادة مسموحة والنقص مرفوض (زيادة فقط)
    client.put(
        f"/access-sections/{sec['id']}/permissions",
        json={"permission_codes": ["sales.order.view", "sales.order.create", "sales.order.price_increase"]},
        headers=_auth(admin_token),
    )
    resp = _order("120")
    assert resp.status_code == 201, resp.text   # زيادة مع الصلاحية
    assert _order("80").status_code == 403      # النقص مرفوض حتى مع الصلاحية
    assert _order("100").status_code == 201     # السعر المعتمد كما هو


def test_user_can_have_multiple_sections_union(client, admin_token):
    """عدة أقسام لموظف واحد: الصلاحية الفعلية = اتحاد صلاحيات كل الأقسام المسندة."""
    sec_a = client.post("/access-sections", json={"code": "multi-a", "name": "قسم أ"}, headers=_auth(admin_token)).json()
    sec_b = client.post("/access-sections", json={"code": "multi-b", "name": "قسم ب"}, headers=_auth(admin_token)).json()
    client.put(f"/access-sections/{sec_a['id']}/permissions", json={"permission_codes": ["sales.customer.view"]}, headers=_auth(admin_token))
    client.put(f"/access-sections/{sec_b['id']}/permissions", json={"permission_codes": ["inventory.product.view"]}, headers=_auth(admin_token))

    uid = _create_staff(client, admin_token, "multi-staff")
    token = _staff_token(client, "multi-staff")

    # بلا أقسام: ممنوع من الاثنين
    assert client.get("/customers", headers=_auth(token)).status_code == 403
    assert client.get("/products", headers=_auth(token)).status_code == 403

    # إسناد قسمين معاً → اتحاد الصلاحيات
    resp = client.put(f"/auth/users/{uid}/section", json={"section_ids": [sec_a["id"], sec_b["id"]]}, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert sorted(resp.json()["section_ids"]) == sorted([sec_a["id"], sec_b["id"]])
    assert client.get("/customers", headers=_auth(token)).status_code == 200
    assert client.get("/products", headers=_auth(token)).status_code == 200

    # إزالة قسم واحد → يبقى اتحاد القسم المتبقي فقط
    resp = client.put(f"/auth/users/{uid}/section", json={"section_ids": [sec_a["id"]]}, headers=_auth(admin_token))
    assert resp.json()["section_ids"] == [sec_a["id"]]
    assert client.get("/customers", headers=_auth(token)).status_code == 200
    assert client.get("/products", headers=_auth(token)).status_code == 403

    # إلغاء كل الأقسام → baseline فقط
    resp = client.put(f"/auth/users/{uid}/section", json={"section_ids": []}, headers=_auth(admin_token))
    assert resp.json()["section_ids"] == []
    assert client.get("/customers", headers=_auth(token)).status_code == 403

    # التوافق: الإسناد المفرد القديم (section_id) ما زال يعمل
    resp = client.put(f"/auth/users/{uid}/section", json={"section_id": sec_b["id"]}, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["section_ids"] == [sec_b["id"]]
    assert client.get("/products", headers=_auth(token)).status_code == 200

    # رفض قسم من شركة أخرى / غير موجود
    resp = client.put(f"/auth/users/{uid}/section", json={"section_ids": [99999]}, headers=_auth(admin_token))
    assert resp.status_code == 404
