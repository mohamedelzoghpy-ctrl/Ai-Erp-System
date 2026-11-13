"""CRM خفيف — العملاء المحتملون ومراحل البيع والأنشطة والتحويل لعميل فعلي."""
from decimal import Decimal
from typing import List, Optional

from datetime import datetime, timedelta as _td, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_permission_or_role

router = APIRouter(
    prefix="/crm",
    tags=["crm"],
    dependencies=[Depends(get_current_user)],
)

_LEAD_STATUSES = ("new", "contacted", "qualified", "won", "lost")

STAGE_AR = {"new": "جديد", "contacted": "تم التواصل", "qualified": "مؤهل", "won": "تحوّل لعميل", "lost": "مفقود"}


def _get_lead(db: Session, lead_id: int) -> models.CrmLead:
    lead = db.get(models.CrmLead, lead_id)
    if lead is None or lead.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    return lead


@router.get("/leads", response_model=List[schemas.CrmLeadOut])
def list_leads(
    response: Response,
    status_filter: Optional[schemas.LeadStatus] = Query(None, alias="status"),
    rep_id: Optional[int] = None,
    search: Optional[str] = Query(None, max_length=100, description="بحث بالاسم/الشركة/الهاتف"),
    follow_up: Optional[str] = Query(None, pattern="^(today|overdue)$", description="متابعات اليوم أو المتأخرة"),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    company_id = db.info["company_id"]
    q = db.query(models.CrmLead).filter(models.CrmLead.company_id == company_id)
    if status_filter:
        q = q.filter(models.CrmLead.status == status_filter)
    if rep_id:
        q = q.filter(models.CrmLead.assigned_rep_id == rep_id)
    if follow_up:
        from ..accounting import local_today
        from ..exports import LOCAL_TZ
        from datetime import datetime as _dt, time as _time, timezone as _tz
        today = local_today()
        day_start = _dt.combine(today, _time.min, tzinfo=LOCAL_TZ)
        today_start_u = day_start.astimezone(_tz.utc).replace(tzinfo=None)
        tomorrow_u = (day_start + _td(days=1)).astimezone(_tz.utc).replace(tzinfo=None)
        q = q.filter(models.CrmLead.next_follow_up_at.isnot(None), models.CrmLead.status.notin_(("won", "lost")))
        if follow_up == "today":
            q = q.filter(models.CrmLead.next_follow_up_at >= today_start_u, models.CrmLead.next_follow_up_at < tomorrow_u)
        else:  # overdue
            q = q.filter(models.CrmLead.next_follow_up_at < today_start_u)
    if search:
        needle = f"%{search.strip()}%"
        q = q.filter(
            models.CrmLead.name.ilike(needle)
            | models.CrmLead.company_name.ilike(needle)
            | models.CrmLead.phone.ilike(needle)
        )
    q = q.order_by(models.CrmLead.id.desc())
    total = q.count()
    response.headers["X-Total-Count"] = str(total)
    return q.offset(skip).limit(min(limit, 200)).all()


@router.get("/leads/check-duplicate", response_model=schemas.DuplicateCheckOut)
def check_duplicate(
    phone: str = Query(min_length=3, max_length=50),
    db: Session = Depends(get_db),
):
    """فحص حي لتكرار رقم هاتف قائد مقابل القادة والعملاء الحاليين."""
    return schemas.DuplicateCheckOut(phone=phone.strip(), duplicates=_phone_duplicates(db, db.info["company_id"], phone))


@router.get("/leads/{obj_id}", response_model=schemas.CrmLeadOut)
def get_lead(obj_id: int, db: Session = Depends(get_db)):
    return _get_lead(db, obj_id)


def _phone_duplicates(db: Session, company_id: int, phone: str, exclude_lead_id: Optional[int] = None) -> list:
    """مطابقات رقم الهاتف عبر القادة الحاليين والعملاء الفعليين."""
    needle = phone.strip()
    if not needle:
        return []
    matches: list = []
    q = db.query(models.CrmLead).filter(
        models.CrmLead.company_id == company_id,
        models.CrmLead.phone == needle,
        models.CrmLead.status.notin_(("lost",)),
    )
    if exclude_lead_id:
        q = q.filter(models.CrmLead.id != exclude_lead_id)
    for l in q.all():
        matches.append({"kind": "lead", "id": l.id, "name": l.name, "phone": l.phone, "code": l.code})
    for c in db.query(models.Customer).filter(
        models.Customer.company_id == company_id, models.Customer.phone == needle
    ).all():
        matches.append({"kind": "customer", "id": c.id, "name": c.name, "phone": c.phone, "code": c.code})
    return matches


@router.post("/leads", response_model=schemas.CrmLeadOut, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: schemas.CrmLeadCreate,
    force: bool = Query(False, description="تجاوز تحذير التكرار"),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_permission_or_role("crm.lead.create", "admin", "manager")),
):
    company_id = db.info["company_id"]
    if payload.phone and payload.phone.strip():
        matches = _phone_duplicates(db, company_id, payload.phone)
        if matches and not force:
            raise HTTPException(status.HTTP_409_CONFLICT, {"message": "يوجد قائد/عميل بنفس رقم الهاتف", "duplicates": matches})
    data = payload.model_dump()
    if payload.assigned_rep_id is not None:
        rep = db.get(models.SalesRep, payload.assigned_rep_id)
        if rep is None or rep.company_id != company_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Assigned rep does not exist in this company")
    code = (payload.code or "").strip() or unique_code(db, models.CrmLead, company_id, payload.name, "LEAD", max_length=50)
    if db.query(models.CrmLead).filter(models.CrmLead.company_id == company_id, models.CrmLead.code == code).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Lead code already exists")
    lead = models.CrmLead(company_id=company_id, code=code, created_by=user.id, **{k: v for k, v in data.items() if k != "code"})
    db.add(lead)
    db.commit()
    db.refresh(lead)
    audit(db, user, "create", "crm_lead", lead, f"{lead.code} · {lead.name}")
    return lead


