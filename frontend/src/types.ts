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
  permissions?: string[];
  active_company_id?: number | null;
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
  license_until?: string | null;
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
  credit_limit?: string | null;
  tax_registration_number?: string | null;
  price_list_id?: number | null;
  price_list_name?: string | null;
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
  reorder_level: number;
  is_active: boolean;
  warehouse_id: number | null;
  supplier_id: number | null;
  image_url?: string | null; // صورة من رابط إنترنت
  image_uploaded?: boolean; // صورة مرفوعة من الجهاز تُستخدم عبر /products/{id}/image
  warehouse_quantity?: number; // in one warehouse, when asked with stock_warehouse_id
  warehouse_min_level?: number | null;
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
  currency_id?: number | null;
  currency_code?: string | null;
  exchange_rate?: string | null;
  foreign_total?: string | null;
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
  lots_expiring_soon?: number;
  cheques_due_soon?: number;
  recurring_journals_due?: number;
  pending_journal_approvals?: number;
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
  status?: string;
  approved_by?: number | null;
  approved_at?: string | null;
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

export interface BomOperation {
  id?: number;
  seq: number;
  name: string;
  work_center_id?: number | null;
  work_center_name?: string | null;
  run_minutes_per_unit: number;
  notes?: string | null;
}

export interface Bom {
  id: number;
  product_id: number;
  product_name?: string | null;
  version: string;
  output_qty: number;
  is_active: boolean;
  valid_from?: string | null;
  valid_to?: string | null;
  notes?: string | null;
  items: BomItem[];
  operations: BomOperation[];
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
  std_unit_cost?: number | null;
  estimated_minutes?: number | null;
  materials_available?: boolean | null;
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
  std_unit_cost?: number | null;
  variance_std?: number | null;
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
  total_variance_std?: number | null;
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
  changed: number;
  journal_entry_id?: number | null;
}

