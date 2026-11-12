import { useState } from "react";
import { api, qs } from "../api";
import { money } from "../format";
import { useAction, useFetch } from "../hooks";
import { useI18n } from "../i18n";
import { useAuth } from "../auth";
import type { PayrollRunLite, PayrollTaxReport, PayrollTaxSettings, TaxBracket, VatReturn, WithholdingCode, WithholdingReport } from "../types";
import { Alert, Empty, Loading, PageHeader } from "../ui";

/** YYYY-MM-DD بتقويم المتصفح المحلي. */
function isoDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDay(d);
}

/** شريط فترة التقرير (من/إلى + أنماط سريعة). */
function useRange() {
  const [from, setFrom] = useState(isoDay(new Date(new Date().getFullYear(), new Date().getMonth(), 1)));
  const [to, setTo] = useState(isoDay(new Date()));
  const download = useAction();
  const range = qs({ date_from: from, date_to: to });
  const exportFile = (path: string, name: string) => void download.run(() => api.download(path, name));
  const preset = (days: number) => { setFrom(daysAgo(days - 1)); setTo(isoDay(new Date())); };
  const thisMonth = () => {
    const now = new Date();
    setFrom(isoDay(new Date(now.getFullYear(), now.getMonth(), 1)));
    setTo(isoDay(now));
  };
  return { from, setFrom, to, setTo, range, exportFile, download, preset, thisMonth };
}

function RangeBar({ r }: { r: ReturnType<typeof useRange> }) {
  const { t } = useI18n();
  return (
    <div className="card card-pad range-bar">
      <label className="range-field">
        <span className="field-label">{t("من تاريخ")}</span>
        <input type="date" value={r.from} max={r.to || undefined} onChange={(e) => r.setFrom(e.target.value)} />
      </label>
      <label className="range-field">
        <span className="field-label">{t("إلى تاريخ")}</span>
        <input type="date" value={r.to} min={r.from || undefined} onChange={(e) => r.setTo(e.target.value)} />
      </label>
      <div className="range-presets">
        <button className="btn btn-sm" onClick={() => r.preset(30)}>{t("آخر 30 يوماً")}</button>
        <button className="btn btn-sm" onClick={() => r.preset(90)}>{t("آخر 90 يوماً")}</button>
        <button className="btn btn-sm" onClick={r.thisMonth}>{t("هذا الشهر")}</button>
      </div>
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: "ok" | "warn" }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value" style={tone === "warn" ? { color: "var(--danger, #b91c1c)" } : undefined}>{value}</div>
    </div>
  );
}

function ExportButton({ onClick, busy, children }: { onClick: () => void; busy: boolean; children: string }) {
  const { t } = useI18n();
  return (
    <button className="btn btn-primary" disabled={busy} onClick={onClick}>
      {busy ? t("جارٍ التجهيز…") : `⬇ ${children}`}
    </button>
  );
}

