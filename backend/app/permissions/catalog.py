"""كتالوج الصلاحيات — الشجرة والبذر (الجزء الأول من نظام الصلاحيات)."""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models

# ---------------------------------------------------------------------------
# 1) كتالوج الصلاحيات — شجرة: وحدة → مورد → إجراءات
#    الإجراء: (code_suffix, label_ar, is_dangerous, is_field)
#    كود الصلاحية الكامل: f"{module}.{resource}.{action}"
# ---------------------------------------------------------------------------

# صلاحيات أساسية يملكها كل مستخدم غير مدير تلقائياً (الخدمة الذاتية).
# ملاحظة الأمان: rep_mobile_balance تُمنح افتراضياً لتعمل شاشة التحصيل في تطبيق
# المندوب، لكنها صلاحية مُعلنة قابلة للسحب من قسم المستخدم في شاشة الصلاحيات.
BASELINE_PERMISSIONS: Tuple[str, ...] = ("hr.me.use", "sales.rep.mobile", "sales.customer.rep_mobile_balance")

# صلاحية إدارة الصلاحيات نفسها.
PERM_MANAGE = "admin.user.permissions_manage"

CATALOG: Dict[str, dict] = {
    "sales": {
        "label": "المبيعات",
        "resources": {
            "pos": ("نقطة البيع", [
                ("use", "استخدام نقطة البيع (الدفع/الخروج)", False, False),
                ("invoices", "عرض فواتير نقطة البيع", False, False),
            ]),
            "order": ("أوامر البيع", [
                ("view", "عرض أوامر البيع", False, False),
                ("create", "إنشاء أمر بيع", False, False),
                ("price_increase", "تعديل سعر البيع (زيادة فقط)", False, False),
                ("credit_exceed", "تجاوز حد العميل الائتماني", False, False),
                ("confirm", "تأكيد أمر بيع", False, False),
                ("cancel", "إلغاء أمر بيع", False, False),
                ("pdf", "طباعة أمر البيع PDF", False, False),
                ("quotation_pdf", "طباعة عرض السعر", False, False),
                ("receipt", "طباعة إيصال", False, False),
                ("export", "تصدير أوامر البيع Excel", False, False),
                ("export_eta", "تصدير فاتورة إلكترونية ETA JSON", False, False),
            ]),
            "price_list": ("قوائم الأسعار", [
                ("view", "عرض القوائم", False, False),
                ("create", "إضافة قائمة", False, False),
                ("update", "تعديل قائمة", False, False),
                ("delete", "حذف قائمة", False, False),
            ]),
            "return": ("مرتجعات البيع", [
                ("view", "عرض مرتجعات البيع", False, False),
                ("create", "إنشاء مرتجع بيع", False, False),
            ]),
            "customer": ("العملاء", [
                ("view", "عرض العملاء", False, False),
                ("create", "إضافة عميل", False, False),
                ("update", "تعديل عميل", False, False),
                ("delete", "حذف عميل", False, False),
                ("statement", "كشف حساب عميل", False, False),
                ("statement_pdf", "كشف حساب PDF", False, False),
                ("statement_xlsx", "كشف حساب Excel", False, False),
                ("balance_view", "عرض رصيد العميل (حقل حساس)", False, True),
                ("rep_mobile_balance", "أرصدة العملاء في تطبيق المندوب (التحصيل)", False, True),
            ]),
            "rep": ("المندوبون", [
                ("mobile", "تطبيق المندوب (الحساب المرتبط)", False, False),
                ("view", "عرض المندوبين", False, False),
                ("create", "إضافة مندوب", False, False),
                ("update", "تعديل مندوب", False, False),
                ("delete", "حذف مندوب", False, False),
            ]),
            "shift": ("ورديات الكاشير", [
                ("view", "عرض الورديات", False, False),
                ("open", "فتح وردية", False, False),
                ("close", "إغلاق وردية", False, False),
                ("pdf", "طباعة تقرير وردية", False, False),
            ]),
        },
    },
    "purchasing": {
        "label": "المشتريات",
        "resources": {
            "order": ("أوامر الشراء", [
                ("view", "عرض أوامر الشراء", False, False),
                ("create", "إنشاء أمر شراء", False, False),
                ("cancel", "إلغاء أمر شراء", False, False),
                ("receive", "استلام أمر شراء", False, False),
                ("pdf", "طباعة أمر الشراء", False, False),
                ("export", "تصدير أوامر الشراء", False, False),
            ]),
            "return": ("مرتجعات الشراء", [
                ("view", "عرض مرتجعات الشراء", False, False),
                ("create", "إنشاء مرتجع شراء", False, False),
            ]),
            "supplier": ("الموردون", [
                ("view", "عرض الموردين", False, False),
                ("create", "إضافة مورد", False, False),
                ("update", "تعديل مورد", False, False),
                ("delete", "حذف مورد", False, False),
                ("statement", "كشف حساب مورد", False, False),
                ("statement_pdf", "كشف حساب PDF", False, False),
                ("statement_xlsx", "كشف حساب Excel", False, False),
                ("price_view", "عرض سعر الشراء (حقل حساس)", False, True),
            ]),
        },
    },
    "inventory": {
        "label": "المخازون والأصناف",
        "resources": {
            "product": ("الأصناف", [
                ("view", "عرض الأصناف", False, False),
                ("create", "إضافة صنف", False, False),
                ("update", "تعديل صنف", False, False),
                ("delete", "حذف صنف", False, False),
                ("adjust_stock", "تسوية مخزون صنف", True, False),
                ("movements", "عرض حركات الصنف", False, False),
                ("stock", "عرض أرصدة الصنف", False, False),
                ("import", "استيراد أصناف Excel", False, False),
                ("template", "تنزيل قالب الاستيراد", False, False),
                ("export", "تصدير الأصناف Excel", False, False),
                ("cost_view", "عرض تكلفة الصنف (حقل حساس)", False, True),
            ]),
            "warehouse": ("المخازن", [
                ("view", "عرض المخازن", False, False),
                ("create", "إضافة مخزن", False, False),
                ("update", "تعديل مخزن", False, False),
                ("delete", "حذف مخزن", False, False),
            ]),
            "lot": ("اللوطات", [
                ("view", "عرض اللوطات", False, False),
                ("create", "استلام لوط / إنشاء", False, False),
                ("update", "تعديل بيانات لوط", False, False),
                ("write_off", "إعدام/هالك من لوط", True, False),
            ]),
            "transfer": ("التحويلات المخزنية", [
                ("view", "عرض التحويلات", False, False),
                ("create", "إنشاء تحويل", False, False),
                ("edit", "تعديل تحويل", False, False),
                ("approve", "اعتماد تحويل", False, False),
                ("reject", "رفض تحويل", False, False),
                ("delete", "حذف تحويل", False, False),
                ("pdf", "طباعة تحويل", False, False),
                ("pending_count", "عدد التحويلات المعلقة", False, False),
            ]),
            "stocktake": ("الجرد", [
                ("view", "عرض عمليات الجرد", False, False),
                ("create", "بدء جرد", False, False),
                ("counts", "تسجيل عجز/زيادة الجرد", False, False),
                ("lines", "إضافة بنود جرد", False, False),
                ("apply", "تطبيق الجرد على المخزون", True, False),
                ("adjust", "تسوية بناءً على جرد", True, False),
                ("cancel", "إلغاء جرد", False, False),
                ("export", "تصدير الجرد Excel", False, False),
            ]),
        },
    },
    "crm": {
        "label": "العملاء المحتملون (CRM)",
        "resources": {
            "lead": ("العملاء المحتملون", [
                ("view", "عرض العملاء المحتملين", False, False),
                ("create", "إضافة عميل محتمل", False, False),
                ("update", "تعديل عميل محتمل / تغيير المرحلة", False, False),
                ("delete", "حذف عميل محتمل", True, False),
                ("convert", "تحويل عميل محتمل لعميل فعلي", False, False),
                ("activity", "تسجيل أنشطة المتابعة (مكالمة/اجتماع)", False, False),
            ]),
        },
    },
    "accounting": {
        "label": "المحاسبة",
        "resources": {
            "payment": ("سندات القبض والصرف", [
                ("view", "عرض السندات", False, False),
                ("create", "إنشاء سند", False, False),
                ("void", "إلغاء سند (إبعاده)", True, False),
            ]),
            "payment_category": ("فئات الدفع", [
                ("view", "عرض الفئات", False, False),
                ("create", "إضافة فئة", False, False),
            ]),
            "cheque": ("الشيكات", [
                ("view", "عرض الشيكات", False, False),
                ("create", "إضافة شيك", False, False),
                ("collect", "تحصيل شيك", False, False),
                ("deposit", "إيداع شيك", False, False),
                ("return_cheque", "إرجاع شيك", False, False),
                ("cash_out", "صرف نقدي لشيك", False, False),
            ]),
            "safe": ("الخزائن", [
                ("view", "عرض الخزائن", False, False),
                ("create", "إضافة خزنة", False, False),
                ("update", "تعديل خزنة", False, False),
                ("delete", "حذف خزنة", False, False),
                ("statement", "كشف حركة خزنة", False, False),
            ]),
            "bank": ("البنوك", [
                ("view", "عرض البنوك", False, False),
                ("create", "إضافة بنك", False, False),
                ("update", "تعديل بنك", False, False),
                ("delete", "حذف بنك", False, False),
                ("statement", "كشف حركة بنك", False, False),
            ]),
            "account": ("شجرة الحسابات", [
                ("view", "عرض الحسابات", False, False),
                ("create", "إضافة حساب", False, False),
                ("update", "تعديل حساب", False, False),
                ("delete", "حذف حساب", True, False),
                ("roll_up", "إعادة احتساب أرصدة المجموعيات", False, False),
                ("seed", "تهيئة الشجرة الافتراضية", False, False),
                ("import", "استيراد حسابات", False, False),
                ("backfill_links", "إعادة ربط الحسابات", False, False),
                ("reconcile", "عرض المطابقة البنكية", False, False),
                ("reconcile_apply", "تطبيق المطابقة", False, False),
                ("reconcile_sync_cash", "مزامنة نقدية للمطابقة", False, False),
            ]),
            "journal": ("القيود اليومية", [
                ("view", "عرض القيود", False, False),
                ("create", "إنشاء قيد", False, False),
                ("update", "تعديل قيد", False, False),
                ("delete", "حذف قيد", True, False),
                ("approve", "اعتماد/رفض القيود المعلّقة", False, False),
            ]),
            "ledger": ("دفتر الأستاذ", [
                ("view", "دفتر الأستاذ العام", False, False),
                ("account", "حركات حساب", False, False),
                ("cost_center", "حركات مركز تكلفة", False, False),
            ]),
            "cost_center": ("مراكز التكلفة", [
                ("view", "عرض المراكز", False, False),
                ("create", "إضافة مركز", False, False),
                ("update", "تعديل مركز", False, False),
                ("delete", "حذف مركز", False, False),
            ]),
            "fiscal_year": ("السنوات المالية", [
                ("view", "عرض السنوات والأشهر", False, False),
                ("create", "إضافة سنة", False, False),
                ("update", "تعديل/إقفال سنة أو شهر", False, False),
                ("delete", "حذف سنة", False, False),
            ]),
            "recurring": ("القيود المتكررة", [
                ("view", "عرض القوالب والمستحق", False, False),
                ("create", "إضافة قالب", False, False),
                ("update", "تعديل قالب", False, False),
                ("delete", "حذف قالب", False, False),
                ("run", "ترحيل القيود المستحقة", False, False),
            ]),
            "attachment": ("مرفقات السندات والقيود", [
                ("view", "عرض/تنزيل المرفقات", False, False),
                ("create", "إضافة مرفق", False, False),
                ("delete", "حذف مرفق", False, False),
            ]),
            "bankrec": ("المطابقة البنكية", [
                ("view", "عرض كشف البنك والملخص", False, False),
                ("import", "استيراد كشف بنك CSV", False, False),
                ("match", "مطابقة/فك مطابقة السطور", False, False),
                ("delete", "حذف سطر كشف", False, False),
            ]),
            "currency": ("العملات وأسعار الصرف", [
                ("view", "عرض العملات", False, False),
                ("create", "إضافة عملة", False, False),
                ("update", "تحديث سعر الصرف/إيقاف", False, False),
            ]),
            "asset": ("الأصول الثابتة", [
                ("view", "عرض الأصول", False, False),
                ("create", "إضافة أصل", False, False),
                ("update", "تعديل أصل", False, False),
                ("delete", "حذف أصل", False, False),
                ("depreciate", "تسجيل إهلاك", False, False),
                ("dispose", "استبعاد أصل", False, False),
            ]),
        },
    },
    "eta": {
        "label": "الفاتورة الإلكترونية",
        "resources": {
            "config": ("إعداد المنظومة", [
                ("view", "عرض الإعداد", False, False),
                ("update", "تعديل الإعداد وتوليد المفاتيح", True, False),
            ]),
            "document": ("إرسال ومتابعة الفواتير", [
                ("view", "عرض حالات الإرسال", False, False),
                ("submit", "إرسال فاتورة وتحديث حالتها", False, False),
            ]),
            "archive": ("الأرشفة الإلكترونية", [
                ("view", "عرض سجل الأرشفة وتنزيل XML", False, False),
                ("run", "أرشفة المستندات الجاهزة", False, False),
            ]),
            "device": ("أجهزة توقيع الإيصالات", [
                ("view", "عرض الأجهزة وCSR", False, False),
                ("manage", "تسجيل وتفعيل وإلغاء الأجهزة", False, False),
            ]),
        },
    },
    "manufacturing": {
        "label": "التصنيع",
        "resources": {
            "bom": ("قوائم المواد BOM", [
                ("view", "عرض القوائم", False, False),
                ("create", "إضافة قائمة", False, False),
                ("update", "تعديل قائمة", False, False),
                ("delete", "حذف قائمة", False, False),
            ]),
            "order": ("أوامر التصنيع", [
                ("view", "عرض الأوامر", False, False),
                ("create", "إنشاء أمر تصنيع", False, False),
                ("delete", "حذف أمر", True, False),
                ("issue", "صرف مواد", False, False),
                ("produce", "تسجيل إنتاج", False, False),
                ("scrape", "تسجيل هالك", False, False),
                ("qc", "فحص جودة تشغيلة", False, False),
                ("trace", "تتبع التشغيلات", False, False),
                ("cancel", "إلغاء أمر", False, False),
                ("cancel_running", "إلغاء أمر جارٍ", True, False),
                ("close", "إغلاق أمر", False, False),
                ("costs", "إضافة تكاليف أمر", False, False),
                ("costs_delete", "حذف تكلفة أمر", False, False),
                ("children", "عرض أوامر الأبناء", False, False),
                ("availability", "فحص توفر المواد", False, False),
                ("mrp_aggregate", "تجميع MRP", False, False),
                ("mrp_suggestions", "اقتراحات MRP", False, False),
                ("operations_issue", "صرف عملية تشغيل", False, False),
                ("operations_progress", "تحديث تقدم عملية", False, False),
                ("print_card", "طباعة بطاقة التشغيل", False, False),
                ("schedule", "جدولة أوامر التصنيع", False, False),
                ("report_summary", "تقرير ملخص التصنيع", False, False),
                ("report_wip", "تقرير تحت التشغيل WIP", False, False),
                ("report_work_centers", "تقرير أداء مراكز التشغيل", False, False),
            ]),
            "line": ("خطوط الإنتاج", [
                ("view", "عرض الخطوط", False, False),
                ("create", "إضافة خط", False, False),
                ("update", "تعديل خط", False, False),
                ("delete", "حذف خط", False, False),
            ]),
            "work_center": ("مراكز العمل", [
                ("view", "عرض المراكز", False, False),
                ("create", "إضافة مركز", False, False),
                ("update", "تعديل مركز", False, False),
                ("delete", "حذف مركز", False, False),
            ]),
            "quality": ("إدارة الجودة", [
                ("view", "عرض نماذج الجودة", False, False),
                ("manage", "إدارة نماذج الجودة والمعايير", False, False),
            ]),
        },
    },
    "hr": {
        "label": "الموارد البشرية",
        "resources": {
            "me": ("الخدمة الذاتية", [
                ("use", "بوابة الموظف (خدمتي)", False, False),
            ]),
            "employee": ("الموظفون", [
                ("view", "عرض الموظفين", False, False),
                ("create", "إضافة موظف", False, False),
                ("update", "تعديل موظف", False, False),
                ("delete", "حذف موظف", True, False),
                ("salary_view", "عرض الراتب (حقل حساس)", False, True),
                ("bank_view", "عرض حساب البنك (حقل حساس)", False, True),
            ]),
            "contract": ("العقود", [
                ("view", "عرض العقود", False, False),
                ("create", "إضافة عقد", False, False),
                ("update", "تعديل عقد", False, False),
                ("delete", "حذف عقد", False, False),
            ]),
            "document": ("مستندات الموظفين", [
                ("view", "عرض المستندات", False, False),
                ("create", "رفع مستند", False, False),
                ("download", "تنزيل مستند", False, False),
                ("delete", "حذف مستند", False, False),
            ]),
            "move": ("التنقلات الوظيفية", [
                ("view", "عرض التنقلات", False, False),
                ("create", "تسجيل تنقل", False, False),
            ]),
            "settlement": ("التسويات النهائية", [
                ("view", "عرض التسويات", False, False),
                ("create", "إنشاء تسوية نهائية", False, False),
            ]),
            "shift": ("ورديات HR", [
                ("view", "عرض الورديات", False, False),
                ("create", "إضافة وردية", False, False),
                ("update", "تعديل وردية", False, False),
                ("delete", "حذف وردية", False, False),
            ]),
            "shift_assignment": ("إسناد الورديات", [
                ("view", "عرض الإسنادات", False, False),
                ("create", "إسناد وردية", False, False),
            ]),
            "attendance": ("الحضور والانصراف", [
                ("view", "عرض الحضور", False, False),
                ("record", "تسجيل حضور/انصراف", False, False),
                ("edit", "تعديل سجل حضور", False, False),
                ("delete", "حذف سجل حضور", False, False),
            ]),
            "attendance_correction": ("تصحيحات الحضور", [
                ("view", "عرض طلبات التصحيح", False, False),
                ("approve", "اعتماد تصحيح", False, False),
                ("reject", "رفض تصحيح", False, False),
            ]),
            "holiday": ("العطل الرسمية", [
                ("view", "عرض العطل", False, False),
                ("create", "إضافة عطلة", False, False),
                ("delete", "حذف عطلة", False, False),
            ]),
            "job_title": ("المسميات الوظيفية", [
                ("view", "عرض المسميات", False, False),
                ("create", "إضافة مسمى", False, False),
                ("update", "تعديل مسمى", False, False),
                ("delete", "حذف مسمى", False, False),
            ]),
            "grade": ("الدرجات الوظيفية", [
                ("view", "عرض الدرجات", False, False),
                ("create", "إضافة درجة", False, False),
                ("update", "تعديل درجة", False, False),
                ("delete", "حذف درجة", False, False),
            ]),
            "leave_type": ("أنواع الإجازات", [
                ("view", "عرض الأنواع", False, False),
                ("create", "إضافة نوع", False, False),
                ("update", "تعديل نوع", False, False),
                ("delete", "حذف نوع", False, False),
            ]),
            "leave_balance": ("أرصدة الإجازات", [
                ("view", "عرض الأرصدة", False, False),
                ("update", "تعديل رصيد", False, False),
            ]),
            "leave": ("طلبات الإجازات", [
                ("view", "عرض الطلبات", False, False),
                ("chain_view", "عرض مسارات الموافقات", False, False),
                ("chain_manage", "ضبط مسارات الموافقات", False, False),
                ("create", "إنشاء طلب", False, False),
                ("approve", "اعتماد طلب", False, False),
                ("reject", "رفض طلب", False, False),
                ("cancel", "إلغاء طلب", False, False),
            ]),
            "salary_component": ("بنود الراتب", [
                ("view", "عرض البنود", False, False),
                ("create", "إضافة بند", False, False),
                ("update", "تعديل بند", False, False),
                ("delete", "حذف بند", False, False),
            ]),
            "payroll": ("الرواتب (المسيرات)", [
                ("view", "عرض المسيرات", False, False),
                ("create", "توليد مسير", False, False),
                ("recalculate", "إعادة احتساب مسير", False, False),
                ("post", "ترحيل مسير (نهائي)", True, False),
                ("delete", "حذف مسير", True, False),
                ("wps_csv", "ملف WPS البنكي", False, False),
                ("form_6h", "نموذج 6ح التأمينات", False, False),
                ("form4", "إقرار ضريبة كسب العمل", False, False),
            ]),
            "payslip": ("قسائم الرواتب", [
                ("view", "عرض القسائم", False, False),
            ]),
            "advance": ("السلف", [
                ("view", "عرض السلف", False, False),
                ("create", "إنشاء سلفة", False, False),
                ("update", "تعديل سلفة", False, False),
                ("delete", "حذف سلفة", False, False),
            ]),
            "posting": ("الوظائف الشاغرة", [
                ("view", "عرض الإعلانات", False, False),
                ("create", "إعلان وظيفة", False, False),
                ("update", "تعديل إعلان", False, False),
                ("add_applicant", "إضافة متقدم", False, False),
            ]),
            "applicant": ("المتقدمون", [
                ("view", "عرض المتقدمين", False, False),
                ("update", "تعديل متقدم", False, False),
                ("advance", "ترقية مرحلة متقدم", False, False),
                ("hire", "تعيين متقدم", False, False),
                ("reject", "رفض متقدم", False, False),
            ]),
            "cycle": ("دورات التقييم", [
                ("view", "عرض الدورات", False, False),
                ("create", "إنشاء دورة", False, False),
                ("close", "إغلاق دورة", False, False),
            ]),
            "review": ("تقييمات الأداء", [
                ("view", "عرض التقييمات", False, False),
                ("create", "إنشاء تقييم", False, False),
                ("update", "تعديل تقييم", False, False),
            ]),
            "training": ("التدريب", [
                ("view", "عرض البرامج", False, False),
                ("create", "إنشاء برنامج", False, False),
                ("update", "تعديل برنامج", False, False),
            ]),
            "enrollment": ("المسجلون في التدريب", [
                ("view", "عرض المسجلين", False, False),
                ("create", "تسجيل موظف", False, False),
                ("complete", "إتمام تدريب", False, False),
                ("no_show", "تسجيل عدم حضور", False, False),
            ]),
            "analytics": ("تحليلات HR", [
                ("view", "عرض التحليلات", False, False),
            ]),
            "summary": ("ملخص HR", [
                ("view", "عرض الملخص", False, False),
            ]),
        },
    },
    "admin": {
        "label": "الإدارة العامة",
        "resources": {
            "backup": ("النسخ الاحتياطي", [
                ("view", "عرض وتنزيل النسخ", False, False),
                ("create", "إنشاء نسخة", False, False),
                ("delete", "حذف نسخة", True, False),
                ("restore", "استعادة نسخة (يستبدل كل البيانات)", True, False),
            ]),
            "user": ("المستخدمون", [
                ("view", "عرض المستخدمين", False, False),
                ("create", "إضافة مستخدم", False, False),
                ("update", "تعديل مستخدم", False, False),
                ("delete", "حذف مستخدم", False, False),
                ("activity", "عرض نشاط مستخدم", False, False),
                ("permissions_manage", "إدارة الصلاحيات والأقسام", False, False),
            ]),
            "company": ("بيانات الشركة", [
                ("view", "عرض إعدادات الشركة", False, False),
                ("update", "تعديل إعدادات الشركة", False, False),
                ("license_renew", "تجديد رخصة الشركة بكلمة السر", False, False),
            ]),
            "branch": ("الفروع", [
                ("view", "عرض الفروع", False, False),
                ("create", "إضافة فرع", False, False),
            ]),
            "department": ("الإدارات", [
                ("view", "عرض الإدارات", False, False),
                ("create", "إضافة إدارة", False, False),
                ("update", "تعديل إدارة", False, False),
                ("delete", "حذف إدارة", False, False),
            ]),
            "company_employee": ("موظفو الشركة", [
                ("view", "عرض سجل الشركة", False, False),
                ("create", "إنشاء سجل موظف", False, False),
                ("update", "تعديل سجل موظف", False, False),
            ]),
            "audit": ("سجل التدقيق", [
                ("view", "عرض سجل التدقيق", False, False),
            ]),
            "dataio": ("استيراد وتصدير البيانات", [
                ("history", "عرض سجل العمليات", False, False),
                ("import", "استيراد بيانات Excel", False, False),
                ("export", "تصدير بيانات Excel", False, False),
                ("template", "تنزيل قوالب الاستيراد", False, False),
                ("stock_undo", "تراجع عن مخزون مستورد", True, False),
            ]),
        },
    },
    "taxes": {
        "label": "الضرائب",
        "resources": {
            "vat": ("ضريبة القيمة المضافة", [
                ("view", "عرض إقرار القيمة المضافة", False, False),
                ("export", "تصدير إقرار القيمة المضافة", False, False),
            ]),
            "withholding": ("ضريبة الخصم والإضافة", [
                ("view", "عرض تقرير الخصم والإضافة", False, False),
                ("export", "تصدير تقرير الخصم والإضافة", False, False),
                ("manage", "إدارة أكواد الخصم والإضافة", False, False),
            ]),
            "payroll": ("ضريبة كسب العمل", [
                ("view", "عرض حساب ضريبة كسب العمل", False, False),
                ("export", "تصدير ضريبة كسب العمل", False, False),
                ("manage", "إدارة شرائح وإعدادات ضريبة كسب العمل", False, False),
            ]),
        },
    },
    "reports": {
        "label": "التقارير",
        "resources": {
            "dashboard": ("لوحة التقارير", [
                ("view", "عرض لوحة التقارير", False, False),
            ]),
            "financial": ("التقارير المالية", [
                ("balance_sheet", "الميزانية العمومية", False, False),
                ("profit_loss", "الأرباح والخسائر", False, False),
                ("profit_loss_detail", "تفصيل الأرباح والخسائر", False, False),
                ("trial_balance", "ميزان المراجعة", False, False),
                ("inventory_reconcile", "مطابقة المخزون مع الدفاتر", False, False),
                ("vat_return", "إقرار ضريبة القيمة المضافة", False, False),
                ("commissions", "عمولات المندوبين", False, False),
                ("customer_credits", "أرصدة العملاء الدائنة", False, False),
                ("vat_return_export", "تصدير إقرار الضريبة", False, False),
            ]),
            "inventory": ("تقارير المخزون", [
                ("purchase_suggestions", "اقتراحات الشراء", False, False),
                ("purchase_suggestions_export", "تصدير اقتراحات الشراء", False, False),
                ("lots_expiring", "لوطات تنتهي قريبًا", False, False),
                ("lots_expiring_export", "تصدير اللوطات المنتهية", False, False),
                ("movements", "سجل حركات المخزون", False, False),
                ("movements_export", "تصدير حركات المخزون", False, False),
                ("valuation", "تقييم المخزون", False, False),
                ("valuation_export", "تصدير تقييم المخزون", False, False),
                ("low_stock", "الأصناف المنخفضة", False, False),
                ("low_stock_export", "تصدير الأصناف المنخفضة", False, False),
            ]),
            "purchasing": ("تقارير المشتريات", [
                ("payables", "الذمم الدائنة", False, False),
                ("payables_export", "تصدير الذمم الدائنة", False, False),
                ("payables_aging", "أعمار الذمم الدائنة", False, False),
                ("payables_aging_export", "تصدير أعمار الذمم الدائنة", False, False),
                ("summary", "ملخص المشتريات", False, False),
                ("summary_export", "تصدير ملخص المشتريات", False, False),
            ]),
            "sales": ("تقارير المبيعات", [
                ("receivables", "الذمم المدينة", False, False),
                ("receivables_export", "تصدير الذمم المدينة", False, False),
                ("receivables_aging", "أعمار الذمم المدينة", False, False),
                ("receivables_aging_export", "تصدير أعمار الذمم المدينة", False, False),
                ("summary", "ملخص المبيعات", False, False),
                ("commissions", "عمولات المندوبين", False, False),
                ("customer_credits", "أرصدة العملاء الدائنة", False, False),
                ("summary_export", "تصدير ملخص المبيعات", False, False),
                ("profit", "تقرير الأرباح", False, False),
                ("profit_export", "تصدير تقرير الأرباح", False, False),
            ]),
        },
    },
    "platform": {
        "label": "إدارة المنصة (خارج الشركات)",
        "resources": {
            "company": ("الشركات", [
                ("view", "عرض الشركات", False, False),
                ("create", "إنشاء شركة", False, False),
                ("update", "تعديل شركة", False, False),
            ]),
            "admin": ("مدير الشركة", [
                ("view", "عرض بيانات المدير", False, False),
                ("update", "تعديل مدير الشركة", False, False),
            ]),
            "banks": ("بنوك الشركة", [
                ("view", "عرض بنوك الشركة", False, False),
                ("create", "إضافة بنك", False, False),
                ("update", "تعديل بنك", False, False),
                ("delete", "حذف بنك", False, False),
            ]),
            "branches": ("فروع الشركة", [
                ("view", "عرض فروع الشركة", False, False),
                ("create", "إضافة فرع", False, False),
                ("update", "تعديل فرع", False, False),
                ("delete", "حذف فرع", False, False),
            ]),
            "departments": ("إدارات الشركة", [
                ("view", "عرض إدارات الشركة", False, False),
                ("create", "إضافة إدارة", False, False),
                ("update", "تعديل إدارة", False, False),
                ("delete", "حذف إدارة", False, False),
            ]),
            "members": ("أعضاء الشركة", [
                ("view", "عرض أعضاء الشركة", False, False),
                ("create", "إضافة عضو", False, False),
                ("delete", "حذف عضو", False, False),
            ]),
            "safes": ("خزائن الشركة", [
                ("view", "عرض خزائن الشركة", False, False),
                ("create", "إضافة خزينة", False, False),
                ("update", "تعديل خزينة", False, False),
            ]),
            "warehouses": ("مخازن الشركة", [
                ("view", "عرض مخازن الشركة", False, False),
                ("create", "إضافة مخزن", False, False),
                ("update", "تعديل مخزن", False, False),
                ("delete", "حذف مخزن", False, False),
            ]),
        },
    },
}


