"""أداة تسوية أرصدة شجرة الحسابات: اختيار الحسابات، وضعا rebuild/journal، ومزامنة الخزائن — عبر الـ API (SQLite في الذاكرة)."""

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
    assert client.post("/auth/setup", json={"username": "boss", "password": "long-password"}).status_code == 201
    token = client.post("/auth/login", data={"username": "boss", "password": "long-password"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    app.dependency_overrides.pop(get_db, None)


def ok(resp, code=200):
    assert resp.status_code == code, (resp.status_code, resp.text)
    return resp.json() if resp.content else None


# ---------------------------------------------------------------- helpers
def setup_company_with_coa(c):
    """فرع + شجرة حسابات مبذورة — عشان الخزائن تتربط بحساباتها تلقائيًا."""
    branch = ok(c.post("/company/branches", json={"name": "Main", "location": None}), 201)
    ok(c.post("/chart-of-accounts/seed", json={}), 201)
    return branch


def make_safe(c, name, opening="0"):
    branches = ok(c.get("/company/branches"))
    return ok(c.post("/safes", json={"name": name, "branch_id": branches[0]["id"], "opening_balance": opening}), 201)


def drifted_lines(report):
    return [l for l in report["lines"] if float(l["drift"]) != 0]


# ---------------------------------------------------------------- partial selection
def test_partial_apply_fixes_only_selected(api):
    setup_company_with_coa(api)
    make_safe(api, "S1", opening="100.00")
    make_safe(api, "S2", opening="50.00")
    report = ok(api.get("/chart-of-accounts/reconcile"))
    drifted = drifted_lines(report)
    assert len(drifted) == 2
    target, other = drifted[0], drifted[1]

    res = ok(api.post("/chart-of-accounts/reconcile/apply", json={"account_ids": [target["account_id"]], "mode": "rebuild"}))
    assert res["changed"] == 1

    report2 = ok(api.get("/chart-of-accounts/reconcile"))
    after = {l["account_id"]: l for l in report2["lines"]}
    # الحساب المُسوّى قد يختفي من التقرير لو صفر وصفر — الغياب يعني drift صفر
    target_after = after.get(target["account_id"])
    assert target_after is None or float(target_after["drift"]) == 0.0
    assert float(after[other["account_id"]]["drift"]) == float(other["drift"])  # غير المختار لم يُمس


# ---------------------------------------------------------------- journal mode
def test_journal_mode_posts_balanced_entry_and_keeps_stored(api):
    setup_company_with_coa(api)
    make_safe(api, "Old Safe", opening="121.80")  # رصيد افتتاحي بلا قيد → drift
    accounts = ok(api.get("/chart-of-accounts"))
    capital = next(a for a in accounts if a["code"] == "3100")
    target = drifted_lines(ok(api.get("/chart-of-accounts/reconcile")))[0]

    res = ok(api.post("/chart-of-accounts/reconcile/apply", json={
        "account_ids": [target["account_id"]],
        "mode": "journal",
        "counter_account_id": capital["id"],
    }))
    assert res["changed"] == 1
    je_id = res["journal_entry_id"]
    assert je_id

    je = ok(api.get(f"/journal-entries/{je_id}"))
    total_debit = round(sum(float(i["debit"]) for i in je["items"]), 2)
    total_credit = round(sum(float(i["credit"]) for i in je["items"]), 2)
    assert total_debit == total_credit == 121.80

    # القيد رفع رصيد الدفتر ليساوي المخزن — والمخزن اتحفظ كما هو
    report2 = ok(api.get("/chart-of-accounts/reconcile"))
    line = next(l for l in report2["lines"] if l["account_id"] == target["account_id"])
    assert float(line["drift"]) == 0.0
    assert float(line["stored"]) == 121.80
    cap_line = next(l for l in report2["lines"] if l["account_id"] == capital["id"])
    assert float(cap_line["stored"]) == 121.80 and float(cap_line["ledger"]) == 121.80


# ---------------------------------------------------------------- backward compatibility
def test_empty_body_rebuilds_all_drifted(api):
    setup_company_with_coa(api)
    make_safe(api, "S1", opening="100.00")
    make_safe(api, "S2", opening="50.00")
    res = ok(api.post("/chart-of-accounts/reconcile/apply"))  # بدون body — السلوك القديم
    assert res["changed"] == 2
    report2 = ok(api.get("/chart-of-accounts/reconcile"))
    assert float(report2["total_drift"]) == 0.0


# ---------------------------------------------------------------- sync cash
def test_sync_cash_pulls_safe_balance_from_linked_account(api):
    setup_company_with_coa(api)
    safe = make_safe(api, "Cash Box", opening="500.00")
    target = drifted_lines(ok(api.get("/chart-of-accounts/reconcile")))[0]
    ok(api.post("/chart-of-accounts/reconcile/apply", json={"account_ids": [target["account_id"]], "mode": "rebuild"}))

    # بعد إعادة البناء رصيد الحساب صفر — الخزينة لسه شايلة الافتتاحي
    assert float(ok(api.get(f"/safes/{safe['id']}"))["balance"]) == 500.0

    res = ok(api.post("/chart-of-accounts/reconcile/sync-cash", json={}))
    assert res["synced"] == 1
    assert float(ok(api.get(f"/safes/{safe['id']}"))["balance"]) == 0.0


# ---------------------------------------------------------------- validation
def test_journal_mode_rejects_bad_counter(api):
    setup_company_with_coa(api)
    make_safe(api, "S1", opening="80.00")
    accounts = ok(api.get("/chart-of-accounts"))
    group_acc = next(a for a in accounts if a["is_group"])
    target_id = drifted_lines(ok(api.get("/chart-of-accounts/reconcile")))[0]["account_id"]

    def apply(**extra):
        body = {"account_ids": [target_id], "mode": "journal", **extra}
        return api.post("/chart-of-accounts/reconcile/apply", json=body)

    assert apply(counter_account_id=target_id).status_code == 400      # المقابل ضمن المُسوّاة
    assert apply(counter_account_id=group_acc["id"]).status_code == 400  # حساب مجموعي
    assert apply(counter_account_id=999999).status_code == 400          # غير موجود
    assert apply().status_code == 400                                   # counter ناقص في وضع journal

    non_drift = next(a["id"] for a in accounts if a["id"] != target_id and not a["is_group"])
    r5 = api.post("/chart-of-accounts/reconcile/apply", json={"account_ids": [target_id, non_drift], "mode": "rebuild"})
    assert r5.status_code == 400  # حساب غير متنافر ضمن الاختيار
