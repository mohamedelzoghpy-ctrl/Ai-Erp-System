import { useState, type FormEvent } from "react";
import { api, qs } from "../api";
import { useAuth } from "../auth";
import { balanceNote, dateOnly, METHOD_LABEL, money } from "../format";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Payment, PaymentMethod, Statement } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader, Pager } from "../ui";

export type PartyKind = "customer" | "supplier";

/** YYYY-MM-DD in the browser's local calendar. */
export function today(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const pathOf = (kind: PartyKind) => (kind === "customer" ? "customers" : "suppliers");

// ------------------------------------------------------------ record a receipt / payment
export function PaymentDialog({
  kind,
  partyId,
  partyName,
  balance,
  onClose,
  onSaved,
}: {
  kind: PartyKind;
  partyId: number;
  partyName: string;
  balance: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isReceipt = kind === "customer";
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [paidOn, setPaidOn] = useState(today());
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const { busy, error, run } = useAction();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/payments", {
        [isReceipt ? "customer_id" : "supplier_id"]: partyId,
        amount,
        method,
        paid_on: paidOn,
        reference: reference.trim() || null,
        notes: notes.trim() || null,
      });
      onSaved();
    });
  };

  return (
    <Modal title={`${isReceipt ? "تسجيل قبض من" : "تسجيل دفعة إلى"} ${partyName}`} onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <p className="muted" style={{ marginTop: 0 }}>
          الرصيد الحالي: <b>{money(balance)}</b> ({balanceNote(kind, balance)})
        </p>
        <div className="form-grid">
          <Field label="المبلغ">
            <input dir="ltr" type="number" inputMode="decimal" min="0.01" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required autoFocus />
          </Field>
          <Field label="التاريخ">
            <input type="date" value={paidOn} max={today()} onChange={(e) => setPaidOn(e.target.value)} required />
          </Field>
        </div>
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
          <Field label="المرجع" hint="رقم الشيك أو التحويل (اختياري)">
            <input dir="ltr" value={reference} onChange={(e) => setReference(e.target.value)} maxLength={100} />
          </Field>
        </div>
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

// ------------------------------------------------------------ account statement
export function StatementDialog({ kind, partyId, partyName, onClose }: { kind: PartyKind; partyId: number; partyName: string; onClose: () => void }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const download = useAction();
  const valid = !from || !to || from <= to;
  const q = qs({ date_from: from, date_to: to });
  const base = `/${pathOf(kind)}/${partyId}/statement`;
  const data = useFetch(() => (valid ? api.get<Statement>(`${base}${q}`) : Promise.resolve(null)), `st-${kind}-${partyId}${q}${valid}`);
  const s = data.data;
  const chargeLabel = kind === "customer" ? "مبيعات (عليه)" : "مشتريات (له)";
  const payLabel = kind === "customer" ? "مقبوضات" : "مدفوعات";

  return (
    <Modal title={`كشف حساب — ${partyName}`} onClose={onClose} wide>
      <div className="range-bar" style={{ marginBottom: 12 }}>
        <label className="range-field">
          <span className="field-label">من تاريخ</span>
          <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="range-field">
          <span className="field-label">إلى تاريخ</span>
          <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </label>
        <div className="range-presets">
          <button className="btn btn-sm btn-primary" disabled={download.busy || !valid} onClick={() => void download.run(() => api.download(`${base}/pdf${q}`, `statement-${partyId}.pdf`))}>
            ⬇ PDF
          </button>
          <button className="btn btn-sm btn-primary" disabled={download.busy || !valid} onClick={() => void download.run(() => api.download(`${base}/xlsx${q}`, `statement-${partyId}.xlsx`))}>
            ⬇ Excel
          </button>
        </div>
      </div>
      {!valid && <Alert>تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.</Alert>}
      <Alert>{data.error || download.error}</Alert>
      {data.loading && !s ? (
        <Loading />
      ) : (
        s && (
          <>
            <div className="table-wrap" style={{ maxHeight: "50vh", overflow: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>التاريخ</th>
                    <th>المرجع</th>
                    <th>البيان</th>
                    <th className="num">{chargeLabel}</th>
                    <th className="num">{payLabel}</th>
                    <th className="num">الرصيد</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td colSpan={5}>
                      <b>رصيد افتتاحي{s.date_from ? ` (قبل ${dateOnly(s.date_from)})` : ""}</b>
                    </td>
                    <td className="num">
                      <b>{money(s.opening)}</b>
                    </td>
                  </tr>
                  {s.lines.length === 0 && (
                    <tr>
                      <td colSpan={6}>
                        <Empty>لا حركات في هذه الفترة</Empty>
                      </td>
                    </tr>
                  )}
                  {s.lines.map((l, i) => (
                    <tr key={i}>
                      <td>{dateOnly(l.date)}</td>
                      <td dir="ltr">{l.ref}</td>
                      <td>{l.description}</td>
                      <td className="num">{Number(l.charge) ? money(l.charge) : ""}</td>
                      <td className="num">{Number(l.payment) ? money(l.payment) : ""}</td>
                      <td className="num">{money(l.balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p style={{ marginBottom: 0 }}>
              {chargeLabel}: <b>{money(s.total_charges)}</b> · {payLabel}: <b>{money(s.total_payments)}</b> · الرصيد الختامي: <b>{money(s.closing)}</b> ({balanceNote(kind, s.closing)})
            </p>
          </>
        )
      )}
    </Modal>
  );
}

// ------------------------------------------------------------ payments list page
export default function Payments() {
  const { isManager } = useAuth();
  const safes = useFetch(() => api.get<{ id: number; name: string; code: string; balance: string; is_active: boolean }[]>("/safes"), "safes");
  const banks = useFetch(() => api.get<{ id: number; name: string; code: string; account_number: string | null; balance: string; is_active: boolean }[]>("/banks"), "banks");
  const customers = useFetch(() => api.get<{ id: number; name: string; balance?: string }[]>("/customers?limit=500"), "acc-customers");
  const suppliers = useFetch(() => api.get<{ id: number; name: string; balance?: string }[]>("/suppliers?limit=500"), "acc-suppliers");
  const [receiptParty, setReceiptParty] = useState<{ id: number; name: string; balance: string } | null>(null);
  const [paymentParty, setPaymentParty] = useState<{ id: number; name: string; balance: string } | null>(null);
  const [showReceiptPicker, setShowReceiptPicker] = useState(false);
  const [showPaymentPicker, setShowPaymentPicker] = useState(false);
  const [kind, setKind] = useState<"" | "receipt" | "payment">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const action = useAction();
  const valid = !from || !to || from <= to;
  const list = usePagedList<Payment>("/payments", valid ? { kind, date_from: from, date_to: to } : { kind, limit: 1 });

  const voidIt = (p: Payment) => {
    if (!confirm(`إلغاء ${p.kind === "receipt" ? "سند القبض" : "سند الدفع"} RC/PY-${p.id} بمبلغ ${money(p.amount)}؟ لا يمكن التراجع.`)) return;
    void action.run(async () => {
      await api.post(`/payments/${p.id}/void`);
      list.reload();
    });
  };

  return (
    <>
      <PageHeader title="المقبوضات والمدفوعات" />
      <div className="card" style={{ padding: 14, marginBottom: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn btn-primary" onClick={() => setShowReceiptPicker(true)}>+ سند قبض</button>
        <button className="btn btn-primary" onClick={() => setShowPaymentPicker(true)}>+ سند صرف</button>
        <button className="btn btn-primary" onClick={() => { const el = document.getElementById("safe-form"); el?.scrollIntoView({ behavior: "smooth" }); }}>+ إضافة خزينة</button>
        <button className="btn btn-primary" onClick={() => { const el = document.getElementById("bank-form"); el?.scrollIntoView({ behavior: "smooth" }); }}>+ إضافة بنك</button>
      </div>
      <div className="card card-pad range-bar" style={{ marginBottom: 14 }}>
        <label className="range-field">
          <span className="field-label">النوع</span>
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            <option value="">الكل</option>
            <option value="receipt">مقبوضات (من العملاء)</option>
            <option value="payment">مدفوعات (للموردين)</option>
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">من تاريخ</span>
          <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="range-field">
          <span className="field-label">إلى تاريخ</span>
          <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>
      {!valid && <Alert>تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.</Alert>}
      <Alert>{list.error || action.error}</Alert>
      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <h2>الخزائن (Safes)</h2>
        {safes.data && safes.data.length > 0 ? (
          <div className="table-wrap" style={{ marginBottom: 12 }}>
            <table>
              <thead><tr><th>الاسم</th><th>الكود</th><th className="num">الرصيد</th><th>الحالة</th></tr></thead>
              <tbody>{safes.data.map((s) => (
                <tr key={s.id}><td>{s.name}</td><td dir="ltr">{s.code}</td><td className="num">{money(s.balance)}</td><td>{s.is_active ? "نشطة" : "معطّلة"}</td></tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty>لا توجد خزائن.</Empty>}
        {isManager && (
          <form onSubmit={(e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            void (async () => {
              await api.post("/safes", { name: String(fd.get("name") || ""), code: String(fd.get("code") || ""), opening_balance: Number(fd.get("opening") || 0) });
              safes.reload();
              (e.target as HTMLFormElement).reset();
            })();
          }} className="form-grid" id="safe-form">
            <Field label="اسم الخزينة"><input name="name" required /></Field>
            <Field label="الكود"><input name="code" dir="ltr" required /></Field>
            <Field label="الرصيد الافتتاحي"><input name="opening" type="number" step="0.01" defaultValue="0" /></Field>
            <button className="btn btn-primary" disabled={action.busy}>إضافة خزينة</button>
          </form>
        )}
      </div>

      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <h2>البنوك (Banks)</h2>
        {banks.data && banks.data.length > 0 ? (
          <div className="table-wrap" style={{ marginBottom: 12 }}>
            <table>
              <thead><tr><th>الاسم</th><th>الكود</th><th>رقم الحساب</th><th className="num">الرصيد</th><th>الحالة</th></tr></thead>
              <tbody>{banks.data.map((b) => (
                <tr key={b.id}><td>{b.name}</td><td dir="ltr">{b.code}</td><td dir="ltr">{b.account_number || "—"}</td><td className="num">{money(b.balance)}</td><td>{b.is_active ? "نشطة" : "معطّلة"}</td></tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty>لا توجد بنوك.</Empty>}
        {isManager && (
          <form onSubmit={(e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            void (async () => {
              await api.post("/banks", { name: String(fd.get("name") || ""), code: String(fd.get("code") || ""), account_number: String(fd.get("acct") || "") || null, opening_balance: Number(fd.get("opening") || 0) });
              banks.reload();
              (e.target as HTMLFormElement).reset();
            })();
          }} className="form-grid" id="bank-form">
            <Field label="اسم البنك"><input name="name" required /></Field>
            <Field label="الكود"><input name="code" dir="ltr" required /></Field>
            <Field label="رقم الحساب"><input name="acct" dir="ltr" /></Field>
            <Field label="الرصيد الافتتاحي"><input name="opening" type="number" step="0.01" defaultValue="0" /></Field>
            <button className="btn btn-primary" disabled={action.busy}>إضافة بنك</button>
          </form>
        )}
      </div>

      <p className="muted" style={{ marginTop: 0 }}>لتسجيل قبض أو دفعة جديدة افتح صفحة العميل أو المورد واضغط «قبض» / «دفع».</p>
      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>الرقم</th>
                <th>التاريخ</th>
                <th>النوع</th>
                <th>الطرف</th>
                <th className="num">المبلغ</th>
                <th>الطريقة</th>
                <th>المرجع</th>
                <th>الحالة</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((p) => (
                <tr key={p.id} style={p.status === "voided" ? { opacity: 0.55 } : undefined}>
                  <td dir="ltr">{p.kind === "receipt" ? "RC" : "PY"}-{p.id}</td>
                  <td>{dateOnly(p.paid_on)}</td>
                  <td>{p.kind === "receipt" ? "قبض" : "دفع"}</td>
                  <td>{p.party_name ?? "—"}</td>
                  <td className="num">{money(p.amount)}</td>
                  <td>{METHOD_LABEL[p.method]}</td>
                  <td dir="ltr">{p.reference || "—"}</td>
                  <td>{p.status === "posted" ? <span className="badge badge-confirmed">مرحّل</span> : <span className="badge badge-cancelled">ملغى</span>}</td>
                  <td className="actions">
                    {isManager && p.status === "posted" && (
                      <button className="btn btn-sm btn-danger" onClick={() => voidIt(p)}>
                        إلغاء
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>لا توجد سندات في هذه الفترة.</Empty>
        )}
        <Pager list={list} />
      </div>
      {showReceiptPicker && (
        <Modal title="اختر العميل (سند قبض)" onClose={() => setShowReceiptPicker(false)}>
          <div className="table-wrap">
            <table>
              <tbody>
                {(customers.data ?? []).map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}</td>
                    <td className="actions">
                      <button className="btn btn-sm" onClick={() => { setReceiptParty({ id: c.id, name: c.name, balance: c.balance ?? "0" }); setShowReceiptPicker(false); }}>اختيار</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Modal>
      )}
      {showPaymentPicker && (
        <Modal title="اختر المورد (سند صرف)" onClose={() => setShowPaymentPicker(false)}>
          <div className="table-wrap">
            <table>
              <tbody>
                {(suppliers.data ?? []).map((s) => (
                  <tr key={s.id}>
                    <td>{s.name}</td>
                    <td className="actions">
                      <button className="btn btn-sm" onClick={() => { setPaymentParty({ id: s.id, name: s.name, balance: s.balance ?? "0" }); setShowPaymentPicker(false); }}>اختيار</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Modal>
      )}
      {receiptParty && (
        <PaymentDialog kind="customer" partyId={receiptParty.id} partyName={receiptParty.name} balance={receiptParty.balance} onClose={() => setReceiptParty(null)} onSaved={() => { setReceiptParty(null); list.reload(); safes.reload(); banks.reload(); }} />
      )}
      {paymentParty && (
        <PaymentDialog kind="supplier" partyId={paymentParty.id} partyName={paymentParty.name} balance={paymentParty.balance} onClose={() => setPaymentParty(null)} onSaved={() => { setPaymentParty(null); list.reload(); safes.reload(); banks.reload(); }} />
      )}
    </>
  );
}
