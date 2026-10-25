"""PDF and Excel export of invoices, purchase orders and report tables.

The builders are independent from the database: they take plain dictionaries so they can be
tested on their own.

Arabic in PDFs: reportlab does no text shaping, so Arabic strings are shaped with
arabic-reshaper and reordered with python-bidi, and drawn with the bundled Amiri font
(SIL Open Font License, see assets/fonts/OFL.txt).

Settings (environment variables, all optional):
  COMPANY_NAME      printed in the header of every document      (default "AI ERP System")
  COMPANY_PHONE     printed under the company name
  COMPANY_ADDRESS   printed under the company name
  CURRENCY_LABEL    appended to money amounts                    (default "ج.م")
  EXPORT_TIMEZONE   timezone for printed dates                   (default "Africa/Cairo")
"""

import io
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import arabic_reshaper
from bidi.algorithm import get_display
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_DIR = Path(__file__).parent / "assets" / "fonts"

COMPANY_NAME = os.getenv("COMPANY_NAME", "AI ERP System")
COMPANY_PHONE = os.getenv("COMPANY_PHONE", "")
COMPANY_ADDRESS = os.getenv("COMPANY_ADDRESS", "")
CURRENCY = os.getenv("CURRENCY_LABEL", "ج.م")

try:
    LOCAL_TZ = ZoneInfo(os.getenv("EXPORT_TIMEZONE", "Africa/Cairo"))
except Exception:  # unknown zone name or missing tzdata: fall back to UTC rather than failing exports
    LOCAL_TZ = timezone.utc

STATUS_LABEL = {"draft": "مسودة", "received": "تم الاستلام", "confirmed": "مؤكد", "cancelled": "ملغي"}
KIND_TITLE = {"sales": "فاتورة بيع", "purchase": "أمر شراء"}

PDF_MIME = "application/pdf"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ----------------------------------------------------------------------------- helpers
def fmt_money(value: Any) -> str:
    return f"{Decimal(str(value or 0)):,.2f}"


def fmt_int(value: Any) -> str:
    return f"{int(value or 0):,}"


def fmt_dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


_ARABIC = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_RESHAPER = arabic_reshaper.ArabicReshaper()


def visual(text: str) -> str:
    """Logical-order string -> string ready to draw left-to-right (shaped + bidi-reordered).

    Text without Arabic is returned unchanged: running it through the bidi algorithm with an
    RTL base would reorder things like "SO-12".
    """
    if not _ARABIC.search(text):
        return text
    return get_display(_RESHAPER.reshape(text), base_dir="R")


_fonts_ready = False


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(TTFont("Amiri", str(FONT_DIR / "Amiri-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Amiri-Bold", str(FONT_DIR / "Amiri-Bold.ttf")))
    _fonts_ready = True


# ----------------------------------------------------------------------------- PDF
PAGE_W, PAGE_H = A4
MARGIN = 40
RIGHT = PAGE_W - MARGIN
LEFT = MARGIN
CONTENT_W = PAGE_W - 2 * MARGIN
BOTTOM = 70  # keep the footer clear
INK = colors.HexColor("#1b2430")
MUTED = colors.HexColor("#6b778a")
RULE = colors.HexColor("#d5dbe3")
HEAD_BG = colors.HexColor("#eef2f7")
ACCENT = colors.HexColor("#1f6feb")


class _Pdf:
    def __init__(self, title: str):
        _register_fonts()
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.c.setTitle(title)
        self.c.setAuthor(COMPANY_NAME)
        self.page = 1
        self.y = PAGE_H - MARGIN

    # -- text primitives
    def width(self, text: str, font: str, size: float) -> float:
        return pdfmetrics.stringWidth(visual(text), font, size)

    def text(self, x: float, y: float, text: str, font="Amiri", size=11, align="r", color=INK) -> None:
        self.c.setFont(font, size)
        self.c.setFillColor(color)
        shown = visual(text)
        if align == "r":
            self.c.drawRightString(x, y, shown)
        elif align == "c":
            self.c.drawCentredString(x, y, shown)
        else:
            self.c.drawString(x, y, shown)

    def wrap(self, text: str, font: str, size: float, max_w: float) -> List[str]:
        """Greedy word wrap on logical text; each returned line is later shaped on its own."""
        lines: List[str] = []
        for para in (text or "").splitlines() or [""]:
            cur = ""
            for word in para.split():
                trial = f"{cur} {word}".strip()
                if cur and self.width(trial, font, size) > max_w:
                    lines.append(cur)
                    cur = word
                else:
                    cur = trial
                # a single word wider than the column: hard-split it
                while self.width(cur, font, size) > max_w and len(cur) > 1:
                    cut = len(cur)
                    while cut > 1 and self.width(cur[:cut], font, size) > max_w:
                        cut -= 1
                    lines.append(cur[:cut])
                    cur = cur[cut:]
            lines.append(cur)
        return lines

    def rule(self, y: float, color=RULE, width=0.7) -> None:
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width)
        self.c.line(LEFT, y, RIGHT, y)

    # -- page handling
    def footer(self) -> None:
        self.rule(BOTTOM - 14)
        self.text(RIGHT, BOTTOM - 30, f"صفحة {self.page}", size=9, color=MUTED)
        # The date is drawn separately: inside an Arabic string the bidi algorithm would reorder
        # its digit groups ("09:15 23-10-2026").
        stamp = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
        self.text(LEFT, BOTTOM - 30, stamp, size=9, color=MUTED, align="l")
        label = "طُبع في"
        label_right = LEFT + pdfmetrics.stringWidth(stamp, "Amiri", 9) + 6 + self.width(label, "Amiri", 9)
        self.text(label_right, BOTTOM - 30, label, size=9, color=MUTED)

    def new_page(self) -> None:
        self.footer()
        self.c.showPage()
        self.page += 1
        self.y = PAGE_H - MARGIN

    def ensure(self, needed: float, on_new_page=None) -> None:
        if self.y - needed < BOTTOM:
            self.new_page()
            if on_new_page:
                on_new_page()

    def finish(self) -> bytes:
        self.footer()
        self.c.save()
        return self.buf.getvalue()


