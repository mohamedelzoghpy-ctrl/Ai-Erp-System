"""Company-scoped sales reps (مندوبي المبيعات): list / create / update / delete."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_manager

router = APIRouter(prefix="/reps", tags=["reps"])


def _rep_query(db: Session, company_id: int):
    return db.query(models.SalesRep).filter(models.SalesRep.company_id == company_id)


@router.get("", response_model=List[schemas.SalesRepOut])
def list_reps(
    active_only: bool = False,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = _rep_query(db, db.info["company_id"])
    if active_only:
        q = q.filter(models.SalesRep.is_active.is_(True))
    if search:
        s = f"%{search.strip()}%"
        q = q.filter((models.SalesRep.name.ilike(s)) | (models.SalesRep.code.ilike(s)) | (models.SalesRep.phone.ilike(s)))
    RBA, RA = models.SalesRepBranchAccess, models.SalesRep
    branch_map: dict = {}
    for rid, bid in db.query(RBA.rep_id, RBA.branch_id).join(RA, RA.id == RBA.rep_id).filter(RA.company_id == db.info["company_id"]).all():
        branch_map.setdefault(rid, []).append(bid)
    out = []
    for r in q.order_by(RA.id).all():
        item = schemas.SalesRepOut.model_validate(r)
        item.branch_ids = branch_map.get(r.id, [])  # type: ignore[union-attr]
        out.append(item)
    return out


def _assign_branches(db: Session, rep: models.SalesRep, company_id: int, branch_ids: List[int]) -> None:
    if not branch_ids:
        unique_ids = []
    else:
        unique_ids = sorted(set(branch_ids))
        valid = (
            db.query(models.Branch.id)
            .filter(models.Branch.company_id == company_id, models.Branch.id.in_(unique_ids))
            .all()
        )
        if len(valid) != len(unique_ids):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "فرع غير موجود في هذه الشركة")
    # Replace access rows explicitly (avoid unique violations on re-assignment)
    db.query(models.SalesRepBranchAccess).filter(models.SalesRepBranchAccess.rep_id == rep.id).delete(synchronize_session=False)
    for bid in unique_ids:
        db.add(models.SalesRepBranchAccess(rep_id=rep.id, branch_id=bid))


@router.post("", response_model=schemas.SalesRepOut, status_code=status.HTTP_201_CREATED)
def create_rep(
    payload: schemas.SalesRepCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    name = payload.name.strip()
    code = (payload.code or "").strip() or unique_code(db, models.SalesRep, company_id, name, "REP")
    if _rep_query(db, company_id).filter(
        (models.SalesRep.code == code) | (models.SalesRep.name == name)
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "اسم المندوب أو الكود مستخدم بالفعل")
    rep = models.SalesRep(
        company_id=company_id,
        name=name,
        code=code,
        phone=payload.phone.strip() if payload.phone else None,
        commission_percent=payload.commission_percent,
        is_active=payload.is_active,
    )
    db.add(rep)
    db.flush()
    _assign_branches(db, rep, company_id, payload.branch_ids)
    db.commit()
    db.refresh(rep)
    audit(db, user, "create", "sales_rep", rep, f"{rep.code}: {rep.name}")
    return _rep_out(db, rep)


def _rep_out(db: Session, rep: models.SalesRep) -> schemas.SalesRepOut:
    item = schemas.SalesRepOut.model_validate(rep)
    item.branch_ids = [a.branch_id for a in rep.branch_access]  # type: ignore[union-attr]
    return item


@router.patch("/{rep_id}", response_model=schemas.SalesRepOut)
def update_rep(
    rep_id: int,
    payload: schemas.SalesRepUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    rep = _rep_query(db, db.info["company_id"]).filter(models.SalesRep.id == rep_id).one_or_none()
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sales rep {rep_id} not found")
    if "name" in payload.model_dump(exclude_unset=True):
        data = payload.model_dump(exclude_unset=True)
        new_name = (data["name"] or "").strip()
        if new_name and new_name != rep.name and _rep_query(db, db.info["company_id"]).filter(models.SalesRep.name == new_name).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "اسم المندوب مستخدم بالفعل")
    data = payload.model_dump(exclude_unset=True)
    if "phone" in data and data["phone"] is not None:
        data["phone"] = data["phone"].strip() or None
    data.pop("branch_ids", None)
    changed = list(data)
    for key, value in data.items():
        setattr(rep, key, value)
    if payload.branch_ids is not None:
        _assign_branches(db, rep, db.info["company_id"], payload.branch_ids)
        changed.append("branch_ids")
    audit(db, user, "update", "sales_rep", rep, f"{rep.code}: " + "، ".join(changed))
    db.commit()
    db.refresh(rep)
    return _rep_out(db, rep)


@router.delete("/{rep_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rep(
    rep_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    rep = _rep_query(db, db.info["company_id"]).filter(models.SalesRep.id == rep_id).one_or_none()
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sales rep {rep_id} not found")
    code, name = rep.code, rep.name
    db.delete(rep)
    audit(db, user, "delete", "sales_rep", None, f"deleted {code} ({name})")
    db.commit()
    return None
