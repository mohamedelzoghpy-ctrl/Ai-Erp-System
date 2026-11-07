import { useEffect, useState, type FormEvent } from "react";
import { api, qs } from "../api";
import { useI18n } from "../i18n";
import { money, num } from "../format";
import { useAction, useFetch } from "../hooks";
import type { Party, Product, Warehouse } from "../types";
import { Alert, Loading, Modal, PageHeader } from "../ui";

// ---------------------------------------------------------------- shared import machinery
interface Err {
  row?: number | null;
  error: string;
  party?: string | null;
  product?: string | null;
  warehouse?: string | null;
}
type Skips = Record<string, number>;
interface ImportReply {
  preview?: boolean;
  rows?: number;
  created?: number;
  updated?: number;
  changes?: number;
  changed_qty?: number;
  products?: number;
  applied?: number;
  applied_products?: number;
  movements?: number;
  warehouse_id?: number;
  batch?: string;
  skipped?: Skips;
  errors: Err[];
  sample?: Record<string, unknown>[];
}

const SKIP_LABEL: Record<string, string> = {
  totals_rows: "صفوف الإجماليات",
  empty_rows: "صفوف فارغة",
  no_new_value: "دون كمية جديدة",
  no_change: "دون تغيير",
  sample_rows: "صفوف نموذجية",
};

const SAMPLE_LABEL: Record<string, string> = {
  row: "الصف", code: "الرمز", name: "الاسم", opening: "الرصيد الافتتاحي", result: "النتيجة",
  product: "الصنف", current: "الحالي", new: "الجديد", delta: "التغيير", warehouse: "المخزن",
};

function entityOf(e: Err): string {
  return e.party ?? e.product ?? e.warehouse ?? "";
}

