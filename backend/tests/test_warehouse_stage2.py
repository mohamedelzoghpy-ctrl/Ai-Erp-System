"""مخازن م2: استلام جزئي لأوامر الشراء + بوابة فحص جودة الاستلام (PO_QC_GATE)
+ التحويلات بمرحلة النقل (مخزن عابر + حساب «مخزون تحت النقل» 1103)."""

import pytest
from decimal import Decimal
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


def make_warehouses(c):
    w1 = ok(c.post("/warehouses", json={"name": "Main", "code": "W1"}), 201)
    w2 = ok(c.post("/warehouses", json={"name": "Shop", "code": "W2"}), 201)
    return w1, w2


def make_product(c, sku, qty, wid, **extra):
    return ok(c.post("/products", json={"sku": sku, "name": f"Item {sku}", "sale_price": "10", "cost_price": "5", "quantity": qty, "warehouse_id": wid, **extra}), 201)


def give_section(c, user_id: int, codes):
    sec = ok(c.post("/access-sections", json={"code": f"t{user_id}", "name": "قسم اختبار"}), 201)
    ok(c.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": codes}))
    ok(c.put(f"/auth/users/{user_id}/section", json={"section_id": sec["id"]}))
    return sec


def by_wh(c, pid):
    return {r["warehouse_id"]: r["quantity"] for r in ok(c.get(f"/products/{pid}/stock"))}


def total_qty(c, p):
    return Decimal(str(ok(c.get(f"/products/{p['id']}"))["quantity"]))


def transit_wh(c) -> int:
    rows = [w for w in ok(c.get("/warehouses")) if w.get("is_transit")]
    assert len(rows) == 1
    return rows[0]["id"]


def reconcile(c):
    return ok(c.get("/reports/financial/inventory-reconcile"))


def assert_books_match(c):
    """القاعدة الذهبية: تقييم المخزون المحسوب = 1101 + 1130 + 1103 دائمًا."""
    r = reconcile(c)
    assert Decimal(r["difference"]) == 0, r


def draft_po(c, supplier_id, warehouse_id, product_id, qty, cost="5"):
    return ok(c.post("/purchase-orders", json={
        "supplier_id": supplier_id, "warehouse_id": warehouse_id, "auto_receive": False,
        "items": [{"product_id": product_id, "quantity": qty, "unit_cost": cost}],
    }), 201)


# ================================================== 1) استلام جزئي لأمر الشراء

def test_po_draft_then_partial_then_full_receive(api):
    c = api
    w1, _ = make_warehouses(c)
    p = make_product(c, "PO-P1", 0, w1["id"])
    sup = ok(c.post("/suppliers", json={"name": "Supplier A"}), 201)

    po = draft_po(c, sup["id"], w1["id"], p["id"], 10)
    assert po["status"] == "draft"
    assert by_wh(c, p["id"]) == {} and total_qty(c, p) == 0
    assert po["items"][0]["received_quantity"] == 0

    # استلام جزء
    po = ok(c.post(f"/purchase-orders/{po['id']}/receive-partial", json={"items": [{"product_id": p["id"], "quantity": 4}]}))
    assert po["status"] == "partial"
    assert po["items"][0]["received_quantity"] == 4
    assert by_wh(c, p["id"]) == {w1["id"]: 4} and total_qty(c, p) == 4
    assert_books_match(c)  # قيد الاستلام الجزئي (20) مطابق للتقييم المحسوب

    # استلام الباقي
    po = ok(c.post(f"/purchase-orders/{po['id']}/receive-partial", json={"items": [{"product_id": p["id"], "quantity": 6}]}))
    assert po["status"] == "received"
    assert by_wh(c, p["id"]) == {w1["id"]: 10} and total_qty(c, p) == 10
    assert_books_match(c)  # مجموع القيود (50) = التقييم الكامل

    # لوط واحد متراكم لكل الاستلامات
    lots = ok(c.get(f"/lots?product_id={p['id']}"))
    assert len(lots) == 1 and Decimal(str(lots[0]["qty_received"])) == 10


def test_po_partial_over_receipt_needs_permission(api):
    c = api
    w1, _ = make_warehouses(c)
    p = make_product(c, "PO-P2", 0, w1["id"])
    sup = ok(c.post("/suppliers", json={"name": "Supplier B"}), 201)
    po = draft_po(c, sup["id"], w1["id"], p["id"], 10)

    # مدير النظام (*) يتجاوز — لكن بلا تجاوز فعلي يرفع 409 للموظف فقط؛ نبدأ بالمسار المحظور
    ok(c.post(f"/purchase-orders/{po['id']}/receive-partial", json={"items": [{"product_id": p["id"], "quantity": 5}]}))

    ok(c.post("/company/employees", json={"username": "buyer", "password": "buyer-password-123", "role": "staff", "warehouse_ids": [w1["id"]]}), 201)
    buyer = [u for u in ok(c.get("/auth/users")) if u["username"] == "buyer"][0]
    give_section(c, buyer["id"], ["purchasing.order.create", "purchasing.order.view", "purchasing.order.receive"])
    tok = ok(c.post("/auth/login", data={"username": "buyer", "password": "buyer-password-123"}))["access_token"]
    staff = TestClient(app, headers={"Authorization": f"Bearer {tok}"})

    r = staff.post(f"/purchase-orders/{po['id']}/receive-partial", json={"items": [{"product_id": p["id"], "quantity": 6}]})
    assert r.status_code == 409 and "استلام أكثر من المطلوب" in r.text, r.text

    # الترقية بالصلاحية تفتح التجاوز
    sec = ok(c.post("/access-sections", json={"code": "bover", "name": "قسم تجاوز"}), 201)
    ok(c.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": ["purchasing.order.receive", "purchasing.order.over_receive"]}))
    ok(c.put(f"/auth/users/{buyer['id']}/section", json={"section_ids": [s["id"] for s in ok(c.get('/access-sections')) if s["code"] in ("t" + str(buyer["id"]), "bover")]}))
    tok = ok(c.post("/auth/login", data={"username": "buyer", "password": "buyer-password-123"}))["access_token"]
    staff = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    po2 = ok(staff.post(f"/purchase-orders/{po['id']}/receive-partial", json={"items": [{"product_id": p["id"], "quantity": 6}]}))
    assert po2["status"] == "received"
    assert by_wh(c, p["id"]) == {w1["id"]: 11}  # 5 + 6 (تجاوز وحدة)
    assert_books_match(c)


def test_po_partial_rejects_wrong_states_and_foreign_product(api):
    c = api
    w1, _ = make_warehouses(c)
    p = make_product(c, "PO-P3", 0, w1["id"])
    other = make_product(c, "PO-P4", 0, w1["id"])
    sup = ok(c.post("/suppliers", json={"name": "Supplier C"}), 201)
    po = draft_po(c, sup["id"], w1["id"], p["id"], 10)

    ok(c.post(f"/purchase-orders/{po['id']}/receive-partial", json={"items": [{"product_id": other["id"], "quantity": 1}]}), 422)
    ok(c.post(f"/purchase-orders/{po['id']}/cancel"))
    r = c.post(f"/purchase-orders/{po['id']}/receive-partial", json={"items": [{"product_id": p["id"], "quantity": 1}]})
    assert r.status_code == 409, r.text


def test_legacy_full_receive_backfills_received_quantity(api):
    c = api
    w1, _ = make_warehouses(c)
    p = make_product(c, "PO-P5", 0, w1["id"])
    sup = ok(c.post("/suppliers", json={"name": "Supplier D"}), 201)
    po = draft_po(c, sup["id"], w1["id"], p["id"], 7, cost="5")
    po = ok(c.post(f"/purchase-orders/{po['id']}/receive"))
    assert po["status"] == "received"
    assert Decimal(str(po["items"][0]["received_quantity"])) == 7
    assert by_wh(c, p["id"]) == {w1["id"]: 7}
    assert_books_match(c)


def test_po_cash_with_draft_rejected(api):
    c = api
    w1, _ = make_warehouses(c)
    p = make_product(c, "PO-P6", 0, w1["id"])
    sup = ok(c.post("/suppliers", json={"name": "Supplier E"}), 201)
    branch = ok(c.get("/company/branches"))[0]
    safe = ok(c.post("/safes", json={"name": "خزينة الاختبار", "code": "S1", "branch_id": branch["id"]}), 201)
    r = c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w1["id"], "auto_receive": False,
        "payment_mode": "cash", "safe_id": safe["id"],
        "items": [{"product_id": p["id"], "quantity": 5, "unit_cost": "5"}],
    })
    assert r.status_code == 422, r.text


