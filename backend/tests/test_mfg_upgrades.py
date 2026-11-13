"""اختبارات ترقيات التصنيع 2026-11-09: سلامة WIP، إيقاف أمر شغال، snapshot، QC بالسبب، أجور تلقائية، MRP، تتبع، بطاقة طباعة."""

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


def make_bom(c, product_id, items, output_qty=1, active=True, version="v1", operations=None):
    return ok(c.post("/boms", json={
        "product_id": product_id,
        "version": version,
        "output_qty": output_qty,
        "is_active": active,
        "items": items,
        "operations": operations or [],
    }), 201)


def make_order(c, product_id, qty, raw_wh, out_wh, **extra):
    return ok(c.post("/production-orders", json={
        "product_id": product_id,
        "qty_planned": qty,
        "raw_warehouse_id": raw_wh,
        "output_warehouse_id": out_wh,
        **extra,
    }), 201)


def stock_of(c, product_id, warehouse_id):
    for row in ok(c.get(f"/products/{product_id}/stock")):
        if row["warehouse_id"] == warehouse_id:
            return row["quantity"]
    return 0


def wip_balance(c):
    """رصيد حساب WIP 1130 كما يراه تقرير المطابقة (الحسابات المصفرية تُحذف من التقرير)."""
    data = ok(c.get("/chart-of-accounts/reconcile"))
    line = next((l for l in data["lines"] if l["code"] == "1130"), None)
    return float(line["stored"]) if line else 0.0


def setup_cycle(c, raw_cost="10", bom_qty_per=1):
    w = make_warehouse(c, "Main", "W1")
    raw = make_product(c, "R1", quantity=100, cost_price=raw_cost, warehouse_id=w["id"])
    fin = make_product(c, "F1")
    bom = make_bom(c, fin["id"], [{"component_id": raw["id"], "qty_per_output": bom_qty_per}])
    return w, raw, fin, bom


# ---------------------------------------------------------------- 1) سلامة WIP
def test_autocomplete_zeroes_wip_after_cost_between_batches(api):
    """الأمر يكتمل تلقائيًا مع آخر دفعة بعد إضافة أجور بين الدفعات → WIP يُصفَّر تمامًا."""
    c = api
    w, raw, fin, _bom = setup_cycle(c, raw_cost="10", bom_qty_per=1)
    po = make_order(c, fin["id"], 10, w["id"], w["id"])
    po = ok(c.post(f"/production-orders/{po['id']}/issue"))          # WIP = 100
    po = ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 5}))  # Cr WIP 50
    po = ok(c.post(f"/production-orders/{po['id']}/costs", json={"cost_type": "labor", "amount": "50"}))  # WIP = 150
    po = ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 5}))  # Cr WIP 75 (unit 15)
    assert po["status"] == "completed"
    # بلا الإصلاح كان WIP يعلق فيه 25 للأبد
    assert wip_balance(c) == 0.0


def test_close_after_scrap_zeroes_wip_no_negative(api):
    """الإنهاء بعد تسجيل هالك: الفروق لا تخصم الهالك مرتين → WIP يصل صفرًا لا سالبًا."""
    c = api
    w, raw, fin, _bom = setup_cycle(c, raw_cost="10", bom_qty_per=1)
    po = make_order(c, fin["id"], 5, w["id"], w["id"])
    po = ok(c.post(f"/production-orders/{po['id']}/issue"))            # WIP = 50
    po = ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 3}))  # Cr 30
    po = ok(c.post(f"/production-orders/{po['id']}/scrape", json={"qty": 1}))   # Cr 10، scrap_cost = 10
    assert float(po["scrap_cost"]) == 10.0
    po = ok(c.post(f"/production-orders/{po['id']}/close"))
    assert po["status"] == "completed"
    # الطريقة القديمة كانت ترحّل 20 → WIP سالب 10
    assert wip_balance(c) == 0.0


