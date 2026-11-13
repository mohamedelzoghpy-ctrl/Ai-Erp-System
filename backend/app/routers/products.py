"""Products and inventory (stock levels, adjustments, movement history)."""

from decimal import Decimal
import re as _re

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..pagination import paginate
from ..audit import audit
from ..codegen import unique_sku
from .. import exports
from ..deps import get_current_user, require_manager, user_role
from .. import models, schemas, stock
from ..accounting import seed_default_coa
from ..database import get_db

router = APIRouter(prefix="/products", tags=["products & inventory"], dependencies=[Depends(get_current_user)])
# صور المنتج: تخدم وسوم <img> — المصادقة عبر توكن الاستعلام (?token=) في البوابة
# المركزية (permission_gate) + قاعدة GET → inventory.product.view + حجب الشركة أدناه.
image_router = APIRouter(prefix="/products", tags=["products & inventory"])

_MAX_IMAGE_BYTES = 3 * 1024 * 1024  # 3MB
_ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _validate_image_url(value: Optional[str]):
    if not value:
        return
    if not value.strip().lower().startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "صورة المنتج: الرابط يجب أن يبدأ http:// أو https:// — أو ارفع الملف من جهازك")


def _product_image_or_404(db: Session, product_id: int) -> models.Product:
    product = db.get(models.Product, product_id)
    if product is None or product.image_blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no image")
    return product


@image_router.get("/{product_id}/image")
def get_product_image(product_id: int, db: Session = Depends(get_db)):
    """تخدم وسم <img> بعد المصادقة (توكن الاستعلام) — مقيّدة بشركة المستخدم عبر المستمع المركزي."""
    product = _product_image_or_404(db, product_id)
    company_id = db.info.get("company_id")
    if company_id is not None and product.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no image")
    return Response(content=product.image_blob, media_type=product.image_mime or "image/png")  # type: ignore


