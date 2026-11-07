import { useState } from "react";
import { api, qs } from "../api";
import { useI18n } from "../i18n";
import { num } from "../format";
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
      setReorderNote("وضع تعديل حد الطلب مفتوح — عدّل «حد الطلب» داخل الجدول، ثم دوس «حفظ حد الطلب».");
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
    setReorderNote(`تم حفظ حد الطلب لـ ${n} صنف` + (errs.length ? ` — أخطاء: ${errs.slice(0, 3).join(" | ")}` : ""));
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
        ? (branches.data ?? []).find((b) => String(b.id) === scopeBranch)?.name ?? `فرع #${scopeBranch}`
        : "الشركة ككل";
  const supplierLabel = scopeSupplier
    ? (suppliers.data ?? []).find((s) => String(s.id) === scopeSupplier)?.name ?? `مورد #${scopeSupplier}`
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
    const scope = esc(`${scopeLabel ?? "الشركة ككل"}${supplierLabel ? " — مورد: " + supplierLabel : ""}`);
    const date = esc(new Date().toLocaleDateString("ar-EG", { year: "numeric", month: "long", day: "numeric" }));
    return (
      `<div class="ls-preview-meta"><h1>${title}</h1><p>${scope} — تاريخ الطباعة: ${date} — عدد المنتجات: ${rows.length}</p></div>` +
      clone.outerHTML
    );
  };

  const printNow = (html: string) => {
    const w = window.open("", "_blank", "width=1020,height=760");
    if (!w) {
      alert("افتح السماح بالنوافذ المنبثقة لتتمكن من الطباعة");
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
          {scopeLabel ?? "الشركة ككل"}
          {supplierLabel && <> — مورد: {supplierLabel}</>}
          {" — تاريخ الطباعة: "}
          {new Date().toLocaleDateString("ar-EG", { year: "numeric", month: "long", day: "numeric" })}
          {" — عدد المنتجات: "}
          {rows.length}
        </p>
      </div>

      <div className="ls-toolbar">
        <label className="ls-filter-label">
          نطاق التنبيه:
          <select
            className="ls-select"
            value={scopeBranch}
            onChange={(e) => {
              setScopeBranch(e.target.value);
              setScopeWarehouse("");
            }}
          >
            <option value="">الشركة ككل</option>
            {(branches.data ?? []).map((b) => (
              <option key={b.id} value={b.id}>
                فرع: {b.name}
              </option>
            ))}
          </select>
        </label>
        <label className="ls-filter-label">
          {scopeBranch ? "مخزن الفرع:" : "مخزن معين:"}
          <select className="ls-select" value={scopeWarehouse} onChange={(e) => setScopeWarehouse(e.target.value)}>
            <option value="">كل المخازن</option>
            {branchWarehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
        <label className="ls-filter-label">
          المورد:
          <select className="ls-select" value={scopeSupplier} onChange={(e) => setScopeSupplier(e.target.value)}>
            <option value="">كل الموردين</option>
            {(suppliers.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <span className="ls-scope-note muted">
          التصنيف الحالي: <b>{scopeLabel ?? "—"}</b>
          {supplierLabel && <> — مورد: <b>{supplierLabel}</b></>}
        </span>
        <input
          type="search"
          className="ls-search"
          placeholder="ابحث بالاسم أو الكود…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className="btn" disabled={download.busy} onClick={() => exportFile(`/reports/low-stock/xlsx${fq}`, "report-low-stock.xlsx")}>
          {download.busy ? "جارٍ التجهيز…" : "⬇ تصدير Excel"}
        </button>
        <button
          className="btn"
          onClick={() => setPrintPreview(buildReportHTML())}
        >
          🖨 طباعة
        </button>
        <button
          className={reorderEdit ? "btn btn-primary" : "btn"}
          onClick={() => toggleReorderEdit(!reorderEdit)}
        >
          {reorderEdit ? "✕ إغلاق وضع التعديل" : "📋 وضع تعديل حد الطلب"}
        </button>
        {reorderEdit && changedReorders.length > 0 && (
          <button className="btn btn-primary" disabled={savingReorder} onClick={() => void saveReorders()}>
            {savingReorder ? "… جارٍ الحفظ" : `💾 حفظ حد الطلب (${changedReorders.length})`}
          </button>
        )}
      </div>

      <Alert>{low.error || download.error}</Alert>
      {reorderEdit && reorderNote && <p className="muted" style={{ margin: "0 0 10px", fontSize: 13 }}>{reorderNote}</p>}

      <div className="kpis" style={{ marginBottom: 14 }}>
        <div className="kpi">
          <div className="label">منتجات تحت حد الطلب</div>
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
    </div>
  );
}

