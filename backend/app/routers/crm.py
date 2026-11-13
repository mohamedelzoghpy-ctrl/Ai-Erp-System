"""CRM خفيف — العملاء المحتملون ومراحل البيع والأنشطة والتحويل لعميل فعلي."""
from typing import List, Optional

from datetime import timedelta as _td

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
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


@router.get("/leads/{obj_id}", response_model=schemas.CrmLeadOut)
def get_lead(obj_id: int, db: Session = Depends(get_db)):
    return _get_lead(db, obj_id)


@router.post("/leads", response_model=schemas.CrmLeadOut, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: schemas.CrmLeadCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_permission_or_role("crm.lead.create", "admin", "manager")),
):
    company_id = db.info["company_id"]
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
    activity = models.CrmActivity(
        company_id=db.info["company_id"],
        lead_id=lead.id,
        kind=payload.kind,
        body=payload.body.strip(),
        created_by=user.id,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    audit(db, user, "create", "crm_activity", activity, f"lead {lead.code} · {activity.kind}")
    return activity