# ---------------------------------------------------------------- 2) إيقاف أمر شغال
def test_cancel_running_returns_materials_and_costs(api):
    c = api
    w, raw, fin, _bom = setup_cycle(c, raw_cost="10", bom_qty_per=2)
    po = make_order(c, fin["id"], 4, w["id"], w["id"])
    po = ok(c.post(f"/production-orders/{po['id']}/issue"))           # صرف 8 × 10 = 80
    assert stock_of(c, raw["id"], w["id"]) == 92
    ok(c.post(f"/production-orders/{po['id']}/costs", json={"cost_type": "labor", "amount": "20"}))

    po = ok(c.post(f"/production-orders/{po['id']}/cancel-running"))
    assert po["status"] == "cancelled"
    assert stock_of(c, raw["id"], w["id"]) == 100                      # الخامات رجعت
    assert wip_balance(c) == 0.0                                       # قيود الأجور عُكست
    assert po["costs"] == []

    # الإيقاف بعد إنتاج دفعة مرفوض
    po2 = make_order(c, fin["id"], 2, w["id"], w["id"])
    ok(c.post(f"/production-orders/{po2['id']}/issue"))
    ok(c.post(f"/production-orders/{po2['id']}/produce", json={"qty": 1}))
    assert c.post(f"/production-orders/{po2['id']}/cancel-running").status_code == 409


# ---------------------------------------------------------------- 3) فحص توفر الخامات
def test_materials_availability(api):
    c = api
    w, raw, fin, _bom = setup_cycle(c, bom_qty_per=2)
    po = make_order(c, fin["id"], 5, w["id"], w["id"])
    data = ok(c.get(f"/production-orders/{po['id']}/materials-availability"))
    assert data["all_available"] is True
    assert float(data["lines"][0]["required"]) == 10
    assert float(data["lines"][0]["available"]) == 100

    # خامة ناقصة
    scarce = make_product(c, "SCARCE", quantity=1)
    make_bom(c, fin["id"], [{"component_id": scarce["id"], "qty_per_output": "5"}], version="v2")
    po2 = make_order(c, fin["id"], 3, w["id"], w["id"])
    data2 = ok(c.get(f"/production-orders/{po2['id']}/materials-availability"))
    assert data2["missing_count"] == 1
    assert float(data2["lines"][0]["required"]) == 15
    assert float(data2["lines"][0]["available"]) == 1
    assert data2["all_available"] is False


# ---------------------------------------------------------------- 4) snapshot بنود القائمة
def test_bom_edit_does_not_change_existing_order(api):
    """تعديل قائمة المواد بعد إنشاء الأمر لا يغيّر متطلبات الأمر (snapshot)."""
    c = api
    w, raw, fin, bom = setup_cycle(c, bom_qty_per=2)
    po = make_order(c, fin["id"], 5, w["id"], w["id"])
    ok(c.patch(f"/boms/{bom['id']}", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": "4"}],
    }))
    po = ok(c.post(f"/production-orders/{po['id']}/issue"))
    assert po["consumptions"][0]["qty"] == 10  # 2 × 5 من الـ snapshot — ليس 20

    # تغيير منتج قائمة مستخدمة مرفوض
    other = make_product(c, "OTHER")
    resp = c.patch(f"/boms/{bom['id']}", json={
        "product_id": other["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": "4"}],
    })
    assert resp.status_code == 409


# ---------------------------------------------------------------- 5) فحص الجودة
def test_qc_reject_requires_reason_and_lowers_cost(api):
    c = api
    w, raw, fin, _bom = setup_cycle(c, raw_cost="5", bom_qty_per=1)
    po = make_order(c, fin["id"], 3, w["id"], w["id"])
    po = ok(c.post(f"/production-orders/{po['id']}/issue"))
    po = ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 3}))
    details = ok(c.get(f"/production-orders/{po['id']}"))
    batch = details["batches"][0]

    # الرفض بدون سبب مرفوض
    resp = c.post(f"/production-orders/{po['id']}/batches/{batch['id']}/qc", json={"result": "rejected"})
    assert resp.status_code == 422

    po = ok(c.post(f"/production-orders/{po['id']}/batches/{batch['id']}/qc",
                   json={"result": "rejected", "notes": "شرخ في التغليف"}))
    assert stock_of(c, fin["id"], w["id"]) == 0
    assert ok(c.get(f"/products/{fin['id']}"))["cost_price"] == "0.00"
    details = ok(c.get(f"/production-orders/{po['id']}"))
    assert details["batches"][0]["qc_status"] == "rejected"
    assert details["batches"][0]["notes"] == "شرخ في التغليف"


