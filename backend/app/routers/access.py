"""إدارة الصلاحيات: الكتالوج، أقسام الصلاحيات، والاستثناءات الفردية للمستخدمين.

كل نقاط هذا الراوتر محمية بـ admin.user.permissions_manage (البوابة المركزية + دفاع داخلي).
"""

from typing import List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..audit import audit
from ..database import get_db
from ..deps import get_current_user
from ..permissions import (
    ALL_PERMISSIONS,
    KNOWN_CODES,
    PERM_MANAGE,
    catalog_tree,
    effective_permissions,
    get_or_create_permission,
    require_permission,
)

router = APIRouter(tags=["permissions"])

_protect = [Depends(get_current_user), Depends(require_permission(PERM_MANAGE))]


# ---------- Schemas ----------


class SectionCreate(BaseModel):
    code: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=120)


class SectionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SectionPermissionsIn(BaseModel):
    permission_codes: List[str] = []


class OverrideIn(BaseModel):
    permission_code: str
    effect: str = Field(pattern="^(grant|deny)$")
    reason: Optional[str] = Field(default=None, max_length=255)


class OverridesIn(BaseModel):
    overrides: List[OverrideIn] = []


class SectionOut(BaseModel):
    id: int
    code: str
    name: str
    is_system: bool
    permission_codes: List[str] = []


class UserPermissionDetail(BaseModel):
    user_id: int
    company_id: int
    section_id: Optional[int]  # القسم الأول (توافق مع الواجهات السابقة)
    section_name: Optional[str]
    section_ids: List[int] = []  # كل الأقسام المسندة — الصلاحية اتحادها
    section_names: List[str] = []
    role: str
    inherited: List[dict] = []  # [{code, label, source: section|baseline}]
    overrides: List[dict] = []  # [{code, effect, reason}]
    effective: List[str] = []


# ---------- الكتالوج ----------


@router.get("/permissions/catalog", dependencies=_protect)
def get_catalog():
    return {"modules": catalog_tree(), "total": len(ALL_PERMISSIONS)}


# ---------- أقسام الصلاحيات ----------


def _section_out(db: Session, section: models.AccessSection) -> SectionOut:
    codes = db.execute(
        select(models.Permission.code)
        .join(
            models.AccessSectionPermission,
            models.AccessSectionPermission.permission_id == models.Permission.id,
        )
        .where(models.AccessSectionPermission.section_id == section.id)
    ).scalars().all()
    return SectionOut(
        id=section.id,
        code=section.code,
        name=section.name,
        is_system=section.is_system,
        permission_codes=sorted(codes),
    )


@router.get("/access-sections", response_model=List[SectionOut], dependencies=_protect)
def list_sections(db: Session = Depends(get_db)):
    sections = db.query(models.AccessSection).order_by(models.AccessSection.id).all()
    return [_section_out(db, s) for s in sections]


@router.post("/access-sections", response_model=SectionOut, status_code=status.HTTP_201_CREATED, dependencies=_protect)
def create_section(payload: SectionCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    exists = db.query(models.AccessSection).filter(models.AccessSection.code == payload.code).first()
    if exists:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "يوجد قسم بنفس الكود")
    section = models.AccessSection(code=payload.code, name=payload.name, is_system=False)
    db.add(section)
    audit(db, user, "create", "access_section", section, f"قسم صلاحيات جديد: {payload.name}")
    db.commit()
    db.refresh(section)
    return _section_out(db, section)


@router.patch("/access-sections/{section_id}", response_model=SectionOut, dependencies=_protect)
def update_section(
    section_id: int,
    payload: SectionUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    section = db.get(models.AccessSection, section_id)
    if section is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "القسم غير موجود")
    section.name = payload.name
    audit(db, user, "update", "access_section", section, f"تعديل قسم صلاحيات: {payload.name}")
    db.commit()
    db.refresh(section)
    return _section_out(db, section)


@router.delete("/access-sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_protect)
def delete_section(section_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    section = db.get(models.AccessSection, section_id)
    if section is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "القسم غير موجود")
    if section.is_system:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "لا يمكن حذف قسم نظامي")
    member_ids = set(
        db.execute(
            select(models.UserCompanyMembership.user_id).where(models.UserCompanyMembership.section_id == section_id)
        ).scalars()
    )
    assigned_ids = set(
        db.execute(
            select(models.UserSectionAccess.user_id).where(models.UserSectionAccess.section_id == section_id)
        ).scalars()
    )
    total = len(member_ids | assigned_ids)
    if total:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"لا يمكن حذف قسم فيه {total} مستخدم — افصلهم أولاً")
    audit(db, user, "delete", "access_section", section_id, f"حذف قسم صلاحيات: {section.name}")
    db.delete(section)
    db.commit()
    return None


