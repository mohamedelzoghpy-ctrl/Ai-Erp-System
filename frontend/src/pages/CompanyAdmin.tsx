import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction, useFetch } from "../hooks";
import type { Branch, Company, Department, Role, User } from "../types";
import { money } from "../format";
import { ActiveBadge, Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

/** تنسيق تاريخ+وقت عربي مقروء: «١٣ نوفمبر ٢٠٢٦، ١٢:٠٠:٤٦ ص». */
function fmtDateTimeAr(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("ar-EG", { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** تنسيق حجم ملف: KB أو MB بأقرب خانة. */
function fmtSize(bytes: number): string {
  if (!bytes || bytes <= 0) return "0 ك.ب";
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)} ك.ب`;
  return `${(kb / 1024).toFixed(1)} م.ب`;
}

export default function CompanyAdmin({ platform = false, onSaved }: { platform?: boolean; onSaved?: () => void }) {
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const currentCompany = useFetch(() => api.get<Company>("/company"), "current-company");
  const branches = useFetch(() => api.get<Branch[]>("/company/branches"), "company-branches");
  const currentDepartments = useFetch(() => (!platform ? api.get<Department[]>("/company/departments") : Promise.resolve([])), "company-departments");
  const currentEmployees = useFetch(() => (!platform ? api.get<User[]>("/company/employees") : Promise.resolve([])), "company-employees");
  const currentBanks = useFetch(
    () => (!platform ? api.get<{ id: number; name: string; code: string; account_number: string | null; branch_id: number | null; branch_name: string | null; balance: string; is_active: boolean }[]>("/banks") : Promise.resolve([])),
    "current-company-banks",
  );
  const companies = useFetch(
    () => (platform ? api.get<Company[]>("/platform/companies") : Promise.resolve([])),
    `platform-companies-${platform}`,
  );
  const [branchName, setBranchName] = useState("");
  const [branchLocation, setBranchLocation] = useState("");
  const [limit, setLimit] = useState<string | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [adminUsername, setAdminUsername] = useState("");
  const [adminFullName, setAdminFullName] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [selectedCompany, setSelectedCompany] = useState<number | null>(null);
  const [selDepartments, setSelDepartments] = useState<Department[]>([]);
  const [newDepartmentName, setNewDepartmentName] = useState("");
  const [newDepartmentDescription, setNewDepartmentDescription] = useState("");
  const [editingDepartment, setEditingDepartment] = useState<Department | null>(null);
  const [newEmployeeUsername, setNewEmployeeUsername] = useState("");
  const [newEmployeeName, setNewEmployeeName] = useState("");
  const [newEmployeePassword, setNewEmployeePassword] = useState("");
  const [newEmployeeRole, setNewEmployeeRole] = useState<Role>("staff");
  const [newEmployeeDepartment, setNewEmployeeDepartment] = useState("");
  const [newEmployeeAllBranches, setNewEmployeeAllBranches] = useState(true);
  const [newEmployeeBranches, setNewEmployeeBranches] = useState<number[]>([]);
  const [editingEmployee, setEditingEmployee] = useState<User | null>(null);
  const [employeeDepartment, setEmployeeDepartment] = useState("");
  const [employeeAllBranches, setEmployeeAllBranches] = useState(false);
  const [employeeBranches, setEmployeeBranches] = useState<number[]>([]);
  const [employeeRole, setEmployeeRole] = useState<Role>("staff");
  const [employeeActive, setEmployeeActive] = useState(true);
  const [employeePassword, setEmployeePassword] = useState("");
  const [employeeWarehouseIds, setEmployeeWarehouseIds] = useState<number[]>([]);
  const [editingCompany, setEditingCompany] = useState<Company | null>(null);
  const [editName, setEditName] = useState("");
  const [jeThreshold, setJeThreshold] = useState<string>(() => {
    const v = (currentCompany.data as any)?.je_approval_threshold;
    return v == null ? "" : String(v);
  });
  const [lockDate, setLockDate] = useState<string>(() => {
    const v = (currentCompany.data as any)?.accounting_lock_date;
    return v == null ? "" : String(v);
  });
  const [bkTick, setBkTick] = useState(0);
  const [bkCreating, setBkCreating] = useState(false);
  const [bkNote, setBkNote] = useState<string | null>(null);
  const [bkError, setBkError] = useState<string | null>(null);
  const [delBk, setDelBk] = useState<any | null>(null);
  const [restoreBk, setRestoreBk] = useState<any | null>(null);
  const [restoreConfirmText, setRestoreConfirmText] = useState("");
  const [restoreBusy, setRestoreBusy] = useState(false);
  const [curTick, setCurTick] = useState(0);
  const currencies = useFetch(
    () => (platform ? Promise.resolve([]) : api.get<any[]>("/currencies")),
    `admin-currencies-${curTick}`,
  );
  const [newCur, setNewCur] = useState({ code: "", name: "", rate: "" });
  const backups = useFetch(
    () => (platform ? api.get<any[]>("/admin/backups") : Promise.resolve([])),
    `admin-backups-${bkTick}`,
  );
  const dl = useAction();
  const [editLimit, setEditLimit] = useState("");
  const [editSafeLimit, setEditSafeLimit] = useState("");
  const [editBranchLimit, setEditBranchLimit] = useState("");
  const [editActive, setEditActive] = useState(true);
  const [editAdminName, setEditAdminName] = useState("");
  const [editAdminPassword, setEditAdminPassword] = useState("");
  const [selBranches, setSelBranches] = useState<{ id: number; name: string; code: string; location: string | null; is_active: boolean }[]>([]);
  const [selWarehouses, setSelWarehouses] = useState<{ id: number; name: string; code: string; branch_id: number; location: string | null; is_active: boolean }[]>([]);
  const [selSafes, setSelSafes] = useState<{ id: number; name: string; code: string; branch_id: number; balance: string; is_active: boolean }[]>([]);
  const [editingSafe, setEditingSafe] = useState<{ id: number; name: string; code: string; branch_id: number; balance: string; is_active: boolean } | null>(null);
  const [selBanks, setSelBanks] = useState<{ id: number; name: string; code: string; account_number: string | null; branch_id: number | null; branch_name: string | null; balance: string; is_active: boolean }[]>([]);
  const [editingBank, setEditingBank] = useState<{ id: number; name: string; code: string; account_number: string | null; branch_id: number | null; branch_name: string | null; balance: string; is_active: boolean } | null>(null);
  const [editingWarehouse, setEditingWarehouse] = useState<{ id: number; name: string; code: string; branch_id: number; location: string | null; is_active: boolean } | null>(null);
  const [allBranches, setAllBranches] = useState<{ company: string; company_id: number; id: number; name: string; code: string; location: string | null; is_active: boolean }[]>([]);
  const [editingBranch, setEditingBranch] = useState<{ company: string; company_id: number; id: number; name: string; code: string; location: string | null; is_active: boolean } | null>(null);
  const [companyAdmins, setCompanyAdmins] = useState<Record<number, string>>({});
  const [newBranchName, setNewBranchName] = useState("");
  const [newBranchLocation, setNewBranchLocation] = useState("");
  const [newWhName, setNewWhName] = useState("");
  const [newWhBranch, setNewWhBranch] = useState<number | null>(null);
  const [newWhLocation, setNewWhLocation] = useState("");
  const [newSafeName, setNewSafeName] = useState("");
  const [newSafeBranch, setNewSafeBranch] = useState<number | null>(null);
  const [newBankName, setNewBankName] = useState("");
  const [newBankAccount, setNewBankAccount] = useState("");
  const [newBankOpeningBalance, setNewBankOpeningBalance] = useState("0");
  const [newBankBranch, setNewBankBranch] = useState(""); // "" = الشركة ككل
  const [companyWarehouseLimit, setCompanyWarehouseLimit] = useState("");
  const [companySafeLimit, setCompanySafeLimit] = useState("");
  // رخصة الاستخدام: التجديد عبر نافذة تطلب كلمة سر المورّد (LICENSE_RENEWAL_PASSWORD على الخادم).
  const [renewing, setRenewing] = useState<{ id: number; name: string; until: string } | null>(null);
  const [renewDate, setRenewDate] = useState("");
  const [renewPwd, setRenewPwd] = useState("");
  const [licenseMsg, setLicenseMsg] = useState<string | null>(null);
  const renewLicense = async (e: FormEvent) => {
    e.preventDefault();
    if (!renewing) return;
    await run(async () => {
      await api.put(`/platform/companies/${renewing.id}/license`, { license_until: renewDate || null, license_password: renewPwd });
      await companies.reload();
      setRenewing(null);
      setRenewPwd("");
      setLicenseMsg(renewDate ? `✅ رخصة «${renewing.name}» حُدّثت حتى ${renewDate}` : `✅ أُلغي قيد الرخصة على «${renewing.name}» (غير مقيّد)`);
    });
  };
  const licenseDaysLeft = (until: string) => Math.ceil((new Date(until).getTime() - Date.now()) / 86400000);
  useEffect(() => {
    if (!platform || !companies.data?.length) return;
    let cancelled = false;
    (async () => {
      const out: { company: string; company_id: number; id: number; name: string; code: string; location: string | null; is_active: boolean }[] = [];
      const admins: Record<number, string> = {};
      for (const c of companies.data ?? []) {
        try {
          const bs = await api.get<{ id: number; name: string; code: string; location: string | null; is_active: boolean }[]>(`/platform/companies/${c.id}/branches`);
          for (const b of bs) out.push({ company: c.name, company_id: c.id, ...b });
        } catch { /* ignore */ }
        try {
          const u = await api.get<{ username: string; full_name: string | null }>(`/platform/companies/${c.id}/admin`);
          admins[c.id] = u.full_name?.trim() || u.username;
        } catch { /* ignore */ }
      }
      if (!cancelled) { setAllBranches(out); setCompanyAdmins(admins); }
    })();
    return () => { cancelled = true; };
  }, [platform, companies.data]);
  useEffect(() => {
    if (!platform) return;
    if (selectedCompany === null) {
      if (currentCompany.data?.id) {
        selectCompany(currentCompany.data.id);
      } else if (companies.data && companies.data.length > 0) {
        selectCompany(companies.data[0].id);
      }
    }
  }, [platform, currentCompany.data, companies.data, selectedCompany]);

  const { busy, error, run } = useAction();

  const deleteBranch = (branch: { company: string; company_id: number; id: number; name: string }) => {
    if (!window.confirm(`هل تريد حذف الفرع «${branch.name}»؟`)) return;
    void run(async () => {
      await api.del(`/platform/companies/${branch.company_id}/branches/${branch.id}`);
      setAllBranches((current) => current.filter((item) => item.id !== branch.id || item.company_id !== branch.company_id));
      if (selectedCompany === branch.company_id) selectCompany(branch.company_id);
    });
  };

  const saveBranch = (e: FormEvent) => {
    e.preventDefault();
    if (!editingBranch) return;
    void run(async () => {
      await api.patch(`/platform/companies/${editingBranch.company_id}/branches/${editingBranch.id}`, {
        name: editingBranch.name.trim(),
        code: editingBranch.code.trim() || undefined,
        location: editingBranch.location,
        is_active: editingBranch.is_active,
      });
      const companyId = editingBranch.company_id;
      setEditingBranch(null);
      const updated = await api.get<{ id: number; name: string; code: string; location: string | null; is_active: boolean }[]>(`/platform/companies/${companyId}/branches`);
      const companyName = companies.data?.find((item) => item.id === companyId)?.name ?? "";
      setAllBranches((current) => [
        ...current.filter((branch) => branch.company_id !== companyId),
        ...updated.map((branch) => ({ ...branch, company: companyName, company_id: companyId })),
      ]);
      if (selectedCompany === companyId) selectCompany(companyId);
    });
  };

  const saveSettings = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.patch("/company", {
        max_warehouses_per_branch: limit?.trim() ? Number(limit) : null,
      });
      setLimit(null);
      currentCompany.reload();
      onSaved?.();
      navigate("/");
    });
  };

  const addBranch = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/company/branches", { name: branchName.trim(), location: branchLocation.trim() || null });
      setBranchName("");
      setBranchLocation("");
      branches.reload();
    });
  };

  const selectCompany = (companyId: number) => {
    setSelectedCompany(companyId);
    void api.get<{ id: number; name: string; code: string; location: string | null; is_active: boolean }[]>(`/platform/companies/${companyId}/branches`).then(setSelBranches).catch(() => setSelBranches([]));
    void api.get<{ id: number; name: string; code: string; branch_id: number; location: string | null; is_active: boolean }[]>(`/platform/companies/${companyId}/warehouses`).then(setSelWarehouses).catch(() => setSelWarehouses([]));
    void api.get<{ id: number; name: string; code: string; branch_id: number; balance: string; is_active: boolean }[]>(`/platform/companies/${companyId}/safes`).then(setSelSafes).catch(() => setSelSafes([]));
    void api.get<Department[]>(`/platform/companies/${companyId}/departments`).then(setSelDepartments).catch(() => setSelDepartments([]));
    void api.get<{ id: number; name: string; code: string; account_number: string | null; branch_id: number | null; branch_name: string | null; balance: string; is_active: boolean }[]>(`/platform/companies/${companyId}/banks`).then(setSelBanks).catch(() => setSelBanks([]));
  };

  const addSelBranch = (e: FormEvent) => {
    e.preventDefault();
    if (!selectedCompany) return;
    void run(async () => {
      await api.post(`/platform/companies/${selectedCompany}/branches`, { name: newBranchName.trim(), location: newBranchLocation.trim() || null });
      setNewBranchName("");
      setNewBranchLocation("");
      selectCompany(selectedCompany);
    });
  };

  const addSelWarehouse = (e: FormEvent) => {
    e.preventDefault();
    if (!selectedCompany) return;
    void run(async () => {
      await api.post(`/platform/companies/${selectedCompany}/warehouses`, { name: newWhName.trim(), branch_id: newWhBranch, location: newWhLocation.trim() || null });
      setNewWhName(""); setNewWhBranch(null); setNewWhLocation("");
      selectCompany(selectedCompany);
    });
  };

  const addCompanyEmployee = (e: FormEvent) => {
    e.preventDefault();
    if (newEmployeeRole === "staff" && !newEmployeeAllBranches && newEmployeeBranches.length === 0) return;
    void run(async () => {
      const created = await api.post<User>("/company/employees", {
        username: newEmployeeUsername.trim(),
        full_name: newEmployeeName.trim() || null,
        password: newEmployeePassword,
        role: newEmployeeRole,
        department_id: newEmployeeDepartment ? Number(newEmployeeDepartment) : null,
        all_branches: newEmployeeRole === "staff" ? newEmployeeAllBranches : false,
        branch_ids: newEmployeeRole === "staff" && !newEmployeeAllBranches ? newEmployeeBranches : [],
        warehouse_ids: [],
      });
      setNewEmployeeUsername("");
      setNewEmployeeName("");
      setNewEmployeePassword("");
      setNewEmployeeDepartment("");
      setNewEmployeeBranches([]);
      currentEmployees.reload();
      window.alert(`تم إنشاء الموظف. رمز الموظف واسم الدخول: ${created.employee_code || created.username}`);
    });
  };

  const openEmployeeEditor = (employee: User) => {
    setEditingEmployee(employee);
    setEmployeeDepartment(String(employee.department_id ?? ""));
    setEmployeeAllBranches(employee.all_branches ?? false);
    setEmployeeBranches(employee.branch_ids ?? []);
    setEmployeeRole(employee.role);
    setEmployeeActive(employee.is_active);
    setEmployeePassword("");
    setEmployeeWarehouseIds(employee.warehouse_ids ?? []);
  };

  const saveCompanyEmployee = (e: FormEvent) => {
    e.preventDefault();
    if (!editingEmployee) return;
    void run(async () => {
      const payload: Record<string, unknown> = {
        full_name: editingEmployee.full_name,
        department_id: employeeDepartment ? Number(employeeDepartment) : null,
        all_branches: employeeRole === "staff" ? employeeAllBranches : false,
        branch_ids: employeeRole === "staff" && !employeeAllBranches ? employeeBranches : [],
        warehouse_ids: employeeWarehouseIds,
        role: employeeRole,
        is_active: employeeActive,
      };
      if (employeePassword) payload.password = employeePassword;
      await api.patch(`/company/employees/${editingEmployee.id}`, payload);
      setEditingEmployee(null);
      currentEmployees.reload();
    });
  };

  const addDepartment = (e: FormEvent) => {
    e.preventDefault();
    if (platform ? selectedCompany === null : !isAdmin || !currentCompany.data?.id) return;
    void run(async () => {
      const path = platform ? `/platform/companies/${selectedCompany}/departments` : "/company/departments";
      const created = await api.post<Department>(path, {
        name: newDepartmentName.trim(),
        description: newDepartmentDescription.trim() || null,
      });
      setNewDepartmentName("");
      setNewDepartmentDescription("");
      if (platform) setSelDepartments((items) => [...items, created].sort((a, b) => a.name.localeCompare(b.name)));
      else currentDepartments.reload();
    });
  };

  const saveDepartment = (e: FormEvent) => {
    e.preventDefault();
    if (!editingDepartment) return;
    void run(async () => {
      const base = platform ? `/platform/companies/${selectedCompany}/departments` : "/company/departments";
      const saved = await api.patch<Department>(`${base}/${editingDepartment.id}`, {
        name: editingDepartment.name.trim(),
        code: editingDepartment.code.trim() || undefined,
        description: editingDepartment.description?.trim() || null,
        is_active: editingDepartment.is_active,
      });
      setEditingDepartment(null);
      if (platform) setSelDepartments((items) => items.map((item) => item.id === saved.id ? saved : item));
      else currentDepartments.reload();
    });
  };

  const deleteDepartment = (department: Department) => {
    if (!window.confirm(`حذف القسم «${department.name}»؟`)) return;
    void run(async () => {
      if (platform) {
        await api.del(`/platform/companies/${selectedCompany}/departments/${department.id}`);
        setSelDepartments((items) => items.filter((item) => item.id !== department.id));
      } else {
        await api.del(`/company/departments/${department.id}`);
        currentDepartments.reload();
      }
    });
  };

  const addSafe = (e: FormEvent) => {
    e.preventDefault();
    if (selectedCompany === null || newSafeBranch === null) return;
    void run(async () => {
      await api.post(`/platform/companies/${selectedCompany}/safes`, { name: newSafeName.trim(), branch_id: newSafeBranch });
      setNewSafeName("");
      setNewSafeBranch(null);
      void api.get<{ id: number; name: string; code: string; branch_id: number; balance: string; is_active: boolean }[]>(`/platform/companies/${selectedCompany}/safes`).then(setSelSafes).catch(() => setSelSafes([]));
    });
  };

  const saveSafe = (e: FormEvent) => {
    e.preventDefault();
    if (selectedCompany === null || !editingSafe) return;
    void run(async () => {
      await api.patch(`/platform/companies/${selectedCompany}/safes/${editingSafe.id}`, {
        name: editingSafe.name.trim(),
        code: editingSafe.code.trim() || undefined,
        branch_id: editingSafe.branch_id,
        is_active: editingSafe.is_active,
      });
      setEditingSafe(null);
      const refreshed = await api.get<{ id: number; name: string; code: string; branch_id: number; balance: string; is_active: boolean }[]>(`/platform/companies/${selectedCompany}/safes`);
      setSelSafes(refreshed);
    });
  };

  const addBank = (e: FormEvent) => {
    e.preventDefault();
    if (selectedCompany === null) return;
    void run(async () => {
      await api.post(`/platform/companies/${selectedCompany}/banks`, {
        name: newBankName.trim(),
        account_number: newBankAccount.trim() || null,
        opening_balance: Number(newBankOpeningBalance) || 0,
        branch_id: newBankBranch === "" ? null : Number(newBankBranch),
      });
      setNewBankName("");
      setNewBankAccount("");
      setNewBankOpeningBalance("0");
      setNewBankBranch("");
      void api.get<{ id: number; name: string; code: string; account_number: string | null; branch_id: number | null; branch_name: string | null; balance: string; is_active: boolean }[]>(`/platform/companies/${selectedCompany}/banks`).then(setSelBanks).catch(() => setSelBanks([]));
    });
  };

  const addCurrentBank = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/banks", {
        name: newBankName.trim(),
        account_number: newBankAccount.trim() || null,
        opening_balance: Number(newBankOpeningBalance) || 0,
        branch_id: newBankBranch === "" ? null : Number(newBankBranch),
      });
      setNewBankName("");
      setNewBankAccount("");
      setNewBankOpeningBalance("0");
      setNewBankBranch("");
      currentBanks.reload();
    });
  };

  const saveBank = (e: FormEvent) => {
    e.preventDefault();
    if (!editingBank) return;
    void run(async () => {
      if (selectedCompany !== null) {
        await api.patch(`/platform/companies/${selectedCompany}/banks/${editingBank.id}`, {
          name: editingBank.name.trim(),
          code: editingBank.code.trim() || undefined,
          account_number: editingBank.account_number?.trim() || null,
          is_active: editingBank.is_active,
        });
        const refreshed = await api.get<{ id: number; name: string; code: string; account_number: string | null; branch_id: number | null; branch_name: string | null; balance: string; is_active: boolean }[]>(`/platform/companies/${selectedCompany}/banks`);
        setSelBanks(refreshed);
      } else {
        await api.patch(`/banks/${editingBank.id}`, {
          name: editingBank.name.trim(),
          code: editingBank.code.trim() || undefined,
          account_number: editingBank.account_number?.trim() || null,
          is_active: editingBank.is_active,
        });
        currentBanks.reload();
      }
      setEditingBank(null);
    });
  };

  const deleteBank = (bank: { id: number; name: string }) => {
    if (selectedCompany === null || !window.confirm(`حذف البنك «${bank.name}»؟`)) return;
    void run(async () => {
      await api.del(`/platform/companies/${selectedCompany}/banks/${bank.id}`);
      const refreshed = await api.get<{ id: number; name: string; code: string; account_number: string | null; branch_id: number | null; branch_name: string | null; balance: string; is_active: boolean }[]>(`/platform/companies/${selectedCompany}/banks`);
      setSelBanks(refreshed);
    });
  };

  const saveWarehouse = (e: FormEvent) => {
    e.preventDefault();
    if (!editingWarehouse || selectedCompany === null) return;
    void run(async () => {
      await api.patch(`/platform/companies/${selectedCompany}/warehouses/${editingWarehouse.id}`, {
        name: editingWarehouse.name.trim(),
        code: editingWarehouse.code.trim() || undefined,
        branch_id: editingWarehouse.branch_id,
        location: editingWarehouse.location,
        is_active: editingWarehouse.is_active,
      });
      setEditingWarehouse(null);
      selectCompany(selectedCompany);
    });
  };

  const deleteWarehouse = (warehouse: { id: number; name: string }) => {
    if (selectedCompany === null || !window.confirm(`حذف المخزن «${warehouse.name}»؟`)) return;
    void run(async () => {
      await api.del(`/platform/companies/${selectedCompany}/warehouses/${warehouse.id}`);
      selectCompany(selectedCompany);
    });
  };

  const addCompany = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/platform/companies", {
        name: companyName.trim(),
        max_warehouses_per_branch: companyWarehouseLimit ? Number(companyWarehouseLimit) : null,
        max_safes_per_branch: companySafeLimit ? Number(companySafeLimit) : null,
        admin_username: adminUsername.trim(),
        admin_full_name: adminFullName.trim() || null,
        admin_password: adminPassword,
      });
      setCompanyName("");
      setAdminUsername("");
      setAdminFullName("");
      setAdminPassword("");
      setCompanyWarehouseLimit("");
      setCompanySafeLimit("");
      companies.reload();
    });
  };

  const saveCompany = () => {
    if (!editingCompany) return;
    void run(async () => {
      await api.patch(`/platform/companies/${editingCompany.id}`, {
        name: editName.trim() || undefined,
        max_warehouses_per_branch: editLimit.trim() ? Number(editLimit) : null,
        max_safes_per_branch: editSafeLimit.trim() ? Number(editSafeLimit) : null,
        max_branches: editBranchLimit.trim() ? Number(editBranchLimit) : null,
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
  };

  return (
    <div className="company-admin-page">
      <PageHeader title={platform ? "إدارة الشركات" : "الفروع وإعدادات الشركة"} />
      <Alert>{error || currentCompany.error || branches.error || companies.error || (!platform ? currentEmployees.error : null)}</Alert>


      {!platform && (
        <div className="card" style={{ padding: 20, marginBottom: 16 }}>
          <h2 style={{ margin: "0 0 12px" }}>💱 العملات وأسعار الصرف</h2>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end", marginBottom: 12 }}>
            <Field label="الرمز (3 أحرف)"><input dir="ltr" maxLength={3} value={newCur.code} placeholder="USD" onChange={(e) => setNewCur({ ...newCur, code: e.target.value.toUpperCase() })} style={{ width: 80 }} /></Field>
            <Field label="الاسم"><input value={newCur.name} placeholder="دولار أمريكي" onChange={(e) => setNewCur({ ...newCur, name: e.target.value })} /></Field>
            <Field label="السعر (جنيه)"><input dir="ltr" type="number" step="0.000001" min={0.000001} value={newCur.rate} placeholder="48.50" onChange={(e) => setNewCur({ ...newCur, rate: e.target.value })} style={{ width: 110 }} /></Field>
            <button className="btn btn-primary" disabled={busy} onClick={async () => {
              try {
                await api.post("/currencies", { code: newCur.code, name: newCur.name, rate: newCur.rate });
                setNewCur({ code: "", name: "", rate: "" });
                setCurTick((t) => t + 1);
              } catch (err) { alert((err as Error).message); }
            }}>+ إضافة عملة</button>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>الرمز</th><th>الاسم</th><th>السعر الحالي (جنيه)</th><th>تحديث السعر</th><th></th></tr></thead>
              <tbody>
                {(currencies.data ?? []).map((cur: any) => (
                  <tr key={cur.id}>
                    <td dir="ltr">{cur.code}</td>
                    <td>{cur.name}</td>
                    <td className="num">{money(cur.rate)}</td>
                    <td>
                      <input dir="ltr" type="number" step="0.000001" min={0.000001} defaultValue={String(cur.rate)}
                        style={{ width: 110 }} onBlur={async (e) => {
                          if (Number(e.target.value) && Number(e.target.value) !== Number(cur.rate)) {
                            try { await api.patch(`/currencies/${cur.id}/rate`, { rate: e.target.value }); setCurTick((t) => t + 1); }
                            catch (err) { alert((err as Error).message); }
                          }
                        }} />
                    </td>
                    <td><button className="btn-delete" onClick={async () => {
                      if (!confirm(`إيقاف/حذف ${cur.code}؟`)) return;
                      try { await api.del(`/currencies/${cur.id}`); setCurTick((t) => t + 1); } catch (err) { alert((err as Error).message); }
                    }}>حذف</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!platform && (
        <div className="card" style={{ padding: 20, marginBottom: 16 }}>
          <h2 style={{ margin: "0 0 12px" }}>إعدادات الشركة</h2>
          <form onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api.patch("/company", {
                je_approval_threshold: jeThreshold === "" ? null : jeThreshold,
                accounting_lock_date: lockDate === "" ? null : lockDate,
              });
              alert("تم حفظ إعدادات الشركة بنجاح");
            } catch (err) { alert((err as Error).message); }
          }} className="form-grid">
            <Field label="حد اعتماد القيود" hint="القيود فوق هذا المبلغ من الموظفين تنتظر اعتماد مدير — فارغ = معطّل">
              <input dir="ltr" type="number" step="0.01" min={0} value={jeThreshold} placeholder="معطّل" onChange={(e) => setJeThreshold(e.target.value)} />
            </Field>
            <Field label="تاريخ قفل الحسابات (Lock Date)" hint="يمنع إدخال أو ترحيل أي قيود/سندات بتاريخ أقدم من أو يساوي هذا التاريخ">
              <input type="date" value={lockDate} onChange={(e) => setLockDate(e.target.value)} />
            </Field>
            <button className="btn btn-primary" disabled={busy}>حفظ الإعدادات</button>
          </form>
        </div>
      )}

      {platform && (
        <div className="card" style={{ padding: 20, marginBottom: 16 }}>
          <form onSubmit={addCompany}>
            <button className="btn btn-primary" disabled={busy} style={{ marginBottom: 12 }}>إنشاء الشركة</button>
            <div className="form-grid">
              <Field label="اسم الشركة" hint="رمز الشركة سيُنشأ تلقائيًا عند الحفظ"><input value={companyName} onChange={(e) => setCompanyName(e.target.value)} required /></Field>
              <Field label="الحد الأقصى للمخازن لكل فرع"><input type="number" min={1} value={companyWarehouseLimit} onChange={(e) => setCompanyWarehouseLimit(e.target.value)} /></Field>
              <Field label="الحد الأقصى للخزائن لكل فرع"><input type="number" min={1} value={companySafeLimit} onChange={(e) => setCompanySafeLimit(e.target.value)} /></Field>
              <Field label="اسم المستخدم للمدير الأول"><input dir="ltr" minLength={3} value={adminUsername} onChange={(e) => setAdminUsername(e.target.value)} required /></Field>
              <Field label="اسم المدير الأول"><input value={adminFullName} onChange={(e) => setAdminFullName(e.target.value)} required /></Field>
              <Field label="كلمة مرور المدير"><input type="password" minLength={8} value={adminPassword} onChange={(e) => setAdminPassword(e.target.value)} required /></Field>
            </div>
          </form>
        </div>
      )}


      {platform && <div className="card table-wrap" style={{ marginBottom: 16 }}>
            <h2 style={{ padding: 16 }}>الشركات المسجلة</h2>
            {licenseMsg && <div style={{ padding: "0 16px 12px" }}><Alert kind="info">{licenseMsg}</Alert></div>}
            {error && <div style={{ padding: "0 16px 12px" }}><Alert kind="error">{error}</Alert></div>}
            {companies.loading && !companies.data ? <Loading /> : companies.data?.length ? (
              <table>
                <thead><tr><th>الشركة</th><th>اسم المدير الأول</th><th>حد المخازن لكل فرع</th><th>حد الخزائن لكل فرع</th><th>حد الفروع</th><th>رخصة الاستخدام</th><th>الحالة</th></tr></thead>
                <tbody>{companies.data.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => selectCompany(item.id)}
                    style={{
                      cursor: "pointer",
                      background: selectedCompany === item.id ? "rgba(37, 99, 235, 0.08)" : undefined,
                    }}
                  >
                    <td>
                      <strong>{item.name}</strong>
                      {selectedCompany === item.id && (
                        <span style={{ marginInlineStart: 8, fontSize: 12, color: "var(--primary)", fontWeight: "bold" }}>
                          (المحددة)
                        </span>
                      )}
                    </td><td dir="ltr">{companyAdmins[item.id] || "—"}</td>
                    <td>{item.max_warehouses_per_branch ?? "غير محدود"}</td><td>{item.max_safes_per_branch ?? "غير محدود"}</td><td>{item.max_branches ?? "غير محدود"}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => {
                          setLicenseMsg(null);
                          setRenewPwd("");
                          setRenewDate(item.license_until ?? "");
                          setRenewing({ id: item.id, name: item.name, until: item.license_until ?? "" });
                        }}
                      >
                        🔑 تجديد
                      </button>
                      {item.license_until && (() => {
                        const d = licenseDaysLeft(item.license_until);
                        return (
                          <small style={{ display: "block", fontSize: 11, marginTop: 2, color: d < 0 ? "var(--danger)" : d <= 30 ? "var(--warn)" : "var(--ok)", fontWeight: 600 }}>
                            {d < 0 ? `⛔ منتهية منذ ${Math.abs(d)} يوم` : d === 0 ? "تنتهي اليوم" : `متبقي ${d} يوم`}
                          </small>
                        );
                      })()}
                    </td>
                    <td><ActiveBadge active={item.is_active} /> <button className="btn-edit" style={{ marginInlineStart: 8 }} onClick={(e) => { e.stopPropagation(); setEditingCompany(item); setEditName(item.name); setEditLimit(item.max_warehouses_per_branch ? String(item.max_warehouses_per_branch) : ""); setEditSafeLimit(item.max_safes_per_branch ? String(item.max_safes_per_branch) : ""); setEditBranchLimit(item.max_branches ? String(item.max_branches) : ""); setEditActive(item.is_active); setEditAdminName(""); setEditAdminPassword(""); void api.get<{ full_name: string | null }>(`/platform/companies/${item.id}/admin`).then((u) => setEditAdminName(u.full_name || "")).catch(() => {}); }}>تعديل</button></td>
                  </tr>
                ))}</tbody>
              </table>
            ) : <Empty>لا توجد شركات.</Empty>}
          </div>}

          {platform && renewing && (
            <Modal title={`🔑 تجديد رخصة — ${renewing.name}`} onClose={() => setRenewing(null)}>
              <form onSubmit={renewLicense}>
                {error && <Alert kind="error">{error}</Alert>}
                <Field label="تاريخ انتهاء الرخصة الجديد" hint="فارغ = إلغاء القيد (غير مقيّد)">
                  <input type="date" dir="ltr" value={renewDate} onChange={(e) => setRenewDate(e.target.value)} />
                </Field>
                <Field label="كلمة سر التجديد (سر المورّد)" hint="كلمة السر المخصصة لتجديد الرخص — تُضبط على الخادم فقط">
                  <input
                    type="password"
                    dir="ltr"
                    autoComplete="off"
                    placeholder="كلمة سر التجديد"
                    value={renewPwd}
                    onChange={(e) => setRenewPwd(e.target.value)}
                    required
                  />
                </Field>
                <div className="form-actions">
                  <button type="submit" className="btn btn-primary" disabled={busy}>تأكيد التجديد</button>
                  <button type="button" className="btn" onClick={() => setRenewing(null)}>إلغاء</button>
                </div>
              </form>
            </Modal>
          )}

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

          <div className="card" style={{ padding: 20, marginBottom: 16 }}>
            <h2>أقسام الشركة</h2>
            {isAdmin && <form onSubmit={addDepartment} className="form-grid" style={{ marginBottom: 14 }}>
              <Field label="اسم القسم" hint="مثال: الحسابات، المبيعات، الموارد البشرية"><input value={newDepartmentName} onChange={(event) => setNewDepartmentName(event.target.value)} required /></Field>
              <Field label="وصف القسم"><input value={newDepartmentDescription} onChange={(event) => setNewDepartmentDescription(event.target.value)} placeholder="اختياري" /></Field>
              <button className="btn btn-primary" disabled={busy}>{busy ? "جارٍ الحفظ…" : "إضافة قسم"}</button>
            </form>}
            {currentDepartments.data?.length ? <div className="table-wrap"><table>
              <thead><tr><th>اسم القسم</th><th>الوصف</th><th>الحالة</th><th>الرمز</th><th /></tr></thead>
              <tbody>{(currentDepartments.data ?? []).map((department) => <tr key={department.id}>
                <td>{department.name}</td><td>{department.description || "—"}</td><td><ActiveBadge active={department.is_active} /></td><td dir="ltr">{department.code}</td>
                <td className="actions">{isAdmin && <><button className="btn-edit" onClick={() => setEditingDepartment({ ...department })}>تعديل</button><button className="btn-delete" onClick={() => deleteDepartment(department)}>حذف</button></>}</td>
              </tr>)}</tbody>
            </table></div> : <Empty>لا توجد أقسام مسجلة لهذه الشركة.</Empty>}
          </div>

          <div className="card" style={{ padding: 20, marginBottom: 16 }}>
            <h2>المستخدمون</h2>
            <form onSubmit={addCompanyEmployee} className="form-grid" style={{ marginBottom: 14 }}>
              <Field label="اسم المستخدم / الدخول"><input dir="ltr" minLength={3} value={newEmployeeUsername} onChange={(event) => setNewEmployeeUsername(event.target.value)} required /></Field>
              <Field label="الاسم الكامل"><input value={newEmployeeName} onChange={(event) => setNewEmployeeName(event.target.value)} /></Field>
              <Field label="كلمة المرور"><input type="password" minLength={8} value={newEmployeePassword} onChange={(event) => setNewEmployeePassword(event.target.value)} required /></Field>
              <Field label="القسم"><select value={newEmployeeDepartment} onChange={(event) => setNewEmployeeDepartment(event.target.value)}><option value="">— بدون قسم —</option>{(currentDepartments.data ?? []).filter((department) => department.is_active).map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></Field>
              <Field label="صلاحية الفروع"><select value={newEmployeeRole === "staff" && newEmployeeAllBranches ? "all" : "selected"} onChange={(event) => setNewEmployeeAllBranches(event.target.value === "all")}><option value="all">كل الفروع</option><option value="selected">فروع محددة</option></select></Field>
              {newEmployeeRole === "staff" && !newEmployeeAllBranches && <Field label="اختر الفروع">{branches.data?.length ? branches.data.map((branch) => <label className="check" key={branch.id}><input type="checkbox" checked={newEmployeeBranches.includes(branch.id)} onChange={(event) => setNewEmployeeBranches((items) => event.target.checked ? [...items, branch.id] : items.filter((id) => id !== branch.id))} />{branch.name}</label>) : <span className="muted">لا توجد فروع</span>}{newEmployeeBranches.length === 0 && <span className="field-hint low">اختر فرعًا واحدًا على الأقل أو غيّر النطاق إلى كل الفروع.</span>}</Field>}
              <Field label="الدور"><select value={newEmployeeRole} onChange={(event) => setNewEmployeeRole(event.target.value as Role)}><option value="staff">موظف</option>{isAdmin && <><option value="manager">مدير</option><option value="admin">مدير شركة</option></>}</select></Field>
              <button className="btn btn-primary" disabled={busy || (newEmployeeRole === "staff" && !newEmployeeAllBranches && newEmployeeBranches.length === 0)}>إضافة مستخدم</button>
            </form>
            {currentEmployees.data?.length ? <div className="table-wrap"><table>
              <thead><tr><th>اسم المستخدم</th><th>كود الموظف</th><th>القسم</th><th>الفروع</th><th>الدور</th><th>الحالة</th><th /></tr></thead>
              <tbody>{currentEmployees.data.map((employee) => <tr key={employee.id}>
                <td dir="ltr">{employee.username}</td><td dir="ltr">{employee.employee_code || "—"}</td><td>{employee.department_name || "—"}</td><td>{employee.all_branches ? "كل الفروع" : `محدد (${employee.branch_ids?.length ?? 0})`}</td><td>{employee.role}</td><td><ActiveBadge active={employee.is_active} /></td><td className="actions"><button className="btn-edit" onClick={() => openEmployeeEditor(employee)}>تعديل</button></td>
              </tr>)}</tbody>
            </table></div> : <Empty>{currentEmployees.loading ? "جارٍ تحميل المستخدمين…" : "لا يوجد مستخدمون مسجلون."}</Empty>}
          </div>

          <div className="card" style={{ padding: 20, marginBottom: 16 }}>
            <h2>إضافة فرع</h2>
            <form onSubmit={addBranch} className="company-admin-form branch-form-button-first">
              <button className="btn btn-primary" disabled={busy}>إضافة فرع</button>
              <div className="form-grid">
                <Field label="اسم الفرع" hint="رمز الفرع سيُنشأ تلقائيًا عند الحفظ"><input value={branchName} onChange={(e) => setBranchName(e.target.value)} required /></Field>
                <Field label="عنوان الفرع"><input value={branchLocation} onChange={(e) => setBranchLocation(e.target.value)} placeholder="اختياري" /></Field>
              </div>
            </form>
          </div>

          <div className="card" style={{ padding: 20, marginBottom: 16 }}>
            <form onSubmit={addCurrentBank} className="form-grid warehouse-create-form">
              <button type="submit" className="warehouse-add-icon" disabled={busy} aria-label="إضافة بنك" title="إضافة بنك">إضافة بنك</button>
              <Field label="اسم البنك" hint="رمز البنك سيُنشأ تلقائيًا عند الحفظ"><input value={newBankName} onChange={(event) => setNewBankName(event.target.value)} required /></Field>
              <Field label="رقم الحساب"><input dir="ltr" value={newBankAccount} onChange={(event) => setNewBankAccount(event.target.value)} placeholder="اختياري" /></Field>
              <Field label="الرصيد الافتتاحي"><input type="number" step="0.01" value={newBankOpeningBalance} onChange={(event) => setNewBankOpeningBalance(event.target.value)} /></Field>
              <Field label="الفرع" hint="اختياري — اتركه «الشركة ككل»">
                <select value={newBankBranch} onChange={(event) => setNewBankBranch(event.target.value)}>
                  <option value="">الشركة ككل</option>
                  {(branches.data ?? []).filter((branch) => branch.is_active).map((branch) => (
                    <option key={branch.id} value={branch.id}>{branch.name}</option>
                  ))}
                </select>
              </Field>
            </form>
            <h3>البنوك المسجلة</h3>
            {currentBanks.data && currentBanks.data.length > 0 ? (
              <div className="table-wrap" style={{ marginBottom: 12 }}>
                <table>
                  <thead><tr><th>اسم البنك</th><th>الرمز</th><th>رقم الحساب</th><th>الفرع</th><th>الرصيد</th><th>الحالة</th><th /></tr></thead>
                  <tbody>{currentBanks.data.map((b) => (
                    <tr key={b.id}>
                      <td>{b.name}</td>
                      <td dir="ltr">{b.code}</td>
                      <td dir="ltr">{b.account_number || "—"}</td>
                      <td>{b.branch_name || "الشركة ككل"}</td>
                      <td>{b.balance}</td>
                      <td>
                        <ActiveBadge active={b.is_active} />
                      </td>
                      <td className="actions">
                        <button className="btn-edit" onClick={() => setEditingBank({ ...b })}>تعديل</button>
                      </td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            ) : <Empty>لا توجد بنوك مسجلة.</Empty>}
          </div>
        </>
      )}

      {platform && (
        <>
          {selectedCompany && (
              <>
                <form onSubmit={addSelBranch} className="company-admin-form branch-form-button-first" style={{ marginBottom: 16 }}>
                   <button className="btn btn-primary" disabled={busy}>إضافة فرع</button>
                   <div className="form-grid">
                     <Field label="اسم الفرع" hint="رمز الفرع سيُنشأ تلقائيًا عند الحفظ"><input value={newBranchName} onChange={(e) => setNewBranchName(e.target.value)} required /></Field>
                     <Field label="عنوان الفرع"><input value={newBranchLocation} onChange={(e) => setNewBranchLocation(e.target.value)} placeholder="اختياري" /></Field>
                   </div>
                 </form>
                 <div className="card table-wrap" style={{ marginBottom: 16 }}>
                   <h2 style={{ padding: 16 }}>الفروع المسجلة</h2>
                   {allBranches.length ? (
                     <table>
                       <thead><tr><th>الشركة</th><th>الاسم</th><th>الرمز</th><th>الموقع</th><th>الحالة</th></tr></thead>
                       <tbody>{allBranches.map((b) => (
                         <tr key={`${b.company}-${b.id}`}><td>{b.company}</td><td>{b.name}</td><td dir="ltr">{b.code}</td><td>{b.location || "—"}</td><td><ActiveBadge active={b.is_active} /><span className="branch-row-actions"><button className="btn-edit" onClick={() => setEditingBranch({ ...b })}>تعديل</button><button className="btn-delete" onClick={() => deleteBranch(b)}>حذف</button></span></td></tr>
                       ))}</tbody>
                     </table>
                   ) : <Empty>لا توجد فروع مسجلة.</Empty>}
                 </div>

                 <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                   <h2>أقسام الشركة</h2>
                   <form onSubmit={addDepartment} className="form-grid" style={{ marginBottom: 14 }}>
                     <Field label="اسم القسم" hint="مثال: الحسابات، المبيعات، الموارد البشرية"><input value={newDepartmentName} onChange={(event) => setNewDepartmentName(event.target.value)} required /></Field>
                     <Field label="وصف القسم"><input value={newDepartmentDescription} onChange={(event) => setNewDepartmentDescription(event.target.value)} placeholder="اختياري" /></Field>
                     <button className="btn btn-primary" disabled={busy}>إضافة قسم</button>
                   </form>
                   {selDepartments.length ? <div className="table-wrap"><table>
                     <thead><tr><th>اسم القسم</th><th>الوصف</th><th>الحالة</th><th>الرمز</th><th /></tr></thead>
                     <tbody>{selDepartments.map((department) => <tr key={department.id}>
                       <td>{department.name}</td><td>{department.description || "—"}</td>
                       <td><ActiveBadge active={department.is_active} /></td><td dir="ltr">{department.code}</td>
                       <td className="actions"><button className="btn-edit" onClick={() => setEditingDepartment({ ...department })}>تعديل</button><button className="btn-delete" onClick={() => deleteDepartment(department)}>حذف</button></td>
                     </tr>)}</tbody>
                   </table></div> : <Empty>لا توجد أقسام مسجلة لهذه الشركة.</Empty>}
                 </div>

                 <form onSubmit={addSelWarehouse} className="form-grid warehouse-create-form">
                   <button
                     type="submit"
                     className="warehouse-add-icon"
                     disabled={busy}
                     aria-label="إضافة مخزن"
                     title="إضافة مخزن"
                   >
                     إضافة مخزن
                   </button>
                   <Field label="اسم المخزن" hint="رمز المخزن سيُنشأ تلقائيًا عند الحفظ"><input id="company-warehouse-name" value={newWhName} onChange={(e) => setNewWhName(e.target.value)} required /></Field>
                   <Field label="الفرع">
                     <select value={newWhBranch ?? ""} onChange={(e) => setNewWhBranch(Number(e.target.value) || null)}>
                       <option value="">— اختر فرع —</option>
                       {selBranches.map((b) => (<option key={b.id} value={b.id}>{b.name}</option>))}
                     </select>
                   </Field>
                   <Field label="الموقع"><input value={newWhLocation} onChange={(e) => setNewWhLocation(e.target.value)} /></Field>
                 </form>
                 <h3>المخازن المسجلة</h3>
                 {selWarehouses.length > 0 ? (
                   <div className="table-wrap" style={{ marginBottom: 12 }}>
                     <table>
                       <thead><tr><th>الاسم</th><th>الكود</th><th>الفرع</th><th>الموقع</th><th>الحالة والإجراء</th></tr></thead>
                       <tbody>{selWarehouses.map((w) => (
                         <tr key={w.id}><td>{w.name}</td><td dir="ltr">{w.code}</td><td>{selBranches.find((b) => b.id === w.branch_id)?.name || "—"}</td><td>{w.location || "—"}</td><td><ActiveBadge active={w.is_active} /><span className="branch-row-actions"><button className="btn-edit" onClick={() => setEditingWarehouse({ ...w })}>تعديل</button><button className="btn-delete" onClick={() => deleteWarehouse(w)}>حذف</button></span></td></tr>
                       ))}</tbody>
                     </table>
                   </div>
                 ) : <Empty>لا توجد مخازن.</Empty>}
                <form onSubmit={addSafe} className="form-grid warehouse-create-form">
                  <button type="submit" className="warehouse-add-icon" disabled={busy} aria-label="إضافة خزينة" title="إضافة خزينة">إضافة خزينة</button>
                  <Field label="اسم الخزينة"><input value={newSafeName} onChange={(event) => setNewSafeName(event.target.value)} required /></Field>
                  <Field label="الفرع"><select value={newSafeBranch ?? ""} onChange={(event) => setNewSafeBranch(Number(event.target.value) || null)} required><option value="">اختر الفرع</option>{selBranches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></Field>
                </form>
                <h3>الخزائن المسجلة</h3>
                {selSafes.length > 0 && <div className="table-wrap" style={{ marginBottom: 12 }}><table>
                  <thead><tr><th>اسم الخزينة</th><th>الرمز</th><th>الفرع</th><th>الرصيد</th><th>الحالة</th><th /></tr></thead>
                  <tbody>{selSafes.map((safe) => <tr key={safe.id}><td>{safe.name}</td><td dir="ltr">{safe.code}</td><td>{selBranches.find((branch) => branch.id === safe.branch_id)?.name || "—"}</td><td>{safe.balance}</td><td><ActiveBadge active={safe.is_active} /></td><td className="actions"><button className="btn-edit" onClick={() => setEditingSafe({ ...safe })}>تعديل</button></td></tr>)}</tbody>
                </table></div>}

                <form onSubmit={addBank} className="form-grid warehouse-create-form">
                  <button type="submit" className="warehouse-add-icon" disabled={busy} aria-label="إضافة بنك" title="إضافة بنك">إضافة بنك</button>
                  <Field label="اسم البنك" hint="رمز البنك سيُنشأ تلقائيًا عند الحفظ"><input value={newBankName} onChange={(event) => setNewBankName(event.target.value)} required /></Field>
                  <Field label="رقم الحساب"><input dir="ltr" value={newBankAccount} onChange={(event) => setNewBankAccount(event.target.value)} placeholder="اختياري" /></Field>
                  <Field label="الرصيد الافتتاحي"><input type="number" step="0.01" value={newBankOpeningBalance} onChange={(event) => setNewBankOpeningBalance(event.target.value)} /></Field>
                  <Field label="الفرع" hint="اختياري — اتركه «الشركة ككل»">
                    <select value={newBankBranch} onChange={(event) => setNewBankBranch(event.target.value)}>
                      <option value="">الشركة ككل</option>
                      {selBranches.filter((branch) => branch.is_active).map((branch) => (
                        <option key={branch.id} value={branch.id}>{branch.name}</option>
                      ))}
                    </select>
                  </Field>
                </form>
                <h3>البنوك المسجلة</h3>
                {selBanks.length > 0 ? (
                  <div className="table-wrap" style={{ marginBottom: 12 }}>
                    <table>
                      <thead><tr><th>اسم البنك</th><th>الرمز</th><th>رقم الحساب</th><th>الفرع</th><th>الرصيد</th><th>الحالة</th><th /></tr></thead>
                      <tbody>{selBanks.map((bank) => (
                        <tr key={bank.id}>
                          <td>{bank.name}</td>
                          <td dir="ltr">{bank.code}</td>
                          <td dir="ltr">{bank.account_number || "—"}</td>
                          <td>{bank.branch_name || "الشركة ككل"}</td>
                          <td>{bank.balance}</td>
                          <td>
                            <ActiveBadge active={bank.is_active} />
                          </td>
                          <td className="actions">
                            <button className="btn-edit" onClick={() => setEditingBank({ ...bank })}>تعديل</button>
                            <button className="btn-delete" style={{ marginInlineStart: 6 }} onClick={() => deleteBank(bank)}>حذف</button>
                          </td>
                        </tr>
                      ))}</tbody>
                    </table>
                  </div>
                ) : <Empty>لا توجد بنوك مسجلة.</Empty>}

              </>
            )}


          {platform && (
            <div className="card card-pad" style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
                <h2 style={{ margin: 0 }}>💾 النسخ الاحتياطي</h2>
                <button
                  className="btn btn-primary"
                  disabled={bkCreating}
                  onClick={async () => {
                    setBkCreating(true);
                    setBkError(null);
                    setBkNote(null);
                    try {
                      const r: any = await api.post("/admin/backups", {});
                      setBkNote(`$أُنشئت نسخة ${r?.name} (${fmtSize(r?.size ?? 0)})`);
                      setBkTick((tick) => tick + 1);
                    } catch (err) {
                      setBkError((err as Error).message);
                    } finally {
                      setBkCreating(false);
                    }
                  }}
                >
                  {bkCreating ? "جارٍ إنشاء النسخة…" : "+ إنشاء نسخة الآن"}
                </button>
              </div>
              <p className="muted" style={{ fontSize: 13, margin: "0 0 12px" }}>
                نسخة كاملة لقاعدة البيانات: كل الجداول مع صور المنتجات وسجل التدقيق — بصيغة JSON مضغوطة. تعمل نسخة JSON تلقائية كل ساعة (يُحتفظ بأحدث اثنتين) إضافة إلى نسخ SQL تلقائية، ويمكنك إنشاء نسخة يدوية متى شئت. الاستعادة تستبدل البيانات الحالية بالكامل، فاحتفظ بنسخة خارج الجهاز قبل أي عملية خطرة.
              </p>

              {(() => {
                const autoRows = (backups.data ?? []).filter((b: any) => b.type === "json_auto" || b.type === "sql_auto");
                if (autoRows.length === 0) {
                  return (
                    <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "#fff4d6", color: "#9a6700" }}>
                      🟠 لا نسخ تلقائية بعد — أول نسخة تُنشأ تلقائيًا بعد دقيقة من إقلاع النظام
                    </div>
                  );
                }
                const newestAuto = autoRows.reduce((acc: any, b: any) => ((b.generated_at || "") > (acc.generated_at || "") ? b : acc));
                const minutes = Math.max(0, Math.floor((Date.now() - new Date(newestAuto.generated_at).getTime()) / 60000));
                const healthy = minutes <= 120;
                const when = minutes < 1 ? "أقل من دقيقة" : minutes < 60 ? `${minutes} دقيقة` : `${Math.floor(minutes / 60)} ساعة و${minutes % 60} دقيقة`;
                return healthy ? (
                  <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg)", color: "var(--ok)" }}>
                    🟢 النسخ التلقائية تعمل بانتظام — آخر نسخة قبل {when} ({newestAuto.type === "sql_auto" ? "SQL" : "JSON"})
                  </div>
                ) : (
                  <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "#fee4e2", color: "#b42318" }}>
                    🔴 آخر نسخة تلقائية قبل {when} — المتوقع كل ساعة! تحقق من حاوية النسخ (<code>docker logs ai-erp-system-1-db-backup-1</code>).
                  </div>
                );
              })()}

              <Alert>{bkError}</Alert>
              {bkNote && (
                <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg)", color: "var(--ok)" }}>
                  ✅ {bkNote}
                </div>
              )}

              {(() => {
                const rows = [...(backups.data ?? [])].sort((a: any, b: any) => (b.generated_at || "").localeCompare(a.generated_at || ""));
                const newest = rows[0]?.name;
                const totalSize = rows.reduce((s: number, b: any) => s + (b.size ?? 0), 0);
                if (rows.length === 0) {
                  return <Empty>لا نسخ احتياطية بعد — اضغط «إنشاء نسخة الآن» للبدء.</Empty>;
                }
                return (
                  <>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
                      <div className="card card-pad" style={{ flex: 1, minWidth: 130 }}>
                        <div className="muted" style={{ fontSize: 12 }}>عدد النسخ</div>
                        <div style={{ fontWeight: 800, fontSize: 18 }}>{rows.length}</div>
                      </div>
                      <div className="card card-pad" style={{ flex: 1, minWidth: 130 }}>
                        <div className="muted" style={{ fontSize: 12 }}>إجمالي الحجم</div>
                        <div style={{ fontWeight: 800, fontSize: 18 }}>{fmtSize(totalSize)}</div>
                      </div>
                      <div className="card card-pad" style={{ flex: 2, minWidth: 220 }}>
                        <div className="muted" style={{ fontSize: 12 }}>أحدث نسخة</div>
                        <div style={{ fontWeight: 800, fontSize: 14 }} dir="ltr">{newest}</div>
                      </div>
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>الملف</th>
                            <th>النوع</th>
                            <th>السلامة</th>
                            <th>تاريخ الإنشاء</th>
                            <th className="num">الحجم</th>
                            <th className="actions">إجراءات</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((b: any) => {
                            const kind = b.type ?? "json_manual";
                            const kindLabel = kind === "sql_auto" ? "SQL تلقائية" : kind === "json_auto" ? "JSON كل ساعة" : "JSON يدوية";
                            const kindStyle = kind === "sql_auto"
                              ? { background: "#e3f2fd", color: "#0d47a1" }
                              : kind === "json_auto"
                                ? { background: "#dcfce7", color: "#15803d" }
                                : { background: "#f6f8fa", color: "#57606a" };
                            return (
                            <tr key={b.name}>
                              <td dir="ltr">
                                <b>{b.name}</b>
                                {b.name === newest && (
                                  <span className="badge badge-confirmed" style={{ marginInlineStart: 8, fontSize: 11 }}>الأحدث</span>
                                )}
                              </td>
                              <td>
                                <span className="badge" style={{ ...kindStyle, borderRadius: 999, padding: "2px 10px", fontSize: 12, fontWeight: 700 }}>
                                  {kindLabel}
                                </span>
                              </td>
                              <td>
                                {b.valid?.ok
                                  ? <span style={{ color: "#15803d", fontSize: 12 }} title={b.valid.detail}>✅ سليمة</span>
                                  : <span style={{ color: "#b42318", fontSize: 12, fontWeight: 700 }} title={b.valid?.detail}>⚠️ تالفة</span>}
                              </td>
                              <td>{fmtDateTimeAr(b.generated_at)}</td>
                              <td className="num">{fmtSize(b.size)}</td>
                              <td className="actions">
                                <button className="btn btn-sm" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/admin/backups/${b.name}/download`, b.name))}>
                                  ⬇️ تنزيل
                                </button>{" "}
                                {kind !== "sql_auto" && (
                                  <>
                                    <button className="btn btn-sm" style={{ color: "#b42318", borderColor: "#b42318" }} onClick={() => setDelBk(b)}>
                                      حذف
                                    </button>{" "}
                                    <button
                                      className="btn-delete"
                                      disabled={b.valid && !b.valid.ok}
                                      title={b.valid && !b.valid.ok ? "نسخة تالفة — لا يمكن الاستعادة منها" : undefined}
                                      onClick={() => { setRestoreBk(b); setRestoreConfirmText(""); }}
                                    >
                                      ♻️ استعادة
                                    </button>
                                  </>
                                )}
                                {kind === "sql_auto" && (
                                  <small className="muted" style={{ fontSize: 11 }}>تُدار تلقائيًا — تُستعاد عبر psql</small>
                                )}
                              </td>
                            </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </>
                );
              })()}
            </div>
          )}
        </>
      )}

      {delBk && (
        <Modal title={`حذف نسخة احتياطية — ${delBk.name}`} onClose={() => setDelBk(null)}>
          <p style={{ margin: "0 0 6px" }}>
            سيُحذف ملف النسخة <b dir="ltr">{delBk.name}</b> ({fmtSize(delBk.size)}) نهائيًا.
            البيانات الحالية لا تتأثر — لكنك ستفقد هذه النسخة إلى الأبد.
          </p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn-delete"
              onClick={async () => {
                try {
                  await api.del(`/admin/backups/${delBk.name}`);
                  setDelBk(null);
                  setBkError(null);
                  setBkNote(null);
                  setBkTick((tick) => tick + 1);
                } catch (err) {
                  setDelBk(null);
                  setBkError((err as Error).message);
                }
              }}
            >
              نعم، حذف النسخة
            </button>
            <button type="button" className="btn" onClick={() => setDelBk(null)}>إلغاء</button>
          </div>
        </Modal>
      )}

      {restoreBk && (
        <Modal title={`♻️ استعادة من ${restoreBk.name}`} onClose={() => { setRestoreBk(null); setRestoreConfirmText(""); }}>
          <div dir="rtl" style={{ marginBottom: 12, padding: "10px 12px", borderRadius: 8, fontSize: 13, background: "#fee4e2", color: "#b42318" }}>
            ⚠️ <b>عملية خطيرة ولا يمكن التراجع عنها:</b> ستُمسح كل البيانات الحالية في كل الشركات
            (أوامر، قيود، عملاء، مستخدمون…) وتُستبدل بمحتوى النسخة
            "<b dir="ltr">{restoreBk.name}</b>" من <b>{fmtDateTimeAr(restoreBk.generated_at)}</b>.
            ستحتاج إلى تسجيل دخول من جديد بعد اكتمالها.
          </div>
          <Field label="اكتب «استعادة» بالضبط للتأكيد">
            <input
              value={restoreConfirmText}
              onChange={(e) => setRestoreConfirmText(e.target.value)}
              placeholder="استعادة"
              dir="ltr"
            />
          </Field>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn-delete"
              disabled={restoreBusy || restoreConfirmText.trim() !== "استعادة"}
              onClick={async () => {
                setRestoreBusy(true);
                try {
                  const r: any = await api.post(`/admin/backups/${restoreBk.name}/restore`, { confirm: restoreConfirmText.trim() });
                  setRestoreBk(null);
                  setRestoreConfirmText("");
                  setBkNote(`تمت الاستعادة — ${r?.rows} صف في ${r?.tables} جدول. سجّل الدخول من جديد.`);
                } catch (err) {
                  setRestoreBk(null);
                  setRestoreConfirmText("");
                  setBkError((err as Error).message);
                } finally {
                  setRestoreBusy(false);
                }
              }}
            >
              {restoreBusy ? "جارٍ الاستعادة…" : "استعادة البيانات"}
            </button>
            <button type="button" className="btn" onClick={() => { setRestoreBk(null); setRestoreConfirmText(""); }}>إلغاء</button>
          </div>
        </Modal>
      )}

      {editingEmployee && (
        <Modal title={`تعديل مستخدم — ${editingEmployee.username}`} onClose={() => setEditingEmployee(null)}>
          <form onSubmit={saveCompanyEmployee}>
            <Alert>{currentEmployees.error}</Alert>
            <Field label="القسم"><select value={employeeDepartment} onChange={(event) => setEmployeeDepartment(event.target.value)}><option value="">— بدون قسم —</option>{(currentDepartments.data ?? []).filter((department) => department.is_active).map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></Field>
            <Field label="نطاق الفروع"><select value={employeeAllBranches ? "all" : "selected"} onChange={(event) => setEmployeeAllBranches(event.target.value === "all")}><option value="all">كل الفروع</option><option value="selected">فروع محددة</option></select></Field>
            {employeeRole === "staff" && !employeeAllBranches && <Field label="الفروع المسموح بها">{(branches.data ?? []).map((branch) => <label className="check" key={branch.id}><input type="checkbox" checked={employeeBranches.includes(branch.id)} onChange={(event) => setEmployeeBranches((items) => event.target.checked ? [...items, branch.id] : items.filter((id) => id !== branch.id))} />{branch.name}</label>)}</Field>}
            <Field label="الدور"><select value={employeeRole} onChange={(event) => setEmployeeRole(event.target.value as Role)} disabled={editingEmployee.id === currentCompany.data?.id}><option value="staff">موظف</option>{isAdmin && <><option value="manager">مدير</option><option value="admin">مدير شركة</option></>}</select></Field>
            <Field label="الحالة"><select value={employeeActive ? "true" : "false"} onChange={(event) => setEmployeeActive(event.target.value === "true")}><option value="true">active</option><option value="false">inactive</option></select></Field>
            <Field label="كلمة مرور جديدة" hint="اتركها فارغة للإبقاء على الحالية"><input type="password" minLength={8} value={employeePassword} onChange={(event) => setEmployeePassword(event.target.value)} /></Field>
            <div className="form-actions"><button className="btn btn-primary" disabled={busy}>حفظ التعديلات</button><button type="button" className="btn" onClick={() => setEditingEmployee(null)}>إلغاء</button></div>
          </form>
        </Modal>
      )}

      {editingSafe && (
        <Modal title={`تعديل خزينة — ${editingSafe.name}`}  onClose={() => setEditingSafe(null)}>
          <form onSubmit={saveSafe} className="form-grid">
            <Field label="اسم الخزينة"><input value={editingSafe.name} onChange={(event) => setEditingSafe({ ...editingSafe, name: event.target.value })} required /></Field>
            <Field label="الفرع"><select value={editingSafe.branch_id} onChange={(event) => setEditingSafe({ ...editingSafe, branch_id: Number(event.target.value) })} required>{selBranches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></Field>
            <button className="btn btn-primary" disabled={busy}>حفظ التعديلات</button>
          </form>
        </Modal>
      )}

      {editingWarehouse && (
        <Modal title={`تعديل مخزن — ${editingWarehouse.name}`} onClose={() => setEditingWarehouse(null)}>
          <form onSubmit={saveWarehouse} className="form-grid">
            <Field label="اسم المخزن"><input value={editingWarehouse.name} onChange={(event) => setEditingWarehouse({ ...editingWarehouse, name: event.target.value })} required /></Field>
            <Field label="رمز المخزن"><input dir="ltr" value={editingWarehouse.code} onChange={(event) => setEditingWarehouse({ ...editingWarehouse, code: event.target.value })} /></Field>
            <Field label="الفرع"><select value={editingWarehouse.branch_id} onChange={(event) => setEditingWarehouse({ ...editingWarehouse, branch_id: Number(event.target.value) })} required>{selBranches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></Field>
            <Field label="الموقع"><input value={editingWarehouse.location ?? ""} onChange={(event) => setEditingWarehouse({ ...editingWarehouse, location: event.target.value || null })} /></Field>
            <Field label="الحالة"><select value={editingWarehouse.is_active ? "true" : "false"} onChange={(event) => setEditingWarehouse({ ...editingWarehouse, is_active: event.target.value === "true" })}><option value="true">نشط</option><option value="false">متوقف</option></select></Field>
            <button className="btn btn-primary" disabled={busy}>حفظ التعديلات</button>
          </form>
        </Modal>
      )}

      {editingBranch && (
        <Modal title={`تعديل فرع — ${editingBranch.name}`} onClose={() => setEditingBranch(null)}>
          <form onSubmit={saveBranch} className="form-grid">
            <Field label="اسم الفرع"><input value={editingBranch.name} onChange={(event) => setEditingBranch({ ...editingBranch, name: event.target.value })} required /></Field>
            <Field label="رمز الفرع"><input dir="ltr" value={editingBranch.code} onChange={(event) => setEditingBranch({ ...editingBranch, code: event.target.value })} placeholder="اتركه فارغًا للتوليد التلقائي" /></Field>
            <Field label="الموقع"><input value={editingBranch.location ?? ""} onChange={(event) => setEditingBranch({ ...editingBranch, location: event.target.value || null })} /></Field>
            <Field label="الحالة"><select value={editingBranch.is_active ? "true" : "false"} onChange={(event) => setEditingBranch({ ...editingBranch, is_active: event.target.value === "true" })}><option value="true">نشط</option><option value="false">متوقف</option></select></Field>
            <button className="btn btn-primary" disabled={busy}>حفظ التعديلات</button>
          </form>
        </Modal>
      )}

      {editingCompany && (
        <Modal title={`تعديل شركة — ${editingCompany.name}`} onClose={() => setEditingCompany(null)}>
          <form onSubmit={(e) => {
            e.preventDefault();
            saveCompany();
          }} className="form-grid">
            <Field label="اسم الشركة"><input value={editName} onChange={(e) => setEditName(e.target.value)} required /></Field>
            <Field label="الحد الأقصى للمخازن لكل فرع"><input type="number" min={1} value={editLimit} onChange={(e) => setEditLimit(e.target.value)} /></Field>
            <Field label="الحد الأقصى للخزائن لكل فرع"><input type="number" min={1} value={editSafeLimit} onChange={(e) => setEditSafeLimit(e.target.value)} /></Field>
            <Field label="الحد الأقصى لعدد الفروع"><input type="number" min={1} value={editBranchLimit} onChange={(e) => setEditBranchLimit(e.target.value)} placeholder="غير محدود" /></Field>
            <Field label="الحالة">
              <select value={editActive ? "1" : "0"} onChange={(e) => setEditActive(e.target.value === "1")}>
                <option value="1">active</option>
                <option value="0">inactive</option>
              </select>
            </Field>
            <Field label="اسم المدير (الاسم الكامل)"><input value={editAdminName} onChange={(e) => setEditAdminName(e.target.value)} /></Field>
            <Field label="كلمة مرور المدير (جديدة)" hint="اتركها فارغًا للإبقاء على الحالية"><input type="password" minLength={8} value={editAdminPassword} onChange={(e) => setEditAdminPassword(e.target.value)} /></Field>
            <button className="btn btn-primary" disabled={busy}>حفظ التعديلات</button>
          </form>
        </Modal>
      )}

      {editingBank && (
        <Modal title={`تعديل بنك — ${editingBank.name}`} onClose={() => setEditingBank(null)}>
          <form onSubmit={saveBank} className="form-grid">
            <Field label="اسم البنك"><input value={editingBank.name} onChange={(event) => setEditingBank({ ...editingBank, name: event.target.value })} required /></Field>
            <Field label="رمز البنك"><input dir="ltr" value={editingBank.code} onChange={(event) => setEditingBank({ ...editingBank, code: event.target.value })} /></Field>
            <Field label="رقم الحساب"><input dir="ltr" value={editingBank.account_number ?? ""} onChange={(event) => setEditingBank({ ...editingBank, account_number: event.target.value || null })} /></Field>
            <Field label="الحالة"><select value={editingBank.is_active ? "true" : "false"} onChange={(event) => setEditingBank({ ...editingBank, is_active: event.target.value === "true" })}><option value="true">نشط</option><option value="false">متوقف</option></select></Field>
            <button className="btn btn-primary" disabled={busy}>حفظ التعديلات</button>
          </form>
        </Modal>
      )}

      {editingDepartment && (
        <Modal title={`تعديل قسم — ${editingDepartment.name}`} onClose={() => setEditingDepartment(null)}>
          <form onSubmit={saveDepartment} className="form-grid">
            <Field label="اسم القسم"><input value={editingDepartment.name} onChange={(event) => setEditingDepartment({ ...editingDepartment, name: event.target.value })} required /></Field>
            <Field label="الرمز"><input dir="ltr" value={editingDepartment.code} onChange={(event) => setEditingDepartment({ ...editingDepartment, code: event.target.value })} /></Field>
            <Field label="الوصف"><input value={editingDepartment.description ?? ""} onChange={(event) => setEditingDepartment({ ...editingDepartment, description: event.target.value || null })} /></Field>
            <Field label="الحالة"><select value={editingDepartment.is_active ? "true" : "false"} onChange={(event) => setEditingDepartment({ ...editingDepartment, is_active: event.target.value === "true" })}><option value="true">نشط</option><option value="false">متوقف</option></select></Field>
            <button className="btn btn-primary" disabled={busy}>حفظ التعديلات</button>
          </form>
        </Modal>
      )}
    </div>
  );
}
