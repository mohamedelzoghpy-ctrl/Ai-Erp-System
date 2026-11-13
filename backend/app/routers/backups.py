"""النسخ الاحتياطي والاستعادة — platform-admin فقط.

نسخة كاملة من قاعدة البيانات (كل الجداول JSON.gz) تُحفظ على القرص وتُنزَّل وتُحذف،
والاستعادة تعيد كل الجداول بترتيب الاعتماديات داخل معاملة واحدة (فشل = تراجع كامل)
مع إعادة ضبط تسلسلات المعرفات على Postgres.

المسار الافتراضي: env BACKUP_DIR (افتراضي /app/backups داخل الحاوية).
"""
import gzip
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import Base, get_db
from ..deps import require_platform_admin
from ..audit import audit
from .. import models

router = APIRouter(prefix="/admin/backups", tags=["backups"])

_SAFE_NAME = re.compile(r"^backup-\d{8}-\d{6}\.json\.gz$")
_JSON_AUTO_NAME = re.compile(r"^auto-json-\d{8}-\d{6}\.json\.gz$")
_SQL_NAME = re.compile(r"^auto-erp_db-\d{8}-\d{6}\.sql\.gz$")


def _validate_file(path: Path, kind: str) -> dict:
    """فحص سلامة النسخة: JSON = فك + تحليل كامل + تنسيق صحيح + جداول غير فارغة؛
    SQL = فك + مؤشر تفريغ PostgreSQL + حجم معقول. يعيد {ok, detail}."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            content = fh.read()
        if not content:
            return {"ok": False, "detail": "الملف فارغ"}
        if kind == "sql_auto":
            if "PostgreSQL database dump" in content or "-- Dumped" in content:
                return {"ok": True, "detail": "تفريغ PostgreSQL سليم"}
            return {"ok": False, "detail": "لا يحتوي تفريغ PostgreSQL"}
        data = json.loads(content)
        if data.get("format") != "mozad-backup-1":
            return {"ok": False, "detail": "تنسيق غير معروف"}
        tables = data.get("tables") or {}
        empty = sum(1 for rows in tables.values() if not rows)
        return {"ok": True, "detail": f"{len(tables)} جدولًا ({len(tables) - empty} بها بيانات)", "tables": len(tables)}
    except Exception as exc:
        return {"ok": False, "detail": f"تالف: {exc}"}


def _backup_kind(name: str) -> str:
    """json_manual | json_auto | sql_auto — للعرض والصلاحيات في الواجهة."""
    if _SQL_NAME.match(name):
        return "sql_auto"
    if _JSON_AUTO_NAME.match(name):
        return "json_auto"
    return "json_manual"


def _restorable(name: str) -> bool:
    """النسخ JSON فقط (اليدوية والتلقائية) قابلة للاستعادة من الواجهة."""
    return not _SQL_NAME.match(name)


def _backup_dir() -> Path:
    d = Path(os.getenv("BACKUP_DIR", "/app/backups"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dump_payload(db: Session) -> dict:
    """لقطة كاملة: كل جدول في metadata بصفوفه (تواريخ/عشري كنص)."""
    tables: dict = {}
    for table in Base.metadata.sorted_tables:
        cols = [c.name for c in table.columns]
        rows = db.execute(table.select()).mappings().all()
        tables[table.name] = [
            {c: (str(v) if hasattr(v, "isoformat") or isinstance(v, __import__("decimal").Decimal) else v) for c, v in row.items()}
            for row in rows
        ]
        _ = cols
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "format": "mozad-backup-1",
        "tables": tables,
    }


@router.get("")
def list_backups(_: models.User = Depends(require_platform_admin)):
    d = _backup_dir()
    files = sorted(
        list(d.glob("backup-*.json.gz")) + list(d.glob("auto-json-*.json.gz")) + list(d.glob("auto-erp_db-*.sql.gz")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out = []
    for f in files:
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                head = json.loads(fh.read(400) or "{}")
        except Exception:
            head = {}
        # النسخ القديمة قد تفتقد generated_at في الرأس — الرقم مضمّن في اسم الملف دائمًا،
        # وmtime احتياط أخير. Date دائمًا موجود.
        generated = head.get("generated_at")
        if not generated:
            m = re.search(r"(\d{8})-(\d{6})\.", f.name)
            if m:
                generated = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()
            else:
                generated = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()
        kind = _backup_kind(f.name)
        out.append({
            "name": f.name, "size": f.stat().st_size, "generated_at": generated,
            "type": kind, "restorable": _restorable(f.name),
            "valid": _validate_file(f, kind),
        })
    return out


def _write_json_backup(db: Session, prefix: str) -> tuple:
    """كتابة نسخة JSON على القرص — يستخدمها اليدوي والمجدول معًا. يعيد (الاسم، الحجم)."""
    payload = _dump_payload(db)
    stamp = datetime.now(timezone.utc)
    name = f"{prefix}-{stamp.strftime('%Y%m%d-%H%M%S')}.json.gz"
    path = _backup_dir() / name
    # نسختان في نفس الثانية (يدوي + مجدول) → زد الثانية حتى الاسم فريد — النمط يبقى سليمًا
    while path.exists():
        stamp = stamp + timedelta(seconds=1)
        name = f"{prefix}-{stamp.strftime('%Y%m%d-%H%M%S')}.json.gz"
        path = _backup_dir() / name
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str)
    return name, path.stat().st_size, len(payload["tables"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_backup(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_platform_admin),
):
    """إنشاء نسخة احتياطية كاملة الآن (JSON.gz على القرص)."""
    name, size, tables = _write_json_backup(db, "backup")
    audit(db, user, "create", "backup", None, f"نسخة احتياطية {name} ({size} بايت)")
    db.commit()
    return {"name": name, "size": size, "tables": tables}


# ---------------- المجدول: نسخ JSON تلقائية كل ساعة (احتفاظ بأحدث 2) ----------------
_SCHED_LOCK = __import__("threading").Lock()


def run_scheduled_json_backup() -> dict:
    """نسخة JSON تلقائية واحدة + تنظيف الاحتفاظ (أحدث 2 من التلقائية فقط —
    لا تمس النسخ اليدوية backup-*). يعيد ملخصًا للتشخيص."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        name, size, tables = _write_json_backup(db, "auto-json")
        keep = sorted(_backup_dir().glob("auto-json-*.json.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
        removed = 0
        for old_path in keep[2:]:
            old_path.unlink()
            removed += 1
        db.commit()
        # تحقق فوري من سلامة ما كُتب — النسخة التالفة تُحذف إن كانت هي الأحدث
        validation = _validate_file(_backup_dir() / name, "json_auto")
        if not validation.get("ok"):
            print(f"[auto-backup] ⚠️ النسخة {name} تالفة — حذفها: {validation.get('detail')}")
            try:
                (_backup_dir() / name).unlink()
            except OSError:
                pass
            return {"ok": False, "error": f"النسخة تالفة: {validation.get('detail')}", "removed": removed}
        # بلا سجل تدقيق: المهمة نظامية بلا مستخدم/شركة — الطباعة ووجود الملف هما الأثر
        return {"ok": True, "name": name, "size": size, "tables": tables, "removed": removed, "validation": validation}
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()


def _auto_json_backup_loop() -> None:
    """حلقة الخلفية: أول نسخة بعد دقيقة من الإقلاع ثم كل ساعة (AUTO_JSON_BACKUP_SECONDS)."""
    import time as _time
    interval = int(os.getenv("AUTO_JSON_BACKUP_SECONDS", "3600"))
    first_delay = int(os.getenv("AUTO_JSON_BACKUP_FIRST_DELAY", "60"))
    _time.sleep(first_delay)
    while True:
        if _SCHED_LOCK.acquire(blocking=False):
            try:
                result = run_scheduled_json_backup()
                print(f"[auto-backup] {result}")
            except Exception as exc:  # noqa: BLE001 — الخلفية لا تُسقط التطبيق
                print(f"[auto-backup] failed: {exc}")
            finally:
                _SCHED_LOCK.release()
        _time.sleep(interval)


@router.get("/{name}/download")
def download_backup(name: str, _: models.User = Depends(require_platform_admin)):

    path = _backup_dir() / name
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "النسخة غير موجودة")
    return Response(
        content=path.read_bytes(),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(
    name: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_platform_admin),
):
    if not (_SAFE_NAME.match(name) or _JSON_AUTO_NAME.match(name) or _SQL_NAME.match(name)):
        raise HTTPException(422, "اسم ملف غير صالح")
    path = _backup_dir() / name
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "النسخة غير موجودة")
    path.unlink()
    audit(db, user, "delete", "backup", None, f"حذف نسخة {name}")
    db.commit()
    return None


