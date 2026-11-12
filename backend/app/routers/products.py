"""Products and inventory (stock levels, adjustments, movement history)."""

from decimal import Decimal
import re as _re

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..pagination import paginate
from ..audit import audit
from ..codegen import unique_sku
from .. import exports
from ..deps import get_current_user, require_manager, user_role
from .. import models, schemas, stock
from ..database import get_db

router = APIRouter(prefix="/products", tags=["products & inventory"], dependencies=[Depends(get_current_user)])
# صور المنتج: استرجاع الصورة دون توكن (تُستخدم داخل <img src> بالمتصفح)
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
    """Public: serves the uploaded product image bytes for <img> tags."""
    product = _product_image_or_404(db, product_id)
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


@router.get("", response_model=List[schemas.ProductOut])
def list_products(
    response: Response,
    search: Optional[str] = None,
    warehouse_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    low_stock: bool = False,
    is_active: Optional[bool] = None,
    stock_warehouse_id: Optional[int] = None,
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
            db.query(models.ProductStock.product_id, models.ProductStock.quantity, models.ProductStock.min_level)
            .filter(models.ProductStock.warehouse_id == stock_warehouse_id, models.ProductStock.product_id.in_([p.id for p in rows]))
            .all()
        )
        have = {pid: q for pid, q, _mn in pairs}
        mins = {pid: float(mn) for pid, _q, mn in pairs if mn is not None}
        for p in rows:
            p.warehouse_quantity = have.get(p.id, 0)
            p.warehouse_min_level = mins.get(p.id)
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
        q = p.quantity or 0
        cost_value = q * float(p.cost_price)  # type: ignore
        sale_value = q * float(p.sale_price)  # type: ignore
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


@router.get("/{product_id}", response_model=schemas.ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    return _product_or_404(db, product_id)


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
    for key, value in data.items():
        setattr(product, key, value)
    audit(db, user, "update", "product", product, "، ".join(data) or None)
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
    """Manual correction (stock-take, damage, etc.). Never lets quantity go negative."""
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
    stock.move_stock(db, product, warehouse_id, payload.change, "adjustment", payload.reference)
    audit(db, user, "adjust_stock", "product", product, f"{stock.q3(payload.change):+} → {product.quantity}" + (f" ({payload.reference})" if payload.reference else ""))  # q3 يوحّد النوع (d يفشل على float)
    db.commit()
    db.refresh(product)
    return product


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
    row = db.query(models.ProductStock).filter(
        models.ProductStock.product_id == product_id, models.ProductStock.warehouse_id == warehouse.id
    ).first()
    if row is None:
        row = models.ProductStock(product_id=product_id, warehouse_id=warehouse.id, quantity=0, min_level=min_level)
        db.add(row)
    else:
        row.min_level = min_level
    audit(db, user, "update", "product_min_level", product,
          f"حد أدنى لـ«{warehouse.name}»: {'إلغاء الخاص' if min_level is None else min_level}")
    db.commit()
    rows = db.query(models.ProductStock).filter(models.ProductStock.product_id == product_id).all()
    return [
        schemas.ProductStockOut(
            warehouse_id=r.warehouse_id,
            warehouse_name=r.warehouse.name if r.warehouse else str(r.warehouse_id),
            quantity=float(r.quantity),
            min_level=float(r.min_level) if r.min_level is not None else None,
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
    return [schemas.ProductStockOut(warehouse_id=r.warehouse_id, warehouse_name=r.warehouse.name, quantity=r.quantity, min_level=float(r.min_level) if r.min_level is not None else None) for r in rows]  # type: ignore


@router.get("/{product_id}/movements", response_model=List[schemas.StockMovementOut])
def product_movements(product_id: int, db: Session = Depends(get_db)):
    _product_or_404(db, product_id)
    return (
        db.query(models.StockMovement)
        .filter(models.StockMovement.product_id == product_id)
        .order_by(models.StockMovement.id.desc())
        .all()
    )
