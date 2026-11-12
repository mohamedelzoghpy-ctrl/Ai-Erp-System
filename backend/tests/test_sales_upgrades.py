"""اختبارات تحسينات المبيعات 2026-11-12:
قوائم الأسعار (حل السعر + بوابة الصلاحية) · عمولات المندوبين · أرصدة العملاء الدائنة.
"""
import uuid as _uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from tests.test_warehouse_stock import make_warehouses


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
    assert client.post("/auth/setup", json={"username": "boss", "password": "long-password"}).status_code == 201
    token = client.post("/auth/login", data={"username": "boss", "password": "long-password"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    app.dependency_overrides.pop(get_db, None)


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def _product(c, price="100"):
    return ok(c.post("/products", json={
        "sku": f"PL-{_uuid.uuid4().hex[:6]}", "name": "صنف أسعار", "sale_price": price,
        "cost_price": "50", "quantity": 50,
    }), 201)


def _wh(c):
    w, _ = make_warehouses(c)
    return w


# ================================================== 1) قوائم الأسعار
def test_price_list_crud_and_resolution_in_orders(api):
    c = api
    wh = _wh(c)
    p = _product(c, price="100")   # سعر عام 100
    # قائمة جملة: نفس الصنف بـ 85
    pl = ok(c.post("/price-lists", json={
        "name": "جملة", "items": [{"product_id": p["id"], "unit_price": "85"}],
    }), 201)
    assert Decimal(str(pl["items"][0]["unit_price"])) == Decimal("85")
    # عميل مرتبط بالقائمة
    cust = ok(c.post("/customers", json={"name": "عميل جملة", "price_list_id": pl["id"]}), 201)
    assert cust["price_list_id"] == pl["id"]
    # أمر بيع بدون سعر صريح → يُحل 85 من القائمة
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 2}],
    }), 201)
    assert Decimal(str(so["items"][0]["unit_price"])) == Decimal("85")
    # عميل بلا قائمة → 100 (السلوك القديم سليم)
    cust2 = ok(c.post("/customers", json={"name": "عميل عادي"}), 201)
    so2 = ok(c.post("/sales-orders", json={
        "customer_id": cust2["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 1}],
    }), 201)
    assert Decimal(str(so2["items"][0]["unit_price"])) == Decimal("100")


def test_price_list_is_permission_base_for_increase(api):
    """بوابة الزيادة-فقط تقاس على سعر القائمة: 90 فوق 85 يُرفض بلا صلاحية."""
    c = api
    wh = _wh(c)
    p = _product(c, price="100")
    pl = ok(c.post("/price-lists", json={"name": "خاص", "items": [{"product_id": p["id"], "unit_price": "85"}]}), 201)
    cust = ok(c.post("/customers", json={"name": "عميل خاص", "price_list_id": pl["id"]}), 201)
    br = ok(c.post("/company/branches", json={"name": "فرع أسعار"}), 201)
    r = c.post("/auth/users", json={"username": "plclerk", "password": "long-password", "role": "staff",
                                    "branch_ids": [br["id"]], "warehouse_ids": [wh["id"]]})
    uid = r.json()["id"]
    sec = ok(c.post("/access-sections", json={"code": f"pl{uid}", "name": "قسم أسعار"}), 201)
    ok(c.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": [
        "sales.order.view", "sales.order.create", "sales.order.confirm",
    ]}))
    ok(c.put(f"/auth/users/{uid}/section", json={"section_id": sec["id"]}))
    tok = c.post("/auth/login", data={"username": "plclerk", "password": "long-password"}).json()["access_token"]
    staff = TestClient(app)
    staff.headers["Authorization"] = f"Bearer {tok}"

    # فوق سعر القائمة (85) → 403 عند الإنشاء مباشرة
    assert staff.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "90"}],
    }).status_code == 403
    # تحت القائمة مرفوض أيضًا (الزيادة فقط)
    assert staff.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "80"}],
    }).status_code == 403
    # بالضبط على القائمة → يُنشأ ويُؤكد
    so = ok(staff.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "85"}],
    }), 201)
    ok(staff.post(f"/sales-orders/{so['id']}/confirm"), 200)


