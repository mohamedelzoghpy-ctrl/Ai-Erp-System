"""المرحلة 3 من خطة التصنيع: التصنيع لدى الغير — عهدة الخامات للمُصنّع الخارجي (إرسال/إرجاع/تقرير)."""
import pytest
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


def make_warehouse(c, name, code):
    return ok(c.post("/warehouses", json={"name": name, "code": code}), 201)


def make_product(c, name, **extra):
    body = {"sku": f"SKU-{name}", "name": name, "sale_price": "100", "cost_price": "5", "quantity": 0, **extra}
    return ok(c.post("/products", json=body), 201)


def setup_subcontract_order(c, raw_qty=50):
    """أمر تصنيع خارجي مُصروف: مُصنّع + خامة + BOM + أمر + صرف. يعيد (الأمر، الخامة، التام، المُصنّع، المخزن)."""
    w = make_warehouse(c, "Main", "W1")
    supp = ok(c.post("/suppliers", json={"name": "مُصنّع خارجي"}), 201)
    raw = make_product(c, "R1", quantity=raw_qty, cost_price="10", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    ok(c.post("/boms", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": 2}],
    }), 201)
    po = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 10,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
        "subcontractor_id": supp["id"],
    }), 201)
    po = ok(c.post(f"/production-orders/{po['id']}/issue"))  # صرف 20 من الخامة
    return po, raw, fin, supp, w


# ---------------------------------------------------------------- قواعد الإرسال
def test_send_requires_subcontractor_and_issued_order(api):
    c = api
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=50, cost_price="10", warehouse_id=w["id"])
    fin = make_product(c, "F1")
    ok(c.post("/boms", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": 1}],
    }), 201)
    # أمر بلا مُصنّع → الإرسال 422
    po = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 5,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
    }), 201)
    r = c.post(f"/production-orders/{po['id']}/subcontract/send", json={
        "lines": [{"product_id": raw["id"], "qty": 5}],
    })
    assert r.status_code == 422 and "مُصنّع" in r.json()["detail"]

    # أمر بمُصنّع لكن لم يُصرف (مسودة) → 422
    po2 = ok(c.post("/production-orders", json={
        "product_id": fin["id"], "qty_planned": 5,
        "raw_warehouse_id": w["id"], "output_warehouse_id": w["id"],
        "subcontractor_id": ok(c.post("/suppliers", json={"name": "مُصنّع ٢"}), 201)["id"],
    }), 201)
    r2 = c.post(f"/production-orders/{po2['id']}/subcontract/send", json={
        "lines": [{"product_id": raw["id"], "qty": 5}],
    })
    assert r2.status_code == 422 and "صرف" in r2.json()["detail"]


def test_send_updates_custody_and_caps_at_issued(api):
    c = api
    po, raw, fin, supp, w = setup_subcontract_order(c)  # صرف 20
    # إرسال أكثر من المصروف → 422
    r = c.post(f"/production-orders/{po['id']}/subcontract/send", json={
        "lines": [{"product_id": raw["id"], "qty": 25}],
    })
    assert r.status_code == 422 and "المتاح" in r.json()["detail"]
    # إرسال 12 → عهدة 12
    sent = ok(c.post(f"/production-orders/{po['id']}/subcontract/send", json={
        "lines": [{"product_id": raw["id"], "qty": 12}], "notes": "الدفعة الأولى",
    }))
    assert len(sent) == 1 and float(sent[0]["qty_sent"]) == 12.0 and float(sent[0]["outstanding"]) == 12.0
    # إرسال 8 إضافية تتراكم على نفس السجل
    sent2 = ok(c.post(f"/production-orders/{po['id']}/subcontract/send", json={
        "lines": [{"product_id": raw["id"], "qty": 8}],
    }))
    assert float(sent2[0]["qty_sent"]) == 20.0
    # تجاوز الكلي (20 مصروف) → 422
    assert c.post(f"/production-orders/{po['id']}/subcontract/send", json={
        "lines": [{"product_id": raw["id"], "qty": 1}],
    }).status_code == 422
    # كشف عهدة الأمر
    rows = ok(c.get(f"/production-orders/{po['id']}/subcontract/custody"))
    assert len(rows) == 1 and float(rows[0]["outstanding"]) == 20.0 and rows[0]["product_name"] == "R1"


