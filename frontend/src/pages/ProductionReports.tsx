import { useState } from "react";
import { api } from "../api";
import { money, num } from "../format";
import { useFetch } from "../hooks";
import type { ManufacturingReportOut, WipOrder } from "../types";
import { Alert, Empty, Loading, PageHeader } from "../ui";

function printReport(report: ManufacturingReportOut) {
  const w = window.open("", "_blank");
  if (!w) return;
  const rowsHtml = report.lines.map((l) => `
    <tr>
      <td>${l.code}</td>
      <td>${l.product_name ?? "—"}</td>
      <td class="num">${l.qty_planned}</td>
      <td class="num">${l.qty_produced}</td>
      <td class="num">${money(l.materials)}</td>
      <td class="num">${money(l.costs)}</td>
      <td class="num">${money(l.total)}</td>
      <td class="num">${money(l.unit_cost)}</td>
      <td class="num">${money(l.variance)}</td>
    </tr>`).join("");
  const byProductHtml = report.by_product.map((b) => `
    <tr>
      <td>${b.product_name ?? `#${b.product_id}`}</td>
      <td class="num">${b.orders}</td>
      <td class="num">${b.qty_produced}</td>
      <td class="num">${money(b.total)}</td>
    </tr>`).join("");
  w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>تقرير التصنيع</title>
    <style>
      body { font-family: Tahoma, Arial, sans-serif; padding: 16px; }
      h1 { text-align: center; font-size: 20px; }
      h2 { text-align: center; font-weight: normal; font-size: 13px; color: #444; }
      h3 { font-size: 15px; margin: 18px 0 6px; }
      table { width: 100%; border-collapse: collapse; margin-top: 8px; }
      th, td { border: 1px solid #999; padding: 6px 8px; text-align: center; font-size: 12px; }
      th { background: #eee; }
      .num { text-align: center; }
      tfoot td { font-weight: bold; background: #f3f4f6; }
    </style></head><body>
    <h1>تقرير التصنيع</h1>
    <h2>الفترة: ${report.date_from ?? "البداية"} — ${report.date_to ?? "حتى اليوم"}</h2>
    <h3>الأوامر المكتملة</h3>
    <table>
      <thead><tr>
        <th>الرقم</th><th>المنتج</th><th>المخطط</th><th>المنتج</th><th>الخامات</th><th>الأجور والأعباء</th><th>الإجمالي</th><th>تكلفة الوحدة</th><th>الانحراف</th>
      </tr></thead>
      <tbody>${rowsHtml || '<tr><td colspan="9">لا توجد أوامر مكتملة في هذه الفترة</td></tr>'}</tbody>
      <tfoot><tr>
        <td colspan="4">الإجمالي (${report.total_orders} أمر · ${report.total_qty_produced} وحدة)</td>
        <td class="num">${money(report.total_materials)}</td>
        <td class="num">${money(report.total_costs)}</td>
        <td class="num">${money(report.total)}</td>
        <td class="num">—</td>
        <td class="num">${money(report.total_variance)}</td>
      </tr></tfoot>
    </table>
    <h3>الإنتاج حسب المنتج</h3>
    <table>
      <thead><tr><th>المنتج</th><th>عدد الأوامر</th><th>الكمية المنتجة</th><th>الإجمالي</th></tr></thead>
      <tbody>${byProductHtml || '<tr><td colspan="4">—</td></tr>'}</tbody>
    </table>
    <script>window.onload = () => { window.print(); };</script>
    </body></html>`);
  w.document.close();
}

