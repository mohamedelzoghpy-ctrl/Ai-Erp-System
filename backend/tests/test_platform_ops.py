"""اختبارات حزمة الأمان والتشغيل (2026-11-12):
إبطال الجلسات · النسخ الاحتياطي/الاستعادة · FEFO · مطابقة مخزون-دفاتر ·
الدفع المقسّم POS · التسليم الجزئي · حد اعتماد القيود من إعداد الشركة.
"""
import gzip
import json
import uuid as _uuid
from datetime import date, timedelta
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


def _product(c, qty=0, wh=None, cost="40", price="100"):
    return ok(c.post("/products", json={
        "sku": f"SK-{_uuid.uuid4().hex[:6]}", "name": "صنف", "sale_price": price,
        "cost_price": cost, "quantity": qty, "warehouse_id": wh["id"] if wh else None,
    }), 201)


# ================================================== 1) إبطال الجلسات
def test_logout_all_and_password_change_revoke_tokens(api):
    c = api
    old_token = c.headers["Authorization"]
    # logout-all يبطل التوكن الحالي فورًا
    assert c.post("/auth/logout-all").status_code == 204
    assert c.get("/auth/me").status_code == 401
    # دخول جديد يعمل
    tok = c.post("/auth/login", data={"username": "boss", "password": "long-password-123"}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    assert c.get("/auth/me").status_code == 200
    # تغيير الباسورد ذاتيًا: يبطل القديم ويرجع توكن جديد
    r = ok(c.post("/auth/change-password", json={"old_password": "long-password-123", "new_password": "newer-password-1"}), 200)
    assert c.get("/auth/me").status_code == 401
    c.headers["Authorization"] = f"Bearer {r['access_token']}"
    assert c.get("/auth/me").status_code == 200
    # باسورد قديم غلط → 403
    assert c.post("/auth/change-password", json={"old_password": "wrong-password", "new_password": "another-pass-1"}).status_code == 403
    # نفس الباسورد → 422 (وإلا نكسر اختبار setup الثاني)
    assert c.post("/auth/change-password", json={"old_password": "newer-password-1", "new_password": "newer-password-1"}).status_code == 422
    # استرجاع الباسورد الأصلي (لن تحتاجه — fixture جديد بكل اختبار)


# ================================================== 2) النسخ الاحتياطي والاستعادة
def test_backup_create_download_restore_roundtrip(api, tmp_path, monkeypatch):
    c = api
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    # بيانات قبل النسخة
    wh1, _ = make_warehouses(c)
    p = _product(c, wh=wh1, qty=7)
    ok(c.post("/admin/backups"), 201)
    files = ok(c.get("/admin/backups"))
    assert len(files) == 1 and files[0]["name"].endswith(".json.gz")
    name = files[0]["name"]
    # تنزيل والتحقق أنه gzip-JSON سليم
    dl = c.get(f"/admin/backups/{name}/download")
    assert dl.status_code == 200 and dl.content[:2] == b"\x1f\x8b"
    data = json.loads(gzip.decompress(dl.content))
    assert data["format"] == "mozad-backup-1" and "products" in data["tables"]
    # غيّر بيانات ثم استعدها
    ok(c.post(f"/products/{p['id']}/adjust-stock", json={"change": 3, "warehouse_id": wh1["id"]}))
    assert ok(c.get(f"/products/{p['id']}/stock"))[0]["quantity"] == 10.0
    r = ok(c.post(f"/admin/backups/{name}/restore", json={"confirm": "استعادة"}), 200)
    assert r["restored"] is True and r["rows"] > 0
    assert ok(c.get(f"/products/{p['id']}/stock"))[0]["quantity"] == 7.0  # رجعت كما في النسخة
    # تأكيد غلط → 422
    assert c.post(f"/admin/backups/{name}/restore", json={"confirm": "نعم"}).status_code == 422
    # حذف
    assert c.delete(f"/admin/backups/{name}").status_code == 204
    assert ok(c.get("/admin/backups")) == []


# ================================================== 3) FEFO
def test_fefo_consumes_earliest_expiry_first(api):
    c = api
    wh, _ = make_warehouses(c)
    sup = ok(c.post("/suppliers", json={"name": "مورد FEFO"}), 201)
    p = _product(c)
    today = date.today()
    # لوطان: قريب الانتهاء (يدوي) ثم شراء بعيد الانتهاء
    ok(c.post("/lots", json={"product_id": p["id"], "warehouse_id": wh["id"], "lot_code": "L-NEAR",
                             "qty": 5, "expiry_date": str(today + timedelta(days=5))}), 201)
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": wh["id"], "payment_mode": "credit",
        "items": [{"product_id": p["id"], "quantity": 8, "unit_cost": "40"}],
    }), 201)
    # اضبط لوط الشراء بتاريخ بعيد — نضيف لوطًا ثالثًا بعيدًا باليد لمحاكاته
    ok(c.post("/lots", json={"product_id": p["id"], "warehouse_id": wh["id"], "lot_code": "L-FAR",
                             "qty": 8, "expiry_date": str(today + timedelta(days=300))}), 201)
    # بيع 6 → يجب أن يخصم 5 من NEAR ثم 1 من FAR
    cust = ok(c.post("/customers", json={"name": "عميل FEFO"}), 201)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 6}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    lots = {l["lot_code"]: float(l["qty_remaining"]) for l in ok(c.get("/lots")) if l["product_id"] == p["id"]}
    assert lots["L-NEAR"] == 0.0      # الأقرب انتهاءً خُصم بالكامل
    assert lots["L-FAR"] == 7.0       # والأبعد خُصم منه 1 فقط


