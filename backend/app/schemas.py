"""Pydantic (v2) schemas for request validation and responses."""

from datetime import date, date as _date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .permissions import field_mask_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Warehouses ----------
class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    description: Optional[str] = None
    is_active: bool = True


class DepartmentOut(ORMModel):
    id: int
    company_id: int
    name: str
    code: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime


# ---------- Sales representatives ----------
class SalesRepCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    phone: Optional[str] = Field(default=None, max_length=40)
    branch_ids: List[int] = Field(default_factory=list)
    commission_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    is_active: bool = True


class SalesRepUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    phone: Optional[str] = Field(default=None, max_length=40)
    branch_ids: Optional[List[int]] = None
    commission_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)
    is_active: Optional[bool] = None


class SalesRepOut(ORMModel):
    user_id: Optional[int] = None
    username: Optional[str] = None
    id: int
    company_id: int
    name: str
    code: str
    phone: Optional[str] = None
    branch_ids: List[int] = []
    commission_percent: Decimal
    is_active: bool
    created_at: datetime


class WarehouseBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50)
    location: Optional[str] = None
    is_active: bool = True


class WarehouseCreate(WarehouseBase):
    code: Optional[str] = None  # type: ignore
    branch_id: Optional[int] = None


class WarehouseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    location: Optional[str] = None
    is_active: Optional[bool] = None


class WarehouseOut(WarehouseBase, ORMModel):
    id: int
    branch_id: int
    created_at: datetime


# ---------- Safes & Banks ----------
class SafeBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50)
    branch_id: int
    is_active: bool = True


class SafeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    branch_id: Optional[int] = None
    is_active: bool = True
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0)


class SafeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    branch_id: Optional[int] = None
    is_active: Optional[bool] = None


class SafeOut(SafeBase, ORMModel):
    id: int
    balance: Decimal
    created_at: datetime


class BankBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50)
    account_number: Optional[str] = None
    is_active: bool = True


class BankCreate(BankBase):
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0)
    branch_id: Optional[int] = None  # NULL = الشركة ككل


class BankUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    account_number: Optional[str] = None
    is_active: Optional[bool] = None


class BankOut(BankBase, ORMModel):
    id: int
    balance: Decimal
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None
    created_at: datetime


# ---------- Suppliers / Customers (same shape) ----------
class PartyBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, max_length=50)  # auto-generated when empty
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    is_active: bool = True
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0)


class PartyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None
    opening_balance: Optional[Decimal] = Field(default=None, ge=0)


class SupplierCreate(PartyBase):
    tax_registration_number: Optional[str] = Field(default=None, max_length=50, description="الرقم الضريبي (فواتير المنظومة)")
    credit_limit: Optional[Decimal] = Field(default=None, ge=0, description="سقف المديونية للمورد (NULL = بلا سقف)")


class SupplierUpdate(PartyUpdate):
    credit_limit: Optional[Decimal] = Field(default=None, ge=0)


class SupplierOut(PartyBase, ORMModel):
    tax_registration_number: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    id: int
    created_at: datetime
    balance: Optional[Decimal] = Decimal("0")  # what we owe the supplier — يُقنَّع لمن لا يملك صلاحية العرض

    from pydantic import field_validator as _fv2

    _mask_balance = _fv2("balance", mode="before")(
        field_mask_validator("Supplier", "balance")
    )


class CustomerCreate(PartyBase):
    credit_limit: Optional[Decimal] = Field(default=None, ge=0, description="الحد الائتماني — اتركه فارغًا لبلا حد")
    tax_registration_number: Optional[str] = Field(default=None, max_length=50, description="الرقم الضريبي للعميل (فواتير B2B)")
    price_list_id: Optional[int] = Field(default=None, description="قائمة أسعار العميل (تتجاوز سعر البيع العام)")


class CustomerUpdate(PartyUpdate):
    credit_limit: Optional[Decimal] = Field(default=None, ge=0)
    tax_registration_number: Optional[str] = Field(default=None, max_length=50)
    price_list_id: Optional[int] = None


class CustomerOut(PartyBase, ORMModel):
    id: int
    created_at: datetime
    credit_limit: Optional[Decimal] = None
    tax_registration_number: Optional[str] = None
    price_list_id: Optional[int] = None
    price_list_name: Optional[str] = None
    balance: Optional[Decimal] = Decimal("0")  # what the customer owes us — يُقنَّع لمن لا يملك صلاحية العرض

    from pydantic import field_validator as _fv3

    _mask_balance = _fv3("balance", mode="before")(
        field_mask_validator("Customer", "balance")
    )


# ---------- Products ----------
class ProductBase(BaseModel):
    sku: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    unit: str = "piece"
    cost_price: Decimal = Field(default=Decimal("0"), ge=0)
    sale_price: Decimal = Field(default=Decimal("0"), ge=0)
    reorder_level: int = Field(default=0, ge=0)
    is_active: bool = True
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None
    # صورة من رابط إنترنت (الملفات المرفوعة تُحفظ بالبايتات وتُصدَر عبر /products/{id}/image)
    image_url: Optional[str] = Field(default=None, max_length=500)


class ProductCreate(ProductBase):
    sku: Optional[str] = Field(default=None, min_length=1, max_length=60)
    # Opening balance only; afterwards quantity changes via purchases/sales/adjustments.
    quantity: float = Field(default=0, ge=0)


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    unit: Optional[str] = None
    cost_price: Optional[Decimal] = Field(default=None, ge=0)
    sale_price: Optional[Decimal] = Field(default=None, ge=0)
    reorder_level: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None
    image_url: Optional[str] = Field(default=None, max_length=500)


class ProductOut(ProductBase, ORMModel):
    warehouse_min_level: Optional[float] = None  # حد المخزن الخاص (مع stock_warehouse_id)
    id: int
    quantity: float  # total over all warehouses
    warehouse_quantity: Optional[float] = None  # only when the list was asked for one warehouse (?stock_warehouse_id=)
    image_uploaded: bool = False
    created_at: datetime
    # حقل حساس: يُقنَّع (None) لمن لا يملك inventory.product.cost_view
    cost_price: Optional[Decimal] = None

    from pydantic import field_validator as _fv

    _mask_cost_price = _fv("cost_price", mode="before")(
        field_mask_validator("Product", "cost_price")
    )


class ProductStockOut(BaseModel):
    warehouse_id: int
    warehouse_name: str
    quantity: float
    min_level: Optional[float] = None  # حد الطلب الأدنى الخاص بالمخزن (NULL = يستخدم العام)


class StockAdjustment(BaseModel):
    change: float = Field(description="Positive to add stock, negative to remove.")
    reference: Optional[str] = None
    warehouse_id: Optional[int] = Field(default=None, description="Defaults to the product's own warehouse.")


class StockMovementOut(ORMModel):
    id: int
    product_id: int
    warehouse_id: Optional[int]
    change: float
    reason: str
    reference: Optional[str]
    created_at: datetime


# ---------- Purchase orders ----------
class PurchaseItemIn(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)


class PurchaseItemOut(PurchaseItemIn, ORMModel):
    id: int
    product_name: Optional[str] = None
    returned_quantity: float = 0


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    notes: Optional[str] = None
    payment_mode: Literal["cash", "credit"] = "credit"
    safe_id: Optional[int] = None
    discount_mode: Literal["amount", "percent"] = "amount"
    discount_value: Decimal = Field(default=Decimal("0"), ge=0)
    tax_rate: Decimal = Field(default=Decimal("14"), ge=0, le=100)
    currency_id: Optional[int] = None
    items: List[PurchaseItemIn] = Field(min_length=1)


class PurchaseOrderOut(ORMModel):
    id: int
    supplier_id: int
    party_name: Optional[str] = None
    warehouse_id: int
    status: str
    notes: Optional[str]
    total_amount: Decimal
    discount_amount: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    currency_id: Optional[int] = None
    currency_code: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    foreign_total: Optional[Decimal] = None
    created_at: datetime
    items: List[PurchaseItemOut]
    paid_amount: Optional[Decimal] = None
    balance_due: Optional[Decimal] = None
    payment_status: Optional[str] = None  # paid | partial | unpaid (None while draft/cancelled)


# ---------- Sales orders ----------
class SalesItemIn(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    unit_price: Optional[Decimal] = Field(
        default=None, ge=0, description="Defaults to the product's current sale price."
    )


class SalesItemOut(ORMModel):
    id: int
    product_id: int
    quantity: float
    unit_price: Decimal
    product_name: Optional[str] = None
    returned_quantity: float = 0


class SalesOrderCreate(BaseModel):
    customer_id: int
    warehouse_id: int
    notes: Optional[str] = None
    rep_id: Optional[int] = None  # مندوب المبيعات المسجل على الفاتورة
    safe_id: Optional[int] = None  # اسم الخزينة المقترحة لتحصيل الفاتورة
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)  # ضريبة القيمة المضافة %
    currency_id: Optional[int] = None  # عملة الفاتورة (اختياري — الافتراضي جنيه)
    document_type: Optional[Literal["order", "quotation"]] = "order"  # عرض سعر = لا مخزون ولا تأكيد
    discount_mode: Optional[Literal["amount", "percent"]] = "amount"
    discount_value: Optional[Decimal] = Field(default=None, ge=0)
    items: List[SalesItemIn] = Field(min_length=1)


class SalesOrderOut(ORMModel):
    id: int
    customer_id: int
    party_name: Optional[str] = None
    warehouse_id: int
    status: str
    discount_amount: Optional[Decimal] = None
    notes: Optional[str]
    rep_id: Optional[int] = None
    rep_name: Optional[str] = None
    safe_id: Optional[int] = None
    safe_name: Optional[str] = None
    total_amount: Decimal
    subtotal: Optional[Decimal] = None  # الصافي قبل الضريبة (NULL للأوامر القديمة)
    tax_rate: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    currency_id: Optional[int] = None
    currency_code: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    foreign_total: Optional[Decimal] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    items: List[SalesItemOut]
    paid_amount: Optional[Decimal] = None
    balance_due: Optional[Decimal] = None
    payment_status: Optional[str] = None


# ---------- Auth / users ----------
Role = Literal["admin", "manager", "staff"]