export default function ProductionReports() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const valid = !from || !to || from <= to;
  const wip = useFetch(() => api.get<WipOrder[]>("/production-orders/reports/wip"), "mfg-wip");
  const wipTotal = (wip.data ?? []).reduce((s, w) => s + Number(w.wip_value), 0);
  const report = useFetch(
    () => (valid ? api.get<ManufacturingReportOut>(`/production-orders/reports/summary?${from ? `date_from=${from}&` : ""}${to ? `date_to=${to}` : ""}`) : Promise.resolve(null)),
    `mfg-report-${from}-${to}`
  );
  const r = report.data ?? null;

  return (
    <>
      <PageHeader title="تقارير التصنيع">
        <button className="btn" onClick={() => r && printReport(r)} disabled={!r}>
          🖨 طباعة
        </button>
      </PageHeader>

      <div className="card card-pad range-bar" style={{ marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
        <label className="range-field">
          <span className="field-label">من تاريخ</span>
          <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="range-field">
          <span className="field-label">إلى تاريخ</span>
          <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>
      {!valid && <Alert>تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.</Alert>}
      <Alert>{report.error}</Alert>

      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>⚙️ الأوامر قيد التنفيذ (WIP)</h3>
        {wip.loading && !wip.data ? (
          <Loading />
        ) : wip.data && wip.data.length > 0 ? (
          <>
            <p className="muted" style={{ margin: "0 0 8px", fontSize: 13 }}>
              قيمة المواد قيد التشغيل حاليًا: <b style={{ fontSize: 15 }}>{money(wipTotal)}</b>
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>الرقم</th><th>المنتج</th><th className="num">المخطط</th><th className="num">المنتج</th><th className="num">المتبقي</th><th className="num">الخامات</th><th className="num">الأجور والأعباء</th><th className="num">قيمة WIP</th><th>تاريخ الجدولة</th></tr>
                </thead>
                <tbody>
                  {wip.data.map((w) => (
                    <tr key={w.id}>
                      <td dir="ltr">{w.code}</td>
                      <td>{w.product_name ?? `#${w.product_id}`}</td>
                      <td className="num">{num(w.qty_planned)}</td>
                      <td className="num">{num(w.qty_produced)}</td>
                      <td className="num">{num(w.remaining)}</td>
                      <td className="num">{money(w.materials)}</td>
                      <td className="num">{money(w.costs)}</td>
                      <td className="num">{money(w.wip_value)}</td>
                      <td>{w.scheduled_date ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <Empty>لا توجد أوامر قيد التنفيذ.</Empty>
        )}
      </div>

      {!r ? (
        <Loading />
      ) : (
        <>
          <div className="card card-pad" style={{ marginBottom: 16, display: "flex", gap: 24, flexWrap: "wrap" }}>
            <span>أوامر مكتملة: <b>{r.total_orders}</b></span>
            <span>إجمالي المنتج: <b>{num(r.total_qty_produced)}</b></span>
            <span>الخامات: <b>{money(r.total_materials)}</b></span>
            <span>الأجور والأعباء: <b>{money(r.total_costs)}</b></span>
            <span>الإجمالي: <b style={{ fontSize: 15 }}>{money(r.total)}</b></span>
            <span>إجمالي الانحرافات: <b>{money(r.total_variance)}</b></span>
          </div>

          <div className="card table-wrap" style={{ marginBottom: 16 }}>
            <h3 style={{ margin: "12px 14px 8px", fontSize: 15 }}>الأوامر المكتملة</h3>
            {r.lines.length > 0 ? (
              <table>
                <thead>
                  <tr>
                    <th>الرقم</th>
                    <th>المنتج</th>
                    <th className="num">المخطط</th>
                    <th className="num">المنتج</th>
                    <th className="num">الخامات</th>
                    <th className="num">الأجور والأعباء</th>
                    <th className="num">الإجمالي</th>
                    <th className="num">تكلفة الوحدة</th>
                    <th className="num">الانحراف</th>
                  </tr>
                </thead>
                <tbody>
                  {r.lines.map((l) => (
                    <tr key={l.order_id}>
                      <td dir="ltr">{l.code}</td>
                      <td>{l.product_name ?? `#${l.order_id}`}</td>
                      <td className="num">{num(l.qty_planned)}</td>
                      <td className="num">{num(l.qty_produced)}</td>
                      <td className="num">{money(l.materials)}</td>
                      <td className="num">{money(l.costs)}</td>
                      <td className="num">{money(l.total)}</td>
                      <td className="num">{money(l.unit_cost)}</td>
                      <td className="num">{Number(l.variance) !== 0 ? money(l.variance) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>لا توجد أوامر مكتملة في هذه الفترة.</Empty>
            )}
          </div>

          <div className="card table-wrap">
            <h3 style={{ margin: "12px 14px 8px", fontSize: 15 }}>الإنتاج حسب المنتج</h3>
            {r.by_product.length > 0 ? (
              <table>
                <thead>
                  <tr>
                    <th>المنتج</th>
                    <th className="num">عدد الأوامر</th>
                    <th className="num">الكمية المنتجة</th>
                    <th className="num">الإجمالي</th>
                  </tr>
                </thead>
                <tbody>
                  {r.by_product.map((b) => (
                    <tr key={b.product_id}>
                      <td>{b.product_name ?? `#${b.product_id}`}</td>
                      <td className="num">{num(b.orders)}</td>
                      <td className="num">{num(b.qty_produced)}</td>
                      <td className="num">{money(b.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>لا توجد بيانات.</Empty>
            )}
          </div>
        </>
      )}
    </>
  );
}