def _flatten(catalog=CATALOG) -> Dict[str, dict]:
    """كود الصلاحية → بياناته (module, resource, action, label, is_dangerous, is_field)."""
    out: Dict[str, dict] = {}
    for module, mdata in catalog.items():
        for resource, (rlabel, actions) in mdata["resources"].items():
            for action, alabel, dangerous, fld in actions:
                code = f"{module}.{resource}.{action}"
                out[code] = {
                    "code": code,
                    "module": module,
                    "module_label": mdata["label"],
                    "resource": resource,
                    "resource_label": rlabel,
                    "action": action,
                    "label": alabel,
                    "is_dangerous": dangerous,
                    "is_field": fld,
                }
    return out


ALL_PERMISSIONS: Dict[str, dict] = _flatten()

#: كل أكواد كل وحدة — تستخدم في بذر الأقسام النظامية.
MODULE_CODES: Dict[str, List[str]] = {}
for _code, _info in ALL_PERMISSIONS.items():
    MODULE_CODES.setdefault(_info["module"], []).append(_code)

KNOWN_CODES: Set[str] = set(ALL_PERMISSIONS)


def catalog_tree() -> dict:
    """الكتالوج بصيغة شجرة للواجهة."""
    tree = []
    for module, mdata in CATALOG.items():
        resources = []
        for resource, (rlabel, actions) in mdata["resources"].items():
            resources.append(
                {
                    "resource": resource,
                    "label": rlabel,
                    "permissions": [
                        {
                            "code": f"{module}.{resource}.{a}",
                            "action": a,
                            "label": lbl,
                            "is_dangerous": d,
                            "is_field": f,
                        }
                        for a, lbl, d, f in actions
                    ],
                }
            )
        tree.append({"module": module, "label": mdata["label"], "resources": resources})
    return tree


