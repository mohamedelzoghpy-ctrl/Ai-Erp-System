import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "./auth";
import { ROLE_LABEL } from "./format";
import { api } from "./api";
import { useFetch } from "./hooks";
import type { Company } from "./types";

export default function Layout() {
  const { user, logout, isManager, isPlatformAdmin } = useAuth();
  const company = useFetch(() => api.get<Company>("/company"), "current-company");
  const link = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">نظام ERP</div>
        <nav className="nav">
          <NavLink to="/" end className={link}>
            لوحة التحكم
          </NavLink>
          <NavLink to="/products" className="section">المخزون</NavLink>
          <NavLink to="/products" className={link}>
            المنتجات
          </NavLink>
          <NavLink to="/warehouses" className={link}>
            المخازن
          </NavLink>
          <NavLink to="/transfers" className={link}>
            التحويلات
          </NavLink>
          <NavLink to="/stocktakes" className={link}>
            الجرد
          </NavLink>
          <NavLink to="/suppliers" className="section">المشتريات</NavLink>
          <NavLink to="/suppliers" className={link}>
            الموردون
          </NavLink>
          <NavLink to="/purchase-orders" className={link}>
            أوامر الشراء
          </NavLink>
          <NavLink to="/pos" className="section">المبيعات</NavLink>
          <NavLink to="/returns" className={link}>
            المرتجعات
          </NavLink>
          <NavLink to="/pos" className={link}>
            نقطة البيع
          </NavLink>
          <NavLink to="/customers" className={link}>
            العملاء
          </NavLink>
          <NavLink to="/sales-orders" className={link}>
            أوامر البيع
          </NavLink>
          <NavLink to="/shifts" className={link}>
            الورديات
          </NavLink>
          <NavLink to="/payments" className="section">الحسابات</NavLink>
          <NavLink to="/payments" className={link}>
            المقبوضات والمدفوعات
          </NavLink>
          {isManager && (
            <>
              <NavLink to="/reports" className="section">التقارير</NavLink>
              <NavLink to="/reports" className={link}>
                التقارير المفصلة
              </NavLink>
              <NavLink to="/audit" className={link}>
                سجل النشاط
              </NavLink>
            </>
          )}
          {isManager && (
            <>
              <NavLink to="/users" className="section">الشركة</NavLink>
              <NavLink to="/users" className={link}>
                الموظفون
              </NavLink>
              <NavLink to="/company" className={link}>
                الفروع والإعدادات
              </NavLink>
            </>
          )}
          {isPlatformAdmin && (
            <NavLink to="/platform/companies" className={link}>
              إدارة الشركات
            </NavLink>
          )}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="who">
            {company.data?.name ? `${company.data.name} · ` : ""}
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
