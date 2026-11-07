"""Import/export of the master parties (customers / suppliers), warehouses, and stock balances.

One file per concern, with matching sheets:
  parties (customers / suppliers): contact data + opening + current balances.
  warehouses: the warehouse records + their computed stock footprint.
  warehouse stock (one warehouse): products x current qty + an empty "new qty" column.
  stock matrix (all warehouses): products x each warehouse (current + new columns).

Every import supports:
  ?preview=1     dry-run — returns what would change without touching the database
  url=...        a Google-Sheets link instead of an uploaded file (CSV export of the sheet)
  .csv           a CSV file as well as .xlsx (auto-detected)
Imports return structured, row-accurate errors and per-reason skip counts. Setting /
changing an opening balance or a stock quantity is manager/admin-only, exactly like the
parties and products pages. A stock upload can be undone (POST .../stock/undo) while its
movements are the last batch for that warehouse.
"""

import csv
import io
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from .. import models, stock
from ..accounts import party_balances
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, user_role
from ..exports import XLSX_MIME, build_tables_xlsx
from .. import exports

router = APIRouter(prefix="/data-io", tags=["data-io"], dependencies=[Depends(get_current_user)])

_KIND_CFG = {
    "customer": {"model": models.Customer, "entity": "customer", "file": "customers"},
    "supplier": {"model": models.Supplier, "entity": "supplier", "file": "suppliers"},
}

_HEADERS = ["الكود", "الاسم", "جهة الاتصال", "الهاتف", "البريد الإلكتروني", "العنوان", "الرصيد الافتتاحي", "نشط"]
_KIND_AR = {"customer": "العملاء", "supplier": "الموردون"}
_TOTAL_ROW = ("الإجمالي", "Total", "TOTAL")
_YES = {"نعم", "true", "1", "yes", "Yes"}
_MAX_SHEET_BYTES = 8 * 1024 * 1024


def _cfg(kind: str):
    c = _KIND_CFG.get(kind)
    if c is None:
        raise HTTPException(422, "kind must be 'customer' or 'supplier'")
    return c


def _headers_for(kind: str) -> List[str]:
    return _HEADERS


def _is_manager(user: models.User) -> bool:
    return user_role(user) in ("admin", "manager")


