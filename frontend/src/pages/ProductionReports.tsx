import { useState } from "react";
import { api } from "../api";
import { money, num } from "../format";
import { useAction, useFetch, type Fetched } from "../hooks";
import type { ManufacturingReportOut, WipOrder, WorkCenterPerfOut, SubReportRow } from "../types";
import { Alert, Empty, Loading, PageHeader } from "../ui";
import { useI18n } from "../i18n";

function escapeHtml(v: unknown): string {
  return String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function printReport(report: ManufacturingReportOut) {
  const w = window.open("", "_blank");
  if (!w) return;
  const rowsHtml = report.lines.map((l) => `
    <tr>
      <td>${escapeHtml(l.code)}</td>
      <td>${escapeHtml(l.product_name ?? "—")}</td>
      <td class="num">${l.qty_planned}</td>
      <td class="num">${l.qty_produced}</td>
      <td class="num">${money(l.materials)}</td>
      <td class="num">${money(l.costs)}</td>
      <td class="num">${money(l.total)}</td>
      <td class="num">${money(l.unit_cost)}</td>
      <td class="num">${money(l.std_unit_cost)}</td>
      <td class="num">${l.variance_std !== null && l.variance_std !== undefined ? money(l.variance_std) : "—"}</td>
      <td class="num">${money(l.variance)}</td>
    </tr>`).join("");
  const byProductHtml = report.by_product.map((b) => `
    <tr>
      <td>${escapeHtml(b.product_name ?? `#${b.product_id}`)}</td>
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
    <h2>الفترة: ${escapeHtml(report.date_from ?? "البداية")} — ${escapeHtml(report.date_to ?? "حتى اليوم")}</h2>
    <h3>الأوامر المكتملة</h3>
    <table>
      <thead><tr>
        <th>الرقم</th><th>المنتج</th><th>المخطط</th><th>المنتج</th><th>الخامات</th><th>الأجور والأعباء</th><th>الإجمالي</th><th>تكلفة الوحدة</th><th>القياسية</th><th>انحراف القياسية</th><th>الانحراف</th>
      </tr></thead>
      <tbody>${rowsHtml || '<tr><td colspan="11">لا توجد أوامر مكتملة في هذه الفترة</td></tr>'}</tbody>
      <tfoot><tr>
        <td colspan="4">الإجمالي (${report.total_orders} أمر · ${report.total_qty_produced} وحدة)</td>
        <td class="num">${money(report.total_materials)}</td>
        <td class="num">${money(report.total_costs)}</td>
        <td class="num">${money(report.total)}</td>
        <td class="num">—</td>
        <td class="num">—</td>
        <td class="num">${money(report.total_variance_std)}</td>
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

interface MrpAggregateRow {
  product_id: number;
  product_name?: string | null;
  unit?: string | null;
  in_stock: number | string;
  open_demand: number | string;
  shortfall: number | string;
  has_bom: boolean;
}

/** تخطيط الاحتياجات (MRP): الطلب المفتوح مقابل الرصيد — ما يجب إنتاجه لسد العجز. */
function MrpPanel({ warehouses }: { warehouses: Fetched<{ id: number; name: string }[]> }) {
  const { t } = useI18n();
  const aggregate = useFetch(() => api.get<{ lines: MrpAggregateRow[] }>("/production-orders/mrp/aggregate"), "mrp-aggregate");
  const suppliers = useFetch(() => api.get<{ id: number; name: string }[]>("/suppliers"), "mrp-suppliers");
  const { run, busy, error } = useAction();
  const [note, setNote] = useState<string | null>(null);
  const [sel, setSel] = useState<Record<number, { qty: string; action: "produce" | "buy"; supplier_id: string }>>({});
  const lines = (aggregate.data?.lines ?? []).filter((l) => Number(l.open_demand) > 0 || Number(l.shortfall) > 0);

  const pick = (l: MrpAggregateRow) =>
    sel[l.product_id] ?? { qty: String(l.shortfall || 0), action: (l.has_bom ? "produce" : "buy") as "produce" | "buy", supplier_id: "" };
  const setPick = (pid: number, patch: Partial<{ qty: string; action: "produce" | "buy"; supplier_id: string }>) =>
    setSel((s) => ({ ...s, [pid]: { ...pick(lines.find((x) => x.product_id === pid)!), ...patch } }));

  const execute = () => {
    const rawWh = (warehouses.data ?? [])[0]?.id;
    if (!rawWh) { setNote(t("لا توجد مخازن — أضف مخزنًا أولًا")); return; }
    const items = lines
      .filter((l) => sel[l.product_id] ? Number(sel[l.product_id].qty) > 0 : Number(l.shortfall) > 0)
      .map((l) => {
        const p = pick(l);
        return { product_id: l.product_id, qty: Number(p.qty), action: p.action, supplier_id: p.supplier_id ? Number(p.supplier_id) : null };
      });
    if (items.length === 0) { setNote(t("حدد كميات للتنفيذ أولًا")); return; }
    void run(async () => {
      const out = await api.post<{ created: { order_code: string; action: string; product_id: number }[]; skipped: { product_id: number; reason: string }[] }>("/production-orders/mrp/execute", {
        raw_warehouse_id: rawWh, output_warehouse_id: rawWh,
        items,
      });
      const made = out.created.map((c) => `${c.order_code}`).join("، ");
      const skippedCount = out.skipped.length;
      setNote(`${t("نُفذ:")} ${out.created.length} ${t("أمر")} ${made ? `(${made})` : ""}${skippedCount ? ` — ${t("تعذر")} ${skippedCount}` : ""}`);
      setSel({});
      aggregate.reload();
    });
  };

  return (
    <div className="card card-pad" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>🧮 {t("تخطيط الاحتياجات — الطلب المفتوح مقابل الرصيد")}</h3>
        <button className="btn btn-primary" disabled={busy || lines.length === 0} onClick={execute}>
          {busy ? t("جارٍ التنفيذ…") : t("⚡ تنفيذ المحدد (أوامر مسودة)")}
        </button>
      </div>
      {error && <Alert>{error}</Alert>}
      {note && <div className="hint" style={{ marginBottom: 8 }}>{note}</div>}
      {(warehouses.data ?? []).length > 0 && <small className="hint" style={{ display: "block", marginBottom: 8 }}>{t("مخزن الصرف والناتج:")} <b>{(warehouses.data ?? [])[0]?.name}</b> — {t("تُنشأ الأوامر كمسودات للمراجعة قبل التأكيد")}</small>}
      {aggregate.loading && !aggregate.data ? (
        <Loading />
      ) : aggregate.error ? (
        <Alert>{aggregate.error}</Alert>
      ) : lines.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>{t("المنتج")}</th><th className="num">{t("الرصيد بكل المخازن")}</th><th className="num">{t("الطلب المفتوح")}</th><th className="num">{t("العجز")}</th><th>{t("التنفيذ")}</th></tr>
            </thead>
            <tbody>
              {lines.map((l) => {
                const p = pick(l);
                return (
                  <tr key={l.product_id}>
                    <td>{l.product_name ?? `#${l.product_id}`}</td>
                    <td className="num">{num(l.in_stock)}</td>
                    <td className="num">{num(l.open_demand)}</td>
                    <td className="num">
                      {Number(l.shortfall) > 0 ? (
                        <span className="badge badge-cancelled">{num(l.shortfall)}</span>
                      ) : (
                        <span className="badge badge-confirmed">{t("مغطى")}</span>
                      )}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                        <input dir="ltr" style={{ width: 90 }} inputMode="decimal" value={p.qty} onChange={(e) => setPick(l.product_id, { qty: e.target.value.replace(/[^0-9.]/g, "") })} />
                        <select value={p.action} onChange={(e) => setPick(l.product_id, { action: e.target.value as "produce" | "buy" })}>
                          <option value="produce">{t("إنتاج")} {l.has_bom ? "✅" : "⚠️"}</option>
                          <option value="buy">{t("شراء")}</option>
                        </select>
                        {p.action === "buy" && (
                          <select value={p.supplier_id} onChange={(e) => setPick(l.product_id, { supplier_id: e.target.value })}>
                            <option value="">{t("اختر موردًا…")}</option>
                            {(suppliers.data ?? []).map((s) => (
                              <option key={s.id} value={s.id}>{s.name}</option>
                            ))}
                          </select>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>{t("لا طلب مفتوح حالياً — الأرصدة تغطي أوامر البيع.")}</Empty>
      )}
    </div>
  );
}

function SubcontractCustodyCard() {
  const { t } = useI18n();
  const rows = useFetch(() => api.get<SubReportRow[]>("/production-orders/reports/subcontract-custody"), "sub-report");
  const data = (rows.data ?? []).filter((r) => Number(r.outstanding) > 0);
  return (
    <div className="card card-pad" style={{ marginBottom: 16 }}>
      <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>🏭 {t("عهدة التصنيع الخارجي — ما لدى المُصنّعين الآن")}</h3>
      <Alert>{rows.error}</Alert>
      {rows.loading && !rows.data ? <Loading /> : data.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("المُصنّع")}</th><th>{t("أمر التصنيع")}</th><th>{t("الخامة")}</th><th className="num">{t("سُلّم")}</th><th className="num">{t("أُرجع")}</th><th className="num">{t("لدى المُصنّع")}</th><th className="num">{t("عمر العهدة")}</th></tr></thead>
            <tbody>
              {data.map((r, i) => (
                <tr key={i} style={r.days_out > 14 ? { background: "var(--danger-bg, #fee4e2)" } : undefined}>
                  <td>{r.subcontractor_name ?? "—"}</td>
                  <td dir="ltr">{r.order_code}</td>
                  <td>{r.product_name ?? "—"}</td>
                  <td className="num">{num(r.qty_sent)}</td>
                  <td className="num">{num(r.qty_returned)}</td>
                  <td className="num" style={{ fontWeight: 800 }}>{num(r.outstanding)}</td>
                  <td className="num">{r.days_out} {t("يوم")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>{t("لا عهدة قائمة لدى مُصنّعين خارجيين.")}</Empty>}
    </div>
  );
}

export default function ProductionReports() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const valid = !from || !to || from <= to;
  const warehouses = useFetch(() => api.get<{ id: number; name: string }[]>("/warehouses"), "mfg-warehouses");
  const wip = useFetch(() => api.get<WipOrder[]>("/production-orders/reports/wip"), "mfg-wip");
  const wipTotal = (wip.data ?? []).reduce((s, w) => s + Number(w.wip_value), 0);
  const report = useFetch(
    () => (valid ? api.get<ManufacturingReportOut>(`/production-orders/reports/summary?${from ? `date_from=${from}&` : ""}${to ? `date_to=${to}` : ""}`) : Promise.resolve(null)),
    `mfg-report-${from}-${to}`
  );
  const wcPerf = useFetch(
    () => (valid ? api.get<WorkCenterPerfOut>(`/production-orders/reports/work-centers?${from ? `date_from=${from}&` : ""}${to ? `date_to=${to}` : ""}`) : Promise.resolve(null)),
    `wc-perf-${from}-${to}`
  );
  const wcRows = (wcPerf.data?.rows ?? []).filter((r) => r.orders_count > 0 || r.planned_minutes > 0);
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
        <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>🏁 أداء مراكز التشغيل (الفعلي مقابل المخطط)</h3>
        {wcPerf.loading && !wcPerf.data ? (
          <Loading />
        ) : wcRows.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>مركز التشغيل</th><th className="num">أوامر</th><th className="num">المنجز</th><th className="num">الهالك</th><th className="num">دقائق فعلية</th><th className="num">دقائق مخططة</th><th className="num">الاستغلال</th></tr>
              </thead>
              <tbody>
                {wcRows.map((r) => (
                  <tr key={r.work_center_id}>
                    <td>{r.name}</td>
                    <td className="num">{num(r.orders_count)}</td>
                    <td className="num">{num(r.qty_done)}</td>
                    <td className="num">{num(r.qty_scrapped)}</td>
                    <td className="num">{num(r.actual_minutes)}</td>
                    <td className="num">{num(r.planned_minutes)}</td>
                    <td className="num">
                      <span className={`badge ${r.utilization > 110 ? "badge-cancelled" : r.utilization >= 80 ? "badge-confirmed" : "badge-muted"}`}>
                        {r.utilization}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>لا بيانات تشغيل على مراكز التشغيل في هذه الفترة — حدد مراحل بمركز تشغيل في قائمة المواد.</Empty>
        )}
      </div>

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

      <MrpPanel warehouses={warehouses} />
      <SubcontractCustodyCard />

      {!valid || report.loading ? (
        <Loading />
      ) : !r ? (
        <div className="card card-pad"><Empty>حدّد فترة صحيحة لعرض التقرير.</Empty></div>
      ) : (
        <>
          <div className="card card-pad" style={{ marginBottom: 16, display: "flex", gap: 24, flexWrap: "wrap" }}>
            <span>أوامر مكتملة: <b>{r.total_orders}</b></span>
            <span>إجمالي المنتج: <b>{num(r.total_qty_produced)}</b></span>
            <span>الخامات: <b>{money(r.total_materials)}</b></span>
            <span>الأجور والأعباء: <b>{money(r.total_costs)}</b></span>
            <span>الإجمالي: <b style={{ fontSize: 15 }}>{money(r.total)}</b></span>
            <span>إجمالي الانحرافات: <b>{money(r.total_variance)}</b></span>
            {Number(r.total_variance_std) !== 0 && <span>ضد القياسية: <b>{money(r.total_variance_std)}</b></span>}
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
                    <th className="num">القياسية</th>
                    <th className="num">ضد القياسية</th>
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
                      <td className="num">{l.std_unit_cost ? money(l.std_unit_cost) : "—"}</td>
                      <td className="num">{l.variance_std !== null && l.variance_std !== undefined && Number(l.variance_std) !== 0 ? money(l.variance_std) : "—"}</td>
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
