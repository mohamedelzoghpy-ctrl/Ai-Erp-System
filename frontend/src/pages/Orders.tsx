import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { ReturnDialog } from "./Returns";
import { dateTime, money, num } from "../format";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Order, OrderStatus, Party, Product, SalesRep, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, Lookup, Modal, PageHeader, Pager, PaymentBadge, StatusBadge } from "../ui";

type Kind = "purchase" | "sales";

interface KindConfig {
  title: string;
  /** singular word for one document, used across headings and confirmations */
  orderWord: string;
  path: string;
  partyPath: string;
  partyField: "supplier_id" | "customer_id";
  partyLabel: string;
  priceField: "unit_cost" | "unit_price";
  priceLabel: string;
  newLabel: string;
  /** the transition that moves stock */
  commit: { path: string; label: string; confirmText: string };
  /** status after commit */
  doneStatus: OrderStatus;
  /** fallback file name prefix for downloads */
  docPrefix: string;
  returnPath: string;
  returnWord: string;
  refundLabel: string;
}

const CONFIG: Record<Kind, KindConfig> = {
  purchase: {
    title: "نقطة مشتريات",
    orderWord: "الفاتورة",
    path: "/purchase-orders",
    partyPath: "/suppliers",
    partyField: "supplier_id",
    partyLabel: "المورد",
    priceField: "unit_cost",
    priceLabel: "تكلفة الوحدة",
    newLabel: "+ فاتورة شراء جديدة",
    commit: { path: "receive", label: "استلام البضاعة", confirmText: "تأكيد استلام البضاعة؟ ستزيد كميات المخزون ويُحدَّث سعر التكلفة." },
    doneStatus: "received",
    docPrefix: "purchase-order",
    returnPath: "/purchase-returns",
    returnWord: "مرتجع للمورد",
    refundLabel: "المبلغ المستلم نقداً من المورد الآن",
  },
  sales: {
    title: "مسودة المبيعات",
    orderWord: "المسودة",
    path: "/sales-orders",
    partyPath: "/customers",
    partyField: "customer_id",
    partyLabel: "العميل",
    priceField: "unit_price",
    priceLabel: "سعر الوحدة",
    newLabel: "+ مسودة مبيعات جديدة",
    commit: { path: "confirm", label: "تحويل إلى فاتورة مبيعات", confirmText: "تحويل المسودة إلى فاتورة مبيعات؟ ستُخصم الكميات من الأرصدة وتصبح فاتورة مبيعات مؤكدة." },
    doneStatus: "confirmed",
    docPrefix: "invoice",
    returnPath: "/sales-returns",
    returnWord: "مرتجع من العميل",
    refundLabel: "المبلغ المردود نقداً للعميل الآن",
  },
};

export const PurchaseOrders = () => <OrdersScreen kind="purchase" />;
export const SalesOrders = () => <OrdersScreen kind="sales" />;

function partyId(o: Order, cfg: KindConfig): number | undefined {
  return o[cfg.partyField];
}

/** Warehouses are few, so the full list is loaded once and names are looked up locally. */
function warehouseName(list: Warehouse[] | null, id: number): string {
  return list?.find((w) => w.id === id)?.name ?? `#${id}`;
}

