// Mirrors the backend response schemas. Decimal values arrive from FastAPI as strings.

export type Role = "admin" | "manager" | "staff";

export interface User {
  id: number;
  username: string;
  full_name: string | null;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface Warehouse {
  id: number;
  name: string;
  code: string;
  location: string | null;
  is_active: boolean;
}

export interface Party {
  id: number;
  name: string;
  contact_person: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  is_active: boolean;
  opening_balance: string;
  balance: string; // >0: owed (customer owes us / we owe supplier); <0: credit
}

export interface Product {
  id: number;
  sku: string;
  name: string;
  description: string | null;
  unit: string;
  cost_price: string;
  sale_price: string;
  quantity: number;
  reorder_level: number;
  is_active: boolean;
  warehouse_id: number | null;
  supplier_id: number | null;
}

export interface StockMovement {
  id: number;
  product_id: number;
  warehouse_id: number | null;
  change: number;
  reason: string;
  reference: string | null;
  created_at: string;
}

export type OrderStatus = "draft" | "received" | "confirmed" | "cancelled";

export interface OrderItem {
  id: number;
  product_id: number;
  product_name?: string | null;
  quantity: number;
  unit_cost?: string; // purchase orders
  unit_price?: string; // sales orders
}

export type PaymentStatus = "paid" | "partial" | "unpaid";

export interface Order {
  id: number;
  paid_amount?: string | null;
  balance_due?: string | null;
  payment_status?: PaymentStatus | null;
  party_name?: string | null;
  supplier_id?: number; // purchase orders
  customer_id?: number; // sales orders
  warehouse_id: number;
  status: OrderStatus;
  notes: string | null;
  total_amount: string;
  created_at: string;
  items: OrderItem[];
}

export interface LowStockItem {
  id: number;
  sku: string;
  name: string;
  quantity: number;
  reorder_level: number;
  shortfall: number;
  warehouse_id: number | null;
}

export interface InventoryValuationRow {
  warehouse_id: number | null;
  warehouse_name: string | null;
  products: number;
  units: number;
  cost_value: string;
  sale_value: string;
}

export interface DayTotal {
  day: string;
  orders: number;
  total: string;
}

export interface SalesSummary {
  orders: number;
  total: string;
  by_day: DayTotal[];
  top_products: { product_id: number; sku: string; name: string; quantity_sold: number; revenue: string }[];
  by_customer: { customer_id: number; customer_name: string; orders: number; total: string }[];
}

export interface PurchasesSummary {
  orders: number;
  total: string;
  by_day: DayTotal[];
  top_products: { product_id: number; sku: string; name: string; quantity_bought: number; spend: string }[];
  by_supplier: { supplier_id: number; supplier_name: string; orders: number; total: string }[];
}

export interface Dashboard {
  period_days: number;
  products: number;
  low_stock_products: number;
  warehouses: number;
  suppliers: number;
  customers: number;
  inventory_cost_value: string;
  inventory_sale_value: string;
  sales_orders_confirmed: number;
  sales_total: string;
  purchase_orders_received: number;
  purchases_total: string;
  draft_sales_orders: number;
  draft_purchase_orders: number;
  receivables_total: string;
  payables_total: string;
}

export type PaymentMethod = "cash" | "bank" | "wallet" | "cheque";

export interface Payment {
  id: number;
  kind: "receipt" | "payment";
  customer_id: number | null;
  supplier_id: number | null;
  party_name: string | null;
  amount: string;
  method: PaymentMethod;
  reference: string | null;
  notes: string | null;
  paid_on: string;
  status: "posted" | "voided";
  created_at: string;
}

export interface StatementLine {
  date: string;
  type: "sale" | "purchase" | "receipt" | "payment";
  ref: string;
  description: string;
  charge: string;
  payment: string;
  balance: string;
}

export interface Statement {
  kind: "customer" | "supplier";
  party_id: number;
  party_name: string;
  date_from: string | null;
  date_to: string | null;
  opening: string;
  lines: StatementLine[];
  total_charges: string;
  total_payments: string;
  closing: string;
}

export interface BalanceRow {
  party_id: number;
  name: string;
  phone: string | null;
  balance: string;
}

export interface BalancesReport {
  total: string;
  rows: BalanceRow[];
}