class SetupAdmin(BaseModel):
    username: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = None


class UserCreate(SetupAdmin):
    role: Role = "staff"
    branch_ids: List[int] = Field(default_factory=list)
    warehouse_ids: List[int] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[Role] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class UserOut(ORMModel):
    id: int
    username: str
    full_name: Optional[str]
    role: str
    is_active: bool
    is_platform_admin: bool = False
    active_company_id: Optional[int] = None
    created_at: datetime
    branch_ids: List[int] = []
    warehouse_ids: List[int] = []
    permissions: List[str] = []


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    max_warehouses_per_branch: Optional[int] = Field(default=None, gt=0)
    max_safes_per_branch: Optional[int] = Field(default=None, gt=0)
    max_branches: Optional[int] = Field(default=None, gt=0)
    admin_username: str = Field(min_length=3, max_length=60)
    admin_password: str = Field(min_length=8, max_length=128)
    admin_full_name: Optional[str] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    max_warehouses_per_branch: Optional[int] = Field(default=None, gt=0)
    max_safes_per_branch: Optional[int] = Field(default=None, gt=0)
    max_branches: Optional[int] = Field(default=None, gt=0)
    je_approval_threshold: Optional[Decimal] = Field(default=None, ge=0,
        description="حد اعتماد القيود بالعملة — أعلى منه يحتاج اعتماد مدير (NULL = معطل)")
    accounting_lock_date: Optional[date] = Field(default=None,
        description="تاريخ قفل الحسابات — يمنع الترحيل بتاريخ أقدم من أو يساوي هذا التاريخ")
    is_active: Optional[bool] = None


class CompanyLicenseUpdate(BaseModel):
    license_until: Optional[date] = None  # تاريخ الانتهاء — NULL = غير مقيّد
    license_password: str = Field(min_length=1)  # كلمة سر التجديد (سر المورّد) — إلزامية لأي تغيير


class CompanyOut(ORMModel):
    id: int
    name: str
    code: str
    max_warehouses_per_branch: Optional[int]
    max_safes_per_branch: Optional[int]
    max_branches: Optional[int] = None
    license_until: Optional[date] = None  # رخصة الاستخدام — NULL = غير مقيّد
    accounting_lock_date: Optional[date] = None
    is_active: bool
    created_at: datetime


class SwitchCompany(BaseModel):
    company_id: int


class CompanyMembershipCreate(BaseModel):
    username: str = Field(min_length=3, max_length=60)
    role: str = Field(default="staff", pattern="^(admin|manager|staff)$")


class BranchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    location: Optional[str] = None


class BranchUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    location: Optional[str] = None
    is_active: Optional[bool] = None


class BranchOut(ORMModel):
    id: int
    company_id: int
    name: str
    code: str
    location: Optional[str]
    is_active: bool
    created_at: datetime


class EmployeeCreate(BaseModel):
    username: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = None
    role: Role = "staff"
    department_id: Optional[int] = None
    all_branches: bool = False
    branch_ids: List[int] = Field(default_factory=list)
    warehouse_ids: List[int] = Field(default_factory=list)


class EmployeeUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[Role] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    department_id: Optional[int] = None
    all_branches: Optional[bool] = None
    branch_ids: Optional[List[int]] = None
    warehouse_ids: Optional[List[int]] = None


class EmployeeOut(UserOut):
    employee_code: str
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    all_branches: bool = False
    branch_ids: List[int]
    warehouse_ids: List[int]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None  # توكن تجديد طويل الأمد (الموبايل) — None للتوافق مع القديم


# ---------- Reports ----------
class LowStockItem(ORMModel):
    id: int
    sku: str
    name: str
    quantity: float
    reorder_level: int
    shortfall: float
    min_source: Optional[str] = None  # "warehouse" عند وجود حد خاص بالمخزن وإلا "product"
    image_url: Optional[str] = None
    image_uploaded: bool = False
    supplier_name: Optional[str] = None
    warehouse_id: Optional[int]
    supplier_id: Optional[int]


class ReorderForecastItem(BaseModel):
    product_id: int
    sku: str
    name: str
    current_stock: float
    daily_sales: float
    lead_time_days: int
    safety_stock: float
    suggested_rop: float
    reorder_urgency: str  # critical | warning | healthy
    days_left: Optional[float] = None
    suggested_order_qty: float
    unit_cost: float
    estimated_cost: float
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    warehouse_id: Optional[int] = None


class ReorderForecastOut(BaseModel):
    days_analyzed: int
    total_items_analyzed: int
    critical_count: int
    warning_count: int
    total_suggested_investment: float
    items: List[ReorderForecastItem]


class InventoryValuationRow(BaseModel):
    warehouse_id: Optional[int]
    warehouse_name: Optional[str]
    products: int
    units: float
    cost_value: Decimal
    sale_value: Decimal


class SalesByDay(BaseModel):
    day: str
    orders: int
    total: Decimal


class ProfitRow(BaseModel):
    product_id: int
    sku: str
    name: str
    quantity: float
    revenue: Decimal
    cost: Decimal
    profit: Decimal
    margin_pct: Optional[Decimal]


class ProfitSummary(BaseModel):
    date_from: datetime
    date_to: datetime
    sales: Decimal  # confirmed sales in the period
    returns: Decimal  # customer returns made in the period
    revenue: Decimal  # sales - returns
    cost: Decimal  # cost of goods sold, net of returned goods
    profit: Decimal
    margin_pct: Optional[Decimal]
    by_product: List[ProfitRow]


class TopProduct(BaseModel):
    product_id: int
    sku: str
    name: str
    quantity_sold: float
    revenue: Decimal


class SalesByCustomer(BaseModel):
    customer_id: int
    customer_name: str
    orders: int
    total: Decimal


class SalesByProductSupplier(BaseModel):
    supplier_id: Optional[int] = None
    supplier_name: str
    orders: int
    total: Decimal


class SalesByCashier(BaseModel):
    username: Optional[str] = None  # None: orders made before creators were recorded
    orders: int
    total: Decimal


class SalesSummary(BaseModel):
    date_from: datetime
    date_to: datetime
    orders: int
    total: Decimal
    by_day: List[SalesByDay]
    top_products: List[TopProduct]
    by_customer: List[SalesByCustomer] = []
    by_cashier: List[SalesByCashier] = []
    by_product_supplier: List[SalesByProductSupplier] = []


class PurchaseTopProduct(BaseModel):
    product_id: int
    sku: str
    name: str
    quantity_bought: float
    spend: Decimal


class PurchaseBySupplier(BaseModel):
    supplier_id: int
    supplier_name: str
    orders: int
    total: Decimal


class PurchasesSummary(BaseModel):
    date_from: datetime
    date_to: datetime
    orders: int
    total: Decimal
    by_day: List[SalesByDay]  # same shape: day, orders, total
    top_products: List[PurchaseTopProduct]
    by_supplier: List[PurchaseBySupplier]


class Dashboard(BaseModel):
    period_days: int
    products: int
    low_stock_products: int
    warehouses: int
    suppliers: int
    customers: int
    inventory_cost_value: Decimal
    inventory_sale_value: Decimal
    sales_orders_confirmed: int
    sales_total: Decimal
    purchase_orders_received: int
    purchases_total: Decimal
    draft_sales_orders: int
    draft_purchase_orders: int
    receivables_total: Decimal = Decimal("0")
    sales_returns_total: Decimal = Decimal("0")  # returns in the same period as sales_total
    purchase_returns_total: Decimal = Decimal("0")
    payables_total: Decimal = Decimal("0")
    stale_shifts: int = 0  # cashier shifts left open too long
    sales_growth_pct: Optional[float] = None
    purchases_growth_pct: Optional[float] = None
    pending_transfers: int = 0
    cash_liquidity_total: Decimal = Decimal("0")
    safes_balance_total: Decimal = Decimal("0")
    banks_balance_total: Decimal = Decimal("0")
    lots_expiring_soon: int = 0        # لوطات تنتهي خلال 30 يومًا وما زالت بها كمية
    cheques_due_soon: int = 0          # شيكات تستحق خلال أيام (المتغير CHEQUES_DUE_DAYS)
    recurring_journals_due: int = 0    # قوالب قيود متكررة مستحقة الترحيل الآن
    pending_journal_approvals: int = 0 # قيود بانتظار اعتماد المدير


# ---------- Payments & statements ----------
PaymentMethod = Literal["cash", "bank", "wallet", "cheque", "credit"]  # credit = آجل (يُخصم من رصيد الطرف)


class PaymentCategoryOut(ORMModel):
    id: int
    name: str
    kind: Literal["receipt", "payment"] = "receipt"
    requires_party: bool = True


class PaymentCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    kind: Literal["receipt", "payment"] = "receipt"
    requires_party: bool = True


class PaymentCreate(BaseModel):
    customer_id: Optional[int] = None  # money received from this customer
    supplier_id: Optional[int] = None  # money paid to this supplier
    safe_id: Optional[int] = None  # optional safe (cash box) to debit/credit
    bank_id: Optional[int] = None  # optional bank account to debit/credit
    category_id: Optional[int] = None  # بند القبض / الصرف (required when the voucher has no party)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    method: PaymentMethod = "cash"
    reference: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None
    paid_on: Optional[date] = None  # defaults to today
    currency_id: Optional[int] = None  # عملة السند (اختياري — الافتراضي جنيه)
    foreign_amount: Optional[Decimal] = Field(default=None, gt=0)  # المبلغ بالعملة الأجنبية
    # ضريبة الخصم والإضافة: سندات الدفع للموردين فقط — المحتجز يُورَّد للمصلحة والنقدية = amount − المحتجز
    withholding_amount: Optional[Decimal] = Field(default=None, ge=0)
    withholding_code_id: Optional[int] = None

    @model_validator(mode="after")
    def _party_shape(self):
        if self.customer_id is not None and self.supplier_id is not None:
            raise ValueError("Provide only one of customer_id or supplier_id")
        if self.customer_id is None and self.supplier_id is None and self.category_id is None:
            raise ValueError("A voucher with no party requires category_id (بند القبض / الصرف)")
        return self


