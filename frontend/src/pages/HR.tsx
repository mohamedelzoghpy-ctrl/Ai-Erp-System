/** الموارد البشرية (HR): الموظفون + ملف الموظف + إعدادات HR. */
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { dateTime, money, num } from "../format";
import { useAction, useFetch, usePagedList, type Fetched } from "../hooks";
import { useI18n } from "../i18n";
import type {
  Branch,
  Department,
  EmployeeStatus,
  HrAdvance,
  HrAnalytics,
  HrApplicant,
  ApplicantStage,
  HrAttendance,
  HrAttendanceCorrection,
  HrContract,
  HrDocument,
  HrEmployee,
  HrEmployeeDetail,
  HrEmployeeMove,
  HrEnrollment,
  HrGrade,
  HrHoliday,
  HrJobPosting,
  HrJobTitle,
  HrLeaveBalance,
  HrLeaveRequest,
  HrLeaveType,
  HrMePayslip,
  HrMeProfile,
  HrPayslip,
  HrPayslipLine,
  HrPayrollRun,
  HrReview,
  HrReviewCycle,
  HrSalaryComponent,
  HrSettlement,
  HrShift,
  HrShiftAssignment,
  HrSummary,
  HrTraining,
} from "../types";
import { ActiveBadge, Alert, Empty, Field, Loading, Lookup, Modal, PageHeader, Pager } from "../ui";

const STATUS: Record<EmployeeStatus, string> = {
  active: "على رأس العمل",
  probation: "تحت التجربة",
  suspended: "موقوف",
  terminated: "منتهي الخدمة",
};

const STATUS_BADGE: Record<EmployeeStatus, string> = {
  active: "badge badge-confirmed",
  probation: "badge badge-draft",
  suspended: "badge badge-off",
  terminated: "badge badge-off",
};

const MOVE_TYPE: Record<HrEmployeeMove["move_type"], string> = {
  hire: "تعيين",
  promotion: "ترقية",
  transfer: "نقل/ثوابت",
  salary_change: "تغيير راتب",
  status_change: "تغيير حالة",
  termination: "إنهاء خدمة",
};

const CONTRACT_KIND: Record<HrContract["kind"], string> = {
  unlimited: "غير محدد المدة",
  fixed: "محدد المدة",
  temp: "مؤقت",
  part_time: "عمل جزئي",
};

const DOC_TYPE: Record<HrDocument["doc_type"], string> = {
  contract: "عقد",
  certificate: "شهادة",
  id: "هوية/رقم قومي",
  visa: "تأشيرة/إقامة",
  other: "أخرى",
};

function StatusBadgeHr({ status }: { status: EmployeeStatus }) {
  return <span className={STATUS_BADGE[status]}>{STATUS[status]}</span>;
}

/** نموذج موحد لبيانات الموظف (إضافة/تعديل). */
function useEmployeeForm(
  employee: HrEmployee | null,
  departments: Department[],
  titles: HrJobTitle[],
  grades: HrGrade[],
  branches: Branch[],
  employees: HrEmployee[],
) {
  const staff = employees.filter((e) => !employee || e.id !== employee.id);
  const base = {
    full_name: employee?.full_name ?? "",
    national_id: employee?.national_id ?? "",
    insurance_number: employee?.insurance_number ?? "",
    phone: employee?.phone ?? "",
    email: employee?.email ?? "",
    gender: employee?.gender ?? ("" as "" | "male" | "female"),
    birth_date: employee?.birth_date ?? "",
    nationality: employee?.nationality ?? "",
    department_id: String(employee?.department_id ?? ""),
    job_title_id: String(employee?.job_title_id ?? ""),
    grade_id: String(employee?.grade_id ?? ""),
    branch_id: String(employee?.branch_id ?? ""),
    manager_id: String(employee?.manager_id ?? ""),
    hire_date: employee?.hire_date ?? new Date().toISOString().slice(0, 10),
    basic_salary: employee?.basic_salary ?? "",
    status: (employee?.status ?? "active") as EmployeeStatus,
    address: employee?.address ?? "",
    notes: employee?.notes ?? "",
  };
  const [f, setF] = useState(base);
  // إعادة تعبئة النموذج عند فتح تعديل موظف آخر
  useEffect(() => { setF(base); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [employee?.id]);
  const reset = () => setF(base);
  const body = () => {
    const num = (v: string): number | null => (v === "" ? null : Number(v));
    return {
      full_name: f.full_name.trim(),
      national_id: f.national_id.trim() || null,
      insurance_number: f.insurance_number.trim() || null,
      phone: f.phone.trim() || null,
      email: f.email.trim() || null,
      gender: f.gender || null,
      birth_date: f.birth_date || null,
      nationality: f.nationality.trim() || null,
      department_id: num(f.department_id),
      job_title_id: num(f.job_title_id),
      grade_id: num(f.grade_id),
      branch_id: num(f.branch_id),
      manager_id: num(f.manager_id),
      hire_date: f.hire_date || undefined,
      basic_salary: f.basic_salary === "" ? null : f.basic_salary,
      status: f.status,
      address: f.address.trim() || null,
      notes: f.notes.trim() || null,
    };
  };
  const form = (
    <div className="form-grid">
      <Field label="الاسم الكامل*">
        <input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required maxLength={200} />
      </Field>
      <Field label="الرقم القومي / الهوية">
        <input dir="ltr" value={f.national_id} onChange={(e) => setF({ ...f, national_id: e.target.value })} maxLength={40} />
      </Field>
      <Field label="رقم التأمين الاجتماعي">
        <input dir="ltr" value={f.insurance_number} onChange={(e) => setF({ ...f, insurance_number: e.target.value })} maxLength={40} />
      </Field>
      <Field label="الهاتف">
        <input dir="ltr" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} maxLength={40} />
      </Field>
      <Field label="البريد الإلكتروني">
        <input dir="ltr" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} maxLength={150} />
      </Field>
      <Field label="الجنس">
        <select value={f.gender} onChange={(e) => setF({ ...f, gender: e.target.value as "" | "male" | "female" })}>
          <option value="">—</option>
          <option value="male">ذكر</option>
          <option value="female">أنثى</option>
        </select>
      </Field>
      <Field label="تاريخ الميلاد">
        <input type="date" value={f.birth_date} onChange={(e) => setF({ ...f, birth_date: e.target.value })} />
      </Field>
      <Field label="الجنسية">
        <input value={f.nationality} onChange={(e) => setF({ ...f, nationality: e.target.value })} maxLength={80} />
      </Field>
      <Field label="الإدارة">
        <select value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value })}>
          <option value="">—</option>
          {departments.map((d) => (<option key={d.id} value={d.id}>{d.name}</option>))}
        </select>
      </Field>
      <Field label="المسمى الوظيفي">
        <select value={f.job_title_id} onChange={(e) => setF({ ...f, job_title_id: e.target.value })}>
          <option value="">—</option>
          {titles.filter((t) => t.is_active).map((t) => (<option key={t.id} value={t.id}>{t.name}</option>))}
        </select>
      </Field>
      <Field label="الدرجة الوظيفية">
        <select value={f.grade_id} onChange={(e) => setF({ ...f, grade_id: e.target.value })}>
          <option value="">—</option>
          {grades.filter((g) => g.is_active).map((g) => (<option key={g.id} value={g.id}>{g.name}</option>))}
        </select>
      </Field>
      <Field label="الفرع">
        <select value={f.branch_id} onChange={(e) => setF({ ...f, branch_id: e.target.value })}>
          <option value="">—</option>
          {branches.map((b) => (<option key={b.id} value={b.id}>{b.name}</option>))}
        </select>
      </Field>
      {!employee && (
        <Field label="تاريخ المباشرة">
          <input type="date" value={f.hire_date} onChange={(e) => setF({ ...f, hire_date: e.target.value })} />
        </Field>
      )}
      <Field label="المدير المباشر">
        <select value={f.manager_id} onChange={(e) => setF({ ...f, manager_id: e.target.value })}>
          <option value="">—</option>
          {staff.map((s) => (<option key={s.id} value={s.id}>{s.full_name} ({s.code})</option>))}
        </select>
      </Field>
      <Field label="الراتب الأساسي">
        <input dir="ltr" inputMode="decimal" value={f.basic_salary} onChange={(e) => setF({ ...f, basic_salary: e.target.value.replace(/[^0-9.]/g, "") })} placeholder="اختياري" />
      </Field>
      <Field label="الحالة">
        <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as EmployeeStatus })}>
          {Object.entries(STATUS).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
        </select>
      </Field>
      <Field label="العنوان">
        <input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} />
      </Field>
      <Field label="ملاحظات">
        <input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
      </Field>
    </div>
  );
  return { f, reset, body, form };
}

