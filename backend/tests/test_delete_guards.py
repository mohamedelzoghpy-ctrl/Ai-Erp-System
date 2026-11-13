"""اختبارات حواجز الحذف: أصل ثابت عليه قيود لا يُحذف، وخزينة/بنك عليه حركة
(سندات/شيكات/قيود) لا يُحذف — والنظيف منها يُحذف عادي."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


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
    client.post("/auth/setup", json={"username": "guard-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "guard-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_fixed_asset_with_ledger_cannot_be_deleted():
    client, engine = _client()
    try:
        # أصل يُرسمل (ينشئ قيد FA-C)
        asset = client.post("/fixed-assets", json={
            "name": "سيارة", "code": "FA-CAR", "asset_type": "مركبات",
            "purchase_date": "2026-01-01", "cost": "500000",
            "current_book_value": "500000", "depreciation_method": "straight_line",
            "useful_life_years": 5,
        })
        assert asset.status_code == 201, asset.text
        asset_id = asset.json()["id"]

        # عليه قيود ⇒ الحذف ممنوع، والتصريف هو المسار
        blocked = client.delete(f"/fixed-assets/{asset_id}")
        assert blocked.status_code == 409, blocked.text
        assert "قيود" in blocked.json()["detail"]

        # أصل نظيف بلا قيود يُحذف عادي — ننشئه ثم نحذف قيد الرسملة؟ لا: أصل بلا
        # رسملة لا يمكن عبر هذا المسار، لذا نتحقق فقط أن الحاجز يقف أمام القيود
        # وأن الحذف يعمل حين لا توجد مراجع (نشئ أصلًا ونمسك قيد الرسملة عبر تعطيل
        # الترحيل غير ممكن — يكفي أن الحاجز نفسه مُختبَر أعلاه).
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_safe_and_bank_with_activity_cannot_be_deleted():
    client, engine = _client()
    try:
        branch = client.post("/company/branches", json={"name": "فرع الحواجز"}).json()
        branch_id = branch["id"]
        safe = client.post("/safes", json={"name": "خزينة الفرع", "opening_balance": "0", "branch_id": branch_id}).json()
        bank = client.post("/banks", json={"name": "بنك النيل", "opening_balance": "0", "branch_id": branch_id}).json()

        # خزينة/بنك نظيفان: يُحذفان عادي
        clean_safe = client.post("/safes", json={"name": "خزينة نظيفة", "opening_balance": "0", "branch_id": branch_id}).json()
        clean_bank = client.post("/banks", json={"name": "بنك نظيف", "opening_balance": "0", "branch_id": branch_id}).json()
        assert client.delete(f"/safes/{clean_safe['id']}").status_code == 204
        assert client.delete(f"/banks/{clean_bank['id']}").status_code == 204

        # سند قبض نقدي على الخزينة ⇒ حذف ممنوع
        customer = client.post("/customers", json={"name": "عميل حواجز"}).json()
        pay = client.post("/payments", json={
            "customer_id": customer["id"], "amount": "300", "method": "cash", "safe_id": safe["id"],
        })
        assert pay.status_code == 201, pay.text

        blocked = client.delete(f"/safes/{safe['id']}")
        assert blocked.status_code == 409, blocked.text
        assert "سندات" in blocked.json()["detail"]

        # شيك مسحوب على البنك ⇒ حذف ممنوع (نشئه عبر سند شيك صادر لعميل/مورد)
        supplier = client.post("/suppliers", json={"name": "مورد حواجز"}).json()
        cheque_pay = client.post("/payments", json={
            "supplier_id": supplier["id"], "amount": "150", "method": "cheque", "bank_id": bank["id"],
        })
        assert cheque_pay.status_code == 201, cheque_pay.text

        blocked_bank = client.delete(f"/banks/{bank['id']}")
        assert blocked_bank.status_code == 409, blocked_bank.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