# ================================================== 2) بوابة فحص جودة الاستلام

def _qc_setup(c, monkeypatch, sku="QC-A"):
    monkeypatch.setenv("PO_QC_GATE", "1")
    w1, _ = make_warehouses(c)
    p = make_product(c, sku, 0, w1["id"], qc_required=True)
    sup = ok(c.post("/suppliers", json={"name": f"Supplier {sku}"}), 201)
    return w1, p, sup


def test_qc_gate_blocks_sale_until_lot_released(api, monkeypatch):
    c = api
    w1, p, sup = _qc_setup(c, monkeypatch)
    po = ok(c.post("/purchase-orders", json={  # استلام فوري عادي
        "supplier_id": sup["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 10, "unit_cost": "5"}],
    }), 201)
    assert po["status"] == "received"
    lots = ok(c.get(f"/lots?product_id={p['id']}"))
    assert len(lots) == 1 and lots[0]["qc_status"] == "pending"

    # البيع/الـPOS محجوب — الكمية يغطيها لوط معلق
    cust = ok(c.post("/customers", json={"name": "Walk-in"}), 201)
    r = c.post("/pos/checkout", json={
        "customer_id": cust["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 2, "unit_price": "10"}], "amount_paid": "20", "method": "cash",
    })
    assert r.status_code == 409 and "فحص جودة الاستلام" in r.text, r.text

    # اعتماد الفحص يفتح البيع
    ok(c.post(f"/qc/lots/{lots[0]['id']}/release?action=passed"))
    ok(c.post("/pos/checkout", json={
        "customer_id": cust["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 2, "unit_price": "10"}], "amount_paid": "20", "method": "cash",
    }), 201)
    assert by_wh(c, p["id"]) == {w1["id"]: 8}
    assert_books_match(c)


def test_qc_gate_reject_zeroes_stock_to_scrap(api, monkeypatch):
    c = api
    w1, p, sup = _qc_setup(c, monkeypatch, sku="QC-B")
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 6, "unit_cost": "5"}],
    }), 201)
    lot = ok(c.get(f"/lots?product_id={p['id']}"))[0]
    ok(c.post(f"/qc/lots/{lot['id']}/release?action=rejected&notes=تالف"))
    assert total_qty(c, p) == 0
    lot = ok(c.get(f"/lots?product_id={p['id']}"))[0]
    assert lot["qc_status"] == "rejected" and Decimal(str(lot["qty_remaining"])) == 0
    assert_books_match(c)  # قيمة اللوط رحلت إلى حساب الهالك — الدفاتر = التقييم (صفر)

    # رفض بلا سبب مرفوض + حكم مكرر مرفوض
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 3, "unit_cost": "5"}],
    }), 201)
    lots = ok(c.get(f"/lots?product_id={p['id']}"))
    lot2 = max(lots, key=lambda l: l["id"])  # لوط الاستلام الجديد
    assert lot2["qc_status"] == "pending"
    r = c.post(f"/qc/lots/{lot2['id']}/release?action=rejected")
    assert r.status_code == 422, r.text
    ok(c.post(f"/qc/lots/{lot2['id']}/release?action=passed"))
    r = c.post(f"/qc/lots/{lot2['id']}/release?action=passed")
    assert r.status_code == 409, r.text


