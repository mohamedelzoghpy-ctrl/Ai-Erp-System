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
from datetime import datetime, timezone
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
    files = sorted(_backup_dir().glob("backup-*.json.gz"), reverse=True)
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
            m = re.match(r"backup-(\d{8})-(\d{6})\.json\.gz", f.name)
            if m:
                generated = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()
            else:
                generated = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()
        out.append({"name": f.name, "size": f.stat().st_size, "generated_at": generated})
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
def create_backup(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_platform_admin),
):
    """إنشاء نسخة احتياطية كاملة الآن (JSON.gz على القرص)."""
    payload = _dump_payload(db)
    name = f"backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json.gz"
    path = _backup_dir() / name
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str)
    size = path.stat().st_size
    audit(db, user, "create", "backup", None, f"نسخة احتياطية {name} ({size} بايت)")
    db.commit()
    return {"name": name, "size": size, "tables": len(payload["tables"])}


@router.get("/{name}/download")
def download_backup(name: str, _: models.User = Depends(require_platform_admin)):
    if not _SAFE_NAME.match(name):
        raise HTTPException(422, "اسم ملف غير صالح")
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
    if not _SAFE_NAME.match(name):
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
    if not _SAFE_NAME.match(name):
        raise HTTPException(422, "اسم ملف غير صالح")
    path = _backup_dir() / name
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "النسخة غير موجودة")

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
