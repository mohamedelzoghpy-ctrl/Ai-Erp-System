import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "./auth";
import { ROLE_LABEL } from "./format";

export default function Layout() {
  const { user, logout, isAdmin, isManager } = useAuth();
  const link = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">نظام ERP</div>
        <nav className="nav">
          <NavLink to="/" end className={link}>
            لوحة التحكم
          </NavLink>
          <div className="section">المخزون</div>
          <NavLink to="/products" className={link}>
            المنتجات
          </NavLink>
          <NavLink to="/warehouses" className={link}>
            المخازن
          </NavLink>
          <div className="section">المشتريات</div>
          <NavLink to="/suppliers" className={link}>
            الموردون
          </NavLink>
          <NavLink to="/purchase-orders" className={link}>
            أوامر الشراء
          </NavLink>
          <div className="section">المبيعات</div>
          <NavLink to="/customers" className={link}>
            العملاء
          </NavLink>
          <NavLink to="/sales-orders" className={link}>
            أوامر البيع
          </NavLink>
          <div className="section">الحسابات</div>
          <NavLink to="/payments" className={link}>
            المقبوضات والمدفوعات
          </NavLink>
          {isManager && (
            <>
              <div className="section">التقارير</div>
              <NavLink to="/reports" className={link}>
                التقارير المفصلة
              </NavLink>
              <NavLink to="/audit" className={link}>
                سجل النشاط
              </NavLink>
            </>
          )}
          {isAdmin && (
            <>
              <div className="section">الإدارة</div>
              <NavLink to="/users" className={link}>
                المستخدمون
              </NavLink>
            </>
          )}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="who">
            {user?.full_name || user?.username} · {user ? ROLE_LABEL[user.role] : ""}
          </span>
          <button className="btn btn-sm" onClick={logout}>
            تسجيل الخروج
          </button>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