def build_shift_pdf(shift: Dict[str, Any]) -> bytes:
    """Shift closing report (A4): cash reconciliation plus signature lines."""
    pdf = _Pdf(f"تقرير وردية {shift['id']}")
    pdf.text(RIGHT, pdf.y - 16, COMPANY_NAME, font="Amiri-Bold", size=19)
    pdf.text(LEFT, pdf.y - 16, "تقرير إغلاق وردية", font="Amiri-Bold", size=19, align="l", color=ACCENT)
    pdf.text(LEFT, pdf.y - 36, f"# {shift['id']}", font="Amiri-Bold", size=13, align="l")
    pdf.y -= 52
    pdf.rule(pdf.y)
    pdf.y -= 24
    closed = shift["closed_at"] is not None
    rows = [
        ("الكاشير", shift["username"]),
        ("وقت الفتح", fmt_dt(shift["opened_at"])),
        ("وقت الإغلاق", fmt_dt(shift["closed_at"]) if closed else "الوردية ما زالت مفتوحة"),
    ]
    for label, value in rows:
        pdf.text(RIGHT, pdf.y, f"{label}:", font="Amiri-Bold", size=11.5, color=MUTED)
        pdf.text(RIGHT - 100, pdf.y, value, size=11.5)
        pdf.y -= 20
    pdf.y -= 8

    money_rows = [
        ("رصيد الافتتاح", shift["opening_cash"], False),
        ("+ نقدي مقبوض (عملاء ومرتجعات موردين)", shift["cash_in"], False),
        ("− نقدي مدفوع (موردين ومرتجعات عملاء)", shift["cash_out"], False),
        ("المتوقع في الدرج", shift["expected_cash"], True),
    ]
    if closed:
        money_rows += [("المعدود فعلياً", shift["counted_cash"], True)]
    for label, value, bold in money_rows:
        pdf.c.setFillColor(HEAD_BG if bold else colors.white)
        pdf.c.rect(LEFT, pdf.y - 7, CONTENT_W, 24, stroke=0, fill=1)
        pdf.text(RIGHT - 8, pdf.y, label, font="Amiri-Bold" if bold else "Amiri", size=12)
        pdf.text(LEFT + 8, pdf.y, f"{fmt_money(value)} {CURRENCY}", font="Amiri-Bold" if bold else "Amiri", size=12, align="l")
        pdf.y -= 26
    if closed:
        d = Decimal(str(shift["difference"] or 0))
        word = "مطابق" if d == 0 else ("زيادة" if d > 0 else "عجز")
        color = colors.HexColor("#1a7f37") if d == 0 else colors.HexColor("#b42318")
        pdf.text(RIGHT - 8, pdf.y - 4, "الفرق", font="Amiri-Bold", size=14, color=color)
        pdf.text(LEFT + 8, pdf.y - 4, word if d == 0 else f"{word} {fmt_money(abs(d))} {CURRENCY}", font="Amiri-Bold", size=14, align="l", color=color)
        pdf.y -= 34
    pdf.text(RIGHT - 8, pdf.y, f"مقبوضات غير نقدية (لا تدخل الدرج): {fmt_money(shift['other_methods_in'])} {CURRENCY}", size=10.5, color=MUTED)
    pdf.y -= 22
    if shift.get("notes"):
        pdf.text(RIGHT - 8, pdf.y, "ملاحظات:", font="Amiri-Bold", size=11, color=MUTED)
        pdf.y -= 16
        for ln in pdf.wrap(shift["notes"], "Amiri", 11, CONTENT_W - 16):
            pdf.text(RIGHT - 8, pdf.y, ln, size=11)
            pdf.y -= 15
    pdf.y -= 50
    for x, label in ((RIGHT, "توقيع الكاشير"), (LEFT + 190, "توقيع المراجع")):
        pdf.c.setStrokeColor(RULE)
        pdf.c.line(x - 170, pdf.y, x, pdf.y)
        pdf.text(x, pdf.y - 16, label, size=10.5, color=MUTED)
    return pdf.finish()


