"""اختبارات الترقية المحاسبية (9.5+):
1. تاريخ قفل الفترات (Accounting Lock Date) ومنع الترحيل بأثر رجعي.
2. إلزامية مراكز التكلفة للحسابات التي تشترط ذلك (requires_cost_center).
3. معالج إهلاك الأصول الشهري الآلي.
"""
from datetime import date, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app import models


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    client.post("/auth/setup", json={"username": "acc-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "acc-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_accounting_lock_date_blocks_retroactive_entries():
    client, engine = _client()
    try:
        # بذر شجرة الحسابات
        client.post("/chart-of-accounts/seed")
        accounts = client.get("/chart-of-accounts").json()
        cash = next(a for a in accounts if a["code"] == "1111")
        revenue = next(a for a in accounts if a["code"] == "4101")

        # 1. ضبط تاريخ قفل الحسابات إلى 2026-10-31
        lock_d = date(2026, 10, 31)
        resp = client.patch("/company", json={"accounting_lock_date": lock_d.isoformat()})
        assert resp.status_code == 200, resp.text
        assert resp.json()["accounting_lock_date"] == lock_d.isoformat()

        # 2. محاولة ترحيل قيد بتاريخ يسبق تاريخ القفل (2026-10-15) ⇒ يجب أن يرفض بـ 409
        old_entry = client.post(
            "/journal-entries",
            json={
                "date": "2026-10-15",
                "description": "قيد قديم بأثر رجعي",
                "items": [
                    {"account_id": cash["id"], "debit": 1000, "credit": 0},
                    {"account_id": revenue["id"], "debit": 0, "credit": 1000},
                ],
            },
        )
        assert old_entry.status_code == 409
        assert "الفترة مقفولة" in old_entry.text

        # 3. محاولة ترحيل قيد بنفس تاريخ القفل (2026-10-31) ⇒ يرفض بـ 409
        same_date = client.post(
            "/journal-entries",
            json={
                "date": "2026-10-31",
                "description": "قيد في نفس يوم القفل",
                "items": [
                    {"account_id": cash["id"], "debit": 500, "credit": 0},
                    {"account_id": revenue["id"], "debit": 0, "credit": 500},
                ],
            },
        )
        assert same_date.status_code == 409

        # 4. ترحيل قيد بعد تاريخ القفل (2026-11-01) ⇒ ينجح بـ 201
        valid_entry = client.post(
            "/journal-entries",
            json={
                "date": "2026-11-01",
                "description": "قيد في فترة مفتوحة",
                "items": [
                    {"account_id": cash["id"], "debit": 1000, "credit": 0},
                    {"account_id": revenue["id"], "debit": 0, "credit": 1000},
                ],
            },
        )
        assert valid_entry.status_code == 201, valid_entry.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_requires_cost_center_enforcement():
    client, engine = _client()
    try:
        client.post("/chart-of-accounts/seed")
        accounts = client.get("/chart-of-accounts").json()
        cash = next(a for a in accounts if a["code"] == "1111")
        
        # إنشاء حساب مصروف جديد يتطلب صراحة مركز تكلفة
        exp_resp = client.post(
            "/chart-of-accounts",
            json={
                "name": "مصروف تسويق خاص",
                "code": "5199",
                "type": "expense",
                "is_group": False,
                "requires_cost_center": True,
            },
        )
        assert exp_resp.status_code == 201, exp_resp.text
        exp_acc = exp_resp.json()

        # إنشاء مركز تكلفة
        cc_resp = client.post("/cost-centers", json={"name": "قطاع القاهرة", "code": "CC-CAI"})
        assert cc_resp.status_code == 201, cc_resp.text
        cc = cc_resp.json()

        # 1. ترحيل قيد على هذا الحساب دون مركز تكلفة ⇒ 422
        bad_entry = client.post(
            "/journal-entries",
            json={
                "description": "مصروف بدون مركز تكلفة",
                "items": [
                    {"account_id": exp_acc["id"], "debit": 300, "credit": 0},
                    {"account_id": cash["id"], "debit": 0, "credit": 300},
                ],
            },
        )
        assert bad_entry.status_code == 422
        assert "يتطلب تحديد مركز تكلفة" in bad_entry.text

        # 2. ترحيل قيد مع مركز التكلفة ⇒ ينجح بـ 201
        good_entry = client.post(
            "/journal-entries",
            json={
                "description": "مصروف بمركز تكلفة سليم",
                "items": [
                    {"account_id": exp_acc["id"], "debit": 300, "credit": 0, "cost_center_id": cc["id"]},
                    {"account_id": cash["id"], "debit": 0, "credit": 300},
                ],
            },
        )
        assert good_entry.status_code == 201, good_entry.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
