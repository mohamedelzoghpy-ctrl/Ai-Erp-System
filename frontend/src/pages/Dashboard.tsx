import { useState, useRef, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  LabelList,
} from "recharts";
import { api } from "../api";
import { useAuth } from "../auth";
import { dayLabel, money, num } from "../format";
import { useFetch } from "../hooks";
import { useI18n } from "../i18n";
import type { Dashboard as DashboardData, InventoryValuationRow, SalesSummary } from "../types";
import { Alert, Empty, PageHeader } from "../ui";

const PALETTE = ["#2563eb", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#64748b"];

function Kpi({ label, value, sub, warn, trend, trendLabel, color, icon }: { label: string; value: string; sub?: string; warn?: boolean; trend?: { direction: "up" | "down"; percentage: number }; trendLabel?: string; color?: string; icon?: string }) {
  const body = (
    <div className="kpi-body">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
      {trend && (
        <span className={`trend-indicator trend-${trend.direction}`} aria-hidden={true}>
          {trendLabel || (trend.direction === "up" ? "↑" : "↓")}
          {trend.percentage}%
        </span>
      )}
    </div>
  );
  if (!icon) {
    return (
      <div className={`card kpi${warn ? " warn" : ""}`} style={{ borderRight: color ? `4px solid ${color}` : undefined }} aria-label={label}>
        {body}
      </div>
    );
  }
  return (
    <div
      className={`card kpi has-icon${warn ? " warn" : ""}`}
      style={color ? { background: `linear-gradient(135deg, ${color}17, ${color}2e)`, borderColor: `${color}45` } : undefined}
      aria-label={label}
    >
      {body}
      <div className="kpi-icon" style={color ? { color, background: "#ffffffd9", borderColor: `${color}55` } : undefined} aria-hidden="true">
        {icon}
      </div>
    </div>
  );
}

/** البطاقة المالية البطلة — كبيرة ملوّنة بأيقونة وشريط نسبة (لوحة التحكم الهرمية). */
function HeroKpi({ kind, icon, label, value, sub, barPct, barLabel }: {
  kind: "profit" | "assets" | "liabilities" | "equity";
  icon: string;
  label: string;
  value: string;
  sub: string;
  barPct?: number | null;
  barLabel?: string;
}) {
  const pct = barPct == null ? null : Math.max(0, Math.min(100, barPct));
  return (
    <div className={`hero-kpi ${kind}`} aria-label={label}>
      <div className="hero-icon" aria-hidden="true">{icon}</div>
      <div className="hero-label">{label}</div>
      <div className="hero-value">{value}</div>
      <div className="hero-sub">{sub}</div>
      {pct != null && (
        <>
          <div className="hero-bar" role="presentation">
            <span style={{ width: `${pct}%` }} />
          </div>
          {barLabel && <div className="hero-bar-label">{barLabel}</div>}
        </>
      )}
    </div>
  );
}

function formatYAxisNumber(val: number) {
  if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1_000) return `${(val / 1_000).toFixed(0)}k`;
  return String(val);
}

/** Real period-over-period growth from the API (null-safe: no fabricated trends). */
function growthTrend(ggrowth: number | null | undefined) {
  if (ggrowth == null || Number.isNaN(ggrowth)) return undefined;
  const rounded = Math.abs(Math.round(ggrowth * 10) / 10);
  return { direction: ggrowth >= 0 ? ("up" as const) : ("down" as const), percentage: rounded };
}

function ChartTooltip({ active, payload, label, unit = "ج.م" }: { active?: boolean; payload?: any[]; label?: string; unit?: string }) {
  if (active && payload && payload.length) {
    return (
      <div
        style={{
          background: "rgba(15, 23, 42, 0.94)",
          color: "#fff",
          padding: "10px 14px",
          borderRadius: "8px",
          boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.4)",
          fontSize: "13px",
          direction: "rtl",
          textAlign: "right",
          border: "1px solid rgba(255, 255, 255, 0.15)",
          minWidth: "150px",
        }}
      >
        {label && <div style={{ fontWeight: 600, marginBottom: 6, color: "#94a3b8", fontSize: "12px" }}>{label}</div>}
        {payload.map((entry, index) => (
          <div key={`entry-${index}`} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, margin: "4px 0" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: entry.color || entry.fill }} />
              <span style={{ color: "#cbd5e1" }}>{entry.name}:</span>
            </div>
            <strong style={{ color: "#fff" }}>
              {typeof entry.value === "number"
                ? unit === "ج.م"
                  ? money(entry.value)
                  : `${num(entry.value)} ${unit}`
                : entry.value}
            </strong>
          </div>
        ))}
      </div>
    );
  }
  return null;
}

