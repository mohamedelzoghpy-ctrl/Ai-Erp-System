"""Pydantic (v2) schemas for request validation and responses."""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    pass


class SupplierUpdate(PartyUpdate):
    pass


class SupplierOut(PartyBase, ORMModel):
    id: int
    created_at: datetime
    balance: Decimal = Decimal("0")  # what we owe the supplier


class CustomerCreate(PartyBase):
    pass


class CustomerUpdate(PartyUpdate):
    pass


class CustomerOut(PartyBase, ORMModel):
    id: int
    created_at: datetime
    balance: Decimal = Decimal("0")  # what the customer owes us


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
    quantity: int = Field(default=0, ge=0)


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
    id: int
    quantity: int  # total over all warehouses
    warehouse_quantity: Optional[int] = None  # only when the list was asked for one warehouse (?stock_warehouse_id=)
    image_uploaded: bool = False
    created_at: datetime


class ProductStockOut(BaseModel):
    warehouse_id: int
    warehouse_name: str
    quantity: int


class StockAdjustment(BaseModel):
    change: int = Field(description="Positive to add stock, negative to remove.")
    reference: Optional[str] = None
    warehouse_id: Optional[int] = Field(default=None, description="Defaults to the product's own warehouse.")


class StockMovementOut(ORMModel):
    id: int
    product_id: int
    warehouse_id: Optional[int]
    change: int
    reason: str
    reference: Optional[str]
    created_at: datetime


# ---------- Purchase orders ----------
class PurchaseItemIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)


class PurchaseItemOut(PurchaseItemIn, ORMModel):
    id: int
    product_name: Optional[str] = None
    returned_quantity: int = 0


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    notes: Optional[str] = None
    payment_mode: Literal["cash", "credit"] = "credit"
    safe_id: Optional[int] = None
    discount_mode: Literal["amount", "percent"] = "amount"
    discount_value: Decimal = Field(default=Decimal("0"), ge=0)
    tax_rate: Decimal = Field(default=Decimal("14"), ge=0, le=100)
    items: List[PurchaseItemIn] = Field(min_length=1)


class PurchaseOrderOut(ORMModel):
    id: int
    supplier_id: int
    party_name: Optional[str] = None
    warehouse_id: int
    status: str
    notes: Optional[str]
    total_amount: Decimal
    created_at: datetime
    items: List[PurchaseItemOut]
    paid_amount: Optional[Decimal] = None
    balance_due: Optional[Decimal] = None
    payment_status: Optional[str] = None  # paid | partial | unpaid (None while draft/cancelled)


# ---------- Sales orders ----------
class SalesItemIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    unit_price: Optional[Decimal] = Field(
        default=None, ge=0, description="Defaults to the product's current sale price."
    )


class SalesItemOut(ORMModel):
    id: int
    product_id: int
    quantity: int
    unit_price: Decimal
    product_name: Optional[str] = None
    returned_quantity: int = 0


class SalesOrderCreate(BaseModel):
    customer_id: int
    warehouse_id: int
    notes: Optional[str] = None
    rep_id: Optional[int] = None  # مندوب المبيعات المسجل على الفاتورة
    safe_id: Optional[int] = None  # اسم الخزينة المقترحة لتحصيل الفاتورة
    items: List[SalesItemIn] = Field(min_length=1)


class SalesOrderOut(ORMModel):
    id: int
    customer_id: int
    party_name: Optional[str] = None
    warehouse_id: int
    status: str
    notes: Optional[str]
    rep_id: Optional[int] = None
    rep_name: Optional[str] = None
    safe_id: Optional[int] = None
    safe_name: Optional[str] = None
    total_amount: Decimal
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
    is_active: Optional[bool] = None


class CompanyOut(ORMModel):
    id: int
    name: str
    code: str
    max_warehouses_per_branch: Optional[int]
    max_safes_per_branch: Optional[int]
    max_branches: Optional[int] = None
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


# ---------- Reports ----------
class LowStockItem(ORMModel):
    id: int
    sku: str
    name: str
    quantity: int
    reorder_level: int
    shortfall: int
    image_url: Optional[str] = None
    image_uploaded: bool = False
    supplier_name: Optional[str] = None
    warehouse_id: Optional[int]
    supplier_id: Optional[int]


class InventoryValuationRow(BaseModel):
    warehouse_id: Optional[int]
    warehouse_name: Optional[str]
    products: int
    units: int
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
    quantity: int
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
    quantity_sold: int
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
    quantity_bought: int
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

class BomItemIn(BaseModel):
    component_id: int
    qty_per_output: Decimal = Field(gt=0, max_digits=12, decimal_places=3)  # كمية المكوّن لكل وحدة ناتجة
    scrap_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=5, decimal_places=2)
    notes: Optional[str] = Field(default=None, max_length=200)


class BomCreate(BaseModel):
    product_id: int
    version: str = Field(default="v1", max_length=20)
    output_qty: int = Field(default=1, ge=1)  # الكمية الناتجة من القائمة
    is_active: bool = True
    notes: Optional[str] = None
    items: List[BomItemIn] = []


class BomItemOut(ORMModel):
    id: int
    component_id: int
    component_name: Optional[str] = None
    component_code: Optional[str] = None
    component_unit: Optional[str] = None
    qty_per_output: Decimal
    scrap_pct: Decimal
    notes: Optional[str] = None