export interface Payment {
  id: number;
  kind: "receipt" | "payment";
  currency_id?: number | null;
  currency_code?: string | null;
  exchange_rate?: string | null;
  foreign_amount?: string | null;
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


// ---------- Accounting upgrades 2026-11 (recurring / bank rec / fiscal periods) ----------
export interface RecurringJournal {
  id: number;
  name: string;
  description: string;
  reference: string | null;
  frequency: string;
  day_of_month: number;
  next_run_date: string;
  is_active: boolean;
  items: { account_id: number; debit: string; credit: string; cost_center_id: number | null; notes: string | null }[];
  last_run_entry_id: number | null;
}

export interface BankStatementLine {
  id: number;
  bank_id: number;
  value_date: string;
  description: string;
  amount: string;
  reference: string | null;
  matched_payment_id: number | null;
  matched_payment_reference?: string | null;
}

export interface BankRecSummary {
  bank_id: number;
  statement_balance: string;
  ledger_balance: string;
  matched_total: string;
  unmatched_count: number;
  difference: string;
}

export interface FiscalPeriod {
  id: number;
  fiscal_year_id: number;
  name: string;
  start_date: string;
  end_date: string;
  is_closed: boolean;
}

// ===== مولّد آليًا من schemas.py + qc.py (v4: Decimal=string) =====
export interface HrJobTitle extends ORMModel {
  company_id: number;
  name: string;
  description?: string | null;
  min_salary?: string | null;
  max_salary?: string | null;
  is_active: boolean;
  created_at: string;
}
export interface HrGrade extends ORMModel {
  company_id: number;
  name: string;
  min_salary?: string | null;
  max_salary?: string | null;
  is_active: boolean;
  created_at: string;
}
export interface HrEmployee extends ORMModel {
  company_id: number;
  code: string;
  full_name: string;
  national_id?: string | null;
  insurance_number?: string | null;
  gender?: string | null;
  birth_date?: string | null;
  nationality?: string | null;
  phone?: string | null;
  email?: string | null;
  address?: string | null;
  department_id?: number | null;
  department_name?: string | null;
  job_title_id?: number | null;
  job_title_name?: string | null;
  grade_id?: number | null;
  branch_id?: number | null;
  branch_name?: string | null;
  manager_id?: number | null;
  manager_name?: string | null;
  user_id?: number | null;
  hire_date: string;
  basic_salary?: string | null;
  bank_account?: string | null;
  status: string;
  terminated_at?: string | null;
  termination_reason?: string | null;
  notes?: string | null;
  is_active: boolean;
  contracts_count: number;
  created_at: string;
}
export interface HrEmployeeDetail extends HrEmployee {
  contracts: HrContract[];
  documents: HrDocument[];
  moves: HrEmployeeMove[];
}
export interface HrContract extends ORMModel {
  company_id: number;
  employee_id: number;
  code: string;
  kind: string;
  start_date: string;
  end_date?: string | null;
  basic_salary?: string | null;
  status: string;
  notes?: string | null;
  created_at: string;
}
export interface HrDocument extends ORMModel {
  company_id: number;
  employee_id: number;
  doc_type: string;
  title: string;
  issue_date?: string | null;
  expiry_date: string | null;
  has_file: boolean;
  file_name?: string | null;
  notes?: string | null;
  created_at: string;
}
export interface HrEmployeeMove extends ORMModel {
  company_id: number;
  employee_id: number;
  move_type: string;
  effective_date: string;
  to_department_id?: number | null;
  to_department_name?: string | null;
  to_job_title_id?: number | null;
  to_job_title_name?: string | null;
  from_salary?: string | null;
  to_salary?: string | null;
  reason?: string | null;
  created_at: string;
}
export interface HrShift extends ORMModel {
  company_id: number;
  name: string;
  start_time: string;
  end_time: string;
  grace_minutes: number;
  cross_midnight: boolean;
  is_active: boolean;
  created_at: string;
}
export interface HrShiftAssignment extends ORMModel {
  company_id: number;
  employee_id: number;
  employee_name?: string | null;
  shift_id: number;
  shift_name?: string | null;
  created_at: string;
}
export interface HrAttendance extends ORMModel {
  company_id: number;
  employee_id: number;
  employee_name?: string | null;
  employee_code?: string | null;
  work_date: string;
  status: string;
  check_in?: string | null;
  check_out?: string | null;
  late_minutes: number;
  overtime_minutes: number;
  source: string;
  notes?: string | null;
  created_at: string;
}
export interface HrHoliday extends ORMModel {
  company_id: number;
  name: string;
  holiday_date: string;
  notes?: string | null;
  created_at: string;
}
export interface HrLeaveType extends ORMModel {
  company_id: number;
  name: string;
  days_per_year: string;
  is_paid: boolean;
  carry_over_days: string;
  is_active: boolean;
  created_at: string;
}
export interface HrLeaveRequest extends ORMModel {
  approval_level: number;
  company_id: number;
  employee_id: number;
  employee_name?: string | null;
  employee_code?: string | null;
  leave_type_id: number;
  leave_type_name?: string | null;
  from_date: string;
  to_date: string;
  days: string;
  status: string;
  reason?: string | null;
  decision_note?: string | null;
  decided_at?: string | null;
  created_at: string;
}
export interface HrLeaveBalance extends ORMModel {
  company_id: number;
  employee_id: number;
  employee_name?: string | null;
  employee_code?: string | null;
  leave_type_id: number;
  leave_type_name?: string | null;
  year: number;
  entitled_days: string;
  carried_days: string;
  used_days: string;
  remaining_days: string;
}
export interface HrSalaryComponent extends ORMModel {
  company_id: number;
  employee_id: number;
  employee_name?: string | null;
  category: string;
  name: string;
  amount_mode: string;
  fixed_amount?: string | null;
  percent_value?: string | null;
  is_active: boolean;
  notes?: string | null;
  created_at: string;
}
export interface HrPayrollRun extends ORMModel {
  company_id: number;
  year: number;
  month: number;
  status: string;
  note?: string | null;
  employees_count: number;
  total_gross: string;
  total_deductions: string;
  total_net: string;
  journal_entry_id?: number | null;
  posted_at?: string | null;
  created_at: string;
}
export interface HrPayslipLine extends ORMModel {
  company_id: number;
  payslip_id: number;
  category: string;
  name: string;
  amount: string;
  notes?: string | null;
}
export interface HrPayslip extends ORMModel {
  company_id: number;
  run_id: number;
  employee_id: number;
  employee_name?: string | null;
  employee_code?: string | null;
  base_salary: string;
  absent_days: number;
  unpaid_leave_days: string;
  absence_deduction: string;
  total_earnings: string;
  total_deductions: string;
  net_pay: string;
  notes?: string | null;
}
export interface HrAdvance extends ORMModel {
  company_id: number;
  employee_id: number;
  employee_name?: string | null;
  employee_code?: string | null;
  amount: string;
  installments_count: number;
  start_year: number;
  start_month: number;
  status: string;
  notes?: string | null;
  created_at: string;
}
export interface HrSettlement extends ORMModel {
  company_id: number;
  employee_id: number;
  employee_name?: string | null;
  employee_code?: string | null;
  termination_date: string;
  service_days: number;
  service_years: string;
  eosb_days: string;
  eosb_amount: string;
  unused_leave_days: string;
  unused_leave_amount: string;
  advances_remaining: string;
  total_due: string;
  note?: string | null;
  created_at: string;
}
export interface HrAttendanceCorrection extends ORMModel {
  company_id: number;
  employee_id: number;
  employee_name?: string | null;
  employee_code?: string | null;
  work_date: string;
  requested_check_in?: string | null;
  requested_check_out?: string | null;
  reason: string;
  status: string;
  decision_note?: string | null;
  applied_attendance_id?: number | null;
  decided_at?: string | null;
  created_at: string;
}
export interface HrMePayslip extends ORMModel {
  run_id: number;
  year: number;
  month: number;
  run_status: string;
  base_salary: string;
  total_earnings: string;
  total_deductions: string;
  net_pay: string;
}
export interface HrJobPosting extends ORMModel {
  company_id: number;
  code: string;
  title: string;
  department_name?: string | null;
  branch_name?: string | null;
  openings: number;
  employment_type: string;
  description?: string | null;
  status: string;
  hired_count: number;
  closed_at?: string | null;
  created_at: string;
}
export interface HrApplicant extends ORMModel {
  company_id: number;
  posting_id: number;
  posting_title?: string | null;
  posting_code?: string | null;
  full_name: string;
  email: string;
  phone?: string | null;
  source?: string | null;
  resume_text?: string | null;
  stage: string;
  rating?: number | null;
  note?: string | null;
  hired_employee_id?: number | null;
  decided_at?: string | null;
  created_at: string;
}
export interface HrReviewCycle extends ORMModel {
  company_id: number;
  name: string;
  period_start: string;
  period_end: string;
  status: string;
  closed_at?: string | null;
  created_at: string;
}
export interface HrReview extends ORMModel {
  company_id: number;
  cycle_id: number;
  employee_id: number;
  employee_name?: string | null;
  employee_code?: string | null;
  quality: number;
  commitment: number;
  teamwork: number;
  initiative: number;
  score: string;
  comment?: string | null;
  reviewed_by?: number | null;
  reviewed_at: string;
}
export interface HrTraining extends ORMModel {
  company_id: number;
  code: string;
  title: string;
  provider?: string | null;
  location?: string | null;
  from_date: string;
  to_date: string;
  cost: string;
  notes?: string | null;
  enrollments_count: number;
  created_at: string;
}
export interface HrEnrollment extends ORMModel {
  company_id: number;
  training_id: number;
  training_title?: string | null;
  employee_id: number;
  employee_name?: string | null;
  employee_code?: string | null;
  status: string;
  completed_at?: string | null;
  certificate_note?: string | null;
  created_at: string;
}
export interface HrAnalytics {
  attendance: any;
  leaves: any;
  turnover: any;
  payroll: any;
  recruiting: any;
  talent: any;
}
export interface WorkCenter {
  id: number;
  name: string;
  capacity_per_hour?: number | null;
  hourly_cost?: string | null;
  notes?: string | null;
  is_active: boolean;
}

export interface WorkCenterPerf {
  date_from?: string | null;
  date_to?: string | null;
  rows: WorkCenterPerfRow[];
}
export interface MaterialsAvailability {
  order_id: number;
  code: string;
  warehouse_name?: string | null;
  lines: MaterialsAvailabilityItem[];
  all_available: boolean;
  missing_count: number;
}
export interface QcTemplate {
  id: number;
  name: string;
  description?: string | null;
  is_active: boolean;
  parameters: QcParameter[];
}
export interface QcParameter {
  id: number;
  name: string;
  unit?: string | null;
  param_type: string;
  min_value?: number | null;
  max_value?: number | null;
}

// ===== إضافات يدوية (استرجاع) =====
export type ORMModel = { id: number };
export type EmployeeStatus = string;
export type ApplicantStage = string;

export interface StockLot extends ORMModel {
  company_id: number;
  product_id: number;
  warehouse_id: number;
  lot_code: string;
  source: string;
  reference: string | null;
  qty_received: number;
  qty_remaining: number;
  expiry_date?: string | null;
  product_name?: string | null;
  warehouse_name?: string | null;
  created_at: string;
}

export interface AccessSection extends ORMModel {
  code: string;
  name: string;
  description?: string | null;
  is_active?: boolean;
  is_system?: boolean;
  permission_codes: string[];
  permissions?: string[];
}

export interface CatalogPermission { code: string; action: string; label: string; is_dangerous?: boolean; is_field?: boolean }
export interface CatalogResource { resource: string; label: string; permissions: CatalogPermission[] }
export interface CatalogModule { module: string; label: string; resources: CatalogResource[] }


export interface QcMeasurementsOut {
  batch_id: number;
  attempt?: number;
  attempts_count?: number;
  overall_pass?: boolean | null;
  results: { parameter_id: number; parameter_name: string; unit?: string | null; value_num?: number | null; value_text?: string | null; pass_fail?: boolean | null; attempt?: number }[];
}

export interface ForwardTraceOut {
  lot_id: number;
  lot_code: string;
  product_id: number;
  product_name?: string | null;
  orders: { order_id: number; order_code: string; order_status: string; product_name?: string | null; consumed_qty: string | number; batches: { batch_no: string; qty: string | number; qc_status: string; finished_lot_qty: string | number }[] }[];
}

export interface MaterialsAvailabilityItem {
  component_id: number;
  component_name?: string | null;
  component_unit?: string | null;
  required: string;
  available: string;
  unit_cost: string;
  enough: boolean;
  staged?: boolean;
}
export interface MaterialsAvailability {
  ok: boolean;
  shortages: MaterialsAvailabilityItem[];
}

export interface WorkCenterPerfOut {
  rows: WorkCenterPerfRow[];
  total_planned_minutes: number;
  total_actual_minutes: number;
}

export interface WorkCenterPerfRow {
  work_center_id: number;
  name: string;
  orders_count: number;
  qty_done: number;
  qty_scrapped: number;
  actual_minutes: number;
  planned_minutes: number;
  utilization: number;
}

export type HrSummary = Record<string, number>;

export interface HrMeProfile extends HrEmployee {
  username?: string;
  role?: string;
}

export interface PermissionOverride { code: string; effect: string; reason?: string | null; label?: string | null }
export interface UserPermissionDetail {
  user_id: number;
  company_id: number;
  section_id?: number | null;
  section_name?: string | null;
  section_ids: number[];
  section_names: string[];
  role: string;
  inherited: { code: string; label: string; source: string }[];
  overrides: PermissionOverride[];
  effective: string[];
}


export interface EtaSubmission {
  id: number;
  order_id: number;
  document_type: string;
  internal_id: string;
  submission_uuid: string | null;
  eta_uuid: string | null;
  eta_long_id: string | null;
  status: string;
  errors?: unknown;
  submitted_at: string | null;
  status_checked_at: string | null;
}


export interface Currency {
  id: number;
  code: string;
  name: string;
  rate: string;
  is_active: boolean;
  updated_at: string | null;
}


export interface EtaQueueRow {
  order_id: number;
  internal_id: string;
  party_name: string;
  total_amount: string;
  foreign_total?: string | null;
  currency_code?: string | null;
  created_at: string | null;
  status?: string;
  eta_long_id?: string | null;
  errors?: unknown;
}

export interface EtaIncoming {
  id: number;
  eta_uuid: string;
  issuer_tin: string | null;
  issuer_name: string;
  internal_id: string | null;
  total_amount: string;
  status: string;
  purchase_order_id: number | null;
  lines: { description: string; internalCode?: string; quantity: number; unitPrice?: number; salesTotal?: number }[];
  received_at: string | null;
}

// ==================== موديول الضرائب ====================
export interface VatRateRow {
  rate: string;
  invoices: number;
  taxable_base: string;
  tax_amount: string;
}

export interface VatMonthRow {
  month: string;
  output_vat: string;
  input_vat: string;
  net: string;
}

export interface VatReturn {
  date_from: string;
  date_to: string;
  output_vat: string;
  input_vat: string;
  net_payable: string;
  sales_by_rate: VatRateRow[];
  monthly: VatMonthRow[];
  taxable_sales_total: string;
}

export interface WithholdingCode {
  id: number;
  name: string;
  rate: string;
  is_active: boolean;
}

export interface WithholdingRow {
  id: number;
  paid_on: string;
  supplier_id: number | null;
  supplier_name: string | null;
  reference: string | null;
  method: string;
  amount: string;
  withholding: string;
  net_cash: string;
  code_name: string;
}

export interface WithholdingReport {
  date_from: string;
  date_to: string;
  rows: WithholdingRow[];
  by_code: { code: string; total: string }[];
  by_supplier: { supplier: string; total: string }[];
  total_withheld: string;
}

export interface TaxBracket {
  id: number;
  min_amount: string;
  max_amount: string | null;
  rate: string;
  sort: number;
}

export interface PayrollTaxSettings {
  personal_exemption: string;
  wage_reduction_percent: string;
  social_insurance_percent: string;
  brackets: TaxBracket[];
}

export interface PayrollTaxRow {
  employee_id: number;
  code: string;
  name: string;
  monthly_gross: string;
  monthly_si: string;
  annual_gross: string;
  annual_si: string;
  personal_exemption: string;
  annual_taxable: string;
  annual_tax: string;
  monthly_tax: string;
  actual_withheld: string;
  difference: string;
}

export interface PayrollTaxReport {
  run_id: number;
  period: string;
  status: string;
  personal_exemption: string;
  wage_reduction_percent: string;
  rows: PayrollTaxRow[];
  total_monthly_tax: string;
  total_actual: string;
  total_difference: string;
}

export interface PayrollRunLite {
  id: number;
  year: number;
  month: number;
  status: string;
  employees_count: number;
  total_net: string;
}
