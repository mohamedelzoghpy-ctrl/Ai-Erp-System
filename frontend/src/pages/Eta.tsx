import { useState, type FormEvent } from "react";
import { api, fetchBlob } from "../api";
import { useAction, useFetch } from "../hooks";
import type { EtaSubmission } from "../types";
import { money } from "../format";
import { Alert, Empty, Field, Loading, PageHeader } from "../ui";

type Tab = "queue" | "statuses" | "incoming" | "settings";

function StatusBadge({ status }: { status: string }) {
  return (
    <span style={{
      padding: "2px 10px", borderRadius: 999, fontSize: 12, fontWeight: 700,
      background: status === "valid" ? "rgba(21,128,61,.12)" : status === "invalid" ? "rgba(185,28,28,.12)" : "rgba(245,158,11,.15)",
      color: status === "valid" ? "#15803d" : status === "invalid" ? "#b91c1c" : "#b45309",
    }}>
      {status === "valid" ? "مقبولة ✓" : status === "invalid" ? "مرفوضة ✖" : status === "submitted" ? "مُرسلة…" : status}
    </span>
  );
}

/** مركز تشغيل الفاتورة الإلكترونية: رفع فواتير البيع + الإيصالات + استيراد مشتريات المنظومة + الإعداد. */
export default function Eta() {
  const [tab, setTab] = useState<Tab>("queue");
  const cfg = useFetch(() => api.get<any>("/eta/config"), "eta-cfg");
  const subs = useFetch(() => api.get<EtaSubmission[]>("/eta/submissions?limit=100"), "eta-subs");
  const queue = useFetch(() => api.get<{ pending: any[]; sent: any[] }>("/eta/queue"), "eta-queue");
  const receipts = useFetch(() => api.get<{ pending: any[]; sent: any[] }>("/eta/queue?type=R"), "eta-receipts");
  const incoming = useFetch(() => api.get<any[]>("/eta/incoming"), "eta-incoming");
  const warehouses = useFetch(() => api.get<{ id: number; name: string }[]>("/warehouses?limit=200"), "eta-whs");
  const { busy, error, run } = useAction();
  const [saved, setSaved] = useState<string | null>(null);
  const [csr, setCsr] = useState<string | null>(null);
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  const [incomingWh, setIncomingWh] = useState("");

  const reloadOps = () => { queue.reload(); receipts.reload(); subs.reload(); incoming.reload(); };
  const submitSelected = async () => {
    const ids = Object.entries(selected).filter(([, v]) => v).map(([k]) => Number(k));
    if (!ids.length) { alert("حدّد فاتورة واحدة على الأقل"); return; }
    if (!confirm(`إرسال ${ids.length} فاتورة للمنظومة؟`)) return;
    void run(async () => {
      let okCount = 0;
      for (const id of ids) {
        try { await api.post(`/eta/submit/${id}`, {}); okCount++; } catch { /* التفاصيل في السجل */ }
      }
      alert(`أُرسل ${okCount} من ${ids.length} — التفاصيل في تبويب الحالات`);
      setSelected({});
      reloadOps();
    });
  };
  const submitPendingAll = async () => {
    if (!confirm("إرسال كل الفواتير غير المرسلة (دفعة واحدة حتى 100)؟")) return;
    void run(async () => {
      const r: any = await api.post("/eta/submit-pending", {});
      alert(r?.submitted ? `أُرسل ${r.submitted} — ${JSON.stringify(r.statuses)}` : (r?.detail || "لا جديد"));
      reloadOps();
    });
  };
  const refreshAll = async () => {
    void run(async () => {
      const r: any = await api.post("/eta/refresh-all", {});
      alert(`فُحص ${r?.checked ?? 0} إرسال قيد الانتظار — حُسم ${r?.updated?.length ?? 0}`);
      reloadOps();
    });
  };
  const submitReceiptOne = async (orderId: number) => {
    void run(async () => {
      const r: any = await api.post(`/eta/submit-receipt/${orderId}`, {});
      alert(r?.status === "valid" ? "قُبل الإيصال ✓" : `الحالة: ${r?.status}`);
      reloadOps();
    });
  };
  const submitReceiptsBulk = async () => {
    if (!confirm("إرسال كل الإيصالات المؤكدة غير المرسلة (دفعة واحدة حتى 100)؟")) return;
    void run(async () => {
      const r: any = await api.post("/eta/submit-receipts-pending", {});
      alert(r?.submitted ? `أُرسل ${r.submitted} إيصال — ${JSON.stringify(r.statuses)}` : (r?.detail || "لا إيصالات جديدة"));
      reloadOps();
    });
  };
  const downloadQr = async (submissionId: number) => {
    const blob = await fetchBlob(`/eta/submissions/${submissionId}/qr.png`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `receipt-qr-${submissionId}.png`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };
  const refreshOne = (id: number) => {
    void run(async () => { await api.post(`/eta/refresh/${id}`, {}); reloadOps(); });
  };
  const incomingSync = () => {
    void run(async () => {
      const r: any = await api.post("/eta/incoming/sync", {});
      alert(`فواتير مشتريات جديدة: ${r?.new ?? 0}`);
      incoming.reload();
    });
  };
  const createPO = async (id: number) => {
    if (!incomingWh) { alert("اختر مخزن الاستلام أولًا (أعلى الجدول)"); return; }
    void run(async () => {
      const r: any = await api.post(`/eta/incoming/${id}/create-po`, { warehouse_id: Number(incomingWh) });
      alert(`أُنشئت مسودة أمر شراء #${r?.purchase_order_id} — استلمها من أوامر الشراء`);
      incoming.reload();
    });
  };

  const pending = queue.data?.pending ?? [];
  const incomingRows = incoming.data ?? [];

  return (
    <>
      <PageHeader title="الفاتورة الإلكترونية (ETA)" />
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14, borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
        {([
          ["queue", "📤 فواتير البيع"],
          ["statuses", "🔄 الحالات والسجل"],
          ["incoming", "📥 مشتريات واردة"],
          ["settings", "⚙️ الإعداد"],
        ] as [Tab, string][]).map(([key, label]) => (
          <button key={key} type="button" className={`btn btn-sm ${tab === key ? "btn-primary" : ""}`} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>
      <Alert>{error}</Alert>

      {/* ============================ 1) طابور فواتير البيع ============================ */}
      {tab === "queue" && (
        <>
          <div className="card card-pad" style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              <h3 style={{ margin: 0 }}>📤 فواتير مؤكدة بانتظار الرفع ({pending.length})</h3>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button className="btn btn-sm btn-primary" disabled={busy || !Object.values(selected).some(Boolean)} onClick={submitSelected}>
                  إرسال المحدد ({Object.values(selected).filter(Boolean).length})
                </button>
                <button className="btn btn-sm" disabled={busy} onClick={submitPendingAll}>⚡ إرسال الكل (دفعة)</button>
                <button className="btn btn-sm" title="تصدير الفواتير المعلقة بصيغة قالب الرفع اليدوي من بوابة المنظومة"
                  onClick={() => void run(async () => {
                    const blob = await fetchBlob("/eta/export-template", { method: "POST", body: JSON.stringify({ order_ids: [] }) });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url; a.download = "eta-manual-template.xlsx"; a.click();
                    setTimeout(() => URL.revokeObjectURL(url), 5000);
                  })}>⬇️ قالب الرفع اليدوي</button>
                <button className="btn btn-sm" title="بعد رفعها يدويًا من البوابة — امنع تكرار إرسالها عبر الـ API"
                  onClick={async () => {
                    const ids = Object.entries(selected).filter(([, v]) => v).map(([k]) => Number(k));
                    if (!ids.length) { alert("حدّد الفواتير المرفوعة خارجيًا"); return; }
                    const reference = prompt("مرجع الرفع الخارجي (رقم من البوابة إن وجد):", "") ?? "";
                    void run(async () => {
                      const r: any = await api.post("/eta/mark-external", { order_ids: ids, reference });
                      alert(`وُسمت ${r?.marked ?? 0} فاتورة كمرفوعة خارجيًا`);
                      setSelected({});
                      reloadOps();
                    });
                  }}>🏷️ مرفوعة خارجيًا</button>
              </div>
            </div>
            <Alert>{queue.error}</Alert>
            {queue.loading ? <Loading /> : pending.length ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th></th><th>#</th><th>العميل</th><th className="num">الإجمالي (ج.م)</th><th>أجنبي</th><th></th></tr></thead>
                  <tbody>
                    {pending.map((r) => (
                      <tr key={r.order_id}>
                        <td><input type="checkbox" checked={!!selected[r.order_id]} onChange={(e) => setSelected({ ...selected, [r.order_id]: e.target.checked })} /></td>
                        <td dir="ltr">{r.internal_id}</td>
                        <td>{r.party_name}</td>
                        <td className="num">{money(r.total_amount)}</td>
                        <td>{r.currency_code ? `${money(r.foreign_total)} ${r.currency_code}` : "—"}</td>
                        <td><button className="btn btn-sm" onClick={() => submitSelected === undefined ? undefined : run(async () => { await api.post(`/eta/submit/${r.order_id}`, {}); reloadOps(); })}>إرسال</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty>لا فواتير بانتظار الرفع 🎉</Empty>}
          </div>

          <div className="card card-pad">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              <h3 style={{ margin: 0 }}>🧾 إيصالات البيع (R) — نقاط البيع B2C</h3>
              <button className="btn btn-sm btn-primary" disabled={busy || !(receipts.data?.pending ?? []).length}
                onClick={submitReceiptsBulk}>⚡ إرسال كل الإيصالات (دفعة)</button>
            </div>
            <p style={{ fontSize: 13, color: "var(--muted,#64748b)", margin: "0 0 10px" }}>
              مبيعات النقاط لعملاء بلا رقم ضريبي تُرسل كإيصالات (R) — في الإنتاج تتطلب توقيع جهاز مسجل، وتعمل الآن في بيئة التجربة.
            </p>
            <Alert>{receipts.error}</Alert>
            {receipts.loading ? <Loading /> : (receipts.data?.pending ?? []).length ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>#</th><th>العميل</th><th className="num">الإجمالي</th><th></th></tr></thead>
                  <tbody>
                    {(receipts.data?.pending ?? []).slice(0, 30).map((r) => (
                      <tr key={r.order_id}>
                        <td dir="ltr">{r.internal_id}</td>
                        <td>{r.party_name}</td>
                        <td className="num">{money(r.total_amount)}</td>
                        <td><button className="btn btn-sm" disabled={busy} onClick={() => submitReceiptOne(r.order_id)}>إرسال إيصال</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty>لا إيصالات بانتظار الرفع 🎉</Empty>}
            {(receipts.data?.sent ?? []).length ? (
              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table>
                  <thead><tr><th>#</th><th>العميل</th><th className="num">الإجمالي</th><th>المنظومة</th><th>QR للطباعة</th></tr></thead>
                  <tbody>
                    {(receipts.data?.sent ?? []).slice(0, 30).map((r) => (
                      <tr key={r.order_id}>
                        <td dir="ltr">{r.internal_id}</td>
                        <td>{r.party_name}</td>
                        <td className="num">{money(r.total_amount)}</td>
                        <td><StatusBadge status={r.status} /></td>
                        <td>{r.submission_id ? (
                          <button className="btn btn-sm" title="حمّل QR وطبعته على فاتورة الكاشير"
                            onClick={() => void run(() => downloadQr(r.submission_id))}>▣ QR</button>
                        ) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        </>
      )}

      {/* ============================ 2) الحالات والسجل ============================ */}
      {tab === "statuses" && (
        <div className="card card-pad">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
            <h3 style={{ margin: 0 }}>🔄 حالات الفواتير على المنظومة</h3>
            <button className="btn btn-primary" disabled={busy} onClick={refreshAll}>🔄 تحديث كل الحالات</button>
          </div>
          <Alert>{subs.error}</Alert>
          {subs.loading ? <Loading /> : (subs.data ?? []).length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>المستند</th><th>النوع</th><th>الحالة</th><th>Long ID</th><th>آخر فحص</th><th>أخطاء</th><th></th></tr></thead>
                <tbody>
                  {(subs.data ?? []).map((s) => (
                    <tr key={s.id}>
                      <td>{s.id}</td>
                      <td dir="ltr">{s.internal_id}</td>
                      <td>{s.document_type === "R" ? "إيصال R" : s.document_type === "C" ? "إشعار دائن C" : "فاتورة I"}</td>
                      <td><StatusBadge status={s.status} /></td>
                      <td dir="ltr">{s.eta_long_id ?? "—"}</td>
                      <td dir="ltr">{s.status_checked_at?.slice(0, 16).replace("T", " ") ?? "—"}</td>
                      <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.errors ? JSON.stringify(s.errors) : ""}>
                        {s.errors ? JSON.stringify(s.errors) : "—"}
                      </td>
                      <td><button className="btn btn-sm" onClick={() => refreshOne(s.id)} disabled={busy}>فحص</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty>لا إرسالات بعد</Empty>}
        </div>
      )}

      {/* ============================ 3) مشتريات واردة ============================ */}
      {tab === "incoming" && (
        <div className="card card-pad">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
            <h3 style={{ margin: 0 }}>📥 فواتير المشتريات الواردة من المنظومة</h3>
            <button className="btn btn-primary" disabled={busy} onClick={incomingSync}>⬇️ مزامنة الوارد الجديد</button>
            <label className="btn btn-sm" style={{ cursor: "pointer" }} title="استيراد فواتير موردين من Excel (احتياطي)">
              ⬆️ استيراد إكسل
              <input type="file" accept=".xlsx,.csv" style={{ display: "none" }} onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                e.target.value = "";
                void run(async () => {
                  const fd = new FormData();
                  fd.append("file", file);
                  const r: any = await api.post("/eta/incoming/import", fd);
                  alert(`استُوردت ${r?.imported ?? 0} فاتورة${r?.errors?.length ? ` — أخطاء: ${r.errors.length}` : ""}`);
                  incoming.reload();
                });
              }} />
            </label>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "end", marginBottom: 10, flexWrap: "wrap" }}>
            <Field label="مخزن الاستلام عند التحويل">
              <select value={incomingWh} onChange={(e) => setIncomingWh(e.target.value)} style={{ minWidth: 220 }}>
                <option value="">— اختر المخزن —</option>
                {(warehouses.data ?? []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </Field>
          </div>
          <Alert>{incoming.error}</Alert>
          {incoming.loading ? <Loading /> : incomingRows.length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>المورد</th><th>رقمها عنده</th><th className="num">الإجمالي</th><th className="num">البنود</th><th>الحالة</th><th></th></tr></thead>
                <tbody>
                  {incomingRows.map((r) => (
                    <tr key={r.id}>
                      <td>{r.issuer_name}<div dir="ltr" style={{ fontSize: 11, color: "var(--muted,#64748b)" }}>{r.issuer_tin ?? "—"}</div></td>
                      <td dir="ltr">{r.internal_id ?? "—"}</td>
                      <td className="num">{money(r.total_amount)}</td>
                      <td className="num">{r.lines.length}</td>
                      <td>{r.status === "new" ? "جديدة" : r.status === "imported" ? `محوّلة → PO#${r.purchase_order_id}` : "متجاهلة"}</td>
                      <td>
                        {r.status === "new" && (
                          <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => createPO(r.id)}>إنشاء مسودة أمر شراء</button>
                        )}
                        {r.purchase_order_id && <a className="btn btn-sm" href="/purchase-orders" style={{ textDecoration: "none" }}>الأوامر</a>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty>لا فواتير واردة — اضغط «مزامنة» لسحب الجديد من المنظومة</Empty>}
        </div>
      )}

      {/* ============================ 4) الإعداد ============================ */}
      {tab === "settings" && (
        <EtaSettings
          cfg={cfg} busy={busy} run={run} saved={saved} setSaved={setSaved} csr={csr} setCsr={setCsr}
        />
      )}
    </>
  );
}

function EtaSettings({ cfg, busy, run, saved, setSaved, csr, setCsr }: {
  cfg: { data: any; error: string | null; loading: boolean; reload: () => void };
  busy: boolean; run: (fn: () => Promise<void>) => void;
  saved: string | null; setSaved: (v: string | null) => void;
  csr: string | null; setCsr: (v: string | null) => void;
}) {
  const [f, setF] = useState<{
    enabled: boolean; env: string; tin: string; client_id: string; client_secret: string;
    activity_code: string; governate: string; region_city: string; street: string; building_number: string;
  } | null>(null);
  const form = f ?? {
    enabled: cfg.data?.enabled ?? false,
    env: cfg.data?.env ?? "mock",
    tin: cfg.data?.tin ?? "",
    client_id: cfg.data?.client_id ?? "",
    client_secret: "",
    activity_code: cfg.data?.activity_code ?? "4690",
    governate: cfg.data?.address?.governate ?? "",
    region_city: cfg.data?.address?.region_city ?? "",
    street: cfg.data?.address?.street ?? "",
    building_number: cfg.data?.address?.building_number ?? "",
  };
  const set = (k: keyof typeof form, v: string | boolean) => setF({ ...form, [k]: v } as typeof form);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const body: any = {
        enabled: form.enabled, env: form.env, tin: form.tin, client_id: form.client_id, activity_code: form.activity_code,
        address: { governate: form.governate, region_city: form.region_city, street: form.street, building_number: form.building_number },
      };
      if (form.client_secret.trim()) body.client_secret = form.client_secret.trim();
      await api.put("/eta/config", body);
      setF(null);
      setSaved("تم حفظ الإعداد");
      cfg.reload();
    });
  };

  return (
    <div className="card card-pad">
      <h3 style={{ marginTop: 0 }}>⚙️ إعداد المنظومة</h3>
      <Alert>{cfg.error}</Alert>
      {saved && <Alert kind="info">{saved}</Alert>}
      {cfg.loading ? <Loading /> : (
        <form onSubmit={submit}>
          <div className="form-grid">
            <Field label="التفعيل">
              <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
                مفعّلة لهذه الشركة
              </label>
            </Field>
            <Field label="البيئة" hint="mock: تجربة بلا شبكة · sandbox: بيئة المنظومة التجريبية · prod: الإنتاج">
              <select value={form.env} onChange={(e) => set("env", e.target.value)}>
                <option value="mock">mock (تجربة محلية)</option>
                <option value="sandbox">sandbox (تجريبية)</option>
                <option value="prod">prod (إنتاج)</option>
              </select>
            </Field>
            <Field label="الرقم الضريبي (TIN)">
              <input dir="ltr" value={form.tin} onChange={(e) => set("tin", e.target.value)} placeholder="مثال: 300000000000003" />
            </Field>
            <Field label="كود النشاط">
              <input dir="ltr" value={form.activity_code} onChange={(e) => set("activity_code", e.target.value)} />
            </Field>
            <Field label="المحافظة" hint="مطلوب في sandbox/prod — المنظومة ترفض العناوين الناقصة">
              <input value={form.governate} onChange={(e) => set("governate", e.target.value)} />
            </Field>
            <Field label="المدينة / المنطقة"><input value={form.region_city} onChange={(e) => set("region_city", e.target.value)} /></Field>
            <Field label="الشارع"><input value={form.street} onChange={(e) => set("street", e.target.value)} /></Field>
            <Field label="رقم العقار"><input dir="ltr" value={form.building_number} onChange={(e) => set("building_number", e.target.value)} /></Field>
            <Field label="Client ID" hint="من بوابة المنظومة بعد تسجيل الحل">
              <input dir="ltr" value={form.client_id} onChange={(e) => set("client_id", e.target.value)} />
            </Field>
            <Field label="Client Secret" hint={cfg.data?.client_secret_masked ? `محفوظ (${cfg.data.client_secret_masked}) — اتركه فارغًا للإبقاء` : "يُكتب مرة واحدة ولا يُعرض"}>
              <input dir="ltr" type="password" value={form.client_secret} onChange={(e) => set("client_secret", e.target.value)} placeholder={cfg.data?.has_client_secret ? "••••••••" : ""} />
            </Field>
          </div>
          <div className="form-actions" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="btn btn-primary" disabled={busy}>{busy ? "..." : "حفظ"}</button>
            <button type="button" className="btn" onClick={() => {
              if (!confirm("توليد زوج مفاتيح + CSR للرقم الضريبي الحالي؟ (يستبدل أي مفتاح سابق)")) return;
              void run(async () => {
                const r: any = await api.post("/eta/config/generate-keys", {});
                setCsr(r?.csr ?? null);
                cfg.reload();
              });
            }} disabled={busy}>🔑 توليد مفاتيح + CSR</button>
            <button type="button" className="btn" onClick={() => {
              void run(async () => {
                const r: any = await api.post("/eta/config/test-connection", {});
                setSaved(`الاتصال سليم ✓ — بيئة ${r?.env} · توقيع يعمل`);
                cfg.reload();
              });
            }} disabled={busy}>🔌 اختبار الاتصال</button>
          </div>
        </form>
      )}
      <div style={{ marginTop: 12, fontSize: 13, color: "var(--muted, #64748b)", lineHeight: 1.9 }}>
        <b>خطوات ما بعد تسجيل الشركة في المنظومة:</b>
        <ol style={{ margin: "6px 0 0", paddingRight: 18 }}>
          <li>أدخل الرقم الضريبي ثم اضغط «توليد مفاتيح + CSR» واحتفظ بملف الـ CSR الناتج.</li>
          <li>ارفع الـ CSR في بوابة المنظومة عند تسجيل الحل واحصل على Client ID/Secret.</li>
          <li>أدخل Client ID/Secret هنا، غيّر البيئة إلى sandbox وجرّب «اختبار الاتصال».</li>
          <li>أرسل فاتورة تجريبية من تبويب «فواتير البيع» وتحقق من حالتها، ثم بدّل إلى prod.</li>
        </ol>
      </div>
      {csr && (
        <div style={{ marginTop: 12 }}>
          <b>ملف الـ CSR (انسخه واحفظه للرفع في البوابة):</b>
          <textarea readOnly rows={6} dir="ltr" style={{ width: "100%", fontFamily: "monospace", fontSize: 11, marginTop: 6 }} value={csr} />
        </div>
      )}
    </div>
  );
}
