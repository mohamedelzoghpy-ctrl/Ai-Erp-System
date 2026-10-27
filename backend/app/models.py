"""SQLAlchemy models for the ERP: inventory, orders, parties, payments and users."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Index,
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
        CheckConstraint(
            "max_warehouses_per_branch IS NULL OR max_warehouses_per_branch > 0",
            name="ck_company_warehouse_limit_positive",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False, unique=True, index=True)
    max_warehouses_per_branch = Column(Integer, nullable=True)
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

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    contact_person = Column(String(150), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    # What the party owed / was owed before this system was used (negative = credit in their favour).
    opening_balance = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    products = relationship("Product", back_populates="supplier")


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
    quantity = Column(Integer, nullable=False, default=0, server_default="0")
    reorder_level = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    warehouse = relationship("Warehouse", back_populates="products")
    supplier = relationship("Supplier", back_populates="products")


class Customer(TenantOwned, Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    contact_person = Column(String(150), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    # What the party owed / was owed before this system was used (negative = credit in their favour).
    opening_balance = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    sales_orders = relationship("SalesOrder", back_populates="customer")


class PurchaseOrder(TenantOwned, Base):
    """Order placed with a supplier. Stock increases when status becomes 'received'."""

    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="draft", server_default="draft", index=True)
    notes = Column(Text, nullable=True)
    total_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
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


class PurchaseOrderItem(TenantOwned, Base):
    __tablename__ = "purchase_order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
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
    total_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # NULL for orders made before this was recorded
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    customer = relationship("Customer", back_populates="sales_orders")
    warehouse = relationship("Warehouse")
    creator = relationship("User", foreign_keys=[created_by])

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
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    # Product cost at the time of sale, so profit reports don't change when the cost price is edited later.
    unit_cost = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")

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
    balance = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Bank(TenantOwned, Base):
    __tablename__ = "banks"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_bank_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False, index=True)
    account_number = Column(String(60), nullable=True)
    balance = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StockMovement(TenantOwned, Base):
    """Audit trail of every quantity change on a product."""

    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True, index=True)
    change = Column(Integer, nullable=False)  # positive = in, negative = out
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


class UserWarehouseAccess(Base):
    __tablename__ = "user_warehouse_access"
    __table_args__ = (UniqueConstraint("user_id", "warehouse_id", name="uq_user_warehouse_access"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)

    user = relationship("User", back_populates="warehouse_access")
    warehouse = relationship("Warehouse")


class Payment(TenantOwned, Base):
    """Money received from a customer (receipt) or paid to a supplier (payment).

    Exactly one of customer_id / supplier_id is set. Payments are never edited or deleted:
    a mistake is corrected by voiding the payment (status 'voided'), which removes it from balances.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("(customer_id IS NOT NULL) <> (supplier_id IS NOT NULL)", name="ck_payment_one_party"),
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    safe_id = Column(Integer, ForeignKey("safes.id"), nullable=True, index=True)
    bank_id = Column(Integer, ForeignKey("banks.id"), nullable=True, index=True)
    amount = Column(Numeric(14, 2), nullable=False)
    method = Column(String(20), nullable=False, default="cash", server_default="cash")  # cash | bank | wallet | cheque
    reference = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    paid_on = Column(Date, nullable=False, server_default=func.current_date())
    status = Column(String(10), nullable=False, default="posted", server_default="posted", index=True)  # posted | voided
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    voided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    voided_at = Column(DateTime(timezone=True), nullable=True)

    customer = relationship("Customer")
    supplier = relationship("Supplier")

    @property
    def kind(self) -> str:
        return "receipt" if self.customer_id is not None else "payment"


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
    order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    total_amount = Column(Numeric(14, 2), nullable=False)
    refund_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")  # cash given back now
    method = Column(String(20), nullable=False, default="cash", server_default="cash")
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    order = relationship("SalesOrder")
    customer = relationship("Customer")
    items = relationship("SalesReturnItem", back_populates="ret", cascade="all, delete-orphan")

    kind = "sales"

    @property
    def party_id(self):
        return self.customer_id

    @property
    def party_name(self):
        return self.customer.name if self.customer else None


class SalesReturnItem(TenantOwned, Base):
    __tablename__ = "sales_return_items"

    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(Integer, ForeignKey("sales_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    order_item_id = Column(Integer, ForeignKey("sales_order_items.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
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
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)
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
    order_item_id = Column(Integer, ForeignKey("purchase_order_items.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
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
    system_qty = Column(Integer, nullable=False)  # quantity when the sheet was created
    counted_qty = Column(Integer, nullable=True)  # NULL = not counted (left untouched when applying)

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
    quantity = Column(Integer, nullable=False, default=0, server_default="0")

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
    quantity = Column(Integer, nullable=False)

    transfer = relationship("StockTransfer", back_populates="items")
    product = relationship("Product")

    @property
    def sku(self):
        return self.product.sku if self.product else None

    @property
    def product_name(self):
        return self.product.name if self.product else None