class BomOut(ORMModel):
    id: int
    product_id: int
    product_name: Optional[str] = None
    version: str
    output_qty: int
    is_active: bool
    notes: Optional[str] = None
    items: List[BomItemOut] = []
    created_at: datetime


class ProductionOrderCreate(BaseModel):
    product_id: int
    bom_id: Optional[int] = None  # auto-picks the active BOM when omitted
    qty_planned: int = Field(ge=1)
    raw_warehouse_id: int
    output_warehouse_id: int
    subcontractor_id: Optional[int] = None  # مورد التصنيع الخارجي (اختياري)
    production_line: Optional[str] = Field(default=None, max_length=100)  # خط الإنتاج
    scheduled_date: Optional[date] = None
    notes: Optional[str] = None


class ProductionConsumptionOut(ORMModel):
    component_id: int
    component_name: Optional[str] = None
    component_unit: Optional[str] = None
    qty: int
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
    qty_planned: int
    qty_produced: int
    status: str
    raw_warehouse_id: int
    raw_warehouse_name: Optional[str] = None
    output_warehouse_id: int
    output_warehouse_name: Optional[str] = None
    subcontractor_id: Optional[int] = None
    subcontractor_name: Optional[str] = None
    production_line_id: Optional[int] = None
    production_line_name: Optional[str] = None
    scheduled_date: Optional[date] = None
    is_late: Optional[bool] = None
    qty_scrapped: int = 0
    notes: Optional[str] = None
    consumptions: List[ProductionConsumptionOut] = []
    costs: List[ProductionCostOut] = []
    costs_total: Decimal = Decimal("0")
    batches: List["ProductionBatchOut"] = []
    children: List["ProductionChildOut"] = []
    created_at: datetime


class ProductionBatchOut(ORMModel):
    id: int
    batch_no: str
    qty: int
    cost: Decimal
    qc_status: Literal["pending", "passed", "rejected"]
    produced_at: datetime
    notes: Optional[str] = None


class ProductionChildOut(ORMModel):
    id: int
    code: str
    product_id: int
    product_name: Optional[str] = None
    qty_planned: int
    status: str


class BatchQcIn(BaseModel):
    result: Literal["passed", "rejected"]


class ProductionLineIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    capacity_per_hour: Optional[int] = Field(default=None, ge=1)
    hourly_cost: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)


class ProductionLineOut(ORMModel):
    id: int
    name: str
    capacity_per_hour: Optional[int] = None
    hourly_cost: Optional[Decimal] = None
    is_active: bool
    created_at: datetime


class ManufacturingReportLine(BaseModel):
    order_id: int
    code: str
    product_name: Optional[str] = None
    qty_planned: int
    qty_produced: int
    materials: Decimal
    costs: Decimal
    total: Decimal
    unit_cost: Decimal
    variance: Decimal


class ManufacturingByProduct(BaseModel):
    product_id: int
    product_name: Optional[str] = None
    orders: int
    qty_produced: int
    total: Decimal


class ManufacturingReportOut(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    lines: List[ManufacturingReportLine]
    total_orders: int
    total_qty_produced: int
    total_materials: Decimal
    total_costs: Decimal
    total: Decimal
    total_variance: Decimal
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


class ProductionProduceIn(BaseModel):
    qty: int = Field(ge=1)  # كمية الدفعة المنتجة


class ProductionScrapIn(BaseModel):
    qty: int = Field(ge=1)  # كمية الهالك
    notes: Optional[str] = Field(default=None, max_length=200)


class WipOrderOut(BaseModel):
    id: int
    code: str
    product_id: int
    product_name: Optional[str] = None
    qty_planned: int
    qty_produced: int
    remaining: int
    materials: Decimal
    costs: Decimal
    wip_value: Decimal
    unit_cost: Decimal
    scheduled_date: Optional[date] = None


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
    quantity: int = Field(gt=0)


class PosCheckout(BaseModel):  # type: ignore
    warehouse_id: int
    items: List[PosItem] = Field(min_length=1)
    customer_id: Optional[int] = None  # default: the shared "walk-in" customer
    rep_id: Optional[int] = None  # مندوب المبيعات المسجل على الفاتورة
    pay_now: bool = True  # False = sale on the customer's account (needs customer_id)
    method: PaymentMethod = "cash"
    notes: Optional[str] = None


class PosReceiptLine(BaseModel):
    name: str
    sku: str
    quantity: int
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
    quantity: int = Field(gt=0)
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
    quantity: int
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
    counted_qty: Optional[int] = Field(default=None, ge=0, description="null clears the count")


class StocktakeAddLine(BaseModel):
    product_id: int


class StocktakeCounts(BaseModel):
    counts: List[StocktakeCount] = Field(min_length=1, max_length=2000)


class StocktakeLineOut(ORMModel):
    product_id: int
    sku: Optional[str] = None
    product_name: Optional[str] = None
    system_qty: int
    counted_qty: Optional[int] = None
    difference: Optional[int] = None


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
    quantity: int = Field(gt=0)


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
    quantity: int


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
    is_active: bool = True

class ChartAccountCreate(ChartAccountBase):
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    parent_id: Optional[int] = None

class ChartAccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    type: Optional[Literal["asset", "liability", "equity", "revenue", "expense"]] = None
    is_group: Optional[bool] = None
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
    date: Optional[date] = None
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
    date: Optional[date] = None
    description: Optional[str] = Field(default=None, min_length=1)
    reference: Optional[str] = None

class JournalEntryOut(JournalEntryBase, ORMModel):
    id: int
    company_id: int
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
