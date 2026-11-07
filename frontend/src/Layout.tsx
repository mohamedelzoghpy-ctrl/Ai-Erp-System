import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import { useI18n } from "./i18n";
import { ROLE_LABEL } from "./format";
import CompanyAdmin from "./pages/CompanyAdmin";
import { Modal } from "./ui";
import { api } from "./api";
import { useFetch } from "./hooks";
import type { Company } from "./types";

export default function Layout() {
  const { user, logout, isManager, isPlatformAdmin } = useAuth();
  const { t, lang, setLang } = useI18n();
  const navigate = useNavigate();
  const companies = useFetch(() => (isPlatformAdmin ? api.get<Company[]>("/platform/companies") : api.get<Company[]>("/auth/companies")), "my-companies");
  const pending = useFetch(() => (isManager ? api.get<{ count: number }>("/stock-transfers/pending-count") : Promise.resolve({ count: 0 })), "pending-transfers");
  const link = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);
  const [companyAdminOpen, setCompanyAdminOpen] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({
    inv: true, pur: true, sal: true, acc: true, rep: true, comp: true, usr: true,
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

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><span className="brand-name">MO<span className="brand-z">Z</span>AD</span> <span className="brand-erp">ERP</span></div>
        <nav className="nav">
          <NavLink to="/" end className={link}>{t("nav.dashboard")}</NavLink>
          {section("inv", t("nav.inventory"), (
            <>
              <NavLink to="/products" className={link}>{t("nav.products")}</NavLink>
              <NavLink to="/warehouses" className={link}>{t("nav.warehouses")}</NavLink>
              <NavLink to="/warehouse-balances" className={link}>{t("nav.warehouseBalances")}</NavLink>
              <NavLink to="/low-stock" className={link}>{t("dashboard.lowStockAlerts")}</NavLink>
              <NavLink to="/transfers" className={link}>{t("nav.transfers")}</NavLink>
              <NavLink to="/stocktakes" className={link}>{t("nav.stocktakes")}</NavLink>
            </>
          ))}
          {section("pur", t("nav.purchasing"), (
            <>
              <NavLink to="/purchase-orders" className={link}>نقطة المشتريات</NavLink>
              <NavLink to="/purchase-returns" className={link}>{t("nav.purchaseReturns")}</NavLink>
              <NavLink to="/suppliers" className={link}>{t("nav.suppliers")}</NavLink>
            </>
          ))}
          {section("sal", t("nav.sales"), (
            <>
              <NavLink to="/pos" className={link}>{t("nav.pos")}</NavLink>
              <NavLink to="/sales-returns" className={link}>{t("nav.salesReturns")}</NavLink>
              <NavLink to="/sales-orders" className={link}>{t("nav.salesOrders")}</NavLink>
              <NavLink to="/shifts" className={link}>{t("nav.shifts")}</NavLink>
              {isManager && <NavLink to="/sales-reps" className={link}>مندوبي المبيعات</NavLink>}
              <NavLink to="/customers" className={link}>{t("nav.customers")}</NavLink>
            </>
          ))}
          {section("acc", t("nav.accounts"), (
            <>
              <NavLink to="/payments" className={link}>{t("nav.payments")}</NavLink>
              <NavLink to="/accounting" className={() => "nav-link-plain"}>{t("nav.accounting")}</NavLink>
            </>
          ))}
          {isManager && section("man", "التصنيع", (
            <>
              <NavLink to="/boms" className={link}>قوائم المواد (BOM)</NavLink>
              <NavLink to="/production-orders" className={link}>أوامر التصنيع</NavLink>
              <NavLink to="/production-reports" className={link}>تقارير التصنيع</NavLink>
            </>
          ))}
          <NavLink to="/production-floor" className={link}>نقطة التشغيل</NavLink>
          {isManager && section("usr", "المستخدمون", (
            <NavLink to="/users" className={link}>قائمة المستخدمين</NavLink>
          ))}
          {isManager && !isPlatformAdmin && section("comp", t("nav.company"), (
            <NavLink to="/company" className={link}>{t("nav.branchesSettings")}</NavLink>
          ))}
          {isManager && (
            <NavLink to="/reports" className={link}>التقارير</NavLink>
          )}
          <NavLink to="/data-io" className={link}>{t("nav.dataIO")}</NavLink>
          {isPlatformAdmin && (
            <button type="button" className="nav-company-admin" onClick={() => setCompanyAdminOpen(true)}>
              {t("nav.companies")}
            </button>
          )}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="who">
            {user?.full_name || user?.username} · {user ? (lang === "ar" ? ROLE_LABEL[user.role] : (user.role === "admin" ? "Admin" : user.role === "manager" ? "Manager" : "Staff")) : ""}
          </span>

          {isManager && (
            <a href="/transfers" style={{ marginInlineStart: 12, position: "relative", textDecoration: "none" }} title="تحويلات قيد الانتظار">
              🔔
              {(pending.data?.count ?? 0) > 0 && (
                <span
                  style={{
                    position: "absolute",
                    top: -6,
                    insetInlineEnd: -6,
                    background: "var(--danger, #dc2626)",
                    color: "#fff",
                    borderRadius: 999,
                    fontSize: 11,
                    padding: "1px 5px",
                    lineHeight: 1,
                  }}
                >
                  {pending.data?.count}
                </span>
              )}
            </a>
          )}
          {(isPlatformAdmin || (companies.data && companies.data.length > 1)) && (
            <button
              className="btn btn-sm"
              style={{ marginInlineStart: 12 }}
              onClick={() => navigate("/switch-company")}
            >
              تبديل الشركة
            </button>
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
      {companyAdminOpen && (
        <Modal title={t("nav.companies")} onClose={() => setCompanyAdminOpen(false)} wide fullscreen>
          <CompanyAdmin
            platform
            onSaved={() => {
              setCompanyAdminOpen(false);
              navigate("/");
            }}
          />
        </Modal>
      )}
    </div>
  );
}
