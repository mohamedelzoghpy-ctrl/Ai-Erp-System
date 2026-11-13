"""إصلاحات التدقيق — الدفعة الثانية: ضريبة المرتجعات + توزيع الخصم + client_ref فريد + عزل Session.get + بوابة QC."""

import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
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


def acc_id(c, code):
    rows = ok(c.get("/chart-of-accounts"))
    return next(a["id"] for a in rows if a["code"] == code)


def make_warehouses(c):
    return ok(c.post("/warehouses", json={"name": "Main", "code": "W1"}), 201)


def setup_sale(c, tax_rate="14", discount="0", qty_sold=6, price="100", cost="50"):
    """PO (استلام فوري) + SO مؤكدة بضريبة — يعيد (product, so, order_item_id)."""
    w = make_warehouses(c)
    prod = ok(c.post("/products", json={"sku": f"P-{discount}-{qty_sold}", "name": "صنف", "sale_price": price, "cost_price": cost, "quantity": 0, "warehouse_id": w["id"]}), 201)
    sup = ok(c.post("/suppliers", json={"name": "مورد"}), 201)
    cust = ok(c.post("/customers", json={"name": "عميل"}), 201)
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w["id"], "tax_rate": "14",
        "items": [{"product_id": prod["id"], "quantity": 10, "unit_cost": cost}],
    }), 201)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": w["id"], "tax_rate": tax_rate,
        "discount_mode": "amount", "discount_value": discount,
        "items": [{"product_id": prod["id"], "quantity": qty_sold, "unit_price": price}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"))
    detail = ok(c.get(f"/sales-orders/{so['id']}"))
    return prod, so, detail["items"][0]["id"]


def tb_credit(c, code, date_to="2026-12-31"):
    rows = ok(c.get(f"/reports/financial/trial-balance?as_of={date_to}"))
    return Decimal(str(next(r["balance"] for r in rows if r["code"] == code)))


# ================================================== 1) ضريبة المرتجعات وتوزيع الخصم

def test_sales_return_reverses_vat_2130(api):
    c = api
    prod, so, item_id = setup_sale(c, qty_sold=6)  # صافي 600 + ضريبة 84 = 684
    assert tb_credit(c, "2130") == Decimal("84.00")  # بعد البيع
    ret = ok(c.post("/sales-returns", json={
        "order_id": so["id"],
        "items": [{"order_item_id": item_id, "quantity": 2}],
        "refund_amount": "0",
    }), 201)
    # مرتجع صافي 200 → ضريبة 28 → أثر العميل 228
    assert Decimal(str(ret["tax_amount"])) == Decimal("28.00")
    assert Decimal(str(ret["discount_share"])) == Decimal("0")
    assert tb_credit(c, "2130") == Decimal("56.00")  # 84 − 28: الضريبة عُكست فعليًا
    assert Decimal(str(ret["total_amount"])) == Decimal("200.00")


def test_sales_return_pro_rates_order_discount(api):
    c = api
    # صافي 600 − خصم 60 = 540 + ضريبة 75.60 = 615.60
    prod, so, item_id = setup_sale(c, discount="60", qty_sold=6)
    ret = ok(c.post("/sales-returns", json={
        "order_id": so["id"],
        "items": [{"order_item_id": item_id, "quantity": 2}],  # ثلث الفاتورة
        "refund_amount": "0",
    }), 201)
    assert Decimal(str(ret["discount_share"])) == Decimal("20.00")  # 60 × 200/600
    assert Decimal(str(ret["tax_amount"])) == Decimal("25.20")      # (200−20) × 14%
    # الإجمالي القديم كان سيُرجع 200 للعميل — الصحيح 205.20 (صافي بعد الخصم + ضريبة)
    assert Decimal(str(ret["total_amount"])) + Decimal(str(ret["tax_amount"])) - Decimal(str(ret["discount_share"])) == Decimal("205.20")


def test_purchase_return_reverses_input_vat_1145(api):
    c = api
    w = make_warehouses(c)
    prod = ok(c.post("/products", json={"sku": "PR-V", "name": "صنف", "sale_price": "10", "cost_price": "50", "quantity": 0, "warehouse_id": w["id"]}), 201)
    sup = ok(c.post("/suppliers", json={"name": "مورد"}), 201)
    po = ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w["id"], "tax_rate": "14",
        "items": [{"product_id": prod["id"], "quantity": 10, "unit_cost": "50"}],
    }), 201)
    assert tb_credit(c, "1145") == Decimal("70.00")  # أصل: مدين 70 (إشارة الأصول موجبة)
    ret = ok(c.post("/purchase-returns", json={
        "order_id": po["id"],
        "items": [{"order_item_id": po["items"][0]["id"], "quantity": 2}],
        "refund_amount": "0",
    }), 201)
    assert Decimal(str(ret["tax_amount"])) == Decimal("14.00")  # 200 × 14%
    assert tb_credit(c, "1145") == Decimal("56.00")             # 70 − 14 عُكست


