import { useState, useRef, useEffect, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { money } from "../format";
import { useAction, useFetch } from "../hooks";
import type { ChartAccount, CostCenter, FiscalYear, FixedAsset, JournalEntry, ReconcileOut } from "../types";
import { ActiveBadge, Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

type Tab = "coa" | "journals" | "ledger" | "costcenters" | "fiscalyears" | "fixedassets" | "reports" | "reconcile";

const TABS: { key: Tab; label: string }[] = [
  { key: "coa", label: "شجرة الحسابات" },
  { key: "journals", label: "القيود" },
  { key: "ledger", label: "دفتر الأستاذ" },
  { key: "costcenters", label: "مراكز التكلفة" },
  { key: "fiscalyears", label: "السنوات المالية" },
  { key: "fixedassets", label: "الأصول" },
  { key: "reports", label: "التقارير" },
  { key: "reconcile", label: "مطابقة الأرصدة" },
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
                    <button className="btn btn-sm" onClick={() => openEdit(a)}>تعديل</button>{" "}
                    <button className="btn btn-sm btn-danger" onClick={() => remove(a)}>حذف</button>
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
                  <td><button className="btn btn-sm btn-danger" onClick={() => remove(c)}>حذف</button></td>
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
                    <button className="btn btn-sm btn-danger" onClick={() => remove(f)}>حذف</button>
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
    try { await api.post(`/fixed-assets/${a.id}/depreciate`, {}); fa.reload(); } catch (e) { alert((e as Error).message); }
  };
  const list = fa.data ?? [];
  return (
    <>
      <div className="page-actions" style={{ marginBottom: 12 }}>
        <button className="btn btn-primary" onClick={() => { setForm({ code: "", name: "", asset_type: "", purchase_date: "", cost: "", current_book_value: "", depreciation_method: "", useful_life_years: "", salvage_value: "0" }); setOpen(true); setError(null); }}>+ إضافة أصل</button>
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
                    <button className="btn btn-sm" onClick={() => depreciate(a)}>إهلاك</button>{" "}
                    <button className="btn btn-sm btn-danger" onClick={() => remove(a)}>حذف</button>
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
                <tr key={j.id}>
                  <td>{j.id}</td><td>{j.date}</td><td>{j.description}</td><td>{j.reference ?? "—"}</td>
                  <td>{j.items.length}</td>
                  <td><button className="btn btn-sm btn-danger" onClick={() => remove(j)}>حذف</button></td>
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
                          {accounts.map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
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
        <h3 style={{ margin: 0 }}>ميزان المراجعة (Trial Balance){to ? ` — حتى ${to}` : ""}</h3>
        <div style={{ display: "flex", gap: 6 }}>
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
        <h3 style={{ margin: 0 }}>الميزانية (Balance Sheet){to ? ` — حتى ${to}` : ""}</h3>
        <div style={{ display: "flex", gap: 6 }}>
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
  const act = useAction();
  const [applied, setApplied] = useState<string | null>(null);

  const apply = () => {
    if (!window.confirm("تطبيق التسوية سيُعيد بناء الرصيد المخزن لكل حساب من دفتر الأستاذ. الأرصدة الافتتاحية غير المرحلة بقيود ستُمتص. متابعة؟")) return;
    void act.run(async () => {
      const res = await api.post<ReconcileOut>("/chart-of-accounts/reconcile/apply");
      setApplied(`تمت التسوية — الحسابات المعدلة: ${Number(res.total_drift) !== 0 ? "تم بناء الأرصدة من الدفتر" : res.lines.length}`);
      report.reload();
    });
  };

  const driftBadge = (d: string) => {
    const v = Number(d);
    if (v === 0) return <span className="badge badge-confirmed">مطابق</span>;
    return <span className="badge badge-cancelled">{money(d)}</span>;
  };

  return (
    <>
      <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "#fff4d6", color: "#9a6700" }}>
        ℹ️ المطابقة تقارن الرصيد المخزن لكل حساب بصافي بنود دفتر الأستاذ. أي فرق يظهر هنا يعني رصيدًا افتتاحيًا زُرع دون قيد أو انحرافًا. التسوية تعيد بناء الأرصدة من الدفتر — راجع الفروق قبل التطبيق.
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
          {isManager && Number(report.data.total_drift) !== 0 && (
            <div style={{ marginBottom: 10 }}>
              <button className="btn" style={{ color: "#fff", background: "var(--danger)" }} disabled={act.busy} onClick={apply}>
                {act.busy ? "جارٍ التطبيق…" : "⚡ تطبيق التسوية"}
              </button>
            </div>
          )}
          <div className="card table-wrap">
            <table>
              <thead>
                <tr>
                  <th>الكود</th><th>الحساب</th><th>النوع</th><th className="num">الرصيد المخزن</th><th className="num">رصيد الدفتر</th><th className="num">الفرق</th>
                </tr>
              </thead>
              <tbody>
                {report.data.lines.map((l) => (
                  <tr key={l.account_id} style={Number(l.drift) !== 0 ? { background: "#fff8e1" } : undefined}>
                    <td dir="ltr">{l.code}</td>
                    <td>{l.name}</td>
                    <td>{l.type === "asset" ? "أصل" : l.type === "liability" ? "التزام" : l.type === "revenue" ? "إيراد" : l.type === "expense" ? "مصروف" : "حقوق ملكية"}</td>
                    <td className="num">{money(l.stored)}</td>
                    <td className="num">{money(l.ledger)}</td>
                    <td className="num">{driftBadge(String(l.drift))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <Loading />
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
    </>
  );
}