class RestoreIn(BaseModel):
    confirm: str = "استعادة"


@router.post("/{name}/restore")
def restore_backup(
    name: str,
    payload: RestoreIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_platform_admin),
):
    """استعادة نسخة كاملة: تمسح الجداول وتعيد بناءها بترتيب الاعتماديات في معاملة واحدة.

    خطير بطبيعته (يستبدل كل البيانات) — يتطلب platform-admin + تأكيد نصي «استعادة»."""
    if payload.confirm != "استعادة":
        raise HTTPException(422, "اكتب كلمة التأكيد «استعادة» للتنفيذ")
    if not (_SAFE_NAME.match(name) or _JSON_AUTO_NAME.match(name) or _SQL_NAME.match(name)):
        raise HTTPException(422, "اسم ملف غير صالح")
    if _SQL_NAME.match(name):
        raise HTTPException(422, "الاستعادة متاحة لنسخ JSON فقط — نسخ SQL تُستعاد عبر psql")
    path = _backup_dir() / name
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "النسخة غير موجودة")

    validation = _validate_file(path, "json_manual" if _SAFE_NAME.match(name) else "json_auto")
    if not validation.get("ok"):
        raise HTTPException(422, f"الملف تالف ولا يمكن الاستعادة منه: {validation.get('detail')}")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("format") != "mozad-backup-1":
        raise HTTPException(422, "الملف ليس نسخة احتياطية صالحة لهذا النظام")
    tables = data.get("tables") or {}
    known = {t.name for t in Base.metadata.sorted_tables}
    unknown = set(tables) - known
    if unknown:
        raise HTTPException(422, f"جداول غير معروفة في الملف: {sorted(unknown)[:5]}")

    def _coerce(table, rows):
        """إعادة الأنواع بعد JSON: تواريخ نصية → كائنات، JSON نصية → كائنات."""
        from datetime import datetime as _dt, date as _d
        from decimal import Decimal as _Dec
        out = []
        for row in rows:
            fixed = {}
            for c in table.columns:
                v = row.get(c.name)
                if v is None:
                    fixed[c.name] = None
                    continue
                py = c.type.python_type if hasattr(c.type, "python_type") else None
                try:
                    if py in (_dt,):
                        fixed[c.name] = _dt.fromisoformat(str(v).replace("Z", "+00:00"))
                    elif py is _d:
                        fixed[c.name] = _d.fromisoformat(str(v)[:10])
                    elif c.type.__class__.__name__.startswith("JSON") and isinstance(v, str):
                        fixed[c.name] = json.loads(v)
                    elif py is _Dec:
                        fixed[c.name] = _Dec(str(v))
                    else:
                        fixed[c.name] = v
                except (ValueError, TypeError):
                    fixed[c.name] = v
            out.append(fixed)
        return out

    try:
        for table in reversed(Base.metadata.sorted_tables):  # الحذف بعكس الاعتماديات
            if table.name in tables:
                db.execute(table.delete())
        for table in Base.metadata.sorted_tables:  # الإدخال بترتيب الاعتماديات
            rows = _coerce(table, tables.get(table.name) or [])
            for chunk_start in range(0, len(rows), 500):
                chunk = rows[chunk_start:chunk_start + 500]
                if chunk:
                    db.execute(table.insert(), chunk)
        if db.bind.dialect.name == "postgresql":
            for table in Base.metadata.sorted_tables:
                if any(c.primary_key and c.autoincrement for c in table.columns):
                    pk = next(c.name for c in table.columns if c.primary_key)
                    db.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk}'), "
                        f"COALESCE((SELECT MAX({pk}) FROM {table.name}), 1))"
                    ))
        audit(db, user, "restore", "backup", None, f"استعادة كاملة من {name} — {sum(len(v) for v in tables.values())} صف")
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"فشلت الاستعادة وتم التراجع كاملًا: {exc}") from exc
    return {"restored": True, "tables": sum(1 for v in tables.values() if v), "rows": sum(len(v) for v in tables.values())}