class PaymentOut(ORMModel):
    id: int
    kind: Literal["receipt", "payment"]
    customer_id: Optional[int]
    supplier_id: Optional[int]
    safe_id: Optional[int] = None
    bank_id: Optional[int] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    company_name: Optional[str] = None
    safe_branch_name: Optional[str] = None
    party_name: Optional[str] = None
    amount: Decimal
    method: str
    reference: Optional[str]
    notes: Optional[str]
    paid_on: date
    currency_id: Optional[int] = None
    currency_code: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    foreign_amount: Optional[Decimal] = None
    withholding_amount: Decimal = Decimal("0")
    withholding_code_id: Optional[int] = None
    withholding_code_name: Optional[str] = None
    status: str
    created_at: datetime


Day = date  # alias: a field called `date` must not shadow its own type annotation


# ---------- Cheques (حافظة الشيكات) ----------

ChequeDirection = Literal["received", "issued"]


class ChequeCreate(BaseModel):
    direction: ChequeDirection
    number: str = Field(min_length=1, max_length=60)
    bank_id: int  # البنك المسحوب عليه
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    customer_id: Optional[int] = None  # required when direction == "received"
    supplier_id: Optional[int] = None  # required when direction == "issued"
    cheque_date: Optional[date] = None  # defaults to today
    due_date: Optional[date] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _party_matches_direction(self):
        if self.direction == "received":
            if self.customer_id is None or self.supplier_id is not None:
                raise ValueError("استلام الشيك يتطلب اختيار العميل")
        else:
            if self.supplier_id is None or self.customer_id is not None:
                raise ValueError("صرف الشيك يتطلب اختيار المورد")
        return self


class ChequeOut(ORMModel):
    id: int
    direction: ChequeDirection
    number: str
    bank_id: int
    bank_name: Optional[str] = None
    bank_branch_name: Optional[str] = None
    company_name: Optional[str] = None
    amount: Decimal
    customer_id: Optional[int] = None
    supplier_id: Optional[int] = None
    party_name: Optional[str] = None
    cheque_date: date
    due_date: Optional[date] = None
    status: str
    payment_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime


class ChequeCollectIn(BaseModel):
    safe_id: int


class ChequeDepositIn(BaseModel):
    bank_id: int


# ---------- Safe / bank statements (from the ledger) ----------

class AccountStatementLine(BaseModel):
    entry_id: int
    date: date
    description: Optional[str] = None
    reference: Optional[str] = None
    debit: Decimal  # داخل (للخزينة/البنك)
    credit: Decimal  # خارج
    balance: Decimal


class AccountStatementOut(BaseModel):
    account_name: str
    account_code: str
    opening: Decimal
    closing: Decimal
    total_debit: Decimal
    total_credit: Decimal
    lines: List[AccountStatementLine]


# ---------- Manufacturing (التصنيفات: قوائم المواد وأوامر التصنيع) ----------

# ---------- Manufacturing (التصنيفات: قوائم المواد وأوامر التصنيع) ----------

class BomOperationIn(BaseModel):
    seq: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=150)
    work_center_id: Optional[int] = None
    run_minutes_per_unit: float = Field(default=0, ge=0)
    notes: Optional[str] = Field(default=None, max_length=200)


class BomOperationOut(ORMModel):
    id: int
    seq: int
    name: str
    work_center_id: Optional[int] = None
    work_center_name: Optional[str] = None
    run_minutes_per_unit: float
    notes: Optional[str] = None


class BomItemIn(BaseModel):
    component_id: int
    qty_per_output: Decimal = Field(gt=0, max_digits=12, decimal_places=3)  # كمية المكوّن لكل وحدة ناتجة
    scrap_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=5, decimal_places=2)
    operation_seq: Optional[int] = None  # مرحلة الصرف (NULL = الصرف المجمّع عند بدء التشغيل)
    notes: Optional[str] = Field(default=None, max_length=200)


class BomCreate(BaseModel):
    product_id: int
    version: str = Field(default="v1", max_length=20)
    output_qty: float = Field(default=1, ge=1)  # الكمية الناتجة من القائمة
    is_active: bool = True
    notes: Optional[str] = None
    items: List[BomItemIn] = []
    operations: List[BomOperationIn] = []  # مسار التشغيل (مراحل مرتبة)


class BomItemOut(ORMModel):
    id: int
    component_id: int
    component_name: Optional[str] = None
    component_code: Optional[str] = None
    component_unit: Optional[str] = None
    qty_per_output: Decimal
    scrap_pct: Decimal
    operation_seq: Optional[int] = None
    notes: Optional[str] = None


class BomOut(ORMModel):
    id: int
    product_id: int
    product_name: Optional[str] = None
    version: str
    output_qty: float
    is_active: bool
    notes: Optional[str] = None
    items: List[BomItemOut] = []
    operations: List[BomOperationOut] = []
    created_at: datetime


class ProductionOrderCreate(BaseModel):
    product_id: int
    bom_id: Optional[int] = None  # auto-picks the active BOM when omitted
    qty_planned: float = Field(gt=0)
    raw_warehouse_id: int
    output_warehouse_id: int
    subcontractor_id: Optional[int] = None  # مورد التصنيع الخارجي (اختياري)
    production_line_id: Optional[int] = None  # خط الإنتاج
    scheduled_date: Optional[date] = None
    notes: Optional[str] = None


class ProductionConsumptionOut(ORMModel):
    component_id: int
    component_name: Optional[str] = None
    component_unit: Optional[str] = None
    qty: float
    unit_cost: Decimal
    total_cost: Decimal


class ProductionCostIn(BaseModel):
    cost_type: Literal["labor", "overhead", "subcontract"]
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    description: Optional[str] = Field(default=None, max_length=200)


class ProductionCostOut(ORMModel):
    id: int
    cost_type: Literal["labor", "overhead", "subcontract"]
    amount: Decimal
    description: Optional[str] = None
    created_at: datetime


class ProductionOrderOut(ORMModel):
    id: int
    code: str
    product_id: int
    product_name: Optional[str] = None
    bom_id: Optional[int] = None
    qty_planned: float
    qty_produced: float
    status: str
    raw_warehouse_id: int
    raw_warehouse_name: Optional[str] = None
    output_warehouse_id: int
    output_warehouse_name: Optional[str] = None
    subcontractor_id: Optional[int] = None
    subcontractor_name: Optional[str] = None
    estimated_minutes: Optional[float] = None  # دقائق التشغيل المقدرة (مراحل الأمر × الكمية المخططة)
    materials_available: Optional[bool] = None  # توفر الخامات بالكامل في مخزن الخامات (للأوامر النشطة)
    production_line_id: Optional[int] = None
    production_line_name: Optional[str] = None
    scheduled_date: Optional[date] = None
    is_late: Optional[bool] = None
    qty_scrapped: float = 0
    scrap_cost: Decimal = Decimal("0")
    std_unit_cost: Optional[Decimal] = None
    parent_order_id: Optional[int] = None
    notes: Optional[str] = None
    consumptions: List[ProductionConsumptionOut] = []
    costs: List[ProductionCostOut] = []
    costs_total: Decimal = Decimal("0")
    batches: List["ProductionBatchOut"] = []
    children: List["ProductionChildOut"] = []
    operations: List["ProductionOrderOperationOut"] = []
    created_at: datetime


class ProductionBatchOut(ORMModel):
    id: int
    batch_no: str
    qty: float
    cost: Decimal
    qc_status: Literal["pending", "passed", "rejected"]
    produced_at: datetime
    notes: Optional[str] = None


class ProductionChildOut(ORMModel):
    id: int
    code: str
    product_id: int
    product_name: Optional[str] = None
    qty_planned: float
    status: str


class ProductionOrderOperationOut(ORMModel):
    id: int
    seq: int
    name: str
    work_center_id: Optional[int] = None
    work_center_name: Optional[str] = None
    run_minutes_per_unit: float
    status: Literal["pending", "in_progress", "done"]
    qty_done: float
    qty_scrapped: float
    issued: bool
    completed_at: Optional[datetime] = None


class BatchQcIn(BaseModel):
    result: Literal["passed", "rejected"]
    notes: Optional[str] = Field(default=None, max_length=200)  # سبب الرفض (إلزامي عند الرفض)


class OperationProgressIn(BaseModel):
    qty_done: float = Field(gt=0)  # الكمية المكتملة في هذه المرحلة
    qty_scrapped: float = Field(default=0, ge=0)


class WorkCenterIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    capacity_per_hour: Optional[float] = Field(default=None, gt=0)
    hourly_cost: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    notes: Optional[str] = Field(default=None, max_length=200)


class WorkCenterOut(ORMModel):
    id: int
    name: str
    capacity_per_hour: Optional[float] = None
    hourly_cost: Optional[Decimal] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime


class ProductionLineIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    capacity_per_hour: Optional[float] = Field(default=None, gt=0)
    hourly_cost: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)


class ProductionLineOut(ORMModel):
    id: int
    name: str
    capacity_per_hour: Optional[float] = None
    hourly_cost: Optional[Decimal] = None
    is_active: bool
    created_at: datetime


class ManufacturingReportLine(BaseModel):
    order_id: int
    code: str
    product_name: Optional[str] = None
    qty_planned: float
    qty_produced: float
    materials: Decimal
    costs: Decimal
    total: Decimal
    unit_cost: Decimal
    variance: Decimal
    std_unit_cost: Optional[Decimal] = None   # التكلفة القياسية للوحدة وقت إنشاء الأمر
    std_total: Optional[Decimal] = None       # القياسية × المنتج فعليًا
    variance_std: Optional[Decimal] = None    # الفعلي − القياسي (تحليل الربح والخسارة)


class ManufacturingByProduct(BaseModel):
    product_id: int
    product_name: Optional[str] = None
    orders: int
    qty_produced: float
    total: Decimal


