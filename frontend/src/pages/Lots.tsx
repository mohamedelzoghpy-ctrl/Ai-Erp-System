/** لوطات الخامات: أرصدة اللوطات لكل منتج ومخزن + استلام يدوي/افتتاحي — الصرف يخصص FIFO تلقائيًا. */
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { num } from "../format";
import { useAction, useFetch } from "../hooks";
import { useI18n } from "../i18n";
import type { Product, StockLot, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

export default function Lots() {
  const { t } = useI18n();
  const products = useFetch(() => api.get<Product[]>("/products?limit=1000"), "lots-products");
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses"), "lots-warehouses");
  const [productFilter, setProductFilter] = useState("");
  const lots = useFetch(
    () => api.get<StockLot[]>(`/lots?limit=1000${productFilter ? `&product_id=${productFilter}` : ""}`),
    `lots-${productFilter}`
  );
  const { busy, error, run } = useAction();
  const [showForm, setShowForm] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const [productId, setProductId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [lotCode, setLotCode] = useState("");
  const [qty, setQty] = useState("");
  const [expiry, setExpiry] = useState("");
  const [reference, setReference] = useState("");

  // إعدام/هالك من لوط: حركة مخزنية موثقة بالسبب (مدير فقط — الـAPI يفرض ذلك)
  const [writingOff, setWritingOff] = useState<StockLot | null>(null);
  const [woQty, setWoQty] = useState("");
  const [woReason, setWoReason] = useState("");

  const submitWriteOff = (e: FormEvent) => {
    e.preventDefault();
    if (!writingOff || !woQty || !woReason.trim()) return;
    void run(async () => {
      const saved = await api.post<StockLot>(`/lots/${writingOff.id}/write-off`, {
        qty: Number(woQty),
        reason: woReason.trim(),
      });
      setWritingOff(null);
      setWoQty("");
      setWoReason("");
      setMsg(`⚠️ ${t("تم الإعدام من لوط")} «${saved.lot_code}» — ${t("الرصيد الآن")} ${num(saved.qty_remaining)}`);
      lots.reload();
    });
  };

  const productsList = products.data ?? [];
  const lotsList = lots.data ?? [];
  const totalRemaining = lotsList.reduce((s, l) => s + Number(l.qty_remaining), 0);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!productId || !warehouseId || !lotCode || !qty) return;
    void run(async () => {
      const saved = await api.post<StockLot>("/lots", {
        product_id: Number(productId),
        warehouse_id: Number(warehouseId),
        lot_code: lotCode.trim(),
        qty: Number(qty),
        expiry_date: expiry || null,
        reference: reference || null,
      });
      setShowForm(false);
      setLotCode("");
      setQty("");
      setExpiry("");
      setReference("");
      setMsg(`✅ ${t("لوط")} «${saved.lot_code}» ${t("رصيده الآن")} ${num(saved.qty_remaining)}`);
      lots.reload();
    });
  };

  const receiveMore = (lot: StockLot) => {
    setProductId(String(lot.product_id));
    setWarehouseId(lot.warehouse_id ? String(lot.warehouse_id) : "");
    setLotCode(lot.lot_code);
    setQty("");
    setExpiry(lot.expiry_date ?? "");
    setReference(lot.reference ?? "");
    setShowForm(true);
  };

  return (
    <>
      <PageHeader title={t("📦 لوطات الخامات")}>
        <button className="btn btn-primary" onClick={() => { setShowForm(true); setMsg(null); }}>
          {t("+ استلام لوط")}
        </button>
      </PageHeader>

      {msg && <Alert kind="info">{msg}</Alert>}
      {error && <Alert kind="error">{error}</Alert>}

      <div className="toolbar page-actions" style={{ marginBottom: 14 }}>
        <select value={productFilter} onChange={(e) => setProductFilter(e.target.value)}>
          <option value="">{t("كل الأصناف")}</option>
          {productsList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <span className="badge badge-pill badge-muted">{t("إجمالي المتبقي باللوطات")}: {num(totalRemaining)}</span>
      </div>

      <div className="card table-wrap">
        {lots.loading && !lots.data ? (
          <Loading />
        ) : lotsList.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("اللوط")}</th>
                <th>{t("الصنف")}</th>
                <th>{t("المخزن")}</th>
                <th>{t("المصدر")}</th>
                <th>{t("المرجع")}</th>
                <th className="num">{t("المستلم")}</th>
                <th className="num">{t("المتبقي")}</th>
                <th>{t("انتهاء الصلاحية")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {lotsList.map((l) => {
                const remainingPct = Number(l.qty_received) > 0 ? Math.round((Number(l.qty_remaining) / Number(l.qty_received)) * 100) : 0;
                return (
                  <tr key={l.id}>
                    <td><b dir="ltr">{l.lot_code}</b></td>
                    <td>{l.product_name}</td>
                    <td>{l.warehouse_name ?? t("بدون مخزن")}</td>
                    <td>{l.source === "purchase" ? t("استلام شراء") : l.source === "opening" ? t("افتتاحي") : t("يدوي")}</td>
                    <td>{l.reference ?? "—"}</td>
                    <td className="num">{num(l.qty_received)}</td>
                    <td className="num">
                      <span className={`badge ${remainingPct === 0 ? "badge-off" : "badge-confirmed"}`}>{num(l.qty_remaining)}</span>
                    </td>
                    <td>{l.expiry_date ?? "—"}</td>
                    <td>
                      <button className="btn-edit" onClick={() => receiveMore(l)}>{t("استلام إضافي")}</button>{" "}
                      {Number(l.qty_remaining) > 0 && l.warehouse_id && (
                        <button className="btn-delete" onClick={() => { setWritingOff(l); setWoQty(""); setWoReason(""); }}>{t("إعدام")}</button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا لوطات مسجلة — سجّل استلام لوط، أو أضِف لوطًا للرصيد الافتتاحي لتتبع الخامات.")}</Empty>
        )}
      </div>

      {showForm && (
        <Modal title={t("استلام لوط")} onClose={() => setShowForm(false)}>
          <form onSubmit={submit}>
            {error && <Alert kind="error">{error}</Alert>}
            <Field label={t("الصنف")}>
              <select value={productId} onChange={(e) => setProductId(e.target.value)} required>
                <option value="">— {t("اختر الصنف")} —</option>
                {productsList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </Field>
            <Field label={t("المخزن")} hint={t("الاستلام حركة مخزنية تُضاف لرصيد المخزن المختار")}>
              <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} required>
                <option value="">— {t("اختر المخزن")} —</option>
                {(warehouses.data ?? []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </Field>
            <Field label={t("كود اللوط")} hint={t("نفس الكود لنفس الصنف والمخزن يضيف للرصيد القائم")}>
              <input dir="ltr" value={lotCode} onChange={(e) => setLotCode(e.target.value)} maxLength={60} required />
            </Field>
            <Field label={t("الكمية المستلمة")}>
              <input type="number" min="0" step="0.001" value={qty} onChange={(e) => setQty(e.target.value)} required autoFocus />
            </Field>
            <Field label={t("تاريخ انتهاء الصلاحية (اختياري)")}>
              <input type="date" dir="ltr" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
            </Field>
            <Field label={t("المرجع (اختياري)")}>
              <input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={80} />
            </Field>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={busy}>{t("استلام")}</button>
              <button type="button" className="btn" onClick={() => setShowForm(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {writingOff && (
        <Modal title={`${t("إعدام من لوط")} — ${writingOff.lot_code}`} onClose={() => setWritingOff(null)}>
          <form onSubmit={submitWriteOff}>
            {error && <Alert kind="error">{error}</Alert>}
            <p className="muted" style={{ margin: "0 0 10px", fontSize: 13 }}>
              {t("الرصيد المتاح")}: <b>{num(writingOff.qty_remaining)}</b> — {t("الإعدام حركة مخزنية سالبة موثقة بالسبب، تخصم اللوط والمخزون معاً")}
            </p>
            <Field label={t("الكمية المعدومة")}>
              <input type="number" min="0.001" step="0.001" max={Number(writingOff.qty_remaining)} value={woQty} onChange={(e) => setWoQty(e.target.value)} required autoFocus />
            </Field>
            <Field label={t("السبب")} hint={t("هالك / انتهاء صلاحية / تلف بالتخزين…")}>
              <input value={woReason} onChange={(e) => setWoReason(e.target.value)} required maxLength={200} />
            </Field>
            <div className="form-actions">
              <button type="submit" className="btn-delete" disabled={busy}>{t("تنفيذ الإعدام")}</button>
              <button type="button" className="btn" onClick={() => setWritingOff(null)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