function OrdersScreen({ kind }: { kind: Kind }) {
  const cfg = CONFIG[kind];
  const { t } = useI18n();
  const [status] = useState(kind === "sales" ? "draft" : "");
  const [creating, setCreating] = useState(false);
  const [viewId, setViewId] = useState<number | null>(null);

  const orders = usePagedList<Order>(cfg.path, { status_filter: status });
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?limit=500"), "wh");

  const view = viewId != null ? orders.data?.find((o) => o.id === viewId) ?? null : null;

  return (
    <>
      <PageHeader title={kind === "purchase" ? t("orders.purchaseTitle") : t("orders.salesTitle")}>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          {kind === "purchase" ? t("orders.newPurchase") : t("orders.newSale")}
        </button>
      </PageHeader>

      <Alert>{orders.error || warehouses.error}</Alert>

      <div className="card table-wrap">
        {orders.loading && !orders.data ? (
          <Loading />
        ) : orders.data && orders.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>رقم {cfg.orderWord}</th>
                <th>التاريخ</th>
                <th>{cfg.partyLabel}</th>
                <th>المخزن</th>
                <th>الحالة</th>
                <th className="num">الإجمالي</th>
                <th>السداد</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {orders.data.map((o) => (
                <tr key={o.id}>
                  <td>#{o.id}</td>
                  <td>{dateTime(o.created_at)}</td>
                  <td>{o.party_name ?? `#${partyId(o, cfg)}`}</td>
                  <td>{warehouseName(warehouses.data, o.warehouse_id)}</td>
                  <td>
                    <StatusBadge status={o.status} />
                  </td>
                  <td className="num">{money(o.total_amount)}</td>
                  <td>
                    <PaymentBadge status={o.payment_status} />
                  </td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => setViewId(o.id)}>
                      عرض
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("orders.empty")}</Empty>
        )}
        <Pager list={orders} />
      </div>

      {creating && (
        <OrderForm
          cfg={cfg}
          warehouses={(warehouses.data ?? []).filter((w) => w.is_active)}
          onClose={() => setCreating(false)}
          onSaved={(id) => {
            setCreating(false);
            orders.setPage(1);
            orders.reload();
            setViewId(id);
          }}
        />
      )}
      {view && (
        <OrderDetail
          cfg={cfg}
          order={view}
          partyName={view.party_name ?? `#${partyId(view, cfg)}`}
          warehouseName={warehouseName(warehouses.data, view.warehouse_id)}
          onClose={() => setViewId(null)}
          onChanged={() => {
            orders.reload();
          }}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------- new order
interface Line {
  key: number;
  product: Product | null;
  quantity: string;
  price: string;
}

let lineKey = 1;
const newLine = (): Line => ({ key: lineKey++, product: null, quantity: "1", price: "" });

function OrderForm({
  cfg,
  warehouses,
  onClose,
  onSaved,
}: {
  cfg: KindConfig;
  warehouses: Warehouse[];
  onClose: () => void;
  onSaved: (id: number) => void;
}) {
  const { user } = useAuth();
  const safes = useFetch(() => api.get<{ id: number; name: string; is_active: boolean; branch_id: number }[]>("/safes"), "purchase-order-safes");
  const [party, setParty] = useState<Party | null>(null);
  const [warehouse, setWarehouse] = useState(warehouses.length === 1 ? String(warehouses[0].id) : "");
  const [paymentMode, setPaymentMode] = useState<"cash" | "credit">("credit");
  const [safeId, setSafeId] = useState("");
  const [discountMode, setDiscountMode] = useState<"amount" | "percent">("amount");
  const [discountValue, setDiscountValue] = useState("");
  const [taxEnabled, setTaxEnabled] = useState(true);
  const [notes, setNotes] = useState("");
  const reps = useFetch(() => api.get<SalesRep[]>("/reps?active_only=true"), "sales-order-reps");
  const [repId, setRepId] = useState("");
  const [lines, setLines] = useState<Line[]>([newLine()]);
  const { busy, error, run } = useAction();

  const isPurchaseOrder = cfg.priceField === "unit_cost";

  // Picking a warehouse resets the safe; the effect below auto-fills it from the
  // safe(s) of the branch the selected warehouse belongs to.
  const pickWarehouse = (id: string) => {
    setWarehouse(id);
    setSafeId("");
  };

  useEffect(() => {
    if (warehouse === "" || !safes.data) return;
    const branchId = warehouses.find((w) => String(w.id) === warehouse)?.branch_id;
    if (branchId === undefined) return;
    const branchSafe = safes.data.find((s) => s.is_active && s.branch_id === branchId);
    setSafeId((current) => (current === "" && branchSafe ? String(branchSafe.id) : current));
  }, [warehouse, safes.data, warehouses]);
  const defaultPrice = (p: Product | undefined) => (p ? (cfg.priceField === "unit_cost" ? p.cost_price : p.sale_price) : "");

  const patch = (key: number, change: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...change } : l)));
  const pickProduct = (key: number, p: Product | null) => patch(key, { product: p, price: p ? String(Number(defaultPrice(p))) : "" });

  const lineTotal = (l: Line) => (Number(l.quantity) || 0) * (Number(l.price) || 0);
  const total = lines.reduce((s, l) => s + lineTotal(l), 0);
  const filled = lines.filter((l) => l.product);
  const discountAmount = discountMode === "percent" ? total * (Number(discountValue) || 0) / 100 : Number(discountValue) || 0;
  const taxableAmount = Math.max(0, total - discountAmount);
  const vatAmount = isPurchaseOrder && taxEnabled ? Math.round(taxableAmount * 0.14 * 100) / 100 : 0;
  const netInvoice = taxableAmount + vatAmount;
  const validDiscount = !isPurchaseOrder || (Number.isFinite(Number(discountValue || 0)) && Number(discountValue || 0) >= 0 && (discountMode === "percent" ? Number(discountValue || 0) <= 100 : discountAmount <= total));
  const valid = !!party && !!warehouse && filled.length > 0 && validDiscount && (!isPurchaseOrder || paymentMode === "credit" || !!safeId) && filled.every((l) => Number.isInteger(Number(l.quantity)) && Number(l.quantity) > 0 && Number(l.price) >= 0);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    void run(async () => {
      const created = await api.post<Order>(cfg.path, {
        [cfg.partyField]: party!.id,
        warehouse_id: Number(warehouse),
        notes: notes.trim() || null,
        ...(isPurchaseOrder ? { payment_mode: paymentMode, safe_id: paymentMode === "cash" ? Number(safeId) : null, discount_mode: discountMode, discount_value: discountValue || "0", tax_rate: taxEnabled ? "14" : "0" } : { rep_id: repId === "" ? null : Number(repId), safe_id: safeId === "" ? null : Number(safeId) }),
        items: filled.map((l) => ({ product_id: l.product!.id, quantity: Number(l.quantity), [cfg.priceField]: l.price })),
      });
      onSaved(created.id);
    });
  };

  return (
    <Modal title={cfg.newLabel.replace("+ ", "")} onClose={onClose} fullscreen>
      <form onSubmit={submit} className="purchase-order-editor">
        <Alert>{error || (isPurchaseOrder ? safes.error : null)}</Alert>
        <section className="quotation-editor" aria-label="بيانات الفاتورة">
          <header className="quotation-editor-head">
            <h2>{cfg.newLabel.replace("+ ", "")}</h2>
            <div>{cfg.partyField === "customer_id" ? "رقم المسودة" : "رقم الفاتورة"}: <strong>يُولَّد عند الحفظ</strong></div>
            <div>التاريخ: <strong>{dateTime(new Date().toISOString())}</strong></div>
          </header>
          <div className="quotation-editor-meta pos-document-meta">
            <div className="quotation-meta-column">
              <Field label={cfg.partyLabel}>
                <Lookup<Party> path={cfg.partyPath} params={{ is_active: true }} value={party} onChange={setParty} label={(p) => p.name} placeholder={`ابحث عن ${cfg.partyLabel}…`} autoFocus />
              </Field>
              <Field label="اسم المخزن">
                <select value={warehouse} onChange={(e) => pickWarehouse(e.target.value)} required>
                  <option value="">— اختر المخزن —</option>
                  {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </Field>
            </div>
            <div className="quotation-meta-column">
              {isPurchaseOrder ? <>
                <Field label="مسؤول المشتريات">
                  <input value={user?.full_name || user?.username || ""} readOnly aria-label="مسؤول المشتريات" />
                </Field>
                <Field label="طريقة الدفع">
                  <select value={paymentMode} onChange={(e) => setPaymentMode(e.target.value as "cash" | "credit")} aria-label="طريقة الدفع">
                    <option value="cash">نقدي</option>
                    <option value="credit">آجل</option>
                  </select>
                </Field>
                {paymentMode === "cash" && <Field label="اسم الخزينة">
                  <select value={safeId} onChange={(e) => setSafeId(e.target.value)} required aria-label="اسم الخزينة">
                    <option value="">— اختر الخزينة —</option>
                    {(safes.data ?? []).filter((safe) => safe.is_active).map((safe) => <option key={safe.id} value={safe.id}>{safe.name}</option>)}
                  </select>
                </Field>}
              </> : <>
                <Field label="مندوب المبيعات">
                  <select value={repId} onChange={(e) => setRepId(e.target.value)} aria-label="مندوب المبيعات">
                    <option value="">— بدون مندوب —</option>
                    {(reps.data ?? []).map((rep) => <option key={rep.id} value={rep.id}>{rep.name}</option>)}
                  </select>
                </Field>
                <Field label="اسم الخزينة">
                  <select value={safeId} onChange={(e) => setSafeId(e.target.value)} aria-label="اسم الخزينة">
                    <option value="">— اختر الخزينة —</option>
                    {(safes.data ?? []).filter((safe) => safe.is_active).map((safe) => <option key={safe.id} value={safe.id}>{safe.name}</option>)}
                  </select>
                </Field>
              </>}
            </div>
          </div>
        </section>

        <div className="card card-pad pos-items-card purchase-order-items">
        <table className="lines">
          <thead>
            <tr>
              <th>المنتج</th>
              <th style={{ width: 90 }}>الكمية</th>
              <th style={{ width: 130 }}>{cfg.priceLabel}</th>
              <th className="num" style={{ width: 130 }}>
                الإجمالي
              </th>
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
                    <input type="number" min="1" step="1" value={l.quantity} onChange={(e) => patch(l.key, { quantity: e.target.value })} aria-label="الكمية" />
                  </td>
                  <td>
                    <input type="number" min="0" step="0.01" value={l.price} onChange={(e) => patch(l.key, { price: e.target.value })} aria-label={cfg.priceLabel} />
                  </td>
                  <td className="num">{money(lineTotal(l))}</td>
                  <td>
                    {lines.length > 1 && (
                      <button type="button" className="icon-btn" onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))} aria-label="delete السطر">
                        ✕
                      </button>
                    )}
                    {cfg.priceField === "unit_price" && p && Number(l.quantity) > p.quantity && (
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
            <div className="pos-summary-total">
              <span className="label">إجمالي الأصناف</span>
              <strong>{money(total)}</strong>
            </div>
            {isPurchaseOrder && <>
              <Field label="الخصم">
                <div className="pos-discount-inputs">
                  <select value={discountMode} onChange={(e) => setDiscountMode(e.target.value as "amount" | "percent")} aria-label="نوع الخصم">
                    <option value="amount">قيمة</option>
                    <option value="percent">نسبة مئوية</option>
                  </select>
                  <input dir="ltr" type="number" min="0" max={discountMode === "percent" ? 100 : total} step="0.01" value={discountValue} onChange={(e) => setDiscountValue(e.target.value)} aria-label="قيمة الخصم" placeholder={discountMode === "percent" ? "0%" : "0.00"} />
                </div>
                <span className="field-hint">قيمة الخصم: {money(discountAmount)}</span>
                {!validDiscount && <span className="field-hint low">الخصم لا يتجاوز إجمالي الأصناف.</span>}
              </Field>
              <Field label="ضريبة القيمة المضافة">
                <select value={taxEnabled ? "with-tax" : "without-tax"} onChange={(e) => setTaxEnabled(e.target.value === "with-tax")} aria-label="تطبيق ضريبة القيمة المضافة">
                  <option value="with-tax">بالضريبة (14%)</option>
                  <option value="without-tax">بدون ضريبة</option>
                </select>
                <span className="field-hint">قيمة الضريبة: {money(vatAmount)}</span>
              </Field>
              <div className="pos-summary-total pos-summary-net">
                <span className="label">صافي قيمة الفاتورة</span>
                <strong>{money(netInvoice)}</strong>
              </div>
            </>}
          </div>
          {!isPurchaseOrder && (
            <Field label="مندوب المبيعات">
              <select value={repId} onChange={(e) => setRepId(e.target.value)} aria-label="مندوب المبيعات">
                <option value="">— بدون مندوب —</option>
                {(reps.data ?? []).filter((r) => r.is_active).map((r) => (
                  <option key={r.id} value={r.id}>{r.name}</option>
                ))}
              </select>
            </Field>
          )}
          <Field label="ملاحظات">
            <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
          <p className="muted" style={{ fontSize: 13, textAlign: "center", margin: "4px 0 0" }}>
            {cfg.partyField === "customer_id"
              ? "تُحفظ كمسودة مبيعات بدون أي خصم من الأرصدة — التحويل إلى فاتورة مبيعات هو الذي يخصم المخزون."
              : "يتم استلام البضاعة وتحديث المخزون فور حفظ الفاتورة."}
          </p>
          <div className="pos-summary-actions">
            <button className="btn btn-primary pos-summary-primary" disabled={busy || !valid}>
              {busy ? "جارٍ الحفظ…" : cfg.partyField === "customer_id" ? "حفظ المسودة" : "حفظ فاتورة الشراء"}
            </button>
            <button type="button" className="btn" onClick={onClose}>إلغاء</button>
          </div>
        </section>
      </form>
    </Modal>
  );
}

