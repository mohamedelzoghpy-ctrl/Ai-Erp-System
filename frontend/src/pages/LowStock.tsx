import { useState } from "react";
import { api, qs } from "../api";
import { useI18n } from "../i18n";
import { money, num } from "../format";
import { useAction, useFetch } from "../hooks";
import type { Branch, LowStockItem, Product, Warehouse } from "../types";
import { Alert, Empty, Loading, Modal, PageHeader, ProductThumb } from "../ui";

/** Standalone low-stock alerts page (moved out of the dashboard into the inventory section).
 *  Scope: the whole company, one branch (all its warehouses), one warehouse, or one supplier.
 *  Includes the reorder-level bulk edit mode (moved here from the products page). */
export default function LowStock() {
  const { t } = useI18n();
  const download = useAction();
  const branches = useFetch(() => api.get<Branch[]>("/company/branches"), "ls-branches");
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?limit=500"), "ls-warehouses");
  const suppliers = useFetch(() => api.get<{ id: number; name: string }[]>("/suppliers?limit=500"), "ls-suppliers");

  // وضع تعديل حد الطلب: عمود «حد الطلب» قابل للتعديل داخل جدول التنبيهات + حفظ المتغير دفعة واحدة
  const [reorderEdit, setReorderEdit] = useState(false);
  const [reorderEdits, setReorderEdits] = useState<Record<number, string>>({});
  const [savingReorder, setSavingReorder] = useState(false);
  const [reorderNote, setReorderNote] = useState<string | null>(null);
  const [printPreview, setPrintPreview] = useState<string | null>(null);

  const toggleReorderEdit = (on: boolean) => {
    setReorderEdit(on);
    if (on) {
      setReorderNote(t("وضع تعديل حد الطلب مفتوح — عدّل «حد الطلب» داخل الجدول، ثم دوس «حفظ حد الطلب»."));
      const init: Record<number, string> = {};
      for (const p of (low.data ?? [])) init[p.id] = String(p.reorder_level);
      setReorderEdits(init);
    } else {
      setReorderEdits({});
      setReorderNote(null);
    }
  };

  const setReorder = (id: number, v: string) => {
    // أرقام صحيحة فقط: عربي أو إنجليزي، بدون كسور
    const t2 = v
      .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
      .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
      .replace(/[^0-9]/g, "")
      .replace(/^0+(?=\d)/, "");
    setReorderEdits((prev) => ({ ...prev, [id]: t2 }));
  };

  const saveReorders = async () => {
    setSavingReorder(true);
    let n = 0;
    const errs: string[] = [];
    for (const p of changedReorders) {
      try {
        await api.patch(`/products/${p.id}`, { reorder_level: Number(reorderEdits[p.id]) });
        n += 1;
      } catch (err) {
        errs.push(`${p.sku}: ${(err as Error).message}`);
      }
    }
    setSavingReorder(false);
    setReorderEdits({});
    setReorderNote(`${t("تم حفظ حد الطلب لـ ")}${n}${t(" صنف")}` + (errs.length ? `${t(" — أخطاء: ")}${errs.slice(0, 3).join(" | ")}` : ""));
    low.reload();
  };

  const [scopeBranch, setScopeBranch] = useState(""); // "" = company-wide
  const [scopeWarehouse, setScopeWarehouse] = useState("");
  const [scopeSupplier, setScopeSupplier] = useState("");

  const branchWarehouses = (warehouses.data ?? []).filter((w) => !scopeBranch || String(w.branch_id) === scopeBranch);

  const fq = qs({
    ...(scopeWarehouse ? { warehouse_id: scopeWarehouse } : scopeBranch ? { branch_id: scopeBranch } : {}),
    ...(scopeSupplier ? { supplier_id: scopeSupplier } : {}),
  });
  const low = useFetch(() => api.get<LowStockItem[]>(`/reports/low-stock${fq}`), `lowstock${fq}`);
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<"alerts" | "forecast">("alerts");
  const [forecastDays, setForecastDays] = useState(30);
  const forecast = useFetch(
    () => api.get<any>(`/reports/reorder-forecast?days_analyzed=${forecastDays}${scopeWarehouse ? `&warehouse_id=${scopeWarehouse}` : ""}${scopeSupplier ? `&supplier_id=${scopeSupplier}` : ""}`),
    `reorder-forecast-${forecastDays}-${scopeWarehouse}-${scopeSupplier}`
  );
  const suggestions = useFetch(
    () => api.get<any[]>(`/reports/purchase-suggestions${fq}`), `purch-sugg${fq}`,
  );
  const expiring = useFetch(
    () => api.get<any[]>(`/reports/lots-expiring?days=30${scopeWarehouse ? `&warehouse_id=${scopeWarehouse}` : ""}`), `lots-exp${scopeWarehouse}`,
  );
  const [creatingPO, setCreatingPO] = useState<number | null>(null);
  const createDraftPO = async (supplierId: number, supplierName: string) => {
    if (!confirm(`إنشاء مسودة أمر شراء للمورد «${supplierName}» بكل الكميات المقترحة له؟`)) return;
    setCreatingPO(supplierId);
    try {
      const r: any = await api.post("/purchase-orders/from-suggestions", {
        supplier_id: supplierId,
        warehouse_id: scopeWarehouse ? Number(scopeWarehouse) : null,
      });
      alert(`تم إنشاء مسودة أمر شراء #${r?.id} — استلمها من صفحة أوامر الشراء`);
      suggestions.reload();
    } catch (e) { alert((e as Error).message); }
    finally { setCreatingPO(null); }
  };

  const rows = (low.data ?? []).filter((p) => {
    // smart match: every typed word must be a prefix of some word in the name or of the SKU
    const tokens = search.trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) return true;
    const words = `${p.name} ${p.sku ?? ""}`.toLowerCase().split(/\s+/);
    return tokens.every((tok) => {
      const t = tok.toLowerCase();
      return words.some((w) => w.startsWith(t));
    });
  });
  const totalShortfall = (low.data ?? []).reduce((s, p) => s + p.shortfall, 0);
  const changedReorders = (low.data ?? []).filter((p) => {
    const e = reorderEdits[p.id];
    return e !== undefined && e !== "" && Number(e) !== (p.reorder_level ?? 0);
  });
  const exportFile = (path: string, name: string) => void download.run(() => api.download(path, name));
  const scopeLabel =
    scopeWarehouse
      ? (warehouses.data ?? []).find((w) => String(w.id) === scopeWarehouse)?.name
      : scopeBranch
        ? (branches.data ?? []).find((b) => String(b.id) === scopeBranch)?.name ?? `${t("فرع #")}${scopeBranch}`
        : t("الشركة ككل");
  const supplierLabel = scopeSupplier
    ? (suppliers.data ?? []).find((s) => String(s.id) === scopeSupplier)?.name ?? `${t("مورد #")}${scopeSupplier}`
    : null;

  // معاينة الطباعة: بناء HTML للتقرير (رأس مختصر + نسخة من الجدول كما يظهر على الشاشة)
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const buildReportHTML = () => {
    const table = document.querySelector(".lowstock-table");
    if (!table) return null;
    const clone = table.cloneNode(true) as HTMLElement;
    // لو وضع تعديل حد الطلب مفتوح: نحوّل الحقول لأرقام عادية
    clone.querySelectorAll("input.ls-reorder-input").forEach((inp) => {
      const span = document.createElement("span");
      span.textContent = (inp as HTMLInputElement).value || "0";
      inp.replaceWith(span);
    });
    const title = esc(t("dashboard.lowStockAlerts"));
    const scope = esc(`${scopeLabel ?? t("الشركة ككل")}${supplierLabel ? t(" — مورد: ") + supplierLabel : ""}`);
    const date = esc(new Date().toLocaleDateString("ar-EG", { year: "numeric", month: "long", day: "numeric" }));
    return (
      `<div class="ls-preview-meta"><h1>${title}</h1><p>${scope}${t(" — تاريخ الطباعة: ")}${date}${t(" — عدد المنتجات: ")}${rows.length}</p></div>` +
      clone.outerHTML
    );
  };

  const printNow = (html: string) => {
    const w = window.open("", "_blank", "width=1020,height=760");
    if (!w) {
      alert(t("افتح السماح بالنوافذ المنبثقة لتتمكن من الطباعة"));
      return;
    }
    const css = Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
      .map((l) => (l as HTMLLinkElement).href)
      .filter(Boolean)
      .map((u) => `<link rel="stylesheet" href="${u}">`)
      .join("");
    w.document.open();
    w.document.write(
      `<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><title>${esc(t("dashboard.lowStockAlerts"))}</title>` +
        css +
        `<style>@page{size:A4;margin:10mm}body{margin:0;background:#fff;padding:14px}` +
        `.ls-preview-meta h1{font-size:18px;margin:0 0 4px}.ls-preview-meta p{margin:0 0 10px;color:#6b7686;font-size:12px}` +
        `.lowstock-table th{position:static}.lowstock-table tbody tr{break-inside:avoid}</style></head><body>` +
        html +
        `<script>window.onload=function(){setTimeout(function(){window.print()},300)}<\/script></body></html>`
    );
    w.document.close();
  };

  return (
    <div className="lowstock-page">
      <PageHeader title={t("dashboard.lowStockAlerts")} />

      {/* رأس يظهر في المطبوع فقط */}
      <div className="ls-print-header">
        <h1>{t("dashboard.lowStockAlerts")}</h1>
        <p>
          {scopeLabel ?? t("الشركة ككل")}
          {supplierLabel && <>{t(" — مورد: ")}{supplierLabel}</>}
          {t(" — تاريخ الطباعة: ")}
          {new Date().toLocaleDateString("ar-EG", { year: "numeric", month: "long", day: "numeric" })}
          {t(" — عدد المنتجات: ")}
          {rows.length}
        </p>
      </div>

      <div className="ls-toolbar">
        <label className="ls-filter-label">
          {t("نطاق التنبيه:")}
          <select
            className="ls-select"
            value={scopeBranch}
            onChange={(e) => {
              setScopeBranch(e.target.value);
              setScopeWarehouse("");
            }}
          >
            <option value="">{t("الشركة ككل")}</option>
            {(branches.data ?? []).map((b) => (
              <option key={b.id} value={b.id}>
                {t("فرع: ")}{b.name}
              </option>
            ))}
          </select>
        </label>
        <label className="ls-filter-label">
          {scopeBranch ? t("مخزن الفرع:") : t("مخزن معين:")}
          <select className="ls-select" value={scopeWarehouse} onChange={(e) => setScopeWarehouse(e.target.value)}>
            <option value="">{t("كل المخازن")}</option>
            {branchWarehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
        <label className="ls-filter-label">
          {t("المورد:")}
          <select className="ls-select" value={scopeSupplier} onChange={(e) => setScopeSupplier(e.target.value)}>
            <option value="">{t("كل الموردين")}</option>
            {(suppliers.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <span className="ls-scope-note muted">
          {t("التصنيف الحالي: ")} <b>{scopeLabel ?? "—"}</b>
          {supplierLabel && <>{t(" — مورد: ")} <b>{supplierLabel}</b></>}
        </span>
        <input
          type="search"
          className="ls-search"
          placeholder={t("ابحث بالاسم أو الكود…")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className="btn" disabled={download.busy} onClick={() => exportFile(`/reports/low-stock/xlsx${fq}`, "report-low-stock.xlsx")}>
          {download.busy ? t("جارٍ التجهيز…") : `⬇ ${t("تصدير Excel")}`}
        </button>
        <button
          className="btn"
          onClick={() => setPrintPreview(buildReportHTML())}
        >
          🖨 {t("طباعة")}
        </button>
        <button
          className={reorderEdit ? "btn btn-primary" : "btn"}
          onClick={() => toggleReorderEdit(!reorderEdit)}
        >
          {reorderEdit ? `✕ ${t("إغلاق وضع التعديل")}` : `📋 ${t("وضع تعديل حد الطلب")}`}
        </button>
        {reorderEdit && changedReorders.length > 0 && (
          <button className="btn btn-primary" disabled={savingReorder} onClick={() => void saveReorders()}>
            {savingReorder ? t("… جارٍ الحفظ") : `💾 ${t("حفظ حد الطلب (")}${changedReorders.length}${t(")")}`}
          </button>
        )}
      </div>

      <div style={{ display: "flex", gap: 10, margin: "16px 0 12px", borderBottom: "1px solid #ddd", paddingBottom: 8 }}>
        <button
          className={`btn ${activeTab === "alerts" ? "btn-primary" : ""}`}
          onClick={() => setActiveTab("alerts")}
        >
          🚨 تنبيهات نقص المخزون الحالية
        </button>
        <button
          className={`btn ${activeTab === "forecast" ? "btn-primary" : ""}`}
          onClick={() => setActiveTab("forecast")}
        >
          ⚡ التنبؤ الذكي بحد الطلب ونقاط إعادة التموين (ROP)
        </button>
      </div>

      <Alert>{low.error || download.error || forecast.error}</Alert>

      {activeTab === "forecast" ? (
        <div className="card card-pad" style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
            <div>
              <h3 style={{ margin: "0 0 4px" }}>📊 التنبؤ الديناميكي بنقاط إعادة الطلب (Dynamic ROP)</h3>
              <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                محسوب بناءً على متوسط سرعة السحب اليومي الفعلي وزمن التوريد ومخزون أمان إضافي.
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <label style={{ fontSize: "0.85rem", fontWeight: 600 }}>فترة تحليل المبيعات:</label>
              <select
                className="ls-select"
                style={{ width: 130 }}
                value={forecastDays}
                onChange={(e) => setForecastDays(Number(e.target.value))}
              >
                <option value={14}>آخر 14 يوماً</option>
                <option value={30}>آخر 30 يوماً</option>
                <option value={60}>آخر 60 يوماً</option>
                <option value={90}>آخر 90 يوماً</option>
              </select>
            </div>
          </div>

          <div className="kpis" style={{ marginBottom: 16 }}>
            <div className="kpi">
              <div className="label">أصناف في مرحلة الخطر (Critical)</div>
              <div className={`value${(forecast.data?.critical_count ?? 0) > 0 ? " low" : ""}`}>
                {num(forecast.data?.critical_count ?? 0)}
              </div>
            </div>
            <div className="kpi">
              <div className="label">أصناف قاربت نقطة الطلب (Warning)</div>
              <div className="value">{num(forecast.data?.warning_count ?? 0)}</div>
            </div>
            <div className="kpi">
              <div className="label">الاستثمار التقديري المقترح للتموين</div>
              <div className="value">{money(forecast.data?.total_suggested_investment ?? 0)}</div>
            </div>
          </div>

          {forecast.loading ? (
            <Loading />
          ) : (forecast.data?.items ?? []).length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>الكود</th>
                    <th>المنتج</th>
                    <th>المورد المعتمد</th>
                    <th className="num">الرصيد الحالي</th>
                    <th className="num">السحب اليومي</th>
                    <th className="num">نقطة الطلب (ROP)</th>
                    <th className="num">الأيام المتبقية</th>
                    <th className="num">الكمية المقترحة</th>
                    <th className="num">التكلفة التقديرية</th>
                    <th>الحالة</th>
                    <th>إجراء</th>
                  </tr>
                </thead>
                <tbody>
                  {(forecast.data?.items ?? []).map((it: any) => {
                    const isCrit = it.reorder_urgency === "critical";
                    const isWarn = it.reorder_urgency === "warning";
                    return (
                      <tr key={it.product_id} style={{ background: isCrit ? "rgba(220, 38, 38, 0.06)" : isWarn ? "rgba(245, 158, 11, 0.05)" : undefined }}>
                        <td dir="ltr"><strong>{it.sku}</strong></td>
                        <td>{it.name}</td>
                        <td>{it.supplier_name || "—"}</td>
                        <td className="num">{num(it.current_stock)}</td>
                        <td className="num">{num(it.daily_sales)}/يوم</td>
                        <td className="num" style={{ fontWeight: 600 }}>{num(it.suggested_rop)}</td>
                        <td className="num" style={{ fontWeight: 700, color: isCrit ? "#dc2626" : isWarn ? "#d97706" : "#16a34a" }}>
                          {it.days_left != null ? `${it.days_left} يوم` : "—"}
                        </td>
                        <td className="num" style={{ fontWeight: 700 }}>{num(it.suggested_order_qty)}</td>
                        <td className="num">{money(it.estimated_cost)}</td>
                        <td>
                          <span style={{
                            padding: "3px 8px",
                            borderRadius: 6,
                            fontSize: "0.8rem",
                            fontWeight: 600,
                            background: isCrit ? "#fee2e2" : isWarn ? "#fef3c7" : "#dcfce7",
                            color: isCrit ? "#991b1b" : isWarn ? "#92400e" : "#166534",
                          }}>
                            {isCrit ? "خطر نفاد ⚠️" : isWarn ? "اقترب الطلب ⏳" : "مستقر ✓"}
                          </span>
                        </td>
                        <td>
                          {it.supplier_id && it.suggested_order_qty > 0 && (
                            <button
                              className="btn btn-sm btn-primary"
                              disabled={creatingPO === it.supplier_id}
                              onClick={() => createDraftPO(it.supplier_id, it.supplier_name || "المورد")}
                            >
                              + أمر شراء
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>لا توجد بيانات حركة كافية لإجراء التنبؤ</Empty>
          )}
        </div>
      ) : (
        <>
          {reorderEdit && reorderNote && <p className="muted" style={{ margin: "0 0 10px", fontSize: 13 }}>{reorderNote}</p>}

          <div className="kpis" style={{ marginBottom: 14 }}>
            <div className="kpi">
              <div className="label">{t("منتجات تحت حد الطلب")}</div>
              <div className={`value${(low.data ?? []).length > 0 ? " low" : ""}`}>{num(low.data?.length ?? 0)}</div>
            </div>
            <div className="kpi">
              <div className="label">إجمالي العجز (وحدات)</div>
              <div className="value">{num(totalShortfall)}</div>
            </div>
          </div>

      {low.loading && !low.data ? (
        <Loading />
      ) : rows.length > 0 ? (
        <div className="card table-wrap">
          <table className="lowstock-table">

            <thead>
              <tr>
                <th className="num-center" style={{ width: 56 }}>صورة</th>
                <th>المنتج</th>
                <th>اسم المورد</th>
                <th className="num">المتاح</th>
                <th className="num">{t("dashboard.reorderLevel")}</th>
                <th className="num">{t("dashboard.shortfall")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const edited = reorderEdit && Number(reorderEdits[p.id] ?? p.reorder_level) !== p.reorder_level;
                const critical = p.shortfall > p.reorder_level;
                return (
                  <tr key={p.id} className={critical ? "ls-row-critical" : undefined}>
                    <td className="num-center">
                      <ProductThumb product={{ id: p.id, name: p.name, sku: p.sku, image_url: p.image_url ?? null, image_uploaded: p.image_uploaded ?? false } as Product} />
                    </td>
                    <td>
                      <div className="ls-product-cell">
                        <span className="ls-product-name">{p.name}</span>
                        <span className="ls-product-sku" dir="ltr">{p.sku}</span>
                      </div>
                    </td>
                    <td className="ls-supplier-cell">{p.supplier_name ?? "—"}</td>
                    <td className="num low">{num(p.quantity)}</td>
                    <td className="num" style={edited ? { background: "#fff8e1" } : undefined}>
                      {reorderEdit ? (
                        <input
                          dir="ltr"
                          inputMode="numeric"
                          className="ls-reorder-input"
                          aria-label={`حد الطلب — ${p.name}`}
                          value={reorderEdits[p.id] ?? ""}
                          onChange={(e) => setReorder(p.id, e.target.value)}
                        />
                      ) : (
                        num(p.reorder_level)
                      )}
                    </td>
                    <td className="num">
                      <span className={`badge ${critical ? "ls-badge-critical" : "ls-badge-warn"}`}>
                        {critical ? "عجز حاد" : "نقص"} · {num(p.shortfall)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3} className="num">{rows.length} منتج تحت حد الطلب</td>
                <td className="num low">{num(rows.reduce((s, p) => s + p.quantity, 0))}</td>
                <td className="num">{num(rows.reduce((s, p) => s + p.reorder_level, 0))}</td>
                <td className="num low">{num(totalShortfall)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      ) : (
        <div className="card card-pad">
          <Empty>{t("dashboard.allAboveReorder")}</Empty>
        </div>
      )}

      {/* معاينة التقرير قبل الطباعة */}
      {printPreview && (
        <Modal title="معاينة التقرير قبل الطباعة" fullscreen onClose={() => setPrintPreview(null)}>
          <div className="ls-preview-actions">
            <button className="btn btn-primary" onClick={() => printNow(printPreview)}>🖨 اطبع الآن</button>
            <button className="btn" onClick={() => setPrintPreview(null)}>✕ إغلاق</button>
          </div>
          <div className="ls-preview-sheet" dangerouslySetInnerHTML={{ __html: printPreview }} />
        </Modal>
      )}

      {/* ============================ اقتراحات الشراء ============================ */}
      <div className="card card-pad" style={{ marginTop: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
          <h3 style={{ margin: 0 }}>🛒 اقتراحات الشراء{scopeWarehouse ? ` — ${scopeLabel}` : ""}</h3>
          <button className="btn btn-sm" disabled={suggestions.loading} onClick={() => exportFile(`/reports/purchase-suggestions/xlsx${fq}`, "report-purchase-suggestions.xlsx")}>⬇️ Excel</button>
        </div>
        <Alert>{suggestions.error}</Alert>
        {suggestions.loading ? <Loading /> : (suggestions.data ?? []).length ? (() => {
          const bySupplier: Record<string, any[]> = {};
          for (const r of suggestions.data ?? []) {
            const key = r.supplier_name || "بلا مورد محدد";
            (bySupplier[key] = bySupplier[key] || []).push(r);
          }
          return (
            <>
              {Object.entries(bySupplier).map(([supplier, rows]) => (
                <div key={supplier} style={{ marginBottom: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <b>{supplier} <span style={{ color: "var(--muted, #64748b)", fontWeight: 400 }}>({rows.length} صنف · {money(rows.reduce((s, r) => s + Number(r.estimated_cost || 0), 0))})</span></b>
                    {rows[0].supplier_id && (
                      <button className="btn btn-sm btn-primary" disabled={creatingPO === rows[0].supplier_id}
                        onClick={() => createDraftPO(rows[0].supplier_id, supplier)}>
                        {creatingPO === rows[0].supplier_id ? "..." : "أنشئ مسودة أمر شراء"}
                      </button>
                    )}
                  </div>
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>الكود</th><th>الصنف</th><th className="num">المتاح</th><th className="num">حد الطلب</th><th className="num">مقترح</th><th className="num">التكلفة التقديرية</th></tr></thead>
                      <tbody>
                        {rows.map((r: any) => (
                          <tr key={r.product_id}>
                            <td dir="ltr">{r.sku}</td><td>{r.name}</td>
                            <td className="num">{num(r.available)}</td><td className="num">{num(r.target)}</td>
                            <td className="num" style={{ fontWeight: 700 }}>{num(r.suggested_qty)}</td>
                            <td className="num">{money(r.estimated_cost)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </>
          );
        })() : <Empty>لا اقتراحات — كل الأصناف فوق حدود الطلب</Empty>}
      </div>

      {/* ============================ لوطات تنتهي قريبًا ============================ */}
      <div className="card card-pad" style={{ marginTop: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
          <h3 style={{ margin: 0 }}>⏳ لوطات تنتهي خلال 30 يومًا</h3>
          <button className="btn btn-sm" disabled={expiring.loading} onClick={() => exportFile(`/reports/lots-expiring/xlsx?days=30${scopeWarehouse ? `&warehouse_id=${scopeWarehouse}` : ""}`, "report-lots-expiring.xlsx")}>⬇️ Excel</button>
        </div>
        <Alert>{expiring.error}</Alert>
        {expiring.loading ? <Loading /> : (expiring.data ?? []).length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>الكود</th><th>الصنف</th><th>المخزن</th><th>اللوط</th><th>الانتهاء</th><th className="num">متبقي</th><th className="num">الكمية</th></tr></thead>
              <tbody>
                {(expiring.data ?? []).map((r: any) => (
                  <tr key={r.lot_id} style={r.expired ? { background: "rgba(185,28,28,.08)" } : r.days_left <= 7 ? { background: "rgba(245,158,11,.08)" } : undefined}>
                    <td dir="ltr">{r.sku}</td><td>{r.product_name}</td><td>{r.warehouse_name || "—"}</td>
                    <td dir="ltr">{r.lot_code}</td><td dir="ltr">{r.expiry_date}</td>
                    <td className="num" style={r.expired ? { color: "#b91c1c", fontWeight: 700 } : undefined}>{r.expired ? "منتهي ⚠️" : `${r.days_left} يوم`}</td>
                    <td className="num">{num(r.qty_remaining)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>لا لوطات قاربت على الانتهاء 🎉</Empty>}
      </div>
        </>
      )}
    </div>
  );
}

