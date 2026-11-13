"""SQLAlchemy models for the ERP: inventory, orders, parties, payments and users."""

from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    JSON,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import relationship

from .database import Base


class TenantOwned:
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("code", name="uq_company_code"),
        CheckConstraint(
            "max_warehouses_per_branch IS NULL OR max_warehouses_per_branch > 0",
            name="ck_company_warehouse_limit_positive",
        ),
        CheckConstraint(
            "max_branches IS NULL OR max_branches > 0",
            name="ck_company_branch_limit_positive",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False, unique=True, index=True)
    max_warehouses_per_branch = Column(Integer, nullable=True)
    max_safes_per_branch = Column(Integer, nullable=True)
    max_branches = Column(Integer, nullable=True)
    # رخصة الاستخدام: تاريخ الانتهاء — NULL = غير مقيّد. بعد التاريخ تُوقف عمليات
    # العمل للمستخدمين غير مديري المنصة حتى يتجدد المورد الرخصة.
    license_until = Column(Date, nullable=True)
    # ---- الفاتورة الإلكترونية (ETA) ----
    eta_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    eta_env = Column(String(10), nullable=False, default="mock", server_default="mock")  # mock | sandbox | prod
    eta_tin = Column(String(50), nullable=True)          # الرقم الضريبي (issuer id)
    eta_client_id = Column(String(120), nullable=True)
    eta_client_secret = Column(String(255), nullable=True)  # يُقنَّع في الـ API
    eta_private_key = Column(Text, nullable=True)           # PEM مشفر بمفتاح التطبيق
    eta_activity_code = Column(String(20), nullable=True, server_default="4690")
    # عنوان المُصدر — المنظومة ترفض المستندات بعنوان ناقص
    eta_governate = Column(String(60), nullable=True)
    eta_region_city = Column(String(60), nullable=True)
    eta_street = Column(String(120), nullable=True)
    eta_building_number = Column(String(20), nullable=True)
    # اعتماد القيود (maker-checker): حد بالعملة — أعلى منه يحتاج اعتماد مدير (NULL = معطل)
    je_approval_threshold = Column(Numeric(14, 2), nullable=True)
    # قفل الفترات المحاسبية: أي قيد أو سند بتاريخ أقدم من أو يساوي هذا التاريخ ممنوع الترحيل
    accounting_lock_date = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    branches = relationship("Branch", back_populates="company")
    memberships = relationship("UserCompanyMembership", back_populates="company")


class Branch(TenantOwned, Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_branch_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False)
    location = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    company = relationship("Company", back_populates="branches")
    warehouses = relationship("Warehouse", back_populates="branch")


