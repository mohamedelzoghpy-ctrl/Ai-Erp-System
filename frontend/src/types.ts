// Mirrors the backend response schemas. Decimal values arrive from FastAPI as strings.

export type Role = "admin" | "manager" | "staff";

export interface User {
  id: number;
  username: string;
  employee_code?: string;
  full_name: string | null;
  role: Role;
  is_active: boolean;
  is_platform_admin: boolean;
  created_at: string;
  branch_ids?: number[];
  warehouse_ids?: number[];
  department_id?: number | null;
  department_name?: string | null;
  all_branches?: boolean;
}

export interface Company {
  id: number;
  name: string;
  code: string;
  max_warehouses_per_branch: number | null;
  max_safes_per_branch: number | null;
  max_branches: number | null;
  is_active: boolean;
  created_at: string;
}

export interface Department {
  id: number;
  company_id: number;
  name: string;
  code: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Branch {
  id: number;
  company_id: number;
  name: string;
  code: string;
  location: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Warehouse {
  id: number;
  name: string;
  code: string;
  location: string | null;
  is_active: boolean;
  branch_id: number;
}

export interface Party {
  id: number;
  name: string;
  code: string | null;
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
  quantity: number; // total over all warehouses
  warehouse_quantity?: number | null; // in one warehouse, when asked with stock_warehouse_id
  reorder_level: number;
  is_active: boolean;
  warehouse_id: number | null;
  supplier_id: number | null;
  image_url?: string | null; // صورة من رابط إنترنت
  image_uploaded?: boolean; // صورة مرفوعة من الجهاز تُستخدم عبر /products/{id}/image
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
  returned_quantity?: number;
  quantity: number;
  unit_cost?: string; // purchase orders
  unit_price?: string; // sales orders
}

export type PaymentStatus = "paid" | "partial" | "unpaid";

export interface Order {
  id: number;
  created_by_name?: string | null; // sales orders
  rep_id?: number | null; // sales orders — مندوب المبيعات
  rep_name?: string | null;
  safe_id?: number | null; // sales orders — اسم الخزينة
  safe_name?: string | null;
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
  image_url?: string | null;
  image_uploaded?: boolean;
  supplier_name?: string | null;
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
  by_cashier: { username: string | null; orders: number; total: string }[];
  by_product_supplier: { supplier_id: number | null; supplier_name: string; orders: number; total: string }[];
}

export interface ProfitRow {
  product_id: number;
  sku: string;
  name: string;
  quantity: number;
  revenue: string;
  cost: string;
  profit: string;
  margin_pct: string | null;
}

export interface ProfitSummary {
  sales: string;
  returns: string;
  revenue: string;
  cost: string;
  profit: string;
  margin_pct: string | null;
  by_product: ProfitRow[];
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
  sales_returns_total: string;
  purchase_returns_total: string;
  payables_total: string;
  stale_shifts?: number;
  sales_growth_pct?: number | null;
  purchases_growth_pct?: number | null;
  pending_transfers?: number;
  cash_liquidity_total?: string;
  safes_balance_total?: string;
  banks_balance_total?: string;
}

export interface CostCenter {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
  created_at: string;
}

export interface FiscalYear {
  id: number;
  name: string;
  start_date: string;
  end_date: string;
  is_closed: boolean;
  created_at: string;
}

export interface FixedAsset {
  id: number;
  code: string;
  name: string;
  asset_type: string;
  purchase_date: string;
  cost: string;
  accumulated_depreciation: string;
  current_book_value: string;
  depreciation_method: string;
  useful_life_years: number;
  salvage_value: string;
  is_active: boolean;
  created_at: string;
}

export interface StockTransfer {
  id: number;
  from_warehouse_id: number;
  from_warehouse_name: string | null;
  to_warehouse_id: number;
  to_warehouse_name: string | null;
  notes: string | null;
  status: "pending" | "approved" | "rejected";
  valuation: "cost" | "sale";
  username: string | null;
  approved_by: number | null;
  approved_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  items: { product_id: number; sku: string | null; product_name: string | null; quantity: number }[];
}

export interface JournalEntry {
  id: number;
  date: string | null;
  description: string;
  reference: string | null;
  created_at: string;
  items: { id: number; account_id: number; account_name?: string | null; debit: string; credit: string; cost_center_id: number | null; notes: string | null }[];
}

export type PaymentMethod = "cash" | "bank" | "wallet" | "cheque";

export interface PaymentCategory {
  id: number;
  name: string;
  kind: "receipt" | "payment";
  requires_party: boolean; // false = سند بدون عميل/مورد (إيراد/مصروف عام)
}

export type ChequeDirection = "received" | "issued";
export type ChequeStatus = "under_collection" | "issued" | "collected" | "cashed" | "returned";

export interface Cheque {
  id: number;
  direction: ChequeDirection;
  number: string;
  bank_id: number;
  bank_name?: string | null;
  bank_branch_name?: string | null; // فرع البنك
  company_name?: string | null;
  amount: string;
  customer_id: number | null;
  supplier_id: number | null;
  party_name: string | null;
  cheque_date: string;
  due_date: string | null;
  status: ChequeStatus;
  payment_id: number | null;
  notes: string | null;
  created_at: string;
}

export interface AccountStatementLine {
  entry_id: number;
  date: string;
  description: string | null;
  reference: string | null;
  debit: string; // داخل (للخزينة/البنك)
  credit: string; // خارج
  balance: string;
}

export interface AccountStatementOut {
  account_name: string;
  account_code: string;
  opening: string;
  closing: string;
  total_debit: string;
  total_credit: string;
  lines: AccountStatementLine[];
}

export interface BomItem {
  id?: number;
  component_id: number;
  component_name?: string | null;
  component_code?: string | null;
  component_unit?: string | null;
  qty_per_output: string;
  scrap_pct: string;
  notes?: string | null;
}

export interface Bom {
  id: number;
  product_id: number;
  product_name?: string | null;
  version: string;
  output_qty: number;
  is_active: boolean;
  notes?: string | null;
  items: BomItem[];
  created_at: string;
}

export interface ProductionConsumption {
  component_id: number;
  component_name?: string | null;
  component_unit?: string | null;
  qty: number;
  unit_cost: string;
  total_cost: string;
}

export type ProductionOrderStatus = "draft" | "in_progress" | "completed" | "cancelled";
export type ProductionCostType = "labor" | "overhead" | "subcontract";

export const PRODUCTION_STATUS_LABEL: Record<ProductionOrderStatus, string> = {
  draft: "مسودة",
  in_progress: "قيد التنفيذ",
  completed: "مكتمل",
  cancelled: "ملغي",
};

export interface ProductionCost {
  id: number;
  cost_type: "labor" | "overhead";
  amount: string;
  description?: string | null;
  created_at: string;
}

export interface ProductionBatch {
  id: number;
  batch_no: string;
  qty: number;
  cost: string;
  qc_status: "pending" | "passed" | "rejected";
  produced_at: string;
  notes?: string | null;
}

export interface ProductionChildOrder {
  id: number;
  code: string;
  product_id: number;
  product_name?: string | null;
  qty_planned: number;
  status: ProductionOrderStatus;
}

export interface ProductionOrder {
  id: number;
  code: string;
  product_id: number;
  product_name?: string | null;
  bom_id?: number | null;
  qty_planned: number;
  qty_produced: number;
  qty_scrapped: number;
  is_late?: boolean;
  status: ProductionOrderStatus;
  raw_warehouse_id: number;
  raw_warehouse_name?: string | null;
  output_warehouse_id: number;
  output_warehouse_name?: string | null;
  subcontractor_id?: number | null;
  subcontractor_name?: string | null;
  production_line_id?: number | null;
  production_line_name?: string | null;
  parent_order_id?: number | null;
  scheduled_date?: string | null;
  notes?: string | null;
  consumptions: ProductionConsumption[];
  costs: ProductionCost[];
  costs_total?: string;
  batches: ProductionBatch[];
  children: ProductionChildOrder[];
  created_at: string;
}

export interface ProductionLine {
  id: number;
  name: string;
  capacity_per_hour?: number | null;
  hourly_cost?: string | null;
  is_active: boolean;
  created_at: string;
}

export interface WipOrder {
  id: number;
  code: string;
  product_id: number;
  product_name?: string | null;
  qty_planned: number;
  qty_produced: number;
  remaining: number;
  materials: string;
  costs: string;
  wip_value: string;
  unit_cost: string;
  scheduled_date?: string | null;
}

export interface ManufacturingReportLine {
  order_id: number;
  code: string;
  product_name?: string | null;
  qty_planned: number;
  qty_produced: number;
  materials: string;
  costs: string;
  total: string;
  unit_cost: string;
  variance: string;
}

export interface ManufacturingByProduct {
  product_id: number;
  product_name?: string | null;
  orders: number;
  qty_produced: number;
  total: string;
}

export interface ManufacturingReportOut {
  date_from?: string | null;
  date_to?: string | null;
  lines: ManufacturingReportLine[];
  total_orders: number;
  total_qty_produced: number;
  total_materials: string;
  total_costs: string;
  total: string;
  total_variance: string;
  by_product: ManufacturingByProduct[];
}

export interface ReconcileLine {
  account_id: number;
  code: string;
  name: string;
  type: string;
  stored: string;
  ledger: string;
  drift: string;
}

export interface ReconcileOut {
  lines: ReconcileLine[];
  total_stored: string;
  total_ledger: string;
  total_drift: string;
}

export interface Payment {
  id: number;
  kind: "receipt" | "payment";
  customer_id: number | null;
  supplier_id: number | null;
  category_id?: number | null; // بند القبض / الصرف
  category_name?: string | null;
  company_name?: string | null;
  safe_branch_name?: string | null; // فرع الخزينة
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

export interface AgingRow {
  party_id: number;
  name: string;
  phone: string | null;
  opening: string;
  current: string;
  d31_60: string;
  d61_90: string;
  d90_plus: string;
  total: string;
}

export interface AgingReport {
  as_of: string;
  total_opening: string;
  total_current: string;
  total_d31_60: string;
  total_d61_90: string;
  total_d90_plus: string;
  total_total: string;
  rows: AgingRow[];
}

export interface AuditEntry {
  id: number;
  created_at: string;
  username: string | null;
  action: string;
  entity: string;
  entity_id: number | null;
  summary: string | null;
}

export interface ReturnItem {
  id: number;
  order_item_id: number | null;
  product_id: number;
  product_name: string | null;
  quantity: number;
  unit_price: string;
}

export interface ReturnDoc {
  id: number;
  kind: "sales" | "purchase";
  order_id: number | null;
  party_id: number | null;
  party_name: string | null;
  warehouse_id: number;
  rep_id?: number | null; // sales returns — مندوب المبيعات
  rep_name?: string | null;
  total_amount: string;
  refund_amount: string;
  method: PaymentMethod;
  notes: string | null;
  created_at: string;
  items: ReturnItem[];
}

export interface Shift {
  id: number;
  user_id: number;
  username: string;
  status: "open" | "closed";
  opened_at: string;
  closed_at: string | null;
  opening_cash: string;
  cash_in: string;
  cash_out: string;
  cash_refunds_in: string;
  cash_refunds_out: string;
  other_methods_in: string;
  expected_cash: string;
  counted_cash: string | null;
  difference: string | null;
  notes: string | null;
  is_stale: boolean;
}

export interface StocktakeLine {
  product_id: number;
  sku: string | null;
  product_name: string | null;
  system_qty: number;
  counted_qty: number | null;
  difference: number | null;
}

export interface Stocktake {
  id: number;
  status: "open" | "applied" | "cancelled";
  warehouse_id: number | null;
  warehouse_name: string | null;
  notes: string | null;
  username: string | null;
  created_at: string;
  applied_at: string | null;
  lines_total: number;
  lines_counted: number;
  lines_with_difference: number;
  lines: StocktakeLine[] | null;
}

export interface ProductStockRow {
  warehouse_id: number;
  warehouse_name: string;
  quantity: number;
}

export interface ChartAccount {
  id: number;
  code: string;
  name: string;
  parent_id: number | null;
  type: "asset" | "liability" | "equity" | "revenue" | "expense";
  is_group: boolean;
  is_active: boolean;
  balance: string;
}

export interface SalesRep {
  id: number;
  company_id: number;
  name: string;
  code: string;
  phone: string | null;
  branch_ids: number[];
  commission_percent: string;
  is_active: boolean;
  created_at: string;
}
