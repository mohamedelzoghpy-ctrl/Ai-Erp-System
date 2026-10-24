import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { METHOD_LABEL, money, num } from "../format";
import { useAction, useFetch } from "../hooks";
import type { Party, PaymentMethod, Product, Warehouse } from "../types";
import { Alert, Field, Lookup, Modal, PageHeader } from "../ui";

interface CartLine {
  product: Product;
  quantity: number;
  price: string;
}

interface Receipt {
  order_id: number;
  customer_name: string;
  total: string;
  paid: string;
  balance_due: string;
}

const WAREHOUSE_KEY = "pos.warehouse";
function remembered(): string {
  try {
    return localStorage.getItem(WAREHOUSE_KEY) ?? "";
  } catch {
    return "";
  }
}

export default function Pos() {
  const { isManager } = useAuth();
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?is_active=true&limit=500"), "pos-wh");
  const [warehouse, setWarehouse] = useState(remembered());
  const [cart, setCart] = useState<CartLine[]>([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Product[]>([]);
  const [customer, setCustomer] = useState<Party | null>(null);
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [paidInput, setPaidInput] = useState("");
  const [tendered, setTendered] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const search = useAction();
  const sale = useAction();
  const dl = useAction();
  const box = useRef<HTMLInputElement>(null);

  // A single active warehouse is picked automatically.
  useEffect(() => {
    const list = warehouses.data;
    if (list && !list.some((w) => String(w.id) === warehouse)) setWarehouse(list.length === 1 ? String(list[0].id) : "");
  }, [warehouses.data, warehouse]);

  const total = cart.reduce((s, l) => s + l.quantity * (Number(l.price) || 0), 0);
  const paid = customer && paidInput !== "" ? Number(paidInput) : total;
  const change = !customer && tendered !== "" ? Number(tendered) - total : null;
  const overStock = cart.filter((l) => l.quantity > l.product.quantity);
  const canPay = cart.length > 0 && !!warehouse && paid >= 0 && paid <= total + 1e-9 && overStock.length === 0 && cart.every((l) => l.quantity > 0 && Number(l.price) >= 0);

  const add = (p: Product) => {
    setNotice(null);
    setCart((c) => {
      const i = c.findIndex((l) => l.product.id === p.id);
      if (i >= 0) return c.map((l, j) => (j === i ? { ...l, quantity: l.quantity + 1 } : l));
      return [...c, { product: p, quantity: 1, price: String(Number(p.sale_price)) }];
    });
    setQ("");
    setHits([]);
    box.current?.focus();
  };

  const find = (e: FormEvent) => {
    e.preventDefault();
    const term = q.trim();
    if (!term) return;
    void search.run(async () => {
      const r = await api.get<Product[]>(`/products?search=${encodeURIComponent(term)}&is_active=true&limit=10`);
      const exact = r.filter((p) => p.sku.toLowerCase() === term.toLowerCase());
      if (exact.length === 1 || r.length === 1) add(exact[0] ?? r[0]);
      else {
        setHits(r);
        setNotice(r.length === 0 ? "لا يوجد منتج مطابق" : null);
      }
    });
  };

  const pay = () => {
    void sale.run(async () => {
      const r = await api.post<Receipt>("/pos/checkout", {
        warehouse_id: Number(warehouse),
        customer_id: customer?.id ?? null,
        items: cart.map((l) => ({ product_id: l.product.id, quantity: l.quantity, ...(isManager ? { unit_price: l.price } : {}) })),
        amount_paid: customer ? String(paid) : undefined,
        method,
      });
      setReceipt(r);
    });
  };

  const reset = () => {
    setCart([]);
    setCustomer(null);
    setPaidInput("");
    setTendered("");
    setMethod("cash");
    setReceipt(null);
    setQ("");
    setHits([]);
    box.current?.focus();
  };

  return (
    <>
      <PageHeader title="نقطة البيع">
        <select
          value={warehouse}
          aria-label="المخزن"
          onChange={(e) => {
            setWarehouse(e.target.value);
            try {
              localStorage.setItem(WAREHOUSE_KEY, e.target.value);
            } catch {
              /* storage unavailable: choice just isn't remembered */
            }
          }}
        >
          <option value="">— اختر المخزن —</option>
          {warehouses.data?.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      </PageHeader>

      <Alert>{search.error || sale.error || warehouses.error}</Alert>
      {notice && <Alert kind="info">{notice}</Alert>}

      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="card card-pad">
          <form onSubmit={find} className="page-actions" style={{ marginBottom: 10 }}>
            <input
              ref={box}
              autoFocus
              style={{ flex: 1, minWidth: 180 }}
              placeholder="امسح الباركود أو اكتب الكود/الاسم ثم Enter"
              aria-label="بحث عن منتج"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <button className="btn btn-primary" disabled={search.busy}>
              إضافة
            </button>
          </form>
          {hits.length > 0 && (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {hits.map((p) => (
                <li key={p.id}>
                  <button type="button" className="btn" style={{ width: "100%", textAlign: "start", marginBottom: 4 }} onClick={() => add(p)}>
                    {p.name} ({p.sku}) — {money(p.sale_price)} — المتاح {num(p.quantity)}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <h3>السلة</h3>
          {cart.length === 0 ? (
            <p className="muted">السلة فارغة. أضف منتجات بالبحث أو الباركود.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>المنتج</th>
                    <th style={{ width: 90 }}>الكمية</th>
                    <th style={{ width: 110 }}>السعر</th>
                    <th className="num">الإجمالي</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {cart.map((l) => (
                    <tr key={l.product.id}>
                      <td>
                        {l.product.name}
                        {l.quantity > l.product.quantity && (
                          <span className="low" style={{ display: "block", fontSize: 12 }}>
                            المتاح {num(l.product.quantity)} فقط
                          </span>
                        )}
                      </td>
                      <td>
                        <input
                          type="number"
                          min="1"
                          step="1"
                          aria-label={`كمية ${l.product.name}`}
                          value={l.quantity}
                          onChange={(e) => setCart((c) => c.map((x) => (x === l ? { ...x, quantity: Math.max(0, Math.floor(Number(e.target.value) || 0)) } : x)))}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          aria-label={`سعر ${l.product.name}`}
                          value={l.price}
                          readOnly={!isManager}
                          title={isManager ? undefined : "تعديل السعر للمدير فقط"}
                          onChange={(e) => setCart((c) => c.map((x) => (x === l ? { ...x, price: e.target.value } : x)))}
                        />
                      </td>
                      <td className="num">{money(l.quantity * (Number(l.price) || 0))}</td>
                      <td>
                        <button type="button" className="icon-btn" aria-label={`حذف ${l.product.name}`} onClick={() => setCart((c) => c.filter((x) => x !== l))}>
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card card-pad">
          <div className="kpi" style={{ marginBottom: 12 }}>
            <div className="label">الإجمالي المستحق</div>
            <div className="value" aria-live="polite">
              {money(total)}
            </div>
          </div>
          <Field label="العميل" hint="اتركه فارغاً للبيع النقدي (عميل نقدي)، أو اختر عميلاً للبيع بالآجل/الدفع الجزئي">
            <Lookup<Party> path="/customers" params={{ is_active: true }} value={customer} onChange={(c) => { setCustomer(c); setPaidInput(""); }} label={(p) => p.name} placeholder="ابحث عن عميل…" />
          </Field>
          <div className="form-grid">
            <Field label="طريقة الدفع">
              <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}>
                {(Object.keys(METHOD_LABEL) as PaymentMethod[]).map((m) => (
                  <option key={m} value={m}>
                    {METHOD_LABEL[m]}
                  </option>
                ))}
              </select>
            </Field>
            {customer ? (
              <Field label="المبلغ المدفوع الآن" hint={`المتبقي على العميل: ${money(Math.max(total - paid, 0))}`}>
                <input dir="ltr" type="number" min="0" step="0.01" value={paidInput} placeholder={String(total)} onChange={(e) => setPaidInput(e.target.value)} />
              </Field>
            ) : (
              <Field label="المبلغ المستلم من العميل" hint={change !== null ? (change >= 0 ? `الباقي للعميل: ${money(change)}` : `ناقص ${money(-change)}`) : "اختياري، لحساب الباقي"}>
                <input dir="ltr" type="number" min="0" step="0.01" value={tendered} onChange={(e) => setTendered(e.target.value)} />
              </Field>
            )}
          </div>
          <button className="btn btn-primary" style={{ width: "100%", padding: 14, fontSize: 18 }} disabled={!canPay || sale.busy || (change !== null && change < 0)} onClick={pay}>
            {sale.busy ? "جارٍ الإتمام…" : `إتمام البيع — ${money(paid)}`}
          </button>
          {cart.length > 0 && (
            <button className="btn" style={{ width: "100%", marginTop: 8 }} onClick={reset}>
              إلغاء العملية
            </button>
          )}
        </div>
      </div>

      {receipt && (
        <Modal title={`تم البيع — فاتورة SO-${receipt.order_id}`} onClose={reset}>
          <Alert>{dl.error}</Alert>
          <p>
            العميل: <b>{receipt.customer_name}</b>
            <br />
            الإجمالي: <b>{money(receipt.total)}</b> · المدفوع: <b>{money(receipt.paid)}</b>
            {Number(receipt.balance_due) > 0 && (
              <>
                {" "}
                · المتبقي على العميل: <b>{money(receipt.balance_due)}</b>
              </>
            )}
            {change !== null && change >= 0 && tendered !== "" && (
              <>
                <br />
                الباقي للعميل: <b>{money(change)}</b>
              </>
            )}
          </p>
          <div className="form-actions">
            <button className="btn btn-primary" autoFocus onClick={reset}>
              عملية جديدة
            </button>
            <button className="btn" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/sales-orders/${receipt.order_id}/pdf`, `invoice-SO-${receipt.order_id}.pdf`))}>
              ⬇ الفاتورة PDF
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
