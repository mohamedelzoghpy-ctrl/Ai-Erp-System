import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "./auth";
import { useI18n } from "./i18n";
import { ROLE_LABEL } from "./format";
import { api } from "./api";
import { useFetch } from "./hooks";
import type { Company } from "./types";

export default function Layout() {
  const { user, logout, isManager, isPlatformAdmin } = useAuth();
  const { t, lang, setLang } = useI18n();
  const company = useFetch(() => api.get<Company>("/company"), "current-company");
  const companies = useFetch(() => api.get<Company[]>("/auth/companies"), "my-companies");
  const link = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);
  const [open, setOpen] = useState<Record<string, boolean>>({
    inv: true, pur: true, sal: true, acc: true, rep: true, comp: true,
  });
  const toggle = (k: string) => setOpen((s) => ({ ...s, [k]: !s[k] }));

  const section = (key: string, title: string, children: React.ReactNode) => (
    <>
      <button type="button" className="section section-toggle" onClick={() => toggle(key)} aria-expanded={open[key]}>
        <span>{title}</span>
        <span className="section-chevron">{open[key] ? "▾" : "▸"}</span>
      </button>
      {open[key] && children}
    </>
  );

  const switchCompany = async (id: number) => {
    if (id === company.data?.id) return;
    try {
      await api.post("/auth/switch-company", { company_id: id });
      window.location.reload();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">{t("app.name")}</div>
        <nav className="nav">
          <NavLink to="/" end className={link}>{t("nav.dashboard")}</NavLink>
          {section("inv", t("nav.inventory"), (
            <>
              <NavLink to="/products" className={link}>{t("nav.products")}</NavLink>
              <NavLink to="/warehouses" className={link}>{t("nav.warehouses")}</NavLink>
              <NavLink to="/transfers" className={link}>{t("nav.transfers")}</NavLink>
              <NavLink to="/stocktakes" className={link}>{t("nav.stocktakes")}</NavLink>
            </>
          ))}
          {section("pur", t("nav.purchasing"), (
            <>
              <NavLink to="/suppliers" className={link}>{t("nav.suppliers")}</NavLink>
              <NavLink to="/purchase-orders" className={link}>{t("nav.purchaseOrders")}</NavLink>
            </>
          ))}
          {section("sal", t("nav.sales"), (
            <>
              <NavLink to="/returns" className={link}>{t("nav.returns")}</NavLink>
              <NavLink to="/pos" className={link}>{t("nav.pos")}</NavLink>
              <NavLink to="/customers" className={link}>{t("nav.customers")}</NavLink>
              <NavLink to="/sales-orders" className={link}>{t("nav.salesOrders")}</NavLink>
              <NavLink to="/shifts" className={link}>{t("nav.shifts")}</NavLink>
            </>
          ))}
          {section("acc", t("nav.accounts"), (
            <NavLink to="/payments" className={link}>{t("nav.payments")}</NavLink>
          ))}
          {isManager && !isPlatformAdmin && section("rep", t("nav.reports"), (
            <>
              <NavLink to="/reports" className={link}>{t("nav.reportsDetailed")}</NavLink>
              <NavLink to="/audit" className={link}>{t("nav.audit")}</NavLink>
            </>
          ))}
          {isManager && !isPlatformAdmin && section("comp", t("nav.company"), (
            <>
              <NavLink to="/users" className={link}>{t("nav.employees")}</NavLink>
              <NavLink to="/company" className={link}>{t("nav.branchesSettings")}</NavLink>
            </>
          ))}
          {isPlatformAdmin && (
            <NavLink to="/platform/companies" className={link}>{t("nav.companies")}</NavLink>
          )}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="who">
            {company.data?.name ? `${company.data.name} · ` : ""}
            {user?.full_name || user?.username} · {user ? (lang === "ar" ? ROLE_LABEL[user.role] : (user.role === "admin" ? "Admin" : user.role === "manager" ? "Manager" : "Staff")) : ""}
          </span>
          {companies.data && companies.data.length > 1 && (
            <select
              value={company.data?.id ?? ""}
              onChange={(e) => switchCompany(Number(e.target.value))}
              style={{ marginInlineStart: 12 }}
              aria-label="الشركة"
            >
              {companies.data.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
          <button className="btn btn-sm" onClick={() => setLang(lang === "ar" ? "en" : "ar")} style={{ marginInlineStart: 12 }}>
            {lang === "ar" ? "EN" : "AR"}
          </button>
          <button className="btn btn-sm" onClick={logout}>
            {t("auth.logout")}
          </button>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
