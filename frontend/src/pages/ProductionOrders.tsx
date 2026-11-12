import { Fragment, useState } from "react";
import { api, getToken } from "../api";
import { useAuth } from "../auth";
import { money, num } from "../format";
import { useAction, useFetch } from "../hooks";
import { useI18n } from "../i18n";
import { PRODUCTION_STATUS_LABEL } from "../types";
import type { Bom, MaterialsAvailability, ProductionLine, ProductionOrder, ProductionOrderStatus, QcMeasurementsOut, QcTemplate, Warehouse } from "../types";
import { ActiveBadge, Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";
import type { FormEvent } from "react";

function ProductionOrderForm({ products, warehouses, suppliers, lines, onClose, onSaved }: {
  products: { id: number; name: string }[];
  warehouses: Warehouse[];
  suppliers: { id: number; name: string }[];
  lines: ProductionLine[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [productId, setProductId] = useState<number | "">("");
  const [qtyPlanned, setQtyPlanned] = useState("1");
  const [rawWh, setRawWh] = useState<number | "">("");
  const [outWh, setOutWh] = useState<number | "">("");
  const [subcontractor, setSubcontractor] = useState<number | "">("");
  const [productionLineId, setProductionLineId] = useState<number | "">("");
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
        production_line_id: productionLineId === "" ? null : productionLineId,
        scheduled_date: scheduled || null,
        notes: notes.trim() || null,
      });
      onSaved();
    });
  };

  return (
    <Modal title={t("أمر تصنيع جديد")} onClose={onClose} wide>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <Alert kind="info">
          {productId === "" ? t("اختر المنتج النهائي — ستُستخدم قائمة المواد المفعّلة الخاصة به") :
            activeBom ? `${t("قائمة المواد المفعّلة: إصدار ")}${activeBom.version}${t(" — ناتج ")}${activeBom.output_qty}${t(" وحدة · ")}${activeBom.items.length}${t(" مكوّن")}` :
              t("⚠️ لا توجد قائمة مواد مفعّلة لهذا المنتج — أنشئها أولًا من صفحة قوائم المواد")}
        </Alert>
        <div className="form-grid">
          <Field label={t("المنتج النهائي")}>
            <select value={String(productId)} onChange={(e) => { setProductId(e.target.value === "" ? "" : Number(e.target.value)); setQtyPlanned("1"); }} required>
              <option value="">{t("— اختر المنتج —")}</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </Field>
          <Field label={t("الكمية المخططة")}>
            <input type="number" min="1" step="1" value={qtyPlanned} onChange={(e) => setQtyPlanned(e.target.value)} required />
          </Field>
        </div>
        <div className="form-grid">
          <Field label={t("مخزن الخامات")} hint={t("يُصرف منه عند بدء التشغيل")}>
            <select value={String(rawWh)} onChange={(e) => setRawWh(e.target.value === "" ? "" : Number(e.target.value))} required>
              <option value="">{t("— اختر —")}</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </Field>
          <Field label={t("مخزن المنتج التام")} hint={t("تُضاف إليه الكميات المنتجة")}>
            <select value={String(outWh)} onChange={(e) => setOutWh(e.target.value === "" ? "" : Number(e.target.value))} required>
              <option value="">{t("— اختر —")}</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </Field>
        </div>
        <div className="form-grid">
          <Field label={t("المورد الصناعي")} hint={t("اختياري — للتصنيع الخارجي")}>
            <select value={String(subcontractor)} onChange={(e) => setSubcontractor(e.target.value === "" ? "" : Number(e.target.value))}>
              <option value="">{t("— تصنيع داخلي —")}</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </Field>
          <Field label={t("خط الإنتاج")} hint={t("اختياري — من الخطوط المعرّفة")}>
            <select value={String(productionLineId)} onChange={(e) => setProductionLineId(e.target.value === "" ? "" : Number(e.target.value))}>
              <option value="">{t("— بلا خط —")}</option>
              {lines.map((l) => (
                <option key={l.id} value={l.id}>{l.name}</option>
              ))}
            </select>
          </Field>
        </div>
        <Field label={t("تاريخ الجدولة")} hint={t("اختياري")}>
          <input type="date" value={scheduled} onChange={(e) => setScheduled(e.target.value)} />
        </Field>
        <Field label={t("ملاحظات")}>
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy || (productId !== "" && !activeBom)}>
            {busy ? t("جارٍ الحفظ…") : t("حفظ الأمر (مسودة)")}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            {t("إلغاء")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** جدول اللوطات المستهلكة لأمر تصنيع — التتبع العكسي من الدفعة إلى الاستلام. */
function LotTrace({ orderId }: { orderId: number }) {
  const { t } = useI18n();
  const lots = useFetch(() => api.get<{ component_name: string; lot_code: string; qty: number; source: string; reference: string | null; expiry_date: string | null }[]>(`/production-orders/${orderId}/lots`), `po-lots-${orderId}`);
  if (lots.loading && !lots.data) return <Loading />;
  const rows = lots.data ?? [];
  if (rows.length === 0) return <small className="hint">{t("لا تخصيص لوطات — الصرف من مخزون غير مرتبط بلوطات")}</small>;
  return (
    <div className="table-wrap" style={{ marginBottom: 4 }}>
      <table>
        <thead>
          <tr><th>{t("اللوط")}</th><th>{t("الصنف")}</th><th className="num">{t("الكمية")}</th><th>{t("المصدر")}</th><th>{t("المرجع")}</th><th>{t("انتهاء الصلاحية")}</th></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><b dir="ltr">{r.lot_code}</b></td>
              <td>{r.component_name}</td>
              <td className="num">{num(r.qty)}</td>
              <td>{r.source === "purchase" ? t("استلام شراء") : r.source === "opening" ? t("افتتاحي") : t("يدوي")}</td>
              <td>{r.reference ?? "—"}</td>
              <td>{r.expiry_date ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** نافذة قياسات الجودة للدفعة — تجمع معايير النماذج المطلوبة لمنتج الأمر وتحسب المطابقة. */
function BatchQcMeasure({ productId, batchId, batchNo, onClose }: { productId: number; batchId: number; batchNo: string; onClose: () => void }) {
  const { t } = useI18n();
  const req = useFetch(() => api.get<{ template_ids: number[] }>(`/qc/products/${productId}`), `qc-req-${productId}`);
  const templates = useFetch(() => api.get<QcTemplate[]>("/qc/templates"), "qc-templates");
  const saved = useFetch(() => api.get<QcMeasurementsOut>(`/qc/batches/${batchId}/results`), `qc-res-${batchId}`);
  const { busy, error, run } = useAction();
  const [values, setValues] = useState<Record<number, { value_num: string; value_text: string }>>({});
  const [savedVerdict, setSavedVerdict] = useState<QcMeasurementsOut | null>(null);

  const requiredIds = req.data?.template_ids ?? [];
  const params = (templates.data ?? [])
    .filter((tp) => requiredIds.includes(tp.id) && tp.is_active)
    .flatMap((tp) => tp.parameters);

  const save = () => {
    const results = params
      .filter((p) => {
        const v = values[p.id];
        return v && (v.value_num !== "" || v.value_text.trim() !== "");
      })
      .map((p) => {
        const v = values[p.id];
        return { parameter_id: p.id, value_num: p.param_type === "number" && v.value_num !== "" ? Number(v.value_num) : null, value_text: p.param_type === "bool" ? v.value_text : v.value_text || null };
      });
    if (results.length === 0) return;
    void run(async () => {
      const out = await api.post<QcMeasurementsOut>(`/qc/batches/${batchId}/results`, { results });
      setSavedVerdict(out);
    });
  };

  return (
    <Modal title={`🧪 ${t("قياسات الجودة")} ${batchNo}`} onClose={onClose} wide>
      {error && <Alert kind="error">{error}</Alert>}
      {savedVerdict && (
        <Alert kind={savedVerdict.overall_pass === false ? "error" : "info"}>
          {savedVerdict.overall_pass === true ? "✅ " + t("جميع المعايير مطابقة") : savedVerdict.overall_pass === false ? "⛔ " + t("توجد معايير غير مطابقة — لا تعتمد الدفعة") : t("قياسات جزئية")}
        </Alert>
      )}
      {req.loading || templates.loading ? <Loading /> : params.length === 0 ? (
        <Empty>{t("لا نماذج فحص مطلوبة لهذا المنتج — اربط نموذجًا من صفحة الجودة")}</Empty>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>{t("المعيار")}</th><th>{t("النطاق المطلوب")}</th><th>{t("القراءة")}</th><th>{t("الحكم")}</th></tr>
              </thead>
              <tbody>
                {params.map((p) => {
                  const existing = (saved.data?.results ?? []).find((r) => r.parameter_id === p.id);
                  const v = values[p.id] ?? { value_num: existing?.value_num != null ? String(existing.value_num) : "", value_text: existing?.value_text ?? "" };
                  const pass = savedVerdict?.results.find((r) => r.parameter_id === p.id)?.pass_fail ?? existing?.pass_fail ?? null;
                  return (
                    <tr key={p.id}>
                      <td>{p.name}{p.unit ? <small className="muted"> ({p.unit})</small> : null}</td>
                      <td>{p.param_type === "number" ? <small className="muted" dir="ltr">{p.min_value ?? "—"} : {p.max_value ?? "—"}</small> : <small className="muted">{t("مطابق/غير مطابق")}</small>}</td>
                      <td>
                        {p.param_type === "number" ? (
                          <input type="number" step="0.001" dir="ltr" style={{ width: 110 }} value={v.value_num} onChange={(e) => setValues((s) => ({ ...s, [p.id]: { ...v, value_num: e.target.value } }))} />
                        ) : (
                          <select value={v.value_text} onChange={(e) => setValues((s) => ({ ...s, [p.id]: { ...v, value_text: e.target.value } }))}>
                            <option value="">—</option>
                            <option value="مطابق">{t("مطابق")}</option>
                            <option value="غير مطابق">{t("غير مطابق")}</option>
                          </select>
                        )}
                      </td>
                      <td>
                        {pass == null ? <span className="badge badge-muted">—</span> : pass ? <span className="badge badge-confirmed">{t("مطابق")}</span> : <span className="badge badge-cancelled">{t("غير مطابق")}</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="form-actions">
            <button type="button" className="btn btn-primary" disabled={busy} onClick={save}>{t("حفظ القياسات")}</button>
            <button type="button" className="btn" onClick={onClose}>{t("إغلاق")}</button>
          </div>
        </>
      )}
    </Modal>
  );
}

function ProductionDetailsModal({ orderId, onClose, onChanged }: { orderId: number; onClose: () => void; onChanged: () => void }) {
  const { t } = useI18n();
  const order = useFetch(() => api.get<ProductionOrder>(`/production-orders/${orderId}`), `po-details-${orderId}`);
  const [qcMeasure, setQcMeasure] = useState<{ batchId: number; batchNo: string } | null>(null);
  const children = useFetch(() => api.get<ProductionOrder[]>(`/production-orders/${orderId}/children`), `po-children-${orderId}`);
  const o = order.data;
  const act = useAction();
  const [costType, setCostType] = useState<"labor" | "overhead" | "subcontract">("labor");
  const [costAmount, setCostAmount] = useState("");
  const [costDesc, setCostDesc] = useState("");
  const [rejectingBatch, setRejectingBatch] = useState<{ id: number; batch_no: string } | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [deletingCost, setDeletingCost] = useState<{ id: number; label: string } | null>(null);
  const COST_TYPE_LABEL: Record<string, string> = { labor: t("أجور تشغيل"), overhead: t("أعباء غير مباشرة"), subcontract: t("تكلفة تصنيع خارجي") };

  const doReject = () => {
    if (!o || !rejectingBatch) return;
    void act.run(async () => {
      await api.post(`/production-orders/${o.id}/batches/${rejectingBatch.id}/qc`, {
        result: "rejected",
        notes: rejectReason.trim() || null,
      });
      setRejectingBatch(null);
      setRejectReason("");
      order.reload();
      onChanged();
    });
  };

  const doDeleteCost = () => {
    if (!o || !deletingCost) return;
    void act.run(async () => {
      await api.del(`/production-orders/${o.id}/costs/${deletingCost.id}`);
      setDeletingCost(null);
      order.reload();
      onChanged();
    });
  };

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

  return (
    <Modal title={`${t("تفاصيل أمر التصنيع ")}${o?.code ?? ""}`} onClose={onClose} wide>
      {order.loading && !o ? (
        <Loading />
      ) : o ? (
        <>
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
            {t("المنتج: ")}<b>{o.product_name}</b>{t(" · المخطط: ")}<b>{num(o.qty_planned)}</b>{t(" · المنتج: ")}<b>{num(o.qty_produced)}</b>{t(" · الحالة: ")}<b>{PRODUCTION_STATUS_LABEL[o.status]}</b>
          </p>
          <h4 style={{ margin: "12px 0 6px" }}>📦 {t("اللوطات المستهلكة (التتبع العكسي)")}</h4>
          <LotTrace orderId={orderId} />
          <h4 style={{ margin: "12px 0 6px" }}>{t("الخامات المصروفة")}</h4>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>{t("المكوّن")}</th><th>{t("الوحدة")}</th><th className="num">{t("الكمية")}</th><th className="num">{t("تكلفة الوحدة")}</th><th className="num">{t("الإجمالي")}</th></tr>
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
                  <tr><td colSpan={5}><Empty>{t("لم يتم صرف خامات بعد — ابدأ التشغيل أولًا.")}</Empty></td></tr>
                )}
              </tbody>
            </table>
          </div>

          <h4 style={{ margin: "14px 0 6px" }}>{t("الأجور والأعباء غير المباشرة")}</h4>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>{t("النوع")}</th><th>{t("الوصف")}</th><th className="num">{t("المبلغ")}</th><th /></tr>
              </thead>
              <tbody>
                {o.costs.length > 0 ? o.costs.map((c) => (
                  <tr key={c.id}>
                    <td>{COST_TYPE_LABEL[c.cost_type] ?? c.cost_type}</td>
                    <td>{c.description || "—"}</td>
                    <td className="num">{money(c.amount)}</td>
                    <td className="actions">
                      {editable && (
                        <button className="btn-delete" onClick={() => setDeletingCost({ id: c.id, label: `${COST_TYPE_LABEL[c.cost_type] ?? c.cost_type} — ${money(c.amount)}` })}>
                          {t("حذف")}
                        </button>
                      )}
                    </td>
                  </tr>
                )) : (
                  <tr><td colSpan={4}><Empty>{t("لا توجد أجور أو أعباء مسجلة.")}</Empty></td></tr>
                )}
              </tbody>
            </table>
          </div>
          {editable && (
            <form onSubmit={addCost} style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginTop: 8 }}>
              <label className="range-field">
                <span className="field-label">{t("النوع")}</span>
                <select value={costType} onChange={(e) => setCostType(e.target.value as "labor" | "overhead" | "subcontract")}>
                  <option value="labor">{t("أجور تشغيل")}</option>
                  <option value="overhead">{t("أعباء غير مباشرة")}</option>
                  {o.subcontractor_id && <option value="subcontract">{t("تكلفة تصنيع خارجي")}</option>}
                </select>
              </label>
              <label className="range-field">
                <span className="field-label">{t("المبلغ")}</span>
                <input type="number" min="0.01" step="0.01" value={costAmount} onChange={(e) => setCostAmount(e.target.value)} required style={{ width: 130 }} />
              </label>
              <label className="range-field">
                <span className="field-label">{t("الوصف")}</span>
                <input value={costDesc} onChange={(e) => setCostDesc(e.target.value)} maxLength={200} placeholder={t("اختياري")} style={{ width: 180 }} />
              </label>
              <button className="btn btn-sm btn-primary" disabled={act.busy || !costAmount} style={{ marginBottom: 2 }}>
                {act.busy ? t("…") : t("+ إضافة")}
              </button>
            </form>
          )}

          {o.batches.length > 0 && (
            <>
              <h4 style={{ margin: "14px 0 6px" }}>{t("دفعات الإنتاج وفحص الجودة")}</h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>{t("رقم الدفعة")}</th><th className="num">{t("الكمية")}</th><th className="num">{t("التكلفة")}</th><th>{t("الفحص")}</th><th>{t("إجراءات")}</th></tr>
                  </thead>
                  <tbody>
                    {o.batches.map((b) => (
                      <tr key={b.id}>
                        <td dir="ltr">{b.batch_no}</td>
                        <td className="num">{num(b.qty)}</td>
                        <td className="num">{money(b.cost)}</td>
                        <td>
                          <span className={`badge ${b.qc_status === "passed" ? "badge-confirmed" : b.qc_status === "rejected" ? "badge-cancelled" : "badge-draft"}`}>
                            {b.qc_status === "passed" ? t("معتمدة") : b.qc_status === "rejected" ? t("مرفوضة") : t("قيد الفحص")}
                          </span>
                          {b.qc_status === "rejected" && b.notes && <div className="muted" style={{ fontSize: 11 }}>{b.notes}</div>}
                        </td>
                        <td className="actions">
                          {b.qc_status === "pending" && editable && (
                            <>
                              <button className="btn btn-sm" disabled={act.busy} onClick={() => void act.run(async () => {
                                await api.post(`/production-orders/${o.id}/batches/${b.id}/qc`, { result: "passed" });
                                order.reload();
                                onChanged();
                              })}>
                                {t("✔ اعتماد")}
                              </button>{" "}
                              <button className="btn btn-sm" style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => { setRejectingBatch({ id: b.id, batch_no: b.batch_no }); setRejectReason(""); }}>
                                {t("✖ رفض")}
                              </button>
                              <button className="btn-edit" onClick={() => setQcMeasure({ batchId: b.id, batchNo: b.batch_no })}>
                                {t("🧪 قياسات")}
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

          {qcMeasure && o && (
            <BatchQcMeasure productId={o.product_id} batchId={qcMeasure.batchId} batchNo={qcMeasure.batchNo} onClose={() => setQcMeasure(null)} />
          )}

          {children.data && children.data.length > 0 && (
            <>
              <h4 style={{ margin: "14px 0 6px" }}>{t("أوامر فرعية مرتبطة (تصنيع مرحلي)")}</h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>{t("الرقم")}</th><th>{t("المكوّن المنتج")}</th><th className="num">{t("الكمية")}</th><th>{t("الحالة")}</th></tr>
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
            <span>{t("الخامات: ")}<b>{money(materialsTotal)}</b></span>
            <span>{t("الأجور والأعباء: ")}<b>{money(costsTotal)}</b></span>
            <span>{t("إجمالي التكلفة: ")}<b style={{ fontSize: 15 }}>{money(totalCost)}</b></span>
            <span>{t("تكلفة الوحدة (من المخطط): ")}<b>{o.qty_planned ? money(totalCost / o.qty_planned) : "—"}</b></span>
            {o.std_unit_cost && <span>{t("القياسية: ")}<b>{money(o.std_unit_cost)}</b></span>}
          </div>
        </>
      ) : (
        <Loading />
      )}

      {rejectingBatch && (
        <Modal title={`${t("رفض الدفعة — ")}${rejectingBatch.batch_no}`} onClose={() => { setRejectingBatch(null); setRejectReason(""); }}>
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); doReject(); }}>
            <Alert>{act.error}</Alert>
            <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
              {t("سيتم سحب الدفعة من مخزن الناتج وترحيل تكلفتها لمصروف الهالك.")}
            </p>
            <Field label={t("سبب الرفض")} hint={t("مطلوب — يظهر بجانب الدفعة")}>
              <textarea rows={2} value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} required maxLength={200} autoFocus />
            </Field>
            <div className="form-actions">
              <button className="btn-delete" disabled={act.busy || !rejectReason.trim()}>
                {act.busy ? t("…") : t("تأكيد الرفض")}
              </button>
              <button type="button" className="btn" onClick={() => { setRejectingBatch(null); setRejectReason(""); }}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {deletingCost && (
        <Modal title={t("حذف تكلفة")} onClose={() => setDeletingCost(null)}>
          <p style={{ margin: "0 0 6px" }}>
            {t("حذف ")}<strong>{deletingCost.label}</strong>{t("؟ سيُعكس قيدها من WIP تلقائيًا.")}
          </p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button className="btn-delete" disabled={act.busy} onClick={doDeleteCost}>
              {act.busy ? t("…") : t("نعم، حذف")}
            </button>
            <button type="button" className="btn" onClick={() => setDeletingCost(null)}>{t("إلغاء")}</button>
          </div>
        </Modal>
      )}
    </Modal>
  );
}


function ProductionLinesModal({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const { t } = useI18n();
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
    <Modal title={t("⚙️ خطوط الإنتاج")} onClose={onClose} wide>
      <form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 10 }}>
        <label className="range-field">
          <span className="field-label">{t("اسم الخط")}</span>
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={150} style={{ width: 180 }} />
        </label>
        <label className="range-field">
          <span className="field-label">{t("السعة/ساعة")}</span>
          <input type="number" min="1" step="1" value={capacity} onChange={(e) => setCapacity(e.target.value)} style={{ width: 110 }} placeholder={t("اختياري")} />
        </label>
        <label className="range-field">
          <span className="field-label">{t("تكلفة الساعة")}</span>
          <input type="number" min="0" step="0.01" value={hourly} onChange={(e) => setHourly(e.target.value)} style={{ width: 110 }} placeholder={t("اختياري")} />
        </label>
        <button className="btn btn-primary" disabled={act.busy || !name.trim()} style={{ marginBottom: 2 }}>
          {editing ? t("حفظ التعديل") : t("+ إضافة خط")}
        </button>
        {editing && <button type="button" className="btn" onClick={() => { setEditing(null); setName(""); setCapacity(""); setHourly(""); }}>{t("إلغاء التعديل")}</button>}
      </form>
      <Alert>{act.error || lines.error}</Alert>
      <div className="table-wrap">
        {lines.loading && !lines.data ? (
          <Loading />
        ) : lines.data && lines.data.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("اسم الخط")}</th><th className="num">{t("السعة/ساعة")}</th><th className="num">{t("تكلفة الساعة")}</th><th>{t("الحالة")}</th><th>{t("إجراءات")}</th></tr>
            </thead>
            <tbody>
              {lines.data.map((l) => (
                <tr key={l.id}>
                  <td>{l.name}</td>
                  <td className="num">{l.capacity_per_hour ?? "—"}</td>
                  <td className="num">{l.hourly_cost ? money(l.hourly_cost) : "—"}</td>
                  <td><ActiveBadge active={l.is_active} /></td>
                  <td className="actions">
                    <button className="btn-edit" onClick={() => { setEditing(l); setName(l.name); setCapacity(l.capacity_per_hour ? String(l.capacity_per_hour) : ""); setHourly(l.hourly_cost ?? ""); }}>{t("تعديل")}</button>{" "}
                    <button className="btn-delete" onClick={() => setDeletingLine(l)}>
                      {t("حذف")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا توجد خطوط إنتاج — أضف أول خط.")}</Empty>
        )}
      </div>

      {deletingLine && (
        <Modal title={`${t("حذف خط الإنتاج — ")}${deletingLine.name}`} onClose={() => setDeletingLine(null)}>
          <p style={{ margin: "0 0 6px" }}>
            {t("هل أنت متأكد من حذف خط الإنتاج ")}<strong>{deletingLine.name}</strong>{t("؟ لا يمكن الرجوع بعد الحذف.")}
          </p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn-delete"
              disabled={act.busy}
              onClick={() => void act.run(async () => {
                await api.del(`/production-lines/${deletingLine.id}`);
                setDeletingLine(null);
                lines.reload();
              })}
            >
              {act.busy ? t("جارٍ الحذف…") : t("نعم، حذف")}
            </button>
            <button type="button" className="btn" onClick={() => setDeletingLine(null)}>
              {t("إلغاء")}
            </button>
          </div>
        </Modal>
      )}
    </Modal>
  );
}

/** لوحة الجدولة الأسبوعية — سحب وإفلات أوامر التصنيع على أيام الأسبوع وخطوط الإنتاج. */
function ScheduleBoard() {
  const { t } = useI18n();
  const { can } = useAuth();
  const canSchedule = can("manufacturing.order.schedule");
  const weekStartOf = (d: Date) => { const x = new Date(d); x.setHours(0, 0, 0, 0); x.setDate(x.getDate() - ((x.getDay() - 6 + 7) % 7)); return x; };
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const [weekStart, setWeekStart] = useState(() => weekStartOf(new Date()));
  const days = Array.from({ length: 7 }, (_, i) => { const d = new Date(weekStart); d.setDate(d.getDate() + i); return d; });
  const from = iso(days[0]);
  const to = iso(days[6]);
  const todayIso = iso(new Date());
  const dayNames = [t("السبت"), t("الأحد"), t("الاثنين"), t("الثلاثاء"), t("الأربعاء"), t("الخميس"), t("الجمعة")];

  const week = useFetch(() => api.get<ProductionOrder[]>(`/production-orders?scheduled_from=${from}&scheduled_to=${to}&limit=1000`), `sched-week-${from}`);
  const pool = useFetch(() => api.get<ProductionOrder[]>("/production-orders?scheduled=false&limit=300"), "sched-pool");
  const lines = useFetch(() => api.get<ProductionLine[]>("/production-lines"), "sched-lines");

  const { busy, error, run } = useAction();
  const [dragId, setDragId] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [editing, setEditing] = useState<ProductionOrder | null>(null);
  const [editDate, setEditDate] = useState("");
  const [editLine, setEditLine] = useState("");

  const schedulable = (o: ProductionOrder) => o.status === "draft" || o.status === "in_progress";

  const schedule = (orderId: number, date: string | null, lineId: number | null) =>
    run(async () => {
      await api.put(`/production-orders/${orderId}/schedule`, { scheduled_date: date, production_line_id: lineId });
      week.reload();
      pool.reload();
      setEditing(null);
    });

  const chip = (o: ProductionOrder) => (
    <div
      key={o.id}
      className={`sched-chip sched-${o.status}${dragId === o.id ? " dragging" : ""}`}
      draggable={canSchedule && schedulable(o)}
      onDragStart={() => setDragId(o.id)}
      onDragEnd={() => { setDragId(null); setDragOver(null); }}
      onClick={() => { setEditing(o); setEditDate(o.scheduled_date ?? ""); setEditLine(o.production_line_id ? String(o.production_line_id) : ""); }}
      title={`${o.code} · ${PRODUCTION_STATUS_LABEL[o.status]}${o.production_line_name ? ` · ${o.production_line_name}` : ""}`}
    >
      <b dir="ltr">{o.code}</b>
      <span>{o.product_name ?? `#${o.product_id}`}</span>
      <span className="sched-qty">{num(o.qty_planned)}</span>
    </div>
  );

  const linesList = lines.data ?? [];
  const poolList = (pool.data ?? []).filter(schedulable);
  const rows: { label: string; lineId: number | null }[] = [
    { label: t("بدون خط"), lineId: null },
    ...linesList.map((l) => ({ label: l.name, lineId: l.id })),
  ];

  return (
    <div className="sched-board">
      {error && <Alert kind="error">{error}</Alert>}
      <div className="sched-controls">
        <button type="button" className="btn btn-sm" onClick={() => { const d = new Date(weekStart); d.setDate(d.getDate() - 7); setWeekStart(d); }}>‹</button>
        <b dir="ltr">{from} — {to}</b>
        <button type="button" className="btn btn-sm" onClick={() => setWeekStart(weekStartOf(new Date()))}>{t("هذا الأسبوع")}</button>
        <button type="button" className="btn btn-sm" onClick={() => { const d = new Date(weekStart); d.setDate(d.getDate() + 7); setWeekStart(d); }}>›</button>
        {pool.loading && !pool.data ? <Loading /> : (
          <span className="sched-pool">
            <b>{t("بانتظار الجدولة")}</b>
            {poolList.length ? poolList.map(chip) : <small>{t("لا أوامر بانتظار الجدولة ✓")}</small>}
          </span>
        )}
        {!canSchedule && <small className="hint">{t("عرض فقط — لا تملك صلاحية الجدولة")}</small>}
      </div>

      <div className="sched-scroll">
        <div className="sched-grid" style={{ gridTemplateColumns: `130px repeat(7, minmax(128px, 1fr))` }}>
          <div className="sched-corner">{t("خط \\ اليوم")}</div>
          {days.map((d, i) => (
            <div key={i} className={`sched-day-head${iso(d) === todayIso ? " today" : ""}`}>
              {dayNames[i]} <small dir="ltr">{iso(d).slice(5)}</small>
            </div>
          ))}
          {rows.map((row) => (
            <Fragment key={row.label + String(row.lineId)}>
              <div className="sched-line-label">{row.label}</div>
              {days.map((d) => {
                const cellDate = iso(d);
                const cellId = `${row.lineId ?? "x"}-${cellDate}`;
                const cellOrders = (week.data ?? []).filter((o) => o.scheduled_date === cellDate && (o.production_line_id ?? null) === row.lineId);
                // مؤشر الحمل: دقائق الأوامر المقدرة ÷ سعة الخط باليوم (شيفت 8 ساعات)
                const minutes = cellOrders.reduce((s, o) => s + Number(o.estimated_minutes ?? 0), 0);
                const lineCap = linesList.find((l) => l.id === row.lineId)?.capacity_per_hour ?? null;
                const capMin = lineCap ? Number(lineCap) * 60 * 8 : 0;
                const loadPct = capMin > 0 ? Math.round((minutes / capMin) * 100) : null;
                return (
                  <div
                    key={cellId}
                    className={`sched-cell${dragOver === cellId ? " drag-over" : ""}`}
                    onDragOver={(e) => { if (dragId != null) { e.preventDefault(); setDragOver(cellId); } }}
                    onDragLeave={() => setDragOver((s) => (s === cellId ? null : s))}
                    onDrop={(e) => { e.preventDefault(); setDragOver(null); const id = dragId; setDragId(null); if (id != null) void schedule(id, cellDate, row.lineId); }}
                  >
                    {cellOrders.length > 0 && (
                      <div className={`sched-load${loadPct == null ? "" : loadPct > 110 ? " over" : loadPct > 80 ? " warn" : " ok"}`}>
                        {loadPct != null ? `⚡ ${loadPct}%` : `⏱ ${Math.round(minutes)} د`}
                      </div>
                    )}
                    {cellOrders.map(chip)}
                  </div>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>

      {editing && (
        <Modal title={`${t("جدولة")} ${editing.code}`} onClose={() => setEditing(null)}>
          <form onSubmit={(e) => { e.preventDefault(); void schedule(editing.id, editDate || null, editLine ? Number(editLine) : null); }}>
            {error && <Alert kind="error">{error}</Alert>}
            <Field label={t("تاريخ التشغيل")}>
              <input type="date" dir="ltr" value={editDate} onChange={(e) => setEditDate(e.target.value)} />
            </Field>
            <Field label={t("خط الإنتاج")}>
              <select value={editLine} onChange={(e) => setEditLine(e.target.value)}>
                <option value="">{t("بدون خط")}</option>
                {linesList.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </Field>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={busy}>{t("حفظ")}</button>
              {editing.scheduled_date && (
                <button type="button" className="btn-delete" disabled={busy} onClick={() => void schedule(editing.id, null, null)}>{t("إزالة الجدولة")}</button>
              )}
              <button type="button" className="btn" onClick={() => setEditing(null)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

/** أرضية التشغيل الرقمية — شاشة لمس لكل خط: بدء/إنتاج/هالك + مسح باركود الأوامر. */
function ShopFloor() {
  const { t } = useI18n();
  const today = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; })();
  const scheduledToday = useFetch(() => api.get<ProductionOrder[]>(`/production-orders?scheduled_from=${today}&scheduled_to=${today}&limit=300`), "floor-today");
  const running = useFetch(() => api.get<ProductionOrder[]>("/production-orders?status=in_progress&limit=300"), "floor-running");
  const lines = useFetch(() => api.get<ProductionLine[]>("/production-lines"), "floor-lines");
  const { busy, error, run } = useAction();
  const [scan, setScan] = useState("");
  const [highlight, setHighlight] = useState<number | null>(null);
  const [produceFor, setProduceFor] = useState<ProductionOrder | null>(null);
  const [produceQty, setProduceQty] = useState("");
  const [scrapFor, setScrapFor] = useState<ProductionOrder | null>(null);
  const [scrapQty, setScrapQty] = useState("");
  const [scrapNotes, setScrapNotes] = useState("");

  const scanOrder = () => {
    const term = scan.trim().toLowerCase();
    if (!term) return;
    const all = [...(running.data ?? []), ...(scheduledToday.data ?? [])];
    const found = all.find((o) => o.code.toLowerCase() === term) ?? all.find((o) => o.code.toLowerCase().includes(term));
    if (!found) { setHighlight(null); return; }
    setHighlight(found.id);
    setScan("");
    window.setTimeout(() => {
      document.getElementById(`floor-${found.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      window.setTimeout(() => setHighlight(null), 4000);
    }, 60);
  };

  const remaining = (o: ProductionOrder) => Math.max(0, Number(o.qty_planned) - Number(o.qty_produced) - Number(o.qty_scrapped));

  const startOrder = (o: ProductionOrder) => run(async () => {
    await api.post(`/production-orders/${o.id}/issue`);
    scheduledToday.reload();
    running.reload();
  });
  const doProduce = (e: FormEvent) => {
    e.preventDefault();
    if (!produceFor) return;
    run(async () => {
      await api.post(`/production-orders/${produceFor.id}/produce`, { qty: Number(produceQty) });
      setProduceFor(null);
      setProduceQty("");
      scheduledToday.reload();
      running.reload();
    });
  };
  const doScrap = (e: FormEvent) => {
    e.preventDefault();
    if (!scrapFor) return;
    run(async () => {
      await api.post(`/production-orders/${scrapFor.id}/scrape`, { qty: Number(scrapQty), notes: scrapNotes || null });
      setScrapFor(null);
      setScrapQty("");
      setScrapNotes("");
      scheduledToday.reload();
      running.reload();
    });
  };

  const card = (o: ProductionOrder) => {
    const pct = Number(o.qty_planned) > 0 ? Math.round((Number(o.qty_produced) / Number(o.qty_planned)) * 100) : 0;
    return (
      <div key={o.id} id={`floor-${o.id}`} className={`floor-card${highlight === o.id ? " highlight" : ""}`}>
        <div className="floor-card-head">
          <b dir="ltr">{o.code}</b>
          <span>{o.product_name ?? `#${o.product_id}`}</span>
          <span className={`badge ${o.status === "in_progress" ? "badge-confirmed" : "badge-muted"}`}>{PRODUCTION_STATUS_LABEL[o.status]}</span>
        </div>
        <div className="floor-progress">
          <div className="floor-progress-bar"><span style={{ width: `${pct}%` }} /></div>
          <small>{t("المنتج ")}{num(o.qty_produced)}{t(" من ")}{num(o.qty_planned)}{t(" · المتبقي ")}{num(remaining(o))}</small>
        </div>
        <div className="floor-actions">
          {o.status === "draft" && (
            <button type="button" className="floor-btn floor-start" disabled={busy} onClick={() => void startOrder(o)}>▶️ {t("بدء التشغيل")}</button>
          )}
          {o.status === "in_progress" && (
            <>
              <button type="button" className="floor-btn floor-produce" disabled={busy} onClick={() => { setProduceFor(o); setProduceQty(String(remaining(o))); }}>➕ {t("إنتاج")}</button>
              <button type="button" className="floor-btn floor-scrap" disabled={busy} onClick={() => { setScrapFor(o); setScrapQty(""); setScrapNotes(""); }}>⚠️ {t("هالك")}</button>
              <button type="button" className="floor-btn floor-close" disabled={busy} onClick={() => void run(async () => { await api.post(`/production-orders/${o.id}/close`); scheduledToday.reload(); running.reload(); })}>✅ {t("إنهاء")}</button>
            </>
          )}
        </div>
      </div>
    );
  };

  const rows: { label: string; lineId: number | null }[] = [
    { label: t("بدون خط"), lineId: null },
    ...(lines.data ?? []).map((l) => ({ label: l.name, lineId: l.id })),
  ];
  const inProgress = running.data ?? [];
  const todays = (scheduledToday.data ?? []).filter((o) => o.status === "draft");

  return (
    <div className="floor">
      {error && <Alert kind="error">{error}</Alert>}
      <div className="floor-scan">
        <input
          dir="ltr"
          placeholder={t("📡 امسح باركود الأمر أو اكتب رقمه ثم Enter")}
          value={scan}
          onChange={(e) => setScan(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); scanOrder(); } }}
        />
      </div>
      {running.loading && !running.data ? <Loading /> : (
        rows.map((row) => {
          const rowRunning = inProgress.filter((o) => (o.production_line_id ?? null) === row.lineId);
          const rowToday = todays.filter((o) => (o.production_line_id ?? null) === row.lineId);
          if (!rowRunning.length && !rowToday.length) return null;
          return (
            <div key={row.label + String(row.lineId)} className="floor-line">
              <h3 className="floor-line-title">🏭 {row.label}</h3>
              {rowRunning.length > 0 && <div className="floor-grid">{rowRunning.map(card)}</div>}
              {rowToday.length > 0 && (
                <>
                  <small className="hint">{t("مجدولة اليوم — بانتظار البدء")}</small>
                  <div className="floor-grid">{rowToday.map(card)}</div>
                </>
              )}
            </div>
          );
        })
      )}
      {(running.data ?? []).length === 0 && (scheduledToday.data ?? []).filter((o) => o.status === "draft").length === 0 && (
        <Empty>{t("لا أوامر على الأرضية — جدول أوامر من تبويب «📅 الجدولة»")}</Empty>
      )}

      {produceFor && (
        <Modal title={`${t("تسجيل إنتاج")} ${produceFor.code}`} onClose={() => setProduceFor(null)}>
          <form onSubmit={doProduce}>
            {error && <Alert kind="error">{error}</Alert>}
            <Field label={t("الكمية المنتجة")} hint={`${t("المتبقي")}: ${num(remaining(produceFor))}`}>
              <input type="number" min="0" step="0.001" value={produceQty} onChange={(e) => setProduceQty(e.target.value)} autoFocus />
            </Field>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={busy}>{t("تسجيل الدفعة")}</button>
              <button type="button" className="btn" onClick={() => setProduceFor(null)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
      {scrapFor && (
        <Modal title={`${t("تسجيل هالك")} ${scrapFor.code}`} onClose={() => setScrapFor(null)}>
          <form onSubmit={doScrap}>
            {error && <Alert kind="error">{error}</Alert>}
            <Field label={t("كمية الهالك")}>
              <input type="number" min="0" step="0.001" value={scrapQty} onChange={(e) => setScrapQty(e.target.value)} autoFocus />
            </Field>
            <Field label={t("السبب / ملاحظات")}>
              <input value={scrapNotes} onChange={(e) => setScrapNotes(e.target.value)} />
            </Field>
            <div className="form-actions">
              <button type="submit" className="btn-delete" disabled={busy}>{t("تسجيل الهالك")}</button>
              <button type="button" className="btn" onClick={() => setScrapFor(null)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

export default function ProductionOrders() {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const searchKey = search.trim();
  const [statusFilter, setStatusFilter] = useState<"" | ProductionOrderStatus>("");
  const orders = useFetch(
    () => api.get<ProductionOrder[]>(`/production-orders?limit=1000${statusFilter ? `&status=${statusFilter}` : ""}${searchKey ? `&search=${encodeURIComponent(searchKey)}` : ""}`),
    `po-list-${statusFilter}-${searchKey}`
  );
  const products = useFetch(() => api.get<{ id: number; name: string }[]>("/products?limit=1000"), "po-products");
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?limit=500"), "po-warehouses");
  const suppliers = useFetch(() => api.get<{ id: number; name: string }[]>("/suppliers?limit=500"), "po-suppliers");
  const [showForm, setShowForm] = useState(false);
  const [view, setView] = useState<"orders" | "schedule" | "floor">("orders");
  const [details, setDetails] = useState<number | null>(null);
  const [produceFor, setProduceFor] = useState<ProductionOrder | null>(null);
  const [produceQty, setProduceQty] = useState("");
  const [scrapFor, setScrapFor] = useState<ProductionOrder | null>(null);
  const [scrapQty, setScrapQty] = useState("");
  const [scrapNotes, setScrapNotes] = useState("");
  const [showLines, setShowLines] = useState(false);
  const [confirming, setConfirming] = useState<{ order: ProductionOrder; action: "issue" | "close" | "cancel" | "stop" | "delete"; text: string } | null>(null);
  const act = useAction();
  const lines = useFetch(() => api.get<ProductionLine[]>("/production-lines"), "po-lines");
  const [availabilityFor, setAvailabilityFor] = useState<ProductionOrder | null>(null);
  const availability = useFetch(
    () => (availabilityFor ? api.get<MaterialsAvailability>(`/production-orders/${availabilityFor.id}/materials-availability`) : Promise.resolve(null)),
    `po-avail-${availabilityFor?.id ?? 0}`
  );

  const warehousesList: Warehouse[] = warehouses.data ?? [];
  const ordersList = orders.data ?? [];

  const refresh = () => orders.reload();

  const runAction = (order: ProductionOrder, action: "issue" | "close" | "cancel" | "stop" | "delete") =>
    act.run(async () => {
      if (action === "issue") await api.post(`/production-orders/${order.id}/issue`);
      if (action === "close") await api.post(`/production-orders/${order.id}/close`);
      if (action === "cancel") await api.post(`/production-orders/${order.id}/cancel`);
      if (action === "stop") await api.post(`/production-orders/${order.id}/cancel-running`);
      if (action === "delete") await api.del(`/production-orders/${order.id}`);
      refresh();
    });

  const printCard = (o: ProductionOrder) => {
    void (async () => {
      const res = await fetch(`/api/production-orders/${o.id}/print-card`, {
        headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
      });
      const html = await res.text();
      const win = window.open("", "_blank");
      if (win) {
        win.document.write(html);
        win.document.close();
      }
    })();
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
      <PageHeader title={t("أوامر التصنيع")}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button className={`btn ${view === "orders" ? "btn-primary" : ""}`} onClick={() => setView("orders")}>
            {t("📋 الأوامر")}
          </button>
          <button className={`btn ${view === "schedule" ? "btn-primary" : ""}`} onClick={() => setView("schedule")}>
            {t("📅 الجدولة")}
          </button>
          <button className={`btn ${view === "floor" ? "btn-primary" : ""}`} onClick={() => setView("floor")}>
            {t("🏭 أرضية التشغيل")}
          </button>
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>
            {t("+ أمر تصنيع جديد")}
          </button>
          <button className="btn" onClick={() => setShowLines(true)}>
            {t("⚙️ خطوط الإنتاج")}
          </button>
        </div>
      </PageHeader>

      {view === "schedule" && <ScheduleBoard />}
      {view === "floor" && <ShopFloor />}
      {view === "orders" && (
      <>

      <div className="toolbar page-actions" style={{ marginBottom: 14 }}>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as "" | ProductionOrderStatus)}>
          <option value="">{t("كل الحالات")}</option>
          {(Object.keys(PRODUCTION_STATUS_LABEL) as ProductionOrderStatus[]).map((s) => (
            <option key={s} value={s}>{PRODUCTION_STATUS_LABEL[s]}</option>
          ))}
        </select>
        <input
          style={{ width: 220 }}
          placeholder={t("بحث برقم الأمر أو المنتج…")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <Alert>{orders.error || act.error}</Alert>

      <div className="card table-wrap">
        {orders.loading && !orders.data ? (
          <Loading />
        ) : ordersList.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("الرقم")}</th>
                <th>{t("المنتج النهائي")}</th>
                <th className="num">{t("المخطط")}</th>
                <th className="num">{t("المنتج")}</th>
                <th>{t("المورد الصناعي")}</th>
                <th>{t("خط الإنتاج")}</th>
                <th>{t("مخزن الخامات")}</th>
                <th>{t("مخزن الناتج")}</th>
                <th>{t("الخامات")}</th>
                <th>{t("تاريخ الجدولة")}</th>
                <th className="num">{t("المتبقي")}</th>
                <th className="num">{t("الهالك")}</th>
                <th>{t("الحالة")}</th>
                <th>{t("إجراءات")}</th>
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
                    {o.materials_available == null ? (
                      <span className="muted">—</span>
                    ) : o.materials_available ? (
                      <span className="badge badge-confirmed">{t("متاحة")}</span>
                    ) : (
                      <span className="badge badge-cancelled">{t("ناقصة")}</span>
                    )}
                  </td>
                  <td>
                    {o.scheduled_date ?? "—"}
                    {isLate(o) && <span className="badge badge-cancelled" style={{ marginInlineStart: 4 }}>{t("متأخر")}</span>}
                  </td>
                  <td className="num">{o.status === "in_progress" ? num(o.qty_planned - o.qty_produced - o.qty_scrapped) : "—"}</td>
                  <td className="num">{o.qty_scrapped ? num(o.qty_scrapped) : "—"}</td>
                  <td>{badge(o.status)}</td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => setDetails(o.id)}>{t("تفاصيل")}</button>{" "}
                    <button className="btn btn-sm" onClick={() => printCard(o)} title={t("بطاقة للطباعة")}>🖨️</button>{" "}
                    {o.status === "draft" && (
                      <>
                        <button className="btn btn-sm" onClick={() => setAvailabilityFor(o)}>
                          {t("خامات؟")}
                        </button>{" "}
                        <button className="btn btn-sm btn-primary" onClick={() => setConfirming({ order: o, action: "issue", text: `${t("بدء تشغيل ")}${o.code}${t("؟ سيتم صرف الخامات من «")}${o.raw_warehouse_name}${t("» حسب قائمة المواد.")}` })}>
                          {t("▶ بدء التشغيل")}
                        </button>{" "}
                        <button className="btn btn-sm" style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => setConfirming({ order: o, action: "cancel", text: `${t("إلغاء الأمر ")}${o.code}${t("؟")}` })}>
                          {t("إلغاء")}
                        </button>{" "}
                        <button className="btn-delete" onClick={() => setConfirming({ order: o, action: "delete", text: `${t("حذف الأمر ")}${o.code}${t(" نهائيًا؟")}` })}>
                          حذف
                        </button>{" "}
                      </>
                    )}
                    {o.status === "in_progress" && (
                      <>
                        <button className="btn btn-sm btn-primary" onClick={() => { setProduceFor(o); setProduceQty(String(o.qty_planned - o.qty_produced - o.qty_scrapped)); }}>
                          {t("+ تسجيل إنتاج")}
                        </button>{" "}
                        <button className="btn btn-sm" onClick={() => { setScrapFor(o); setScrapQty("1"); }}>
                          {t("🗑️ هالك")}
                        </button>{" "}
                        <button className="btn btn-sm" onClick={() => setConfirming({ order: o, action: "close", text: `${t("إنهاء الأمر ")}${o.code}${t("؟ الفروق المتبقية سترحّل لمصاريف متنوعة.")}` })}>
                          {t("✔ إنهاء")}
                        </button>{" "}
                        {o.qty_produced === 0 && o.qty_scrapped === 0 && (
                          <button className="btn btn-sm" style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => setConfirming({ order: o, action: "stop", text: `${t("إيقاف الأمر ")}${o.code}${t(" وإرجاع خاماته لمخزنها؟ ستُعكس قيود الأجور تلقائيًا.")}` })}>
                            {t("⏹ إيقاف")}
                          </button>
                        )}
                      </>
                    )}
                    {o.status === "completed" && <span className="muted">{t("مكتمل")}</span>}
                    {o.status === "cancelled" && <span className="muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا توجد أوامر تصنيع — اضغط «+ أمر تصنيع جديد» للبدء.")}</Empty>
        )}
      </div>
      </>
      )}

      {showForm && (
        <ProductionOrderForm
          products={products.data ?? []}
          warehouses={warehousesList}
          suppliers={suppliers.data ?? []}
          lines={lines.data ?? []}
          onClose={() => setShowForm(false)}
          onSaved={() => { setShowForm(false); refresh(); }}
        />
      )}

      {details && (
        <ProductionDetailsModal orderId={details} onClose={() => setDetails(null)} onChanged={() => orders.reload()} />
      )}

      {produceFor && (
        <Modal title={`${t("تسجيل إنتاج — ")}${produceFor.code}`} onClose={() => { setProduceFor(null); setProduceQty(""); }}>
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); doProduce(); }}>
            <Alert>{act.error}</Alert>
            <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
              {t("المنتج: ")}<b>{produceFor.product_name}</b>{t(" · المخطط: ")}<b>{num(produceFor.qty_planned)}</b>{t(" · المنتج حتى الآن: ")}<b>{num(produceFor.qty_produced)}</b>{t(" · الهالك: ")}<b>{num(produceFor.qty_scrapped)}</b>{t(" · المتبقي: ")}<b>{num(produceFor.qty_planned - produceFor.qty_produced - produceFor.qty_scrapped)}</b>
            </p>
            <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
              {t("رقم الدفعة المقترح تلقائيًا: ")}<b dir="ltr">{produceFor.code}-B{produceFor.batches.length + 1}</b>{t(" — وتظهر في نافذة التفاصيل لفحص الجودة.")}
            </p>
            <Field label={t("كمية الدفعة المنتجة")} hint={`${t("تُضاف إلى «")}${produceFor.output_warehouse_name}${t("»")}`}>
              <input type="number" min="1" max={produceFor.qty_planned - produceFor.qty_produced - produceFor.qty_scrapped} step="1" value={produceQty} onChange={(e) => setProduceQty(e.target.value)} required autoFocus />
            </Field>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={act.busy}>{act.busy ? t("جارٍ التسجيل…") : t("تسجيل الإنتاج")}</button>
              <button type="button" className="btn" onClick={() => { setProduceFor(null); setProduceQty(""); }}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {availabilityFor && (
        <Modal title={`${t("توفر الخامات — ")}${availabilityFor.code}`} onClose={() => setAvailabilityFor(null)}>
          {availability.loading && !availability.data ? (
            <Loading />
          ) : availability.data ? (
            <>
              <Alert kind={availability.data.all_available ? "info" : "error"}>
                {availability.data.all_available
                  ? t("✅ كل الخامات متاحة في «") + (availability.data.warehouse_name ?? "") + t("» — يمكن بدء التشغيل.")
                  : `${t("⚠️ نواقص في ")}${availability.data.missing_count}${t(" خامة — أمدّ المخزن أولًا أو عدّل الكمية.")}`}
              </Alert>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>{t("المكوّن")}</th><th className="num">{t("المطلوب")}</th><th className="num">{t("المتاح")}</th><th className="num">{t("تكلفة الوحدة")}</th><th>{t("الحالة")}</th></tr>
                  </thead>
                  <tbody>
                    {availability.data.lines.map((l) => (
                      <tr key={l.component_id}>
                        <td>{l.component_name ?? `#${l.component_id}`}{l.staged && <span className="muted" style={{ fontSize: 11 }}> ({t("مرحلي")})</span>}</td>
                        <td className="num">{num(l.required)}</td>
                        <td className="num">{num(l.available)}</td>
                        <td className="num">{money(l.unit_cost)}</td>
                        <td>{l.enough ? <span className="badge badge-confirmed">{t("متاح")}</span> : <span className="badge badge-cancelled">{t("ناقص")}</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <Alert>{availability.error}</Alert>
          )}
        </Modal>
      )}

      {scrapFor && (
        <Modal title={`${t("تسجيل هالك — ")}${scrapFor.code}`} onClose={() => { setScrapFor(null); setScrapQty(""); setScrapNotes(""); }}>
          <form onSubmit={doScrap}>
            <Alert>{act.error}</Alert>
            <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
              {t("المتبقي للتشغيل: ")}<b>{num(scrapFor.qty_planned - scrapFor.qty_produced - scrapFor.qty_scrapped)}</b>{t(" — الكمية الهالكة تُرحّل من WIP لمصروف هالك ولا تُنتج.")}
            </p>
            <Field label={t("كمية الهالك")}>
              <input type="number" min="1" max={scrapFor.qty_planned - scrapFor.qty_produced - scrapFor.qty_scrapped} step="1" value={scrapQty} onChange={(e) => setScrapQty(e.target.value)} required autoFocus />
            </Field>
            <Field label={t("ملاحظات")} hint={t("سبب الهالك (اختياري)")}>
              <input value={scrapNotes} onChange={(e) => setScrapNotes(e.target.value)} maxLength={200} />
            </Field>
            <div className="form-actions">
              <button className="btn-delete" disabled={act.busy}>
                {act.busy ? t("جارٍ التسجيل…") : t("تسجيل الهالك")}
              </button>
              <button type="button" className="btn" onClick={() => { setScrapFor(null); setScrapQty(""); setScrapNotes(""); }}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {showLines && (
        <ProductionLinesModal onClose={() => setShowLines(false)} onChanged={() => lines.reload()} />
      )}

      {confirming && (
        <Modal title={t("تأكيد الإجراء")} onClose={() => setConfirming(null)}>
          <Alert>{act.error}</Alert>
          <p style={{ margin: "0 0 6px" }}>{confirming.text}</p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn"
              style={confirming.action === "issue" ? { color: "#fff", background: "var(--primary, #2563eb)" } : { color: "#fff", background: "var(--danger)" }}
              disabled={act.busy}
              onClick={() => { const { order, action } = confirming; runAction(order, action).then(() => setConfirming(null)); }}
            >
              {act.busy ? t("…") : t("تأكيد")}
            </button>
            <button type="button" className="btn" onClick={() => setConfirming(null)}>
              {t("إلغاء")}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
