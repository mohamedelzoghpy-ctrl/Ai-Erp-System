import { useState, type FormEvent } from "react";
import { api, getToken } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { dateTime, money, num, reasonLabel } from "../format";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Party, Product, StockMovement, ProductStockRow, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader, Pager, ProductThumb } from "../ui";

export default function Products() {
  const { isManager } = useAuth();
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const [history, setHistory] = useState<Product | null>(null);

  const products = usePagedList<Product>("/products", { search: search.trim(), low_stock: lowOnly, is_active: showInactive ? undefined : true });
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?limit=500"), "wh");
  const suppliers = useFetch(() => api.get<Party[]>("/suppliers?limit=500"), "sup");
  const rows = products.data ?? [];
  const action = useAction();
  const [tmplBusy, setTmplBusy] = useState(false);
  const [tmplNote, setTmplNote] = useState<string | null>(null);
  type ImportSummary = { updated: number; created: number; errors: string[] };
  type ImportCheck = ImportSummary & { file: File };
  const [pending, setPending] = useState<ImportCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [importNote, setImportNote] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  // وضع تعديل الأسعار: خانات تكلفة/بيع في الجدول + حفظ المتغير منها دفعة واحدة
  type PriceEdits = Record<number, { cost_price: string; sale_price: string }>;
  const [priceEdit, setPriceEdit] = useState(false);
  const [edits, setEdits] = useState<PriceEdits>({});
  const [savingPrices, setSavingPrices] = useState(false);
  const [priceNote, setPriceNote] = useState<string | null>(null);

  const togglePriceEdit = (on: boolean) => {
    setPriceEdit(on);
    setEdits({});
    setPriceNote(on ? t("وضع تعديل الأسعار مفتوح — عدّل «التكلفة» و«سعر البيع» داخل الجدول، ثم دوس «حفظ الأسعار».") : null);
    if (on) {
      const init: PriceEdits = {};
      for (const p of rows) init[p.id] = { cost_price: String(p.cost_price), sale_price: String(p.sale_price) };
      setEdits(init);
    }
  };

  const setEdit = (id: number, key: "cost_price" | "sale_price", v: string) => {
    // اكتب بيدك: عربي أو إنجليزي، نقط أو فاصلة — كل الخطوط بتتحول شكل واحد موحد هنا
    const t = v
      .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
      .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
      .replace(/[٫,،]/g, ".")
      .replace(/[^0-9.]/g, "")
      .replace(/\.(?=.*\.)/g, "");
    setEdits((prev) => ({ ...prev, [id]: { ...(prev[id] ?? { cost_price: "", sale_price: "" }), [key]: t } }));
  };

  const changedRows = rows.filter((p) => {
    const e = edits[p.id];
    if (!e) return false;
    const c = Number(e.cost_price), s = Number(e.sale_price);
    const costChanged = e.cost_price !== "" && c !== Number(p.cost_price);
    const saleChanged = e.sale_price !== "" && s !== Number(p.sale_price);
    return costChanged || saleChanged;
  });

  const savePrices = async () => {
    setSavingPrices(true);
    let n = 0;
    const errs: string[] = [];
    for (const p of changedRows) {
      const e = edits[p.id];
      const body: Record<string, string> = {};
      if (Number(e.cost_price) !== Number(p.cost_price)) body.cost_price = e.cost_price || "0";
      if (Number(e.sale_price) !== Number(p.sale_price)) body.sale_price = e.sale_price || "0";
      try {
        await api.patch(`/products/${p.id}`, body);
        n += 1;
      } catch (err) {
        errs.push(`${p.sku}: ${(err as Error).message}`);
      }
    }
    setSavingPrices(false);
    setEdits({});
    setPriceNote(`${t("تم حفظ أسعار ")}${n}${t(" صنف")}` + (errs.length ? `${t(" — أخطاء: ")}${errs.slice(0, 3).join(" | ")}` : "") );
    products.reload();
  };

  // وضع تعديل حد الطلب انتقل لصفحة «تنبيهات نقص المخزون» (LowStock) — هنا تُعدَّل الأسعار فقط، وحد الطلب من نموذج تعديل المنتج.

  const downloadTemplate = async () => {
    setTmplBusy(true);
    setTmplNote(null);
    try {
      await api.download("/products/import-template/xlsx", "products-upload-template.xlsx");
      setTmplNote(t("نزل النموذج في «التنزيلات» — املأ الأعمدة وارفعه من زرار الاستيراد."));
    } catch (e) {
      setTmplNote((e as Error).message);
    } finally {
      setTmplBusy(false);
    }
  };

  // اختبار النموذج أولًا (dry run بدون تسجيل) — العدّاد يظهر في المودال ثم بعد الرفع الفعلي
  const checkFile = async (f: File) => {
    setChecking(true);
    setImportNote(null);
    try {
      const res = await api.upload<ImportSummary>("/products/import/xlsx?dry_run=true", f);
      setPending({ file: f, ...res });
    } catch (e) {
      setImportNote((e as Error).message);
    } finally {
      setChecking(false);
    }
  };

  const confirmImport = async () => {
    if (!pending) return;
    setImporting(true);
    try {
      const res = await api.upload<ImportSummary>("/products/import/xlsx", pending.file);
      setImportNote(
        `${t("العدّاد: ")}${res.created}${t(" جديد · ")}${res.updated}${t(" تحديث · ")}${res.errors.length}${t(" خطأ")}` +
          (res.errors.length ? `${t(" — آخر الأخطاء: ")}${res.errors.slice(0, 3).join(" | ")}` : ""),
      );
      setPending(null);
      products.reload();
    } catch (e) {
      setImportNote((e as Error).message);
    } finally {
      setImporting(false);
    }
  };

  return (
    <>
      <PageHeader title={t("products.title")}>
        <button className="btn btn-primary" onClick={() => setEditing("new")}>
          {t("products.new")}
        </button>
        <button
          className="btn"
          disabled={action.busy}
          onClick={() => void action.run(() => api.download("/products/export/xlsx", "products.xlsx"))}
        >
          {t("⬇ تصدير Excel")}
        </button>
        <button className="btn" disabled={tmplBusy} onClick={() => void downloadTemplate()}>
          {tmplBusy ? t("… جارٍ التنزيل") : t("⬇ نموذج رفع المنتجات")}
        </button>
        <label className="btn" style={{ cursor: "pointer" }}>
          {checking ? t("… جارٍ الاختبار") : t("⬆ استيراد Excel")}
          <input type="file" accept=".xlsx,.xls" style={{ display: "none" }} onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            void checkFile(f);
            e.target.value = "";
          }} />
        </label>
        <button className="btn" onClick={() => {
          const w = window.open("", "_blank");
          if (!w) return;
          const rowsHtml = rows.map((p) => {
            const sup = suppliers.data?.find((s) => s.id === p.supplier_id);
            return `
            <tr>
              <td>${p.sku}</td>
              <td>${p.name}</td>
              <td>${sup?.code ?? ""}</td>
              <td>${sup?.name ?? ""}</td>
              <td>${p.unit || "—"}</td>
              <td>${money(p.cost_price)}</td>
              <td>${money(p.sale_price)}</td>
            </tr>`;
          }).join("");
          w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>${t("قائمة المنتجات")}</title>
            <style>
              body { font-family: Tahoma, Arial, sans-serif; padding: 16px; }
              h1 { text-align: center; }
              table { width: 100%; border-collapse: collapse; }
              th, td { border: 1px solid #999; padding: 6px 8px; text-align: center; }
              th { background: #eee; }
              .num { text-align: center; }
            </style></head><body>
            <h1>${t("قائمة المنتجات")}</h1>
            <table>
              <thead><tr>
                <th>${t("كود الصنف")}</th><th>${t("الاسم")}</th><th>${t("كود المورد")}</th><th>${t("اسم المورد")}</th><th>${t("الوحدة")}</th><th>${t("التكلفة")}</th><th>${t("سعر البيع")}</th>
              </tr></thead>
              <tbody>${rowsHtml}</tbody>
            </table>
            </table>
            <script>window.onload = () => { window.print(); };</script>
            </body></html>`);
          w.document.close();
        }}>
          {t("🖨 طباعة")}
        </button>
      </PageHeader>

      {tmplNote && (
        <p style={{ marginTop: 8, padding: "8px 10px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg, #e8f5e9)", color: "var(--ok-fg, #1b5e20)" }}>
          {tmplNote}
        </p>
      )}

      {importNote && (
        <div
          dir="rtl"
          style={{
            marginTop: 8,
            padding: "10px 12px",
            borderRadius: 8,
            fontSize: 14,
            background: importNote.startsWith("العدّاد") ? "var(--ok-bg, #e8f5e9)" : "#fdecea",
            color: importNote.startsWith("العدّاد") ? "var(--ok-fg, #1b5e20)" : "#93321b",
            border: "1px solid rgba(0,0,0,0.08)",
          }}
        >
          {importNote}
        </div>
      )}

      {pending && (
        <Modal title={t("اختبار النموذج")} onClose={() => setPending(null)}>
          <p style={{ marginTop: 0, color: "var(--muted, #6B778A)", fontSize: 13 }}>
            {t("الملف: ")}<b dir="ltr">{pending.file.name}</b>{t(" — تجربة بدون تسجيل، الرفع الفعلي يتم بعد تأكيدك.")}
          </p>
          <div style={{ display: "flex", gap: 10, margin: "14px 0" }}>
            <div style={{ flex: 1, padding: 12, borderRadius: 10, background: "#e8f5e9", color: "#1b5e20", textAlign: "center" }}>
              <div style={{ fontSize: 26, fontWeight: 700 }}>{pending.created}</div>
              <div style={{ fontSize: 12 }}>{t("صنف جديد")}</div>
            </div>
            <div style={{ flex: 1, padding: 12, borderRadius: 10, background: "#e3f2fd", color: "#0d47a1", textAlign: "center" }}>
              <div style={{ fontSize: 26, fontWeight: 700 }}>{pending.updated}</div>
              <div style={{ fontSize: 12 }}>{t("تحديث صنف موجود")}</div>
            </div>
            <div style={{ flex: 1, padding: 12, borderRadius: 10, background: pending.errors.length ? "#fdecea" : "#efeef4", color: pending.errors.length ? "#93321b" : "#555", textAlign: "center" }}>
              <div style={{ fontSize: 26, fontWeight: 700 }}>{pending.errors.length}</div>
              <div style={{ fontSize: 12 }}>{t("خطأ")}</div>
            </div>
          </div>
          {pending.errors.length > 0 && (
            <ul dir="rtl" style={{ maxHeight: 140, overflowY: "auto", margin: "0 0 14px", paddingRight: 18, fontSize: 13, color: "#93321b" }}>
              {pending.errors.slice(0, 10).map((err, i) => (
                <li key={i}>{err}</li>
              ))}
              {pending.errors.length > 10 && <li>{t("… (")}{pending.errors.length - 10}{t(" أخرى)")}</li>}
            </ul>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary" disabled={importing} onClick={() => void confirmImport()} style={{ flex: 1 }}>
              {importing ? t("… جارٍ الرفع") : `${t("تأكيد الرفع (")}${pending.created}${t(" جديد، ")}${pending.updated}${t(" تحديث)")}`}
            </button>
            <button className="btn" disabled={importing} onClick={() => setPending(null)}>
              {t("إلغاء")}
            </button>
          </div>
        </Modal>
      )}

      <div className="toolbar page-actions" style={{ marginBottom: 14 }}>
        <input placeholder={t("products.search")} value={search} onChange={(e) => setSearch(e.target.value)} />
        <label className="check">
          <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} /> {t("products.lowStock")}
        </label>
        <label className="check">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> {t("products.showInactive")}
        </label>
        <button
          className={priceEdit ? "btn btn-primary" : "btn"}
          onClick={() => togglePriceEdit(!priceEdit)}
        >
          {priceEdit ? t("✕ إغلاق وضع التعديل") : t("✏️ وضع تعديل الأسعار")}
        </button>
        {priceEdit && changedRows.length > 0 && (
          <button className="btn btn-primary" disabled={savingPrices} onClick={() => void savePrices()}>
            {savingPrices ? t("… جارٍ الحفظ") : `${t("💾 حفظ الأسعار (")}${changedRows.length}${t(")")}`}
          </button>
        )}
      </div>

      {priceNote && (
        <div
          dir="rtl"
          style={{
            marginBottom: 10,
            padding: "8px 12px",
            borderRadius: 8,
            fontSize: 13,
            background: priceNote.startsWith("تم حفظ") ? "var(--ok-bg, #e8f5e9)" : "#fff8e1",
            color: priceNote.startsWith("تم حفظ") ? "var(--ok-fg, #1b5e20)" : "#7F6000",
            border: "1px solid rgba(0,0,0,0.08)",
          }}
        >
          {priceNote}
        </div>
      )}

      <Alert>{products.error || action.error}</Alert>

      <div className="card table-wrap">
        {products.loading && !products.data ? (
          <Loading />
        ) : rows.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th style={{ width: 56 }}>{t("صورة")}</th>
                <th>{t("products.sku")}</th>
                <th>{t("products.name")}</th>
                <th>{t("كود المورد")}</th>
                <th>{t("اسم المورد")}</th>
                <th>{t("الوحدة")}</th>
                <th className="num">{t("products.cost")}</th>
                <th className="num">{t("products.salePrice")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const sup = suppliers.data?.find((s) => s.id === p.supplier_id);
                const edit = priceEdit ? (edits[p.id] ?? { cost_price: String(p.cost_price), sale_price: String(p.sale_price) }) : null;
                const isChanged = edit && (Number(edit.cost_price) !== Number(p.cost_price) || Number(edit.sale_price) !== Number(p.sale_price));
                const inputStyle: React.CSSProperties = { width: 95, textAlign: "end" };
                return (
                  <tr key={p.id} style={p.is_active ? undefined : { opacity: 0.55 }}>
                    <td>
                      <ProductThumb product={p} />
                    </td>
                    <td dir="ltr">{p.sku}</td>
                    <td
                      style={isChanged ? { background: "#fff8e1" } : undefined}
                    >
                      {p.name}
                      {!p.is_active && <span className="badge badge-off" style={{ marginInlineStart: 8 }}>inactive</span>}
                    </td>
                    <td dir="ltr" style={{ fontSize: 12 }}>{sup?.code ?? "—"}</td>
                    <td>{sup?.name ?? ""}</td>
                    <td>{p.unit || "—"}</td>
                    {priceEdit && isManager ? (
                      <td className="num" style={Number(edit?.cost_price) !== Number(p.cost_price) ? { background: "#fff8e1" } : undefined}>
                        <input
                          dir="ltr"
                          inputMode="decimal"
                          style={inputStyle}
                          value={edit?.cost_price ?? ""}
                          onChange={(e) => setEdit(p.id, "cost_price", e.target.value)}
                        />
                      </td>
                    ) : (
                      <td className="num" style={isChanged ? { background: "#fff8e1" } : undefined}>{money(p.cost_price)}</td>
                    )}
                    {priceEdit ? (
                      <td className="num" style={Number(edit?.sale_price) !== Number(p.sale_price) ? { background: "#fff8e1" } : undefined}>
                        <input
                          dir="ltr"
                          inputMode="decimal"
                          style={inputStyle}
                          value={edit?.sale_price ?? ""}
                          onChange={(e) => setEdit(p.id, "sale_price", e.target.value)}
                        />
                      </td>
                    ) : (
                      <td className="num" style={isChanged ? { background: "#fff8e1" } : undefined}>{money(p.sale_price)}</td>
                    )}
                    <td className="actions">
                      <button className="btn-edit" onClick={() => setEditing(p)}>{t("تعديل")}</button>
                      <button className="btn btn-sm" onClick={() => setHistory(p)}>
                        {t("الحركات")}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <Empty>{search || lowOnly ? t("products.noResults") : t("products.empty")}</Empty>
        )}
        <Pager list={products} />
      </div>

      {editing && (
        <ProductForm
          initial={editing === "new" ? null : editing}
          isManager={isManager}
          warehouses={warehouses.data ?? []}
          suppliers={suppliers.data ?? []}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            products.reload();
          }}
        />
      )}
      {history && <MovementsModal product={history} onClose={() => setHistory(null)} />}
    </>
  );
}

function ProductForm({
  initial,
  isManager,
  warehouses,
  suppliers,
  onClose,
  onSaved,
}: {
  initial: Product | null;
  isManager: boolean;
  warehouses: Warehouse[];
  suppliers: Party[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  // أنواع الوحدات المتاحة لاختيارها عند إضافة/تعديل منتج
  // (القيم تُخزَّن كما هي في قاعدة البيانات — الترجمة تُطبَّق على العرض فقط)
  const PRODUCT_UNITS = ["قطعة", "علبة", "كرتونة", "عبوة", "دستة", "زجاجة", "رول", "طقم", "كجم", "جرام", "لتر", "متر", "سم"];
  const [f, setF] = useState({
    sku: initial?.sku ?? "",
    name: initial?.name ?? "",
    description: initial?.description ?? "",
    unit: initial?.unit ?? "قطعة",
    cost_price: initial?.cost_price ?? "0",
    sale_price: initial?.sale_price ?? "0",
    quantity: "0",
    reorder_level: String(initial?.reorder_level ?? 0),
    warehouse_id: initial?.warehouse_id ? String(initial.warehouse_id) : "",
    supplier_id: initial?.supplier_id ? String(initial.supplier_id) : "",
    is_active: initial?.is_active ?? true,
    image_url: initial?.image_url ?? "",
  });
  const { busy, error, run } = useAction();
  const set = (k: keyof typeof f, v: string | boolean) => setF((p) => ({ ...p, [k]: v }));
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imageNote, setImageNote] = useState<string | null>(null);
  const imageUrl = f.image_url.trim() || null;
  const _tok = getToken();
  const previewSrc = imageFile
    ? URL.createObjectURL(imageFile)
    : initial?.image_uploaded
      ? `/api/products/${initial.id}/image${_tok ? `?token=${encodeURIComponent(_tok)}` : ""}`
      : imageUrl;
  const currentImageTitle = initial?.image_uploaded ? t("صورة مرفوعة من الجهاز") : imageUrl ? t("صورة من رابط") : t("لا صورة بعد");

  const pickImage = (file: File | null) => {
    setImageFile(file);
    if (file && file.size > 3 * 1024 * 1024) {
      setImageNote(t("⚠️ حجم الصورة أكبر من 3 ميجابايت — اختر صورة أصغر."));
      setImageFile(null);
      return;
    }
    if (file && !file.type.startsWith("image/")) {
      setImageNote(t("⚠️ المفروض ملف صورة (PNG/JPEG/WebP/GIF)."));
      setImageFile(null);
      return;
    }
    setImageNote(null);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const common = {
      name: f.name.trim(),
      description: f.description.trim() || null,
      unit: f.unit.trim() || "قطعة",
      sale_price: f.sale_price || "0",
      reorder_level: Number(f.reorder_level) || 0,
      is_active: f.is_active,
      warehouse_id: f.warehouse_id ? Number(f.warehouse_id) : null,
      supplier_id: f.supplier_id ? Number(f.supplier_id) : null,
      image_url: imageUrl,
      ...(isManager ? { cost_price: f.cost_price || "0" } : {}),
    };
    void run(async () => {
      if (initial) {
        await api.patch(`/products/${initial.id}`, common);
        if (imageFile) await api.upload(`/products/${initial.id}/image`, imageFile);
      } else {
        const created = await api.post<Product>("/products", {
          ...common,
          ...(f.sku.trim() ? { sku: f.sku.trim() } : {}),
          ...(isManager ? { quantity: Number(f.quantity) || 0 } : {}),
        });
        if (imageFile) await api.upload(`/products/${created.id}/image`, imageFile);
      }
      onSaved();
    });
  };

  return (
    <Modal title={initial ? t("تعديل منتج") : t("منتج جديد")} onClose={onClose} wide>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <div className="form-grid">
          {!initial && <p className="field-hint">{t("سيُنشأ رمز SKU تلقائيًا من اسم المنتج عند الحفظ.")}</p>}
          <Field label={t("اسم المنتج")}>
            <input value={f.name} onChange={(e) => set("name", e.target.value)} required autoFocus={!!initial} />
          </Field>
          <Field label={t("سعر التكلفة")}>
            <input
              type="number"
              min="0"
              step="0.01"
              value={f.cost_price}
              readOnly={!isManager}
              title={isManager ? undefined : t("تعديل سعر التكلفة للمدير فقط")}
              onChange={(e) => set("cost_price", e.target.value)}
            />
          </Field>
          <Field label={t("سعر البيع")}>
            <input type="number" min="0" step="0.01" value={f.sale_price} onChange={(e) => set("sale_price", e.target.value)} />
          </Field>
          <Field label={t("الوحدة")}>
            <select value={f.unit} onChange={(e) => set("unit", e.target.value)}>
              {(f.unit && !PRODUCT_UNITS.includes(f.unit) ? [...PRODUCT_UNITS, f.unit] : PRODUCT_UNITS).map((u) => (
                <option key={u} value={u}>{t(u)}</option>
              ))}
            </select>
          </Field>
          <Field label={t("حد إعادة الطلب")}>
            <input type="number" min="0" step="1" value={f.reorder_level} onChange={(e) => set("reorder_level", e.target.value)} />
          </Field>
          <Field label={t("المخزن")}>
            <select value={f.warehouse_id} onChange={(e) => set("warehouse_id", e.target.value)}>
              <option value="">{t("— بدون —")}</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("المورد")}>
            <select value={f.supplier_id} onChange={(e) => set("supplier_id", e.target.value)}>
              <option value="">{t("— بدون —")}</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label={t("الوصف")}>
          <textarea rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} />
        </Field>
        <div className="product-image-field">
          <div className="product-image-preview" title={currentImageTitle}>
            {previewSrc ? (
              <img src={previewSrc} alt={t("معاينة صورة المنتج")} style={{ width: 96, height: 96, objectFit: "cover", borderRadius: 8, border: "1px solid var(--border, #d8dde6)" }} onError={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = "0.25"; }} />
            ) : (
              <div style={{ width: 96, height: 96, borderRadius: 8, border: "1px dashed var(--border, #d8dde6)", display: "grid", placeItems: "center", fontSize: 40 }} aria-label={t("بدون صورة")}>📦</div>
            )}
          </div>
          <div style={{ flex: 1 }}>
            <Field label={t("رابط الصورة من الإنترنت")} hint={t("http:// أو https:// — تُستخدم لو مفيش ملف مرفوع")}>
              <input dir="ltr" type="text" placeholder="https://example.com/product.jpg" value={f.image_url} onChange={(e) => set("image_url", e.target.value)} />
            </Field>
            <Field label={t("أو ارفع صورة من جهازك")} hint={imageNote ?? t("PNG / JPEG / WebP / GIF — حتى 3 ميجابايت")}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <label className="btn btn-primary" style={{ cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6 }}>
                  {t("📁 اختر صورة من الجهاز")}
                  <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" style={{ display: "none" }} onChange={(e) => pickImage(e.target.files?.[0] ?? null)} />
                </label>
                <span className="muted" style={{ fontSize: 13 }}>
                  {imageFile ? `${t("تم الاختيار: ")}${imageFile.name}` : t("لم يتم اختيار صورة")}
                </span>
              </div>
            </Field>
          </div>
        </div>
        <label className="check">
          <input type="checkbox" checked={f.is_active} onChange={(e) => set("is_active", e.target.checked)} /> active
        </label>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy}>
            {busy ? t("جارٍ الحفظ…") : t("حفظ")}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            {t("إلغاء")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function MovementsModal({ product, onClose }: { product: Product; onClose: () => void }) {
  const { t } = useI18n();
  const moves = useFetch(() => api.get<StockMovement[]>(`/products/${product.id}/movements`), `m${product.id}`);
  const where = useFetch(() => api.get<ProductStockRow[]>(`/products/${product.id}/stock`), `w${product.id}`);
  return (
    <Modal title={`${t("حركة المخزون — ")}${product.name}`} onClose={onClose} wide>
      <Alert>{moves.error || where.error}</Alert>
      {where.data && where.data.length > 0 && (
        <p data-testid="stock-by-warehouse">
          {t("الكمية حسب المخزن:")}{" "}
          {where.data.map((r, i) => (
            <span key={r.warehouse_id}>
              {i > 0 && " · "}
              {r.warehouse_name}: <b>{num(r.quantity)}</b>
            </span>
          ))}
        </p>
      )}
      {moves.loading && !moves.data ? (
        <Loading />
      ) : moves.data && moves.data.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("التاريخ")}</th>
                <th>{t("النوع")}</th>
                <th>{t("المرجع")}</th>
                <th className="num">{t("التغيير")}</th>
              </tr>
            </thead>
            <tbody>
              {moves.data.map((m) => (
                <tr key={m.id}>
                  <td>{dateTime(m.created_at)}</td>
                  <td>{reasonLabel(m.reason)}</td>
                  <td>{m.reference || "—"}</td>
                  <td className="num" dir="ltr" style={{ color: m.change < 0 ? "var(--danger)" : "var(--ok)", fontWeight: 600 }}>
                    {m.change > 0 ? `+${m.change}` : m.change}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>{t("لا توجد حركات لهذا المنتج.")}</Empty>
      )}
    </Modal>
  );
}
