"""Platform company provisioning and company-scoped organization management."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user, require_manager, require_platform_admin, user_role
from ..security import hash_password

platform = APIRouter(prefix="/platform", tags=["platform administration"])
company = APIRouter(prefix="/company", tags=["company administration"])


def _membership(db: Session, user: models.User) -> models.UserCompanyMembership:
    membership = (
        db.query(models.UserCompanyMembership)
        .filter(
            models.UserCompanyMembership.user_id == user.id,
            models.UserCompanyMembership.company_id == db.info["company_id"],
        )
        .one_or_none()
    )
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is not assigned to this company")
    return membership


def _check_access_targets(
    db: Session,
    company_id: int,
    branch_ids: List[int],
    warehouse_ids: List[int],
) -> None:
    branches = (
        db.query(models.Branch.id)
        .filter(models.Branch.company_id == company_id, models.Branch.id.in_(branch_ids or [-1]))
        .all()
    )
    warehouses = (
        db.query(models.Warehouse.id)
        .filter(
            models.Warehouse.company_id == company_id,
            models.Warehouse.id.in_(warehouse_ids or [-1]),
        )
        .all()
    )
    if len(branches) != len(set(branch_ids)):
        raise HTTPException(422, "One or more branches do not belong to this company")
    if len(warehouses) != len(set(warehouse_ids)):
        raise HTTPException(422, "One or more warehouses do not belong to this company")


def _employee_out(db: Session, user: models.User) -> schemas.EmployeeOut:
    membership = _membership(db, user)
    branches = [
        branch_id
        for (branch_id,) in db.query(models.UserBranchAccess.branch_id)
        .filter(models.UserBranchAccess.user_id == user.id)
        .all()
    ]
    warehouses = [
        warehouse_id
        for (warehouse_id,) in db.query(models.UserWarehouseAccess.warehouse_id)
        .filter(models.UserWarehouseAccess.user_id == user.id)
        .all()
    ]
    return schemas.EmployeeOut(
        id=user.id,  # type: ignore
        username=user.username,  # type: ignore
        full_name=user.full_name,  # type: ignore
        role=membership.role,  # type: ignore
        is_active=user.is_active,  # type: ignore
        created_at=user.created_at,  # type: ignore
        branch_ids=branches,
        warehouse_ids=warehouses,
    )


def _replace_access(
    db: Session,
    user: models.User,
    company_id: int,
    branch_ids: List[int],
    warehouse_ids: List[int],
) -> None:
    _check_access_targets(db, company_id, branch_ids, warehouse_ids)
    db.query(models.UserBranchAccess).filter(models.UserBranchAccess.user_id == user.id).delete()
    db.query(models.UserWarehouseAccess).filter(models.UserWarehouseAccess.user_id == user.id).delete()
    db.add_all(
        [models.UserBranchAccess(user_id=user.id, branch_id=branch_id) for branch_id in set(branch_ids)]
        + [
            models.UserWarehouseAccess(user_id=user.id, warehouse_id=warehouse_id)
            for warehouse_id in set(warehouse_ids)
        ]
    )


@platform.get("/companies", response_model=List[schemas.CompanyOut])
def list_companies(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_platform_admin),
):
    return db.query(models.Company).order_by(models.Company.id).all()


@platform.post("/companies", response_model=schemas.CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(
    payload: schemas.CompanyCreate,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_platform_admin),
):
    company_obj = models.Company(
        name=payload.name.strip(),
        code=payload.code.strip().lower(),
        max_warehouses_per_branch=payload.max_warehouses_per_branch,
        max_safes_per_branch=payload.max_safes_per_branch,
    )
    user = models.User(
        username=payload.admin_username.strip().lower(),
        full_name=payload.admin_full_name,
        hashed_password=hash_password(payload.admin_password),
        role="admin",
    )
    db.add_all([company_obj, user])
    try:
        db.info["allow_company_provisioning"] = True
        db.flush()
        branch = models.Branch(company_id=company_obj.id, name="Main Branch", code="main")  # type: ignore
        db.add(branch)
        db.flush()
        db.add(
            models.UserCompanyMembership(
                user_id=user.id,
                company_id=company_obj.id,
                role="admin",
            )
        )
        db.add(models.UserBranchAccess(user_id=user.id, branch_id=branch.id))
        audit(db, actor, "create", "company", company_obj, f"{company_obj.code} · admin {user.username}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Company code or username already exists") from exc
    finally:
        db.info.pop("allow_company_provisioning", None)
    db.refresh(company_obj)
    return company_obj


@platform.get("/companies/{company_id}/members")
def list_company_members(company_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    memberships = db.query(models.UserCompanyMembership).filter(models.UserCompanyMembership.company_id == company_id).all()
    out = []
    for m in memberships:
        u = db.get(models.User, m.user_id)
        if u is None:
            continue
        out.append({"user_id": u.id, "username": u.username, "full_name": u.full_name, "role": m.role})
    return out


@platform.post("/companies/{company_id}/members", status_code=status.HTTP_201_CREATED)
def add_company_member(company_id: int, payload: schemas.CompanyMembershipCreate, db: Session = Depends(get_db), actor: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    user = db.query(models.User).filter(models.User.username == payload.username.strip().lower()).one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User '{payload.username}' not found")
    existing = db.query(models.UserCompanyMembership).filter(
        models.UserCompanyMembership.user_id == user.id,
        models.UserCompanyMembership.company_id == company_id,
    ).one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already a member of this company")
    membership = models.UserCompanyMembership(user_id=user.id, company_id=company_id, role=payload.role)
    db.add(membership)
    # If user has no active company, set this one.
    if user.active_company_id is None:
        user.active_company_id = company_id  # type: ignore
    db.commit()
    audit(db, actor, "add_member", "company", company, f"{user.username} ({payload.role})")
    return {"user_id": user.id, "username": user.username, "role": payload.role}


@platform.delete("/companies/{company_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_company_member(company_id: int, user_id: int, db: Session = Depends(get_db), actor: models.User = Depends(require_platform_admin)):
    membership = db.query(models.UserCompanyMembership).filter(
        models.UserCompanyMembership.user_id == user_id,
        models.UserCompanyMembership.company_id == company_id,
    ).one_or_none()
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    user = db.get(models.User, user_id)
    db.delete(membership)
    # If removed the active company, switch to another membership if any.
    if user is not None and user.active_company_id == company_id:  # type: ignore
        other = db.query(models.UserCompanyMembership).filter(models.UserCompanyMembership.user_id == user_id).first()
        user.active_company_id = other.company_id if other else None  # type: ignore
    db.commit()
    audit(db, actor, "remove_member", "company", db.get(models.Company, company_id), f"user {user_id}")
@platform.patch("/companies/{company_id}", response_model=schemas.CompanyOut)
def update_platform_company(company_id: int, payload: schemas.CompanyUpdate, db: Session = Depends(get_db), actor: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    data = payload.model_dump(exclude_unset=True)
    if "max_warehouses_per_branch" in data:
        company.max_warehouses_per_branch = data["max_warehouses_per_branch"]
    if "max_safes_per_branch" in data:
        company.max_safes_per_branch = data["max_safes_per_branch"]
    if "name" in data and data["name"] is not None:
        company.name = data["name"]
    if "is_active" in data and data["is_active"] is not None:
        new_active = data["is_active"]
        if new_active is False:
            other_active = db.query(models.Company).filter(models.Company.id != company_id, models.Company.is_active.is_(True)).count()
            if other_active == 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "لا يمكن تعطيل الشركة الوحيدة النشطة")
        company.is_active = new_active
    db.commit()
    db.refresh(company)
    audit(db, actor, "update", "company", company, f"{company.code}")
    return company

@platform.get("/companies/{company_id}/admin", response_model=schemas.UserOut)
def get_platform_company_admin(company_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_platform_admin)):
    membership = (
        db.query(models.UserCompanyMembership)
        .filter(models.UserCompanyMembership.company_id == company_id, models.UserCompanyMembership.role == "admin")
        .order_by(models.UserCompanyMembership.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No admin user for this company")
    user = db.get(models.User, membership.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admin user not found")
    return user

@platform.patch("/companies/{company_id}/admin", response_model=schemas.UserOut)
def update_platform_company_admin(company_id: int, payload: schemas.UserUpdate, db: Session = Depends(get_db), actor: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    membership = (
        db.query(models.UserCompanyMembership)
        .filter(models.UserCompanyMembership.company_id == company_id, models.UserCompanyMembership.role == "admin")
        .order_by(models.UserCompanyMembership.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No admin user for this company")
    user = db.get(models.User, membership.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admin user not found")
    data = payload.model_dump(exclude_unset=True)
    if "password" in data and data["password"]:
        user.hashed_password = hash_password(data.pop("password"))  # type: ignore
    if "role" in data and data["role"] is not None:
        membership.role = data["role"]
    for key, value in data.items():
        if value is not None:
            setattr(user, key, value)
    db.commit()
    db.refresh(user)
    audit(db, actor, "update", "user", user, f"{user.username}")
    return user


@platform.get("/companies/{company_id}/branches", response_model=List[schemas.BranchOut])
def platform_list_branches(company_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return db.query(models.Branch).filter(models.Branch.company_id == company_id).order_by(models.Branch.id).all()


@platform.post("/companies/{company_id}/branches", response_model=schemas.BranchOut, status_code=status.HTTP_201_CREATED)
def platform_create_branch(company_id: int, payload: schemas.BranchCreate, db: Session = Depends(get_db), actor: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    raw_code = (payload.code or "").strip()
    if not raw_code:
        base = payload.name.strip().lower().replace(" ", "-")[:30] or "branch"
        code = base
        i = 2
        while db.query(models.Branch).filter(models.Branch.company_id == company_id, models.Branch.code == code).first():
            code = f"{base}-{i}"; i += 1
    else:
        code = raw_code
    branch = models.Branch(company_id=company_id, name=payload.name.strip(), code=code, location=payload.location)  # type: ignore
    db.add(branch)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Branch code already exists for this company")
    db.refresh(branch)
    audit(db, actor, "create", "branch", branch, f"{branch.code} · {company.code}")
    return branch


@platform.get("/companies/{company_id}/warehouses", response_model=List[schemas.WarehouseOut])
def platform_list_warehouses(company_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return db.query(models.Warehouse).filter(models.Warehouse.company_id == company_id).order_by(models.Warehouse.id).all()


@platform.post("/companies/{company_id}/warehouses", response_model=schemas.WarehouseOut, status_code=status.HTTP_201_CREATED)
def platform_create_warehouse(company_id: int, payload: schemas.WarehouseCreate, db: Session = Depends(get_db), actor: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    branch_id = payload.branch_id
    if branch_id is None:
        branch = db.query(models.Branch).filter(models.Branch.company_id == company_id).order_by(models.Branch.id).first()
        if branch is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Create a branch first")
        branch_id = branch.id
    else:
        branch = db.get(models.Branch, branch_id)
        if branch is None or branch.company_id != company_id:  # type: ignore
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Branch does not belong to this company")
    # Enforce per-branch warehouse limit.
    if company.max_warehouses_per_branch is not None:
        count = db.query(models.Warehouse).filter(models.Warehouse.branch_id == branch_id).count()
        if count >= company.max_warehouses_per_branch:  # type: ignore
            raise HTTPException(status.HTTP_409_CONFLICT, f"Branch warehouse limit reached ({company.max_warehouses_per_branch})")
    code = (payload.code or "").strip()
    if not code:
        # Auto-generate a unique code per company.
        count = db.query(models.Warehouse).filter(models.Warehouse.company_id == company_id).count()
        code = f"WH-{count + 1:03d}"
        while db.query(models.Warehouse).filter(models.Warehouse.company_id == company_id, models.Warehouse.code == code).first():
            count += 1
            code = f"WH-{count + 1:03d}"
    wh = models.Warehouse(company_id=company_id, branch_id=branch_id, name=payload.name.strip(), code=code, location=payload.location, is_active=payload.is_active)  # type: ignore
    db.add(wh)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Warehouse code already exists for this company")
    db.refresh(wh)
    audit(db, actor, "create", "warehouse", wh, f"{wh.code} · {company.code}")
    return wh


@company.get("", response_model=schemas.CompanyOut)
def get_company(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    result = db.get(models.Company, db.info["company_id"])
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return result


@company.patch("", response_model=schemas.CompanyOut)
def update_company(
    payload: schemas.CompanyUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    if user_role(user) != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a company admin can update company settings")
    result = db.get(models.Company, db.info["company_id"])
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(result, key, value)
    audit(db, user, "update", "company", result, "company settings")
    db.commit()
    db.refresh(result)
    return result


@company.get("/branches", response_model=List[schemas.BranchOut])
def list_branches(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.Branch).order_by(models.Branch.id).all()


@company.post("/branches", response_model=schemas.BranchOut, status_code=status.HTTP_201_CREATED)
def create_branch(
    payload: schemas.BranchCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    raw_code = (payload.code or "").strip()
    if not raw_code:
        base = payload.name.strip().lower().replace(" ", "-")[:30] or "branch"
        code = base
        i = 2
        company_id = db.info["company_id"]  # type: ignore
        while db.query(models.Branch).filter(models.Branch.company_id == company_id, models.Branch.code == code).first():
            code = f"{base}-{i}"; i += 1
    else:
        code = raw_code.lower()
    branch = models.Branch(
        company_id=db.info["company_id"],  # type: ignore
        name=payload.name.strip(),  # type: ignore
        code=code,  # type: ignore
        location=payload.location,  # type: ignore
    )
    db.add(branch)
    audit(db, user, "create", "branch", branch, f"{branch.code} · {branch.name}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Branch code already exists in this company") from exc
    db.refresh(branch)
    return branch


@company.get("/employees", response_model=List[schemas.EmployeeOut])
def list_employees(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    users = (
        db.query(models.User)
        .join(models.UserCompanyMembership)
        .filter(models.UserCompanyMembership.company_id == company_id)
        .order_by(models.User.id)
        .all()
    )
    return [_employee_out(db, employee) for employee in users]


@company.post("/employees", response_model=schemas.EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: schemas.EmployeeCreate,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_manager),
):
    role = user_role(actor)
    if payload.role != "staff" and role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a company admin can assign manager or admin roles")
    if payload.role == "staff" and not payload.branch_ids and not payload.warehouse_ids:
        raise HTTPException(422, "Assign at least one branch or warehouse to a staff member")
    company_id = db.info["company_id"]
    _check_access_targets(db, company_id, payload.branch_ids, payload.warehouse_ids)
    employee = models.User(
        username=payload.username.strip().lower(),
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(employee)
    try:
        db.flush()
        db.add(
            models.UserCompanyMembership(
                user_id=employee.id,
                company_id=company_id,
                role=payload.role,
            )
        )
        _replace_access(db, employee, company_id, payload.branch_ids, payload.warehouse_ids)
        audit(db, actor, "create", "user", employee, f"{employee.username} ({payload.role})")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists") from exc
    db.refresh(employee)
    return _employee_out(db, employee)


@company.patch("/employees/{user_id}", response_model=schemas.EmployeeOut)
def update_employee(
    user_id: int,
    payload: schemas.EmployeeUpdate,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_manager),
):
    company_id = db.info["company_id"]
    membership = (
        db.query(models.UserCompanyMembership)
        .filter(
            models.UserCompanyMembership.user_id == user_id,
            models.UserCompanyMembership.company_id == company_id,
        )
        .one_or_none()
    )
    employee = db.get(models.User, user_id)
    if membership is None or employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Employee {user_id} not found")
    if employee.is_platform_admin and employee.id != actor.id:  # type: ignore
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The platform administrator cannot be managed as a company employee")
    data = payload.model_dump(exclude_unset=True)
    role = user_role(actor)
    if role != "admin" and membership.role != "staff":  # type: ignore
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a company admin can manage managers and admins")
    if data.get("role") not in (None, "staff") and role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a company admin can assign manager or admin roles")
    if data.get("role") is not None:
        if employee.id == actor.id and data["role"] != "admin":  # type: ignore
            raise HTTPException(status.HTTP_409_CONFLICT, "You cannot demote your own account")
        if membership.role == "admin" and data["role"] != "admin" and employee.is_active:  # type: ignore
            remaining_admins = (
                db.query(models.UserCompanyMembership)
                .join(models.User)
                .filter(
                    models.UserCompanyMembership.company_id == company_id,
                    models.UserCompanyMembership.role == "admin",
                    models.UserCompanyMembership.user_id != employee.id,
                    models.User.is_active.is_(True),
                )
                .count()
            )
            if remaining_admins == 0:
                raise HTTPException(status.HTTP_409_CONFLICT, "The company must have an active admin")
        membership.role = data["role"]  # type: ignore
        employee.role = data["role"]  # type: ignore
    if data.get("role") == "staff":
        branch_ids = data.get("branch_ids")
        warehouse_ids = data.get("warehouse_ids")
        if branch_ids is None:
            branch_ids = [
                branch_id
                for (branch_id,) in db.query(models.UserBranchAccess.branch_id)
                .filter(models.UserBranchAccess.user_id == employee.id)
                .all()
            ]
        if warehouse_ids is None:
            warehouse_ids = [
                warehouse_id
                for (warehouse_id,) in db.query(models.UserWarehouseAccess.warehouse_id)
                .filter(models.UserWarehouseAccess.user_id == employee.id)
                .all()
            ]
        if not branch_ids and not warehouse_ids:
            raise HTTPException(422, "Assign at least one branch or warehouse to a staff member")
    if "password" in data and data["password"]:
        employee.hashed_password = hash_password(data["password"])  # type: ignore
    if "full_name" in data:
        employee.full_name = data["full_name"]
    if "is_active" in data:
        if employee.id == actor.id and data["is_active"] is False:  # type: ignore
            raise HTTPException(status.HTTP_409_CONFLICT, "You cannot deactivate your own account")
        if membership.role == "admin" and data["is_active"] is False:  # type: ignore
            remaining_admins = (
                db.query(models.UserCompanyMembership)
                .join(models.User)
                .filter(
                    models.UserCompanyMembership.company_id == company_id,
                    models.UserCompanyMembership.role == "admin",
                    models.UserCompanyMembership.user_id != employee.id,
                    models.User.is_active.is_(True),
                )
                .count()
            )
            if remaining_admins == 0:
                raise HTTPException(status.HTTP_409_CONFLICT, "The company must have an active admin")
        employee.is_active = data["is_active"]  # type: ignore
    if "branch_ids" in data or "warehouse_ids" in data:
        branch_ids = data.get("branch_ids")
        warehouse_ids = data.get("warehouse_ids")
        if branch_ids is None:
            branch_ids = [
                branch_id
                for (branch_id,) in db.query(models.UserBranchAccess.branch_id)
                .filter(models.UserBranchAccess.user_id == employee.id)
                .all()
            ]
        if warehouse_ids is None:
            warehouse_ids = [
                warehouse_id
                for (warehouse_id,) in db.query(models.UserWarehouseAccess.warehouse_id)
                .filter(models.UserWarehouseAccess.user_id == employee.id)
                .all()
            ]
        _replace_access(db, employee, company_id, branch_ids, warehouse_ids)
    audit(db, actor, "update", "user", employee, employee.username)  # type: ignore
    db.commit()
    db.refresh(employee)
    return _employee_out(db, employee)
