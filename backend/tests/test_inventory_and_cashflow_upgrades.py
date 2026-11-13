"""ترقيات المخازن والتقارير: جرد بكميات عشرية، إعدام لوط مع أثر مخزني،
وتعديل صلاحية لوط — وقائمة التدفقات النقدية بالطريقة المباشرة."""
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from tests.test_warehouse_stock import make_product, make_warehouses


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
    client.post("/auth/setup", json={"username": "upg-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "upg-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


# ---------------------------------------------------------------- الجرد العشري

def test_stocktake_accepts_fractional_counts():
    client, engine = _client()
    try:
        w1, _ = make_warehouses(client)
        product = make_product(client, "FR1", 10, w1["id"])  # كيلو واحد ونص فعلياً

        st = client.post("/stocktakes", json={"warehouse_id": w1["id"], "notes": "جرد عشري"})
        assert st.status_code == 201, st.text
        sid = st.json()["id"]

        saved = client.put(f"/stocktakes/{sid}/counts", json={"counts": [
            {"product_id": product["id"], "counted_qty": 1.5},
        ]})
        assert saved.status_code == 200, saved.text
        line = [l for l in saved.json()["lines"] if l["product_id"] == product["id"]][0]
        assert line["counted_qty"] == 1.5

        submitted = client.post(f"/stocktakes/{sid}/submit")
        assert submitted.status_code == 200, submitted.text
        applied = client.post(f"/stocktakes/{sid}/apply")
        assert applied.status_code == 200, applied.text
        # الفرق -8.5 نُرحّل للرصيد فعلاً
        refreshed = client.get(f"/products/{product['id']}").json()
        assert float(refreshed["quantity"]) == 1.5
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


# ---------------------------------------------------------------- إعدام اللوطات وتعديل صلاحيتها

def test_lot_write_off_moves_stock_and_reduces_lot():
    client, engine = _client()
    try:
        w1, _ = make_warehouses(client)
        product = make_product(client, "WO1", 0, w1["id"])

        lot = client.post("/lots", json={
            "product_id": product["id"], "warehouse_id": w1["id"],
            "lot_code": "WO-01", "qty": 20,
        })
        assert lot.status_code == 201, lot.text
        lot_id = lot.json()["id"]

        # إعدام 6 وحدات (تلف)
        wo = client.post(f"/lots/{lot_id}/write-off", json={"qty": 6, "reason": "تلف بالتخزين"})
        assert wo.status_code == 200, wo.text
        assert float(wo.json()["qty_remaining"]) == 14.0
        assert float(client.get(f"/products/{product['id']}").json()["quantity"]) == 14.0

        # الحركة مسجلة في دفتر الحركة
        movements = client.get(f"/products/{product['id']}/movements").json()
        wo_moves = [m for m in movements if m.get("reason") == "lot-writeoff"]
        assert len(wo_moves) == 1 and float(wo_moves[0]["change"]) == -6.0

        # لا إعدام أكبر من رصيد اللوط
        over = client.post(f"/lots/{lot_id}/write-off", json={"qty": 99, "reason": "خطأ"})
        assert over.status_code == 409

        # تعديل صلاحية اللوط
        patched = client.patch(f"/lots/{lot_id}", json={"expiry_date": "2027-06-30"})
        assert patched.status_code == 200, patched.text
        assert patched.json()["expiry_date"] == "2027-06-30"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


# ---------------------------------------------------------------- قائمة التدفقات النقدية

def test_cash_flow_statement_direct_method():
    client, engine = _client()
    try:
        # زرع شجرة الحسابات (تُزرع lazily عند أول ترحيل)
        assert client.post("/chart-of-accounts/seed").status_code in (200, 201), client.post("/chart-of-accounts/seed").text
        coa = client.get("/chart-of-accounts").json()
        by_code = {a["code"]: a["id"] for a in coa if isinstance(a, dict) and "code" in a}
        cash, capital = by_code["1111"], by_code["3100"]
        revenue, equipment = by_code["4101"], by_code["1210"]

        def je(items, date=None):
            payload = {"description": "اختبار تدفقات", "items": items}
            if date:
                payload["date"] = date
            r = client.post("/journal-entries", json=payload)
            assert r.status_code == 201, r.text

        # الشهر الماضي: إيداع رأس مال 1000 (تمويلي)
        je([
            {"account_id": cash, "debit": "1000", "credit": "0"},
            {"account_id": capital, "debit": "0", "credit": "1000"},
        ], date="2026-10-05")

        # الفترة الحالية: بيع نقدي 400 (تشغيلي) + شراء معدات 150 (استثماري)
        # + تحويل خزينة→بنك 200 (لا أثر على الإجمالي)
        je([
            {"account_id": cash, "debit": "400", "credit": "0"},
            {"account_id": revenue, "debit": "0", "credit": "400"},
        ], date="2026-11-03")
        je([
            {"account_id": equipment, "debit": "150", "credit": "0"},
            {"account_id": cash, "debit": "0", "credit": "150"},
        ], date="2026-11-04")
        by_code2 = {a["code"]: a["id"] for a in client.get("/chart-of-accounts").json() if isinstance(a, dict) and "code" in a}
        bank = by_code2["1112"]
        je([
            {"account_id": bank, "debit": "200", "credit": "0"},
            {"account_id": cash, "debit": "0", "credit": "200"},
        ], date="2026-11-05")

        r = client.get("/reports/financial/cash-flow?date_from=2026-11-01&date_to=2026-11-30")
        assert r.status_code == 200, r.text
        cf = r.json()

        assert cf["opening"] == "1000.00"
        # التشغيلي: بيع +400 · الاستثماري: معدات -150 · التمويلي: لا شيء بالفترة
        assert cf["operating_total"] == "400.00"
        assert cf["investing_total"] == "-150.00"
        assert cf["financing_total"] == "0.00"
        assert cf["net_change"] == "250.00"
        assert cf["closing"] == "1250.00"
        op_codes = {row["code"] for row in cf["operating"]}
        assert "4101" in op_codes
        inv_codes = {row["code"] for row in cf["investing"]}
        assert "1210" in inv_codes

        # XLSX يعمل
        assert client.get("/reports/financial/cash-flow/xlsx?date_from=2026-11-01&date_to=2026-11-30").status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
