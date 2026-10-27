import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { dayLabel, money, num } from "../format";
import { Link } from "react-router-dom";
import { useFetch } from "../hooks";
import type { Dashboard as DashboardData, InventoryValuationRow, LowStockItem, SalesSummary } from "../types";
import { Alert, Empty, Loading, PageHeader } from "../ui";

function Kpi({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className={`card kpi${warn ? " warn" : ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export default function Dashboard() {
  const { isManager } = useAuth();
  const { t } = useI18n();
  const [days, setDays] = useState(30);

  // Staff can only see the low-stock report; the financial reports need manager/admin.
  const dash = useFetch(() => (isManager ? api.get<DashboardData>(`/reports/dashboard?days=${days}`) : Promise.resolve(null)), `d${days}${isManager}`);
  const sales = useFetch(() => (isManager ? api.get<SalesSummary>(`/reports/sales-summary?top=5`) : Promise.resolve(null)), `s${isManager}`);
  const valuation = useFetch(
    () => (isManager ? api.get<InventoryValuationRow[]>("/reports/inventory-valuation") : Promise.resolve(null)),
    `v${isManager}`,
  );
  const low = useFetch(() => api.get<LowStockItem[]>("/reports/low-stock"), "low");

  const d = dash.data;
  const series = sales.data?.by_day ?? [];
  const maxDay = Math.max(1, ...series.map((x) => Number(x.total)));

  return (
    <>
      <PageHeader title={t("dashboard.title")}>
        {isManager && (
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label={t("dashboard.period")}>
            <option value={7}>{t("dashboard.last7")}</option>
            <option value={30}>{t("dashboard.last30")}</option>
            <option value={90}>{t("dashboard.last90")}</option>
          </select>
        )}
      </PageHeader>

      <Alert>{dash.error || sales.error || valuation.error || low.error}</Alert>
      {isManager && d && (d.stale_shifts ?? 0) > 0 && (
        <Alert kind="info">
          {num(d.stale_shifts)} {t("dashboard.staleShifts")}. <Link to="/shifts">{t("dashboard.reviewShifts")}</Link>
        </Alert>
      )}

      {isManager &&
        (dash.loading && !d ? (
          <Loading />
        ) : (
          d && (
            <div className="kpis">
              <Kpi label={t("dashboard.sales") + ` (${t("dashboard.last30")})`} value={money(d.sales_total)} sub={`${num(d.sales_orders_confirmed)} ${t("dashboard.confirmedOrder")}`} />
              <Kpi label={t("dashboard.purchases") + ` (${t("dashboard.last30")})`} value={money(d.purchases_total)} sub={`${num(d.purchase_orders_received)} ${t("dashboard.receivedOrder")}`} />
              <Kpi label={t("dashboard.inventoryValue")} value={money(d.inventory_cost_value)} sub={`${t("dashboard.inventorySaleValue")}: ${money(d.inventory_sale_value)}`} />
              <Kpi label={t("dashboard.profitEstimate")} value={money(Number(d.inventory_sale_value) - Number(d.inventory_cost_value))} sub={`Margin: ${d.inventory_cost_value && Number(d.inventory_cost_value) > 0 ? (((Number(d.inventory_sale_value) - Number(d.inventory_cost_value)) / Number(d.inventory_cost_value)) * 100).toFixed(1) : 0}%`} />
              <Kpi label={t("dashboard.activeProducts")} value={num(d.products)} sub={`${num(d.warehouses)} ${t("dashboard.warehouses")} · ${num(d.suppliers)} ${t("dashboard.suppliers")} · ${num(d.customers)} ${t("dashboard.customers")}`} />
              <Kpi label={t("dashboard.returns")} value={money(d.sales_returns_total)} sub={`${t("dashboard.purchaseReturn")}: ${money(d.purchase_returns_total)}`} />
              <Kpi label={t("dashboard.receivables")} value={money(d.receivables_total)} sub={t("dashboard.totalReceivables")} warn={Number(d.receivables_total) > 0} />
              <Kpi label={t("dashboard.payables")} value={money(d.payables_total)} sub={t("dashboard.totalPayables")} />
              <Kpi label={t("dashboard.lowStock")} value={num(d.low_stock_products)} warn={d.low_stock_products > 0} />
              <Kpi label={t("dashboard.draftOrders")} value={num(d.draft_sales_orders + d.draft_purchase_orders)} sub={`${num(d.draft_sales_orders)} ${t("dashboard.salesOrders")} · ${num(d.draft_purchase_orders)} ${t("dashboard.purchaseOrders")}`} />
            </div>
          )
        ))}

      {isManager && (
        <div className="grid-2">
          <div className="card card-pad">
            <h3>{t("dashboard.dailySales")}</h3>
            {series.length === 0 ? (
              <Empty>{t("dashboard.noConfirmedSales")}</Empty>
            ) : (
              <div className="bars" role="img" aria-label={t("dashboard.dailySalesShort")}>
                {series.map((x) => (
                  <div className="bar-col" key={x.day} title={`${dayLabel(x.day)}: ${money(x.total)}`}>
                    <div className="bar" style={{ height: `${(Number(x.total) / maxDay) * 100}%` }} />
                    <div className="bar-label">{dayLabel(x.day)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="card card-pad">
            <h3>{t("dashboard.topProducts")}</h3>
            {sales.data && sales.data.top_products.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t("dashboard.product")}</th>
                      <th className="num">{t("dashboard.qty")}</th>
                      <th className="num">{t("dashboard.revenue")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sales.data.top_products.map((p) => (
                      <tr key={p.product_id}>
                        <td>{p.name}</td>
                        <td className="num">{num(p.quantity_sold)}</td>
                        <td className="num">{money(p.revenue)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>{t("dashboard.noData")}</Empty>
            )}
          </div>
        </div>
      )}

      <div className="grid-2">
        <div className="card card-pad">
          <h3>{t("dashboard.lowStockAlerts")}</h3>
          {low.loading && !low.data ? (
            <Loading />
          ) : low.data && low.data.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("dashboard.productCol")}</th>
                    <th className="num">{t("dashboard.available")}</th>
                    <th className="num">{t("dashboard.reorderLevel")}</th>
                    <th className="num">{t("dashboard.shortfall")}</th>
                  </tr>
                </thead>
                <tbody>
                  {low.data.map((p) => (
                    <tr key={p.id}>
                      <td>
                        {p.name} <span className="muted">({p.sku})</span>
                      </td>
                      <td className="num low">{num(p.quantity)}</td>
                      <td className="num">{num(p.reorder_level)}</td>
                      <td className="num">{num(p.shortfall)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>{t("dashboard.allAboveReorder")}</Empty>
          )}
        </div>

        {isManager && (
          <div className="card card-pad">
            <h3>{t("dashboard.inventoryByWarehouse")}</h3>
            {valuation.data && valuation.data.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t("dashboard.warehouse")}</th>
                      <th className="num">{t("dashboard.units")}</th>
                      <th className="num">{t("dashboard.atCost")}</th>
                      <th className="num">{t("dashboard.atSale")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {valuation.data.map((r) => (
                      <tr key={r.warehouse_id ?? "none"}>
                        <td>{r.warehouse_name ?? t("dashboard.noWarehouse")}</td>
                        <td className="num">{num(r.units)}</td>
                        <td className="num">{money(r.cost_value)}</td>
                        <td className="num">{money(r.sale_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>{t("dashboard.noData")}</Empty>
            )}
          </div>
        )}
      </div>
    </>
  );
}