class Department(TenantOwned, Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_department_company_code"),
        UniqueConstraint("company_id", "name", name="uq_department_company_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    code = Column(String(50), nullable=False, index=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# Sales representatives (مندوبي المبيعات) — standalone company-scoped list
class Currency(TenantOwned, Base):
    """عملة أجنبية بسعر صرفها مقابل الجنيه (العملة الأساسية للنظام).

    الدفاتر والتقارير بالجنيه دائمًا؛ العملة تُخزن على المستند مع سعر الصرف
    لحظة إصداره، وفروق الصرف عند السداد تُرحّل آليًا في 4240/5350."""
    __tablename__ = "currencies"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_currency_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(3), nullable=False, index=True)   # USD / EUR / SAR
    name = Column(String(60), nullable=False)
    rate = Column(Numeric(14, 6), nullable=False, default=1, server_default="1")  # EGP لكل 1 وحدة
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PriceList(TenantOwned, Base):
    """قائمة أسعار (جملة/موزع/خاص): أسعار بديلة لصنف معين تُطبَّق على عملاء مرتبطين بها."""
    __tablename__ = "price_lists"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_price_list_company_name"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    notes = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items = relationship("PriceListItem", back_populates="price_list", cascade="all, delete-orphan")


class PriceListItem(TenantOwned, Base):
    """سعر صنف داخل قائمة — يُستبدل به سعر البيع العام لحامل القائمة."""
    __tablename__ = "price_list_items"
    __table_args__ = (UniqueConstraint("price_list_id", "product_id", name="uq_price_list_item"),)

    id = Column(Integer, primary_key=True, index=True)
    price_list_id = Column(Integer, ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_price = Column(Numeric(12, 2), nullable=False)

    price_list = relationship("PriceList", back_populates="items")


class SalesRep(TenantOwned, Base):
    __tablename__ = "sales_reps"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    code = Column(String(50), nullable=False, index=True)
    phone = Column(String(40), nullable=True)
    commission_percent = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    # حساب دخول تطبيق المندوب: مستخدم staff مرتبط بهذا المندوب (علاقة 1:1)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    branch_access = relationship("SalesRepBranchAccess", back_populates="rep", cascade="all, delete-orphan")
    devices = relationship("RepDevice", back_populates="rep", cascade="all, delete-orphan")
    notifications = relationship("RepNotification", back_populates="rep", cascade="all, delete-orphan")


class RepDevice(TenantOwned, Base):
    """جهاز موبايل لمندوب (توكن FCM) — لتطبيق المندوبين."""
    __tablename__ = "rep_devices"
    __table_args__ = (UniqueConstraint("rep_id", "fcm_token", name="uq_rep_device_token"),)

    id = Column(Integer, primary_key=True, index=True)
    rep_id = Column(Integer, ForeignKey("sales_reps.id", ondelete="CASCADE"), nullable=False, index=True)
    fcm_token = Column(String(255), nullable=False)
    platform = Column(String(10), nullable=False, default="android", server_default="android")  # android | ios
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    rep = relationship("SalesRep", back_populates="devices")


class RepNotification(TenantOwned, Base):
    """صندوق تنبيهات المندوب (يُقرأ من التطبيق) + يُدفع FCM عند توفره."""
    __tablename__ = "rep_notifications"
    __table_args__ = (Index("ix_rep_notif_rep_read", "company_id", "rep_id", "read_at"),)

    id = Column(Integer, primary_key=True, index=True)
    rep_id = Column(Integer, ForeignKey("sales_reps.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(30), nullable=False, default="general", server_default="general")  # order_confirmed | payment | general
    title = Column(String(150), nullable=False)
    body = Column(String(500), nullable=False)
    ref_id = Column(Integer, nullable=True)  # مثلاً رقم أمر البيع
    read_at = Column(DateTime(timezone=True), nullable=True)
    pushed = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    rep = relationship("SalesRep", back_populates="notifications")


class SalesRepBranchAccess(Base):
    __tablename__ = "sales_rep_branch_access"
    __table_args__ = (UniqueConstraint("rep_id", "branch_id", name="uq_sales_rep_branch_access"),)

    id = Column(Integer, primary_key=True, index=True)
    rep_id = Column(Integer, ForeignKey("sales_reps.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)

    rep = relationship("SalesRep", back_populates="branch_access")
    branch = relationship("Branch")


class Warehouse(TenantOwned, Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_warehouse_company_name"),
        UniqueConstraint("company_id", "code", name="uq_warehouse_company_code"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    code = Column(String(50), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    location = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    products = relationship("Product", back_populates="warehouse")
    branch = relationship("Branch", back_populates="warehouses")


class Supplier(TenantOwned, Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_supplier_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), nullable=False, index=True)
    name = Column(String(150), nullable=False, index=True)
    contact_person = Column(String(150), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    # الرقم الضريبي للمورد (فواتير الشراء الواردة من المنظومة B2B)
    tax_registration_number = Column(String(50), nullable=True)
    # Account in Chart of Accounts for this supplier
    chart_account_id = Column(Integer, ForeignKey("chart_accounts.id"), nullable=True, index=True)
    # What the party owed / was owed before this system was used (negative = credit in their favour).
    opening_balance = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    # الحد الائتماني للمورد: سقف المستحقات المسموح تراكمها دون سداد (NULL = بلا حد)
    credit_limit = Column(Numeric(14, 2), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    products = relationship("Product", back_populates="supplier")
    chart_account = relationship("ChartAccount")


class Product(TenantOwned, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("company_id", "sku", name="uq_product_company_sku"),)

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(60), nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    unit = Column(String(30), nullable=False, default="piece", server_default="piece")
    cost_price = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    sale_price = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    quantity = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")
    reorder_level = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    # صورة المنتج: إما رابط إنترنت (image_url) أو ملف مرفوع مباشرة (image_blob)
    image_url = Column(String(500), nullable=True)
    image_blob = Column(LargeBinary, nullable=True)
    image_mime = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    warehouse = relationship("Warehouse", back_populates="products")
    supplier = relationship("Supplier", back_populates="products")

    @property
    def image_uploaded(self) -> bool:
        return self.image_blob is not None


class Customer(TenantOwned, Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_customer_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), nullable=False, index=True)
    name = Column(String(150), nullable=False, index=True)
    contact_person = Column(String(150), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    # Account in Chart of Accounts for this customer
    chart_account_id = Column(Integer, ForeignKey("chart_accounts.id"), nullable=True, index=True)
    # What the party owed / was owed before this system was used (negative = credit in their favour).
    opening_balance = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    # الحد الائتماني: أقصى مديونية مسموحة (NULL = بلا حد) — يُفحص عند تأكيد البيع والـ POS
    credit_limit = Column(Numeric(14, 2), nullable=True)
    # الرقم الضريبي للعميل (B2B) — يُستعمل receiver.id في الفاتورة الإلكترونية
    tax_registration_number = Column(String(50), nullable=True)
    # قائمة الأسعار الخاصة بالعميل (تتجاوز سعر البيع العام عند وجود الصنف فيها)
    price_list_id = Column(Integer, ForeignKey("price_lists.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    sales_orders = relationship("SalesOrder", back_populates="customer")
    chart_account = relationship("ChartAccount")


class PurchaseOrder(TenantOwned, Base):
    """Order placed with a supplier. Stock increases when status becomes 'received'."""

    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="draft", server_default="draft", index=True)
    notes = Column(Text, nullable=True)
    total_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    # تفكيك الإجمالي: يلزم عند الاستلام لترحيل ضريبة المدخلات (1145) وخصمها من قيمة المخزون
    discount_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    tax_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="SET NULL"), nullable=True)
    exchange_rate = Column(Numeric(14, 6), nullable=True)
    foreign_total = Column(Numeric(14, 2), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    supplier = relationship("Supplier")
    warehouse = relationship("Warehouse")

    @property
    def party_name(self):
        return self.supplier.name if self.supplier else None
    items = relationship("PurchaseOrderItem", back_populates="order", cascade="all, delete-orphan")
    currency = relationship("Currency")

    @property
    def currency_code(self):
        return self.currency.code if self.currency else None


class PurchaseOrderItem(TenantOwned, Base):
    __tablename__ = "purchase_order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_cost = Column(Numeric(12, 2), nullable=False)

    order = relationship("PurchaseOrder", back_populates="items")
    product = relationship("Product")
    return_items = relationship("PurchaseReturnItem", back_populates="order_item")

    @property
    def returned_quantity(self):
        return sum(r.quantity for r in self.return_items)

    @property
    def product_name(self):
        return self.product.name if self.product else None


class SalesOrder(TenantOwned, Base):
    """Order sold to a customer. Stock decreases when status becomes 'confirmed'."""

    __tablename__ = "sales_orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="draft", server_default="draft", index=True)
    notes = Column(Text, nullable=True)
    total_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")  # الإجمالي شامل الضريبة (مثل أوامر الشراء)
    subtotal = Column(Numeric(14, 2), nullable=True)  # الصافي قبل الضريبة (NULL للأوامر القديمة قبل نظام الـ VAT)
    tax_rate = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    tax_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    # العملة الأجنبية: كل أعمدة المبالغ تبقى بالجنيه — العملة وسعرها إثبات لحظة الإصدار
    currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="SET NULL"), nullable=True)
    exchange_rate = Column(Numeric(14, 6), nullable=True)
    foreign_total = Column(Numeric(14, 2), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # NULL for orders made before this was recorded
    rep_id = Column(Integer, ForeignKey("sales_reps.id", ondelete="SET NULL"), nullable=True, index=True)
    # معرف يولده تطبيق المندوب لكل أوردر أوفلاين — يضمن عدم التكرار عند إعادة المزامنة
    client_ref = Column(String(64), nullable=True, index=True)
    # خصم على مستوى الأوردر (يُخصم من الإجمالي قبل الضريبة) — توثيقه عمودًا لشفافية ETA والتقارير
    discount_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    # دورة عمولات أُدرج فيها الأوردر — يمنع احتساب العمولة مرتين
    commission_run_id = Column(Integer, nullable=True, index=True)
    safe_id = Column(Integer, ForeignKey("safes.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    customer = relationship("Customer", back_populates="sales_orders")
    warehouse = relationship("Warehouse")
    currency = relationship("Currency")

    @property
    def currency_code(self):
        return self.currency.code if self.currency else None
    creator = relationship("User", foreign_keys=[created_by])
    rep = relationship("SalesRep")
    safe = relationship("Safe")

    @property
    def rep_name(self):
        return self.rep.name if self.rep else None

    @property
    def safe_name(self):
        return self.safe.name if self.safe else None

    @property
    def created_by_name(self):
        return self.creator.username if self.creator else None

    @property
    def party_name(self):
        return self.customer.name if self.customer else None
    items = relationship("SalesOrderItem", back_populates="order", cascade="all, delete-orphan")


class SalesOrderItem(TenantOwned, Base):
    __tablename__ = "sales_order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    # Product cost at the time of sale, so profit reports don't change when the cost price is edited later.
    unit_cost = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    # الكمية المُسلَّمة فعليًا (التسليم الجزئي) — المحاسبة كاملة عند التأكيد والتسليم لوجستي
    delivered_quantity = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")

    order = relationship("SalesOrder", back_populates="items")
    product = relationship("Product")
    return_items = relationship("SalesReturnItem", back_populates="order_item")

    @property
    def returned_quantity(self):
        return sum(r.quantity for r in self.return_items)

    @property
    def product_name(self):
        return self.product.name if self.product else None


class Safe(TenantOwned, Base):
    __tablename__ = "safes"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_safe_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Linked account in the CoA
    chart_account_id = Column(Integer, ForeignKey("chart_accounts.id"), nullable=True, index=True)
    balance = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    branch = relationship("Branch")
    chart_account = relationship("ChartAccount")


class Bank(TenantOwned, Base):
    __tablename__ = "banks"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_bank_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False, index=True)
    account_number = Column(String(60), nullable=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True, index=True)  # NULL = الشركة ككل
    # Linked account in the CoA
    chart_account_id = Column(Integer, ForeignKey("chart_accounts.id"), nullable=True, index=True)
    balance = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    chart_account = relationship("ChartAccount")
    branch = relationship("Branch")

    @property
    def branch_name(self) -> str | None:
        return self.branch.name if self.branch else None


class StockMovement(TenantOwned, Base):
    """Audit trail of every quantity change on a product."""

    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True, index=True)
    change = Column(Numeric(12, 3), nullable=False)  # positive = in, negative = out
    reason = Column(String(30), nullable=False)  # purchase_receipt | sale | adjustment | sales_return | purchase_return
    reference = Column(String(60), nullable=True)  # e.g. "PO-12", "SO-7"
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product = relationship("Product")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(60), nullable=False, unique=True, index=True)
    full_name = Column(String(150), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="staff", server_default="staff")  # admin | manager | staff
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    is_platform_admin = Column(Boolean, nullable=False, default=False, server_default="false")
    # إصدار الجلسة: رفعه (تسجيل خروج شامل/تغيير كلمة السر) يبطل كل التوكنات السابقة فورًا
    token_version = Column(Integer, nullable=False, default=1, server_default="1")
    active_company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    memberships = relationship("UserCompanyMembership", back_populates="user", cascade="all, delete-orphan")
    branch_access = relationship("UserBranchAccess", back_populates="user", cascade="all, delete-orphan")
    warehouse_access = relationship("UserWarehouseAccess", back_populates="user", cascade="all, delete-orphan")


class UserCompanyMembership(Base):
    __tablename__ = "user_company_memberships"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'manager', 'staff')", name="ck_membership_role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="staff", server_default="staff")
    employee_code = Column(String(60), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)
    # قسم الصلاحيات (AccessSection) — كيان صلاحيات مستقل تماماً عن إدارات HR أعلاه.
    section_id = Column(
        Integer, ForeignKey("access_sections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    all_branches = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="memberships")
    company = relationship("Company", back_populates="memberships")


class UserBranchAccess(Base):
    __tablename__ = "user_branch_access"
    __table_args__ = (UniqueConstraint("user_id", "branch_id", name="uq_user_branch_access"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)

    user = relationship("User", back_populates="branch_access")
    branch = relationship("Branch")


class UserSectionAccess(TenantOwned, Base):
    """أقسام الصلاحيات المسندة للمستخدم — عدة أقسام لموظف واحد (اتحاد الصلاحيات)."""

    __tablename__ = "user_section_access"
    __table_args__ = (UniqueConstraint("company_id", "user_id", "section_id", name="uq_user_section_access"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(
        Integer, ForeignKey("access_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")
    section = relationship("AccessSection")


class UserWarehouseAccess(Base):
    __tablename__ = "user_warehouse_access"
    __table_args__ = (UniqueConstraint("user_id", "warehouse_id", name="uq_user_warehouse_access"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)

    user = relationship("User", back_populates="warehouse_access")
    warehouse = relationship("Warehouse")


class Payment(TenantOwned, Base):
    """Money received (receipt) or paid out (payment).

    A voucher has at most one party: a customer (receipt), a supplier (payment), or no party at
    all for general income / general expense vouchers (then category_id is set and a safe or
    bank must hold the money). Payments are never edited or deleted: a mistake is corrected by
    voiding the payment (status 'voided'), which removes it from balances.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("NOT (customer_id IS NOT NULL AND supplier_id IS NOT NULL)", name="ck_payment_party_shape"),
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(10), nullable=False, default="receipt", server_default="receipt", index=True)  # receipt | payment
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    safe_id = Column(Integer, ForeignKey("safes.id"), nullable=True, index=True)
    bank_id = Column(Integer, ForeignKey("banks.id"), nullable=True, index=True)
    category_id = Column(Integer, ForeignKey("payment_categories.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Numeric(14, 2), nullable=False)
    method = Column(String(20), nullable=False, default="cash", server_default="cash")  # cash | bank | wallet | cheque
    reference = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    paid_on = Column(Date, nullable=False, server_default=func.current_date())
    # سند بعملة أجنبية: amount يبقى بالجنيه — العملة والمبلغ الأجنبي وسعر الصرف إثبات
    # عملة السند
    currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="SET NULL"), nullable=True)
    exchange_rate = Column(Numeric(14, 6), nullable=True)
    foreign_amount = Column(Numeric(14, 2), nullable=True)
    # ضريبة الخصم والإضافة: جزء من السند محتجز توريدًا للمصلحة — النقدية الفعلية = amount − withholding_amount
    withholding_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    withholding_code_id = Column(Integer, ForeignKey("withholding_codes.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(10), nullable=False, default="posted", server_default="posted", index=True)  # posted | voided
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    voided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    voided_at = Column(DateTime(timezone=True), nullable=True)

    customer = relationship("Customer")
    supplier = relationship("Supplier")
    safe = relationship("Safe")
    bank = relationship("Bank")
    company = relationship("Company")
    category = relationship("PaymentCategory")
    withholding_code = relationship("WithholdingCode")

    @property
    def category_name(self) -> str | None:
        return self.category.name if self.category else None


class WithholdingCode(TenantOwned, Base):
    """أكواد ضريبة الخصم والإضافة (المادة 62 من قانون 91/2005): نوع التوريد ونسبته.

    تُبذر أنواع افتراضية (سلع 1% · خدمات 3% · مهن حرة 5% ...) وتُعدَّل بحرية لكل شركة.
    """

    __tablename__ = "withholding_codes"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_withholding_code_name"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    rate = Column(Numeric(5, 2), nullable=False)  # نسبة مئوية على قيمة الفاتورة قبل VAT
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaxSetting(TenantOwned, Base):
    """إعدادات ضريبية لكل شركة — kind='payroll' لضريبة كسب العمل (قابلة للتعديل)."""

    __tablename__ = "tax_settings"
    __table_args__ = (UniqueConstraint("company_id", "kind", name="uq_tax_setting_kind"),)

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False, default="payroll", server_default="payroll", index=True)
    personal_exemption = Column(Numeric(14, 2), nullable=False, default=20000, server_default="20000")
    wage_reduction_percent = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    social_insurance_percent = Column(Numeric(5, 2), nullable=False, default=11, server_default="11")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TaxBracket(TenantOwned, Base):
    """شريحة ضريبية تصاعدية — kind='payroll': من min_amount (شامل) إلى max_amount (غير شامل، NULL = ما بعدها)."""

    __tablename__ = "tax_brackets"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False, default="payroll", server_default="payroll", index=True)
    min_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    max_amount = Column(Numeric(14, 2), nullable=True)  # NULL = مفتوحة حتى ما لا نهاية
    rate = Column(Numeric(5, 2), nullable=False)
    sort = Column(Integer, nullable=False, default=0, server_default="0")


class PaymentCategory(TenantOwned, Base):
    """بنود القبض والصرف: selectable labels on receipt / payment vouchers."""

    __tablename__ = "payment_categories"
    __table_args__ = (UniqueConstraint("company_id", "kind", "name", name="uq_payment_category_name"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    kind = Column(String(10), nullable=False, default="receipt", server_default="receipt", index=True)  # receipt | payment
    requires_party = Column(Boolean, nullable=False, default=True, server_default=text("true"))  # force customer/supplier on the voucher
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Bom(TenantOwned, Base):
    """قائمة مواد التصنيع (BOM): مكونات إنتاج `output_qty` وحدة من المنتج النهائي."""

    __tablename__ = "boms"
    __table_args__ = (UniqueConstraint("company_id", "product_id", "version", name="uq_bom_product_version"),)

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)  # المنتج النهائي
    version = Column(String(20), nullable=False, default="v1", server_default="v1")
    output_qty = Column(Integer, nullable=False, default=1, server_default="1")  # الكمية الناتجة من هذه القائمة
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    # سريان الإصدار (اختياري): تُختار القائمة المفعّلة التي يشمل تاريخ الأمر فترتها — NULL = دائمة
    valid_from = Column(Date, nullable=True)
    valid_to = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product = relationship("Product")
    items = relationship("BomItem", back_populates="bom", cascade="all, delete-orphan")
    operations = relationship("BomOperation", back_populates="bom", cascade="all, delete-orphan", order_by="BomOperation.seq")


class WorkCenter(TenantOwned, Base):
    """مركز تشغيل (قسم/ماكينة) — وحدة الموارد التي تُنفذ عليها عمليات التشغيل."""

    __tablename__ = "work_centers"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_work_center_company_name"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    capacity_per_hour = Column(Numeric(12, 3), nullable=True)  # الوحدات القابلة للتنفيذ بالساعة
    hourly_cost = Column(Numeric(14, 2), nullable=True)  # تكلفة ساعة التشغيل (أجور + أعباء)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    notes = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BomOperation(TenantOwned, Base):
    """عملية (مرحلة تشغيل) ضمن مسار تصنيع قائمة المواد — مرتبة بالتسلسل seq."""

    __tablename__ = "bom_operations"
    __table_args__ = (UniqueConstraint("bom_id", "seq", name="uq_bom_operation_seq"),)

    id = Column(Integer, primary_key=True, index=True)
    bom_id = Column(Integer, ForeignKey("boms.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)  # ترتيب المرحلة (1، 2، …)
    name = Column(String(150), nullable=False)  # اسم المرحلة (قص / تجميع / صباغة …)
    work_center_id = Column(Integer, ForeignKey("work_centers.id"), nullable=True, index=True)
    run_minutes_per_unit = Column(Numeric(10, 3), nullable=False, default=0, server_default="0")  # دقائق التشغيل للوحدة
    notes = Column(String(200), nullable=True)

    bom = relationship("Bom", back_populates="operations")
    work_center = relationship("WorkCenter")


class BomItem(TenantOwned, Base):
    """مكوّن في قائمة المواد: كمية لكل وحدة ناتجة + نسبة فاقد، ويُصرف اختياريًا في مرحلة محددة."""

    __tablename__ = "bom_items"
    __table_args__ = (UniqueConstraint("bom_id", "component_id", name="uq_bom_component"),)

    id = Column(Integer, primary_key=True, index=True)
    bom_id = Column(Integer, ForeignKey("boms.id", ondelete="CASCADE"), nullable=False, index=True)
    component_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)  # المكوّن (خامة)
    qty_per_output = Column(Numeric(12, 3), nullable=False)  # كمية المكوّن لكل وحدة ناتجة (تسمح بكسور مثل 0.5 كجم)
    scrap_pct = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")  # نسبة الفاقد %
    operation_seq = Column(Integer, nullable=True)  # مرحلة الصرف (NULL = الصرف المجمّع التقليدي)
    notes = Column(String(200), nullable=True)

    bom = relationship("Bom", back_populates="items")
    component = relationship("Product")


class ProductionOrder(TenantOwned, Base):
    """أمر تصنيع: صرف خامات حسب قائمة المواد وتشغيل دفعات المنتج النهائي.

    Lifecycle: draft -> in_progress (issue: صرف خامات + قيد WIP) -> completed (produce batches / close with variance) | cancelled (draft only).
    """

    __tablename__ = "production_orders"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_production_order_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)  # المنتج النهائي
    bom_id = Column(Integer, ForeignKey("boms.id"), nullable=True, index=True)  # القائمة المستخدمة
    qty_planned = Column(Numeric(12, 3), nullable=False)
    qty_produced = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")
    qty_scrapped = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")
    scrap_cost = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")  # إجمالي تكلفة الهالك المُرحّلة من WIP (أمر + مراحل)
    std_unit_cost = Column(Numeric(14, 4), nullable=True)  # التكلفة القياسية للوحدة وقت الإنشاء (من قائمة المواد)
    parent_order_id = Column(Integer, ForeignKey("production_orders.id"), nullable=True, index=True)  # أمر فرعي من تصنيع مرحلي
    # تصنيع حسب الطلب: أمر البيع الذي دفع هذا الأمر (MRP التنفيذي)
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    production_line_id = Column(Integer, ForeignKey("production_lines.id"), nullable=True)  # خط الإنتاج
    status = Column(String(20), nullable=False, default="draft", server_default="draft", index=True)  # draft | in_progress | completed | cancelled
    raw_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)  # مخزن الخامات
    output_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)  # مخزن المنتج التام
    subcontractor_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)  # مورد التصنيع الخارجي
    scheduled_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    product = relationship("Product")
    bom = relationship("Bom")
    raw_warehouse = relationship("Warehouse", foreign_keys=[raw_warehouse_id])
    output_warehouse = relationship("Warehouse", foreign_keys=[output_warehouse_id])
    subcontractor = relationship("Supplier")
    consumptions = relationship("ProductionConsumption", back_populates="order", cascade="all, delete-orphan")
    costs = relationship("ProductionCost", back_populates="order", cascade="all, delete-orphan")
    batches = relationship("ProductionBatch", back_populates="order", cascade="all, delete-orphan")
    production_line = relationship("ProductionLine")
    item_snapshots = relationship("ProductionOrderItem", back_populates="order", cascade="all, delete-orphan")
    operations = relationship("ProductionOrderOperation", back_populates="order", cascade="all, delete-orphan", order_by="ProductionOrderOperation.seq")

    @property
    def costs_total(self) -> Decimal:
        return sum((Decimal(c.amount or 0) for c in self.costs), Decimal("0"))


class ProductionOrderOperation(TenantOwned, Base):
    """نسخة المرحلة على أمر التشغيل (snapshot من مسار قائمة المواد) — تتبّع الصرف والإنتاج المرحلي."""

    __tablename__ = "production_order_operations"
    __table_args__ = (UniqueConstraint("order_id", "seq", name="uq_poo_order_seq"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    name = Column(String(150), nullable=False)
    work_center_id = Column(Integer, ForeignKey("work_centers.id"), nullable=True, index=True)
    run_minutes_per_unit = Column(Numeric(10, 3), nullable=False, default=0, server_default="0")
    status = Column(String(20), nullable=False, default="pending", server_default="pending")  # pending | in_progress | done
    qty_done = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")
    qty_scrapped = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")
    issued = Column(Boolean, nullable=False, default=False, server_default="false")  # هل صُرفت خامات هذه المرحلة؟
    completed_at = Column(DateTime(timezone=True), nullable=True)

    order = relationship("ProductionOrder", back_populates="operations")
    work_center = relationship("WorkCenter")


class ProductionOrderItem(TenantOwned, Base):
    """نسخة بنود قائمة المواد على أمر التشغيل (snapshot عند الإنشاء) — تعديل القائمة لاحقًا لا يغيّر الأوامر القديمة."""

    __tablename__ = "production_order_items"
    __table_args__ = (UniqueConstraint("order_id", "component_id", name="uq_poi_order_component"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    component_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    qty_per_output = Column(Numeric(12, 3), nullable=False)
    scrap_pct = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    operation_seq = Column(Integer, nullable=True)
    notes = Column(String(200), nullable=True)

    order = relationship("ProductionOrder", back_populates="item_snapshots")
    component = relationship("Product")


class ProductionCost(TenantOwned, Base):
    """أجور تشغيل وأعباء غير مباشرة مضافة على أمر التصنيع (تُحمّل على WIP)."""

    __tablename__ = "production_costs"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    cost_type = Column(String(20), nullable=False, index=True)  # labor | overhead
    amount = Column(Numeric(14, 2), nullable=False)
    description = Column(String(200), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    order = relationship("ProductionOrder", back_populates="costs")


class ProductionBatch(TenantOwned, Base):
    """دفعة إنتاج من أمر تصنيع — لحظة تتبع وفحص الجودة."""

    __tablename__ = "production_batches"
    __table_args__ = (UniqueConstraint("order_id", "batch_no", name="uq_production_batch_no"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_no = Column(String(50), nullable=False)
    qty = Column(Numeric(12, 3), nullable=False)
    cost = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")  # التكلفة المخصصة للدفعة
    qc_status = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)  # pending | passed | rejected
    # محاولة الفحص الحالية (إعادة الفحص تزيدها) — قياسات كل محاولة تُحفظ في batch_qc_results
    qc_attempt = Column(Integer, nullable=False, default=1, server_default="1")
    produced_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    notes = Column(String(200), nullable=True)

    order = relationship("ProductionOrder", back_populates="batches")


class ProductionLine(TenantOwned, Base):
    """خطوط/ورش الإنتاج: سعة و تكلفة تشغيل بالساعة."""

    __tablename__ = "production_lines"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_production_line_company_name"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    capacity_per_hour = Column(Integer, nullable=True)  # الوحدات المنتجة بالساعة
    hourly_cost = Column(Numeric(14, 2), nullable=True)  # تكلفة تشغيل الساعة
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StockLot(TenantOwned, Base):
    """لوطات الخامات لكل (منتج × مخزن): استلامات الشراء أو يدوية — أساس التتبع العكسي."""

    __tablename__ = "stock_lots"
    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "warehouse_id", "lot_code", name="uq_stock_lot_code"),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True, index=True)
    lot_code = Column(String(60), nullable=False)
    source = Column(String(20), nullable=False, default="manual", server_default="manual")  # purchase | opening | manual
    reference = Column(String(80), nullable=True)  # رقم المستند (أمر الشراء مثلاً)
    expiry_date = Column(Date, nullable=True)
    qty_received = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")
    qty_remaining = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product = relationship("Product")
    warehouse = relationship("Warehouse")


class ConsumptionLot(TenantOwned, Base):
    """تخصيص صرف الخامات على اللوطات (FIFO) — يربط أمر التصنيع بالوط الذي استُهلك."""

    __tablename__ = "consumption_lots"
    __table_args__ = (
        UniqueConstraint("order_id", "component_id", "lot_id", name="uq_consumption_lot"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    component_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    lot_id = Column(Integer, ForeignKey("stock_lots.id"), nullable=False, index=True)
    qty = Column(Numeric(12, 3), nullable=False)

    order = relationship("ProductionOrder")
    lot = relationship("StockLot")


# ---------- الجودة: نماذج فحص بمعايير قابلة للقياس ----------

class QcTemplate(TenantOwned, Base):
    """نموذج فحص جودة: قائمة معايير تُقاس على دفعات الإنتاج."""

    __tablename__ = "qc_templates"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_qc_template_name"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    description = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    parameters = relationship("QcParameter", back_populates="template", cascade="all, delete-orphan")


class QcParameter(TenantOwned, Base):
    """معيار قياس: رقمي بنطاق (حد أدنى/أعلى) أو مطابقة منطقية."""

    __tablename__ = "qc_parameters"
    __table_args__ = (UniqueConstraint("template_id", "name", name="uq_qc_parameter_name"),)

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("qc_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    unit = Column(String(30), nullable=True)
    param_type = Column(String(10), nullable=False, default="number", server_default="number")  # number | bool
    min_value = Column(Numeric(12, 3), nullable=True)
    max_value = Column(Numeric(12, 3), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    template = relationship("QcTemplate", back_populates="parameters")


class QcProductRequirement(TenantOwned, Base):
    """ربط نموذج فحص بمنتج: الفحوصات المطلوبة قبل اعتماد دفعاته."""

    __tablename__ = "qc_product_requirements"
    __table_args__ = (UniqueConstraint("company_id", "product_id", "template_id", name="uq_qc_product_template"),)

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("qc_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product = relationship("Product")
    template = relationship("QcTemplate")


class BatchQcResult(TenantOwned, Base):
    """نتائج قياس معايير الجودة لدفعة إنتاج — قيم مسجلة + حكم مطابقة لكل معيار."""

    __tablename__ = "batch_qc_results"
    __table_args__ = (UniqueConstraint("batch_id", "attempt", "parameter_id", name="uq_batch_qc_result_attempt"),)

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    # محاولة الفحص (1 = الأولى) — إعادة الفحص تنشئ محاولة جديدة بقياسات نظيفة
    attempt = Column(Integer, nullable=False, default=1, server_default="1")
    parameter_id = Column(Integer, ForeignKey("qc_parameters.id", ondelete="SET NULL"), nullable=True, index=True)
    template_id = Column(Integer, ForeignKey("qc_templates.id", ondelete="SET NULL"), nullable=True, index=True)
    parameter_name = Column(String(150), nullable=False)  # snapshot — يبقى بعد تعديل/حذف النموذج
    unit = Column(String(30), nullable=True)
    value_num = Column(Numeric(12, 3), nullable=True)
    value_text = Column(String(200), nullable=True)
    pass_fail = Column(Boolean, nullable=True)
    recorded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    batch = relationship("ProductionBatch")
    parameter = relationship("QcParameter")


class ProductionConsumption(TenantOwned, Base):
    """الخامات المستهلكة فعليًا عند بدء التشغيل (snapshot بتكلفة لحظة الصرف)."""

    __tablename__ = "production_consumptions"
    __table_args__ = (UniqueConstraint("order_id", "component_id", name="uq_production_consumption"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    component_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    qty = Column(Numeric(12, 3), nullable=False)
    unit_cost = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")  # تكلفة الوحدة وقت الصرف

    order = relationship("ProductionOrder", back_populates="consumptions")
    component = relationship("Product")

    @property
    def total_cost(self) -> Decimal:
        return (Decimal(self.qty or 0) * Decimal(self.unit_cost or 0)).quantize(Decimal("0.01"))


class Cheque(TenantOwned, Base):
    """حافظة الشيكات: cheques received from customers or issued to suppliers.

    Every cheque is backed by a Payment voucher (method='cheque') so party balances and
    statements stay consistent. Lifecycle:
      received: under_collection -> collected (cash/bank) | returned
      issued:   issued -> cashed (drawn from the bank) | returned
    """

    __tablename__ = "cheques"

    id = Column(Integer, primary_key=True, index=True)
    direction = Column(String(10), nullable=False, index=True)  # received | issued
    number = Column(String(60), nullable=False)
    bank_id = Column(Integer, ForeignKey("banks.id"), nullable=False, index=True)  # البنك المسحوب عليه
    amount = Column(Numeric(14, 2), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)  # received cheques
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)  # issued cheques
    cheque_date = Column(Date, nullable=False, server_default=func.current_date())
    due_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="under_collection", server_default="under_collection", index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True, index=True)  # the voucher that recorded it
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    bank = relationship("Bank")
    customer = relationship("Customer")
    supplier = relationship("Supplier")
    company = relationship("Company")
    payment = relationship("Payment")

    @property
    def party_name(self) -> str | None:
        party = self.customer if self.direction == "received" else self.supplier
        return party.name if party else None


class AuditLog(TenantOwned, Base):
    """Who did what and when. Rows are only ever inserted, in the same transaction as the change they describe."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    username = Column(String(60), nullable=True)  # snapshot, survives user changes
    action = Column(String(30), nullable=False, index=True)
    entity = Column(String(30), nullable=False, index=True)
    entity_id = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)


class SalesReturn(TenantOwned, Base):
    """Goods a customer sends back: stock goes up, the customer's balance goes down by (total - refund)."""

    __tablename__ = "sales_returns"
    __table_args__ = (CheckConstraint("refund_amount >= 0 AND refund_amount <= total_amount", name="ck_sales_return_refund"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    total_amount = Column(Numeric(14, 2), nullable=False)
    refund_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")  # cash given back now
    method = Column(String(20), nullable=False, default="cash", server_default="cash")
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    rep_id = Column(Integer, ForeignKey("sales_reps.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    order = relationship("SalesOrder")
    customer = relationship("Customer")
    rep = relationship("SalesRep")
    items = relationship("SalesReturnItem", back_populates="ret", cascade="all, delete-orphan")

    kind = "sales"

    @property
    def rep_name(self):
        return self.rep.name if self.rep else None

    @property
    def party_id(self):
        return self.customer_id

    @property
    def party_name(self):
        return self.customer.name if self.customer else None
    # دورة العمولات التي احتسبت هذا المرتجع — يمنع الخصم المزدوج من العمولة
    commission_run_id = Column(Integer, nullable=True, index=True)


class SalesReturnItem(TenantOwned, Base):
    __tablename__ = "sales_return_items"

    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(Integer, ForeignKey("sales_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    order_item_id = Column(Integer, ForeignKey("sales_order_items.id"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)

    ret = relationship("SalesReturn", back_populates="items")
    order_item = relationship("SalesOrderItem", back_populates="return_items")
    product = relationship("Product")

    @property
    def product_name(self):
        return self.product.name if self.product else None


class PurchaseReturn(TenantOwned, Base):
    """Goods sent back to a supplier: stock goes down, what we owe the supplier goes down by (total - refund)."""

    __tablename__ = "purchase_returns"
    __table_args__ = (CheckConstraint("refund_amount >= 0 AND refund_amount <= total_amount", name="ck_purchase_return_refund"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    total_amount = Column(Numeric(14, 2), nullable=False)
    refund_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")  # cash received back now
    method = Column(String(20), nullable=False, default="cash", server_default="cash")
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    order = relationship("PurchaseOrder")
    supplier = relationship("Supplier")
    items = relationship("PurchaseReturnItem", back_populates="ret", cascade="all, delete-orphan")

    kind = "purchase"

    @property
    def party_id(self):
        return self.supplier_id

    @property
    def party_name(self):
        return self.supplier.name if self.supplier else None


class PurchaseReturnItem(TenantOwned, Base):
    __tablename__ = "purchase_return_items"

    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(Integer, ForeignKey("purchase_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    order_item_id = Column(Integer, ForeignKey("purchase_order_items.id"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)  # the order line's unit cost

    ret = relationship("PurchaseReturn", back_populates="items")
    order_item = relationship("PurchaseOrderItem", back_populates="return_items")
    product = relationship("Product")

    @property
    def product_name(self):
        return self.product.name if self.product else None


class Shift(TenantOwned, Base):
    """A cashier's drawer session. Expected cash is derived from the cash movements the user recorded while it was open."""

    __tablename__ = "shifts"
    __table_args__ = (
        Index("uq_shift_one_open_per_user", "user_id", unique=True, postgresql_where=text("status = 'open'"), sqlite_where=text("status = 'open'")),
        CheckConstraint("opening_cash >= 0", name="ck_shift_opening_cash"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    username = Column(String(60), nullable=False)
    status = Column(String(10), nullable=False, default="open", server_default="open", index=True)  # open | closed
    opened_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    opening_cash = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    # frozen at close
    cash_in = Column(Numeric(14, 2), nullable=True)
    cash_out = Column(Numeric(14, 2), nullable=True)
    cash_refunds_in = Column(Numeric(14, 2), nullable=True)  # cash received back from suppliers (purchase returns)
    cash_refunds_out = Column(Numeric(14, 2), nullable=True)  # cash handed back to customers (sales returns)
    other_methods_in = Column(Numeric(14, 2), nullable=True)
    expected_cash = Column(Numeric(14, 2), nullable=True)
    counted_cash = Column(Numeric(14, 2), nullable=True)
    difference = Column(Numeric(14, 2), nullable=True)  # counted - expected (negative = shortage)
    notes = Column(Text, nullable=True)


class Stocktake(TenantOwned, Base):
    """A physical count of stock. Lines snapshot the system quantity; applying turns count differences into adjustments."""

    __tablename__ = "stocktakes"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(10), nullable=False, default="open", server_default="open", index=True)  # open | applied | cancelled
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)  # NULL = all products
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(60), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    applied_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    warehouse = relationship("Warehouse")
    lines = relationship("StocktakeLine", back_populates="stocktake", cascade="all, delete-orphan", order_by="StocktakeLine.id")


class StocktakeLine(TenantOwned, Base):
    __tablename__ = "stocktake_lines"
    __table_args__ = (
        UniqueConstraint("stocktake_id", "product_id", name="uq_stocktake_line_product"),
        CheckConstraint("counted_qty IS NULL OR counted_qty >= 0", name="ck_stocktake_counted"),
    )

    id = Column(Integer, primary_key=True, index=True)
    stocktake_id = Column(Integer, ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    system_qty = Column(Numeric(12, 3), nullable=False)  # quantity when the sheet was created
    counted_qty = Column(Numeric(12, 3), nullable=True)  # NULL = not counted (left untouched when applying)

    stocktake = relationship("Stocktake", back_populates="lines")
    product = relationship("Product")

    @property
    def sku(self):
        return self.product.sku if self.product else None

    @property
    def product_name(self):
        return self.product.name if self.product else None

    @property
    def difference(self):
        return None if self.counted_qty is None else self.counted_qty - self.system_qty


class ProductStock(TenantOwned, Base):
    """Quantity of one product in one warehouse. Product.quantity stays the total (kept in sync by app.stock)."""

    __tablename__ = "product_stock"
    __table_args__ = (CheckConstraint("quantity >= 0", name="ck_product_stock_quantity"),)

    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), primary_key=True, index=True)
    quantity = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")
    # حد الطلب الأدنى لهذا المخزن تحديدًا — يتجاوز reorder_level العام للمنتج عند ضبطه
    min_level = Column(Numeric(12, 3), nullable=True)

    warehouse = relationship("Warehouse")


class StockTransfer(TenantOwned, Base):
    """Goods moved between two warehouses. Created as 'pending', executed on approval."""

    __tablename__ = "stock_transfers"
    __table_args__ = (CheckConstraint("from_warehouse_id <> to_warehouse_id", name="ck_transfer_distinct_warehouses"),)

    id = Column(Integer, primary_key=True, index=True)
    from_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    to_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    notes = Column(Text, nullable=True)
    valuation = Column(String(10), nullable=False, server_default="cost")  # cost / sale
    status = Column(String(20), nullable=False, server_default="pending", index=True)  # pending/approved/rejected
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(60), nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    from_warehouse = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse = relationship("Warehouse", foreign_keys=[to_warehouse_id])
    items = relationship("StockTransferItem", back_populates="transfer", cascade="all, delete-orphan", order_by="StockTransferItem.id")

    @property
    def from_warehouse_name(self):
        return self.from_warehouse.name if self.from_warehouse else None

    @property
    def to_warehouse_name(self):
        return self.to_warehouse.name if self.to_warehouse else None


class StockTransferItem(TenantOwned, Base):
    __tablename__ = "stock_transfer_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_transfer_item_quantity"),)

    id = Column(Integer, primary_key=True, index=True)
    transfer_id = Column(Integer, ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Numeric(12, 3), nullable=False)

    transfer = relationship("StockTransfer", back_populates="items")
    product = relationship("Product")

    @property
    def sku(self):
        return self.product.sku if self.product else None

    @property
    def product_name(self):
        return self.product.name if self.product else None


class ChartAccount(TenantOwned, Base):
    """The Chart of Accounts (CoA).
    Hierarchical structure: parent_id allows grouping.
    is_group = True means it's a category/group and cannot have transactions.
    """
    __tablename__ = "chart_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_coa_company_code"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("chart_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    type = Column(String(20), nullable=False)  # asset | liability | equity | revenue | expense
    is_group = Column(Boolean, nullable=False, default=False, server_default="false")
    requires_cost_center = Column(Boolean, nullable=False, default=False, server_default="false")
    balance = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    parent = relationship("ChartAccount", backref="children", remote_side=[id])

class CostCenter(TenantOwned, Base):
    __tablename__ = "cost_centers"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_cc_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class FiscalYear(TenantOwned, Base):
    __tablename__ = "fiscal_years"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_closed = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    periods = relationship("FiscalPeriod", back_populates="fiscal_year", cascade="all, delete-orphan")


class FiscalPeriod(TenantOwned, Base):
    """شهر مالي داخل السنة — إقفال شهري مستقل (المحاسب المصري يقفل شهريًا عادة)."""
    __tablename__ = "fiscal_periods"
    __table_args__ = (UniqueConstraint("company_id", "fiscal_year_id", "start_date", name="uq_fiscal_period_start"),)

    id = Column(Integer, primary_key=True, index=True)
    fiscal_year_id = Column(Integer, ForeignKey("fiscal_years.id"), nullable=False, index=True)
    name = Column(String(30), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_closed = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    fiscal_year = relationship("FiscalYear", back_populates="periods")


class EtaIncomingDocument(TenantOwned, Base):
    """فاتورة مشتريات واردة من المنظومة (مورد أرسلها إلكترونيًا) — تُسحب وتُحوَّل لمسودة أمر شراء."""
    __tablename__ = "eta_incoming_documents"
    __table_args__ = (Index("ix_eta_incoming_status", "company_id", "status"),)

    id = Column(Integer, primary_key=True, index=True)
    eta_uuid = Column(String(80), nullable=False, index=True)
    issuer_tin = Column(String(50), nullable=True)
    issuer_name = Column(String(150), nullable=False)
    internal_id = Column(String(60), nullable=True)
    total_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    status = Column(String(20), nullable=False, default="new", server_default="new")  # new | imported | ignored
    payload = Column(JSON, nullable=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True)
    imported_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EtaSubmission(TenantOwned, Base):
    """إرسال فاتورة للمنظومة: يتبع دورة الحياة submitted → valid/invalid (+cancel لاحقًا)."""
    __tablename__ = "eta_submissions"
    __table_args__ = (Index("ix_eta_company_order", "company_id", "order_id"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=True, index=True)
    return_id = Column(Integer, ForeignKey("sales_returns.id", ondelete="CASCADE"), nullable=True, index=True)
    document_type = Column(String(2), nullable=False, default="I")  # I فاتورة / C إشعار دائن
    device_id = Column(Integer, ForeignKey("eta_devices.id", ondelete="SET NULL"), nullable=True, index=True)  # جهاز توقيع الإيصال
    internal_id = Column(String(60), nullable=False)
    submission_uuid = Column(String(80), nullable=True)
    eta_uuid = Column(String(80), nullable=True)
    eta_long_id = Column(String(120), nullable=True)
    status = Column(String(20), nullable=False, default="draft", server_default="draft", index=True)
    # draft → submitted → valid | invalid | cancelled
    signature = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    response = Column(JSON, nullable=True)
    errors = Column(JSON, nullable=True)
    submitted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    status_checked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EtaDevice(TenantOwned, Base):
    """جهاز SDK مسجل لإيصالات المنظومة: زوج مفاتيح الجهاز يوقّع الإيصالات (R) عند الإنتاج.

    التسجيل الحقيقي: توليد CSR للجهاز ثم رفعه في بوابة المنظومة — بعد إشعار
    المنظومة يتتفعل الجهاز من هنا. في mock يتتفعل فورًا للتجربة."""
    __tablename__ = "eta_devices"
    __table_args__ = (UniqueConstraint("company_id", "serial", name="uq_eta_device_serial"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    serial = Column(String(80), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)  # pending | active | revoked
    private_key = Column(Text, nullable=True)   # PEM (للجهاز) — لا يُرجع نصًا كاملًا أبدًا
    public_key = Column(Text, nullable=True)
    csr = Column(Text, nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    registered_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EtaArchive(TenantOwned, Base):
    """أرشفة إلكترونية للمستندات (e-Archiving): سجل لكل مستند أُرشف بصيغة XML.

    المصادر: إرسال صادر (فاتورة I / إشعار C / إيصال R) أو فاتورة مشتريات واردة —
    الـ payload يحفظ المستند الكامل والـ xml بصيغة تقرير الأرشفة للمنظومة.
    في mock تُؤرشف فورًا؛ في sandbox/prod تبقى pending لحين تسجيل خدمة الأرشفة."""
    __tablename__ = "eta_archives"
    __table_args__ = (
        UniqueConstraint("company_id", "eta_uuid", name="uq_eta_archive_uuid"),
        Index("ix_eta_archive_status", "company_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(10), nullable=False)  # submission | incoming
    submission_id = Column(Integer, ForeignKey("eta_submissions.id", ondelete="SET NULL"), nullable=True, index=True)
    incoming_id = Column(Integer, ForeignKey("eta_incoming_documents.id", ondelete="SET NULL"), nullable=True, index=True)
    document_type = Column(String(2), nullable=False)  # I | C | R
    internal_id = Column(String(60), nullable=False)
    eta_uuid = Column(String(80), nullable=False)
    total_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    payload = Column(JSON, nullable=True)
    xml = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="archived", server_default="archived", index=True)  # archived | pending | failed
    note = Column(Text, nullable=True)
    archived_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    archived_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class RecurringJournal(TenantOwned, Base):
    """قالب قيد متكرر (إيجار/رواتب): يُرحّل عند استحقاقه عبر POST /run."""
    __tablename__ = "recurring_journals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=False)
    reference = Column(String(100), nullable=True)
    frequency = Column(String(20), nullable=False, default="monthly", server_default="monthly")
    day_of_month = Column(Integer, nullable=False, default=1, server_default="1")
    next_run_date = Column(Date, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    items = Column(JSON, nullable=False, default=list)  # [{account_id, debit, credit, cost_center_id, notes}]
    last_run_entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Attachment(TenantOwned, Base):
    """مرفق (صورة فاتورة/شيك) على كيان محاسبي: payment / journal_entry / fixed_asset."""
    __tablename__ = "attachments"
    __table_args__ = (Index("ix_attachments_entity", "company_id", "entity_type", "entity_id"),)

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(30), nullable=False)
    entity_id = Column(Integer, nullable=False)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False, default="application/octet-stream")
    size = Column(Integer, nullable=False, default=0)
    data = Column(LargeBinary, nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BankStatementLine(TenantOwned, Base):
    """سطر من كشف حساب بنك مستورد — يُطابق يدويًا/آليًا مع سندات القبض والصرف."""
    __tablename__ = "bank_statement_lines"
    __table_args__ = (Index("ix_bank_stmt_bank_date", "company_id", "bank_id", "value_date"),)

    id = Column(Integer, primary_key=True, index=True)
    bank_id = Column(Integer, ForeignKey("banks.id", ondelete="CASCADE"), nullable=False, index=True)
    value_date = Column(Date, nullable=False)
    description = Column(String(500), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)  # موجب = داخل للبنك، سالب = خارج
    reference = Column(String(200), nullable=True)
    matched_payment_id = Column(Integer, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)
    # سطر مُرحَّل كقيد تسوية (فروق) — يمنع الترحيل المزدوج ويوثق أثره
    posted_in_entry_id = Column(Integer, nullable=True, index=True)
    imported_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    imported_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    payment = relationship("Payment", foreign_keys=[matched_payment_id])


class FixedAsset(TenantOwned, Base):
    __tablename__ = "fixed_assets"

    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_fa_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False, index=True)
    asset_type = Column(String(100), nullable=False)
    purchase_date = Column(Date, nullable=False)
    cost = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    accumulated_depreciation = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    current_book_value = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    depreciation_method = Column(String(50), nullable=False)
    useful_life_years = Column(Integer, nullable=False)
    salvage_value = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class JournalEntry(TenantOwned, Base):
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, server_default=func.current_date())
    description = Column(Text, nullable=False)
    reference = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="posted", server_default="posted", index=True)  # posted | pending_approval | rejected
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items = relationship("JournalItem", back_populates="entry", cascade="all, delete-orphan")

class JournalItem(TenantOwned, Base):
    __tablename__ = "journal_items"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("chart_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.id"), nullable=True, index=True)
    debit = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    credit = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    notes = Column(Text, nullable=True)

    entry = relationship("JournalEntry", back_populates="items")
    account = relationship("ChartAccount")
    cost_center = relationship("CostCenter")


# =====================================================================
# الموارد البشرية (HR) — ملف الموظف المؤسسي: وظائف، درجات، موظفون،
# عقود، مستندات، وسجل تحركات وظيفية.
# =====================================================================

class RepCommissionRun(TenantOwned, Base):
    """دورة صرف عمولات المندوبين: تُحسب صافي مبيعات الفترة (بعد المرتجعات)
    وتقفل الأوردرات المدرجة — فلا تحتسب عمولتها مرتين في دورة لاحقة."""

    __tablename__ = "rep_commission_runs"

    id = Column(Integer, primary_key=True, index=True)
    period_from = Column(Date, nullable=False)
    period_to = Column(Date, nullable=False)
    total = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    status = Column(String(20), nullable=False, default="posted", server_default="posted")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    lines = relationship("RepCommissionRunLine", back_populates="run", cascade="all, delete-orphan")


class RepCommissionRunLine(TenantOwned, Base):
    __tablename__ = "rep_commission_run_lines"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("rep_commission_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    rep_id = Column(Integer, ForeignKey("sales_reps.id", ondelete="RESTRICT"), nullable=False, index=True)
    orders_count = Column(Integer, nullable=False, default=0, server_default="0")
    gross = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    returns_total = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    net = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    percent = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    commission = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")

    run = relationship("RepCommissionRun", back_populates="lines")
    rep = relationship("SalesRep")


class HrJobTitle(TenantOwned, Base):
    """مسمى وظيفي على مستوى الشركة (مهندس، محاسب، ...) مع حد أدنى/أقصى اختياري للراتب."""

    __tablename__ = "hr_job_titles"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_hr_job_title_company_name"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    description = Column(Text, nullable=True)
    min_salary = Column(Numeric(14, 2), nullable=True)
    max_salary = Column(Numeric(14, 2), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class HrGrade(TenantOwned, Base):
    """درجة وظيفية / شريحة مؤسسية (Grade) مع شريحة سقف وفّة الراتب."""

    __tablename__ = "hr_grades"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_hr_grade_company_name"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    min_salary = Column(Numeric(14, 2), nullable=True)
    max_salary = Column(Numeric(14, 2), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HrEmployee(TenantOwned, Base):
    """ملف الموظف — منفصل عن حساب الدخول (User) لكن يمكن ربطه به اختياريًا عبر user_id.

    status: active (على رأس العمل) | probation (تحت التجربة) | suspended (موقوف) | terminated (منتهي الخدمة).
    """

    __tablename__ = "hr_employees"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_hr_employee_company_code"),
        UniqueConstraint("company_id", "national_id", name="uq_hr_employee_company_national_id"),
        Index("ix_hr_employees_company_status", "company_id", "status"),
        CheckConstraint("basic_salary IS NULL OR basic_salary >= 0", name="ck_hr_employee_salary_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), nullable=False, index=True)
    full_name = Column(String(200), nullable=False, index=True)
    national_id = Column(String(40), nullable=True)
    insurance_number = Column(String(40), nullable=True)  # رقم التأمين الاجتماعي (نموذج 6ح)
    gender = Column(String(10), nullable=True)  # male | female
    birth_date = Column(Date, nullable=True)
    nationality = Column(String(80), nullable=True)
    phone = Column(String(40), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(Text, nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)
    job_title_id = Column(Integer, ForeignKey("hr_job_titles.id", ondelete="SET NULL"), nullable=True, index=True)
    grade_id = Column(Integer, ForeignKey("hr_grades.id", ondelete="SET NULL"), nullable=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    manager_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    hire_date = Column(Date, nullable=False, server_default=func.current_date())
    basic_salary = Column(Numeric(14, 2), nullable=True)
    bank_account = Column(String(60), nullable=True)
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    terminated_at = Column(Date, nullable=True)
    termination_reason = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    department = relationship("Department")
    job_title = relationship("HrJobTitle")
    grade = relationship("HrGrade")
    branch = relationship("Branch")
    user = relationship("User")
    manager = relationship("HrEmployee", remote_side=[id])

    @property
    def department_name(self) -> str | None:
        return self.department.name if self.department else None

    @property
    def job_title_name(self) -> str | None:
        return self.job_title.name if self.job_title else None

    @property
    def branch_name(self) -> str | None:
        return self.branch.name if self.branch else None

    @property
    def manager_name(self) -> str | None:
        return self.manager.full_name if self.manager else None


class HrContract(TenantOwned, Base):
    """عقد عمل: unlimited (غير محدد المدة) | fixed (محدد المدة) | temp (مؤقت) | part_time (جزئي).

    status: active | expired | terminated — لا يُعدّل عقد مُنهي؛ تُنشئ عقدًا جديدًا بدلًا منه.
    """

    __tablename__ = "hr_contracts"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_hr_contract_company_code"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_hr_contract_dates"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(50), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="unlimited", server_default="unlimited", index=True)
    start_date = Column(Date, nullable=False, server_default=func.current_date())
    end_date = Column(Date, nullable=True)
    basic_salary = Column(Numeric(14, 2), nullable=True)
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)  # active | expired | terminated
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    employee = relationship("HrEmployee", back_populates="contracts")


class HrDocument(TenantOwned, Base):
    """مستند مرتبط بالموظف (عقد/شهادة/هوية/تأشيرة ...) مع تاريخ انتهاء اختياري لتنبيهات التجديد.

    المحتوى مخزّن كـ bytea مثل صور المنتجات: يُخدَّم عبر /hr/documents/{id}/file.
    """

    __tablename__ = "hr_documents"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_type = Column(String(30), nullable=False, default="other", server_default="other", index=True)  # contract | certificate | id | visa | other
    title = Column(String(200), nullable=False)
    issue_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True, index=True)
    file_name = Column(String(255), nullable=True)
    file_blob = Column(LargeBinary, nullable=True)
    file_mime = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee = relationship("HrEmployee", back_populates="documents")


class HrEmployeeMove(TenantOwned, Base):
    """سجل تحرك وظيفي (تاريخية كاملة): hire | promotion | transfer | salary_change | status_change | termination.

    عند إنشاء move من نوع يغيّر ملف الموظف (تغيير قسم/مسماى/راتب/حالة) يُطلق المُسجل
    التغيير على ملف الموظف ضمن نفس العملية (Effective Dating through movements).
    """

    __tablename__ = "hr_employee_moves"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    move_type = Column(String(20), nullable=False, index=True)
    effective_date = Column(Date, nullable=False, server_default=func.current_date())
    from_department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    to_department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    from_job_title_id = Column(Integer, ForeignKey("hr_job_titles.id", ondelete="SET NULL"), nullable=True)
    to_job_title_id = Column(Integer, ForeignKey("hr_job_titles.id", ondelete="SET NULL"), nullable=True)
    from_salary = Column(Numeric(14, 2), nullable=True)
    to_salary = Column(Numeric(14, 2), nullable=True)
    reason = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee = relationship("HrEmployee", back_populates="moves")
    to_department = relationship("Department", foreign_keys=[to_department_id])
    to_job_title = relationship("HrJobTitle", foreign_keys=[to_job_title_id])

    @property
    def to_department_name(self) -> str | None:
        return self.to_department.name if self.to_department else None

    @property
    def to_job_title_name(self) -> str | None:
        return self.to_job_title.name if self.to_job_title else None


HrEmployee.contracts = relationship("HrContract", back_populates="employee", cascade="all, delete-orphan", order_by="HrContract.start_date.desc()")
HrEmployee.documents = relationship("HrDocument", back_populates="employee", cascade="all, delete-orphan", order_by="HrDocument.id.desc()")
HrEmployee.moves = relationship("HrEmployeeMove", back_populates="employee", cascade="all, delete-orphan", order_by="HrEmployeeMove.effective_date.desc(), HrEmployeeMove.id.desc()")


# =====================================================================
# HR — الوقت والإجازات (S2): ورديات، حضور، عطلات رسمية، أنواع إجازات،
# أرصدة الإجازات وطلباتها بموافقات.
# =====================================================================

class HrShift(TenantOwned, Base):
    """وردية عمل يومية مع دقائق سماح (grace) ودعم عبور منتصف الليل (22:00→06:00).

    الأوقات بنمط HH:MM (24 ساعة) — نصوص بسيطة لأنها تُقارن نصيًا داخل اليوم
    الواحد فقط، وعبور منتصف الليل يُعامل عبر cross_midnight.
    """

    __tablename__ = "hr_shifts"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_hr_shift_company_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    start_time = Column(String(5), nullable=False)
    end_time = Column(String(5), nullable=False)
    grace_minutes = Column(Integer, nullable=False, default=15, server_default="15")
    cross_midnight = Column(Boolean, nullable=False, default=False, server_default="false")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HrShiftAssignment(TenantOwned, Base):
    """إسناد وردية لموظف (وردية واحدة فعّالة لكل موظف — الإضافة تستبدل السابقة)."""

    __tablename__ = "hr_shift_assignments"
    __table_args__ = (
        UniqueConstraint("company_id", "employee_id", name="uq_hr_shift_assignment_employee"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    shift_id = Column(Integer, ForeignKey("hr_shifts.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee = relationship("HrEmployee")
    shift = relationship("HrShift")

    @property
    def employee_name(self) -> str | None:
        return self.employee.full_name if self.employee else None

    @property
    def shift_name(self) -> str | None:
        return self.shift.name if self.shift else None


class HrAttendance(TenantOwned, Base):
    """حضور وانصراف لليوم الواحد: record واحد لكل موظف/يوم (فريد لكل شركة).

    status: present (حاضر) | late (متأخر) | absent (غياب) | excused (غياب بعذر) .
    source: manual (يدوي) | device (بصمة) | api.
    """

    __tablename__ = "hr_attendance"
    __table_args__ = (
        UniqueConstraint("company_id", "employee_id", "work_date", name="uq_hr_attendance_day"),
        Index("ix_hr_attendance_company_date", "company_id", "work_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    work_date = Column(Date, nullable=False, server_default=func.current_date(), index=True)
    status = Column(String(10), nullable=False, default="present", server_default="present", index=True)
    check_in = Column(String(5), nullable=True)
    check_out = Column(String(5), nullable=True)
    late_minutes = Column(Integer, nullable=False, default=0, server_default="0")
    overtime_minutes = Column(Integer, nullable=False, default=0, server_default="0")
    overtime_type = Column(String(10), nullable=False, default="day", server_default="day")  # day (نهاري 1.35x) | night (ليلي 1.70x) | holiday (عطلة 2.0x)
    overtime_approved = Column(Boolean, nullable=False, default=True, server_default="true")
    source = Column(String(10), nullable=False, default="manual", server_default="manual", index=True)  # manual | device | api
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    employee = relationship("HrEmployee")

    @property
    def employee_name(self) -> str | None:
        return self.employee.full_name if self.employee else None

    @property
    def employee_code(self) -> str | None:
        return self.employee.code if self.employee else None


class BiometricDevice(TenantOwned, Base):
    """جهاز بصمة مسجل (ZKTeco / ADMS / Standalone): عنوان IP، المنفذ، وحالة الاتصال."""

    __tablename__ = "biometric_devices"
    __table_args__ = (
        UniqueConstraint("company_id", "ip_address", "port", name="uq_biometric_device_ip_port"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # اسم الجهاز (بصمة الباب الرئيسي، بصمة المصنع)
    device_model = Column(String(50), nullable=True, default="ZKTeco")
    ip_address = Column(String(45), nullable=False)
    port = Column(Integer, nullable=False, default=4370, server_default="4370")
    serial_number = Column(String(100), nullable=True)
    comm_key = Column(String(50), nullable=True, default="0", server_default="0")
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(20), nullable=False, default="unknown", server_default="unknown")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    branch = relationship("Branch")


class BiometricLog(TenantOwned, Base):
    """سجل البصمات الخام المستلم من الجهاز قبل تحويله لحضور وانصراف مجمع."""

    __tablename__ = "biometric_logs"
    __table_args__ = (
        Index("ix_biometric_logs_emp_time", "company_id", "employee_code", "timestamp"),
    )

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("biometric_devices.id", ondelete="SET NULL"), nullable=True)
    employee_code = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    punch_type = Column(String(10), nullable=False, default="auto", server_default="auto")  # check_in | check_out | auto
    processed = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    device = relationship("BiometricDevice")


class HrHoliday(TenantOwned, Base):
    """عطلة رسمية (لكل الشركة/دولتها) — تُستخدم لاحقًا في رصيد الإجازات والتقارير."""

    __tablename__ = "hr_holidays"
    __table_args__ = (
        UniqueConstraint("company_id", "holiday_date", name="uq_hr_holiday_company_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    holiday_date = Column(Date, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HrLeaveType(TenantOwned, Base):
    """نوع إجازة قابل للتهيئة: رصيد سنوي، مدفوعة/غير مدفوعة، أيام ترحيل."""

    __tablename__ = "hr_leave_types"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_hr_leave_type_company_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    days_per_year = Column(Numeric(5, 1), nullable=False, default=0, server_default="0")
    is_paid = Column(Boolean, nullable=False, default=True, server_default="true")
    carry_over_days = Column(Numeric(5, 1), nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HrLeaveBalance(TenantOwned, Base):
    """رصيد إجازة موظف/نوع/سنة: entitled (المستحق) + carried (المُرحَّل) − used (المستخدم)."""

    __tablename__ = "hr_leave_balances"
    __table_args__ = (
        UniqueConstraint("company_id", "employee_id", "leave_type_id", "year", name="uq_hr_leave_balance"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    leave_type_id = Column(Integer, ForeignKey("hr_leave_types.id", ondelete="CASCADE"), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    entitled_days = Column(Numeric(5, 1), nullable=False, default=0, server_default="0")
    carried_days = Column(Numeric(5, 1), nullable=False, default=0, server_default="0")
    used_days = Column(Numeric(5, 1), nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    employee = relationship("HrEmployee")
    leave_type = relationship("HrLeaveType")

    @property
    def remaining_days(self) -> Decimal:
        return (Decimal(self.entitled_days or 0) + Decimal(self.carried_days or 0) - Decimal(self.used_days or 0)).quantize(Decimal("0.1"))


class HrLeaveRequest(TenantOwned, Base):
    """طلب إجازة: pending → approved (يخصم الرصيد) | rejected | cancelled.

    الأيام تحسب شاملة (from–to). الموافقة تتحقق من الرصيد وتعارض الطلبات الأخرى
    المعتمدة/المعلقة لنفس الموظف قبل الالتزام.
    """

    __tablename__ = "hr_leave_requests"
    __table_args__ = (
        CheckConstraint("to_date >= from_date", name="ck_hr_leave_request_dates"),
        CheckConstraint("days > 0", name="ck_hr_leave_request_days_positive"),
        Index("ix_hr_leave_requests_company_status", "company_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    leave_type_id = Column(Integer, ForeignKey("hr_leave_types.id", ondelete="RESTRICT"), nullable=False, index=True)
    from_date = Column(Date, nullable=False, index=True)
    to_date = Column(Date, nullable=False, index=True)
    days = Column(Numeric(5, 1), nullable=False)
    status = Column(String(10), nullable=False, default="pending", server_default="pending", index=True)  # pending | approved | rejected | cancelled
    approval_level = Column(Integer, nullable=False, default=0, server_default="0")  # المستوى المتحقق من مسار الموافقات
    reason = Column(Text, nullable=True)
    decision_note = Column(Text, nullable=True)
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee = relationship("HrEmployee")
    leave_type = relationship("HrLeaveType")

    @property
    def employee_name(self) -> str | None:
        return self.employee.full_name if self.employee else None

    @property
    def employee_code(self) -> str | None:
        return self.employee.code if self.employee else None

    @property
    def leave_type_name(self) -> str | None:
        return self.leave_type.name if self.leave_type else None


# =====================================================================
# HR — الرواتب (S3): مكونات راتب لكل موظف، مسيرات شهرية بمسودّة/ترحيل
# قسائم (بايسليبات) وتوليد آلي من الحضور والإجازات غير المدفوعة، مع قيد
# محاسبي عند الترحيل.
# =====================================================================

class HrSalaryComponent(TenantOwned, Base):
    """مكوّن راتب شهري لموظف: بدل/علاوة (earning) أو خصم (deduction).

    amount_mode: fixed (قيمة مطلقة) | percent_of_base (نسبة من الراتب الأساسي ×100).
    """

    __tablename__ = "hr_salary_components"
    __table_args__ = (
        UniqueConstraint("company_id", "employee_id", "name", name="uq_hr_salary_component_employee_name"),
        CheckConstraint("percent_value IS NULL OR (percent_value >= 0 AND percent_value <= 100)", name="ck_hr_salary_component_percent"),
        CheckConstraint("fixed_amount IS NULL OR fixed_amount >= 0", name="ck_hr_salary_component_amount"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(12), nullable=False, index=True)  # earning | deduction
    name = Column(String(100), nullable=False)
    amount_mode = Column(String(16), nullable=False, default="fixed", server_default="fixed")  # fixed | percent_of_base
    fixed_amount = Column(Numeric(14, 2), nullable=True)
    percent_value = Column(Numeric(5, 2), nullable=True)  # نسبة مئوية 0-100 من الراتب الأساسي
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee = relationship("HrEmployee")

    @property
    def employee_name(self) -> str | None:
        return self.employee.full_name if self.employee else None


class HrPayrollRun(TenantOwned, Base):
    """مسير رواتب لشهر واحد: draft (قابل للتعديل/إعادة الحساب) → posted (قيد محاسبي).

    فريد لكل (شركة، سنة، شهر) — لا يمكن تكرار شهر. الترحيل ينشئ قيداً متوازناً:
    مدين مصروف الرواتب (5210) / دائن رواتب مستحقة (2140) + خصومات موظفين محتجزة (2120).
    """

    __tablename__ = "hr_payroll_runs"
    __table_args__ = (
        UniqueConstraint("company_id", "year", "month", name="uq_hr_payroll_run_period"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_hr_payroll_run_month"),
        Index("ix_hr_payroll_runs_company_status", "company_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False, index=True)
    month = Column(Integer, nullable=False, index=True)
    status = Column(String(8), nullable=False, default="draft", server_default="draft", index=True)  # draft | posted
    note = Column(Text, nullable=True)
    employees_count = Column(Integer, nullable=False, default=0, server_default="0")
    total_gross = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    total_deductions = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    total_net = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    journal_entry_id = Column(Integer, nullable=True, index=True)  # قيد المحاسبة عند الترحيل
    posted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    @property
    def period_label(self) -> str:
        return f"{self.year}-{int(self.month):02d}"


class HrPayslip(TenantOwned, Base):
    """قسيمة راتب موظف داخل مسير: الأساسي + الربح − الخصومات − غياب/إجازات غير مدفوعة."""

    __tablename__ = "hr_payslips"
    __table_args__ = (
        UniqueConstraint("run_id", "employee_id", name="uq_hr_payslip_run_employee"),
    )

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("hr_payroll_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False, index=True)
    base_salary = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    absent_days = Column(Integer, nullable=False, default=0, server_default="0")
    unpaid_leave_days = Column(Numeric(5, 1), nullable=False, default=0, server_default="0")
    absence_deduction = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    total_earnings = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    total_deductions = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    net_pay = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee = relationship("HrEmployee")
    # lines عبر HrPayslipLine (بدون relationship ثنائية لدورية التنفيذ)

    @property
    def employee_name(self) -> str | None:
        return self.employee.full_name if self.employee else None

    @property
    def employee_code(self) -> str | None:
        return self.employee.code if self.employee else None


class HrPayslipLine(TenantOwned, Base):
    """سطر تفصيلي داخل قسيمة راتب (مكوّن مجمد وقت التوليد للمراجعة والتدقيق)."""

    __tablename__ = "hr_payslip_lines"
    __table_args__ = (
        Index("ix_hr_payslip_lines_payslip", "payslip_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    payslip_id = Column(Integer, ForeignKey("hr_payslips.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(12), nullable=False)  # earning | deduction | absence
    name = Column(String(150), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    notes = Column(Text, nullable=True)
    advance_id = Column(Integer, ForeignKey("hr_advances.id", ondelete="SET NULL"), nullable=True)  # أثر قسط سلفة

    # payslip عبر HrPayslip.id (استعلام يدوي — بدون relationship لدورية التنفيذ)


# =====================================================================
# HR — السلف والتسوية النهائية (S4)
# =====================================================================

# ---------- مسارات الموافقات متعددة المستويات ----------

class HrApprovalChain(TenantOwned, Base):
    """مسار موافقات مرتب لكيان (إجازة حاليًا): كل مستوى موافق محدد أو دور."""

    __tablename__ = "hr_approval_chains"
    __table_args__ = (UniqueConstraint("company_id", "entity_type", "level", name="uq_hr_approval_chain_level"),)

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(10), nullable=False, index=True)  # leave
    level = Column(Integer, nullable=False)
    approver_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    approver_role = Column(String(10), nullable=True)  # manager | admin
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    approver = relationship("User")


class HrApprovalStep(TenantOwned, Base):
    """سجل قرار على مستوى من مسار الموافقات — التاريخ يبقى حتى بعد تغيير المسار."""

    __tablename__ = "hr_approval_steps"
    __table_args__ = (Index("ix_hr_approval_steps_entity", "company_id", "entity_type", "entity_id"),)

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(10), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    level = Column(Integer, nullable=False)
    approver_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decision = Column(String(10), nullable=False)  # approved | rejected
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HrAdvanceApprovalLimit(TenantOwned, Base):
    """حد الموافقة على السلف لكل مستخدم: ما يتجاوز الحد يُرفض تلقائيًا عند الإنشاء (لغير الإدارة)."""

    __tablename__ = "hr_advance_approval_limits"
    __table_args__ = (UniqueConstraint("company_id", "user_id", name="uq_hr_advance_limit_user"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    max_amount = Column(Numeric(14, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")


class HrAdvance(TenantOwned, Base):
    """سلفة/قرض موظف تُسدَّد على أقساط شهرية متساوية تبدأ من شهر البدء.

    القسط يُحسب آلياً في قسيمة الراتب داخل نطاق الأقساط (بداية + installments_count
    − 1 شهر)، ولا يتجاوز المتبقي منها. الأقساط المخصومة فعلًا تُتتبَّع عبر
    سطور القسائم (advance_id).
    """

    __tablename__ = "hr_advances"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_hr_advance_amount_positive"),
        CheckConstraint("installments_count >= 1 AND installments_count <= 240", name="ck_hr_advance_installments"),
        CheckConstraint("start_month >= 1 AND start_month <= 12", name="ck_hr_advance_start_month"),
        Index("ix_hr_advances_company_status", "company_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=False)
    installments_count = Column(Integer, nullable=False)
    start_year = Column(Integer, nullable=False, index=True)
    start_month = Column(Integer, nullable=False)
    status = Column(String(10), nullable=False, default="active", server_default="active", index=True)  # active | completed | cancelled
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee = relationship("HrEmployee")

    @property
    def employee_name(self) -> str | None:
        return self.employee.full_name if self.employee else None

    @property
    def advance_code(self) -> str:
        return f"ADV-{self.id}"


class HrSettlement(TenantOwned, Base):
    """تسوية نهائية عند إنهاء الخدمة (سجل واحد لكل موظف).

    تحتوي: مكافأة نهاية الخدمة (EOSB) وفق قاعدة 21 يوم/سنة لأول 5 سنوات ثم 30
    يوم/سنة (تناسب جزئي بالأيام)، تعويض رصيد الإجازات المدفوعة غير المستخدمة،
    وخصم متبقٍّ من السلف — والإجمالي المستحق للموظف.
    """

    __tablename__ = "hr_settlements"
    __table_args__ = (
        UniqueConstraint("company_id", "employee_id", name="uq_hr_settlement_employee"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False, index=True)
    termination_date = Column(Date, nullable=False)
    service_days = Column(Integer, nullable=False)
    service_years = Column(Numeric(8, 2), nullable=False)
    eosb_days = Column(Numeric(8, 1), nullable=False)
    eosb_amount = Column(Numeric(14, 2), nullable=False)
    unused_leave_days = Column(Numeric(5, 1), nullable=False, default=0, server_default="0")
    unused_leave_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    advances_remaining = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    total_due = Column(Numeric(14, 2), nullable=False)
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee = relationship("HrEmployee")

    @property
    def employee_name(self) -> str | None:
        return self.employee.full_name if self.employee else None

    @property
    def employee_code(self) -> str | None:
        return self.employee.code if self.employee else None
    status = Column(String(20), nullable=False, default="draft", server_default="draft")  # draft | posted
    journal_entry_id = Column(Integer, nullable=True)


class HrAttendanceCorrection(TenantOwned, Base):
    """طلب تصحيح حضور من الموظف نفسه (ESS): pending → approved (تُطبَّق على السجل) | rejected.

    الموافقة تُحدّث/تُنشئ سجل الحضور بأوقات الدخول/الخروج المطلوبة مع إعادة حساب
    التأخير والإضافي من وردية الموظف، مع سجل تدقيق في الجانبين.
    """

    __tablename__ = "hr_attendance_corrections"
    __table_args__ = (
        UniqueConstraint("company_id", "employee_id", "work_date", name="uq_hr_attendance_correction_day"),
        Index("ix_hr_att_corr_company_status", "company_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    work_date = Column(Date, nullable=False, index=True)
    requested_check_in = Column(String(5), nullable=True)
    requested_check_out = Column(String(5), nullable=True)
    reason = Column(Text, nullable=False)
    status = Column(String(10), nullable=False, default="pending", server_default="pending", index=True)  # pending | approved | rejected
    decision_note = Column(Text, nullable=True)
    applied_attendance_id = Column(Integer, nullable=True)  # السجل المُعدّل/المُنشأ عند الموافقة
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee = relationship("HrEmployee")

    @property
    def employee_name(self) -> str | None:
        return self.employee.full_name if self.employee else None

    @property
    def employee_code(self) -> str | None:
        return self.employee.code if self.employee else None


# =====================================================================
# S6 — التوظيف (ATS) والأداء والتدريب
# =====================================================================

JOB_POSTING_STATUSES = ("open", "on_hold", "closed", "filled")
APPLICANT_STAGES = ("applied", "screening", "interview", "offer", "hired", "rejected")


class HrJobPosting(TenantOwned, Base):
    """إعلان توظيف لوظيفة شاغرة (ATS): open → on_hold | closed | filled."""

    __tablename__ = "hr_job_postings"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_hr_job_posting_code"),
        Index("ix_hr_job_posting_company_status", "company_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    openings = Column(Integer, nullable=False, default=1, server_default="1")
    employment_type = Column(String(20), nullable=False, default="full_time", server_default="full_time")  # full_time | part_time | contract | internship
    description = Column(Text, nullable=True)
    status = Column(String(10), nullable=False, default="open", server_default="open", index=True)  # open | on_hold | closed | filled
    hired_count = Column(Integer, nullable=False, default=0, server_default="0")
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    department = relationship("Department")
    branch = relationship("Branch")

    @property
    def department_name(self) -> str | None:
        return self.department.name if self.department else None

    @property
    def branch_name(self) -> str | None:
        return self.branch.name if self.branch else None


class HrJobApplicant(TenantOwned, Base):
    """متقدم لوظيفة: applied → screening → interview → offer → hired|rejected.

    hired يُنشئ ملف موظف عبر POST /hr/applicants/{id}/hire.
    """

    __tablename__ = "hr_job_applicants"
    __table_args__ = (
        UniqueConstraint("company_id", "posting_id", "email", name="uq_hr_applicant_posting_email"),
        Index("ix_hr_applicant_company_stage", "company_id", "stage"),
    )

    id = Column(Integer, primary_key=True, index=True)
    posting_id = Column(Integer, ForeignKey("hr_job_postings.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name = Column(String(200), nullable=False)
    email = Column(String(150), nullable=False)
    phone = Column(String(40), nullable=True)
    source = Column(String(50), nullable=True)  # موقع توظيف/ترشيح/…
    resume_text = Column(Text, nullable=True)  # ملخص السيرة الذاتية
    stage = Column(String(20), nullable=False, default="applied", server_default="applied", index=True)
    rating = Column(Integer, nullable=True)  # 1..5 تقييم فحص أولي
    note = Column(Text, nullable=True)
    hired_employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    posting = relationship("HrJobPosting")
    hired_employee = relationship("HrEmployee", foreign_keys=[hired_employee_id])

    @property
    def posting_title(self) -> str | None:
        return self.posting.title if self.posting else None

    @property
    def posting_code(self) -> str | None:
        return self.posting.code if self.posting else None


class HrReviewCycle(TenantOwned, Base):
    """دورة تقييم أداء: open → closed (الإغلاق يقفل التعديل على تقييماتها)."""

    __tablename__ = "hr_review_cycles"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_hr_review_cycle_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(String(10), nullable=False, default="open", server_default="open", index=True)  # open | closed
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HrPerformanceReview(TenantOwned, Base):
    """تقييم أداء موظف داخل دورة — درجات 1..5 مع إجمالي محسوب (متوسط × 20 = نسبة)."""

    __tablename__ = "hr_performance_reviews"
    __table_args__ = (
        UniqueConstraint("company_id", "cycle_id", "employee_id", name="uq_hr_review_cycle_employee"),
    )

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("hr_review_cycles.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    quality = Column(Integer, nullable=False)  # 1..5
    commitment = Column(Integer, nullable=False)
    teamwork = Column(Integer, nullable=False)
    initiative = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    cycle = relationship("HrReviewCycle")
    employee = relationship("HrEmployee")

    @property
    def score(self) -> Decimal:
        """متوسط الدرجات (1..5) — النسبة = × 20."""
        return (Decimal(self.quality + self.commitment + self.teamwork + self.initiative) / 4).quantize(Decimal("0.01"))

    @property
    def employee_name(self) -> str | None:
        return self.employee.full_name if self.employee else None

    @property
    def employee_code(self) -> str | None:
        return self.employee.code if self.employee else None


class HrTraining(TenantOwned, Base):
    """دورة تدريبية داخل الشركة أو مزوّد خارجي."""

    __tablename__ = "hr_trainings"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_hr_training_code"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    provider = Column(String(150), nullable=True)
    location = Column(String(150), nullable=True)
    from_date = Column(Date, nullable=False)
    to_date = Column(Date, nullable=False)
    cost = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HrTrainingEnrollment(TenantOwned, Base):
    """تسجيل موظف في دورة: enrolled → completed | no_show (الإلغاء بحذف السجل)."""

    __tablename__ = "hr_training_enrollments"
    __table_args__ = (
        UniqueConstraint("company_id", "training_id", "employee_id", name="uq_hr_enroll_training_employee"),
    )

    id = Column(Integer, primary_key=True, index=True)
    training_id = Column(Integer, ForeignKey("hr_trainings.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(15), nullable=False, default="enrolled", server_default="enrolled", index=True)  # enrolled | completed | no_show
    completed_at = Column(DateTime(timezone=True), nullable=True)
    certificate_note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    training = relationship("HrTraining")
    employee = relationship("HrEmployee")

    @property
    def training_title(self) -> str | None:
        return self.training.title if self.training else None

    @property
    def employee_name(self) -> str | None:
        return self.employee.full_name if self.employee else None

    @property
    def employee_code(self) -> str | None:
        return self.employee.code if self.employee else None


# ---------------------------------------------------------------------------
# نظام الصلاحيات: كتالوج عالمي + أقسام واستثناءات فردية لكل شركة
# ---------------------------------------------------------------------------


class Permission(Base):
    """كتالوج الصلاحيات — مشتق من الكود (app/permissions.py) وعالمي غير tenant-scoped."""

    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(120), nullable=False, unique=True, index=True)
    module = Column(String(60), nullable=False, index=True)
    resource = Column(String(60), nullable=False, index=True)
    action = Column(String(60), nullable=False)
    label = Column(String(255), nullable=False, default="")
    is_dangerous = Column(Boolean, nullable=False, default=False, server_default="false")
    is_field = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AccessSection(TenantOwned, Base):
    """قسم صلاحيات — حزمة صلاحيات مشتركة تُسند للمستخدمين (مستقل عن إدارات HR)."""

    __tablename__ = "access_sections"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_access_section_code"),)

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(60), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    is_system = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AccessSectionPermission(TenantOwned, Base):
    """مصفوفة القسم × الصلاحية."""

    __tablename__ = "access_section_permissions"
    __table_args__ = (UniqueConstraint("section_id", "permission_id", name="uq_section_permission"),)

    id = Column(Integer, primary_key=True, index=True)
    section_id = Column(
        Integer, ForeignKey("access_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id = Column(
        Integer, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserPermissionOverride(TenantOwned, Base):
    """استثناء فردي فوق صلاحيات القسم: effect = grant (منح) أو deny (سحب يغلب)."""

    __tablename__ = "user_permission_overrides"
    __table_args__ = (
        CheckConstraint("effect IN ('grant', 'deny')", name="ck_permission_override_effect"),
        UniqueConstraint("user_id", "permission_id", name="uq_user_permission_override"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    permission_id = Column(
        Integer, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effect = Column(String(10), nullable=False, default="grant", server_default="grant")
    reason = Column(String(255), nullable=True)
    granted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SubcontractCustody(TenantOwned, Base):
    """عهدة خامات لدى مُصنّع خارجي: ما سُلّم له فيزيائيًا وما أُرجع — تتبع فوق مسار WIP القائم.

    الصرف المحاسبي يبقى عبر issue (Dr WIP/Cr مخزون) — العهدة سجل موقع فيزيائي فقط."""

    __tablename__ = "subcontract_custodies"
    __table_args__ = (UniqueConstraint("order_id", "product_id", name="uq_subcontract_custody"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    subcontractor_id = Column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    qty_sent = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")
    qty_returned = Column(Numeric(12, 3), nullable=False, default=0, server_default="0")
    notes = Column(String(200), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    order = relationship("ProductionOrder")
    product = relationship("Product")
    subcontractor = relationship("Supplier")


class CrmLead(TenantOwned, Base):
    """عميل محتمل (Lead) — خط البيع قبل التحويل لعميل فعلي في العملاء.

    المراحل: new → contacted → qualified → won (بعد التحويل) / lost.
    الكود فريد داخل الشركة (uq_crm_lead_company_code)."""

    __tablename__ = "crm_leads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'contacted', 'qualified', 'won', 'lost')",
            name="ck_crm_lead_status",
        ),
        UniqueConstraint("company_id", "code", name="uq_crm_lead_company_code"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), nullable=False, index=True)
    name = Column(String(150), nullable=False, index=True)          # اسم الشخص المسؤول
    company_name = Column(String(150), nullable=True)               # اسم النشاط/الشركة
    phone = Column(String(50), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(Text, nullable=True)
    source = Column(String(50), nullable=False, default="walk_in", server_default="walk_in")
    status = Column(String(20), nullable=False, default="new", server_default="new", index=True)
    expected_value = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    assigned_rep_id = Column(Integer, ForeignKey("sales_reps.id", ondelete="SET NULL"), nullable=True, index=True)
    notes = Column(Text, nullable=True)
    converted_customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    assigned_rep = relationship("SalesRep")
    converted_customer = relationship("Customer")
    activities = relationship(
        "CrmActivity", back_populates="lead", cascade="all, delete-orphan", order_by="CrmActivity.id.desc()"
    )


class CrmActivity(TenantOwned, Base):
    """نشاط متابعة على عميل محتمل (مكالمة/اجتماع/ملاحظة)."""

    __tablename__ = "crm_activities"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("crm_leads.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="note", server_default="note")
    body = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    lead = relationship("CrmLead", back_populates="activities")