# --------------------------------------------------------------------------- table sources
def _fetch_sheet_csv(url: str) -> bytes:
    """Read a Google-Sheets sharing link as its CSV export. Allow-listed host only."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("docs.google.com", "drive.google.com"):
        raise HTTPException(422, "الرابط يجب أن يكون رابط Google Sheets (docs.google.com)")
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    if not m:
        raise HTTPException(422, "رابط Google Sheets غير صالح (لا يحتوي معرّف الجدول)")
    gid_m = re.search(r"[#&?]gid=(\d+)", url)
    export_url = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
    if gid_m:
        export_url += f"&gid={gid_m.group(1)}"
    import urllib.request

    req = urllib.request.Request(export_url, headers={"User-Agent": "Mozilla/5.0 MOZAD-ERP"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosec: allow-listed host only
            data = resp.read(_MAX_SHEET_BYTES + 1)
    except Exception as exc:
        raise HTTPException(
            422,
            "Google Sheets رفض الاتصال أو الجدول غير موجود — تأكد أن الرابط صحيح وأنه مشارك كـ «أي شخص لديه الرابط · عارض»",
        ) from exc
    if len(data) > _MAX_SHEET_BYTES:
        raise HTTPException(422, "الجدول على Google Sheets أكبر من الحد المسموح")
    return data


def _decode_csv(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _pick_header_rows(all_rows: List[Tuple]) -> Tuple[List[str], List[Tuple]]:
    """Find the header row (the first rows may hold a title/subtitle like the exports do)."""
    keywords = ("الاسم", "المنتج", "الكود", "sku", "الكمية", "الرصيد")
    header_idx = None
    for i, row in enumerate(all_rows[:10]):
        row_text = " ".join(str(c) for c in row).lower()
        # Titles/subtitles often mention a single field (for example, "new quantity").
        # A header row has multiple independent column labels.
        matched = sum(1 for keyword in keywords if keyword in row_text)
        if matched >= 2:
            header_idx = i
            break
    if header_idx is None:
        if not all_rows:
            raise HTTPException(422, "الملف فارغ")
        header_idx = 0
    headers = [str(c).strip() for c in all_rows[header_idx]]
    data = [row for row in all_rows[header_idx + 1:] if any(str(c).strip() for c in row)]
    return headers, data


def _rows_from_xlsx(content: bytes) -> Tuple[List[str], List[Tuple]]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception:
        raise HTTPException(422, "ملف إكسل غير صالح")
    ws = wb.active
    all_rows: List[Tuple] = []
    for r in range(1, (ws.max_row or 0) + 1):  # type: ignore
        all_rows.append(tuple("" if c.value is None else str(c.value).strip() for c in ws[r]))  # type: ignore
    return _pick_header_rows(all_rows)


def _rows_from_csv(text: str) -> Tuple[List[str], List[Tuple]]:
    first = text.splitlines()[0] if text.splitlines() else ""
    delim = ";"
    try:
        delim = csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
    except csv.Error:
        counts = {d: first.count(d) for d in (",", ";", "\t")}
        delim = max(counts, key=lambda k: counts[k]) if any(counts.values()) else ","
    rows = [[(c.strip() if isinstance(c, str) else c) for c in row] for row in csv.reader(io.StringIO(text), delimiter=delim)]
    return _pick_header_rows([tuple(row) for row in rows])


def _read_table(file: Optional[UploadFile], url: Optional[str], *, csv_preferred: bool = False) -> Tuple[List[str], List[Tuple]]:
    """Return (headers, data_rows) from an uploaded xlsx/csv or a Google-Sheets URL."""
    if url and file:
        raise HTTPException(422, "اختر ملفًا أو رابط Google Sheets — لا يمكن الاثنين معًا")
    if url:
        return _rows_from_csv(_decode_csv(_fetch_sheet_csv(url)))
    if file is None:
        raise HTTPException(422, "ارفع ملفًا أو أدخل رابط Google Sheets")
    name = (file.filename or "").lower()
    content = file.file.read(_MAX_SHEET_BYTES + 1)
    if len(content) > _MAX_SHEET_BYTES:
        raise HTTPException(422, "الملف أكبر من الحد المسموح (8MB)")
    if len(content) < 4:
        raise HTTPException(422, "الملف فارغ")
    is_zip = content[:2] == b"PK"  # xlsx is a zip container
    if name.endswith(".csv") or (csv_preferred and not is_zip):
        return _rows_from_csv(_decode_csv(content))
    if is_zip:
        return _rows_from_xlsx(content)
    return _rows_from_csv(_decode_csv(content))


def _value(row: Tuple, idx: Optional[int]) -> Optional[str]:
    if idx is not None and idx < len(row) and row[idx] is not None and str(row[idx]).strip():
        return str(row[idx]).strip()
    return None


def _col_lookup(headers: List[str]):
    header = {h: i for i, h in enumerate(headers) if h}

    def col(*names: str) -> Optional[int]:
        for n in names:
            for h, i in header.items():
                if n == h or n in h:
                    return i
        return None

    return col


def _skip_counts() -> Dict[str, int]:
    return {"totals_rows": 0, "empty_rows": 0, "no_new_value": 0, "no_change": 0, "sample_rows": 0}


def _mark_skip(skips: Dict[str, int], key: str) -> None:
    skips[key if key in skips else "empty_rows"] += 1


def _decorate_template_xlsx(content: bytes, required_titles: Sequence[str], yes_no_title: Optional[str] = "نشط") -> bytes:
    """Shared helper lives in exports; kept as a thin alias for readability."""
    return exports.decorate_template_xlsx(content, required_titles, yes_no_title)


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


# --------------------------------------------------------------------------- parties: export/template
@router.get("/parties/export/xlsx")
def export_parties_xlsx(kind: str, db: Session = Depends(get_db)):
    c = _cfg(kind)
    model = c["model"]
    parties = db.query(model).order_by(model.id).all()
    balances = party_balances(db, kind, [p.id for p in parties]) if parties else {}
    rows, total_opening, total_balance = [], Decimal("0"), Decimal("0")
    for p in parties:
        opening = Decimal(str(p.opening_balance or 0))
        bal = balances.get(p.id, Decimal("0"))
        total_opening += opening
        total_balance += bal
        row: list = [("text", getattr(p, "code", "") or "")]
        row += [
            ("text", p.name), ("text", p.contact_person or ""), ("text", p.phone or ""),
            ("text", p.email or ""), ("text", p.address or ""),
            ("money", p.opening_balance), ("money", bal), ("text", "نعم" if p.is_active else "لا"),
        ]
        rows.append(row)
    rows.append([("text", "الإجمالي")] + [("text", "")] * 5 + [("money", total_opening), ("money", total_balance), ("text", "")])
    content = build_tables_xlsx(
        f"قائمة {_KIND_AR[kind]} وأرصدتهم",
        "يشمل الرصيد الافتتاحي والرصيد الحالي المحسوب من الحركات",
        [(_KIND_AR[kind], _headers_for(kind), rows)],
    )
    return _xlsx_response(content, f'{c["file"]}.xlsx')


@router.get("/parties/template/xlsx")
def party_template_xlsx(kind: str, minimal: Optional[bool] = None):
    """`minimal=1` produces the light template: name + opening balance only (balance-fix imports)."""
    c = _cfg(kind)
    if minimal:
        code_t, name_t, phone_t = (
            ("كود العميل", "اسم العميل", "هاتف العميل") if kind == "customer" else ("كود المورد", "اسم المورد", "هاتف المورد")
        )
        headers = [code_t, name_t, phone_t, "الرصيد"]
        content = build_tables_xlsx(
            f"نموذج رفع أرصدة {_KIND_AR[kind]}",
            "«الكود» الفاضي يتولد تلقائيًا للطرف الجديد (ياخد CUS-…)، وكود موجود يطابق صاحبه — الهاتف والرصيد يُحدَّثان لمن سطر مطابق والعمود الفارغ يعني بدون تغيير",
            [(_KIND_AR[kind], headers, [[("text", ""), ("text", ""), ("text", ""), ("text", "")]])],
        )
        filename = f'{c["file"]}-balance-template.xlsx'
        required = [name_t]
    else:
        content = build_tables_xlsx(
            f"نموذج استيراد {_KIND_AR[kind]}",
            "املأ الصفوف تحت العناوين ثم استوردها — غيّر الأسماء أو احذف صفوف الأمثلة",
            [(_KIND_AR[kind], _headers_for(kind), [
                [("text", "")] * 1 + [
                    ("text", "مثال: محمد أحمد — احذف هذا الصف قبل الاستيراد"),
                    ("text", ""), ("text", "01000000000"), ("text", ""), ("text", ""),
                    ("money", 0), ("text", "نعم"),
                ],
            ])],
        )
        filename = f'{c["file"]}-import-template.xlsx'
        required = ["الاسم"]
    content = _decorate_template_xlsx(content, required_titles=required)
    return _xlsx_response(content, filename)


# --------------------------------------------------------------------------- parties: import
def _plan_parties(kind: str, db: Session, file, url: Optional[str], preview: bool, user: models.User):
    """Parse rows into a plan; in preview mode nothing is written."""
    c = _cfg(kind)
    model = c["model"]
    company_id = db.info["company_id"]
    headers, data = _read_table(file, url, csv_preferred=url is not None)
    col = _col_lookup(headers)
    name_i, code_i = col("الاسم", "اسم العميل", "اسم المورد", "Name"), col("كود", "Code")
    if name_i is None:
        raise HTTPException(422, "لم نجد عمود الاسم في الملف")
    contact_i, phone_i = col("جهة الاتصال"), col("هاتف", "موبايل", "Phone")
    email_i, address_i = col("البريد", "Email"), col("العنوان", "Address")
    opening_i, active_i = col("الرصيد"), col("نشط", "Active")

    skips = _skip_counts()
    errors: List[Dict[str, Any]] = []
    plan: List[Dict[str, Any]] = []
    total_rows = 0

    for row_num, row in enumerate(data, start=2):
        name = _value(row, name_i)
        if not name:
            _mark_skip(skips, "empty_rows")
            continue
        if name in _TOTAL_ROW or "احذف هذا الصف" in name:
            _mark_skip(skips, "totals_rows")
            continue
        total_rows += 1
        opening_raw = _value(row, opening_i)
        opening = None
        if opening_raw is not None:
            try:
                opening = Decimal(opening_raw.replace(",", ""))
            except (InvalidOperation, ValueError):
                errors.append({"row": row_num, "party": name, "error": f"رصيد افتتاحي غير صالح «{opening_raw}»"})
                continue
            if opening < 0:
                errors.append({"row": row_num, "party": name, "error": f"رصيد افتتاحي سالب مرفوض «{opening_raw}» — لا تُسمح بالقيم السالبة"})
                continue
        code = _value(row, code_i)
        party = None
        if code:
            # first try an exact code match (works for customers as well as suppliers)…
            party = db.query(model).filter(model.company_id == company_id, model.code == code).one_or_none()
            if party is None and kind == "customer" and code.isdigit():
                # …else a numeric customer code may still be the row id inside the system
                maybe = db.get(models.Customer, int(code))
                if maybe is not None and maybe.company_id == company_id:
                    party = maybe
        if party is None:
            party = db.query(model).filter(model.company_id == company_id, model.name.ilike(name)).one_or_none()
        entry = {
            "row": row_num, "name": name, "code": code, "opening": opening,
            "active": _value(row, active_i),
            "fields": {f: _value(row, i) for f, i in (("contact_person", contact_i), ("phone", phone_i), ("email", email_i), ("address", address_i)) if _value(row, i) is not None},
            "matched": party.id if party is not None else None,  # type: ignore
            "matched_name": party.name if party is not None else None,  # type: ignore
        }
        if party is not None and kind == "supplier" and code and party.code != code:  # type: ignore
            entry["error"] = f"الكود {code} يخص «{party.name}» وليس «{name}»"  # type: ignore
            errors.append({"row": row_num, "party": name, "error": entry["error"]})
        if opening is not None and opening != 0 and not _is_manager(user):
            errors.append({"row": row_num, "party": name, "error": "تغيير الرصيد الافتتاحي للمدير/الإدارة فقط"})
        plan.append(entry)

    created = sum(1 for p in plan if p.get("matched") is None and "error" not in p)
    updated = sum(1 for p in plan if p.get("matched") is not None and "error" not in p)
    if preview:
        sample = [
            {
                "row": p["row"], "code": p["code"] or "", "name": p["name"],
                "opening": str(p["opening"]) if p["opening"] is not None else None,
                "result": f'يُنشأ جديد' if p.get("matched") is None else f'يُحدَّث «{p["matched_name"]}»',
            }
            for p in plan if "error" not in p
        ][:10]
        return {"preview": True, "rows": total_rows, "created": created, "updated": updated,
                "skipped": skips, "errors": errors, "sample": sample}

    # apply — every blocked row continues via errors; hard-403 only when nothing can proceed
    created = updated = 0
    from sqlalchemy.exc import IntegrityError

    for p in plan:
        if "error" in p:
            continue
        row = p["row"]
        if p.get("matched") is None:
            if not _is_manager(user):
                raise HTTPException(403, f"الصف {row}: فقط المدير أو الإدارة يمكنهم إضافة طراف جديدة")
            data_in: Dict[str, Any] = {"name": p["name"]}
            # code passed in the file is kept as-is; an empty cell gets an auto-generated one
            data_in["code"] = p["code"] or unique_code(db, model, company_id, p["name"], "CUS" if kind == "customer" else "SUP", max_length=50)
            party = model(company_id=company_id, **data_in)  # type: ignore[call-arg]
            acc_code = "2100" if kind == "supplier" else "1100"
            acc = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == acc_code).first()
            if acc is not None:
                party.chart_account_id = acc.id
            if p["opening"] is not None:
                party.opening_balance = p["opening"]
            if p["active"] is not None:
                party.is_active = p["active"] in _YES
            if kind == "customer":
                for f, v in p["fields"].items():
                    if v is not None:
                        setattr(party, f, v)
            elif kind == "supplier":
                for f, v in p["fields"].items():
                    if v is not None:
                        setattr(party, f, v)
            db.add(party)
            db.flush()
            created += 1
            audit(db, user, "import", c["entity"], party, f"import: new {c['entity']} code «{party.code}» · «{p['name']}» · opening {party.opening_balance}")
        else:
            party = db.get(model, p["matched"])
            updated += 1
            before_opening = Decimal(str(party.opening_balance or 0))
            for f, v in p["fields"].items():
                setattr(party, f, v)
            if p["active"] is not None:
                party.is_active = p["active"] in _YES
            if p["opening"] is not None and p["opening"] != before_opening:
                if not _is_manager(user):
                    raise HTTPException(403, f"الصف {row}: فقط المدير أو الإدارة يمكنهم تغيير الرصيد الافتتاحي")
                audit(db, user, "opening_balance", c["entity"], party, f"{before_opening} → {p['opening']}")
                party.opening_balance = p["opening"]
            audit(db, user, "import", c["entity"], party, f"import: updated {c['entity']} «{p['name']}»")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "بيانات مكررة (اسم أو كود يظهر مرتين في الملف)")
    return {"created": created, "updated": updated, "skipped": skips, "errors": errors}


@router.post("/parties/import/xlsx")
async def import_parties_xlsx(kind: str, preview: Optional[bool] = None, url: Optional[str] = None,
                              file: Optional[UploadFile] = File(None), db: Session = Depends(get_db),
                              user: models.User = Depends(get_current_user)):
    return _plan_parties(kind, db, file, url, bool(preview), user)


# --------------------------------------------------------------------------- warehouses: export/template
def _warehouse_stock(db: Session) -> Dict[int, Tuple[int, int, Decimal]]:
    """warehouse_id -> (items_count, total_qty, cost_value) for that warehouse's stock."""
    q = (
        db.query(models.ProductStock.warehouse_id, models.ProductStock.quantity, models.Product.cost_price)
        .join(models.Product, models.Product.id == models.ProductStock.product_id)
        .filter(models.ProductStock.quantity != 0)
        .all()
    )
    out: Dict[int, Tuple[int, int, Decimal]] = {}
    for wh_id, qty, cost in q:
        items, total, value = out.get(wh_id, (0, 0, Decimal("0")))
        out[wh_id] = (items + 1, total + (qty or 0), value + Decimal(str(cost or 0)) * (qty or 0))
    return out


