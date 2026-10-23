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
  quantity: number;
  unit_cost?: string; // purchase orders
  unit_price?: string; // sales orders
}

export interface Order {
  id: number;
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

export interface SalesSummary {
  orders: number;
  total: string;
  by_day: { day: string; orders: number; total: string }[];
  top_products: { product_id: number; sku: string; name: string; quantity_sold: number; revenue: string }[];
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
}