# ---------------------------------------------------------------- 6) أجور تلقائية من مركز التشغيل
def test_auto_labor_from_work_center_on_progress(api):
    c = api
    wc = ok(c.post("/work-centers", json={"name": "WC-1", "hourly_cost": "120"}), 201)
    w, raw, fin, _bom = setup_cycle(c, bom_qty_per=1)
    make_bom(c, fin["id"], [{"component_id": raw["id"], "qty_per_output": "1"}], version="v2",
             operations=[{"seq": 1, "name": "cut", "work_center_id": wc["id"], "run_minutes_per_unit": 60}])
    po = make_order(c, fin["id"], 2, w["id"], w["id"])
    assert float(po["std_unit_cost"]) == 10.0  # التكلفة القياسية تُحسب عند الإنشاء
    po = ok(c.post(f"/production-orders/{po['id']}/issue"))

    po = ok(c.post(f"/production-orders/{po['id']}/operations/1/progress", json={"qty_done": 2}))
    # أجور تلقائية = 2 × 60 دقيقة × 120/ساعة = 240
    assert po["costs_total"] == "240.00"
    assert any("تلقائي" in (cst["description"] or "") for cst in po["costs"])


# ---------------------------------------------------------------- 7) MRP
def test_mrp_single_product_explode(api):
    c = api
    w, raw, fin, _bom = setup_cycle(c, bom_qty_per=2)
    data = ok(c.get(f"/production-orders/mrp/suggestions?product_id={fin['id']}&qty=10"))
    line = data["lines"][0]
    assert line["product_id"] == raw["id"]
    assert float(line["required_total"]) == 20.0
    assert float(line["in_stock"]) == 100.0
    assert float(line["shortfall"]) == 0.0


def test_mrp_aggregate_uses_draft_sales_orders(api):
    c = api
    w, raw, fin, _bom = setup_cycle(c, bom_qty_per=1)
    cust = ok(c.post("/customers", json={"name": "C1"}), 201)
    ok(c.post("/sales-orders", json={
        "customer_id": cust["id"], "warehouse_id": w["id"],
        "items": [{"product_id": fin["id"], "quantity": 10, "unit_price": "50"}],
    }), 201)
    # الرصيد الحالي للمنتج النهائي 0 → اقتراح إنتاج 10
    data = ok(c.get("/production-orders/mrp/aggregate"))
    row = next(r for r in data["lines"] if r["product_id"] == fin["id"])
    assert float(row["open_demand"]) == 10.0
    assert float(row["shortfall"]) == 10.0


def test_mrp_detects_bom_cycle(api):
    c = api
    w = make_warehouse(c, "W", "W9")
    a = make_product(c, "CYC-A", warehouse_id=w["id"])
    b = make_product(c, "CYC-B", warehouse_id=w["id"])
    make_bom(c, a["id"], [{"component_id": b["id"], "qty_per_output": "1"}])
    make_bom(c, b["id"], [{"component_id": a["id"], "qty_per_output": "1"}])
    resp = c.get(f"/production-orders/mrp/suggestions?product_id={a['id']}&qty=1")
    assert resp.status_code == 422


# ---------------------------------------------------------------- 8) تتبع الدفعات + بطاقة الطباعة
def test_batch_trace(api):
    c = api
    w, raw, fin, _bom = setup_cycle(c, bom_qty_per=2)
    po = make_order(c, fin["id"], 3, w["id"], w["id"])
    ok(c.post(f"/production-orders/{po['id']}/issue"))
    po = ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 3}))
    batch_no = f"{po['code']}-B1"
    data = ok(c.get(f"/production-orders/batches/trace?batch_no={batch_no}"))
    assert data["order_code"] == po["code"]
    assert data["consumptions"][0]["qty"] == 6
    assert c.get("/production-orders/batches/trace?batch_no=NOPE").status_code == 404


def test_print_card(api):
    c = api
    w, raw, fin, _bom = setup_cycle(c)
    po = make_order(c, fin["id"], 2, w["id"], w["id"])
    resp = c.get(f"/production-orders/{po['id']}/print-card")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert po["code"] in resp.text


# ---------------------------------------------------------------- 9) حماية المخازن + البحث
def test_list_search_and_std_cost_in_order(api):
    c = api
    w, raw, fin, _bom = setup_cycle(c)
    po = make_order(c, fin["id"], 2, w["id"], w["id"])
    rows = ok(c.get("/production-orders?search=F1"))
    assert any(r["id"] == po["id"] for r in rows)
    rows = ok(c.get("/production-orders?search=NO-MATCH-XYZ"))
    assert rows == []
    assert float(po["std_unit_cost"]) == 10.0  # خامة واحدة × 1 × 10 (سعر الخامة الافتراضي)


