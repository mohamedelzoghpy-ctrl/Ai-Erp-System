import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useFetch, usePagedList } from "../hooks";
import type { Branch, Order, SalesRep } from "../types";
import { ActiveBadge, Alert, Empty, Field, Loading, Modal, PageHeader, Pager, PaymentBadge, StatusBadge } from "../ui";
import { dateTime, money } from "../format";

/** نسبة العمولة: أرقام و«.» فقط، بأقصى قيمة 100 (مكتوبة أو ملزوقة أثناء الكتابة). */
function normCommission(v: string): string {
  let t = v.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1").replace(/^0+(?=\d)/, "");
  if (t !== "" && Number(t) > 100) t = "100";
  return t;
}

/** مندوبي المبيعات: قائمة مستقلة مع إضافة وتعديل وحذف. */
export default function SalesReps() {
  const reps = useFetch(() => api.get<SalesRep[]>("/reps"), "reps-list");
  const branches = useFetch(() => api.get<Branch[]>("/company/branches"), "reps-branches");

  const [openAdd, setOpenAdd] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [f, setF] = useState({ name: "", phone: "", branch_ids: [] as number[], commission_percent: "" });
  const [editing, setEditing] = useState<SalesRep | null>(null);
  const [ef, setEf] = useState({ name: "", phone: "", branch_ids: [] as number[], commission_percent: "", is_active: true });
  const [confirmDel, setConfirmDel] = useState<SalesRep | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [following, setFollowing] = useState<SalesRep | null>(null);

  const rows = (reps.data ?? []).filter((r) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return r.name.toLowerCase().includes(q) || r.code.toLowerCase().includes(q) || (r.phone ?? "").includes(q);
  });

  const branchName = (id: number) => {
    const b = (branches.data ?? []).find((x) => x.id === id);
    return b ? b.name : `فرع ${id}`;
  };

  const toggleBranch = (list: number[], id: number, setList: (v: number[]) => void) =>
    setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  const submitAdd = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await api.post<SalesRep>("/reps", {
        name: f.name.trim(),
        phone: f.phone.trim() || null,
        branch_ids: f.branch_ids,
        commission_percent: f.commission_percent.trim() === "" ? 0 : Number(f.commission_percent),
      });
      setOpenAdd(false);
      setF({ name: "", phone: "", branch_ids: [], commission_percent: "" });
      setNote(`تم إضافة المندوب «${created.name}» برقم ${created.code}.`);
      reps.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const openEdit = (r: SalesRep) => {
    setEditing(r);
    setEf({
      name: r.name,
      phone: r.phone ?? "",
      branch_ids: [...r.branch_ids],
      commission_percent: String(r.commission_percent),
      is_active: r.is_active,
    });
    setError(null);
  };

  const sameBranches = (a: number[], b: number[]) => a.length === b.length && [...a].sort().every((x, i) => x === [...b].sort()[i]);

  const submitEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setError(null);
    setBusy(true);
    const body: Record<string, unknown> = {};
    if (ef.name.trim() !== editing.name) body.name = ef.name.trim();
    const newPhone = ef.phone.trim() || null;
    if (newPhone !== editing.phone) body.phone = newPhone;
    if (!sameBranches(ef.branch_ids, editing.branch_ids)) body.branch_ids = ef.branch_ids;
    const newComm = ef.commission_percent.trim() === "" ? 0 : Number(ef.commission_percent);
    if (newComm !== Number(editing.commission_percent)) body.commission_percent = newComm;
    if (ef.is_active !== editing.is_active) body.is_active = ef.is_active;
    try {
      if (Object.keys(body).length > 0) await api.patch(`/reps/${editing.id}`, body);
      setEditing(null);
      setNote(`تم تحديث المندوب «${editing.name}».`);
      reps.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async (r: SalesRep) => {
    setDeleting(r.id);
    setError(null);
    try {
      await api.del(`/reps/${r.id}`);
      setConfirmDel(null);
      setNote(`تم حذف المندوب «${r.name}».`);
      reps.reload();
    } catch (err) {
      setConfirmDel(null);
      setError((err as Error).message);
    } finally {
      setDeleting(null);
    }
  };

  return (
    <>
      <PageHeader title="مندوبي المبيعات">
        <button className="btn btn-primary" onClick={() => { setError(null); setOpenAdd(true); }}>
          + إضافة مندوب
        </button>
      </PageHeader>

      <div className="toolbar page-actions" style={{ marginBottom: 14 }}>
        <input placeholder="ابحث بالاسم أو الكود أو التليفون…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      <Alert>{reps.error}</Alert>
      {error && <Alert>{error}</Alert>}
      <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "#fff4d6", color: "#9a6700" }}>
        ℹ️ مندوب المبيعات ليس مستخدماً في النظام: يظهر على فاتورة المبيعات ومرتجع المبيعات وتقارير المبيعات فقط، ولا له حساب دخول أو كلمة مرور أو صلاحيات. أما المستخدمون فلهم حساب للدخول وخصوصيات.
      </div>
      {note && (
        <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg)", color: "var(--ok)" }}>
          {note}
        </div>
      )}

      <div className="card table-wrap">
        {reps.loading && !reps.data ? (
          <Loading />
        ) : rows.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>كود المندوب</th>
                <th>الاسم</th>
                <th>الهاتف</th>
                <th>الفرع</th>
                <th className="num">نسبة العمولة %</th>
                <th>الحالة</th>
                <th>أُنشئ في</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} style={r.is_active ? undefined : { opacity: 0.55 }}>
                  <td className="num-center" dir="ltr">{r.code}</td>
                  <td>{r.name}</td>
                  <td dir="ltr">{r.phone ?? "—"}</td>
                  <td>
                    {r.branch_ids && r.branch_ids.length > 0 ? (
                      <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 4 }}>
                        {r.branch_ids.map((bid) => (
                          <span key={bid} className="badge" style={{ background: "#e3f2fd", color: "#0d47a1", borderRadius: 999, padding: "2px 9px", fontSize: 12 }}>
                            {branchName(bid)}
                          </span>
                        ))}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="num">{r.commission_percent}</td>
                  <td><ActiveBadge active={r.is_active} /></td>
                  <td>{new Date(r.created_at).toLocaleDateString("ar-EG")}</td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => openEdit(r)}>
                      تعديل
                    </button>{" "}
                    <button
                      className="btn btn-sm"
                      style={{ color: "var(--danger)", borderColor: "var(--danger)" }}
                      disabled={deleting === r.id}
                      onClick={() => setConfirmDel(r)}
                    >
                      {deleting === r.id ? "…" : "حذف"}
                    </button>{" "}
                    <button
                      className="btn btn-sm"
                      style={{ color: "#6b21a8", borderColor: "#6b21a8" }}
                      onClick={() => setFollowing(r)}
                    >
                      👁️ مراقبة
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{search ? "لا توجد مندوبين مطابقين." : "لا يوجد مندوبين — اضغط «إضافة مندوب» للبدء."}</Empty>
        )}
      </div>

      {openAdd && (
        <Modal title="إضافة مندوب" onClose={() => setOpenAdd(false)} wide>
          <form onSubmit={submitAdd}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="اسم المندوب">
                <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={150} />
              </Field>
              <Field label="رقم الهاتف">
                <input dir="ltr" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} maxLength={40} placeholder="اختياري" />
              </Field>
            </div>
            <p style={{ margin: "12px 0 4px", fontWeight: 700, fontSize: 13 }}>فروع المندوب (اختيار أكثر من فرع):</p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {(branches.data ?? []).map((b) => (
                <label key={b.id} className="check" style={{ background: f.branch_ids.includes(b.id) ? "#e3f2fd" : undefined, borderRadius: 8, padding: "4px 10px" }}>
                  <input type="checkbox" checked={f.branch_ids.includes(b.id)} onChange={() => toggleBranch(f.branch_ids, b.id, (v) => setF({ ...f, branch_ids: v }))} /> {b.name}
                </label>
              ))}
              {(branches.data ?? []).length === 0 && <span className="muted" style={{ fontSize: 13 }}>لا توجد فروع.</span>}
            </div>
            <Field label="نسبة العمولة %">
              <input dir="ltr" inputMode="decimal" value={f.commission_percent} onChange={(e) => setF({ ...f, commission_percent: normCommission(e.target.value) })} placeholder="0 - 100" />
              <span className="field-hint">من 0 إلى 100 فقط</span>
            </Field>
            <div className="form-actions" style={{ marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy || !f.name.trim()}>
                {busy ? "جارٍ الحفظ…" : "إنشاء المندوب"}
              </button>
              <button type="button" className="btn" onClick={() => setOpenAdd(false)}>
                إلغاء
              </button>
            </div>
          </form>
        </Modal>
      )}

      {editing && (
        <Modal title={`تعديل المندوب — ${editing.name}`} onClose={() => setEditing(null)} wide>
          <form onSubmit={submitEdit}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="اسم المندوب">
                <input value={ef.name} onChange={(e) => setEf({ ...ef, name: e.target.value })} required maxLength={150} />
              </Field>
              <Field label="رقم الهاتف">
                <input dir="ltr" value={ef.phone} onChange={(e) => setEf({ ...ef, phone: e.target.value })} maxLength={40} />
              </Field>
            </div>
            <p style={{ margin: "12px 0 4px", fontWeight: 700, fontSize: 13 }}>فروع المندوب (اختيار أكثر من فرع):</p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {(branches.data ?? []).map((b) => (
                <label key={b.id} className="check" style={{ background: ef.branch_ids.includes(b.id) ? "#e3f2fd" : undefined, borderRadius: 8, padding: "4px 10px" }}>
                  <input type="checkbox" checked={ef.branch_ids.includes(b.id)} onChange={() => toggleBranch(ef.branch_ids, b.id, (v) => setEf({ ...ef, branch_ids: v }))} /> {b.name}
                </label>
              ))}
              {(branches.data ?? []).length === 0 && <span className="muted" style={{ fontSize: 13 }}>لا توجد فروع.</span>}
            </div>
            <Field label="نسبة العمولة %">
              <input dir="ltr" inputMode="decimal" value={ef.commission_percent} onChange={(e) => setEf({ ...ef, commission_percent: normCommission(e.target.value) })} />
              <span className="field-hint">من 0 إلى 100 فقط</span>
            </Field>
            <Field label="الحالة">
              <select value={String(ef.is_active)} onChange={(e) => setEf({ ...ef, is_active: e.target.value === "true" })}>
                <option value="true">نشط</option>
                <option value="false">موقوف</option>
              </select>
            </Field>
            <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
              الكود: {editing.code} — لا يمكن تغييره بعد الإنشاء.
            </p>
            <div className="form-actions" style={{ marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy}>
                {busy ? "جارٍ الحفظ…" : "حفظ التعديلات"}
              </button>
              <button type="button" className="btn" onClick={() => setEditing(null)}>
                إلغاء
              </button>
            </div>
          </form>
        </Modal>
      )}

      {confirmDel && (
        <Modal title={`حذف المندوب — ${confirmDel.name}`} onClose={() => setConfirmDel(null)}>
          <p style={{ margin: "0 0 6px" }}>
            هل أنت متأكد من حذف المندوب <strong>{confirmDel.name}</strong> ({confirmDel.code})؟ لا يمكن الرجوع بعد الحذف.
          </p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn"
              style={{ color: "#fff", background: "var(--danger)" }}
              disabled={deleting !== null}
              onClick={() => void doDelete(confirmDel)}
            >
              {deleting !== null ? "جارٍ الحذف…" : "🗑️ نعم، حذف"}
            </button>
            <button type="button" className="btn" onClick={() => setConfirmDel(null)}>
              إلغاء
            </button>
          </div>
        </Modal>
      )}
      {following && <RepInvoicesModal rep={following} onClose={() => setFollowing(null)} />}
    </>
  );
}