@router.put("/access-sections/{section_id}/permissions", response_model=SectionOut, dependencies=_protect)
def set_section_permissions(
    section_id: int,
    payload: SectionPermissionsIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    section = db.get(models.AccessSection, section_id)
    if section is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "القسم غير موجود")
    unknown = [c for c in payload.permission_codes if c not in KNOWN_CODES]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"أكواد صلاحيات غير معروفة: {unknown[:5]}")

    perm_ids = [
        get_or_create_permission(db, code).id for code in payload.permission_codes
    ]
    db.query(models.AccessSectionPermission).filter(
        models.AccessSectionPermission.section_id == section_id
    ).delete(synchronize_session=False)
    for pid in perm_ids:
        db.add(models.AccessSectionPermission(section_id=section_id, permission_id=pid))
    audit(db, user, "update", "access_section", section, f"تحديث صلاحيات القسم: {section.name} ({len(perm_ids)} صلاحية)")
    db.commit()
    db.refresh(section)
    return _section_out(db, section)


# ---------- المستخدم: الموروث + الاستثناءات + الفعلي ----------


def _user_assigned_section_ids(db: Session, user_id: int, company_id: int, membership) -> List[int]:
    """كل أقسام الصلاحيات المسندة للمستخدم: جدول الأقسام المتعددة + الإسناد القديم."""
    ids: Set[int] = set()
    if membership is not None and membership.section_id:
        ids.add(membership.section_id)
    ids.update(
        db.execute(
            select(models.UserSectionAccess.section_id)
            .where(
                models.UserSectionAccess.user_id == user_id,
                models.UserSectionAccess.company_id == company_id,
            )
            .execution_options(ignore_tenant_scope=True)
        ).scalars()
    )
    return sorted(ids)


def _user_permission_detail(db: Session, target: models.User, company_id: int) -> UserPermissionDetail:
    membership = db.execute(
        select(models.UserCompanyMembership)
        .where(
            models.UserCompanyMembership.user_id == target.id,
            models.UserCompanyMembership.company_id == company_id,
        )
        .execution_options(ignore_tenant_scope=True)
    ).scalar_one_or_none()

    assigned_ids = _user_assigned_section_ids(db, target.id, company_id, membership)
    inherited: List[dict] = []
    sections: List[models.AccessSection] = []
    if assigned_ids:
        sections = db.execute(
            select(models.AccessSection)
            .where(models.AccessSection.id.in_(assigned_ids))
            .order_by(models.AccessSection.id)
            .execution_options(ignore_tenant_scope=True)
        ).scalars().all()
        rows = db.execute(
            select(models.Permission)
            .join(
                models.AccessSectionPermission,
                models.AccessSectionPermission.permission_id == models.Permission.id,
            )
            .where(models.AccessSectionPermission.section_id.in_(assigned_ids))
            .order_by(models.Permission.code)
            .execution_options(ignore_tenant_scope=True)
        ).scalars().all()
        inherited = [{"code": p.code, "label": p.label, "source": "section"} for p in rows]
    inherited.append(
        {"code": "hr.me.use", "label": "بوابة الموظف (خدمتي)", "source": "baseline"}
    )

    overrides = []
    if membership is not None:
        rows = db.execute(
            select(models.UserPermissionOverride, models.Permission)
            .join(models.Permission, models.Permission.id == models.UserPermissionOverride.permission_id)
            .where(
                models.UserPermissionOverride.user_id == target.id,
                models.UserPermissionOverride.company_id == company_id,
            )
            .order_by(models.Permission.code)
            .execution_options(ignore_tenant_scope=True)
        ).all()
        for ov, perm in rows:
            overrides.append(
                {
                    "code": perm.code,
                    "label": perm.label,
                    "effect": ov.effect,
                    "reason": ov.reason,
                }
            )

    effective = effective_permissions(db, target, company_id=company_id)
    return UserPermissionDetail(
        user_id=target.id,
        company_id=company_id,
        section_id=assigned_ids[0] if assigned_ids else None,
        section_name=sections[0].name if sections else None,
        section_ids=assigned_ids,
        section_names=[s.name for s in sections],
        role=membership.role if membership else (target.role or "staff"),
        inherited=sorted(inherited, key=lambda x: x["code"]),
        overrides=overrides,
        effective=sorted(effective),
    )


