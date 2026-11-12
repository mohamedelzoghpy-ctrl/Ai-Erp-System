"""الفاتورة الإلكترونية (ETA): إعداد الشركة، توليد المفاتيح/CSR، الإرسال، ومتابعة الحالة.

الإعداد مخفي الأسرار: client_secret والخاص لا يُرجعان نصًا كاملًا أبدًا.
بيئة mock تعمل بلا شبكة — عند تسجيل الشركة تُبدَّل إلى sandbox/prod ببيانات الدخول فقط.
"""
import json
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Optional

import fastapi
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import eta, models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user
from ..pagination import paginate

router = APIRouter(prefix="/eta", tags=["eta"])

ALLOWED_ENVS = ("mock", "sandbox", "prod")
RECEIVER_TIN_PATTERN = None  # التحقق الصارم للرقم الضريبي عند تشغيل sandbox/prod


def _company(db: Session) -> models.Company:
    company = db.get(models.Company, db.info["company_id"])
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الشركة غير موجودة")
    return company


def _masked(company: models.Company) -> dict:
    return {
        "enabled": bool(company.eta_enabled),
        "env": company.eta_env,
        "tin": company.eta_tin,
        "client_id": company.eta_client_id,
        "has_client_secret": bool(company.eta_client_secret),
        "client_secret_masked": ("••••" + company.eta_client_secret[-4:]) if company.eta_client_secret else None,
        "has_private_key": bool(company.eta_private_key),
        "activity_code": company.eta_activity_code,
        "address": {
            "governate": company.eta_governate,
            "region_city": company.eta_region_city,
            "street": company.eta_street,
            "building_number": company.eta_building_number,
        },
    }


def _client_for(company: models.Company) -> eta.EtaClient:
    return eta.EtaClient(
        env=company.eta_env,
        client_id=company.eta_client_id or "",
        client_secret=company.eta_client_secret or "",
    )


def _require_ready(company: models.Company, *, need_secret: bool = True) -> None:
    if not company.eta_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "الفاتورة الإلكترونية غير مفعّلة — فعّلها من الإعداد")
    if not company.eta_tin:
        raise HTTPException(status.HTTP_409_CONFLICT, "الرقم الضريبي غير مضبوط")
    if need_secret and company.eta_env != "mock" and not (company.eta_client_id and company.eta_client_secret):
        raise HTTPException(status.HTTP_409_CONFLICT, "بيانات الدخول (client_id/secret) مطلوبة في بيئة " + company.eta_env)
    if not company.eta_private_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يوجد مفتاح توقيع — ولّد المفاتيح من صفحة الإعداد أولًا")
    if company.eta_env != "mock" and not all(
        (company.eta_governate, company.eta_region_city, company.eta_street)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "عنوان المُصدر ناقص — المنظومة ترفض المستندات بلا (المحافظة/المدينة/الشارع)، أكمله من الإعداد",
        )


# ---------------------------------------------------------------- طابور فواتير البيع
def _receipt_filter_submitted(db: Session, company_id: int) -> tuple[set, dict]:
    """معرّفات الأوامر المُرسلة كإيصالات (valid/submitted) + آخر حالة لكل أمر."""
    submitted_ids = {
        row.order_id for row in db.query(models.EtaSubmission.order_id).filter(
            models.EtaSubmission.company_id == company_id,
            models.EtaSubmission.document_type == "R",
            models.EtaSubmission.order_id.isnot(None),
            models.EtaSubmission.status.in_(("submitted", "valid")),
        ).all()
    }
    status_by_order: dict = {}
    for row in db.query(models.EtaSubmission).filter(
        models.EtaSubmission.company_id == company_id, models.EtaSubmission.document_type == "R"
    ).order_by(models.EtaSubmission.id.desc()).all():
        if row.order_id not in status_by_order:
            status_by_order[row.order_id] = {
                "status": row.status, "eta_long_id": row.eta_long_id,
                "errors": row.errors, "submission_id": row.id,
            }
    return submitted_ids, status_by_order


