import { useState } from "react";
import { api, qs } from "../api";
import { dayLabel, money, num } from "../format";
import { useAction, useFetch } from "../hooks";
import { useI18n } from "../i18n";
import type { AgingReport, BalancesReport, DayTotal, InventoryValuationRow, LowStockItem, ProfitSummary, PurchasesSummary, SalesRep, SalesSummary } from "../types";
import { Alert, Empty, Loading, PageHeader } from "../ui";

/** YYYY-MM-DD in the browser's local calendar (what the user sees), not UTC. */
function isoDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDay(d);
}

/** حالة الفترة المشتركة لتقارير التاريخ (من/إلى + أنماط سريعة + تصدير). */
function useReportRange() {
  const [from, setFrom] = useState(daysAgo(29));
  const [to, setTo] = useState(isoDay(new Date()));
  const download = useAction();
  const rangeValid = !!from && !!to && from <= to;
  const range = qs({ date_from: from, date_to: to });
  const preset = (days: number) => {
    setFrom(daysAgo(days - 1));
    setTo(isoDay(new Date()));
  };
  const thisMonth = () => {
    const now = new Date();
    setFrom(isoDay(new Date(now.getFullYear(), now.getMonth(), 1)));
    setTo(isoDay(now));
  };
  const exportFile = (path: string, name: string) => void download.run(() => api.download(path, name));
  return { from, setFrom, to, setTo, range, rangeValid, preset, thisMonth, exportFile, download };
}

/** شريط الفترة المشترك — من/إلى + أنماط سريعة. */
function RangeBar({ from, setFrom, to, setTo, preset, thisMonth }: ReturnType<typeof useReportRange>) {
  const { t } = useI18n();
  return (
    <div className="card card-pad range-bar">
      <label className="range-field">
        <span className="field-label">{t("من تاريخ")}</span>
        <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
      </label>
      <label className="range-field">
        <span className="field-label">{t("إلى تاريخ")}</span>
        <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
      </label>
      <div className="range-presets">
        <button className="btn btn-sm" onClick={() => preset(7)}>{t("آخر 7 أيام")}</button>
        <button className="btn btn-sm" onClick={() => preset(30)}>{t("آخر 30 يوماً")}</button>
        <button className="btn btn-sm" onClick={() => preset(90)}>{t("آخر 90 يوماً")}</button>
        <button className="btn btn-sm" onClick={thisMonth}>{t("هذا الشهر")}</button>
      </div>
    </div>
  );
}

/** كل تقرير في صفحة مستقلة — تُعرض كعناصر في القائمة المنسدلة «التقارير» بالشريط الجانبي. */
export function ReportsSales() {
  const { t } = useI18n();
  const r = useReportRange();
  return (
    <>
      <PageHeader title={t("تقرير المبيعات")} />
      <RangeBar {...r} />
      <Alert>{r.download.error}</Alert>
      {r.rangeValid ? <SalesTab from={r.from} to={r.to} onExport={r.exportFile} busy={r.download.busy} /> : <Alert>{t("اختر فترة صحيحة: تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.")}</Alert>}
    </>
  );
}

export function ReportsProfit() {
  const { t } = useI18n();
  const r = useReportRange();
  return (
    <>
      <PageHeader title={t("تقرير الأرباح")} />
      <RangeBar {...r} />
      <Alert>{r.download.error}</Alert>
      {r.rangeValid ? <ProfitTab range={r.range} from={r.from} to={r.to} onExport={r.exportFile} busy={r.download.busy} /> : <Alert>{t("اختر فترة صحيحة: تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.")}</Alert>}
    </>
  );
}

export function ReportsPurchases() {
  const { t } = useI18n();
  const r = useReportRange();
  return (
    <>
      <PageHeader title={t("تقرير المشتريات")} />
      <RangeBar {...r} />
      <Alert>{r.download.error}</Alert>
      {r.rangeValid ? <PurchasesTab range={r.range} from={r.from} to={r.to} onExport={r.exportFile} busy={r.download.busy} /> : <Alert>{t("اختر فترة صحيحة: تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.")}</Alert>}
    </>
  );
}

export function ReportsInventory() {
  const { t } = useI18n();
  const r = useReportRange();
  return (
    <>
      <PageHeader title={t("تقرير المخزون")} />
      <Alert>{r.download.error}</Alert>
      <InventoryTab onExport={r.exportFile} busy={r.download.busy} />
    </>
  );
}