RECEIPT_W = 226.8  # 80 mm thermal paper


def build_receipt_pdf(doc: Dict[str, Any]) -> bytes:
    """Narrow receipt for 80 mm thermal printers. Page height grows with the content (one continuous strip)."""
    _register_fonts()
    inner = RECEIPT_W - 20

    def w(text, font, size):
        return pdfmetrics.stringWidth(visual(text), font, size)

    def wrap(text, font, size):
        lines, cur = [], ""
        for word in (text or "").split():
            trial = f"{cur} {word}".strip()
            if cur and w(trial, font, size) > inner:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        return lines + [cur]

    # Lay everything out first as (kind, payload) rows so the page height is known before drawing.
    rows: List[Tuple[str, Any]] = [("title", COMPANY_NAME)]
    for extra in (COMPANY_ADDRESS, COMPANY_PHONE):
        if extra:
            rows.append(("small", extra))
    rows += [("rule", None), ("kv", ("فاتورة", doc["number"])), ("kv", ("التاريخ", fmt_dt(doc["date"]))), ("kv", ("العميل", doc["party"]["name"])), ("rule", None)]
    for it in doc["items"]:
        for ln in wrap(it["name"], "Amiri-Bold", 10):
            rows.append(("name", ln))
        rows.append(("line", (f"{it['quantity']} × {fmt_money(it['price'])}", fmt_money(it["total"]))))
    rows += [("rule", None), ("total", ("الإجمالي", f"{fmt_money(doc['total'])} {CURRENCY}"))]
    if doc.get("paid") is not None:
        rows.append(("kv", ("المدفوع", f"{fmt_money(doc['paid'])} {CURRENCY}")))
        if Decimal(str(doc["remaining"] or 0)) > 0:
            rows.append(("kv", ("المتبقي", f"{fmt_money(doc['remaining'])} {CURRENCY}")))
    rows += [("rule", None), ("small", "شكراً لتعاملكم معنا")]

    heights = {"title": 24, "small": 14, "rule": 10, "kv": 15, "name": 14, "line": 15, "total": 22}
    page_h = 20 + sum(heights[k] for k, _ in rows)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(RECEIPT_W, page_h))
    c.setTitle(f"إيصال {doc['number']}")
    y = page_h - 10
    xr, xl = RECEIPT_W - 10, 10
    for kind, val in rows:
        y -= heights[kind]
        c.setFillColor(INK)
        if kind == "title":
            c.setFont("Amiri-Bold", 15); c.drawCentredString(RECEIPT_W / 2, y + 6, visual(val))
        elif kind == "small":
            c.setFont("Amiri", 9); c.setFillColor(MUTED); c.drawCentredString(RECEIPT_W / 2, y + 4, visual(val))
        elif kind == "rule":
            c.setStrokeColor(MUTED); c.setDash(2, 2); c.line(xl, y + 5, xr, y + 5); c.setDash()
        elif kind == "kv":
            c.setFont("Amiri", 10); c.drawRightString(xr, y + 3, visual(val[0] + ":")); c.drawString(xl, y + 3, visual(val[1]))
        elif kind == "name":
            c.setFont("Amiri-Bold", 10); c.drawRightString(xr, y + 3, visual(val))
        elif kind == "line":
            c.setFont("Amiri", 10); c.drawRightString(xr, y + 3, visual(val[0])); c.drawString(xl, y + 3, visual(val[1]))
        elif kind == "total":
            c.setFont("Amiri-Bold", 13); c.drawRightString(xr, y + 4, visual(val[0])); c.drawString(xl, y + 4, visual(val[1]))
    c.showPage()
    c.save()
    return buf.getvalue()


