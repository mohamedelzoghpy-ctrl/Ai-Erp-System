"""إصلاحات التدقيق الحرجة (2026-11-14): ذرية البذرة + سلامة الدفاتر على مستوى القاعدة."""

import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.accounting import seed_default_coa
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


# ================================================== إصلاح 1: ذرية البذرة

def test_seed_coa_is_flush_only_rolls_back_with_caller(api, monkeypatch):
    """البذرة بلا commit داخلي: rollback من المستدعي يمسحها — لا نصف بذر مثبّت."""
    c = api
    ok(c.post("/chart-of-accounts/seed", json={}), 201)
    assert ok(c.get("/chart-of-accounts"))  # البذرة عبر الـendpoint تُثبَّت (الـendpoint يملك الـcommit)

    # استدعاء مباشر داخل جلسة اختبار: بدون commit من المستدعي لا شيء يثبت
    from app.database import SessionLocal  # noqa: F401  (الاختبار يستخدم نفس override)
    db = None
    for override in app.dependency_overrides.values():
        pass
    factory = sessionmaker(bind=create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))
    Base.metadata.create_all(bind=factory.kw["bind"])
    db = factory()
    try:
        created = seed_default_coa(db, company_id=1)
        assert created > 0
        assert db.query(models.ChartAccount).count() > 0  # مرئية قبل الإثبات (flush)
        db.rollback()
        assert db.query(models.ChartAccount).count() == 0  # ← الدليل: بلا commit داخلي
    finally:
        db.close()


# ================================================== إصلاح 3: سلامة الدفاتر بالقاعدة

def test_journal_item_check_rejects_both_sides(api):
    """CHECK على مستوى القاعدة: بند بمدين ودائن معًا مرفوض (SQLite يفرض الـCHECK من الميتاداتا)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        db.add(models.Company(id=1, name="شركة", code="t1"))
        db.add(models.User(id=1, username="u", hashed_password="x"))
        db.add(models.ChartAccount(id=1, company_id=1, code="9999", name="اختبار", type="asset", is_group=False))
        entry = models.JournalEntry(id=1, company_id=1, date=__import__("datetime").date(2026, 1, 1), description="اختبار")
        db.add(entry)
        db.add(models.JournalItem(company_id=1, entry_id=1, account_id=1, debit=Decimal("100"), credit=Decimal("100")))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_create_entry_rejects_both_sides_item(api):
    """حارس create_entry: بند بطرفين مرفوض برسالة واضحة قبل الوصول للقاعدة."""
    c = api
    cash, capital = acc_id(c, "1111"), acc_id(c, "3100")
    r = c.post("/journal-entries", json={
        "date": "2026-01-10",
        "description": "بند بطرفين",
        "items": [
            {"account_id": cash, "debit": 500, "credit": 200},
            {"account_id": capital, "debit": 0, "credit": 300},
        ],
    })
    assert r.status_code in (400, 422), r.text
    assert "split it into two items" in r.text, r.text


def test_je_flow_still_posts_after_guards(api):
    """القيد السليم يمر طبيعيًا بعد الحارسين (لا كسر رجعي)."""
    c = api
    cash, capital = acc_id(c, "1111"), acc_id(c, "3100")
    je = ok(c.post("/journal-entries", json={
        "date": "2026-01-10",
        "description": "قيد سليم",
        "items": [
            {"account_id": cash, "debit": 500, "credit": 0},
            {"account_id": capital, "debit": 0, "credit": 500},
        ],
    }), 201)
    assert je["status"] == "posted"
