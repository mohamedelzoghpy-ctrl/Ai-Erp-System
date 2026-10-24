"""Pydantic (v2) schemas for request validation and responses."""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _reject_explicit_nulls(model: BaseModel, *fields: str) -> BaseModel:
    invalid = [name for name in fields if name in model.model_fields_set and getattr(model, name) is None]
    if invalid:
        raise ValueError(f"{', '.join(invalid)} cannot be null")
    return model


# ---------- Warehouses ----------
class WarehouseBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50)
    location: Optional[str] = None
    is_active: bool = True


class WarehouseCreate(WarehouseBase):
    pass


class WarehouseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    location: Optional[str] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def _validate_non_nullable_fields(self):
        return _reject_explicit_nulls(self, "name", "code", "is_active")


class WarehouseOut(WarehouseBase, ORMModel):
    id: int
    created_at: datetime


# ---------- Suppliers / Customers (same shape) ----------
class PartyBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    is_active: bool = True
    opening_balance: Decimal = Field(default=Decimal("0"), max_digits=14, decimal_places=2)


class PartyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None
    opening_balance: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)

    @model_validator(mode="after")
    def _validate_non_nullable_fields(self):
        return _reject_explicit_nulls(self, "name", "is_active", "opening_balance")


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
    cost_price: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    sale_price: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    reorder_level: int = Field(default=0, ge=0)
    is_active: bool = True
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None


class ProductCreate(ProductBase):
    # Opening balance only; afterwards quantity changes via purchases/sales/adjustments.
    quantity: int = Field(default=0, ge=0)


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    unit: Optional[str] = None
    cost_price: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    sale_price: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    reorder_level: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None

    @model_validator(mode="after")
    def _validate_non_nullable_fields(self):
        return _reject_explicit_nulls(
            self, "name", "unit", "cost_price", "sale_price", "reorder_level", "is_active"
        )


class ProductOut(ProductBase, ORMModel):
    id: int
    quantity: int
    created_at: datetime


class StockAdjustment(BaseModel):
    change: int = Field(description="Positive to add stock, negative to remove.")
    reference: Optional[str] = None


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
    unit_cost: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class PurchaseItemOut(PurchaseItemIn, ORMModel):
    id: int
    product_name: Optional[str] = None
    returned_quantity: int = 0


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    notes: Optional[str] = None
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
        default=None, ge=0, max_digits=12, decimal_places=2, description="Defaults to the product's current sale price."
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
    items: List[SalesItemIn] = Field(min_length=1)


class SalesOrderOut(ORMModel):
    id: int
    customer_id: int
    party_name: Optional[str] = None
    warehouse_id: int
    status: str
    notes: Optional[str]
    total_amount: Decimal
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


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[Role] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def _validate_non_nullable_fields(self):
        return _reject_explicit_nulls(self, "role", "is_active", "password")


class UserOut(ORMModel):
    id: int
    username: str
    full_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime


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


class SalesSummary(BaseModel):
    date_from: datetime
    date_to: datetime
    orders: int
    total: Decimal
    by_day: List[SalesByDay]
    top_products: List[TopProduct]
    by_customer: List[SalesByCustomer] = []


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


# ---------- Payments & statements ----------
PaymentMethod = Literal["cash", "bank", "wallet", "cheque"]


class PaymentCreate(BaseModel):
    customer_id: Optional[int] = None  # money received from this customer
    supplier_id: Optional[int] = None  # money paid to this supplier
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    method: PaymentMethod = "cash"
    reference: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None
    paid_on: Optional[date] = None  # defaults to today

    @model_validator(mode="after")
    def _exactly_one_party(self):
        if (self.customer_id is None) == (self.supplier_id is None):
            raise ValueError("Provide exactly one of customer_id or supplier_id")
        return self


class PaymentOut(ORMModel):
    id: int
    kind: Literal["receipt", "payment"]
    customer_id: Optional[int]
    supplier_id: Optional[int]
    party_name: Optional[str] = None
    amount: Decimal
    method: str
    reference: Optional[str]
    notes: Optional[str]
    paid_on: date
    status: str
    created_at: datetime


Day = date  # alias: a field called `date` must not shadow its own type annotation


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


# ---------- Point of sale ----------
class PosItem(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)


class PosCheckout(BaseModel):
    warehouse_id: int
    items: List[PosItem] = Field(min_length=1)
    customer_id: Optional[int] = None  # default: the shared "walk-in" customer
    pay_now: bool = True  # False = sale on the customer's account (needs customer_id)
    method: PaymentMethod = "cash"
    notes: Optional[str] = None


class PosReceiptLine(BaseModel):
    name: str
    sku: str
    quantity: int
    unit_price: Decimal
    total: Decimal


class PosReceipt(BaseModel):
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
    items: List[SalesItemIn] = Field(min_length=1)
    amount_paid: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2, description="Defaults to the full total.")
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
    order_item_id: int
    quantity: int = Field(gt=0)


class ReturnCreate(BaseModel):
    order_id: int
    items: List[ReturnItemIn] = Field(min_length=1)
    refund_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2, description="Cash exchanged now; the rest changes the balance.")
    method: PaymentMethod = "cash"
    notes: Optional[str] = None


class ReturnItemOut(ORMModel):
    id: int
    order_item_id: int
    product_id: int
    product_name: Optional[str] = None
    quantity: int
    unit_price: Decimal


class ReturnOut(ORMModel):
    id: int
    kind: str  # sales | purchase
    order_id: int
    party_id: int
    party_name: Optional[str] = None
    warehouse_id: int
    total_amount: Decimal
    refund_amount: Decimal
    method: str
    notes: Optional[str] = None
    created_at: datetime
    items: List[ReturnItemOut]