function Table({ title, headers, rows }: { title: string; headers: string[]; rows: (string | number)[][] }) {
  const { t } = useI18n();
  return (
    <div className="card card-pad">
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <Empty>{t("لا بيانات")}</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>{headers.map((h, i) => <th key={h + i} className={i === 0 ? undefined : "num"}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>{r.map((c, ci) => <td key={ci} className={ci === 0 ? undefined : "num"}>{c}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Locked({ perm }: { perm: string }) {
  const { t } = useI18n();
  return <Alert>🔒 {t("تحتاج صلاحية")} <code>{perm}</code> {t("لعرض هذا القسم")}</Alert>;
}

// ============================================================ القيمة المضافة
function VatTab({ r }: { r: ReturnType<typeof useRange> }) {
  const { t } = useI18n();
  const [tick, setTick] = useState(0);
  const now = new Date();
  const [vatFormType, setVatFormType] = useState("quarter");
  const [vatFormPeriod, setVatFormPeriod] = useState(Math.floor(now.getMonth() / 3) + 1);
  const [vatFormYear, setVatFormYear] = useState(now.getFullYear());
  const vat = useFetch<VatReturn>(() => api.get<VatReturn>(`/taxes/vat-return${r.range}`), `vat${r.range}${tick}`);
  return (
    <>
      <RangeBar r={r} />
      <Alert>{r.download.error}</Alert>
      {vat.loading && <Loading />}
      {vat.error && <Alert>{vat.error}</Alert>}
      {vat.data && (
        <>
          <div className="grid kpis" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 12, margin: "14px 0" }}>
            <Kpi label={t("ضريبة المخرجات (المبيعات)")} value={money(vat.data.output_vat)} />
            <Kpi label={t("ضريبة المدخلات (المشتريات)")} value={money(vat.data.input_vat)} />
            <Kpi label={t("الصافي المستحق للسداد")} value={money(vat.data.net_payable)} tone={Number(vat.data.net_payable) > 0 ? "warn" : "ok"} />
            <Kpi label={t("وعاء المبيعات الخاضع")} value={money(vat.data.taxable_sales_total)} />
          </div>
          <div className="row" style={{ gap: 8, marginBottom: 14 }}>
            <ExportButton busy={r.download.busy} onClick={() => r.exportFile(`/taxes/vat-return/xlsx${r.range}`, `vat-${r.from}_${r.to}.xlsx`)}>{t("Excel")}</ExportButton>
            <ExportButton busy={r.download.busy} onClick={() => r.exportFile(`/taxes/vat-return/pdf${r.range}`, `vat-${r.from}_${r.to}.pdf`)}>{t("PDF")}</ExportButton>
            <button className="btn" onClick={() => setTick((x) => x + 1)}>↻</button>
          </div>
          <div className="card card-pad" style={{ marginBottom: 14 }}>
            <h3>{t("النموذج الرسمي لمصلحة الضرائب")}</h3>
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              <select value={vatFormType} onChange={(e) => setVatFormType(e.target.value)}>
                <option value="quarter">{t("ربع سنوي")}</option>
                <option value="month">{t("شهري")}</option>
              </select>
              <select value={vatFormPeriod} onChange={(e) => setVatFormPeriod(Number(e.target.value))}>
                {vatFormType === "quarter"
                  ? [1, 2, 3, 4].map((q) => <option key={q} value={q}>{t("الربع")} {q}</option>)
                  : Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{t("شهر")} {m}</option>)}
              </select>
              <input dir="ltr" type="number" min="2015" max="2100" style={{ width: 90 }} value={vatFormYear} onChange={(e) => setVatFormYear(Number(e.target.value))} />
              <ExportButton busy={r.download.busy} onClick={() => r.exportFile(`/taxes/vat-return/form-xlsx?period_type=${vatFormType}&period=${vatFormPeriod}&year=${vatFormYear}`, `vat-form-${vatFormType}${vatFormPeriod}-${vatFormYear}.xlsx`)}>{t("تنزيل النموذج Excel")}</ExportButton>
              <ExportButton busy={r.download.busy} onClick={() => r.exportFile(`/taxes/vat-return/form-pdf?period_type=${vatFormType}&period=${vatFormPeriod}&year=${vatFormYear}`, `vat-form-${vatFormType}${vatFormPeriod}-${vatFormYear}.pdf`)}>{t("تنزيل النموذج PDF")}</ExportButton>
            </div>
          </div>
          <Table
            title={t("تفصيل المبيعات بنسبة الضريبة")}
            headers={[t("النسبة %"), t("عدد الفواتير"), t("الوعاء"), t("الضريبة")]}
            rows={vat.data.sales_by_rate.map((b) => [Number(b.rate).toLocaleString("ar-EG"), b.invoices, money(b.taxable_base), money(b.tax_amount)])}
          />
          <div style={{ height: 12 }} />
          <Table
            title={t("تفصيل شهري (مخرجات − مدخلات)")}
            headers={[t("الشهر"), t("مخرجات"), t("مدخلات"), t("صافي")]}
            rows={vat.data.monthly.map((m) => [m.month, money(m.output_vat), money(m.input_vat), money(m.net)])}
          />
        </>
      )}
    </>
  );
}

// ============================================================ الخصم والإضافة
function WithholdingTab({ r }: { r: ReturnType<typeof useRange> }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const [tick, setTick] = useState(0);
  const now = new Date();
  const [whFormMonth, setWhFormMonth] = useState(now.getMonth() + 1);
  const [whFormYear, setWhFormYear] = useState(now.getFullYear());
  const rep = useFetch<WithholdingReport>(() => api.get<WithholdingReport>(`/taxes/withholding${r.range}`), `wh${r.range}${tick}`);
  const codes = useFetch<WithholdingCode[]>(() => api.get<WithholdingCode[]>("/taxes/withholding/codes?include_inactive=true"), `whc${tick}`);
  const manage = can("taxes.withholding.manage");
  const [newCode, setNewCode] = useState({ name: "", rate: "" });
  const save = useAction();
  const addCode = () =>
    void save.run(async () => {
      await api.post("/taxes/withholding/codes", { name: newCode.name, rate: newCode.rate });
      setNewCode({ name: "", rate: "" });
      setTick((x) => x + 1);
    });
  const toggleCode = (c: WithholdingCode) =>
    void save.run(async () => {
      await api.patch(`/taxes/withholding/codes/${c.id}`, { is_active: !c.is_active });
      setTick((x) => x + 1);
    });
  return (
    <>
      <RangeBar r={r} />
      <Alert>{r.download.error || save.error}</Alert>
      {rep.loading && <Loading />}
      {rep.error && <Alert>{rep.error}</Alert>}
      {rep.data && (
        <>
          <div className="grid kpis" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 12, margin: "14px 0" }}>
            <Kpi label={t("عدد سندات الخصم")} value={String(rep.data.rows.length)} />
            <Kpi label={t("إجمالي المحتجز للفترة")} value={money(rep.data.total_withheld)} />
          </div>
          <div className="row" style={{ gap: 8, marginBottom: 14 }}>
            <ExportButton busy={r.download.busy} onClick={() => r.exportFile(`/taxes/withholding/xlsx${r.range}`, `withholding-${r.from}_${r.to}.xlsx`)}>{t("Excel")}</ExportButton>
            <ExportButton busy={r.download.busy} onClick={() => r.exportFile(`/taxes/withholding/pdf${r.range}`, `withholding-${r.from}_${r.to}.pdf`)}>{t("PDF")}</ExportButton>
            <button className="btn" onClick={() => setTick((x) => x + 1)}>↻</button>
          </div>
          <div className="card card-pad" style={{ marginBottom: 14 }}>
            <h3>{t("النموذج الشهري الرسمي (المادة 62)")}</h3>
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              <select value={whFormMonth} onChange={(e) => setWhFormMonth(Number(e.target.value))}>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{t("شهر")} {m}</option>)}
              </select>
              <input dir="ltr" type="number" min="2015" max="2100" style={{ width: 90 }} value={whFormYear} onChange={(e) => setWhFormYear(Number(e.target.value))} />
              <ExportButton busy={r.download.busy} onClick={() => r.exportFile(`/taxes/withholding/form-xlsx?year=${whFormYear}&month=${whFormMonth}`, `withholding-form-${whFormYear}-${String(whFormMonth).padStart(2, "0")}.xlsx`)}>{t("تنزيل النموذج Excel")}</ExportButton>
              <ExportButton busy={r.download.busy} onClick={() => r.exportFile(`/taxes/withholding/form-pdf?year=${whFormYear}&month=${whFormMonth}`, `withholding-form-${whFormYear}-${String(whFormMonth).padStart(2, "0")}.pdf`)}>{t("تنزيل النموذج PDF")}</ExportButton>
            </div>
            <p className="muted" style={{ marginTop: 6 }}>💡 {t("املأ الرقم الضريبي للمورد من بيانات الموردين ليظهر في النموذج")}</p>
          </div>
          <Table
            title={t("سندات الخصم والإضافة")}
            headers={[t("التاريخ"), t("المورد"), t("قيمة السند"), t("المحتجز"), t("النقدية"), t("الكود")]}
            rows={rep.data.rows.map((w) => [
              w.paid_on, w.supplier_name || "—", money(w.amount), money(w.withholding), money(w.net_cash), w.code_name,
            ])}
          />
          <div style={{ height: 12 }} />
          <Table
            title={t("الإجماليات بالكود")}
            headers={[t("الكود"), t("إجمالي المحتجز")]}
            rows={rep.data.by_code.map((b) => [b.code, money(b.total)])}
          />
          <div style={{ height: 12 }} />
          <Table
            title={t("الإجماليات بالمورد")}
            headers={[t("المورد"), t("إجمالي المحتجز")]}
            rows={rep.data.by_supplier.map((b) => [b.supplier, money(b.total)])}
          />
        </>
      )}
      {manage && (
        <div className="card card-pad" style={{ marginTop: 14 }}>
          <h3>{t("أكواد النسب (المادة 62)")}</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>{t("الاسم")}</th><th className="num">{t("النسبة %")}</th><th className="num">{t("الحالة")}</th><th></th></tr></thead>
              <tbody>
                {(codes.data || []).map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}</td>
                    <td className="num">{Number(c.rate).toLocaleString("ar-EG")}</td>
                    <td className="num">{c.is_active ? "✅" : "⛔"}</td>
                    <td className="num">
                      <button className="btn btn-sm" onClick={() => toggleCode(c)}>{c.is_active ? t("تعطيل") : t("تفعيل")}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <input style={{ flex: 2 }} placeholder={t("اسم النوع")} value={newCode.name} onChange={(e) => setNewCode({ ...newCode, name: e.target.value })} />
            <input dir="ltr" type="number" min="0" max="100" step="0.01" style={{ width: 100 }} placeholder="%" value={newCode.rate} onChange={(e) => setNewCode({ ...newCode, rate: e.target.value })} />
            <button className="btn btn-primary" disabled={save.busy || !newCode.name || !newCode.rate} onClick={addCode}>{t("إضافة")}</button>
          </div>
        </div>
      )}
    </>
  );
}