/** قائمة الموظفين: بحث وتصفية وترقيم، مع إضافة/تعديل/حذف والانتقال لملف الموظف. */
export function HrEmployees() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const summary = useFetch(() => api.get<HrSummary>("/hr/summary"), "hr-summary");
  const departments = useFetch(() => api.get<Department[]>("/company/departments"), "hr-departments");
  const titles = useFetch(() => api.get<HrJobTitle[]>("/hr/job-titles"), "hr-titles");
  const grades = useFetch(() => api.get<HrGrade[]>("/hr/grades"), "hr-grades");
  const branches = useFetch(() => api.get<Branch[]>("/company/branches"), "hr-branches");
  const employees = useFetch(() => api.get<HrEmployee[]>("/hr/employees?limit=200"), "hr-employees-all");

  const [search, setSearch] = useState("");
  const [statusF, setStatusF] = useState("");
  const [deptF, setDeptF] = useState("");
  const list = usePagedList<HrEmployee>("/hr/employees", {
    search,
    employee_status: statusF || undefined,
    department_id: deptF || undefined,
  });

  const [openAdd, setOpenAdd] = useState(false);
  const [editing, setEditing] = useState<HrEmployee | null>(null);
  const [confirmDel, setConfirmDel] = useState<HrEmployee | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const addForm = useEmployeeForm(null, departments.data ?? [], titles.data ?? [], grades.data ?? [], branches.data ?? [], employees.data ?? []);
  const editForm = useEmployeeForm(editing, departments.data ?? [], titles.data ?? [], grades.data ?? [], branches.data ?? [], employees.data ?? []);

  const refreshAll = () => {
    list.reload();
    summary.reload();
    employees.reload();
  };

  const submitAdd = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await api.post<HrEmployee>("/hr/employees", addForm.body());
      setOpenAdd(false);
      addForm.reset();
      setNote(`${t("تم إنشاء ملف الموظف «")}${created.full_name}${t("» بكود ")}${created.code}${t(".")}`);
      refreshAll();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setError(null);
    setBusy(true);
    try {
      const body = editForm.body();
      await api.patch(`/hr/employees/${editing.id}`, body);
      setEditing(null);
      setNote(`${t("تم تحديث «")}${editing.full_name}${t("»؛ أي تغيير في الإدارة أو المسمى أو الراتب أو الحالة سُجّل في السجل الوظيفي.")}`);
      refreshAll();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async (emp: HrEmployee) => {
    setError(null);
    setBusy(true);
    try {
      await api.del(`/hr/employees/${emp.id}`);
      setConfirmDel(null);
      setNote(`${t("تم حذف ملف الموظف «")}${emp.full_name}${t("» ومرفقاته وعقوده.")}`);
      refreshAll();
    } catch (err) {
      setConfirmDel(null);
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const chip = (label: string, value: number, color: string) => (
    <div className="card" style={{ padding: "10px 16px", display: "flex", gap: 10, alignItems: "center" }}>
      <span style={{ fontWeight: 700, fontSize: 20, color }}>{value}</span>
      <span className="muted" style={{ fontSize: 13 }}>{label}</span>
    </div>
  );

  return (
    <>
      <PageHeader title={t("hr.employeesTitle")}>
        <button className="btn btn-primary" onClick={() => { setError(null); setOpenAdd(true); }}>
          {"+ "}{t("إضافة موظف")}
        </button>
      </PageHeader>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
        {chip(t("إجمالي الموظفين"), (summary.data ?? { total: 0, active: 0, probation: 0, suspended: 0, terminated: 0, expiring_documents: 0 }).total, "var(--primary, #2563eb)")}
        {chip(STATUS.active, (summary.data?.active ?? 0), "#15803d")}
        {chip(STATUS.probation, (summary.data?.probation ?? 0), "#b45309")}
        {chip(STATUS.suspended, (summary.data?.suspended ?? 0), "#b91c1c")}
        {chip(STATUS.terminated, (summary.data?.terminated ?? 0), "#6b7280")}
        {chip(t("مستندات منتهية"), (summary.data?.expiring_documents ?? 0), "#b91c1c")}
      </div>

      <div className="toolbar page-actions" style={{ marginBottom: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input placeholder={t("ابحث بالاسم أو الكود أو الهاتف أو الرقم القومي…")} value={search} onChange={(e) => setSearch(e.target.value)} style={{ minWidth: 260 }} />
        <select value={statusF} onChange={(e) => setStatusF(e.target.value)}>
          <option value="">{t("كل الحالات")}</option>
          {Object.entries(STATUS).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
        </select>
        <select value={deptF} onChange={(e) => setDeptF(e.target.value)}>
          <option value="">{t("كل الإدارات")}</option>
          {(departments.data ?? []).map((d) => (<option key={d.id} value={d.id}>{d.name}</option>))}
        </select>
      </div>

      <Alert>{list.error}</Alert>
      {error && <Alert>{error}</Alert>}
      {note && (
        <div style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg)", color: "var(--ok)" }}>
          {note}
        </div>
      )}

      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : (list.data ?? []).length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("الكود")}</th>
                <th>{t("الاسم")}</th>
                <th>{t("الإدارة / المسمى")}</th>
                <th>{t("الفرع")}</th>
                <th>{t("المباشرة")}</th>
                <th className="num">{t("الراتب الأساسي")}</th>
                <th>{t("الحالة")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(list.data ?? []).map((e) => (
                <tr key={e.id} style={e.is_active ? undefined : { opacity: 0.55 }}>
                  <td className="num-center" dir="ltr">{e.code}</td>
                  <td><strong>{e.full_name}</strong></td>
                  <td>{e.department_name ?? "—"}{e.job_title_name ? <span className="muted"> · {e.job_title_name}</span> : null}</td>
                  <td>{e.branch_name ?? "—"}</td>
                  <td>{e.hire_date}</td>
                  <td className="num">{e.basic_salary ? money(e.basic_salary) : "—"}</td>
                  <td><StatusBadgeHr status={e.status} /></td>
                  <td className="actions">
                    <button className="btn btn-sm" style={{ color: "#0d47a1", borderColor: "#0d47a1" }} onClick={() => navigate(`/hr/employees/${e.id}`)}>
                      📄 {t("الملف")}
                    </button>{" "}
                    <button className="btn-edit" onClick={() => { setEditing(e); setError(null); }}>{t("تعديل")}</button>{" "}
                    <button
                      className="btn-delete"
                     
                      onClick={() => setConfirmDel(e)}
                    >
                      {t("حذف")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{search || statusF || deptF ? t("لا توجد نتائج مطابقة.") : t("لا يوجد موظفون — اضغط «إضافة موظف» للبدء.")}</Empty>
        )}
      </div>
      {list.pages > 1 && (
        <div className="pager" style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "center", padding: 12 }}>
          <button className="btn btn-sm" disabled={list.page <= 1} onClick={() => list.setPage(list.page - 1)}>{t("السابق")}</button>
          <span className="muted">{t("صفحة")} {list.page} / {list.pages} · {list.total}</span>
          <button className="btn btn-sm" disabled={list.page >= list.pages} onClick={() => list.setPage(list.page + 1)}>{t("التالي")}</button>
        </div>
      )}

      {openAdd && (
        <Modal title={t("إضافة موظف")} onClose={() => setOpenAdd(false)} wide>
          <form onSubmit={submitAdd}>
            <Alert>{error}</Alert>
            {addForm.form}
            <div className="form-actions" style={{ marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy || !addForm.f.full_name.trim()}>
                {busy ? t("جارٍ الحفظ…") : t("إنشاء ملف الموظف")}
              </button>
              <button type="button" className="btn" onClick={() => setOpenAdd(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {editing && (
        <Modal title={`${t("تعديل الموظف — ")}${editing.full_name}`} onClose={() => setEditing(null)} wide>
          <form onSubmit={submitEdit}>
            <Alert>{error}</Alert>
            {editForm.form}
            <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
              {t("الكود: ")}{editing.code}{t(" — لا يتغير بعد الإنشاء. تغيير الحالة إلى «منتهي الخدمة» يسجّل تاريخ الإنهاء تلقائيًا.")}
            </p>
            <div className="form-actions" style={{ marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy}>
                {busy ? t("جارٍ الحفظ…") : t("حفظ التعديلات")}
              </button>
              <button type="button" className="btn" onClick={() => setEditing(null)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {confirmDel && (
        <Modal title={`${t("حذف الموظف — ")}${confirmDel.full_name}`} onClose={() => setConfirmDel(null)}>
          <p style={{ margin: "0 0 6px" }}>
            {t("سيُحذف ملف الموظف ")}<strong>{confirmDel.full_name}</strong>{t(" (")}{confirmDel.code}{t(") مع عقوده ومستنداته وسجل تحركاته نهائيًا. لا يمكن الرجوع.")}
          </p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn-delete"
              disabled={busy}
              onClick={() => void doDelete(confirmDel)}
            >
              {busy ? t("جارٍ الحذف…") : t("نعم، حذف")}
            </button>
            <button type="button" className="btn" onClick={() => setConfirmDel(null)}>{t("إلغاء")}</button>
          </div>
        </Modal>
      )}
    </>
  );
}

/** ملف الموظف: نظرة عامة + العقود + المستندات + السجل الوظيفي. */
export function HrEmployeeProfile() {
  const { id } = useParams();
  const { t } = useI18n();
  const detail = useFetch(() => api.get<HrEmployeeDetail>(`/hr/employees/${id}`), `hr-emp-${id}`);
  const departments = useFetch(() => api.get<Department[]>("/company/departments"), "hr-departments");
  const titles = useFetch(() => api.get<HrJobTitle[]>("/hr/job-titles"), "hr-titles");

  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  if (detail.error) return <Alert>{detail.error}</Alert>;
  if (detail.loading || !detail.data) return <Loading />;
  const emp = detail.data;

  const after = (message: string) => {
    detail.reload();
    setNote(message);
  };

  return (
    <>
      <PageHeader title={`${emp.full_name} — ${emp.code}`}>
        <StatusBadgeHr status={emp.status} />
      </PageHeader>

      <Alert>{error}</Alert>
      {note && (
        <div style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg)", color: "var(--ok)" }}>
          {note}
        </div>
      )}

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="form-grid" style={{ padding: 14 }}>
          <Field label={t("الإدارة")}><input disabled value={emp.department_name ?? "—"} /></Field>
          <Field label={t("المسمى الوظيفي")}><input disabled value={emp.job_title_name ?? "—"} /></Field>
          <Field label={t("الفرع")}><input disabled value={emp.branch_name ?? "—"} /></Field>
          <Field label={t("المدير المباشر")}><input disabled value={emp.manager_name ?? "—"} /></Field>
          <Field label={t("تاريخ المباشرة")}><input disabled value={emp.hire_date} /></Field>
          <Field label={t("الراتب الأساسي")}><input disabled value={emp.basic_salary ? money(emp.basic_salary) : "—"} /></Field>
          <Field label={t("الهاتف")}><input disabled value={emp.phone ?? "—"} /></Field>
          <Field label={t("البريد الإلكتروني")}><input disabled value={emp.email ?? "—"} /></Field>
          <Field label={t("الرقم القومي / الهوية")}><input disabled value={emp.national_id ?? "—"} /></Field>
          <Field label={t("الجنسية")}><input disabled value={emp.nationality ?? "—"} /></Field>
          <Field label={t("تاريخ الإنهاء")}><input disabled value={emp.terminated_at ?? "—"} /></Field>
          <Field label={t("ملاحظات")}><input disabled value={emp.notes ?? "—"} /></Field>
        </div>
      </div>

      <ContractsCard emp={emp} onDone={(m) => after(m)} setError={setError} />
      <DocumentsCard emp={emp} onDone={(m) => after(m)} setError={setError} />
      <MovesCard emp={emp} departments={departments.data ?? []} titles={titles.data ?? []} onDone={(m) => after(m)} setError={setError} />
    </>
  );
}

function ContractsCard({ emp, onDone, setError }: { emp: HrEmployeeDetail; onDone: (message: string) => void; setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<HrContract | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [f, setF] = useState({ kind: "unlimited", start_date: new Date().toISOString().slice(0, 10), end_date: "", basic_salary: "", notes: "" });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    const body = {
      kind: f.kind,
      start_date: f.start_date || undefined,
      end_date: f.end_date || null,
      basic_salary: f.basic_salary === "" ? null : f.basic_salary,
      notes: f.notes.trim() || null,
    };
    try {
      if (editing) {
        await api.patch(`/hr/contracts/${editing.id}`, body);
        onDone(`${t("تم تحديث العقد.")}`);
      } else {
        await api.post(`/hr/employees/${emp.id}/contracts`, body);
        onDone(`${t("تم إنشاء عقد جديد وتعطيل العقود النشطة السابقة تلقائيًا.")}`);
      }
      setOpen(false);
      setEditing(null);
    } catch (r) {
      setErr((r as Error).message);
      setError((r as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>📑 {t("عقود العمل")}</h2>
          <button className="btn btn-sm btn-primary" onClick={() => { setEditing(null); setF({ kind: "unlimited", start_date: new Date().toISOString().slice(0, 10), end_date: "", basic_salary: emp.basic_salary ?? "", notes: "" }); setOpen(true); }}>
            {"+ "}{t("عقد جديد")}
          </button>
        </div>
        <div className="table-wrap">
          {emp.contracts.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>{t("الكود")}</th>
                  <th>{t("النوع")}</th>
                  <th>{t("من")}</th>
                  <th>{t("إلى")}</th>
                  <th className="num">{t("الراتب")}</th>
                  <th>{t("الحالة")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {emp.contracts.map((c) => (
                  <tr key={c.id}>
                    <td dir="ltr" className="num-center">{c.code}</td>
                    <td>{CONTRACT_KIND[c.kind]}</td>
                    <td>{c.start_date}</td>
                    <td>{c.end_date ?? "—"}</td>
                    <td className="num">{c.basic_salary ? money(c.basic_salary) : "—"}</td>
                    <td><span className={`badge ${c.status === "active" ? "badge-confirmed" : c.status === "expired" ? "badge-draft" : "badge-off"}`}>{c.status === "active" ? t("ساري") : c.status === "expired" ? t("منتهي بالمدة") : t("مُنهي")}</span></td>
                    <td className="actions">
                      <button className="btn-edit" onClick={() => { setF({ kind: c.kind, start_date: c.start_date, end_date: c.end_date ?? "", basic_salary: c.basic_salary ?? "", notes: c.notes ?? "" }); setEditing(c); setOpen(true); }}>{t("تعديل")}</button>{" "}
                      <button
                        className="btn-delete"
                       
                        onClick={async () => { try { await api.del(`/hr/contracts/${c.id}`); onDone(t("تم حذف العقد.")); } catch (r) { setError((r as Error).message); } }}
                      >
                        {t("حذف")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("لا توجد عقود بعد.")}</Empty>
          )}
        </div>
      </div>

      {open && (
        <Modal title={editing ? `${t("تعديل عقد ")}${editing.code}` : t("عقد جديد")} onClose={() => setOpen(false)} wide>
          <form onSubmit={submit}>
            <Alert>{err}</Alert>
            <div className="form-grid">
              <Field label={t("نوع العقد")}>
                <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
                  {Object.entries(CONTRACT_KIND).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
                </select>
              </Field>
              <Field label={t("تاريخ البداية")}>
                <input type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} />
              </Field>
              <Field label={t("تاريخ النهاية")} hint={t("إلزامي لعقود المدة المحددة/المؤقت/الجزئي")}>
                <input type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} />
              </Field>
              <Field label={t("الراتب الأساسي")}>
                <input dir="ltr" inputMode="decimal" value={f.basic_salary} onChange={(e) => setF({ ...f, basic_salary: e.target.value.replace(/[^0-9.]/g, "") })} />
              </Field>
              <Field label={t("ملاحظات")}>
                <input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
              </Field>
            </div>
            <div className="form-actions" style={{ marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy}>{busy ? t("جارٍ الحفظ…") : t("حفظ")}</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

function DocumentsCard({ emp, onDone, setError }: { emp: HrEmployeeDetail; onDone: (message: string) => void; setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ title: "", doc_type: "other", issue_date: "", expiry_date: "", notes: "" });
  const [file, setFile] = useState<File | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file && !f.title.trim()) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("title", f.title.trim());
      fd.append("doc_type", f.doc_type);
      if (f.issue_date) fd.append("issue_date", f.issue_date);
      if (f.expiry_date) fd.append("expiry_date", f.expiry_date);
      if (f.notes.trim()) fd.append("notes", f.notes.trim());
      if (file) fd.append("file", file);
      await api.uploadForm(`/hr/employees/${emp.id}/documents`, fd);
      setF({ title: "", doc_type: "other", issue_date: "", expiry_date: "", notes: "" });
      setFile(null);
      onDone(t("تم إضافة المستند."));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const expired = (d: string | null) => d !== null && d <= new Date().toISOString().slice(0, 10);

  return (
    <>
      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>🗂️ {t("مستندات الموظف")}</h2>
        </div>
        <div className="table-wrap">
          {emp.documents.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>{t("العنوان")}</th>
                  <th>{t("النوع")}</th>
                  <th>{t("تاريخ الإصدار")}</th>
                  <th>{t("تاريخ الانتهاء")}</th>
                  <th>{t("الملف")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {emp.documents.map((d) => (
                  <tr key={d.id}>
                    <td>{d.title}</td>
                    <td>{DOC_TYPE[d.doc_type]}</td>
                    <td>{d.issue_date ?? "—"}</td>
                    <td style={expired(d.expiry_date) ? { color: "var(--danger)", fontWeight: 700 } : undefined}>
                      {d.expiry_date ?? "—"}{expired(d.expiry_date) ? ` ${t("(منتهي)")}` : ""}
                    </td>
                    <td>{d.has_file ? `📎 ${d.file_name ?? t("مرفق")}` : "—"}</td>
                    <td className="actions">
                      {d.has_file && (
                        <button className="btn btn-sm" onClick={() => void api.download(`/hr/documents/${d.id}/file`, d.file_name ?? "document")}>
                          ⬇️ {t("تنزيل")}
                        </button>
                      )}{" "}
                      <button
                        className="btn-delete"
                       
                        onClick={async () => { try { await api.del(`/hr/documents/${d.id}`); onDone(t("تم حذف المستند.")); } catch (err) { setError((err as Error).message); } }}
                      >
                        {t("حذف")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("لا توجد مستندات.")}</Empty>
          )}
        </div>
        <form onSubmit={submit} style={{ padding: 14, borderTop: "1px solid var(--border, #e2e8f0)" }}>
          <div className="form-grid">
            <Field label={t("عنوان المستند*")}>
              <input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required maxLength={200} />
            </Field>
            <Field label={t("النوع")}>
              <select value={f.doc_type} onChange={(e) => setF({ ...f, doc_type: e.target.value })}>
                {Object.entries(DOC_TYPE).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
              </select>
            </Field>
            <Field label={t("تاريخ الإصدار")}>
              <input type="date" value={f.issue_date} onChange={(e) => setF({ ...f, issue_date: e.target.value })} />
            </Field>
            <Field label={t("تاريخ الانتهاء")} hint={t("يُستخدم لتنبيهات التجديد")}>
              <input type="date" value={f.expiry_date} onChange={(e) => setF({ ...f, expiry_date: e.target.value })} />
            </Field>
            <Field label={t("ملف (اختياري — ≤10MB)")}>
              <input type="file" accept=".pdf,.png,.jpeg,.jpg,.webp,.gif,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </Field>
            <Field label={t("ملاحظات")}>
              <input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
            </Field>
          </div>
          <div className="form-actions" style={{ marginTop: 10 }}>
            <button className="btn btn-primary" disabled={busy || !f.title.trim()}>{busy ? t("جارٍ الإضافة…") : t("إضافة مستند")}</button>
          </div>
        </form>
      </div>
    </>
  );
}

function MovesCard({
  emp,
  departments,
  titles,
  onDone,
  setError,
}: {
  emp: HrEmployeeDetail;
  departments: Department[];
  titles: HrJobTitle[];
  onDone: (message: string) => void;
  setError: (e: string | null) => void;
}) {
  const { t } = useI18n();
  const busyState = useState(false);
  const busy = busyState[0];
  const setBusy = busyState[1];
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ move_type: "transfer", effective_date: today, to_department_id: "", to_job_title_id: "", to_salary: "", new_status: "", reason: "" });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const body = {
        move_type: f.move_type,
        effective_date: f.effective_date || undefined,
        to_department_id: f.to_department_id === "" ? null : Number(f.to_department_id),
        to_job_title_id: f.to_job_title_id === "" ? null : Number(f.to_job_title_id),
        to_salary: f.to_salary === "" ? null : f.to_salary,
        new_status: f.new_status === "" ? null : f.new_status,
        reason: f.reason.trim() || null,
      };
      await api.post(`/hr/employees/${emp.id}/moves`, body);
      setF({ move_type: "transfer", effective_date: today, to_department_id: "", to_job_title_id: "", to_salary: "", new_status: "", reason: "" });
      onDone(t("تم تسجيل التحرك الوظيفي وتطبيقه على ملف الموظف."));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>📋 {t("السجل الوظيفي (ترقيات ونقل وإنهاء)")}</h2>
        </div>
        <div className="table-wrap">
          {emp.moves.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>{t("التاريخ")}</th>
                  <th>{t("النوع")}</th>
                  <th>{t("التغييرات")}</th>
                  <th>{t("السبب")}</th>
                  <th>{t("أُنشئ في")}</th>
                </tr>
              </thead>
              <tbody>
                {emp.moves.map((m) => (
                  <tr key={m.id}>
                    <td>{m.effective_date}</td>
                    <td><span className="badge badge-draft">{MOVE_TYPE[m.move_type]}</span></td>
                    <td>
                      {m.to_department_name ?? ""}{m.to_job_title_name ? ` · ${m.to_job_title_name}` : ""}
                      {m.from_salary !== m.to_salary && m.to_salary !== null ? (
                        <span> · {money(m.from_salary ?? "0")} ← <strong>{money(m.to_salary)}</strong></span>
                      ) : null}
                    </td>
                    <td>{m.reason ?? "—"}</td>
                    <td>{dateTime(m.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("لا توجد تحركات وظيفية.")}</Empty>
          )}
        </div>
        <form onSubmit={submit} style={{ padding: 14, borderTop: "1px solid var(--border, #e2e8f0)" }}>
          <div className="form-grid">
            <Field label={t("نوع التحرك*")}>
              <select value={f.move_type} onChange={(e) => setF({ ...f, move_type: e.target.value, new_status: e.target.value === "termination" ? "terminated" : f.new_status })}>
                {Object.entries(MOVE_TYPE).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
              </select>
            </Field>
            <Field label={t("تاريخ التنفيذ")}>
              <input type="date" value={f.effective_date} onChange={(e) => setF({ ...f, effective_date: e.target.value })} />
            </Field>
            <Field label={t("الإدارة الجديدة")}>
              <select value={f.to_department_id} onChange={(e) => setF({ ...f, to_department_id: e.target.value })}>
                <option value="">{t("بدون تغيير")}</option>
                {departments.map((d) => (<option key={d.id} value={d.id}>{d.name}</option>))}
              </select>
            </Field>
            <Field label={t("المسمى الجديد")}>
              <select value={f.to_job_title_id} onChange={(e) => setF({ ...f, to_job_title_id: e.target.value })}>
                <option value="">{t("بدون تغيير")}</option>
                {titles.filter((x) => x.is_active).map((x) => (<option key={x.id} value={x.id}>{x.name}</option>))}
              </select>
            </Field>
            <Field label={t("الراتب الجديد")}>
              <input dir="ltr" inputMode="decimal" value={f.to_salary} onChange={(e) => setF({ ...f, to_salary: e.target.value.replace(/[^0-9.]/g, "") })} placeholder={t("بدون تغيير")} />
            </Field>
            <Field label={t("الحالة الجديدة")}>
              <select value={f.new_status} onChange={(e) => setF({ ...f, new_status: e.target.value })}>
                <option value="">{t("بدون تغيير")}</option>
                {Object.entries(STATUS).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
              </select>
            </Field>
            <Field label={t("السبب")}>
              <input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
            </Field>
          </div>
          <div className="form-actions" style={{ marginTop: 10 }}>
            <button className="btn btn-primary" disabled={busy}>{busy ? t("جارٍ التسجيل…") : t("تسجيل التحرك")}</button>
          </div>
        </form>
      </div>
    </>
  );
}

/** إعدادات HR: المسميات الوظيفية والدرجات والورديات والإجازات والعطلات. */
export function HrSettings() {
  const { t } = useI18n();
  const useTitles = useFetch(() => api.get<HrJobTitle[]>("/hr/job-titles"), "hr-titles");
  const useGrades = useFetch(() => api.get<HrGrade[]>("/hr/grades"), "hr-grades");
  const [error, setError] = useState<string | null>(null);

  return (
    <>
      <PageHeader title={t("hr.settingsTitle")} />
      <Alert>{error}</Alert>
      <TitlesCard list={useTitles} setError={setError} />
      <GradesCard list={useGrades} setError={setError} />
      <LeaveTypesCard setError={setError} />
      <ShiftsCard setError={setError} />
      <ShiftAssignmentsCard setError={setError} />
      <HolidaysCard setError={setError} />
    </>
  );
}

type CardList = { data: unknown; loading: boolean; reload: () => void };

function TitlesCard({ list, setError }: { list: CardList; setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const [f, setF] = useState({ name: "", min: "", max: "", desc: "" });
  const [busy, setBusy] = useState(false);
  const rows = (list.data as (HrJobTitle[] | null)) ?? [];
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>🏷️ {t("المسميات الوظيفية")}</h2>
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await api.post("/hr/job-titles", { name: f.name.trim(), min_salary: f.min || null, max_salary: f.max || null, description: f.desc.trim() || null });
            setF({ name: "", min: "", max: "", desc: "" });
            list.reload();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
        style={{ padding: "0 14px 10px" }}
      >
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field label={t("اسم المسمى*")}>
            <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={150} />
          </Field>
          <Field label={t("حد أدنى للراتب")}>
            <input dir="ltr" inputMode="decimal" value={f.min} onChange={(e) => setF({ ...f, min: e.target.value.replace(/[^0-9.]/g, "") })} />
          </Field>
          <Field label={t("حد أقصى للراتب")}>
            <input dir="ltr" inputMode="decimal" value={f.max} onChange={(e) => setF({ ...f, max: e.target.value.replace(/[^0-9.]/g, "") })} />
          </Field>
          <Field label={t("وصف")}>
            <input value={f.desc} onChange={(e) => setF({ ...f, desc: e.target.value })} />
          </Field>
          <button className="btn btn-primary" disabled={busy || !f.name.trim()}>{"+ "}{t("إضافة")}</button>
        </div>
      </form>
      <div className="table-wrap">
        {rows.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("الاسم")}</th><th className="num">{t("حد أدنى")}</th><th className="num">{t("حد أقصى")}</th><th>{t("الحالة")}</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td className="num">{r.min_salary ? money(r.min_salary) : "—"}</td>
                  <td className="num">{r.max_salary ? money(r.max_salary) : "—"}</td>
                  <td><ActiveBadge active={r.is_active} /></td>
                  <td className="actions">
                    <button className={`btn-toggle ${r.is_active ? "btn-toggle-off" : "btn-toggle-on"}`}
                      onClick={async () => { try { await api.patch(`/hr/job-titles/${r.id}`, { is_active: !r.is_active }); list.reload(); } catch (err) { setError((err as Error).message); } }}
                    >{r.is_active ? t("إيقاف") : t("تفعيل")}</button>{" "}
                    <button
                      className="btn-delete"
                     
                      onClick={async () => { try { await api.del(`/hr/job-titles/${r.id}`); list.reload(); } catch (err) { setError((err as Error).message); } }}
                    >
                      {t("حذف")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا توجد مسميات وظيفية بعد.")}</Empty>
        )}
      </div>
    </div>
  );
}

function GradesCard({ list, setError }: { list: CardList; setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const [f, setF] = useState({ name: "", min: "", max: "" });
  const [busy, setBusy] = useState(false);
  const rows = (list.data as (HrGrade[] | null)) ?? [];
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>🪜 {t("الدرجات الوظيفية")}</h2>
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await api.post("/hr/grades", { name: f.name.trim(), min_salary: f.min || null, max_salary: f.max || null });
            setF({ name: "", min: "", max: "" });
            list.reload();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
        style={{ padding: "0 14px 10px" }}
      >
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field label={t("اسم الدرجة*")}>
            <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={100} />
          </Field>
          <Field label={t("حد أدنى للراتب")}>
            <input dir="ltr" inputMode="decimal" value={f.min} onChange={(e) => setF({ ...f, min: e.target.value.replace(/[^0-9.]/g, "") })} />
          </Field>
          <Field label={t("حد أقصى للراتب")}>
            <input dir="ltr" inputMode="decimal" value={f.max} onChange={(e) => setF({ ...f, max: e.target.value.replace(/[^0-9.]/g, "") })} />
          </Field>
          <button className="btn btn-primary" disabled={busy || !f.name.trim()}>{"+ "}{t("إضافة")}</button>
        </div>
      </form>
      <div className="table-wrap">
        {rows.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("الاسم")}</th><th className="num">{t("حد أدنى")}</th><th className="num">{t("حد أقصى")}</th><th>{t("الحالة")}</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td className="num">{r.min_salary ? money(r.min_salary) : "—"}</td>
                  <td className="num">{r.max_salary ? money(r.max_salary) : "—"}</td>
                  <td><ActiveBadge active={r.is_active} /></td>
                  <td className="actions">
                    <button className={`btn-toggle ${r.is_active ? "btn-toggle-off" : "btn-toggle-on"}`}
                      onClick={async () => { try { await api.patch(`/hr/grades/${r.id}`, { is_active: !r.is_active }); list.reload(); } catch (err) { setError((err as Error).message); } }}
                    >{r.is_active ? t("إيقاف") : t("تفعيل")}</button>{" "}
                    <button
                      className="btn-delete"
                     
                      onClick={async () => { try { await api.del(`/hr/grades/${r.id}`); list.reload(); } catch (err) { setError((err as Error).message); } }}
                    >
                      {t("حذف")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا توجد درجات بعد.")}</Empty>
        )}
      </div>
    </div>
  );
}

/** أنواع الإجازات: رصيد سنوي، مدفوعة/لا، أيام ترحيل. */
function LeaveTypesCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const list = useFetch(() => api.get<HrLeaveType[]>("/hr/leave-types"), "hr-leave-types-admin");
  const [f, setF] = useState({ name: "", days: "", carry: "" });
  const [busy, setBusy] = useState(false);
  const rows = list.data ?? [];
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>🏖️ {t("أنواع الإجازات")}</h2>
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await api.post("/hr/leave-types", { name: f.name.trim(), days_per_year: f.days || "0", carry_over_days: f.carry || "0" });
            setF({ name: "", days: "", carry: "" });
            list.reload();
          } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
        }}
        style={{ padding: "0 14px 10px" }}
      >
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field label={t("اسم النوع*")}>
            <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={100} />
          </Field>
          <Field label={t("أيام/سنة")}>
            <input dir="ltr" inputMode="decimal" value={f.days} onChange={(e) => setF({ ...f, days: e.target.value.replace(/[^0-9.]/g, "") })} />
          </Field>
          <Field label={t("أيام ترحيل")}>
            <input dir="ltr" inputMode="decimal" value={f.carry} onChange={(e) => setF({ ...f, carry: e.target.value.replace(/[^0-9.]/g, "") })} />
          </Field>
          <button className="btn btn-primary" disabled={busy || !f.name.trim()}>{t("+ إضافة")}</button>
        </div>
      </form>
      <div className="table-wrap">
        {rows.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("الاسم")}</th><th className="num">{t("أيام/سنة")}</th><th className="num">{t("ترحيل")}</th><th>{t("الحالة")}</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td className="num">{r.days_per_year}</td>
                  <td className="num">{r.carry_over_days}</td>
                  <td><ActiveBadge active={r.is_active} /></td>
                  <td className="actions">
                    <button className={`btn-toggle ${r.is_active ? "btn-toggle-off" : "btn-toggle-on"}`}
                      onClick={async () => { try { await api.patch(`/hr/leave-types/${r.id}`, { is_active: !r.is_active }); list.reload(); } catch (err) { setError((err as Error).message); } }}
                    >{r.is_active ? t("إيقاف") : t("تفعيل")}</button>{" "}
                    <button
                      className="btn-delete"
                     
                      onClick={async () => { try { await api.del(`/hr/leave-types/${r.id}`); list.reload(); } catch (err) { setError((err as Error).message); } }}
                    >
                      {t("حذف")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا توجد أنواع إجازات — أضف «سنوية», «مرضية»…")}</Empty>
        )}
      </div>
    </div>
  );
}

/** الورديات: أوقات الدخول/الخروج ودقائق السماح وعبور منتصف الليل. */
function ShiftsCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const list = useFetch(() => api.get<HrShift[]>("/hr/shifts"), "hr-shifts");
  const [f, setF] = useState({ name: "", start: "09:00", end: "17:00", grace: "15", cross: false });
  const [busy, setBusy] = useState(false);
  const rows = list.data ?? [];
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>⏰ {t("الورديات")}</h2>
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await api.post("/hr/shifts", { name: f.name.trim(), start_time: f.start, end_time: f.end, grace_minutes: Number(f.grace || "15"), cross_midnight: f.cross });
            setF({ name: "", start: "09:00", end: "17:00", grace: "15", cross: false });
            list.reload();
          } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
        }}
        style={{ padding: "0 14px 10px" }}
      >
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field label={t("اسم الوردية*")}>
            <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={100} />
          </Field>
          <Field label={t("الدخول (HH:MM)")}>
            <input dir="ltr" pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} required />
          </Field>
          <Field label={t("الخروج (HH:MM)")}>
            <input dir="ltr" pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} required />
          </Field>
          <Field label={t("سماح (دقائق)")}>
            <input dir="ltr" inputMode="numeric" value={f.grace} onChange={(e) => setF({ ...f, grace: e.target.value.replace(/[^0-9]/g, "") })} />
          </Field>
          <label className="check"><input type="checkbox" checked={f.cross} onChange={(e) => setF({ ...f, cross: e.target.checked })} /> {t("عبور منتصف الليل")}</label>
          <button className="btn btn-primary" disabled={busy || !f.name.trim()}>{t("+ إضافة")}</button>
        </div>
      </form>
      <div className="table-wrap">
        {rows.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("الاسم")}</th><th>{t("الدخول")}</th><th>{t("الخروج")}</th><th className="num">{t("سماح")}</th><th>{t("ليلية؟")}</th><th>{t("الحالة")}</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td dir="ltr">{r.start_time}</td>
                  <td dir="ltr">{r.end_time}</td>
                  <td className="num">{r.grace_minutes}</td>
                  <td>{r.cross_midnight ? t("نعم") : "—"}</td>
                  <td><ActiveBadge active={r.is_active} /></td>
                  <td className="actions">
                    <button className={`btn-toggle ${r.is_active ? "btn-toggle-off" : "btn-toggle-on"}`}
                      onClick={async () => { try { await api.patch(`/hr/shifts/${r.id}`, { is_active: !r.is_active }); list.reload(); } catch (err) { setError((err as Error).message); } }}
                    >{r.is_active ? t("إيقاف") : t("تفعيل")}</button>{" "}
                    <button
                      className="btn-delete"
                     
                      onClick={async () => { try { await api.del(`/hr/shifts/${r.id}`); list.reload(); } catch (err) { setError((err as Error).message); } }}
                    >
                      {t("حذف")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا توجد ورديات — أضف وردية صباحية كالبداية.")}</Empty>
        )}
      </div>
    </div>
  );
}

/** إسناد الورديات للموظفين: صف لكل موظف نشط مع قائمة اختيار الوردية. */
function ShiftAssignmentsCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const list = useFetch(() => api.get<HrShiftAssignment[]>("/hr/shift-assignments"), "hr-shift-assigned");
  const shifts = useFetch(() => api.get<HrShift[]>("/hr/shifts?active_only=true"), "hr-shifts-active");
  const employees = useFetch(() => api.get<HrEmployee[]>("/hr/employees?limit=200"), "hr-employees-assignments");
  const saving = useState(false);
  const setBusy = saving[1];
  const byEmployee = new Map((list.data ?? []).map((a) => [a.employee_id, a]));
  const rows = (employees.data ?? []).filter((e) => e.is_active);
  const assign = async (employeeId: number, shiftId: string) => {
    setBusy(true);
    try {
      await api.post("/hr/shift-assignments", { employee_id: employeeId, shift_id: shiftId === "" ? null : Number(shiftId) });
      list.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>👷 {t("إسناد الورديات")}</h2>
        <span className="muted" style={{ fontSize: 13 }}>{t("اختر وردية لكل موظف — يُحسب التأخير تلقائيًا في سجل الحضور")}</span>
      </div>
      <div className="table-wrap" style={{ maxHeight: 360, overflow: "auto" }}>
        {rows.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("الموظف")}</th><th>{t("الوردية الحالية")}</th></tr>
            </thead>
            <tbody>
              {rows.map((e) => {
                const cur = byEmployee.get(e.id);
                return (
                  <tr key={e.id}>
                    <td>{e.full_name} <span className="muted">({e.code})</span></td>
                    <td>
                      <select value={cur ? String(cur.shift_id) : ""} onChange={(ev) => void assign(e.id, ev.target.value)} disabled={saving[0]}>
                        <option value="">{t("بدون وردية")}</option>
                        {(shifts.data ?? []).map((s) => (<option key={s.id} value={s.id}>{s.name} ({s.start_time}–{s.end_time})</option>))}
                      </select>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا يوجد موظفون نشطون بعد.")}</Empty>
        )}
      </div>
    </div>
  );
}

/** العطلات الرسمية: فريدة بالتاريخ لكل شركة. */
function HolidaysCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const list = useFetch(() => api.get<HrHoliday[]>(`/hr/holidays?year=${new Date().getFullYear()}`), "hr-holidays");
  const [f, setF] = useState({ name: "", date: "" });
  const [busy, setBusy] = useState(false);
  const rows = list.data ?? [];
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>🎉 {t("العطلات الرسمية")}</h2>
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await api.post("/hr/holidays", { name: f.name.trim(), holiday_date: f.date });
            setF({ name: "", date: "" });
            list.reload();
          } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
        }}
        style={{ padding: "0 14px 10px" }}
      >
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field label={t("اسم العطلة*")}>
            <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={150} />
          </Field>
          <Field label={t("التاريخ*")}>
            <input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} required />
          </Field>
          <button className="btn btn-primary" disabled={busy || !f.name.trim() || !f.date}>{t("+ إضافة")}</button>
        </div>
      </form>
      <div className="table-wrap">
        {rows.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("التاريخ")}</th><th>{t("الاسم")}</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.holiday_date}</td>
                  <td>{r.name}</td>
                  <td className="actions">
                    <button
                      className="btn-delete"
                     
                      onClick={async () => { try { await api.del(`/hr/holidays/${r.id}`); list.reload(); } catch (err) { setError((err as Error).message); } }}
                    >
                      {t("حذف")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا توجد عطلات رسمية مسجلة لهذه السنة.")}</Empty>
        )}
      </div>
    </div>
  );
}

// =====================================================================
// S2 — الحضور والورديات والإجازات
// =====================================================================

const ATT_STATUS: Record<HrAttendance["status"], string> = {
  present: "حاضر",
  late: "متأخر",
  absent: "غياب",
  excused: "غياب بعذر",
};

/** مطالبات تصحيح الحضور من الموظفين — المدير يعتمدها أو يرفضها. */
function AttendanceCorrectionsCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const list = useFetch(() => api.get<HrAttendanceCorrection[]>("/hr/attendance-corrections?correction_status=pending"), "hr-corr-pending");
  const [busy, setBusy] = useState(false);

  const decide = async (id: number, kind: "approve" | "reject") => {
    setBusy(true);
    setError(null);
    try {
      if (kind === "approve") {
        await api.post(`/hr/attendance-corrections/${id}/approve`, { decision_note: null });
        list.reload();
      } else {
        await api.post(`/hr/attendance-corrections/${id}/reject`, { decision_note: null });
        list.reload();
      }
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const rows = list.data ?? [];
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>🔧 {t("مطالبات تصحيح الحضور")}</h2>
        <span className="muted" style={{ fontSize: 13 }}>
          {rows.length > 0 ? `⏳ ${rows.length} ${t("طلب معلّق")}` : t("لا مطالبات معلّقة")}
        </span>
      </div>
      <div className="table-wrap">
        {rows.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("اليوم")}</th><th>{t("الموظف")}</th><th>{t("مطلوب")}</th><th>{t("السبب")}</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>{c.work_date}</td>
                  <td>{c.employee_name} <span className="muted">({c.employee_code})</span></td>
                  <td dir="ltr">{c.requested_check_in ?? "—"} → {c.requested_check_out ?? "—"}</td>
                  <td>{c.reason}</td>
                  <td className="actions">
                    <button className="btn btn-sm" disabled={busy} style={{ color: "#15803d", borderColor: "#15803d" }} onClick={() => void decide(c.id, "approve")}>✓ {t("اعتماد")}</button>{" "}
                    <button className="btn btn-sm" disabled={busy} style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => void decide(c.id, "reject")}>✕ {t("رفض")}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا مطالبات معلّقة الآن — ستظهر هنا على أكثرها حداثة.")}</Empty>
        )}
      </div>
    </div>
  );
}

