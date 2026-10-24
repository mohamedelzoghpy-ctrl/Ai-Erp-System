import { useState, type FormEvent } from "react";
import { api } from "../api";
import { dateTime, money, num } from "../format";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Order, OrderStatus, Party, Product, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, Modal, nameOf, PageHeader, Pager, StatusBadge } from "../ui";

type Kind = "purchase" | "sales";

interface KindConfig {
  title: string;
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
}

const CONFIG: Record<Kind, KindConfig> = {
  purchase: {
    title: "أوامر الشراء",
    path: "/purchase-orders",
    partyPath: "/suppliers",
    partyField: "supplier_id",
    partyLabel: "المورد",
    priceField: "unit_cost",
    priceLabel: "تكلفة الوحدة",
    newLabel: "+ أمر شراء جديد",
    commit: { path: "receive", label: "استلام البضاعة", confirmText: "تأكيد استلام البضاعة؟ ستزيد كميات المخزون ويُحدَّث سعر التكلفة." },
    doneStatus: "received",
    docPrefix: "purchase-order",
  },
  sales: {
    title: "أوامر البيع",
    path: "/sales-orders",
    partyPath: "/customers",
    partyField: "customer_id",
    partyLabel: "العميل",
    priceField: "unit_price",
    priceLabel: "سعر الوحدة",
    newLabel: "+ أمر بيع جديد",
    commit: { path: "confirm", label: "تأكيد البيع", confirmText: "تأكيد أمر البيع؟ ستُخصم الكميات من المخزون." },
    doneStatus: "confirmed",
    docPrefix: "invoice",
  },
};

export const PurchaseOrders = () => <OrdersScreen kind="purchase" />;
export const SalesOrders = () => <OrdersScreen kind="sales" />;

function partyId(o: Order, cfg: KindConfig): number | undefined {
  return o[cfg.partyField];
}

