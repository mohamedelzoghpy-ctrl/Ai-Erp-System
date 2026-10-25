import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { dateTime, ROLE_LABEL } from "../format";
import { useAction, useFetch } from "../hooks";
import type { Branch, Role, User, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

export default function Users() {
  const { user: me, isAdmin } = useAuth();
  const users = useFetch(() => api.get<User[]>("/company/employees"), "company-employees");
  const [editing, setEditing] = useState<User | "new" | null>(null);

  return (
    <>
      <PageHeader title="موظفو الشركة">
        <button className="btn btn-primary" onClick={() => setEditing("new")}>
          + مستخدم جديد
        </button>
      </PageHeader>
      <Alert>{users.error}</Alert>
      <div className="card table-wrap">
        {users.loading && !users.data ? (
          <Loading />
        ) : users.data && users.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>اسم المستخدم</th>
                <th>الاسم</th>
                <th>الدور</th>
                <th>الحالة</th>
                <th>أُنشئ في</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.data.map((u) => (
                <tr key={u.id}>
                  <td dir="ltr">
                    {u.username}
                    {u.id === me?.id && <span className="muted"> (أنت)</span>}
                  </td>
                  <td>{u.full_name || "—"}</td>
                  <td>{ROLE_LABEL[u.role]}</td>
                  <td>{u.is_active ? <span className="badge badge-confirmed">نشط</span> : <span className="badge badge-off">معطّل</span>}</td>
                  <td>{dateTime(u.created_at)}</td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => setEditing(u)}>
                      تعديل
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>لا يوجد مستخدمون.</Empty>
        )}
      </div>
      {editing && (
        <UserForm
          initial={editing === "new" ? null : editing}
          isSelf={editing !== "new" && editing.id === me?.id}
          canAssignAdmin={isAdmin}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            users.reload();
          }}
        />
      )}
    </>
  );
}

function UserForm({ initial, isSelf, canAssignAdmin, onClose, onSaved }: { initial: User | null; isSelf: boolean; canAssignAdmin: boolean; onClose: () => void; onSaved: () => void }) {
  const branches = useFetch(() => api.get<Branch[]>("/company/branches"), "employee-branch-options");
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses"), "employee-warehouse-options");
  const [username, setUsername] = useState(initial?.username ?? "");
  const [fullName, setFullName] = useState(initial?.full_name ?? "");
  const [role, setRole] = useState<Role>(initial?.role ?? "staff");
  const [active, setActive] = useState(initial?.is_active ?? true);
  const [password, setPassword] = useState("");
  const [branchIds, setBranchIds] = useState<number[]>(initial?.branch_ids ?? []);
  const [warehouseIds, setWarehouseIds] = useState<number[]>(initial?.warehouse_ids ?? []);
  const { busy, error, run } = useAction();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      if (initial) {
        const body: Record<string, unknown> = {
          full_name: fullName.trim() || null,
          role,
          is_active: active,
          branch_ids: branchIds,
          warehouse_ids: warehouseIds,
        };
        if (password) body.password = password;
        await api.patch(`/company/employees/${initial.id}`, body);
      } else {
        await api.post("/company/employees", {
          username: username.trim(),
          password,
          full_name: fullName.trim() || null,
          role,
          branch_ids: branchIds,
          warehouse_ids: warehouseIds,
        });
      }
      onSaved();
    });
  };

  return (
    <Modal title={initial ? "تعديل مستخدم" : "مستخدم جديد"} onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <div className="form-grid">
          <Field label="اسم المستخدم" hint={initial ? undefined : "3 أحرف على الأقل"}>
            <input dir="ltr" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} disabled={!!initial} autoFocus={!initial} />
          </Field>
          <Field label="الاسم الكامل">
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="الدور" hint={isSelf ? "لا يمكنك تغيير دور حسابك" : undefined}>
            <select value={role} onChange={(e) => setRole(e.target.value as Role)} disabled={isSelf}>
              <option value="staff">{ROLE_LABEL.staff}</option>
              {canAssignAdmin && <option value="manager">{ROLE_LABEL.manager}</option>}
              {canAssignAdmin && <option value="admin">{ROLE_LABEL.admin}</option>}
            </select>
          </Field>
          <Field label={initial ? "كلمة مرور جديدة" : "كلمة المرور"} hint={initial ? "اتركها فارغة بدون تغيير" : "8 أحرف على الأقل"}>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required={!initial} minLength={8} autoComplete="new-password" />
          </Field>
        </div>
        {initial && (
          <label className="check">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} disabled={isSelf} /> نشط
          </label>
        )}
        {role === "staff" && (
          <div className="form-grid" style={{ marginTop: 16 }}>
            <Field label="الفروع المسموح بها" hint="صلاحية الفرع تشمل كل مخازنه">
              {branches.data?.length ? branches.data.map((branch) => (
                <label className="check" key={branch.id}>
                  <input
                    type="checkbox"
                    checked={branchIds.includes(branch.id)}
                    onChange={(e) => setBranchIds((current) => e.target.checked ? [...current, branch.id] : current.filter((id) => id !== branch.id))}
                  />
                  {branch.name}
                </label>
              )) : <span className="muted">لا توجد فروع</span>}
            </Field>
            <Field label="المخازن المسموح بها" hint="يمكن إضافة صلاحيات مخازن محددة خارج صلاحيات الفروع">
              {warehouses.data?.length ? warehouses.data.map((warehouse) => (
                <label className="check" key={warehouse.id}>
                  <input
                    type="checkbox"
                    checked={warehouseIds.includes(warehouse.id)}
                    onChange={(e) => setWarehouseIds((current) => e.target.checked ? [...current, warehouse.id] : current.filter((id) => id !== warehouse.id))}
                  />
                  {warehouse.name}
                </label>
              )) : <span className="muted">لا توجد مخازن</span>}
            </Field>
          </div>
        )}
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