class ManufacturingReportOut(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    lines: List[ManufacturingReportLine]
    total_orders: int
    total_qty_produced: float
    total_materials: Decimal
    total_costs: Decimal
    total: Decimal
    total_variance: Decimal
    total_variance_std: Decimal = Decimal("0")  # إجمالي (الفعلي − القياسي)
    by_product: List[ManufacturingByProduct]

# ---------- Reconciliation (مطابقة أرصدة الشجرة مع الدفتر) ----------

class ReconcileLine(BaseModel):
    account_id: int
    code: str
    name: str
    type: str
    stored: Decimal
    ledger: Decimal
    drift: Decimal


class ReconcileOut(BaseModel):
    lines: List[ReconcileLine]
    total_stored: Decimal
    total_ledger: Decimal
    total_drift: Decimal
    changed: int = 0
    journal_entry_id: Optional[int] = None
    cash_synced: int = 0


class ReconcileApplyIn(BaseModel):
    """تسوية مختارة: إعادة بناء الرصيد المخزن من الدفتر أو ترحيل الفرق كقيد موزون."""
    account_ids: Optional[List[int]] = None  # None = كل الحسابات المتنافرة
    mode: Literal["rebuild", "journal"] = "rebuild"
    counter_account_id: Optional[int] = None  # إلزامي في وضع journal


class ProductionProduceIn(BaseModel):
    qty: float = Field(gt=0)  # كمية الدفعة المنتجة


class BomCopyIn(BaseModel):
    version: Optional[str] = Field(default=None, max_length=20)  # فارغ = اقتراح vN التالي تلقائيًا
    is_active: bool = False  # فعّل النسخة الجديدة فورًا؟


class ProductionScheduleIn(BaseModel):
    scheduled_date: Optional[date] = None  # تاريخ التشغيل المخطط — NULL = إزالة الجدولة
    production_line_id: Optional[int] = None  # خط الإنتاج — NULL = بدون خط


class ConsumptionLotRow(BaseModel):
    component_id: int
    component_name: str
    lot_id: int
    lot_code: str
    qty: float
    source: str
    reference: Optional[str] = None
    expiry_date: Optional[date] = None


class WorkCenterPerfRow(BaseModel):
    work_center_id: int
    name: str
    orders_count: int = 0
    qty_done: float = 0
    qty_scrapped: float = 0
    actual_minutes: float = 0
    planned_minutes: float = 0
    utilization: float = 0  # الفعلي ÷ المخطط %


class WorkCenterPerfOut(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    rows: List[WorkCenterPerfRow] = []


class ProductionScrapIn(BaseModel):
    qty: float = Field(gt=0)  # كمية الهالك
    notes: Optional[str] = Field(default=None, max_length=200)


class WipOrderOut(BaseModel):
    id: int
    code: str
    product_id: int
    product_name: Optional[str] = None
    qty_planned: float
    qty_produced: float
    remaining: float
    materials: Decimal
    costs: Decimal
    wip_value: Decimal
    unit_cost: Decimal
    scheduled_date: Optional[date] = None


class MaterialsAvailabilityItem(BaseModel):
    component_id: int
    component_name: Optional[str] = None
    component_unit: Optional[str] = None
    required: Decimal          # المطلوب حسب القائمة (بالخامات المرحلية أيضًا)
    available: Decimal         # المتاح في مخزن الخامات الآن
    unit_cost: Decimal
    enough: bool
    staged: bool = False       # مرتبطة بمرحلة (تُصرف من الصرف المرحلي)


class MaterialsAvailabilityOut(BaseModel):
    order_id: int
    code: str
    warehouse_name: Optional[str] = None
    lines: List[MaterialsAvailabilityItem]
    all_available: bool
    missing_count: int


class MrpComponentSuggestion(BaseModel):
    product_id: int
    product_name: Optional[str] = None
    unit: Optional[str] = None
    required_total: Decimal    # إجمالي المطلوب عبر كل المستويات
    in_stock: Decimal          # الرصيد الكلي بكل المخازن
    shortfall: Decimal         # العجز (موجب) أو الفائض (0)
    has_bom: bool              # يُنتج داخليًا (أمر تصنيع) أم يُشترى
    suggested_qty: Decimal     # الكمية المقترح إنتاجها أو شراؤها


class MrpSuggestionOut(BaseModel):
    product_id: int
    product_name: Optional[str] = None
    qty: Decimal
    lines: List[MrpComponentSuggestion]


class MrpAggregateOut(BaseModel):
    """تخطيط الاحتياجات الإجمالي: لكل منتج مصنّع — المطلوب (أوامر البيع المفتوحة) مقابل الرصيد واقتراح الكمية."""
    lines: List["MrpAggregateRow"]


class MrpAggregateRow(BaseModel):
    product_id: int
    product_name: Optional[str] = None
    unit: Optional[str] = None
    in_stock: Decimal            # الرصيد الكلي بكل المخازن
    open_demand: Decimal         # كميات أوامر البيع المؤكدة وغير المشحونة
    shortfall: Decimal           # ما يجب إنتاجه لسد الطلب المفتوح (عند العجز)
    has_bom: bool


class BatchTraceChild(BaseModel):
    code: str
    product_name: Optional[str] = None
    batches: List[str]         # أرقام دفعات الأوامر الفرعية


class BatchTraceOut(BaseModel):
    batch_no: str
    qty: Decimal
    cost: Decimal
    qc_status: str
    produced_at: datetime
    order_id: int
    order_code: str
    order_status: str
    product_name: Optional[str] = None
    consumptions: List[ProductionConsumptionOut] = []   # الخامات التي صُنعت منها الدفعة
    children: List[BatchTraceChild] = []                # دفعات الأوامر الفرعية المرتبطة


class StatementLine(BaseModel):
    date: Day
    type: Literal["sale", "purchase", "receipt", "payment", "sale_return", "purchase_return"]
    ref: str
    description: str
    charge: Decimal  # increases the balance (sale to a customer / purchase from a supplier)
    payment: Decimal  # decreases the balance (money received / paid)
    balance: Decimal  # running balance after this line


class Statement(BaseModel):
    kind: Literal["customer", "supplier"]
    party_id: int
    party_name: str
    date_from: Optional[date]
    date_to: Optional[date]
    opening: Decimal
    lines: List[StatementLine]
    total_charges: Decimal
    total_payments: Decimal
    closing: Decimal


class BalanceRow(BaseModel):
    party_id: int
    name: str
    phone: Optional[str]
    balance: Decimal


class BalancesReport(BaseModel):
    total: Decimal
    rows: List[BalanceRow]


class AgingRow(BaseModel):
    party_id: int
    name: str
    phone: Optional[str] = None
    opening: Decimal  # unpaid part of the opening balance
    current: Decimal  # 0-30 days
    d31_60: Decimal
    d61_90: Decimal
    d90_plus: Decimal
    total: Decimal


class AgingReport(BaseModel):
    as_of: date
    total_opening: Decimal
    total_current: Decimal
    total_d31_60: Decimal
    total_d61_90: Decimal
    total_d90_plus: Decimal
    total_total: Decimal
    rows: List[AgingRow]


class CashFlowRow(BaseModel):
    """سطر في قائمة التدفقات النقدية: الحساب المقابل وأثره على النقدية."""
    code: str
    name: str
    amount: Decimal


class CashFlowStatement(BaseModel):
    """قائمة التدفقات النقدية — الطريقة المباشرة من حركة حسابات النقدية."""
    date_from: date
    date_to: date
    opening: Decimal
    closing: Decimal
    net_change: Decimal
    operating: List[CashFlowRow]
    operating_total: Decimal
    investing: List[CashFlowRow]
    investing_total: Decimal
    financing: List[CashFlowRow]
    financing_total: Decimal


class AuditLogOut(ORMModel):
    id: int
    created_at: datetime
    username: Optional[str]
    action: str
    entity: str
    entity_id: Optional[int]
    summary: Optional[str]


class UserActivity(BaseModel):
    """مراقبة المستخدم: سجل نشاطه كاملاً من أول تسجيل دخول حتى الآن."""

    username: str
    full_name: Optional[str] = None
    first_login: Optional[datetime] = None
    last_login: Optional[datetime] = None
    login_count: int = 0
    total: int
    logs: List[AuditLogOut]


# ---------- Point of sale ----------
class PosItem(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)


class PosPaymentLeg(BaseModel):
    """سطر دفع في الفاتورة المقسّمة (نقدًا + فيزا/محفظة في نفس الفاتورة)."""
    method: PaymentMethod = "cash"
    amount: Decimal = Field(gt=0)
    safe_id: Optional[int] = None
    bank_id: Optional[int] = None


class PosCheckout(BaseModel):  # type: ignore
    warehouse_id: int
    items: List[PosItem] = Field(min_length=1)
    customer_id: Optional[int] = None  # default: the shared "walk-in" customer
    rep_id: Optional[int] = None  # مندوب المبيعات المسجل على الفاتورة
    pay_now: bool = True  # False = sale on the customer's account (needs customer_id)
    method: PaymentMethod = "cash"
    amount_paid: Optional[Decimal] = Field(default=None, ge=0)
    safe_id: Optional[int] = None
    bank_id: Optional[int] = None
    payments: Optional[List[PosPaymentLeg]] = Field(default=None, max_length=4,
        description="دفع مقسّم: مجموع الأسطر = المدفوع. إن حُدد تتجاهل method/amount_paid/safe/bank المفردة")
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, description="ضريبة القيمة المضافة %")
    notes: Optional[str] = None


class PosReceiptLine(BaseModel):
    name: str
    sku: str
    quantity: float
    unit_price: Decimal
    total: Decimal


class PosReceipt(BaseModel):  # type: ignore
    order_id: int
    payment_id: Optional[int]
    total: Decimal
    paid: bool
    customer_name: str
    method: Optional[str]
    created_at: datetime
    cashier: str
    lines: List[PosReceiptLine]


class PosInfo(BaseModel):
    company_name: str
    company_phone: str
    company_address: str
    currency: str


# ---------- Point of sale ----------
class PosCheckout(BaseModel):
    warehouse_id: int
    customer_id: Optional[int] = Field(default=None, description="Omit for a walk-in cash customer (must pay in full).")
    rep_id: Optional[int] = Field(default=None, description="مندوب المبيعات المسجل على الفاتورة.")
    items: List[SalesItemIn] = Field(min_length=1)
    amount_paid: Optional[Decimal] = Field(default=None, ge=0, description="Defaults to the full total.")
    method: PaymentMethod = "cash"
    safe_id: Optional[int] = Field(default=None, description="الخزنة التي تستقبل النقدية (تُقيّد تلقائيًا).")
    bank_id: Optional[int] = Field(default=None, description="الحساب البنكي الذي يستقبل المبلغ (بديل الخزنة).")
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, description="ضريبة القيمة المضافة %")
    payments: Optional[List[PosPaymentLeg]] = Field(default=None, max_length=4,
        description="دفع مقسّم: مجموع الأسطر = المدفوع (تتجاهل method/amount_paid/safe/bank المفردة)")
    notes: Optional[str] = None


