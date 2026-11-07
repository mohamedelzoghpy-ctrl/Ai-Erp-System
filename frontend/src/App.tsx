import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Products from "./pages/Products";
import WarehouseBalances from "./pages/WarehouseBalances";
import LowStock from "./pages/LowStock";
import Boms from "./pages/Boms";
import ProductionOrders from "./pages/ProductionOrders";
import ProductionReports from "./pages/ProductionReports";
import ProductionFloor from "./pages/ProductionFloor";
import { Customers, Suppliers, Warehouses } from "./pages/MasterData";
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
import Reports from "./pages/Reports";
import Users from "./pages/Users";
import CompanyAdmin from "./pages/CompanyAdmin";
import DataIO from "./pages/DataIO";
import SwitchCompany from "./pages/SwitchCompany";
import { Loading } from "./ui";
import { useEffect } from "react";

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
  const { user, loading, isManager } = useAuth();
  useNoNegativeInputs();

  if (loading) return <Loading />;
  if (!user) return <Login />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="products" element={<Products />} />
        <Route path="warehouse-balances" element={<WarehouseBalances />} />
        <Route path="low-stock" element={<LowStock />} />
        <Route path="warehouses" element={<Warehouses />} />
        <Route path="suppliers" element={<Suppliers />} />
        <Route path="customers" element={<Customers />} />
        <Route path="data-io" element={<DataIO />} />
        <Route path="purchase-orders" element={<PurchaseOrders />} />
        <Route path="sales-orders" element={<SalesOrders />} />
        <Route path="pos" element={<Pos />} />
        <Route path="transfers" element={<Transfers />} />
        <Route path="stocktakes" element={<Stocktakes />} />
        <Route path="shifts" element={<Shifts />} />
        {isManager && <Route path="boms" element={<Boms />} />}
        {isManager && <Route path="production-orders" element={<ProductionOrders />} />}
        {isManager && <Route path="production-reports" element={<ProductionReports />} />}
        <Route path="production-floor" element={<ProductionFloor />} />
        {isManager && <Route path="sales-reps" element={<SalesReps />} />}
        <Route path="returns" element={<Navigate to="/sales-returns" replace />} />
        <Route path="sales-returns" element={<Returns lockKind="sales" />} />
        <Route path="purchase-returns" element={<Returns lockKind="purchase" />} />
        <Route path="payments" element={<Payments />} />
        <Route path="accounting" element={<Accounting />} />
  <Route path="chart-of-accounts" element={<Navigate to="/accounting" replace />} />
        {isManager && <Route path="reports" element={<Reports />} />}
        {isManager && <Route path="audit" element={<AuditLog />} />}
        {isManager && <Route path="users" element={<Users />} />}
        {isManager && <Route path="company" element={<CompanyAdmin />} />}
        <Route path="platform/companies" element={<Navigate to="/" replace />} />
        <Route path="switch-company" element={<SwitchCompany />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