/** متابعة مندوب: الفواتير (أوامر البيع) التي تعامل عليها المندوب. */
function RepInvoicesModal({ rep, onClose }: { rep: SalesRep; onClose: () => void }) {
  const list = usePagedList<Order>("/sales-orders", { rep_id: rep.id });
  return (
    <Modal title={`👁️ مراقبة المندوب — ${rep.name}`} onClose={onClose} wide>
      <p className="muted" style={{ fontSize: 13, margin: "0 0 10px" }}>
        الفواتير التي تعامل عليها <strong>{rep.name}</strong> ({rep.code}) — الإجمالي: {list.total} فاتورة.
      </p>
      <Alert>{list.error}</Alert>
      <div className="table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>رقم الفاتورة</th>
                <th>التاريخ</th>
                <th>العميل</th>
                <th>الحالة</th>
                <th className="num">الإجمالي</th>
                <th>السداد</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((o) => (
                <tr key={o.id}>
                  <td dir="ltr">SO-{o.id}</td>
                  <td>{dateTime(o.created_at)}</td>
                  <td>{o.party_name || "—"}</td>
                  <td><StatusBadge status={o.status} /></td>
                  <td className="num">{money(o.total_amount)}</td>
                  <td><PaymentBadge status={o.payment_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>لا توجد فواتير لهذا المندوب.</Empty>
        )}
      </div>
      <Pager list={list} />
    </Modal>
  );
}
