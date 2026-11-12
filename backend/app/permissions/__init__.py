"""نظام الصلاحيات الموحّد — حزمة مقسّمة على ثلاث وحدات:

- ``catalog``: كتالوج الصلاحيات (الشجرة، البذر، الصلاحيات الأساسية).
- ``rules``: قواعد المسارات (تغطية مغلقة لكل نقاط الـ API).
- ``engine``: الحساب الفعلي، البوابة المركزية ``permission_gate``، وأقنعة الحقول.

كل الأسماء العامة تُعاد تصديريها من هنا — ``from app.permissions import X``
يبقى العقد العام كما كان عند وجود الموديول المفرد.
"""

from .catalog import (
    ALL_PERMISSIONS,
    BASELINE_PERMISSIONS,
    CATALOG,
    KNOWN_CODES,
    MODULE_CODES,
    PERM_MANAGE,
    SYSTEM_SECTIONS,
    catalog_tree,
    get_or_create_permission,
    migrate_legacy_user_sections,
    seed_all,
    seed_company_sections,
    seed_permission_catalog,
)
from .engine import (
    FIELD_MASKS,
    apply_field_masks,
    can,
    current_permissions,
    effective_permissions,
    field_mask_validator,
    permission_gate,
    require_permission,
    user_has_permission,
)
from .rules import (
    PUBLIC_ENDPOINTS,
    ROUTE_RULES,
    SELF_ENDPOINTS,
    RouteRule,
    match_rule,
)

__all__ = [
    # catalog
    "ALL_PERMISSIONS",
    "BASELINE_PERMISSIONS",
    "CATALOG",
    "KNOWN_CODES",
    "MODULE_CODES",
    "PERM_MANAGE",
    "SYSTEM_SECTIONS",
    "catalog_tree",
    "get_or_create_permission",
    "migrate_legacy_user_sections",
    "seed_all",
    "seed_company_sections",
    "seed_permission_catalog",
    # engine
    "FIELD_MASKS",
    "apply_field_masks",
    "can",
    "current_permissions",
    "effective_permissions",
    "field_mask_validator",
    "permission_gate",
    "require_permission",
    "user_has_permission",
    # rules
    "PUBLIC_ENDPOINTS",
    "ROUTE_RULES",
    "SELF_ENDPOINTS",
    "RouteRule",
    "match_rule",
]