// -------------------------------------------------------------- order detail
// PDF printing is shared: api.printPdf(path) sends the document to the browser print dialog.

function OrderDetail({
  cfg,
  order,
  partyName,
  warehouseName,
  onClose,
  onChanged,
}: {
  cfg: KindConfig;
  order: Order;
  partyName: string;
  warehouseName: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { busy, error, run } = useAction();
  const isDraft = order.status === "draft";
  const isSales = cfg.partyField === "customer_id";
  const [returning, setReturning] = useState(false);

  const transition = (path: string, confirmText: string) => {
    if (!confirm(confirmText)) return;
    void run(async () => {
      await api.post(`${cfg.path}/${order.id}/${path}`);
      onChanged();
    });
  };

  return (
    <Modal title={`${cfg.orderWord.startsWith("ال") ? cfg.orderWord : `ال${cfg.orderWord}`} #${order.id}`} onClose={onClose} wide>
      <Alert>{error}</Alert>
      <div className="form-grid" style={{ marginBottom: 12 }}>
        <div>
          <span className="muted">{cfg.partyLabel}: </span>
          {partyName}
        </div>
        <div>
          <span className="muted">المخزن: </span>
          {warehouseName}
        </div>
        <div>
          <span className="muted">التاريخ: </span>
          {dateTime(order.created_at)}
        </div>
        <div>
          <span className="muted">الحالة: </span>
          <StatusBadge status={order.status} />
        </div>
        {order.rep_name !== undefined && (
          <div>
            <span className="muted">مندوب المبيعات: </span>
            {order.rep_name ?? "—"}
          </div>
        )}
        {order.safe_name !== undefined && order.safe_name !== null && (
          <div>
            <span className="muted">اسم الخزينة: </span>
            {order.safe_name}
          </div>
        )}
      </div>
      {order.notes && (
        <p>
          <span className="muted">ملاحظات: </span>
          {order.notes}
        </p>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>المنتج</th>
              <th className="num">الكمية</th>
              <th className="num">{cfg.priceLabel}</th>
              <th className="num">الإجمالي</th>
            </tr>
          </thead>
          <tbody>
            {order.items.map((it) => {
              const price = it[cfg.priceField] ?? "0";
              return (
                <tr key={it.id}>
                  <td>{it.product_name ?? `#${it.product_id}`}</td>
                  <td className="num">{num(it.quantity)}</td>
                  <td className="num">{money(price)}</td>
                  <td className="num">{money(Number(price) * it.quantity)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="total-row">
        <span>الإجمالي</span>
        <span>{money(order.total_amount)}</span>
      </div>
      {order.payment_status && (
        <p style={{ marginTop: 0 }}>
          السداد: <PaymentBadge status={order.payment_status} /> · المسدد: <b>{money(order.paid_amount)}</b> · المتبقي: <b>{money(order.balance_due)}</b>
          <span className="muted" style={{ display: "block", fontSize: 12 }}>
            تُوزَّع المدفوعات تلقائياً على الأقدم أولاً (رصيد أول المدة ثم الفواتير بترتيب تأكيدها).
          </span>
        </p>
      )}

      <div className="form-actions" style={{ marginBottom: 4 }}>
        <button className="btn" disabled={busy} onClick={() => void run(() => api.printPdf(`${cfg.path}/${order.id}/pdf`))}>
          🖨 طباعة
        </button>
        <button className="btn" disabled={busy} onClick={() => void run(() => api.download(`${cfg.path}/${order.id}/pdf`, `${cfg.docPrefix}-${order.id}.pdf`))}>
          ⬇ تنزيل PDF
        </button>
        <button className="btn" disabled={busy} onClick={() => void run(() => api.download(`${cfg.path}/${order.id}/xlsx`, `${cfg.docPrefix}-${order.id}.xlsx`))}>
          ⬇ تنزيل Excel
        </button>
      </div>

      {isDraft ? (
        <div className="form-actions">
          {isSales ? (
            <>
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={() => transition(cfg.commit.path, cfg.commit.confirmText)}
              >
                ✅ {cfg.commit.label}
              </button>
              <button
                className="btn btn-success"
                title="نسخة رسمية من بيان الأسعار — بدون أي خصم من الأرصدة"
                disabled={busy}
                onClick={() => void run(() => api.download(`${cfg.path}/${order.id}/quotation.pdf`, `quotation-SO-${order.id}.pdf`))}
              >
                🧾 تحويل إلى بيان أسعار مبيعات
              </button>
              <button className="btn btn-danger" disabled={busy} onClick={() => transition("cancel", `إلغاء ${cfg.orderWord}؟ لا يمكن التراجع.`)}>
                إلغاء {cfg.orderWord}
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-primary" disabled={busy} onClick={() => transition(cfg.commit.path, cfg.commit.confirmText)}>
                {cfg.commit.label}
              </button>
              <button className="btn btn-danger" disabled={busy} onClick={() => transition("cancel", `إلغاء ${cfg.orderWord}؟ لا يمكن التراجع.`)}>
                إلغاء {cfg.orderWord}
              </button>
            </>
          )}
        </div>
      ) : (
        <>
          <p className="muted" style={{ marginBottom: 8 }}>
            {order.status === "cancelled" ? `${cfg.orderWord} ملغاة.` : isSales ? "تم تحويل المسودة إلى فاتورة مبيعات وخصم الكميات من الأرصدة." : `تم تنفيذ ${cfg.orderWord} وتحديث المخزون.`}
          </p>
          {order.status === cfg.doneStatus && order.items.some((i) => i.quantity > (i.returned_quantity ?? 0)) && (
            <div className="form-actions">
              <button className="btn" onClick={() => setReturning(true)}>
                ↩ تسجيل {cfg.returnWord}
              </button>
            </div>
          )}
        </>
      )}
      {returning && (
        <ReturnDialog
          cfg={cfg}
          order={order}
          onClose={() => setReturning(false)}
          onDone={() => {
            setReturning(false);
            onChanged();
          }}
        />
      )}
    </Modal>
  );
}