@router.get("/queue")
def submit_queue(
    document_type: str = Query("I", alias="type", pattern="^(I|R)$"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """الفواتير المؤكدة غير المرسلة (جاهزة للرفع) + المرسلة (لمتابعتها).

    document_type=I فواتير B2B · document_type=R إيصالات نقاط البيع B2C."""
    company = _company(db)
    doc_type = "R" if document_type == "R" else "I"
    if doc_type == "R":
        submitted_ids, status_by_order = _receipt_filter_submitted(db, company.id)
    else:
        submitted_ids = {
            row.order_id for row in db.query(models.EtaSubmission.order_id).filter(
                models.EtaSubmission.company_id == company.id,
                models.EtaSubmission.document_type == "I",
                models.EtaSubmission.order_id.isnot(None),
                models.EtaSubmission.status.in_(("submitted", "valid")),
            ).all()
        }
        status_by_order: dict = {}
        for row in db.query(models.EtaSubmission).filter(
            models.EtaSubmission.company_id == company.id, models.EtaSubmission.document_type == "I"
        ).order_by(models.EtaSubmission.id.desc()).all():
            if row.order_id not in status_by_order:
                status_by_order[row.order_id] = {
                    "status": row.status, "eta_long_id": row.eta_long_id,
                    "errors": row.errors, "submission_id": row.id,
                }
    pending, sent = [], []
    orders = (
        db.query(models.SalesOrder)
        .filter(models.SalesOrder.company_id == company.id, models.SalesOrder.status == "confirmed")
        .order_by(models.SalesOrder.id.desc())
        .limit(300)
        .all()
    )
    for o in orders:
        is_b2b = o.customer is not None and bool(o.customer.tax_registration_number)
        if doc_type == "R" and is_b2b:
            continue  # عميل مسجل ضريبيًا → فاتورة I لا إيصال R
        row = {
            "order_id": o.id, "internal_id": f"SO-{o.id}", "party_name": o.party_name,
            "total_amount": o.total_amount, "foreign_total": o.foreign_total,
            "currency_code": o.currency_code, "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        if o.id in submitted_ids:
            info = status_by_order.get(o.id, {})
            sent.append({**row, "status": info.get("status"), "eta_long_id": info.get("eta_long_id"),
                         "errors": info.get("errors"), "submission_id": info.get("submission_id")})
        else:
            pending.append(row)
    return {"pending": pending, "sent": sent, "document_type": doc_type}


@router.post("/submit-receipt/{order_id}")
def submit_receipt(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """إيصال بيع (documentType R) لمبيعات نقاط البيع B2C — العملاء بلا رقم ضريبي."""
    company = _company(db)
    _require_ready(company)
    order = db.query(models.SalesOrder).filter(
        models.SalesOrder.id == order_id, models.SalesOrder.company_id == company.id
    ).first()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "أمر البيع غير موجود")
    if order.status != "confirmed":  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "الإيصال يتطلب فاتورة مؤكدة")
    customer = order.customer
    if customer is not None and customer.tax_registration_number:
        raise HTTPException(status.HTTP_409_CONFLICT, "العميل مسجل ضريبيًا (B2B) — أرسلها فاتورة I لا إيصال R")
    dup = db.query(models.EtaSubmission).filter(
        models.EtaSubmission.company_id == company.id,
        models.EtaSubmission.order_id == order_id,
        models.EtaSubmission.document_type == "R",
        models.EtaSubmission.status.in_(("submitted", "valid")),
    ).first()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"الإيصال مُرسل بالفعل (حالة {dup.status})")

    products = {p.id: p for p in db.query(models.Product).filter(
        models.Product.id.in_([it.product_id for it in order.items])
    ).all()} if order.items else {}
    lines = [{
        "description": it.product_name or (products[it.product_id].name if it.product_id in products else ""),
        "product_id": it.product_id,
        "internal_code": (products[it.product_id].sku if it.product_id in products else None) or str(it.product_id),
        "unit_price": it.unit_price, "quantity": it.quantity,
    } for it in order.items]
    document = eta.build_receipt_document(
        internal_id=f"SO-{order.id}", issuer_tin=company.eta_tin or "", issuer_name=company.name,
        receiver_name=order.party_name or (customer.name if customer else "عميل نقدي"),
        lines=lines, vat_rate=float(order.tax_rate or 0),
        issued_at=order.updated_at, issuer_address=_issuer_address(company),
    )
    outs = _submit_documents(db, company, user, [document], order_ids=[order.id], return_ids=[None])
    sub = outs[0]
    sub.document_type = "R"  # type: ignore
    db.commit()
    return _out(sub)


@router.post("/submit-receipts-pending")
def submit_receipts_pending(
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """إرسال دفعي لكل إيصالات البيع المؤكدة غير المرسلة (نقاط البيع B2C) — حتى 100 لكل دفعة.

    استبعاد: أوامر العملاء المسجلين ضريبيًا (تُرسل فواتير I) والمُرسلة سابقًا."""
    company = _company(db)
    _require_ready(company)
    submitted_ids, _ = _receipt_filter_submitted(db, company.id)
    orders = (
        db.query(models.SalesOrder)
        .filter(models.SalesOrder.company_id == company.id, models.SalesOrder.status == "confirmed")
        .order_by(models.SalesOrder.id)
        .limit(200)
        .all()
    )
    documents, order_ids = [], []
    for order in orders:
        if len(documents) >= limit:
            break
        if order.id in submitted_ids:
            continue
        if order.customer is not None and order.customer.tax_registration_number:
            continue
        products = {p.id: p for p in db.query(models.Product).filter(
            models.Product.id.in_([it.product_id for it in order.items])
        ).all()} if order.items else {}
        lines = [{
            "description": it.product_name or (products[it.product_id].name if it.product_id in products else ""),
            "product_id": it.product_id,
            "internal_code": (products[it.product_id].sku if it.product_id in products else None) or str(it.product_id),
            "unit_price": it.unit_price, "quantity": it.quantity,
        } for it in order.items]
        documents.append(eta.build_receipt_document(
            internal_id=f"SO-{order.id}", issuer_tin=company.eta_tin or "", issuer_name=company.name,
            receiver_name=order.party_name or (order.customer.name if order.customer else "عميل نقدي"),
            lines=lines, vat_rate=float(order.tax_rate or 0),
            issued_at=order.updated_at, issuer_address=_issuer_address(company),
        ))
        order_ids.append(order.id)
    if not documents:
        return {"submitted": 0, "detail": "لا إيصالات مؤكدة غير مرسلة"}
    outs = _submit_documents(db, company, user, documents, order_ids=order_ids, return_ids=[None] * len(documents))
    for sub in outs:
        sub.document_type = "R"  # type: ignore
    db.commit()
    counts: dict = {}
    for o in outs:
        counts[o.status] = counts.get(o.status, 0) + 1
    return {"submitted": len(outs), "statuses": counts, "submission_uuid": outs[0].submission_uuid}


@router.get("/submissions/{submission_id}/qr.png")
def submission_qr_png(
    submission_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """QR الخاص بالإيصال للطباعة على فاتورة الكاشير — يشفّر توقيع المستند (مواصفة المنظومة)."""
    import io

    import segno

    sub = db.query(models.EtaSubmission).filter(
        models.EtaSubmission.id == submission_id,
        models.EtaSubmission.company_id == db.info["company_id"],
    ).first()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الإرسال غير موجود")
    content = sub.signature or sub.eta_uuid or sub.internal_id
    buf = io.BytesIO()
    segno.make(str(content)).save(buf, kind="png", scale=6, border=2)
    return Response(content=buf.getvalue(), media_type="image/png")


@router.post("/refresh-all")
def refresh_all_statuses(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تحديث حالة كل الإرسالات غير المحسومة (submitted) من المنظومة دفعة واحدة."""
    company = _company(db)
    client = _client_for(company)
    rows = db.query(models.EtaSubmission).filter(
        models.EtaSubmission.company_id == company.id,
        models.EtaSubmission.status == "submitted",
        models.EtaSubmission.eta_uuid.isnot(None),
    ).all()
    updated = []
    for sub in rows:
        doc = client.get_document(sub.eta_uuid)  # type: ignore[arg-type]
        if doc is None:
            continue
        new_status = str(doc.get("status") or "").lower()
        if new_status in ("valid", "invalid", "cancelled"):
            sub.status = new_status  # type: ignore
        sub.response = {**(sub.response or {}), "last_status": doc}
        sub.status_checked_at = datetime.now(timezone.utc)
        updated.append({"id": sub.id, "internal_id": sub.internal_id, "status": sub.status})
    audit(db, user, "update", "eta_submission", None, f"تحديث جماعي: {len(updated)} إرسال")
    db.commit()
    return {"checked": len(rows), "updated": updated}


# ---------------------------------------------------------------- فواتير المشتريات الواردة
@router.post("/incoming/sync")
def incoming_sync(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """سحب فواتير المشتريات الجديدة من المنظومة وتسجيلها محليًا (من دون تخزين مكرر)."""
    company = _company(db)
    _require_ready(company, need_secret=False)
    client = _client_for(company)
    try:
        docs = eta.fetch_new_purchase_documents(
            env=company.eta_env, client_id=company.eta_client_id or "", client_secret=company.eta_client_secret or "",
        )
    except eta.EtaNotConfigured as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    existing_uuids = {
        row.eta_uuid for row in db.query(models.EtaIncomingDocument.eta_uuid)
        .filter(models.EtaIncomingDocument.company_id == company.id).all()
    }
    existing_keys = {
        (row.issuer_tin, row.internal_id) for row in db.query(
            models.EtaIncomingDocument.issuer_tin, models.EtaIncomingDocument.internal_id
        ).filter(models.EtaIncomingDocument.company_id == company.id).all()
    }
    created = 0
    for d in docs:
        uuid_v = str(d.get("uuid") or "")
        issuer = d.get("issuer") or {}
        issuer_tin = str(issuer.get("id") or "") or None
        internal_id = str(d.get("internalID") or "") or None
        # منع التكرار: UUID أو (مورد + رقم فاتورة) — يحمي من إعادة الجلب بأي آلية
        if not uuid_v or uuid_v in existing_uuids or (issuer_tin, internal_id) in existing_keys:
            continue
        db.add(models.EtaIncomingDocument(
            company_id=company.id,
            eta_uuid=uuid_v,
            issuer_tin=issuer_tin,
            issuer_name=str(issuer.get("name") or "مورد غير مسمى"),
            internal_id=internal_id,
            total_amount=Decimal(str(d.get("totalAmount") or 0)),
            payload=d, status="new",
        ))
        created += 1
    audit(db, user, "sync", "eta_incoming", None, f"مزامنة واردة: {created} فاتورة جديدة")
    db.commit()
    return {"new": created}


@router.get("/incoming")
def list_incoming(
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(new|imported|ignored)$"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.EtaIncomingDocument).filter(models.EtaIncomingDocument.company_id == db.info["company_id"])
    if status_filter:
        q = q.filter(models.EtaIncomingDocument.status == status_filter)
    rows = q.order_by(models.EtaIncomingDocument.id.desc()).limit(200).all()
    return [
        {
            "id": r.id, "eta_uuid": r.eta_uuid, "issuer_tin": r.issuer_tin, "issuer_name": r.issuer_name,
            "internal_id": r.internal_id, "total_amount": r.total_amount, "status": r.status,
            "purchase_order_id": r.purchase_order_id,
            "lines": (r.payload or {}).get("invoiceLines", []),
            "received_at": r.received_at.isoformat() if r.received_at else None,
        }
        for r in rows
    ]


@router.post("/incoming/{incoming_id}/create-po")
def incoming_create_po(
    incoming_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تحويل فاتورة واردة إلى مسودة أمر شراء: المورد بالرقم الضريبي (يُنشأ إن لم يوجد)
    والأصناف بالكود الداخلي (يُنشأ الغائب) — بلا حركة مخزون حتى الاستلام اليدوي."""
    company = _company(db)
    inc = db.query(models.EtaIncomingDocument).filter(
        models.EtaIncomingDocument.id == incoming_id, models.EtaIncomingDocument.company_id == company.id
    ).first()
    if inc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الفاتورة الواردة غير موجودة")
    if inc.status != "new":
        raise HTTPException(status.HTTP_409_CONFLICT, f"الفاتورة معالجة بالفعل (حالة {inc.status})")
    warehouse = db.query(models.Warehouse).filter(
        models.Warehouse.id == payload.get("warehouse_id"), models.Warehouse.company_id == company.id
    ).first()
    if warehouse is None:
        raise HTTPException(422, "اختر مخزن الاستلام")

    from ..codegen import unique_code
    supplier = db.query(models.Supplier).filter(
        models.Supplier.company_id == company.id, models.Supplier.tax_registration_number == inc.issuer_tin
    ).first() if inc.issuer_tin else None
    if supplier is None:
        supplier = models.Supplier(
            company_id=company.id,
            name=inc.issuer_name,
            code=unique_code(db, models.Supplier, company.id, inc.issuer_name, "SUP", max_length=50),
            tax_registration_number=inc.issuer_tin,
        )
        db.add(supplier)
        db.flush()

    lines = (inc.payload or {}).get("invoiceLines", [])
    if not lines:
        raise HTTPException(422, "الفاتورة الواردة بلا بنود")
    order = models.PurchaseOrder(
        supplier_id=supplier.id, warehouse_id=warehouse.id,
        notes=f"مستوردة من المنظومة — {inc.internal_id or inc.eta_uuid[:8]}", status="draft",
    )
    total = Decimal("0")
    unmatched = []
    for ln in lines:
        code = str(ln.get("internalCode") or "")
        product = db.query(models.Product).filter(
            models.Product.company_id == company.id, models.Product.sku == code
        ).first() if code else None
        if product is None:
            product = models.Product(
                company_id=company.id, sku=code or unique_code(db, models.Product, company.id, ln.get("description", ""), "PRD", max_length=60),
                name=str(ln.get("description") or "صنف مستورد"),
                sale_price=Decimal(str(ln.get("unitPrice") or 0)) * Decimal("1.2"),
                cost_price=Decimal(str(ln.get("unitPrice") or 0)),
                quantity=0,
            )
            db.add(product)
            db.flush()
            unmatched.append(product.sku)
        qty = Decimal(str(ln.get("quantity") or 0))
        cost = Decimal(str(ln.get("unitPrice") or 0))
        order.items.append(models.PurchaseOrderItem(
            product_id=product.id, quantity=qty, unit_cost=cost,  # type: ignore
        ))
        total += cost * qty
    order.total_amount = total.quantize(Decimal("0.01"))  # type: ignore
    db.add(order)
    db.flush()
    inc.status = "imported"  # type: ignore
    inc.purchase_order_id = order.id  # type: ignore
    inc.imported_by = user.id  # type: ignore
    audit(db, user, "import", "eta_incoming", inc.id,
          f"تحويل فاتورة {inc.internal_id or inc.eta_uuid[:8]} → مسودة PO-{order.id} · {len(lines)} بند" +
          (f" · أنشئ أصناف: {unmatched[:5]}" if unmatched else ""))
    db.commit()
    db.refresh(order)
    return {"purchase_order_id": order.id, "supplier_id": supplier.id,
            "supplier_created": supplier.name, "products_created": unmatched, "total_amount": order.total_amount}


# ---------------------------------------------------------------- الإكسل الاحتياطي
@router.post("/export-template")
def export_manual_template(
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تصدير الفواتير المحددة (أو كل المعلقة) بصيغة جدول مسطح قابل للرفع اليدوي
    من بوابة المنظومة عند تعطل التكامل — ملف احتياطي لا يعطل مسار الـ API."""
    from fastapi.responses import Response as _R
    from ..exports import build_tables_xlsx, XLSX_MIME
    company = _company(db)
    wanted = set(payload.get("order_ids") or [])
    submitted_ids = {
        row.order_id for row in db.query(models.EtaSubmission.order_id).filter(
            models.EtaSubmission.company_id == company.id,
            models.EtaSubmission.document_type == "I",
            models.EtaSubmission.status.in_(("submitted", "valid")),
        ).all()
    }
    orders = (
        db.query(models.SalesOrder)
        .filter(models.SalesOrder.company_id == company.id, models.SalesOrder.status == "confirmed")
        .order_by(models.SalesOrder.id)
        .all()
    )
    rows_out = []
    for o in orders:
        if o.id in submitted_ids:
            continue
        if wanted and o.id not in wanted:
            continue
        for it in o.items:
            rows_out.append([
                ("text", f"SO-{o.id}"),
                ("text", o.party_name or ""),
                ("text", ""),
                ("text", o.currency_code or "EGP"),
                ("money", o.total_amount),
                ("text", it.product.sku if it.product else str(it.product_id)),
                ("text", it.product_name or ""),
                ("money", float(it.quantity)),
                ("money", float(it.unit_price or 0)),
                ("money", float(it.quantity * (it.unit_price or 0))),
            ])
    tables = [(
        "فواتير للبيع (صف لكل بند)",
        ["رقم الفاتورة الداخلي", "اسم العميل", "الرقم الضريبي للعميل (اختياري)", "العملة",
         "الإجمالي بالجنيه", "كود الصنف", "وصف الصنف", "الكمية", "سعر الوحدة", "إجمالي السطر"],
        rows_out,
    ), (
        "تعليمات",
        ["البند", "التفصيل"],
        [
            [("text", "الاستخدام"), ("text", "ملف احتياطي عند تعطل التكامل: ارفعه من بوابة المنظومة يدويًا")],
            [("text", "بعد الرفع اليدوي"), ("text", "ارجع هنا وحدد نفس الفواتير ثم اضغط «تحديد كمرفوعة خارجيًا» لمنع التكرار")],
            [("text", "التوقيع"), ("text", "رفع البوابة اليدوي لا يحمل توقيع C14B — البقاء على مسار الـ API هو الأصل")],
        ],
    )]
    content = build_tables_xlsx("قالب رفع يدوي — منظومة الفاتورة الإلكترونية",
                                f"{company.name} · {len(rows_out)} بند", tables)
    return _R(content=content, media_type=XLSX_MIME,
              headers={"Content-Disposition": 'attachment; filename="eta-manual-template.xlsx"'})


@router.post("/mark-external")
def mark_submitted_externally(
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """وسم فواتير كمرفوعة يدويًا من البوابة (بعد استخدام الإكسل الاحتياطي):
    تسجل submitted بمرجع خارجي فتختفي من الطابور ولا تُعاد إرسالها عبر الـ API."""
    company = _company(db)
    order_ids = set(payload.get("order_ids") or [])
    reference = str(payload.get("reference") or "").strip()
    if not order_ids:
        raise HTTPException(422, "حدد الفواتير المرفوعة خارجيًا")
    existing = {
        row.order_id for row in db.query(models.EtaSubmission.order_id).filter(
            models.EtaSubmission.company_id == company.id,
            models.EtaSubmission.document_type == "I",
            models.EtaSubmission.status.in_(("submitted", "valid")),
            models.EtaSubmission.order_id.in_(order_ids),
        ).all()
    }
    created = 0
    for oid in sorted(order_ids - existing):
        order = db.query(models.SalesOrder).filter(
            models.SalesOrder.id == oid, models.SalesOrder.company_id == company.id
        ).first()
        if order is None or order.status != "confirmed":  # type: ignore
            continue
        db.add(models.EtaSubmission(
            company_id=company.id, order_id=oid, document_type="I",
            internal_id=f"SO-{oid}", status="submitted",
            errors={"external": reference or "رفع يدوي من بوابة المنظومة"},
            submitted_by=user.id, submitted_at=datetime.now(timezone.utc),
        ))
        created += 1
    audit(db, user, "update", "eta_submission", None,
          f"وسم {created} فاتورة كمرفوعة خارجيًا ({reference or 'بدون مرجع'})")
    db.commit()
    return {"marked": created, "skipped_existing": len(existing & order_ids)}


@router.post("/incoming/import", status_code=status.HTTP_201_CREATED)
async def incoming_import(
    file: "fastapi.UploadFile" = fastapi.File(...),  # type: ignore[name-defined]
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """استيراد فواتير مشتريات من Excel (احتياطي بديل سحب الـ API).
    الأعمدة: issuerTin · issuerName · internalID · internalCode · description · quantity · unitPrice"""
    company = _company(db)
    import io as _io
    from ..exports import XLSX_MIME
    content = await file.read()
    filename = (file.filename or "").lower()
    rows_raw: list = []
    if filename.endswith(".csv"):
        import csv as _csv
        text = content.decode("utf-8-sig", errors="replace")
        rows_raw = list(_csv.DictReader(_io.StringIO(text)))
    else:
        from openpyxl import load_workbook
        wb = load_workbook(_io.BytesIO(content), data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        headers = [str(h or "").strip() for h in next(it, [])]
        for values in it:
            if all(v is None for v in values):
                continue
            rows_raw.append({headers[i]: values[i] for i in range(min(len(headers), len(values)))})

    def pick(row: dict, names: list) -> str:
        for n in names:
            if n in row and row[n] not in (None, ""):
                return str(row[n]).strip()
        return ""

    grouped: dict = {}
    order_keys: list = []
    errors: list = []
    for idx, row in enumerate(rows_raw, start=2):
        tin = pick(row, ["issuerTin", "issuer_tin", "الرقم الضريبي"])
        name = pick(row, ["issuerName", "issuer_name", "اسم المورد"]) or (f"مورد {tin}" if tin else "")
        internal = pick(row, ["internalID", "internal_id", "رقم الفاتورة"])
        code = pick(row, ["internalCode", "internal_code", "كود الصنف"])
        desc = pick(row, ["description", "description", "الصنف", "وصف الصنف"])
        qty = pick(row, ["quantity", "quantity", "الكمية"])
        price = pick(row, ["unitPrice", "unit_price", "سعر الوحدة"])
        if not (tin or name or internal):
            continue
        if not (internal and (code or desc)):
            errors.append(f"سطر {idx}: رقم الفاتورة وكود الصنف مطلوبان")
            continue
        try:
            q = Decimal(qty)
            p_ = Decimal(price)
        except Exception:
            errors.append(f"سطر {idx}: كمية/سعر غير رقمي")
            continue
        key = (tin, internal)
        if key not in grouped:
            grouped[key] = {"issuer_tin": tin, "issuer_name": name, "internal_id": internal, "lines": [], "total": Decimal("0")}
            order_keys.append(key)
        g = grouped[key]
        g["lines"].append({
            "internalCode": code, "description": desc or code,
            "quantity": float(q), "unitPrice": float(p_), "salesTotal": float((q * p_).quantize(Decimal("0.01"))),
        })
        g["total"] += (q * p_).quantize(Decimal("0.01"))

    existing_uuids = {r.eta_uuid for r in db.query(models.EtaIncomingDocument.eta_uuid).filter(
        models.EtaIncomingDocument.company_id == company.id).all()}
    existing_keys = {(r.issuer_tin, r.internal_id) for r in db.query(
        models.EtaIncomingDocument.issuer_tin, models.EtaIncomingDocument.internal_id
    ).filter(models.EtaIncomingDocument.company_id == company.id).all()}

    created = 0
    for key in order_keys:
        g = grouped[key]
        fake_uuid = "xlsx-" + __import__("hashlib").sha256(
            f"{g['issuer_tin']}|{g['internal_id']}".encode()).hexdigest()[:24]
        if fake_uuid in existing_uuids or (g["issuer_tin"], g["internal_id"]) in existing_keys:
            continue
        db.add(models.EtaIncomingDocument(
            company_id=company.id, eta_uuid=fake_uuid,
            issuer_tin=g["issuer_tin"] or None, issuer_name=g["issuer_name"] or "مورد غير مسمى",
            internal_id=g["internal_id"], total_amount=g["total"].quantize(Decimal("0.01")),
            payload={"invoiceLines": g["lines"], "issuer": {"id": g["issuer_tin"], "name": g["issuer_name"]},
                     "uuid": fake_uuid, "internalID": g["internal_id"], "source": "xlsx"},
            status="new",
        ))
        created += 1
    audit(db, user, "import", "eta_incoming", None,
          f"استيراد إكسل: {created} فاتورة جديدة · {len(errors)} خطأ")
    db.commit()
    if errors and not created:
        raise HTTPException(422, "; ".join(errors[:5]))
    return {"imported": created, "errors": errors[:10]}


# ---------------------------------------------------------------- الإعداد
@router.get("/config")
def get_config(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _masked(_company(db))


class EtaConfigIn(BaseModel):
    enabled: Optional[bool] = None
    env: Optional[str] = None
    tin: Optional[str] = Field(default=None, max_length=50)
    client_id: Optional[str] = Field(default=None, max_length=120)
    client_secret: Optional[str] = Field(default=None, max_length=255)  # كتابة فقط
    activity_code: Optional[str] = Field(default=None, max_length=20)
    address: Optional[dict] = None


@router.put("/config")
def update_config(
    payload: EtaConfigIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    company = _company(db)
    data = payload.model_dump(exclude_unset=True)
    if "env" in data and data["env"] is not None:
        if data["env"] not in ALLOWED_ENVS:
            raise HTTPException(422, "البيئة يجب أن تكون mock أو sandbox أو prod")
        company.eta_env = data["env"]
    if "enabled" in data and data["enabled"] is not None:
        company.eta_enabled = data["enabled"]
    if "tin" in data:
        company.eta_tin = (data["tin"] or "").strip() or None
    if "client_id" in data:
        company.eta_client_id = (data["client_id"] or "").strip() or None
    if "client_secret" in data and data["client_secret"]:
        company.eta_client_secret = data["client_secret"]
    if "activity_code" in data:
        company.eta_activity_code = (data["activity_code"] or "").strip() or "4690"
    if isinstance(data.get("address"), dict):
        addr = data["address"]
        company.eta_governate = (addr.get("governate") or "").strip() or None
        company.eta_region_city = (addr.get("region_city") or "").strip() or None
        company.eta_street = (addr.get("street") or "").strip() or None
        company.eta_building_number = (addr.get("building_number") or "").strip() or None
    audit(db, user, "update", "eta_config", company, f"env={company.eta_env} · enabled={company.eta_enabled} · tin={bool(company.eta_tin)}")
    db.commit()
    return _masked(company)


@router.post("/config/generate-keys")
def generate_keys(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """خطوة ما قبل التسجيل: توليد زوج مفاتيح + CSR (CN=الرقم الضريبي).
    الـ CSR يُرفع في بوابة المنظومة عند التسجيل، والخاص يُخزن للتوقيع."""
    company = _company(db)
    if not company.eta_tin:
        raise HTTPException(409, "أدخل الرقم الضريبي أولًا ثم ولّد المفاتيح")
    keys = eta.generate_keypair_and_csr(company.eta_tin, company.name)
    company.eta_private_key = keys["private_key"]
    audit(db, user, "update", "eta_config", company, "توليد زوج مفاتيح + CSR للفاتورة الإلكترونية")
    db.commit()
    return {"csr": keys["csr"], "message": "احتفظ بملف الـ CSR — ارفعه في بوابة المنظومة أثناء تسجيل الحل"}


@router.post("/config/test-connection")
def test_connection(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """اختبار جاهزية: التوكن + المفتاح (في mock ينجح دائمًا بعد اكتمال الإعداد)."""
    company = _company(db)
    _require_ready(company)
    client = _client_for(company)
    try:
        token = client._get_token()
    except eta.EtaNotConfigured as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    probe = eta.canonicalize({"probe": "ok"})
    sig = eta.sign_document({"probe": "ok"}, company.eta_private_key.encode())
    return {
        "ok": True,
        "env": company.eta_env,
        "token_prefix": token[:12] + "…",
        "signature_works": bool(sig),
        "hash_b64": __import__("base64").b64encode(__import__("hashlib").sha256(probe).digest()).decode()[:12] + "…",
    }


# ---------------------------------------------------------------- الإرسال والمتابعة
def _issuer_address(company: models.Company) -> dict:
    return {
        "governate": company.eta_governate or "",
        "regionCity": company.eta_region_city or "",
        "street": company.eta_street or "",
        "buildingNumber": company.eta_building_number or "0",
    }


def _build_payload_for_order(db: Session, company: models.Company, order: models.SalesOrder) -> dict:
    products = {p.id: p for p in db.query(models.Product).filter(
        models.Product.id.in_([it.product_id for it in order.items])
    ).all()} if order.items else {}
    lines = []
    for it in order.items:
        product = products.get(it.product_id)
        lines.append({
            "description": it.product_name or (product.name if product else f"صنف #{it.product_id}"),
            "product_id": it.product_id,
            "internal_code": (product.sku if product else None) or str(it.product_id),
            "unit_price": it.unit_price,
            "quantity": it.quantity,
        })
    customer = order.customer
    receiver_tin = (customer.tax_registration_number if customer else None) or ""
    return eta.build_document(
        document_type="I",
        internal_id=f"SO-{order.id}",
        issuer_tin=company.eta_tin or "",
        issuer_name=company.name,
        receiver_name=order.party_name or (customer.name if customer else ""),
        receiver_type="B" if receiver_tin else "P",
        receiver_id=receiver_tin,
        lines=lines,
        vat_rate=float(order.tax_rate or 0),
        issued_at=order.updated_at,
        issuer_address=_issuer_address(company),
    )


def _submit_documents(db: Session, company: models.Company, user: models.User, documents: List[dict], *, order_ids: List[Optional[int]], return_ids: List[Optional[int]]):
    """إرسال دفعة موحّد: قيد إرسال لكل مستند (يشاركان submissionUUID)، وأخطاء النقل تسجل invalid.

    الإيصالات (R) تُوقّع بمفتاح جهاز SDK النشط إن وُجد (مواصفة إيصالات المنظومة) —
    وإلا بمفتاح الشركة (في mock للتجربة)."""
    if len(documents) > 100:
        raise HTTPException(422, "أقصى حجم للدفعة 100 مستند")
    active_device = db.query(models.EtaDevice).filter(
        models.EtaDevice.company_id == company.id,
        models.EtaDevice.status == "active",
        models.EtaDevice.private_key.isnot(None),
    ).order_by(models.EtaDevice.id).first() if any(d["documentType"] == "R" for d in documents) else None
    signed: List[dict] = []
    signatures: List[str] = []
    device_ids: List[Optional[int]] = []
    for document in documents:
        if document["documentType"] == "R" and active_device is not None:
            key_pem, device_id = active_device.private_key.encode(), active_device.id  # type: ignore[union-attr]
        else:
            key_pem, device_id = company.eta_private_key.encode(), None  # type: ignore[union-attr]
        sig = eta.sign_document(document, key_pem)
        signatures.append(sig)
        device_ids.append(device_id)
        signed.append({**document, "signatures": [{"signatureType": "I", "value": sig}]})

    client = _client_for(company)
    try:
        result = client.submit_documents(signed)
    except eta.EtaNotConfigured as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Exception as exc:
        for doc, oid, rid, sig, did in zip(documents, order_ids, return_ids, signatures, device_ids):
            db.add(models.EtaSubmission(
                company_id=company.id, order_id=oid, return_id=rid, document_type=doc["documentType"],
                device_id=did, internal_id=doc["internalID"], status="invalid", signature=signatures[0],
                payload=doc, errors={"transport": str(exc)},
                submitted_by=user.id, submitted_at=datetime.now(timezone.utc),
            ))
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"تعذر الاتصال بالمنظومة: {exc}") from exc

    accepted_by_internal = {a.get("internalId"): a for a in (result.get("acceptedDocuments") or [])}
    rejected_by_internal = {r.get("internalId"): r for r in (result.get("rejectedDocuments") or [])}
    outs = []
    for doc, sig, oid, rid, did in zip(documents, signatures, order_ids, return_ids, device_ids):
        internal = doc["internalID"]
        acc = accepted_by_internal.get(internal) or {}
        rej = rejected_by_internal.get(internal)
        sub = models.EtaSubmission(
            company_id=company.id, order_id=oid, return_id=rid, document_type=doc["documentType"],
            device_id=did, internal_id=internal,
            submission_uuid=result.get("submissionUUID"),
            eta_uuid=acc.get("uuid"),
            eta_long_id=acc.get("longId"),
            status="valid" if acc.get("status") == "Valid" else ("invalid" if rej else "submitted"),
            signature=sig, payload=doc, response=result,
            errors=(rej.get("error") if rej else None),
            submitted_by=user.id, submitted_at=datetime.now(timezone.utc),
        )
        db.add(sub)
        outs.append(sub)
    audit(db, user, "submit", "eta_submission", None,
          f"إرسال {len(documents)} مستند → submission {result.get('submissionUUID')}")
    db.commit()
    for sub in outs:
        db.refresh(sub)
    return outs


@router.post("/submit/{order_id}")
def submit_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    company = _company(db)
    _require_ready(company)
    order = db.query(models.SalesOrder).filter(
        models.SalesOrder.id == order_id, models.SalesOrder.company_id == company.id
    ).first()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "أمر البيع غير موجود")
    if order.status != "confirmed":  # type: ignore
        raise HTTPException(status.HTTP_409_CONFLICT, "الفاتورة الإلكترونية تتطلب أمر بيع مؤكدًا")
    existing = db.query(models.EtaSubmission).filter(
        models.EtaSubmission.company_id == company.id,
        models.EtaSubmission.order_id == order_id,
        models.EtaSubmission.document_type == "I",
        models.EtaSubmission.status.in_(("draft", "submitted", "valid")),
    ).first()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"الفاتورة مُرسلة بالفعل (حالة {existing.status})")

    document = _build_payload_for_order(db, company, order)
    outs = _submit_documents(db, company, user, [document], order_ids=[order.id], return_ids=[None])
    return _out(outs[0])


@router.post("/submit-pending")
def submit_pending(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """إرسال دفعي لكل الفواتير المؤكدة غير المرسلة (حتى 100 لكل دفعة)."""
    company = _company(db)
    _require_ready(company)
    submitted_order_ids = {
        row.order_id for row in db.query(models.EtaSubmission.order_id).filter(
            models.EtaSubmission.company_id == company.id,
            models.EtaSubmission.document_type == "I",
            models.EtaSubmission.order_id.isnot(None),
            models.EtaSubmission.status.in_(("submitted", "valid")),
        ).all()
    }
    pending = (
        db.query(models.SalesOrder)
        .filter(models.SalesOrder.company_id == company.id, models.SalesOrder.status == "confirmed")
        .order_by(models.SalesOrder.id)
        .limit(100)
        .all()
    )
    documents, order_ids = [], []
    for order in pending:
        if order.id in submitted_order_ids:
            continue
        documents.append(_build_payload_for_order(db, company, order))
        order_ids.append(order.id)
    if not documents:
        return {"submitted": 0, "detail": "لا فواتير مؤكدة غير مرسلة"}
    outs = _submit_documents(db, company, user, documents, order_ids=order_ids, return_ids=[None] * len(documents))
    counts: dict = {}
    for o in outs:
        counts[o.status] = counts.get(o.status, 0) + 1
    return {"submitted": len(outs), "statuses": counts, "submission_uuid": outs[0].submission_uuid}


@router.post("/submit-return/{return_id}")
def submit_return(
    return_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """إشعار دائن (documentType C) لمرتجع بيع — يتطلب الفاتورة الأصلية مقبولة في المنظومة."""
    company = _company(db)
    _require_ready(company)
    ret = db.query(models.SalesReturn).filter(
        models.SalesReturn.id == return_id, models.SalesReturn.company_id == company.id
    ).first()
    if ret is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المرتجع غير موجود")
    if ret.order_id is None:
        raise HTTPException(422, "المرتجعات المستقلة (بلا أمر أصلي) تحتاج ربطها بفاتورة أصلية لإرسال إشعار دائن")
    original = db.query(models.EtaSubmission).filter(
        models.EtaSubmission.company_id == company.id,
        models.EtaSubmission.order_id == ret.order_id,
        models.EtaSubmission.document_type == "I",
        models.EtaSubmission.status == "valid",
    ).first()
    if original is None or not original.eta_uuid:
        raise HTTPException(status.HTTP_409_CONFLICT, "الفاتورة الأصلية ليست مقبولة في المنظومة بعد — أرسلها أولًا")
    dup = db.query(models.EtaSubmission).filter(
        models.EtaSubmission.company_id == company.id,
        models.EtaSubmission.return_id == return_id,
        models.EtaSubmission.status.in_(("submitted", "valid")),
    ).first()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"المرتجع مُرسل بالفعل (حالة {dup.status})")

    order = db.get(models.SalesOrder, ret.order_id)
    customer = order.customer if order else None
    product_rows = {p.id: p for p in db.query(models.Product).filter(
        models.Product.id.in_([it.product_id for it in ret.items])
    ).all()} if ret.items else {}
    lines = []
    for it in ret.items:
        product = product_rows.get(it.product_id)
        lines.append({
            "description": f"مرتجع — {it.product_name or (product.name if product else f'صنف #{it.product_id}')}",
            "product_id": it.product_id,
            "internal_code": (product.sku if product else None) or str(it.product_id),
            "unit_price": it.unit_price,
            "quantity": it.quantity,
        })
    receiver_tin = (customer.tax_registration_number if customer else None) or ""
    document = eta.build_document(
        document_type="C",
        internal_id=f"SR-{ret.id}",
        issuer_tin=company.eta_tin or "",
        issuer_name=company.name,
        receiver_name=(customer.name if customer else order.party_name if order else ""),
        receiver_type="B" if receiver_tin else "P",
        receiver_id=receiver_tin,
        lines=lines,
        vat_rate=0.0,
        issued_at=ret.created_at,
        reference={"uuid": original.eta_uuid, "internalId": original.internal_id},
        issuer_address=_issuer_address(company),
    )
    outs = _submit_documents(db, company, user, [document], order_ids=[None], return_ids=[ret.id])
    return _out(outs[0])


def _out(sub: models.EtaSubmission) -> dict:
    return {
        "id": sub.id,
        "order_id": sub.order_id,
        "document_type": sub.document_type,
        "device_id": sub.device_id,
        "internal_id": sub.internal_id,
        "submission_uuid": sub.submission_uuid,
        "eta_uuid": sub.eta_uuid,
        "eta_long_id": sub.eta_long_id,
        "status": sub.status,
        "errors": sub.errors,
        "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else None,
        "status_checked_at": sub.status_checked_at.isoformat() if sub.status_checked_at else None,
    }


@router.get("/submissions")
def list_submissions(
    response: Response,
    order_id: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="status",
                                         pattern="^(draft|submitted|valid|invalid|cancelled)$"),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.EtaSubmission).filter(models.EtaSubmission.company_id == db.info["company_id"])
    if order_id:
        q = q.filter(models.EtaSubmission.order_id == order_id)
    if status_filter:
        q = q.filter(models.EtaSubmission.status == status_filter)
    rows = paginate(q, response, skip, min(limit, 200), models.EtaSubmission.id.desc())
    return [_out(r) for r in rows]


@router.post("/refresh/{submission_id}")
def refresh_status(
    submission_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """استعلام المنظومة عن أحدث حالة للمستند وتسجيلها محليًا."""
    company = _company(db)
    sub = db.query(models.EtaSubmission).filter(
        models.EtaSubmission.id == submission_id, models.EtaSubmission.company_id == company.id
    ).first()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الإرسال غير موجود")
    if sub.eta_uuid is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يوجد معرف منظومة لهذا الإرسال بعد")
    client = _client_for(company)
    doc = client.get_document(sub.eta_uuid)
    if doc is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "تعذر الاستعلام من المنظومة")
    new_status = str(doc.get("status") or sub.status).lower()
    if new_status in ("valid", "invalid", "submitted", "cancelled"):
        sub.status = new_status  # type: ignore
    sub.response = {**(sub.response or {}), "last_status": doc}
    sub.status_checked_at = datetime.now(timezone.utc)
    audit(db, user, "update", "eta_submission", sub.id, f"تحديث حالة {sub.internal_id} → {sub.status}")
    db.commit()
    return _out(sub)


# ---------------------------------------------------------------- الأرشفة الإلكترونية
def _archive_source_docs(db: Session, company: models.Company) -> list:
    """المستندات الجاهزة للأرشفة: إرسالات مقبولة + فواتير واردة، غير المؤرشفة سابقًا."""
    archived_submission_ids = {
        row.submission_id for row in db.query(models.EtaArchive.submission_id).filter(
            models.EtaArchive.company_id == company.id,
            models.EtaArchive.source == "submission",
            models.EtaArchive.submission_id.isnot(None),
        ).all()
    }
    archived_incoming_ids = {
        row.incoming_id for row in db.query(models.EtaArchive.incoming_id).filter(
            models.EtaArchive.company_id == company.id,
            models.EtaArchive.source == "incoming",
            models.EtaArchive.incoming_id.isnot(None),
        ).all()
    }
    docs = []
    for sub in db.query(models.EtaSubmission).filter(
        models.EtaSubmission.company_id == company.id,
        models.EtaSubmission.status == "valid",
    ).order_by(models.EtaSubmission.id).all():
        if sub.id in archived_submission_ids:
            continue
        payload = sub.payload or {}
        docs.append({
            "source": "submission", "submission": sub,
            "document_type": sub.document_type, "internal_id": sub.internal_id,
            "eta_uuid": sub.eta_uuid or sub.internal_id,
            "date_time_issued": payload.get("dateTimeIssued"),
            "total_amount": payload.get("totalAmount") or 0,
            "submission_uuid": sub.submission_uuid,
            "payload": payload,
        })
    for inc in db.query(models.EtaIncomingDocument).filter(
        models.EtaIncomingDocument.company_id == company.id,
    ).order_by(models.EtaIncomingDocument.id).all():
        if inc.id in archived_incoming_ids:
            continue
        payload = inc.payload or {}
        docs.append({
            "source": "incoming", "incoming": inc,
            "document_type": "I", "internal_id": inc.internal_id or inc.eta_uuid,
            "eta_uuid": inc.eta_uuid,
            "date_time_issued": payload.get("dateTimeIssued"),
            "total_amount": inc.total_amount,
            "submission_uuid": None,
            "payload": payload,
        })
    return docs


def _archive_run(db: Session, company: models.Company, user: models.User, limit: int) -> dict:
    """أرشفة دفعة: XML لكل مستند — mock: مؤرشف فورًا · غيره: pending لحين تسجيل الخدمة."""
    docs = _archive_source_docs(db, company)[:limit]
    if not docs:
        return {"archived": 0, "pending": 0, "detail": "لا مستندات جديدة للأرشفة"}
    archived = pending = 0
    now = datetime.now(timezone.utc)
    for d in docs:
        xml = eta.build_archive_xml(
            rin=company.eta_tin or "", taxpayer_name=company.name,
            activity_code=company.eta_activity_code or "4690",
            documents=[d],
        )
        if company.eta_env == "mock":
            status, note = "archived", None
            archived += 1
        else:
            status, note = "pending", "بانتظار تسجيل خدمة الأرشفة لدى المنظومة — الـ XML جاهز"
            pending += 1
        db.add(models.EtaArchive(
            company_id=company.id,
            source=d["source"],
            submission_id=(d["submission"].id if d["source"] == "submission" else None),
            incoming_id=(d["incoming"].id if d["source"] == "incoming" else None),
            document_type=d["document_type"], internal_id=d["internal_id"], eta_uuid=d["eta_uuid"],
            total_amount=Decimal(str(d["total_amount"] or 0)),
            payload=d["payload"], xml=xml, status=status, note=note,
            archived_by=user.id, archived_at=now,
        ))
    audit(db, user, "archive", "eta_archive", None, f"أرشفة: {archived} مؤرشف · {pending} قيد الانتظار")
    db.commit()
    return {"archived": archived, "pending": pending}


@router.post("/archive/run")
def archive_run(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """أرشفة كل المستندات الجاهزة (مقبولة صادرًا + واردة) — idempotent: المؤرشف لا يتكرر."""
    company = _company(db)
    _require_ready(company, need_secret=False)
    return _archive_run(db, company, user, limit)


@router.get("/archive")
def list_archive(
    response: Response,
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(archived|pending|failed)$"),
    source: Optional[str] = Query(None, pattern="^(submission|incoming)$"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """سجل الأرشفة: كل مستند مؤرشف بمرجعه وحالته."""
    q = db.query(models.EtaArchive).filter(models.EtaArchive.company_id == db.info["company_id"])
    if status_filter:
        q = q.filter(models.EtaArchive.status == status_filter)
    if source:
        q = q.filter(models.EtaArchive.source == source)
    rows = paginate(q, response, skip, limit, models.EtaArchive.id.desc())
    return [
        {
            "id": r.id, "source": r.source, "document_type": r.document_type,
            "internal_id": r.internal_id, "eta_uuid": r.eta_uuid,
            "total_amount": r.total_amount, "status": r.status, "note": r.note,
            "submission_id": r.submission_id, "incoming_id": r.incoming_id,
            "archived_at": r.archived_at.isoformat() if r.archived_at else None,
        }
        for r in rows
    ]


@router.get("/archive/{archive_id}/xml")
def archive_xml(
    archive_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """تنزيل XML المستند المؤرشف (لرفعه يدويًا أو للمراجعة)."""
    row = db.query(models.EtaArchive).filter(
        models.EtaArchive.id == archive_id,
        models.EtaArchive.company_id == db.info["company_id"],
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "سجل الأرشفة غير موجود")
    if not row.xml:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يوجد XML لهذا السجل")
    return Response(
        content=row.xml.encode("utf-8"),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="eta-archive-{row.id}.xml"'},
    )


# ---------------------------------------------------------------- أجهزة SDK المسجلة للإيصالات
class EtaDeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    serial: str = Field(min_length=1, max_length=80)


def _get_device(db: Session, company: models.Company, device_id: int) -> models.EtaDevice:
    dev = db.query(models.EtaDevice).filter(
        models.EtaDevice.id == device_id, models.EtaDevice.company_id == company.id
    ).first()
    if dev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الجهاز غير موجود")
    return dev


def _device_out(d: models.EtaDevice) -> dict:
    return {
        "id": d.id, "name": d.name, "serial": d.serial, "status": d.status,
        "has_keys": bool(d.private_key),
        "csr": d.csr,
        "activated_at": d.activated_at.isoformat() if d.activated_at else None,
        "revoked_at": d.revoked_at.isoformat() if d.revoked_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("/devices")
def list_devices(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """أجهزة SDK المسجلة لإيصالات المنظومة — المفاتيح لا تُرجع نصًا كاملًا أبدًا."""
    company = _company(db)
    rows = db.query(models.EtaDevice).filter(
        models.EtaDevice.company_id == company.id
    ).order_by(models.EtaDevice.id.desc()).all()
    return [_device_out(d) for d in rows]


@router.post("/devices", status_code=status.HTTP_201_CREATED)
def create_device(
    payload: EtaDeviceIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تسجيل جهاز إيصالات: زوج مفاتيح + CSR للجهاز — CSR يُرفع في بوابة المنظومة،
    وبعد إشعار المنظومة يتتفعل من نقطة التفعيل."""
    company = _company(db)
    _require_ready(company, need_secret=False)
    serial = payload.serial.strip()
    if db.query(models.EtaDevice).filter(
        models.EtaDevice.company_id == company.id, models.EtaDevice.serial == serial
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "جهاز بنفس الرقم التسلسلي مسجل بالفعل")
    keys = eta.generate_keypair_and_csr(company.eta_tin or serial, company.name)
    dev = models.EtaDevice(
        company_id=company.id, name=payload.name.strip(), serial=serial,
        private_key=keys["private_key"], public_key=keys["public_key"], csr=keys["csr"],
        registered_by=user.id,
    )
    db.add(dev)
    audit(db, user, "create", "eta_device", None, f"جهاز {serial} — CSR للتسجيل في البوابة")
    db.commit()
    db.refresh(dev)
    return _device_out(dev)


@router.post("/devices/{device_id}/activate")
def activate_device(
    device_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """تفعيل جهاز بعد رفع CSR في بوابة المنظومة — بعدها إيصالات هذا الجهاز تُوقّع بمفاتيحه."""
    company = _company(db)
    dev = _get_device(db, company, device_id)
    if dev.status == "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "الجهاز مفعّل بالفعل")
    if dev.status == "revoked":
        raise HTTPException(status.HTTP_409_CONFLICT, "الجهاز ملغى ولا يُفعَّل — سجّل جهازًا جديدًا")
    if not dev.private_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا مفاتيح للجهاز — أعد تسجيله")
    dev.status = "active"  # type: ignore
    dev.activated_at = datetime.now(timezone.utc)  # type: ignore
    audit(db, user, "update", "eta_device", dev.id, f"تفعيل جهاز {dev.serial} لتوقيع الإيصالات")
    db.commit()
    return _device_out(dev)


@router.post("/devices/{device_id}/revoke")
def revoke_device(
    device_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """إلغاء جهاز (فقد/تغيير كاشير/إعادة تسجيل) — الإيصالات تعود لمفتاح الشركة."""
    company = _company(db)
    dev = _get_device(db, company, device_id)
    if dev.status == "revoked":
        raise HTTPException(status.HTTP_409_CONFLICT, "الجهاز ملغى بالفعل")
    dev.status = "revoked"  # type: ignore
    dev.revoked_at = datetime.now(timezone.utc)  # type: ignore
    audit(db, user, "update", "eta_device", dev.id, f"إلغاء جهاز {dev.serial}")
    db.commit()
    return _device_out(dev)


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """حذف جهاز — مفعّل فقط بعد إلغائه حفاظًا على سجل التوقيعات."""
    company = _company(db)
    dev = _get_device(db, company, device_id)
    if dev.status == "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "الجهاز مفعّل — ألغِه أولًا ثم احذفه")
    db.delete(dev)
    audit(db, user, "delete", "eta_device", dev.id, f"حذف جهاز {dev.serial}")
    db.commit()
