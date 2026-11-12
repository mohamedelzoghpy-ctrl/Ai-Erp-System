import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAction, useFetch } from "../hooks";
import type { Product } from "../types";
import { money } from "../format";
import { Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

interface PriceListRow {
  id: number;
  name: string;
  notes: string | null;
  is_active: boolean;
  customers_count: number;
  items: { product_id: number; sku: string; name: string; unit_price: string }[];
}

/** صفحة قوائم الأسعار: أسعار بديلة لصنف معين تُطبَّق تلقائيًا على عملاء مرتبطين بالقائمة. */
export default function PriceLists() {
  const lists = useFetch(() => api.get<PriceListRow[]>("/price-lists"), "price-lists");
  const products = useFetch(() => api.get<Product[]>("/products?limit=500&is_active=true"), "pl-products");
  const { busy, error, run } = useAction();
  const [msg, setMsg] = useState<string | null>(null);

  const [editing, setEditing] = useState<PriceListRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  // بنود المحرر: product_id → سعر (نص)
  const [items, setItems] = useState<Record<number, string>>({});
  const [addPid, setAddPid] = useState("");
  const [addPrice, setAddPrice] = useState("");

  const openEdit = (pl: PriceListRow) => {
    setEditing(pl);
    setCreating(false);
    setName(pl.name);
    setNotes(pl.notes ?? "");
    setItems(Object.fromEntries(pl.items.map((i) => [i.product_id, String(i.unit_price)])));
  };
  const openCreate = () => {
    setCreating(true);
    setEditing(null);
    setName("");
    setNotes("");
    setItems({});
  };

  const addItem = () => {
    const pid = Number(addPid);
    const price = Number(addPrice);
    if (!pid || !addPrice || isNaN(price) || price < 0) return;
    setItems((m) => ({ ...m, [pid]: String(price) }));
    setAddPid("");
    setAddPrice("");
  };
  const removeItem = (pid: number) => {
    setItems((m) => {
      const n = { ...m };
      delete n[pid];
      return n;
    });
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const payload = {
      name: name.trim(),
      notes: notes.trim() || null,
      items: Object.entries(items).map(([pid, price]) => ({ product_id: Number(pid), unit_price: price })),
    };
    void run(async () => {
      if (editing) await api.put(`/price-lists/${editing.id}`, payload);
      else await api.post("/price-lists", payload);
      setEditing(null);
      setCreating(false);
      setMsg("تم الحفظ");
      lists.reload();
    });
  };

  const remove = (pl: PriceListRow) => {
    if (!confirm(`حذف قائمة «${pl.name}»؟`)) return;
    void run(async () => {
      await api.del(`/price-lists/${pl.id}`);
      lists.reload();
    });
  };

  const byId = new Map((products.data ?? []).map((p) => [p.id, p]));
  const rows = lists.data ?? [];

  return (
    <>
      <PageHeader title="قوائم الأسعار" />
      <Alert>{lists.error}</Alert>
      {error && <Alert>{error}</Alert>}
      {msg && <Alert kind="info">{msg}</Alert>}
      <div className="page-actions" style={{ marginBottom: 12 }}>
        <button className="btn btn-primary" onClick={openCreate}>+ قائمة جديدة</button>
      </div>

      {lists.loading && !rows.length ? <Loading /> : rows.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>القائمة</th><th>عدد الأسعار</th><th>العملاء المرتبطون</th><th>الحالة</th><th></th></tr></thead>
            <tbody>
              {rows.map((pl) => (
                <tr key={pl.id}>
                  <td>{pl.name}{pl.notes ? <span style={{ color: "var(--muted,#64748b)" }}> — {pl.notes}</span> : null}</td>
                  <td className="num">{pl.items.length}</td>
                  <td className="num">{pl.customers_count}</td>
                  <td>{pl.is_active ? "نشطة" : "متوقفة"}</td>
                  <td>
                    <button className="btn-edit" onClick={() => openEdit(pl)}>تعديل ✏️</button>{" "}
                    <button className="btn-delete" onClick={() => remove(pl)}>حذف 🗑️</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>لا قوائم — أنشئ «جملة» أو «موزعين» واربطها بعملائها</Empty>}

      {(creating || editing) && (
        <Modal title={editing ? `تعديل قائمة — ${editing.name}` : "قائمة أسعار جديدة"} onClose={() => { setEditing(null); setCreating(false); }} wide>
          <form onSubmit={submit}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="اسم القائمة"><input value={name} onChange={(e) => setName(e.target.value)} required /></Field>
              <Field label="ملاحظات"><input value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
            </div>
            <h4 style={{ margin: "12px 0 6px" }}>أسعار الأصناف (تتجاوز سعر البيع العام لحاملي القائمة)</h4>
            <div style={{ display: "flex", gap: 6, alignItems: "end", flexWrap: "wrap", marginBottom: 8 }}>
              <Field label="الصنف">
                <select value={addPid} onChange={(e) => setAddPid(e.target.value)} style={{ minWidth: 240 }}>
                  <option value="">— اختر صنفًا —</option>
                  {(products.data ?? []).filter((p) => items[p.id] === undefined).map((p) => (
                    <option key={p.id} value={p.id}>{p.sku} — {p.name} (العام: {money(p.sale_price)})</option>
                  ))}
                </select>
              </Field>
              <Field label="السعر الخاص">
                <input dir="ltr" type="number" step="0.01" min={0} value={addPrice} onChange={(e) => setAddPrice(e.target.value)} />
              </Field>
              <button type="button" className="btn btn-sm btn-primary" onClick={addItem}>+ إضافة</button>
            </div>
            {Object.keys(items).length ? (
              <div className="table-wrap" style={{ marginBottom: 10 }}>
                <table>
                  <thead><tr><th>الصنف</th><th>السعر الخاص</th><th></th></tr></thead>
                  <tbody>
                    {Object.entries(items).map(([pid, price]) => {
                      const p = byId.get(Number(pid));
                      return (
                        <tr key={pid}>
                          <td>{p ? `${p.sku} — ${p.name}` : `#${pid}`} <span style={{ color: "var(--muted,#64748b)" }}>(العام: {money(p?.sale_price ?? 0)})</span></td>
                          <td className="num">
                            <input dir="ltr" type="number" step="0.01" min={0} value={price}
                              onChange={(e) => setItems((m) => ({ ...m, [Number(pid)]: e.target.value }))} style={{ width: 100 }} />
                          </td>
                          <td><button type="button" className="btn btn-sm btn-danger" onClick={() => removeItem(Number(pid))}>×</button></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : <Empty>لا أسعار في القائمة بعد</Empty>}
            <div className="form-actions">
              <button className="btn btn-primary" disabled={busy}>{busy ? "..." : "حفظ"}</button>
              <button type="button" className="btn" onClick={() => { setEditing(null); setCreating(false); }}>إلغاء</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
