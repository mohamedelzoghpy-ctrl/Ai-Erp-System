import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { dateTime, METHOD_LABEL, money, num } from "../format";

/** طرق الرد في المرتجعات — مع «آجل» (يُخصم كامل القيمة من رصيد الطرف). */
const RETURN_METHODS: Record<ReturnMethod, string> = { ...METHOD_LABEL, credit: "آجل" };
type ReturnMethod = PaymentMethod | "credit";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Order, Party, PaymentMethod, Product, ReturnDoc, SalesRep, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, Lookup, Modal, PageHeader, Pager } from "../ui";

interface DialogCfg {
  returnPath: string;
  returnWord: string;
  refundLabel: string;
  priceField: "unit_cost" | "unit_price";
}

/** Records a return against a confirmed sale / received purchase order. */
export function ReturnDialog({ cfg, order, onClose, onDone }: { cfg: DialogCfg; order: Order; onClose: () => void; onDone: () => void }) {
  const lines = order.items.map((i) => ({ item: i, left: i.quantity - (i.returned_quantity ?? 0), price: Number(i[cfg.priceField] ?? 0) }));
  const [qty, setQty] = useState<Record<number, string>>({});
  const [refund, setRefund] = useState("");
  const [method, setMethod] = useState<ReturnMethod>("cash");
  const [notes, setNotes] = useState("");
  const { busy, error, run } = useAction();

  const chosen = lines.filter((l) => Number(qty[l.item.id]) > 0);
  const total = chosen.reduce((s, l) => s + Number(qty[l.item.id]) * l.price, 0);
  const refundNum = refund === "" ? 0 : Number(refund);
  const valid = chosen.length > 0 && chosen.every((l) => Number.isInteger(Number(qty[l.item.id])) && Number(qty[l.item.id]) <= l.left) && refundNum >= 0 && refundNum <= total + 1e-9;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    void run(async () => {
      await api.post(cfg.returnPath, {
        order_id: order.id,
        items: chosen.map((l) => ({ order_item_id: l.item.id, quantity: Number(qty[l.item.id]) })),
        refund_amount: String(refundNum),
        method,
        notes: notes.trim() || null,
      });
      onDone();
    });
  };

  const isPurchaseReturn = cfg.priceField === "unit_cost";

  return (
    <Modal title={`${cfg.returnWord} — أمر #${order.id}`} onClose={onClose} fullscreen={isPurchaseReturn} wide={!isPurchaseReturn}>
      <form onSubmit={submit} className={isPurchaseReturn ? "purchase-order-editor" : undefined}>
        <Alert>{error}</Alert>
        {isPurchaseReturn && <section className="quotation-editor" aria-label="بيانات مرتجع المشتريات">
          <header className="quotation-editor-head">
            <h2>فاتورة مرتجع مشتريات</h2>
            <div>رقم المرتجع: <strong>يُولَّد عند الحفظ</strong></div>
            <div>التاريخ: <strong>{dateTime(new Date().toISOString())}</strong></div>
          </header>
          <div className="quotation-editor-meta pos-document-meta">
            <div className="quotation-meta-column">
              <Field label="اسم المورد"><input value={order.party_name ?? "—"} readOnly /></Field>
              <Field label="المخزن"><input value={order.warehouse_id ? `#${order.warehouse_id}` : "—"} readOnly /></Field>
            </div>
            <div className="quotation-meta-column">
              <Field label="رقم فاتورة الشراء الأصلية"><input value={`PO-${order.id}`} readOnly /></Field>
              <Field label="نوع المرتجع"><input value="مرتجع مورد" readOnly /></Field>
            </div>
          </div>
        </section>}
        {isPurchaseReturn ? (
          <div className="card card-pad pos-items-card purchase-order-items">
            <table className="lines">
              <thead><tr><th>المنتج</th><th className="num">المستلم</th><th className="num">سبق إرجاعه</th><th style={{ width: 110 }}>كمية المرتجع</th><th className="num">القيمة</th></tr></thead>
              <tbody>{lines.map((l) => (
                <tr key={l.item.id}>
                  <td>{l.item.product_name ?? `#${l.item.product_id}`}</td>
                  <td className="num">{num(l.item.quantity)}</td>
                  <td className="num">{num(l.item.returned_quantity ?? 0)}</td>
                  <td><input type="number" min="0" max={l.left} step="1" disabled={l.left === 0} aria-label={`كمية مرتجع ${l.item.product_name ?? l.item.product_id}`} value={qty[l.item.id] ?? ""} onChange={(e) => setQty((q) => ({ ...q, [l.item.id]: e.target.value }))} /></td>
                  <td className="num">{money((Number(qty[l.item.id]) || 0) * l.price)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : (
          <table className="lines">
            <thead><tr><th>المنتج</th><th className="num">المباع/المستلم</th><th className="num">سبق إرجاعه</th><th style={{ width: 110 }}>كمية المرتجع</th><th className="num">القيمة</th></tr></thead>
            <tbody>{lines.map((l) => (
              <tr key={l.item.id}>
                <td>{l.item.product_name ?? `#${l.item.product_id}`}</td>
                <td className="num">{num(l.item.quantity)}</td>
                <td className="num">{num(l.item.returned_quantity ?? 0)}</td>
                <td><input type="number" min="0" max={l.left} step="1" disabled={l.left === 0} aria-label={`كمية مرتجع ${l.item.product_name ?? l.item.product_id}`} value={qty[l.item.id] ?? ""} onChange={(e) => setQty((q) => ({ ...q, [l.item.id]: e.target.value }))} /></td>
                <td className="num">{money((Number(qty[l.item.id]) || 0) * l.price)}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
        {isPurchaseReturn ? (
          <section className="card card-pad pos-summary-card purchase-order-summary">
            <div className="purchase-cost-breakdown">
              <div className="pos-summary-total pos-summary-net"><span className="label">إجمالي المرتجع</span><strong>{money(total)}</strong></div>
            </div>
            <div className="form-grid">
              <Field label={cfg.refundLabel} hint={`الباقي (${money(Math.max(total - refundNum, 0))}) يُخصم من الرصيد`}>
                <input dir="ltr" type="number" min="0" max={total || undefined} step="0.01" value={refund} placeholder="0" onChange={(e) => setRefund(e.target.value)} />
              </Field>
              <Field label="طريقة الرد">
                <select value={method} onChange={(e) => setMethod(e.target.value as ReturnMethod)}>
                  {Object.keys(RETURN_METHODS).map((m) => <option key={m} value={m}>{RETURN_METHODS[m as ReturnMethod]}</option>)}
                </select>
              </Field>
            </div>
            <Field label="ملاحظات / سبب الإرجاع"><textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
            <div className="pos-summary-actions">
              <button className="btn btn-primary pos-summary-primary" disabled={busy || !valid}>{busy ? "جارٍ الحفظ…" : "حفظ مرتجع المشتريات"}</button>
              <button type="button" className="btn" onClick={onClose}>إلغاء</button>
            </div>
          </section>
        ) : (
          <>
            <div className="total-row"><span>إجمالي المرتجع</span><span>{money(total)}</span></div>
            <div className="form-grid">
              <Field label={cfg.refundLabel} hint={`الباقي (${money(Math.max(total - refundNum, 0))}) يُخصم من الرصيد`}>
                <input dir="ltr" type="number" min="0" max={total || undefined} step="0.01" value={refund} placeholder="0" onChange={(e) => setRefund(e.target.value)} />
              </Field>
              <Field label="طريقة الرد">
                <select value={method} onChange={(e) => setMethod(e.target.value as ReturnMethod)}>
                  {Object.keys(RETURN_METHODS).map((m) => <option key={m} value={m}>{RETURN_METHODS[m as ReturnMethod]}</option>)}
                </select>
              </Field>
            </div>
            <Field label="ملاحظات / سبب الإرجاع"><textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
            <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>المرتجع نهائي ولا يمكن تعديله أو إلغاؤه بعد الحفظ؛ يتم تحديث المخزون والرصيد فوراً.</p>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={busy || !valid}>{busy ? "جارٍ الحفظ…" : "تسجيل المرتجع"}</button>
              <button type="button" className="btn" onClick={onClose}>إلغاء</button>
            </div>
          </>
        )}
      </form>
    </Modal>
  );
}

/** List of returns. With `lockKind` the page is dedicated to one direction (no tabs). */
export default function Returns({ defaultKind = "sales", lockKind }: { defaultKind?: "sales" | "purchase"; lockKind?: "sales" | "purchase" }) {
  const { t } = useI18n();
  const [kindState, setKindState] = useState<"sales" | "purchase">(lockKind ?? defaultKind);
  const kind = lockKind ?? kindState;
  const setKind = setKindState;
  const list = usePagedList<ReturnDoc>(kind === "sales" ? "/sales-returns" : "/purchase-returns", {});
  const [open, setOpen] = useState<ReturnDoc | null>(null);
  const [creating, setCreating] = useState(false);

  return (
    <>
      <PageHeader title={lockKind ? (lockKind === "sales" ? t("returns.sales") : t("returns.purchases")) : t("returns.title")}>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>+ تسجيل مرتجع جديد</button>
      </PageHeader>
      {!lockKind && (
        <div className="tabs" role="tablist">
          {(["sales", "purchase"] as const).map((k) => (
            <button key={k} role="tab" aria-selected={kind === k} className={`tab${kind === k ? " active" : ""}`} onClick={() => setKind(k)}>
              {k === "sales" ? t("returns.sales") : t("returns.purchases")}
            </button>
          ))}
        </div>
      )}
      <p className="muted" style={{ marginTop: 0 }} dir="rtl">
        {kind === "purchase"
          ? "اضغط «تسجيل مرتجع جديد»، اختر المخزن والمنتجات المرتجعة وسجل المرتجع مباشرة — بدون الحاجة لأمر شراء أصلي."
          : "اضغط «تسجيل مرتجع جديد»، اختر الأمر البيع الأصلي وسجل المرتجع من هنا مباشرة — أو افتح الفاتورة من «نقطة البيع» أو «مسودة المبيعات»."}
      </p>
      <Alert>{list.error}</Alert>
      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>الرقم</th>
                <th>التاريخ</th>
                <th>الأمر</th>
                <th>{kind === "sales" ? "العميل" : "المورد"}</th>
                <th className="num">الإجمالي</th>
                <th className="num">رد نقدي</th>
                <th>ملاحظات</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((r) => (
                <tr key={r.id}>
                  <td dir="ltr">
                    {kind === "sales" ? "SR" : "PR"}-{r.id}
                  </td>
                  <td>{dateTime(r.created_at)}</td>
                  <td>{r.order_id ? `#${r.order_id}` : "مرتجع حر"}</td>
                  <td>{r.party_name ?? "—"}</td>
                  <td className="num">{money(r.total_amount)}</td>
                  <td className="num">{Number(r.refund_amount) ? money(r.refund_amount) : "—"}</td>
                  <td>{r.notes ?? ""}</td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => setOpen(r)}>
                      عرض
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("returns.empty")}</Empty>
        )}
        <Pager list={list} />
      </div>
      {open && (
        <Modal title={`${kind === "sales" ? "SR" : "PR"}-${open.id} — ${open.party_name ?? ""}`} onClose={() => setOpen(null)}>
          <table>
            <thead>
              <tr>
                <th>{t("returns.product")}</th>
                <th className="num">{t("returns.qty")}</th>
                <th className="num">{t("returns.price")}</th>
                <th className="num">{t("returns.value")}</th>
              </tr>
            </thead>
            <tbody>
              {open.items.map((i) => (
                <tr key={i.id}>
                  <td>{i.product_name ?? `#${i.product_id}`}</td>
                  <td className="num">{num(i.quantity)}</td>
                  <td className="num">{money(i.unit_price)}</td>
                  <td className="num">{money(Number(i.unit_price) * i.quantity)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ marginBottom: 0 }}>
            الإجمالي: <b>{money(open.total_amount)}</b> · مردود نقداً: <b>{money(open.refund_amount)}</b> ({RETURN_METHODS[open.method as ReturnMethod] ?? open.method})
          </p>
        </Modal>
      )}

      {creating && (
        kind === "purchase"
          ? <PurchaseReturnEditor onClose={() => setCreating(false)} onDone={() => { setCreating(false); list.reload(); }} />
          : <FreeReturnDialog onClose={() => setCreating(false)} onDone={() => { setCreating(false); list.reload(); }} />
      )}
    </>
  );
}

/** مرتبج مبيعات حر (بدون أمر بيع) — بنفس شكل «فاتورة بيع جديدة». */
function FreeReturnDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?limit=500"), "sales-return-whs");
  const reps = useFetch(() => api.get<SalesRep[]>("/reps?active_only=true"), "sales-return-reps");
  interface Line { key: number; product: Product | null; qty: string; price: string; }
  let lineKey = 100;
  const newLine = (): Line => ({ key: ++lineKey, product: null, qty: "1", price: "" });
  const [lines, setLines] = useState<Line[]>([{ key: 1, product: null, qty: "1", price: "" }]);
  const [party, setParty] = useState<Party | null>(null);
  const [warehouse, setWarehouse] = useState("");
  const [repId, setRepId] = useState("");
  const [refund, setRefund] = useState("");
  const [method, setMethod] = useState<ReturnMethod>("cash");
  const [notes, setNotes] = useState("");
  const { busy, error, run } = useAction();

  const patch = (key: number, change: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...change } : l)));
  const pickProduct = (key: number, p: Product | null) => patch(key, { product: p, price: p ? String(Number(p.sale_price)) : "" });
  const pickedLines = lines.filter((l) => l.product && Number(l.qty) > 0);
  const total = pickedLines.reduce((s, l) => s + Number(l.price || l.product?.sale_price || 0) * Number(l.qty), 0);
  const refundNum = refund === "" ? 0 : Number(refund);
  const valid = !!warehouse && pickedLines.length > 0 && pickedLines.every((l) => Number.isInteger(Number(l.qty)) && Number(l.qty) > 0 && Number(l.price || l.product?.sale_price || 0) >= 0) && refundNum >= 0 && refundNum <= total + 1e-9;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    void run(async () => {
      await api.post("/sales-returns", {
        order_id: null,
        customer_id: party?.id ?? null,
        warehouse_id: Number(warehouse),
        rep_id: repId === "" ? null : Number(repId),
        items: pickedLines.map((l) => ({ product_id: l.product!.id, quantity: Number(l.qty), unit_price: l.price === "" ? null : Number(l.price) })),
        refund_amount: String(refundNum),
        method,
        notes: notes.trim() || null,
      });
      onDone();
    });
  };

  return (
    <Modal title="مرتجع مبيعات — بدون أمر بيع" onClose={onClose} fullscreen>
      <form onSubmit={submit} className="purchase-order-editor">
        <Alert>{error}</Alert>
        <section className="quotation-editor" aria-label="بيانات مرتجع المبيعات">
          <header className="quotation-editor-head">
            <h2>فاتورة مرتجع مبيعات</h2>
            <div>رقم المرتجع: <strong>يُولَّد عند الحفظ</strong></div>
            <div>التاريخ: <strong>{dateTime(new Date().toISOString())}</strong></div>
          </header>
          <div className="quotation-editor-meta pos-document-meta">
            <div className="quotation-meta-column">
              <Field label="العميل" hint="اختياري — بدون عميل لن يؤثر رصيد أي عميل">
                <Lookup<Party> path="/customers" params={{ is_active: true }} value={party} onChange={setParty} label={(x) => x.name} placeholder="ابحث عن عميل…" autoFocus />
              </Field>
              <Field label="اسم المخزن" hint="تُضاف الكميات للمخزن المختار">
                <select value={warehouse} onChange={(e) => setWarehouse(e.target.value)} required aria-label="اسم المخزن">
                  <option value="">— اختر المخزن —</option>
                  {(warehouses.data ?? []).filter((w) => w.is_active).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </Field>
            </div>
            <div className="quotation-meta-column">
              <Field label="مندوب المبيعات" hint="اختياري — المندوب المسجل على المرتجع">
                <select value={repId} onChange={(e) => setRepId(e.target.value)} aria-label="مندوب المبيعات">
                  <option value="">— بدون مندوب —</option>
                  {(reps.data ?? []).filter((r) => r.is_active).map((r) => (<option key={r.id} value={r.id}>{r.name}</option>))}
                </select>
              </Field>
              <Field label="نوع المرتجع">
                <input value="مرتجع عميل — بدون فاتورة بيع" readOnly aria-label="نوع المرتجع" />
              </Field>
            </div>
          </div>
        </section>

        <div className="card card-pad pos-items-card purchase-order-items">
          <table className="lines">
            <thead>
              <tr>
                <th>المنتج</th>
                <th style={{ width: 90 }}>الكمية</th>
                <th style={{ width: 130 }}>سعر الوحدة</th>
                <th className="num" style={{ width: 130 }}>الإجمالي</th>
                <th style={{ width: 36 }} />
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => {
                const p = l.product;
                return (
                  <tr key={l.key}>
                    <td>
                      <Lookup<Product>
                        path="/products"
                        params={{ is_active: true }}
                        value={l.product}
                        onChange={(x) => pickProduct(l.key, x)}
                        label={(x) => `${x.name} (${x.sku})`}
                        text={(x) => `${x.name} (${x.sku})`}
                        placeholder="ابحث بالاسم أو الكود…"
                      />
                    </td>
                    <td>
                      <input type="number" min="1" step="1" value={l.qty} onChange={(e) => patch(l.key, { qty: e.target.value })} aria-label="الكمية" />
                    </td>
                    <td>
                      <input dir="ltr" type="number" min="0" step="0.01" value={l.price} onChange={(e) => patch(l.key, { price: e.target.value })} aria-label="سعر الوحدة" />
                    </td>
                    <td className="num">{money(Number(l.price || p?.sale_price || 0) * Number(l.qty))}</td>
                    <td>
                      {lines.length > 1 && (
                        <button type="button" className="icon-btn" onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))} aria-label="delete السطر">
                          ✕
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <button type="button" className="btn btn-sm" onClick={() => setLines((ls) => [...ls, newLine()])}>
            + إضافة سطر
          </button>
        </div>

        <section className="card card-pad pos-summary-card purchase-order-summary">
          <div className="purchase-cost-breakdown">
            <div className="pos-summary-total pos-summary-net"><span className="label">إجمالي المرتجع</span><strong>{money(total)}</strong></div>
            <Field label="المبلغ المردود نقداً للعميل" hint={party ? `الباقي (${money(Math.max(total - refundNum, 0))}) يُخصم من رصيد العميل` : "بدون عميل: هذا رد نقدي فقط"}>
              <input dir="ltr" type="number" min="0" max={total || undefined} step="0.01" value={refund} placeholder="0" onChange={(e) => setRefund(e.target.value)} aria-label="المبلغ المردود نقداً للعميل" />
            </Field>
            <Field label="طريقة الرد">
              <select value={method} onChange={(e) => setMethod(e.target.value as ReturnMethod)}>
                {Object.keys(RETURN_METHODS).map((m) => <option key={m} value={m}>{RETURN_METHODS[m as ReturnMethod]}</option>)}
              </select>
            </Field>
          </div>
          <Field label="ملاحظات / سبب الإرجاع">
            <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
          <p className="muted" style={{ fontSize: 13, textAlign: "center", margin: "4px 0 0" }}>
            المرتجع نهائي ولا يمكن تعديله أو إلغاؤه بعد الحفظ؛ يتم إضافة الكميات للمخزون فوراً.
          </p>
          <div className="pos-summary-actions">
            <button className="btn btn-primary pos-summary-primary" disabled={busy || !valid}>
              {busy ? "جارٍ الحفظ…" : "حفظ مرتجع المبيعات"}
            </button>
            <button type="button" className="btn" onClick={onClose}>إلغاء</button>
          </div>
        </section>
      </form>
    </Modal>
  );
}

/** مرتجع مشتريات مستقل (بدون أمر شراء) — بنفس شكل «فاتورة شراء جديدة». */
function PurchaseReturnEditor({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { user } = useAuth();
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?limit=500"), "purchase-return-whs");
  interface Line { key: number; product: Product | null; qty: string; price: string; }
  let lineKey = 100;
  const newLine = (): Line => ({ key: ++lineKey, product: null, qty: "1", price: "" });
  const [lines, setLines] = useState<Line[]>([{ key: 1, product: null, qty: "1", price: "" }]);
  const [party, setParty] = useState<Party | null>(null);
  const [warehouse, setWarehouse] = useState("");
  const [refund, setRefund] = useState("");
  const [method, setMethod] = useState<ReturnMethod>("cash");
  const [notes, setNotes] = useState("");
  const { busy, error, run } = useAction();

  const patch = (key: number, change: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...change } : l)));
  const pickProduct = (key: number, p: Product | null) => patch(key, { product: p, price: p ? String(Number(p.cost_price)) : "" });
  const pickedLines = lines.filter((l) => l.product && Number(l.qty) > 0);
  const total = pickedLines.reduce((s, l) => s + Number(l.price || l.product?.cost_price || 0) * Number(l.qty), 0);
  const refundNum = refund === "" ? 0 : Number(refund);
  const valid = !!warehouse && pickedLines.length > 0 && pickedLines.every((l) => Number.isInteger(Number(l.qty)) && Number(l.qty) > 0 && Number(l.price || l.product?.cost_price || 0) >= 0) && refundNum >= 0 && refundNum <= total + 1e-9;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    void run(async () => {
      await api.post("/purchase-returns", {
        order_id: null,
        supplier_id: party?.id ?? null,
        warehouse_id: Number(warehouse),
        items: pickedLines.map((l) => ({ product_id: l.product!.id, quantity: Number(l.qty), unit_price: l.price === "" ? null : Number(l.price) })),
        refund_amount: String(refundNum),
        method,
        notes: notes.trim() || null,
      });
      onDone();
    });
  };

  return (
    <Modal title="مرتجع مشتريات — بدون أمر شراء" onClose={onClose} fullscreen>
      <form onSubmit={submit} className="purchase-order-editor">
        <Alert>{error}</Alert>
        <section className="quotation-editor" aria-label="بيانات مرتجع المشتريات">
          <header className="quotation-editor-head">
            <h2>فاتورة مرتجع مشتريات</h2>
            <div>رقم المرتجع: <strong>يُولَّد عند الحفظ</strong></div>
            <div>التاريخ: <strong>{dateTime(new Date().toISOString())}</strong></div>
          </header>
          <div className="quotation-editor-meta pos-document-meta">
            <div className="quotation-meta-column">
              <Field label="اسم المورد" hint="اختياري — بدون مورد لن يؤثر رصيد أي مورد">
                <Lookup<Party> path="/suppliers" params={{ is_active: true }} value={party} onChange={setParty} label={(x) => x.name} placeholder="ابحث عن مورد…" autoFocus />
              </Field>
              <Field label="اسم المخزن" hint="تُخصم الكميات من المخزن المختار">
                <select value={warehouse} onChange={(e) => setWarehouse(e.target.value)} required aria-label="اسم المخزن">
                  <option value="">— اختر المخزن —</option>
                  {(warehouses.data ?? []).filter((w) => w.is_active).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </Field>
            </div>
            <div className="quotation-meta-column">
              <Field label="مسؤول المشتريات">
                <input value={user?.full_name || user?.username || ""} readOnly aria-label="مسؤول المشتريات" />
              </Field>
              <Field label="نوع المرتجع">
                <input value="مرتجع مورد — بدون فاتورة شراء" readOnly aria-label="نوع المرتجع" />
              </Field>
            </div>
          </div>
        </section>

        <div className="card card-pad pos-items-card purchase-order-items">
          <table className="lines">
            <thead>
              <tr>
                <th>المنتج</th>
                <th style={{ width: 90 }}>الكمية</th>
                <th style={{ width: 130 }}>تكلفة الوحدة</th>
                <th className="num" style={{ width: 130 }}>الإجمالي</th>
                <th style={{ width: 36 }} />
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => {
                const p = l.product;
                return (
                  <tr key={l.key}>
                    <td>
                      <Lookup<Product>
                        path="/products"
                        params={{ is_active: true }}
                        value={l.product}
                        onChange={(x) => pickProduct(l.key, x)}
                        label={(x) => `${x.name} (${x.sku}) — المتاح ${x.quantity}`}
                        text={(x) => `${x.name} (${x.sku})`}
                        placeholder="ابحث بالاسم أو الكود…"
                      />
                    </td>
                    <td>
                      <input type="number" min="1" step="1" value={l.qty} onChange={(e) => patch(l.key, { qty: e.target.value })} aria-label="الكمية" />
                    </td>
                    <td>
                      <input dir="ltr" type="number" min="0" step="0.01" value={l.price} onChange={(e) => patch(l.key, { price: e.target.value })} aria-label="تكلفة الوحدة" />
                    </td>
                    <td className="num">{money(Number(l.price || p?.cost_price || 0) * Number(l.qty))}</td>
                    <td>
                      {lines.length > 1 && (
                        <button type="button" className="icon-btn" onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))} aria-label="delete السطر">
                          ✕
                        </button>
                      )}
                      {p && Number(l.qty) > p.quantity && (
                        <span className="low" title="الكمية أكبر من المتاح حالياً" style={{ marginInlineStart: 4 }}>
                          ⚠
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <button type="button" className="btn btn-sm" onClick={() => setLines((ls) => [...ls, newLine()])}>
            + إضافة سطر
          </button>
        </div>

        <section className="card card-pad pos-summary-card purchase-order-summary">
          <div className="purchase-cost-breakdown">
            <div className="pos-summary-total pos-summary-net"><span className="label">إجمالي المرتجع</span><strong>{money(total)}</strong></div>
            <Field label="المبلغ المستلم نقداً من المورد" hint={`الباقي (${money(Math.max(total - refundNum, 0))}) يُخصم من رصيد المورد`}>
              <input dir="ltr" type="number" min="0" max={total || undefined} step="0.01" value={refund} placeholder="0" onChange={(e) => setRefund(e.target.value)} aria-label="المبلغ المستلم نقداً من المورد" />
            </Field>
            <Field label="طريقة الرد">
              <select value={method} onChange={(e) => setMethod(e.target.value as ReturnMethod)}>
                {Object.keys(RETURN_METHODS).map((m) => <option key={m} value={m}>{RETURN_METHODS[m as ReturnMethod]}</option>)}
              </select>
            </Field>
          </div>
          <Field label="ملاحظات / سبب الإرجاع">
            <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
          <p className="muted" style={{ fontSize: 13, textAlign: "center", margin: "4px 0 0" }}>
            المرتجع نهائي ولا يمكن تعديله أو إلغاؤه بعد الحفظ؛ يتم خصم الكميات من المخزون فوراً.
          </p>
          <div className="pos-summary-actions">
            <button className="btn btn-primary pos-summary-primary" disabled={busy || !valid}>
              {busy ? "جارٍ الحفظ…" : "حفظ مرتجع المشتريات"}
            </button>
            <button type="button" className="btn" onClick={onClose}>إلغاء</button>
          </div>
        </section>
      </form>
    </Modal>
  );
}
