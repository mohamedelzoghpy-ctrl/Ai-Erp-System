import { useState, useRef, useEffect, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { money } from "../format";
import { useAction, useFetch } from "../hooks";
import type { BankRecSummary, BankStatementLine, ChartAccount, CostCenter, FiscalYear, FixedAsset, JournalEntry, ReconcileOut, RecurringJournal } from "../types";
import { ActiveBadge, Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

type Tab = "coa" | "journals" | "ledger" | "costcenters" | "fiscalyears" | "fixedassets" | "reports" | "reconcile" | "recurring" | "bankrec";

const TABS: { key: Tab; label: string }[] = [
  { key: "coa", label: "شجرة الحسابات" },
  { key: "journals", label: "القيود" },
  { key: "ledger", label: "دفتر الأستاذ" },
  { key: "costcenters", label: "مراكز التكلفة" },
  { key: "fiscalyears", label: "السنوات المالية" },
  { key: "fixedassets", label: "الأصول" },
  { key: "reports", label: "التقارير" },
  { key: "reconcile", label: "مطابقة الأرصدة" },
  { key: "recurring", label: "قيود متكررة" },
  { key: "bankrec", label: "مطابقة بنكية" },
];

// ============================================================ CoA tab
function CoaTab() {
  const accounts = useFetch(() => api.get<ChartAccount[]>("/chart-of-accounts"), "coa");
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current) return;
    if (accounts.loading) return;
    if (accounts.data && accounts.data.length > 0) {
      // still backfill links once
      seededRef.current = true;
      api.post("/chart-of-accounts/backfill-links", {}).catch(() => {});
      return;
    }
    seededRef.current = true;
    api.post("/chart-of-accounts/seed", {}).then(() => {
      api.post("/chart-of-accounts/backfill-links", {}).catch(() => {});
      accounts.reload();
    }).catch(() => {});
  }, [accounts.loading, accounts.data]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<ChartAccount | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({ code: "", name: "", type: "asset", parent_id: "", is_group: false, is_active: true });

  const openCreate = () => {
    setEditing(null);
    setForm({ code: "", name: "", type: "asset", parent_id: "", is_group: false, is_active: true });
    setOpen(true);
    setError(null);
  };
  const openEdit = (a: ChartAccount) => {
    setEditing(a);
    setForm({ code: a.code, name: a.name, type: a.type, parent_id: a.parent_id ? String(a.parent_id) : "", is_group: a.is_group, is_active: a.is_active });
    setOpen(true);
    setError(null);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload: any = {
        code: form.code.trim() || undefined,
        name: form.name.trim(),
        type: form.type,
        is_group: form.is_group,
        is_active: form.is_active,
        parent_id: form.parent_id ? Number(form.parent_id) : null,
      };
      if (editing) await api.put(`/chart-of-accounts/${editing.id}`, payload);
      else await api.post("/chart-of-accounts", payload);
      setOpen(false);
      accounts.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (a: ChartAccount) => {
    if (!confirm(`حذف الحساب "${a.name}"؟`)) return;
    try {
      await api.del(`/chart-of-accounts/${a.id}`);
      accounts.reload();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const list = accounts.data ?? [];
  const byId = new Map(list.map((a) => [a.id, a]));

  return (
    <>
      <div className="page-actions" style={{ marginBottom: 12, gap: 8 }}>
        <button className="btn btn-primary" onClick={openCreate}>+ إضافة حساب</button>
        <div style={{ display: "inline-flex", gap: 6, padding: 4, background: "var(--bg, #f1f5f9)", borderRadius: 8, border: "1px solid var(--border)" }}>
          <button
            className="btn btn-sm"
            title="توليد شجرة حسابات افتراضية (71 حساب) — idempotent"
            style={{ background: "transparent", border: "none" }}
            onClick={() => api.post("/chart-of-accounts/seed", {}).then((r: any) => { alert(`تم توليد ${r?.created ?? 0} حساب`); accounts.reload(); }).catch((e) => alert((e as Error).message))}
          >
            🌱 توليد افتراضية
          </button>
          <span style={{ width: 1, background: "var(--border)", margin: "2px 0" }} />
          <button
            className="btn btn-sm"
            title="ربط الكيانات القديمة (safes/banks/suppliers/customers) بالحسابات"
            style={{ background: "transparent", border: "none" }}
            onClick={() => api.post("/chart-of-accounts/backfill-links", {}).then((r: any) => { alert(`تم ربط ${r?.linked ?? 0} كيان`); accounts.reload(); }).catch((e) => alert((e as Error).message))}
          >
            🔗 ربط الكيانات
          </button>
        </div>
      </div>
      <Alert>{accounts.error}</Alert>
      {accounts.loading && !list.length ? <Loading /> : list.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>الكود</th><th>الاسم</th><th>النوع</th><th>الأب</th><th>المجموعة</th><th>الرصيد</th><th>الحالة</th><th></th>
              </tr>
            </thead>
            <tbody>
              {list.map((a) => (
                <tr key={a.id}>
                  <td dir="ltr">{a.code}</td>
                  <td>{a.name}</td>
                  <td>{a.type}</td>
                  <td>{a.parent_id ? byId.get(a.parent_id)?.name ?? a.parent_id : "—"}</td>
                  <td>{a.is_group ? "نعم" : "لا"}</td>
                  <td className="num">{money(a.balance)}</td>
                  <td><ActiveBadge active={a.is_active} /></td>
                  <td>
                    <button className="btn-edit" onClick={() => openEdit(a)}>تعديل</button>{" "}
                    <button className="btn-delete" onClick={() => remove(a)}>حذف</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>لا توجد حسابات</Empty>}

      {open && (
        <Modal title={editing ? "تعديل حساب" : "إضافة حساب"} onClose={() => setOpen(false)}>
          <form onSubmit={submit}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="الكود" hint="اتركه فارغًا → توليد تلقائي حسب النوع">
                <input dir="ltr" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
              </Field>
              <Field label="الاسم">
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </Field>
            </div>
            <div className="form-grid">
              <Field label="النوع">
                <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                  <option value="asset">asset</option>
                  <option value="liability">liability</option>
                  <option value="equity">equity</option>
                  <option value="revenue">revenue</option>
                  <option value="expense">expense</option>
                </select>
              </Field>
              <Field label="الحساب الأب">
                <select value={form.parent_id} onChange={(e) => setForm({ ...form, parent_id: e.target.value })}>
                  <option value="">— بدون —</option>
                  {list.map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
                </select>
              </Field>
            </div>
            <div className="form-grid">
              <Field label="مجموعة (group)">
                <input type="checkbox" checked={form.is_group} onChange={(e) => setForm({ ...form, is_group: e.target.checked })} />
              </Field>
              <Field label="active">
                <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
              </Field>
            </div>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={busy}>{busy ? "..." : "حفظ"}</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>إلغاء</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

// ============================================================ Cost Centers tab
function CostCentersTab() {
  const cc = useFetch(() => api.get<CostCenter[]>("/cost-centers"), "cc");
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current) return;
    if (cc.loading) return;
    if (cc.data && cc.data.length > 0) return;
    seededRef.current = true;
    api.post("/chart-of-accounts/backfill-links", {}).then(() => cc.reload()).catch(() => {});
  }, [cc.loading, cc.data]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ code: "", name: "", is_active: true });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.post("/cost-centers", { code: form.code.trim() || undefined, name: form.name.trim(), is_active: form.is_active });
      setOpen(false);
      cc.reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const remove = async (c: CostCenter) => {
    if (!confirm(`حذف "${c.name}"؟`)) return;
    try { await api.del(`/cost-centers/${c.id}`); cc.reload(); } catch (e) { alert((e as Error).message); }
  };
  const list = cc.data ?? [];
  return (
    <>
      <div className="page-actions" style={{ marginBottom: 12 }}>
        <button className="btn btn-primary" onClick={() => { setForm({ code: "", name: "", is_active: true }); setOpen(true); setError(null); }}>+ إضافة مركز تكلفة</button>
      </div>
      <Alert>{cc.error}</Alert>
      {cc.loading && !list.length ? <Loading /> : list.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>الكود</th><th>الاسم</th><th>الحالة</th><th></th></tr></thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id}>
                  <td dir="ltr">{c.code}</td><td>{c.name}</td><td><ActiveBadge active={c.is_active} /></td>
                  <td><button className="btn-delete" onClick={() => remove(c)}>حذف</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>لا توجد مراكز تكلفة</Empty>}
      {open && (
        <Modal title="إضافة مركز تكلفة" onClose={() => setOpen(false)}>
          <form onSubmit={submit}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="الكود" hint="اتركه فارغًا للتوليد التلقائي"><input dir="ltr" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
              <Field label="الاسم"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
            </div>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={busy}>{busy ? "..." : "حفظ"}</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>إلغاء</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

// ============================================================ Fiscal Years tab
function FiscalYearsTab() {
  const fy = useFetch(() => api.get<FiscalYear[]>("/fiscal-years"), "fy");
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current) return;
    if (fy.loading) return;
    if (fy.data && fy.data.length > 0) return;
    seededRef.current = true;
    api.post("/chart-of-accounts/backfill-links", {}).then(() => fy.reload()).catch(() => {});
  }, [fy.loading, fy.data]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", start_date: "", end_date: "", is_closed: false });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.post("/fiscal-years", { name: form.name.trim(), start_date: form.start_date, end_date: form.end_date, is_closed: form.is_closed });
      setOpen(false);
      fy.reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const remove = async (f: FiscalYear) => {
    if (!confirm(`حذف "${f.name}"؟`)) return;
    try { await api.del(`/fiscal-years/${f.id}`); fy.reload(); } catch (e) { alert((e as Error).message); }
  };
  const toggleClosed = async (f: FiscalYear) => {
    try { await api.patch(`/fiscal-years/${f.id}`, { is_closed: !f.is_closed }); fy.reload(); } catch (e) { alert((e as Error).message); }
  };
  const list = fy.data ?? [];
  return (
    <>
      <div className="page-actions" style={{ marginBottom: 12 }}>
        <button className="btn btn-primary" onClick={() => { setForm({ name: "", start_date: "", end_date: "", is_closed: false }); setOpen(true); setError(null); }}>+ إضافة سنة مالية</button>
      </div>
      <Alert>{fy.error}</Alert>
      {fy.loading && !list.length ? <Loading /> : list.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>الاسم</th><th>البداية</th><th>النهاية</th><th>مغلقة</th><th></th></tr></thead>
            <tbody>
              {list.map((f) => (
                <tr key={f.id}>
                  <td>{f.name}</td><td>{f.start_date}</td><td>{f.end_date}</td>
                  <td>{f.is_closed ? "نعم" : "لا"}</td>
                  <td>
                    <button className="btn btn-sm" onClick={() => toggleClosed(f)}>{f.is_closed ? "فتح" : "إغلاق"}</button>{" "}
                    <button className="btn-delete" onClick={() => remove(f)}>حذف</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>لا توجد سنوات مالية</Empty>}
      {open && (
        <Modal title="إضافة سنة مالية" onClose={() => setOpen(false)}>
          <form onSubmit={submit}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="الاسم"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
              <Field label="البداية"><input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} required /></Field>
              <Field label="النهاية"><input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} required /></Field>
            </div>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={busy}>{busy ? "..." : "حفظ"}</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>إلغاء</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

// ============================================================ Fixed Assets tab
function FixedAssetsTab() {
  const fa = useFetch(() => api.get<FixedAsset[]>("/fixed-assets"), "fa");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ code: "", name: "", asset_type: "", purchase_date: "", cost: "", current_book_value: "", depreciation_method: "", useful_life_years: "", salvage_value: "0" });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.post("/fixed-assets", {
        code: form.code.trim() || undefined,
        name: form.name.trim(),
        asset_type: form.asset_type.trim(),
        purchase_date: form.purchase_date,
        cost: form.cost,
        current_book_value: form.current_book_value || form.cost,
        depreciation_method: form.depreciation_method.trim(),
        useful_life_years: Number(form.useful_life_years),
        salvage_value: form.salvage_value || "0",
      });
      setOpen(false);
      fa.reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const remove = async (a: FixedAsset) => {
    if (!confirm(`حذف "${a.name}"؟`)) return;
    try { await api.del(`/fixed-assets/${a.id}`); fa.reload(); } catch (e) { alert((e as Error).message); }
  };
  const depreciate = async (a: FixedAsset) => {
    const input = prompt(`مبلغ الإهلاك لـ "${a.name}" (القيمة الدفترية: ${money(a.current_book_value)}):`, "0.00");
    if (input === null) return;
    const amount = Number(input);
    if (!amount || amount <= 0) { alert("أدخل مبلغًا موجبًا"); return; }
    try { await api.post(`/fixed-assets/${a.id}/depreciate`, { amount: String(amount) }); fa.reload(); } catch (e) { alert((e as Error).message); }
  };
  const dispose = async (a: FixedAsset) => {
    const input = prompt(`عائدات بيع "${a.name}" (القيمة الدفترية: ${money(a.current_book_value)}). اكتب 0 للاستبعاد بالكتابة:`, "0.00");
    if (input === null) return;
    const proceeds = Number(input);
    if (isNaN(proceeds) || proceeds < 0) { alert("أدخل مبلغًا صحيحًا"); return; }
    if (!confirm(`تأكيد استبعاد "${a.name}"؟ سيُرحّل قيد الاستبعاد ولا يمكن التراجع.`)) return;
    try { await api.post(`/fixed-assets/${a.id}/dispose`, { disposal_proceeds: String(proceeds) }); fa.reload(); } catch (e) { alert((e as Error).message); }
  };
  const list = fa.data ?? [];
  return (
    <>
      <div className="page-actions" style={{ marginBottom: 12 }}>
        <button className="btn btn-primary" onClick={() => { setForm({ code: "", name: "", asset_type: "", purchase_date: "", cost: "", current_book_value: "", depreciation_method: "", useful_life_years: "", salvage_value: "0" }); setOpen(true); setError(null); }}>+ إضافة أصل</button>
        <button className="btn" onClick={async () => {
          if (!confirm("ترحيل الإهلاك الشهري المجمع لكل الأصول النشطة (قسط ثابت)؟")) return;
          try {
            const r: any = await api.post("/fixed-assets/depreciate-all", {});
            alert(r?.assets ? `تم ترحيل إهلاك ${r.assets} أصل بإجمالي ${money(r.total)}` : "لا أصول مستحقة للإهلاك");
            fa.reload();
          } catch (e) { alert((e as Error).message); }
        }}>🧮 إهلاك الشهر</button>
      </div>
      <Alert>{fa.error}</Alert>
      {fa.loading && !list.length ? <Loading /> : list.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>الكود</th><th>الاسم</th><th>النوع</th><th>التكلفة</th><th>القيمة الدفترية</th><th>العمر</th><th></th></tr></thead>
            <tbody>
              {list.map((a) => (
                <tr key={a.id}>
                  <td dir="ltr">{a.code}</td><td>{a.name}</td><td>{a.asset_type}</td>
                  <td className="num">{money(a.cost)}</td><td className="num">{money(a.current_book_value)}</td>
                  <td className="num">{a.useful_life_years}</td>
                  <td>
                    <button className="btn btn-sm" onClick={() => depreciate(a)} disabled={!a.is_active}>إهلاك</button>{" "}
                    <button className="btn btn-sm" onClick={() => dispose(a)} disabled={!a.is_active}>استبعاد</button>{" "}
                    <button className="btn-delete" onClick={() => remove(a)}>حذف</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>لا توجد أصول</Empty>}
      {open && (
        <Modal title="إضافة أصل" onClose={() => setOpen(false)} wide>
          <form onSubmit={submit}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="الكود" hint="اتركه فارغًا للتوليد التلقائي"><input dir="ltr" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
              <Field label="الاسم"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
              <Field label="نوع الأصل"><input value={form.asset_type} onChange={(e) => setForm({ ...form, asset_type: e.target.value })} required /></Field>
              <Field label="تاريخ الشراء"><input type="date" value={form.purchase_date} onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} required /></Field>
            </div>
            <div className="form-grid">
              <Field label="التكلفة"><input type="number" step="0.01" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} required /></Field>
              <Field label="القيمة الدفترية"><input type="number" step="0.01" value={form.current_book_value} onChange={(e) => setForm({ ...form, current_book_value: e.target.value })} required /></Field>
              <Field label="طريقة الإهلاك"><input value={form.depreciation_method} onChange={(e) => setForm({ ...form, depreciation_method: e.target.value })} required /></Field>
              <Field label="العمر (سنوات)"><input type="number" value={form.useful_life_years} onChange={(e) => setForm({ ...form, useful_life_years: e.target.value })} required /></Field>
              <Field label="القيمة المتبقية"><input type="number" step="0.01" value={form.salvage_value} onChange={(e) => setForm({ ...form, salvage_value: e.target.value })} /></Field>
            </div>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={busy}>{busy ? "..." : "حفظ"}</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>إلغاء</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

// ============================================================ Recurring Journals tab
function RecurringTab() {
  const list = useFetch(() => api.get<RecurringJournal[]>("/recurring-journals"), "recurring");
  const accounts = useFetch(() => api.get<ChartAccount[]>("/chart-of-accounts"), "coa-recurring");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", description: "", reference: "", day_of_month: "1", next_run_date: "" });
  const [items, setItems] = useState([
    { account_id: "", debit: "", credit: "" },
    { account_id: "", debit: "", credit: "" },
  ]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.post("/recurring-journals", {
        name: form.name.trim(),
        description: form.description.trim(),
        reference: form.reference.trim() || null,
        day_of_month: Number(form.day_of_month) || 1,
        next_run_date: form.next_run_date,
        items: items.map((i) => ({
          account_id: Number(i.account_id),
          debit: i.debit || "0",
          credit: i.credit || "0",
        })),
      });
      setOpen(false);
      list.reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const runAll = async () => {
    if (!confirm("ترحيل كل القيود المستحقة؟")) return;
    setBusy(true);
    try {
      const r: any = await api.post("/recurring-journals/run", {});
      alert(`تم ترحيل ${r?.count ?? 0} قيد`);
      list.reload();
    } catch (e) { alert((e as Error).message); }
    finally { setBusy(false); }
  };
  const runOne = async (t: RecurringJournal) => {
    try {
      const r: any = await api.post(`/recurring-journals/run?template_id=${t.id}`, {});
      alert(`تم الترحيل (قيد #${r?.ran?.[0]?.entry_id ?? "—"})`);
      list.reload();
    } catch (e) { alert((e as Error).message); }
  };
  const remove = async (t: RecurringJournal) => {
    if (!confirm(`حذف قالب "${t.name}"؟`)) return;
    try { await api.del(`/recurring-journals/${t.id}`); list.reload(); } catch (e) { alert((e as Error).message); }
  };
  const rows = list.data ?? [];
  const leaves = (accounts.data ?? []).filter((a) => !a.is_group);
  return (
    <>
      <div className="page-actions" style={{ marginBottom: 12 }}>
        <button className="btn btn-primary" onClick={() => { setOpen(true); setError(null); }}>+ قالب متكرر</button>
        <button className="btn" onClick={runAll} disabled={busy}>▶️ ترحيل المستحق الآن</button>
      </div>
      <Alert>{list.error}</Alert>
      {list.loading && !rows.length ? <Loading /> : rows.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>الاسم</th><th>الوصف</th><th>الاستحقاق القادم</th><th>الحالة</th><th></th></tr></thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td>{t.description}{t.reference ? ` · ${t.reference}` : ""}</td>
                  <td dir="ltr">{t.next_run_date}</td>
                  <td><ActiveBadge active={t.is_active} /></td>
                  <td>
                    {t.is_active && new Date(t.next_run_date) <= new Date() && (
                      <button className="btn btn-sm btn-primary" onClick={() => runOne(t)}>ترحيل</button>
                    )}{" "}
                    <button className="btn-delete" onClick={() => remove(t)}>حذف</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>لا توجد قوالب متكررة — أضف إيجارًا أو قسطًا يتكرر شهريًا</Empty>}
      {open && (
        <Modal title="قالب قيد متكرر" onClose={() => setOpen(false)} wide>
          <form onSubmit={submit}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="الاسم"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
              <Field label="الوصف على القيد"><input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} required /></Field>
              <Field label="المرجع"><input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} /></Field>
              <Field label="يوم الاستحقاق (1-28)"><input type="number" min="1" max="28" value={form.day_of_month} onChange={(e) => setForm({ ...form, day_of_month: e.target.value })} /></Field>
              <Field label="أول استحقاق"><input type="date" value={form.next_run_date} onChange={(e) => setForm({ ...form, next_run_date: e.target.value })} required /></Field>
            </div>
            <h4 style={{ margin: "12px 0 6px" }}>البنود (لازم تتوازن)</h4>
            <div className="table-wrap">
              <table>
                <thead><tr><th>الحساب</th><th>مدين</th><th>دائن</th><th></th></tr></thead>
                <tbody>
                  {items.map((it, i) => (
                    <tr key={i}>
                      <td>
                        <select value={it.account_id} onChange={(e) => setItems(items.map((x, ix) => (ix === i ? { ...x, account_id: e.target.value } : x)))} required>
                          <option value="">—</option>
                          {leaves.map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
                        </select>
                      </td>
                      <td><input type="number" step="0.01" value={it.debit} onChange={(e) => setItems(items.map((x, ix) => (ix === i ? { ...x, debit: e.target.value } : x)))} /></td>
                      <td><input type="number" step="0.01" value={it.credit} onChange={(e) => setItems(items.map((x, ix) => (ix === i ? { ...x, credit: e.target.value } : x)))} /></td>
                      <td><button type="button" className="btn btn-sm btn-danger" onClick={() => setItems(items.filter((_, ix) => ix !== i))}>×</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button type="button" className="btn btn-sm" onClick={() => setItems([...items, { account_id: "", debit: "", credit: "" }])}>+ بند</button>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={busy}>{busy ? "..." : "حفظ"}</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>إلغاء</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

// ============================================================ Bank reconciliation tab
function BankRecTab() {
  const banks = useFetch(() => api.get<{ id: number; name: string; balance: number }[]>("/banks"), "banks-rec");
  const [bankId, setBankId] = useState<string>("");
  const lines = useFetch(
    () => (bankId ? api.get<BankStatementLine[]>(`/banks/${bankId}/statements`) : Promise.resolve(null)),
    `bank-lines-${bankId}`,
  );
  const summary = useFetch(
    () => (bankId ? api.get<BankRecSummary>(`/banks/${bankId}/statements/summary`) : Promise.resolve(null)),
    `bank-summary-${bankId}`,
  );
  const importRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);

  const doImport = async (file: File) => {
    if (!bankId) { alert("اختر البنك أولًا"); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r: any = await api.post(`/banks/${bankId}/statements/import`, fd);
      alert(`تم استيراد ${Array.isArray(r) ? r.length : 0} سطر`);
      lines.reload();
      summary.reload();
    } catch (e) { alert((e as Error).message); }
    finally { setBusy(false); }
  };
  const match = async (l: BankStatementLine) => {
    const pid = prompt("رقم السند المطلوب مطابقته (payment id):", l.matched_payment_id ? String(l.matched_payment_id) : "");
    if (pid === null) return;
    try {
      await api.post(`/banks/${bankId}/statements/${l.id}/match`, { payment_id: pid ? Number(pid) : null });
      lines.reload();
      summary.reload();
    } catch (e) { alert((e as Error).message); }
  };
  const rows = (lines.data as BankStatementLine[] | null) ?? [];
  const sm = summary.data as BankRecSummary | null;
  return (
    <>
      <div className="page-actions" style={{ marginBottom: 12, gap: 8 }}>
        <select value={bankId} onChange={(e) => { setBankId(e.target.value); }} style={{ minWidth: 200 }}>
          <option value="">— اختر البنك —</option>
          {(banks.data ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <input ref={importRef} type="file" accept=".csv,text/csv" style={{ display: "none" }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) doImport(f); e.target.value = ""; }} />
        <button className="btn btn-primary" disabled={!bankId || busy} onClick={() => importRef.current?.click()}>⬆️ استيراد كشف CSV</button>
        <button className="btn" disabled={!bankId || busy} onClick={async () => {
          try {
            const r: any = await api.post(`/banks/${bankId}/statements/auto-match`, {});
            alert(`مطابق آليًا: ${r?.matched ?? 0} · غامض: ${r?.ambiguous ?? 0} · بلا مرشح: ${r?.unmatched_left ?? 0}`);
            lines.reload();
            summary.reload();
          } catch (e) { alert((e as Error).message); }
        }}>⚡ مطابقة آلية</button>
      </div>
      {sm && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
          {[
            ["صافي الكشف", money(sm.statement_balance)],
            ["رصيد الدفاتر", money(sm.ledger_balance)],
            ["المطابق", money(sm.matched_total)],
            ["غير مطابق", String(sm.unmatched_count)],
            ["الفرق", money(sm.difference)],
          ].map(([k, v]) => (
            <div key={k} style={{ border: "1px solid var(--border)", borderRadius: 10, padding: "8px 14px" }}>
              <div style={{ fontSize: 12, color: "var(--muted, #64748b)" }}>{k}</div>
              <div className="num" style={{ fontWeight: 700 }}>{v}</div>
            </div>
          ))}
        </div>
      )}
      <Alert>{lines.error}</Alert>
      {!bankId ? <Empty>اختر بنكًا لعرض كشفه المستورد</Empty> : rows.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>التاريخ</th><th>الوصف</th><th>المبلغ</th><th>السند المطابق</th><th></th></tr></thead>
            <tbody>
              {rows.map((l) => (
                <tr key={l.id} style={!l.matched_payment_id ? { background: "rgba(245,158,11,.06)" } : undefined}>
                  <td dir="ltr">{l.value_date}</td>
                  <td>{l.description}</td>
                  <td className="num">{money(l.amount)}</td>
                  <td>{l.matched_payment_id ? `#${l.matched_payment_id}${l.matched_payment_reference ? ` · ${l.matched_payment_reference}` : ""}` : "—"}</td>
                  <td><button className="btn btn-sm" onClick={() => match(l)}>{l.matched_payment_id ? "فك/تعديل" : "مطابقة"}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>لا سطور مستوردة — استورد كشف بنك CSV (date, description, amount)</Empty>}
    </>
  );
}

// ============================================================ Journal Entries tab
function JournalsTab() {
  const je = useFetch(() => api.get<JournalEntry[]>("/journal-entries"), "je");
  const coa = useFetch(() => api.get<ChartAccount[]>("/chart-of-accounts"), "coa2");
  const cc = useFetch(() => api.get<CostCenter[]>("/cost-centers"), "cc2");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ date: "", description: "", reference: "" });
  const [items, setItems] = useState<{ account_id: string; debit: string; credit: string; cost_center_id: string; notes: string }[]>([
    { account_id: "", debit: "", credit: "", cost_center_id: "", notes: "" },
    { account_id: "", debit: "", credit: "", cost_center_id: "", notes: "" },
  ]);

  const addItem = () => setItems([...items, { account_id: "", debit: "", credit: "", cost_center_id: "", notes: "" }]);
  const removeItem = (i: number) => setItems(items.filter((_, idx) => idx !== i));
  const updateItem = (i: number, patch: Partial<typeof items[0]>) => setItems(items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));

  const totalD = items.reduce((s, i) => s + (Number(i.debit) || 0), 0);
  const totalC = items.reduce((s, i) => s + (Number(i.credit) || 0), 0);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.post("/journal-entries", {
        date: form.date || undefined,
        description: form.description.trim(),
        reference: form.reference.trim() || null,
        items: items.map((i) => ({
          account_id: Number(i.account_id),
          debit: i.debit || "0",
          credit: i.credit || "0",
          cost_center_id: i.cost_center_id ? Number(i.cost_center_id) : null,
          notes: i.notes.trim() || null,
        })),
      });
      setOpen(false);
      je.reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const remove = async (j: JournalEntry) => {
    if (!confirm("حذف القيد؟")) return;
    try { await api.del(`/journal-entries/${j.id}`); je.reload(); } catch (e) { alert((e as Error).message); }
  };
  const decide = async (j: JournalEntry, approve: boolean) => {
    if (!confirm(approve ? "اعتماد القيد وترحيل أرصدته؟" : "رفض القيد وحذفه؟")) return;
    try { await api.post(`/journal-entries/${j.id}/${approve ? "approve" : "reject"}`, {}); je.reload(); } catch (e) { alert((e as Error).message); }
  };
  const list = je.data ?? [];
  const accounts = coa.data ?? [];
  const centers = cc.data ?? [];
  return (
    <>
      <div className="page-actions" style={{ marginBottom: 12 }}>
        <button className="btn btn-primary" onClick={() => {
          setForm({ date: "", description: "", reference: "" });
          setItems([{ account_id: "", debit: "", credit: "", cost_center_id: "", notes: "" }, { account_id: "", debit: "", credit: "", cost_center_id: "", notes: "" }]);
          setError(null);
          setOpen(true);
        }}>+ إضافة قيد</button>
      </div>
      <Alert>{je.error}</Alert>
      {je.loading && !list.length ? <Loading /> : list.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>التاريخ</th><th>الوصف</th><th>المرجع</th><th>البنود</th><th></th></tr></thead>
            <tbody>
              {list.map((j) => (
                <tr key={j.id} style={j.status === "pending_approval" ? { background: "rgba(245,158,11,.08)" } : undefined}>
                  <td>{j.id}</td><td>{j.date}</td><td>{j.description}{j.status === "pending_approval" ? " ⏳ بانتظار الاعتماد" : ""}</td><td>{j.reference ?? "—"}</td>
                  <td>{j.items.length}</td>
                  <td>
                    {j.status === "pending_approval" && <button className="btn btn-sm btn-primary" onClick={() => decide(j, true)}>اعتماد ✔</button>}{" "}
                    {j.status === "pending_approval" && <button className="btn btn-sm" onClick={() => decide(j, false)}>رفض ✖</button>}{" "}
                    {j.status !== "pending_approval" && <button className="btn-delete" onClick={() => remove(j)}>حذف</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>لا توجد قيود</Empty>}
      {open && (
        <Modal title="إضافة قيد" onClose={() => setOpen(false)} wide>
          <form onSubmit={submit}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="التاريخ"><input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></Field>
              <Field label="الوصف"><input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} required /></Field>
              <Field label="المرجع"><input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} /></Field>
            </div>
            <h4 style={{ margin: "12px 0 6px" }}>البنود</h4>
            <div className="table-wrap">
              <table>
                <thead><tr><th>الحساب</th><th>مدين</th><th>دائن</th><th>مركز التكلفة</th><th>ملاحظات</th><th></th></tr></thead>
                <tbody>
                  {items.map((it, i) => (
                    <tr key={i}>
                      <td>
                        <select value={it.account_id} onChange={(e) => updateItem(i, { account_id: e.target.value })} required>
                          <option value="">—</option>
                          {accounts.filter((a) => !a.is_group).map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
                        </select>
                      </td>
                      <td><input type="number" step="0.01" value={it.debit} onChange={(e) => updateItem(i, { debit: e.target.value })} /></td>
                      <td><input type="number" step="0.01" value={it.credit} onChange={(e) => updateItem(i, { credit: e.target.value })} /></td>
                      <td>
                        <select value={it.cost_center_id} onChange={(e) => updateItem(i, { cost_center_id: e.target.value })}>
                          <option value="">—</option>
                          {centers.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
                        </select>
                      </td>
                      <td><input value={it.notes} onChange={(e) => updateItem(i, { notes: e.target.value })} /></td>
                      <td><button type="button" className="btn btn-sm btn-danger" onClick={() => removeItem(i)}>×</button></td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td><strong>الإجمالي</strong></td>
                    <td className="num"><strong>{totalD.toFixed(2)}</strong></td>
                    <td className="num"><strong>{totalC.toFixed(2)}</strong></td>
                    <td colSpan={3} className={totalD === totalC ? "" : "low"}>{totalD === totalC ? "متوازن ✓" : "غير متوازن"}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <div className="page-actions" style={{ marginTop: 8 }}>
              <button type="button" className="btn btn-sm" onClick={addItem}>+ بند</button>
            </div>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={busy || totalD !== totalC}>{busy ? "..." : "حفظ"}</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>إلغاء</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

// ============================================================ General Ledger tab
function LedgerTab() {
  const [accountId, setAccountId] = useState("");
  const coa = useFetch(() => api.get<ChartAccount[]>("/chart-of-accounts"), "coa3");
  const url = accountId ? `/general-ledger/account/${accountId}` : "/general-ledger";
  const gl = useFetch(() => api.get<any[]>(url), `gl-${accountId}`);
  const list = gl.data ?? [];
  const accounts = coa.data ?? [];
  return (
    <>
      <div className="page-actions" style={{ marginBottom: 12 }}>
        <Field label="الحساب">
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">— جميع الحسابات —</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
          </select>
        </Field>
      </div>
      <Alert>{gl.error}</Alert>
      {gl.loading && !list.length ? <Loading /> : list.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>التاريخ</th><th>الوصف</th><th>الحساب</th><th>مدين</th><th>دائن</th><th>مركز</th></tr></thead>
            <tbody>
              {list.map((e: any, i: number) => (
                <tr key={i}>
                  <td>{e.date}</td><td>{e.description}</td><td>{e.account_code} — {e.account_name}</td>
                  <td className="num">{money(e.debit)}</td><td className="num">{money(e.credit)}</td>
                  <td>{e.cost_center ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>لا توجد حركات</Empty>}
    </>
  );
}

// ============================================================ Reports tab
function printReport(title: string, bodyHtml: string) {
  const html = `<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><title>${title}</title>
  <style>
    body { font-family: "Segoe UI", Tahoma, Arial, sans-serif; padding: 24px; color: #1c2430; }
    h1 { font-size: 20px; margin-bottom: 4px; }
    .meta { color: #6b7686; font-size: 12px; margin-bottom: 16px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border: 1px solid #cbd5e1; padding: 6px 8px; }
    th { background: #f1f5f9; font-weight: 700; }
    .num { text-align: end; font-variant-numeric: tabular-nums; }
    .section { font-weight: 700; background: #e2e8f0; }
    .total { font-weight: 700; background: #f8fafc; }
    .grand { font-weight: 700; background: #dbeafe; }
    tfoot td { font-weight: 700; }
    @media print { body { padding: 12px; } }
  </style></head><body>
  <h1>${title}</h1>
  <div class="meta">MOZAD ERP — ${new Date().toLocaleString("ar-EG")}</div>
  ${bodyHtml}
  </body></html>`;
  const iframe = document.createElement("iframe");
  iframe.style.position = "fixed";
  iframe.style.right = "0";
  iframe.style.bottom = "0";
  iframe.style.width = "0";
  iframe.style.height = "0";
  iframe.style.border = "none";
  document.body.appendChild(iframe);
  const doc = iframe.contentDocument || iframe.contentWindow?.document;
  if (!doc) { document.body.removeChild(iframe); alert("تعذر الطباعة"); return; }
  doc.open();
  doc.write(html);
  doc.close();
  const win = iframe.contentWindow;
  if (win) {
    win.focus();
    setTimeout(() => { win.print(); }, 300);
  }
  setTimeout(() => { try { document.body.removeChild(iframe); } catch {} }, 60000);
}

function ReportsTab() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [preview, setPreview] = useState<{ title: string; html: string } | null>(null);
  const qs = (p: string) => (from || to) ? `${p}${p.includes("?") ? "&" : "?"}${from ? `date_from=${from}` : ""}${from && to ? "&" : ""}${to ? `date_to=${to}` : ""}` : p;

  const tb = useFetch(() => api.get<any[]>(`/reports/financial/trial-balance${to ? `?as_of=${to}` : ""}`), `tb5-${to}`);
  const pnlDetail = useFetch(() => api.get<any[]>(qs("/reports/financial/profit-loss-detail")), `pd-${from}-${to}`);
  const bs = useFetch(() => api.get<any>(`/reports/financial/balance-sheet${to ? `?as_of=${to}` : ""}`), `bs4-${to}`);
  const vat = useFetch(() => api.get<any>(qs("/reports/financial/vat-return")), `vat-${from}-${to}`);
  const byCC = useFetch(() => api.get<any[]>(qs("/reports/financial/profit-loss-by-cost-center")), `pnl-cc-${from}-${to}`);

  const trial = tb.data ?? [];
  const pnlRows = pnlDetail.data ?? [];

  const revenueRows = pnlRows.filter((r: any) => r.type === "revenue");
  const expenseRows = pnlRows.filter((r: any) => r.type === "expense");
  const assetRows = trial.filter((r: any) => r.type === "asset");
  const liabilityRows = trial.filter((r: any) => r.type === "liability");
  const equityRows = trial.filter((r: any) => r.type === "equity");

  const sumOf = (rows: any[], key = "balance") => rows.reduce((acc: number, r: any) => acc + (Number(r[key] ?? r.balance ?? r.amount) || 0), 0);
  const totalRevenue = revenueRows.reduce((s: number, r: any) => s + (Number(r.amount) || 0), 0);
  const totalExpenses = expenseRows.reduce((s: number, r: any) => s + (Number(r.amount) || 0), 0);
  const netProfit = totalRevenue - totalExpenses;
  const totalAssets = sumOf(assetRows);
  const totalLiabilities = sumOf(liabilityRows);
  const totalEquity = sumOf(equityRows);
  const totalBalance = trial.reduce((acc: number, r: any) => acc + (Number(r.balance) || 0), 0);

  return (
    <>
      <div className="range-bar" style={{ marginBottom: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <label>من تاريخ: <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>إلى تاريخ: <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <button className="btn btn-sm" onClick={() => { setFrom(""); setTo(""); }}>إعادة تعيين</button>
        <button className="btn btn-sm btn-primary" onClick={() => { tb.reload(); pnlDetail.reload(); bs.reload(); }}>تحديث</button>
      </div>

      <div className="card card-pad" style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>🧾 إقرار ضريبة القيمة المضافة{from || to ? ` — ${from || "…"} إلى ${to || "…"}` : ""}</h3>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn btn-sm btn-primary" onClick={() => void api.download(qs("/reports/financial/vat-return/xlsx"), `vat-return-${from || "start"}_${to || "today"}.xlsx`)}>⬇️ Excel</button>
            <button className="btn btn-sm" onClick={() => { vat.reload(); }}>تحديث</button>
          </div>
        </div>
        <Alert>{vat.error}</Alert>
        {vat.loading ? <Loading /> : vat.data ? (
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {[
              ["ضريبة المخرجات (المبيعات)", vat.data.output_vat, "#15803d"],
              ["ضريبة المدخلات (المشتريات)", vat.data.input_vat, "#1f6feb"],
              ["الصافي المستحق للسداد", vat.data.net_payable, Number(vat.data.net_payable) >= 0 ? "#b91c1c" : "#15803d"],
            ].map(([label, value, color]) => (
              <div key={label as string} style={{ flex: "1 1 180px", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 14px" }}>
                <div style={{ fontSize: 12, color: "var(--muted, #64748b)" }}>{label as string}</div>
                <div className="num" style={{ fontWeight: 800, fontSize: 18, color: color as string }}>{money(value as any)}</div>
              </div>
            ))}
          </div>
        ) : <Empty>لا توجد بيانات ضريبية للفترة</Empty>}
      </div>

      <div className="card card-pad" style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>ميزان المراجعة (Trial Balance){to ? ` — حتى ${to}` : ""}</h3>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="btn btn-sm" title="طباعة PDF" onClick={() => void api.printPdf(`/reports/financial/trial-balance/pdf${to ? `?as_of=${to}` : ""}`)}>🖨️ PDF</button>
          <button className="btn btn-sm" onClick={() => {
            const rows = trial.map((r: any) => `<tr><td>${r.code}</td><td>${r.name}</td><td>${r.type}</td><td class="num">${money(r.balance)}</td></tr>`).join("");
            setPreview({ title: "ميزان المراجعة", html: `<table><thead><tr><th>الكود</th><th>الاسم</th><th>النوع</th><th class="num">الرصيد</th></tr></thead><tbody>${rows}</tbody><tfoot><tr><td colspan="3"><strong>المجموع</strong></td><td class="num"><strong>${money(totalBalance)}</strong></td></tr></tfoot></table>` });
          }}>معاينة</button>
        </div>
      </div>
      <Alert>{tb.error}</Alert>
      {tb.loading ? <Loading /> : trial.length ? (
        <div className="table-wrap" style={{ marginBottom: 20 }}>
          <table>
            <thead><tr><th>الكود</th><th>الاسم</th><th>النوع</th><th className="num">الرصيد</th></tr></thead>
            <tbody>
              {trial.map((r: any, i: number) => (
                <tr key={i}><td dir="ltr">{r.code}</td><td>{r.name}</td><td>{r.type}</td><td className="num">{money(r.balance)}</td></tr>
              ))}
            </tbody>
            <tfoot>
              <tr><td colSpan={3}><strong>المجموع</strong></td><td className="num"><strong>{money(totalBalance)}</strong></td></tr>
            </tfoot>
          </table>
        </div>
      ) : <Empty>لا توجد حسابات</Empty>}
      </div>

      <div className="card card-pad" style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>قائمة الدخل (Profit & Loss){from || to ? ` — ${from || "…"} إلى ${to || "…"}` : ""}</h3>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="btn btn-sm" title="طباعة PDF" onClick={() => void api.printPdf(qs("/reports/financial/profit-loss/pdf"))}>🖨️ PDF</button>
          <button className="btn btn-sm" onClick={() => {
            const rev = revenueRows.map((r: any) => `<tr><td>${r.code}</td><td>${r.name}</td><td class="num">${money(r.amount)}</td></tr>`).join("");
            const exp = expenseRows.map((r: any) => `<tr><td>${r.code}</td><td>${r.name}</td><td class="num">${money(r.amount)}</td></tr>`).join("");
            const html = `<table><thead><tr><th>الكود</th><th>الحساب</th><th class="num">المبلغ</th></tr></thead><tbody>
              <tr class="section"><td colspan="3">الإيرادات (Revenue)</td></tr>${rev}
              <tr class="total"><td colspan="2">إجمالي الإيرادات</td><td class="num">${money(totalRevenue)}</td></tr>
              <tr class="section"><td colspan="3">المصاريف (Expenses)</td></tr>${exp}
              <tr class="total"><td colspan="2">إجمالي المصاريف</td><td class="num">${money(totalExpenses)}</td></tr>
            </tbody><tfoot><tr class="grand"><td colspan="2">صافي الربح / (الخسارة)</td><td class="num">${money(netProfit)}</td></tr></tfoot></table>`;
            setPreview({ title: "قائمة الدخل", html });
          }}>معاينة</button>
        </div>
      </div>
      <Alert>{pnlDetail.error}</Alert>
      {pnlDetail.loading ? <Loading /> : pnlRows.length ? (
        <div className="table-wrap" style={{ marginBottom: 20 }}>
          <table>
            <thead><tr><th>الكود</th><th>الحساب</th><th className="num">المبلغ</th></tr></thead>
            <tbody>
              <tr><td colSpan={3} style={{ fontWeight: 700, background: "var(--bg, #f1f5f9)" }}>الإيرادات (Revenue)</td></tr>
              {revenueRows.map((r: any, i: number) => (
                <tr key={`rev-${i}`}><td dir="ltr">{r.code}</td><td>{r.name}</td><td className="num">{money(r.amount)}</td></tr>
              ))}
              <tr style={{ fontWeight: 600 }}><td colSpan={2}>إجمالي الإيرادات</td><td className="num">{money(totalRevenue)}</td></tr>
              <tr><td colSpan={3} style={{ fontWeight: 700, background: "var(--bg, #f1f5f9)" }}>المصاريف (Expenses)</td></tr>
              {expenseRows.map((r: any, i: number) => (
                <tr key={`exp-${i}`}><td dir="ltr">{r.code}</td><td>{r.name}</td><td className="num">{money(r.amount)}</td></tr>
              ))}
              <tr style={{ fontWeight: 600 }}><td colSpan={2}>إجمالي المصاريف</td><td className="num">{money(totalExpenses)}</td></tr>
            </tbody>
            <tfoot>
              <tr style={{ fontWeight: 700 }}><td colSpan={2}>صافي الربح / (الخسارة)</td><td className="num">{money(netProfit)}</td></tr>
            </tfoot>
          </table>
        </div>
      ) : <Empty>لا حركات في هذه الفترة — سجّل دفعة/استلم PO/أكّد SO لتوليد قيود</Empty>}
      </div>

      <div className="card card-pad" style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>🏢 قائمة الدخل حسب مركز التكلفة{from || to ? ` — ${from || "…"} إلى ${to || "…"}` : ""}</h3>
        </div>
        <Alert>{byCC.error}</Alert>
        {byCC.loading ? <Loading /> : (byCC.data ?? []).length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>مركز التكلفة</th><th className="num">الإيرادات</th><th className="num">المصاريف</th><th className="num">الصافي</th></tr></thead>
              <tbody>
                {(byCC.data ?? []).map((r: any) => (
                  <tr key={r.cost_center_id ?? "none"}>
                    <td>{r.name}</td>
                    <td className="num">{money(r.revenue)}</td>
                    <td className="num">{money(r.expenses)}</td>
                    <td className="num" style={{ fontWeight: 700, color: Number(r.net_profit) >= 0 ? "#15803d" : "#b91c1c" }}>{money(r.net_profit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>لا بنود إيراد/مصروف في الفترة</Empty>}
      </div>

      <div className="card card-pad" style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>الميزانية (Balance Sheet){to ? ` — حتى ${to}` : ""}</h3>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="btn btn-sm" title="طباعة PDF" onClick={() => void api.printPdf(`/reports/financial/balance-sheet/pdf${to ? `?as_of=${to}` : ""}`)}>🖨️ PDF</button>
          <button className="btn btn-sm" onClick={() => {
            const ast = assetRows.map((r: any) => `<tr><td>${r.code}</td><td>${r.name}</td><td class="num">${money(r.balance)}</td></tr>`).join("");
            const liab = liabilityRows.map((r: any) => `<tr><td>${r.code}</td><td>${r.name}</td><td class="num">${money(r.balance)}</td></tr>`).join("");
            const eq = equityRows.map((r: any) => `<tr><td>${r.code}</td><td>${r.name}</td><td class="num">${money(r.balance)}</td></tr>`).join("");
            const html = `<table><thead><tr><th>الكود</th><th>الحساب</th><th class="num">المبلغ</th></tr></thead><tbody>
              <tr class="section"><td colspan="3">الأصول (Assets)</td></tr>${ast}
              <tr class="total"><td colspan="2">إجمالي الأصول</td><td class="num">${money(totalAssets)}</td></tr>
              <tr class="section"><td colspan="3">الخصوم (Liabilities)</td></tr>${liab}
              <tr class="total"><td colspan="2">إجمالي الخصوم</td><td class="num">${money(totalLiabilities)}</td></tr>
              <tr class="section"><td colspan="3">حقوق الملكية (Equity)</td></tr>${eq}
              <tr class="total"><td colspan="2">إجمالي حقوق الملكية</td><td class="num">${money(totalEquity)}</td></tr>
            </tbody><tfoot>
              <tr class="grand"><td colspan="2">الخصوم + حقوق الملكية</td><td class="num">${money(totalLiabilities + totalEquity)}</td></tr>
              <tr class="grand"><td colspan="2">متوازنة؟ (Assets = Liab + Equity)</td><td class="num">${totalAssets === totalLiabilities + totalEquity ? "نعم ✓" : "لا ✗"}</td></tr>
            </tfoot></table>`;
            setPreview({ title: "الميزانية", html });
          }}>معاينة</button>
        </div>
      </div>
      <Alert>{bs.error}</Alert>
      {bs.loading ? <Loading /> : bs.data ? (
        <div className="table-wrap" style={{ marginBottom: 20 }}>
          <table>
            <thead><tr><th>الكود</th><th>الحساب</th><th className="num">المبلغ</th></tr></thead>
            <tbody>
              <tr><td colSpan={3} style={{ fontWeight: 700, background: "var(--bg, #f1f5f9)" }}>الأصول (Assets)</td></tr>
              {assetRows.map((r: any, i: number) => (
                <tr key={`ast-${i}`}><td dir="ltr">{r.code}</td><td>{r.name}</td><td className="num">{money(r.balance)}</td></tr>
              ))}
              <tr style={{ fontWeight: 600 }}><td colSpan={2}>إجمالي الأصول</td><td className="num">{money(totalAssets)}</td></tr>
              <tr><td colSpan={3} style={{ fontWeight: 700, background: "var(--bg, #f1f5f9)" }}>الخصوم (Liabilities)</td></tr>
              {liabilityRows.map((r: any, i: number) => (
                <tr key={`liab-${i}`}><td dir="ltr">{r.code}</td><td>{r.name}</td><td className="num">{money(r.balance)}</td></tr>
              ))}
              <tr style={{ fontWeight: 600 }}><td colSpan={2}>إجمالي الخصوم</td><td className="num">{money(totalLiabilities)}</td></tr>
              <tr><td colSpan={3} style={{ fontWeight: 700, background: "var(--bg, #f1f5f9)" }}>حقوق الملكية (Equity)</td></tr>
              {equityRows.map((r: any, i: number) => (
                <tr key={`eq-${i}`}><td dir="ltr">{r.code}</td><td>{r.name}</td><td className="num">{money(r.balance)}</td></tr>
              ))}
              <tr style={{ fontWeight: 600 }}><td colSpan={2}>إجمالي حقوق الملكية</td><td className="num">{money(totalEquity)}</td></tr>
            </tbody>
            <tfoot>
              <tr style={{ fontWeight: 700 }}><td colSpan={2}>الخصوم + حقوق الملكية</td><td className="num">{money(totalLiabilities + totalEquity)}</td></tr>
              <tr style={{ fontWeight: 700, color: totalAssets === totalLiabilities + totalEquity ? "var(--ok, #1a7f4b)" : "var(--danger, #c93c37)" }}>
                <td colSpan={2}>متوازنة؟ (Assets = Liab + Equity)</td>
                <td className="num">{totalAssets === totalLiabilities + totalEquity ? "نعم ✓" : "لا ✗"}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      ) : <Empty>لا بيانات</Empty>}
      </div>
    {preview && (
      <Modal title={preview.title} onClose={() => setPreview(null)} wide>
        <div dangerouslySetInnerHTML={{ __html: preview.html }} />
        <div className="form-actions" style={{ marginTop: 12 }}>
          <button className="btn btn-primary" onClick={() => printReport(preview.title, preview.html)}>طباعة</button>
          <button type="button" className="btn" onClick={() => setPreview(null)}>إغلاق</button>
        </div>
      </Modal>
    )}
    </>
  );
}

// ============================================================ Main page

// ============================================================ Reconcile tab (مطابقة الأرصدة)
function ReconcileTab() {
  const { isManager } = useAuth();
  const report = useFetch(() => api.get<ReconcileOut>("/chart-of-accounts/reconcile"), "reconcile");
  const accounts = useFetch(() => api.get<ChartAccount[]>("/chart-of-accounts"), "reconcile-coa");
  const act = useAction();
  const [applied, setApplied] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [journalOpen, setJournalOpen] = useState(false);
  const [counterId, setCounterId] = useState<string>("");

  // التحديد التلقائي: الحسابات المتنافرة فقط عند كل تحميل
  useEffect(() => {
    if (!report.data) return;
    setSelected(new Set(report.data.lines.filter((l) => Number(l.drift) !== 0).map((l) => l.account_id)));
  }, [report.data]);

  const driftedIds = report.data ? report.data.lines.filter((l) => Number(l.drift) !== 0).map((l) => l.account_id) : [];
  const allDriftedSelected = driftedIds.length > 0 && driftedIds.every((id) => selected.has(id));

  const toggle = (id: number, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const toggleAllDrifted = (checked: boolean) => {
    setSelected(checked ? new Set(driftedIds) : new Set());
  };

  const applyRebuild = () => {
    const ids = [...selected];
    if (!ids.length) return;
    if (!window.confirm(`إعادة بناء الرصيد المخزن لـ ${ids.length} حساب من دفتر الأستاذ؟ الأرصدة الافتتاحية غير المرحلة بقيود ستُمتص.`)) return;
    void act.run(async () => {
      const res = await api.post<ReconcileOut>("/chart-of-accounts/reconcile/apply", { account_ids: ids, mode: "rebuild" });
      setApplied(`تمت إعادة البناء — الحسابات المعدلة: ${res.changed}`);
      report.reload();
    });
  };

  const applyJournal = () => {
    const ids = [...selected];
    if (!ids.length || !counterId) return;
    const counter = counterAccount();
    if (!window.confirm(`ترحيل فروق ${ids.length} حساب كقيد محاسبي موزون على «${counter?.name ?? ""}»؟`)) return;
    void act.run(async () => {
      const res = await api.post<ReconcileOut>("/chart-of-accounts/reconcile/apply", { account_ids: ids, mode: "journal", counter_account_id: Number(counterId) });
      setApplied(`تم الترحيل — الحسابات المعدلة: ${res.changed}${res.journal_entry_id ? ` · قيد رقم ${res.journal_entry_id}` : ""}`);
      setJournalOpen(false);
      report.reload();
    });
  };

  const syncCash = () => {
    if (!window.confirm("مزامنة أرصدة الخزائن والبنوك مع حساباتها المرتبطة في الشجرة؟")) return;
    void act.run(async () => {
      const res = await api.post<{ synced: number }>("/chart-of-accounts/reconcile/sync-cash", {});
      setApplied(`تمت المزامنة — الخزائن/البنوك المحدّثة: ${res.synced}`);
      report.reload();
    });
  };

  const counterCandidates = (accounts.data ?? []).filter((a) => !a.is_group && a.is_active);
  const counterAccount = () => counterCandidates.find((a) => a.id === Number(counterId));

  const driftBadge = (d: string) => {
    const v = Number(d);
    if (v === 0) return <span className="badge badge-confirmed">مطابق</span>;
    return <span className="badge badge-cancelled">{money(d)}</span>;
  };

  return (
    <>
      <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "#fff4d6", color: "#9a6700" }}>
        ℹ️ المطابقة تقارن الرصيد المخزن لكل حساب بصافي بنود دفتر الأستاذ. أي فرق يعني رصيدًا افتتاحيًا زُرع دون قيد أو انحرافًا. اختر الحسابات ثم: «إعادة البناء» تمتص الفرق من الدفتر، أو «ترحيل كقيود» يُثبت الفرق بقيد موزون على حساب مقابل (مثل رأس المال للأرصدة الافتتاحية).
      </div>
      <Alert>{report.error || act.error}</Alert>
      {applied && (
        <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg, #e8f5e9)", color: "var(--ok-fg, #1b5e20)" }}>
          ✓ {applied}
        </div>
      )}
      {report.loading && !report.data ? (
        <Loading />
      ) : report.data ? (
        <>
          {isManager && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              <button className="btn" disabled={act.busy || selected.size === 0} onClick={applyRebuild} title="يكتب الرصيد المخزن من دفتر الأستاذ للحسابات المختارة">
                {act.busy ? "جارٍ التنفيذ…" : `🔧 إعادة البناء من الدفتر (${selected.size})`}
              </button>
              <button className="btn" disabled={act.busy || selected.size === 0} onClick={() => setJournalOpen(true)} title="يرحّل الفرق كقيد محاسبي موزون على حساب مقابل">
                📝 ترحيل الفرق كقيود
              </button>
              <button className="btn btn-secondary" disabled={act.busy} onClick={syncCash} title="يزامن رصيد كل خزينة/بنك مع حسابه المرتبط">
                🔄 مزامنة الخزائن والبنوك
              </button>
            </div>
          )}
          <div className="card table-wrap">
            <table>
              <thead>
                <tr>
                  {isManager && (
                    <th style={{ width: 36 }}>
                      <input type="checkbox" checked={allDriftedSelected} onChange={(e) => toggleAllDrifted(e.target.checked)} title="تحديد كل الحسابات المتنافرة" />
                    </th>
                  )}
                  <th>الكود</th><th>الحساب</th><th>النوع</th><th className="num">الرصيد المخزن</th><th className="num">رصيد الدفتر</th><th className="num">الفرق</th>
                </tr>
              </thead>
              <tbody>
                {report.data.lines.map((l) => {
                  const drifted = Number(l.drift) !== 0;
                  return (
                    <tr key={l.account_id} style={drifted ? { background: "#fff8e1" } : undefined}>
                      {isManager && (
                        <td>
                          <input type="checkbox" checked={selected.has(l.account_id)} disabled={!drifted} onChange={(e) => toggle(l.account_id, e.target.checked)} />
                        </td>
                      )}
                      <td dir="ltr">{l.code}</td>
                      <td>{l.name}</td>
                      <td>{l.type === "asset" ? "أصل" : l.type === "liability" ? "التزام" : l.type === "revenue" ? "إيراد" : l.type === "expense" ? "مصروف" : "حقوق ملكية"}</td>
                      <td className="num">{money(l.stored)}</td>
                      <td className="num">{money(l.ledger)}</td>
                      <td className="num">{driftBadge(String(l.drift))}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr>
                  {isManager && <td />}
                  <td colSpan={3}><strong>الإجمالي</strong></td>
                  <td className="num"><strong>{money(report.data.total_stored)}</strong></td>
                  <td className="num"><strong>{money(report.data.total_ledger)}</strong></td>
                  <td className="num"><strong>{money(report.data.total_drift)}</strong></td>
                </tr>
              </tfoot>
            </table>
          </div>
        </>
      ) : (
        <Loading />
      )}
      {journalOpen && (
        <Modal title="ترحيل الفروق كقيد محاسبي" onClose={() => setJournalOpen(false)}>
          <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "#fff4d6", color: "#9a6700" }}>
            ℹ️ سيُنشأ قيد واحد موزون: سطر لكل حساب مختار بصافي فرقه، وسطر مقابل على الحساب المختار أدناه (للأرصدة الافتتاحية استخدم «رأس المال» 3100).
          </div>
          <Field label="الحساب المقابل">
            <select value={counterId} onChange={(e) => setCounterId(e.target.value)}>
              <option value="">— اختر —</option>
              {counterCandidates.map((a) => (
                <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
              ))}
            </select>
          </Field>
          <div className="form-actions">
            <button className="btn" onClick={() => setJournalOpen(false)}>إلغاء</button>
            <button className="btn btn-primary" disabled={act.busy || !counterId || selected.size === 0} onClick={applyJournal}>
              {act.busy ? "جارٍ الترحيل…" : `ترحيل ${selected.size} حساب`}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

export default function Accounting() {
  const [tab, setTab] = useState<Tab>("coa");

  return (
    <>
      <PageHeader title="المحاسبة" />
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16, borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
        {TABS.map((tb) => (
          <button key={tb.key} type="button" className={`btn btn-sm ${tab === tb.key ? "btn-primary" : ""}`} onClick={() => setTab(tb.key)}>
            {tb.label}
          </button>
        ))}
      </div>
      {tab === "coa" && <CoaTab />}
      {tab === "journals" && <JournalsTab />}
      {tab === "ledger" && <LedgerTab />}
      {tab === "costcenters" && <CostCentersTab />}
      {tab === "fiscalyears" && <FiscalYearsTab />}
      {tab === "fixedassets" && <FixedAssetsTab />}
      {tab === "reports" && <ReportsTab />}
      {tab === "reconcile" && <ReconcileTab />}
      {tab === "recurring" && <RecurringTab />}
      {tab === "bankrec" && <BankRecTab />}
    </>
  );
}
