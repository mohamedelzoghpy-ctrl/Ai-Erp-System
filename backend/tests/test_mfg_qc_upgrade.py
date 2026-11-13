"""اختبارات ترقية التصنيع وضبط الجودة:
1. محاكي MRP لاحتياجات الخامات (simulate_bom_mrp) واستكشاف النواقص وحساب تكلفة العجز.
2. بوابة الجودة والإفراج عن الدفعات (QC Release / Reject) عبر مسار الجودة الموحد.
"""
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
    client.post("/auth/setup", json={"username": "mfg-admin", "password": "strong-password-123"})
    token = client.post(
        "/auth/login", data={"username": "mfg-admin", "password": "strong-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, engine


def test_bom_mrp_simulation_detects_shortages():
    client, engine = _client()
    try:
        w1, w2 = make_warehouses(client)
        # مكوّن 1: متوفر منه 10 وحدات في مخزن الخامات w1
        comp1 = make_product(client, "RAW-1", 10, w1["id"], cost_price="20.00")
        # مكوّن 2: متوفر منه 0 وحدات
        comp2 = make_product(client, "RAW-2", 0, w1["id"], cost_price="50.00")
        # منتج نهائي
        finished = make_product(client, "FIN-1", 0, w2["id"])

        # إنشاء قائمة مواد BOM لإنتاج 1 وحدة تتطلب: 2 من RAW-1 و 1 من RAW-2
        bom = client.post(
            "/boms",
            json={
                "product_id": finished["id"],
                "version": "v1",
                "output_qty": 1,
                "items": [
                    {"component_id": comp1["id"], "qty_per_output": 2, "scrap_pct": 0},
                    {"component_id": comp2["id"], "qty_per_output": 1, "scrap_pct": 10},  # 1.1 وحدة
                ],
            },
        ).json()

        # تشغيل محاكي MRP لإنتاج 10 وحدات من المنتج النهائي
        # المطلوب: RAW-1 = 20 وحدة (المتوفر 10 ⇒ العجز 10 وحدات × 20 جنيه = 200 جنيه)
        # المطلوب: RAW-2 = 11 وحدة (المتوفر 0 ⇒ العجز 11 وحدة × 50 جنيه = 550 جنيه)
        sim = client.get(f"/boms/{bom['id']}/mrp-simulate?qty_planned=10&raw_warehouse_id={w1['id']}").json()
        assert sim["can_produce_immediately"] is False
        assert sim["total_shortage_cost"] == 750.0

        item1 = next(i for i in sim["items"] if i["component_id"] == comp1["id"])
        assert item1["required_qty"] == 20.0
        assert item1["available_qty"] == 10.0
        assert item1["shortage_qty"] == 10.0
        assert item1["estimated_purchase_cost"] == 200.0

        item2 = next(i for i in sim["items"] if i["component_id"] == comp2["id"])
        assert item2["required_qty"] == 11.0
        assert item2["available_qty"] == 0.0
        assert item2["shortage_qty"] == 11.0
        assert item2["estimated_purchase_cost"] == 550.0
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_bom_mrp_simulation_default_total_availability():
    """انحدار (2026-11-14): المسار الافتراضي بلا raw_warehouse_id كان يرفع 500 —
    نداء stock.total_available لم يكن معرفًا أصلًا في stock.py، والواجهة تستخدم هذا
    المسار افتراضيًا (زر ⚡ محاكي MRP في قوائم المواد)."""
    client, engine = _client()
    try:
        w1, w2 = make_warehouses(client)
        comp1 = make_product(client, "RAW-T1", 10, w1["id"], cost_price="20.00")
        comp2 = make_product(client, "RAW-T2", 4, w2["id"], cost_price="50.00")  # مخزن مختلف
        finished = make_product(client, "FIN-T1", 0, w2["id"])
        bom = client.post(
            "/boms",
            json={
                "product_id": finished["id"],
                "version": "v1",
                "output_qty": 1,
                "items": [
                    {"component_id": comp1["id"], "qty_per_output": 2, "scrap_pct": 0},
                    {"component_id": comp2["id"], "qty_per_output": 1, "scrap_pct": 0},
                ],
            },
        ).json()
        # بلا raw_warehouse_id: المتاح = الإجمالي عبر كل المخازن (نفس دلالة mrp_suggestions)
        resp = client.get(f"/boms/{bom['id']}/mrp-simulate?qty_planned=10")
        assert resp.status_code == 200, resp.text
        sim = resp.json()
        item1 = next(i for i in sim["items"] if i["component_id"] == comp1["id"])
        item2 = next(i for i in sim["items"] if i["component_id"] == comp2["id"])
        assert item1["available_qty"] == 10.0 and item1["shortage_qty"] == 10.0   # مطلوب 20
        assert item2["available_qty"] == 4.0 and item2["shortage_qty"] == 6.0     # مطلوب 10
        assert sim["can_produce_immediately"] is False
        assert sim["total_shortage_cost"] == 500.0  # 10×20 + 6×50
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_qc_release_and_reject_flow():
    client, engine = _client()
    try:
        w1, w2 = make_warehouses(client)
        comp = make_product(client, "RM-1", 50, w1["id"], cost="10.00")
        finished = make_product(client, "FP-1", 0, w2["id"])

        bom = client.post(
            "/boms",
            json={
                "product_id": finished["id"],
                "version": "v1",
                "items": [{"component_id": comp["id"], "qty_per_output": 2}],
            },
        ).json()

        order = client.post(
            "/production-orders",
            json={
                "product_id": finished["id"],
                "bom_id": bom["id"],
                "qty_planned": 10,
                "raw_warehouse_id": w1["id"],
                "output_warehouse_id": w2["id"],
            },
        ).json()

        # صرف الخامات
        client.post(f"/production-orders/{order['id']}/issue")
        # إنتاج دفعة أولى من 5 وحدات
        produced = client.post(
            f"/production-orders/{order['id']}/produce",
            json={"qty": 5},
        ).json()
        batch = produced["batches"][0]
        assert batch["qc_status"] == "pending"

        # اعتماد الجودة عبر مسار الإفراج الموحد /qc/batches/{id}/release
        rel = client.post(f"/qc/batches/{batch['id']}/release?action=passed&notes=معتمدة").json()
        assert rel["batch_id"] == batch["id"]
        assert rel["qc_status"] == "passed"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
