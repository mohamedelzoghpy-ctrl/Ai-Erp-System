"""Platform company provisioning and company-scoped organization management."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..accounting import seed_default_coa, seed_default_cost_centers, seed_default_fiscal_year
from ..audit import audit
from ..codegen import unique_code
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
    department = db.get(models.Department, membership.department_id) if membership.department_id else None
    return schemas.EmployeeOut(
        id=user.id,  # type: ignore
        username=user.username,  # type: ignore
        employee_code=membership.employee_code or user.username,  # type: ignore
        full_name=user.full_name,  # type: ignore
        role=membership.role,  # type: ignore
        is_active=user.is_active,  # type: ignore
        created_at=user.created_at,  # type: ignore
        department_id=membership.department_id,  # type: ignore
        department_name=department.name if department else None,
        all_branches=membership.all_branches,  # type: ignore
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
    company_code = (payload.code or "").strip().lower() or unique_code(
        db, models.Company, 0, payload.name, "co", max_length=50
    )
    company_obj = models.Company(
        name=payload.name.strip(),
        code=company_code,
        max_warehouses_per_branch=payload.max_warehouses_per_branch,
        max_safes_per_branch=payload.max_safes_per_branch,
        max_branches=payload.max_branches,
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
        main_branch_code = unique_code(db, models.Branch, company_obj.id, "Main Branch", "br", max_length=50)
        branch = models.Branch(company_id=company_obj.id, name="Main Branch", code=main_branch_code)  # type: ignore
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
        seed_default_coa(db, company_obj.id)
        seed_default_cost_centers(db, company_obj.id)
        seed_default_fiscal_year(db, company_obj.id)
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
    new_branch_limit = data.get("max_branches", company.max_branches)
    if new_branch_limit is not None:
        current_branches = db.query(models.Branch.id).filter(models.Branch.company_id == company_id).count()
        if new_branch_limit < current_branches:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Company already has {current_branches} branch(es); the limit cannot be lower than the current count",
            )
    if "max_warehouses_per_branch" in data:
        company.max_warehouses_per_branch = data["max_warehouses_per_branch"]
    if "max_safes_per_branch" in data:
        company.max_safes_per_branch = data["max_safes_per_branch"]
    if "max_branches" in data:
        company.max_branches = data["max_branches"]
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


@platform.patch("/companies/{company_id}/branches/{branch_id}", response_model=schemas.BranchOut)
def platform_update_branch(
    company_id: int,
    branch_id: int,
    payload: schemas.BranchUpdate,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_platform_admin),
):
    db.info["ignore_tenant_scope"] = True
    try:
        branch = db.query(models.Branch).filter(
            models.Branch.id == branch_id,
            models.Branch.company_id == company_id,
        ).one_or_none()
        if branch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")

        data = payload.model_dump(exclude_unset=True)
        if "name" in data and data["name"] is not None:
            branch.name = data["name"].strip()
        if "code" in data and data["code"] is not None:
            branch.code = data["code"].strip().lower()
        if "location" in data:
            branch.location = data["location"]
        if "is_active" in data and data["is_active"] is not None:
            branch.is_active = data["is_active"]

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Branch code already exists for this company") from exc
        db.refresh(branch)
        audit(db, actor, "update", "branch", branch, f"{branch.code} · {company_id}")
        db.commit()
        return branch
    finally:
        db.info.pop("ignore_tenant_scope", None)


@platform.delete("/companies/{company_id}/branches/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
def platform_delete_branch(
    company_id: int,
    branch_id: int,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_platform_admin),
):
    db.info["ignore_tenant_scope"] = True
    try:
        branch = db.query(models.Branch).filter(
            models.Branch.id == branch_id,
            models.Branch.company_id == company_id,
        ).one_or_none()
        if branch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
        if db.query(models.Warehouse.id).filter(models.Warehouse.branch_id == branch_id).first():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "لا يمكن حذف الفرع لوجود مخازن مرتبطة به. انقل المخازن أو احذفها أولاً.",
            )
        if db.query(models.Safe.id).filter(models.Safe.branch_id == branch_id).first():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "لا يمكن حذف الفرع لوجود خزائن مرتبطة به. انقل الخزائن أو احذفها أولاً.",
            )
        audit(db, actor, "delete", "branch", branch.id, f"{branch.code} · {company_id}")
        try:
            db.delete(branch)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Cannot delete branch: it is still referenced.") from exc
        return None
    finally:
        db.info.pop("ignore_tenant_scope", None)


@platform.post("/companies/{company_id}/branches", response_model=schemas.BranchOut, status_code=status.HTTP_201_CREATED)
def platform_create_branch(company_id: int, payload: schemas.BranchCreate, db: Session = Depends(get_db), actor: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    if company.max_branches is not None:
        branch_count = db.query(models.Branch.id).filter(models.Branch.company_id == company_id).count()
        if branch_count >= company.max_branches:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Company branch limit reached ({company.max_branches})")
    raw_code = (payload.code or "").strip()
    if not raw_code:
        code = unique_code(db, models.Branch, company_id, payload.name, "br", max_length=50)
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


@platform.get("/companies/{company_id}/safes", response_model=List[schemas.SafeOut])
def platform_list_safes(company_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_platform_admin)):
    if db.get(models.Company, company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    db.info["ignore_tenant_scope"] = True
    return db.query(models.Safe).filter(models.Safe.company_id == company_id).order_by(models.Safe.id).all()


@platform.post("/companies/{company_id}/safes", status_code=status.HTTP_201_CREATED)
def platform_create_safe(company_id: int, payload: schemas.SafeCreate, db: Session = Depends(get_db), actor: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    db.info["ignore_tenant_scope"] = True
    db.info["allow_company_provisioning"] = True
    branch = db.query(models.Branch).filter(
        models.Branch.id == payload.branch_id,
        models.Branch.company_id == company_id,
        models.Branch.is_active.is_(True),
    ).one_or_none()
    if branch is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose an active branch belonging to this company")
    if company.max_safes_per_branch is not None:
        count = db.query(models.Safe).filter(models.Safe.branch_id == branch.id).count()
        if count >= company.max_safes_per_branch:
            raise HTTPException(status.HTTP_409_CONFLICT, "Branch safe limit reached")
    code = (payload.code or "").strip() or unique_code(db, models.Safe, company_id, payload.name, "SAFE", max_length=50)
    safe = models.Safe(company_id=company_id, branch_id=branch.id, name=payload.name.strip(), code=code, balance=payload.opening_balance, is_active=payload.is_active)
    cash_parent = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1011").first()
    if cash_parent is not None:
        acc = models.ChartAccount(company_id=company_id, code=unique_code(db, models.ChartAccount, company_id, payload.name, "CASH", max_length=50), name=f"Safe: {payload.name.strip()}", type="asset", parent_id=cash_parent.id, is_group=False, balance=payload.opening_balance, is_active=payload.is_active)
        db.add(acc)
        db.flush()
        safe.chart_account_id = acc.id
    db.add(safe)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Safe code already exists for this company") from exc
    finally:
        db.info.pop("allow_company_provisioning", None)
        db.info.pop("ignore_tenant_scope", None)
    audit(db, actor, "create", "safe", safe, f"{safe.code} · {branch.name}")
    db.commit()
    db.refresh(safe)
    return safe


@platform.patch("/companies/{company_id}/safes/{safe_id}", response_model=schemas.SafeOut)
def platform_update_safe(
    company_id: int,
    safe_id: int,
    payload: schemas.SafeUpdate,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_platform_admin),
):
    db.info["ignore_tenant_scope"] = True
    safe = db.query(models.Safe).filter(
        models.Safe.id == safe_id,
        models.Safe.company_id == company_id,
    ).one_or_none()
    if safe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Safe not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        safe.name = data["name"].strip()
    if "code" in data and data["code"] is not None:
        safe.code = data["code"].strip() or unique_code(db, models.Safe, company_id, safe.name, "SAFE")
    if "branch_id" in data and data["branch_id"] is not None:
        branch = db.query(models.Branch).filter(
            models.Branch.id == data["branch_id"],
            models.Branch.company_id == company_id,
            models.Branch.is_active.is_(True),
        ).one_or_none()
        if branch is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose an active branch belonging to this company")
        safe.branch_id = data["branch_id"]
    if "is_active" in data and data["is_active"] is not None:
        safe.is_active = data["is_active"]
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Safe code already exists for this company") from exc
    finally:
        db.info.pop("ignore_tenant_scope", None)
    db.refresh(safe)
    audit(db, actor, "update", "safe", safe, f"{safe.code} · {company_id}")
    db.commit()
    return safe


@platform.get("/companies/{company_id}/banks", response_model=List[schemas.BankOut])
def platform_list_banks(company_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_platform_admin)):
    if db.get(models.Company, company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    db.info["ignore_tenant_scope"] = True
    return db.query(models.Bank).filter(models.Bank.company_id == company_id).order_by(models.Bank.id).all()


@platform.post("/companies/{company_id}/banks", response_model=schemas.BankOut, status_code=status.HTTP_201_CREATED)
def platform_create_bank(company_id: int, payload: schemas.BankCreate, db: Session = Depends(get_db), actor: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    code = (payload.code or "").strip() or unique_code(db, models.Bank, company_id, payload.name, "BANK", max_length=50)
    db.info["ignore_tenant_scope"] = True
    db.info["allow_company_provisioning"] = True
    branch_id = payload.branch_id
    if branch_id is not None:
        branch = db.query(models.Branch).filter(
            models.Branch.id == branch_id,
            models.Branch.company_id == company_id,
            models.Branch.is_active.is_(True),
        ).first()
        if branch is None:
            raise HTTPException(422, "فرع غير موجود في هذه الشركة")
    bank = models.Bank(
        company_id=company_id,
        name=payload.name.strip(),
        code=code,
        account_number=payload.account_number.strip() if payload.account_number else None,
        balance=payload.opening_balance,
        is_active=payload.is_active,
        branch_id=branch_id,
    )
    bank_parent = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "1010").first()
    if bank_parent is not None:
        acc = models.ChartAccount(company_id=company_id, code=unique_code(db, models.ChartAccount, company_id, payload.name, "BANK", max_length=50), name=f"Bank: {payload.name.strip()}", type="asset", parent_id=bank_parent.id, is_group=False, balance=payload.opening_balance, is_active=payload.is_active)
        db.add(acc)
        db.flush()
        bank.chart_account_id = acc.id
    db.add(bank)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Bank code already exists for this company") from exc
    finally:
        db.info.pop("allow_company_provisioning", None)
        db.info.pop("ignore_tenant_scope", None)
    db.refresh(bank)
    audit(db, actor, "create", "bank", bank, f"{bank.code} · {company.name}")
    db.commit()
    return bank


@platform.patch("/companies/{company_id}/banks/{bank_id}", response_model=schemas.BankOut)
def platform_update_bank(
    company_id: int,
    bank_id: int,
    payload: schemas.BankUpdate,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_platform_admin),
):
    db.info["ignore_tenant_scope"] = True
    bank = db.query(models.Bank).filter(
        models.Bank.id == bank_id,
        models.Bank.company_id == company_id,
    ).one_or_none()
    if bank is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        bank.name = data["name"].strip()
    if "code" in data and data["code"] is not None:
        bank.code = data["code"].strip() or unique_code(db, models.Bank, company_id, bank.name, "BANK")
    if "account_number" in data:
        bank.account_number = data["account_number"].strip() if data["account_number"] else None
    if "is_active" in data and data["is_active"] is not None:
        bank.is_active = data["is_active"]
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Bank code already exists for this company") from exc
    finally:
        db.info.pop("ignore_tenant_scope", None)
    db.refresh(bank)
    audit(db, actor, "update", "bank", bank, f"{bank.code} · {company_id}")
    db.commit()
    return bank


@platform.delete("/companies/{company_id}/banks/{bank_id}", status_code=status.HTTP_204_NO_CONTENT)
def platform_delete_bank(
    company_id: int,
    bank_id: int,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_platform_admin),
):
    db.info["ignore_tenant_scope"] = True
    bank = db.query(models.Bank).filter(
        models.Bank.id == bank_id,
        models.Bank.company_id == company_id,
    ).one_or_none()
    if bank is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank not found")
    referenced_payment = db.query(models.Payment.id).filter(models.Payment.bank_id == bank_id).first()
    if referenced_payment is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "لا يمكن حذف البنك لوجود حركات مالية مسجلة عليه. عطّله بدلًا من ذلك.",
        )
    audit(db, actor, "delete", "bank", bank_id, f"{bank.code} · {company_id}")
    db.delete(bank)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "لا يمكن حذف البنك لوجود حركات مرتبطة به.",
        ) from exc
    finally:
        db.info.pop("ignore_tenant_scope", None)
    return None


@platform.get("/companies/{company_id}/warehouses", response_model=List[schemas.WarehouseOut])
def platform_list_warehouses(company_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_platform_admin)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    db.info["ignore_tenant_scope"] = True
    return db.query(models.Warehouse).filter(models.Warehouse.company_id == company_id).order_by(models.Warehouse.id).all()


@platform.patch("/companies/{company_id}/warehouses/{warehouse_id}", response_model=schemas.WarehouseOut)
def platform_update_warehouse(
    company_id: int,
    warehouse_id: int,
    payload: schemas.WarehouseUpdate,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_platform_admin),
):
    db.info["ignore_tenant_scope"] = True
    warehouse = db.query(models.Warehouse).filter(
        models.Warehouse.id == warehouse_id,
        models.Warehouse.company_id == company_id,
    ).one_or_none()
    if warehouse is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Warehouse not found")

    data = payload.model_dump(exclude_unset=True)
    branch_id = data.get("branch_id")
    if branch_id is not None:
        branch = db.query(models.Branch).filter(
            models.Branch.id == branch_id,
            models.Branch.company_id == company_id,
        ).one_or_none()
        if branch is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Branch does not belong to this company")
        company = db.get(models.Company, company_id)
        if company and company.max_warehouses_per_branch is not None:
            count = db.query(models.Warehouse).filter(
                models.Warehouse.branch_id == branch_id,
                models.Warehouse.id != warehouse_id,
            ).count()
            if count >= company.max_warehouses_per_branch:
                raise HTTPException(status.HTTP_409_CONFLICT, "Branch warehouse limit reached")
    if "name" in data and data["name"] is not None:
        warehouse.name = data["name"].strip()
    if "code" in data and data["code"] is not None:
        warehouse.code = data["code"].strip() or unique_code(
            db, models.Warehouse, company_id, warehouse.name, "WH", max_length=50
        )
    if "location" in data:
        warehouse.location = data["location"]
    if "is_active" in data and data["is_active"] is not None:
        warehouse.is_active = data["is_active"]
    if branch_id is not None:
        warehouse.branch_id = branch_id
    audit(db, actor, "update", "warehouse", warehouse, f"{warehouse.code} · {company_id}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Warehouse code or name already exists") from exc
    db.refresh(warehouse)
    return warehouse


@platform.delete("/companies/{company_id}/warehouses/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT)
def platform_delete_warehouse(
    company_id: int,
    warehouse_id: int,
    db: Session = Depends(get_db),
    actor: models.User = Depends(require_platform_admin),
):
    db.info["ignore_tenant_scope"] = True
    warehouse = db.query(models.Warehouse).filter(
        models.Warehouse.id == warehouse_id,
        models.Warehouse.company_id == company_id,
    ).one_or_none()
    if warehouse is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Warehouse not found")
    referenced_product = db.query(models.Product.id).filter(models.Product.warehouse_id == warehouse_id).first()
    if referenced_product is None:
        referenced_product = db.query(models.ProductStock.product_id).filter(models.ProductStock.warehouse_id == warehouse_id).first()
    if referenced_product is None:
        referenced_product = db.query(models.StockMovement.id).filter(models.StockMovement.warehouse_id == warehouse_id).first()
    if referenced_product is None:
        referenced_product = db.query(models.PurchaseOrder.id).filter(models.PurchaseOrder.warehouse_id == warehouse_id).first()
    if referenced_product is None:
        referenced_product = db.query(models.SalesOrder.id).filter(models.SalesOrder.warehouse_id == warehouse_id).first()
    if referenced_product is None:
        referenced_product = db.query(models.Stocktake.id).filter(models.Stocktake.warehouse_id == warehouse_id).first()
    if referenced_product is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "لا يمكن حذف المخزن لارتباطه بمنتجات أو حركات أو مستندات. عطّله بدلًا من ذلك.",
        )
    audit(db, actor, "delete", "warehouse", warehouse.id, f"{warehouse.code} · {company_id}")
    db.delete(warehouse)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "لا يمكن حذف المخزن لارتباطه بمنتجات أو حركات مخزون أو مستندات. عطّله بدلًا من ذلك.",
        ) from exc
    return None


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
    code = (payload.code or "").strip() or unique_code(
        db, models.Warehouse, company_id, payload.name, "WH", max_length=50
    )
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
    company_id = db.info["company_id"]
    company = db.get(models.Company, company_id)
    if company is not None and company.max_branches is not None:
        branch_count = db.query(models.Branch.id).filter(models.Branch.company_id == company_id).count()
        if branch_count >= company.max_branches:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Company branch limit reached ({company.max_branches})")
    code = (payload.code or "").strip().lower() or unique_code(
        db, models.Branch, company_id, payload.name, "br", max_length=50
    )
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
    company_id = db.info["company_id"]
    branch_ids = [
        branch.id for branch in db.query(models.Branch).filter(models.Branch.company_id == company_id, models.Branch.is_active.is_(True)).all()
    ] if payload.all_branches else payload.branch_ids
    if payload.role == "staff" and not branch_ids and not payload.warehouse_ids:
        raise HTTPException(422, "Assign all branches or at least one branch or warehouse to a staff member")
    _check_access_targets(db, company_id, branch_ids, payload.warehouse_ids)
    department = None
    if payload.department_id is not None:
        department = db.query(models.Department).filter(models.Department.id == payload.department_id, models.Department.company_id == company_id, models.Department.is_active.is_(True)).one_or_none()
        if department is None:
            raise HTTPException(422, "Department does not belong to this company or is inactive")
    from sqlalchemy import func
    employee_count = db.query(func.count(models.UserCompanyMembership.id)).filter(models.UserCompanyMembership.company_id == company_id).scalar() or 0
    next_number = employee_count + 1
    existing_codes = {code for (code,) in db.query(models.UserCompanyMembership.employee_code).filter(models.UserCompanyMembership.company_id == company_id).all() if code}
    while str(next_number) in existing_codes:
        next_number += 1
    employee_code = str(next_number)
    login_username = payload.username.strip().lower()
    if db.query(models.User.id).filter(models.User.username == login_username).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    employee = models.User(
        username=login_username,
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
                employee_code=employee_code,
                department_id=department.id if department else None,
                all_branches=payload.all_branches,
            )
        )
        _replace_access(db, employee, company_id, branch_ids, payload.warehouse_ids)
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
    if "department_id" in data:
        department_id = data["department_id"]
        if department_id is not None:
            department = db.query(models.Department).filter(
                models.Department.id == department_id,
                models.Department.company_id == company_id,
                models.Department.is_active.is_(True),
            ).one_or_none()
            if department is None:
                raise HTTPException(422, "Department does not belong to this company or is inactive")
        membership.department_id = department_id  # type: ignore
    if "all_branches" in data:
        membership.all_branches = bool(data["all_branches"])  # type: ignore
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
        if data.get("all_branches", membership.all_branches):
            branch_ids = [branch.id for branch in db.query(models.Branch).filter(models.Branch.company_id == company_id, models.Branch.is_active.is_(True)).all()]
        if warehouse_ids is None:
            warehouse_ids = [
                warehouse_id
                for (warehouse_id,) in db.query(models.UserWarehouseAccess.warehouse_id)
                .filter(models.UserWarehouseAccess.user_id == employee.id)
                .all()
            ]
        if not branch_ids and not warehouse_ids:
            raise HTTPException(422, "Assign all branches or at least one branch or warehouse to a staff member")
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