_W_HEADERS = ["الكود", "الاسم", "الفرع", "الموقع", "عدد الأصناف", "إجمالي الكميات", "قيمة المخزون", "نشط"]


@router.get("/warehouses/export/xlsx")
def export_warehouses_xlsx(db: Session = Depends(get_db)):
    company_id = db.info["company_id"]
    warehouses = db.query(models.Warehouse).order_by(models.Warehouse.id).all()
    branch_names = {b.id: b.name for b in db.query(models.Branch).filter(models.Branch.company_id == company_id).all()}
    stock_map = _warehouse_stock(db)
    rows, total_qty, total_value = [], 0, Decimal("0")
    for w in warehouses:
        items_n, qty, value = stock_map.get(w.id, (0, 0, Decimal("0")))
        total_qty += qty
        total_value += value
        rows.append([
            ("text", w.code or ""), ("text", w.name), ("text", branch_names.get(w.branch_id, "")),
            ("text", w.location or ""), ("int", items_n), ("int", qty), ("money", value),
            ("text", "نعم" if w.is_active else "لا"),
        ])
    rows.append([("text", "الإجمالي"), ("text", ""), ("text", ""), ("text", ""), ("int", 0), ("int", total_qty), ("money", total_value), ("text", "")])
    content = build_tables_xlsx(
        "قائمة المخازن وأرصدتها",
        "رصيد المخزن = عدد الأصناف وإجمالي الكميات وقيمة المخزون بسعر التكلفة",
        [("المخازن", _W_HEADERS, rows)],
    )
    return _xlsx_response(content, "warehouses.xlsx")


