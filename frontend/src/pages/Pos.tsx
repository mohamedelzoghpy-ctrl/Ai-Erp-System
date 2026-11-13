import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { dateTime, discountedUnitPrice, METHOD_LABEL, methodLabel, money, num } from "../format";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Order, Party, PaymentMethod, Product, SalesRep, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, Lookup, Modal, PageHeader, Pager, PaymentBadge } from "../ui";
import { printThermal, type ThermalLine } from "../escpos";

interface CartLine {
  product: Product;
  quantity: number;
  price: string;
  discountPct: string; // خصم السطر بنسبة مئوية (0-100) — السعر المرسل هو الفعلي
}

type DocumentType = "invoice" | "quotation";
type DiscountMode = "amount" | "percent";

interface Receipt {
  order_id: number;
  customer_name: string;
  total: string;
  paid: string;
  balance_due: string;
  document_type: DocumentType;
  created_at?: string;
  discount_amount?: string;
}

const WAREHOUSE_KEY = "pos.warehouse";
function remembered(): string {
  try {
    return localStorage.getItem(WAREHOUSE_KEY) ?? "";
  } catch {
    return "";
  }
}

function quantityInCart(cart: CartLine[], productId: number): number {
  return cart.find((l) => l.product.id === productId)?.quantity ?? 0;
}