class PosReceipt(BaseModel):
    order_id: int
    customer_id: int
    customer_name: str
    total: Decimal
    paid: Decimal
    balance_due: Decimal
    payment_id: Optional[int] = None


# ---------- Returns ----------
class ReturnItemIn(BaseModel):
    order_item_id: Optional[int] = None
    product_id: Optional[int] = None  # required when the return is not tied to an order line
    quantity: float = Field(gt=0)
    unit_price: Optional[Decimal] = Field(default=None, ge=0, description="Used for order-less returns; defaults to the product's sale/cost price")


class ReturnCreate(BaseModel):
    order_id: Optional[int] = None  # when omitted the return is standalone (pick products directly)
    customer_id: Optional[int] = None  # optional party for standalone sales returns
    supplier_id: Optional[int] = None  # optional party for standalone purchase returns
    warehouse_id: Optional[int] = None  # required for standalone returns
    rep_id: Optional[int] = None  # مندوب المبيعات (مرتجع البيع)
    items: List[ReturnItemIn] = Field(min_length=1)
    refund_amount: Decimal = Field(default=Decimal("0"), ge=0, description="Cash exchanged now; the rest changes the balance.")
    method: PaymentMethod = "cash"
    notes: Optional[str] = None


class ReturnItemOut(ORMModel):
    id: int
    order_item_id: Optional[int] = None  # NULL for standalone returns (no original order line)
    product_id: int
    product_name: Optional[str] = None
    quantity: float
    unit_price: Decimal


class ReturnOut(ORMModel):
    id: int
    kind: str  # sales | purchase
    order_id: Optional[int] = None
    party_id: Optional[int] = None
    party_name: Optional[str] = None
    warehouse_id: int
    rep_id: Optional[int] = None
    rep_name: Optional[str] = None
    total_amount: Decimal
    refund_amount: Decimal
    method: str
    notes: Optional[str] = None
    created_at: datetime
    items: List[ReturnItemOut]


# ---------- Cashier shifts ----------
class ShiftOpen(BaseModel):
    opening_cash: Decimal = Field(default=Decimal("0"), ge=0, description="Cash already in the drawer.")


class ShiftClose(BaseModel):
    counted_cash: Decimal = Field(ge=0, description="Cash actually counted in the drawer.")
    notes: Optional[str] = None


class ShiftOut(BaseModel):
    id: int
    user_id: int
    username: str
    status: str
    opened_at: datetime
    closed_at: Optional[datetime] = None
    opening_cash: Decimal
    cash_in: Decimal = Decimal("0")  # cash receipts from customers
    cash_out: Decimal = Decimal("0")  # cash payments to suppliers
    cash_refunds_in: Decimal = Decimal("0")  # cash received back from suppliers for purchase returns
    cash_refunds_out: Decimal = Decimal("0")  # cash handed back to customers for sales returns
    other_methods_in: Decimal = Decimal("0")  # bank / wallet / cheque receipts (not in the drawer)
    expected_cash: Decimal = Decimal("0")
    counted_cash: Optional[Decimal] = None
    difference: Optional[Decimal] = None  # counted - expected; negative = shortage
    notes: Optional[str] = None
    is_stale: bool = False  # still open long after it should have been closed


# ---------- Stock-take ----------
class StocktakeCreate(BaseModel):
    warehouse_id: int
    notes: Optional[str] = None


class StocktakeCount(BaseModel):
    product_id: int
    counted_qty: Optional[float] = Field(default=None, ge=0, description="null clears the count — كميات عشرية مسموحة (0.5 كجم)")


class StocktakeAddLine(BaseModel):
    product_id: int


class StocktakeCounts(BaseModel):
    counts: List[StocktakeCount] = Field(min_length=1, max_length=2000)


class StocktakeLineOut(ORMModel):
    product_id: int
    sku: Optional[str] = None
    product_name: Optional[str] = None
    system_qty: float
    counted_qty: Optional[float] = None
    difference: Optional[float] = None


class StocktakeOut(BaseModel):
    id: int
    status: str
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    notes: Optional[str] = None
    username: Optional[str] = None
    created_at: datetime
    applied_at: Optional[datetime] = None
    lines_total: int
    lines_counted: int
    lines_with_difference: int
    lines: Optional[List[StocktakeLineOut]] = None  # only in the detail view


# ---------- Warehouse transfers ----------
class TransferItemIn(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)


class TransferCreate(BaseModel):
    from_warehouse_id: int
    to_warehouse_id: int
    notes: Optional[str] = None
    valuation: Optional[str] = "cost"  # cost / sale
    items: List[TransferItemIn] = Field(min_length=1, max_length=500)


class TransferItemOut(ORMModel):
    product_id: int
    sku: Optional[str] = None
    product_name: Optional[str] = None
    quantity: float


class TransferOut(ORMModel):
    id: int
    from_warehouse_id: int
    from_warehouse_name: Optional[str] = None
    to_warehouse_id: int
    to_warehouse_name: Optional[str] = None
    notes: Optional[str] = None
    status: str = "pending"
    valuation: str = "cost"
    username: Optional[str] = None
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    items: List[TransferItemOut]


# ---------- Chart of Accounts ----------
class ChartAccountBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50)
    type: Literal["asset", "liability", "equity", "revenue", "expense"]
    is_group: bool = False
    requires_cost_center: bool = False
    is_active: bool = True

class ChartAccountCreate(ChartAccountBase):
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    parent_id: Optional[int] = None

class ChartAccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    type: Optional[Literal["asset", "liability", "equity", "revenue", "expense"]] = None
    is_group: Optional[bool] = None
    requires_cost_center: Optional[bool] = None
    parent_id: Optional[int] = None
    is_active: Optional[bool] = None

class ChartAccountOut(ChartAccountBase, ORMModel):
    id: int
    parent_id: Optional[int]
    balance: Decimal
    created_at: datetime

# ---------- Cost Centers ----------
class CostCenterBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50)
    is_active: bool = True

class CostCenterCreate(CostCenterBase):
    pass

class CostCenterUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    is_active: Optional[bool] = None

class CostCenterOut(CostCenterBase, ORMModel):
    id: int
    created_at: datetime

# ---------- CRM (العملاء المحتملون) ----------
LeadSource = Literal["walk_in", "phone", "social", "referral", "exhibition", "other"]
LeadStatus = Literal["new", "contacted", "qualified", "won", "lost"]
ActivityKind = Literal["note", "call", "meeting"]


class CrmLeadBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    company_name: Optional[str] = Field(default=None, max_length=150)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=150)
    address: Optional[str] = None
    source: LeadSource = "walk_in"
    status: LeadStatus = "new"
    expected_value: Decimal = Field(default=Decimal("0"), ge=0)
    assigned_rep_id: Optional[int] = None
    notes: Optional[str] = None


class CrmLeadCreate(CrmLeadBase):
    code: Optional[str] = Field(default=None, max_length=50)


class CrmLeadUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    company_name: Optional[str] = Field(default=None, max_length=150)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=150)
    address: Optional[str] = None
    source: Optional[LeadSource] = None
    status: Optional[LeadStatus] = None
    expected_value: Optional[Decimal] = Field(default=None, ge=0)
    assigned_rep_id: Optional[int] = None
    notes: Optional[str] = None


class CrmLeadOut(CrmLeadBase, ORMModel):
    id: int
    code: str
    converted_customer_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class CrmActivityCreate(BaseModel):
    kind: ActivityKind = "note"
    body: str = Field(min_length=1)


class CrmActivityOut(ORMModel):
    id: int
    lead_id: int
    kind: ActivityKind
    body: str
    created_by: Optional[int] = None
    created_at: datetime

# ---------- Fiscal Years ----------
class FiscalYearBase(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    start_date: date
    end_date: date
    is_closed: bool = False

class FiscalYearCreate(FiscalYearBase):
    pass

class FiscalYearUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_closed: Optional[bool] = None

class FiscalYearOut(FiscalYearBase, ORMModel):
    id: int
    created_at: datetime

# ---------- Journal Entries ----------
class JournalItemBase(BaseModel):
    account_id: int
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)
    cost_center_id: Optional[int] = None
    notes: Optional[str] = None

class JournalItemCreate(JournalItemBase):
    pass

class JournalItemOut(JournalItemBase, ORMModel):
    id: int
    account_name: Optional[str] = None

class JournalEntryBase(BaseModel):
    # NOTE: annotated with the `_date` alias — under pydantic 2.14 a field named `date`
    # with `Optional[date]` resolves the annotation against the class namespace, where
    # the default (None) shadows the datetime import, silently making it None-only.
    date: Optional[_date] = None
    description: str = Field(min_length=1)
    reference: Optional[str] = None

class JournalEntryCreate(JournalEntryBase):
    items: List[JournalItemCreate] = Field(min_length=2)

    @model_validator(mode="after")
    def _check_balance(self):
        total_debit = sum(item.debit for item in self.items)
        total_credit = sum(item.credit for item in self.items)
        if total_debit != total_credit:
            raise ValueError(f"Journal entry must balance. Debit ({total_debit}) != Credit ({total_credit})")
        return self

class JournalEntryUpdate(BaseModel):
    date: Optional[_date] = None  # `_date` alias: see JournalEntryBase note
    description: Optional[str] = Field(default=None, min_length=1)
    reference: Optional[str] = None

class JournalEntryOut(JournalEntryBase, ORMModel):
    id: int
    company_id: int
    status: str = "posted"
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    created_by: Optional[int]
    created_at: datetime
    items: List[JournalItemOut]

