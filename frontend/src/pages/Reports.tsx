import { useState } from "react";
import { api, qs } from "../api";
import { dayLabel, money, num } from "../format";
import { useAction, useFetch } from "../hooks";
import type { BalancesReport, DayTotal, InventoryValuationRow, LowStockItem, PurchasesSummary, SalesSummary } from "../types";
import { Alert, Empty, Loading, PageHeader } from "../ui";

type Tab = "sales" | "purchases" | "inventory" | "receivables" | "payables";

const TABS: { id: Tab; label: string }[] = [
  { id: "sales", label: "المبيعات" },
  { id: "purchases", label: "المشتريات" },
  { id: "inventory", label: "المخزون" },
  { id: "receivables", label: "مستحقات العملاء" },
  { id: "payables", label: "مستحقات الموردين" },
];

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

export default function Reports() {
  const [tab, setTab] = useState<Tab>("sales");
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
  const usesRange = tab === "sales" || tab === "purchases";

  return (
    <>
      <PageHeader title="التقارير المفصلة" />

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={`tab${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {usesRange && (
        <div className="card card-pad range-bar">
          <label className="range-field">
            <span className="field-label">من تاريخ</span>
            <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="range-field">
            <span className="field-label">إلى تاريخ</span>
            <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
          </label>
          <div className="range-presets">
            <button className="btn btn-sm" onClick={() => preset(7)}>
              آخر 7 أيام
            </button>
            <button className="btn btn-sm" onClick={() => preset(30)}>
              آخر 30 يوماً
            </button>
            <button className="btn btn-sm" onClick={() => preset(90)}>
              آخر 90 يوماً
            </button>
            <button className="btn btn-sm" onClick={thisMonth}>
              هذا الشهر
            </button>
          </div>
        </div>
      )}

      <Alert>{download.error}</Alert>
      {usesRange && !rangeValid && <Alert>اختر فترة صحيحة: تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.</Alert>}

      {tab === "sales" && rangeValid && <SalesTab range={range} from={from} to={to} onExport={exportFile} busy={download.busy} />}
      {tab === "purchases" && rangeValid && <PurchasesTab range={range} from={from} to={to} onExport={exportFile} busy={download.busy} />}
      {tab === "inventory" && <InventoryTab onExport={exportFile} busy={download.busy} />}
      {(tab === "receivables" || tab === "payables") && <BalancesTab kind={tab} onExport={exportFile} busy={download.busy} />}
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
  return (
    <button className="btn btn-primary" disabled={busy} onClick={onClick}>
      {busy ? "جارٍ التجهيز…" : `⬇ ${children}`}
    </button>
  );
}

function DailyBars({ series, label }: { series: DayTotal[]; label: string }) {
  const max = Math.max(1, ...series.map((x) => Number(x.total)));
  return (
    <div className="card card-pad" style={{ marginBottom: 18 }}>
      <h3>{label}</h3>
      {series.length === 0 ? (
        <Empty>لا توجد بيانات في هذه الفترة</Empty>
      ) : (
        <div className="bars" role="img" aria-label={label}>
          {series.map((x) => (
            <div className="bar-col" key={x.day} title={`${dayLabel(x.day)}: ${money(x.total)} (${num(x.orders)} أمر)`}>
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
  return (
    <div className="card card-pad">
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <Empty>لا بيانات</Empty>
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

function SalesTab({ range, from, to, onExport, busy }: TabProps) {
  const q = qs({ date_from: from, date_to: to, top: 10 });
  const data = useFetch(() => api.get<SalesSummary>(`/reports/sales-summary${q}`), `sales${q}`);
  const s = data.data;
  const avg = s && s.orders > 0 ? Number(s.total) / s.orders : 0;

  return (
    <>
      <div className="page-actions" style={{ marginBottom: 14 }}>
        <ExportButton busy={busy} onClick={() => onExport(`/reports/sales-summary/xlsx${range}`, `report-sales-${from}_${to}.xlsx`)}>
          تصدير Excel
        </ExportButton>
      </div>
      <Alert>{data.error}</Alert>
      {data.loading && !s ? (
        <Loading />
      ) : (
        s && (
          <>
            <div className="kpis">
              <Kpi label="إجمالي المبيعات" value={money(s.total)} />
              <Kpi label="عدد الأوامر المؤكدة" value={num(s.orders)} />
              <Kpi label="متوسط قيمة الأمر" value={money(avg)} />
            </div>
            <DailyBars series={s.by_day} label="المبيعات اليومية" />
            <div className="grid-2">
              <RankTable
                title="الأكثر مبيعاً"
                headers={["المنتج", "الكمية", "الإيراد"]}
                rows={s.top_products.map((p) => [`${p.name} (${p.sku})`, num(p.quantity_sold), money(p.revenue)])}
              />
              <RankTable
                title="أفضل العملاء"
                headers={["العميل", "الأوامر", "الإجمالي"]}
                rows={s.by_customer.map((c) => [c.customer_name, num(c.orders), money(c.total)])}
              />
            </div>
          </>
        )
      )}
    </>
  );
}

function PurchasesTab({ range, from, to, onExport, busy }: TabProps) {
  const q = qs({ date_from: from, date_to: to, top: 10 });
  const data = useFetch(() => api.get<PurchasesSummary>(`/reports/purchases-summary${q}`), `purch${q}`);
  const s = data.data;
  const avg = s && s.orders > 0 ? Number(s.total) / s.orders : 0;

  return (
    <>
      <div className="page-actions" style={{ marginBottom: 14 }}>
        <ExportButton busy={busy} onClick={() => onExport(`/reports/purchases-summary/xlsx${range}`, `report-purchases-${from}_${to}.xlsx`)}>
          تصدير Excel
        </ExportButton>
      </div>
      <Alert>{data.error}</Alert>
      {data.loading && !s ? (
        <Loading />
      ) : (
        s && (
          <>
            <div className="kpis">
              <Kpi label="إجمالي المشتريات" value={money(s.total)} />
              <Kpi label="عدد الأوامر المستلمة" value={num(s.orders)} />
              <Kpi label="متوسط قيمة الأمر" value={money(avg)} />
            </div>
            <DailyBars series={s.by_day} label="المشتريات اليومية (حسب تاريخ الاستلام)" />
            <div className="grid-2">
              <RankTable
                title="الأكثر شراءً"
                headers={["المنتج", "الكمية", "الإنفاق"]}
                rows={s.top_products.map((p) => [`${p.name} (${p.sku})`, num(p.quantity_bought), money(p.spend)])}
              />
              <RankTable
                title="أكبر الموردين"
                headers={["المورد", "الأوامر", "الإجمالي"]}
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
  const valuation = useFetch(() => api.get<InventoryValuationRow[]>("/reports/inventory-valuation"), "inv-val");
  const low = useFetch(() => api.get<LowStockItem[]>("/reports/low-stock"), "inv-low");
  const totalCost = (valuation.data ?? []).reduce((s, r) => s + Number(r.cost_value), 0);
  const totalSale = (valuation.data ?? []).reduce((s, r) => s + Number(r.sale_value), 0);

  return (
    <>
      <div className="page-actions" style={{ marginBottom: 14 }}>
        <ExportButton busy={busy} onClick={() => onExport("/reports/inventory-valuation/xlsx", "report-inventory-valuation.xlsx")}>
          تصدير قيمة المخزون Excel
        </ExportButton>
        <ExportButton busy={busy} onClick={() => onExport("/reports/low-stock/xlsx", "report-low-stock.xlsx")}>
          تصدير النقص Excel
        </ExportButton>
      </div>
      <Alert>{valuation.error || low.error}</Alert>
      {valuation.loading && !valuation.data ? (
        <Loading />
      ) : (
        <div className="kpis">
          <Kpi label="قيمة المخزون بالتكلفة" value={money(totalCost)} />
          <Kpi label="قيمة المخزون بسعر البيع" value={money(totalSale)} sub={`هامش محتمل: ${money(totalSale - totalCost)}`} />
          <Kpi label="منتجات تحت حد الطلب" value={num(low.data?.length ?? 0)} />
        </div>
      )}
      <div className="grid-2">
        <RankTable
          title="قيمة المخزون لكل مخزن"
          headers={["المخزن", "الوحدات", "بالتكلفة", "بسعر البيع"]}
          rows={(valuation.data ?? []).map((r) => [r.warehouse_name ?? "بدون مخزن", num(r.units), money(r.cost_value), money(r.sale_value)])}
        />
        <RankTable
          title="نقص المخزون"
          headers={["المنتج", "المتاح", "حد الطلب", "العجز"]}
          rows={(low.data ?? []).map((p) => [`${p.name} (${p.sku})`, num(p.quantity), num(p.reorder_level), num(p.shortfall)])}
        />
      </div>
    </>
  );
}

function BalancesTab({ kind, onExport, busy }: { kind: "receivables" | "payables"; onExport: (path: string, name: string) => void; busy: boolean }) {
  const isRec = kind === "receivables";
  const data = useFetch(() => api.get<BalancesReport>(`/reports/${kind}`), `bal-${kind}`);
  const r = data.data;
  return (
    <>
      <div className="page-actions" style={{ marginBottom: 14 }}>
        <ExportButton busy={busy} onClick={() => onExport(`/reports/${kind}/xlsx`, `report-${kind}.xlsx`)}>
          تصدير Excel
        </ExportButton>
      </div>
      <Alert>{data.error}</Alert>
      {data.loading && !r ? (
        <Loading />
      ) : (
        r && (
          <>
            <div className="kpis">
              <Kpi label={isRec ? "إجمالي المستحق على العملاء" : "إجمالي المستحق للموردين"} value={money(r.total)} sub={`${num(r.rows.filter((x) => Number(x.balance) > 0).length)} ${isRec ? "عميل" : "مورد"} عليهم رصيد`} />
            </div>
            <RankTable
              title={isRec ? "أرصدة العملاء (الأعلى أولاً)" : "أرصدة الموردين (الأعلى أولاً)"}
              headers={[isRec ? "العميل" : "المورد", "الهاتف", "الرصيد"]}
              rows={r.rows.map((x) => [x.name, x.phone ?? "—", money(x.balance)])}
            />
          </>
        )
      )}
    </>
  );
}
