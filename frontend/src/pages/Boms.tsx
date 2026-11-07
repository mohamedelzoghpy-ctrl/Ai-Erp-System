import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { money, num } from "../format";
import { useAction, useFetch } from "../hooks";
import type { Bom, Product } from "../types";
import { ActiveBadge, Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

type ItemRow = { component_id: number | ""; qty_per_output: string; scrap_pct: string; notes: string };

function BomForm({ initial, products, onClose, onSaved }: {
  initial: Bom | null;
  products: Product[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [productId, setProductId] = useState<number | "">(initial?.product_id ?? "");
  const [version, setVersion] = useState(initial?.version ?? "v1");
  const [outputQty, setOutputQty] = useState(String(initial?.output_qty ?? 1));
  const [isActive, setIsActive] = useState(initial?.is_active ?? true);
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [items, setItems] = useState<ItemRow[]>(
    initial?.items?.length
      ? initial.items.map((it) => ({ component_id: it.component_id, qty_per_output: String(it.qty_per_output), scrap_pct: String(it.scrap_pct), notes: it.notes ?? "" }))
      : [{ component_id: "", qty_per_output: "1", scrap_pct: "0", notes: "" }]
  );
  const { busy, error, run } = useAction();

  const setItem = (idx: number, patch: Partial<ItemRow>) =>
    setItems((rows) => rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  const addItem = () => setItems((rows) => [...rows, { component_id: "", qty_per_output: "1", scrap_pct: "0", notes: "" }]);
  const removeItem = (idx: number) => setItems((rows) => rows.filter((_, i) => i !== idx));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (productId === "") return;
    void run(async () => {
      const body = {
        product_id: productId,
        version: version.trim() || "v1",
        output_qty: Number(outputQty) || 1,
        is_active: isActive,
        notes: notes.trim() || null,
        items: items.map((r) => ({
          component_id: r.component_id,
          qty_per_output: r.qty_per_output,
          scrap_pct: r.scrap_pct || "0",
          notes: r.notes.trim() || null,
        })),
      };
      if (initial) await api.patch(`/boms/${initial.id}`, body);
      else await api.post("/boms", body);
      onSaved();
    });
  };

  return (
    <Modal title={initial ? `تعديل قائمة المواد — ${initial.version}` : "قائمة مواد جديدة"} onClose={onClose} wide>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <div className="form-grid">
          <Field label="المنتج النهائي">
            <select value={String(productId)} onChange={(e) => setProductId(e.target.value === "" ? "" : Number(e.target.value))} required>
              <option value="">— اختر المنتج —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </Field>
          <Field label="إصدار القائمة">
            <input dir="ltr" value={version} onChange={(e) => setVersion(e.target.value)} maxLength={20} />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="الكمية الناتجة من القائمة" hint="عدد الوحدات النهائية المنتجة بتطبيق هذه القائمة كاملة">
            <input type="number" min="1" step="1" value={outputQty} onChange={(e) => setOutputQty(e.target.value)} required />
          </Field>
          <Field label="مفعّلة">
            <label className="check" style={{ paddingTop: 8 }}>
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} /> مفعّلة للاستخدام في أوامر التصنيع
            </label>
          </Field>
        </div>

        <p style={{ margin: "8px 0 6px", fontWeight: 700, fontSize: 13 }}>مكونات القائمة:</p>
        <div className="table-wrap" style={{ marginBottom: 8 }}>
          <table>
            <thead>
              <tr>
                <th>المكوّن (خامة)</th>
                <th className="num">الكمية لكل وحدة</th>
                <th className="num">الفاقد %</th>
                <th>ملاحظات</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((row, idx) => (
                <tr key={idx}>
                  <td>
                    <select value={String(row.component_id)} onChange={(e) => setItem(idx, { component_id: Number(e.target.value) })} required style={{ minWidth: 200 }}>
                      <option value="">— اختر المكوّن —</option>
                      {products.filter((p) => p.id !== productId).map((p) => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </select>
                  </td>
                  <td className="num"><input type="number" min="0.001" step="0.001" value={row.qty_per_output} onChange={(e) => setItem(idx, { qty_per_output: e.target.value })} required style={{ width: 110 }} /></td>
                  <td className="num"><input type="number" min="0" max="100" step="0.01" value={row.scrap_pct} onChange={(e) => setItem(idx, { scrap_pct: e.target.value })} style={{ width: 90 }} /></td>
                  <td><input value={row.notes} onChange={(e) => setItem(idx, { notes: e.target.value })} maxLength={200} /></td>
                  <td className="actions">
                    {items.length > 1 && (
                      <button type="button" className="btn btn-sm btn-danger" onClick={() => removeItem(idx)}>حذف</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button type="button" className="btn btn-sm" onClick={addItem}>+ إضافة مكوّن</button>

        <Field label="ملاحظات">
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy}>
            {busy ? "جارٍ الحفظ…" : "حفظ"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            إلغاء
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default function Boms() {
  const boms = useFetch(() => api.get<Bom[]>("/boms"), "boms-list");
  const products = useFetch(() => api.get<Product[]>("/products?limit=1000"), "boms-products");
  const [editing, setEditing] = useState<Bom | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [deleting, setDeleting] = useState<Bom | null>(null);
  const [toggling, setToggling] = useState<number | null>(null);
  const { busy, error, run } = useAction();

  const productsById = useMemo(() => new Map((products.data ?? []).map((p) => [p.id, p])), [products.data]);

  const stdCost = (bom: Bom) => {
    let total = 0;
    for (const it of bom.items) {
      const p = productsById.get(it.component_id);
      const qty = Number(it.qty_per_output) * (1 + Number(it.scrap_pct) / 100);
      total += qty * Number(p?.cost_price ?? 0);
    }
    return total / Math.max(bom.output_qty, 1);
  };

  const toggleActive = (bom: Bom) => {
    setToggling(bom.id);
    void run(async () => {
      await api.patch(`/boms/${bom.id}`, {
        product_id: bom.product_id,
        version: bom.version,
        output_qty: bom.output_qty,
        is_active: !bom.is_active,
        notes: bom.notes,
        items: bom.items.map((it) => ({ component_id: it.component_id, qty_per_output: it.qty_per_output, scrap_pct: it.scrap_pct, notes: it.notes })),
      });
      boms.reload();
    }).finally(() => setToggling(null));
  };

  const doDelete = (bom: Bom) => {
    if (!deleting) return;
    void run(async () => {
      await api.del(`/boms/${bom.id}`);
      setDeleting(null);
      boms.reload();
    });
  };

  const saveAndClose = () => {
    setShowForm(false);
    setEditing(null);
    boms.reload();
  };

  return (
    <>
      <PageHeader title="قوائم المواد (BOM)">
        <button className="btn btn-primary" onClick={() => { setEditing(null); setShowForm(true); }}>
          + قائمة مواد جديدة
        </button>
      </PageHeader>

      <Alert>{boms.error || error}</Alert>

      <div className="card table-wrap">
        {boms.loading && !boms.data ? (
          <Loading />
        ) : boms.data && boms.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>المنتج النهائي</th>
                <th>الإصدار</th>
                <th className="num">كمية الناتج</th>
                <th className="num">عدد المكونات</th>
                <th className="num">التكلفة القياسية للوحدة</th>
                <th>الحالة</th>
                <th>إجراءات</th>
              </tr>
            </thead>
            <tbody>
              {boms.data.map((bom) => (
                <tr key={bom.id} style={bom.is_active ? undefined : { opacity: 0.55 }}>
                  <td>{productsById.get(bom.product_id)?.name ?? `#${bom.product_id}`}</td>
                  <td dir="ltr">{bom.version}</td>
                  <td className="num">{num(bom.output_qty)}</td>
                  <td className="num">{bom.items.length}</td>
                  <td className="num">{money(stdCost(bom))}</td>
                  <td><ActiveBadge active={bom.is_active} /></td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => { setEditing(bom); setShowForm(true); }}>
                      تعديل
                    </button>{" "}
                    <button className="btn btn-sm" disabled={toggling === bom.id} onClick={() => toggleActive(bom)}>
                      {bom.is_active ? "إيقاف" : "تفعيل"}
                    </button>{" "}
                    <button
                      className="btn btn-sm"
                      style={{ color: "var(--danger)", borderColor: "var(--danger)" }}
                      onClick={() => setDeleting(bom)}
                    >
                      حذف
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>لا توجد قوائم مواد — اضغط «+ قائمة مواد جديدة» للبدء.</Empty>
        )}
      </div>

      {(showForm || editing) && (
        <BomForm
          initial={editing}
          products={products.data ?? []}
          onClose={() => { setShowForm(false); setEditing(null); }}
          onSaved={saveAndClose}
        />
      )}

      {deleting && (
        <Modal title={`حذف قائمة المواد — ${deleting.version}`} onClose={() => setDeleting(null)}>
          <p style={{ margin: "0 0 6px" }}>
            هل أنت متأكد من حذف قائمة المواد لإنتاج <strong>{productsById.get(deleting.product_id)?.name}</strong> (إصدار {deleting.version})؟ لا يمكن الرجوع بعد الحذف.
          </p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn"
              style={{ color: "#fff", background: "var(--danger)" }}
              disabled={busy}
              onClick={() => doDelete(deleting)}
            >
              {busy ? "جارٍ الحذف…" : "🗑️ نعم، حذف"}
            </button>
            <button type="button" className="btn" onClick={() => setDeleting(null)}>
              إلغاء
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