@router.get("/warehouses/template/xlsx")
def warehouse_template_xlsx():
    content = build_tables_xlsx(
        "نموذج استيراد المخازن",
        "املأ الكود/الاسم/الفرع/الموقع/نشط — عمودا الكميات والقيمة للقراءة فقط لا يُؤخذان من الملف",
        [("المخازن", _W_HEADERS, [[
            ("text", ""), ("text", "مثال: مخزن المحطة — احذف هذا الصف قبل الاستيراد"),
            ("text", "الفرع الرئيسي"), ("text", ""), ("int", 0), ("int", 0), ("money", 0), ("text", "نعم"),
        ]])],
    )
    content = _decorate_template_xlsx(content, required_titles=["الاسم"])
    return _xlsx_response(content, "warehouses-import-template.xlsx")


# --------------------------------------------------------------------------- warehouses: import
def _import_warehouses(file, url: Optional[str], db: Session, user: models.User, preview: bool):
    from .masterdata import _default_branch_id

    company_id = db.info["company_id"]
    headers, data = _read_table(file, url, csv_preferred=url is not None)
    col = _col_lookup(headers)
    name_i, code_i = col("الاسم", "Name"), col("الكود", "Code")
    if name_i is None:
        raise HTTPException(422, "العمود «الاسم» غير موجود في الملف")
    branch_i, location_i, active_i = col("الفرع"), col("الموقع"), col("نشط", "Active")
    branches = {b.name.strip(): b for b in db.query(models.Branch).filter(models.Branch.company_id == company_id, models.Branch.is_active.is_(True)).all()}
    by_code = {w.code: w for w in db.query(models.Warehouse).filter(models.Warehouse.company_id == company_id).all()}
    by_name = {w.name.strip(): w for w in by_code.values()}

    skips = _skip_counts()
    errors: List[Dict[str, Any]] = []
    plan: List[Dict[str, Any]] = []
    company = db.get(models.Company, company_id)
    for row_num, row in enumerate(data, start=2):
        name = _value(row, name_i)
        if not name:
            _mark_skip(skips, "empty_rows")
            continue
        if name in _TOTAL_ROW or "احذف هذا الصف" in name:
            _mark_skip(skips, "totals_rows")
            continue
        code = _value(row, code_i)
        w = by_code.get(code) if code else None
        if w is None:
            w = by_name.get(name)
        entry = {
            "row": row_num, "name": name, "code": code,
            "location": _value(row, location_i), "active": _value(row, active_i),
            "matched": w.id if w is not None else None, "matched_name": w.name if w is not None else None,
            "branch": None if w is not None else (_value(row, branch_i) or None),
        }
        if code and w is not None and w.code != code:
            entry["error"] = f"الكود {code} يخص «{w.name}» وليس «{name}»"
            errors.append({"row": row_num, "warehouse": name, "error": entry["error"]})
        if w is None:
            if not _is_manager(user):
                errors.append({"row": row_num, "warehouse": name, "error": "إضافة مخازن جديدة للمدير/الإدارة فقط"})
        plan.append(entry)

    creates = sum(1 for p in plan if p.get("matched") is None and "error" not in p)
    updates = sum(1 for p in plan if p.get("matched") is not None and "error" not in p)
    if preview:
        sample = [
            {"row": p["row"], "code": p["code"] or "", "name": p["name"],
             "result": "يُنشأ جديد" if p.get("matched") is None else f'يُحدَّث «{p["matched_name"]}»'}
            for p in plan if "error" not in p
        ][:10]
        return {"preview": True, "rows": len(plan), "created": creates, "updated": updates, "skipped": skips, "errors": errors, "sample": sample}

    created = updated = 0
    for p in plan:
        if "error" in p:
            continue
        row = p["row"]
        w = db.get(models.Warehouse, p["matched"]) if p.get("matched") is not None else None
        if w is None:
            if not _is_manager(user):
                raise HTTPException(403, f"الصف {row}: فقط المدير أو الإدارة يمكنهم إضافة مخزن جديد")
            branch = branches.get((p["branch"] or "").strip()) if p["branch"] else None
            branch_id = branch.id if branch is not None else _default_branch_id(db)
            if company is not None and company.max_warehouses_per_branch is not None:  # type: ignore
                count = db.query(models.Warehouse).filter(models.Warehouse.branch_id == branch_id).count()
                if count >= company.max_warehouses_per_branch:  # type: ignore
                    errors.append({"row": row, "warehouse": p["name"], "error": "وصلت لحد المخازن المسموح للفرع"})
                    continue
            w = models.Warehouse(
                company_id=company_id, name=p["name"],
                code=p["code"] or unique_code(db, models.Warehouse, company_id, p["name"], "WH", max_length=50),
                branch_id=branch_id,
            )
            db.add(w)
            db.flush()
            created += 1
            audit(db, user, "import", "warehouse", w, f"import: new warehouse «{p['name']}»")
        else:
            updated += 1
        if p["location"] is not None:
            w.location = p["location"]
        if p["active"] is not None:
            w.is_active = p["active"] in _YES
        if p.get("matched") is not None:
            audit(db, user, "import", "warehouse", w, f"import: updated warehouse «{p['name']}»")
    db.commit()
    return {"created": created, "updated": updated, "skipped": skips, "errors": errors}