def get_or_create_permission(db: Session, code: str) -> models.Permission:
    """يجلب صف الصلاحية من الكتالوج المبذور أو ينشئه من الكود — يمنع الصمت إن سبق البذر."""
    row = db.execute(
        select(models.Permission).where(models.Permission.code == code).execution_options(ignore_tenant_scope=True)
    ).scalar_one_or_none()
    if row is not None:
        return row
    info = ALL_PERMISSIONS[code]
    row = models.Permission(
        code=code,
        module=info["module"],
        resource=info["resource"],
        action=info["action"],
        label=info["label"],
        is_dangerous=info["is_dangerous"],
        is_field=info["is_field"],
    )
    db.add(row)
    db.flush()
    return row


#: صلاحيات الطلب الحالي — تضبطها البوابة وتقرؤها أقنعة الحقول في المُسلسلات.

# ---------------------------------------------------------------------------
# 6) الأقسام النظامية + البذر
# ---------------------------------------------------------------------------

SYSTEM_SECTIONS: List[dict] = [
    {"code": "sales", "name": "المبيعات", "modules": ["sales"]},
    {"code": "purchasing", "name": "المشتريات", "modules": ["purchasing"]},
    {"code": "warehouse", "name": "المخازن", "modules": ["inventory"]},
    {"code": "accounting", "name": "المحاسبة", "modules": ["accounting"]},
    {"code": "eta", "name": "الفاتورة الإلكترونية", "modules": ["eta"]},
    {"code": "manufacturing", "name": "التصنيع", "modules": ["manufacturing"]},
    {"code": "hr", "name": "الموارد البشرية", "modules": ["hr"]},
    {"code": "general", "name": "الإدارة العامة", "modules": ["admin"]},
    {"code": "taxes", "name": "الضرائب", "modules": ["taxes"]},
    {"code": "reports", "name": "التقارير", "modules": ["reports"]},
]