def build_document_pdf(doc: Dict[str, Any]) -> bytes:
    """Invoice (sales) or purchase order PDF. `doc` shape: see build_document_xlsx."""
    pdf = _Pdf(f"{KIND_TITLE[doc['kind']]} {doc['number']}")
    c = pdf.c

    # ---- header: company on the right, document title on the left
    pdf.text(RIGHT, pdf.y - 16, COMPANY_NAME, font="Amiri-Bold", size=19)
    sub_y = pdf.y - 34
    for line in (COMPANY_ADDRESS, COMPANY_PHONE):
        if line:
            pdf.text(RIGHT, sub_y, line, size=9.5, color=MUTED)
            sub_y -= 13
    pdf.text(LEFT, pdf.y - 16, KIND_TITLE[doc["kind"]], font="Amiri-Bold", size=19, align="l", color=ACCENT)
    pdf.text(LEFT, pdf.y - 36, f"# {doc['number']}", font="Amiri-Bold", size=13, align="l")
    pdf.y = min(sub_y, pdf.y - 44) - 6
    pdf.rule(pdf.y)
    pdf.y -= 22

    # ---- parties and meta
    party = doc["party"]
    top = pdf.y
    pdf.text(RIGHT, top, f"{doc['party_label']}:", font="Amiri-Bold", size=11, color=MUTED)
    # The party block must stay right of the meta block (which starts near x = LEFT + 215).
    party_w = 235
    name_lines = pdf.wrap(party["name"], "Amiri-Bold", 13, party_w)
    for i, ln in enumerate(name_lines):
        pdf.text(RIGHT - 52, top - i * 16, ln, font="Amiri-Bold", size=13)
    ry = top - 17 - (len(name_lines) - 1) * 16
    for label, value in (("الهاتف", party.get("phone")), ("البريد", party.get("email")), ("العنوان", party.get("address"))):
        if value:
            for i, ln in enumerate(pdf.wrap(value, "Amiri", 10.5, party_w)):
                if i == 0:
                    pdf.text(RIGHT, ry, f"{label}:", size=10.5, color=MUTED)
                pdf.text(RIGHT - 52, ry, ln, size=10.5)
                ry -= 14

    meta = [
        ("التاريخ", fmt_dt(doc["date"])),
        ("المخزن", doc.get("warehouse") or "—"),
        ("الحالة", STATUS_LABEL.get(doc["status"], doc["status"])),
    ]
    # meta block on the left: label right-aligned at META_X, value right-aligned just left of it
    meta_x, value_x = LEFT + 215, LEFT + 215 - 50
    ly = top
    for label, value in meta:
        pdf.text(meta_x, ly, f"{label}:", size=10.5, color=MUTED)
        for i, ln in enumerate(pdf.wrap(value, "Amiri", 10.5, value_x - LEFT)):
            pdf.text(value_x, ly, ln, size=10.5)
            ly -= 15
    pdf.y = min(ry, ly) - 10

    if doc["status"] in ("draft", "cancelled"):
        note = "مسودة — لم يتم التنفيذ بعد ولم يتأثر المخزون" if doc["status"] == "draft" else "هذا المستند ملغي"
        c.setFillColor(colors.HexColor("#fff4e5") if doc["status"] == "draft" else colors.HexColor("#eceff3"))
        c.roundRect(LEFT, pdf.y - 20, CONTENT_W, 24, 5, stroke=0, fill=1)
        pdf.text(PAGE_W / 2, pdf.y - 13, note, font="Amiri-Bold", size=11, align="c",
                 color=colors.HexColor("#9a5b00") if doc["status"] == "draft" else MUTED)
        pdf.y -= 34

    # ---- items table (columns listed in logical RTL order: first = rightmost)
    cols: List[Tuple[str, float, str]] = [
        ("#", 26, "c"),
        ("المنتج", 196, "r"),
        ("الكود", 76, "c"),
        ("الكمية", 56, "c"),
        (doc["price_label"], 79, "c"),
        ("الإجمالي", 82, "c"),
    ]
    assert abs(sum(w for _, w, _ in cols) - CONTENT_W) < 1, "column widths must fill the page"
    pad = 5

    def col_spans() -> List[Tuple[float, float]]:
        spans, x = [], RIGHT
        for _, w, _ in cols:
            spans.append((x - w, x))
            x -= w
        return spans

    def table_header() -> None:
        h = 24
        c.setFillColor(HEAD_BG)
        c.rect(LEFT, pdf.y - h, CONTENT_W, h, stroke=0, fill=1)
        for (name, _, _), (x0, x1) in zip(cols, col_spans()):
            pdf.text((x0 + x1) / 2, pdf.y - 16, name, font="Amiri-Bold", size=10.5, align="c", color=MUTED)
        pdf.y -= h

    table_header()
    font, size, lead = "Amiri", 10.5, 14
    for idx, it in enumerate(doc["items"], 1):
        name_w = cols[1][1] - 2 * pad
        name_lines = pdf.wrap(it["name"], font, size, name_w)
        row_h = max(26, len(name_lines) * lead + 10)
        pdf.ensure(row_h + 4, on_new_page=table_header)
        cells = [
            str(idx),
            None,  # product name drawn as wrapped lines
            it.get("sku") or "—",
            f"{fmt_int(it['quantity'])} {it.get('unit') or ''}".strip(),
            fmt_money(it["price"]),
            fmt_money(it["total"]),
        ]
        base = pdf.y - 17
        for ci, ((_, _, align), (x0, x1)) in enumerate(zip(cols, col_spans())):
            if ci == 1:
                for li, ln in enumerate(name_lines):
                    pdf.text(x1 - pad, base - li * lead, ln, size=size)
            elif align == "c":
                pdf.text((x0 + x1) / 2, base, cells[ci], size=size, align="c")
        pdf.y -= row_h
        pdf.rule(pdf.y)

    # ---- total
    pdf.ensure(70)
    pdf.y -= 8
    box_w = 230
    c.setFillColor(HEAD_BG)
    c.roundRect(LEFT, pdf.y - 30, box_w, 32, 5, stroke=0, fill=1)
    pdf.text(LEFT + box_w - 10, pdf.y - 20, "الإجمالي", font="Amiri-Bold", size=12.5)
    pdf.text(LEFT + 10, pdf.y - 20, f"{fmt_money(doc['total'])} {CURRENCY}", font="Amiri-Bold", size=13, align="l", color=ACCENT)
    pdf.y -= 46

    # ---- notes
    if doc.get("notes"):
        pdf.ensure(40)
        pdf.text(RIGHT, pdf.y, "ملاحظات:", font="Amiri-Bold", size=11, color=MUTED)
        pdf.y -= 16
        for ln in pdf.wrap(doc["notes"], "Amiri", 10.5, CONTENT_W):
            pdf.ensure(16)
            pdf.text(RIGHT, pdf.y, ln, size=10.5)
            pdf.y -= 14

    return pdf.finish()