@router.post("/warehouses/import/xlsx")
async def import_warehouses_xlsx(preview: Optional[bool] = None, url: Optional[str] = None,
                                 file: Optional[UploadFile] = File(None), db: Session = Depends(get_db),
                                 user: models.User = Depends(get_current_user)):
    return _import_warehouses(file, url, db, user, bool(preview))


# --------------------------------------------------------------------------- one warehouse's stock balance
def _warehouse_for_import(db: Session, warehouse_id: int) -> models.Warehouse:
    w = db.get(models.Warehouse, warehouse_id)
    if w is None or w.company_id != db.info["company_id"]:
        raise HTTPException(404, f"Warehouse {warehouse_id} not found")
    return w


_S_HEADERS = ["الكود (SKU)", "المنتج", "الوحدة", "الكمية الحالية بالمخزن", "الكمية الجديدة"]


@router.get("/warehouses/stock/xlsx")
def export_warehouse_stock_xlsx(warehouse_id: int, db: Session = Depends(get_db)):
    """Pre-filled file for one warehouse: current stock + an empty 'new quantity' column."""
    w = _warehouse_for_import(db, warehouse_id)
    products = db.query(models.Product).filter(models.Product.is_active.is_(True)).order_by(models.Product.id).all()
    rows, total_current = [], 0
    for p in products:
        current = stock.available(db, p.id, w.id)
        total_current += current
        rows.append([("text", p.sku), ("text", p.name), ("text", p.unit), ("int", current), ("text", "")])
    rows.append([("text", "الإجمالي"), ("text", ""), ("text", ""), ("int", total_current), ("text", "")])
    content = build_tables_xlsx(
        f"رصيد المخزن — {w.name}",
        "املأ عمود «الكمية الجديدة» للأصناف التي تريد تعديل رصيدها فقط ثم ارفع الملف — العمود الفارغ يعني بدون تغيير",
        [(f"مخزن: {w.name}", _S_HEADERS, rows)],
    )
    content = _decorate_template_xlsx(content, required_titles=["الكود (SKU)", "المنتج"], yes_no_title="— غير موجود —")
    return _xlsx_response(content, f"stock-{w.code or w.id}.xlsx")