def seed_permission_catalog(db: Session) -> None:
    """يزرع كتالوج الصلاحيات من الكود (عالمي، idempotent) + يزامن التسميات المتغيرة."""
    existing = set(db.execute(select(models.Permission.code).execution_options(ignore_tenant_scope=True)).scalars())
    new_rows = []
    for code, info in ALL_PERMISSIONS.items():
        if code in existing:
            continue
        new_rows.append(
            models.Permission(
                code=code,
                module=info["module"],
                resource=info["resource"],
                action=info["action"],
                label=info["label"],
                is_dangerous=info["is_dangerous"],
                is_field=info["is_field"],
            )
        )
    if new_rows:
        db.add_all(new_rows)

    # مزامنة التسميات: التسمية في الكود هي مصدر الحقيقة — تصحيح أي صف قديم مختلف.
    stale = db.execute(
        select(models.Permission)
        .where(models.Permission.code.in_(set(ALL_PERMISSIONS)))
        .execution_options(ignore_tenant_scope=True)
    ).scalars()
    changed = 0
    for row in stale:
        info = ALL_PERMISSIONS[row.code]
        if row.label != info["label"] or row.is_dangerous != info["is_dangerous"] or row.is_field != info["is_field"]:
            row.label = info["label"]
            row.is_dangerous = info["is_dangerous"]
            row.is_field = info["is_field"]
            changed += 1
    if new_rows or changed:
        db.commit()