def test_return_reduces_outstanding_and_report(api):
    c = api
    po, raw, fin, supp, w = setup_subcontract_order(c)
    ok(c.post(f"/production-orders/{po['id']}/subcontract/send", json={
        "lines": [{"product_id": raw["id"], "qty": 15}],
    }))
    # تقرير العهدة: القائمة تظهر
    rep = ok(c.get("/production-orders/reports/subcontract-custody"))
    match = [r for r in rep if r["order_id"] == po["id"]]
    assert len(match) == 1 and float(match[0]["outstanding"]) == 15.0 and match[0]["subcontractor_name"] == "مُصنّع خارجي"
    # استرداد 5
    ret = ok(c.post(f"/production-orders/{po['id']}/subcontract/return", json={
        "lines": [{"product_id": raw["id"], "qty": 5}],
    }))
    assert float(ret[0]["outstanding"]) == 10.0
    # استرداد أكثر من القائم → 422
    r = c.post(f"/production-orders/{po['id']}/subcontract/return", json={
        "lines": [{"product_id": raw["id"], "qty": 11}],
    })
    assert r.status_code == 422 and "العهدة القائمة" in r.json()["detail"]
    # بلا عهدة على منتج آخر → 422
    other = make_product(c, "OTHER")
    assert c.post(f"/production-orders/{po['id']}/subcontract/return", json={
        "lines": [{"product_id": other["id"], "qty": 1}],
    }).status_code == 422
    # تقرير بعد التراجع الكامل يختفي من القائمة (outstanding_only الافتراضي)
    ok(c.post(f"/production-orders/{po['id']}/subcontract/return", json={
        "lines": [{"product_id": raw["id"], "qty": 10}],
    }))
    rep2 = ok(c.get("/production-orders/reports/subcontract-custody"))
    assert all(r["order_id"] != po["id"] for r in rep2)
    # والكل (بلا فلتر) يظهر بالقيم الصفرية
    rep3 = ok(c.get("/production-orders/reports/subcontract-custody?outstanding_only=false"))
    mine = [r for r in rep3 if r["order_id"] == po["id"]]
    assert len(mine) == 1 and float(mine[0]["qty_sent"]) == 15.0 and float(mine[0]["qty_returned"]) == 15.0


def test_full_subcontract_cycle_keeps_wip_zero(api):
    """الدورة الخارجية الكاملة: صرف ← عهدة ← أجرة خدمة التصنيع ← إنتاج ← إغلاق = WIP صفر."""
    c = api
    po, raw, fin, supp, w = setup_subcontract_order(c)  # صرف 20 × 10 = 200
    ok(c.post(f"/production-orders/{po['id']}/subcontract/send", json={
        "lines": [{"product_id": raw["id"], "qty": 20}],
    }))
    ok(c.post(f"/production-orders/{po['id']}/costs", json={"cost_type": "subcontract", "amount": "50", "description": "أجرة صباغة"}))
    po2 = ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 10}))
    assert po2["status"] == "completed"
    batches = po2["batches"]
    assert len(batches) == 1 and float(batches[0]["qty"]) == 10.0
    # تكلفة الدفعة الكلية = 200 خامات + 50 خدمة = 250 (لـ10 وحدات)
    assert float(batches[0]["cost"]) == 250.0
    # متوسط تكلفة المنتج النهائي 25
    fin_after = ok(c.get(f"/products/{fin['id']}"))
    assert float(fin_after["cost_price"]) == 25.0
    # WIP مصفّر
    data = ok(c.get("/chart-of-accounts/reconcile"))
    # التقرير يحذف الحسابات المصفّرة — غياب سطر 1130 = WIP صفر تماماً
    wip_line = next((l for l in data["lines"] if l["code"] == "1130"), None)
    assert wip_line is None or float(wip_line["stored"]) == 0.0
    # عهدة ما زالت مسجلة (تتبع فيزيائي مستقل عن المحاسبة)
    rows = ok(c.get(f"/production-orders/{po['id']}/subcontract/custody"))
    assert float(rows[0]["outstanding"]) == 20.0