/** Errors list + a downloadable CSV report. */
function ErrorsBox({ errors }: { errors: Err[] }) {
  const { t } = useI18n();
  if (!errors?.length) return null;
  const dl = () => {
    const lines = ["الصف,الكيان,الخطأ"];
    for (const e of errors) {
      const cells = [e.row ?? "", entityOf(e), e.error ?? ""].map((c) => `"${String(c).replace(/"/g, '""')}"`);
      lines.push(cells.join(","));
    }
    const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "import-errors.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <div className="card" style={{ border: "1px solid #f0c19b", background: "#fff8f1", padding: 10, marginTop: 8, textAlign: "match-parent" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <b style={{ color: "var(--danger, #b3261e)", fontSize: 13 }}>
          {t("dataio.errors")} ({num(errors.length)})
        </b>
        <button type="button" className="btn btn-sm" onClick={dl}>{t("dataio.dlErrors")}</button>
      </div>
      <table style={{ marginTop: 6, fontSize: 12.5 }}>
        <thead>
          <tr><th>الصف</th><th>الكيان</th><th>الخطأ</th></tr>
        </thead>
        <tbody>
          {errors.slice(0, 30).map((e, i) => (
            <tr key={i}>
              <td dir="ltr">{e.row ?? "—"}</td>
              <td>{entityOf(e) || "—"}</td>
              <td style={{ color: "var(--danger, #b3261e)" }}>{e.error}</td>
            </tr>
          ))}
          {errors.length > 30 && <tr><td colSpan={3} className="muted">… {num(errors.length - 30)} أخطاء أخرى — نزّل التقرير الكامل</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function skipsText(skips?: Skips): string {
  if (!skips) return "";
  const parts = Object.entries(SKIP_LABEL)
    .filter(([k]) => skips[k])
    .map(([k, label]) => `${label}: ${num(skips[k])}`);
  return parts.length ? parts.join(" · ") : "";
}

/** The dry-run modal: what will change + errors, before touching anything. */
function PreviewModal({
  title, data, busy, onConfirm, onClose,
}: { title: string; data: ImportReply; busy: boolean; onConfirm: () => void; onClose: () => void }) {
  const { t } = useI18n();
  const counts: string[] = [];
  if (data.rows != null) counts.push(`صفوف مقروءة: ${num(data.rows)}`);
  if (data.created != null) counts.push(`قادم جديد: ${num(data.created)}`);
  if (data.updated != null) counts.push(`تحديث: ${num(data.updated)}`);
  if (data.changes != null) counts.push(`تغييرات كمية: ${num(data.changes)}`);
  if (data.changed_qty != null) counts.push(`صافي الكميات: ${data.changed_qty > 0 ? "+" : ""}${num(data.changed_qty)}`);
  if (data.products != null) counts.push(`أصناف: ${num(data.products)}`);
  const sample = data.sample ?? [];
  const keys = sample.length ? Object.keys(sample[0]).filter((k) => SAMPLE_LABEL[k]) : [];
  const sk = skipsText(data.skipped);
  return (
    <Modal title={title} onClose={onClose} wide>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBlock: 6 }}>
        {counts.map((c) => (
          <span key={c} className="chip" style={{ background: "#eef3fb", padding: "6px 12px", borderRadius: 20, fontWeight: 600, fontSize: 13 }}>{c}</span>
        ))}
      </div>
      {sk && <p className="muted" style={{ marginTop: 4 }}>{t("dataio.skippedHeader")}{sk}</p>}
      {keys.length > 0 && (
        <div className="card table-wrap" style={{ maxHeight: "40vh", overflow: "auto", marginTop: 8 }}>
          <table>
            <thead>
              <tr>{keys.map((k) => <th key={k}>{SAMPLE_LABEL[k]}</th>)}</tr>
            </thead>
            <tbody>
              {sample.map((r, i) => (
                <tr key={i}>
                  {keys.map((k) => (
                    <td key={k} dir={k === "row" || /qty|opening|new|current|delta/.test(k) ? "ltr" : undefined}>
                      {String(r[k] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorsBox errors={data.errors ?? []} />
      <p className="muted" style={{ fontSize: 12.5 }}>{t("dataio.previewNote")}</p>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={busy || (data.errors ?? []).some((e) => !e.row)} onClick={onConfirm}>
          {busy ? t("dataio.importing") : t("dataio.confirm")}
        </button>
        <button type="button" className="btn" onClick={onClose}>{t("common.cancel")}</button>
      </div>
    </Modal>
  );
}

/** File/sheet-url picker + preview + confirm flow, reused by every import button. */
function ImportBlock({
  buildPath, label, allowUrl = false, onDone, disabled = false, disabledTitle,
}: {
  buildPath: (opts: { preview?: boolean; url?: string }) => string;
  label: string;
  allowUrl?: boolean;
  onDone: () => void;
  disabled?: boolean;
  disabledTitle?: string;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [previewData, setPreviewData] = useState<ImportReply | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [resultErrors, setResultErrors] = useState<Err[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheetUrl, setSheetUrl] = useState("");
  const [urlMode, setUrlMode] = useState(false);
  const [src, setSrc] = useState<{ f?: File; url?: string } | null>(null);  // remembered between preview & confirm

  const run = async (f: File | null, url: string | null, isPreview: boolean) => {
    setBusy(true);
    setError(null);
    if (isPreview) setSrc(f ? { f } : url ? { url } : null);
    try {
      let reply: ImportReply;
      if (f) {
        reply = await api.upload<ImportReply>(buildPath({ preview: isPreview }), f);
      } else if (url) {
        const res = await api.post<ImportReply>(buildPath({ preview: isPreview, url }));
        reply = res;
      } else {
        setError(t("dataio.needSource"));
        return;
      }
      if (reply.preview) {
        setPreviewData(reply);
      } else {
        setPreviewData(null);
        setResult(summarizeDone(reply));
        setResultErrors(reply.errors?.length ? reply.errors : null);
        onDone();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const summarizeDone = (r: ImportReply): string => {
    const parts: string[] = [];
    if (r.created != null) parts.push(`${num(r.created)} جديد`);
    if (r.updated != null) parts.push(`${num(r.updated)} تحديث`);
    if (r.applied != null) parts.push(`تم تعديل ${num(r.applied)} صنف`);
    if (r.applied_products != null) parts.push(`تم تعديل أرصدة ${num(r.applied_products)} صنف عبر المخازن`);
    if (r.changed_qty != null) parts.push(`صافي التغيير ${r.changed_qty > 0 ? "+" : ""}${num(r.changed_qty)}`);
    const sk = skipsText(r.skipped);
    return `${label} — ${parts.join(" · ") || "تم"}` + (sk ? ` · متخطى (${sk})` : "") + (r.errors?.length ? ` · أخطاء: ${num(r.errors.length)}` : "");
  };

  const pick = (e: FormEvent<HTMLInputElement>) => {
    const el = e.target as HTMLInputElement;
    const f = el.files?.[0];
    el.value = "";
    if (f) void run(f, null, true);
  };

  return (
    <>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {disabled ? (
          <button type="button" className="btn btn-primary" disabled title={disabledTitle} style={{ opacity: 0.55 }}>
            {t("dataio.import")}
          </button>
        ) : (
          <label className="btn btn-primary" style={{ cursor: busy ? "wait" : "pointer", opacity: busy ? 0.7 : 1 }}>
            {busy ? t("dataio.importing") : label}
            <input type="file" accept=".xlsx,.xls,.csv,.txt" style={{ display: "none" }} disabled={busy} onChange={pick} />
          </label>
        )}
        {allowUrl && (
          <button type="button" className="btn" onClick={() => setUrlMode((m) => !m)} title={t("dataio.sheetUrlTitle")}>
            🌐
          </button>
        )}
      </div>
      {allowUrl && urlMode && (
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <input
            value={sheetUrl}
            placeholder={t("dataio.sheetUrl")}
            onChange={(e) => setSheetUrl(e.target.value)}
            dir="ltr"
            style={{ flex: 1 }}
          />
          <button type="button" className="btn" disabled={busy || !sheetUrl.trim()} onClick={() => void run(null, sheetUrl.trim(), true)}>
            {t("dataio.importFromUrl")}
          </button>
        </div>
      )}
      <Alert>{error}</Alert>
      {result && (
        <p style={{ background: "var(--ok-bg, #e8f5e9)", color: "var(--ok-fg, #1b5e20)", padding: "8px 10px", borderRadius: 8, fontSize: 13 }}>
          {result}
        </p>
      )}
      <ErrorsBox errors={resultErrors ?? []} />
      {previewData && (
        <PreviewModal
          title={t("dataio.previewTitle")}
          data={previewData}
          busy={busy}
          onClose={() => setPreviewData(null)}
          onConfirm={() => {
            setPreviewData(null);
            void run(src?.f ?? null, src?.url ?? null, false);
          }}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------- party cards
function PartyIOCard({ kind, title }: { kind: "customer" | "supplier"; title: string }) {
  const { t } = useI18n();
  const list = useFetch<Party[]>(() => api.get<Party[]>(`/${kind === "customer" ? "customers" : "suppliers"}?limit=500`), `dataio-${kind}`);
  const dl = useAction();
  const rows = list.data ?? [];
  const totalOpening = rows.reduce((s, p) => s + Number(p.opening_balance || 0), 0);
  const totalBalance = rows.reduce((s, p) => s + Number(p.balance || 0), 0);
  return (
    <div className="card" style={{ padding: 16 }}>
      <h3 style={{ margin: "0 0 6px" }}>{title}</h3>
      <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>{t("dataio.hintNoBalance")}</p>
      {list.loading && !list.data ? (
        <Loading />
      ) : (
        <div className="kpis" style={{ gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 12 }}>
          <div className="card kpi" style={{ padding: "10px 12px" }}>
            <div className="label">{t("dataio.count")}</div>
            <div className="value">{num(rows.length)}</div>
          </div>
          <div className="card kpi" style={{ padding: "10px 12px" }}>
            <div className="label">{t("dataio.totalOpening")}</div>
            <div className="value" dir="ltr">{money(totalOpening)}</div>
          </div>
          <div className="card kpi" style={{ padding: "10px 12px" }}>
            <div className="label">{t("dataio.totalBalance")}</div>
            <div className="value" dir="ltr">{money(totalBalance)}</div>
          </div>
        </div>
      )}
      <Alert>{dl.error}</Alert>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <button className="btn" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/data-io/parties/export/xlsx${qs({ kind })}`, `parties-${kind}.xlsx`))}>{t("dataio.export")}</button>
        <button className="btn" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/data-io/parties/template/xlsx${qs({ kind })}`, `parties-template-${kind}.xlsx`))}>{t("dataio.template")}</button>
        <button className="btn" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/data-io/parties/template/xlsx${qs({ kind, minimal: 1 })}`, `parties-fast-template-${kind}.xlsx`))}>{t("dataio.fastTemplate")}</button>
      </div>
      <ImportBlock
        buildPath={(opts) => `/data-io/parties/import/xlsx?kind=${kind}${opts.preview ? "&preview=1" : ""}${opts.url ? `&url=${encodeURIComponent(opts.url)}` : ""}`}
        label={t("dataio.import")}
        allowUrl
        onDone={() => list.reload()}
      />
    </div>
  );
}

// ---------------------------------------------------------------- warehouses card
function WarehouseIOCard() {
  const { t } = useI18n();
  const list = useFetch<Warehouse[]>(() => api.get<Warehouse[]>("/warehouses?limit=500"), "dataio-wh");
  const products = useFetch<Product[]>(() => api.get<Product[]>("/products?limit=1000"), "dataio-wh-products");
  const [whId, setWhId] = useState("");
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [undoBusy, setUndoBusy] = useState(false);
  const [undoResult, setUndoResult] = useState<string | null>(null);
  const [undoError, setUndoError] = useState<string | null>(null);

  const totalQty = (products.data ?? []).reduce((s, p) => s + (p.quantity || 0), 0);
  const stockValue = (products.data ?? []).reduce((s, p) => s + (p.quantity || 0) * Number(p.cost_price), 0);
  const selected = (list.data ?? []).find((w) => String(w.id) === whId) ?? null;
  const warehouses = list.data ?? [];

  // A single visible warehouse is always the intended target — skip the extra step.
  useEffect(() => {
    if (!whId && warehouses.length === 1) setWhId(String(warehouses[0].id));
  }, [whId, warehouses]);

  const exportStock = async () => {
    if (!whId) return;
    setExportBusy(true);
    setExportError(null);
    try {
      const warehouse = selected;
      await api.download(`/data-io/warehouses/stock/xlsx?warehouse_id=${whId}`, `stock-${warehouse?.code || whId}.xlsx`);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e));
    } finally {
      setExportBusy(false);
    }
  };

  const exportFile = async (path: string, name: string) => {
    setExportBusy(true);
    setExportError(null);
    try {
      await api.download(path, name);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e));
    } finally {
      setExportBusy(false);
    }
  };

  const undo = async () => {
    if (!whId) return;
    if (!confirm(`تراجع عن آخر رفع رصيد على «${selected?.name}»؟ ستُعكس كل التغييرات التي أدخلها الرفع الأخير.`)) return;
    setUndoBusy(true);
    setUndoError(null);
    setUndoResult(null);
    try {
      const res = await api.post<{ products: number; changed_qty: number }>(`/data-io/warehouses/stock/undo?warehouse_id=${whId}`);
      setUndoResult(`تم التراجع: عكس رصيد ${num(res.products)} صنف (صافي ${res.changed_qty > 0 ? "+" : ""}${num(res.changed_qty)})`);
      products.reload();
    } catch (e) {
      setUndoError(e instanceof Error ? e.message : String(e));
    } finally {
      setUndoBusy(false);
    }
  };

  return (
    <div className="card" style={{ padding: 16 }}>
      <h3 style={{ margin: "0 0 6px" }}>{t("dataio.warehouses")}</h3>
      <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>{t("dataio.warehouseHint")}</p>
      {list.loading && !list.data ? (
        <Loading />
      ) : (
        <div className="kpis" style={{ gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 12 }}>
          <div className="card kpi" style={{ padding: "10px 12px" }}>
            <div className="label">{t("dataio.count")}</div>
            <div className="value">{num((list.data ?? []).length)}</div>
          </div>
          <div className="card kpi" style={{ padding: "10px 12px" }}>
            <div className="label">{t("dataio.totalQty")}</div>
            <div className="value" dir="ltr">{num(totalQty)}</div>
          </div>
          <div className="card kpi" style={{ padding: "10px 12px" }}>
            <div className="label">{t("dataio.stockValue")}</div>
            <div className="value" dir="ltr">{money(stockValue)}</div>
          </div>
        </div>
      )}

      {(list.data ?? []).length === 0 && !list.loading && !whId && (
        <p style={{ background: "var(--warn-bg, #fff8f1)", border: "1px solid var(--warn-border, #f0c19b)", color: "var(--warn-fg, #7a4b00)", padding: "8px 12px", borderRadius: 8, fontSize: 13 }}>
          <b>{t("dataio.noWarehouses")}</b> — {t("dataio.noWarehousesHint")}
        </p>
      )}
      <select value={whId} aria-label={"المخزن المستهدف"} style={{ marginBottom: 10, width: "100%" }}
        onChange={(e) => { setWhId(e.target.value); setUndoResult(null); setUndoError(null); }}>
        <option value="">{t("dataio.pickWarehouse")}</option>
        {(list.data ?? []).map((w) => (<option key={w.id} value={w.id}>{w.name} ({w.code})</option>))}
      </select>
      <Alert>{exportError || undoError}</Alert>
      {undoResult && (
        <p style={{ background: "var(--ok-bg, #e8f5e9)", color: "var(--ok-fg, #1b5e20)", padding: "8px 10px", borderRadius: 8, fontSize: 13 }}>{undoResult}</p>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        <button type="button" className="btn" disabled={!whId || exportBusy} title={!whId ? t("dataio.pickFirst") : undefined} onClick={() => void exportStock()} style={{ opacity: !whId ? 0.55 : 1 }}>
          {exportBusy ? "جارٍ التصدير…" : t("dataio.stockExport")}
        </button>
        <button type="button" className="btn" disabled={!whId || undoBusy} title={!whId ? t("dataio.pickFirst") : t("dataio.undoTitle")} onClick={() => void undo()} style={{ opacity: !whId ? 0.55 : 1 }}>
          {undoBusy ? "جارٍ التراجع…" : t("dataio.undo")}
        </button>
      </div>
      {!whId && (list.data ?? []).length > 0 && (
        <p className="muted" style={{ margin: "-8px 0 14px", fontSize: 12.5 }}>💡 {t("dataio.pickFirstHint")}</p>
      )}

      <h3 style={{ fontSize: 14 }}>{t("dataio.warehouses")}</h3>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <button type="button" className="btn" disabled={exportBusy} onClick={() => void exportFile("/data-io/warehouses/export/xlsx", "warehouses.xlsx")}>{t("dataio.export")}</button>
        <button type="button" className="btn" disabled={exportBusy} onClick={() => void exportFile("/data-io/warehouses/template/xlsx", "warehouses-template.xlsx")}>{t("dataio.template")}</button>
      </div>
      <ImportBlock
        buildPath={(opts) => `/data-io/warehouses/import/xlsx${opts.preview ? "?preview=1" : ""}${opts.url ? `${opts.preview ? "&" : "?"}url=${encodeURIComponent(opts.url)}` : ""}`}
        label={t("dataio.import")}
        allowUrl
        onDone={() => list.reload()}
      />
    </div>
  );
}

// ---------------------------------------------------------------- page
export default function DataIO() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("dataio.title")} />
      <p className="muted" style={{ marginTop: 0 }} dir="rtl">{t("dataio.hint")}</p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 16 }}>
        <PartyIOCard kind="customer" title={t("dataio.customers")} />
        <PartyIOCard kind="supplier" title={t("dataio.suppliers")} />
        <WarehouseIOCard />
      </div>
    </>
  );
}