const LEAVE_STATUS: Record<HrLeaveRequest["status"], string> = {
  pending: "معلّق",
  approved: "معتمد",
  rejected: "مرفوض",
  cancelled: "ملغى",
};

/** صفحة الحضور والانصراف: تصفية بالموظف/التاريخ/الحالة + تسجيل وتعديل وحذف. */
/** استيراد حضور من جهاز البصمة — لصق CSV: كود الموظف، التاريخ، الدخول، الخروج، الحالة. */
function AttendanceImportCard() {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const { busy, error, run } = useAction();
  const [result, setResult] = useState<{ created: number; updated: number; errors: string[] } | null>(null);

  const parse = (): { employee_code: string; work_date: string; check_in: string | null; check_out: string | null; status: string | null }[] => {
    const rows: { employee_code: string; work_date: string; check_in: string | null; check_out: string | null; status: string | null }[] = [];
    for (const line of text.split(/\n+/)) {
      const cells = line.split(/[,\t;]+/).map((c) => c.trim());
      if (!cells[0] || !cells[1] || /^(كود|code|employee)/i.test(cells[0])) continue; // تخطي العنوان
      rows.push({ employee_code: cells[0], work_date: cells[1], check_in: cells[2] || null, check_out: cells[3] || null, status: cells[4] || null });
    }
    return rows;
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const rows = parse();
    if (rows.length === 0) { setResult({ created: 0, updated: 0, errors: [t("لا صفوف صالحة — تأكد من التنسيق")] }); return; }
    void run(async () => {
      const out = await api.post<{ created: number; updated: number; errors: string[] }>("/hr/attendance/import", { rows });
      setResult(out);
      setText("");
    });
  };

  return (
    <div className="card card-pad" style={{ marginBottom: 16 }}>
      <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>📡 {t("استيراد حضور من جهاز البصمة")}</h3>
      <p className="muted" style={{ margin: "0 0 8px", fontSize: 12.5 }} dir="rtl">
        {t("الصق صفوفًا بصيغة CSV: كود الموظف، التاريخ (YYYY-MM-DD)، الدخول، الخروج، الحالة (اختياري)")}. {t("الصف الموجود يُحدَّث والمفقود يُنشأ بمصدر بصمة.")}
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      {result && (
        <Alert kind={result.errors.length ? "error" : "info"}>
          ✅ {t("جديد")}: {result.created} · {t("محدّث")}: {result.updated}
          {result.errors.length > 0 && <div>{result.errors.join(" · ")}</div>}
        </Alert>
      )}
      <form onSubmit={submit}>
        <textarea
          dir="ltr"
          rows={6}
          style={{ width: "100%", fontFamily: "monospace", fontSize: 12.5 }}
          placeholder={"EG-1,2026-11-10,08:00,16:00\nEG-2,2026-11-10,08:30,16:30,late"}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="form-actions" style={{ marginTop: 8 }}>
          <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>{t("استيراد")}</button>
        </div>
      </form>
    </div>
  );
}