@router.patch("/leads/{obj_id}", response_model=schemas.CrmLeadOut)
def update_lead(
    obj_id: int,
    payload: schemas.CrmLeadUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_permission_or_role("crm.lead.update", "admin", "manager")),
):
    lead = _get_lead(db, obj_id)
    old_status = lead.status
    data = payload.model_dump(exclude_unset=True)
    if data.get("assigned_rep_id") is not None:
        rep = db.get(models.SalesRep, data["assigned_rep_id"])
        if rep is None or rep.company_id != db.info["company_id"]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Assigned rep does not exist in this company")
    if "name" in data and data["name"] is not None:
        lead.name = data["name"].strip()
    for field in ("company_name", "phone", "email", "address", "source", "status", "expected_value", "assigned_rep_id", "next_follow_up_at", "lost_reason", "notes"):
        if field in data and data[field] is not None:
            setattr(lead, field, data[field])
    # النقل إلى lost يتطلب سببًا
    if data.get("status") == "lost" and not (data.get("lost_reason") or lead.lost_reason or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "سبب الفقد مطلوب عند نقل القائد إلى مفقود")
    # سجل نظامي عند تغيير المرحلة
    new_status = data.get("status")
    if new_status and new_status != old_status:
        sys_body = f"تغيّرت المرحلة: {STAGE_AR.get(old_status, old_status)} ← {STAGE_AR.get(new_status, new_status)}"
        if new_status == "lost" and (data.get("lost_reason") or "").strip():
            sys_body += f" — السبب: {data['lost_reason'].strip()}"
        db.add(models.CrmActivity(
            company_id=lead.company_id, lead_id=lead.id, kind="system", body=sys_body, created_by=user.id,
        ))
    db.commit()
    db.refresh(lead)
    audit(db, user, "update", "crm_lead", lead, ", ".join(data.keys()))
    return lead