def test_pos_uses_customer_price_list(api):
    c = api
    wh = _wh(c)
    p = _product(c, price="100")
    pl = ok(c.post("/price-lists", json={"name": "موزعين", "items": [{"product_id": p["id"], "unit_price": "80"}]}), 201)
    cust = ok(c.post("/customers", json={"name": "عميل موزع", "price_list_id": pl["id"]}), 201)
    br = ok(c.post("/company/branches", json={"name": "فرع POS قوائم"}), 201)
    safe = ok(c.post("/safes", json={"name": "خزينة قوائم", "branch_id": br["id"]}), 201)
    r = ok(c.post("/pos/checkout", json={
        "warehouse_id": wh["id"], "customer_id": cust["id"],
        "items": [{"product_id": p["id"], "quantity": 2}],  # بلا سعر صريح
        "safe_id": safe["id"],
    }), 201)
    assert Decimal(str(r["total"])) == Decimal("160")  # 2 × 80 من القائمة


def test_price_list_delete_guard_and_duplicates(api):
    c = api
    _wh(c)  # حتى يُقبل إنشاء المنتج بكمية افتتاحية
    p = _product(c)
    pl = ok(c.post("/price-lists", json={"name": "قائمة محذوفة", "items": [{"product_id": p["id"], "unit_price": "70"}]}), 201)
    # اسم مكرر
    assert c.post("/price-lists", json={"name": "قائمة محذوفة"}).status_code == 409
    # منتج غير موجود
    assert c.post("/price-lists", json={"name": "قائمة 2", "items": [{"product_id": 99999, "unit_price": "1"}]}).status_code == 422
    # مرتبطة بعميل → حذف ممنوع
    ok(c.post("/customers", json={"name": "عميل مرتبط", "price_list_id": pl["id"]}), 201)
    assert c.delete(f"/price-lists/{pl['id']}").status_code == 409


# ================================================== 2) عمولات المندوبين
def test_reps_commissions_report(api):
    c = api
    wh = _wh(c)
    p = _product(c, price="200")
    rep = ok(c.post("/reps", json={"name": "مندوب العمولات", "commission_percent": "5"}), 201)
    cust = ok(c.post("/customers", json={"name": "عميل عمولات"}), 201)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"], "rep_id": rep["id"],
        "items": [{"product_id": p["id"], "quantity": 2}],
    }), 201)  # 400
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    # مرتجع 1 قطعة (100) على نفس المندوب
    line = ok(c.get(f"/sales-orders/{so['id']}"))["items"][0]["id"]
    ok(c.post("/sales-returns", json={"order_id": so["id"], "items": [{"order_item_id": line, "quantity": 1}]}), 201)
    rows = ok(c.get("/reports/reps-commissions"), 200)
    mine = [r for r in rows if r["rep_id"] == rep["id"]]
    assert len(mine) == 1
    assert Decimal(str(mine[0]["gross_sales"])) == Decimal("400")
    # مرتجع قطعة بسعر 200 (كريدت نوت بلا نقدي) → الصافي 200 والعمولة 5% = 10
    assert Decimal(str(mine[0]["returns"])) == Decimal("200")
    assert Decimal(str(mine[0]["net_sales"])) == Decimal("200")
    assert Decimal(str(mine[0]["commission_amount"])) == Decimal("10.00")
    x = c.get("/reports/reps-commissions/xlsx")
    assert x.status_code == 200


# ================================================== 3) أرصدة العملاء الدائنة
def test_customer_credits_report(api):
    c = api
    wh = _wh(c)
    br = ok(c.post("/company/branches", json={"name": "فرع دائن"}), 201)
    safe = ok(c.post("/safes", json={"name": "خزينة دائن", "branch_id": br["id"]}), 201)
    cust = ok(c.post("/customers", json={"name": "عميل دفع زيادة"}), 201)
    ok(c.post("/payments", json={"customer_id": cust["id"], "safe_id": safe["id"], "amount": "250"}), 201)
    rows = ok(c.get("/reports/customer-credits"), 200)
    mine = [r for r in rows if r["customer_id"] == cust["id"]]
    assert len(mine) == 1 and Decimal(str(mine[0]["credit_balance"])) == Decimal("250.00")
    x = c.get("/reports/customer-credits/xlsx")
    assert x.status_code == 200