# ================================================== 4) مطابقة المخزون مع الدفاتر
def test_inventory_vs_ledger_reconcile(api):
    c = api
    wh, _ = make_warehouses(c)
    sup = ok(c.post("/suppliers", json={"name": "مورد مطابقة"}), 201)
    p = _product(c)
    ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": wh["id"], "payment_mode": "credit", "tax_rate": "0",
        "items": [{"product_id": p["id"], "quantity": 10, "unit_cost": "40"}],
    }), 201)
    r = ok(c.get("/reports/financial/inventory-reconcile"), 200)
    # مشتريات آجل: مدين 1101 بمبلغ 400 (بلا ضريبة) والمخزون المحسوب 10×40 = 400
    assert Decimal(str(r["computed_value"])) == Decimal("400.00")
    assert Decimal(str(r["ledger_inventory"])) == Decimal("400.00")
    assert Decimal(str(r["difference"])) == Decimal("0.00")
    x = c.get("/reports/financial/inventory-reconcile/xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


# ================================================== 5) الدفع المقسّم POS
def test_pos_split_payment_two_legs(api):
    c = api
    wh, _ = make_warehouses(c)
    p = _product(c, wh=wh, qty=10, price="100")
    br = ok(c.post("/company/branches", json={"name": "فرع مقسّم"}), 201)
    safe = ok(c.post("/safes", json={"name": "خزينة مقسّم", "branch_id": br["id"]}), 201)
    bank = ok(c.post("/banks", json={"name": "بنك مقسّم", "branch_id": br["id"]}), 201)
    safe_before = Decimal(str(ok(c.get(f"/safes/{safe['id']}"))["balance"]))
    bank_before = Decimal(str(ok(c.get(f"/banks/{bank['id']}"))["balance"]))
    r = ok(c.post("/pos/checkout", json={
        "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 2, "unit_price": "100"}],
        "payments": [
            {"method": "cash", "amount": "120", "safe_id": safe["id"]},
            {"method": "bank", "amount": "80", "bank_id": bank["id"]},
        ],
    }), 201)
    assert Decimal(str(r["total"])) == Decimal("200")
    assert Decimal(str(r["paid"])) == Decimal("200")
    assert Decimal(str(ok(c.get(f"/safes/{safe['id']}"))["balance"])) == safe_before + Decimal("120")
    assert Decimal(str(ok(c.get(f"/banks/{bank['id']}"))["balance"])) == bank_before + Decimal("80")
    # القيود: سندا دفع بمرجعين مختلفين
    entries = ok(c.get("/journal-entries?limit=50"))
    refs = [e["reference"] for e in entries]
    assert f"SO-{r['order_id']}-1" in refs and f"SO-{r['order_id']}-2" in refs
    # مبلغ زائد على الإجمالي مرفوض
    assert c.post("/pos/checkout", json={
        "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 1, "unit_price": "100"}],
        "payments": [
            {"method": "cash", "amount": "60", "safe_id": safe["id"]},
            {"method": "bank", "amount": "60", "bank_id": bank["id"]},
        ],
    }).status_code == 422


# ================================================== 6) التسليم الجزئي
def test_partial_delivery_flow(api):
    c = api
    wh, _ = make_warehouses(c)
    p = _product(c, wh=wh, qty=20, price="100")
    cust = ok(c.post("/customers", json={"name": "عميل تسليم"}), 201)
    so = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 10}],
    }), 201)
    ok(c.post(f"/sales-orders/{so['id']}/confirm"), 200)
    # المخزون: 20 − 10 تأكيد − 4 تسليم = 6
    ok(c.post(f"/sales-orders/{so['id']}/deliveries", json={"items": [{"product_id": p["id"], "quantity": 4}]}), 201)
    stocks = {r["warehouse_id"]: float(r["quantity"]) for r in ok(c.get(f"/products/{p['id']}/stock"))}
    assert stocks[wh["id"]] == 6.0
    # تجاوز المتبقي للتسليم → 409
    r = c.post(f"/sales-orders/{so['id']}/deliveries", json={"items": [{"product_id": p["id"], "quantity": 7}]})
    assert r.status_code == 409 and "6" in r.json()["detail"]
    # تسليم 6 الباقية → المخزون يهبط لصفر + ملاحظة «مُسلَّمة كاملة»
    ok(c.post(f"/sales-orders/{so['id']}/deliveries", json={"items": [{"product_id": p["id"], "quantity": 6}]}), 201)
    stocks = {r["warehouse_id"]: float(r["quantity"]) for r in ok(c.get(f"/products/{p['id']}/stock"))}
    assert stocks.get(wh["id"], 0) == 0.0
    assert "مُسلَّمة كاملة" in ok(c.get(f"/sales-orders/{so['id']}"))["notes"]
    # سجل التسليمات
    moves = ok(c.get(f"/sales-orders/{so['id']}/deliveries"))
    assert len(moves) == 2 and all(m["change"] < 0 for m in moves)
    # مسودة → مرفوضة
    so2 = ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": wh["id"],
        "items": [{"product_id": p["id"], "quantity": 1}],
    }), 201)
    assert c.post(f"/sales-orders/{so2['id']}/deliveries", json={"items": [{"product_id": p["id"], "quantity": 1}]}).status_code == 409