export default function Pos() {
  const { isManager, can } = useAuth();
  const { t } = useI18n();
  const warehouses = useFetch(
    () => api.get<Warehouse[]>("/warehouses?is_active=true&limit=500").then((ws) => ws.filter((w) => !w.is_transit)),
    "pos-wh",
  );
  const safes = useFetch(() => api.get<{ id: number; name: string; is_active: boolean }[]>("/safes"), "pos-safes");
  const [warehouse, setWarehouse] = useState(remembered());
  const [screen, setScreen] = useState<"history" | "new">("history");
  const [documentType, setDocumentType] = useState<DocumentType>("invoice");
  const [safeId, setSafeId] = useState("");
  const [bankId, setBankId] = useState("");
  const invoices = usePagedList<Order>("/pos/invoices", {});
  const [cart, setCart] = useState<CartLine[]>([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Product[]>([]);
  const [customer, setCustomer] = useState<Party | null>(null);
  const reps = useFetch(() => api.get<SalesRep[]>("/reps?active_only=true"), "pos-reps");
  const [repId, setRepId] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [paidInput, setPaidInput] = useState("");
  const [tendered, setTendered] = useState("");
  const [quotationReceived, setQuotationReceived] = useState("");
  const [discountMode, setDiscountMode] = useState<DiscountMode>("amount");
  const [taxEnabled, setTaxEnabled] = useState(true);
  const banks = useFetch(() => api.get<{ id: number; name: string; is_active: boolean }[]>("/banks?limit=200"), "pos-banks");
  const [splitMode, setSplitMode] = useState(false);
  const [splitCash, setSplitCash] = useState("");
  const HELD_KEY = "pos-held-carts";
  const heldCarts: { id: string; savedAt: string; cart: CartLine[]; customer: Party | null; notes: string }[] =
    JSON.parse(localStorage.getItem(HELD_KEY) || "[]");
  const holdCart = () => {
    if (!cart.length) return;
    const entry = { id: Math.random().toString(36).slice(2, 8), savedAt: new Date().toISOString(), cart, customer, notes: "" };
    localStorage.setItem(HELD_KEY, JSON.stringify([entry, ...heldCarts].slice(0, 10)));
    setCart([]);
    setCustomer(null);
    alert(`عُلّقت الفاتورة (${entry.id}) — استرجعها من قائمة «معلّقة»`);
  };
  const restoreHeld = (id: string) => {
    const entry = heldCarts.find((h) => h.id === id);
    if (!entry) return;
    if (cart.length && !confirm("السلة الحالية ستُستبدل بالمعلّقة. متابعة؟")) return;
    setCart(entry.cart);
    setCustomer(entry.customer);
    localStorage.setItem(HELD_KEY, JSON.stringify(heldCarts.filter((h) => h.id !== id)));
  };
  const [discountValue, setDiscountValue] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const search = useAction();
  const sale = useAction();
  const dl = useAction();
  const thermal = useAction();
  const box = useRef<HTMLInputElement>(null);

  // ==== شبكة المنتجات اللمسية: أصناف المخزن المختار — بحث فوري محلي + ترقيم ====
  const [grid, setGrid] = useState<Product[]>([]);
  const [gridFilter, setGridFilter] = useState("");
  const [gridPage, setGridPage] = useState(0);
  const GRID_PAGE_SIZE = 24;
  useEffect(() => {
    if (!warehouse) { setGrid([]); return; }
    let alive = true;
    api.get<Product[]>(`/products?is_active=true&limit=500&stock_warehouse_id=${warehouse}`)
      .then((r) => { if (alive) setGrid(r); })
      .catch(() => { if (alive) setGrid([]); });
    return () => { alive = false; };
  }, [warehouse]);
  const gridFiltered = grid.filter((p) => {
    const f = gridFilter.trim().toLowerCase();
    return !f || p.name.toLowerCase().includes(f) || p.sku.toLowerCase().includes(f);
  });
  const gridPages = Math.max(1, Math.ceil(gridFiltered.length / GRID_PAGE_SIZE));
  const gridPageSafe = Math.min(gridPage, gridPages - 1);
  const gridSlice = gridFiltered.slice(gridPageSafe * GRID_PAGE_SIZE, (gridPageSafe + 1) * GRID_PAGE_SIZE);

  // A single active warehouse is picked automatically.
  useEffect(() => {
    const list = warehouses.data;
    if (list && !list.some((w) => String(w.id) === warehouse)) setWarehouse(list.length === 1 ? String(list[0].id) : "");
  }, [warehouses.data, warehouse]);

  // ==== باركود مستمر + اختصارات لوحة مفاتيح (F2 بحث · F4 حفظ · F8 تفريغ) ====
  const submitRef = useRef<() => void>(() => {});
  const canPayRef = useRef(false);
  const scanBuf = useRef({ text: "", last: 0 });
  useEffect(() => {
    if (screen !== "new") return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "F2") {
        e.preventDefault();
        box.current?.focus();
        return;
      }
      if (e.key === "F4") {
        e.preventDefault();
        if (canPayRef.current) submitRef.current();
        return;
      }
      if (e.key === "F8") {
        e.preventDefault();
        setCart([]);
        return;
      }
      if (e.key.length === 1 && /[a-zA-Z0-9\-_.]/.test(e.key)) {
        const now = Date.now();
        const buf = scanBuf.current;
        // فجوة أطول من 120ms = كتابة يدوية — نصفّر المخزن؛ السكانير يكتب بأقل من ذلك
        if (now - buf.last > 120) buf.text = "";
        buf.last = now;
        buf.text += e.key;
      } else if (e.key === "Enter") {
        const code = scanBuf.current.text.trim();
        scanBuf.current.text = "";
        // بصمة الباركود: ≥6 محارف كُتبت بسرعة — تطابق SKU تام → إضافة مباشرة
        if (code.length >= 6) {
          void search.run(async () => {
            const r = await api.get<Product[]>(`/products?search=${encodeURIComponent(code)}&is_active=true&limit=5${warehouse ? `&stock_warehouse_id=${warehouse}` : ""}`);
            const exact = r.find((p) => p.sku.toLowerCase() === code.toLowerCase());
            if (exact) add(exact);
          });
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // add/search تُغلق على الحالة الحية عبر refs المذكورة أعلاه — المستمع يُسجل مرة لكل شاشة
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screen, warehouse]);

  /** What is on the shelf in the selected warehouse (the API only sends it when asked for one warehouse). */
  const avail = (p: Product) => p.warehouse_quantity ?? p.quantity;

  /** سعر الوحدة الفعلي بعد خصم السطر — كل الحسابات والإرسال عليه */
  const unitEff = (l: CartLine) => discountedUnitPrice(l.price, l.discountPct);

  const total = cart.reduce((s, l) => s + l.quantity * unitEff(l), 0);
  const totalCents = cart.reduce((s, l) => s + l.quantity * Math.round(unitEff(l) * 100), 0);
  const discountInput = discountValue === "" ? 0 : Number(discountValue);
  const discountCents = discountMode === "percent"
    ? Math.round(totalCents * discountInput / 100)
    : Math.round(discountInput * 100);
  const discountAmount = discountCents / 100;
  const netDue = Math.max(0, totalCents - discountCents) / 100;
  const netCents = Math.round(netDue * 100);
  const vatCents = taxEnabled ? Math.round(netCents * 0.14) : 0;
  const vatAmount = vatCents / 100;
  const grandDue = (netCents + vatCents) / 100;
  const validDiscount = Number.isFinite(discountInput) && discountInput >= 0 && (discountMode === "percent" ? discountInput <= 100 : discountCents <= totalCents);
  const splitCashAmount = splitMode && splitCash !== "" ? Number(splitCash) : 0;
  const splitBankAmount = splitMode ? Math.max(0, grandDue - splitCashAmount) : 0;
  const paid = splitMode
    ? splitCashAmount + splitBankAmount
    : customer && paidInput !== "" ? Number(paidInput) : grandDue;
  const change = !customer && tendered !== "" ? Number(tendered) - grandDue : null;
  const overStock = cart.filter((l) => l.quantity > avail(l.product));
  // صلاحية تعديل سعر البيع: الحقل متاح للمدير أو حامل الصلاحية، والتعديل بالزيادة فقط — ليس أقل من سعر البيع المعتمد.
  const canEditPrice = isManager || can("sales.order.price_increase");
  const underPriced = cart.filter((l) => Number(l.price) < Number(l.product.sale_price));
  const validPcts = cart.every((l) => {
    const p = Number(l.discountPct ?? 0);
    return Number.isFinite(p) && p >= 0 && p <= 100;
  });
  const validLines = cart.length > 0 && validPcts && cart.every((l) => l.quantity > 0 && Number(l.price) >= 0);
  const receivedForQuotation = quotationReceived === "" ? 0 : Number(quotationReceived);
  const validQuotationReceived = Number.isFinite(receivedForQuotation) && receivedForQuotation >= 0 && receivedForQuotation <= grandDue + 1e-9;
  const canPay = !!warehouse && validLines && validDiscount && overStock.length === 0 && underPriced.length === 0 && (documentType === "quotation" ? validQuotationReceived : paid >= 0 && paid <= grandDue + 1e-9);
  canPayRef.current = canPay;
  let undistributedDiscountCents = discountCents;
  const discountedItems = cart.flatMap((line) => {
    const unitCents = Math.round(unitEff(line) * 100); // السعر الفعلي بعد خصم السطر
    const lineDiscountCents = Math.min(undistributedDiscountCents, unitCents * line.quantity);
    undistributedDiscountCents -= lineDiscountCents;
    const fullyDiscountedUnits = unitCents > 0 ? Math.min(line.quantity, Math.floor(lineDiscountCents / unitCents)) : 0;
    const partialDiscount = unitCents > 0 && fullyDiscountedUnits < line.quantity ? lineDiscountCents - fullyDiscountedUnits * unitCents : 0;
    const unitsAtFullPrice = line.quantity - fullyDiscountedUnits - (partialDiscount > 0 ? 1 : 0);
    const result = [];
    if (fullyDiscountedUnits) result.push({ product_id: line.product.id, quantity: fullyDiscountedUnits, unit_price: "0.00" });
    if (partialDiscount) result.push({ product_id: line.product.id, quantity: 1, unit_price: ((unitCents - partialDiscount) / 100).toFixed(2) });
    if (unitsAtFullPrice) result.push({ product_id: line.product.id, quantity: unitsAtFullPrice, unit_price: (unitCents / 100).toFixed(2) });
    return result;
  });

  const add = (p: Product) => {
    setNotice(null);
    setCart((c) => {
      const i = c.findIndex((l) => l.product.id === p.id);
      if (i >= 0) return c.map((l, j) => (j === i ? { ...l, quantity: l.quantity + 1 } : l));
      return [...c, { product: p, quantity: 1, price: String(Number(p.sale_price)), discountPct: "0" }];
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
      const r = await api.get<Product[]>(`/products?search=${encodeURIComponent(term)}&is_active=true&limit=10${warehouse ? `&stock_warehouse_id=${warehouse}` : ""}`);
      const exact = r.filter((p) => p.sku.toLowerCase() === term.toLowerCase());
      if (exact.length === 1 || r.length === 1) add(exact[0] ?? r[0]);
      else {
        setHits(r);
        setNotice(r.length === 0 ? t("pos.noProduct") : null);
      }
    });
  };

  const submitDocument = () => {
    const isQuotation = documentType === "quotation";
    if (isQuotation && !customer) return;
    void sale.run(async () => {
      const safeName = safes.data?.find((s) => String(s.id) === safeId)?.name ?? safeId;
      const repName = (reps.data ?? []).find((r) => String(r.id) === repId)?.name ?? repId;
      const metadata = [
        ...(isQuotation ? [] : [`مندوب البيع: ${repName || "بدون مندوب"}`]),
        `الخزينة: ${safeName || "—"}`,
        `طريقة الدفع: ${METHOD_LABEL[method]}`,
        ...(isQuotation ? [`المبلغ المستلم: ${receivedForQuotation}`] : []),
        ...(discountCents ? [`الخصم: ${money(discountAmount)}${discountMode === "percent" ? ` (${discountInput}%)` : ""}`] : []),
      ].join(" · ");
      const received = isQuotation ? receivedForQuotation : splitMode ? grandDue : customer ? paid : undefined;
      const splitPayments = splitMode && !isQuotation ? [
        { method: "cash" as const, amount: String(Math.min(splitCashAmount, grandDue)), safe_id: safeId === "" ? null : Number(safeId) },
        { method: "bank" as const, amount: String(splitBankAmount), bank_id: bankId === "" ? null : Number(bankId) },
      ].filter((l) => Number(l.amount) > 0) : undefined;
      const r = await api.post<Receipt>("/pos/checkout", {
        warehouse_id: Number(warehouse),
        customer_id: customer?.id ?? null,
        rep_id: repId === "" ? null : Number(repId),
        items: discountedItems,
        amount_paid: received === undefined ? undefined : String(received),
        tax_rate: taxEnabled ? "14" : "0",
        method,
        ...(splitPayments ? { payments: splitPayments } : {}),
        notes: metadata,
      });
      setReceipt({ ...r, document_type: documentType, created_at: new Date().toISOString(), discount_amount: String(discountAmount) });
      invoices.reload();
    });
  };
  submitRef.current = submitDocument;

  const reset = () => {
    setCart([]);
    setCustomer(null);
    setPaidInput("");
    setTendered("");
    setQuotationReceived("");
    setDiscountMode("amount");
    setDiscountValue("");
    setMethod("cash");
    setReceipt(null);
    setDocumentType("invoice");
    setSafeId("");
    setQ("");
    setHits([]);
    setScreen("history");
  };

  const startNewInvoice = () => {
    reset();
    setScreen("new");
  };

  const invoiceFile = (order: Order) => {
    return (
      <tr key={order.id}>
        <td dir="ltr">SO-{order.id}</td>
        <td>{dateTime(order.created_at)}</td>
        <td>{order.party_name || "—"}</td>
        <td>{warehouses.data?.find((item) => item.id === order.warehouse_id)?.name || `#${order.warehouse_id}`}</td>
        <td>{order.created_by_name || "—"}</td>
        <td className="num">{money(order.total_amount)}</td>
        <td><PaymentBadge status={order.payment_status} /></td>
        <td className="actions">
          <button className="btn btn-sm" onClick={() => void dl.run(() => api.download(`/sales-orders/${order.id}/pdf`, `invoice-SO-${order.id}.pdf`))}>PDF</button>
          <button className="btn btn-sm" onClick={() => void dl.run(() => api.download(`/sales-orders/${order.id}/receipt`, `receipt-SO-${order.id}.pdf`))}>{t("إيصال")}</button>
        </td>
      </tr>
    );
  };

  return (
    <>
      {screen === "history" ? (
        <PageHeader title={t("فواتير البيع")}>
          <button className="btn btn-primary" onClick={startNewInvoice}>{t("+ إضافة فاتورة بيع جديدة")}</button>
        </PageHeader>
      ) : (
        <div className="pos-new-actions">
          <button className="btn" onClick={() => { reset(); setScreen("history"); }}>{t("العودة إلى الفواتير")}</button>
        </div>
      )}

      <Alert>{search.error || sale.error || warehouses.error || safes.error || (screen === "history" ? invoices.error : null) || dl.error}</Alert>
      {screen === "history" ? (
        <>
          <div className="card table-wrap">
            {invoices.loading ? <Loading /> : invoices.data?.length ? (
              <table>
                <thead><tr><th>{t("رقم الفاتورة")}</th><th>{t("التاريخ")}</th><th>{t("العميل")}</th><th>{t("المخزن")}</th><th>{t("الكاشير")}</th><th className="num">{t("الإجمالي")}</th><th>{t("السداد")}</th><th>{t("المستندات")}</th></tr></thead>
                <tbody>{invoices.data.map(invoiceFile)}</tbody>
              </table>
            ) : <Empty>{t("لا توجد فواتير بيع سابقة.")}</Empty>}
            <Pager list={invoices} />
          </div>
          {dl.error && <Alert>{dl.error}</Alert>}
        </>
      ) : (
      <>
      {notice && <Alert kind="info">{notice}</Alert>}

      <section className="quotation-editor" aria-label={documentType === "quotation" ? t("بيانات بيان الأسعار") : t("بيانات الفاتورة")}>
        <header className="quotation-editor-head">
          <h2>{documentType === "quotation" ? t("بيان أسعار جديد") : t("فاتورة بيع جديدة")}</h2>
          <div>{t("رقم البيان: ")}<strong>{receipt ? `SO-${receipt.order_id}` : t("يُولَّد عند الحفظ")}</strong></div>
          <div>{t("التاريخ: ")}<strong>{receipt?.created_at ? dateTime(receipt.created_at) : dateTime(new Date().toISOString())}</strong></div>
        </header>
        <div className="page-actions" role="group" aria-label={t("نوع البيان")} style={{ justifyContent: "center", marginBottom: 14 }}>
          <button type="button" className={`btn ${documentType === "quotation" ? "btn-primary" : ""}`} aria-pressed={documentType === "quotation"} onClick={() => setDocumentType("quotation")}>{t("بيان أسعار")}</button>
          <button type="button" className={`btn ${documentType === "invoice" ? "btn-primary" : ""}`} aria-pressed={documentType === "invoice"} onClick={() => setDocumentType("invoice")}>{t("فاتورة")}</button>
        </div>
        <div className={`quotation-editor-meta pos-document-meta pos-document-meta-${documentType}`}>
          <div className="quotation-meta-column pos-document-customer-column">
            <Field label={t("اسم العميل")}>
              <Lookup<Party> path="/customers" params={{ is_active: true }} value={customer} onChange={(c) => { setCustomer(c); setPaidInput(""); }} label={(p) => p.name} placeholder={t("ابحث عن العميل…")} />
            </Field>
            <Field label={t("رقم الهاتف")}>
              <a className={`btn customer-phone-button customer-phone-${documentType}`} href={customer?.phone ? `tel:${customer.phone}` : undefined} aria-label={`${t("رقم هاتف العميل في ")}${documentType === "quotation" ? t("بيان الأسعار") : t("الفاتورة")}`} aria-disabled={!customer?.phone} onClick={(event) => { if (!customer?.phone) event.preventDefault(); }}>
                {customer?.phone || t("اختر العميل لعرض رقم الهاتف")}
              </a>
            </Field>
            <Field label={t("اسم المخزن")}>
              <select value={warehouse} aria-label={t("اسم المخزن")} onChange={(e) => {
                setWarehouse(e.target.value);
                setCart([]);
                setHits([]);
                try { localStorage.setItem(WAREHOUSE_KEY, e.target.value); } catch { /* storage unavailable */ }
              }}>
                <option value="">{t("— اختر المخزن —")}</option>
                {warehouses.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </Field>
          </div>
          <div className="quotation-meta-column">
            <Field label={t("مندوب المبيعات")}>
              <select aria-label={t("مندوب المبيعات")} value={repId} onChange={(e) => setRepId(e.target.value)}>
                <option value="">{t("— بدون مندوب —")}</option>
                {(reps.data ?? []).filter((r) => r.is_active).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </Field>
            <Field label={t("اسم الخزينة")}>
              <select aria-label={t("اسم الخزينة")} value={safeId} onChange={(e) => setSafeId(e.target.value)}>
                <option value="">{t("— اختر الخزينة —")}</option>
                {(safes.data ?? []).filter((s) => s.is_active).map((safe) => <option key={safe.id} value={safe.id}>{safe.name}</option>)}
              </select>
            </Field>
            <Field label={t("pos.paymentMethod")}>
              <select aria-label={t("pos.paymentMethod")} value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}>
                {(Object.keys(METHOD_LABEL) as PaymentMethod[]).map((m: PaymentMethod) => <option key={m} value={m}>{methodLabel(m)}</option>)}
              </select>
            </Field>
          </div>
        </div>
      </section>

      <div className="pos-sale-layout">
        <div className="card card-pad pos-items-card">
          <form onSubmit={find} className="page-actions" style={{ marginBottom: 10 }}>
            <input
              ref={box}
              autoFocus
              style={{ flex: 1, minWidth: 180 }}
              placeholder={t("امسح الباركود أو اكتب الكود/الاسم ثم Enter — F2 للتركيز")}
              aria-label={t("بحث عن منتج")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <button className="btn btn-primary" disabled={search.busy}>
              {t("إضافة")}
            </button>
          </form>
          {hits.length > 0 && (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {hits.map((p) => (
                <li key={p.id}>
                  <button type="button" className="btn" style={{ width: "100%", textAlign: "start", marginBottom: 4 }} onClick={() => add(p)}>
                    {p.name} ({p.sku}) — {money(p.sale_price)} — {t("المتاح ")}{num(avail(p))}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <h3>{t("السلة")}</h3>
          {cart.length === 0 ? (
            <p className="muted">{t("السلة فارغة. أضف منتجات بالبحث أو الباركود.")}</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("المنتج")}</th>
                    <th style={{ width: 90 }}>{t("الكمية")}</th>
                    <th style={{ width: 110 }}>{t("السعر")}</th>
                    <th style={{ width: 72 }} title={t("خصم السطر بنسبة مئوية — يُرسل السعر الفعلي للفاتورة")}>{t("خصم %")}</th>
                    <th className="num">{t("الإجمالي")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {cart.map((l) => {
                    const eff = unitEff(l);
                    const pct = Number(l.discountPct ?? 0) || 0;
                    return (
                    <tr key={l.product.id}>
                      <td>
                        {l.product.name}
                        {l.quantity > avail(l.product) && (
                          <span className="low" style={{ display: "block", fontSize: 12 }}>
                            {t("المتاح ")}{num(avail(l.product))}{t(" فقط")}
                          </span>
                        )}
                      </td>
                      <td>
                        <input
                          type="number"
                          min="1"
                          step="1"
                          aria-label={`${t("كمية ")}${l.product.name}`}
                          value={l.quantity}
                          onChange={(e) => setCart((c) => c.map((x) => (x === l ? { ...x, quantity: Math.max(0, Math.floor(Number(e.target.value) || 0)) } : x)))}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          aria-label={`${t("سعر ")}${l.product.name}`}
                          value={l.price}
                          readOnly={!canEditPrice}
                          title={canEditPrice ? t("تعديل سعر البيع بالزيادة فقط") : t("السعر يحدده المدير فقط")}
                          onChange={(e) => setCart((c) => c.map((x) => (x === l ? { ...x, price: e.target.value } : x)))}
                        />
                        {Number(l.price) < Number(l.product.sale_price) && (
                          <span className="low" style={{ display: "block", fontSize: 12 }}>
                            {t("تعديل سعر البيع بالزيادة فقط")}
                          </span>
                        )}
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          step="1"
                          style={{ width: 60 }}
                          aria-label={`${t("خصم ")}${l.product.name}`}
                          value={l.discountPct ?? "0"}
                          onChange={(e) => setCart((c) => c.map((x) => (x === l ? { ...x, discountPct: e.target.value } : x)))}
                        />
                        {pct > 0 && (
                          <span className="muted" style={{ display: "block", fontSize: 11 }}>
                            {t("بعد الخصم: ")}{money(eff)}
                          </span>
                        )}
                      </td>
                      <td className="num" style={pct > 0 ? { fontWeight: 700 } : undefined}>{money(l.quantity * eff)}</td>
                      <td>
                        <button type="button" className="icon-btn" aria-label={`delete ${l.product.name}`} onClick={() => setCart((c) => c.filter((x) => x !== l))}>
                          ✕
                        </button>
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ==== شبكة المنتجات اللمسية: لمسة = إضافة للسلة ==== */}
        <div className="card card-pad pos-grid-card">
          <div className="page-actions" style={{ marginBottom: 8 }}>
            <input
              style={{ flex: 1, minWidth: 160 }}
              placeholder={t("تصفية الشبكة (اسم/كود)…")}
              aria-label={t("تصفية شبكة المنتجات")}
              value={gridFilter}
              onChange={(e) => { setGridFilter(e.target.value); setGridPage(0); }}
            />
            <span className="muted" style={{ fontSize: 12 }}>{num(gridFiltered.length)} {t("صنف")}</span>
          </div>
          {grid.length === 0 ? (
            <p className="muted">{t("اختر المخزن لعرض أصنافه هنا — واللمس يضيف للسلة")}</p>
          ) : gridSlice.length === 0 ? (
            <p className="muted">{t("لا نتائج في هذه الصفحة")}</p>
          ) : (
            <>
              <div className="pos-grid">
                {gridSlice.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className={`pos-tile ${quantityInCart(cart, p.id) > 0 ? "pos-tile-in-cart" : ""}`}
                    onClick={() => add(p)}
                    title={`${p.name} — ${money(p.sale_price)}`}
                  >
                    <span className="pos-tile-name">{p.name}</span>
                    <span className="pos-tile-price">{money(p.sale_price)}</span>
                    <span className={`pos-tile-stock ${avail(p) <= 0 ? "low" : ""}`}>{t("المتاح ")}{num(avail(p))}</span>
                  </button>
                ))}
              </div>
              {gridPages > 1 && (
                <div className="page-actions" style={{ justifyContent: "center", marginTop: 8 }}>
                  <button type="button" className="btn btn-sm" disabled={gridPageSafe === 0} onClick={() => setGridPage(gridPageSafe - 1)}>‹ {t("السابق")}</button>
                  <span className="muted" style={{ fontSize: 12 }}>{gridPageSafe + 1} / {gridPages}</span>
                  <button type="button" className="btn btn-sm" disabled={gridPageSafe >= gridPages - 1} onClick={() => setGridPage(gridPageSafe + 1)}>{t("التالي")} ›</button>
                </div>
              )}
            </>
          )}
        </div>

      </div>

      <section className={`card card-pad pos-summary-card pos-summary-${documentType}`} aria-label={documentType === "quotation" ? t("إجمالي وخصم بيان الأسعار") : t("إجمالي وخصم الفاتورة")}>
        <div className="pos-summary-values">
          <div className="pos-summary-total">
            <span className="label">{t("الإجمالي المستحق")}</span>
            <strong>{money(total)}</strong>
          </div>
          <div className="pos-summary-total">
            <span className="label">{t("الإجمالي بعد الخصم")}</span>
            <strong>{money(netDue)}</strong>
          </div>
          <div className="pos-summary-total">
            <span className="label">{t("ضريبة القيمة المضافة (14%)")}</span>
            <strong>{money(vatAmount)}</strong>
          </div>
          <div className="pos-summary-total pos-summary-net">
            <span className="label">{t("الإجمالي المستحق شامل الضريبة")}</span>
            <strong>{money(grandDue)}</strong>
          </div>
        </div>
        <div className="pos-summary-fields">
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <button type="button" className="btn btn-sm" onClick={holdCart} disabled={!cart.length}>⏸️ تعليق</button>
            {heldCarts.length > 0 && heldCarts.map((h) => (
              <button key={h.id} type="button" className="btn btn-sm btn-primary" onClick={() => restoreHeld(h.id)}
                title={`${h.customer?.name || "بدون عميل"} · ${new Date(h.savedAt).toLocaleTimeString()} · ${h.cart.length} صنف`}>
                ↩️ استرجاع {h.id}
              </button>
            ))}
          </div>
          <Field label={t("ضريبة القيمة المضافة")}>
            <select aria-label={t("تطبيق ضريبة القيمة المضافة")} value={taxEnabled ? "with-tax" : "without-tax"} onChange={(e) => setTaxEnabled(e.target.value === "with-tax")}>
              <option value="with-tax">{t("بالضريبة (14%)")}</option>
              <option value="without-tax">{t("بدون ضريبة")}</option>
            </select>
          </Field>
          <Field label={t("الدفع")} hint={t("مقسّم: نقدًا جزء والباقي من البنك في نفس الفاتورة")}>
            <select value={splitMode ? "split" : "single"} onChange={(e) => setSplitMode(e.target.value === "split")}>
              <option value="single">{t("وسيلة واحدة")}</option>
              <option value="split">{t("مقسّم (نقدًا + بنك)")}</option>
            </select>
          </Field>
          {splitMode && (
            <>
              <Field label={t("النقدي المستلم")} hint={`${t("البنك يستلم: ")}${money(splitBankAmount)}`}>
                <input dir="ltr" type="number" min="0" step="0.01" max={grandDue} value={splitCash} placeholder="0.00" onChange={(e) => setSplitCash(e.target.value)} />
              </Field>
              <Field label={t("بنك الجزء الثاني")}>
                <select value={bankId} onChange={(e) => setBankId(e.target.value)}>
                  <option value="">—</option>
                  {(banks.data ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              </Field>
            </>
          )}
          <Field label={t("الخصم")}>
            <div className="pos-discount-inputs">
              <select aria-label={t("نوع الخصم")} value={discountMode} onChange={(e) => setDiscountMode(e.target.value as DiscountMode)}>
                <option value="amount">{t("مبلغ")}</option>
                <option value="percent">{t("نسبة مئوية")}</option>
              </select>
              <input dir="ltr" type="number" min="0" max={discountMode === "percent" ? 100 : total} step="0.01" value={discountValue} onChange={(e) => setDiscountValue(e.target.value)} aria-label={discountMode === "percent" ? t("نسبة الخصم المئوية") : t("مبلغ الخصم")} placeholder={discountMode === "percent" ? "0%" : "0.00"} />
            </div>
            {discountCents > 0 && <span className="field-hint">{t("قيمة الخصم: ")}{money(discountAmount)}</span>}
            {!validDiscount && <span className="field-hint low">{t("الخصم لا يمكن أن يتجاوز الإجمالي")}{discountMode === "percent" ? t(" أو 100%") : ""}{t(".")}</span>}
          </Field>
          {documentType === "quotation" ? <Field label={t("المبلغ المستلم من العميل")} hint={t("سيُسجّل ضمن عملية البيع عند الحفظ")}>
            <input dir="ltr" type="number" min="0" max={grandDue} step="0.01" value={quotationReceived} onChange={(e) => setQuotationReceived(e.target.value)} aria-label={t("المبلغ المستلم من العميل")} />
          </Field> : <Field label={customer ? t("pos.amountPaid") : t("pos.amountReceived")} hint={customer ? `${t("pos.balanceDue")}: ${money(Math.max(grandDue - paid, 0))}` : change !== null ? (change >= 0 ? `${t("pos.change")}: ${money(change)}` : `${t("pos.short")} ${money(-change)}`) : t("اختياري، لحساب الباقي")}>
            <input dir="ltr" type="number" min="0" max={customer ? netDue : undefined} step="0.01" value={customer ? paidInput : tendered} placeholder={customer ? String(grandDue) : undefined} onChange={(e) => customer ? setPaidInput(e.target.value) : setTendered(e.target.value)} />
          </Field>}

          {/* ==== numpad لمسي: يعدّل حقل المبلغ حسب الحالة + فئات سريعة ==== */}
          {documentType === "invoice" && (
            <div className="pos-numpad" role="group" aria-label={t("لوحة الأرقام اللمسية")}>
              {["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"].map((k) => (
                <button
                  key={k}
                  type="button"
                  className="pos-numpad-key"
                  onClick={() => {
                    const target = customer ? paidInput : tendered;
                    const setTarget = customer ? setPaidInput : setTendered;
                    if (k === "⌫") setTarget(target.slice(0, -1));
                    else if (k === "." && target.includes(".")) return;
                    else setTarget(target + k);
                  }}
                >
                  {k}
                </button>
              ))}
              <button type="button" className="pos-numpad-key pos-numpad-clear" onClick={() => (customer ? setPaidInput("") : setTendered(""))}>{t("مسح")}</button>
              <button type="button" className="pos-numpad-key pos-numpad-exact" onClick={() => (customer ? setPaidInput(netDue.toFixed(2)) : setTendered(grandDue.toFixed(2)))}>{t("المطلوب")}</button>
              {[50, 100, 200, 500].map((v) => (
                <button key={v} type="button" className="pos-numpad-key pos-numpad-cash" onClick={() => { const cur = customer ? paidInput : tendered; (customer ? setPaidInput : setTendered)(String((Number(cur) || 0) + v)); }}>{v}</button>
              ))}
            </div>
          )}
        </div>
        <div className={`pos-summary-actions pos-summary-actions-${documentType}`}>
          <button className="btn btn-primary pos-summary-primary" disabled={!canPay || (documentType === "quotation" && (!customer || !safeId)) || sale.busy || (documentType === "invoice" && change !== null && change < 0)} onClick={submitDocument}>
            {sale.busy ? t("جارٍ الحفظ…") : documentType === "quotation" ? t("حفظ وطباعة بيان الأسعار") : t("حفظ وطباعة الفاتورة")}
          </button>
          {cart.length > 0 && <button className="btn" onClick={reset}>{t("pos.cancel")}</button>}
        </div>
      </section>
      </>
      )}

      {receipt && (
        <Modal title={`${receipt.document_type === "quotation" ? t("بيان أسعار") : t("pos.receiptTitle")} SO-${receipt.order_id}`} onClose={reset}>
          <Alert>{dl.error}</Alert>
          {receipt.document_type === "quotation" && <p className="muted">{t("تم اعتماد بيان الأسعار كعملية بيع وتحديث المخزون وتسجيل المبلغ المستلم.")}</p>}
          <p>
            {t("pos.customerLabel")}: <b>{receipt.customer_name}</b>
            <br />
            {t("pos.total")}: <b>{money(receipt.total)}</b>
            {Number(receipt.discount_amount) > 0 && <>{t(" · الخصم: ")}<b>{money(receipt.discount_amount)}</b></>}
            {receipt.document_type === "invoice" ? <> · {t("pos.paid")}: <b>{money(receipt.paid)}</b></> : <>{t(" · المبلغ المستلم: ")}<b>{money(receipt.paid)}</b></>}
            {Number(receipt.balance_due) > 0 && (
              <>
                {" "}
                · {t("pos.balanceDueLabel")}: <b>{money(receipt.balance_due)}</b>
              </>
            )}
            {receipt.document_type === "invoice" && change !== null && change >= 0 && tendered !== "" && (
              <>
                <br />
                {t("pos.changeLabel")}: <b>{money(change)}</b>
              </>
            )}
          </p>
          <div className="form-actions">
            <button className="btn btn-primary" autoFocus onClick={reset}>
              {receipt.document_type === "quotation" ? t("إغلاق") : t("pos.newSale")}
            </button>
            <button className="btn" disabled={dl.busy} onClick={() => void dl.run(() => api.download(receipt.document_type === "quotation" ? `/sales-orders/${receipt.order_id}/quotation.pdf` : `/sales-orders/${receipt.order_id}/pdf`, `${receipt.document_type === "quotation" ? "quotation" : "invoice"}-SO-${receipt.order_id}.pdf`))}>
              {receipt.document_type === "quotation" ? t("تنزيل بيان الأسعار PDF") : t("pos.invoicePdf")}
            </button>
            <button className="btn" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/sales-orders/${receipt.order_id}/receipt`, `receipt-SO-${receipt.order_id}.pdf`))}>
              {t("pos.receipt80")}
            </button>
            {/* طباعة حرارية مباشرة عبر WebUSB — العربية ترسم على canvas ثم raster */}
            <button
              className="btn"
              disabled={thermal.busy}
              title={t("طابعة حرارية USB — Chrome/Edge فقط")}
              onClick={() => void thermal.run(async () => {
                const lines: ThermalLine[] = [
                  { center: "MOZAD ERP", big: true },
                  { center: documentType === "quotation" ? t("بيان أسعار") : t("فاتورة بيع") },
                  { divider: true },
                  { right: `SO-${receipt.order_id}`, left: dateTime(receipt.created_at ?? new Date().toISOString()) },
                  ...(receipt.customer_name ? [{ right: `${t("العميل")}: ${receipt.customer_name}` }] : []),
                  { divider: true },
                  ...cart.map((l) => ({ right: l.product.name.slice(0, 24), left: `${l.quantity} × ${money(l.price)}` })),
                  { divider: true },
                  { right: t("الإجمالي"), left: money(total) },
                  ...(discountCents > 0 ? [{ right: t("الخصم"), left: money(discountAmount) }] : []),
                  { right: t("ضريبة القيمة المضافة"), left: money(vatAmount) },
                  { right: t("الإجمالي المستحق"), left: money(grandDue), bold: true },
                  ...(documentType === "invoice" && receipt.paid ? [{ right: t("المدفوع"), left: money(receipt.paid) }] : []),
                  ...(Number(receipt.balance_due) > 0 ? [{ right: t("المتبقي"), left: money(receipt.balance_due), bold: true }] : []),
                  ...(change !== null && change >= 0 && tendered !== "" ? [{ right: t("الباقي للعميل"), left: money(change), bold: true }] : []),
                ];
                await printThermal(lines, "شكراً لزيارتكم — MOZAD");
              })}
            >
              {thermal.busy ? t("جارٍ الطباعة…") : `🖨 ${t("حرارية")}`}
            </button>
          </div>
          {thermal.error && <Alert>{thermal.error}</Alert>}
        </Modal>
      )}
    </>
  );
}
