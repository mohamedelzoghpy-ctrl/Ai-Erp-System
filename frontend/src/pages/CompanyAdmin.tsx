import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction, useFetch } from "../hooks";
import type { Branch, Company } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

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
  const [adminPassword, setAdminPassword] = useState("");
  const [selectedCompany, setSelectedCompany] = useState<number | null>(null);
  const [editingCompany, setEditingCompany] = useState<Company | null>(null);
  const [editName, setEditName] = useState("");
  const [editLimit, setEditLimit] = useState("");
  const [editSafeLimit, setEditSafeLimit] = useState("");
  const [editActive, setEditActive] = useState(true);
  const [editAdminName, setEditAdminName] = useState("");
  const [editAdminPassword, setEditAdminPassword] = useState("");
  const [memberUsername, setMemberUsername] = useState("");
  const [memberRole, setMemberRole] = useState("staff");
  const [members, setMembers] = useState<{ user_id: number; username: string; full_name: string | null; role: string }[]>([]);
  const [selBranches, setSelBranches] = useState<{ id: number; name: string; code: string; location: string | null; is_active: boolean }[]>([]);
  const [selWarehouses, setSelWarehouses] = useState<{ id: number; name: string; code: string; branch_id: number; location: string | null; is_active: boolean }[]>([]);
  const [allBranches, setAllBranches] = useState<{ company: string; id: number; name: string; code: string; location: string | null; is_active: boolean }[]>([]);
  const [newBranchName, setNewBranchName] = useState("");
  const [newBranchCode, setNewBranchCode] = useState("");
  const [newWhName, setNewWhName] = useState("");
  const [newWhCode, setNewWhCode] = useState("");
  const [newWhBranch, setNewWhBranch] = useState<number | null>(null);
  const [newWhLocation, setNewWhLocation] = useState("");
  const [selLimit, setSelLimit] = useState<string | null>(null);
  const [companyWarehouseLimit, setCompanyWarehouseLimit] = useState("");
  const [companySafeLimit, setCompanySafeLimit] = useState("");
  useEffect(() => {
    if (!platform || !companies.data?.length) return;
    let cancelled = false;
    (async () => {
      const out: { company: string; id: number; name: string; code: string; location: string | null; is_active: boolean }[] = [];
      for (const c of companies.data ?? []) {
        try {
          const bs = await api.get<{ id: number; name: string; code: string; location: string | null; is_active: boolean }[]>(`/platform/companies/${c.id}/branches`);
          for (const b of bs) out.push({ company: c.name, ...b });
        } catch { /* ignore */ }
      }
      if (!cancelled) setAllBranches(out);
    })();
    return () => { cancelled = true; };
  }, [platform, companies.data]);
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
      await api.post("/company/branches", { name: branchName.trim(), ...(branchCode.trim() ? { code: branchCode.trim() } : {}) });
      setBranchName("");
      setBranchCode("");
      branches.reload();
    });
  };

  const selectCompany = (companyId: number) => {
    setSelectedCompany(companyId);
    void api.get<{ user_id: number; username: string; full_name: string | null; role: string }[]>(`/platform/companies/${companyId}/members`).then(setMembers).catch(() => setMembers([]));
    void api.get<{ id: number; name: string; code: string; location: string | null; is_active: boolean }[]>(`/platform/companies/${companyId}/branches`).then(setSelBranches).catch(() => setSelBranches([]));
    void api.get<{ id: number; name: string; code: string; branch_id: number; location: string | null; is_active: boolean }[]>(`/platform/companies/${companyId}/warehouses`).then(setSelWarehouses).catch(() => setSelWarehouses([]));
  };

  const addSelBranch = (e: FormEvent) => {
    e.preventDefault();
    if (!selectedCompany) return;
    void run(async () => {
      await api.post(`/platform/companies/${selectedCompany}/branches`, { name: newBranchName.trim(), ...(newBranchCode.trim() ? { code: newBranchCode.trim() } : {}) });
      setNewBranchName(""); setNewBranchCode("");
      selectCompany(selectedCompany);
    });
  };

  const addSelWarehouse = (e: FormEvent) => {
    e.preventDefault();
    if (!selectedCompany) return;
    void run(async () => {
      await api.post(`/platform/companies/${selectedCompany}/warehouses`, { name: newWhName.trim(), code: newWhCode.trim() || null, branch_id: newWhBranch, location: newWhLocation.trim() || null });
      setNewWhName(""); setNewWhCode(""); setNewWhBranch(null); setNewWhLocation("");
      selectCompany(selectedCompany);
    });
  };

  const removeSelMember = (userId: number) => {
    if (!selectedCompany) return;
    if (!confirm("إزالة العضوية؟")) return;
    void run(async () => {
      await api.del(`/platform/companies/${selectedCompany}/members/${userId}`);
      selectCompany(selectedCompany);
    });
  };
  const addSelMember = (e: FormEvent) => {
    e.preventDefault();
    if (!selectedCompany) return;
    void run(async () => {
      await api.post(`/platform/companies/${selectedCompany}/members`, { username: memberUsername.trim(), role: memberRole });
      setMemberUsername("");
      selectCompany(selectedCompany);
    });
  };

  const addCompany = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/platform/companies", {
        name: companyName.trim(),
        code: companyCode.trim(),
        max_warehouses_per_branch: companyWarehouseLimit ? Number(companyWarehouseLimit) : null,
        max_safes_per_branch: companySafeLimit ? Number(companySafeLimit) : null,
        admin_username: adminUsername.trim(),
        admin_full_name: adminUsername.trim() || null,
        admin_password: adminPassword,
      });
      setCompanyName("");
      setCompanyCode("");
      setAdminUsername("");
      setAdminPassword("");
      setCompanyWarehouseLimit("");
      setCompanySafeLimit("");
      companies.reload();
    });
  };

  return (
    <>
      <PageHeader title={platform ? "إدارة الشركات" : "الفروع وإعدادات الشركة"} />
      <Alert>{error || currentCompany.error || branches.error || companies.error}</Alert>

      {platform && (
        <div className="card" style={{ padding: 20, marginBottom: 16 }}>
          <form onSubmit={addCompany}>
            <button className="btn btn-primary" disabled={busy} style={{ marginBottom: 12 }}>إنشاء الشركة</button>
            <div className="form-grid">
              <Field label="اسم الشركة"><input value={companyName} onChange={(e) => setCompanyName(e.target.value)} required /></Field>
              <Field label="رمز الشركة"><input dir="ltr" value={companyCode} onChange={(e) => setCompanyCode(e.target.value)} required /></Field>
              <Field label="الحد الأقصى للمخازن لكل فرع"><input type="number" min={1} value={companyWarehouseLimit} onChange={(e) => setCompanyWarehouseLimit(e.target.value)} /></Field>
              <Field label="الحد الأقصى للخزائن لكل فرع"><input type="number" min={1} value={companySafeLimit} onChange={(e) => setCompanySafeLimit(e.target.value)} /></Field>
              <Field label="اسم مستخدم المدير الأول"><input dir="ltr" minLength={3} value={adminUsername} onChange={(e) => setAdminUsername(e.target.value)} required /></Field>
              <Field label="كلمة مرور المدير"><input type="password" minLength={8} value={adminPassword} onChange={(e) => setAdminPassword(e.target.value)} required /></Field>
            </div>
          </form>
        </div>
      )}

          <div className="card table-wrap" style={{ marginBottom: 16 }}>
            <h2 style={{ padding: 16 }}>الشركات المسجلة</h2>
            {companies.loading && !companies.data ? <Loading /> : companies.data?.length ? (
              <table>
                <thead><tr><th>الشركة</th><th>الرمز</th><th>حد المخازن لكل فرع</th><th>الحالة</th></tr></thead>
                <tbody>{companies.data.map((item) => (
                  <tr key={item.id}>
                    <td>{item.name}</td><td dir="ltr">{item.code}</td>
                    <td>{item.max_warehouses_per_branch ?? "غير محدود"}</td><td>{item.is_active ? "active" : "inactive"} <button className="btn btn-sm" style={{ marginInlineStart: 8 }} onClick={() => { setEditingCompany(item); setEditName(item.name); setEditLimit(item.max_warehouses_per_branch ? String(item.max_warehouses_per_branch) : ""); setEditSafeLimit(item.max_safes_per_branch ? String(item.max_safes_per_branch) : ""); setEditActive(item.is_active); setEditAdminName(""); setEditAdminPassword(""); void api.get<{ full_name: string | null }>(`/platform/companies/${item.id}/admin`).then((u) => setEditAdminName(u.full_name || "")).catch(() => {}); }}>تعديل</button></td>
                  </tr>
                ))}</tbody>
              </table>
            ) : <Empty>لا توجد شركات.</Empty>}
          </div>

      {!platform && (
        <>
          <div className="card" style={{ padding: 20, marginBottom: 16 }}>
            <h2>{currentCompany.data?.name || "الشركة الحالية"}</h2>
            <p className="muted">
              {currentCompany.data
                ? `الرمز: ${currentCompany.data.code} · ${currentCompany.data.max_warehouses_per_branch ? `الحد ${currentCompany.data.max_warehouses_per_branch} مخازن لكل فرع` : "عدد المخازن لكل فرع غير محدود"}`
                : ""}
            </p>
            {isAdmin && (
              <form onSubmit={saveSettings}>
                <Field label="الحد الأقصى للمخازن في كل فرع">
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
                    <td>{branch.is_active ? "active" : "inactive"}</td>
                  </tr>
                ))}</tbody>
              </table>
            ) : <Empty>لا توجد فروع بعد.</Empty>}
          </div>

          <div className="card" style={{ padding: 20, marginBottom: 16 }}>
            <h2>إضافة فرع</h2>
            <form onSubmit={addBranch} className="form-grid">
              <Field label="اسم الفرع"><input value={branchName} onChange={(e) => setBranchName(e.target.value)} required /></Field>
              <Field label="رمز الفرع" hint="اتركه فارغًا للتوليد التلقائي"><input dir="ltr" value={branchCode} onChange={(e) => setBranchCode(e.target.value)} /></Field>
              <button className="btn btn-primary" disabled={busy}>إضافة الفرع</button>
            </form>
          </div>
        </>
      )}

      {platform && (
        <>
          <div className="card table-wrap" style={{ marginBottom: 16 }}>
            <h2 style={{ padding: 16 }}>الفروع المسجلة</h2>
            {allBranches.length ? (
              <table>
                <thead><tr><th>الشركة</th><th>الاسم</th><th>الرمز</th><th>الموقع</th><th>الحالة</th></tr></thead>
                <tbody>{allBranches.map((b) => (
                  <tr key={`${b.company}-${b.id}`}><td>{b.company}</td><td>{b.name}</td><td dir="ltr">{b.code}</td><td>{b.location || "—"}</td><td>{b.is_active ? "active" : "inactive"}</td></tr>
                ))}</tbody>
              </table>
            ) : <Empty>لا توجد فروع مسجلة.</Empty>}
          </div>
          <div className="card" style={{ padding: 20, marginBottom: 16 }}>
            <h2>ربط المستخدمين بالشركات (تبديل شركة)</h2>
            <p className="muted" style={{ marginTop: 0 }}>اختر شركة لعرض/إدارة أعضائها. المستخدم الذي ينتمي لأكثر من شركة سيظهر له مُبدِّل "الشركة" في الشريط العلوي.</p>
            <div className="form-grid" style={{ marginBottom: 12 }}>
              <Field label="الشركة">
                <select value={selectedCompany ?? ""} onChange={(e) => { const v = Number(e.target.value); if (v) selectCompany(v); }}>
                  <option value="">— اختر —</option>
                  {companies.data?.map((c) => (
                    <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                  ))}
                </select>
              </Field>
            </div>
            {selectedCompany && (
              <>

                 <h3 style={{ marginTop: 16 }}>الفروع</h3>
                 {selBranches.length > 0 ? (
                   <div className="table-wrap" style={{ marginBottom: 12 }}>
                     <table>
                       <thead><tr><th>الاسم</th><th>الرمز</th><th>الموقع</th><th>الحالة</th></tr></thead>
                       <tbody>{selBranches.map((b) => (
                         <tr key={b.id}><td>{b.name}</td><td dir="ltr">{b.code}</td><td>{b.location || "—"}</td><td>{b.is_active ? "active" : "inactive"}</td></tr>
                       ))}</tbody>
                     </table>
                   </div>
                 ) : <Empty>لا توجد فروع.</Empty>}
                 <form onSubmit={addSelBranch} className="form-grid" style={{ marginBottom: 16 }}>
                   <Field label="اسم الفرع"><input value={newBranchName} onChange={(e) => setNewBranchName(e.target.value)} required /></Field>
                   <Field label="رمز الفرع" hint="اتركه فارغًا للتوليد التلقائي"><input dir="ltr" value={newBranchCode} onChange={(e) => setNewBranchCode(e.target.value)} /></Field>
                   <button className="btn btn-primary" disabled={busy}>إضافة فرع</button>
                 </form>

                 <h3>المخازن</h3>
                 {selWarehouses.length > 0 ? (
                   <div className="table-wrap" style={{ marginBottom: 12 }}>
                     <table>
                       <thead><tr><th>الاسم</th><th>الكود</th><th>الفرع</th><th>الموقع</th><th>الحالة</th></tr></thead>
                       <tbody>{selWarehouses.map((w) => (
                         <tr key={w.id}><td>{w.name}</td><td>{w.code}</td><td>{selBranches.find((b) => b.id === w.branch_id)?.name || "—"}</td><td>{w.location || "—"}</td><td>{w.is_active ? "active" : "inactive"}</td></tr>
                       ))}</tbody>
                     </table>
                   </div>
                 ) : <Empty>لا توجد مخازن.</Empty>}
                 <form onSubmit={addSelWarehouse} className="form-grid">
                   <Field label="اسم المخزن"><input value={newWhName} onChange={(e) => setNewWhName(e.target.value)} required /></Field>
                   <Field label="كود المخزن" hint="اتركه فارغاً للتوليد التلقائي"><input dir="ltr" value={newWhCode} onChange={(e) => setNewWhCode(e.target.value)} /></Field>
                   <Field label="الفرع">
                     <select value={newWhBranch ?? ""} onChange={(e) => setNewWhBranch(Number(e.target.value) || null)}>
                       <option value="">— اختر فرع —</option>
                       {selBranches.map((b) => (<option key={b.id} value={b.id}>{b.name}</option>))}
                     </select>
                   </Field>
                   <Field label="الموقع"><input value={newWhLocation} onChange={(e) => setNewWhLocation(e.target.value)} /></Field>
                   <button className="btn btn-primary" disabled={busy}>إضافة مخزن</button>
                 </form>
                <h3>3.3 الأعضاء (الخزن)</h3>
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
                <form onSubmit={addSelMember} className="form-grid">
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
              </>
            )}
          </div>

          <div className="card" style={{ padding: 20, marginBottom: 16 }}>
            <h2>5. حفظ الإعدادات (الشركة المختارة)</h2>
            <p className="muted" style={{ marginTop: 0 }}>حد المخازن لكل فرع.</p>
            {selectedCompany ? (
              <form onSubmit={(e) => {
                e.preventDefault();
                if (!selectedCompany) return;
                void run(async () => {
                  await api.patch(`/platform/companies/${selectedCompany}`, { max_warehouses_per_branch: selLimit?.trim() ? Number(selLimit) : null });
                  setSelLimit(null);
                  companies.reload();
                });
              }} className="form-grid">
                <Field label="الحد الأقصى للمخازن في كل فرع">
                  <input type="number" min={1} value={selLimit ?? ""} onChange={(e) => setSelLimit(e.target.value)} />
                </Field>
                <button className="btn btn-primary" disabled={busy}>حفظ الإعدادات</button>
              </form>
            ) : (
              <Empty>اختر شركة أولاً.</Empty>
            )}
          </div>

        </>
      )}

      {editingCompany && (
        <Modal title={`تعديل شركة — ${editingCompany.name}`} onClose={() => setEditingCompany(null)}>
          <form onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              await api.patch(`/platform/companies/${editingCompany.id}`, {
                name: editName.trim() || undefined,
                max_warehouses_per_branch: editLimit.trim() ? Number(editLimit) : null,
                max_safes_per_branch: editSafeLimit.trim() ? Number(editSafeLimit) : null,
                is_active: editActive,
              });
              const adminPayload: Record<string, unknown> = {};
              if (editAdminName.trim()) adminPayload.full_name = editAdminName.trim();
              if (editAdminPassword.trim()) adminPayload.password = editAdminPassword.trim();
              if (Object.keys(adminPayload).length) {
                await api.patch(`/platform/companies/${editingCompany.id}/admin`, adminPayload);
              }
              setEditingCompany(null);
              companies.reload();
            });
          }} className="form-grid">
            <Field label="اسم الشركة"><input value={editName} onChange={(e) => setEditName(e.target.value)} required /></Field>
            <Field label="الحد الأقصى للمخازن لكل فرع"><input type="number" min={1} value={editLimit} onChange={(e) => setEditLimit(e.target.value)} /></Field>
            <Field label="الحد الأقصى للخزائن لكل فرع"><input type="number" min={1} value={editSafeLimit} onChange={(e) => setEditSafeLimit(e.target.value)} /></Field>
            <Field label="الحالة">
              <select value={editActive ? "1" : "0"} onChange={(e) => setEditActive(e.target.value === "1")}>
                <option value="1">active</option>
                <option value="0">inactive</option>
              </select>
            </Field>
            <Field label="اسم المدير (الاسم الكامل)"><input value={editAdminName} onChange={(e) => setEditAdminName(e.target.value)} /></Field>
            <Field label="كلمة مرور المدير (جديدة)" hint="اتركها فارغًا للإبقاء على الحالية"><input type="password" minLength={8} value={editAdminPassword} onChange={(e) => setEditAdminPassword(e.target.value)} /></Field>
            <button className="btn btn-primary" disabled={busy}>حفظ</button>
          </form>
        </Modal>
      )}
    </>
  );
}
