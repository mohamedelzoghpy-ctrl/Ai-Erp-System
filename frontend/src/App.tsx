import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Products from "./pages/Products";
import { Customers, Suppliers, Warehouses } from "./pages/MasterData";
import { PurchaseOrders, SalesOrders } from "./pages/Orders";
import Payments from "./pages/Accounts";
import Reports from "./pages/Reports";
import Users from "./pages/Users";
import { Loading } from "./ui";

export default function App() {
  const { user, loading, isAdmin, isManager } = useAuth();

  if (loading) return <Loading />;
  if (!user) return <Login />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="products" element={<Products />} />
        <Route path="warehouses" element={<Warehouses />} />
        <Route path="suppliers" element={<Suppliers />} />
        <Route path="customers" element={<Customers />} />
        <Route path="purchase-orders" element={<PurchaseOrders />} />
        <Route path="sales-orders" element={<SalesOrders />} />
        <Route path="payments" element={<Payments />} />
        {isManager && <Route path="reports" element={<Reports />} />}
        {isAdmin && <Route path="users" element={<Users />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
