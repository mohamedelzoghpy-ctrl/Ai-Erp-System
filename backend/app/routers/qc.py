"""الجودة بمعايير قابلة للقياس: نماذج الفحص، ربطها بالمنتجات، ونتائج قياس الدفعات."""

from datetime import date
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/qc", tags=["quality"])


# ---------- Schemas ----------

class QcParameterIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    unit: Optional[str] = Field(default=None, max_length=30)
    param_type: Literal["number", "bool"] = "number"
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class QcTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=255)
    is_active: bool = True
    parameters: List[QcParameterIn] = []


class QcParameterOut(BaseModel):
    id: int
    name: str
    unit: Optional[str] = None
    param_type: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class QcTemplateOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    parameters: List[QcParameterOut] = []


class ProductQcOut(BaseModel):
    product_id: int
    template_ids: List[int] = []


class ProductQcIn(BaseModel):
    template_ids: List[int] = []


class QcMeasurementIn(BaseModel):
    parameter_id: int
    value_num: Optional[float] = None
    value_text: Optional[str] = Field(default=None, max_length=200)
    pass_fail: Optional[bool] = None


class QcMeasurementsIn(BaseModel):
    results: List[QcMeasurementIn] = []


class QcResultRow(BaseModel):
    parameter_id: Optional[int] = None
    parameter_name: str
    unit: Optional[str] = None
    value_num: Optional[float] = None
    value_text: Optional[str] = None
    pass_fail: Optional[bool] = None
    attempt: int = 1


class QcMeasurementsOut(BaseModel):
    batch_id: int
    attempt: int = 1                 # محاولة الفحص الحالية المعروضة
    attempts_count: int = 1          # إجمالي محاولات الفحص المسجلة
    overall_pass: Optional[bool] = None
    results: List[QcResultRow] = []


# ---------- Helpers ----------

def _template_out(db: Session, tpl: models.QcTemplate) -> QcTemplateOut:
    return QcTemplateOut(
        id=tpl.id,
        name=tpl.name,
        description=tpl.description,
        is_active=tpl.is_active,
        parameters=[
            QcParameterOut(id=p.id, name=p.name, unit=p.unit, param_type=p.param_type, min_value=p.min_value, max_value=p.max_value)
            for p in tpl.parameters
        ],
    )


def _get_template(db: Session, template_id: int, company_id: int) -> models.QcTemplate:
    tpl = db.get(models.QcTemplate, template_id)
    if tpl is None or tpl.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "نموذج الفحص غير موجود")
    return tpl


# ---------- النماذج ----------