# ----------------------------------------------------------------------------- Excel
_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
THIN = Side(style="thin", color="D5DBE3")
BORDER = Border(bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="EEF2F7")
MONEY_FMT = "#,##0.00"


def _text(ws, row: int, col: int, value: Any, bold=False, color: Optional[str] = None, size: Optional[int] = None):
    """Writes user-controlled text as a *string* cell.

    openpyxl turns any string starting with "=" into a formula; a product named "=HYPERLINK(...)"
    would then execute when the file is opened. Forcing the cell type to string prevents that.
    """
    cell = ws.cell(row=row, column=col)
    cell.value = _ILLEGAL.sub("", str(value))
    cell.data_type = "s"
    cell.font = Font(name="Arial", bold=bold, color=color, size=size or 11)
    cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True, readingOrder=2)
    return cell


def _number(ws, row: int, col: int, value: Any, money: bool = False, bold=False):
    cell = ws.cell(row=row, column=col, value=float(Decimal(str(value or 0))))
    cell.number_format = MONEY_FMT if money else "#,##0"
    cell.font = Font(name="Arial", bold=bold)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    return cell


def _safe_sheet_name(name: str) -> str:
    return re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Sheet"


def build_document_xlsx(doc: Dict[str, Any]) -> bytes:
    """doc = {kind, number, date, status, party_label, party{name,phone,email,address}, warehouse,
    price_label, items[{name,sku,unit,quantity,price,total}], total, notes}"""
    wb = Workbook()
    ws = wb.active
    ws.title = _safe_sheet_name(f"{KIND_TITLE[doc['kind']]} {doc['number']}")
    ws.sheet_view.rightToLeft = True

    r = 1
    _text(ws, r, 1, COMPANY_NAME, bold=True, size=16)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    r += 1
    _text(ws, r, 1, f"{KIND_TITLE[doc['kind']]}  #{doc['number']}", bold=True, size=13, color="1F6FEB")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    r += 2

    party = doc["party"]
    info = [
        (doc["party_label"], party["name"]),
        ("الهاتف", party.get("phone")),
        ("البريد", party.get("email")),
        ("العنوان", party.get("address")),
        ("التاريخ", fmt_dt(doc["date"])),
        ("المخزن", doc.get("warehouse")),
        ("الحالة", STATUS_LABEL.get(doc["status"], doc["status"])),
    ]
    for label, value in info:
        if value:
            _text(ws, r, 1, label, bold=True, color="6B778A")
            _text(ws, r, 2, value)
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
            r += 1
    r += 1

    headers = ["#", "المنتج", "الكود", "الكمية", doc["price_label"], "الإجمالي"]
    for i, h in enumerate(headers, 1):
        cell = _text(ws, r, i, h, bold=True, color="6B778A")
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", readingOrder=2)
    head_row = r
    r += 1
    for idx, it in enumerate(doc["items"], 1):
        _number(ws, r, 1, idx)
        _text(ws, r, 2, it["name"])
        c3 = _text(ws, r, 3, it.get("sku") or "")
        c3.alignment = Alignment(horizontal="center", readingOrder=2)
        _number(ws, r, 4, it["quantity"])
        _number(ws, r, 5, it["price"], money=True)
        _number(ws, r, 6, it["total"], money=True)
        for col in range(1, 7):
            ws.cell(row=r, column=col).border = BORDER
        r += 1

    r += 1
    _text(ws, r, 5, f"الإجمالي ({CURRENCY})", bold=True)
    total_cell = _number(ws, r, 6, doc["total"], money=True, bold=True)
    total_cell.fill = HEAD_FILL
    r += 2
    if doc.get("notes"):
        _text(ws, r, 1, "ملاحظات", bold=True, color="6B778A")
        _text(ws, r, 2, doc["notes"])
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
        ws.row_dimensions[r].height = 15 * max(1, len(doc["notes"]) // 60 + 1)

    for col, width in zip("ABCDEF", (6, 38, 16, 12, 16, 18)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = ws.cell(row=head_row + 1, column=1)
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# A report workbook: any number of titled tables. Cell kinds: ("text"|"int"|"money", value).
Table = Tuple[str, Sequence[str], Sequence[Sequence[Tuple[str, Any]]]]


def build_tables_xlsx(title: str, subtitle: str, tables: Iterable[Table]) -> bytes:
    """One sheet per table, each with a title row, a header row and typed data rows."""
    wb = Workbook()
    wb.remove(wb.active)
    used: set = set()
    for name, headers, rows in tables:
        sheet_name = _safe_sheet_name(name)
        base, n = sheet_name, 2
        while sheet_name in used:  # sheet names must be unique
            sheet_name = f"{base[:28]} {n}"
            n += 1
        used.add(sheet_name)
        ws = wb.create_sheet(sheet_name)
        ws.sheet_view.rightToLeft = True
        _text(ws, 1, 1, f"{COMPANY_NAME} — {title}", bold=True, size=14)
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(2, len(headers)))
        _text(ws, 2, 1, subtitle, color="6B778A")
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(2, len(headers)))
        for i, h in enumerate(headers, 1):
            cell = _text(ws, 4, i, h, bold=True, color="6B778A")
            cell.fill = HEAD_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center", readingOrder=2)
        for ri, row in enumerate(rows, 5):
            for ci, (kind, value) in enumerate(row, 1):
                if kind == "money":
                    _number(ws, ri, ci, value, money=True)
                elif kind == "int":
                    _number(ws, ri, ci, value)
                else:
                    _text(ws, ri, ci, value if value is not None else "")
                ws.cell(row=ri, column=ci).border = BORDER
        for ci, h in enumerate(headers, 1):
            longest = max([len(str(h))] + [len(str(r[ci - 1][1])) for r in rows if ci - 1 < len(r)])
            ws.column_dimensions[get_column_letter(ci)].width = min(48, max(12, longest + 3))
        ws.freeze_panes = "A5"

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ----------------------------------------------------------------------------- account statements
STATEMENT_LABELS = {
    # kind -> (document title, charge column, payment column, "owed" caption, party label)
    "customer": ("كشف حساب عميل", "مبيعات", "مقبوضات", "مستحق على العميل", "العميل"),
    "supplier": ("كشف حساب مورد", "مشتريات", "مدفوعات", "مستحق للمورد", "المورد"),
}


