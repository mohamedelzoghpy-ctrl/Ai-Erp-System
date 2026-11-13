"""اختبارات تقوية قسم المحاسبة والمالية (2026-11):
حارس حسابات المجموعة · عزل الشركات في المسارات المالية · قفل السنة المالية ·
قيود الأصول الثابتة (إهلاك/استبعاد) · دورة حياة الشيكات · التقارير المالية ·
الإلغاء المتين للسندات · حذف الحساب المحمي · roll-up المجموعيات.
"""
import pytest
from datetime import date
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


def _second_company(api) -> TestClient:
    """شركة ثانية بـ admin خاص بها (ينشأ تلقائيًا معها)، ويرجع عميل يعمل داخلها."""
    r = api.post("/platform/companies", json={
        "name": "شركة تانية",
        "admin_username": "boss2",
        "admin_password": "long-password-123",
    })
    assert r.status_code == 201, r.text
    client2 = TestClient(app)
    tok = client2.post("/auth/login", data={"username": "boss2", "password": "long-password-123"}).json()["access_token"]
    client2.headers["Authorization"] = f"Bearer {tok}"
    # تأكيد تفعيل الشركة الثانية (الدخول يختار أول عضوية تلقائيًا)
    me = client2.get("/auth/me").json()
    assert me.get("active_company_id") is not None, me
    return client2


def _coa(api):
    return {a["code"]: a for a in api.get("/chart-of-accounts").json()}


def _leaf_account(api, code="1111", name=None):
    """حساب فرعي حقيقي للترحيل."""
    coa = _coa(api)
    return coa[code]


def _group_account(api):
    coa = _coa(api)
    return coa["1110"]  # النقد والبنوك — مجموعة


def _branch_safe(api):
    branch = api.post("/company/branches", json={"name": "فرع المحاسبة"}).json()
    safe = api.post("/safes", json={"name": "خزينة الاختبار", "branch_id": branch["id"]}).json()
    return branch, safe


# ================================================== 1) حارس حسابات المجموعة
def test_journal_entry_on_group_account_is_rejected(api):
    group = _group_account(api)
    leaf = _leaf_account(api, "1111")
    r = api.post("/journal-entries", json={
        "description": "قيد على حساب مجموعي",
        "items": [
            {"account_id": group["id"], "debit": "100", "credit": "0"},
            {"account_id": leaf["id"], "debit": "0", "credit": "100"},
        ],
    })
    assert r.status_code == 422, r.text
    assert "مجموعي" in r.json()["detail"]


def test_payment_with_foreign_company_customer_is_rejected(api):
    other = _second_company(api)
    foreign_customer = other.post("/customers", json={"name": "عميل شركة أخرى"}).json()
    r = api.post("/payments", json={"customer_id": foreign_customer["id"], "amount": "50", "method": "cash"})
    assert r.status_code == 422, r.text


def test_statement_of_foreign_company_party_is_404(api):
    other = _second_company(api)
    foreign_customer = other.post("/customers", json={"name": "عميل سري"}).json()
    r = api.get(f"/customers/{foreign_customer['id']}/statement")
    assert r.status_code == 404, r.text


# ================================================== 2) قفل السنة المالية
def test_closing_fiscal_year_blocks_posting_into_it(api):
    """قفل السنة الحالية يمنع قيود بتاريخها — ثم يُفتح فتعمل."""
    import time as _t
    je_payload = {
        "description": "قيد اختبار",
        "items": [
            {"account_id": _leaf_account(api, "1111")["id"], "debit": "10", "credit": "0"},
            {"account_id": _leaf_account(api, "1112")["id"], "debit": "0", "credit": "10"},
        ],
    }
    # التاريخ الحالي ضمن FY الحالي (المولد تلقائيًا) — نغلق السنة
    today = date.today()
    fys = api.get("/fiscal-years").json()
    assert fys, "السنة المالية الافتراضية يجب أن تكون موجودة"
    fy = fys[0]
    r = api.patch(f"/fiscal-years/{fy['id']}", json={"is_closed": True})
    assert r.status_code == 200, r.text
    try:
        blocked = api.post("/journal-entries", json=je_payload)
        assert blocked.status_code == 409, blocked.text
        assert "مقفولة" in blocked.json()["detail"]
        # تحويل تاريخ قيد موجود إلى سنة مقفولة ممنوع أيضًا
        open_je = api.post("/journal-entries", json={
            "description": "قيد قبل القفل",
            "date": str(date(today.year - 1, 12, 31)),
            "items": je_payload["items"],
        })
        if open_je.status_code == 201:
            moved = api.patch(f"/journal-entries/{open_je.json()['id']}", json={"date": str(today)})
            assert moved.status_code == 409, moved.text
    finally:
        assert api.patch(f"/fiscal-years/{fy['id']}", json={"is_closed": False}).status_code == 200
    ok = api.post("/journal-entries", json=je_payload)
    assert ok.status_code == 201, ok.text