export default function Dashboard() {
  const { isManager } = useAuth();
  const { t, lang } = useI18n();
  const localIso = (dt: Date) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
  const [dateFrom, setDateFrom] = useState(() => localIso(new Date(Date.now() - 29 * 86_400_000)));
  const [dateTo, setDateTo] = useState(() => localIso(new Date()));
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const refreshRef = useRef<number | null>(null);

  // Chart interactivity states
  const [salesChartType, setSalesChartType] = useState<"area" | "bar">("area");
  const [salesMetric, setSalesMetric] = useState<"revenue" | "orders">("revenue");
  const [productMetric, setProductMetric] = useState<"revenue" | "qty">("revenue");
  const [inventoryMetric, setInventoryMetric] = useState<"cost" | "sale">("cost");

  // Data fetching (declared before handleRefresh so the callback can reference them)
  const rangeKey = `${dateFrom}|${dateTo}`;
  const dash = useFetch(() => (isManager ? api.get<DashboardData>(`/reports/dashboard?date_from=${dateFrom}&date_to=${dateTo}`) : Promise.resolve(null)), `d${rangeKey}${isManager}`);
  const sales = useFetch(() => (isManager ? api.get<SalesSummary>(`/reports/sales-summary?top=5&date_from=${dateFrom}&date_to=${dateTo}`) : Promise.resolve(null)), `s${rangeKey}${isManager}`);
  const valuation = useFetch(
    () => (isManager ? api.get<InventoryValuationRow[]>("/reports/inventory-valuation") : Promise.resolve(null)),
    `v${isManager}`,
  );
  const pnl = useFetch(() => (isManager ? api.get<{ total_revenue: string; total_expenses: string; net_profit: string }>(`/reports/financial/profit-loss`) : Promise.resolve(null)), `pnl${isManager}`);
  const bs = useFetch(() => (isManager ? api.get<{ total_assets: string; total_liabilities: string; total_equity: string; is_balanced: boolean }>(`/reports/financial/balance-sheet`) : Promise.resolve(null)), `bs${isManager}`);

  const refreshing = dash.loading || sales.loading || valuation.loading || pnl.loading || bs.loading;

  // Manual refresh (debounced)
  const handleRefresh = useCallback(() => {
    if (refreshRef.current) clearTimeout(refreshRef.current);
    refreshRef.current = window.setTimeout(() => {
      dash.reload();
      sales.reload();
      valuation.reload();
      pnl.reload();
      bs.reload();
      setLastRefresh(new Date());
    }, 500);
  }, [dash, sales, valuation, pnl, bs]);

  // Clear the debounce timer on unmount so callbacks never fire on a dead component
  useEffect(() => () => { if (refreshRef.current) clearTimeout(refreshRef.current); }, []);

  const d = dash.data;
  const series = sales.data?.by_day ?? [];
  const periodLabel = t("dashboard.customRange") + ` (${dateFrom} ${t("dashboard.rangeTo")} ${dateTo})`;

  // Mapped Daily Sales Data for Recharts
  const salesChartData = series.map((item) => ({
    rawDay: item.day,
    day: dayLabel(item.day),
    revenue: Number(item.total) || 0,
    orders: item.orders || 0,
  }));

  // Mapped Top Products Data
  const topProductsChartData = (sales.data?.top_products ?? []).map((p) => ({
    name: p.name.length > 18 ? p.name.slice(0, 16) + "…" : p.name,
    fullName: p.name,
    sku: p.sku,
    qty: p.quantity_sold,
    revenue: Number(p.revenue) || 0,
  }));

  // Mapped Warehouse Valuation Data
  const totalCost = (valuation.data ?? []).reduce((acc, row) => acc + (Number(row.cost_value) || 0), 0);
  const totalSale = (valuation.data ?? []).reduce((acc, row) => acc + (Number(row.sale_value) || 0), 0);
  const warehouseChartData = (valuation.data ?? []).map((w, index) => {
    const cost = Number(w.cost_value) || 0;
    const sale = Number(w.sale_value) || 0;
    return {
      name: w.warehouse_name ?? t("dashboard.noWarehouse"),
      units: w.units,
      cost,
      sale,
      costPercent: totalCost > 0 ? ((cost / totalCost) * 100).toFixed(1) : "0",
      salePercent: totalSale > 0 ? ((sale / totalSale) * 100).toFixed(1) : "0",
      color: PALETTE[index % PALETTE.length],
    };
  });

  // Financial Comparison Data (paired: sales vs purchases, receivables vs payables, cost vs expected sale)
  const financialCompareData = d
    ? [
        { name: t("dashboard.sales"), value: Number(d.sales_total) || 0, color: "#2563eb" },
        { name: t("dashboard.purchases"), value: Number(d.purchases_total) || 0, color: "#f59e0b" },
        { name: t("dashboard.receivables"), value: Number(d.receivables_total) || 0, color: "#2563eb" },
        { name: t("dashboard.payables"), value: Number(d.payables_total) || 0, color: "#f59e0b" },
        { name: t("dashboard.inventoryValue"), value: Number(d.inventory_cost_value) || 0, color: "#2563eb" },
        { name: t("dashboard.inventorySaleValue"), value: Number(d.inventory_sale_value) || 0, color: "#f59e0b" },
      ]
    : [];

  return (
    <>
      <PageHeader title={t("dashboard.title")}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {isManager && (
            <div className="dashboard-range" role="group" aria-label={t("dashboard.period")}>
              <label>
                <span>{t("dashboard.fromDate")}</span>
                <input type="date" value={dateFrom} max={dateTo} onChange={(e) => setDateFrom(e.target.value)} />
              </label>
              <span className="dashboard-range-sep" aria-hidden="true">—</span>
              <label>
                <span>{t("dashboard.toDate")}</span>
                <input type="date" value={dateTo} min={dateFrom} onChange={(e) => setDateTo(e.target.value)} />
              </label>
            </div>
          )}
          {isManager && (
            <button type="button" className={`dashboard-refresh${refreshing ? " refreshing" : ""}`} onClick={handleRefresh} disabled={refreshing} aria-label={t("dashboard.refresh")}>
              {refreshing ? (
                <span className="spinner spinner-sm" aria-hidden="true" style={{ marginInlineEnd: 0 }} />
              ) : (
                <svg className="refresh-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
                </svg>
              )}
              {t("dashboard.refresh")}
            </button>
          )}
          {lastRefresh && (
            <span className="badge badge-pill badge-muted" style={{ fontSize: "12px" }} aria-label={t("dashboard.lastUpdated")}>
              {t("dashboard.lastUpdated")} {lastRefresh.toLocaleTimeString(lang === "en" ? "en-GB" : "ar-EG", { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
      </PageHeader>

      {/* TOP SECTION: Financial Core KPIs — بطاقات بطل كبيرة ملوّنة */}
      {isManager && (
        ((pnl.loading && !pnl.data) || (bs.loading && !bs.data)) ? (
          <div className="hero-kpis" aria-hidden="true">
            {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton skeleton-hero" />)}
          </div>
        ) : (
          (() => {
            const revenue = Number(pnl.data?.total_revenue ?? 0);
            const netProfit = Number(pnl.data?.net_profit ?? 0);
            const assets = Number(bs.data?.total_assets ?? 0);
            const liabilities = Number(bs.data?.total_liabilities ?? 0);
            const equity = Number(bs.data?.total_equity ?? 0);
            const marginPct = revenue > 0 ? (netProfit / revenue) * 100 : null;
            const debtPct = assets > 0 ? (liabilities / assets) * 100 : null;
            const equityPct = assets > 0 ? (equity / assets) * 100 : null;
            return (
              <div className="hero-kpis">
                <HeroKpi kind="profit" icon="💰" label={t("dashboard.netProfit")} value={money(netProfit)} sub={`${t("dashboard.revenues")}: ${money(revenue)}`} barPct={marginPct} barLabel={`${t("dashboard.profitMargin")}: ${marginPct != null ? marginPct.toFixed(1) + "%" : "—"}`} />
                <HeroKpi kind="assets" icon="🏦" label={t("dashboard.totalAssets")} value={money(assets)} sub={t("dashboard.assetsFormula")} barPct={100} barLabel={t("dashboard.assetsFormula")} />
                <HeroKpi kind="liabilities" icon="⚠️" label={t("dashboard.totalLiabilities")} value={money(liabilities)} sub={t("dashboard.liabilitiesSub")} barPct={debtPct} barLabel={`${t("dashboard.debtRatio")}: ${debtPct != null ? debtPct.toFixed(1) + "%" : "—"}`} />
                <HeroKpi kind="equity" icon="📊" label={t("dashboard.equity")} value={money(equity)} sub={t("dashboard.equitySub")} barPct={equityPct} barLabel={`${t("dashboard.equityRatio")}: ${equityPct != null ? equityPct.toFixed(1) + "%" : "—"}`} />
              </div>
            );
          })()
        )
      )}

      <Alert>{dash.error || sales.error || valuation.error || pnl.error || bs.error}</Alert>
      {isManager && d && (d.stale_shifts ?? 0) > 0 && (
        <Alert kind="info">
          {num(d.stale_shifts)} {t("dashboard.staleShifts")}. <Link to="/shifts">{t("dashboard.reviewShifts")}</Link>
        </Alert>
      )}
      {isManager && d && (d.lots_expiring_soon ?? 0) > 0 && (
        <Alert kind="info">⏳ {num(d.lots_expiring_soon)} لوط ينتهي خلال 30 يومًا — راجع تنبيهات المخزون.</Alert>
      )}
      {isManager && d && (d.cheques_due_soon ?? 0) > 0 && (
        <Alert kind="info">📅 {num(d.cheques_due_soon)} شيك يستحق خلال 7 أيام — راجع حافظة الشيكات.</Alert>
      )}
      {isManager && d && (d.recurring_journals_due ?? 0) > 0 && (
        <Alert kind="info">🔁 {num(d.recurring_journals_due)} قيد متكرر مستحق الترحيل — من صفحة المحاسبة ← قيود متكررة.</Alert>
      )}
      {isManager && d && (d.pending_journal_approvals ?? 0) > 0 && (
        <Alert kind="info">⏳ {num(d.pending_journal_approvals)} قيد بانتظار اعتمادك — من صفحة المحاسبة ← القيود.</Alert>
      )}

      {/* KPI Cards — مجمعة في مجموعات منطقية */}
      {isManager &&
        (dash.loading && !d ? (
          <div className="kpi-group" aria-hidden="true">
            <div className="skeleton skeleton-group-title" />
            <div className="kpis">
              {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton skeleton-kpi" />)}
            </div>
          </div>
        ) : (
          d && (
            [
              {
                title: t("dashboard.groupOps"), icon: "💼",
                items: [
                  <Kpi key="sales" icon="📈" color="#10b981" label={t("dashboard.sales") + ` (${periodLabel})`} value={money(d.sales_total)} sub={`${num(d.sales_orders_confirmed)} ${t("dashboard.confirmedOrder")}`} trend={growthTrend(d.sales_growth_pct)} trendLabel={t(d.sales_growth_pct != null && d.sales_growth_pct < 0 ? "dashboard.trendDown" : "dashboard.trendUp")} />,
                  <Kpi key="purch" icon="🛒" color="#2563eb" label={t("dashboard.purchases") + ` (${periodLabel})`} value={money(d.purchases_total)} sub={`${num(d.purchase_orders_received)} ${t("dashboard.receivedOrder")}`} trend={growthTrend(d.purchases_growth_pct)} trendLabel={t(d.purchases_growth_pct != null && d.purchases_growth_pct < 0 ? "dashboard.trendDown" : "dashboard.trendUp")} />,
                  <Kpi key="returns" icon="↩️" color="#f59e0b" label={t("dashboard.returns")} value={money(d.sales_returns_total)} sub={`${t("dashboard.purchaseReturn")}: ${money(d.purchase_returns_total)}`} />,
                  <Kpi key="drafts" icon="📝" color="#64748b" label={t("dashboard.draftOrders")} value={num(d.draft_sales_orders + d.draft_purchase_orders)} sub={`${num(d.draft_sales_orders)} ${t("dashboard.salesOrders")} · ${num(d.draft_purchase_orders)} ${t("dashboard.purchaseOrders")}`} />,
                ],
              },
              {
                title: t("dashboard.groupInventory"), icon: "📦",
                items: [
                  <Kpi key="inv" icon="📦" color="#2563eb" label={t("dashboard.inventoryValue")} value={money(d.inventory_cost_value)} sub={`${t("dashboard.inventorySaleValue")}: ${money(d.inventory_sale_value)}`} />,
                  <Kpi key="est" icon="💵" color="#10b981" label={t("dashboard.profitEstimate")} value={money(Number(d.inventory_sale_value) - Number(d.inventory_cost_value))} sub={`${t("dashboard.margin")}: ` + (d.inventory_cost_value && Number(d.inventory_cost_value) > 0 ? (((Number(d.inventory_sale_value) - Number(d.inventory_cost_value)) / Number(d.inventory_cost_value)) * 100).toFixed(1) + "%" : "0%")} />,
                  <Kpi key="low" icon="⚠️" color="#ef4444" label={t("dashboard.lowStock")} value={num(d.low_stock_products)} warn={d.low_stock_products > 0} />,
                  <Kpi key="prod" icon="🏷️" color="#8b5cf6" label={t("dashboard.activeProducts")} value={num(d.products)} sub={`${num(d.warehouses)} ${t("dashboard.warehouses")} · ${num(d.suppliers)} ${t("dashboard.suppliers")} · ${num(d.customers)} ${t("dashboard.customers")}`} />,
                ],
              },
              {
                title: t("dashboard.groupCash"), icon: "💰",
                items: [
                  <Kpi key="recv" icon="💰" color="#10b981" label={t("dashboard.receivables")} value={money(d.receivables_total)} sub={t("dashboard.totalReceivables")} warn={Number(d.receivables_total) > 0} />,
                  <Kpi key="pay" icon="💸" color="#ef4444" label={t("dashboard.payables")} value={money(d.payables_total)} sub={t("dashboard.totalPayables")} />,
                ],
              },
            ].map((g) => (
              <div className="kpi-group" key={g.title}>
                <div className="kpi-group-title"><span aria-hidden="true">{g.icon}</span>{g.title}</div>
                <div className="kpis">{g.items}</div>
              </div>
            ))
          )
        ))}

      {/* Row 1: Daily Sales & Top Products Charts */}
      {isManager && (
        <div className="grid-2">
          {/* Chart 1: Daily Sales Trend */}
          <div className="card card-pad">
            <div className="chart-header">
              <h3 className="chart-title">{t("dashboard.dailySalesShort")}</h3>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <div className="chart-pills">
                  <button
                    type="button"
                    className={`chart-pill ${salesMetric === "revenue" ? "active" : ""}`}
                    onClick={() => setSalesMetric("revenue")}
                  >
                    {t("dashboard.pillRevenue")}
                  </button>
                  <button
                    type="button"
                    className={`chart-pill ${salesMetric === "orders" ? "active" : ""}`}
                    onClick={() => setSalesMetric("orders")}
                  >
                    {t("dashboard.pillOrders")}
                  </button>
                </div>
                <div className="chart-pills">
                  <button
                    type="button"
                    className={`chart-pill ${salesChartType === "area" ? "active" : ""}`}
                    onClick={() => setSalesChartType("area")}
                    title={t("dashboard.pillAreaTitle")}
                  >
                    {t("dashboard.pillArea")}
                  </button>
                  <button
                    type="button"
                    className={`chart-pill ${salesChartType === "bar" ? "active" : ""}`}
                    onClick={() => setSalesChartType("bar")}
                    title={t("dashboard.pillBarTitle")}
                  >
                    {t("dashboard.pillBar")}
                  </button>
                </div>
              </div>
            </div>

            {salesChartData.length === 0 ? (
              <Empty>{t("dashboard.noConfirmedSales")}</Empty>
            ) : (
              <div className="chart-wrapper">
                <ResponsiveContainer width="100%" height="100%">
                  {salesChartType === "area" ? (
                    <AreaChart data={salesChartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="salesGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#2563eb" stopOpacity={0.4} />
                          <stop offset="95%" stopColor="#2563eb" stopOpacity={0.0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                      <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={{ stroke: "#e2e8f0" }} />
                      <YAxis tickFormatter={formatYAxisNumber} tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} width={45} />
                      <Tooltip content={<ChartTooltip unit={salesMetric === "revenue" ? "ج.م" : t("dashboard.orderUnit")} />} />
                      <Area
                        type="monotone"
                        dataKey={salesMetric === "revenue" ? "revenue" : "orders"}
                        name={salesMetric === "revenue" ? t("dashboard.sales") : t("dashboard.ordersCount")}
                        stroke="#2563eb"
                        strokeWidth={2.5}
                        fillOpacity={1}
                        fill="url(#salesGradient)"
                        activeDot={{ r: 6, fill: "#1d4ed8", stroke: "#fff", strokeWidth: 2 }}
                      />
                    </AreaChart>
                  ) : (
                    <BarChart data={salesChartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                      <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={{ stroke: "#e2e8f0" }} />
                      <YAxis tickFormatter={formatYAxisNumber} tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} width={45} />
                      <Tooltip content={<ChartTooltip unit={salesMetric === "revenue" ? "ج.م" : t("dashboard.orderUnit")} />} />
                      <Bar
                        dataKey={salesMetric === "revenue" ? "revenue" : "orders"}
                        name={salesMetric === "revenue" ? t("dashboard.sales") : t("dashboard.ordersCount")}
                        fill="#2563eb"
                        radius={[4, 4, 0, 0]}
                      />
                    </BarChart>
                  )}
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Chart 2: Top Selling Products */}
          <div className="card card-pad">
            <div className="chart-header">
              <h3 className="chart-title">{t("dashboard.topProducts5")}</h3>
              <div className="chart-pills">
                <button
                  type="button"
                  className={`chart-pill ${productMetric === "revenue" ? "active" : ""}`}
                  onClick={() => setProductMetric("revenue")}
                >
                  {t("dashboard.pillByRevenue")}
                </button>
                <button
                  type="button"
                  className={`chart-pill ${productMetric === "qty" ? "active" : ""}`}
                  onClick={() => setProductMetric("qty")}
                >
                  {t("dashboard.pillByQty")}
                </button>
              </div>
            </div>

            {topProductsChartData.length === 0 ? (
              <Empty>{t("dashboard.noData")}</Empty>
            ) : (
              <div className="chart-wrapper">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    layout="vertical"
                    data={topProductsChartData}
                    margin={{ top: 10, right: 20, left: 20, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                    <XAxis type="number" tickFormatter={formatYAxisNumber} tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "#475569" }} axisLine={false} tickLine={false} width={90} />
                    <Tooltip content={<ChartTooltip unit={productMetric === "revenue" ? "ج.م" : t("dashboard.pieceUnit")} />} />
                    <Bar
                      dataKey={productMetric === "revenue" ? "revenue" : "qty"}
                      name={productMetric === "revenue" ? t("dashboard.revenue") : t("dashboard.soldQty")}
                      fill="#10b981"
                      radius={[0, 4, 4, 0]}
                    >
                      {topProductsChartData.map((_, index) => (
                        <Cell key={`cell-${index}`} fill={PALETTE[index % PALETTE.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Row 2: Warehouse Inventory Distribution & Financial Balance */}
      {isManager && (
        <div className="grid-2">
          {/* Chart 3: Inventory Valuation by Warehouse (Donut Chart) */}
          <div className="card card-pad">
            <div className="chart-header">
              <h3 className="chart-title">{t("dashboard.inventoryByWarehouse")}</h3>
              <div className="chart-pills">
                <button
                  type="button"
                  className={`chart-pill ${inventoryMetric === "cost" ? "active" : ""}`}
                  onClick={() => setInventoryMetric("cost")}
                >
                  {t("dashboard.atCost")}
                </button>
                <button
                  type="button"
                  className={`chart-pill ${inventoryMetric === "sale" ? "active" : ""}`}
                  onClick={() => setInventoryMetric("sale")}
                >
                  {t("dashboard.pillAtExpected")}
                </button>
              </div>
            </div>

            {warehouseChartData.length === 0 ? (
              <Empty>{t("dashboard.noData")}</Empty>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", alignItems: "center", minHeight: 250 }}>
                <div style={{ width: "100%", height: 230, direction: "ltr" }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={warehouseChartData}
                        dataKey={inventoryMetric === "cost" ? "cost" : "sale"}
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        innerRadius={55}
                        outerRadius={85}
                        paddingAngle={3}
                      >
                        {warehouseChartData.map((entry, index) => (
                          <Cell key={`wh-cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip content={<ChartTooltip unit="ج.م" />} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="donut-legend">
                  {warehouseChartData.map((item, index) => (
                    <div key={`legend-${index}`} className="donut-legend-item">
                      <div className="donut-legend-left">
                        <span className="donut-color-dot" style={{ background: item.color }} />
                        <span style={{ fontWeight: 500, color: "var(--text)" }}>{item.name}</span>
                      </div>
                      <div style={{ textAlign: "left", direction: "ltr" }}>
                        <strong>{money(inventoryMetric === "cost" ? item.cost : item.sale)}</strong>
                        <span style={{ fontSize: 11, color: "var(--muted)", marginInlineStart: 4 }}>
                          ({inventoryMetric === "cost" ? item.costPercent : item.salePercent}%)
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Chart 4: Financial & Commercial Balance */}
          <div className="card card-pad">
            <div className="chart-header">
              <h3 className="chart-title">{t("dashboard.financialCompare")}</h3>
              <div className="chart-metric-badge">
                <span>{t("dashboard.sales")}:</span>
                <strong>{money(d?.sales_total ?? 0)}</strong>
              </div>
            </div>

            {!d ? (
              <Empty>{t("dashboard.noData")}</Empty>
            ) : (
              <div className="chart-wrapper">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart layout="vertical" data={financialCompareData} margin={{ top: 6, right: 72, left: 6, bottom: 0 }} barCategoryGap={10}>
                    <defs>
                      {[...new Set(financialCompareData.map((row) => row.color))].map((color) => (
                        <linearGradient key={color} id={`fcg-${color.slice(1)}`} x1="0" y1="0" x2="1" y2="0">
                          <stop offset="0%" stopColor={color} stopOpacity={0.5} />
                          <stop offset="100%" stopColor={color} stopOpacity={1} />
                        </linearGradient>
                      ))}
                    </defs>
                    <XAxis type="number" hide />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 12, fill: "#334155" }} axisLine={false} tickLine={false} width={112} />
                    <Tooltip cursor={{ fill: "rgba(37, 99, 235, 0.06)" }} content={<ChartTooltip unit="ج.م" />} />
                    <Bar
                      dataKey="value"
                      name={t("dashboard.compareValue")}
                      barSize={16}
                      radius={[0, 8, 8, 0]}
                      background={{ fill: "#f1f5f9", radius: 8 }}
                      isAnimationActive
                    >
                      {financialCompareData.map((row) => (
                        <Cell key={row.name} fill={`url(#fcg-${row.color.slice(1)})`} />
                      ))}
                      <LabelList dataKey="value" position="right" formatter={(label) => formatYAxisNumber(Number(label ?? 0))} style={{ fill: "#334155", fontSize: 11, fontWeight: 600 }} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      )}

    </>
  );
}
