import { useState, type FormEvent } from "react";
import { api, qs } from "../api";
import { useAuth } from "../auth";
import { balanceNote, dateOnly, METHOD_LABEL, money } from "../format";
import { useAction, useFetch } from "../hooks";
import type { Payment, PaymentMethod, Statement } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

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
  const [kind, setKind] = useState<"" | "receipt" | "payment">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const action = useAction();
  const valid = !from || !to || from <= to;
  const q = qs({ kind, date_from: from, date_to: to, limit: 500 });
  const list = useFetch(() => (valid ? api.get<Payment[]>(`/payments${q}`) : Promise.resolve([] as Payment[])), `pay${q}${valid}`);

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
      </div>
    </>
  );
}