def test_duplicate_bom_version_rejected_cleanly(api):
    """تكرار إصدار قائمة المواد لنفس المنتج → 422 برسالة واضحة (وليس 500)."""
    c = api
    w, raw, fin, _bom = setup_cycle(c)
    dup = c.post("/boms", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": "1"}], "operations": [],
    })
    assert dup.status_code == 422, dup.text
    assert "موجود بالفعل" in dup.text

    # التعديل إلى إصدار قائمة أخرى لنفس المنتج مرفوض أيضًا
    other = make_bom(c, fin["id"], [{"component_id": raw["id"], "qty_per_output": "1"}], version="v9")
    clash = c.patch(f"/boms/{other['id']}", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": False,
        "items": [{"component_id": raw["id"], "qty_per_output": "1"}], "operations": [],
    })
    assert clash.status_code == 422, clash.text


def test_production_order_scheduling(api):
    """جدولة أوامر التصنيع: تحديد التاريخ والخط + فلاتر القائمة + منع جدولة المكتمل."""
    from datetime import date, timedelta

    c = api
    w, raw, fin, _bom = setup_cycle(c)
    line = ok(c.post("/production-lines", json={"name": "خط الجدولة", "capacity_per_hour": "10", "hourly_cost": "50"}), 201)
    po = make_order(c, fin["id"], 5, w["id"], w["id"])

    d1 = (date.today() + timedelta(days=2)).isoformat()
    resp = ok(c.put(f"/production-orders/{po['id']}/schedule", json={"scheduled_date": d1, "production_line_id": line["id"]}))
    assert resp["scheduled_date"] == d1
    assert resp["production_line_id"] == line["id"]

    # فلاتر القائمة: مجدولة ضمن الأسبوع + بلا جدولة + خط محدد
    rows = ok(c.get(f"/production-orders?scheduled_from={date.today().isoformat()}&scheduled_to={(date.today() + timedelta(days=7)).isoformat()}"))
    assert any(r["id"] == po["id"] for r in rows)
    rows = ok(c.get("/production-orders?scheduled=false"))
    assert all(r["scheduled_date"] is None for r in rows)
    rows = ok(c.get(f"/production-orders?line_id={line['id']}"))
    assert [r["id"] for r in rows] == [po["id"]]

    # إزالة الجدولة
    resp = ok(c.put(f"/production-orders/{po['id']}/schedule", json={"scheduled_date": None, "production_line_id": None}))
    assert resp["scheduled_date"] is None and resp["production_line_id"] is None

    # خط غير موجود مرفوض
    resp = c.put(f"/production-orders/{po['id']}/schedule", json={"scheduled_date": d1, "production_line_id": 99999})
    assert resp.status_code == 422, resp.text

    # أمر مكتمل لا يُجدول
    ok(c.post(f"/production-orders/{po['id']}/issue"))
    ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 5}))
    resp = c.put(f"/production-orders/{po['id']}/schedule", json={"scheduled_date": d1})
    assert resp.status_code == 409, resp.text


def test_efficiency_features(api):
    """رفع الكفاءة: الدقائق المقدرة في القائمة + تقرير أداء مراكز التشغيل."""
    c = api
    wc = ok(c.post("/work-centers", json={"name": "WC-EFF", "capacity_per_hour": "10", "hourly_cost": "60"}), 201)
    w, raw, fin, _bom = setup_cycle(c)
    ok(c.patch(f"/boms/{_bom['id']}", json={
        "product_id": fin["id"], "version": "v1", "output_qty": 1, "is_active": True,
        "items": [{"component_id": raw["id"], "qty_per_output": "1"}],
        "operations": [{"seq": 1, "name": "تشغيل", "work_center_id": wc["id"], "run_minutes_per_unit": "30"}],
    }))
    po = make_order(c, fin["id"], 4, w["id"], w["id"])

    # الدقائق المقدرة = 30 دقيقة × 4 وحدات = 120
    rows = ok(c.get("/production-orders"))
    row = next(r for r in rows if r["id"] == po["id"])
    assert float(row["estimated_minutes"]) == 120.0, row

    # تقدم المرحلة: 2 منجز → فعلي 60 من أصل 120 مخططة = 50%
    ok(c.post(f"/production-orders/{po['id']}/issue"))
    ok(c.post(f"/production-orders/{po['id']}/operations/1/progress", json={"qty_done": 2}))
    rep = ok(c.get("/production-orders/reports/work-centers"))
    wcr = next(r for r in rep["rows"] if r["work_center_id"] == wc["id"])
    assert wcr["orders_count"] == 1
    assert float(wcr["planned_minutes"]) == 120.0
    assert float(wcr["actual_minutes"]) == 60.0
    assert wcr["utilization"] == 50.0

    # فلترة بالتاريخ: المستقبل فقط → صفر بيانات
    from datetime import date, timedelta
    rep = ok(c.get(f"/production-orders/reports/work-centers?date_from={(date.today() + timedelta(days=3)).isoformat()}"))
    wcr = next(r for r in rep["rows"] if r["work_center_id"] == wc["id"])
    assert wcr["orders_count"] == 0 and float(wcr["planned_minutes"]) == 0.0