function OrdersScreen({ kind }: { kind: Kind }) {
  const cfg = CONFIG[kind];
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const [viewId, setViewId] = useState<number | null>(null);

  const orders = usePagedList<Order>(cfg.path, { status_filter: status });
  const parties = useFetch(() => api.get<Party[]>(`${cfg.partyPath}?limit=500`), `${kind}-parties`);
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?limit=500"), "wh");
  const products = useFetch(() => api.get<Product[]>("/products?limit=500"), "products-all");

  const view = viewId != null ? orders.data?.find((o) => o.id === viewId) ?? null : null;

  return (
    <>
      <PageHeader title={cfg.title}>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="الحالة">
          <option value="">كل الحالات</option>
          <option value="draft">مسودة</option>
          <option value={cfg.doneStatus}>{cfg.doneStatus === "received" ? "تم الاستلام" : "مؤكد"}</option>
          <option value="cancelled">ملغي</option>
        </select>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          {cfg.newLabel}
        </button>
      </PageHeader>

      <Alert>{orders.error || parties.error || warehouses.error || products.error}</Alert>

      <div className="card table-wrap">
        {orders.loading && !orders.data ? (
          <Loading />
        ) : orders.data && orders.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>رقم الأمر</th>
                <th>التاريخ</th>
                <th>{cfg.partyLabel}</th>
                <th>المخزن</th>
                <th>الحالة</th>
                <th className="num">الإجمالي</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {orders.data.map((o) => (
                <tr key={o.id}>
                  <td>#{o.id}</td>
                  <td>{dateTime(o.created_at)}</td>
                  <td>{nameOf(parties.data, partyId(o, cfg))}</td>
                  <td>{nameOf(warehouses.data, o.warehouse_id)}</td>
                  <td>
                    <StatusBadge status={o.status} />
                  </td>
                  <td className="num">{money(o.total_amount)}</td>
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
          <Empty>{status ? "لا نتائج مطابقة" : "لا توجد أوامر بعد."}</Empty>
        )}
        <Pager list={orders} />
      </div>

      {creating && (
        <OrderForm
          cfg={cfg}
          parties={(parties.data ?? []).filter((p) => p.is_active)}
          warehouses={(warehouses.data ?? []).filter((w) => w.is_active)}
          products={(products.data ?? []).filter((p) => p.is_active)}
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
          partyName={nameOf(parties.data, partyId(view, cfg))}
          warehouseName={nameOf(warehouses.data, view.warehouse_id)}
          products={products.data ?? []}
          onClose={() => setViewId(null)}
          onChanged={() => {
            orders.reload();
            products.reload(); // stock levels changed
          }}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------- new order
interface Line {
  key: number;
  product_id: string;
  quantity: string;
  price: string;
}

let lineKey = 1;
const newLine = (): Line => ({ key: lineKey++, product_id: "", quantity: "1", price: "" });

function OrderForm({
  cfg,
  parties,
  warehouses,
  products,
  onClose,
  onSaved,
}: {
  cfg: KindConfig;
  parties: Party[];
  warehouses: Warehouse[];
  products: Product[];
  onClose: () => void;
  onSaved: (id: number) => void;
}) {
  const [party, setParty] = useState("");
  const [warehouse, setWarehouse] = useState(warehouses.length === 1 ? String(warehouses[0].id) : "");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>([newLine()]);
  const { busy, error, run } = useAction();

  const byId = new Map(products.map((p) => [p.id, p]));
  const defaultPrice = (p: Product | undefined) => (p ? (cfg.priceField === "unit_cost" ? p.cost_price : p.sale_price) : "");

  const patch = (key: number, change: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...change } : l)));
  const pickProduct = (key: number, id: string) => patch(key, { product_id: id, price: id ? String(Number(defaultPrice(byId.get(Number(id))))) : "" });

  const lineTotal = (l: Line) => (Number(l.quantity) || 0) * (Number(l.price) || 0);
  const total = lines.reduce((s, l) => s + lineTotal(l), 0);
  const filled = lines.filter((l) => l.product_id);
  const valid = !!party && !!warehouse && filled.length > 0 && filled.every((l) => Number.isInteger(Number(l.quantity)) && Number(l.quantity) > 0 && Number(l.price) >= 0);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    void run(async () => {
      const created = await api.post<Order>(cfg.path, {
        [cfg.partyField]: Number(party),
        warehouse_id: Number(warehouse),
        notes: notes.trim() || null,
        items: filled.map((l) => ({ product_id: Number(l.product_id), quantity: Number(l.quantity), [cfg.priceField]: l.price })),
      });
      onSaved(created.id);
    });
  };

  return (
    <Modal title={cfg.newLabel.replace("+ ", "")} onClose={onClose} wide>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <div className="form-grid">
          <Field label={cfg.partyLabel}>
            <select value={party} onChange={(e) => setParty(e.target.value)} required autoFocus>
              <option value="">— اختر —</option>
              {parties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="المخزن">
            <select value={warehouse} onChange={(e) => setWarehouse(e.target.value)} required>
              <option value="">— اختر —</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
        </div>

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
              const p = byId.get(Number(l.product_id));
              return (
                <tr key={l.key}>
                  <td>
                    <select value={l.product_id} onChange={(e) => pickProduct(l.key, e.target.value)} aria-label="المنتج">
                      <option value="">— اختر منتجاً —</option>
                      {products.map((x) => (
                        <option key={x.id} value={x.id}>
                          {x.name} ({x.sku}) — المتاح {x.quantity}
                        </option>
                      ))}
                    </select>
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
                      <button type="button" className="icon-btn" onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))} aria-label="حذف السطر">
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

        <div className="total-row">
          <span>الإجمالي</span>
          <span>{money(total)}</span>
        </div>

        <Field label="ملاحظات">
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
          يُحفظ الأمر كمسودة ولا يتأثر المخزون حتى {cfg.commit.label}.
        </p>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy || !valid}>
            {busy ? "جارٍ الحفظ…" : "حفظ كمسودة"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            إلغاء
          </button>
        </div>
      </form>
    </Modal>
  );
}

// -------------------------------------------------------------- order detail
function OrderDetail({
  cfg,
  order,
  partyName,
  warehouseName,
  products,
  onClose,
  onChanged,
}: {
  cfg: KindConfig;
  order: Order;
  partyName: string;
  warehouseName: string;
  products: Product[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const { busy, error, run } = useAction();
  const isDraft = order.status === "draft";

  const transition = (path: string, confirmText: string) => {
    if (!confirm(confirmText)) return;
    void run(async () => {
      await api.post(`${cfg.path}/${order.id}/${path}`);
      onChanged();
    });
  };

  return (
    <Modal title={`${cfg.title.replace("أوامر", "أمر")} #${order.id}`} onClose={onClose} wide>
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
                  <td>{nameOf(products, it.product_id)}</td>
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

      <div className="form-actions" style={{ marginBottom: 4 }}>
        <button className="btn" disabled={busy} onClick={() => void run(() => api.download(`${cfg.path}/${order.id}/pdf`, `${cfg.docPrefix}-${order.id}.pdf`))}>
          ⬇ تنزيل PDF
        </button>
        <button className="btn" disabled={busy} onClick={() => void run(() => api.download(`${cfg.path}/${order.id}/xlsx`, `${cfg.docPrefix}-${order.id}.xlsx`))}>
          ⬇ تنزيل Excel
        </button>
      </div>

      {isDraft ? (
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy} onClick={() => transition(cfg.commit.path, cfg.commit.confirmText)}>
            {cfg.commit.label}
          </button>
          <button className="btn btn-danger" disabled={busy} onClick={() => transition("cancel", "إلغاء هذا الأمر؟ لا يمكن التراجع.")}>
            إلغاء الأمر
          </button>
        </div>
      ) : (
        <p className="muted" style={{ marginBottom: 0 }}>
          {order.status === "cancelled" ? "هذا الأمر ملغي." : "تم تنفيذ هذا الأمر وتحديث المخزون."}
        </p>
      )}
    </Modal>
  );
}