// ============================================================ ضريبة كسب العمل
function PayrollTab() {
  const { t } = useI18n();
  const { can } = useAuth();
  const [runId, setRunId] = useState("");
  const runs = useFetch<PayrollRunLite[]>(() => api.get<PayrollRunLite[]>("/hr/payroll-runs?limit=50"), "pruns");
  const rep = useFetch<PayrollTaxReport | null>(
    () => (runId ? api.get<PayrollTaxReport>(`/taxes/payroll-tax/${runId}`) : Promise.resolve(null)),
    `ptax${runId}`,
  );
  const settings = useFetch<PayrollTaxSettings>(() => api.get<PayrollTaxSettings>("/taxes/payroll-tax/settings"), "psettings");
  const manage = can("taxes.payroll.manage");
  const [edit, setEdit] = useState<PayrollTaxSettings | null>(null);
  const save = useAction();
  const startEdit = () => {
    if (settings.data) setEdit(JSON.parse(JSON.stringify(settings.data)) as PayrollTaxSettings);
  };
  const saveSettings = () =>
    void save.run(async () => {
      if (!edit) return;
      await api.put("/taxes/payroll-tax/settings", {
        personal_exemption: edit.personal_exemption,
        wage_reduction_percent: edit.wage_reduction_percent,
        social_insurance_percent: edit.social_insurance_percent,
        brackets: edit.brackets.map((b, i) => ({ min_amount: b.min_amount, max_amount: b.max_amount, rate: b.rate, sort: i })),
      });
      setEdit(null);
      settings.reload();
      if (runId) rep.reload();
    });
  const dl = useAction();
  const fq = runId ? `/${runId}` : "";
  return (
    <>
      <div className="card card-pad">
        <label className="range-field" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="field-label">{t("مسير الرواتب")}</span>
          <select value={runId} onChange={(e) => setRunId(e.target.value)}>
            <option value="">— {t("اختر مسيراً")} —</option>
            {(runs.data || []).map((r) => (
              <option key={r.id} value={r.id}>{r.year}-{String(r.month).padStart(2, "0")} · {r.status === "posted" ? t("مُرحَّل") : t("مسودة")} · {r.employees_count} {t("موظف")}</option>
            ))}
          </select>
        </label>
      </div>
      <Alert>{dl.error || save.error}</Alert>
      {!runId && <Empty>{t("اختر مسير رواتب لحساب الضريبة")}</Empty>}
      {rep.loading && <Loading />}
      {rep.error && <Alert>{rep.error}</Alert>}
      {rep.data && (
        <>
          <div className="grid kpis" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 12, margin: "14px 0" }}>
            <Kpi label={t("الضريبة الشهرية المحسبة")} value={money(rep.data.total_monthly_tax)} />
            <Kpi label={t("المقطوع فعليًا")} value={money(rep.data.total_actual)} />
            <Kpi label={t("فرق التسوية")} value={money(rep.data.total_difference)} />
          </div>
          <div className="row" style={{ gap: 8, marginBottom: 14 }}>
            <ExportButton busy={dl.busy} onClick={() => void dl.run(() => api.download(`/taxes/payroll-tax/xlsx${fq}`, `payroll-tax-${rep.data!.period}.xlsx`))}>{t("Excel")}</ExportButton>
            <ExportButton busy={dl.busy} onClick={() => void dl.run(() => api.download(`/taxes/payroll-tax/pdf${fq}`, `payroll-tax-${rep.data!.period}.pdf`))}>{t("PDF")}</ExportButton>
            <button className="btn" onClick={() => rep.reload()}>↻</button>
          </div>
          <Table
            title={t("حساب الضريبة لكل موظف — سنوي ÷ 12")}
            headers={[t("الكود"), t("الاسم"), t("الإجمالي الشهري"), t("تأمينات/شهر"), t("الوعاء السنوي"), t("الضريبة السنوية"), t("الخصم الشهري"), t("المقطوع فعليًا"), t("الفرق")]}
            rows={rep.data.rows.map((row) => [
              row.code, row.name, money(row.monthly_gross), money(row.monthly_si),
              money(row.annual_taxable), money(row.annual_tax), money(row.monthly_tax),
              money(row.actual_withheld), money(row.difference),
            ])}
          />
        </>
      )}
      {manage && (
        <div className="card card-pad" style={{ marginTop: 14 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3>{t("الشرائح والإعدادات")}</h3>
            {!edit && <button className="btn" onClick={startEdit}>{t("تعديل")}</button>}
          </div>
          {!edit && settings.data && (
            <p className="muted">
              {t("الاعفاء الشخصي")}: {money(settings.data.personal_exemption)} · {t("تخفيض الضريبة")}: {Number(settings.data.wage_reduction_percent)}% · {t("التأمينات")}: {Number(settings.data.social_insurance_percent)}% · {t("شرائح")}: {settings.data.brackets.length}
            </p>
          )}
          {edit && (
            <>
              <div className="row" style={{ gap: 8, marginBottom: 10 }}>
                <label className="range-field"><span className="field-label">{t("الاعفاء الشخصي السنوي")}</span>
                  <input dir="ltr" type="number" min="0" value={edit.personal_exemption} onChange={(e) => setEdit({ ...edit, personal_exemption: e.target.value })} style={{ width: 140 }} />
                </label>
                <label className="range-field"><span className="field-label">{t("تخفيض الضريبة %")}</span>
                  <input dir="ltr" type="number" min="0" max="100" value={edit.wage_reduction_percent} onChange={(e) => setEdit({ ...edit, wage_reduction_percent: e.target.value })} style={{ width: 100 }} />
                </label>
                <label className="range-field"><span className="field-label">{t("نسبة التأمينات %")}</span>
                  <input dir="ltr" type="number" min="0" max="100" value={edit.social_insurance_percent} onChange={(e) => setEdit({ ...edit, social_insurance_percent: e.target.value })} style={{ width: 100 }} />
                </label>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>{t("من")}</th><th>{t("إلى (فارغ = مفتوحة)")}</th><th>{t("النسبة %")}</th><th></th></tr></thead>
                  <tbody>
                    {edit.brackets.map((b: TaxBracket, i: number) => (
                      <tr key={i}>
                        <td><input dir="ltr" type="number" min="0" value={b.min_amount} onChange={(e) => {
                          const bs = [...edit.brackets]; bs[i] = { ...b, min_amount: e.target.value }; setEdit({ ...edit, brackets: bs });
                        }} /></td>
                        <td><input dir="ltr" type="number" min="0" value={b.max_amount ?? ""} onChange={(e) => {
                          const bs = [...edit.brackets]; bs[i] = { ...b, max_amount: e.target.value || null }; setEdit({ ...edit, brackets: bs });
                        }} /></td>
                        <td><input dir="ltr" type="number" min="0" max="100" step="0.5" value={b.rate} onChange={(e) => {
                          const bs = [...edit.brackets]; bs[i] = { ...b, rate: e.target.value }; setEdit({ ...edit, brackets: bs });
                        }} /></td>
                        <td><button className="btn btn-sm" onClick={() => setEdit({ ...edit, brackets: edit.brackets.filter((_, j) => j !== i) })}>✕</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="row" style={{ gap: 8, marginTop: 10 }}>
                <button className="btn" onClick={() => setEdit({ ...edit, brackets: [...edit.brackets, { id: 0, min_amount: "0", max_amount: null, rate: "0", sort: edit.brackets.length }] })}>{t("+ شريحة")}</button>
                <button className="btn btn-primary" disabled={save.busy} onClick={saveSettings}>{t("حفظ")}</button>
                <button className="btn" onClick={() => setEdit(null)}>{t("إلغاء")}</button>
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}

// ============================================================ الصفحة
export function Taxes() {
  const { t } = useI18n();
  const { can } = useAuth();
  const r = useRange();
  const tabs: { key: string; label: string; perm: string; render: () => React.ReactNode }[] = [
    { key: "vat", label: t("ضريبة القيمة المضافة"), perm: "taxes.vat.view", render: () => <VatTab r={r} /> },
    { key: "withholding", label: t("الخصم والإضافة"), perm: "taxes.withholding.view", render: () => <WithholdingTab r={r} /> },
    { key: "payroll", label: t("ضريبة كسب العمل"), perm: "taxes.payroll.view", render: () => <PayrollTab /> },
  ];
  const [active, setActive] = useState("vat");
  const current = tabs.find((x) => x.key === active) || tabs[0];
  return (
    <>
      <PageHeader title={t("الضرائب")} />
      <div className="row" style={{ gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
        {tabs.map((x) => (
          <button key={x.key} className={`btn ${current.key === x.key ? "btn-primary" : ""}`} onClick={() => setActive(x.key)}>
            {can(x.perm) ? x.label : `🔒 ${x.label}`}
          </button>
        ))}
      </div>
      {can(current.perm) ? current.render() : <Locked perm={current.perm} />}
    </>
  );
}
