"""محرك الصلاحيات — الحساب الفعلي، البوابة المركزية، وأقنعة الحقول."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Dict, Optional, Set

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from .catalog import BASELINE_PERMISSIONS
from ..database import get_db
from ..deps import get_current_user, user_role
from .rules import PUBLIC_ENDPOINTS, SELF_ENDPOINTS, match_rule

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# ---------------------------------------------------------------------------
# 3) الحساب الفعلي للصلاحيات
# ---------------------------------------------------------------------------

def effective_permissions(db: Session, user, company_id: Optional[int] = None) -> Set[str]:
    """مجموعة الصلاحيات الفعلية للمستخدم في شركة معينة.

    admin/manager/platform-admin → {"*"} (تجاوز كامل — سلوك محفوظ).
    staff → baseline ∪ أقسامه المسندة (اتحاد كل الأقسام) ∪ منوحات − سحبات.
    تُستدعى بعد get_current_user (تضبط db.info) أو بمعرّف شركة صريح (switch-company).
    """
    if company_id is None:
        company_id = db.info.get("company_id")
    role = user_role(user)
    if user.is_platform_admin or role in ("admin", "manager"):
        return {"*"}
    if company_id is None:
        return set(BASELINE_PERMISSIONS)

    # استعلامات صريحة بمعرّف الشركة — بغض النظر عن نطاق الجلسة الحالي.
    membership = db.execute(
        select(models.UserCompanyMembership)
        .where(
            models.UserCompanyMembership.user_id == user.id,
            models.UserCompanyMembership.company_id == company_id,
        )
        .execution_options(ignore_tenant_scope=True)
    ).scalar_one_or_none()

    perms: Set[str] = set(BASELINE_PERMISSIONS)
    # أقسام الصلاحيات: كل الأقسام المسندة (user_section_access) + الإسناد القديم
    # في membership.section_id (توافق مع ما سبق) — الصلاحية الفعلية اتحاد الجميع.
    section_ids: Set[int] = set()
    if membership is not None and membership.section_id:
        section_ids.add(membership.section_id)
    section_ids.update(
        db.execute(
            select(models.UserSectionAccess.section_id)
            .where(
                models.UserSectionAccess.user_id == user.id,
                models.UserSectionAccess.company_id == company_id,
            )
            .execution_options(ignore_tenant_scope=True)
        ).scalars()
    )
    if section_ids:
        codes = db.execute(
            select(models.Permission.code)
            .join(
                models.AccessSectionPermission,
                models.AccessSectionPermission.permission_id == models.Permission.id,
            )
            .where(models.AccessSectionPermission.section_id.in_(section_ids))
            .execution_options(ignore_tenant_scope=True)
        ).scalars().all()
        perms.update(codes)

    overrides = db.execute(
        select(models.UserPermissionOverride, models.Permission.code)
        .join(models.Permission, models.Permission.id == models.UserPermissionOverride.permission_id)
        .where(
            models.UserPermissionOverride.user_id == user.id,
            models.UserPermissionOverride.company_id == company_id,
        )
        .execution_options(ignore_tenant_scope=True)
    ).all()
    for _override, code in overrides:
        override = _override
        if override.effect == "grant":
            perms.add(code)
        else:  # deny — يغلب كل شيء
            perms.discard(code)
    return perms


def user_has_permission(perms: Set[str], *needed: str) -> bool:
    """any-of: تكفي صلاحية واحدة من المطلوب. {"*"} يتجاوز الكل."""
    if "*" in perms:
        return True
    return any(p in perms for p in needed)


current_permissions: ContextVar[Optional[Set[str]]] = ContextVar("current_permissions", default=None)


def can(*needed: str) -> bool:
    """فحص صلاحية داخل سياق الطلب الحالي (للأقنعة والمسلسلات)."""
    perms = current_permissions.get()
    if perms is None:
        return True  # خارج طلب (بذر/سكربتات) — لا إخفاء
    return user_has_permission(perms, *needed)


# ---------------------------------------------------------------------------
# 4) البوابة المركزية — تُركّب كـ dependency عام على مستوى التطبيق
# ---------------------------------------------------------------------------

async def permission_gate(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> None:
    """يُطبَّق على كل مسار: المصادقة أولاً ثم صلاحية المسار المعلنة.

    - المسارات العامة: تمر بلا فحص.
    - مسارات الذات (me/switch-company): مصادقة فقط.
    - أي مسار حقيقي آخر بلا قاعدة معلنة → 403 (فشل مغلق — والتغطية مُتحقق منها باختبار CI).
    """
    path = request.url.path
    method = request.method.upper()

    # مسارات التوثيق والوثائق التفاعلية ليست API عملاً.
    if path in ("/docs", "/redoc", "/openapi.json", "/favicon.ico", "/metrics") or path.startswith(("/docs/",)):
        return
    if (method, path) in PUBLIC_ENDPOINTS:
        return

    # وسوم <img> لا ترسل ترويسات — تسمح بـ token في الاستعلام فقط لطلبات GET
    # لمسارات الصور (ضيق عمداً؛ التوكن في الـ URL قد يظهر في سجلات البروكسي).
    token = token or (
        request.query_params.get("token") if method == "GET" and path.endswith("/image") else None
    )

    user = get_current_user(request, token_header=token, db=db)  # يرفع 401/403 ويضبط db.info ويخزن في request.state

    if (method, path) in SELF_ENDPOINTS:
        return

    if not user.is_platform_admin:
        _company_id = db.info.get("company_id")
        if _company_id is not None:
            _company = db.get(models.Company, _company_id)
            if _company is not None and _company.license_until is not None:
                from ..exports import LOCAL_TZ  # توقيت العمل المحلي — الاستحقاق تقويمي محلي لا UTC
                _today = datetime.now(LOCAL_TZ).date()
                if _today > _company.license_until:
                    # أدمن الشركة نفسه فقط يبقى قادراً على الدخول والتجديد بكلمة السر المحفوظة
                    if user_role(user) != "admin":
                        raise HTTPException(
                            status.HTTP_403_FORBIDDEN,
                            f"انتهت رخصة استخدام البرنامج بتاريخ {_company.license_until.isoformat()} — يرجى التجديد. مدير الشركة يمكنه الدخول والتجديد.",
                        )

    rule = match_rule(method, path)
    if rule is None:
        # فشل مغلق: مسار API حقيقي بلا قاعدة — تكتشفه اختبارات التغطية أيضاً.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Route {method} {path} is not covered by any permission rule",
        )

    perms = effective_permissions(db, user)
    request.state.permissions = perms
    current_permissions.set(perms)
    if user_has_permission(perms, *rule.perms):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "ليس لديك صلاحية للقيام بهذا الإجراء" if perms else "No permission",
    )


def require_permission(*needed: str):
    """Dependency اختياري على مستوى الراوتر (دفاع إضافي فوق البوابة المركزية)."""

    def checker(request: Request) -> None:
        perms = getattr(request.state, "permissions", None)
        if perms is None:
            return  # البوابة لم تشغّل (مسار عام) — الفحص على المسؤولية الأخرى
        if not user_has_permission(perms, *needed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No permission")

    return checker


# ---------------------------------------------------------------------------
# 5) أقنعة الحقول الحساسة — الحقل لا يُرسل أصلاً بلا الصلاحية
# ---------------------------------------------------------------------------

FIELD_MASKS: Dict[str, Dict[str, str]] = {
    "HrEmployee": {"basic_salary": "hr.employee.salary_view", "bank_account": "hr.employee.bank_view"},
    "Product": {"cost_price": "inventory.product.cost_view"},
    "Customer": {"balance": "sales.customer.balance_view"},
    "Supplier": {"balance": "purchasing.supplier.price_view"},
}


def apply_field_masks(model_name: str, out) -> None:
    """يضبط الحقول الحساسة إلى None على كائن إخراج pydantic — وفق FIELD_MASKS (المصدر الوحيد)."""
    for field_name, code in FIELD_MASKS.get(model_name, {}).items():
        if not can(code):
            setattr(out, field_name, None)


def field_mask_validator(model_name: str, field_name: str):
    """يعيد دالة pydantic validator (mode=before) تُقنّع الحقل حسب FIELD_MASKS.

    الاستخدام في schemas.py:
        _mask = field_validator("cost_price", mode="before")(
            classmethod(field_mask_validator("Product", "cost_price"))
        )
    """
    code = FIELD_MASKS[model_name][field_name]

    def _validate(cls, v):
        return v if can(code) else None

    return classmethod(_validate)

