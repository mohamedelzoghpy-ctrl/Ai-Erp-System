import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction, useFetch } from "../hooks";
import type { Branch, Company } from "../types";
import { Alert, Empty, Field, Loading, PageHeader } from "../ui";

export default function CompanyAdmin({ platform = false }: { platform?: boolean }) {
  const { isAdmin } = useAuth();
  const currentCompany = useFetch(() => api.get<Company>("/company"), "current-company");
  const branches = useFetch(() => api.get<Branch[]>("/company/branches"), "company-branches");
  const companies = useFetch(
    () => (platform ? api.get<Company[]>("/platform/companies") : Promise.resolve([])),
    `platform-companies-${platform}`,
  );
  const [branchName, setBranchName] = useState("");
  const [branchCode, setBranchCode] = useState("");
  const [limit, setLimit] = useState<string | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [companyCode, setCompanyCode] = useState("");
  const [adminUsername, setAdminUsername] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [memberCompany, setMemberCompany] = useState<number | null>(null);
  const [memberUsername, setMemberUsername] = useState("");
  const [memberRole, setMemberRole] = useState("staff");
  const [members, setMembers] = useState<{ user_id: number; username: string; full_name: string | null; role: string }[]>([]);
  const [selBranches, setSelBranches] = useState<{ id: number; name: string; code: string; location: string | null; is_active: boolean }[]>([]);
  const [selWarehouses, setSelWarehouses] = useState<{ id: number; name: string; code: string; branch_id: number; location: string | null; is_active: boolean }[]>([]);
  const [newBranchName, setNewBranchName] = useState("");
  const [newBranchCode, setNewBranchCode] = useState("");
  const [newWhName, setNewWhName] = useState("");
  const [newWhCode, setNewWhCode] = useState("");
  const [newWhBranch, setNewWhBranch] = useState<number | null>(null);
  const [newWhLocation, setNewWhLocation] = useState("");
  const [companyWarehouseLimit, setCompanyWarehouseLimit] = useState("");
  const { busy, error, run } = useAction();

  const saveSettings = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.patch("/company", {
        max_warehouses_per_branch: limit?.trim() ? Number(limit) : null,
      });
      setLimit(null);
      currentCompany.reload();
    });
  };

  const addBranch = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/company/branches", { name: branchName.trim(), code: branchCode.trim() });
      setBranchName("");
      setBranchCode("");
      branches.reload();
    });
  };

  const loadMembers = (companyId: number) => {
    setMemberCompany(companyId);
    void api.get<{ user_id: number; username: string; full_name: string | null; role: string }[]>(`/platform/companies/${companyId}/members`).then(setMembers).catch(() => setMembers([]));
    void api.get<{ id: number; name: string; code: string; location: string | null; is_active: boolean }[]>(`/platform/companies/${companyId}/branches`).then(setSelBranches).catch(() => setSelBranches([]));
    void api.get<{ id: number; name: string; code: string; branch_id: number; location: string | null; is_active: boolean }[]>(`/platform/companies/${companyId}/warehouses`).then(setSelWarehouses).catch(() => setSelWarehouses([]));
  };

  const addMember = (e: FormEvent) => {
    e.preventDefault();
    if (!memberCompany) return;
    void run(async () => {
      await api.post(`/platform/companies/${memberCompany}/members`, { username: memberUsername.trim(), role: memberRole });
      setMemberUsername("");
      loadMembers(memberCompany);
    });
  };

  const addSelBranch = (e: FormEvent) => {
    e.preventDefault();
    if (!memberCompany) return;
    void run(async () => {
      await api.post(`/platform/companies/${memberCompany}/branches`, { name: newBranchName.trim(), code: newBranchCode.trim() });
      setNewBranchName(""); setNewBranchCode("");
      loadMembers(memberCompany);
    });
  };

  const addSelWarehouse = (e: FormEvent) => {
    e.preventDefault();
    if (!memberCompany) return;
    void run(async () => {
      await api.post(`/platform/companies/${memberCompany}/warehouses`, { name: newWhName.trim(), code: newWhCode.trim(), branch_id: newWhBranch, location: newWhLocation.trim() || null });
      setNewWhName(""); setNewWhCode(""); setNewWhBranch(null); setNewWhLocation("");
      loadMembers(memberCompany);
    });
  };

  const removeSelMember = (userId: number) => {
    if (!memberCompany) return;
    if (!confirm("إزالة العضوية؟")) return;
    void run(async () => {
      await api.del(`/platform/companies/${memberCompany}/members/${userId}`);
      loadMembers(memberCompany);
    });
  };
  const addCompany = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/platform/companies", {
        name: companyName.trim(),
        code: companyCode.trim(),
        max_warehouses_per_branch: companyWarehouseLimit ? Number(companyWarehouseLimit) : null,
        admin_username: adminUsername.trim(),
        admin_full_name: adminName.trim() || null,
        admin_password: adminPassword,
      });
      setCompanyName("");
      setCompanyCode("");
      setAdminUsername("");
      setAdminName("");
      setAdminPassword("");
      setCompanyWarehouseLimit("");
      companies.reload();
    });
  };

  return (
    <>
      <PageHeader title={platform ? "إدارة الشركات" : "الفروع وإعدادات الشركة"} />
      <Alert>{error || currentCompany.error || branches.error || companies.error}</Alert>

      {platform && (
        <div className="card" style={{ padding: 20, marginBottom: 16 }}>
          <h2>إضافة شركة ومديرها الأول</h2>
          <form onSubmit={addCompany}>
            <div className="form-grid">
              <Field label="اسم الشركة"><input value={companyName} onChange={(e) => setCompanyName(e.target.value)} required /></Field>
              <Field label="رمز الشركة"><input dir="ltr" value={companyCode} onChange={(e) => setCompanyCode(e.target.value)} required /></Field>
              <Field label="الحد الأقصى للمخازن لكل فرع" hint="اتركه فارغًا لعدد غير محدود"><input type="number" min={1} value={companyWarehouseLimit} onChange={(e) => setCompanyWarehouseLimit(e.target.value)} /></Field>
              <Field label="اسم مستخدم المدير الأول"><input dir="ltr" minLength={3} value={adminUsername} onChange={(e) => setAdminUsername(e.target.value)} required /></Field>
              <Field label="اسم المدير"><input value={adminName} onChange={(e) => setAdminName(e.target.value)} /></Field>
              <Field label="كلمة مرور المدير"><input type="password" minLength={8} value={adminPassword} onChange={(e) => setAdminPassword(e.target.value)} required /></Field>
            </div>
            <button className="btn btn-primary" disabled={busy}>إنشاء الشركة</button>
          </form>
        </div>
      )}

      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <h2>{currentCompany.data?.name || "الشركة الحالية"}</h2>
        <p className="muted">
          {currentCompany.data
            ? `الرمز: ${currentCompany.data.code} · ${currentCompany.data.max_warehouses_per_branch ? `الحد ${currentCompany.data.max_warehouses_per_branch} مخازن لكل فرع` : "عدد المخازن لكل فرع غير محدود"}`
            : ""}
        </p>
        {isAdmin && (
          <form onSubmit={saveSettings}>
            <Field label="الحد الأقصى للمخازن في كل فرع" hint="اتركه فارغًا للسماح بعدد غير محدود">
              <input
                type="number"
                min={1}
                value={limit ?? String(currentCompany.data?.max_warehouses_per_branch ?? "")}
                onChange={(e) => setLimit(e.target.value)}
              />
            </Field>
            <button className="btn btn-primary" disabled={busy}>حفظ الإعدادات</button>
          </form>
        )}
      </div>

      <div className="card table-wrap" style={{ marginBottom: 16 }}>
        <h2 style={{ padding: 16 }}>الفروع</h2>
        {branches.loading && !branches.data ? <Loading /> : branches.data?.length ? (
          <table>
            <thead><tr><th>الاسم</th><th>الرمز</th><th>الموقع</th><th>الحالة</th></tr></thead>
            <tbody>{branches.data.map((branch) => (
              <tr key={branch.id}>
                <td>{branch.name}</td><td dir="ltr">{branch.code}</td><td>{branch.location || "—"}</td>
                <td>{branch.is_active ? "نشط" : "معطّل"}</td>
              </tr>
            ))}</tbody>
          </table>
        ) : <Empty>لا توجد فروع بعد.</Empty>}
      </div>

      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <h2>إضافة فرع</h2>
        <form onSubmit={addBranch} className="form-grid">
          <Field label="اسم الفرع"><input value={branchName} onChange={(e) => setBranchName(e.target.value)} required /></Field>
          <Field label="رمز الفرع"><input dir="ltr" value={branchCode} onChange={(e) => setBranchCode(e.target.value)} required /></Field>
          <button className="btn btn-primary" disabled={busy}>إضافة الفرع</button>
        </form>
      </div>

      {platform && (
        <>
          <div className="card table-wrap" style={{ marginBottom: 16 }}>
            <h2 style={{ padding: 16 }}>الشركات المسجلة</h2>
            {companies.loading && !companies.data ? <Loading /> : companies.data?.length ? (
              <table>
                <thead><tr><th>الشركة</th><th>الرمز</th><th>حد المخازن لكل فرع</th><th>الحالة</th></tr></thead>
                <tbody>{companies.data.map((item) => (
                  <tr key={item.id}>
                    <td>{item.name}</td><td dir="ltr">{item.code}</td>
                    <td>{item.max_warehouses_per_branch ?? "غير محدود"}</td><td>{item.is_active ? "نشطة" : "معطّلة"}</td>
                  </tr>
                ))}</tbody>
              </table>
            ) : <Empty>لا توجد شركات.</Empty>}
          </div>
          <div className="card" style={{ padding: 20, marginBottom: 16 }}>
            <h2>ربط المستخدمين بالشركات (تبديل شركة)</h2>
            <p className="muted" style={{ marginTop: 0 }}>اختر شركة لعرض/إدارة أعضائها. المستخدم الذي ينتمي لأكثر من شركة سيظهر له مُبدِّل "الشركة" في الشريط العلوي.</p>
            <div className="form-grid" style={{ marginBottom: 12 }}>
              <Field label="الشركة">
                <select value={memberCompany ?? ""} onChange={(e) => { const v = Number(e.target.value); if (v) loadMembers(v); }}>
                  <option value="">— اختر —</option>
                  {companies.data?.map((c) => (
                    <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                  ))}
                </select>
              </Field>
            </div>
            {memberCompany && (
              <>
                {members.length > 0 ? (
                  <div className="table-wrap" style={{ marginBottom: 12 }}>
                    <table>
                      <thead><tr><th>اسم المستخدم</th><th>الاسم</th><th>الدور</th><th /></tr></thead>
                      <tbody>
                        {members.map((m) => (
                          <tr key={m.user_id}>
                            <td dir="ltr">{m.username}</td>
                            <td>{m.full_name || "—"}</td>
                            <td>{m.role}</td>
                            <td className="actions">
                              <button className="btn btn-sm btn-danger" onClick={() => removeSelMember(m.user_id)}>إزالة</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty>لا يوجد أعضاء بعد.</Empty>
                )}
                <form onSubmit={addMember} className="form-grid">
                  <Field label="اسم المستخدم (موجود)"><input dir="ltr" value={memberUsername} onChange={(e) => setMemberUsername(e.target.value)} required /></Field>
                  <Field label="الدور">
                    <select value={memberRole} onChange={(e) => setMemberRole(e.target.value)}>
                      <option value="staff">موظف</option>
                      <option value="manager">مدير</option>
                      <option value="admin">مدير عام</option>
                    </select>
                  </Field>
                  <button className="btn btn-primary" disabled={busy}>إضافة عضوية</button>
                </form>
                 <h3 style={{ marginTop: 16 }}>الفروع</h3>
                 {selBranches.length > 0 ? (
                   <div className="table-wrap" style={{ marginBottom: 12 }}>
                     <table>
                       <thead><tr><th>الاسم</th><th>الرمز</th><th>الموقع</th><th>الحالة</th></tr></thead>
                       <tbody>{selBranches.map((b) => (
                         <tr key={b.id}><td>{b.name}</td><td dir="ltr">{b.code}</td><td>{b.location || "—"}</td><td>{b.is_active ? "نشط" : "معطّل"}</td></tr>
                       ))}</tbody>
                     </table>
                   </div>
                 ) : <Empty>لا توجد فروع.</Empty>}
                 <form onSubmit={addSelBranch} className="form-grid" style={{ marginBottom: 16 }}>
                   <Field label="اسم الفرع"><input value={newBranchName} onChange={(e) => setNewBranchName(e.target.value)} required /></Field>
                   <Field label="رمز الفرع"><input dir="ltr" value={newBranchCode} onChange={(e) => setNewBranchCode(e.target.value)} required /></Field>
                   <button className="btn btn-primary" disabled={busy}>إضافة فرع</button>
                 </form>

                 <h3>المخازن</h3>
                 {selWarehouses.length > 0 ? (
                   <div className="table-wrap" style={{ marginBottom: 12 }}>
                     <table>
                       <thead><tr><th>الاسم</th><th>الكود</th><th>الفرع</th><th>الموقع</th><th>الحالة</th></tr></thead>
                       <tbody>{selWarehouses.map((w) => (
                         <tr key={w.id}><td>{w.name}</td><td>{w.code}</td><td>{selBranches.find((b) => b.id === w.branch_id)?.name || "—"}</td><td>{w.location || "—"}</td><td>{w.is_active ? "نشط" : "معطّل"}</td></tr>
                       ))}</tbody>
                     </table>
                   </div>
                 ) : <Empty>لا توجد مخازن.</Empty>}
                 <form onSubmit={addSelWarehouse} className="form-grid">
                   <Field label="اسم المخزن"><input value={newWhName} onChange={(e) => setNewWhName(e.target.value)} required /></Field>
                   <Field label="كود المخزن"><input dir="ltr" value={newWhCode} onChange={(e) => setNewWhCode(e.target.value)} required /></Field>
                   <Field label="الفرع">
                     <select value={newWhBranch ?? ""} onChange={(e) => setNewWhBranch(Number(e.target.value) || null)}>
                       <option value="">— اختر فرع —</option>
                       {selBranches.map((b) => (<option key={b.id} value={b.id}>{b.name}</option>))}
                     </select>
                   </Field>
                   <Field label="الموقع"><input value={newWhLocation} onChange={(e) => setNewWhLocation(e.target.value)} /></Field>
                   <button className="btn btn-primary" disabled={busy}>إضافة مخزن</button>
                 </form>              </>
            )}
          </div>

        </>
      )}
    </>
  );
}