def _balance_caption(kind: str, balance: Any) -> str:
    value = Decimal(str(balance or 0))
    owed = STATEMENT_LABELS[kind][3]
    if value > 0:
        return owed
    if value < 0:
        return "رصيد دائن (دفع زائد)"
    return "الحساب مُسوّى"


def _period_label(stmt: Dict[str, Any]) -> str:
    if stmt.get("date_from") and stmt.get("date_to"):
        return f"الفترة: من {stmt['date_from']} إلى {stmt['date_to']}"
    if stmt.get("date_from"):
        return f"الفترة: من {stmt['date_from']}"
    if stmt.get("date_to"):
        return f"الفترة: حتى {stmt['date_to']}"
    return "الفترة: كل الحركات"


def build_statement_pdf(stmt: Dict[str, Any]) -> bytes:
    """stmt = schemas.Statement.model_dump(): kind, party_name, date_from/to, opening, lines[], totals, closing.
    Optional extra keys: party{phone,address}."""
    title, charge_label, pay_label, _, party_label = STATEMENT_LABELS[stmt["kind"]]
    pdf = _Pdf(f"{title} - {stmt['party_name']}")
    c = pdf.c

    pdf.text(RIGHT, pdf.y - 16, COMPANY_NAME, font="Amiri-Bold", size=19)
    sub_y = pdf.y - 34
    for line in (COMPANY_ADDRESS, COMPANY_PHONE):
        if line:
            pdf.text(RIGHT, sub_y, line, size=9.5, color=MUTED)
            sub_y -= 13
    pdf.text(LEFT, pdf.y - 16, title, font="Amiri-Bold", size=19, align="l", color=ACCENT)
    pdf.y = min(sub_y, pdf.y - 30) - 6
    pdf.rule(pdf.y)
    pdf.y -= 22

    top = pdf.y
    pdf.text(RIGHT, top, f"{party_label}:", font="Amiri-Bold", size=11, color=MUTED)
    name_lines = pdf.wrap(stmt["party_name"], "Amiri-Bold", 13, 330)
    for i, ln in enumerate(name_lines):
        pdf.text(RIGHT - 52, top - i * 16, ln, font="Amiri-Bold", size=13)
    ry = top - 17 - (len(name_lines) - 1) * 16
    pdf.text(RIGHT, ry, _period_label(stmt), size=10.5, color=MUTED)
    ry -= 15
    pdf.y = ry - 6

    cols: List[Tuple[str, float, str]] = [
        ("التاريخ", 70, "c"),
        ("المرجع", 62, "c"),
        ("البيان", 153, "r"),
        (charge_label, 76, "c"),
        (pay_label, 76, "c"),
        ("الرصيد", 78, "c"),
    ]
    assert abs(sum(w for _, w, _ in cols) - CONTENT_W) < 1, "column widths must fill the page"
    pad = 5

    def spans() -> List[Tuple[float, float]]:
        out, x = [], RIGHT
        for _, w, _ in cols:
            out.append((x - w, x))
            x -= w
        return out

    def header() -> None:
        h = 24
        c.setFillColor(HEAD_BG)
        c.rect(LEFT, pdf.y - h, CONTENT_W, h, stroke=0, fill=1)
        for (name, _, _), (x0, x1) in zip(cols, spans()):
            pdf.text((x0 + x1) / 2, pdf.y - 16, name, font="Amiri-Bold", size=10.5, align="c", color=MUTED)
        pdf.y -= h

    def row(cells: List[str], bold: bool = False, desc_lines: Optional[List[str]] = None) -> None:
        font, size, lead = ("Amiri-Bold" if bold else "Amiri"), 10.5, 14
        lines = desc_lines or [cells[2]]
        row_h = max(26, len(lines) * lead + 10)
        pdf.ensure(row_h + 4, on_new_page=header)
        base = pdf.y - 17
        for ci, ((_, _, align), (x0, x1)) in enumerate(zip(cols, spans())):
            if ci == 2:
                for li, ln in enumerate(lines):
                    pdf.text(x1 - pad, base - li * lead, ln, font=font, size=size)
            elif cells[ci]:
                pdf.text((x0 + x1) / 2, base, cells[ci], font=font, size=size, align="c")
        pdf.y -= row_h
        pdf.rule(pdf.y)

    header()
    row(["", "", "رصيد افتتاحي", "", "", fmt_money(stmt["opening"])], bold=True)
    desc_w = cols[2][1] - 2 * pad
    for ln in stmt["lines"]:
        charge = Decimal(str(ln["charge"] or 0))
        payment = Decimal(str(ln["payment"] or 0))
        row(
            [
                str(ln["date"]),
                ln["ref"],
                ln["description"],
                fmt_money(charge) if charge else "",
                fmt_money(payment) if payment else "",
                fmt_money(ln["balance"]),
            ],
            desc_lines=pdf.wrap(ln["description"], "Amiri", 10.5, desc_w),
        )
    if not stmt["lines"]:
        pdf.ensure(30)
        pdf.text(PAGE_W / 2, pdf.y - 20, "لا توجد حركات في هذه الفترة", size=10.5, align="c", color=MUTED)
        pdf.y -= 34

    # ---- totals box
    pdf.ensure(100)
    pdf.y -= 10
    box_w, box_h = 260, 78
    c.setFillColor(HEAD_BG)
    c.roundRect(LEFT, pdf.y - box_h, box_w, box_h, 5, stroke=0, fill=1)
    y = pdf.y - 18
    for label, value, bold, color in (
        (f"إجمالي {charge_label}", fmt_money(stmt["total_charges"]), False, INK),
        (f"إجمالي {pay_label}", fmt_money(stmt["total_payments"]), False, INK),
        ("الرصيد الختامي", f"{fmt_money(stmt['closing'])} {CURRENCY}", True, ACCENT),
    ):
        font = "Amiri-Bold" if bold else "Amiri"
        pdf.text(LEFT + box_w - 10, y, label, font=font, size=11.5 if bold else 10.5)
        pdf.text(LEFT + 10, y, value, font=font, size=12.5 if bold else 10.5, align="l", color=color)
        y -= 21
    pdf.text(LEFT + box_w + 12, pdf.y - 18, _balance_caption(stmt["kind"], stmt["closing"]), font="Amiri-Bold", size=11, align="l", color=MUTED)
    pdf.y -= box_h + 10
    return pdf.finish()