def _parse_new_qty(row_num: int, new_raw: Optional[str]) -> Optional[int]:
    if new_raw is None:
        return None
    try:
        val = int(Decimal(str(new_raw).replace(",", "")))
    except (InvalidOperation, ValueError):
        raise ValueError(f"الصف {row_num}: كمية غير صالحة «{new_raw}»")
    if val < 0:
        raise ValueError(f"الصف {row_num}: كمية سالبة")
    return val


def _import_warehouse_stock(warehouse_id: int, file, url: Optional[str], db: Session, user: models.User, preview: bool):
    from .orders import _locked_product

    w = _warehouse_for_import(db, warehouse_id)
    if not _is_manager(user):
        raise HTTPException(403, "فقط المدير أو الإدارة يمكنهم تعديل أرصدة المخزون")
    headers, data = _read_table(file, url, csv_preferred=url is not None)
    col = _col_lookup(headers)
    sku_i, name_i = col("SKU", "الكود", "Code"), col("المنتج", "الاسم", "Name")
    new_i = col("الكمية الجديدة")
    if new_i is None:
        raise HTTPException(422, "الملف يجب أن يحتوي عمود «الكمية الجديدة»")
    if sku_i is None and name_i is None:
        raise HTTPException(422, "الملف يجب أن يحتوي عمود «الكود (SKU)» أو «المنتج»")
    company_id = db.info["company_id"]
    products = {p.sku: p for p in db.query(models.Product).filter(models.Product.company_id == company_id).all()}
    by_name = {p.name: p for p in products.values()}

    skips = _skip_counts()
    errors: List[Dict[str, Any]] = []
    plan: List[Dict[str, Any]] = []
    for row_num, row in enumerate(data, start=2):
        new_raw = _value(row, new_i)
        label = _value(row, sku_i) or _value(row, name_i) or ""
        if new_raw is None or label in _TOTAL_ROW:
            _mark_skip(skips, "totals_rows" if label in _TOTAL_ROW else "no_new_value")
            continue
        sku, name = _value(row, sku_i), _value(row, name_i)
        product = products.get(sku) if sku else None
        if product is None:
            product = by_name.get(name) if name else None
        if product is None:
            errors.append({"row": row_num, "product": label, "error": "منتج غير موجود في النظام"})
            continue
        try:
            new_qty = _parse_new_qty(row_num, new_raw)
        except ValueError as exc:
            errors.append({"row": row_num, "product": product.name, "error": str(exc)})
            continue
        current = stock.available(db, product.id, w.id)
        delta = new_qty - current
        if delta == 0:
            _mark_skip(skips, "no_change")
            continue
        if delta < 0:
            errors.append({"row": row_num, "product": product.name, "error": f"الكمية المطلوبة ({new_qty}) أقل من الرصيد الحالي ({current})؛ الأنظمة لا تحذف مخزونًا تلقائيًا — استخدم الجرد للتسويات الناقصة"})
            continue
        plan.append({"row": row_num, "product_id": product.id, "product": product.name, "new": new_qty, "delta": delta, "current": current})

    if preview:
        sample = [{"row": p["row"], "product": p["product"], "current": p["current"], "new": p["new"], "delta": p["delta"]} for p in plan][:10]
        return {"preview": True, "changes": len(plan), "changed_qty": sum(p["delta"] for p in plan), "skipped": skips, "errors": errors, "sample": sample}

    applied = 0
    batch = f"stock-import:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    for p in plan:
        product = _locked_product(db, p["product_id"])
        stock.move_stock(db, product, w.id, p["delta"], "stock_import", batch)
        applied += 1
        audit(db, user, "stock_import", "warehouse", w, f"stock import «{p['product']}» في «{w.name}»: {p['current']} → {p['new']}")
    db.commit()
    return {"warehouse_id": w.id, "batch": batch, "applied": applied, "changed_qty": sum(p["delta"] for p in plan), "skipped": skips, "errors": errors}


