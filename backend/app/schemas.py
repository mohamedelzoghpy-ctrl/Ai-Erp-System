"""Pydantic (v2) schemas for request validation and responses."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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


class PartyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None


class SupplierCreate(PartyBase):
    pass


class SupplierUpdate(PartyUpdate):
    pass


class SupplierOut(PartyBase, ORMModel):
    id: int
    created_at: datetime


class CustomerCreate(PartyBase):
    pass


class CustomerUpdate(PartyUpdate):
    pass


class CustomerOut(PartyBase, ORMModel):
    id: int
    created_at: datetime


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


class ProductCreate(ProductBase):
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
    unit_cost: Decimal = Field(ge=0)


class PurchaseItemOut(PurchaseItemIn, ORMModel):
    id: int


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    notes: Optional[str] = None
    items: List[PurchaseItemIn] = Field(min_length=1)


class PurchaseOrderOut(ORMModel):
    id: int
    supplier_id: int
    warehouse_id: int
    status: str
    notes: Optional[str]
    total_amount: Decimal
    created_at: datetime
    items: List[PurchaseItemOut]


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


class SalesOrderCreate(BaseModel):
    customer_id: int
    warehouse_id: int
    notes: Optional[str] = None
    items: List[SalesItemIn] = Field(min_length=1)


class SalesOrderOut(ORMModel):
    id: int
    customer_id: int
    warehouse_id: int
    status: str
    notes: Optional[str]
    total_amount: Decimal
    created_at: datetime
    items: List[SalesItemOut]