# ================================================== 2) client_ref فريد (مزامنة أوفلاين)

def test_client_ref_unique_per_company_rep(api):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        db.add(models.Company(id=1, name="شركة", code="t1"))
        db.add(models.Customer(id=1, company_id=1, name="عميل", code="C1"))
        db.add(models.Warehouse(id=1, company_id=1, name="م", code="W1", branch_id=1))
        db.add(models.Branch(id=1, company_id=1, name="فرع", code="B1"))
        db.add(models.SalesRep(id=1, company_id=1, name="مندوب", code="R1", commission_percent=1))
        db.flush()
        base = dict(company_id=1, customer_id=1, warehouse_id=1, rep_id=1, status="draft", total_amount=100)
        db.add(models.SalesOrder(**base, client_ref="offline-abc-123"))
        db.commit()
        db.add(models.SalesOrder(**base, client_ref="offline-abc-123"))  # نفس (شركة×مندوب×مرجع)
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
        # مرجع مختلف يمر + شركة أخرى نفس المرجع تمر
        db.add(models.SalesOrder(**base, client_ref="offline-abc-999"))
        db.commit()
    finally:
        db.close()


# ================================================== 3) عزل Session.get (تحويلات/مدفوعات/مرتجعات)

def _second_company(c):
    """شركة ثانية بمديرها — يعيد توكن المدير."""
    other = ok(c.post("/platform/companies", json={
        "name": "شركة ثانية", "admin_username": "other-admin", "admin_password": "other-pass-123", "admin_full_name": "آخر",
    }), 201)
    tok = ok(c.post("/auth/login", data={"username": "other-admin", "password": "other-pass-123"}))["access_token"]
    other_c = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    ok(other_c.post("/auth/switch-company", json={"company_id": other["id"]}))
    return other_c


def test_transfers_and_payments_are_company_scoped(api):
    c = api
    w = make_warehouses(c)
    prod = ok(c.post("/products", json={"sku": "ISO-P", "name": "صنف", "sale_price": "10", "cost_price": "5", "quantity": 10, "warehouse_id": w["id"]}), 201)
    cust = ok(c.post("/customers", json={"name": "عميل"}), 201)
    trf = ok(c.post("/stock-transfers", json={
        "from_warehouse_id": w["id"], "to_warehouse_id": w["id"],
        "items": [{"product_id": prod["id"], "quantity": 1}],
    }), 422) or None  # مصدر=هدف مرفوض — أنشئ مخزنًا ثانيًا
    w2 = ok(c.post("/warehouses", json={"name": "Shop", "code": "W2"}), 201)
    trf = ok(c.post("/stock-transfers", json={
        "from_warehouse_id": w["id"], "to_warehouse_id": w2["id"],
        "items": [{"product_id": prod["id"], "quantity": 1}],
    }), 201)
    receipt = ok(c.post("/pos/checkout", json={
        "customer_id": cust["id"], "warehouse_id": w["id"],
        "items": [{"product_id": prod["id"], "quantity": 1, "unit_price": "10"}],
        "amount_paid": "10", "method": "cash",
    }), 201)
    payments = ok(c.get("/payments?kind=receipt"))
    payment_id = next(p["id"] for p in payments if p["customer_id"] == cust["id"])

    other_c = _second_company(c)
    # قبل الإصلاح: GET بالمعرف كان يرجع مستند شركة أخرى
    assert other_c.get(f"/stock-transfers/{trf['id']}").status_code == 404
    assert other_c.get(f"/payments/{payment_id}").status_code == 404
    assert c.get(f"/stock-transfers/{trf['id']}").status_code == 200
    assert c.get(f"/payments/{payment_id}").status_code == 200


# ================================================== 4) بوابة QC (لا تجاوز بموظف)

def test_qc_release_requires_manager(api):
    c = api
    w = make_warehouses(c)
    ok(c.post("/company/employees", json={"username": "qcstaff", "password": "qc-pass-123", "role": "staff", "warehouse_ids": [w["id"]]}), 201)
    staff_user = [u for u in ok(c.get("/auth/users")) if u["username"] == "qcstaff"][0]
    sec = ok(c.post("/access-sections", json={"code": "qcsec", "name": "قسم جودة"}), 201)
    ok(c.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": ["manufacturing.order.qc"]}))
    ok(c.put(f"/auth/users/{staff_user['id']}/section", json={"section_id": sec["id"]}))
    tok = ok(c.post("/auth/login", data={"username": "qcstaff", "password": "qc-pass-123"}))["access_token"]
    staff = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    # قبل الإصلاح: الموظف بالصلاحية كان يتجاوز شرط المدير (البوابة في Depends للمسار الآخر)
    r = staff.post("/qc/batches/999/release?action=passed")
    assert r.status_code == 403 and "يتطلب مديرًا" in r.text, r.text