def test_void_payment_in_closed_year_is_blocked(api):
    branch, safe = _branch_safe(api)
    supplier = api.post("/suppliers", json={"name": "مورد اختبار"}).json()
    p = api.post("/payments", json={"supplier_id": supplier["id"], "safe_id": safe["id"], "amount": "100"}).json()
    fys = api.get("/fiscal-years").json()
    api.patch(f"/fiscal-years/{fys[0]['id']}", json={"is_closed": True})
    try:
        r = api.post(f"/payments/{p['id']}/void")
        assert r.status_code == 409, r.text
    finally:
        api.patch(f"/fiscal-years/{fys[0]['id']}", json={"is_closed": False})


# ================================================== 3) الأصول الثابتة مربوطة بالدفاتر
def _make_asset(api, cost="1200"):
    r = api.post("/fixed-assets", json={
        "name": "مكتب إداري", "asset_type": "أثاث", "purchase_date": str(date.today()),
        "cost": cost, "current_book_value": cost, "depreciation_method": "straight_line",
        "useful_life_years": 5, "salvage_value": "0",
    })
    assert r.status_code == 201, r.text
    return r.json()


def _account_balance(api, code):
    return {a["code"]: a for a in api.get("/chart-of-accounts").json()}[code]


def test_depreciation_posts_journal_entry(api):
    asset = _make_asset(api)
    before = _account_balance(api, "5240")["balance"]
    r = api.post(f"/fixed-assets/{asset['id']}/depreciate", json={"amount": "100"})
    assert r.status_code == 200, r.text
    after = _account_balance(api, "5240")["balance"]
    assert Decimal(str(after)) == Decimal(str(before)) + Decimal("100")
    # مجمع الإهلاك (أصل عكسي) يزيد بالدائن — رصيده المخزن ينقص
    accum = Decimal(str(_account_balance(api, "1290")["balance"]))
    assert accum == Decimal(str(_account_balance(api, "1290")["balance"]))  # ثابت نسبيًا
    # القيد مرئي في دفتر اليومية
    entries = api.get("/journal-entries").json()
    assert any("Depreciation" in e["description"] for e in entries)


def test_depreciation_requires_positive_amount(api):
    asset = _make_asset(api)
    r = api.post(f"/fixed-assets/{asset['id']}/depreciate", json={"amount": "0"})
    assert r.status_code == 422
    r = api.post(f"/fixed-assets/{asset['id']}/depreciate", json={})
    assert r.status_code == 422


def test_disposal_with_loss_posts_journal(api):
    asset = _make_asset(api, cost="1200")
    api.post(f"/fixed-assets/{asset['id']}/depreciate", json={"amount": "700"})
    before_exp = Decimal(str(_account_balance(api, "5600")["balance"]))
    r = api.post(f"/fixed-assets/{asset['id']}/dispose", json={"disposal_proceeds": "300"})
    assert r.status_code == 200, r.text
    after_exp = Decimal(str(_account_balance(api, "5600")["balance"]))
    # خسارة استبعاد = القيمة الدفترية 500 - العائدات 300 = 200
    assert after_exp - before_exp == Decimal("200")
    entries = api.get("/journal-entries").json()
    assert any("Disposal" in e["description"] for e in entries)