# ---------- Fixed Assets ----------
class FixedAssetBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50)
    asset_type: str = Field(min_length=1, max_length=50)
    purchase_date: date
    cost: Decimal = Field(ge=0)
    accumulated_depreciation: Decimal = Field(default=Decimal("0"), ge=0)
    current_book_value: Decimal = Field(ge=0)
    depreciation_method: str = Field(min_length=1, max_length=50)
    useful_life_years: int = Field(ge=0)
    salvage_value: Decimal = Field(default=Decimal("0"), ge=0)
    is_active: bool = True

class FixedAssetCreate(FixedAssetBase):
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)

class FixedAssetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    asset_type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    purchase_date: Optional[date] = None
    cost: Optional[Decimal] = Field(default=None, ge=0)
    accumulated_depreciation: Optional[Decimal] = Field(default=None, ge=0)
    current_book_value: Optional[Decimal] = Field(default=None, ge=0)
    depreciation_method: Optional[str] = Field(default=None, min_length=1, max_length=50)
    useful_life_years: Optional[int] = Field(default=None, ge=0)
    salvage_value: Optional[Decimal] = Field(default=None, ge=0)
    is_active: Optional[bool] = None

class FixedAssetOut(FixedAssetBase, ORMModel):
    id: int
    company_id: int
    created_at: datetime


class FixedAssetDepreciateIn(BaseModel):
    amount: Decimal = Field(gt=0)
    date: Optional[date] = None


class FixedAssetDisposeIn(BaseModel):
    disposal_proceeds: Decimal = Field(default=Decimal("0"), ge=0)
    safe_id: Optional[int] = None
    bank_id: Optional[int] = None
    date: Optional[date] = None

# ---------- General Ledger ----------
class LedgerEntryOut(BaseModel):
    date: date
    description: str
    reference: Optional[str]
    account_code: str
    account_name: str
    account_type: str
    debit: Decimal
    credit: Decimal
    cost_center: Optional[str]
    notes: Optional[str]

    @classmethod
    def from_journal_item(cls, je, ji) -> "LedgerEntryOut":
        account = ji.account
        cc = ji.cost_center
        return cls(
            date=je.date,
            description=je.description,
            reference=je.reference,
            account_code=account.code,
            account_name=account.name,
            account_type=account.type,
            debit=ji.debit,
            credit=ji.credit,
            cost_center=cc.code if cc else None,
            notes=ji.notes,
        )


# ---------- الموارد البشرية (HR) ----------
_EMPLOYEE_STATUSES = ("active", "probation", "suspended", "terminated")
_CONTRACT_KINDS = ("unlimited", "fixed", "temp", "part_time")
_CONTRACT_STATUSES = ("active", "expired", "terminated")
_MOVE_TYPES = ("hire", "promotion", "transfer", "salary_change", "status_change", "termination")
_DOC_TYPES = ("contract", "certificate", "id", "visa", "other")
_GENDERS = ("male", "female")

EmployeeStatus = Literal[_EMPLOYEE_STATUSES]  # type: ignore[valid-type]


class HrJobTitleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = None
    min_salary: Optional[Decimal] = Field(default=None, ge=0)
    max_salary: Optional[Decimal] = Field(default=None, ge=0)
    is_active: bool = True


class HrJobTitleOut(ORMModel):
    id: int
    company_id: int
    name: str
    description: Optional[str] = None
    min_salary: Optional[Decimal] = None
    max_salary: Optional[Decimal] = None
    is_active: bool
    created_at: datetime


class HrGradeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    min_salary: Optional[Decimal] = Field(default=None, ge=0)
    max_salary: Optional[Decimal] = Field(default=None, ge=0)
    is_active: bool = True


class HrGradeOut(ORMModel):
    id: int
    company_id: int
    name: str
    min_salary: Optional[Decimal] = None
    max_salary: Optional[Decimal] = None
    is_active: bool
    created_at: datetime


class HrEmployeeCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    national_id: Optional[str] = Field(default=None, max_length=40)
    insurance_number: Optional[str] = Field(default=None, max_length=40)
    gender: Optional[Literal["male", "female"]] = None
    birth_date: Optional[date] = None
    nationality: Optional[str] = Field(default=None, max_length=80)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=150)
    address: Optional[str] = None
    department_id: Optional[int] = None
    job_title_id: Optional[int] = None
    grade_id: Optional[int] = None
    branch_id: Optional[int] = None
    manager_id: Optional[int] = None
    user_id: Optional[int] = None  # ربط اختياري بحساب دخول (خدمة الموظف ESS)
    hire_date: Optional[date] = None
    basic_salary: Optional[Decimal] = Field(default=None, ge=0)
    bank_account: Optional[str] = Field(default=None, max_length=60)
    status: EmployeeStatus = "active"
    notes: Optional[str] = None


class HrEmployeeUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    national_id: Optional[str] = Field(default=None, max_length=40)
    insurance_number: Optional[str] = Field(default=None, max_length=40)
    gender: Optional[Literal["male", "female"]] = None
    birth_date: Optional[date] = None
    nationality: Optional[str] = Field(default=None, max_length=80)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=150)
    address: Optional[str] = None
    department_id: Optional[int] = None
    job_title_id: Optional[int] = None
    grade_id: Optional[int] = None
    branch_id: Optional[int] = None
    manager_id: Optional[int] = None
    user_id: Optional[int] = None
    basic_salary: Optional[Decimal] = Field(default=None, ge=0)
    bank_account: Optional[str] = Field(default=None, max_length=60)
    status: Optional[EmployeeStatus] = None
    terminated_at: Optional[date] = None
    termination_reason: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class HrEmployeeOut(ORMModel):
    id: int
    company_id: int
    code: str
    full_name: str
    national_id: Optional[str] = None
    insurance_number: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    nationality: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    job_title_id: Optional[int] = None
    job_title_name: Optional[str] = None
    grade_id: Optional[int] = None
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None
    manager_id: Optional[int] = None
    manager_name: Optional[str] = None
    user_id: Optional[int] = None
    hire_date: date
    basic_salary: Optional[Decimal] = None
    bank_account: Optional[str] = None
    status: str
    terminated_at: Optional[date] = None
    termination_reason: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    contracts_count: int = 0
    created_at: datetime


class HrEmployeeDetailOut(HrEmployeeOut):
    contracts: List["HrContractOut"] = []
    documents: List["HrDocumentOut"] = []
    moves: List["HrEmployeeMoveOut"] = []


class HrContractCreate(BaseModel):
    kind: Literal["unlimited", "fixed", "temp", "part_time"] = "unlimited"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    basic_salary: Optional[Decimal] = Field(default=None, ge=0)
    status: Literal["active", "expired", "terminated"] = "active"
    notes: Optional[str] = None