def _product_or_404(db: Session, product_id: int) -> models.Product:
    product = db.get(models.Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product {product_id} not found")
    return product


def _check_refs(db: Session, warehouse_id: Optional[int], supplier_id: Optional[int]):
    if warehouse_id is not None and db.get(models.Warehouse, warehouse_id) is None:
        raise HTTPException(422, f"Warehouse {warehouse_id} does not exist")
    if supplier_id is not None and db.get(models.Supplier, supplier_id) is None:
        raise HTTPException(422, f"Supplier {supplier_id} does not exist")


def _supplier_based_sku(db: Session, company_id: int, supplier: Optional[models.Supplier], name: Optional[str]) -> str:
    """كود الصنف منبثق من كود المورد: SUP-00001-01 ثم -02… بدون مورد يتولد من الاسم (SKU-…)."""
    if supplier is not None:
        taken = {
            s for (s,) in
            db.query(models.Product.sku)
            .filter(models.Product.company_id == company_id, models.Product.sku.like(f"{supplier.code}-%"))
            .all()
        }
        n = 1
        while True:
            candidate = f"{supplier.code}-{n:02d}"
            if candidate not in taken:  # flush المشتركة في نفس الجلسة تجعل الأكواد الجديدة مرئية هنا
                return candidate
            n += 1
    return unique_sku(db, models.Product, company_id, name or "product", max_length=60)


@router.post("", response_model=schemas.ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: schemas.ProductCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    # Cost price and opening stock are manager-only (mirrors opening balances for parties).
    _validate_image_url(payload.image_url)
    if user_role(user) not in ("admin", "manager"):
        if Decimal(str(payload.cost_price)) != 0:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can set a cost price")
        if payload.quantity != 0:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can set an opening stock balance")
    _check_refs(db, payload.warehouse_id, payload.supplier_id)
    data = payload.model_dump()
    if not (data.get("sku") or "").strip():
        sup = db.get(models.Supplier, payload.supplier_id) if payload.supplier_id else None
        data["sku"] = _supplier_based_sku(db, db.info["company_id"], sup, payload.name)
    else:
        data["sku"] = data["sku"].strip().upper()
    opening = data.pop("quantity", 0)
    product = models.Product(**data)
    db.add(product)
    try:
        db.flush()
        if opening:
            home = stock.home_warehouse_id(db, product)
            if home is None:
                db.rollback()
                raise HTTPException(422, "Create a warehouse before adding opening stock")
            stock.move_stock(db, product, home, opening, "adjustment", "opening balance")
        audit(db, user, "create", "product", product, f"{product.sku} · {product.name}")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"SKU '{payload.sku}' already exists")
    db.refresh(product)
    return product


def _availability_map(db: Session, product_ids: list) -> dict:
    """حسابات التوفر (م3) — استعلامان مجمّعان للصفحة بلا N+1:
    reserved: مجموع الحجوزات الصريحة لمسودات البيع · awaiting: المؤكدة غير المسلّمة.
    متاح للبيع = الرصيد − الحجوزات (التأكيد يخصم المخزون فورًا في هذا النظام)."""
    if not product_ids:
        return {}
    reserved = dict(
        db.query(models.StockReservation.product_id, func.coalesce(func.sum(models.StockReservation.quantity), 0))
        .filter(models.StockReservation.product_id.in_(product_ids))
        .group_by(models.StockReservation.product_id)
        .all()
    )
    awaiting = dict(
        db.query(
            models.SalesOrderItem.product_id,
            func.coalesce(func.sum(models.SalesOrderItem.quantity - func.coalesce(models.SalesOrderItem.delivered_quantity, 0)), 0),
        )
        .join(models.SalesOrder, models.SalesOrder.id == models.SalesOrderItem.order_id)
        .filter(models.SalesOrder.status == "confirmed", models.SalesOrderItem.product_id.in_(product_ids))
        .group_by(models.SalesOrderItem.product_id)
        .all()
    )
    return {
        pid: {
            "reserved": float(reserved.get(pid, 0) or 0),
            "awaiting_delivery": float(awaiting.get(pid, 0) or 0),
        }
        for pid in product_ids
    }


@router.get("", response_model=List[schemas.ProductOut])
def list_products(
    response: Response,
    search: Optional[str] = None,
    warehouse_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    low_stock: bool = False,
    is_active: Optional[bool] = None,
    stock_warehouse_id: Optional[int] = None,
    with_availability: bool = False,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """`stock_warehouse_id` adds `warehouse_quantity` (what is on the shelf in that warehouse) to each row."""
    query = db.query(models.Product)
    if search:
        # Smart search: split the typed text into words; every word must match a *word prefix*
        # in the product name (e.g. "طش نان" finds «طشت نانسي») or the start of the SKU.
        for tok in (t for t in search.split() if t):
            pat = r"(^|\s)" + _re.escape(tok)
            query = query.filter(models.Product.name.op("~*")(pat) | models.Product.sku.ilike(f"{tok}%"))
    if warehouse_id is not None:
        query = query.filter(models.Product.warehouse_id == warehouse_id)
    if supplier_id is not None:
        query = query.filter(models.Product.supplier_id == supplier_id)
    if is_active is not None:
        query = query.filter(models.Product.is_active == is_active)
    if low_stock:
        query = query.filter(models.Product.quantity <= models.Product.reorder_level)
    rows = paginate(query, response, skip, limit, models.Product.id)
    if stock_warehouse_id is not None and rows:
        pairs = (
            db.query(models.ProductStock.product_id, models.ProductStock.quantity, models.ProductStock.min_level, models.ProductStock.max_level)
            .filter(models.ProductStock.warehouse_id == stock_warehouse_id, models.ProductStock.product_id.in_([p.id for p in rows]))
            .all()
        )
        have = {pid: q for pid, q, _mn, _mx in pairs}
        mins = {pid: float(mn) for pid, _q, mn, _mx in pairs if mn is not None}
        maxs = {pid: float(mx) for pid, _q, _mn, mx in pairs if mx is not None}
        for p in rows:
            p.warehouse_quantity = have.get(p.id, 0)
            p.warehouse_min_level = mins.get(p.id)
            p.warehouse_max_level = maxs.get(p.id)
    if with_availability and rows:
        avail = _availability_map(db, [p.id for p in rows])
        for p in rows:
            info = avail.get(p.id, {"reserved": 0, "awaiting_delivery": 0})
            p.reserved = info["reserved"]
            p.awaiting_delivery = info["awaiting_delivery"]
            p.available_to_promise = float(p.quantity or 0) - info["reserved"]
    return rows


@router.get("/export/xlsx")
def export_products_xlsx(db: Session = Depends(get_db)):
    products = db.query(models.Product).order_by(models.Product.id).all()
    rows = []
    total_qty = 0
    total_cost_value = 0
    total_sale_value = 0
    for p in products:
        wh = db.get(models.Warehouse, p.warehouse_id) if p.warehouse_id else None  # type: ignore
        sup = db.get(models.Supplier, p.supplier_id) if p.supplier_id else None  # type: ignore
        # الكميات والأسعار Numeric تعود Decimal من القاعدة — نحسب بـDecimal ولا
        # نخلط float (كان يكسر التصدير بـTypeError لأي منتج له كمية)
        from decimal import Decimal
        q = Decimal(str(p.quantity or 0))
        cost_value = q * Decimal(str(p.cost_price or 0))
        sale_value = q * Decimal(str(p.sale_price or 0))
        total_qty += q
        total_cost_value += cost_value
        total_sale_value += sale_value
        rows.append([
            ("text", p.sku),
            ("text", p.name),
            ("text", p.unit),
            ("money", p.cost_price),
            ("money", p.sale_price),
            ("int", p.quantity),
            ("int", p.reorder_level),
            ("money", cost_value),
            ("money", sale_value),
            ("text", wh.name if wh else ""),
            ("text", sup.name if sup else ""),
            ("text", "نعم" if p.is_active else "لا"),  # type: ignore
        ])
    rows.append([
        ("text", "الإجمالي"),
        ("text", ""),
        ("text", ""),
        ("money", 0),
        ("money", 0),
        ("int", total_qty),
        ("int", 0),
        ("money", total_cost_value),
        ("money", total_sale_value),
        ("text", ""),
        ("text", ""),
        ("text", ""),
    ])
    content = exports.build_tables_xlsx(
        "قائمة المنتجات", "", [("المنتجات", ["الكود", "الاسم", "الوحدة", "سعر التكلفة", "سعر البيع", "الكمية", "حد إعادة الطلب", "قيمة التكلفة", "قيمة البيع", "المخزن", "المورد", "نشط"], rows)]
    )
    return Response(content=content, media_type=exports.XLSX_MIME, headers={"Content-Disposition": 'attachment; filename="products.xlsx"', "Cache-Control": "no-store"})


_UPLOAD_TEMPLATE_HEADERS = [
    "كود الصنف", "اسم الصنف", "كود المورد", "اسم المورد", "الوحدة", "سعر البيع", "سعر الشراء",
]


@router.get("/import-template/xlsx")
def product_import_template_xlsx():
    """نيوفت الرفع السريع: كود/اسم الصنف + المورد بالكود أو الاسم + الوحدة والأسعار."""
    content = exports.build_tables_xlsx(
        "نموذج رفع المنتجات",
        "«كود الصنف» الفاضي يتولد من كود المورد (مثل SUP-00001-01 ثم -02…) وبدون مورد من اسم الصنف (SKU-…) — المورد يتطابق بكود المورد أولًا ثم اسمه، والعمود الفارغ يعني بدون تغيير",
        [("المنتجات", _UPLOAD_TEMPLATE_HEADERS, [
            [("text", ""), ("text", "مثال: أمبولة فريدة — احذف هذا الصف قبل الاستيراد"), ("text", ""), ("text", ""), ("text", "قطعة"), ("money", 0), ("money", 0)],
        ])],
    )
    content = exports.decorate_template_xlsx(content, required_titles=["اسم الصنف"], yes_no_title="— غير موجود —")
    return Response(
        content=content,
        media_type=exports.XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="products-upload-template.xlsx"', "Cache-Control": "no-store"},
    )


@router.post("/import/xlsx")
async def import_products_xlsx(
    file: UploadFile = File(...),
    dry_run: bool = False,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    import io
    import openpyxl
    content = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception:
        raise HTTPException(422, "Invalid Excel file")
    ws = wb.active
    # Find the header row: rows may start with title/subtitle lines, and a DATA row can
    # also mention «الكود» inside a product name — so require ≥2 cells that look like
    # column titles (a full sentence in one cell only scores 1).
    header_row_idx = 1
    header_aliases = (
        "الكود", "كود الصنف", "SKU", "sku", "الاسم", "اسم الصنف", "Name",
        "الوحدة", "Unit", "التكلفة", "Cost", "سعر الشراء", "شراء",
        "سعر البيع", "البيع", "Sale", "إعادة الطلب", "Reorder",
        "كود المورد", "اسم المورد", "المورد", "نشط", "الكمية",
    )
    for r in range(1, min(ws.max_row, 10) + 1):  # type: ignore
        cells = [str(c.value).strip() if c.value is not None else "" for c in ws[r]]  # type: ignore
        if sum(1 for c in cells if c and any(a in c for a in header_aliases)) >= 2:
            header_row_idx = r
            break
    header = [str(c.value).strip() if c.value is not None else "" for c in ws[header_row_idx]]  # type: ignore

    def col(*aliases: str):
        """First column whose header contains any alias (earlier aliases win)."""
        for a in aliases:
            for i, h in enumerate(header):
                if a and a in h:
                    return i
        return None

    # كود الصنف first: the new upload template's header, then the old export's «الكود»/SKU
    sku_i = col("كود الصنف", "الكود", "SKU", "sku")
    name_i = col("اسم الصنف", "الاسم", "Name")
    unit_i = col("الوحدة", "Unit")
    cost_i = col("سعر الشراء", "شراء", "التكلفة", "Cost")
    sale_i = col("سعر البيع", "البيع", "Sale")
    reorder_i = col("إعادة الطلب", "Reorder")
    sup_code_i = col("كود المورد")
    sup_name_i = col("اسم المورد", "المورد")

    company_id = db.info["company_id"]
    # supplier lookup (code first, then name), scoped to this company
    suppliers_by_code = {s.code: s for s in db.query(models.Supplier).filter(models.Supplier.company_id == company_id).all()} if sup_code_i is not None else {}
    suppliers_by_name = {s.name.strip(): s for s in db.query(models.Supplier).filter(models.Supplier.company_id == company_id).all()}

    def _cell(row, idx):
        if idx is not None and idx < len(row) and row[idx] is not None:
            s = str(row[idx]).strip()
            return s or None
        return None

    updated = 0
    created = 0
    errors = []
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):  # type: ignore
        if not row or all(v is None for v in row):
            continue
        sku = _cell(row, sku_i)
        name = _cell(row, name_i)
        first = sku or (name or "")
        if not first or first in ("الإجمالي", "Total", "TOTAL") or "احذف هذا الصف" in first:
            continue
        # المورد يتحدد أولًا — كود الصنف المتولد ينبع من كود المورد
        sup = None
        sup_written = ""
        if sup_code_i is not None or sup_name_i is not None:
            sup = suppliers_by_code.get(_cell(row, sup_code_i) or "") if sup_code_i is not None else None
            if sup is None and sup_name_i is not None:
                sup = suppliers_by_name.get(_cell(row, sup_name_i) or "")
            sup_written = _cell(row, sup_code_i) or _cell(row, sup_name_i) or ""
        product = None
        if sku:
            product = db.query(models.Product).filter(models.Product.company_id == company_id, models.Product.sku == sku).one_or_none()
        if product is None and name:
            product = db.query(models.Product).filter(models.Product.company_id == company_id, models.Product.name == name).one_or_none()
        is_new = product is None
        if is_new:
            # كود الصنف منبثق من كود المورد — ولو مفيش مورد يتولد من اسم الصنف (SKU-…)
            if not sku and not name and not sup:
                continue
            new_sku = sku or _supplier_based_sku(db, company_id, sup, name)
            new_name = name or sku or (sup.name if sup else "")  # type: ignore[union-attr]
            product = models.Product(company_id=company_id, sku=new_sku, name=new_name, unit="قطعة", is_active=True)  # type: ignore
            db.add(product)
            db.flush()
            created += 1
        else:
            updated += 1
        if name:
            product.name = name  # type: ignore[union-attr]
        if sup is not None:
            product.supplier_id = sup.id  # type: ignore[union-attr]
        elif sup_written:
            errors.append(f"{name or sku}: المورد المكتوب «{sup_written}» غير موجود — الصنف بقى بدون مورد")
        if unit_i is not None and unit_i < len(row) and row[unit_i] is not None:
            product.unit = str(row[unit_i]).strip() or product.unit  # type: ignore
        if cost_i is not None and cost_i < len(row) and row[cost_i] is not None:
            try:
                product.cost_price = Decimal(str(row[cost_i]))  # type: ignore
            except Exception:
                errors.append(f"{sku}: invalid cost_price")
        if sale_i is not None and sale_i < len(row) and row[sale_i] is not None:
            try:
                product.sale_price = Decimal(str(row[sale_i]))  # type: ignore
            except Exception:
                errors.append(f"{sku}: invalid sale_price")
        if reorder_i is not None and reorder_i < len(row) and row[reorder_i] is not None:
            try:
                product.reorder_level = int(row[reorder_i])  # type: ignore
            except Exception:
                errors.append(f"{sku}: invalid reorder_level")
        # (counted above)
    if dry_run:
        # اختبار النموذج: نفس الحساب بالضبط بدون تسجيل أي شيء في القاعدة
        db.rollback()
        return {"updated": updated, "created": created, "errors": errors, "dry_run": True}
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "الرفع اترفض: كود مكرر في الملف أو في النظام — سلّسلت الأكواد المتولدة محمية، والكود المكتوب باليد لازم يكون جديدًا أو لصنف موجود",
        )
    return {"updated": updated, "created": created, "errors": errors}


@router.post("/{product_id}/image", response_model=schemas.ProductOut)
async def upload_product_image(product_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Upload the product picture from the user's device (max 3MB)."""
    product = _product_or_404(db, product_id)
    if (file.content_type or "") not in _ALLOWED_IMAGE_MIMES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "نوع الملف غير مدعوم — استخدم صورة PNG أو JPEG أو WebP أو GIF")
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الملف فارغ")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "حجم الصورة يتجاوز 3 ميجابايت")
    product.image_blob = data  # type: ignore[assignment]
    product.image_mime = file.content_type  # type: ignore[assignment]
    audit(db, user, "update", "product", product, f"صورة المنتج: {file.content_type} ({len(data)} bytes)")
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}/image", response_model=schemas.ProductOut)
def remove_product_image(product_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Remove the uploaded picture only (an internet link set separately stays)."""
    product = _product_or_404(db, product_id)
    product.image_blob = None  # type: ignore[assignment]
    product.image_mime = None  # type: ignore[assignment]
    audit(db, user, "update", "product", product, "حذف صورة المنتج المرفوعة")
    db.commit()
    db.refresh(product)
    return product


@router.get("/adjustment-reasons", response_model=List[schemas.AdjustmentReasonOut])
def list_adjustment_reasons(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.AdjustmentReason).filter(
        models.AdjustmentReason.company_id == db.info["company_id"], models.AdjustmentReason.is_active.is_(True)
    ).order_by(models.AdjustmentReason.name).all()


@router.get("/{product_id}", response_model=schemas.ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = _product_or_404(db, product_id)
    info = _availability_map(db, [product.id]).get(product.id, {"reserved": 0, "awaiting_delivery": 0})
    product.reserved = info["reserved"]
    product.awaiting_delivery = info["awaiting_delivery"]
    product.available_to_promise = float(product.quantity or 0) - info["reserved"]
    return product


REVALUATION_CODE = "5295"  # فروق تقييم المخزون (expense) — يُبذر عند أول حاجة


def _ensure_revaluation_account(db: Session, company_id: int) -> int:
    """حساب فروق التقييم: يُبذر مع الشجرة للشركات الجديدة، ويُنشأ يدويًا هنا
    للشركات المزروعة سابقًا (البذر idempotent لا يضيف لأشجار قائمة)."""
    seed_default_coa(db, company_id)
    acc = (
        db.query(models.ChartAccount)
        .filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == REVALUATION_CODE)
        .first()
    )
    if acc is not None:
        return acc.id
    parent = (
        db.query(models.ChartAccount)
        .filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "5200")
        .first()
    )
    acc = models.ChartAccount(
        company_id=company_id, code=REVALUATION_CODE, name="فروق تقييم المخزون (Revaluation)",
        type="expense", is_group=False, parent_id=parent.id if parent else None,
    )
    db.add(acc)
    db.flush()
    return acc.id


@router.patch("/{product_id}", response_model=schemas.ProductOut)
def update_product(product_id: int, payload: schemas.ProductUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    product = _product_or_404(db, product_id)
    data = payload.model_dump(exclude_unset=True)
    _validate_image_url(data.get("image_url"))  # type: ignore[arg-type]
    # Cost price changes are manager-only (mirrors opening balances for parties).
    if "cost_price" in data and user_role(user) not in ("admin", "manager"):
        if Decimal(str(data["cost_price"])) != Decimal(str(product.cost_price)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager or admin can change the cost price")
    _check_refs(db, data.get("warehouse_id"), data.get("supplier_id"))

    # إعادة تقييم المخزون: تعديل التكلفة بكمية قائمة يُرحَّل فرق التقييم للدفاتر
    # بدل تعديل صامت — إما أن يكون المخزون مساوياً لدفاتره أو هناك قيد يفسر الفرق
    reval_delta = Decimal("0")
    if "cost_price" in data and product.quantity and Decimal(str(product.quantity)) > 0:
        old_cost = Decimal(str(product.cost_price or 0))
        new_cost = Decimal(str(data["cost_price"] or 0))
        if new_cost != old_cost:
            reval_delta = (new_cost - old_cost) * Decimal(str(product.quantity))

    for key, value in data.items():
        setattr(product, key, value)
    audit(db, user, "update", "product", product, "، ".join(data) or None)

    if reval_delta != 0:
        from ..accounting import AccountingEngine
        company_id = db.info["company_id"]
        seed_default_coa(db, company_id)
        reval_acc_id = _ensure_revaluation_account(db, company_id)
        inventory = (
            db.query(models.ChartAccount)
            .filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1101")
            .first()
        )
        if inventory is not None:
            if reval_delta > 0:
                items = [
                    {"account_id": inventory.id, "debit": reval_delta, "credit": 0},
                    {"account_id": reval_acc_id, "debit": 0, "credit": reval_delta},
                ]
            else:
                items = [
                    {"account_id": reval_acc_id, "debit": -reval_delta, "credit": 0},
                    {"account_id": inventory.id, "debit": 0, "credit": -reval_delta},
                ]
            AccountingEngine.create_entry(
                db=db, company_id=company_id, user_id=user.id,
                description=f"إعادة تقييم مخزون {product.sku} — {product.name}",
                items=items,
                reference=f"REVAL-{product.id}",
            )

    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)
):
    product = _product_or_404(db, product_id)
    audit(db, user, "delete", "product", product.id, f"{product.sku} · {product.name}")
    db.delete(product)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Product has order or stock history; deactivate it instead (is_active=false)",
        )


@router.post("/{product_id}/adjust-stock", response_model=schemas.ProductOut)
def adjust_stock(product_id: int, payload: schemas.StockAdjustment, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """تسوية مخزنية بسبب من الكتالوج — القيمة فوق الحد تتطلب مديرًا (اعتماد)."""
    import os as _os
    from ..deps import user_role
    if payload.change == 0:
        raise HTTPException(422, "change must not be zero")
    product = (
        db.query(models.Product).filter(models.Product.id == product_id).with_for_update().one_or_none()
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product {product_id} not found")
    warehouse_id = payload.warehouse_id if payload.warehouse_id is not None else stock.home_warehouse_id(db, product)
    if warehouse_id is None or db.get(models.Warehouse, warehouse_id) is None:
        raise HTTPException(422, "Choose an existing warehouse for this adjustment")
    reason = db.get(models.AdjustmentReason, payload.reason_id)
    if reason is None or reason.company_id != db.info["company_id"] or not reason.is_active:
        raise HTTPException(422, "اختر سبب تسوية صالحًا من الكتالوج")
    # الاعتماد: القيمة التقديرية للتسوية فوق الحد تتطلب مديرًا
    value = abs(float(payload.change)) * float(product.cost_price or 0)
    threshold = float(_os.getenv("ADJUST_APPROVAL_VALUE", "1000"))
    if value > threshold and user_role(user) not in ("admin", "manager") and not user.is_platform_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"تسوية بقيمة ≈{value:.0f} ج تتجاوز حد الاعتماد ({threshold:.0f} ج) — تتطلب موافقة مدير",
        )
    note = (payload.note or "").strip() or reason.name
    stock.move_stock(db, product, warehouse_id, payload.change, "adjustment", payload.reference, user_id=user.id, reason_note=f"{reason.name}: {note}"[:200])
    audit(db, user, "adjust_stock", "product", product, f"{stock.q3(payload.change):+} → {product.quantity} ({reason.name}" + (f" — {payload.reference})" if payload.reference else ")"))  # q3 يوحّد النوع
    db.commit()
    db.refresh(product)
    return product


@router.get("/by-barcode/{barcode}")
def resolve_barcode(barcode: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """تحليل باركود: منتج + الكمية بالقطع — يدعم باركود المقياس (prefix 20-29 = وزن بالجرام)
    وباركود الحزمة (pack_qty). يعيد 404 إن لم يُعرف."""
    code = barcode.strip()
    row = (
        db.query(models.ProductBarcode)
        .filter(models.ProductBarcode.company_id == db.info["company_id"], models.ProductBarcode.barcode == code)
        .first()
    )
    pack_qty = Decimal("1")
    product = None
    scale_qty = None
    if row is not None:
        product = db.get(models.Product, row.product_id)
        pack_qty = row.pack_qty
        if product is not None and not product.is_active:
            product = None
    if product is None:
        product = db.query(models.Product).filter(
            models.Product.company_id == db.info["company_id"],
            models.Product.sku == code,
            models.Product.is_active.is_(True),
        ).first()
    if product is None and len(code) == 13 and code[:2] in ("20", "21", "22", "23", "24", "25", "26", "27", "28", "29"):
        # باركود مقياس: خانات 3-7 كود الصنف، 8-12 الوزن بالجرام
        prefix = code[2:7].lstrip("0")
        product = db.query(models.Product).filter(
            models.Product.company_id == db.info["company_id"],
            models.Product.sku.like(prefix + "%"),
            models.Product.is_active.is_(True),
        ).first()
        if product is not None:
            grams = int(code[7:12])
            scale_qty = grams / 1000.0
            pack_qty = Decimal(str(scale_qty))
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "باركود غير معروف")
    return {
        "product_id": product.id, "sku": product.sku, "name": product.name,
        "sale_price": str(product.sale_price), "pack_qty": str(pack_qty),
        "scale_qty": scale_qty,
    }


@router.get("/labels/{product_id}", response_class=Response)
def product_labels(product_id: int, copies: int = Query(default=24, ge=1, le=200), db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """شيت ملصقات قابل للطباعة: الاسم + السعر + باركود Code128 (SVG مدمج)."""
    product = db.get(models.Product, product_id)
    if product is None or product.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الصنف غير موجود")
    # Code128 لا يدعم غير ASCII — الأصناف بأسماء/أكواد عربية تُستبدل بكود داخلي فريد
    code = product.sku if all(32 <= ord(ch) <= 126 for ch in product.sku) else f"MZ-{product.id}"
    try:
        import barcode as _barcode_lib
        from barcode.writer import SVGWriter as _SVGWriter
        from io import BytesIO as _BIO
        buf = _BIO()
        code128 = _barcode_lib.get("code128", code, writer=_SVGWriter())
        code128.write(buf)
        svg = buf.getvalue().decode()
        svg_inner = svg[svg.index(">") + 1:]
    except Exception as exc:
        raise HTTPException(422, "تعذر توليد الباركود: " + str(exc))
    label = ('<div class="lbl"><div class="nm">' + product.name + '</div><div class="pr">'
             + str(product.sale_price) + ' EGP</div>' + svg_inner + '</div>')
    cells = label * copies
    css = (
        "body { font-family: sans-serif; }"
        ".sheet { display: flex; flex-wrap: wrap; }"
        ".lbl { width: 38mm; height: 25mm; border: 1px dashed #bbb; box-sizing: border-box;"
        " padding: 2mm; text-align: center; overflow: hidden; page-break-inside: avoid; }"
        ".lbl .nm { font-size: 11px; font-weight: 700; white-space: nowrap; overflow: hidden; }"
        ".lbl .pr { font-size: 12px; font-weight: 800; }"
        ".lbl svg { width: 32mm; height: 10mm; }"
        "@media print { .lbl { border: none; } }"
    )
    html = ('<!doctype html><html dir="rtl"><head><meta charset="utf-8"><style>' + css
            + '</style></head><body onload="window.print()"><div class="sheet">' + cells + '</div></body></html>')
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/{product_id}/barcodes", response_model=List[schemas.ProductBarcodeOut])
def list_product_barcodes(product_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    product = db.get(models.Product, product_id)
    if product is None or product.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الصنف غير موجود")
    return db.query(models.ProductBarcode).filter(models.ProductBarcode.product_id == product_id).order_by(models.ProductBarcode.id).all()


@router.post("/{product_id}/barcodes", response_model=schemas.ProductBarcodeOut, status_code=status.HTTP_201_CREATED)
def add_product_barcode(product_id: int, payload: schemas.ProductBarcodeIn, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    product = db.get(models.Product, product_id)
    if product is None or product.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الصنف غير موجود")
    code = payload.barcode.strip()
    if db.query(models.ProductBarcode).filter(
        models.ProductBarcode.company_id == db.info["company_id"], models.ProductBarcode.barcode == code
    ).first():
        raise HTTPException(409, "الباركود مستخدم لصنف آخر")
    row = models.ProductBarcode(company_id=db.info["company_id"], product_id=product_id, barcode=code, pack_qty=payload.pack_qty)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "create", "product_barcode", row, product.sku + " <- " + code + " x" + str(row.pack_qty))
    return row


@router.delete("/{product_id}/barcodes/{barcode_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product_barcode(product_id: int, barcode_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.get(models.ProductBarcode, barcode_id)
    if row is None or row.company_id != db.info["company_id"] or row.product_id != product_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الباركود غير موجود")
    db.delete(row)
    db.commit()
    audit(db, user, "delete", "product_barcode", barcode_id, "barcode " + row.barcode)


@router.post("/adjustment-reasons", response_model=schemas.AdjustmentReasonOut, status_code=status.HTTP_201_CREATED)
def create_adjustment_reason(payload: schemas.AdjustmentReasonIn, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "اسم السبب مطلوب")
    if db.query(models.AdjustmentReason).filter(
        models.AdjustmentReason.company_id == db.info["company_id"], models.AdjustmentReason.name == name
    ).first():
        raise HTTPException(409, "يوجد سبب بنفس الاسم")
    row = models.AdjustmentReason(company_id=db.info["company_id"], name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "create", "adjustment_reason", row, row.name)
    return row


@router.post("/{product_id}/min-level", response_model=List[schemas.ProductStockOut])
def set_min_level(
    product_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """ضبط حد الطلب الأدنى الخاص بمخزن معين (يتجاوز الحد العام للمنتج). null = إلغاء الخاص."""
    product = (
        db.query(models.Product)
        .filter(models.Product.id == product_id, models.Product.company_id == db.info["company_id"])
        .with_for_update()
        .one_or_none()
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product {product_id} not found")
    warehouse_id = payload.get("warehouse_id")
    warehouse = (
        db.query(models.Warehouse)
        .filter(models.Warehouse.id == warehouse_id, models.Warehouse.company_id == db.info["company_id"])
        .first()
    ) if warehouse_id else None
    if warehouse is None:
        raise HTTPException(422, "اختر مخزنًا موجودًا في الشركة")
    min_level = payload.get("min_level")
    if min_level is not None:
        from decimal import Decimal as _D
        min_level = _D(str(min_level))
        if min_level < 0:
            raise HTTPException(422, "الحد الأدنى لا يكون سالبًا")
    max_level = payload.get("max_level")
    if max_level is not None:
        from decimal import Decimal as _D
        max_level = _D(str(max_level))
        if max_level < 0:
            raise HTTPException(422, "الحد الأقصى لا يكون سالبًا")
        if min_level is not None and max_level < min_level:
            raise HTTPException(422, "الحد الأقصى لا يقل عن الحد الأدنى")
    row = db.query(models.ProductStock).filter(
        models.ProductStock.product_id == product_id, models.ProductStock.warehouse_id == warehouse.id
    ).first()
    if row is None:
        row = models.ProductStock(product_id=product_id, warehouse_id=warehouse.id, quantity=0, min_level=min_level, max_level=max_level)  # type: ignore
        db.add(row)
    else:
        if "min_level" in payload:
            row.min_level = min_level
        if "max_level" in payload:
            row.max_level = max_level
    audit(db, user, "update", "product_min_level", product,
          f"حدود «{warehouse.name}»: أدنى {'إلغاء' if min_level is None else min_level} · أقصى {'إلغاء' if max_level is None else max_level}")
    db.commit()
    rows = db.query(models.ProductStock).filter(models.ProductStock.product_id == product_id).all()
    return [
        schemas.ProductStockOut(
            warehouse_id=r.warehouse_id,
            warehouse_name=r.warehouse.name if r.warehouse else str(r.warehouse_id),
            quantity=float(r.quantity),
            min_level=float(r.min_level) if r.min_level is not None else None,
            max_level=float(r.max_level) if r.max_level is not None else None,
        )
        for r in rows
    ]


@router.get("/{product_id}/stock", response_model=List[schemas.ProductStockOut])
def product_stock(product_id: int, db: Session = Depends(get_db)):
    """Where this product's stock sits, one row per warehouse that holds some."""
    _product_or_404(db, product_id)
    rows = (
        db.query(models.ProductStock)
        .filter(models.ProductStock.product_id == product_id, models.ProductStock.quantity > 0)
        .order_by(models.ProductStock.warehouse_id)
        .all()
    )
    return [schemas.ProductStockOut(warehouse_id=r.warehouse_id, warehouse_name=r.warehouse.name, quantity=r.quantity, min_level=float(r.min_level) if r.min_level is not None else None, max_level=float(r.max_level) if r.max_level is not None else None) for r in rows]  # type: ignore


@router.get("/{product_id}/movements", response_model=List[schemas.StockMovementOut])
def product_movements(product_id: int, db: Session = Depends(get_db)):
    _product_or_404(db, product_id)
    return (
        db.query(models.StockMovement)
        .filter(models.StockMovement.product_id == product_id)
        .order_by(models.StockMovement.id.desc())
        .all()
    )