@router.delete("/leads/{obj_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(
    obj_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_permission_or_role("crm.lead.delete", "admin", "manager")),
):
    lead = _get_lead(db, obj_id)
    db.delete(lead)
    db.commit()
    audit(db, user, "delete", "crm_lead", obj_id, f"lead {obj_id}")


@router.post("/leads/{obj_id}/convert", response_model=schemas.CrmLeadOut)
def convert_lead(
    obj_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_permission_or_role("crm.lead.convert", "admin", "manager")),
):
    """تحويل عميل محتمل إلى عميل فعلي: يُنشئ سجلاً في العملاء بكود CUS، ووسم القائد بـ won."""
    lead = _get_lead(db, obj_id)
    if lead.converted_customer_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Lead already converted")
    company_id = db.info["company_id"]
    customer = models.Customer(
        company_id=company_id,
        code=unique_code(db, models.Customer, company_id, lead.company_name or lead.name, "CUS", max_length=50),
        name=lead.company_name or lead.name,
        contact_person=lead.name if lead.company_name else None,
        phone=lead.phone,
        email=lead.email,
        address=lead.address,
    )
    db.add(customer)
    db.flush()
    lead.converted_customer_id = customer.id
    lead.status = "won"
    db.add(models.CrmActivity(
        company_id=lead.company_id, lead_id=lead.id, kind="system",
        body=f"تحوّل لعميل فعلي ({customer.code}) — بنجاح الفوز", created_by=user.id,
    ))
    db.commit()
    db.refresh(lead)
    audit(db, user, "convert", "crm_lead", lead, f"→ customer {customer.code}")
    return lead


@router.post("/leads/{obj_id}/quotation")
def create_lead_quotation(
    obj_id: int,
    payload: schemas.LeadQuotationIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_permission_or_role("crm.lead.convert", "admin", "manager")),
):
    """عرض سعر مباشر من القائد: يحوّله لعميل فعلي إن لم يتحول، ثم ينشئ عرض سعر مربوطًا به (قائد ← عرض ← أمر ← عميل)."""
    lead = _get_lead(db, obj_id)
    company_id = db.info["company_id"]
    warehouse = db.get(models.Warehouse, payload.warehouse_id)
    if warehouse is None or warehouse.company_id != company_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "المخزن غير موجود")
    for it in payload.items:
        prod = db.get(models.Product, it.product_id)
        if prod is None or prod.company_id != company_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"الصنف {it.product_id} غير موجود")

    # تحويل ضمني عند الحاجة
    if lead.converted_customer_id is None:
        lead = convert_lead(obj_id=obj_id, db=db, user=user)
        db.refresh(lead)
    customer_id = lead.converted_customer_id
    assert customer_id is not None

    from ..routers.orders import create_sales_order
    from starlette.requests import Request as _Req
    fake_request = _Req({"type": "http", "method": "POST", "headers": [], "query_string": b"", "state": {}})
    so_payload = schemas.SalesOrderCreate(
        customer_id=customer_id,
        warehouse_id=payload.warehouse_id,
        notes=(payload.notes or f"عرض سعر من القائد {lead.code}").strip(),
        document_type="quotation",
        lead_id=lead.id,
        items=[schemas.SalesItemIn(product_id=it.product_id, quantity=it.quantity, unit_price=it.unit_price) for it in payload.items],
    )
    order = create_sales_order(request=fake_request, payload=so_payload, db=db, user=user)
    total = sum(float(it.quantity) * float(it.unit_price) for it in payload.items)
    db.add(models.CrmActivity(
        company_id=company_id, lead_id=lead.id, kind="system",
        body=f"عُرض سعر رقم SO-{order.id} بقيمة {total:.2f}", created_by=user.id,
    ))
    db.commit()
    return {"lead_id": lead.id, "lead_status": lead.status, "converted_customer_id": lead.converted_customer_id,
            "quotation": {"id": order.id, "code": f"SO-{order.id}", "status": order.status}}


