import { useState } from "react";
import { api } from "../api";
import { money, num } from "../format";
import { useAction, useFetch } from "../hooks";
import { PRODUCTION_STATUS_LABEL } from "../types";
import type { Bom, ProductionLine, ProductionOrder, ProductionOrderStatus, Warehouse } from "../types";
import { ActiveBadge, Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";
import type { FormEvent } from "react";

function ProductionOrderForm({ products, warehouses, suppliers, onClose, onSaved }: {
  products: { id: number; name: string }[];
  warehouses: Warehouse[];
  suppliers: { id: number; name: string }[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [productId, setProductId] = useState<number | "">("");
  const [qtyPlanned, setQtyPlanned] = useState("1");
  const [rawWh, setRawWh] = useState<number | "">("");
  const [outWh, setOutWh] = useState<number | "">("");
  const [subcontractor, setSubcontractor] = useState<number | "">("");
  const [productionLine, setProductionLine] = useState("");
  const [scheduled, setScheduled] = useState("");
  const [notes, setNotes] = useState("");
  const bom = useFetch(
    () => (productId === "" ? Promise.resolve([]) : api.get<Bom[]>(`/boms?product_id=${productId}&active_only=true`)),
    `po-form-bom-${productId}`
  );
  const activeBom = (bom.data ?? []).find((b) => b.is_active) ?? null;
  const { busy, error, run } = useAction();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (productId === "") return;
    void run(async () => {
      await api.post("/production-orders", {
        product_id: productId,
        qty_planned: Number(qtyPlanned) || 1,
        raw_warehouse_id: rawWh,
        output_warehouse_id: outWh,
        subcontractor_id: subcontractor === "" ? null : subcontractor,
        production_line: productionLine.trim() || null,
        scheduled_date: scheduled || null,
        notes: notes.trim() || null,
      });
      onSaved();
    });
  };

  return (
    <Modal title="أمر تصنيع جديد" onClose={onClose} wide>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <Alert kind="info">
          {productId === "" ? "اختر المنتج النهائي — ستُستخدم قائمة المواد المفعّلة الخاصة به" :
            activeBom ? `قائمة المواد المفعّلة: إصدار ${activeBom.version} — ناتج ${activeBom.output_qty} وحدة · ${activeBom.items.length} مكوّن` :
              "⚠️ لا توجد قائمة مواد مفعّلة لهذا المنتج — أنشئها أولًا من صفحة قوائم المواد"}
        </Alert>
        <div className="form-grid">
          <Field label="المنتج النهائي">
            <select value={String(productId)} onChange={(e) => { setProductId(e.target.value === "" ? "" : Number(e.target.value)); setQtyPlanned("1"); }} required>
              <option value="">— اختر المنتج —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </Field>
          <Field label="الكمية المخططة">
            <input type="number" min="1" step="1" value={qtyPlanned} onChange={(e) => setQtyPlanned(e.target.value)} required />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="مخزن الخامات" hint="يُصرف منه عند بدء التشغيل">
            <select value={String(rawWh)} onChange={(e) => setRawWh(e.target.value === "" ? "" : Number(e.target.value))} required>
              <option value="">— اختر —</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </Field>
          <Field label="مخزن المنتج التام" hint="تُضاف إليه الكميات المنتجة">
            <select value={String(outWh)} onChange={(e) => setOutWh(e.target.value === "" ? "" : Number(e.target.value))} required>
              <option value="">— اختر —</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </Field>
        </div>
        <div className="form-grid">
          <Field label="المورد الصناعي" hint="اختياري — للتصنيع الخارجي">
            <select value={String(subcontractor)} onChange={(e) => setSubcontractor(e.target.value === "" ? "" : Number(e.target.value))}>
              <option value="">— تصنيع داخلي —</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </Field>
          <Field label="خط الإنتاج" hint="اختياري">
            <input value={productionLine} onChange={(e) => setProductionLine(e.target.value)} maxLength={100} />
          </Field>
        </div>
        <Field label="تاريخ الجدولة" hint="اختياري">
          <input type="date" value={scheduled} onChange={(e) => setScheduled(e.target.value)} />
        </Field>
        <Field label="ملاحظات">
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy || (productId !== "" && !activeBom)}>
            {busy ? "جارٍ الحفظ…" : "حفظ الأمر (مسودة)"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            إلغاء
          </button>
        </div>
      </form>
    </Modal>
  );
}

const COST_TYPE_LABEL: Record<string, string> = { labor: "أجور تشغيل", overhead: "أعباء غير مباشرة", subcontract: "تكلفة تصنيع خارجي" };

function ProductionDetailsModal({ orderId, onClose, onChanged }: { orderId: number; onClose: () => void; onChanged: () => void }) {
  const order = useFetch(() => api.get<ProductionOrder>(`/production-orders/${orderId}`), `po-details-${orderId}`);
  const children = useFetch(() => api.get<ProductionOrder[]>(`/production-orders/${orderId}/children`), `po-children-${orderId}`);
  const o = order.data;
  const act = useAction();
  const [costType, setCostType] = useState<"labor" | "overhead" | "subcontract">("labor");
  const [costAmount, setCostAmount] = useState("");
  const [costDesc, setCostDesc] = useState("");

  const materialsTotal = (o?.consumptions ?? []).reduce((s, c) => s + Number(c.qty) * Number(c.unit_cost), 0);
  const costsTotal = Number(o?.costs_total ?? 0);
  const totalCost = materialsTotal + costsTotal;
  const editable = o ? o.status === "draft" || o.status === "in_progress" : false;

  const addCost = (e: FormEvent) => {
    e.preventDefault();
    if (!o) return;
    void act.run(async () => {
      await api.post(`/production-orders/${o.id}/costs`, {
        cost_type: costType,
        amount: costAmount,
        description: costDesc.trim() || null,
      });
      setCostAmount("");
      setCostDesc("");
      order.reload();
      onChanged();
    });
  };

  const delCost = (costId: number) => {
    void act.run(async () => {
      await api.del(`/production-orders/${o!.id}/costs/${costId}`);
      order.reload();
      onChanged();
    });
  };

  return (
    <Modal title={`تفاصيل أمر التصنيع ${o?.code ?? ""}`} onClose={onClose} wide>
      {order.loading && !o ? (
        <Loading />
      ) : o ? (
        <>
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
            المنتج: <b>{o.product_name}</b> · المخطط: <b>{num(o.qty_planned)}</b> · المنتج: <b>{num(o.qty_produced)}</b> · الحالة: <b>{PRODUCTION_STATUS_LABEL[o.status]}</b>
          </p>
          <h4 style={{ margin: "12px 0 6px" }}>الخامات المصروفة</h4>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>المكوّن</th><th>الوحدة</th><th className="num">الكمية</th><th className="num">تكلفة الوحدة</th><th className="num">الإجمالي</th></tr>
              </thead>
              <tbody>
                {o.consumptions.length > 0 ? o.consumptions.map((c) => (
                  <tr key={c.component_id}>
                    <td>{c.component_name ?? `#${c.component_id}`}</td>
                    <td>{c.component_unit ?? "—"}</td>
                    <td className="num">{num(c.qty)}</td>
                    <td className="num">{money(c.unit_cost)}</td>
                    <td className="num">{money(Number(c.qty) * Number(c.unit_cost))}</td>
                  </tr>
                )) : (
                  <tr><td colSpan={5}><Empty>لم يتم صرف خامات بعد — ابدأ التشغيل أولًا.</Empty></td></tr>
                )}
              </tbody>
            </table>
          </div>

          <h4 style={{ margin: "14px 0 6px" }}>الأجور والأعباء غير المباشرة</h4>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>النوع</th><th>الوصف</th><th className="num">المبلغ</th><th /></tr>
              </thead>
              <tbody>
                {o.costs.length > 0 ? o.costs.map((c) => (
                  <tr key={c.id}>
                    <td>{COST_TYPE_LABEL[c.cost_type] ?? c.cost_type}</td>
                    <td>{c.description || "—"}</td>
                    <td className="num">{money(c.amount)}</td>
                    <td className="actions">
                      {editable && (
                        <button className="btn btn-sm" style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => delCost(c.id)}>
                          حذف
                        </button>
                      )}
                    </td>
                  </tr>
                )) : (
                  <tr><td colSpan={4}><Empty>لا توجد أجور أو أعباء مسجلة.</Empty></td></tr>
                )}
              </tbody>
            </table>
          </div>
          {editable && (
            <form onSubmit={addCost} style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginTop: 8 }}>
              <label className="range-field">
                <span className="field-label">النوع</span>
                <select value={costType} onChange={(e) => setCostType(e.target.value as "labor" | "overhead" | "subcontract")}>
                  <option value="labor">أجور تشغيل</option>
                  <option value="overhead">أعباء غير مباشرة</option>
                  {o.subcontractor_id && <option value="subcontract">تكلفة تصنيع خارجي</option>}
                </select>
              </label>
              <label className="range-field">
                <span className="field-label">المبلغ</span>
                <input type="number" min="0.01" step="0.01" value={costAmount} onChange={(e) => setCostAmount(e.target.value)} required style={{ width: 130 }} />
              </label>
              <label className="range-field">
                <span className="field-label">الوصف</span>
                <input value={costDesc} onChange={(e) => setCostDesc(e.target.value)} maxLength={200} placeholder="اختياري" style={{ width: 180 }} />
              </label>
              <button className="btn btn-sm btn-primary" disabled={act.busy || !costAmount} style={{ marginBottom: 2 }}>
                {act.busy ? "…" : "+ إضافة"}
              </button>
            </form>
          )}

          {o.batches.length > 0 && (
            <>
              <h4 style={{ margin: "14px 0 6px" }}>دفعات الإنتاج وفحص الجودة</h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>رقم الدفعة</th><th className="num">الكمية</th><th className="num">التكلفة</th><th>الفحص</th><th>إجراءات</th></tr>
                  </thead>
                  <tbody>
                    {o.batches.map((b) => (
                      <tr key={b.id}>
                        <td dir="ltr">{b.batch_no}</td>
                        <td className="num">{num(b.qty)}</td>
                        <td className="num">{money(b.cost)}</td>
                        <td>
                          <span className={`badge ${b.qc_status === "passed" ? "badge-confirmed" : b.qc_status === "rejected" ? "badge-cancelled" : "badge-draft"}`}>
                            {b.qc_status === "passed" ? "معتمدة" : b.qc_status === "rejected" ? "مرفوضة" : "قيد الفحص"}
                          </span>
                        </td>
                        <td className="actions">
                          {b.qc_status === "pending" && editable && (
                            <>
                              <button className="btn btn-sm" onClick={() => void act.run(async () => {
                                await api.post(`/production-orders/${o.id}/batches/${b.id}/qc`, { result: "passed" });
                                order.reload();
                                onChanged();
                              })}>
                                ✔ اعتماد
                              </button>{" "}
                              <button className="btn btn-sm" style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => void act.run(async () => {
                                await api.post(`/production-orders/${o.id}/batches/${b.id}/qc`, { result: "rejected" });
                                order.reload();
                                onChanged();
                              })}>
                                ✖ رفض
                              </button>
                            </>
                          )}
                          {b.qc_status !== "pending" && <span className="muted">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {children.data && children.data.length > 0 && (
            <>
              <h4 style={{ margin: "14px 0 6px" }}>أوامر فرعية مرتبطة (تصنيع مرحلي)</h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>الرقم</th><th>المكوّن المنتج</th><th className="num">الكمية</th><th>الحالة</th></tr>
                  </thead>
                  <tbody>
                    {children.data.map((c) => (
                      <tr key={c.id}>
                        <td dir="ltr">{c.code}</td>
                        <td>{c.product_name ?? `#${c.product_id}`}</td>
                        <td className="num">{num(c.qty_planned)}</td>
                        <td>{PRODUCTION_STATUS_LABEL[c.status]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <div className="card card-pad" style={{ marginTop: 14, display: "flex", gap: 24, flexWrap: "wrap" }}>
            <span>الخامات: <b>{money(materialsTotal)}</b></span>
            <span>الأجور والأعباء: <b>{money(costsTotal)}</b></span>
            <span>إجمالي التكلفة: <b style={{ fontSize: 15 }}>{money(totalCost)}</b></span>
            <span>تكلفة الوحدة (من المخطط): <b>{o.qty_planned ? money(totalCost / o.qty_planned) : "—"}</b></span>
          </div>
        </>
      ) : (
        <Loading />
      )}
    </Modal>
  );
}


function ProductionLinesModal({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const lines = useFetch(() => api.get<ProductionLine[]>("/production-lines"), "lines-manage");
  const act = useAction();
  const [deletingLine, setDeletingLine] = useState<ProductionLine | null>(null);
  const [name, setName] = useState("");
  const [capacity, setCapacity] = useState("");
  const [hourly, setHourly] = useState("");
  const [editing, setEditing] = useState<ProductionLine | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void act.run(async () => {
      const body = {
        name: name.trim(),
        capacity_per_hour: capacity === "" ? null : Number(capacity),
        hourly_cost: hourly === "" ? null : hourly,
      };
      if (editing) await api.patch(`/production-lines/${editing.id}`, body);
      else await api.post("/production-lines", body);
      setName(""); setCapacity(""); setHourly(""); setEditing(null);
      lines.reload();
      onChanged();
    });
  };

  return (
    <Modal title="⚙️ خطوط الإنتاج" onClose={onClose} wide>
      <form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 10 }}>
        <label className="range-field">
          <span className="field-label">اسم الخط</span>
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={150} style={{ width: 180 }} />
        </label>
        <label className="range-field">
          <span className="field-label">السعة/ساعة</span>
          <input type="number" min="1" step="1" value={capacity} onChange={(e) => setCapacity(e.target.value)} style={{ width: 110 }} placeholder="اختياري" />
        </label>
        <label className="range-field">
          <span className="field-label">تكلفة الساعة</span>
          <input type="number" min="0" step="0.01" value={hourly} onChange={(e) => setHourly(e.target.value)} style={{ width: 110 }} placeholder="اختياري" />
        </label>
        <button className="btn btn-primary" disabled={act.busy || !name.trim()} style={{ marginBottom: 2 }}>
          {editing ? "حفظ التعديل" : "+ إضافة خط"}
        </button>
        {editing && <button type="button" className="btn" onClick={() => { setEditing(null); setName(""); setCapacity(""); setHourly(""); }}>إلغاء التعديل</button>}
      </form>
      <Alert>{act.error || lines.error}</Alert>
      <div className="table-wrap">
        {lines.loading && !lines.data ? (
          <Loading />
        ) : lines.data && lines.data.length > 0 ? (
          <table>
            <thead>
              <tr><th>اسم الخط</th><th className="num">السعة/ساعة</th><th className="num">تكلفة الساعة</th><th>الحالة</th><th>إجراءات</th></tr>
            </thead>
            <tbody>
              {lines.data.map((l) => (
                <tr key={l.id}>
                  <td>{l.name}</td>
                  <td className="num">{l.capacity_per_hour ?? "—"}</td>
                  <td className="num">{l.hourly_cost ? money(l.hourly_cost) : "—"}</td>
                  <td><ActiveBadge active={l.is_active} /></td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => { setEditing(l); setName(l.name); setCapacity(l.capacity_per_hour ? String(l.capacity_per_hour) : ""); setHourly(l.hourly_cost ?? ""); }}>
                      تعديل
                    </button>{" "}
                    <button className="btn btn-sm" style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => setDeletingLine(l)}>
                      حذف
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>لا توجد خطوط إنتاج — أضف أول خط.</Empty>
        )}
      </div>

      {deletingLine && (
        <Modal title={`حذف خط الإنتاج — ${deletingLine.name}`} onClose={() => setDeletingLine(null)}>
          <p style={{ margin: "0 0 6px" }}>
            هل أنت متأكد من حذف خط الإنتاج <strong>{deletingLine.name}</strong>؟ لا يمكن الرجوع بعد الحذف.
          </p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn"
              style={{ color: "#fff", background: "var(--danger)" }}
              disabled={act.busy}
              onClick={() => void act.run(async () => {
                await api.del(`/production-lines/${deletingLine.id}`);
                setDeletingLine(null);
                lines.reload();
              })}
            >
              {act.busy ? "جارٍ الحذف…" : "🗑️ نعم، حذف"}
            </button>
            <button type="button" className="btn" onClick={() => setDeletingLine(null)}>
              إلغاء
            </button>
          </div>
        </Modal>
      )}
    </Modal>
  );
}

export default function ProductionOrders() {
  const orders = useFetch(() => api.get<ProductionOrder[]>("/production-orders"), "po-list");
  const products = useFetch(() => api.get<{ id: number; name: string }[]>("/products?limit=1000"), "po-products");
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?limit=500"), "po-warehouses");
  const suppliers = useFetch(() => api.get<{ id: number; name: string }[]>("/suppliers?limit=500"), "po-suppliers");
  const [statusFilter, setStatusFilter] = useState<"" | ProductionOrderStatus>("");
  const [showForm, setShowForm] = useState(false);
  const [details, setDetails] = useState<number | null>(null);
  const [produceFor, setProduceFor] = useState<ProductionOrder | null>(null);
  const [produceQty, setProduceQty] = useState("");
  const [scrapFor, setScrapFor] = useState<ProductionOrder | null>(null);
  const [scrapQty, setScrapQty] = useState("");
  const [scrapNotes, setScrapNotes] = useState("");
  const [showLines, setShowLines] = useState(false);
  const [confirming, setConfirming] = useState<{ order: ProductionOrder; action: "issue" | "close" | "cancel" | "delete"; text: string } | null>(null);
  const act = useAction();
  const lines = useFetch(() => api.get<ProductionLine[]>("/production-lines"), "po-lines");

  const warehousesList: Warehouse[] = warehouses.data ?? [];
  const ordersList = (orders.data ?? []).filter((o) => statusFilter === "" || o.status === statusFilter);

  const refresh = () => orders.reload();

  const runAction = (order: ProductionOrder, action: "issue" | "close" | "cancel" | "delete") => {
    void act.run(async () => {
      if (action === "issue") await api.post(`/production-orders/${order.id}/issue`);
      if (action === "close") await api.post(`/production-orders/${order.id}/close`);
      if (action === "cancel") await api.post(`/production-orders/${order.id}/cancel`);
      if (action === "delete") await api.del(`/production-orders/${order.id}`);
      refresh();
    });
  };

  const doProduce = () => {
    if (!produceFor) return;
    void act.run(async () => {
      await api.post(`/production-orders/${produceFor.id}/produce`, { qty: Number(produceQty) });
      setProduceFor(null);
      setProduceQty("");
      refresh();
    });
  };

  const doScrap = (e: FormEvent) => {
    e.preventDefault();
    if (!scrapFor) return;
    void act.run(async () => {
      await api.post(`/production-orders/${scrapFor.id}/scrape`, {
        qty: Number(scrapQty),
        notes: scrapNotes.trim() || null,
      });
      setScrapFor(null);
      setScrapQty("");
      setScrapNotes("");
      refresh();
    });
  };

  const today = new Date().toISOString().slice(0, 10);
  const isLate = (o: ProductionOrder) => !!o.scheduled_date && o.scheduled_date < today && (o.status === "draft" || o.status === "in_progress");

  const badge = (status: ProductionOrderStatus) => (
    <span className={`badge ${status === "completed" ? "badge-confirmed" : status === "cancelled" ? "badge-cancelled" : status === "in_progress" ? "badge-draft" : ""}`}>
      {PRODUCTION_STATUS_LABEL[status]}
    </span>
  );

  return (
    <>
      <PageHeader title="أوامر التصنيع">
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          + أمر تصنيع جديد
        </button>
        <button className="btn" onClick={() => setShowLines(true)}>
          ⚙️ خطوط الإنتاج
        </button>
      </PageHeader>

      <div className="toolbar page-actions" style={{ marginBottom: 14 }}>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as "" | ProductionOrderStatus)}>
          <option value="">كل الحالات</option>
          {(Object.keys(PRODUCTION_STATUS_LABEL) as ProductionOrderStatus[]).map((s) => (
            <option key={s} value={s}>{PRODUCTION_STATUS_LABEL[s]}</option>
          ))}
        </select>
      </div>

      <Alert>{orders.error || act.error}</Alert>

      <div className="card table-wrap">
        {orders.loading && !orders.data ? (
          <Loading />
        ) : ordersList.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>الرقم</th>
                <th>المنتج النهائي</th>
                <th className="num">المخطط</th>
                <th className="num">المنتج</th>
                <th>المورد الصناعي</th>
                <th>خط الإنتاج</th>
                <th>مخزن الخامات</th>
                <th>مخزن الناتج</th>
                <th>تاريخ الجدولة</th>
                <th className="num">المتبقي</th>
                <th className="num">الهالك</th>
                <th>الحالة</th>
                <th>إجراءات</th>
              </tr>
            </thead>
            <tbody>
              {ordersList.map((o) => (
                <tr key={o.id} style={o.status === "cancelled" ? { opacity: 0.55 } : undefined}>
                  <td dir="ltr">{o.code}</td>
                  <td>{o.product_name ?? `#${o.product_id}`}</td>
                  <td className="num">{num(o.qty_planned)}</td>
                  <td className="num">{num(o.qty_produced)}</td>
                  <td>{o.subcontractor_name ?? "—"}</td>
                  <td>{o.production_line_name ?? "—"}</td>
                  <td>{o.raw_warehouse_name ?? "—"}</td>
                  <td>{o.output_warehouse_name ?? "—"}</td>
                  <td>
                    {o.scheduled_date ?? "—"}
                    {isLate(o) && <span className="badge badge-cancelled" style={{ marginInlineStart: 4 }}>متأخر</span>}
                  </td>
                  <td className="num">{o.status === "in_progress" ? num(o.qty_planned - o.qty_produced) : "—"}</td>
                  <td className="num">{o.qty_scrapped ? num(o.qty_scrapped) : "—"}</td>
                  <td>{badge(o.status)}</td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => setDetails(o.id)}>تفاصيل</button>{" "}
                    {o.status === "draft" && (
                      <>
                        <button className="btn btn-sm btn-primary" onClick={() => setConfirming({ order: o, action: "issue", text: `بدء تشغيل ${o.code}؟ سيتم صرف الخامات من «${o.raw_warehouse_name}» حسب قائمة المواد.` })}>
                          ▶ بدء التشغيل
                        </button>{" "}
                        <button className="btn btn-sm" style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => setConfirming({ order: o, action: "cancel", text: `إلغاء الأمر ${o.code}؟` })}>
                          إلغاء
                        </button>{" "}
                        <button className="btn btn-sm" style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => setConfirming({ order: o, action: "delete", text: `حذف الأمر ${o.code} نهائيًا؟` })}>
                          🗑️
                        </button>{" "}
                      </>
                    )}
                    {o.status === "in_progress" && (
                      <>
                        <button className="btn btn-sm btn-primary" onClick={() => { setProduceFor(o); setProduceQty(String(o.qty_planned - o.qty_produced)); }}>
                          + تسجيل إنتاج
                        </button>{" "}
                        <button className="btn btn-sm" onClick={() => { setScrapFor(o); setScrapQty("1"); }}>
                          🗑️ هالك
                        </button>{" "}
                        <button className="btn btn-sm" onClick={() => setConfirming({ order: o, action: "close", text: `إنهاء الأمر ${o.code}؟ الفروق المتبقية سترحّل لمصاريف متنوعة.` })}>
                          ✔ إنهاء
                        </button>{" "}
                      </>
                    )}
                    {o.status === "completed" && <span className="muted">مكتمل</span>}
                    {o.status === "cancelled" && <span className="muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>لا توجد أوامر تصنيع — اضغط «+ أمر تصنيع جديد» للبدء.</Empty>
        )}
      </div>

      {showForm && (
        <ProductionOrderForm
          products={products.data ?? []}
          warehouses={warehousesList}
          suppliers={suppliers.data ?? []}
          onClose={() => setShowForm(false)}
          onSaved={() => { setShowForm(false); refresh(); }}
        />
      )}

      {details && (
        <ProductionDetailsModal orderId={details} onClose={() => setDetails(null)} onChanged={() => orders.reload()} />
      )}

      {produceFor && (
        <Modal title={`تسجيل إنتاج — ${produceFor.code}`} onClose={() => { setProduceFor(null); setProduceQty(""); }}>
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); doProduce(); }}>
            <Alert>{act.error}</Alert>
            <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
              المنتج: <b>{produceFor.product_name}</b> · المخطط: <b>{num(produceFor.qty_planned)}</b> · المنتج حتى الآن: <b>{num(produceFor.qty_produced)}</b> · المتبقي: <b>{num(produceFor.qty_planned - produceFor.qty_produced)}</b>
            </p>
            <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
              رقم الدفعة المقترح تلقائيًا: <b dir="ltr">{produceFor.code}-B{produceFor.batches.length + 1}</b> — وتظهر في نافذة التفاصيل لفحص الجودة.
            </p>
            <Field label="كمية الدفعة المنتجة" hint={`تُضاف إلى «${produceFor.output_warehouse_name}»`}>
              <input type="number" min="1" max={produceFor.qty_planned - produceFor.qty_produced} step="1" value={produceQty} onChange={(e) => setProduceQty(e.target.value)} required autoFocus />
            </Field>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={act.busy}>{act.busy ? "جارٍ التسجيل…" : "تسجيل الإنتاج"}</button>
              <button type="button" className="btn" onClick={() => { setProduceFor(null); setProduceQty(""); }}>إلغاء</button>
            </div>
          </form>
        </Modal>
      )}

      {scrapFor && (
        <Modal title={`تسجيل هالك — ${scrapFor.code}`} onClose={() => { setScrapFor(null); setScrapQty(""); setScrapNotes(""); }}>
          <form onSubmit={doScrap}>
            <Alert>{act.error}</Alert>
            <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
              المتبقي للتشغيل: <b>{num(scrapFor.qty_planned - scrapFor.qty_produced - scrapFor.qty_scrapped)}</b> — الكمية الهالكة تُرحّل من WIP لمصروف هالك ولا تُنتج.
            </p>
            <Field label="كمية الهالك">
              <input type="number" min="1" max={scrapFor.qty_planned - scrapFor.qty_produced - scrapFor.qty_scrapped} step="1" value={scrapQty} onChange={(e) => setScrapQty(e.target.value)} required autoFocus />
            </Field>
            <Field label="ملاحظات" hint="سبب الهالك (اختياري)">
              <input value={scrapNotes} onChange={(e) => setScrapNotes(e.target.value)} maxLength={200} />
            </Field>
            <div className="form-actions">
              <button className="btn" style={{ color: "#fff", background: "var(--danger)" }} disabled={act.busy}>
                {act.busy ? "جارٍ التسجيل…" : "تسجيل الهالك"}
              </button>
              <button type="button" className="btn" onClick={() => { setScrapFor(null); setScrapQty(""); setScrapNotes(""); }}>إلغاء</button>
            </div>
          </form>
        </Modal>
      )}

      {showLines && (
        <ProductionLinesModal onClose={() => setShowLines(false)} onChanged={() => lines.reload()} />
      )}

      {confirming && (
        <Modal title="تأكيد الإجراء" onClose={() => setConfirming(null)}>
          <p style={{ margin: "0 0 6px" }}>{confirming.text}</p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn"
              style={confirming.action === "issue" ? { color: "#fff", background: "var(--primary, #2563eb)" } : { color: "#fff", background: "var(--danger)" }}
              disabled={act.busy}
              onClick={() => { const { order, action } = confirming; setConfirming(null); runAction(order, action); }}
            >
              {act.busy ? "…" : "تأكيد"}
            </button>
            <button type="button" className="btn" onClick={() => setConfirming(null)}>
              إلغاء
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