def seed_company_sections(db: Session, company_id: int) -> None:
    """يزرع الأقسام النظامية الافتراضية لشركة (idempotent — يعبّئ الأذون عند الإنشاء أو إن كانت فارغة)."""
    for spec in SYSTEM_SECTIONS:
        section = db.execute(
            select(models.AccessSection)
            .where(models.AccessSection.company_id == company_id, models.AccessSection.code == spec["code"])
            .execution_options(ignore_tenant_scope=True)
        ).scalar_one_or_none()
        if section is None:
            section = models.AccessSection(
                company_id=company_id,
                code=spec["code"],
                name=spec["name"],
                is_system=True,
            )
            db.add(section)
            db.flush()

        # القسم موجود مسبقاً — نعبّئ الأذون فقط إن كانت مصفوفته فارغة
        # (يعالج أيضاً حالة بذر فاشل جزئي سابق أنشأ القسم دون صلاحياته).
        has_rows = db.execute(
            select(models.AccessSectionPermission.id)
            .where(models.AccessSectionPermission.section_id == section.id)
            .limit(1)
            .execution_options(ignore_tenant_scope=True)
        ).scalar_one_or_none()
        if has_rows is not None:
            continue

        perm_codes: List[str] = []
        for module in spec["modules"]:
            perm_codes.extend(MODULE_CODES.get(module, []))
        perm_codes.extend(BASELINE_PERMISSIONS)
        # الصفوف (id, code) — نبني الخريطة {code: id} بشكل صريح لتجنّب قلب الترتيب.
        code_to_id: Dict[str, int] = {
            code: perm_id
            for perm_id, code in db.execute(
                select(models.Permission.id, models.Permission.code)
                .where(models.Permission.code.in_(perm_codes))
                .execution_options(ignore_tenant_scope=True)
            ).all()
        }
        # أي كود ناقص من الكتالوج المبذور يُنشأ من التعريف البرمجي مباشرة.
        for code in perm_codes:
            if code not in code_to_id:
                code_to_id[code] = get_or_create_permission(db, code).id
        for pid in code_to_id.values():
            db.add(
                models.AccessSectionPermission(company_id=company_id, section_id=section.id, permission_id=pid)
            )
        # لا commit هنا — المتدعي يتحكم بالذرية (إنشاء الشركة يبقى معكوساً بالكامل عند الفشل).