# ================================================== 7) حد الاعتماد من إعداد الشركة
def test_company_threshold_overrides_env(api, monkeypatch):
    from app.routers import journal_entries as je_mod
    monkeypatch.setattr(je_mod, "APPROVAL_THRESHOLD", Decimal("0"))  # env معطل
    c = api
    # حد الشركة 500
    ok(c.patch("/company", json={"je_approval_threshold": "500"}))
    br = ok(c.post("/company/branches", json={"name": "فرع اعتماد"}), 201)
    r = c.post("/auth/users", json={"username": "jclerk", "password": "long-password-123", "role": "staff",
                                    "branch_ids": [br["id"]]})
    uid = r.json()["id"]
    sec = ok(c.post("/access-sections", json={"code": f"th{uid}", "name": "قسم قيود"}), 201)
    ok(c.put(f"/access-sections/{sec['id']}/permissions", json={"permission_codes": ["accounting.journal.create", "accounting.account.view"]}))
    ok(c.put(f"/auth/users/{uid}/section", json={"section_id": sec["id"]}))
    tok = c.post("/auth/login", data={"username": "jclerk", "password": "long-password-123"}).json()["access_token"]
    staff = TestClient(app)
    staff.headers["Authorization"] = f"Bearer {tok}"
    cash = {a["code"]: a for a in ok(c.get("/chart-of-accounts"))}["1111"]
    other = {a["code"]: a for a in ok(c.get("/chart-of-accounts"))}["1112"]
    # 600 > 500 → معلّق رغم أن env معطل
    r = ok(staff.post("/journal-entries", json={"description": "فوق حد الشركة", "items": [
        {"account_id": cash["id"], "debit": "600", "credit": "0"},
        {"account_id": other["id"], "debit": "0", "credit": "600"},
    ]}), 201)
    assert r["status"] == "pending_approval"
    # إلغاء حد الشركة → يُرحّل فورًا
    ok(c.patch("/company", json={"je_approval_threshold": None}))
    r2 = ok(staff.post("/journal-entries", json={"description": "بلا حد", "items": [
        {"account_id": cash["id"], "debit": "900", "credit": "0"},
        {"account_id": other["id"], "debit": "0", "credit": "900"},
    ]}), 201)
    assert r2["status"] == "posted"
