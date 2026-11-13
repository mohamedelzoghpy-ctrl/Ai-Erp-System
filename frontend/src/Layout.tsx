import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import { useI18n } from "./i18n";
import { roleLabel } from "./format";
import CompanyAdmin from "./pages/CompanyAdmin";
import { Modal } from "./ui";
import { api } from "./api";
import { useFetch } from "./hooks";
import type { Company } from "./types";

export default function Layout() {
  const { user, logout, isPlatformAdmin, can } = useAuth();
  const { t, lang, setLang } = useI18n();
  const navigate = useNavigate();
  const companies = useFetch(() => (isPlatformAdmin ? api.get<Company[]>("/platform/companies") : api.get<Company[]>("/auth/companies")), "my-companies");
  const pending = useFetch(() => (can("inventory.transfer.view") ? api.get<{ count: number }>("/stock-transfers/pending-count") : Promise.resolve({ count: 0 })), "pending-transfers");
  const link = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);
  const activeCompany = companies.data?.find((c) => c.id === user?.active_company_id);
  // رخصة الاستخدام: تنبيه مرئي بالأيام المتبقية — الإدارة من شاشة إدارة الشركات (مدير المنصة).
  const licenseInfo = (() => {
    if (!activeCompany?.license_until) return null;
    const days = Math.ceil((new Date(activeCompany.license_until).getTime() - Date.now()) / 86400000);
    return { days, expired: days < 0, until: activeCompany.license_until };
  })();
  const showCompanySwitch = isPlatformAdmin || (companies.data?.length ?? 0) > 1;
  const [companyAdminOpen, setCompanyAdminOpen] = useState(false);
  // رسالة ترحيب للموظف بعد تسجيل الدخول — تظهر مرة واحدة لكل جلسة دخول ثم تختفي.
  const [welcome, setWelcome] = useState(false);
  useEffect(() => {
    if (!user) return;
    if (sessionStorage.getItem("erp_welcome") === "1") {
      sessionStorage.removeItem("erp_welcome");
      setWelcome(true);
      const timer = window.setTimeout(() => setWelcome(false), 6000);
      return () => window.clearTimeout(timer);
    }
  }, [user?.id]);
  const welcomeGreeting = new Date().getHours() < 12 ? t("welcome.morning") : t("welcome.evening");
  // كل الأقسام مطوية افتراضياً — عند تسجيل الدخول وإعادة التحميل.
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const toggle = (k: string) => setOpen((s) => ({ ...s, [k]: !s[k] }));

  // عند تسجيل دخول مستخدم (أو تغيير الحساب) تُطوى كل الأقسام من جديد.
  useEffect(() => {
    setOpen({});
  }, [user?.id]);

  // القوائم تتولد من الصلاحيات — أي رابط بلا صلاحية لا يظهر إطلاقاً.
  const navSections: { key: string; title: string; items: { to: string; label: string; perm: string }[] }[] = [
    {
      key: "inv",
      title: t("nav.inventory"),
      items: [
        { to: "/products", label: t("nav.products"), perm: "inventory.product.view" },
        { to: "/warehouses", label: t("nav.warehouses"), perm: "inventory.warehouse.view" },
        { to: "/lots", label: t("nav.lots"), perm: "inventory.lot.view" },
        { to: "/warehouse-balances", label: t("nav.warehouseBalances"), perm: "inventory.product.stock" },
        { to: "/low-stock", label: t("dashboard.lowStockAlerts"), perm: "reports.inventory.low_stock" },
        { to: "/transfers", label: t("nav.transfers"), perm: "inventory.transfer.view" },
        { to: "/stocktakes", label: t("nav.stocktakes"), perm: "inventory.stocktake.view" },
      ],
    },
    {
      key: "pur",
      title: t("nav.purchasing"),
      items: [
        { to: "/purchase-orders", label: t("nav.purchasePoint"), perm: "purchasing.order.view" },
        { to: "/purchase-returns", label: t("nav.purchaseReturns"), perm: "purchasing.return.view" },
        { to: "/suppliers", label: t("nav.suppliers"), perm: "purchasing.supplier.view" },
      ],
    },
    {
      key: "sal",
      title: t("nav.sales"),
      items: [
        { to: "/pos", label: t("nav.pos"), perm: "sales.pos.use" },
        { to: "/sales-returns", label: t("nav.salesReturns"), perm: "sales.return.view" },
        { to: "/sales-orders", label: t("nav.salesOrders"), perm: "sales.order.view" },
        { to: "/shifts", label: t("nav.shifts"), perm: "sales.shift.view" },
        { to: "/sales-reps", label: t("nav.salesReps"), perm: "sales.rep.view" },
        { to: "/crm", label: t("nav.crm"), perm: "crm.lead.view" },
        { to: "/customers", label: t("nav.customers"), perm: "sales.customer.view" },
      ],
    },
    {
      key: "acc",
      title: t("nav.accounts"),
      items: [
        { to: "/payments", label: t("nav.payments"), perm: "accounting.payment.view" },
        { to: "/accounting", label: t("nav.accounting"), perm: "accounting.account.view" },
      ],
    },
    {
      key: "man",
      title: t("nav.manufacturing"),
      items: [
        { to: "/boms", label: t("nav.boms"), perm: "manufacturing.bom.view" },
        { to: "/production-orders", label: t("nav.productionOrders"), perm: "manufacturing.order.view" },
        { to: "/work-centers", label: t("مراكز العمل"), perm: "manufacturing.work_center.view" },
        { to: "/quality", label: t("nav.quality"), perm: "manufacturing.quality.view" },
        { to: "/production-reports", label: t("nav.productionReports"), perm: "manufacturing.order.report_summary" },
        { to: "/production-floor", label: t("nav.productionFloor"), perm: "manufacturing.order.produce" },
      ],
    },
    {
      key: "hr",
      title: t("nav.hr"),
      items: [
        { to: "/hr/me", label: t("nav.hrSelfService"), perm: "hr.me.use" },
        { to: "/hr/employees", label: t("nav.hrEmployees"), perm: "hr.employee.view" },
        { to: "/hr/attendance", label: t("nav.hrAttendance"), perm: "hr.attendance.view" },
        { to: "/hr/leaves", label: t("nav.hrLeaves"), perm: "hr.leave.view" },
        { to: "/hr/payroll", label: t("nav.hrPayroll"), perm: "hr.payroll.view" },
        { to: "/hr/talent", label: t("nav.hrTalent"), perm: "hr.posting.view" },
        { to: "/hr/settings", label: t("nav.hrSettings"), perm: "hr.job_title.view" },
      ],
    },
    {
      key: "usr",
      title: t("nav.users"),
      items: [
        { to: "/users", label: t("nav.userList"), perm: "admin.user.view" },
        { to: "/permissions", label: t("nav.permissions"), perm: "admin.user.permissions_manage" },
      ],
    },
    {
      key: "comp",
      title: t("nav.company"),
      items: [{ to: "/company", label: t("nav.branchesSettings"), perm: "admin.company.view" }],
    },
  ];
  navSections.push({
    key: "reports",
    title: t("nav.reports"),
    items: [
      { to: "/reports/sales", label: t("nav.reports.sales"), perm: "reports.sales.summary" },
      { to: "/reports/profit", label: t("nav.reports.profit"), perm: "reports.sales.profit" },
      { to: "/reports/purchases", label: t("nav.reports.purchases"), perm: "reports.purchasing.summary" },
      { to: "/reports/inventory", label: t("nav.reports.inventory"), perm: "reports.inventory.valuation" },
      { to: "/reports/receivables", label: t("nav.reports.receivables"), perm: "reports.sales.receivables" },
      { to: "/reports/payables", label: t("nav.reports.payables"), perm: "reports.purchasing.payables" },
    ],
  });
  navSections.push({
    key: "taxes",
    title: t("الضرائب"),
    items: [{ to: "/taxes", label: t("مركز الضرائب"), perm: "taxes.vat.view" }],
  });
  navSections.push({
    key: "pricelists",
    title: t("قوائم الأسعار"),
    items: [
      { to: "/price-lists", label: t("إدارة قوائم الأسعار"), perm: "sales.price_list.view" },
    ],
  });
  navSections.push({
    key: "eta",
    title: t("الفاتورة الإلكترونية"),
    items: [
      { to: "/eta", label: t("الإعداد وسجل الإرسال"), perm: "eta.config.view" },
    ],
  });
  navSections.push({
    key: "dataio",
    title: t("nav.reports.dataio"),
    items: [
      { to: "/data-io/customers", label: t("nav.reports.dataioCustomers"), perm: "admin.dataio.history" },
      { to: "/data-io/suppliers", label: t("nav.reports.dataioSuppliers"), perm: "admin.dataio.history" },
      { to: "/data-io/warehouses", label: t("nav.reports.dataioWarehouses"), perm: "admin.dataio.history" },
    ],
  });

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
      {welcome && user && (
        <div className="welcome-toast" role="status" aria-live="polite">
          <div className="welcome-title">
            {welcomeGreeting}، <strong>{user.full_name || user.username}</strong> 👋
          </div>
          <div className="welcome-sub">{t("welcome.title")} — {t("welcome.sub")}</div>
        </div>
      )}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">MZ</div>
          <div className="brand-text">
            <div className="brand-name">MO<span className="brand-z">Z</span>AD</div>
            <span className="brand-erp">ERP</span>
          </div>
        </div>
        <nav className="nav">
          <NavLink to="/" end className={link}>{t("nav.dashboard")}</NavLink>
          {navSections.map((sec) => {
            const visible = sec.items.filter((it) => can(it.perm));
            if (!visible.length) return null;
            if (sec.key === "comp" && isPlatformAdmin) return null;
            return section(sec.key, sec.title, (
              <>
                {visible.map((it) => (
                  <NavLink key={it.to} to={it.to} className={link}>{it.label}</NavLink>
                ))}
              </>
            ));
          })}

          {isPlatformAdmin && (
            <button type="button" className="nav-company-admin" onClick={() => setCompanyAdminOpen(true)}>
              {t("nav.companies")}
            </button>
          )}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          {licenseInfo && (
            <span
              className="badge"
              style={
                licenseInfo.expired
                  ? { background: "var(--danger-bg)", color: "var(--danger)", fontWeight: 700 }
                  : licenseInfo.days <= 30
                    ? { background: "var(--warn-bg)", color: "var(--warn)", fontWeight: 700 }
                    : { background: "var(--ok-bg)", color: "var(--ok)" }
              }
              title={`${t("الرخصة تنتهي في")} ${licenseInfo.until}`}
            >
              {licenseInfo.expired
                ? t("license.expired")
                : licenseInfo.days === 0
                  ? t("license.expiresToday")
                  : t("license.expiresIn") + " " + licenseInfo.days + " " + t("common.days")}
            </span>
          )}
          <span className="who">
            {user?.full_name || user?.username} · {user ? roleLabel(user.role, lang) : ""}
          </span>

          {can("inventory.transfer.view") && (
            <a href="/transfers" style={{ marginInlineStart: 12, position: "relative", textDecoration: "none" }} title={t("transfers.pendingTitle")}>
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
          {showCompanySwitch && (
            <button type="button" className="btn-company" onClick={() => navigate("/switch-company")} title={t("nav.switchCompany")}>
              <span className="co-swap" aria-hidden="true">⇄</span>
              <span className="co-name">{activeCompany?.name ?? t("nav.switchCompany")}</span>
            </button>
          )}
          <button
            type="button"
            className="btn-lang"
            onClick={() => setLang(lang === "ar" ? "en" : "ar")}
            title={lang === "ar" ? "Switch to English" : "التبديل إلى العربية"}
          >
            <span className="lang-icon" aria-hidden="true">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="2" y1="12" x2="22" y2="12" />
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
              </svg>
            </span>
            <span className="lang-text">{lang === "ar" ? "English" : "العربية"}</span>
          </button>
          <button type="button" className="btn-logout" onClick={logout} title={t("auth.logout")}>
            <span className="lo-icon" aria-hidden="true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </span>
            <span className="lo-text">{t("auth.logout")}</span>
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