@router.get("/templates", response_model=List[QcTemplateOut])
def list_templates(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    templates = (
        db.query(models.QcTemplate)
        .filter(models.QcTemplate.company_id == db.info["company_id"])
        .order_by(models.QcTemplate.id.desc())
        .all()
    )
    return [_template_out(db, t) for t in templates]


@router.post("/templates", response_model=QcTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(payload: QcTemplateIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    company_id = db.info["company_id"]
    dup = db.query(models.QcTemplate).filter(
        models.QcTemplate.company_id == company_id, models.QcTemplate.name == payload.name.strip()
    ).first()
    if dup is not None:
        raise HTTPException(422, "يوجد نموذج فحص بنفس الاسم")
    tpl = models.QcTemplate(company_id=company_id, name=payload.name.strip(), description=payload.description, is_active=payload.is_active)  # type: ignore
    db.add(tpl)
    db.flush()
    for p in payload.parameters:
        db.add(models.QcParameter(
            company_id=company_id,  # type: ignore
            template_id=tpl.id,  # type: ignore
            name=p.name.strip(),  # type: ignore
            unit=p.unit,
            param_type=p.param_type,  # type: ignore
            min_value=p.min_value,
            max_value=p.max_value,
        ))
    audit(db, user, "create", "qc_template", tpl, f"{tpl.name} · {len(payload.parameters)} معيار")
    db.commit()
    db.refresh(tpl)
    return _template_out(db, tpl)


@router.put("/templates/{template_id}", response_model=QcTemplateOut)
def update_template(template_id: int, payload: QcTemplateIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    company_id = db.info["company_id"]
    tpl = _get_template(db, template_id, company_id)
    tpl.name = payload.name.strip()  # type: ignore
    tpl.description = payload.description  # type: ignore
    tpl.is_active = payload.is_active  # type: ignore
    db.query(models.QcParameter).filter(models.QcParameter.template_id == tpl.id).delete(synchronize_session=False)
    db.flush()
    for p in payload.parameters:
        db.add(models.QcParameter(
            company_id=company_id,  # type: ignore
            template_id=tpl.id,  # type: ignore
            name=p.name.strip(),  # type: ignore
            unit=p.unit,
            param_type=p.param_type,  # type: ignore
            min_value=p.min_value,
            max_value=p.max_value,
        ))
    audit(db, user, "update", "qc_template", tpl, f"{tpl.name} · {len(payload.parameters)} معيار")
    db.commit()
    db.refresh(tpl)
    return _template_out(db, tpl)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    company_id = db.info["company_id"]
    tpl = _get_template(db, template_id, company_id)
    used = db.query(models.QcProductRequirement).filter(models.QcProductRequirement.template_id == tpl.id).count()
    if used:
        raise HTTPException(400, f"النموذج مربوط بـ {used} منتج — افصل الربط أولاً")
    audit(db, user, "delete", "qc_template", tpl, f"حذف نموذج فحص: {tpl.name}")
    db.delete(tpl)
    db.commit()
    return None


# ---------- ربط النماذج بالمنتجات ----------

@router.get("/products/{product_id}", response_model=ProductQcOut)
def get_product_requirements(product_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.query(models.QcProductRequirement).filter(
        models.QcProductRequirement.company_id == db.info["company_id"],
        models.QcProductRequirement.product_id == product_id,
    ).all()
    return ProductQcOut(product_id=product_id, template_ids=[r.template_id for r in rows])


@router.put("/products/{product_id}", response_model=ProductQcOut)
def set_product_requirements(product_id: int, payload: ProductQcIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    company_id = db.info["company_id"]
    product = db.get(models.Product, product_id)
    if product is None or product.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المنتج غير موجود")
    for tid in payload.template_ids:
        tpl = db.get(models.QcTemplate, tid)
        if tpl is None or tpl.company_id != company_id:
            raise HTTPException(422, f"نموذج فحص غير موجود: {tid}")
    db.query(models.QcProductRequirement).filter(
        models.QcProductRequirement.company_id == company_id,
        models.QcProductRequirement.product_id == product_id,
    ).delete(synchronize_session=False)
    for tid in set(payload.template_ids):
        db.add(models.QcProductRequirement(company_id=company_id, product_id=product_id, template_id=tid))
    audit(db, user, "update", "qc_product_requirements", product_id, f"نماذج فحص المنتج #{product_id}: {sorted(set(payload.template_ids))}")
    db.commit()
    return ProductQcOut(product_id=product_id, template_ids=sorted(set(payload.template_ids)))


# ---------- نتائج قياس الدفعات ----------

def _batch_or_404(db: Session, batch_id: int) -> models.ProductionBatch:
    batch = db.get(models.ProductionBatch, batch_id)
    if batch is None or batch.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الدفعة غير موجودة")
    return batch


def _latest_attempt(db: Session, batch_id: int) -> int:
    # عداد المحاولة محفوظ على الدفعة نفسها — إعادة الفحص تزيده حتى مع قياسات فارغة
    batch = db.get(models.ProductionBatch, batch_id)
    return int(getattr(batch, "qc_attempt", 1) or 1) if batch else 1


@router.get("/batches/{batch_id}/results", response_model=QcMeasurementsOut)
def get_batch_results(batch_id: int, all_attempts: bool = False, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """قياسات الدفعة — آخر محاولة افتراضياً، وكل المحاولات مع ?all_attempts=true (لإعادة الفحص)."""
    _batch_or_404(db, batch_id)
    attempts_count = _latest_attempt(db, batch_id)
    attempt = attempts_count if not all_attempts else 0
    q = db.query(models.BatchQcResult).filter(models.BatchQcResult.batch_id == batch_id)
    if not all_attempts:
        q = q.filter(models.BatchQcResult.attempt == attempts_count)
    rows = q.order_by(models.BatchQcResult.attempt, models.BatchQcResult.id).all()
    current = [r for r in rows if r.attempt == attempts_count]
    overall = None
    if current and all(r.pass_fail is not None for r in current):
        overall = all(bool(r.pass_fail) for r in current)
    return QcMeasurementsOut(
        batch_id=batch_id,
        attempt=attempts_count,
        attempts_count=attempts_count,
        overall_pass=overall,
        results=[QcResultRow(
            parameter_id=r.parameter_id, parameter_name=r.parameter_name, unit=r.unit,
            value_num=r.value_num, value_text=r.value_text, pass_fail=r.pass_fail,
            attempt=r.attempt,
        ) for r in rows],
    )


@router.post("/batches/{batch_id}/results", response_model=QcMeasurementsOut)
def record_batch_measurements(batch_id: int, payload: QcMeasurementsIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """تسجيل قياسات معايير الجودة لدفعة — الحكم الرقمي يُحسب تلقائيًا من النطاق إن لم يُرسل."""
    batch = _batch_or_404(db, batch_id)
    company_id = db.info["company_id"]
    if not payload.results:
        raise HTTPException(422, "لا توجد قياسات للتسجيل")
    out_rows: List[QcResultRow] = []
    for item in payload.results:
        param = db.get(models.QcParameter, item.parameter_id)
        if param is None or param.company_id != company_id:
            raise HTTPException(422, f"معيار غير موجود: {item.parameter_id}")
        pass_fail = item.pass_fail
        if pass_fail is None and param.param_type == "number" and item.value_num is not None:
            within_min = param.min_value is None or item.value_num >= float(param.min_value)
            within_max = param.max_value is None or item.value_num <= float(param.max_value)
            pass_fail = within_min and within_max
        if pass_fail is None and param.param_type == "bool" and item.value_text is not None:
            pass_fail = item.value_text.strip().lower() in ("مطابق", "yes", "true", "1", "ok", "pass")
        attempt = _latest_attempt(db, batch_id)
        existing = db.query(models.BatchQcResult).filter(
            models.BatchQcResult.batch_id == batch_id,
            models.BatchQcResult.attempt == attempt,
            models.BatchQcResult.parameter_id == param.id,
        ).first()
        if existing is None:
            existing = models.BatchQcResult(
                company_id=company_id,  # type: ignore
                batch_id=batch_id,  # type: ignore
                attempt=attempt,  # type: ignore
                parameter_id=param.id,  # type: ignore
                template_id=param.template_id,  # type: ignore
                parameter_name=param.name,  # type: ignore
            )
            db.add(existing)
        existing.unit = param.unit
        existing.value_num = item.value_num
        existing.value_text = item.value_text
        existing.pass_fail = pass_fail
        existing.recorded_by = user.id  # type: ignore
        out_rows.append(QcResultRow(
            parameter_id=param.id, parameter_name=param.name, unit=param.unit,
            value_num=item.value_num, value_text=item.value_text, pass_fail=pass_fail,
        ))
    overall = None
    if out_rows and all(r.pass_fail is not None for r in out_rows):
        overall = all(bool(r.pass_fail) for r in out_rows)
    audit(db, user, "update", "batch_qc_measurements", batch, f"قياسات جودة الدفعة {batch.batch_no} — الحكم: {'مطابق' if overall else ('غير مطابق' if overall is False else 'جزئي')}")
    db.commit()
    attempt = _latest_attempt(db, batch_id)
    return QcMeasurementsOut(batch_id=batch_id, attempt=attempt, attempts_count=attempt, overall_pass=overall, results=out_rows)


@router.post("/batches/{batch_id}/release", response_model=dict)
def release_batch_qc(
    batch_id: int,
    action: Literal["passed", "rejected"],
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """اعتماد الجودة والإفراج عن الدفعة (QC Release / Reject):
    - passed: تُعتمد الدفعة ويُسمح بصرفها واستخدامها في أوامر البيع.
    - rejected: تُرفض الدفعة وتُحجز من المخزون مع خصم قيمتها ونقلها إلى حساب الهالك."""
    batch = _batch_or_404(db, batch_id)
    if batch.qc_status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"الدفعة مفحوصة بالفعل وحالتها: {batch.qc_status}")
    
    # استدعاء منطق الفحص الرسمي المرتبط بأمر التصنيع
    from ..routers.manufacturing import qc_production_batch
    from .. import schemas as _schemas
    qc_production_batch(
        order_id=batch.order_id,
        batch_id=batch.id,
        payload=_schemas.BatchQcIn(result=action, notes=notes),
        db=db,
        user=user,
    )
    db.refresh(batch)
    return {
        "batch_id": batch.id,
        "batch_no": batch.batch_no,
        "order_id": batch.order_id,
        "qc_status": batch.qc_status,
        "notes": batch.notes,
    }

@router.post("/batches/{batch_id}/retest", response_model=QcMeasurementsOut)
def retest_batch_qc(batch_id: int, notes: Optional[str] = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """إعادة فحص الدفعة: تفتح محاولة قياس جديدة (رقم أعلى) والقياسات السابقة تُحفظ كسجل.
    الدفعة تبقى pending حتى الحكم النهائي (passed/rejected)."""
    batch = _batch_or_404(db, batch_id)
    if batch.qc_status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"الدفعة مفحوصة نهائياً وحالتها: {batch.qc_status} — إعادة الفحص قبل الحكم النهائي فقط")
    new_attempt = int(batch.qc_attempt or 1) + 1
    batch.qc_attempt = new_attempt
    audit(db, user, "update", "batch_qc_retest", batch, f"إعادة فحص الدفعة {batch.batch_no} — محاولة {new_attempt}" + (f" — {notes}" if notes else ""))
    db.commit()
    db.refresh(batch)
    return QcMeasurementsOut(batch_id=batch_id, attempt=new_attempt, attempts_count=new_attempt, overall_pass=None, results=[])
