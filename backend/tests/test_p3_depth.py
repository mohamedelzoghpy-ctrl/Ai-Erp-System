"""المرحلة 3: عمق المخازن والمحاسبي — عكس القيود، إعادة التقييم، تسويات البنك،
بوابة فحص الجودة، وتقرير الهالك."""
import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models as m
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
    client.post("/auth/setup", json={"username": "p3-admin", "password": "strong-password-123"})
    token = client.post("/auth/login", data={"username": "p3-admin", "password": "strong-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client, engine
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------- P3.5: عكس القيود

def test_delete_posted_entry_creates_reversal_not_hard_delete(api):
    client, engine = api
    client.post("/chart-of-accounts/seed")
    by_code = {a["code"]: a["id"] for a in client.get("/chart-of-accounts").json()}
    r = client.post("/journal-entries", json={
        "description": "قيد تجريبي للعكس",
        "items": [
            {"account_id": by_code["1111"], "debit": "300", "credit": "0"},
            {"account_id": by_code["4101"], "debit": "0", "credit": "300"},
        ],
    })
    assert r.status_code == 201, r.text
    je_id = r.json()["id"]

    # الحذف → عكس آلي وليس حذف
    assert client.delete(f"/journal-entries/{je_id}").status_code == 204
    original = client.get(f"/journal-entries/{je_id}").json()
    assert original["status"] == "voided"
    # قيد العكس موجود بمرجع VOID وبنود معكوسة
    reversal = next(e for e in client.get("/journal-entries").json() if e.get("reference") == f"VOID-{je_id}")
    rev_items = reversal["items"]
    assert sum(float(i["debit"]) for i in rev_items) == 300.0

    # ميزان المراجعة ما زال يتوازن (الأصل + العكس = صفر صافي)
    tb = client.get("/reports/financial/trial-balance").json()
    assert abs(sum(float(r["balance"]) for r in tb)) < 0.01

    # لا عكس مرتين
    assert client.delete(f"/journal-entries/{je_id}").status_code == 409


def test_delete_pending_entry_is_hard_delete_without_balances(api):
    """قيد معلق (maker-checker): أرصدته لم تُطبق — الحذف نهائي مباشر بلا عكس."""
    from decimal import Decimal as D
    client, engine = api
    client.post("/chart-of-accounts/seed")
    # حد الشركة 1 → أي قيد موظف يعلق
    assert client.patch("/company", json={"je_approval_threshold": "1"}).status_code == 200
    br = client.post("/company/branches", json={"name": "فرع p3"}).json()
    u = client.post("/auth/users", json={"username": "p3clerk", "password": "clerk-pass-123", "role": "staff",
                                         "branch_ids": [br["id"]]}).json()
    sec = client.post("/access-sections", json={"code": "p3sec", "name": "قسم p3"}).json()
    client.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": ["accounting.journal.create", "accounting.account.view"]})
    client.put(f"/auth/users/{u['id']}/section", json={"section_id": sec["id"]})
    tok = client.post("/auth/login", data={"username": "p3clerk", "password": "clerk-pass-123"}).json()["access_token"]
    staff = TestClient(app)
    staff.headers["Authorization"] = f"Bearer {tok}"

    by_code = {a["code"]: a["id"] for a in client.get("/chart-of-accounts").json()}
    r = staff.post("/journal-entries", json={
        "description": "قيد معلق سيُرفض ويُحذف",
        "items": [
            {"account_id": by_code["1111"], "debit": "10", "credit": "0"},
            {"account_id": by_code["4101"], "debit": "0", "credit": "10"},
        ],
    })
    assert r.status_code == 201 and r.json()["status"] == "pending_approval", r.text
    je_id = r.json()["id"]

    # رفض المدير يحذف المعلق بنفسه (أرصدته لم تُطبق أصلًا) — ولا عكس يُنشأ
    assert client.post(f"/journal-entries/{je_id}/reject").status_code == 200
    assert client.get(f"/journal-entries/{je_id}").status_code == 404
    # لا قيد عكس أُنشئ
    voids = [e for e in client.get("/journal-entries").json() if e.get("reference") == f"VOID-{je_id}"]
    assert voids == []


# ---------------------------------------------------------------- P3.3: إعادة التقييم

def test_cost_price_change_posts_revaluation_entry(api):
    client, engine = api
    w1, _ = make_warehouses(client)
    product = make_product(client, "RV1", 10, w1["id"], cost_price="50")

    # رفع التكلفة 50 → 60 بكمية 10 = فرق +100 يُرحَّل
    patched = client.patch(f"/products/{product['id']}", json={"cost_price": "60"})
    assert patched.status_code == 200, patched.text
    entries = [e for e in client.get("/journal-entries").json() if e.get("reference") == f"REVAL-{product['id']}"]
    assert entries, "لا قيد إعادة تقييم"
    items = entries[0]["items"]
    assert sum(float(i["debit"]) for i in items) == 100.0
    inv_id = next(a["id"] for a in client.get("/chart-of-accounts").json() if a["code"] == "1101")
    assert any(i["account_id"] == inv_id and float(i["debit"]) == 100.0 for i in items)

    # حساب المخزون ارتفع 100 فعلياً (رصيد مخزون يزيد بالإضافة)
    tb = {r["code"]: float(r["balance"]) for r in client.get("/reports/financial/trial-balance").json()}
    assert "1101" in tb

    # خفض التكلفة → قيد معاكس
    client.patch(f"/products/{product['id']}", json={"cost_price": "55"})
    entries2 = [e for e in client.get("/journal-entries").json() if e.get("reference") == f"REVAL-{product['id']}"]
    assert len(entries2) == 2


def test_cost_change_with_zero_qty_posts_nothing(api):
    client, engine = api
    w1, _ = make_warehouses(client)
    product = make_product(client, "RV2", 0, w1["id"], cost_price="50")
    client.patch(f"/products/{product['id']}", json={"cost_price": "99"})
    entries = [e for e in client.get("/journal-entries").json() if e.get("reference") == f"REVAL-{product['id']}"]
    assert entries == []


# ---------------------------------------------------------------- P3.4: تسويات البنك

def test_bank_post_unmatched_lines(api):
    client, engine = api
    client.post("/chart-of-accounts/seed")
    branch = client.post("/company/branches", json={"name": "فرع بنك"}).json()
    bank = client.post("/banks", json={"name": "بنك التسوية", "opening_balance": "0", "branch_id": branch["id"]}).json()

    csv_content = "date,description,amount,reference\n2026-11-01,خصم إداري غير مسجل,-75.50,FEE-1\n2026-11-02,إيداع غير مسجل,120.00,DEP-1\n"
    files = {"file": ("statement.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    imp = client.post(f"/banks/{bank['id']}/statements/import", files=files)
    assert imp.status_code == 201, imp.text

    r = client.post(f"/banks/{bank['id']}/statements/post-unmatched")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["posted"] == 2 and len(body["entry_ids"]) == 2

    # كل سطر مُوسم بقيدته — وإعادة الترحيل: صفر
    with engine.connect() as conn:
        posted = conn.execute(text("SELECT COUNT(*) FROM bank_statement_lines WHERE posted_in_entry_id IS NOT NULL")).scalar()
    assert posted == 2
    again = client.post(f"/banks/{bank['id']}/statements/post-unmatched").json()
    assert again["posted"] == 0

    # قيود التسوية موجودة بمرجع BNKREC
    entries = [e for e in client.get("/journal-entries").json() if str(e.get("reference", "")).startswith("BNKREC-")]
    assert len(entries) == 2
    # ميزان المراجعة يتوازن بعد التسويات
    tb = client.get("/reports/financial/trial-balance").json()
    assert abs(sum(float(row["balance"]) for row in tb)) < 0.01


# ---------------------------------------------------------------- P3.2: بوابة الجودة

def _produce_batch_with_pending_qc(client, engine):
    """دورة تصنيع حقيقية: خامة + BOM + أمر إنتاج + إنتاج دفعة (QC باقي pending)."""
    from tests.test_warehouse_stock import make_warehouses as mw
    w1, _ = mw(client)
    raw = make_product(client, "QCRAW", 100, w1["id"], cost_price="10")
    finished = make_product(client, "QCFIN", 0, w1["id"], cost_price="0", sale_price="100")
    bom = client.post("/boms", json={
        "product_id": finished["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": "2", "scrap_pct": "0", "notes": None}],
    }).json()
    po = client.post("/production-orders", json={
        "product_id": finished["id"], "qty_planned": 5, "raw_warehouse_id": w1["id"],
        "output_warehouse_id": w1["id"],
    }).json()
    issued = client.post(f"/production-orders/{po['id']}/issue")
    assert issued.status_code == 200, issued.text
    produced = client.post(f"/production-orders/{po['id']}/produce", json={"qty": 5})
    assert produced.status_code == 200, produced.text
    # لوط الإنتاج موجود برقم الدفعة
    with engine.connect() as conn:
        lot = conn.execute(
            text("SELECT lot_code, source, qty_remaining FROM stock_lots WHERE product_id=:p"),
            {"p": finished["id"]},
        ).fetchall()
    assert lot and lot[0][1] == "production" and float(lot[0][2]) == 5.0, lot
    return finished, lot[0][0], w1, po["id"]


def test_qc_gate_blocks_selling_pending_batches(api, monkeypatch):
    client, engine = api
    finished, batch_no, w1, po_id = _produce_batch_with_pending_qc(client, engine)
    customer = client.post("/customers", json={"name": "عميل QC"}).json()

    monkeypatch.setenv("QC_GATE", "1")
    try:
        order = client.post("/sales-orders", json={
            "customer_id": customer["id"], "warehouse_id": w1["id"],
            "items": [{"product_id": finished["id"], "quantity": 2, "unit_price": "100"}],
        })
        assert order.status_code == 201, order.text
        confirmed = client.post(f"/sales-orders/{order.json()['id']}/confirm")
        assert confirmed.status_code == 409, confirmed.text
        assert "بانتظار فحص الجودة" in confirmed.json()["detail"]
        assert batch_no in confirmed.json()["detail"]

        # اعتماد فحص الدفعة → البيع يمر
        with engine.connect() as conn:
            batch_id = conn.execute(
                text("SELECT id FROM production_batches WHERE batch_no=:b"), {"b": batch_no}
            ).scalar()
        qc = client.post(f"/production-orders/{po_id}/batches/{batch_id}/qc", json={"result": "passed"})
        assert qc.status_code == 200, qc.text
        confirmed2 = client.post(f"/sales-orders/{order.json()['id']}/confirm")
        assert confirmed2.status_code == 200, confirmed2.text
    finally:
        monkeypatch.delenv("QC_GATE", raising=False)


def test_qc_gate_off_by_default_allows_pending_sale(api):
    client, engine = api
    finished, batch_no, w1, po_id = _produce_batch_with_pending_qc(client, engine)
    customer = client.post("/customers", json={"name": "عميل عادي"}).json()
    order = client.post("/sales-orders", json={
        "customer_id": customer["id"], "warehouse_id": w1["id"],
        "items": [{"product_id": finished["id"], "quantity": 1, "unit_price": "100"}],
    })
    assert order.status_code == 201
    assert client.post(f"/sales-orders/{order.json()['id']}/confirm").status_code == 200


# ---------------------------------------------------------------- P3.6: تقرير الهالك

def test_writeoffs_report_after_lot_write_off(api):
    client, engine = api
    w1, _ = make_warehouses(client)
    product = make_product(client, "WO9", 0, w1["id"], cost_price="20")
    lot = client.post("/lots", json={
        "product_id": product["id"], "warehouse_id": w1["id"], "lot_code": "WO-REP", "qty": 10,
    }).json()
    client.post(f"/lots/{lot['id']}/write-off", json={"qty": 4, "reason": "تلف"})
    client.post(f"/lots/{lot['id']}/write-off", json={"qty": 2, "reason": "انتهاء صلاحية"})

    r = client.get("/reports/writeoffs")
    assert r.status_code == 200, r.text
    body = r.json()
    rows = [x for x in body["rows"] if x["product_id"] == product["id"]]
    assert rows and rows[0]["qty"] == 6.0 and rows[0]["movements"] == 2
    assert rows[0]["value"] == 120.0  # 6 × 20
    assert body["total_value"] >= 120.0
    assert client.get("/reports/writeoffs/xlsx").status_code == 200
