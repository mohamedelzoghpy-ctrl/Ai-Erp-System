import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { dayLabel, money, num } from "../format";
import { Link } from "react-router-dom";
import { useFetch } from "../hooks";
import type { Dashboard as DashboardData, InventoryValuationRow, LowStockItem, ProfitSummary, SalesSummary } from "../types";
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
  const [days, setDays] = useState(30);

  // Staff can only see the low-stock report; the financial reports need manager/admin.
  const dash = useFetch(() => (isManager ? api.get<DashboardData>(`/reports/dashboard?days=${days}`) : Promise.resolve(null)), `d${days}${isManager}`);
  const sales = useFetch(() => (isManager ? api.get<SalesSummary>(`/reports/sales-summary?top=5`) : Promise.resolve(null)), `s${isManager}`);
  const valuation = useFetch(
    () => (isManager ? api.get<InventoryValuationRow[]>("/reports/inventory-valuation") : Promise.resolve(null)),
    `v${isManager}`,
  );
  const profit = useFetch(
    () => (isManager ? api.get<ProfitSummary>("/reports/profit") : Promise.resolve(null)),
    `profit${isManager}`,
  );
  const low = useFetch(() => api.get<LowStockItem[]>("/reports/low-stock"), "low");

  const d = dash.data;
  const series = sales.data?.by_day ?? [];
  const maxDay = Math.max(1, ...series.map((x) => Number(x.total)));

  return (
    <>
      <PageHeader title="لوحة التحكم">
        {isManager && (
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="الفترة">
            <option value={7}>آخر 7 أيام</option>
            <option value={30}>آخر 30 يوماً</option>
            <option value={90}>آخر 90 يوماً</option>
          </select>
        )}
      </PageHeader>

      <Alert>{dash.error || sales.error || valuation.error || profit.error || low.error}</Alert>
      {isManager && d && (d.stale_shifts ?? 0) > 0 && (
        <Alert kind="info">
          يوجد {num(d.stale_shifts)} وردية مفتوحة منذ وقت طويل. <Link to="/shifts">راجع الورديات وأغلقها</Link>
        </Alert>
      )}

      {isManager &&
        (dash.loading && !d ? (
          <Loading />
        ) : (
          d && (
            <div className="kpis">
              <Kpi label={`المبيعات (آخر ${d.period_days} يوماً)`} value={money(d.sales_total)} sub={`${num(d.sales_orders_confirmed)} أمر مؤكد`} />
              <Kpi label={`المشتريات (آخر ${d.period_days} يوماً)`} value={money(d.purchases_total)} sub={`${num(d.purchase_orders_received)} أمر مستلم`} />
              <Kpi label="قيمة المخزون (بالتكلفة)" value={money(d.inventory_cost_value)} sub={`بسعر البيع: ${money(d.inventory_sale_value)}`} />
              <Kpi label="تقدير الربحية" value={money(profit.data?.profit ?? "0")} sub={profit.data?.margin_pct ? `Margin: ${profit.data.margin_pct}%` : undefined} />
              <Kpi label="منتجات active" value={num(d.products)} sub={`${num(d.warehouses)} مخزن · ${num(d.suppliers)} مورد · ${num(d.customers)} عميل`} />
              <Kpi label="المرتجعات" value={money(d.sales_returns_total)} sub={`مرتجع مشتريات: ${money(d.purchase_returns_total)}`} />
              <Kpi label="مستحقات على العملاء" value={money(d.receivables_total)} sub="إجمالي الذمم المدينة" warn={Number(d.receivables_total) > 0} />
              <Kpi label="مستحقات للموردين" value={money(d.payables_total)} sub="إجمالي الذمم الدائنة" />
              <Kpi label="تحت حد إعادة الطلب" value={num(d.low_stock_products)} warn={d.low_stock_products > 0} />
              <Kpi label="أوامر معلّقة (مسودة)" value={num(d.draft_sales_orders + d.draft_purchase_orders)} sub={`${num(d.draft_sales_orders)} بيع · ${num(d.draft_purchase_orders)} شراء`} />
            </div>
          )
        ))}

      {isManager && (
        <div className="grid-2">
          <div className="card card-pad">
            <h3>المبيعات اليومية (آخر 30 يوماً)</h3>
            {series.length === 0 ? (
              <Empty>لا توجد مبيعات مؤكدة في هذه الفترة</Empty>
            ) : (
              <div className="bars" role="img" aria-label="مبيعات يومية">
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
            <h3>الأكثر مبيعاً</h3>
            {sales.data && sales.data.top_products.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>المنتج</th>
                      <th className="num">الكمية</th>
                      <th className="num">الإيراد</th>
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
              <Empty>لا بيانات</Empty>
            )}
          </div>
        </div>
      )}

      <div className="grid-2">
        <div className="card card-pad">
          <h3>تنبيهات نقص المخزون</h3>
          {low.loading && !low.data ? (
            <Loading />
          ) : low.data && low.data.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>المنتج</th>
                    <th className="num">المتاح</th>
                    <th className="num">حد الطلب</th>
                    <th className="num">العجز</th>
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
            <Empty>كل المنتجات فوق حد إعادة الطلب ✓</Empty>
          )}
        </div>

        {isManager && (
          <div className="card card-pad">
            <h3>قيمة المخزون لكل مخزن</h3>
            {valuation.data && valuation.data.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>المخزن</th>
                      <th className="num">الوحدات</th>
                      <th className="num">بالتكلفة</th>
                      <th className="num">بسعر البيع</th>
                    </tr>
                  </thead>
                  <tbody>
                    {valuation.data.map((r) => (
                      <tr key={r.warehouse_id ?? "none"}>
                        <td>{r.warehouse_name ?? "بدون مخزن"}</td>
                        <td className="num">{num(r.units)}</td>
                        <td className="num">{money(r.cost_value)}</td>
                        <td className="num">{money(r.sale_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>لا بيانات</Empty>
            )}
          </div>
        )}
      </div>
    </>
  );
}