def migrate_legacy_user_sections(db: Session) -> None:
    """انسخ الإسناد القديم (membership.section_id) إلى جدول الأقسام المتعددة (idempotent).

    قبل تعدد الأقسام كان لكل عضوية قسم واحد في user_company_memberships.section_id؛
    ننسخه إلى user_section_access حتى تُحتسب في اتحاد الصلاحيات من مصدر واحد.
    """
    rows = db.execute(
        select(
            models.UserCompanyMembership.company_id,
            models.UserCompanyMembership.user_id,
            models.UserCompanyMembership.section_id,
        )
        .where(models.UserCompanyMembership.section_id.is_not(None))
        .execution_options(ignore_tenant_scope=True)
    ).all()
    existing = set(
        db.execute(
            select(models.UserSectionAccess.company_id, models.UserSectionAccess.user_id, models.UserSectionAccess.section_id)
            .execution_options(ignore_tenant_scope=True)
        ).all()
    )
    for company_id, user_id, section_id in rows:
        if (company_id, user_id, section_id) in existing:
            continue
        db.add(models.UserSectionAccess(company_id=company_id, user_id=user_id, section_id=section_id))
    db.commit()


def seed_all(engine) -> None:
    """بذر الكتالوج + أقسام كل الشركات القائمة — يُستدعى عند إقلاع التطبيق."""
    from .database import SessionLocal

    db = SessionLocal()
    try:
        seed_permission_catalog(db)
        company_ids = db.execute(
            select(models.Company.id).execution_options(ignore_tenant_scope=True)
        ).scalars().all()
        for cid in company_ids:
            seed_company_sections(db, cid)
        migrate_legacy_user_sections(db)
        db.commit()
    finally:
        db.close()
