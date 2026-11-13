import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { money, num } from "../format";
import { useAction, useFetch } from "../hooks";
import type { Bom, Product, WorkCenter } from "../types";
import { ActiveBadge, Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

type ItemRow = { component_id: number | ""; qty_per_output: string; scrap_pct: string; notes: string };
type OperationRow = { name: string; work_center_id: number | ""; run_minutes_per_unit: string; notes: string };

function BomForm({ initial, products, onClose, onSaved }: {
  initial: Bom | null;
  products: Product[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const workCenters = useFetch(() => api.get<WorkCenter[]>("/work-centers"), "bom-work-centers");
  const workCenterList = workCenters.data ?? [];
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
  const [operations, setOperations] = useState<OperationRow[]>(
    initial?.operations?.length
      ? initial.operations.map((op) => ({ name: op.name, work_center_id: op.work_center_id ?? "", run_minutes_per_unit: String(op.run_minutes_per_unit ?? 0), notes: op.notes ?? "" }))
      : []
  );
  const { busy, error, run } = useAction();

  const setItem = (idx: number, patch: Partial<ItemRow>) =>
    setItems((rows) => rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  const addItem = () => setItems((rows) => [...rows, { component_id: "", qty_per_output: "1", scrap_pct: "0", notes: "" }]);
  const removeItem = (idx: number) => setItems((rows) => rows.filter((_, i) => i !== idx));

  const setOperation = (idx: number, patch: Partial<OperationRow>) =>
    setOperations((rows) => rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  const addOperation = () => setOperations((rows) => [...rows, { name: "", work_center_id: "", run_minutes_per_unit: "0", notes: "" }]);
  const removeOperation = (idx: number) => setOperations((rows) => rows.filter((_, i) => i !== idx));

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
        // مسار التشغيل: مراحل مرتبة تُرحَّل لأوامر الإنتاج (صرف مرحلي + تكلفة عمالة)
        operations: operations
          .filter((op) => op.name.trim())
          .map((op, i) => ({
            seq: i + 1,
            name: op.name.trim(),
            work_center_id: op.work_center_id === "" ? null : op.work_center_id,
            run_minutes_per_unit: Number(op.run_minutes_per_unit) || 0,
            notes: op.notes.trim() || null,
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
                      <button type="button" className="btn-delete" onClick={() => removeItem(idx)}>حذف</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button type="button" className="btn btn-sm" onClick={addItem}>+ إضافة مكوّن</button>

        <p style={{ margin: "14px 0 6px", fontWeight: 700, fontSize: 13 }}>
          مسار التشغيل (المراحل):
          <span style={{ fontWeight: 400, color: "#666", marginInlineStart: 8 }}>
            مراحل مرتبة تُرحَّل لأوامر الإنتاج — صرف مرحلي وتكلفة عمالة لكل مركز
          </span>
        </p>
        {operations.length > 0 && (
          <div className="table-wrap" style={{ marginBottom: 8 }}>
            <table>
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>المرحلة</th>
                  <th>مركز التشغيل</th>
                  <th className="num">دقائق/وحدة</th>
                  <th>ملاحظات</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {operations.map((op, idx) => (
                  <tr key={idx}>
                    <td className="num">{idx + 1}</td>
                    <td><input value={op.name} onChange={(e) => setOperation(idx, { name: e.target.value })} required maxLength={150} style={{ minWidth: 160 }} /></td>
                    <td>
                      <select value={String(op.work_center_id)} onChange={(e) => setOperation(idx, { work_center_id: e.target.value === "" ? "" : Number(e.target.value) })} style={{ minWidth: 160 }}>
                        <option value="">— بلا مركز —</option>
                        {workCenterList.filter((wc) => wc.is_active).map((wc) => (
                          <option key={wc.id} value={wc.id}>{wc.name}</option>
                        ))}
                      </select>
                    </td>
                    <td className="num"><input type="number" min="0" step="0.01" value={op.run_minutes_per_unit} onChange={(e) => setOperation(idx, { run_minutes_per_unit: e.target.value })} style={{ width: 100 }} /></td>
                    <td><input value={op.notes} onChange={(e) => setOperation(idx, { notes: e.target.value })} maxLength={200} /></td>
                    <td className="actions">
                      <button type="button" className="btn-delete" onClick={() => removeOperation(idx)}>حذف</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <button type="button" className="btn btn-sm" onClick={addOperation} disabled={workCenterList.length === 0 && operations.length === 0 ? undefined : undefined}>
          + إضافة مرحلة تشغيل
        </button>
        {workCenters.loading && <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>جارٍ تحميل مراكز التشغيل…</div>}
        {!workCenters.loading && workCenterList.length === 0 && operations.length === 0 && (
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            لا مراكز تشغيل معرّفة — أضفها من صفحة «مراكز العمل» أولًا (اختياري: يمكن ترك المسار فارغًا).
          </div>
        )}

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
  const [simulatingBom, setSimulatingBom] = useState<Bom | null>(null);
  const [simQty, setSimQty] = useState<string>("10");
  const [simResult, setSimResult] = useState<any | null>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [toggling, setToggling] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const { busy, error, run } = useAction();

  const productsById = useMemo(() => new Map((products.data ?? []).map((p) => [p.id, p])), [products.data]);

  const filtered = (boms.data ?? []).filter((bom) => {
    const term = search.trim().toLowerCase();
    if (!term) return true;
    const productName = productsById.get(bom.product_id)?.name?.toLowerCase() ?? "";
    return productName.includes(term) || bom.version.toLowerCase().includes(term);
  });

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
        // العمليات تُعاد كما هي — إرسالها فارغة يمسح مسار التشغيل
        operations: (bom.operations ?? []).map((op) => ({ seq: op.seq, name: op.name, work_center_id: op.work_center_id ?? null, run_minutes_per_unit: op.run_minutes_per_unit, notes: op.notes ?? null })),
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
        <input
          style={{ width: 220 }}
          placeholder="بحث بالمنتج أو الإصدار…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className="btn btn-primary" onClick={() => { setEditing(null); setShowForm(true); }}>
          + قائمة مواد جديدة
        </button>
      </PageHeader>

      <Alert>{boms.error || error}</Alert>

      <div className="card table-wrap">
        {boms.loading && !boms.data ? (
          <Loading />
        ) : filtered.length > 0 ? (
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
              {filtered.map((bom) => (
                <tr key={bom.id} style={bom.is_active ? undefined : { opacity: 0.55 }}>
                  <td>{productsById.get(bom.product_id)?.name ?? `#${bom.product_id}`}</td>
                  <td dir="ltr">{bom.version}</td>
                  <td className="num">{num(bom.output_qty)}</td>
                  <td className="num">{bom.items.length}</td>
                  <td className="num">{money(stdCost(bom))}</td>
                  <td><ActiveBadge active={bom.is_active} /></td>
                  <td className="actions">
                    <button className="btn btn-sm" title="محاكي MRP واستكشاف النواقص" onClick={async () => {
                      setSimulatingBom(bom);
                      setSimResult(null);
                      setSimLoading(true);
                      try {
                        const r = await api.get<any>(`/boms/${bom.id}/mrp-simulate?qty_planned=${simQty || "1"}`);
                        setSimResult(r);
                      } catch (err) { alert((err as Error).message); }
                      finally { setSimLoading(false); }
                    }}>
                      ⚡ محاكي MRP
                    </button>{" "}
                    <button className="btn-edit" onClick={() => { setEditing(bom); setShowForm(true); }}>تعديل</button>{" "}
                    <button className={`btn-toggle ${bom.is_active ? "btn-toggle-off" : "btn-toggle-on"}`} disabled={toggling === bom.id} onClick={() => toggleActive(bom)}>{bom.is_active ? "إيقاف" : "تفعيل"}</button>{" "}
                    <button className="btn btn-sm" disabled={toggling === bom.id} onClick={() => { const v = window.prompt("نسخ إلى إصدار (اتركه فارغًا لاقتراح التالي):", ""); if (v !== null) void run(async () => { await api.post(`/boms/${bom.id}/copy`, { version: v || null, is_active: false }); boms.reload(); }); }}>
                      📄 نسخ
                    </button>{" "}
                    <button
                      className="btn-delete"
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
          <Empty>{search ? "لا توجد نتائج مطابقة للبحث." : "لا توجد قوائم مواد — اضغط «+ قائمة مواد جديدة» للبدء."}</Empty>
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
          <Alert>{error}</Alert>
          <p style={{ margin: "0 0 6px" }}>
            هل أنت متأكد من حذف قائمة المواد لإنتاج <strong>{productsById.get(deleting.product_id)?.name}</strong> (إصدار {deleting.version})؟ لا يمكن الرجوع بعد الحذف.
          </p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn-delete"
              disabled={busy}
              onClick={() => doDelete(deleting)}
            >
              {busy ? "جارٍ الحذف…" : "نعم، حذف"}
            </button>
            <button type="button" className="btn" onClick={() => setDeleting(null)}>
              إلغاء
            </button>
          </div>
        </Modal>
      )}

      {simulatingBom && (
        <Modal title={`محاكي تخطيط الاحتياجات (MRP) — ${productsById.get(simulatingBom.product_id)?.name} (${simulatingBom.version})`} onClose={() => setSimulatingBom(null)}>
          <div style={{ marginBottom: 16, display: "flex", gap: 10, alignItems: "center" }}>
            <label style={{ fontWeight: 600 }}>الكمية المخططة:</label>
            <input
              type="number"
              min="1"
              style={{ width: 120 }}
              value={simQty}
              onChange={(e) => setSimQty(e.target.value)}
            />
            <button
              className="btn btn-primary"
              disabled={simLoading}
              onClick={async () => {
                setSimLoading(true);
                try {
                  const r = await api.get<any>(`/boms/${simulatingBom.id}/mrp-simulate?qty_planned=${simQty || "1"}`);
                  setSimResult(r);
                } catch (err) { alert((err as Error).message); }
                finally { setSimLoading(false); }
              }}
            >
              {simLoading ? "جارٍ الحساب…" : "إعادة المحاكاة"}
            </button>
          </div>

          {simResult && (
            <div>
              <div style={{ padding: "10px 14px", borderRadius: 8, marginBottom: 14, background: simResult.can_produce_immediately ? "#e6f4ea" : "#fce8e6", color: simResult.can_produce_immediately ? "#137333" : "#c5221f" }}>
                <strong>{simResult.can_produce_immediately ? "✓ جاهز للتشغيل فوراً: جميع الخامات متوفرة بالكامل في المخزن." : `⚠ يوجد عجز في الخامات — التكلفة التقديرية لتغطية النواقص: ${money(simResult.total_shortage_cost)}`}</strong>
              </div>

              <table style={{ width: "100%", fontSize: "0.9rem" }}>
                <thead>
                  <tr>
                    <th>الخامة</th>
                    <th className="num">المطلوب</th>
                    <th className="num">المتاح بالمخزن</th>
                    <th className="num">العجز</th>
                    <th className="num">تكلفة الشراء</th>
                  </tr>
                </thead>
                <tbody>
                  {simResult.items.map((it: any) => (
                    <tr key={it.component_id} style={{ background: it.has_shortage ? "#fff8f7" : undefined }}>
                      <td><strong>{it.component_name}</strong> <span style={{ color: "#666", fontSize: "0.8rem" }}>({it.component_sku})</span></td>
                      <td className="num">{num(it.required_qty)} {it.unit}</td>
                      <td className="num">{num(it.available_qty)}</td>
                      <td className="num" style={{ color: it.has_shortage ? "#c5221f" : "#137333", fontWeight: it.has_shortage ? 700 : 400 }}>
                        {it.has_shortage ? `${num(it.shortage_qty)}` : "—"}
                      </td>
                      <td className="num">{it.has_shortage ? money(it.estimated_purchase_cost) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Modal>
      )}
    </>
  );
}
