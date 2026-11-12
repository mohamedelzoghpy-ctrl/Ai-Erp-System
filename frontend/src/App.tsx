import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Products from "./pages/Products";
import WarehouseBalances from "./pages/WarehouseBalances";
import Eta from "./pages/Eta";
import PriceLists from "./pages/PriceLists";
import LowStock from "./pages/LowStock";
import { ReportsInventory, ReportsPayables, ReportsProfit, ReportsPurchases, ReportsReceivables, ReportsSales } from "./pages/Reports";
import Lots from "./pages/Lots";
import Quality from "./pages/Quality";
import { DataIOCustomers, DataIOSuppliers, DataIOWarehouses } from "./pages/DataIO";
import Boms from "./pages/Boms";
import ProductionOrders from "./pages/ProductionOrders";
import ProductionReports from "./pages/ProductionReports";
import ProductionFloor from "./pages/ProductionFloor";
import { Customers, Suppliers, Warehouses } from "./pages/MasterData";
import { HrAttendancePage, HrEmployees, HrEmployeeProfile, HrLeaves, HrPayrollPage, HrSelfService, HrSettings, HrTalentPage } from "./pages/HR";
import { PurchaseOrders, SalesOrders } from "./pages/Orders";
import Payments from "./pages/Accounts";
import Accounting from "./pages/Accounting";
import AuditLog from "./pages/AuditLog";
import Shifts from "./pages/Shifts";
import SalesReps from "./pages/SalesReps";
import Stocktakes from "./pages/Stocktakes";
import Transfers from "./pages/Transfers";
import Pos from "./pages/Pos";
import Returns from "./pages/Returns";
import Users from "./pages/Users";
import CompanyAdmin from "./pages/CompanyAdmin";
import SwitchCompany from "./pages/SwitchCompany";
import Permissions from "./pages/Permissions";
import { Loading } from "./ui";
import { useEffect, type ReactNode } from "react";

/** حارس مسار: يعرض رسالة بدل الصفحة إن غابت الصلاحية (الخادم يحمي الحقيقة دائماً). */
function Guard({ perm, children }: { perm: string; children: ReactNode }) {
  const { can } = useAuth();
  if (can(perm)) return <>{children}</>;
  return (
    <div className="card" style={{ padding: 24, textAlign: "center" }}>
      <h3>🔒 لا تملك صلاحية الوصول لهذه الشاشة</h3>
      <p style={{ color: "var(--muted)" }}>
        الصلاحية المطلوبة: <code>{perm}</code> — تواصل مع مدير النظام لمنحها لك من شاشة الصلاحيات.
      </p>
    </div>
  );
}

/** منع أي قيم سالبة: الحقول الرقمية لا تقبل "-" نهائيًا (الكتابة أو اللصق) */
function useNoNegativeInputs() {
  useEffect(() => {
    const isNumericField = (el: EventTarget | null): el is HTMLInputElement =>
      el instanceof HTMLInputElement &&
      (el.type === "number" ||
        (el.type === "text" && (el.inputMode === "decimal" || el.inputMode === "numeric")));
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.key === "-" || e.key === "Minus" || e.key === "Subtract") && isNumericField(e.target)) e.preventDefault();
    };
    const setName = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    const setNative = (el: HTMLInputElement, v: string) => {
      if (!setName) return;
      setName.call(el, v);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    };
    const strip = (el: HTMLInputElement) => {
      const clean = el.value.replace(/^-+/, "");
      if (clean !== el.value) setNative(el, clean);
    };
    const onInput = (e: Event) => {
      if (e instanceof InputEvent && isNumericField(e.target) && e.target.value.startsWith("-")) strip(e.target);
    };
    const onPaste = (e: ClipboardEvent) => {
      if (e.target instanceof HTMLInputElement && isNumericField(e.target) && /-\s*\d/.test(e.clipboardData?.getData("text") ?? "")) {
        e.preventDefault();
        const clean = (e.clipboardData?.getData("text") ?? "").replace(/-\s*(?=\d)/g, "");
        setNative(e.target, clean);
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("input", onInput, true);
    document.addEventListener("paste", onPaste, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("input", onInput, true);
      document.removeEventListener("paste", onPaste, true);
    };
  }, []);
}