class HrContractUpdate(BaseModel):
    kind: Optional[Literal["unlimited", "fixed", "temp", "part_time"]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    basic_salary: Optional[Decimal] = Field(default=None, ge=0)
    status: Optional[Literal["active", "expired", "terminated"]] = None
    notes: Optional[str] = None


class HrContractOut(ORMModel):
    id: int
    company_id: int
    employee_id: int
    code: str
    kind: str
    start_date: date
    end_date: Optional[date] = None
    basic_salary: Optional[Decimal] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime


class HrDocumentCreate(BaseModel):
    doc_type: Literal["contract", "certificate", "id", "visa", "other"] = "other"
    title: str = Field(min_length=1, max_length=200)
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    notes: Optional[str] = None


class HrDocumentOut(ORMModel):
    id: int
    company_id: int
    employee_id: int
    doc_type: str
    title: str
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    has_file: bool = False
    file_name: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class HrEmployeeMoveCreate(BaseModel):
    move_type: Literal["hire", "promotion", "transfer", "salary_change", "status_change", "termination"]
    effective_date: Optional[date] = None
    to_department_id: Optional[int] = None
    to_job_title_id: Optional[int] = None
    to_salary: Optional[Decimal] = Field(default=None, ge=0)
    new_status: Optional[EmployeeStatus] = None
    reason: Optional[str] = None


class HrEmployeeMoveOut(ORMModel):
    id: int
    company_id: int
    employee_id: int
    move_type: str
    effective_date: date
    to_department_id: Optional[int] = None
    to_department_name: Optional[str] = None
    to_job_title_id: Optional[int] = None
    to_job_title_name: Optional[str] = None
    from_salary: Optional[Decimal] = None
    to_salary: Optional[Decimal] = None
    reason: Optional[str] = None
    created_at: datetime


# ---------- HR — الوقت والإجازات (S2) ----------
_HHMM_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
_TIME_FIELD = Field(default=None, pattern=_HHMM_PATTERN)


class HrShiftCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    start_time: str = Field(pattern=_HHMM_PATTERN)
    end_time: str = Field(pattern=_HHMM_PATTERN)
    grace_minutes: int = Field(default=15, ge=0, le=240)
    cross_midnight: bool = False
    is_active: bool = True


class HrShiftOut(ORMModel):
    id: int
    company_id: int
    name: str
    start_time: str
    end_time: str
    grace_minutes: int
    cross_midnight: bool
    is_active: bool
    created_at: datetime


class HrShiftUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    grace_minutes: Optional[int] = Field(default=None, ge=0, le=240)
    cross_midnight: Optional[bool] = None
    is_active: Optional[bool] = None


class HrShiftAssignmentSet(BaseModel):
    """إسناد وردية لموظف؛ employee_id موجود → استبدال الوردية الحالية."""
    employee_id: int
    shift_id: Optional[int] = None  # None = إزالة الإسناد


class HrShiftAssignmentOut(ORMModel):
    id: int
    company_id: int
    employee_id: int
    employee_name: Optional[str] = None
    shift_id: int
    shift_name: Optional[str] = None
    created_at: datetime


class HrAttendanceCreate(BaseModel):
    employee_id: int
    work_date: date
    status: Literal["present", "late", "absent", "excused"] = "present"
    check_in: Optional[str] = _TIME_FIELD
    check_out: Optional[str] = _TIME_FIELD
    overtime_type: Optional[Literal["day", "night", "holiday"]] = "day"
    overtime_approved: bool = True
    notes: Optional[str] = None


class HrAttendanceUpdate(BaseModel):
    status: Optional[Literal["present", "late", "absent", "excused"]] = None
    check_in: Optional[str] = _TIME_FIELD
    check_out: Optional[str] = _TIME_FIELD
    overtime_type: Optional[Literal["day", "night", "holiday"]] = None
    overtime_approved: Optional[bool] = None
    notes: Optional[str] = None


class HrAttendanceOut(ORMModel):
    id: int
    company_id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    work_date: date
    status: str
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    late_minutes: int
    overtime_minutes: int
    overtime_type: Optional[str] = "day"
    overtime_approved: bool = True
    source: str
    notes: Optional[str] = None
    created_at: datetime


class BiometricDeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    device_model: Optional[str] = "ZKTeco"
    ip_address: str = Field(min_length=7, max_length=45)
    port: int = Field(default=4370, ge=1, le=65535)
    serial_number: Optional[str] = None
    comm_key: Optional[str] = "0"
    branch_id: Optional[int] = None
    is_active: bool = True


class BiometricDeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    device_model: Optional[str] = None
    ip_address: Optional[str] = Field(default=None, min_length=7, max_length=45)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    serial_number: Optional[str] = None
    comm_key: Optional[str] = None
    branch_id: Optional[int] = None
    is_active: Optional[bool] = None


class BiometricDeviceOut(ORMModel):
    id: int
    company_id: int
    name: str
    device_model: Optional[str] = None
    ip_address: str
    port: int
    serial_number: Optional[str] = None
    comm_key: Optional[str] = None
    branch_id: Optional[int] = None
    is_active: bool
    last_sync_at: Optional[datetime] = None
    last_status: str
    created_at: datetime


class BiometricPunchIn(BaseModel):
    employee_code: str
    timestamp: datetime
    punch_type: Optional[Literal["check_in", "check_out", "auto"]] = "auto"


class BiometricBatchPush(BaseModel):
    device_id: Optional[int] = None
    serial_number: Optional[str] = None
    punches: List[BiometricPunchIn]


class BiometricSyncSummary(BaseModel):
    device_id: Optional[int]
    total_received: int
    matched_punches: int
    attendance_records_created: int
    attendance_records_updated: int
    unmatched_employee_codes: List[str]


class HrHolidayCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    holiday_date: date
    notes: Optional[str] = None


class HrHolidayOut(ORMModel):
    id: int
    company_id: int
    name: str
    holiday_date: date
    notes: Optional[str] = None
    created_at: datetime


class HrLeaveTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    days_per_year: Decimal = Field(default=Decimal("0"), ge=0, le=3650)
    is_paid: bool = True
    carry_over_days: Decimal = Field(default=Decimal("0"), ge=0, le=365)
    is_active: bool = True


class HrLeaveTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    days_per_year: Optional[Decimal] = Field(default=None, ge=0, le=3650)
    is_paid: Optional[bool] = None
    carry_over_days: Optional[Decimal] = Field(default=None, ge=0, le=365)
    is_active: Optional[bool] = None


class HrLeaveTypeOut(ORMModel):
    id: int
    company_id: int
    name: str
    days_per_year: Decimal
    is_paid: bool
    carry_over_days: Decimal
    is_active: bool
    created_at: datetime


class HrLeaveRequestCreate(BaseModel):
    employee_id: int
    leave_type_id: int
    from_date: date
    to_date: date
    reason: Optional[str] = None


class HrLeaveDecision(BaseModel):
    decision_note: Optional[str] = None


class HrLeaveRequestOut(ORMModel):
    id: int
    approval_level: int = 0
    company_id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    leave_type_id: int
    leave_type_name: Optional[str] = None
    from_date: date
    to_date: date
    days: Decimal
    status: str
    reason: Optional[str] = None
    decision_note: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: datetime


class HrLeaveBalanceAdjust(BaseModel):
    """تعديل يدوي للرصيد (تسييب رصيد الأول من سنة مالية أو إضافة مفردات)."""
    entitled_days: Optional[Decimal] = Field(default=None, ge=0, le=3650)
    carried_days: Optional[Decimal] = Field(default=None, ge=0, le=365)


class HrLeaveBalanceOut(ORMModel):
    id: int
    company_id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    leave_type_id: int
    leave_type_name: Optional[str] = None
    year: int
    entitled_days: Decimal
    carried_days: Decimal
    used_days: Decimal
    remaining_days: Decimal


# ---------- HR — الرواتب (S3) ----------

_MONEY = Field(default=None, ge=0)


class HrSalaryComponentCreate(BaseModel):
    employee_id: int
    category: Literal["earning", "deduction"] = "earning"
    name: str = Field(min_length=1, max_length=100)
    amount_mode: Literal["fixed", "percent_of_base"] = "fixed"
    fixed_amount: Optional[Decimal] = Field(default=None, ge=0, le=10**12)
    percent_value: Optional[Decimal] = Field(default=None, ge=0, le=100)
    is_active: bool = True
    notes: Optional[str] = None


class HrSalaryComponentUpdate(BaseModel):
    category: Optional[Literal["earning", "deduction"]] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    amount_mode: Optional[Literal["fixed", "percent_of_base"]] = None
    fixed_amount: Optional[Decimal] = Field(default=None, ge=0, le=10**12)
    percent_value: Optional[Decimal] = Field(default=None, ge=0, le=100)
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class HrSalaryComponentOut(ORMModel):
    id: int
    company_id: int
    employee_id: int
    employee_name: Optional[str] = None
    category: str
    name: str
    amount_mode: str
    fixed_amount: Optional[Decimal] = None
    percent_value: Optional[Decimal] = None
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime


class HrPayrollRunCreate(BaseModel):
    year: int = Field(ge=2000, le=2999)
    month: int = Field(ge=1, le=12)
    note: Optional[str] = None


class HrPayrollRunPost(BaseModel):
    note: Optional[str] = None


class HrPayrollRunOut(ORMModel):
    id: int
    company_id: int
    year: int
    month: int
    status: str
    note: Optional[str] = None
    employees_count: int
    total_gross: Decimal
    total_deductions: Decimal
    total_net: Decimal
    journal_entry_id: Optional[int] = None
    posted_at: Optional[datetime] = None
    created_at: datetime


class HrPayslipLineOut(ORMModel):
    id: int
    company_id: int
    payslip_id: int
    category: str
    name: str
    amount: Decimal
    notes: Optional[str] = None


class HrPayslipOut(ORMModel):
    id: int
    company_id: int
    run_id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    base_salary: Decimal
    absent_days: int
    unpaid_leave_days: Decimal
    absence_deduction: Decimal
    total_earnings: Decimal
    total_deductions: Decimal
    net_pay: Decimal
    notes: Optional[str] = None


# ---------- HR — السلف والتسوية النهائية (S4) ----------

class HrAdvanceCreate(BaseModel):
    employee_id: int
    amount: Decimal = Field(gt=0, le=10**12)
    installments_count: int = Field(ge=1, le=240)
    start_year: int = Field(ge=2000, le=2999)
    start_month: int = Field(ge=1, le=12)
    notes: Optional[str] = None


class HrAdvanceUpdate(BaseModel):
    """تعليل/إستئناف/إلغاء السلفة فقط — القيمة والأقساط مقفلَتان للنفاذية المالية."""
    status: Literal["active", "completed", "cancelled"]
    notes: Optional[str] = None


class HrApprovalChainLevelIn(BaseModel):
    level: int = Field(gt=0)
    approver_user_id: Optional[int] = None
    approver_role: Optional[Literal["manager", "admin"]] = None


class HrApprovalChainLevelOut(BaseModel):
    level: int
    approver_user_id: Optional[int] = None
    approver_username: Optional[str] = None
    approver_role: Optional[str] = None


class HrApprovalLimitUserRow(BaseModel):
    id: int
    username: str


class HrApprovalChainPage(BaseModel):
    entity_type: str = "leave"
    levels: List[HrApprovalChainLevelOut] = []
    users: List[HrApprovalLimitUserRow] = []


class HrApprovalChainIn(BaseModel):
    levels: List[HrApprovalChainLevelIn] = []


class HrApprovalStepRow(BaseModel):
    level: int
    approver_username: Optional[str] = None
    decision: str
    notes: Optional[str] = None
    created_at: Optional[str] = None


class HrSalaryComponentBulkIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)  # اسم البند (مثل التأمينات الاجتماعية)
    category: Literal["earning", "deduction"] = "deduction"
    percent_value: Optional[float] = Field(default=None, ge=0, le=100)
    is_active: Optional[bool] = None


class HrSalaryComponentBulkOut(BaseModel):
    updated_count: int = 0


class HrSeedEgComponentsIn(BaseModel):
    employee_ids: Optional[List[int]] = None  # فارغ = كل الموظفين النشطين


class HrSeedEgComponentsOut(BaseModel):
    created_count: int = 0
    skipped_count: int = 0
    employees: int = 0


class HrApprovalLimitPage(BaseModel):
    limits: List["HrApprovalLimitOut"] = []
    users: List[HrApprovalLimitUserRow] = []


class HrApprovalLimitOut(ORMModel):
    user_id: int
    username: str
    max_amount: float


class HrApprovalLimitIn(BaseModel):
    max_amount: Optional[float] = None  # NULL = إلغاء الحد (غير محدود)


class HrAttendanceImportRowIn(BaseModel):
    employee_code: str = Field(min_length=1, max_length=50)
    work_date: date
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    status: Optional[Literal["present", "late", "absent", "excused"]] = None


class HrAttendanceImportIn(BaseModel):
    rows: List[HrAttendanceImportRowIn] = Field(min_length=1)


class HrAttendanceImportOut(BaseModel):
    created: int = 0
    updated: int = 0
    errors: List[str] = []


class HrAdvanceOut(ORMModel):
    id: int
    company_id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    amount: Decimal
    installments_count: int
    start_year: int
    start_month: int
    status: str
    notes: Optional[str] = None
    created_at: datetime


class HrSettlementCreate(BaseModel):
    note: Optional[str] = None


class HrOvertimeReview(BaseModel):
    approved: bool


class HrSettlementOut(ORMModel):
    id: int
    company_id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    status: str = "draft"
    journal_entry_id: Optional[int] = None
    termination_date: date
    service_days: int
    service_years: Decimal
    eosb_days: Decimal
    eosb_amount: Decimal
    unused_leave_days: Decimal
    unused_leave_amount: Decimal
    advances_remaining: Decimal
    total_due: Decimal
    note: Optional[str] = None
    created_at: datetime