export function HrAttendancePage() {
  const { t } = useI18n();
  const today = new Date().toISOString().slice(0, 10);
  const [emp, setEmp] = useState<HrEmployee | null>(null);
  const [statusF, setStatusF] = useState("");
  const [dateF, setDateF] = useState("");
  const list = usePagedList<HrAttendance>("/hr/attendance", {
    employee_id: emp?.id ?? undefined,
    attendance_status: statusF || undefined,
    work_date: dateF || undefined,
  });

  const [openAdd, setOpenAdd] = useState(false);
  const [editing, setEditing] = useState<HrAttendance | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [f, setF] = useState({ employee: null as HrEmployee | null, date: today, status: "present", check_in: "", check_out: "", notes: "" });
  const [ef, setEf] = useState({ status: "present", check_in: "", check_out: "", notes: "" });

  const submitAdd = async (e: FormEvent) => {
    e.preventDefault();
    if (!f.employee) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/hr/attendance", {
        employee_id: f.employee.id,
        work_date: f.date,
        status: f.status,
        check_in: f.check_in || null,
        check_out: f.check_out || null,
        notes: f.notes.trim() || null,
      });
      setOpenAdd(false);
      setF({ employee: null, date: today, status: "present", check_in: "", check_out: "", notes: "" });
      setNote(t("تم تسجيل سجل الحضور."));
      list.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/hr/attendance/${editing.id}`, {
        status: ef.status,
        check_in: ef.check_in || null,
        check_out: ef.check_out || null,
        notes: ef.notes.trim() || null,
      });
      setEditing(null);
      setNote(t("تم تحديث السجل؛ أعيد حساب التأخير والإضافي حسب الوردية."));
      list.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const badge = (s: HrAttendance["status"]) => (
    <span className={`badge ${s === "present" ? "badge-confirmed" : s === "late" ? "badge-draft" : "badge-off"}`}>{ATT_STATUS[s]}</span>
  );

  return (
    <>
      <PageHeader title={t("الحضور والانصراف")}>
        <button className="btn btn-primary" onClick={() => { setError(null); setF({ employee: null, date: today, status: "present", check_in: "", check_out: "", notes: "" }); setOpenAdd(true); }}>
          {"+ "}{t("تسجيل حضور")}
        </button>
      </PageHeader>

      <AttendanceImportCard />

      <div className="toolbar" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        <div style={{ minWidth: 240 }}>
          <Lookup<HrEmployee>
            path="/hr/employees"
            value={emp}
            onChange={setEmp}
            label={(x) => `${x.full_name} (${x.code})`}
            placeholder={t("تصفية بموظف…")}
          />
        </div>
        <input type="date" value={dateF} onChange={(e) => setDateF(e.target.value)} title={t("تاريخ محدد")} />
        <select value={statusF} onChange={(e) => setStatusF(e.target.value)}>
          <option value="">{t("كل الحالات")}</option>
          {Object.entries(ATT_STATUS).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
        </select>
        {(emp || statusF || dateF) && (
          <button className="btn btn-sm" onClick={() => { setEmp(null); setStatusF(""); setDateF(""); }}>{t("مسح التصفية")}</button>
        )}
      </div>

      <Alert>{list.error}</Alert>
      {error && <Alert>{error}</Alert>}
      {note && (
        <div style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg)", color: "var(--ok)" }}>
          {note}
        </div>
      )}

      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : (list.data ?? []).length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("التاريخ")}</th>
                <th>{t("الموظف")}</th>
                <th>{t("الدخول")}</th>
                <th>{t("الخروج")}</th>
                <th className="num">{t("تأخير (د)")}</th>
                <th className="num">{t("إضافي (د)")}</th>
                <th>{t("الحالة")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(list.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td>{r.work_date}</td>
                  <td><strong>{r.employee_name}</strong><span className="muted"> ({r.employee_code})</span></td>
                  <td dir="ltr">{r.check_in ?? "—"}</td>
                  <td dir="ltr">{r.check_out ?? "—"}</td>
                  <td className="num">{r.late_minutes || "—"}</td>
                  <td className="num">{r.overtime_minutes || "—"}</td>
                  <td>{badge(r.status)}</td>
                  <td className="actions">
                    <button className="btn-edit" onClick={() => { setEditing(r); setEf({ status: r.status, check_in: r.check_in ?? "", check_out: r.check_out ?? "", notes: r.notes ?? "" }); setError(null); }}>{t("تعديل")}</button>{" "}
                    <button
                      className="btn-delete"
                     
                      onClick={async () => { try { await api.del(`/hr/attendance/${r.id}`); list.reload(); } catch (err) { setError((err as Error).message); } }}
                    >
                      {t("حذف")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا توجد سجلات حضور مطابقة.")}</Empty>
        )}
      </div>
      <Pager list={list} />

      <AttendanceCorrectionsCard setError={setError} />

      {openAdd && (
        <Modal title={t("تسجيل حضور")} onClose={() => setOpenAdd(false)} wide>
          <form onSubmit={submitAdd}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="الموظف*">
                <Lookup<HrEmployee>
                  path="/hr/employees"
                  value={f.employee}
                  onChange={(v) => setF({ ...f, employee: v })}
                  label={(x) => `${x.full_name} (${x.code})`}
                  placeholder="ابحث بالاسم أو الكود…"
                />
              </Field>
              <Field label="التاريخ*">
                <input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} required />
              </Field>
              <Field label="الحالة">
                <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
                  {Object.entries(ATT_STATUS).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
                </select>
              </Field>
              <Field label="وقت الدخول" hint="يحسب التأخير حسب وردية الموظف تلقائيًا">
                <input dir="ltr" inputMode="numeric" pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$" value={f.check_in} onChange={(e) => setF({ ...f, check_in: e.target.value })} placeholder="09:00" />
              </Field>
              <Field label="وقت الخروج">
                <input dir="ltr" inputMode="numeric" pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$" value={f.check_out} onChange={(e) => setF({ ...f, check_out: e.target.value })} placeholder="17:00" />
              </Field>
              <Field label="ملاحظات">
                <input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
              </Field>
            </div>
            <div className="form-actions" style={{ marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy || !f.employee} >{busy ? t("جارٍ الحفظ…") : t("حفظ السجل")}</button>
              <button type="button" className="btn" onClick={() => setOpenAdd(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {editing && (
        <Modal title={`${t("تعديل حضور — ")}${editing.employee_name ?? ""} · ${editing.work_date}`} onClose={() => setEditing(null)} wide>
          <form onSubmit={submitEdit}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="الحالة">
                <select value={ef.status} onChange={(e) => setEf({ ...ef, status: e.target.value })}>
                  {Object.entries(ATT_STATUS).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
                </select>
              </Field>
              <Field label="وقت الدخول">
                <input dir="ltr" value={ef.check_in} onChange={(e) => setEf({ ...ef, check_in: e.target.value })} placeholder="09:00" />
              </Field>
              <Field label="وقت الخروج">
                <input dir="ltr" value={ef.check_out} onChange={(e) => setEf({ ...ef, check_out: e.target.value })} placeholder="17:00" />
              </Field>
              <Field label="ملاحظات">
                <input value={ef.notes} onChange={(e) => setEf({ ...ef, notes: e.target.value })} />
              </Field>
            </div>
            <div className="form-actions" style={{ marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy}>{busy ? t("جارٍ الحفظ…") : t("حفظ")}</button>
              <button type="button" className="btn" onClick={() => setEditing(null)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

/** صفحة الإجازات: الأنواع تلقائيًا، الأرصدة، الطلبات مع موافقة/رفض/إلغاء. */
export function HrLeaves() {
  const { t } = useI18n();
  const today = new Date().toISOString().slice(0, 10);
  const year = today.slice(0, 4);
  const balances = useFetch(() => api.get<HrLeaveBalance[]>(`/hr/leave-balances?year=${year}`), `hr-balances-${year}`);
  const types = useFetch(() => api.get<HrLeaveType[]>("/hr/leave-types?active_only=true"), "hr-leave-types");
  const [statusF, setStatusF] = useState<string>("pending");
  const requests = usePagedList<HrLeaveRequest>("/hr/leave-requests", { request_status: statusF || undefined });

  const [openAdd, setOpenAdd] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [f, setF] = useState({ employee: null as HrEmployee | null, type_id: "", from_date: today, to_date: today, reason: "" });
  const [decision, setDecision] = useState<{ req: HrLeaveRequest; kind: "approve" | "reject" } | null>(null);
  const [decisionNote, setDecisionNote] = useState("");

  const submitAdd = async (e: FormEvent) => {
    e.preventDefault();
    if (!f.employee || !f.type_id) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/hr/leave-requests", {
        employee_id: f.employee.id,
        leave_type_id: Number(f.type_id),
        from_date: f.from_date,
        to_date: f.to_date,
        reason: f.reason.trim() || null,
      });
      setOpenAdd(false);
      setF({ employee: null, type_id: "", from_date: today, to_date: today, reason: "" });
      setNote(t("تم إنشاء طلب الإجازة في حالة «معلّق»."));
      requests.reload();
      balances.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const decide = async () => {
    if (!decision) return;
    setBusy(true);
    setError(null);
    try {
      if (decision.kind === "approve") {
        await api.post(`/hr/leave-requests/${decision.req.id}/approve`, { decision_note: decisionNote.trim() || null });
        setNote(t("تمت الموافقة وخصم الأيام من الرصيد."));
      } else {
        await api.post(`/hr/leave-requests/${decision.req.id}/reject`, { decision_note: decisionNote.trim() || null });
        setNote(t("تم رفض الطلب."));
      }
      setDecision(null);
      setDecisionNote("");
      requests.reload();
      balances.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const leaveBadge = (s: HrLeaveRequest["status"]) => (
    <span className={`badge ${s === "approved" ? "badge-confirmed" : s === "pending" ? "badge-draft" : "badge-off"}`}>{LEAVE_STATUS[s]}</span>
  );

  return (
    <>
      <PageHeader title={t("الإجازات")}>
        <button className="btn btn-primary" onClick={() => { setError(null); setOpenAdd(true); }}>
          {"+ "}{t("طلب إجازة")}
        </button>
      </PageHeader>

      <Alert>{error}</Alert>
      {note && (
        <div style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg)", color: "var(--ok)" }}>
          {note}
        </div>
      )}

      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>⚖️ {t(`أرصدة الإجازات — سنة ${year}`)}</h2>
        </div>
        <div className="table-wrap">
          {balances.loading ? (
            <Loading />
          ) : (balances.data ?? []).length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>{t("الموظف")}</th>
                  <th>{t("النوع")}</th>
                  <th className="num">{t("المستحق")}</th>
                  <th className="num">{t("المُرحَّل")}</th>
                  <th className="num">{t("المستخدم")}</th>
                  <th className="num">{t("المتبقي")}</th>
                </tr>
              </thead>
              <tbody>
                {(balances.data ?? []).map((b) => (
                  <tr key={b.id}>
                    <td>{b.employee_name} <span className="muted">({b.employee_code})</span></td>
                    <td>{b.leave_type_name}</td>
                    <td className="num">{b.entitled_days}</td>
                    <td className="num">{b.carried_days}</td>
                    <td className="num">{b.used_days}</td>
                    <td className="num" style={{ fontWeight: 700, color: b.remaining_days === "0.0" ? "var(--danger)" : undefined }}>{b.remaining_days}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("لا يوجد موظفون نشطون أو أنواع إجازات مفعّلة بعد.")}</Empty>
          )}
        </div>
      </div>

      <div className="toolbar" style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <select value={statusF} onChange={(e) => setStatusF(e.target.value)}>
          <option value="">{t("كل الحالات")}</option>
          {Object.entries(LEAVE_STATUS).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
        </select>
      </div>

      <div className="card table-wrap">
        {requests.loading && !requests.data ? (
          <Loading />
        ) : (requests.data ?? []).length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("الموظف")}</th>
                <th>{t("النوع")}</th>
                <th>{t("من")}</th>
                <th>{t("إلى")}</th>
                <th className="num">{t("الأيام")}</th>
                <th>{t("الحالة")}</th>
                <th>{t("السبب / القرار")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(requests.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td><strong>{r.employee_name}</strong> <span className="muted">({r.employee_code})</span></td>
                  <td>{r.leave_type_name}</td>
                  <td>{r.from_date}</td>
                  <td>{r.to_date}</td>
                  <td className="num">{r.days}</td>
                  <td>{leaveBadge(r.status)}</td>
                  <td>{r.reason ?? r.decision_note ?? "—"}</td>
                  <td className="actions">
                    {r.status === "pending" && (
                      <>
                        <button
                          className="btn btn-sm"
                          style={{ color: "#15803d", borderColor: "#15803d" }}
                          onClick={() => setDecision({ req: r, kind: "approve" })}
                        >
                          ✓ {t("موافقة")}
                        </button>{" "}
                        <button
                          className="btn btn-sm"
                          style={{ color: "var(--danger)", borderColor: "var(--danger)" }}
                          onClick={() => setDecision({ req: r, kind: "reject" })}
                        >
                          ✕ {t("رفض")}
                        </button>{" "}
                      </>
                    )}
                    {r.status === "approved" && (
                      <button
                        className="btn btn-sm"
                        onClick={() => { setError(null); setBusy(true); void (async () => { try { await api.post(`/hr/leave-requests/${r.id}/cancel`); setNote(t("تم إلغاء الإجازة وأعيدت أيامها للرصيد.")); requests.reload(); balances.reload(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); } })(); }}
                        disabled={busy}
                      >
                        {t("إلغاء")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا توجد طلبات إجازة مطابقة.")}</Empty>
        )}
      </div>
      <Pager list={requests} />

      {openAdd && (
        <Modal title={t("طلب إجازة جديد")} onClose={() => setOpenAdd(false)} wide>
          <form onSubmit={submitAdd}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label="الموظف*">
                <Lookup<HrEmployee>
                  path="/hr/employees"
                  value={f.employee}
                  onChange={(v) => setF({ ...f, employee: v })}
                  label={(x) => `${x.full_name} (${x.code})`}
                  placeholder="ابحث بالاسم أو الكود…"
                />
              </Field>
              <Field label="نوع الإجازة*">
                <select value={f.type_id} onChange={(e) => setF({ ...f, type_id: e.target.value })} required>
                  <option value="">—</option>
                  {(types.data ?? []).map((x) => (<option key={x.id} value={x.id}>{x.name} ({x.days_per_year} يوم/سنة)</option>))}
                </select>
              </Field>
              <Field label="من تاريخ*">
                <input type="date" value={f.from_date} onChange={(e) => setF({ ...f, from_date: e.target.value })} required />
              </Field>
              <Field label="إلى تاريخ*">
                <input type="date" value={f.to_date} onChange={(e) => setF({ ...f, to_date: e.target.value })} required />
              </Field>
              <Field label="السبب">
                <input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
              </Field>
            </div>
            <div className="form-actions" style={{ marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy || !f.employee || !f.type_id}>{busy ? t("جارٍ الحفظ…") : t("إنشاء الطلب")}</button>
              <button type="button" className="btn" onClick={() => setOpenAdd(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {decision && (
        <Modal title={decision.kind === "approve" ? t("موافقة على الطلب") : t("رفض الطلب")} onClose={() => setDecision(null)}>
          <p style={{ margin: "0 0 10px" }}>
            {decision.req.employee_name} · {decision.req.leave_type_name} · {decision.req.from_date} → {decision.req.to_date} ({decision.req.days} يوم)
          </p>
          <Field label={t("ملاحظة القرار (اختياري)")}>
            <input value={decisionNote} onChange={(e) => setDecisionNote(e.target.value)} />
          </Field>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              className="btn btn-primary"
              disabled={busy}
              style={decision.kind === "reject" ? { background: "var(--danger)", borderColor: "var(--danger)" } : undefined}
              onClick={() => void decide()}
            >
              {busy ? t("جارٍ التنفيذ…") : decision.kind === "approve" ? `✓ ${t("تأكيد الموافقة")}` : `✕ ${t("تأكيد الرفض")}`}
            </button>
            <button type="button" className="btn" onClick={() => setDecision(null)}>{t("إلغاء")}</button>
          </div>
        </Modal>
      )}
    </>
  );
}

// =====================================================================
// S3 — الرواتب: مكونات لكل موظف + مسيرات شهرية بترحيل محاسبي
// =====================================================================

const MONTH_NAMES = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"];

const slipBadge = (s: HrPayrollRun["status"], t: (x: string) => string) => (
  <span className={`badge ${s === "posted" ? "badge-confirmed" : "badge-draft"}`}>{s === "posted" ? t("مُرحَّل") : t("مسودّة")}</span>
);

/** نافذة تفاصيل قسيمة: سطور الربح والخصوم (مجمدة وقت التوليد). */
function PayslipLinesModal({ slip, onClose }: { slip: HrPayslip; onClose: () => void }) {
  const { t } = useI18n();
  const [lines, setLines] = useState<HrPayslipLine[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .get<HrPayslipLine[]>(`/hr/payslips/${slip.id}`)
      .then((d) => { if (!cancelled) setLines(d); })
      .catch(() => setLines([]));
    return () => { cancelled = true; };
  }, [slip.id]);
  return (
    <Modal title={`${t("قسيمة")} — ${slip.employee_name ?? ""} (${slip.employee_code ?? ""})`} onClose={onClose} wide>
      <table style={{ width: "100%", marginBottom: 14 }}>
        <tbody>
          <tr><td>{t("الأساسي")}</td><td className="num">{money(slip.base_salary)}</td></tr>
          <tr><td>{t("غياب")}</td><td className="num">{slip.absent_days} — {t("أيام إجازة غير مدفوعة")}: {slip.unpaid_leave_days}</td></tr>
          <tr><td>{t("خصم الغياب")}</td><td className="num">{money(slip.absence_deduction)}</td></tr>
        </tbody>
      </table>
      <div className="table-wrap">
        {lines === null ? (
          <Loading />
        ) : lines.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("البند")}</th><th>{t("النوع")}</th><th className="num">{t("القيمة")}</th></tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.id}>
                  <td>{l.name}</td>
                  <td><span className={`badge ${l.category === "earning" ? "badge-confirmed" : "badge-off"}`}>{l.category === "earning" ? t("استحقاق") : t("خصم")}</span></td>
                  <td className="num" style={{ color: l.category === "earning" ? undefined : "var(--danger)" }}>{money(l.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا بنود.")}</Empty>
        )}
      </div>
      <p style={{ marginTop: 14, textAlign: "end", fontWeight: 700 }}>{t("الصافي")}: <span dir="ltr" style={{ fontSize: 16 }}>{money(slip.net_pay)}</span></p>
    </Modal>
  );
}

/** إدارة مكوّنات راتب موظف (بدلات/خصومات ثابتة أو نسبي). */
function SalaryComponentsCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const [seedMsg, setSeedMsg] = useState<string | null>(null);
  const [emp, setEmp] = useState<HrEmployee | null>(null);
  const list = useFetch(
    () => (emp ? api.get<HrSalaryComponent[]>(`/hr/salary-components?employee_id=${emp.id}`) : Promise.resolve([])),
    `hr-comp-${emp?.id ?? "none"}`,
  );
  const [f, setF] = useState({ category: "earning", name: "", mode: "fixed", value: "" });
  const [busy, setBusy] = useState(false);

  const seedEg = async () => {
    setBusy(true);
    try {
      const out = await api.post<{ created_count: number; skipped_count: number; employees: number }>("/hr/payroll/seed-eg-components", {});
      setSeedMsg(`✅ ${t("أُنشئ")}: ${out.created_count} · ${t("موجود مسبقًا")}: ${out.skipped_count} · ${t("موظفين")}: ${out.employees}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const [bulk, setBulk] = useState({ name: "التأمينات الاجتماعية (حصة الموظف)", percent: "" });
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);
  const saveBulk = async (e: FormEvent) => {
    e.preventDefault();
    if (!bulk.name.trim() || bulk.percent === "") return;
    setBusy(true);
    try {
      const out = await api.patch<{ updated_count: number }>("/hr/salary-components/bulk", {
        name: bulk.name.trim(),
        category: "deduction",
        percent_value: Number(bulk.percent),
      });
      setBulkMsg(`✅ ${t("حُدّثت")}: ${out.updated_count} ${t("بنداً بنسبة")} ${bulk.percent}%`);
      list.reload();
    } catch (err) {
      setBulkMsg((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!emp) return;
    setBusy(true);
    try {
      await api.post("/hr/salary-components", {
        employee_id: emp.id,
        category: f.category,
        name: f.name.trim(),
        amount_mode: f.mode,
        fixed_amount: f.mode === "fixed" ? f.value || "0" : null,
        percent_value: f.mode === "percent_of_base" ? f.value || "0" : null,
      });
      setF({ ...f, name: "", value: "" });
      list.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>💵 {t("مكونات الراتب")}</h2>
        <span className="muted" style={{ fontSize: 13 }}>{t("بدلات وخصومات لكل موظف — تدخل في قسيمات أي مسير جديد")}</span>
        <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void seedEg()}>
            🇪🇬 {t("تهيئة خصومات مصر (تأمينات + ضريبة) لكل الموظفين النشطين")}
          </button>
          {seedMsg && <small className="hint">{seedMsg}</small>}
        </div>
        <details style={{ marginTop: 8 }}>
          <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: 13 }}>✏️ {t("تحديث جماعي لنسبة خصم (بعد البذر)")}</summary>
          <form onSubmit={saveBulk} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginTop: 8 }}>
            <Field label={t("اسم البند")}>
              <input list="eg-deduction-names" value={bulk.name} onChange={(e) => setBulk({ ...bulk, name: e.target.value })} maxLength={100} style={{ minWidth: 260 }} />
              <datalist id="eg-deduction-names">
                <option value="التأمينات الاجتماعية (حصة الموظف)" />
                <option value="ضريبة الدخل المصري" />
              </datalist>
            </Field>
            <Field label={t("النسبة الجديدة %")}>
              <input type="number" min="0" max="100" step="0.01" dir="ltr" value={bulk.percent} onChange={(e) => setBulk({ ...bulk, percent: e.target.value })} style={{ width: 110 }} />
            </Field>
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy || bulk.percent === ""}>{t("تحديث للكل")}</button>
            {bulkMsg && <small className="hint">{bulkMsg}</small>}
          </form>
        </details>
      </div>
      <div style={{ padding: "10px 14px" }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <div style={{ minWidth: 240 }}>
            <Lookup<HrEmployee>
              path="/hr/employees"
              value={emp}
              onChange={setEmp}
              label={(x) => `${x.full_name} (${x.code})`}
              placeholder={t("اختر موظفاً…")}
            />
          </div>
        </div>
        {emp && (
          <>
            <form onSubmit={submit} style={{ margin: "10px 0" }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
                <Field label={t("النوع")}>
                  <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
                    <option value="earning">{t("استحقاق (بدل/علاوة)")}</option>
                    <option value="deduction">{t("خصم")}</option>
                  </select>
                </Field>
                <Field label={t("الاسم*")}>
                  <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={100} />
                </Field>
                <Field label={t("نمط القيمة")}>
                  <select value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}>
                    <option value="fixed">{t("مبلغ ثابت")}</option>
                    <option value="percent_of_base">{t("نسبة من الأساسي")}</option>
                  </select>
                </Field>
                <Field label={f.mode === "fixed" ? t("المبلغ*") : t("النسبة (0-100)*")}>
                  <input dir="ltr" inputMode="decimal" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value.replace(/[^0-9.]/g, "") })} required />
                </Field>
                <button className="btn btn-primary" disabled={busy}>{t("+ إضافة")}</button>
              </div>
            </form>
            <div className="table-wrap">
              {(list.data ?? []).length > 0 ? (
                <table>
                  <thead>
                    <tr><th>{t("الاسم")}</th><th>{t("النوع")}</th><th className="num">{t("القيمة")}</th><th>{t("الحالة")}</th><th /></tr>
                  </thead>
                  <tbody>
                    {(list.data ?? []).map((c) => (
                      <tr key={c.id}>
                        <td>{c.name}</td>
                        <td><span className={`badge ${c.category === "earning" ? "badge-confirmed" : "badge-off"}`}>{c.category === "earning" ? t("استحقاق") : t("خصم")}</span></td>
                        <td className="num">{c.amount_mode === "fixed" ? money(c.fixed_amount ?? "0") : `${c.percent_value}%`}</td>
                        <td><ActiveBadge active={c.is_active} /></td>
                        <td className="actions">
                          <button className={`btn-toggle ${c.is_active ? "btn-toggle-off" : "btn-toggle-on"}`} onClick={async () => { try { await api.patch(`/hr/salary-components/${c.id}`, { is_active: !c.is_active }); list.reload(); } catch (err) { setError((err as Error).message); } }}>{c.is_active ? t("إيقاف") : t("تفعيل")}</button>{" "}
                          <button className="btn-delete" onClick={async () => { try { await api.del(`/hr/salary-components/${c.id}`); list.reload(); } catch (err) { setError((err as Error).message); } }}>
                            {t("حذف")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <Empty>{t("لا مكونات لهذا الموظف — الراتب سيكون الأساسي فقط.")}</Empty>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** السلف/القروض: مبلغ على أقساط شهرية تُخصم آلياً في قسائم المسير. */
function AdvancesCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const now = new Date();
  const [limits, setLimits] = useState<{ user_id: number; username: string; max_amount: number }[]>([]);
  const [limitUsers, setLimitUsers] = useState<{ id: number; username: string }[]>([]);
  const [limitUser, setLimitUser] = useState("");
  const [limitAmount, setLimitAmount] = useState("");
  const [limitMsg, setLimitMsg] = useState<string | null>(null);
  const [emp, setEmp] = useState<HrEmployee | null>(null);

  const reloadLimits = async () => {
    try {
      const page = await api.get<{ limits: { user_id: number; username: string; max_amount: number }[]; users: { id: number; username: string }[] }>("/hr/approval-limits");
      setLimits(page.limits);
      setLimitUsers(page.users);
    } catch { /* عرض اللوطات اختياري */ }
  };
  useState(() => { void reloadLimits(); });
  const list = useFetch(
    () => (emp ? api.get<HrAdvance[]>(`/hr/advances?employee_id=${emp.id}`) : api.get<HrAdvance[]>("/hr/advances")),
    `hr-adv-${emp?.id ?? "all"}`,
  );
  const [f, setF] = useState({ amount: "", count: "10", y: now.getFullYear(), m: now.getMonth() + 1, notes: "" });
  const [busy, setBusy] = useState(false);

  const saveLimit = async (e: FormEvent) => {
    e.preventDefault();
    if (!limitUser) return;
    try {
      await api.put(`/hr/approval-limits/${limitUser}`, { max_amount: limitAmount === "" ? null : Number(limitAmount) });
      setLimitMsg(`✅ ${t("حُفظ حد الموافقة")}`);
      setLimitAmount("");
      void reloadLimits();
    } catch (err) {
      setLimitMsg((err as Error).message);
    }
  };
  const removeLimit = async (userId: number) => {
    try {
      await api.put(`/hr/approval-limits/${userId}`, { max_amount: null });
      void reloadLimits();
    } catch (err) {
      setLimitMsg((err as Error).message);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!emp) return;
    setBusy(true);
    try {
      await api.post("/hr/advances", {
        employee_id: emp.id,
        amount: f.amount,
        installments_count: Number(f.count || "1"),
        start_year: Number(f.y),
        start_month: Number(f.m),
        notes: f.notes.trim() || null,
      });
      setF({ ...f, amount: "", notes: "" });
      list.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const ADV_STATUS: Record<HrAdvance["status"], string> = { active: t("نشطة"), completed: t("مسددة"), cancelled: t("ملغاة") };

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <details style={{ marginBottom: 12 }}>
        <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: 13 }}>🔐 {t("حدود الموافقة على السلف")}</summary>
        <form onSubmit={saveLimit} className="toolbar page-actions" style={{ marginTop: 8, alignItems: "flex-end" }}>
          <Field label={t("المستخدم (مدير)")}>
            <select value={limitUser} onChange={(e) => setLimitUser(e.target.value)}>
              <option value="">— {t("اختر")} —</option>
              {limitUsers.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
            </select>
          </Field>
          <Field label={t("الحد الأقصى (فارغ = إلغاء الحد)")}>
            <input type="number" min="0" step="0.01" value={limitAmount} onChange={(e) => setLimitAmount(e.target.value)} />
          </Field>
          <button type="submit" className="btn btn-sm" disabled={busy || !limitUser}>{t("حفظ الحد")}</button>
          {limitMsg && <small className="hint">{limitMsg}</small>}
        </form>
        {limits.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>{t("المستخدم")}</th><th className="num">{t("الحد الأقصى")}</th><th /></tr></thead>
              <tbody>
                {limits.map((l) => (
                  <tr key={l.user_id}>
                    <td>{l.username}</td>
                    <td className="num">{num(l.max_amount)}</td>
                    <td><button type="button" className="btn-delete" onClick={() => void removeLimit(l.user_id)}>{t("إلغاء الحد")}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <small className="hint">{t("ما يتجاوز حد أي مدير يُرفض تلقائيًا عند إنشاء السلفة — مدير المنصة ودور admin يتجاوزان.")}</small>
      </details>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>💳 {t("سلف الموظفين")}</h2>
        <span className="muted" style={{ fontSize: 13 }}>{t("تُخصم أقساطها آلياً في قسائم المسير داخل نطاقها — الحذف مقفل بعد أول قسط")}</span>
      </div>
      <div style={{ padding: "10px 14px" }}>
        <div style={{ minWidth: 240, maxWidth: 420 }}>
          <Lookup<HrEmployee>
            path="/hr/employees"
            value={emp}
            onChange={setEmp}
            label={(x) => `${x.full_name} (${x.code})`}
            placeholder={t("اختر موظفاً…")}
          />
        </div>
        {emp && (
          <form onSubmit={submit} style={{ margin: "10px 0" }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
              <Field label={t("المبلغ*")}>
                <input dir="ltr" inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value.replace(/[^0-9.]/g, "") })} required />
              </Field>
              <Field label={t("عدد الأقساط*")}>
                <input dir="ltr" inputMode="numeric" value={f.count} onChange={(e) => setF({ ...f, count: e.target.value.replace(/[^0-9]/g, "") })} required />
              </Field>
              <Field label={t("يبدأ السداد من*")}>
                <div style={{ display: "flex", gap: 6 }}>
                  <select value={f.m} onChange={(e) => setF({ ...f, m: Number(e.target.value) })}>
                    {MONTH_NAMES.map((m, i) => (<option key={m} value={i + 1}>{m}</option>))}
                  </select>
                  <input dir="ltr" type="number" min={2000} max={2999} value={f.y} onChange={(e) => setF({ ...f, y: Number(e.target.value) })} style={{ width: 76 }} />
                </div>
              </Field>
              <button className="btn btn-primary" disabled={busy}>{t("+ تسجيل سلفة")}</button>
            </div>
          </form>
        )}
        <div className="table-wrap">
          {(list.data ?? []).length > 0 ? (
            <table>
              <thead>
                <tr><th>{t("الموظف")}</th><th className="num">{t("المبلغ")}</th><th className="num">{t("أقساط")}</th><th>{t("تبدأ")}</th><th>{t("الحالة")}</th><th /></tr>
              </thead>
              <tbody>
                {(list.data ?? []).map((a) => (
                  <tr key={a.id}>
                    <td>{a.employee_name} <span className="muted">({a.employee_code})</span></td>
                    <td className="num">{money(a.amount)}</td>
                    <td className="num">{a.installments_count}</td>
                    <td dir="ltr">{MONTH_NAMES[a.start_month - 1]} {a.start_year}</td>
                    <td><span className={`badge ${a.status === "active" ? "badge-draft" : "badge-off"}`}>{ADV_STATUS[a.status]}</span></td>
                    <td className="actions">
                      {a.status === "active" && (
                        <>
                          <button className="btn btn-sm" onClick={async () => { try { await api.patch(`/hr/advances/${a.id}`, { status: "completed" }); list.reload(); } catch (err) { setError((err as Error).message); } }}>{t("مسددة")}</button>{" "}
                          <button className="btn btn-sm" onClick={async () => { try { await api.patch(`/hr/advances/${a.id}`, { status: "cancelled" }); list.reload(); } catch (err) { setError((err as Error).message); } }}>{t("إلغاء")}</button>{" "}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("لا سلف مسجلة.")}</Empty>
          )}
        </div>
      </div>
    </div>
  );
}

/** التسويات النهائية: EOSB + رصيد إجازات مدفوعة − سلف متبقية. */
function SettlementsCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const [note, setNoteInternal] = useState<string | null>(null);
  const list = useFetch(() => api.get<HrSettlement[]>("/hr/settlements"), "hr-settlements");
  const [emp, setEmp] = useState<HrEmployee | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!emp) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/hr/employees/${emp.id}/settlement`, { note: null });
      setNoteInternal(t("تم إنشاء التسوية النهائية."));
      list.reload();
      setEmp(null);
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>🧾 {t("التسويات النهائية (EOSB)")}</h2>
        <span className="muted" style={{ fontSize: 13 }}>{`21 ${t("يوم لكل سنة من أول 5 سنوات ثم 30 — تُنشأ بعد إنهاء الخدمة، سجل واحد لكل موظف")}`}</span>
      </div>
      <div style={{ padding: "10px 14px" }}>
        {note && <p style={{ fontSize: 13, color: "var(--ok)", margin: "0 0 8px" }}>{note}</p>}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 12, minWidth: 240 }}>
          <div style={{ minWidth: 240 }}>
            <Lookup<HrEmployee>
              path="/hr/employees?employee_status=terminated"
              value={emp}
              onChange={setEmp}
              label={(x) => `${x.full_name} (${x.code})`}
              placeholder={t("اختر موظفاً منتهاً للخدمة…")}
            />
          </div>
          <button className="btn btn-primary" disabled={busy || !emp} onClick={() => void create()}>⚖️ {t("احسب التسوية")}</button>
        </div>
        <div className="table-wrap">
          {(list.data ?? []).length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>{t("الموظف")}</th>
                  <th>{t("تاريخ الإنهاء")}</th>
                  <th className="num">{t("سنوات الخدمة")}</th>
                  <th className="num">EOSB</th>
                  <th className="num">{t("إجازات متبقية")}</th>
                  <th className="num">{t("سلف متبقية")}</th>
                  <th className="num">{t("الإجمالي")}</th>
                </tr>
              </thead>
              <tbody>
                {(list.data ?? []).map((s) => (
                  <tr key={s.id}>
                    <td><strong>{s.employee_name}</strong> <span className="muted">({s.employee_code})</span></td>
                    <td>{s.termination_date}</td>
                    <td className="num">{s.service_years}</td>
                    <td className="num">{money(s.eosb_amount)} <span className="muted">({s.eosb_days} {t("يوم")})</span></td>
                    <td className="num">{s.unused_leave_amount !== "0.00" ? money(s.unused_leave_amount) : "—"}</td>
                    <td className="num" style={{ color: s.advances_remaining !== "0.00" ? "var(--danger)" : undefined }}>{s.advances_remaining !== "0.00" ? money(s.advances_remaining) : "—"}</td>
                    <td className="num" style={{ fontWeight: 700 }}>{money(s.total_due)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("لا تسويات نهائية بعد.")}</Empty>
          )}
        </div>
      </div>
    </div>
  );
}

/** صفحة الرواتب: مسيرات شهرية — توليد آلي من الحضور والإجازات + ترحيل محاسبي. */
export function HrPayrollPage() {
  const { t } = useI18n();
  const now = new Date();
  const runs = usePagedList<HrPayrollRun>("/hr/payroll-runs", {});
  const [openNew, setOpenNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [f, setF] = useState({ year: now.getFullYear(), month: now.getMonth() + 1, note: "" });
  const [openRun, setOpenRun] = useState<HrPayrollRun | null>(null);
  const [slips, setSlips] = useState<HrPayslip[] | null>(null);
  const [linesFor, setLinesFor] = useState<HrPayslip | null>(null);

  const loadSlips = (run: HrPayrollRun) => {
    setOpenRun(run);
    setSlips(null);
    api
      .get<HrPayslip[]>(`/hr/payroll-runs/${run.id}/payslips`)
      .then(setSlips)
      .catch((e: Error) => { setError(e.message); setSlips([]); });
  };

  const createRun = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const run = await api.post<HrPayrollRun>("/hr/payroll-runs", { year: Number(f.year), month: Number(f.month), note: f.note.trim() || null });
      setOpenNew(false);
      setNote(t(`تم توليد مسير ${MONTH_NAMES[run.month - 1]} ${run.year} كمسودّة بموظف ${run.employees_count}.`));
      runs.reload();
      loadSlips(run);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const recalc = async (run: HrPayrollRun) => {
    setBusy(true);
    setError(null);
    try {
      const fresh = await api.post<HrPayrollRun>(`/hr/payroll-runs/${run.id}/recalculate`, {});
      setNote(t("أعيد توليد القسائم ببيانات الحضور والإجازات الحالية."));
      runs.reload();
      loadSlips(fresh);
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const del = async (run: HrPayrollRun) => {
    setBusy(true);
    setError(null);
    try {
      await api.del(`/hr/payroll-runs/${run.id}`);
      setNote(t("تم حذف المسير."));
      if (openRun?.id === run.id) { setOpenRun(null); setSlips(null); }
      runs.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const post = async (run: HrPayrollRun) => {
    setBusy(true);
    setError(null);
    try {
      const fresh = await api.post<HrPayrollRun>(`/hr/payroll-runs/${run.id}/post`, { note: null });
      setNote(t(`تم ترحيل المسير وإنشاء قيد محاسبي #${fresh.journal_entry_id}.`));
      runs.reload();
      loadSlips(fresh);
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title={t("الرواتب")} />
      <Alert>{error}</Alert>
      {note && (
        <div style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg)", color: "var(--ok)" }}>
          {note}
        </div>
      )}

      <div className="toolbar" style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <button className="btn btn-primary" onClick={() => { setError(null); setF({ year: now.getFullYear(), month: now.getMonth() + 1, note: "" }); setOpenNew(true); }}>
          {"+ "}{t("مسير شهري جديد")}
        </button>
      </div>

      <div className="card table-wrap">
        {runs.loading && !runs.data ? (
          <Loading />
        ) : (runs.data ?? []).length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("الشهر")}</th>
                <th className="num">{t("موظفون")}</th>
                <th className="num">{t("الإجمالي")}</th>
                <th className="num">{t("الخصومات")}</th>
                <th className="num">{t("الصافي")}</th>
                <th>{t("الحالة")}</th>
                <th>{t("تم الترحيل")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(runs.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td><strong dir="ltr">{MONTH_NAMES[r.month - 1]} {r.year}</strong></td>
                  <td className="num">{r.employees_count}</td>
                  <td className="num">{money(r.total_gross)}</td>
                  <td className="num" style={{ color: r.total_deductions !== "0.00" ? "var(--danger)" : undefined }}>{money(r.total_deductions)}</td>
                  <td className="num" style={{ fontWeight: 700 }}>{money(r.total_net)}</td>
                  <td>{slipBadge(r.status, t)}</td>
                  <td>{r.posted_at ? dateTime(r.posted_at) : "—"}</td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => loadSlips(r)}>{t("تفاصيل")}</button>{" "}
                    {r.status === "draft" && (
                      <>
                        <button className="btn btn-sm" disabled={busy} onClick={() => void recalc(r)}>{t("إعادة حساب")}</button>{" "}
                        <button className="btn btn-sm" disabled={busy} style={{ color: "#15803d", borderColor: "#15803d" }} onClick={() => void post(r)}>⇪ {t("ترحيل")}</button>{" "}
                        <button className="btn-delete" disabled={busy} onClick={() => void del(r)}>{t("حذف")}</button>
                      </>
                    )}
                    {r.status === "posted" && (
                      <>
                        <button
                          className="btn btn-sm"
                          style={{ color: "var(--accent)", borderColor: "var(--accent)" }}
                          onClick={() => { try { void api.download(`/hr/payroll-runs/${r.id}/wps.csv`, `wps-${r.year}-${String(r.month).padStart(2, "0")}.csv`); } catch (err) { setError((err as Error).message); } }}
                        >
                          ⤓ {t("ملف WPS")}
                        </button>
                        <button className="btn btn-sm" onClick={() => { try { void api.download(`/hr/payroll-runs/${r.id}/form-6h.xlsx`, `form6h-${r.year}-${String(r.month).padStart(2, "0")}.xlsx`); } catch (err) { setError((err as Error).message); } }}>
                          📄 6ح
                        </button>
                        <button className="btn btn-sm" onClick={() => { try { void api.download(`/hr/payroll-runs/${r.id}/form-4.xlsx`, `form4-${r.year}-${String(r.month).padStart(2, "0")}.xlsx`); } catch (err) { setError((err as Error).message); } }}>
                          📄 إقرار ضريبة
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا مسيرات بعد — أنشئ مسير الشهر الحالي أو السابق.")}</Empty>
        )}
      </div>
      <Pager list={runs} />

      {openRun && (
        <Modal
          title={`${t("قسائم")} — ${MONTH_NAMES[openRun.month - 1]} ${openRun.year} ${openRun.status === "posted" ? `(${t("مُرحَّل")})` : ""}`}
          onClose={() => { setOpenRun(null); setSlips(null); }}
          wide
        >
          <div className="table-wrap">
            {slips === null ? (
              <Loading />
            ) : slips.length > 0 ? (
              <table>
                <thead>
                  <tr>
                    <th>{t("الموظف")}</th>
                    <th className="num">{t("الأساسي")}</th>
                    <th className="num">{t("غياب")}</th>
                    <th className="num">{t("خصم الغياب")}</th>
                    <th className="num">{t("استحقاقات")}</th>
                    <th className="num">{t("خصومات")}</th>
                    <th className="num">{t("الصافي")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {slips.map((s) => (
                    <tr key={s.id}>
                      <td><strong>{s.employee_name}</strong> <span className="muted">({s.employee_code})</span></td>
                      <td className="num">{money(s.base_salary)}</td>
                      <td className="num">{s.absent_days || "—"}</td>
                      <td className="num">{s.absence_deduction !== "0.00" ? money(s.absence_deduction) : "—"}</td>
                      <td className="num">{s.total_earnings !== "0.00" ? money(s.total_earnings) : "—"}</td>
                      <td className="num" style={{ color: s.total_deductions !== "0.00" ? "var(--danger)" : undefined }}>{s.total_deductions !== "0.00" ? money(s.total_deductions) : "—"}</td>
                      <td className="num" style={{ fontWeight: 700 }}>{money(s.net_pay)}</td>
                      <td className="actions">
                        <button className="btn btn-sm" onClick={() => setLinesFor(s)}>{t("البنود")}</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>{t("المسير بلا قسائم (لا موظف براتب معروف).")}</Empty>
            )}
          </div>
        </Modal>
      )}

      {linesFor && <PayslipLinesModal slip={linesFor} onClose={() => setLinesFor(null)} />}

      {openNew && (
        <Modal title={t("مسير شهري جديد")} onClose={() => setOpenNew(false)}>
          <form onSubmit={createRun}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label={t("السنة*")}>
                <input dir="ltr" type="number" min={2000} max={2999} value={f.year} onChange={(e) => setF({ ...f, year: Number(e.target.value) })} required />
              </Field>
              <Field label={t("الشهر*")}>
                <select value={f.month} onChange={(e) => setF({ ...f, month: Number(e.target.value) })}>
                  {MONTH_NAMES.map((m, i) => (<option key={m} value={i + 1}>{m}</option>))}
                </select>
              </Field>
              <Field label={t("ملاحظة")}>
                <input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
              </Field>
            </div>
            <p className="muted" style={{ fontSize: 13 }}>{t("سيُولَّد تلقائياً: الأساسي + المكونات − خصم الغياب والإجازات غير المدفوعة — لكل موظف نشط براتب معروف.")}</p>
            <div className="form-actions" style={{ marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy}>{busy ? t("جارٍ التوليد…") : t("توليد المسير")}</button>
              <button type="button" className="btn" onClick={() => setOpenNew(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      <SalaryComponentsCard setError={setError} />
      <AdvancesCard setError={setError} />
      <SettlementsCard setError={setError} />
    </>
  );
}

// =====================================================================
// S5 — الخدمة الذاتية للموظف (متاحة لكل مستخدم مرتبط بملف موظف)
// =====================================================================

const CORR_STATUS: Record<HrAttendanceCorrection["status"], string> = {
  pending: "معلّق",
  approved: "معتمد",
  rejected: "مرفوض",
};

 /** بطاقة الطلبات الذاتية: إنشاء إجازة + مطالبة تصحيح + متابعة الحالة. */
function SelfServiceRequestsCard({
  setError, types,
}: {
  setError: (e: string | null) => void;
  types: Fetched<HrLeaveType[]>;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [f, setF] = useState({ type_id: "", from: "", to: "", reason: "" });
  const [corr, setCorr] = useState({ date: "", in: "", out: "", reason: "" });
  const corrections = useFetch(() => api.get<HrAttendanceCorrection[]>("/hr/me/attendance-corrections"), "me-corr");
  const requests = useFetch(() => api.get<HrLeaveRequest[]>("/hr/me/leave-requests"), "me-req");

  const submitLeave = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/hr/me/leave-requests", {
        leave_type_id: Number(f.type_id),
        from_date: f.from,
        to_date: f.to,
        reason: f.reason.trim() || null,
      });
      setF({ type_id: "", from: "", to: "", reason: "" });
      setNote(t("أُرسل طلب الإجازة بانتظار موافقة المدير."));
      requests.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const submitCorrection = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/hr/me/attendance-corrections", {
        work_date: corr.date,
        requested_check_in: corr.in || null,
        requested_check_out: corr.out || null,
        reason: corr.reason.trim(),
      });
      setCorr({ date: "", in: "", out: "", reason: "" });
      setNote(t("أُرسل طلب تصحيح الحضور بانتظار الاعتماد."));
      corrections.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>📨 {t("طلباتي الذاتية")}</h2>
      </div>
      <div style={{ padding: "10px 14px" }}>
        {note && <Alert kind="info">{note}</Alert>}
        <form onSubmit={submitLeave} style={{ marginBottom: 8 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field label={t("نوع الإجازة*")}>
            <select value={f.type_id} onChange={(e) => setF({ ...f, type_id: e.target.value })} required>
              <option value="">—</option>
              {(types.data ?? []).map((tp) => (
                <option key={tp.id} value={tp.id}>{tp.name} ({tp.days_per_year} {t("يوم/سنة")})</option>
              ))}
            </select>
          </Field>
          <Field label={t("من*")}>
            <input type="date" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} required />
          </Field>
          <Field label={t("إلى*")}>
            <input type="date" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} required />
          </Field>
          <Field label={t("السبب")}>
            <input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
          </Field>
          <button className="btn btn-primary" disabled={busy || !f.type_id || !f.from || !f.to}>{t("+ طلب إجازة")}</button>
        </div>
      </form>
      <form onSubmit={submitCorrection} style={{ marginBottom: 14 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field label={t("تصحيح حضور: اليوم*")}>
            <input type="date" value={corr.date} onChange={(e) => setCorr({ ...corr, date: e.target.value })} required />
          </Field>
          <Field label={t("دخول")}>
            <input dir="ltr" pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$" value={corr.in} onChange={(e) => setCorr({ ...corr, in: e.target.value })} placeholder="09:00" />
          </Field>
          <Field label={t("خروج")}>
            <input dir="ltr" pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$" value={corr.out} onChange={(e) => setCorr({ ...corr, out: e.target.value })} placeholder="17:00" />
          </Field>
          <Field label={t("السبب (5+ حرف)*")}>
            <input value={corr.reason} onChange={(e) => setCorr({ ...corr, reason: e.target.value })} required minLength={5} />
          </Field>
          <button className="btn" disabled={busy || !corr.date || (!corr.in && !corr.out)}>🔧 {t("طلب تصحيح")}</button>
        </div>
      </form>

        <div className="table-wrap">
          {((corrections.data ?? []).length > 0 || (requests.data ?? []).length > 0) ? (
            <table>
              <thead>
                <tr><th>{t("النوع")}</th><th>{t("الفترة/اليوم")}</th><th className="num">{t("الأيام")}</th><th>{t("الحالة")}</th><th>{t("السبب/القرار")}</th></tr>
              </thead>
              <tbody>
                {(requests.data ?? []).map((r) => (
                  <tr key={`L${r.id}`}>
                    <td>🏖 {r.leave_type_name}</td>
                    <td dir="ltr">{r.from_date} → {r.to_date}</td>
                    <td className="num">{r.days}</td>
                    <td><span className={`badge ${r.status === "approved" ? "badge-confirmed" : r.status === "pending" ? "badge-draft" : "badge-off"}`}>{t(r.status)}</span></td>
                    <td>{r.reason ?? r.decision_note ?? "—"}</td>
                  </tr>
                ))}
                {(corrections.data ?? []).map((c) => (
                  <tr key={`C${c.id}`}>
                    <td>🔧 {t("تصحيح حضور")}</td>
                    <td dir="ltr">{c.work_date} {c.requested_check_in ?? ""}{c.requested_check_out ? ` → ${c.requested_check_out}` : ""}</td>
                    <td className="num">—</td>
                    <td><span className={`badge ${c.status === "approved" ? "badge-confirmed" : c.status === "pending" ? "badge-draft" : "badge-off"}`}>{CORR_STATUS[c.status]}</span></td>
                    <td>{c.reason}{c.decision_note ? ` — ${c.decision_note}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("لا طلبات بعد — استخدم النماذج أعلاه.")}</Empty>
          )}
        </div>
      </div>
    </div>
  );
}

/** صفحة بوابة الموظف (ESS) — متاحة لكل مستخدم مرتبط بملف موظف. */
export function HrSelfService() {
  const { t } = useI18n();
  const year = new Date().getFullYear();
  const [callErr, setCallErr] = useState<string | null>(null);

  const profile = useFetch(() => api.get<HrMeProfile>("/hr/me").catch(() => {
    return Promise.reject(new Error("NOT_LINKED"));
  }), "ess-me");

  const balances = useFetch(() => api.get<HrLeaveBalance[]>("/hr/me/leave-balances"), "ess-bal");
  const mySlips = useFetch(() => api.get<HrMePayslip[]>("/hr/me/payslips"), "ess-slips");
  const myAttendance = useFetch(() => api.get<HrAttendance[]>(`/hr/me/attendance?year=${year}&limit=200`), `ess-att-${year}`);
  const types = useFetch(() => api.get<HrLeaveType[]>("/hr/leave-types?active_only=true"), "ess-types");

  const POStat = (c: HrAttendance["status"]) => (
    <span className={`badge ${c === "present" ? "badge-confirmed" : c === "late" ? "badge-draft" : "badge-off"}`}>{ATT_STATUS[c]}</span>
  );

  if (profile.error === "NOT_LINKED" || (profile.error ?? "").includes("غير مرتبط")) {
    return (
      <>
        <PageHeader title={t("خدمة الموظف — حسابي")} />
        <div className="card" style={{ padding: "24px", textAlign: "center" }}>
          <p style={{ fontSize: 16, marginBottom: 8 }}>🔒 {t("حسابك غير مرتبط بملف موظف")}</p>
          <p className="muted">{t("اطلب من إدارة الموارد البشرية ربط حسابك بملفك الوظيفي، وستظهر هنا أرصدتك وحضورك وطلباتك ذاتية.")}</p>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader title={t("خدمة الموظف — حسابي")} />
      {callErr && <Alert>{callErr}</Alert>}

      <div className="card" style={{ marginBottom: 14, padding: "12px 16px" }}>
        {profile.loading ? (
          <Loading />
        ) : profile.data ? (
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
            <strong style={{ fontSize: 17 }}>{profile.data.full_name}</strong>
            <span className="muted" style={{ fontSize: 13 }}>({profile.data.code})</span>
            {profile.data.department_name && <span>🏢 {t("الإدارة")}: <strong>{profile.data.department_name}</strong></span>}
            {profile.data.job_title_name && <span>💼 {t("المسمى")}: <strong>{profile.data.job_title_name}</strong></span>}
            {profile.data.manager_name && <span>👤 {t("المدير")}: <strong>{profile.data.manager_name}</strong></span>}
            <span style={{ marginInlineStart: "auto" }} dir="ltr"><em>{profile.data.hire_date}</em></span>
          </div>
        ) : null}
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>🏖 {t("أرصدة إجازاتي")}</h2>
        </div>
        <div className="table-wrap">
          {(balances.data ?? []).length > 0 ? (
            <table>
              <thead>
                <tr><th>{t("النوع")}</th><th className="num">{t("المستحق")}</th><th className="num">{t("المستخدم")}</th><th className="num">{t("المتبقي")}</th></tr>
              </thead>
              <tbody>
                {(balances.data ?? []).map((b) => (
                  <tr key={b.id}>
                    <td>{b.leave_type_name}</td>
                    <td className="num">{b.entitled_days}</td>
                    <td className="num" style={{ color: b.used_days !== "0.0" ? "var(--danger)" : undefined }}>{b.used_days}</td>
                    <td className="num" style={{ fontWeight: 700 }}>{b.remaining_days}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("لا أرصدة بعد.")}</Empty>
          )}
        </div>
      </div>

      <SelfServiceRequestsCard setError={setCallErr} types={types} />

      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>⏱ {t(`حضوري — سنة ${year}`)}</h2>
        </div>
        <div className="table-wrap" style={{ maxHeight: 320, overflow: "auto" }}>
          {(myAttendance.data ?? []).length > 0 ? (
            <table>
              <thead>
                <tr><th>{t("اليوم")}</th><th>{t("الدخول")}</th><th>{t("الخروج")}</th><th className="num">{t("تأخير")}</th><th className="num">{t("إضافي")}</th><th>{t("الحالة")}</th></tr>
              </thead>
              <tbody>
                {(myAttendance.data ?? []).map((a) => (
                  <tr key={a.id}>
                    <td>{a.work_date}</td>
                    <td dir="ltr">{a.check_in ?? "—"}</td>
                    <td dir="ltr">{a.check_out ?? "—"}</td>
                    <td className="num">{a.late_minutes || "—"}</td>
                    <td className="num">{a.overtime_minutes || "—"}</td>
                    <td>{POStat(a.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("لا سجلات حضور لهذه السنة.")}</Empty>
          )}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>💰 {t("قسائم رواتبي (المُرحّلة)")}</h2>
        </div>
        <div className="table-wrap">
          {(mySlips.data ?? []).length > 0 ? (
            <table>
              <thead>
                <tr><th>{t("الفترة")}</th><th className="num">{t("الأساسي")}</th><th className="num">{t("استحقاقات")}</th><th className="num">{t("خصومات")}</th><th className="num">{t("الصافي")}</th><th>{t("الحالة")}</th></tr>
              </thead>
              <tbody>
                {(mySlips.data ?? []).map((s) => (
                  <tr key={s.id}>
                    <td dir="ltr">{MONTH_NAMES[s.month - 1]} {s.year}</td>
                    <td className="num">{money(s.base_salary)}</td>
                    <td className="num">{s.total_earnings !== "0.00" ? money(s.total_earnings) : "—"}</td>
                    <td className="num" style={{ color: s.total_deductions !== "0.00" ? "var(--danger)" : undefined }}>{s.total_deductions !== "0.00" ? money(s.total_deductions) : "—"}</td>
                    <td className="num" style={{ fontWeight: 700 }}>{money(s.net_pay)}</td>
                    <td><span className={`badge ${s.run_status === "posted" ? "badge-confirmed" : "badge-draft"}`}>{s.run_status === "posted" ? t("مُرحَّل") : t("مسودّة")}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("لا قسائم بعد — تظهر بعد ترحيل أول مسير.")}</Empty>
          )}
        </div>
      </div>
    </>
  );
}

// =====================================================================
// S6 — التوظيف (ATS) والأداء والتدريب + لوحة HR التحليلية
// =====================================================================

const STAGE_LITERAL: Record<ApplicantStage, string> = {
  applied: "تقدم بطلب",
  screening: "فرز",
  interview: "مقابلة",
  offer: "عرض عمل",
  hired: "تم التعيين",
  rejected: "مرفوض",
};

const POSTING_STATUS: Record<HrJobPosting["status"], string> = {
  open: "مفتوح",
  on_hold: "معلّق",
  closed: "مغلق",
  filled: "اكتمل",
};

const EMP_TYPE: Record<string, string> = {
  full_time: "دوام كامل",
  part_time: "دوام جزئي",
  contract: "عقد مؤقت",
  internship: "تدريب مهني",
};

const ENROLL_STATUS: Record<HrEnrollment["status"], string> = {
  enrolled: "مسجَّل",
  completed: "أتمّ الدورة",
  no_show: "لم يحضر",
};

/** بطاقة KPI صغيرة للوحة التحليلية. */
function Kpi({ title, value, hint, tone }: { title: string; value: string; hint?: string; tone?: "good" | "warn" | "off" }) {
  const color = tone === "good" ? "#15803d" : tone === "warn" ? "#b45309" : tone === "off" ? "var(--danger)" : undefined;
  return (
    <div className="card" style={{ padding: "10px 14px", marginInlineEnd: 10, marginBottom: 10, flex: "1 1 150px" }}>
      <div className="muted" style={{ fontSize: 12 }}>{title}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color }} dir="ltr">{value}</div>
      {hint && <div className="muted" style={{ fontSize: 11 }}>{hint}</div>}
    </div>
  );
}

/** لوحة HR التحليلية — أعلى صفحة التوظيف والمواهب. */
function AnalyticsStrip({ refreshKey }: { refreshKey: number }) {
  const { t } = useI18n();
  const list = useFetch(() => api.get<HrAnalytics>("/hr/analytics"), `hr-analytics-${refreshKey}`);
  if (list.error) return <Alert>{list.error}</Alert>;
  if (list.loading) return <Loading />;
  const d = list.data;
  if (!d) return null;
  const stages = d.recruiting.applicants_by_stage;
  return (
    <div style={{ marginBottom: 14 }}>
      <div className="card" style={{ padding: "10px 14px", marginBottom: 10 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>📊 {t("لوحة HR التحليلية")}</h2>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap" }}>
        <Kpi title={t("نسبة الحضور (الشهر)")} value={`${d.attendance.attendance_rate}%`} tone={d.attendance.attendance_rate >= 90 ? "good" : d.attendance.attendance_rate >= 70 ? "warn" : "off"} hint={`${d.attendance.records} ${t("سجل")}`} />
        <Kpi title={t("متأخرات الشهر")} value={String(d.attendance.late)} hint={`${d.attendance.absent} ${t("غياب")}`} />
        <Kpi title={t("قيد الموافقة")} value={String(d.leaves.pending_requests)} hint={`${d.leaves.approved_days_this_year} ${t("يوم معتمد هذا العام")}`} />
        <Kpi title={t("دوران العمالة")} value={`${d.turnover.rate}%`} tone={d.turnover.rate > 15 ? "off" : "good"} hint={`${d.turnover.terminated} / ${d.turnover.headcount}`} />
        <Kpi title={t("صافي آخر مسير")} value={d.payroll.last_run_period ?? "—"} hint={`${d.payroll.slips} ${t("قسيمة")} · ${money(d.payroll.net_total)}`} />
        <Kpi title={t("سلف نشطة (متبقٍ)")} value={String(d.payroll.advances_active)} hint={money(d.payroll.advances_outstanding)} />
        <Kpi title={t("إعلانات مفتوحة")} value={String(d.recruiting.open_postings)} hint={Object.entries(stages).map(([s, c]) => `${STAGE_LITERAL[s as ApplicantStage] ?? s}: ${c}`).join(" · ") || "—"} />
        <Kpi title={t("متوسط الأداء")} value={d.talent.avg_score != null ? `${d.talent.avg_score}/5` : "—"} tone={d.talent.avg_score != null && d.talent.avg_score >= 4 ? "good" : undefined} hint={`${d.talent.trainings} ${t("دورة تدريب")}`} />
      </div>
    </div>
  );
}

/** بطاقة التوظيف: إعلانات + متقدمون بتدرج المراحل + تعيين. */
function RecruitingCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const postings = usePagedList<HrJobPosting>("/hr/job-postings", { posting_status: "" });
  const [postingFilter, setPostingFilter] = useState<string>("");
  const applicants = usePagedList<HrApplicant>("/hr/applicants", { posting_id: postingFilter || null });
  const [openPosting, setOpenPosting] = useState(false);
  const [openApplicant, setOpenApplicant] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const [pf, setPf] = useState({ title: "", openings: "1", dept: "", desc: "" });
  const [af, setAf] = useState({ posting: "", name: "", email: "", phone: "", source: "" });

  const departments = useFetch(() => api.get<Department[]>("/departments"), "hr6-depts");
  const [busy, setBusy] = useState(false);

  const submitPosting = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.post("/hr/job-postings", {
        title: pf.title.trim(),
        openings: Number(pf.openings) || 1,
        department_id: pf.dept ? Number(pf.dept) : null,
        description: pf.desc.trim() || null,
      });
      setPf({ title: "", openings: "1", dept: "", desc: "" });
      setOpenPosting(false);
      setNote(t("أُنشئ إعلان التوظيف."));
      postings.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const submitApplicant = async (e: FormEvent) => {
    e.preventDefault();
    const pid = Number(af.posting.split("|")[0]);
    setBusy(true); setError(null);
    try {
      await api.post(`/hr/job-postings/${pid}/applicants`, {
        full_name: af.name.trim(), email: af.email.trim(), phone: af.phone.trim() || null, source: af.source.trim() || null,
      });
      setAf({ posting: "", name: "", email: "", phone: "", source: "" });
      setOpenApplicant(false);
      setNote(t("سُجّل المتقدم في مرحلة «تقدم بطلب»."));
      applicants.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true); setError(null);
    try { await fn(); setNote(msg); applicants.reload(); postings.reload(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)", display: "flex", alignItems: "center", gap: 10 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>🧲 {t("التوظيف (ATS)")}</h2>
        <button className="btn btn-sm btn-primary" style={{ marginInlineStart: "auto" }} onClick={() => setOpenPosting(true)}>{t("+ إعلان وظيفة")}</button>
        <button className="btn btn-sm" onClick={() => setOpenApplicant(true)}>{t("+ تسجيل متقدم")}</button>
      </div>
      {note && <Alert kind="info">{note}</Alert>}
      <div className="table-wrap">
        {postings.data && postings.data.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("الكود")}</th><th>{t("الوظيفة")}</th><th>{t("الإدارة")}</th><th className="num">{t("المناصب")}</th><th>{t("النوع")}</th><th>{t("الحالة")}</th><th>{t("المعيّنان")}</th></tr>
            </thead>
            <tbody>
              {postings.data.map((p) => (
                <tr key={p.id}>
                  <td dir="ltr">{p.code}</td>
                  <td><strong>{p.title}</strong></td>
                  <td>{p.department_name ?? "—"}</td>
                  <td className="num">{p.openings}</td>
                  <td>{EMP_TYPE[p.employment_type] ?? p.employment_type}</td>
                  <td><span className={`badge ${p.status === "open" ? "badge-confirmed" : p.status === "filled" ? "badge-off" : "badge-draft"}`}>{POSTING_STATUS[p.status]}</span></td>
                  <td className="num">{p.hired_count}/{p.openings}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (<Empty>{t("لا إعلانات توظيف بعد.")}</Empty>)}
      </div>

      <div style={{ padding: "8px 14px", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
        <select value={postingFilter} onChange={(e) => setPostingFilter(e.target.value)} style={{ maxWidth: 320 }}>
          <option value="">{t("كل المتقدمين (كل الإعلانات)")}</option>
          {(postings.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>{p.code} — {p.title}</option>
          ))}
        </select>
      </div>
      <div className="table-wrap">
        {applicants.data && applicants.data.length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("الاسم")}</th><th>{t("الإعلان")}</th><th dir="ltr">{t("البريد")}</th><th>{t("المرحلة")}</th><th>{t("المصدر")}</th><th /></tr>
            </thead>
            <tbody>
              {applicants.data.map((a) => (
                <tr key={a.id}>
                  <td><strong>{a.full_name}</strong></td>
                  <td className="muted" dir="ltr">{a.posting_code}</td>
                  <td dir="ltr">{a.email}</td>
                  <td>
                    <span className={`badge ${a.stage === "hired" ? "badge-confirmed" : a.stage === "rejected" ? "badge-off" : "badge-draft"}`}>{STAGE_LITERAL[a.stage]}</span>
                  </td>
                  <td>{a.source ?? "—"}</td>
                  <td className="actions">
                    {!["hired", "rejected"].includes(a.stage) && (
                      <>
                        <button className="btn btn-sm" disabled={busy} onClick={() => void act(() => api.post(`/hr/applicants/${a.id}/advance`, {}), t("تدرّج المتقدم للمرحلة التالية."))}>→ {t("تدرّج")}</button>{" "}
                        <button className="btn btn-sm" disabled={busy} style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => void act(() => api.post(`/hr/applicants/${a.id}/reject`, {}), t("رُفض المتقدم."))}>{t("رفض")}</button>
                      </>
                    )}
                    {a.stage === "offer" && (
                      <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => void act(() => api.post(`/hr/applicants/${a.id}/hire`, {}), t("تم التعيين وإنشاء ملف الموظف."))}>✓ {t("تعيين")}</button>
                    )}
                    {a.stage === "hired" && a.hired_employee_id && (
                      <span className="muted">#{a.hired_employee_id}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (<Empty>{t("لا متقدمين بعد.")}</Empty>)}
      </div>
      <Pager list={applicants} />

      {openPosting && (
        <Modal title={t("إعلان وظيفة جديد")} onClose={() => setOpenPosting(false)}>
          <form onSubmit={submitPosting}>
            <Alert>{null}</Alert>
            <div className="form-grid">
              <Field label={t("المسمى*")}><input value={pf.title} onChange={(e) => setPf({ ...pf, title: e.target.value })} required minLength={3} /></Field>
              <Field label={t("عدد المناصب*")}><input type="number" min={1} max={100} value={pf.openings} onChange={(e) => setPf({ ...pf, openings: e.target.value })} required /></Field>
              <Field label={t("الإدارة")}>
                <select value={pf.dept} onChange={(e) => setPf({ ...pf, dept: e.target.value })}>
                  <option value="">—</option>
                  {(departments.data ?? []).map((d) => (<option key={d.id} value={d.id}>{d.name}</option>))}
                </select>
              </Field>
              <Field label={t("الوصف")}><input value={pf.desc} onChange={(e) => setPf({ ...pf, desc: e.target.value })} /></Field>
            </div>
            <div className="actions" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={busy || !pf.title.trim()}>{t("إنشاء")}</button>
              <button type="button" className="btn" onClick={() => setOpenPosting(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {openApplicant && (
        <Modal title={t("تسجيل متقدم جديد")} onClose={() => setOpenApplicant(false)}>
          <form onSubmit={submitApplicant}>
            <Alert>{null}</Alert>
            <div className="form-grid">
              <Field label={t("الإعلان*")}>
                <select value={af.posting} onChange={(e) => setAf({ ...af, posting: e.target.value })} required>
                  <option value="">—</option>
                  {(postings.data ?? []).filter((p) => p.status === "open").map((p) => (
                    <option key={p.id} value={`${p.id}|${p.title}`}>{p.code} — {p.title}</option>
                  ))}
                </select>
              </Field>
              <Field label={t("الاسم*")}><input value={af.name} onChange={(e) => setAf({ ...af, name: e.target.value })} required minLength={3} /></Field>
              <Field label={t("البريد الإلكتروني*")}><input type="email" dir="ltr" value={af.email} onChange={(e) => setAf({ ...af, email: e.target.value })} required /></Field>
              <Field label={t("الهاتف")}><input dir="ltr" value={af.phone} onChange={(e) => setAf({ ...af, phone: e.target.value })} /></Field>
              <Field label={t("المصدر")}><input value={af.source} onChange={(e) => setAf({ ...af, source: e.target.value })} placeholder="لينكدإن / ترشيح" /></Field>
            </div>
            <div className="actions" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={busy}>{t("تسجيل")}</button>
              <button type="button" className="btn" onClick={() => setOpenApplicant(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

/** بطاقة الأداء: دورات + تقييمات. */
function PerformanceCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const cycles = useFetch(() => api.get<HrReviewCycle[]>("/hr/review-cycles"), "hr6-cycles");
  const [cycleId, setCycleId] = useState<string>("");
  const reviews = useFetch(() => (cycleId ? api.get<HrReview[]>(`/hr/review-cycles/${cycleId}/reviews`) : api.get<HrReview[]>("/hr/performance-reviews")), `hr6-reviews-${cycleId}`);
  const [busy, setBusy] = useState(false);
  const [rf, setRf] = useState({ cycle: "", employee: null as HrEmployee | null, q: "3", c: "3", tw: "3", i: "3", comment: "" });
  const [open, setOpen] = useState(false);

  const ReviewScore = ({ n }: { n: number }) => (
    <span className={`badge ${n >= 4 ? "badge-confirmed" : n >= 3 ? "badge-draft" : "badge-off"}`}>{n}/5</span>
  );

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!rf.employee || !rf.cycle) return;
    setBusy(true); setError(null);
    try {
      await api.post(`/hr/review-cycles/${rf.cycle}/reviews`, {
        employee_id: rf.employee.id, quality: Number(rf.q), commitment: Number(rf.c), teamwork: Number(rf.tw), initiative: Number(rf.i),
        comment: rf.comment.trim() || null,
      });
      setRf({ cycle: "", employee: null, q: "3", c: "3", tw: "3", i: "3", comment: "" });
      setOpen(false);
      reviews.reload(); cycles.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)", display: "flex", alignItems: "center", gap: 10 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>⭐ {t("تقييم الأداء")}</h2>
        <select value={cycleId} onChange={(e) => setCycleId(e.target.value)} className="btn btn-sm" style={{ maxWidth: 260 }}>
          <option value="">{t("كل الدورات")}</option>
          {(cycles.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>{c.name} ({c.status === "open" ? t("مفتوحة") : t("مغلقة")})</option>
          ))}
        </select>
        <button className="btn btn-sm btn-primary" style={{ marginInlineStart: "auto" }} onClick={() => setOpen(true)}>{t("+ دورة تقييم")}</button>
      </div>
      <div className="table-wrap">
        {(reviews.data ?? []).length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("الموظف")}</th><th className="num">{t("الجودة")}</th><th className="num">{t("الالتزام")}</th><th className="num">{t("فريق العمل")}</th><th className="num">{t("المبادرة")}</th><th className="num">{t("المتوسط")}</th><th>{t("الملاحظة")}</th></tr>
            </thead>
            <tbody>
              {(reviews.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td><strong>{r.employee_name}</strong> <span className="muted">({r.employee_code})</span></td>
                  <td className="num"><ReviewScore n={r.quality} /></td>
                  <td className="num"><ReviewScore n={r.commitment} /></td>
                  <td className="num"><ReviewScore n={r.teamwork} /></td>
                  <td className="num"><ReviewScore n={r.initiative} /></td>
                  <td className="num" style={{ fontWeight: 700 }} dir="ltr">{r.score}</td>
                  <td>{r.comment ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (<Empty>{t("لا تقييمات بعد — أنشئ دورة وسجّل تقييماً.")}</Empty>)}
      </div>

      {open && (
        <Modal title={t("دورة تقييم + تقييم موظف")} onClose={() => setOpen(false)} wide>
          <form onSubmit={submit}>
            <Alert>{null}</Alert>
            <div className="form-grid">
              <Field label={t("الدورة*")}>
                <select value={rf.cycle} onChange={(e) => setRf({ ...rf, cycle: e.target.value })} required>
                  <option value="">—</option>
                  {(cycles.data ?? []).filter((c) => c.status === "open").map((c) => (
                    <option key={c.id} value={c.id}>{c.name} ({c.period_start} → {c.period_end})</option>
                  ))}
                </select>
              </Field>
              <Field label={t("الموظف*")}>
                <Lookup<HrEmployee> path="/hr/employees" value={rf.employee} onChange={(v) => setRf({ ...rf, employee: v })} label={(x) => `${x.full_name} (${x.code})`} />
              </Field>
              {(["الجودة", "الالتزام", "فريق العمل", "المبادرة"] as const).map((lbl, idx) => (
                <Field key={lbl} label={`${lbl} (1-5)*`}>
                  <select value={[rf.q, rf.c, rf.tw, rf.i][idx]} onChange={(e) => {
                    const v = e.target.value;
                    setRf(idx === 0 ? { ...rf, q: v } : idx === 1 ? { ...rf, c: v } : idx === 2 ? { ...rf, tw: v } : { ...rf, i: v });
                  }}>
                    {[1, 2, 3, 4, 5].map((n) => (<option key={n} value={n}>{n}</option>))}
                  </select>
                </Field>
              ))}
              <Field label={t("ملاحظة")}><input value={rf.comment} onChange={(e) => setRf({ ...rf, comment: e.target.value })} /></Field>
            </div>
            <div className="actions" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={busy || !rf.cycle || !rf.employee}>{t("حفظ")}</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

/** بطاقة التدريب: دورات + تسجيلات. */
function TrainingCard({ setError }: { setError: (e: string | null) => void }) {
  const { t } = useI18n();
  const trainings = useFetch(() => api.get<HrTraining[]>("/hr/trainings"), "hr6-trainings");
  const [selected, setSelected] = useState<number | null>(null);
  const enrollments = useFetch(() => (selected ? api.get<HrEnrollment[]>(`/hr/trainings/${selected}/enrollments`) : api.get<HrEnrollment[]>("/hr/enrollments")), `hr6-enroll-${selected}`);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [tf, setTf] = useState({ title: "", provider: "", from: "", to: "", cost: "" });
  const [ef, setEf] = useState({ training: "", employee: null as HrEmployee | null });
  const [openEnroll, setOpenEnroll] = useState(false);

  const submitTraining = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.post("/hr/trainings", {
        title: tf.title.trim(), provider: tf.provider.trim() || null,
        from_date: tf.from, to_date: tf.to, cost: tf.cost || "0",
      });
      setTf({ title: "", provider: "", from: "", to: "", cost: "" });
      setOpen(false);
      trainings.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const submitEnroll = async (e: FormEvent) => {
    e.preventDefault();
    if (!ef.employee || !ef.training) return;
    setBusy(true); setError(null);
    try {
      await api.post(`/hr/trainings/${ef.training}/enrollments`, { employee_id: ef.employee.id });
      setEf({ training: "", employee: null });
      setOpenEnroll(false);
      enrollments.reload(); trainings.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); enrollments.reload(); trainings.reload(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #e2e8f0)", display: "flex", alignItems: "center", gap: 10 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>🎓 {t("التدريب والتطوير")}</h2>
        <button className="btn btn-sm btn-primary" style={{ marginInlineStart: "auto" }} onClick={() => setOpen(true)}>{t("+ دورة تدريب")}</button>
        <button className="btn btn-sm" onClick={() => setOpenEnroll(true)}>{t("+ تسجيل موظف")}</button>
      </div>
      <div className="table-wrap">
        {(trainings.data ?? []).length > 0 ? (
          <table>
            <thead>
              <tr><th>{t("الكود")}</th><th>{t("الدورة")}</th><th>{t("المزوّد")}</th><th dir="ltr">{t("الفترة")}</th><th className="num">{t("التكلفة")}</th><th className="num">{t("المسجَّلون")}</th><th /></tr>
            </thead>
            <tbody>
              {(trainings.data ?? []).map((tr) => (
                <tr key={tr.id} style={selected === tr.id ? { background: "var(--hover-bg, rgba(0,0,0,0.03))" } : undefined}>
                  <td dir="ltr">{tr.code}</td>
                  <td>
                    <button className="btn-link" style={{ textDecoration: "underline" }} onClick={() => setSelected(selected === tr.id ? null : tr.id)}>
                      <strong>{tr.title}</strong>
                    </button>
                  </td>
                  <td>{tr.provider ?? "—"}</td>
                  <td dir="ltr">{tr.from_date} → {tr.to_date}</td>
                  <td className="num">{tr.cost !== "0.00" ? money(tr.cost) : "—"}</td>
                  <td className="num">{tr.enrollments_count}</td>
                  <td />
                </tr>
              ))}
            </tbody>
          </table>
        ) : (<Empty>{t("لا دورات تدريبية بعد.")}</Empty>)}
      </div>
      {selected != null && (
        <div className="table-wrap" style={{ borderTop: "1px solid var(--border, #e2e8f0)" }}>
          <table>
            <thead>
              <tr><th>{t("الموظف")}</th><th>{t("الحالة")}</th><th>{t("الشهادة")}</th><th /></tr>
            </thead>
            <tbody>
              {(enrollments.data ?? []).length > 0 ? (enrollments.data ?? []).map((en) => (
                <tr key={en.id}>
                  <td><strong>{en.employee_name}</strong> <span className="muted">({en.employee_code})</span></td>
                  <td><span className={`badge ${en.status === "completed" ? "badge-confirmed" : en.status === "no_show" ? "badge-off" : "badge-draft"}`}>{ENROLL_STATUS[en.status]}</span></td>
                  <td>{en.certificate_note ?? "—"}</td>
                  <td className="actions">
                    {en.status === "enrolled" && (
                      <>
                        <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => void act(() => api.post(`/hr/enrollments/${en.id}/complete`, { certificate_note: null }))}>✓ {t("إتمام")}</button>{" "}
                        <button className="btn btn-sm" disabled={busy} onClick={() => void act(() => api.post(`/hr/enrollments/${en.id}/no-show`, {}))}>{t("لم يحضر")}</button>
                      </>
                    )}
                  </td>
                </tr>
              )) : (<tr><td colSpan={4}><Empty>{t("لا تسجيلات في هذه الدورة.")}</Empty></td></tr>)}
            </tbody>
          </table>
        </div>
      )}

      {open && (
        <Modal title={t("دورة تدريبية جديدة")} onClose={() => setOpen(false)}>
          <form onSubmit={submitTraining}>
            <Alert>{null}</Alert>
            <div className="form-grid">
              <Field label={t("المسمى*")}><input value={tf.title} onChange={(e) => setTf({ ...tf, title: e.target.value })} required minLength={3} /></Field>
              <Field label={t("المزوّد")}><input value={tf.provider} onChange={(e) => setTf({ ...tf, provider: e.target.value })} /></Field>
              <Field label={t("من*")}><input type="date" value={tf.from} onChange={(e) => setTf({ ...tf, from: e.target.value })} required /></Field>
              <Field label={t("إلى*")}><input type="date" value={tf.to} onChange={(e) => setTf({ ...tf, to: e.target.value })} required /></Field>
              <Field label={t("التكلفة")}><input dir="ltr" inputMode="decimal" value={tf.cost} onChange={(e) => setTf({ ...tf, cost: e.target.value.replace(/[^0-9.]/g, "") })} /></Field>
            </div>
            <div className="actions" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={busy || !tf.title.trim() || !tf.from || !tf.to}>{t("إنشاء")}</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {openEnroll && (
        <Modal title={t("تسجيل موظف في دورة")} onClose={() => setOpenEnroll(false)}>
          <form onSubmit={submitEnroll}>
            <Alert>{null}</Alert>
            <div className="form-grid">
              <Field label={t("الدورة*")}>
                <select value={ef.training} onChange={(e) => setEf({ ...ef, training: e.target.value })} required>
                  <option value="">—</option>
                  {(trainings.data ?? []).map((tr) => (<option key={tr.id} value={tr.id}>{tr.code} — {tr.title}</option>))}
                </select>
              </Field>
              <Field label={t("الموظف*")}>
                <Lookup<HrEmployee> path="/hr/employees" value={ef.employee} onChange={(v) => setEf({ ...ef, employee: v })} label={(x) => `${x.full_name} (${x.code})`} />
              </Field>
            </div>
            <div className="actions" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={busy}>{t("تسجيل")}</button>
              <button type="button" className="btn" onClick={() => setOpenEnroll(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

/** صفحة S6: لوحة تحليلية + توظيف + أداء + تدريب (للمدير). */
export function HrTalentPage() {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);

  return (
    <>
      <PageHeader title={t("المواهب: توظيف · أداء · تدريب")} />
      <Alert>{error}</Alert>
      <AnalyticsStrip refreshKey={1} />
      <RecruitingCard setError={setError} />
      <PerformanceCard setError={setError} />
      <TrainingCard setError={setError} />
    </>
  );
}