export default function App() {
  const { user, loading } = useAuth();
  useNoNegativeInputs();

  if (loading) return <Loading />;
  if (!user) return <Login />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="products" element={<Guard perm="inventory.product.view"><Products /></Guard>} />
        <Route path="warehouse-balances" element={<Guard perm="inventory.product.stock"><WarehouseBalances /></Guard>} />
        <Route path="low-stock" element={<Guard perm="reports.inventory.low_stock"><LowStock /></Guard>} />
        <Route path="eta" element={<Guard perm="eta.config.view"><Eta /></Guard>} />
        <Route path="price-lists" element={<Guard perm="sales.price_list.view"><PriceLists /></Guard>} />
        <Route path="warehouses" element={<Guard perm="inventory.warehouse.view"><Warehouses /></Guard>} />
        <Route path="lots" element={<Guard perm="inventory.lot.view"><Lots /></Guard>} />
        <Route path="quality" element={<Guard perm="manufacturing.quality.view"><Quality /></Guard>} />
        <Route path="suppliers" element={<Guard perm="purchasing.supplier.view"><Suppliers /></Guard>} />
        <Route path="customers" element={<Guard perm="sales.customer.view"><Customers /></Guard>} />
        <Route path="data-io" element={<Navigate to="/data-io/customers" replace />} />
        <Route path="data-io/customers" element={<Guard perm="admin.dataio.history"><DataIOCustomers /></Guard>} />
        <Route path="data-io/suppliers" element={<Guard perm="admin.dataio.history"><DataIOSuppliers /></Guard>} />
        <Route path="data-io/warehouses" element={<Guard perm="admin.dataio.history"><DataIOWarehouses /></Guard>} />
        <Route path="purchase-orders" element={<Guard perm="purchasing.order.view"><PurchaseOrders /></Guard>} />
        <Route path="sales-orders" element={<Guard perm="sales.order.view"><SalesOrders /></Guard>} />
        <Route path="pos" element={<Guard perm="sales.pos.use"><Pos /></Guard>} />
        <Route path="transfers" element={<Guard perm="inventory.transfer.view"><Transfers /></Guard>} />
        <Route path="stocktakes" element={<Guard perm="inventory.stocktake.view"><Stocktakes /></Guard>} />
        <Route path="shifts" element={<Guard perm="sales.shift.view"><Shifts /></Guard>} />
        <Route path="boms" element={<Guard perm="manufacturing.bom.view"><Boms /></Guard>} />
        <Route path="production-orders" element={<Guard perm="manufacturing.order.view"><ProductionOrders /></Guard>} />
        <Route path="production-reports" element={<Guard perm="manufacturing.order.report_summary"><ProductionReports /></Guard>} />
        <Route path="production-floor" element={<Guard perm="manufacturing.order.produce"><ProductionFloor /></Guard>} />
        <Route path="sales-reps" element={<Guard perm="sales.rep.view"><SalesReps /></Guard>} />
        <Route path="hr" element={<Guard perm="hr.employee.view"><Navigate to="/hr/employees" replace /></Guard>} />
        <Route path="hr/employees" element={<Guard perm="hr.employee.view"><HrEmployees /></Guard>} />
        <Route path="hr/employees/:id" element={<Guard perm="hr.employee.view"><HrEmployeeProfile /></Guard>} />
        <Route path="hr/attendance" element={<Guard perm="hr.attendance.view"><HrAttendancePage /></Guard>} />
        <Route path="hr/leaves" element={<Guard perm="hr.leave.view"><HrLeaves /></Guard>} />
        <Route path="hr/payroll" element={<Guard perm="hr.payroll.view"><HrPayrollPage /></Guard>} />
        <Route path="hr/settings" element={<Guard perm="hr.job_title.view"><HrSettings /></Guard>} />
        <Route path="hr/talent" element={<Guard perm="hr.posting.view"><HrTalentPage /></Guard>} />
        <Route path="hr/me" element={<HrSelfService />} />
        <Route path="returns" element={<Navigate to="/sales-returns" replace />} />
        <Route path="sales-returns" element={<Guard perm="sales.return.view"><Returns lockKind="sales" /></Guard>} />
        <Route path="purchase-returns" element={<Guard perm="purchasing.return.view"><Returns lockKind="purchase" /></Guard>} />
        <Route path="payments" element={<Guard perm="accounting.payment.view"><Payments /></Guard>} />
        <Route path="accounting" element={<Guard perm="accounting.account.view"><Accounting /></Guard>} />
  <Route path="chart-of-accounts" element={<Navigate to="/accounting" replace />} />
        <Route path="reports" element={<Navigate to="/reports/sales" replace />} />
        <Route path="reports/sales" element={<Guard perm="reports.sales.summary"><ReportsSales /></Guard>} />
        <Route path="reports/profit" element={<Guard perm="reports.sales.profit"><ReportsProfit /></Guard>} />
        <Route path="reports/purchases" element={<Guard perm="reports.purchasing.summary"><ReportsPurchases /></Guard>} />
        <Route path="reports/inventory" element={<Guard perm="reports.inventory.valuation"><ReportsInventory /></Guard>} />
        <Route path="reports/receivables" element={<Guard perm="reports.sales.receivables"><ReportsReceivables /></Guard>} />
        <Route path="reports/payables" element={<Guard perm="reports.purchasing.payables"><ReportsPayables /></Guard>} />
        <Route path="audit" element={<Guard perm="admin.audit.view"><AuditLog /></Guard>} />
        <Route path="users" element={<Guard perm="admin.user.view"><Users /></Guard>} />
        <Route path="permissions" element={<Guard perm="admin.user.permissions_manage"><Permissions /></Guard>} />
        <Route path="company" element={<Guard perm="admin.company.view"><CompanyAdmin /></Guard>} />
        <Route path="platform/companies" element={<Navigate to="/" replace />} />
        <Route path="switch-company" element={<SwitchCompany />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