# ---------- HR — الخدمة الذاتية للموظف (S5) ----------

class HrMeEmployeeOut(ORMModel):
    id: int
    code: str
    full_name: str
    department_name: Optional[str] = None
    job_title_name: Optional[str] = None
    branch_name: Optional[str] = None
    manager_name: Optional[str] = None
    hire_date: date
    status: str


class HrAttendanceCorrectionCreate(BaseModel):
    work_date: date
    requested_check_in: Optional[str] = _TIME_FIELD
    requested_check_out: Optional[str] = _TIME_FIELD
    reason: str = Field(min_length=5, max_length=1000)


class HrCorrectionDecision(BaseModel):
    decision_note: Optional[str] = None


class HrAttendanceCorrectionOut(ORMModel):
    id: int
    company_id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    work_date: date
    requested_check_in: Optional[str] = None
    requested_check_out: Optional[str] = None
    reason: str
    status: str
    decision_note: Optional[str] = None
    applied_attendance_id: Optional[int] = None
    decided_at: Optional[datetime] = None
    created_at: datetime


class HrMeLeaveRequestCreate(BaseModel):
    leave_type_id: int
    from_date: date
    to_date: date
    reason: Optional[str] = None


class HrMePayslipOut(ORMModel):
    id: int
    run_id: int
    year: int
    month: int
    run_status: str
    base_salary: Decimal
    total_earnings: Decimal
    total_deductions: Decimal
    net_pay: Decimal


# ---------- HR — التوظيف والأداء والتدريب (S6) ----------

ApplicantStage = Literal["applied", "screening", "interview", "offer", "hired", "rejected"]
PostingStatus = Literal["open", "on_hold", "closed", "filled"]
EmploymentType = Literal["full_time", "part_time", "contract", "internship"]


class HrJobPostingCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    department_id: Optional[int] = None
    branch_id: Optional[int] = None
    openings: int = Field(default=1, ge=1, le=100)
    employment_type: EmploymentType = "full_time"
    description: Optional[str] = None


class HrJobPostingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    department_id: Optional[int] = None
    branch_id: Optional[int] = None
    openings: Optional[int] = Field(default=None, ge=1, le=100)
    employment_type: Optional[EmploymentType] = None
    description: Optional[str] = None
    status: Optional[PostingStatus] = None


class HrJobPostingOut(ORMModel):
    id: int
    company_id: int
    code: str
    title: str
    department_name: Optional[str] = None
    branch_name: Optional[str] = None
    openings: int
    employment_type: str
    description: Optional[str] = None
    status: str
    hired_count: int
    closed_at: Optional[datetime] = None
    created_at: datetime


class HrApplicantCreate(BaseModel):
    full_name: str = Field(min_length=3, max_length=200)
    email: str = Field(min_length=5, max_length=150)
    phone: Optional[str] = Field(default=None, max_length=40)
    source: Optional[str] = Field(default=None, max_length=50)
    resume_text: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)


class HrApplicantUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=3, max_length=200)
    email: Optional[str] = Field(default=None, min_length=5, max_length=150)
    phone: Optional[str] = Field(default=None, max_length=40)
    source: Optional[str] = Field(default=None, max_length=50)
    resume_text: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    note: Optional[str] = None


class HrApplicantOut(ORMModel):
    id: int
    company_id: int
    posting_id: int
    posting_title: Optional[str] = None
    posting_code: Optional[str] = None
    full_name: str
    email: str
    phone: Optional[str] = None
    source: Optional[str] = None
    resume_text: Optional[str] = None
    stage: str
    rating: Optional[int] = None
    note: Optional[str] = None
    hired_employee_id: Optional[int] = None
    decided_at: Optional[datetime] = None
    created_at: datetime


class HrApplicantHire(BaseModel):
    """تحويل متقدم إلى موظف (اختياري — الملء الآلي إن لم يحدد)."""
    job_title_id: Optional[int] = None
    basic_salary: Optional[Decimal] = Field(default=None, ge=0)
    hire_date: Optional[date] = None


class HrReviewCycleCreate(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    period_start: date
    period_end: date


class HrReviewCycleOut(ORMModel):
    id: int
    company_id: int
    name: str
    period_start: date
    period_end: date
    status: str
    closed_at: Optional[datetime] = None
    created_at: datetime


class HrReviewCreate(BaseModel):
    employee_id: int
    quality: int = Field(ge=1, le=5)
    commitment: int = Field(ge=1, le=5)
    teamwork: int = Field(ge=1, le=5)
    initiative: int = Field(ge=1, le=5)
    comment: Optional[str] = None


class HrReviewUpdate(BaseModel):
    quality: Optional[int] = Field(default=None, ge=1, le=5)
    commitment: Optional[int] = Field(default=None, ge=1, le=5)
    teamwork: Optional[int] = Field(default=None, ge=1, le=5)
    initiative: Optional[int] = Field(default=None, ge=1, le=5)
    comment: Optional[str] = None


class HrReviewOut(ORMModel):
    id: int
    company_id: int
    cycle_id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    quality: int
    commitment: int
    teamwork: int
    initiative: int
    score: Decimal
    comment: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: datetime


class HrTrainingCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    provider: Optional[str] = Field(default=None, max_length=150)
    location: Optional[str] = Field(default=None, max_length=150)
    from_date: date
    to_date: date
    cost: Decimal = Field(default=Decimal("0"), ge=0)
    notes: Optional[str] = None


class HrTrainingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    provider: Optional[str] = Field(default=None, max_length=150)
    location: Optional[str] = Field(default=None, max_length=150)
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    cost: Optional[Decimal] = Field(default=None, ge=0)
    notes: Optional[str] = None


class HrTrainingOut(ORMModel):
    id: int
    company_id: int
    code: str
    title: str
    provider: Optional[str] = None
    location: Optional[str] = None
    from_date: date
    to_date: date
    cost: Decimal
    notes: Optional[str] = None
    enrollments_count: int = 0
    created_at: datetime


class HrEnrollmentCreate(BaseModel):
    employee_id: int


class HrEnrollmentOut(ORMModel):
    id: int
    company_id: int
    training_id: int
    training_title: Optional[str] = None
    employee_id: int
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    status: str
    completed_at: Optional[datetime] = None
    certificate_note: Optional[str] = None
    created_at: datetime


class HrEnrollmentDecision(BaseModel):
    certificate_note: Optional[str] = None


class HrAnalytics(BaseModel):
    """لوحة HR التحليلية — أرقام مجمعة للشهر/السنة الحالية."""
    attendance: dict
    leaves: dict
    turnover: dict
    payroll: dict
    recruiting: dict
    talent: dict


# ---------- Monthly fiscal periods ----------
class FiscalPeriodOut(ORMModel):
    id: int
    fiscal_year_id: int
    name: str
    start_date: date
    end_date: date
    is_closed: bool


# ---------- Recurring journals ----------
class RecurringJournalItemIn(BaseModel):
    account_id: int
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)
    cost_center_id: Optional[int] = None
    notes: Optional[str] = None


class RecurringJournalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(min_length=1)
    reference: Optional[str] = Field(default=None, max_length=100)
    day_of_month: int = Field(default=1, ge=1, le=28)
    next_run_date: date
    is_active: bool = True
    items: List[RecurringJournalItemIn] = Field(min_length=2)


class RecurringJournalUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    description: Optional[str] = None
    reference: Optional[str] = Field(default=None, max_length=100)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=28)
    next_run_date: Optional[date] = None
    is_active: Optional[bool] = None
    items: Optional[List[RecurringJournalItemIn]] = None


class RecurringJournalOut(ORMModel):
    id: int
    company_id: int
    name: str
    description: str
    reference: Optional[str] = None
    frequency: str
    day_of_month: int
    next_run_date: date
    is_active: bool
    items: list
    last_run_entry_id: Optional[int] = None
    created_at: datetime


# ---------- Attachments ----------
class AttachmentOut(ORMModel):
    id: int
    entity_type: str
    entity_id: int
    filename: str
    content_type: str
    size: int
    uploaded_by: Optional[int] = None
    created_at: datetime


# ---------- Bank statement reconciliation ----------
class BankStatementLineOut(ORMModel):
    id: int
    bank_id: int
    value_date: date
    description: str
    amount: Decimal
    reference: Optional[str] = None
    matched_payment_id: Optional[int] = None
    matched_payment_reference: Optional[str] = None


class BankStatementMatchIn(BaseModel):
    payment_id: Optional[int] = None  # None = unmatch


class BankReconciliationSummary(BaseModel):
    bank_id: int
    statement_balance: Decimal      # صافي الكشف المستورد
    ledger_balance: Decimal         # رصيد حساب البنك في الدفاتر
    matched_total: Decimal          # صافي السطور المطابقة
    unmatched_count: int
    difference: Decimal             # الكشف − الدفاتر


# ---------- الضرائب: أكواد الخصم والإضافة + ضريبة كسب العمل ----------
class WithholdingCodeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    is_active: Optional[bool] = None


class WithholdingCodeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    rate: Optional[Decimal] = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    is_active: Optional[bool] = None


class WithholdingCodeOut(ORMModel):
    id: int
    name: str
    rate: Decimal
    is_active: bool


class TaxBracketIn(BaseModel):
    min_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    max_amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    sort: int = 0


class PayrollTaxSettingsUpdate(BaseModel):
    personal_exemption: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    wage_reduction_percent: Optional[Decimal] = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    social_insurance_percent: Optional[Decimal] = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    brackets: Optional[List[TaxBracketIn]] = None


class SelfRegisterIn(BaseModel):
    """طلب تسجيل شركة ذاتي — محمي بمفتاح تشغيلي وليس بحساب."""
    company_name: str = Field(min_length=1, max_length=150)
    company_code: Optional[str] = Field(default=None, min_length=2, max_length=50)
    admin_username: str = Field(min_length=3, max_length=60)
    admin_password: str = Field(min_length=8, max_length=128)
    admin_full_name: Optional[str] = None
    registration_key: str = Field(min_length=1, max_length=128)