export function ReportsReceivables() {
  const { t } = useI18n();
  const r = useReportRange();
  return (
    <>
      <PageHeader title={t("تقرير مستحقات العملاء")} />
      <Alert>{r.download.error}</Alert>
      <BalancesTab key="receivables" kind="receivables" onExport={r.exportFile} busy={r.download.busy} />
    </>
  );
}

export function ReportsPayables() {
  const { t } = useI18n();
  const r = useReportRange();
  return (
    <>
      <PageHeader title={t("تقرير مستحقات الموردين")} />
      <Alert>{r.download.error}</Alert>
      <BalancesTab key="payables" kind="payables" onExport={r.exportFile} busy={r.download.busy} />
    </>
  );
}

interface TabProps {
  range: string;
  from: string;
  to: string;
  onExport: (path: string, name: string) => void;
  busy: boolean;
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

function ExportButton({ onClick, busy, children }: { onClick: () => void; busy: boolean; children: string }) {
  const { t } = useI18n();
  return (
    <button className="btn btn-primary" disabled={busy} onClick={onClick}>
      {busy ? t("جارٍ التجهيز…") : `⬇ ${children}`}
    </button>
  );
}

function DailyBars({ series, label }: { series: DayTotal[]; label: string }) {
  const { t } = useI18n();
  const max = Math.max(1, ...series.map((x) => Number(x.total)));
  return (
    <div className="card card-pad" style={{ marginBottom: 18 }}>
      <h3>{label}</h3>
      {series.length === 0 ? (
        <Empty>{t("لا توجد بيانات في هذه الفترة")}</Empty>
      ) : (
        <div className="bars" role="img" aria-label={label}>
          {series.map((x) => (
            <div className="bar-col" key={x.day} title={`${dayLabel(x.day)}: ${money(x.total)} (${num(x.orders)} ${t("أمر")})`}>
              <div className="bar" style={{ height: `${(Number(x.total) / max) * 100}%` }} />
              <div className="bar-label">{dayLabel(x.day)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RankTable({ title, headers, rows }: { title: string; headers: string[]; rows: (string | number)[][] }) {
  const { t } = useI18n();
  return (
    <div className="card card-pad">
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <Empty>{t("لا بيانات")}</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {headers.map((h, i) => (
                  <th key={h} className={i === 0 ? undefined : "num"}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((c, ci) => (
                    <td key={ci} className={ci === 0 ? undefined : "num"}>
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SalesTab({ from, to, onExport, busy }: Omit<TabProps, "range">) {
  const { t } = useI18n();
  // classification filter options
  const customers = useFetch(() => api.get<{ id: number; name: string }[]>("/customers?limit=500"), "sales-custs");
  const suppliers = useFetch(() => api.get<{ id: number; name: string }[]>("/suppliers?limit=500"), "sales-sups");
  const products = useFetch(() => api.get<{ id: number; name: string; sku: string }[]>("/products?limit=1000"), "sales-prods");
  const users = useFetch(() => api.get<{ id: number; username: string; full_name: string }[]>("/auth/users"), "sales-users");
  const reps = useFetch(() => api.get<SalesRep[]>("/reps"), "sales-reps");

  const [customerId, setCustomerId] = useState("");
  const [productId, setProductId] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [userId, setUserId] = useState("");
  const [repId, setRepId] = useState("");

  const fq = qs({
    date_from: from,
    date_to: to,
    top: 10,
    ...(customerId ? { customer_id: customerId } : {}),
    ...(productId ? { product_id: productId } : {}),
    ...(supplierId ? { supplier_id: supplierId } : {}),
    ...(userId ? { user_id: userId } : {}),
    ...(repId ? { rep_id: repId } : {}),
  });
  const data = useFetch(() => api.get<SalesSummary>(`/reports/sales-summary${fq}`), `sales${fq}`);
  const s = data.data;
  const avg = s && s.orders > 0 ? Number(s.total) / s.orders : 0;

  const Filter = ({ icon, label, value, onChange, options }: { icon: string; label: string; value: string; onChange: (v: string) => void; options: { id: number; label: string }[] }) => (
    <span className={`rf-pill${value ? " active" : ""}`}>
      <span className="rf-icon">{icon}</span>
      <span className="rf-label">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("الكل")}</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
    </span>
  );

  return (
    <>
      <div className="report-filters">
        <span className="rf-title">{t("🏷️ تصنيف التقرير")}</span>
        <Filter icon="👤" label={t("العميل")} value={customerId} onChange={setCustomerId} options={(customers.data ?? []).map((c) => ({ id: c.id, label: c.name }))} />
        <Filter icon="📦" label={t("الصنف")} value={productId} onChange={setProductId} options={(products.data ?? []).map((p) => ({ id: p.id, label: `${p.name} (${p.sku})` }))} />
        <Filter icon="🏭" label={t("مورد الصنف")} value={supplierId} onChange={setSupplierId} options={(suppliers.data ?? []).map((x) => ({ id: x.id, label: x.name }))} />
        <Filter icon="🧾" label={t("البائع / المستخدم")} value={userId} onChange={setUserId} options={(users.data ?? []).map((u) => ({ id: u.id, label: u.full_name || u.username }))} />
        <Filter icon="🧑‍💼" label={t("المندوب")} value={repId} onChange={setRepId} options={(reps.data ?? []).map((r) => ({ id: r.id, label: r.name }))} />
        <button type="button" className="rf-clear" onClick={() => { setCustomerId(""); setProductId(""); setSupplierId(""); setUserId(""); setRepId(""); }} disabled={!customerId && !productId && !supplierId && !userId && !repId}>
          {t("✕ مسح التصنيف")}
        </button>
      </div>
      <div className="page-actions" style={{ marginBottom: 14 }}>
        <ExportButton busy={busy} onClick={() => onExport(`/reports/sales-summary/xlsx${fq}`, `report-sales-${from}_${to}.xlsx`)}>
          {t("تصدير Excel")}
        </ExportButton>
      </div>
      <Alert>{data.error}</Alert>
      {data.loading && !s ? (
        <Loading />
      ) : (
        s && (
          <>
            <div className="kpis">
              <Kpi label={t("إجمالي المبيعات")} value={money(s.total)} />
              <Kpi label={t("عدد الأوامر المؤكدة")} value={num(s.orders)} />
              <Kpi label={t("متوسط قيمة الأمر")} value={money(avg)} />
            </div>
            <DailyBars series={s.by_day} label={t("المبيعات اليومية")} />
            <div className="grid-2">
              <RankTable
                title={t("الأكثر مبيعاً")}
                headers={[t("المنتج"), t("الكمية"), t("الإيراد")]}
                rows={s.top_products.map((p) => [`${p.name} (${p.sku})`, num(p.quantity_sold), money(p.revenue)])}
              />
              <RankTable
                title={t("أفضل العملاء")}
                headers={[t("العميل"), t("الأوامر"), t("الإجمالي")]}
                rows={s.by_customer.map((c) => [c.customer_name, num(c.orders), money(c.total)])}
              />
            </div>
            <RankTable
              title={t("المبيعات حسب الكاشير")}
              headers={[t("الكاشير"), t("الأوامر"), t("الإجمالي")]}
              rows={s.by_cashier.map((c) => [c.username ?? t("غير مسجّل"), num(c.orders), money(c.total)])}
            />
            <RankTable
              title={t("المبيعات حسب مورد الصنف")}
              headers={[t("المورد"), t("الأوامر"), t("الإجمالي")]}
              rows={s.by_product_supplier.map((c) => [c.supplier_name, num(c.orders), money(c.total)])}
            />
          </>
        )
      )}
    </>
  );
}

function ProfitTab({ range, from, to, onExport, busy }: TabProps) {
  const { t } = useI18n();
  const q = qs({ date_from: from, date_to: to });
  const data = useFetch(() => api.get<ProfitSummary>(`/reports/profit${q}`), `profit${q}`);
  const s = data.data;
  const pct = (v: string | null) => (v === null ? "—" : `${v}%`);

  return (
    <>
      <div className="page-actions" style={{ marginBottom: 14 }}>
        <ExportButton busy={busy} onClick={() => onExport(`/reports/profit/xlsx${range}`, `report-profit-${from}_${to}.xlsx`)}>
          {t("تصدير Excel")}
        </ExportButton>
      </div>
      <Alert>{data.error}</Alert>
      {data.loading && !s ? (
        <Loading />
      ) : (
        s && (
          <>
            <div className="kpis">
              <Kpi label={t("صافي الإيراد")} value={money(s.revenue)} />
              <Kpi label={t("تكلفة البضاعة المباعة")} value={money(s.cost)} />
              <Kpi label={t("مجمل الربح")} value={money(s.profit)} />
              <Kpi label={t("هامش الربح")} value={pct(s.margin_pct)} />
            </div>
            <p className="muted">
              {t("المبيعات ")}{money(s.sales)}{t(" − المرتجعات ")}{money(s.returns)}{t(". التكلفة محسوبة بسعر التكلفة وقت البيع.")}
            </p>
            <RankTable
              title={t("الربح حسب المنتج")}
              headers={[t("المنتج"), t("الكمية"), t("الإيراد"), t("التكلفة"), t("الربح"), t("الهامش")]}
              rows={s.by_product.map((r) => [`${r.name} (${r.sku})`, num(r.quantity), money(r.revenue), money(r.cost), money(r.profit), pct(r.margin_pct)])}
            />
          </>
        )
      )}
    </>
  );
}

function PurchasesTab({ range, from, to, onExport, busy }: TabProps) {
  const { t } = useI18n();
  const q = qs({ date_from: from, date_to: to, top: 10 });
  const data = useFetch(() => api.get<PurchasesSummary>(`/reports/purchases-summary${q}`), `purch${q}`);
  const s = data.data;
  const avg = s && s.orders > 0 ? Number(s.total) / s.orders : 0;

  return (
    <>
      <div className="page-actions" style={{ marginBottom: 14 }}>
        <ExportButton busy={busy} onClick={() => onExport(`/reports/purchases-summary/xlsx${range}`, `report-purchases-${from}_${to}.xlsx`)}>
          {t("تصدير Excel")}
        </ExportButton>
      </div>
      <Alert>{data.error}</Alert>
      {data.loading && !s ? (
        <Loading />
      ) : (
        s && (
          <>
            <div className="kpis">
              <Kpi label={t("إجمالي المشتريات")} value={money(s.total)} />
              <Kpi label={t("عدد الأوامر المستلمة")} value={num(s.orders)} />
              <Kpi label={t("متوسط قيمة الأمر")} value={money(avg)} />
            </div>
            <DailyBars series={s.by_day} label={t("المشتريات اليومية (حسب تاريخ الاستلام)")} />
            <div className="grid-2">
              <RankTable
                title={t("الأكثر شراءً")}
                headers={[t("المنتج"), t("الكمية"), t("الإنفاق")]}
                rows={s.top_products.map((p) => [`${p.name} (${p.sku})`, num(p.quantity_bought), money(p.spend)])}
              />
              <RankTable
                title={t("أكبر الموردين")}
                headers={[t("المورد"), t("الأوامر"), t("الإجمالي")]}
                rows={s.by_supplier.map((x) => [x.supplier_name, num(x.orders), money(x.total)])}
              />
            </div>
          </>
        )
      )}
    </>
  );
}

function InventoryTab({ onExport, busy }: { onExport: (path: string, name: string) => void; busy: boolean }) {
  const { t } = useI18n();
  const valuation = useFetch(() => api.get<InventoryValuationRow[]>("/reports/inventory-valuation"), "inv-val");
  const low = useFetch(() => api.get<LowStockItem[]>("/reports/low-stock"), "inv-low");
  const totalCost = (valuation.data ?? []).reduce((s, r) => s + Number(r.cost_value), 0);
  const totalSale = (valuation.data ?? []).reduce((s, r) => s + Number(r.sale_value), 0);

  return (
    <>
      <div className="page-actions" style={{ marginBottom: 14 }}>
        <ExportButton busy={busy} onClick={() => onExport("/reports/inventory-valuation/xlsx", "report-inventory-valuation.xlsx")}>
          {t("تصدير قيمة المخزون Excel")}
        </ExportButton>
        <ExportButton busy={busy} onClick={() => onExport("/reports/low-stock/xlsx", "report-low-stock.xlsx")}>
          {t("تصدير النقص Excel")}
        </ExportButton>
      </div>
      <Alert>{valuation.error || low.error}</Alert>
      {valuation.loading && !valuation.data ? (
        <Loading />
      ) : (
        <div className="kpis">
          <Kpi label={t("قيمة المخزون بالتكلفة")} value={money(totalCost)} />
          <Kpi label={t("قيمة المخزون بسعر البيع")} value={money(totalSale)} sub={`${t("هامش محتمل: ")}${money(totalSale - totalCost)}`} />
          <Kpi label={t("منتجات تحت حد الطلب")} value={num(low.data?.length ?? 0)} />
        </div>
      )}
      <div className="grid-2">
        <RankTable
          title={t("قيمة المخزون لكل مخزن")}
          headers={[t("المخزن"), t("الوحدات"), t("بالتكلفة"), t("بسعر البيع")]}
          rows={(valuation.data ?? []).map((r) => [r.warehouse_name ?? t("بدون مخزن"), num(r.units), money(r.cost_value), money(r.sale_value)])}
        />
        <RankTable
          title={t("نقص المخزون")}
          headers={[t("المنتج"), t("المتاح"), t("حد الطلب"), t("العجز")]}
          rows={(low.data ?? []).map((p) => [`${p.name} (${p.sku})`, num(p.quantity), num(p.reorder_level), num(p.shortfall)])}
        />
      </div>
    </>
  );
}

function BalancesTab({ kind, onExport, busy }: { kind: "receivables" | "payables"; onExport: (path: string, name: string) => void; busy: boolean }) {
  const { t } = useI18n();
  const isRec = kind === "receivables";
  const [view, setView] = useState<"balances" | "aging">("balances");
  const data = useFetch(() => api.get<BalancesReport>(`/reports/${kind}`), `bal-${kind}`);
  const r = data.data;
  const suffix = view === "aging" ? "/aging" : "";
  return (
    <>
      <div className="page-actions" style={{ marginBottom: 14 }}>
        <select value={view} onChange={(e) => setView(e.target.value as typeof view)} aria-label={t("نوع العرض")}>
          <option value="balances">{t("الأرصدة")}</option>
          <option value="aging">{t("أعمار الديون")}</option>
        </select>
        <ExportButton busy={busy} onClick={() => onExport(`/reports/${kind}${suffix}/xlsx`, `report-${kind}${view === "aging" ? "-aging" : ""}.xlsx`)}>
          {t("تصدير Excel")}
        </ExportButton>
      </div>
      {view === "aging" && <AgingTable kind={kind} />}
      <Alert>{data.error}</Alert>
      {view === "balances" && (data.loading && !r ? (
        <Loading />
      ) : (
        r && (
          <>
            <div className="kpis">
              <Kpi label={isRec ? t("إجمالي المستحق على العملاء") : t("إجمالي المستحق للموردين")} value={money(r.total)} sub={`${num(r.rows.filter((x) => Number(x.balance) > 0).length)} ${isRec ? t("عميل") : t("مورد")} ${t("عليهم رصيد")}`} />
            </div>
            <RankTable
              title={isRec ? t("أرصدة العملاء (الأعلى أولاً)") : t("أرصدة الموردين (الأعلى أولاً)")}
              headers={[isRec ? t("العميل") : t("المورد"), t("الهاتف"), t("الرصيد")]}
              rows={r.rows.map((x) => [x.name, x.phone ?? "—", money(x.balance)])}
            />
          </>
        )
      ))}
    </>
  );
}

function AgingTable({ kind }: { kind: "receivables" | "payables" }) {
  const { t } = useI18n();
  const data = useFetch(() => api.get<AgingReport>(`/reports/${kind}/aging`), `aging-${kind}`);
  const a = data.data;
  const isRec = kind === "receivables";
  if (data.error) return <Alert>{data.error}</Alert>;
  if (!a) return <Loading />;
  const cols = [t("أول المدة"), t("0–30 يوماً"), t("31–60 يوماً"), t("61–90 يوماً"), t("أكثر من 90"), t("الإجمالي")];
  const sum = [a.total_opening, a.total_current, a.total_d31_60, a.total_d61_90, a.total_d90_plus, a.total_total];
  return (
    <div className="card card-pad">
      <h3>{isRec ? t("أعمار ديون العملاء") : t("أعمار ديون الموردين")} ({t("حتى ")}{a.as_of})</h3>
      {a.rows.length === 0 ? (
        <Empty>{t("لا توجد مبالغ مستحقة")}</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{isRec ? t("العميل") : t("المورد")}</th>
                {cols.map((c) => (
                  <th key={c} className="num">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {a.rows.map((r) => (
                <tr key={r.party_id}>
                  <td>{r.name}</td>
                  {[r.opening, r.current, r.d31_60, r.d61_90, r.d90_plus, r.total].map((v, i) => (
                    <td key={i} className="num" style={i === 4 && Number(v) > 0 ? { color: "var(--danger, #b42318)", fontWeight: 600 } : undefined}>
                      {Number(v) ? money(v) : "—"}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td>
                  <b>{t("الإجمالي")}</b>
                </td>
                {sum.map((v, i) => (
                  <td key={i} className="num">
                    <b>{money(v)}</b>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ marginBottom: 0, fontSize: 12 }}>{t("العمر = الأيام منذ تأكيد الفاتورة. تُسدَّد الأقدم أولاً، والأرصدة الدائنة لا تُحتسب.")}</p>
    </div>
  );
}
