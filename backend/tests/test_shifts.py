"""اختبارات ورديات الكاشير: دورة الفتح/الإغلاق، معادلة النقد المتوقع
(افتتاحي + مقبوضات نقدية − مرتجعات نقدية)، تجميد الأرقام عند الإغلاق،
وحجب الرؤية بين الكاشيرين مع سماح للمدير."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from tests.test_warehouse_stock import give_section, make_product, make_warehouses

SHIFT_CODES = ["sales.shift.view", "sales.shift.open", "sales.shift.close", "sales.shift.pdf"]


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
    client.post("/auth/setup", json={"username": "shift-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "shift-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def _make_cashier(client, username):
    branches = client.get("/company/branches").json()
    resp = client.post(
        "/auth/users",
        json={
            "username": username,
            "password": "cashier-password-123",
            "role": "staff",
            "full_name": username,
            "branch_ids": [branches[0]["id"]],
        },
    )
    assert resp.status_code == 201, resp.text
    give_section(client, resp.json()["id"], SHIFT_CODES)
    login = client.post(
        "/auth/login", data={"username": username, "password": "cashier-password-123"}
    )
    assert login.status_code == 200, login.text
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    return c


def test_shift_lifecycle_and_expected_cash_math():
    client, engine = _client()
    try:
        # فتح برصيد افتتاحي
        opened = client.post("/shifts/open", json={"opening_cash": "500"})
        assert opened.status_code == 201, opened.text
        assert opened.json()["status"] == "open"
        assert opened.json()["expected_cash"] == "500.00"

        # منع وردية ثانية مفتوحة لنفس المستخدم
        assert client.post("/shifts/open", json={"opening_cash": "0"}).status_code == 409

        # مقبوض نقدية داخل النافذة يرفع المتوقع
        customer = client.post("/customers", json={"name": "عميل وردية"}).json()
        assert client.post(
            "/payments", json={"customer_id": customer["id"], "amount": "200", "method": "cash"}
        ).status_code == 201
        current = client.get("/shifts/current").json()
        assert current["cash_in"] == "200.00"
        assert current["expected_cash"] == "700.00"

        # إقفال بعدّ فعلي أقل من المتوقع ⇒ فرق سالب، وتجميد الأرقام
        closed = client.post(f"/shifts/{current['id']}/close", json={"counted_cash": "650"})
        assert closed.status_code == 200, closed.text
        body = closed.json()
        assert body["status"] == "closed"
        assert body["expected_cash"] == "700.00"
        assert body["counted_cash"] == "650.00"
        assert body["difference"] == "-50.00"

        # لا إقفال مرتين
        assert client.post(f"/shifts/{current['id']}/close", json={"counted_cash": "650"}).status_code == 409

        # بعد الإقفال: لا وردية جارية، والأرقام المجمدة ظاهرة في القائمة
        assert client.get("/shifts/current").json() is None
        listed = client.get("/shifts?status_filter=closed").json()
        assert len(listed) == 1 and listed[0]["difference"] == "-50.00"

        # وردية جديدة بعد الإقفال مقبولة
        assert client.post("/shifts/open", json={"opening_cash": "10"}).status_code == 201
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_cash_refund_lowers_expected_cash():
    client, engine = _client()
    try:
        w1, _ = make_warehouses(client)
        product = make_product(client, "SH1", 10, w1["id"])
        assert client.post("/shifts/open", json={"opening_cash": "100"}).status_code == 201

        # مرتجع بيع نقدي داخل النافذة ⇒ المبلغ مخرج من الدرج
        ret = client.post(
            "/sales-returns",
            json={
                "warehouse_id": w1["id"],
                "items": [{"product_id": product["id"], "quantity": 2, "unit_price": "25"}],
                "refund_amount": "50",
                "method": "cash",
            },
        )
        assert ret.status_code == 201, ret.text
        current = client.get("/shifts/current").json()
        assert current["cash_refunds_out"] == "50.00"
        assert current["expected_cash"] == "50.00"  # 100 − 50

        closed = client.post(f"/shifts/{current['id']}/close", json={"counted_cash": "50"})
        assert closed.status_code == 200, closed.text
        assert closed.json()["difference"] == "0.00"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_shift_visibility_and_manager_override():
    client, engine = _client()
    try:
        cashier_a = _make_cashier(client, "cashier-a")
        cashier_b = _make_cashier(client, "cashier-b")

        opened = cashier_a.post("/shifts/open", json={"opening_cash": "75"})
        assert opened.status_code == 201, opened.text
        shift_id = opened.json()["id"]

        # الكاشير الآخر: لا يرى الوردية في قائمته
        assert cashier_b.get("/shifts").json() == []
        assert cashier_b.get("/shifts/current").json() is None
        # ولا يستطيع إقفالها ولا جلب وصلها
        assert cashier_b.post(f"/shifts/{shift_id}/close", json={"counted_cash": "75"}).status_code == 403
        assert cashier_b.get(f"/shifts/{shift_id}/pdf").status_code == 404

        # المدير يراها ويقفلها (تجاوز إداري)
        assert len(client.get("/shifts?status_filter=open").json()) == 1
        closed = client.post(f"/shifts/{shift_id}/close", json={"counted_cash": "75", "notes": "إقفال إداري"})
        assert closed.status_code == 200, closed.text
        assert closed.json()["difference"] == "0.00"
        assert client.get(f"/shifts/{shift_id}/pdf").status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