class SectionAssignIn(BaseModel):
    section_id: Optional[int] = None  # إسناد مفرد (توافق مع الواجهات السابقة)
    section_ids: Optional[List[int]] = None  # عدة أقسام لموظف واحد — الصلاحية اتحادها


@router.put("/auth/users/{user_id}/section", response_model=UserPermissionDetail, dependencies=_protect)
def assign_user_section(
    user_id: int,
    payload: SectionAssignIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """إسناد أقسام الصلاحيات للمستخدم في الشركة النشطة — يقبل قسماً واحداً أو عدة أقسام."""
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستخدم غير موجود")
    company_id = db.info["company_id"]
    membership = db.execute(
        select(models.UserCompanyMembership)
        .where(
            models.UserCompanyMembership.user_id == user_id,
            models.UserCompanyMembership.company_id == company_id,
        )
        .execution_options(ignore_tenant_scope=True)
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستخدم ليس عضواً في الشركة النشطة")

    # القائمة الجديدة هي المرجع؛ إن أُرسل حقل قديم مفرد نطبّعه داخل القائمة.
    section_ids = list(dict.fromkeys(payload.section_ids)) if payload.section_ids is not None else (
        [payload.section_id] if payload.section_id is not None else []
    )
    if membership.role in ("admin", "manager") and section_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "أدوار الإدارة تتجاوز الصلاحيات — لا حاجة لقسم")
    if section_ids:
        found = db.execute(
            select(models.AccessSection.id, models.AccessSection.company_id)
            .where(models.AccessSection.id.in_(section_ids))
            .execution_options(ignore_tenant_scope=True)
        ).all()
        missing = set(section_ids) - {row[0] for row in found}
        if missing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"أقسام غير موجودة: {sorted(missing)}")
        wrong_company = {row[0] for row in found if row[1] != company_id}
        if wrong_company:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"أقسام لا تنتمي للشركة النشطة: {sorted(wrong_company)}")

    # إعادة كتابة الأقسام المسندة + مزامنة الحقل القديم (أول قسم) للتوافق.
    db.query(models.UserSectionAccess).filter(
        models.UserSectionAccess.user_id == user_id,
        models.UserSectionAccess.company_id == company_id,
    ).delete(synchronize_session=False)
    for sid in section_ids:
        db.add(models.UserSectionAccess(company_id=company_id, user_id=user_id, section_id=sid))
    membership.section_id = section_ids[0] if section_ids else None
    audit(db, user, "update", "user_section", user_id, f"إسناد {len(section_ids)} قسم صلاحيات لمستخدم #{user_id}: {section_ids}")
    db.commit()
    return _user_permission_detail(db, target, company_id)


@router.get("/auth/users/{user_id}/permissions", response_model=UserPermissionDetail, dependencies=_protect)
def get_user_permissions(user_id: int, db: Session = Depends(get_db)):
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستخدم غير موجود")
    return _user_permission_detail(db, target, db.info["company_id"])


@router.put("/auth/users/{user_id}/overrides", response_model=UserPermissionDetail, dependencies=_protect)
def set_user_overrides(
    user_id: int,
    payload: OverridesIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستخدم غير موجود")
    company_id = db.info["company_id"]
    membership = db.execute(
        select(models.UserCompanyMembership)
        .where(
            models.UserCompanyMembership.user_id == user_id,
            models.UserCompanyMembership.company_id == company_id,
        )
        .execution_options(ignore_tenant_scope=True)
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستخدم ليس عضواً في الشركة النشطة")
    if membership.role in ("admin", "manager"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "لا توجد استثناءات لأدوار الإدارة (لديها كل الصلاحيات)")

    unknown = [o.permission_code for o in payload.overrides if o.permission_code not in KNOWN_CODES]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"أكواد صلاحيات غير معروفة: {unknown[:5]}")

    from ..permissions import get_or_create_permission

    db.query(models.UserPermissionOverride).filter(
        models.UserPermissionOverride.user_id == user_id,
        models.UserPermissionOverride.company_id == company_id,
    ).delete(synchronize_session=False)
    for item in payload.overrides:
        db.add(
            models.UserPermissionOverride(
                user_id=user_id,
                permission_id=get_or_create_permission(db, item.permission_code).id,
                effect=item.effect,
                reason=item.reason,
                granted_by=user.id,
            )
        )
    audit(db, user, "update", "user_permissions", user_id, f"تحديث استثناءات صلاحيات مستخدم #{user_id} ({len(payload.overrides)})")
    db.commit()
    return _user_permission_detail(db, target, company_id)