@router.post("/warehouses/stock/xlsx")
async def import_warehouse_stock_xlsx(warehouse_id: int, preview: Optional[bool] = None, url: Optional[str] = None,
                                      file: Optional[UploadFile] = File(None), db: Session = Depends(get_db),
                                      user: models.User = Depends(get_current_user)):
    return _import_warehouse_stock(warehouse_id, file, url, db, user, bool(preview))


@router.post("/warehouses/stock/undo")
def undo_warehouse_stock_xlsx(warehouse_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Revert the LAST stock_import batch on this warehouse, movement by movement."""
    from .orders import _locked_product

    w = _warehouse_for_import(db, warehouse_id)
    if not _is_manager(user):
        raise HTTPException(403, "فقط المدير أو الإدارة يمكنهم التراجع عن عمليات الرفع")
    movements = (
        db.query(models.StockMovement)
        .filter(models.StockMovement.warehouse_id == warehouse_id, models.StockMovement.reason == "stock_import")
        .order_by(models.StockMovement.id.desc())
        .limit(500)
        .all()
    )
    if not movements:
        raise HTTPException(404, "لا توجد عمليات رفع مخزون لهذا المخزن")
    batch_ref = movements[0].reference  # latest batch
    batch = [m for m in movements if m.reference == batch_ref]
    if not batch:
        raise HTTPException(404, "لا يوجد رفع قابل للتراجع")
    # Reversal must be valid for every product: check availability first, then apply.
    per_pid: Dict[int, int] = {}
    for m in batch:
        per_pid[m.product_id] = per_pid.get(m.product_id, 0) + (-m.change)
    for pid, change in per_pid.items():
        if change < 0 and stock.available(db, pid, warehouse_id) + change < 0:
            raise HTTPException(
                409, "لا يمكن التراجع: رصيد بعض الأصناف تغيّر بعد هذا الرفع بحركات أخرى ولا تكفي الكمية للإرجاع"
            )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    applied = 0
    for pid in sorted(per_pid):
        product = _locked_product(db, pid)
        change = per_pid[pid]
        stock.move_stock(db, product, warehouse_id, change, "stock_import_undo", f"stock-undo:{ts}:{batch_ref}")
        applied += 1
        audit(db, user, "stock_import_undo", "warehouse", w, f"stock undo «{product.name}» في «{w.name}»: {change:+d} (تراجع عن {batch_ref})")
    db.commit()
    return {"warehouse_id": warehouse_id, "undone_batch": batch_ref, "products": applied, "changed_qty": sum(per_pid.values())}


# --------------------------------------------------------------------------- stock matrix (all warehouses)
@router.get("/stock-matrix/xlsx")
def export_stock_matrix_xlsx(db: Session = Depends(get_db)):
    company_id = db.info["company_id"]
    warehouses = db.query(models.Warehouse).order_by(models.Warehouse.id).all()
    products = db.query(models.Product).filter(models.Product.is_active.is_(True)).order_by(models.Product.id).all()
    stocks = {
        (ps.product_id, ps.warehouse_id): ps.quantity
        for ps in db.query(models.ProductStock).all()
    }
    headers = ["الكود (SKU)", "المنتج", "الوحدة"]
    warehouse_names: List[str] = []
    for w in warehouses:
        warehouse_names.append(w.name if w.name not in warehouse_names else f"{w.name} ({w.code})")
        headers += [f"{warehouse_names[-1]} — حالي", f"{warehouse_names[-1]} — جديد"]
    rows = []
    totals = [0] * len(warehouse_names)
    for p in products:
        row: list = [("text", p.sku), ("text", p.name), ("text", p.unit)]
        for gi, w in enumerate(warehouses):
            qty = stocks.get((p.id, w.id), 0)
            row += [("int", qty), ("text", "")]
            totals[gi] += qty
        rows.append(row)
    totals_row: list = [("text", "الإجمالي"), ("text", ""), ("text", "")]
    for gi in range(len(warehouse_names)):
        totals_row += [("int", totals[gi]), ("text", "")]
    rows.append(totals_row)
    content = build_tables_xlsx(
        "أرصدة المنتجات في كل المخازن",
        "كل مخزن له عمودان: «حالي» (للقراءة) و«جديد» — املأ فقط ما تريد تعديله وارفع الملف",
        [("المخازن × المنتجات", headers, rows)],
    )
    return _xlsx_response(content, "stock-matrix.xlsx")


def _import_stock_matrix(file, url: Optional[str], db: Session, user: models.User, preview: bool):
    from .orders import _locked_product

    if not _is_manager(user):
        raise HTTPException(403, "فقط المدير أو الإدارة يمكنهم تعديل أرصدة المخزون")
    company_id = db.info["company_id"]
    headers, data = _read_table(file, url, csv_preferred=url is not None)
    col = _col_lookup(headers)
    sku_i, name_i = col("SKU", "الكود", "Code"), col("المنتج", "الاسم", "Name")
    if sku_i is None and name_i is None:
        raise HTTPException(422, "الملف يجب أن يحتوي عمود «الكود (SKU)» أو «المنتج»")
    products_by_sku = {p.sku: p for p in db.query(models.Product).filter(models.Product.company_id == company_id).all()}
    products_by_name = {p.name: p for p in products_by_sku.values()}
    warehouses_by_name = {w.name.strip(): w for w in db.query(models.Warehouse).filter(models.Warehouse.company_id == company_id).all()}

    # map each «… — جديد» column to a warehouse
    new_cols: List[Tuple[int, models.Warehouse]] = []
    for h, i in sorted(((h, i) for i, h in enumerate(headers)), key=lambda x: x[1]):
        if "— جديد" in h:
            wname = h.split("—")[0].strip()
            w = warehouses_by_name.get(wname)
            if w is None:
                raise HTTPException(422, f"العمود «{h}» لا يطابق أي مخزن موجود (الاسم: «{wname}»)")
            new_cols.append((i, w))
    if not new_cols:
        raise HTTPException(422, "لا يوجد أي عمود جديد في الملف (المفروض: «اسم المخزن — جديد»)")

    skips = _skip_counts()
    errors: List[Dict[str, Any]] = []
    plan: List[Dict[str, Any]] = []
    products_in_plan: Dict[int, Dict[int, int]] = {}
    product_names: Dict[int, str] = {}

    for row_num, row in enumerate(data, start=2):
        sku, name = _value(row, sku_i), _value(row, name_i)
        if not sku and not name:
            _mark_skip(skips, "empty_rows")
            continue
        label = sku or name or ""
        if label in _TOTAL_ROW:
            _mark_skip(skips, "totals_rows")
            continue
        product = products_by_sku.get(sku) if sku else None
        if product is None:
            product = products_by_name.get(name) if name else None
        if product is None:
            errors.append({"row": row_num, "product": label, "error": "منتج غير موجود في النظام"})
            continue
        requested: Dict[int, int] = {}
        for ci, w in new_cols:
            raw = _value(row, ci)
            if raw is None:
                continue
            try:
                new_qty = _parse_new_qty(row_num, raw)
            except ValueError as exc:
                errors.append({"row": row_num, "product": product.name, "error": str(exc)})
                requested = {}
                break
            current = stock.available(db, product.id, w.id)
            if new_qty == current:
                _mark_skip(skips, "no_change")
                continue
            if new_qty < current:
                errors.append({"row": row_num, "product": product.name, "error": f"«{w.name}»: الكمية الجديدة ({new_qty}) أقل من الحالية ({current}) — لا حذف تلقائي؛ استخدم الجرد"})
                requested = {}
                break
            requested[w.id] = new_qty
        if requested:
            products_in_plan.setdefault(product.id, {}).update(requested)
            product_names[product.id] = product.name
            for wid, new_qty in requested.items():
                wh = next(w for w in new_cols if w[1].id == wid)[1]
                plan.append({"row": row_num, "product_id": product.id, "product": product.name,
                             "warehouse": wh.name, "new": new_qty})

    if preview:
        changes = [
            {"row": p["row"], "product": p["product"], "warehouse": p["warehouse"], "new": p["new"]}
            for p in plan
        ]
        sample = changes[:10]
        return {"preview": True, "changes": len(changes), "products": len(products_in_plan), "skipped": skips, "errors": errors, "sample": sample}

    batch = f"stock-import:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    applied_products = 0
    movements = 0
    for pid, per_wh in products_in_plan.items():
        product = _locked_product(db, pid)
        product_changed = False
        for wid, new_qty in per_wh.items():
            wh = db.get(models.Warehouse, wid)
            delta = new_qty - stock.available(db, pid, wid)
            if delta == 0:
                continue
            stock.move_stock(db, product, wid, delta, "stock_import", batch)
            movements += 1
            product_changed = True
        if product_changed:
            audit(db, user, "stock_import", "product", product, f"matrix import «{product.name}»: رفع أرصدة لكل المخازن ({batch})")
            applied_products += 1
    db.commit()
    return {"batch": batch, "applied_products": applied_products, "movements": movements, "skipped": skips, "errors": errors}


@router.post("/stock-matrix/xlsx")
async def import_stock_matrix_xlsx(preview: Optional[bool] = None, url: Optional[str] = None,
                                   file: Optional[UploadFile] = File(None), db: Session = Depends(get_db),
                                   user: models.User = Depends(get_current_user)):
    return _import_stock_matrix(file, url, db, user, bool(preview))


# --------------------------------------------------------------------------- import history
@router.get("/history")
def import_history(limit: int = 30, db: Session = Depends(get_db)):
    """The recent import activity for this company (from the audit log, insert-only)."""
    rows = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.action.in_(["import", "stock_import", "stock_import_undo"]))
        .order_by(models.AuditLog.id.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return {
        "items": [
            {
                "id": a.id,
                "at": a.created_at.isoformat() if a.created_at else None,
                "user": a.username,
                "action": a.action,
                "entity": a.entity,
                "entity_id": a.entity_id,
                "summary": a.summary,
            }
            for a in rows
        ],
        "count": len(rows),
    }
