"""المرحلة 4: خصم الأوردر، عرض السعر وتحويله، دورات العمولات، ترحيل EOSB، مراجعة أوفر تايم."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from tests.test_warehouse_stock import make_product, make_warehouses


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
    client.post("/auth/setup", json={"username": "p4-admin", "password": "strong-password-123"})
    token = client.post("/auth/login", data={"username": "p4-admin", "password": "strong-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client, engine
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------- خصم الأوردر

def test_sales_order_discount_reduces_taxable(api):
    client, engine = api
    w1, _ = make_warehouses(client)
    product = make_product(client, "D1", 50, w1["id"], sale_price="100")
    customer = client.post("/customers", json={"name": "عميل خصم"}).json()

    # 2×100=200 — خصم 50 → taxable 150 → VAT 21 → إجمالي 171
    r = client.post("/sales-orders", json={
        "customer_id": customer["id"], "warehouse_id": w1["id"], "tax_rate": "14",
        "discount_mode": "amount", "discount_value": "50",
        "items": [{"product_id": product["id"], "quantity": 2}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert float(body["discount_amount"]) == 50.0
    assert float(body["subtotal"]) == 150.0
    assert float(body["tax_amount"]) == 21.0
    assert float(body["total_amount"]) == 171.0

    # خصم بالنسبة: 10% من 200 = 20 → taxable 180 → VAT 25.2 → 205.2
    r2 = client.post("/sales-orders", json={
        "customer_id": customer["id"], "warehouse_id": w1["id"], "tax_rate": "14",
        "discount_mode": "percent", "discount_value": "10",
        "items": [{"product_id": product["id"], "quantity": 2}],
    })
    assert float(r2.json()["total_amount"]) == 205.2

    # خصم يتجاوز الإجمالي → 422
    r3 = client.post("/sales-orders", json={
        "customer_id": customer["id"], "warehouse_id": w1["id"],
        "discount_mode": "amount", "discount_value": "500",
        "items": [{"product_id": product["id"], "quantity": 2}],
    })
    assert r3.status_code == 422


# ---------------------------------------------------------------- عرض السعر

def test_quotation_lifecycle_and_convert(api):
    client, engine = api
    w1, _ = make_warehouses(client)
    product = make_product(client, "Q1", 50, w1["id"])
    customer = client.post("/customers", json={"name": "عميل عرض"}).json()

    q = client.post("/sales-orders", json={
        "customer_id": customer["id"], "warehouse_id": w1["id"],
        "document_type": "quotation",
        "items": [{"product_id": product["id"], "quantity": 5}],
    })
    assert q.status_code == 201, q.text
    qid = q.json()["id"]

    # عرض سعر لا يخصم مخزون ولا يُؤكد
    stock_after = float(client.get(f"/products/{product['id']}").json()["quantity"])
    assert stock_after == 50.0
    c = client.post(f"/sales-orders/{qid}/confirm")
    assert c.status_code == 409

    # تحويله إلى أوردر → يؤكد ويخصم
    conv = client.post(f"/sales-orders/{qid}/convert")
    assert conv.status_code == 200, conv.text
    assert conv.json()["status"] == "draft"
    confirmed = client.post(f"/sales-orders/{qid}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert float(client.get(f"/products/{product['id']}").json()["quantity"]) == 45.0

    # تحويل مرتين → 409
    assert client.post(f"/sales-orders/{qid}/convert").status_code == 409


# ---------------------------------------------------------------- دورات العمولات

def test_commission_run_locks_orders_against_double_payment(api):
    client, engine = api
    w1, _ = make_warehouses(client)
    product = make_product(client, "C1", 100, w1["id"])
    rep = client.post("/reps", json={"name": "مندوب عمولات", "code": "RC1", "commission_percent": "5"}).json()
    customer = client.post("/customers", json={"name": "عميل عمولات"}).json()

    # أوردران مؤكدان للمنادوب + مرتجع منسوب له
    ids = []
    for _ in range(2):
        o = client.post("/sales-orders", json={
            "customer_id": customer["id"], "warehouse_id": w1["id"], "rep_id": rep["id"],
            "items": [{"product_id": product["id"], "quantity": 10}],
        }).json()
        assert client.post(f"/sales-orders/{o['id']}/confirm").status_code == 200
        ids.append(o["id"])
    ret = client.post("/sales-returns", json={
        "order_id": ids[0],
        "items": [{"order_item_id": client.get(f"/sales-orders/{ids[0]}").json()["items"][0]["id"], "product_id": product["id"], "quantity": 2}],
        "rep_id": rep["id"], "refund_amount": "0",
    })
    assert ret.status_code == 201, ret.text

    run = client.post("/reps/commission-runs", json={"period_from": "2026-01-01", "period_to": "2026-12-31"})
    assert run.status_code == 201, run.text
    body = run.json()
    line = body["lines"][0]
    # صافي = 200 - 20 = 180 → عمولة 5% = 9
    assert float(line["net"]) == 180.0
    assert float(line["commission"]) == 9.0
    assert body["orders_locked"] == 2

    # الأوردرات مقفولة → دورة ثانية بنفس الفترة: صفر
    run2 = client.post("/reps/commission-runs", json={"period_from": "2026-01-01", "period_to": "2026-12-31"}).json()
    assert run2["lines"] == [] and run2["orders_locked"] == 0

    # الأوردرات الجديدة بعد الدورة تدخل في دورة لاحقة
    o3 = client.post("/sales-orders", json={
        "customer_id": customer["id"], "warehouse_id": w1["id"], "rep_id": rep["id"],
        "items": [{"product_id": product["id"], "quantity": 10}],
    }).json()
    assert client.post(f"/sales-orders/{o3['id']}/confirm").status_code == 200
    run3 = client.post("/reps/commission-runs", json={"period_from": "2026-01-01", "period_to": "2026-12-31"}).json()
    assert run3["lines"] and float(run3["lines"][0]["net"]) == 100.0

    # قائمة الدورات
    runs = client.get("/reps/commission-runs").json()
    assert len(runs) == 3


# ---------------------------------------------------------------- EOSB + أوفر تايم

def test_settlement_posts_to_gl_once(api):
    client, engine = api
    client.post("/chart-of-accounts/seed")
    emp = client.post("/hr/employees", json={"full_name": "موظف منتهٍ", "basic_salary": "9000"}).json()
    # إنهاء خدمة
    term = client.patch(f"/hr/employees/{emp['id']}", json={"status": "terminated", "termination_date": "2026-11-01"})
    assert term.status_code == 200, term.text
    st = client.post(f"/hr/employees/{emp['id']}/settlement", json={})
    assert st.status_code == 201, st.text
    sid = st.json()["id"]
    assert st.json()["status"] == "draft"

    posted = client.post(f"/hr/settlements/{sid}/post")
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "posted"
    entry_id = posted.json()["journal_entry_id"]

    # قيد HR-EOSB بمبلغ المستحق — متوازن داخلياً (المحرك يفرض ذلك) وبحسابين صحيحين
    entries = [e for e in client.get("/journal-entries").json() if e.get("reference") == f"HR-EOSB-{sid}"]
    assert entries and entries[0]["id"] == entry_id
    total_due = float(st.json()["total_due"])
    items = entries[0]["items"]
    assert sum(float(i["debit"]) for i in items) == total_due
    assert sum(float(i["credit"]) for i in items) == total_due

    # ترحيل مرتين → 409
    assert client.post(f"/hr/settlements/{sid}/post").status_code == 409


def test_overtime_review_flow(api):
    client, engine = api
    emp = client.post("/hr/employees", json={"full_name": "موظف أوفر"}).json()
    att = client.post("/hr/attendance", json={
        "employee_id": emp["id"], "work_date": "2026-11-10", "status": "present",
        "check_in": "08:00", "check_out": "20:00", "overtime_type": "day",
        "overtime_approved": False,
    })
    assert att.status_code == 201, att.text
    att_id = att.json()["id"]
    assert att.json()["overtime_approved"] is False
    # بدون وردية لا يُحسب أوفر تايم آلياً — نضبط الدقائق كأنها جاءت من جهاز بصمة
    with engine.begin() as conn:
        conn.execute(text("UPDATE hr_attendance SET overtime_minutes = 120 WHERE id = :i"), {"i": att_id})

    approved = client.post(f"/hr/attendance/{att_id}/overtime-review", json={"approved": True})
    assert approved.status_code == 200, approved.text
    assert approved.json()["overtime_approved"] is True

    # سجل بلا أوفر تايم → 422
    att2 = client.post("/hr/attendance", json={
        "employee_id": emp["id"], "work_date": "2026-11-11", "status": "present",
        "check_in": "08:00", "check_out": "16:00",
    }).json()
    r = client.post(f"/hr/attendance/{att2['id']}/overtime-review", json={"approved": True})
    assert r.status_code == 422