def test_lot_tracking_fifo(api):
    """تتبع اللوطات: استلام → تخصيص FIFO عند الصرف → تتبع عكسي → إرجاع عند الإيقاف."""
    from decimal import Decimal

    c = api
    w, raw, fin, _bom = setup_cycle(c, bom_qty_per=1)

    # لوطان: أقدم بلا انتهاء، وأحدث بانتهاء أبعد — FIFO بالأقدم أولًا
    l1 = ok(c.post("/lots", json={"product_id": raw["id"], "warehouse_id": w["id"], "lot_code": "LOT-A", "qty": 10, "reference": "استلام افتتاحي"}), 201)
    l2 = ok(c.post("/lots", json={"product_id": raw["id"], "warehouse_id": w["id"], "lot_code": "LOT-B", "qty": 15, "reference": "استلام ثاني"}), 201)

    # قائمة اللوطات
    rows = ok(c.get(f"/lots?product_id={raw['id']}"))
    assert {r["lot_code"] for r in rows} == {"LOT-A", "LOT-B"}

    # استلام شراء يبني لوطًا تلقائيًا PO-{id}
    sup = ok(c.post("/suppliers", json={"name": "مورد اللوطات"}), 201)
    po_recv = ok(c.post("/purchase-orders", json={
        "supplier_id": sup["id"], "warehouse_id": w["id"],
        "items": [{"product_id": raw["id"], "quantity": 20, "unit_cost": "3"}],
    }), 201)
    # إنشاء أمر الشراء يستلم فورًا → لوط تلقائي PO-{id}
    lots = ok(c.get(f"/lots?product_id={raw['id']}"))
    assert any(r["lot_code"] == f"PO-{po_recv['id']}" and float(r["qty_remaining"]) == 20 for r in lots)

    # أمر تصنيع يحتاج 12 → FIFO: LOT-A (10) ثم LOT-B (2)
    po = make_order(c, fin["id"], 12, w["id"], w["id"])
    ok(c.post(f"/production-orders/{po['id']}/issue"))
    trace = ok(c.get(f"/production-orders/{po['id']}/lots"))
    allocs = {t["lot_code"]: float(t["qty"]) for t in trace}
    assert allocs == {"LOT-A": 10.0, "LOT-B": 2.0}, trace

    # الأرصدة انخفضت صح
    rows = {r["lot_code"]: float(r["qty_remaining"]) for r in ok(c.get(f"/lots?product_id={raw['id']}"))}
    assert rows["LOT-A"] == 0.0 and rows["LOT-B"] == 13.0

    # لوطات لا تكفي → 409 عند محاولة صرف أكبر من رصيد اللوطات
    po2 = make_order(c, fin["id"], 999, w["id"], w["id"])
    resp = c.post(f"/production-orders/{po2['id']}/issue")
    assert resp.status_code == 409, resp.text

    # إيقاف أمر قيد التنفيذ يرجع اللوطات لأرصدتها
    ok(c.post(f"/production-orders/{po['id']}/cancel-running"))
    rows = {r["lot_code"]: float(r["qty_remaining"]) for r in ok(c.get(f"/lots?product_id={raw['id']}"))}
    assert rows["LOT-A"] == 10.0 and rows["LOT-B"] == 15.0
    assert ok(c.get(f"/production-orders/{po['id']}/lots")) == []