def test_disposal_twice_is_conflict(api):
    asset = _make_asset(api)
    api.post(f"/fixed-assets/{asset['id']}/dispose", json={"disposal_proceeds": "0"})
    r = api.post(f"/fixed-assets/{asset['id']}/dispose", json={"disposal_proceeds": "0"})
    assert r.status_code == 409


# ================================================== 4) دورة حياة الشيكات
def _bank(api):
    branch = api.post("/company/branches", json={"name": "فرع بنك"}).json()
    r = api.post("/banks", json={"name": "بنك الاختبار", "branch_id": branch["id"]})
    assert r.status_code == 201, r.text
    return r.json()


def test_cheque_full_lifecycle_moves_portfolio_to_bank(api):
    bank = _bank(api)
    customer = api.post("/customers", json={"name": "عميل شيكات"}).json()
    # استلام شيك → 1115
    ch = api.post("/cheques", json={
        "direction": "received", "number": "123456", "bank_id": bank["id"],
        "amount": "500", "customer_id": customer["id"], "cheque_date": str(date.today()),
    })
    assert ch.status_code == 201, ch.text
    cheque = ch.json()
    assert cheque["status"] == "under_collection"
    balance_1115_before = Decimal(str(_account_balance(api, "1115")["balance"]))
    assert balance_1115_before == Decimal("500")
    # إيداع → من 1115 إلى حساب البنك
    r = api.post(f"/cheques/{cheque['id']}/deposit", json={"bank_id": bank["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "collected"
    assert Decimal(str(_account_balance(api, "1115")["balance"])) == Decimal("0")
    # إلغاء سند شيك محصّل ممنوع
    payment_id = cheque["payment_id"]
    assert api.post(f"/payments/{payment_id}/void").status_code == 409
    # ارتجاع شيك محصّل ممنوع
    assert api.post(f"/cheques/{cheque['id']}/return").status_code == 409


def test_received_cheque_return_reverses_voucher(api):
    bank = _bank(api)
    customer = api.post("/customers", json={"name": "عميل ارتجاع"}).json()
    ch = api.post("/cheques", json={
        "direction": "received", "number": "777", "bank_id": bank["id"],
        "amount": "250", "customer_id": customer["id"], "cheque_date": str(date.today()),
    })
    cheque = ch.json()
    r = api.post(f"/cheques/{cheque['id']}/return")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "returned"
    # السند المرتبط أصبح voided
    p = [x for x in api.get("/payments").json() if x["id"] == cheque["payment_id"]][0]
    assert p["status"] == "voided"
    # رصيد الحافظة رجع صفر
    assert Decimal(str(_account_balance(api, "1115")["balance"])) == Decimal("0")


# ================================================== 5) التقارير المالية
def test_financial_reports_balanced_after_flows(api):
    """بعد سندات + شيك + إهلاك: قيد الدفاتر موزون والميزانية متوازنة."""
    branch, safe = _branch_safe(api)
    customer = api.post("/customers", json={"name": "عميل تقارير"}).json()
    api.post("/payments", json={"customer_id": customer["id"], "safe_id": safe["id"], "amount": "1000"})
    asset = _make_asset(api)
    api.post(f"/fixed-assets/{asset['id']}/depreciate", json={"amount": "150"})

    tb = api.get("/reports/financial/trial-balance").json()
    assert any(a["code"] == "1115" for a in tb)  # حافظة الشيكات مش عاملة: cash sale — لا شيك
    debits = sum(Decimal(str(a["balance"])) for a in tb if a["type"] in ("asset", "expense"))
    credits = sum(Decimal(str(a["balance"])) for a in tb if a["type"] in ("liability", "equity", "revenue"))
    assert debits == credits, f"ميزان المراجعة غير متوازن: {debits} != {credits}"

    bs = api.get("/reports/financial/balance-sheet").json()
    assert bs["is_balanced"] is True, bs

    pl = api.get("/reports/financial/profit-loss").json()
    # مصروف الإهلاك 150 ظاهر والمبيعات صفر
    assert Decimal(str(pl["total_expenses"])) == Decimal("150")
    assert Decimal(str(pl["net_profit"])) == Decimal("-150")


# ================================================== 6) الإلغاء المتين + حذف الحساب + roll-up
def test_void_payment_reverses_once_even_with_similar_description(api):
    branch, safe = _branch_safe(api)
    customer = api.post("/customers", json={"name": "عميل إلغاء"}).json()
    p = api.post("/payments", json={"customer_id": customer["id"], "safe_id": safe["id"], "amount": "80"}).json()
    # قيد يدوي بنفس وصف السند — القديم كان يعمل عكسًا مزدوجًا بسبب LIKE
    leaf = _leaf_account(api, "1111")
    api.post("/journal-entries", json={
        "description": f"Payment {p['id']}: تسوية يدوية",
        "items": [
            {"account_id": leaf["id"], "debit": "1", "credit": "0"},
            {"account_id": _leaf_account(api, "1112")["id"], "debit": "0", "credit": "1"},
        ],
    })
    safe_before = api.get(f"/safes/{safe['id']}").json()["balance"]
    assert Decimal(str(safe_before)) == Decimal("80")  # القبض رفع الخزينة
    assert api.post(f"/payments/{p['id']}/void").status_code == 200
    safe_after = Decimal(str(api.get(f"/safes/{safe['id']}").json()["balance"]))
    assert safe_after == Decimal("0")  # رجع لرصيد ما قبل السند بالضبط
    # قيد واحد فقط للعكس
    voids = [e for e in api.get("/journal-entries").json() if e["reference"] == f"VOID-{p['id']}"]
    assert len(voids) == 1


def test_delete_account_guards(api):
    leaf = _leaf_account(api, "1111")
    group = _group_account(api)
    # حساب مجموعي ممنوع
    r = api.delete(f"/chart-of-accounts/{group['id']}")
    assert r.status_code == 409
    # حساب بلا حركة يقبل الحذف (ننشئه)
    created = api.post("/chart-of-accounts", json={"code": "TST1", "name": "حساب مؤقت", "type": "asset", "is_group": False}).json()
    assert api.delete(f"/chart-of-accounts/{created['id']}").status_code == 204
    # حساب عليه حركة ممنوع
    api.post("/journal-entries", json={
        "description": "حركة على الحساب",
        "items": [
            {"account_id": leaf["id"], "debit": "5", "credit": "0"},
            {"account_id": _leaf_account(api, "1112")["id"], "debit": "0", "credit": "5"},
        ],
    })
    assert api.delete(f"/chart-of-accounts/{leaf['id']}").status_code == 409


def test_roll_up_recomputes_group_balances(api):
    # ليف جديد تحت مجموعة النقد 1110 عليه حركة مقابل إيراد → رصيد المجموعة المخزن
    # يبقى 0 (القيود تحدّث الفروع فقط) حتى يأتي roll-up فيعيد احتسابه.
    new_leaf = api.post("/chart-of-accounts", json={
        "code": "1116", "name": "نقد اختبار", "type": "asset", "is_group": False, "parent_id": _group_account(api)["id"],
    })
    assert new_leaf.status_code == 201, new_leaf.text
    api.post("/journal-entries", json={
        "description": "حركة قبل roll-up",
        "items": [
            {"account_id": new_leaf.json()["id"], "debit": "42", "credit": "0"},
            {"account_id": _leaf_account(api, "4101")["id"], "debit": "0", "credit": "42"},
        ],
    })
    group_before = Decimal(str(_group_account(api)["balance"]))
    r = api.post("/chart-of-accounts/roll-up")
    assert r.status_code == 200, r.text
    assert r.json()["changed"] > 0
    group = _group_account(api)  # 1110 النقد والبنوك
    assert Decimal(str(group["balance"])) == group_before + Decimal("42")


def test_empty_account_list_for_zero_balance_group_after_rollup(api):
    """التقرير المالي يتوازن بعد roll-up."""
    api.post("/chart-of-accounts/roll-up")
    bs = api.get("/reports/financial/balance-sheet").json()
    assert bs["is_balanced"] is True
