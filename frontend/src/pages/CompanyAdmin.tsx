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
          <div className="card" style={{ padding: 20 }}>
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
        </>
      )}
    </>
  );
}