def test_qc_gate_off_receipts_pass_even_for_sensitive_products(api, monkeypatch):
    c = api
    monkeypatch.delenv("PO_QC_GATE", raising=False)
    w1, _ = make_warehouses(c)
    p = make_product(c, "QC-C", 0, w1["id"], qc_required=True)
    sup = ok(c.post("/suppliers", json={"name": "Supplier QC-C"}), 201)
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 4, "unit_cost": "5"}],
    }), 201)
    lots = ok(c.get(f"/lots?product_id={p['id']}"))
    assert lots[0]["qc_status"] == "passed"
    cust = ok(c.post("/customers", json={"name": "Walk-in"}), 201)
    ok(c.post("/pos/checkout", json={
        "customer_id": cust["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "10"}], "amount_paid": "10", "method": "cash",
    }), 201)  # بلا بوابة — يبيع بحرية


# ================================================== 3) التحويلات بمرحلة النقل

def seed_stock(c, sku, warehouse_id, qty, cost="5"):
    """مخزون مبدئي بقيد محاسبي (استلام شراء فوري) — قاعدة المطابقة تتطلب دفاتر مسندة."""
    p = make_product(c, sku, 0, warehouse_id)
    sup = ok(c.post("/suppliers", json={"name": f"Supplier {sku}"}), 201)
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": warehouse_id,
        "items": [{"product_id": p["id"], "quantity": qty, "unit_cost": cost}],
    }), 201)
    assert_books_match(c)
    return p


def test_transfer_in_transit_partial_receive_completes(api):
    c = api
    w1, w2 = make_warehouses(c)
    p = seed_stock(c, "TR-A", w1["id"], 10)
    t = ok(c.post("/stock-transfers", json={"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"],
                                            "items": [{"product_id": p["id"], "quantity": 6}]}), 201)
    # pending: لا حركة بعد
    assert t["status"] == "pending"
    assert by_wh(c, p["id"]) == {w1["id"]: 10}

    t = ok(c.post(f"/stock-transfers/{t['id']}/approve"))
    assert t["status"] == "in_transit"
    tr = transit_wh(c)
    assert by_wh(c, p["id"]) == {w1["id"]: 4, tr: 6}
    assert Decimal(str(t["booked_value"])) == 30  # 6 × 5
    assert_books_match(c)  # 1101(20) + 1103(30) = 50 المحسوبة

    # استلام جزئي: نصفي الكمية
    t = ok(c.post(f"/stock-transfers/{t['id']}/receive", json={"items": [{"product_id": p["id"], "quantity": 2}]}))
    assert t["status"] == "in_transit"
    assert by_wh(c, p["id"]) == {w1["id"]: 4, tr: 4, w2["id"]: 2}
    assert Decimal(str(t["items"][0]["received_quantity"])) == 2
    assert_books_match(c)

    # الاستلام الكامل (بلا payload = كل المتبقي)
    t = ok(c.post(f"/stock-transfers/{t['id']}/receive"))
    assert t["status"] == "completed"
    assert by_wh(c, p["id"]) == {w1["id"]: 4, w2["id"]: 6} and transit_wh(c)
    assert_books_match(c)  # 1103 صفّر