def test_quality_checkpoints(api):
    """الجودة بمعايير: نموذج فحص بمعايير رقمية ومنطقية → قياس دفعة → أحكام محسوبة."""
    c = api
    w, raw, fin, _bom = setup_cycle(c)

    tpl = ok(c.post("/qc/templates", json={
        "name": "فحص العصير",
        "description": "فحص أساسي للدفعة",
        "parameters": [
            {"name": "الحموضة pH", "unit": "pH", "param_type": "number", "min_value": 3.2, "max_value": 3.8},
            {"name": "اللون مطابق", "param_type": "bool"},
        ],
    }), 201)
    assert len(tpl["parameters"]) == 2

    # ربط النموذج بالمنتج
    resp = ok(c.put(f"/qc/products/{fin['id']}", json={"template_ids": [tpl["id"]]}))
    assert resp["template_ids"] == [tpl["id"]]
    assert ok(c.get(f"/qc/products/{fin['id']}"))["template_ids"] == [tpl["id"]]

    # دفعة إنتاج → تسجيل قياسات: واحد داخل النطاق وواحد مطابق → الحكم الإجمالي مطابق
    po = make_order(c, fin["id"], 5, w["id"], w["id"])
    ok(c.post(f"/production-orders/{po['id']}/issue"))
    batch = ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 5}))
    batch_id = batch["batches"][-1]["id"]
    meas = ok(c.post(f"/qc/batches/{batch_id}/results", json={"results": [
        {"parameter_id": tpl["parameters"][0]["id"], "value_num": 3.5},
        {"parameter_id": tpl["parameters"][1]["id"], "value_text": "مطابق"},
    ]}))
    assert meas["overall_pass"] is True
    assert meas["results"][0]["pass_fail"] is True

    # قيمة خارج النطاق → غير مطابق
    meas = ok(c.post(f"/qc/batches/{batch_id}/results", json={"results": [
        {"parameter_id": tpl["parameters"][0]["id"], "value_num": 4.5},
    ]}))
    assert meas["overall_pass"] is False
    assert meas["results"][0]["pass_fail"] is False

    # النتائج محفوظة واسترجاعها يعمل
    saved = ok(c.get(f"/qc/batches/{batch_id}/results"))
    assert len(saved["results"]) == 2

    # رفض الاعتماد النهائي — قياس غير مطابق لا يمنع القرار اليدوي (القرار للمُعتمِد)
    ok(c.post(f"/production-orders/{po['id']}/batches/{batch_id}/qc", json={"result": "rejected", "notes": "قياس خارج النطاق"}))
    po_full = ok(c.get(f"/production-orders/{po['id']}"))
    assert po_full["batches"][-1]["qc_status"] == "rejected"

    # حذف نموذج مربوط بمنتج مرفوض حتى فصل الربط
    resp = c.delete(f"/qc/templates/{tpl['id']}")
    assert resp.status_code == 400, resp.text
    ok(c.put(f"/qc/products/{fin['id']}", json={"template_ids": []}))
    assert c.delete(f"/qc/templates/{tpl['id']}").status_code == 204


def test_availability_badge_and_bom_copy(api):
    """شارة توافر الخامات في القائمة + نسخ إصدار BOM."""
    from datetime import date

    c = api
    w, raw, fin, _bom = setup_cycle(c, bom_qty_per=1)

    # الخامة متاحة (100 في المخزن والمطلوب 5) → badge true
    po = make_order(c, fin["id"], 5, w["id"], w["id"])
    rows = {r["id"]: r for r in ok(c.get("/production-orders"))}
    assert rows[po["id"]]["materials_available"] is True

    # أمر أكبر من الرصيد → false
    po2 = make_order(c, fin["id"], 500, w["id"], w["id"])
    rows = {r["id"]: r for r in ok(c.get("/production-orders"))}
    assert rows[po2["id"]]["materials_available"] is False
    # المكتملة لا تحمل الشارة
    ok(c.post(f"/production-orders/{po['id']}/issue"))
    ok(c.post(f"/production-orders/{po['id']}/produce", json={"qty": 5}))
    rows = {r["id"]: r for r in ok(c.get("/production-orders"))}
    assert rows[po["id"]]["materials_available"] is None

    # نسخ الإصدار: تلقائي v2 + بنود مطابقة، غير مفعّل افتراضيًا
    copy = ok(c.post(f"/boms/{_bom['id']}/copy", json={}), 201)
    assert copy["version"] == "v2" and copy["is_active"] is False
    assert len(copy["items"]) == len(_bom["items"])

    # نسخ بإصدار موجود → 422، والنسخ المفعّل يوقف القديم
    resp = c.post(f"/boms/{_bom['id']}/copy", json={"version": "v2"})
    assert resp.status_code == 422, resp.text
    active_copy = ok(c.post(f"/boms/{_bom['id']}/copy", json={"version": "v3", "is_active": True}), 201)
    assert active_copy["is_active"] is True
    bom_full = ok(c.get(f"/boms/{_bom['id']}"))
    assert bom_full["is_active"] is False
