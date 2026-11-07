import { useState, type FormEvent } from "react";
import { api, qs } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { balanceNote, CHEQUE_STATUS_LABEL, dateOnly, METHOD_LABEL, money } from "../format";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { AccountStatementOut, Cheque, ChequeDirection, ChequeStatus, Payment, PaymentCategory, PaymentMethod, Statement } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader, Pager } from "../ui";

export type PartyKind = "customer" | "supplier";

/** YYYY-MM-DD in the browser's local calendar. */
export function today(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const pathOf = (kind: PartyKind) => (kind === "customer" ? "customers" : "suppliers");

/** مستند جاهز للمعاينة/الطباعة (نتيجة فلاتر التصنيفات). */
interface FilterDoc {
  title: string;
  subtitle: string;
  headers: string[];
  rows: string[][];
  totalLabel: string;
  total: string;
}

function printDoc(doc: FilterDoc) {
  const w = window.open("", "_blank");
  if (!w) return;
  const rowsHtml = doc.rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("");
  w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>${doc.title}</title>
    <style>
      body { font-family: Tahoma, Arial, sans-serif; padding: 16px; }
      h1 { text-align: center; font-size: 20px; }
      h2 { text-align: center; font-weight: normal; font-size: 13px; color: #444; }
      table { width: 100%; border-collapse: collapse; margin-top: 12px; }
      th, td { border: 1px solid #999; padding: 6px 8px; text-align: center; font-size: 12px; }
      th { background: #eee; }
      tfoot td { font-weight: bold; background: #f3f4f6; }
    </style></head><body>
    <h1>${doc.title}</h1>
    <h2>${doc.subtitle}</h2>
    <table>
      <thead><tr>${doc.headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rowsHtml || `<tr><td colspan="${doc.headers.length}">لا توجد بيانات</td></tr>`}</tbody>
      <tfoot><tr><td colspan="${doc.headers.length - 1}">${doc.totalLabel}</td><td>${doc.total}</td></tr></tfoot>
    </table>
    <script>window.onload = () => { window.print(); };</script>
    </body></html>`);
  w.document.close();
}

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
  partyId?: number; // fixed party (customers/suppliers pages) — omitted on the payments page flow
  partyName?: string;
  balance?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isReceipt = kind === "customer";
  const fixedParty = partyId != null;
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [paidOn, setPaidOn] = useState(today());
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  // بند السند = نوعه: أول حقل، ويحدد هل يلزم عميل/مورد أم لا
  const catKind = isReceipt ? "receipt" : "payment";
  const categories = useFetch(() => api.get<PaymentCategory[]>(`/payment-categories?kind=${catKind}`), `pay-categories-${catKind}`);
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [addingCategory, setAddingCategory] = useState(false);
  const [newCategory, setNewCategory] = useState("");
  const [newCategoryNoParty, setNewCategoryNoParty] = useState(false);
  const [partyChoice, setPartyChoice] = useState<number | "">("");
  const [place, setPlace] = useState(""); // "safe:<id>" | "bank:<id>" — where the money lands for party-less vouchers
  const catAction = useAction();
  const { busy, error, run } = useAction();

  // Lists for the free (payments-page) flow; unused when the party is fixed.
  const parties = useFetch(
    () => (fixedParty ? Promise.resolve([]) : api.get<{ id: number; name: string; balance?: string }[]>(`/${pathOf(kind)}?limit=500`)),
    `paydlg-parties-${kind}`
  );
  const safes = useFetch(() => api.get<{ id: number; name: string; is_active: boolean }[]>("/safes"), "paydlg-safes");
  const banks = useFetch(() => api.get<{ id: number; name: string; is_active: boolean }[]>("/banks"), "paydlg-banks");

  const selCat = (categories.data ?? []).find((c) => c.id === categoryId) ?? null;
  const partyNeeded = fixedParty || selCat?.requires_party !== false;
  const chosenParty = fixedParty
    ? { id: partyId!, name: partyName ?? "", balance: balance ?? "0" }
    : (parties.data ?? []).find((p) => p.id === partyChoice) ?? null;

  const addCategory = () => {
    const name = newCategory.trim();
    if (!name) return;
    void catAction.run(async () => {
      const created = await api.post<PaymentCategory>("/payment-categories", { name, kind: catKind, requires_party: !newCategoryNoParty });
      setNewCategory("");
      setNewCategoryNoParty(false);
      setAddingCategory(false);
      categories.reload();
      setCategoryId(created.id);
    });
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const body: Record<string, unknown> = {
        amount,
        method,
        paid_on: paidOn,
        reference: reference.trim() || null,
        notes: notes.trim() || null,
        category_id: categoryId === "" ? null : categoryId,
      };
      if (partyNeeded) {
        body[isReceipt ? "customer_id" : "supplier_id"] = fixedParty ? partyId : partyChoice;
      }
      if (place !== "") {
        // تحديد مكان المبلغ (خزينة/بنك) متاح لكل السندات — وإجباري للسند بدون طرف
        const [placeKind, placeId] = place.split(":");
        body[placeKind === "safe" ? "safe_id" : "bank_id"] = Number(placeId);
      }
      await api.post("/payments", body);
      onSaved();
    });
  };

  return (
    <Modal title={fixedParty ? `${isReceipt ? "تسجيل قبض من" : "تسجيل دفعة إلى"} ${partyName}` : isReceipt ? "سند قبض جديد" : "سند صرف جديد"} onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        {chosenParty && (
          <p className="muted" style={{ marginTop: 0 }}>
            الرصيد الحالي: <b>{money(chosenParty.balance)}</b> ({balanceNote(kind, chosenParty.balance ?? "0")})
          </p>
        )}
        <Field label={isReceipt ? "بند القبض" : "بند الصرف"} hint={fixedParty ? "اختياري — اختر من القائمة أو أضف بندًا جديدًا" : "نوع السند — اختر من القائمة أو أضف بندًا جديدًا"}>
          <div style={{ display: "flex", gap: 6 }}>
            <select
              value={String(categoryId)}
              onChange={(e) => setCategoryId(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ flex: 1 }}
              autoFocus={!fixedParty}
            >
              <option value="">{fixedParty ? "— بدون بند —" : "— اختر البند —"}</option>
              {(categories.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}{c.requires_party ? "" : " (بدون " + (isReceipt ? "عميل" : "مورد") + ")"}
                </option>
              ))}
            </select>
            <button type="button" className="btn" onClick={() => setAddingCategory((v) => !v)}>
              {addingCategory ? "إلغاء" : "+ بند جديد"}
            </button>
          </div>
        </Field>
        {addingCategory && (
          <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
            <input
              placeholder={`اسم ${isReceipt ? "بند القبض" : "بند الصرف"} الجديد`}
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addCategory();
                }
              }}
              maxLength={150}
              style={{ flex: 1, minWidth: 160 }}
            />
            <label className="check" style={{ fontSize: 13, whiteSpace: "nowrap" }}>
              <input type="checkbox" checked={newCategoryNoParty} onChange={(e) => setNewCategoryNoParty(e.target.checked)} /> بدون {isReceipt ? "عميل" : "مورد"}
            </label>
            <button type="button" className="btn btn-primary" disabled={catAction.busy || !newCategory.trim()} onClick={addCategory}>
              {catAction.busy ? "…" : "إضافة"}
            </button>
          </div>
        )}
        {catAction.error && <Alert>{catAction.error}</Alert>}
        {partyNeeded && !fixedParty && (
          <Field label={isReceipt ? "العميل" : "المورد"}>
            <select value={String(partyChoice)} onChange={(e) => setPartyChoice(e.target.value === "" ? "" : Number(e.target.value))} required>
              <option value="">— اختر —</option>
              {(parties.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}{p.balance != null ? ` — ${money(p.balance)}` : ""}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field
          label="الخزينة / البنك"
          hint={partyNeeded ? "اختياري — حدد اسم الخزينة أو البنك الذي سيوضع فيه المبلغ" : "مكان حفظ المبلغ — إجباري للسند بدون طرف"}
        >
          <select value={place} onChange={(e) => setPlace(e.target.value)} required={!partyNeeded}>
            <option value="">— اختر —</option>
            {(safes.data ?? []).filter((s) => s.is_active).map((s) => (
              <option key={`safe-${s.id}`} value={`safe:${s.id}`}>خزينة: {s.name}</option>
            ))}
            {(banks.data ?? []).filter((b) => b.is_active).map((b) => (
              <option key={`bank-${b.id}`} value={`bank:${b.id}`}>بنك: {b.name}</option>
            ))}
          </select>
        </Field>
        <div className="form-grid">
          <Field label="المبلغ">
            <input dir="ltr" type="number" inputMode="decimal" min="0.01" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required autoFocus={fixedParty} />
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

// ------------------------------------------------------------ cheques (حافظة الشيكات)
function ChequeDialog({ direction, onClose, onSaved }: { direction: ChequeDirection; onClose: () => void; onSaved: () => void }) {
  const isReceive = direction === "received";
  const [number, setNumber] = useState("");
  const [bankId, setBankId] = useState<number | "">("");
  const [partyId, setPartyId] = useState<number | "">("");
  const [amount, setAmount] = useState("");
  const [chequeDate, setChequeDate] = useState(today());
  const [dueDate, setDueDate] = useState("");
  const [notes, setNotes] = useState("");
  const { busy, error, run } = useAction();

  const banks = useFetch(() => api.get<{ id: number; name: string; is_active: boolean }[]>("/banks"), "chq-banks");
  const parties = useFetch(
    () => api.get<{ id: number; name: string; balance?: string }[]>(`/${isReceive ? "customers" : "suppliers"}?limit=500`),
    `chq-parties-${direction}`
  );

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/cheques", {
        direction,
        number: number.trim(),
        bank_id: bankId,
        amount,
        ...(isReceive ? { customer_id: partyId } : { supplier_id: partyId }),
        cheque_date: chequeDate,
        due_date: dueDate || null,
        notes: notes.trim() || null,
      });
      onSaved();
    });
  };

  return (
    <Modal title={isReceive ? "استلام شيك" : "صرف شيك"} onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <div className="form-grid">
          <Field label={isReceive ? "العميل" : "المورد"}>
            <select value={String(partyId)} onChange={(e) => setPartyId(e.target.value === "" ? "" : Number(e.target.value))} required>
              <option value="">— اختر —</option>
              {(parties.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.balance != null ? ` — ${money(p.balance)}` : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="رقم الشيك">
            <input dir="ltr" value={number} onChange={(e) => setNumber(e.target.value)} required maxLength={60} autoFocus />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="البنك المسحوب عليه">
            <select value={String(bankId)} onChange={(e) => setBankId(e.target.value === "" ? "" : Number(e.target.value))} required>
              <option value="">— اختر —</option>
              {(banks.data ?? []).filter((b) => b.is_active).map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          </Field>
          <Field label="المبلغ">
            <input dir="ltr" type="number" inputMode="decimal" min="0.01" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="تاريخ الشيك">
            <input type="date" value={chequeDate} max={today()} onChange={(e) => setChequeDate(e.target.value)} required />
          </Field>
          <Field label="تاريخ الاستحقاق" hint="اختياري">
            <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
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

function ChequeActionDialog({ cheque, action, onClose, onDone }: { cheque: Cheque; action: "collect" | "deposit"; onClose: () => void; onDone: () => void }) {
  const isCollect = action === "collect";
  const [targetId, setTargetId] = useState<number | "">("");
  const { busy, error, run } = useAction();
  const targets = useFetch(
    () => api.get<{ id: number; name: string; is_active: boolean }[]>(isCollect ? "/safes" : "/banks"),
    `chq-target-${action}`
  );

  return (
    <Modal title={isCollect ? `تحصيل الشيك ${cheque.number}` : `إيداع الشيك ${cheque.number}`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            if (isCollect) await api.post(`/cheques/${cheque.id}/collect`, { safe_id: targetId });
            else await api.post(`/cheques/${cheque.id}/deposit`, { bank_id: targetId });
            onDone();
          });
        }}
      >
        <Alert>{error}</Alert>
        <p className="muted" style={{ marginTop: 0 }}>
          مبلغ الشيك: <b>{money(cheque.amount)}</b> — {isCollect ? "يُضاف إلى الخزينة" : "يُضاف إلى حساب البنك"}
        </p>
        <Field label={isCollect ? "الخزينة" : "البنك"}>
          <select value={String(targetId)} onChange={(e) => setTargetId(e.target.value === "" ? "" : Number(e.target.value))} required autoFocus>
            <option value="">— اختر —</option>
            {(targets.data ?? []).filter((t) => t.is_active).map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </Field>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy}>
            {busy ? "…" : "تأكيد"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            إلغاء
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ChequesTable({
  direction,
  status,
  bankId,
  branchId,
  dateFrom,
  dateTo,
  onChanged,
}: {
  direction?: ChequeDirection | "";
  status?: ChequeStatus | "";
  bankId?: number | "";
  branchId?: number | "";
  dateFrom?: string;
  dateTo?: string;
  onChanged: () => void;
}) {
  const list = useFetch(
    () => api.get<Cheque[]>(`/cheques?${qs({ direction: direction || undefined, status: status || undefined, bank_id: bankId || undefined, branch_id: branchId || undefined, date_from: dateFrom || undefined, date_to: dateTo || undefined })}`),
    `cheques-${direction}-${status}-${bankId}-${branchId}-${dateFrom}-${dateTo}`
  );
  const [actionState, setActionState] = useState<{ cheque: Cheque; action: "collect" | "deposit" } | null>(null);
  const act = useAction();

  const doReturn = (c: Cheque) => {
    if (!confirm(`ارتجاع الشيك ${c.number} بمبلغ ${money(c.amount)}؟ سيُلغى السند المرتبط ويرجع رصيد الطرف.`)) return;
    void act.run(async () => {
      await api.post(`/cheques/${c.id}/return`);
      list.reload();
      onChanged();
    });
  };
  const doCashOut = (c: Cheque) => {
    if (!confirm(`تأكيد صرف الشيك ${c.number} من البنك بمبلغ ${money(c.amount)}؟ سيُخصم من رصيد البنك.`)) return;
    void act.run(async () => {
      await api.post(`/cheques/${c.id}/cash-out`);
      list.reload();
      onChanged();
    });
  };

  return (
    <>
      <Alert>{list.error || act.error}</Alert>
        <div className="table-wrap">
          {list.loading && !list.data ? (
            <Loading />
          ) : list.data && list.data.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>الرقم</th>
                  <th>الاتجاه</th>
                  <th>اسم الفرع</th>
                  <th>رقم الشيك</th>
                  <th>البنك</th>
                  <th>الطرف</th>
                  <th>تاريخ الشيك</th>
                  <th>الاستحقاق</th>
                  <th className="num">المبلغ</th>
                  <th>الحالة</th>
                  <th>إجراءات</th>
                </tr>
              </thead>
              <tbody>
                {list.data.map((c) => (
                  <tr key={c.id}>
                    <td dir="ltr">{c.direction === "received" ? "IN" : "OUT"}-{c.id}</td>
                    <td>{c.direction === "received" ? "مقبوض" : "مصروف"}</td>
                    <td>{c.bank_branch_name ?? "—"}</td>
                    <td dir="ltr">{c.number}</td>
                    <td>{c.bank_name ?? "—"}</td>
                    <td>{c.party_name ?? "—"}</td>
                    <td>{dateOnly(c.cheque_date)}</td>
                    <td>{c.due_date ? dateOnly(c.due_date) : "—"}</td>
                    <td className="num">{money(c.amount)}</td>
                    <td>
                      <span className={`badge ${c.status === "collected" || c.status === "cashed" ? "badge-confirmed" : c.status === "returned" ? "badge-cancelled" : "badge-draft"}`}>
                        {CHEQUE_STATUS_LABEL[c.status]}
                      </span>
                    </td>
                    <td className="actions">
                      {c.direction === "received" && c.status === "under_collection" && (
                        <>
                          <button className="btn btn-sm" onClick={() => setActionState({ cheque: c, action: "collect" })}>
                            💵 تحصيل
                          </button>{" "}
                          <button className="btn btn-sm" onClick={() => setActionState({ cheque: c, action: "deposit" })}>
                            🏦 إيداع
                          </button>{" "}
                        </>
                      )}
                      {c.direction === "issued" && c.status === "issued" && (
                        <button className="btn btn-sm" onClick={() => doCashOut(c)}>
                          🏦 تم الصرف
                        </button>
                      )}
                      {(c.status === "under_collection" || c.status === "issued") && (
                        <button
                          className="btn btn-sm"
                          style={{ color: "var(--danger)", borderColor: "var(--danger)" }}
                          onClick={() => doReturn(c)}
                        >
                          ↩️ ارتجاع
                        </button>
                      )}
                      {(c.status === "collected" || c.status === "cashed" || c.status === "returned") && <span className="muted">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>لا توجد شيكات.</Empty>
          )}
        </div>
      {actionState && (
        <ChequeActionDialog
          cheque={actionState.cheque}
          action={actionState.action}
          onClose={() => setActionState(null)}
          onDone={() => {
            setActionState(null);
            list.reload();
            onChanged();
          }}
        />
      )}
    </>
  );
}

function PortfolioModal({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [statusFilter, setStatusFilter] = useState<"" | ChequeStatus>("");
  return (
    <Modal title="📁 حافظة الشيكات" onClose={onClose} wide>
      <div style={{ marginBottom: 10, display: "flex", gap: 8 }}>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as "" | ChequeStatus)}>
          <option value="">كل الحالات</option>
          {(Object.keys(CHEQUE_STATUS_LABEL) as ChequeStatus[]).map((s) => (
            <option key={s} value={s}>
              {CHEQUE_STATUS_LABEL[s]}
            </option>
          ))}
        </select>
      </div>
      <ChequesTable status={statusFilter} onChanged={onChanged} />
    </Modal>
  );
}

function SafeBalanceModal({ onClose }: { onClose: () => void }) {
  const [safeId, setSafeId] = useState<number | "">("");
  const safes = useFetch(() => api.get<{ id: number; name: string; code: string; balance: string; is_active: boolean }[]>("/safes"), "safe-balance-safes");
  // كشف من دفتر الأستاذ: يشمل حركات السندات والشيكات وكل ما يمس الخزينة
  const list = useFetch(
    () => (safeId === "" ? Promise.resolve(null) : api.get<AccountStatementOut>(`/safes/${safeId}/statement`)),
    `safe-balance-${safeId}`
  );
  const selSafe = (safes.data ?? []).find((s) => s.id === safeId) ?? null;
  const stmt = list.data ?? null;

  const printNow = () => {
    if (!stmt) return;
    const w = window.open("", "_blank");
    if (!w) return;
    const rowsHtml = stmt.lines.map((l) => `
      <tr>
        <td>${l.entry_id}</td>
        <td>${dateOnly(l.date)}</td>
        <td>${l.description ?? "—"}</td>
        <td>${l.reference ?? "—"}</td>
        <td class="num">${Number(l.debit) ? money(l.debit) : "—"}</td>
        <td class="num">${Number(l.credit) ? money(l.credit) : "—"}</td>
        <td class="num">${money(l.balance)}</td>
      </tr>`).join("");
    w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>كشف حركة الخزينة</title>
      <style>
        body { font-family: Tahoma, Arial, sans-serif; padding: 16px; }
        h1 { text-align: center; font-size: 20px; }
        h2 { text-align: center; font-weight: normal; font-size: 14px; color: #444; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; }
        th, td { border: 1px solid #999; padding: 6px 8px; text-align: center; font-size: 12px; }
        th { background: #eee; }
        .num { text-align: center; }
        tfoot td { font-weight: bold; background: #f3f4f6; }
      </style></head><body>
      <h1>كشف حركة الخزينة — ${stmt.account_name}</h1>
      <h2>الكود: ${stmt.account_code} · الرصيد الحالي: ${money(stmt.closing)}</h2>
      <table>
        <thead><tr>
          <th>القيد</th><th>التاريخ</th><th>البيان</th><th>المرجع</th><th>داخل</th><th>خارج</th><th>الرصيد</th>
        </tr></thead>
        <tbody>${rowsHtml || '<tr><td colspan="7">لا توجد حركات على هذه الخزينة</td></tr>'}</tbody>
        <tfoot><tr>
          <td colspan="4">الإجمالي</td>
          <td class="num">${money(stmt.total_debit)}</td>
          <td class="num">${money(stmt.total_credit)}</td>
          <td class="num">${money(stmt.closing)}</td>
        </tr></tfoot>
      </table>
      <script>window.onload = () => { window.print(); };</script>
      </body></html>`);
    w.document.close();
  };

  return (
    <Modal title="💰 رصيد الخزينة" onClose={onClose} wide>
      <div style={{ marginBottom: 10, display: "flex", gap: 8 }}>
        <select value={String(safeId)} onChange={(e) => setSafeId(e.target.value === "" ? "" : Number(e.target.value))} style={{ flex: 1 }}>
          <option value="">— اختر الخزينة —</option>
          {(safes.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <button className="btn" onClick={printNow} disabled={!stmt}>🖨 طباعة</button>
      </div>
      {selSafe && (
        <div className="card card-pad" style={{ marginBottom: 10, display: "flex", gap: 24, flexWrap: "wrap" }}>
          <span>الخزينة: <b>{selSafe.name}</b></span>
          <span>الكود: <span dir="ltr">{selSafe.code}</span></span>
          <span>الرصيد الحالي: <b>{money(selSafe.balance)}</b></span>
        </div>
      )}
      <Alert>{list.error}</Alert>
      <div className="table-wrap">
        {list.loading && safeId !== "" && !stmt ? (
          <Loading />
        ) : stmt && stmt.lines.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>القيد</th>
                <th>التاريخ</th>
                <th>البيان</th>
                <th>المرجع</th>
                <th className="num">داخل</th>
                <th className="num">خارج</th>
                <th className="num">الرصيد</th>
              </tr>
            </thead>
            <tbody>
              {stmt.lines.map((l) => (
                <tr key={`${l.entry_id}-${l.debit}-${l.credit}`}>
                  <td dir="ltr">JE-{l.entry_id}</td>
                  <td>{dateOnly(l.date)}</td>
                  <td>{l.description ?? "—"}</td>
                  <td dir="ltr">{l.reference ?? "—"}</td>
                  <td className="num">{Number(l.debit) ? money(l.debit) : "—"}</td>
                  <td className="num">{Number(l.credit) ? money(l.credit) : "—"}</td>
                  <td className="num">{money(l.balance)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={4} className="num">الإجمالي</td>
                <td className="num">{money(stmt.total_debit)}</td>
                <td className="num">{money(stmt.total_credit)}</td>
                <td className="num">{money(stmt.closing)}</td>
              </tr>
            </tfoot>
          </table>
        ) : (
          <Empty>{safeId === "" ? "اختر خزينة لعرض رصيدها وحركتها." : "لا توجد حركات على هذه الخزينة."}</Empty>
        )}
      </div>
    </Modal>
  );
}

function AccountTransactionsModal({ kind, onClose }: { kind: "safe" | "bank"; onClose: () => void }) {
  const isSafe = kind === "safe";
  const [accId, setAccId] = useState<number | "">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const accounts = useFetch(() => api.get<{ id: number; name: string; code: string; balance: string; is_active: boolean }[]>(isSafe ? "/safes" : "/banks"), `acct-tx-${kind}`);
  const list = useFetch(
    () => (accId === "" ? Promise.resolve(null) : api.get<AccountStatementOut>(`/${isSafe ? "safes" : "banks"}/${accId}/statement?${qs({ date_from: from, date_to: to })}`)),
    `acct-stmt-${kind}-${accId}-${from}-${to}`
  );
  const stmt = list.data ?? null;
  const valid = !from || !to || from <= to;
  const entityLabel = isSafe ? "الخزينة" : "البنك";

  const printNow = () => {
    if (!stmt || !valid) return;
    const w = window.open("", "_blank");
    if (!w) return;
    const rowsHtml = stmt.lines.map((l) => `
      <tr>
        <td>${l.entry_id}</td>
        <td>${dateOnly(l.date)}</td>
        <td>${l.description ?? "—"}</td>
        <td>${l.reference ?? "—"}</td>
        <td class="num">${Number(l.debit) ? money(l.debit) : "—"}</td>
        <td class="num">${Number(l.credit) ? money(l.credit) : "—"}</td>
        <td class="num">${money(l.balance)}</td>
      </tr>`).join("");
    w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>كشف معاملات ${entityLabel}</title>
      <style>
        body { font-family: Tahoma, Arial, sans-serif; padding: 16px; }
        h1 { text-align: center; font-size: 20px; }
        h2 { text-align: center; font-weight: normal; font-size: 14px; color: #444; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; }
        th, td { border: 1px solid #999; padding: 6px 8px; text-align: center; font-size: 12px; }
        th { background: #eee; }
        .num { text-align: center; }
        tfoot td { font-weight: bold; background: #f3f4f6; }
      </style></head><body>
      <h1>كشف معاملات ${entityLabel} — ${stmt.account_name}</h1>
      <h2>الفترة: ${from ? dateOnly(from) : "البداية"} — ${to ? dateOnly(to) : dateOnly(today())} · الكود: ${stmt.account_code}</h2>
      <p style="text-align:center; font-size:14px;">رصيد ما قبل الفترة: <b>${money(stmt.opening)}</b> · الرصيد الختامي: <b>${money(stmt.closing)}</b></p>
      <table>
        <thead><tr>
          <th>القيد</th><th>التاريخ</th><th>البيان</th><th>المرجع</th><th>داخل</th><th>خارج</th><th>الرصيد</th>
        </tr></thead>
        <tbody>${rowsHtml || '<tr><td colspan="7">لا توجد حركات في هذه الفترة</td></tr>'}</tbody>
        <tfoot><tr>
          <td colspan="4">الإجمالي</td>
          <td class="num">${money(stmt.total_debit)}</td>
          <td class="num">${money(stmt.total_credit)}</td>
          <td class="num">${money(stmt.closing)}</td>
        </tr></tfoot>
      </table>
      <script>window.onload = () => { window.print(); };</script>
      </body></html>`);
    w.document.close();
  };

  return (
    <Modal title={isSafe ? "🧾 معاملات الخزينة" : "🧾 معاملات البنك"} onClose={onClose} wide>
      <div style={{ marginBottom: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <select value={String(accId)} onChange={(e) => setAccId(e.target.value === "" ? "" : Number(e.target.value))} style={{ flex: 1, minWidth: 180 }}>
          <option value="">— اختر {entityLabel} —</option>
          {(accounts.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <label className="range-field">
          <span className="field-label">من تاريخ</span>
          <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="range-field">
          <span className="field-label">إلى تاريخ</span>
          <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </label>
        <button className="btn" onClick={printNow} disabled={!stmt || !valid}>🖨 طباعة</button>
      </div>
      {!valid && <Alert>تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.</Alert>}
      {stmt && (
        <div className="card card-pad" style={{ marginBottom: 10, display: "flex", gap: 24, flexWrap: "wrap" }}>
          <span>{entityLabel}: <b>{stmt.account_name}</b></span>
          <span>رصيد ما قبل الفترة: <b>{money(stmt.opening)}</b></span>
          <span>الرصيد الختامي: <b>{money(stmt.closing)}</b></span>
        </div>
      )}
      <Alert>{list.error}</Alert>
      <div className="table-wrap">
        {list.loading && accId !== "" && !stmt ? (
          <Loading />
        ) : stmt && stmt.lines.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>القيد</th>
                <th>التاريخ</th>
                <th>البيان</th>
                <th>المرجع</th>
                <th className="num">داخل</th>
                <th className="num">خارج</th>
                <th className="num">الرصيد</th>
              </tr>
            </thead>
            <tbody>
              {stmt.lines.map((l) => (
                <tr key={`${l.entry_id}-${l.date}-${l.debit}-${l.credit}`}>
                  <td dir="ltr">JE-{l.entry_id}</td>
                  <td>{dateOnly(l.date)}</td>
                  <td>{l.description ?? "—"}</td>
                  <td dir="ltr">{l.reference ?? "—"}</td>
                  <td className="num">{Number(l.debit) ? money(l.debit) : "—"}</td>
                  <td className="num">{Number(l.credit) ? money(l.credit) : "—"}</td>
                  <td className="num">{money(l.balance)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={4} className="num">الإجمالي</td>
                <td className="num">{money(stmt.total_debit)}</td>
                <td className="num">{money(stmt.total_credit)}</td>
                <td className="num">{money(stmt.closing)}</td>
              </tr>
            </tfoot>
          </table>
        ) : (
          <Empty>{accId === "" ? `اختر ${entityLabel} وحدد الفترة لعرض معاملاتها.` : "لا توجد معاملات في هذه الفترة."}</Empty>
        )}
      </div>
    </Modal>
  );
}

function DocPreviewModal({ doc, onClose }: { doc: FilterDoc; onClose: () => void }) {
  return (
    <Modal title={`👁️ معاينة — ${doc.title}`} onClose={onClose} wide>
      <h3 style={{ textAlign: "center", margin: "0 0 4px" }}>{doc.title}</h3>
      <p className="muted" style={{ textAlign: "center", marginTop: 0, fontSize: 13 }}>{doc.subtitle}</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>{doc.headers.map((h) => <th key={h}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {doc.rows.length > 0 ? (
              doc.rows.map((r, i) => (
                <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
              ))
            ) : (
              <tr><td colSpan={doc.headers.length}><Empty>لا توجد بيانات</Empty></td></tr>
            )}
          </tbody>
        </table>
      </div>
      <p style={{ textAlign: "center", fontWeight: 700 }}>{doc.totalLabel}: {doc.total}</p>
      <div className="form-actions">
        <button className="btn" onClick={() => printDoc(doc)}>🖨 طباعة</button>
        <button className="btn btn-primary" onClick={onClose}>إغلاق</button>
      </div>
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
  const chargeLabel = kind === "customer" ? "مدين" : "مشتريات (له)";
  const payLabel = kind === "customer" ? "دائن" : "مدفوعات";

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
          <button className="btn btn-sm btn-primary" disabled={download.busy || !valid} onClick={() => void download.run(() => api.printPdf(`${base}/pdf${q}`))}>
            🖨 طباعة
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
  const { t } = useI18n();
  const [showReceiptDialog, setShowReceiptDialog] = useState(false);
  const [showPaymentDialog, setShowPaymentDialog] = useState(false);
  const [chequeDialog, setChequeDialog] = useState<null | ChequeDirection>(null);
  const [showPortfolio, setShowPortfolio] = useState(false);
  const [showSafeBalance, setShowSafeBalance] = useState(false);
  const [txModal, setTxModal] = useState<null | "safe" | "bank">(null);
  // فلاتر السندات والخزينة
  const [docKindV, setDocKindV] = useState<"" | "receipt" | "payment">("");
  const [subTypeV, setSubTypeV] = useState(""); // بند السند
  const [branchFilterV, setBranchFilterV] = useState<number | "">("");
  const [safeFilter, setSafeFilter] = useState<number | "">("");
  const [fromV, setFromV] = useState("");
  const [toV, setToV] = useState("");
  // فلاتر الشيكات والبنوك
  const [docKindC, setDocKindC] = useState<"" | "cheque-received" | "cheque-issued">("");
  const [statusC, setStatusC] = useState<ChequeStatus | "">("");
  const [branchFilterC, setBranchFilterC] = useState<number | "">("");
  const [bankFilter, setBankFilter] = useState<number | "">("");
  const [fromC, setFromC] = useState("");
  const [toC, setToC] = useState("");
  const action = useAction();
  const validV = !fromV || !toV || fromV <= toV;
  const list = usePagedList<Payment>("/payments", validV ? { kind: docKindV, category_id: subTypeV, branch_id: branchFilterV, safe_id: safeFilter, date_from: fromV, date_to: toV } : { kind: docKindV, limit: 1 });
  const filterCategories = useFetch(
    () => (docKindV ? api.get<PaymentCategory[]>(`/payment-categories?kind=${docKindV}`) : Promise.resolve([])),
    `filter-cats-${docKindV}`
  );
  const filterBranchesV = useFetch(() => api.get<{ id: number; name: string; is_active: boolean }[]>("/company/branches"), "filter-branches-v");
  const filterBranchesC = useFetch(() => api.get<{ id: number; name: string; is_active: boolean }[]>("/company/branches"), "filter-branches-c");
  // خزائن الفرع المختار فقط — وكل الفروع لما الفرع «الكل»
  const filterSafes = useFetch(
    () => api.get<{ id: number; name: string; is_active: boolean }[]>(`/safes${branchFilterV ? `?branch_id=${branchFilterV}` : ""}`),
    `filter-safes-${branchFilterV}`
  );
  // بنوك الفرع المختار فقط — وكل الفروع لما الفرع «الكل»
  const filterBanks = useFetch(
    () => api.get<{ id: number; name: string; is_active: boolean }[]>(`/banks${branchFilterC ? `?branch_id=${branchFilterC}` : ""}`),
    `filter-banks-${branchFilterC}`
  );
  const [previewDoc, setPreviewDoc] = useState<FilterDoc | null>(null);
  const runV = useAction(); // معاينة/طباعة كشف السندات
  const runC = useAction(); // معاينة/طباعة كشف الشيكات

  const fetchVoucherDoc = async (): Promise<FilterDoc> => {
    const rows = await api.get<Payment[]>(`/payments?${qs({ kind: docKindV || undefined, category_id: subTypeV || undefined, branch_id: branchFilterV || undefined, safe_id: safeFilter || undefined, date_from: fromV || undefined, date_to: toV || undefined, limit: 500 })}`);
    const catName = docKindV ? (filterCategories.data ?? []).find((c) => String(c.id) === subTypeV)?.name ?? "" : "";
    const branchName = (filterBranchesV.data ?? []).find((b) => String(b.id) === String(branchFilterV))?.name ?? "";
    const safeName = (filterSafes.data ?? []).find((s) => String(s.id) === String(safeFilter))?.name ?? "";
    const total = rows.filter((p) => p.status === "posted").reduce((s, p) => s + Number(p.amount), 0);
    return {
      title: "كشف السندات",
      subtitle: `${docKindV ? (docKindV === "receipt" ? "سند قبض" : "سند صرف") : "كل السندات"} · ${catName ? `البند: ${catName}` : "كل الأنواع"} · ${branchName ? `الفرع: ${branchName}` : "كل الفروع"} · ${safeName ? `الخزينة: ${safeName}` : "كل الخزائن"} · الفترة: ${fromV ? dateOnly(fromV) : "البداية"} — ${toV ? dateOnly(toV) : dateOnly(today())}`,
      headers: ["الرقم", "التاريخ", "النوع", "اسم الفرع", "الطرف", "البند", "المبلغ", "الطريقة", "الحالة"],
      rows: rows.map((p) => [
        `${p.kind === "receipt" ? "RC" : "PY"}-${p.id}`,
        dateOnly(p.paid_on),
        p.kind === "receipt" ? "قبض" : "دفع",
        p.safe_branch_name ?? "—",
        p.party_name ?? "—",
        p.category_name ?? "—",
        money(p.amount),
        METHOD_LABEL[p.method],
        p.status === "posted" ? "مرحّل" : "ملغى",
      ]),
      totalLabel: "إجمالي مبالغ السندات المرحّلة",
      total: money(total),
    };
  };

  const fetchChequeDoc = async (): Promise<FilterDoc> => {
    const rows = await api.get<Cheque[]>(`/cheques?${qs({ direction: docKindC === "cheque-received" ? "received" : docKindC === "cheque-issued" ? "issued" : undefined, status: statusC || undefined, bank_id: bankFilter || undefined, branch_id: branchFilterC || undefined, date_from: fromC || undefined, date_to: toC || undefined })}`);
    const statusName = statusC ? CHEQUE_STATUS_LABEL[statusC] : "";
    const branchName = (filterBranchesC.data ?? []).find((b) => String(b.id) === String(branchFilterC))?.name ?? "";
    const bankName = (filterBanks.data ?? []).find((b) => String(b.id) === String(bankFilter))?.name ?? "";
    const total = rows.reduce((s, c) => s + Number(c.amount), 0);
    return {
      title: "كشف الشيكات",
      subtitle: `${docKindC ? (docKindC === "cheque-received" ? "شيكات مقبوضة" : "شيكات مصروفة") : "كل الشيكات"} · ${statusName ? `الحالة: ${statusName}` : "كل الحالات"} · ${branchName ? `الفرع: ${branchName}` : "كل الفروع"} · ${bankName ? `البنك: ${bankName}` : "كل البنوك"} · الفترة: ${fromC ? dateOnly(fromC) : "البداية"} — ${toC ? dateOnly(toC) : dateOnly(today())}`,
      headers: ["الرقم", "الاتجاه", "اسم الفرع", "رقم الشيك", "البنك", "الطرف", "تاريخ الشيك", "الاستحقاق", "المبلغ", "الحالة"],
      rows: rows.map((c) => [
        `${c.direction === "received" ? "IN" : "OUT"}-${c.id}`,
        c.direction === "received" ? "مقبوض" : "مصروف",
        c.bank_branch_name ?? "—",
        c.number,
        c.bank_name ?? "—",
        c.party_name ?? "—",
        dateOnly(c.cheque_date),
        c.due_date ? dateOnly(c.due_date) : "—",
        money(c.amount),
        CHEQUE_STATUS_LABEL[c.status],
      ]),
      totalLabel: "عدد الشيكات / إجمالي المبالغ",
      total: `${rows.length} · ${money(total)}`,
    };
  };

  const voidIt = (p: Payment) => {
    if (!confirm(`إلغاء ${p.kind === "receipt" ? "سند القبض" : "سند الدفع"} RC/PY-${p.id} بمبلغ ${money(p.amount)}؟ لا يمكن التراجع.`)) return;
    void action.run(async () => {
      await api.post(`/payments/${p.id}/void`);
      list.reload();
    });
  };

  return (
    <>
      <PageHeader title={t("accounts.title")} />
      <div className="card" style={{ padding: 14, marginBottom: 16, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-primary" style={{ minWidth: 160, textAlign: "center" }} onClick={() => setShowReceiptDialog(true)}>+ {t("accounts.receipt")}</button>
          <button className="btn btn-primary" style={{ minWidth: 160, textAlign: "center" }} onClick={() => setShowPaymentDialog(true)}>+ {t("accounts.payment")}</button>
          <button className="btn" style={{ minWidth: 160, textAlign: "center" }} onClick={() => setTxModal("safe")}>🧾 معاملات الخزينة</button>
          <button className="btn" style={{ minWidth: 160, textAlign: "center" }} onClick={() => setShowSafeBalance(true)}>💰 رصيد الخزينة</button>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-primary" style={{ minWidth: 160, textAlign: "center" }} onClick={() => setChequeDialog("received")}>+ استلام شيك</button>
          <button className="btn btn-primary" style={{ minWidth: 160, textAlign: "center" }} onClick={() => setChequeDialog("issued")}>+ صرف شيك</button>
          <button className="btn" style={{ minWidth: 160, textAlign: "center" }} onClick={() => setTxModal("bank")}>🧾 معاملات البنك</button>
          <button className="btn" style={{ minWidth: 160, textAlign: "center" }} onClick={() => setShowPortfolio(true)}>📁 حافظة الشيكات</button>
        </div>
      </div>
      {/* تصنيفات الخزينة — إطار مستقل */}
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 style={{ margin: "0 0 12px", fontSize: 16 }}>🗂️ تصنيفات الخزينة</h3>
        <div className="range-bar" style={{ marginBottom: 12, flexWrap: "wrap", gap: 10 }}>
        <label className="range-field">
          <span className="field-label">السند</span>
          <select value={docKindV} onChange={(e) => { setDocKindV(e.target.value as typeof docKindV); setSubTypeV(""); }}>
            <option value="">الكل</option>
            <option value="receipt">سند قبض</option>
            <option value="payment">سند صرف</option>
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">نوع السند</span>
          <select value={subTypeV} onChange={(e) => setSubTypeV(e.target.value)} disabled={docKindV === ""}>
            {docKindV === "" ? (
              <option value="">—</option>
            ) : (
              <>
                <option value="">الكل</option>
                {(filterCategories.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </>
            )}
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">اسم الفرع</span>
          <select value={String(branchFilterV)} onChange={(e) => { setBranchFilterV(e.target.value === "" ? "" : Number(e.target.value)); setSafeFilter(""); }}>
            <option value="">الكل</option>
            {(filterBranchesV.data ?? []).map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">اسم الخزينة</span>
          <select value={String(safeFilter)} onChange={(e) => setSafeFilter(e.target.value === "" ? "" : Number(e.target.value))}>
            <option value="">الكل</option>
            {(filterSafes.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">من تاريخ</span>
          <input type="date" value={fromV} max={toV || undefined} onChange={(e) => setFromV(e.target.value)} />
        </label>
        <label className="range-field">
          <span className="field-label">إلى تاريخ</span>
          <input type="date" value={toV} min={fromV || undefined} onChange={(e) => setToV(e.target.value)} />
        </label>
        </div>
        <div className="range-bar" style={{ marginBottom: 12, flexWrap: "wrap", gap: 10, alignItems: "flex-end" }}>
        <div style={{ display: "flex", gap: 6, marginInlineStart: "auto" }}>
          <button className="btn" onClick={() => void runV.run(async () => setPreviewDoc(await fetchVoucherDoc()))} disabled={runV.busy}>👁️ معاينة</button>
          <button className="btn" onClick={() => void runV.run(async () => printDoc(await fetchVoucherDoc()))} disabled={runV.busy}>🖨 طباعة</button>
        </div>
        </div>
        {!validV && <Alert>تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.</Alert>}
        <Alert>{list.error || action.error || runV.error}</Alert>

        <div className="table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
              <thead>
              <tr>
                <th>الرقم</th>
                <th>التاريخ</th>
                <th>النوع</th>
                <th>اسم الفرع</th>
                <th>الطرف</th>
                <th>البند</th>
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
                  <td>{p.safe_branch_name ?? "—"}</td>
                  <td>{p.party_name ?? "—"}</td>
                  <td>{p.category_name ?? "—"}</td>
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
      </div>

      {/* تصنيفات البنك — إطار مستقل */}
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 style={{ margin: "0 0 12px", fontSize: 16 }}>🗂️ تصنيفات البنك</h3>
        <div className="range-bar" style={{ marginBottom: 12, flexWrap: "wrap", gap: 10 }}>
        <label className="range-field">
          <span className="field-label">السند</span>
          <select value={docKindC} onChange={(e) => { setDocKindC(e.target.value as typeof docKindC); setStatusC(""); }}>
            <option value="">الكل</option>
            <option value="cheque-received">استلام شيك</option>
            <option value="cheque-issued">صرف شيك</option>
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">نوع السند</span>
          <select value={statusC} onChange={(e) => setStatusC(e.target.value as ChequeStatus | "")} disabled={docKindC === ""}>
            {docKindC === "" ? (
              <option value="">—</option>
            ) : (
              <>
                <option value="">الكل</option>
                {((docKindC === "cheque-received" ? ["under_collection", "collected", "returned"] : ["issued", "cashed", "returned"]) as ChequeStatus[]).map((s) => (
                  <option key={s} value={s}>{CHEQUE_STATUS_LABEL[s]}</option>
                ))}
              </>
            )}
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">اسم الفرع</span>
          <select value={String(branchFilterC)} onChange={(e) => { setBranchFilterC(e.target.value === "" ? "" : Number(e.target.value)); setBankFilter(""); }}>
            <option value="">الكل</option>
            {(filterBranchesC.data ?? []).map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">اسم البنك</span>
          <select value={String(bankFilter)} onChange={(e) => setBankFilter(e.target.value === "" ? "" : Number(e.target.value))}>
            <option value="">الكل</option>
            {(filterBanks.data ?? []).map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">من تاريخ</span>
          <input type="date" value={fromC} max={toC || undefined} onChange={(e) => setFromC(e.target.value)} />
        </label>
        <label className="range-field">
          <span className="field-label">إلى تاريخ</span>
          <input type="date" value={toC} min={fromC || undefined} onChange={(e) => setToC(e.target.value)} />
        </label>
        </div>
        <div className="range-bar" style={{ marginBottom: 12, flexWrap: "wrap", gap: 10, alignItems: "flex-end" }}>
        <div style={{ display: "flex", gap: 6, marginInlineStart: "auto" }}>
          <button className="btn" onClick={() => void runC.run(async () => setPreviewDoc(await fetchChequeDoc()))} disabled={runC.busy}>👁️ معاينة</button>
          <button className="btn" onClick={() => void runC.run(async () => printDoc(await fetchChequeDoc()))} disabled={runC.busy}>🖨 طباعة</button>
        </div>
        </div>
        <Alert>{runC.error}</Alert>
        <ChequesTable
          direction={docKindC === "cheque-received" ? "received" : docKindC === "cheque-issued" ? "issued" : ""}
          status={statusC}
          bankId={bankFilter}
          branchId={branchFilterC}
          dateFrom={fromC}
          dateTo={toC}
          onChanged={() => {}}
        />
      </div>
      {showReceiptDialog && (
        <PaymentDialog kind="customer" onClose={() => setShowReceiptDialog(false)} onSaved={() => { setShowReceiptDialog(false); list.reload(); }} />
      )}
      {showPaymentDialog && (
        <PaymentDialog kind="supplier" onClose={() => setShowPaymentDialog(false)} onSaved={() => { setShowPaymentDialog(false); list.reload(); }} />
      )}
      {chequeDialog && (
        <ChequeDialog direction={chequeDialog} onClose={() => setChequeDialog(null)} onSaved={() => { setChequeDialog(null); list.reload(); }} />
      )}
      {showPortfolio && (
        <PortfolioModal onClose={() => setShowPortfolio(false)} onChanged={() => list.reload()} />
      )}
      {showSafeBalance && (
        <SafeBalanceModal onClose={() => setShowSafeBalance(false)} />
      )}
      {txModal && (
        <AccountTransactionsModal kind={txModal} onClose={() => setTxModal(null)} />
      )}
      {previewDoc && (
        <DocPreviewModal doc={previewDoc} onClose={() => setPreviewDoc(null)} />
      )}
    </>
  );
}