@router.get("/reports/funnel", response_model=schemas.CrmFunnelOut)
def crm_funnel(db: Session = Depends(get_db)):
    """قمع التحويل: كل مرحلة بالعدد والقيمة + معدل الفوز ومتوسط الصفقة وعمرها."""
    company_id = db.info["company_id"]
    leads = db.query(models.CrmLead).filter(models.CrmLead.company_id == company_id).all()
    stages = []
    open_value = Decimal("0")
    for st in _LEAD_STATUSES:
        rows = [l for l in leads if l.status == st]
        val = sum((Decimal(str(l.expected_value or 0)) for l in rows), Decimal("0"))
        if st in ("new", "contacted", "qualified"):
            open_value += val
        stages.append(schemas.FunnelStageRow(stage=st, count=len(rows), expected_value=val))
    won = [l for l in leads if l.status == "won"]
    lost = [l for l in leads if l.status == "lost"]
    won_value = sum((Decimal(str(l.expected_value or 0)) for l in won), Decimal("0"))
    decided = len(won) + len(lost)
    win_rate = round(100.0 * len(won) / decided, 1) if decided else None
    avg_won = (won_value / len(won)).quantize(Decimal("0.01")) if won else None
    days = [max(0, (l.updated_at - l.created_at).days) for l in won if l.updated_at and l.created_at]
    avg_days = round(sum(days) / len(days), 1) if days else None
    return schemas.CrmFunnelOut(
        stages=stages, open_pipeline_value=open_value,
        won_count=len(won), won_value=won_value,
        lost_count=len(lost), win_rate_pct=win_rate,
        avg_won_value=avg_won, avg_days_to_win=avg_days,
    )


@router.get("/reports/sources", response_model=List[schemas.CrmSourceRow])
def crm_sources(db: Session = Depends(get_db)):
    """أداء مصادر البيع: أي مصدر يجيب عملاء فعليين؟"""
    company_id = db.info["company_id"]
    leads = db.query(models.CrmLead).filter(models.CrmLead.company_id == company_id).all()
    by_source: dict = {}
    for l in leads:
        b = by_source.setdefault(l.source or "other", {"count": 0, "won": 0, "lost": 0, "open": 0, "won_value": Decimal("0")})
        b["count"] += 1
        if l.status == "won":
            b["won"] += 1
            b["won_value"] += Decimal(str(l.expected_value or 0))
        elif l.status == "lost":
            b["lost"] += 1
        else:
            b["open"] += 1
    out = []
    for src_name, b in sorted(by_source.items(), key=lambda kv: -kv[1]["won_value"]):
        decided = b["won"] + b["lost"]
        out.append(schemas.CrmSourceRow(
            source=src_name, count=b["count"], won_count=b["won"], lost_count=b["lost"],
            open_count=b["open"], won_value=b["won_value"],
            win_rate_pct=round(100.0 * b["won"] / decided, 1) if decided else None,
        ))
    return out


