"""Company-scoped department management."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_manager, require_platform_admin

router = APIRouter(tags=["departments"], dependencies=[Depends(get_current_user)])


def _department_query(db: Session, company_id: int):
    return db.query(models.Department).filter(models.Department.company_id == company_id)


def _code(db: Session, company_id: int, name: str, requested: Optional[str] = None) -> str:
    return (requested or "").strip() or unique_code(db, models.Department, company_id, name, "DEPT", max_length=50)


def _create(db: Session, company_id: int, payload: schemas.DepartmentCreate, user: models.User, can_seed_coa: bool = False) -> models.Department:
    name = payload.name.strip()
    code = _code(db, company_id, name, payload.code)
    if _department_query(db, company_id).filter(
        (models.Department.code == code) | (models.Department.name == name)
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Department name or code already exists in this company")
    department = models.Department(
        company_id=company_id,
        name=name,
        code=code,
        description=payload.description.strip() if payload.description else None,
        is_active=payload.is_active,
    )
    db.add(department)
    if can_seed_coa:
        db.flush()
    audit(db, user, "create", "department", department, f"{department.code} · {department.name}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Department name or code already exists in this company") from exc
    db.refresh(department)
    return department


@router.get("/company/departments", response_model=List[schemas.DepartmentOut])
def list_departments(db: Session = Depends(get_db)):
    return _department_query(db, db.info["company_id"]).order_by(models.Department.name, models.Department.id).all()


@router.post("/company/departments", response_model=schemas.DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(payload: schemas.DepartmentCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    return _create(db, db.info["company_id"], payload, user)


@router.patch("/company/departments/{department_id}", response_model=schemas.DepartmentOut)
def update_department(
    department_id: int,
    payload: schemas.DepartmentCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    department = _department_query(db, db.info["company_id"]).filter(models.Department.id == department_id).one_or_none()
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    data = payload.model_dump(exclude_unset=True)
    name = (data.get("name") or department.name).strip()
    code = _code(db, db.info["company_id"], name, data.get("code") or department.code)
    duplicate = _department_query(db, db.info["company_id"]).filter(
        models.Department.id != department_id,
        (models.Department.name == name) | (models.Department.code == code),
    ).first()
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "Department name or code already exists in this company")
    department.name = name
    department.code = code
    department.description = data.get("description")
    department.is_active = data.get("is_active", department.is_active)
    audit(db, user, "update", "department", department, f"{department.code} · {department.name}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Department name or code already exists in this company") from exc
    db.refresh(department)
    return department


@router.delete("/company/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(department_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    department = _department_query(db, db.info["company_id"]).filter(models.Department.id == department_id).one_or_none()
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    audit(db, user, "delete", "department", department.id, f"{department.code} · {department.name}")
    db.delete(department)
    db.commit()


@router.patch("/platform/companies/{company_id}/departments/{department_id}", response_model=schemas.DepartmentOut)
def platform_update_department(
    company_id: int,
    department_id: int,
    payload: schemas.DepartmentCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_platform_admin),
):
    if db.get(models.Company, company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    db.info["ignore_tenant_scope"] = True
    db.info["allow_company_provisioning"] = True
    department = _department_query(db, company_id).filter(models.Department.id == department_id).one_or_none()
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    data = payload.model_dump(exclude_unset=True)
    name = (data.get("name") or department.name).strip()
    code = _code(db, company_id, name, data.get("code") or department.code)
    duplicate = _department_query(db, company_id).filter(
        models.Department.id != department_id,
        (models.Department.name == name) | (models.Department.code == code),
    ).first()
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "Department name or code already exists in this company")
    department.name = name
    department.code = code
    department.description = data.get("description")
    department.is_active = data.get("is_active", department.is_active)
    audit(db, user, "update", "department", department, f"{department.code} · {department.name}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Department name or code already exists in this company") from exc
    db.refresh(department)
    return department


@router.delete("/platform/companies/{company_id}/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
def platform_delete_department(
    company_id: int,
    department_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_platform_admin),
):
    if db.get(models.Company, company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    db.info["ignore_tenant_scope"] = True
    db.info["allow_company_provisioning"] = True
    department = _department_query(db, company_id).filter(models.Department.id == department_id).one_or_none()
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    audit(db, user, "delete", "department", department.id, f"{department.code} · {department.name}")
    db.delete(department)
    db.commit()


@router.get("/platform/companies/{company_id}/departments", response_model=List[schemas.DepartmentOut])
def platform_list_departments(company_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_platform_admin)):
    if db.get(models.Company, company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    db.info["ignore_tenant_scope"] = True
    return _department_query(db, company_id).order_by(models.Department.name, models.Department.id).all()


@router.post("/platform/companies/{company_id}/departments", response_model=schemas.DepartmentOut, status_code=status.HTTP_201_CREATED)
def platform_create_department(
    company_id: int,
    payload: schemas.DepartmentCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_platform_admin),
):
    if db.get(models.Company, company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    db.info["ignore_tenant_scope"] = True
    db.info["allow_company_provisioning"] = True
    return _create(db, company_id, payload, user, can_seed_coa=True)
