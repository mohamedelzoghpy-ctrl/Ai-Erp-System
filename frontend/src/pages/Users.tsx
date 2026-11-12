import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";
import { useAuth } from "../auth";
import { dateTime, num } from "../format";
import { useFetch } from "../hooks";
import type { Branch, Warehouse } from "../types";
import { ActiveBadge, Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

const ROLE_LABEL: Record<string, { ar: string; en: string }> = {
  admin: { ar: "مدير عام", en: "Admin" },
  manager: { ar: "مدير", en: "Manager" },
  staff: { ar: "موظف", en: "Staff" },
};
const ROLE_STYLE: Record<string, { background: string; color: string }> = {
  admin: { background: "#f3e8ff", color: "#6b21a8" },
  manager: { background: "#e3f2fd", color: "#0d47a1" },
  staff: { background: "#efeef4", color: "#444" },
};

interface UserRow {
  id: number;
  username: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  is_platform_admin: boolean;
  created_at: string;
  branch_ids: number[];
  warehouse_ids: number[];
}

interface ActivityData {
  username: string;
  full_name: string | null;
  first_login: string | null;
  last_login: string | null;
  login_count: number;
  total: number;
  logs: { id: number; created_at: string; action: string; entity: string; entity_id: number | null; summary: string | null }[];
}

const MON_ACTION: Record<string, string> = {
  create: "إنشاء",
  update: "تعديل",
  delete: "حذف",
  receive: "استلام",
  confirm: "تأكيد",
  cancel: "إلغاء",
  void: "إلغاء سند",
  adjust_stock: "تسوية مخزون",
  opening_balance: "تغيير رصيد أول المدة",
  login: "تسجيل دخول",
  open: "فتح",
  apply: "اعتماد",
  close: "إغلاق",
};

const MON_ENTITY: Record<string, string> = {
  purchase_order: "أمر شراء",
  sales_order: "أمر بيع",
  payment: "سند",
  product: "منتج",
  customer: "عميل",
  supplier: "مورد",
  warehouse: "مخزن",
  user: "مستخدم",
  shift: "وردية",
  stocktake: "جرد",
  stock_transfer: "تحويل مخزني",
  sales_rep: "مندوب مبيعات",
  branch: "فرع",
  chart_account: "حساب دليل",
  cost_center: "مركز تكلفة",
};

/** قائمة المستخدمين + إضافة مستخدم جديد (الإضافة من داخل الصفحة، مش من الشريط الجانبي). */
export default function Users() {
  const { user } = useAuth();
  const { t, lang } = useI18n();
  const users = useFetch(() => api.get<UserRow[]>("/auth/users"), "users-list");
  const branches = useFetch(() => api.get<Branch[]>("/company/branches"), "users-branches");
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?limit=500"), "users-whs");

  const [openAdd, setOpenAdd] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [f, setF] = useState({ username: "", password: "", full_name: "", role: "staff" });
  const [branchIds, setBranchIds] = useState<number[]>([]);
  const [warehouseIds, setWarehouseIds] = useState<number[]>([]);

  const rows = (users.data ?? []).filter((u) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (u.username ?? "").toLowerCase().includes(q) || (u.full_name ?? "").toLowerCase().includes(q);
  });

  const toggle = (list: number[], id: number, setList: (v: number[]) => void) =>
    setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  // وضع تعديل مستخدم: الاسم الكامل + الدور + الحالة + كلمة مرور جديدة (اختياری)
  const [editing, setEditing] = useState<UserRow | null>(null);
  const [ef, setEf] = useState({ full_name: "", role: "staff", is_active: true, password: "" });
  const openEdit = (u: UserRow) => {
    setEditing(u);
    setEf({ full_name: u.full_name ?? "", role: u.role, is_active: u.is_active, password: "" });
    setError(null);
  };
  const self = editing && user && editing.id === user.id;

  // حذف مستخدم: تأكيد ثم DELETE /auth/users/{id} — المدير المنصة وحسابك لا يمكن حذفهم
  const [confirmDel, setConfirmDel] = useState<UserRow | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  // مراقبة مستخدم: كل نشاطه من أول تسجيل دخول حتى الآن
  const [monitoring, setMonitoring] = useState<UserRow | null>(null);
  const [monData, setMonData] = useState<ActivityData | null>(null);
  const [monLoad, setMonLoad] = useState(false);
  const [monError, setMonError] = useState<string | null>(null);
  const openMonitor = (u: UserRow) => {
    setMonitoring(u);
    setMonData(null);
    setMonError(null);
    setMonLoad(true);
    api
      .get<ActivityData>(`/auth/users/${u.id}/activity`)
      .then((d) => setMonData(d))
      .catch(() => setMonError("تعذر تحميل سجل النشاط. حاول مرة أخرى."))
      .finally(() => setMonLoad(false));
  };

  const doDelete = async (u: UserRow) => {
    setDeleting(u.id);
    setError(null);
    try {
      await api.del(`/auth/users/${u.id}`);
      setConfirmDel(null);
      setNote(`تم حذف المستخدم «${u.username}».`);
      users.reload();
    } catch (err) {
      setConfirmDel(null);
      setError((err as Error).message);
    } finally {
      setDeleting(null);
    }
  };

  const saveEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setError(null);
    setBusy(true);
    const body: Record<string, unknown> = {};
    if (ef.full_name.trim() !== (editing.full_name ?? "")) body.full_name = ef.full_name.trim() || null;
    if (ef.role !== editing.role) body.role = ef.role;
    if (ef.is_active !== editing.is_active) body.is_active = ef.is_active;
    if (ef.password.length > 0) {
      if (ef.password.length < 8) {
        setError("كلمة المرور الجديدة لازم تكون 8 أحرف على الأقل.");
        setBusy(false);
        return;
      }
      body.password = ef.password;
    }
    try {
      await api.patch(`/auth/users/${editing.id}`, body);
      setEditing(null);
      setNote(`تم تحديث المستخدم «${editing.username}».`);
      users.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.post("/auth/users", {
        username: f.username.trim(),
        password: f.password,
        full_name: f.full_name.trim() || null,
        role: f.role,
        branch_ids: branchIds,
        warehouse_ids: warehouseIds,
      });
      setOpenAdd(false);
      setF({ username: "", password: "", full_name: "", role: "staff" });
      setBranchIds([]);
      setWarehouseIds([]);
      setNote(`تم إنشاء المستخدم «${f.username.trim()}».`);
      users.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="قائمة المستخدمين">
        <button className="btn btn-primary" onClick={() => { setError(null); setOpenAdd(true); }}>
          + إضافة مستخدم جديد
        </button>
      </PageHeader>

      <div className="toolbar page-actions" style={{ marginBottom: 14 }}>
        <input placeholder="ابحث بالاسم أو اسم المستخدم…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ minWidth: 320 }} />
      </div>

      <Alert>{users.error}</Alert>
      {note && (
        <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "#e6f6ee", color: "#1a7f4b" }}>
          {note}
        </div>
      )}

      <div className="card table-wrap">
        {users.loading && !users.data ? (
          <Loading />
        ) : rows.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>كود المستخدم</th>
                <th>اسم المستخدم</th>
                <th>الدور</th>
                <th>الحالة</th>
                <th>الفرع</th>
                <th>أُنشئ في</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id} style={u.is_active ? undefined : { opacity: 0.55 }}>
                  <td className="num-center">{u.id}</td>
                  <td dir="ltr">{u.username}</td>
                  <td>
                    {u.is_platform_admin ? (
                      <span className="badge" style={{ background: "#f3e8ff", color: "#6b21a8", borderRadius: 999, padding: "2px 10px", fontSize: 12 }}>
                        {t("users.platformAdmin")}
                      </span>
                    ) : (
                      <span className="badge" style={{ ...ROLE_STYLE[u.role], borderRadius: 999, padding: "2px 10px", fontSize: 12 }}>
                        {ROLE_LABEL[u.role]?.[lang] ?? u.role}
                      </span>
                    )}
                  </td>
                  <td><ActiveBadge active={u.is_active} /></td>
                  <td>
                    {u.branch_ids && u.branch_ids.length > 0 ? (
                      <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 4 }}>
                        {u.branch_ids.map((bid) => {
                          const b = (branches.data ?? []).find((x) => x.id === bid);
                          return (
                            <span key={bid} className="badge" style={{ background: "#e3f2fd", color: "#0d47a1", borderRadius: 999, padding: "2px 9px", fontSize: 12 }}>
                              {b ? b.name : `فرع ${bid}`}
                            </span>
                          );
                        })}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>{new Date(u.created_at).toLocaleDateString("ar-EG")}</td>
                  <td className="actions">
                    <button className="btn-edit" onClick={() => openEdit(u)}>تعديل</button>{" "}
                    <button
                      className="btn btn-sm"
                      style={{ color: "#6b21a8", borderColor: "#6b21a8" }}
                      onClick={() => openMonitor(u)}
                    >
                      👁️ مراقبة
                    </button>{" "}
                    <button
                      className="btn btn-sm"
                      style={{ color: "var(--danger)", borderColor: "var(--danger)" }}
                      disabled={deleting === u.id}
                      onClick={() => setConfirmDel(u)}
                    >
                      {deleting === u.id ? "…" : "حذف"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{search ? "لا توجد مستخدمين مطابقين." : "لا يوجد مستخدمون."}</Empty>
        )}
      </div>

      {openAdd && (
        <Modal title="إضافة مستخدم جديد" onClose={() => setOpenAdd(false)} wide>
        <form onSubmit={submit}>
          <Alert>{error}</Alert>
          <div className="form-grid">
            <Field label="اسم المستخدم">
              <input dir="ltr" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} required minLength={3} maxLength={60} />
            </Field>
            <Field label="الاسم الكامل">
              <input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} placeholder="اختياري" />
            </Field>
          </div>
          <Field label="كلمة المرور (8 أحرف على الأقل)">
            <input dir="ltr" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required minLength={8} maxLength={128} />
          </Field>
          <Field label="الدور">
            <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              <option value="staff">موظف — صلاحيات محدودة حسب الفرع/المخزن</option>
              <option value="manager">مدير — صلاحيات كاملة داخل الشركة</option>
              <option value="admin">مدير عام — كل الصلاحيات + إدارة المستخدمين</option>
            </select>
          </Field>

          {(branches.data ?? []).length > 0 && (
            <>
              <p style={{ margin: "12px 0 4px", fontWeight: 700, fontSize: 13 }}>الوصول إلى الفروع:</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }} className="form-grid">
                {(branches.data ?? []).map((b) => (
                  <label key={b.id} className="check" style={{ background: branchIds.includes(b.id) ? "#e3f2fd" : undefined, borderRadius: 8, padding: "4px 10px" }}>
                    <input type="checkbox" checked={branchIds.includes(b.id)} onChange={() => toggle(branchIds, b.id, setBranchIds)} /> {b.name}
                  </label>
                ))}
              </div>
            </>
          )}

          {(warehouses.data ?? []).length > 0 && (
            <>
              <p style={{ margin: "12px 0 4px", fontWeight: 700, fontSize: 13 }}>الوصول إلى المخازن:</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {(warehouses.data ?? []).map((w) => (
                  <label key={w.id} className="check" style={{ background: warehouseIds.includes(w.id) ? "#e6f6ee" : undefined, borderRadius: 8, padding: "4px 10px" }}>
                    <input type="checkbox" checked={warehouseIds.includes(w.id)} onChange={() => toggle(warehouseIds, w.id, setWarehouseIds)} /> {w.name}
                  </label>
                ))}
              </div>
            </>
          )}

          {f.role === "staff" && branchIds.length === 0 && warehouseIds.length === 0 && (
            <p className="muted" style={{ fontSize: 13 }}>
              الموظف لازم يُخصَّص لفرع واحد أو مخزن على الأقل.
            </p>
          )}

          <div className="form-actions" style={{ marginTop: 14 }}>
            <button className="btn btn-primary" disabled={busy || !f.username.trim() || f.password.length < 8}>
              {busy ? "جارٍ الحفظ…" : "إنشاء المستخدم"}
            </button>
            <button type="button" className="btn" onClick={() => setOpenAdd(false)}>
              إلغاء
            </button>
          </div>
        </form>
        </Modal>
      )}

      {editing && (
        <Modal title={`تعديل المستخدم — ${editing.username}`} onClose={() => setEditing(null)} wide>
          <form onSubmit={saveEdit}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="الاسم الكامل">
                <input value={ef.full_name} onChange={(e) => setEf({ ...ef, full_name: e.target.value })} />
              </Field>
              <Field label="الدور">
                <select value={ef.role} onChange={(e) => setEf({ ...ef, role: e.target.value })} disabled={!!self}>
                  <option value="staff">موظف — صلاحيات محدودة حسب الفرع/المخزن</option>
                  <option value="manager">مدير — صلاحيات كاملة داخل الشركة</option>
                  <option value="admin">مدير عام — كل الصلاحيات + إدارة المستخدمين</option>
                </select>
              </Field>
            </div>
            <div className="form-grid">
              <Field label="الحالة">
                <select value={String(ef.is_active)} onChange={(e) => setEf({ ...ef, is_active: e.target.value === "true" })} disabled={!!self}>
                  <option value="true">نشط</option>
                  <option value="false">موقوف</option>
                </select>
              </Field>
              <Field label="كلمة مرور جديدة (اختياري)">
                <input dir="ltr" type="password" value={ef.password} onChange={(e) => setEf({ ...ef, password: e.target.value })} minLength={8} maxLength={128} placeholder="اتركه فارغاً لعدم التغيير" />
              </Field>
            </div>
            {self && (
              <p className="muted" style={{ fontSize: 13 }}>
                لا يمكن تغيير دورك أو إيقاف حسابك بنفسك.
              </p>
            )}
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
        <Modal title={`حذف المستخدم — ${confirmDel.username}`} onClose={() => setConfirmDel(null)}>
          <p style={{ margin: "0 0 6px" }}>
            هل أنت متأكد من حذف المستخدم <strong>{confirmDel.username}</strong>؟ لا يمكن الرجوع بعد الحذف.
          </p>
          {confirmDel.is_platform_admin && (
            <p style={{ margin: "0 0 6px", color: "var(--danger)", fontSize: 13 }}>{t("users.platformAdminNoDelete")}</p>
          )}
          {user && confirmDel.id === user.id && (
            <p style={{ margin: "0 0 6px", color: "var(--danger)", fontSize: 13 }}>لا يمكنك حذف حسابك بنفسك.</p>
          )}
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn-delete"
              disabled={confirmDel.is_platform_admin || (!!user && confirmDel.id === user.id) || deleting !== null}
              onClick={() => void doDelete(confirmDel)}
            >
              {deleting !== null ? "جارٍ الحذف…" : "نعم، حذف"}
            </button>
            <button type="button" className="btn" onClick={() => setConfirmDel(null)}>
              إلغاء
            </button>
          </div>
        </Modal>
      )}

      {monitoring && (
        <Modal title={`👁️ مراقبة المستخدم — ${monitoring.username}`} onClose={() => setMonitoring(null)} wide>
          <Alert>{monError}</Alert>
          {monLoad && <Loading />}
          {monData && (
            <>
              <div className="form-grid" style={{ marginBottom: 12 }}>
                <div>
                  <span className="muted">الاسم: </span>
                  {monData.full_name || "—"}
                </div>
                <div>
                  <span className="muted">أول تسجيل دخول: </span>
                  {monData.first_login ? dateTime(monData.first_login) : "—"}
                </div>
                <div>
                  <span className="muted">آخر تسجيل دخول: </span>
                  {monData.last_login ? dateTime(monData.last_login) : "—"}
                </div>
                <div>
                  <span className="muted">عدد مرات الدخول: </span>
                  <strong>{num(monData.login_count)}</strong>
                </div>
              </div>
              {monData.logs.length === 0 ? (
                <Empty>لا يوجد نشاط مسجل لهذا المستخدم حتى الآن.</Empty>
              ) : (
                <div style={{ maxHeight: "60vh", overflowY: "auto" }}>
                  <table style={{ width: "100%" }}>
                    <thead>
                      <tr>
                        <th>التاريخ والوقت</th>
                        <th>العملية</th>
                        <th>السند / الوحدة</th>
                        <th>التفاصيل</th>
                      </tr>
                    </thead>
                    <tbody>
                      {monData.logs.map((l) => (
                        <tr key={l.id}>
                          <td dir="ltr" style={{ whiteSpace: "nowrap" }}>{dateTime(l.created_at)}</td>
                          <td>
                            <span
                              className="badge"
                              style={
                                l.action === "login"
                                  ? { background: "#e3f2fd", color: "#0d47a1" }
                                  : l.action === "delete"
                                    ? { background: "#fdecea", color: "#b71c1c" }
                                    : { background: "#fff4d6", color: "#9a6700" }
                              }
                            >
                              {MON_ACTION[l.action] ?? l.action}
                            </span>
                          </td>
                          <td>
                            {MON_ENTITY[l.entity] ?? l.entity}
                            {l.entity_id != null && l.action !== "login" ? ` #${l.entity_id}` : ""}
                          </td>
                          <td>{l.summary || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                    يعرض أحدث {num(monData.logs.length)} حدث من أصل {num(monData.total)} حدث مسجل — من أول تسجيل دخول حتى الوقت الحالي.
                  </p>
                </div>
              )}
            </>
          )}
        </Modal>
      )}
    </>
  );
}
