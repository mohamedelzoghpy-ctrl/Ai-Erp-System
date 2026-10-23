import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { dateTime, ROLE_LABEL } from "../format";
import { useAction, useFetch } from "../hooks";
import type { Role, User } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

export default function Users() {
  const { user: me } = useAuth();
  const users = useFetch(() => api.get<User[]>("/auth/users"), "users");
  const [editing, setEditing] = useState<User | "new" | null>(null);

  return (
    <>
      <PageHeader title="المستخدمون">
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

function UserForm({ initial, isSelf, onClose, onSaved }: { initial: User | null; isSelf: boolean; onClose: () => void; onSaved: () => void }) {
  const [username, setUsername] = useState(initial?.username ?? "");
  const [fullName, setFullName] = useState(initial?.full_name ?? "");
  const [role, setRole] = useState<Role>(initial?.role ?? "staff");
  const [active, setActive] = useState(initial?.is_active ?? true);
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAction();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      if (initial) {
        const body: Record<string, unknown> = { full_name: fullName.trim() || null, role, is_active: active };
        if (password) body.password = password;
        await api.patch(`/auth/users/${initial.id}`, body);
      } else {
        await api.post("/auth/users", { username: username.trim(), password, full_name: fullName.trim() || null, role });
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
              <option value="manager">{ROLE_LABEL.manager}</option>
              <option value="admin">{ROLE_LABEL.admin}</option>
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