@router.post("/activities/{activity_id}/complete", response_model=schemas.CrmActivityOut)
def toggle_task_complete(
    activity_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_permission_or_role("crm.lead.update", "admin", "manager")),
):
    """إتمام/إعادة فتح مهمة مجدولة."""
    row = db.get(models.CrmActivity, activity_id)
    if row is None or row.company_id != db.info["company_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "النشاط غير موجود")
    if row.kind != "task":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الإتمام للمهام فقط")
    row.done_at = None if row.done_at else datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    audit(db, user, "update", "crm_task", row, f"مهمة #{row.id}: {'أُتمت' if row.done_at else 'أُعيد فتحها'}")
    return row


@router.get("/tasks", response_model=List[schemas.CrmTaskOut])
def list_tasks(
    status_filter: Optional[str] = Query("open", pattern="^(open|done|all)$", alias="status"),
    lead_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """المهام المجدولة عبر كل القادة — open الافتراضي (المستحقة والمتأخرة والمستقبلية غير المتمة)."""
    company_id = db.info["company_id"]
    q = (
        db.query(models.CrmActivity, models.CrmLead)
        .join(models.CrmLead, models.CrmActivity.lead_id == models.CrmLead.id)
        .filter(
            models.CrmActivity.company_id == company_id,
            models.CrmActivity.kind == "task",
            models.CrmLead.company_id == company_id,
        )
    )
    if status_filter == "open":
        q = q.filter(models.CrmActivity.done_at.is_(None))
    elif status_filter == "done":
        q = q.filter(models.CrmActivity.done_at.isnot(None))
    if lead_id:
        q = q.filter(models.CrmActivity.lead_id == lead_id)
    rows = q.order_by(models.CrmActivity.due_at.is_(None), models.CrmActivity.due_at.asc()).limit(200).all()
    return [schemas.CrmTaskOut(
        id=a.id, lead_id=a.lead_id, lead_name=l.name, lead_code=l.code,
        body=a.body, due_at=a.due_at, done_at=a.done_at, created_at=a.created_at,
    ) for a, l in rows]


@router.post("/leads/bulk", response_model=schemas.CrmBulkOut)
def bulk_update_leads(
    payload: schemas.CrmBulkIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_permission_or_role("crm.lead.update", "admin", "manager")),
):
    """عمليات جماعية: إسناد لمندوب / تغيير مرحلة / تحديد متابعة — مع سجل نظامي لكل قائد."""
    company_id = db.info["company_id"]
    if payload.action == "assign_rep":
        rep = db.get(models.SalesRep, payload.assigned_rep_id or 0)
        if rep is None or rep.company_id != company_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "المندوب غير موجود")
    if payload.action == "set_stage" and payload.status == "lost" and not (payload.lost_reason or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "سبب الفقد مطلوب عند النقل إلى مفقود")
    updated, skipped = 0, []
    for lid in payload.ids:
        lead = db.get(models.CrmLead, lid)
        if lead is None or lead.company_id != company_id:
            skipped.append({"id": lid, "reason": "غير موجود"})
            continue
        if lead.converted_customer_id is not None and payload.action == "set_stage":
            skipped.append({"id": lid, "reason": "مُحوَّل بالفعل"})
            continue
        old_status = lead.status
        if payload.action == "assign_rep":
            lead.assigned_rep_id = payload.assigned_rep_id
            note = f"أُسند إلى {rep.name} (جماعي)"
        elif payload.action == "set_stage":
            lead.status = payload.status
            if payload.status == "lost":
                lead.lost_reason = (payload.lost_reason or "").strip()
            note = f"تغيّرت المرحلة جماعياً: {STAGE_AR.get(old_status, old_status)} ← {STAGE_AR.get(payload.status, payload.status)}"
        else:  # set_follow_up
            lead.next_follow_up_at = payload.next_follow_up_at
            note = "حدّد موعد متابعة جماعي"
        db.add(models.CrmActivity(company_id=company_id, lead_id=lead.id, kind="system", body=note, created_by=user.id))
        updated += 1
    db.commit()
    audit(db, user, "update", "crm_lead", None, f"عملية جماعية {payload.action} على {updated} قائد")
    return schemas.CrmBulkOut(updated=updated, skipped=skipped)


_SOURCE_AR_TO_KEY = {"زائر": "walk_in", "مباشر": "walk_in", "هاتف": "phone", "اتصال": "phone", "سوشيال": "social", "توصية": "referral", "معرض": "exhibition", "أخرى": "other", "other": "other", "walk_in": "walk_in", "phone": "phone", "social": "social", "referral": "referral", "exhibition": "exhibition"}