def build_statement_xlsx(stmt: Dict[str, Any]) -> bytes:
    title, charge_label, pay_label, _, party_label = STATEMENT_LABELS[stmt["kind"]]
    rows: List[List[Tuple[str, Any]]] = [
        [("text", ""), ("text", ""), ("text", "رصيد افتتاحي"), ("text", ""), ("text", ""), ("money", stmt["opening"])]
    ]
    for ln in stmt["lines"]:
        charge, payment = Decimal(str(ln["charge"] or 0)), Decimal(str(ln["payment"] or 0))
        rows.append(
            [
                ("text", str(ln["date"])),
                ("text", ln["ref"]),
                ("text", ln["description"]),
                ("money", charge) if charge else ("text", ""),
                ("money", payment) if payment else ("text", ""),
                ("money", ln["balance"]),
            ]
        )
    rows.append(
        [
            ("text", ""),
            ("text", ""),
            ("text", f"الإجمالي — {_balance_caption(stmt['kind'], stmt['closing'])}"),
            ("money", stmt["total_charges"]),
            ("money", stmt["total_payments"]),
            ("money", stmt["closing"]),
        ]
    )
    table = ("كشف الحساب", ["التاريخ", "المرجع", "البيان", charge_label, pay_label, "الرصيد"], rows)
    return build_tables_xlsx(f"{title}: {stmt['party_name']}", _period_label(stmt), [table])