def test_transfer_cancel_returns_remaining_to_source(api):
    c = api
    w1, w2 = make_warehouses(c)
    p = seed_stock(c, "TR-B", w1["id"], 10)
    t = ok(c.post("/stock-transfers", json={"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"],
                                            "items": [{"product_id": p["id"], "quantity": 6}]}), 201)
    ok(c.post(f"/stock-transfers/{t['id']}/approve"))
    ok(c.post(f"/stock-transfers/{t['id']}/receive", json={"items": [{"product_id": p["id"], "quantity": 2}]}))
    t = ok(c.post(f"/stock-transfers/{t['id']}/cancel"))
    assert t["status"] == "cancelled"
    tr = transit_wh(c)
    assert by_wh(c, p["id"]) == {w1["id"]: 8, w2["id"]: 2} and total_qty(c, p) == 10
    assert_books_match(c)


def test_transfer_receive_and_edit_guards(api):
    c = api
    w1, w2 = make_warehouses(c)
    p = seed_stock(c, "TR-C", w1["id"], 10)
    t = ok(c.post("/stock-transfers", json={"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"],
                                            "items": [{"product_id": p["id"], "quantity": 5}]}), 201)
    # استلام قبل الاعتماد ممنوع
    r = c.post(f"/stock-transfers/{t['id']}/receive")
    assert r.status_code == 409, r.text
    ok(c.post(f"/stock-transfers/{t['id']}/approve"))

    # تجاوز المتبقي ممنوع + صنف أجنبي ممنوع
    r = c.post(f"/stock-transfers/{t['id']}/receive", json={"items": [{"product_id": p["id"], "quantity": 6}]})
    assert r.status_code == 409, r.text
    r = c.post(f"/stock-transfers/{t['id']}/receive", json={"items": [{"product_id": 999, "quantity": 1}]})
    assert r.status_code == 422, r.text

    # تعديل أثناء الطريق (قبل أي استلام) يعكس ويعيد الحجز
    t = ok(c.put(f"/stock-transfers/{t['id']}/edit", json={"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"],
                                                           "items": [{"product_id": p["id"], "quantity": 8}]}))
    assert t["status"] == "in_transit" and Decimal(str(t["booked_value"])) == 40
    tr = transit_wh(c)
    assert by_wh(c, p["id"]) == {w1["id"]: 2, tr: 8}
    assert_books_match(c)

    # بعد استلام جزئي: التعديل والحذف ممنوعان، والإلغاء فقط للمتبقي
    ok(c.post(f"/stock-transfers/{t['id']}/receive", json={"items": [{"product_id": p["id"], "quantity": 1}]}))
    r = c.put(f"/stock-transfers/{t['id']}/edit", json={"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"],
                                                        "items": [{"product_id": p["id"], "quantity": 3}]})
    assert r.status_code == 409, r.text
    r = c.delete(f"/stock-transfers/{t['id']}")
    assert r.status_code == 409, r.text
    t = ok(c.post(f"/stock-transfers/{t['id']}/cancel"))
    assert by_wh(c, p["id"]) == {w1["id"]: 9, w2["id"]: 1}
    assert_books_match(c)


def test_transit_warehouse_is_not_transferable_and_delete_in_transit(api):
    c = api
    w1, w2 = make_warehouses(c)
    p = seed_stock(c, "TR-D", w1["id"], 10)
    t = ok(c.post("/stock-transfers", json={"from_warehouse_id": w1["id"], "to_warehouse_id": w2["id"],
                                            "items": [{"product_id": p["id"], "quantity": 4}]}), 201)
    ok(c.post(f"/stock-transfers/{t['id']}/approve"))
    tr = transit_wh(c)
    r = c.post("/stock-transfers", json={"from_warehouse_id": w1["id"], "to_warehouse_id": tr,
                                         "items": [{"product_id": p["id"], "quantity": 1}]})
    assert r.status_code == 422, r.text

    # حذف تحويل عابر (بلا استلام): عودة كل الكمية للمصدر
    ok(c.delete(f"/stock-transfers/{t['id']}"), 204)
    assert by_wh(c, p["id"]) == {w1["id"]: 10}
    assert_books_match(c)