@router.post("/leads/import/xlsx")
async def import_leads_xlsx(
    preview: bool = Query(False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_permission_or_role("crm.lead.create", "admin", "manager")),
):
    """استيراد قادة من Excel: الأعمدة (الاسم*، الشركة، الهاتف، البريد، المصدر، القيمة المتوقعة، ملاحظات).
    preview=true يعيد الجدول المُحلل مع كشف التكرار دون إنشاء."""
    import openpyxl
    import io as _io
    company_id = db.info["company_id"]
    content = await file.read()
    try:
        wb = openpyxl.load_workbook(_io.BytesIO(content), data_only=True)
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ملف Excel غير صالح")
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows_iter, [])]
    col = {name: i for i, name in enumerate(header)}
    plan, errors = [], []
    for idx, row in enumerate(rows_iter, start=2):
        if row is None or all(c is None or str(c).strip() == "" for c in row):
            continue
        get = lambda key: (str(row[col[key]]).strip() if key in col and col[key] < len(row) and row[col[key]] is not None else "")
        name = get("الاسم") or get("name")
        if not name:
            errors.append({"row": idx, "error": "الاسم مطلوب"})
            continue
        phone = get("الهاتف") or get("phone")
        source_raw = get("المصدر") or get("source")
        source = _SOURCE_AR_TO_KEY.get(source_raw.lower() if source_raw else "", "walk_in")
        value_raw = get("القيمة المتوقعة") or get("expected_value")
        try:
            expected = str(round(float(value_raw or 0), 2))
        except ValueError:
            errors.append({"row": idx, "error": f"قيمة غير صالحة: {value_raw}"})
            continue
        dup = bool(phone) and bool(_phone_duplicates(db, company_id, phone))
        plan.append({
            "row": idx, "name": name[:150],
            "company_name": (get("الشركة") or get("company_name"))[:150] or None,
            "phone": phone[:50] or None,
            "email": (get("البريد") or get("email"))[:150] or None,
            "source": source,
            "expected_value": expected,
            "notes": (get("ملاحظات") or get("notes"))[:500] or None,
            "duplicate": dup,
        })
    if preview:
        return {"planned": plan, "errors": errors, "duplicates": sum(1 for p in plan if p["duplicate"])}
    created, skipped = 0, []
    for p in plan:
        if p["duplicate"]:
            skipped.append({"row": p["row"], "reason": "تكرار هاتف"})
            continue
        code = unique_code(db, models.CrmLead, company_id, p["name"], "LEAD", max_length=50)
        db.add(models.CrmLead(company_id=company_id, code=code, created_by=user.id, **{k: v for k, v in p.items() if k in ("name", "company_name", "phone", "email", "source", "expected_value", "notes")}))
        db.flush()  # يجب أن يرى السطر التالي الكود الجديد عند توليده (autoflush=False في الاختبار)
        created += 1
    db.commit()
    audit(db, user, "create", "crm_lead", None, f"استيراد Excel: {created} قائد، تخطي {len(skipped)} مكرر، أخطاء {len(errors)}")
    return {"created": created, "skipped": skipped, "errors": errors}


@router.get("/leads/{obj_id}/activities", response_model=List[schemas.CrmActivityOut])
def list_activities(
    response: Response,
    obj_id: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    lead = _get_lead(db, obj_id)
    q = db.query(models.CrmActivity).filter(models.CrmActivity.lead_id == lead.id).order_by(models.CrmActivity.id.desc())
    total = q.count()
    response.headers["X-Total-Count"] = str(total)
    return q.offset(skip).limit(min(limit, 200)).all()


@router.post("/leads/{obj_id}/activities", response_model=schemas.CrmActivityOut, status_code=status.HTTP_201_CREATED)
def add_activity(
    obj_id: int,
    payload: schemas.CrmActivityCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_permission_or_role("crm.lead.activity", "admin", "manager")),
):
    lead = _get_lead(db, obj_id)
    if payload.kind == "task" and payload.due_at is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "المهمة تتطلب موعد استحقاق")
    activity = models.CrmActivity(
        company_id=db.info["company_id"],
        lead_id=lead.id,
        kind=payload.kind,
        body=payload.body.strip(),
        created_by=user.id,
        due_at=payload.due_at,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    audit(db, user, "create", "crm_activity", activity, f"lead {lead.code} · {activity.kind}")
    return activity
