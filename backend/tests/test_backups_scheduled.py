"""النسخ الاحتياطية المجدولة (JSON تلقائية كل ساعة) + عرض نسخ SQL في القائمة."""
import gzip
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def env(tmp_path, monkeypatch):
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
    # المجدول يستخدم SessionLocal داخليًا — وجّهه لمحرك الاختبار
    import app.database as adb
    monkeypatch.setattr(adb, "SessionLocal", factory)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    client = TestClient(app)
    client.post("/auth/setup", json={"username": "boss", "password": "long-password-123"})
    tok = client.post("/auth/login", data={"username": "boss", "password": "long-password-123"}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {tok}"
    yield client, factory, tmp_path
    app.dependency_overrides.pop(get_db, None)


def ok(resp, code=200):
    assert resp.status_code == code, (resp.status_code, resp.text)
    return resp.json() if resp.content else None


def test_scheduled_json_backup_with_keep2_retention(env):
    client, factory, tmp_path = env
    from app.routers.backups import run_scheduled_json_backup

    # نسخة يدوية من الواجهة — لا يجب أن تمسها التلقائية
    manual = ok(client.post("/admin/backups"), 201)

    r1 = run_scheduled_json_backup()
    assert r1["ok"] is True and r1["name"].startswith("auto-json-")
    r2 = run_scheduled_json_backup()
    r3 = run_scheduled_json_backup()

    rows = ok(client.get("/admin/backups"))
    autos = [r for r in rows if r["type"] == "json_auto"]
    manuals = [r for r in rows if r["type"] == "json_manual"]
    assert len(autos) == 2  # الاحتفاظ بأحدث تلقائيتين فقط
    assert len(manuals) == 1  # اليدوية لا تمس
    names = {r["name"] for r in autos}
    assert r3["name"] in names and r1["name"] not in names  # الأقدم حُذف
    # كل التلقائية قابلة للاستعادة
    assert all(r["restorable"] for r in autos)


def test_list_includes_sql_backups_as_non_restorable(env):
    client, factory, tmp_path = env
    # ملف SQL تلقائي وهمي (كما تكتبه حاوية db-backup)
    (tmp_path / "auto-erp_db-20261114-120000.sql.gz").write_bytes(
        gzip.compress(b"-- fake dump")
    )
    rows = ok(client.get("/admin/backups"))
    sql = [r for r in rows if r["type"] == "sql_auto"]
    assert len(sql) == 1
    assert sql[0]["restorable"] is False
    assert sql[0]["generated_at"].startswith("2026-11-14T12:00:00")  # من اسم الملف
    # تنزيل SQL يعمل
    dl = client.get(f"/admin/backups/{sql[0]['name']}/download")
    assert dl.status_code == 200 and dl.content[:2] == b"\x1f\x8b"


def test_restore_json_auto_but_not_sql(env):
    client, factory, tmp_path = env
    from app.routers.backups import run_scheduled_json_backup
    r = run_scheduled_json_backup()
    assert r["ok"] is True

    # استعادة نسخة JSON تلقائية تعمل
    res = ok(client.post(f"/admin/backups/{r['name']}/restore", json={"confirm": "استعادة"}), 200)
    assert res["restored"] is True

    # ملف SQL → الاستعادة مرفوضة برسالة واضحة
    (tmp_path / "auto-erp_db-20261114-130000.sql.gz").write_bytes(gzip.compress(b"x"))
    resp = client.post("/admin/backups/auto-erp_db-20261114-130000.sql.gz/restore", json={"confirm": "استعادة"})
    assert resp.status_code == 422 and "JSON" in resp.json()["detail"]
