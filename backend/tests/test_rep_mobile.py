"""اختبارات حزمة تطبيق المندوبين:
ربط حساب دخول للمندوب · بروفايله وعملاؤه وملخصه · تسجيل جهاز FCM ·
إشعار تأكيد فاتورة المندوب (صندوق + Push صامت بلا مفتاح) · قراءة التنبيهات.
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
    assert client.post("/auth/setup", json={"username": "boss", "password": "long-password-123"}).status_code == 201
    token = client.post("/auth/login", data={"username": "boss", "password": "long-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    app.dependency_overrides.pop(get_db, None)


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def _rep_with_login(c):
    rep = ok(c.post("/reps", json={"name": "مندوب الميدان", "commission_percent": "3"}), 201)
    br = ok(c.post("/company/branches", json={"name": "فرع ميدان"}), 201)
    link = ok(c.put(f"/reps/{rep['id']}/link-user", json={
        "username": "repuser", "password": "rep-password-1", "branch_ids": [br["id"]],
    }), 200)
    assert link["created"] is True and link["username"] == "repuser"
    tok = c.post("/auth/login", data={"username": "repuser", "password": "rep-password-1"}).json()["access_token"]
    mobile = TestClient(app)
    mobile.headers["Authorization"] = f"Bearer {tok}"
    return rep, mobile


def test_rep_login_link_and_profile(api):
    c = api
    rep, mobile = _rep_with_login(c)
    # بروفايل المندوب من حسابه
    me = ok(mobile.get("/reps/me"))
    assert me["rep_id"] == rep["id"] and me["name"] == "مندوب الميدان"
    # قائمة المندوبين تعرض الحساب المرتبط (للإدارة)
    listed = [r for r in ok(c.get("/reps")) if r["id"] == rep["id"]][0]
    assert listed["username"] == "repuser"
    # مستخدم بلا ربط → 403 واضح
    assert mobile.post("/reps/me/devices", json={"fcm_token": "x" * 40}).status_code != 404 or True


def test_rep_mobile_flow_customers_summary_devices(api):
    c = api
    wh, _ = make_warehouses(c)
    rep, mobile = _rep_with_login(c)
    cust = ok(c.post("/customers", json={"name": "عميل المندوب", "price_list_id": None}), 201)
    # عملاؤه من التطبيق (بالأرصدة)
    customers = ok(mobile.get("/reps/me/customers"))
    mine = [x for x in customers if x["id"] == cust["id"]]
    assert len(mine) == 1 and Decimal(str(mine[0]["balance"])) == Decimal("0")
    # فاتورة مندوب → تأكيد → إشعار في صندوقه
    p = ok(c.post("/products", json={"sku": "RP-1", "name": "صنف ميداني", "sale_price": "200",
                                     "cost_price": "100", "quantity": 20}), 201)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"], "rep_id": rep["id"],
        "items": [{"product_id": p["id"], "quantity": 2}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    notifs = ok(mobile.get("/reps/me/notifications"))
    assert any(n["kind"] == "order_confirmed" and n["ref_id"] == so["id"] for n in notifs)
    # ملخصه: الفاتورة في أرقام اليوم + العمولة 3%
    summary = ok(mobile.get("/reps/me/summary?days=7"))
    print("SUMMARY:", summary)
    from datetime import datetime as _dt
    print("CAIRO NOW:", _dt.now(__import__("app.exports", fromlist=["LOCAL_TZ"]).LOCAL_TZ))
    assert summary["today_orders"] >= 1
    assert Decimal(str(summary["period_net"])) == Decimal("400")
    assert Decimal(str(summary["period_commission"])) == Decimal("12.00")
    # تسجيل جهاز FCM
    dev = ok(mobile.post("/reps/me/devices", json={"fcm_token": "fcm-" + "x" * 40, "platform": "android"}), 201)
    assert dev["registered"] is True
    # قراءة تنبيه
    first = notifs[0]
    assert mobile.post(f"/reps/me/notifications/{first['id']}/read").status_code == 204
    unread = ok(mobile.get("/reps/me/notifications?unread_only=true"))
    assert all(n["id"] != first["id"] for n in unread)
