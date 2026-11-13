import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useFetch, usePagedList } from "../hooks";
import { useI18n } from "../i18n";
import { dateTime, money } from "../format";
import { Alert, Empty, Field, Loading, Modal, PageHeader, Pager } from "../ui";
import { useAuth } from "../auth";

/** مراحل العميل المحتمل بألوانها. */
const STAGES: { key: string; color: string; bg: string }[] = [
  { key: "new", color: "#57606a", bg: "#eaeef2" },
  { key: "contacted", color: "#0d47a1", bg: "#e3f2fd" },
  { key: "qualified", color: "#6b21a8", bg: "#f3e8ff" },
  { key: "won", color: "#15803d", bg: "#dcfce7" },
  { key: "lost", color: "#b42318", bg: "#fee4e2" },
];
const SOURCES = ["walk_in", "phone", "social", "referral", "exhibition", "other"];

type Lead = {
  id: number;
  code: string;
  name: string;
  company_name: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  source: string;
  status: string;
  expected_value: string;
  assigned_rep_id: number | null;
  next_follow_up_at: string | null;
  lost_reason: string | null;
  notes: string | null;
  converted_customer_id: number | null;
  created_at: string;
};

type CrmFunnelOut = {
  stages: { stage: string; count: number; expected_value: string }[];
  open_pipeline_value: string;
  won_count: number;
  won_value: string;
  lost_count: number;
  win_rate_pct?: number | null;
  avg_won_value?: string | null;
  avg_days_to_win?: number | null;
};
type CrmSourceRow = { source: string; count: number; won_count: number; lost_count: number; open_count: number; won_value: string; win_rate_pct?: number | null };

/** تحويل ISO إلى صيغة datetime-local للإدخال. */
const dtLocal = (iso?: string | null) => iso ? new Date(iso).toLocaleString("sv-SE").replace(" ", "T").slice(0, 16) : "";

type Activity = { id: number; kind: string; body: string; created_at: string };

function StageBadge({ status }: { status: string }) {
  const s = STAGES.find((x) => x.key === status) ?? STAGES[0];
  const labels: Record<string, string> = {
    new: "جديد",
    contacted: "تم التواصل",
    qualified: "مؤهل",
    won: "تحوّل لعميل",
    lost: "مفقود",
  };
  return (
    <span className="badge" style={{ background: s.bg, color: s.color, borderRadius: 999, padding: "2px 10px", fontSize: 12, fontWeight: 700 }}>
      {labels[status] ?? status}
    </span>
  );
}

const SOURCE_LABELS: Record<string, string> = {
  walk_in: "زائر / مباشر",
  phone: "اتصال هاتفي",
  social: "سوشيال ميديا",
  referral: "توصية عميل",
  exhibition: "معرض أو مؤتمر",
  other: "أخرى",
};

/** العملاء المحتملون (CRM): مراحل البيع + أنشطة المتابعة + التحويل لعميل فعلي. */
export default function Crm() {
  const { t } = useI18n();
  const { can } = useAuth();
  const canUpdate = can("crm.lead.update");
  const reps = useFetch(() => api.get<{ id: number; name: string; code: string }[]>("/reps"), "crm-reps");
  const [stage, setStage] = useState<string>("");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"table" | "kanban" | "analytics">("kanban");
  const [followUp, setFollowUp] = useState<"" | "today" | "overdue">("");
  const leads = usePagedList<Lead>("/crm/leads", { status: stage || undefined, search: search || undefined, follow_up: followUp || undefined });
  const board = useFetch(() => api.get<Lead[]>("/crm/leads?limit=200"), "crm-board");

  const [openAdd, setOpenAdd] = useState(false);
  const [editing, setEditing] = useState<Lead | null>(null);
  const [actLead, setActLead] = useState<Lead | null>(null);
  const [confirmConv, setConfirmConv] = useState<Lead | null>(null);
  const [confirmDel, setConfirmDel] = useState<Lead | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [dupMatches, setDupMatches] = useState<{ kind: string; id: number; name: string; code: string }[] | null>(null);
  const [quoteLead, setQuoteLead] = useState<Lead | null>(null);
  const [quoteRows, setQuoteRows] = useState<{ product_id: number | ""; quantity: string; unit_price: string }[]>([{ product_id: "", quantity: "1", unit_price: "" }]);
  const [quoteBusy, setQuoteBusy] = useState(false);
  const products = useFetch(() => api.get<{ id: number; name: string; sale_price: string }[]>("/products?limit=500"), "crm-products");
  const warehouseList = useFetch(() => api.get<{ id: number; name: string }[]>("/warehouses"), "crm-warehouses");
  const funnel = useFetch(() => api.get<CrmFunnelOut>("/crm/reports/funnel"), "crm-funnel");
  const sources = useFetch(() => api.get<CrmSourceRow[]>("/crm/reports/sources"), "crm-sources");

  const emptyForm = { name: "", company_name: "", phone: "", email: "", address: "", source: "walk_in", status: "new", expected_value: "", assigned_rep_id: "", next_follow_up_at: "", lost_reason: "", notes: "" };
  const [f, setF] = useState(emptyForm);

  const repName = (id: number | null) => {
    if (!id) return "—";
    const r = (reps.data ?? []).find((x) => x.id === id);
    return r ? r.name : `#${id}`;
  };

  const submitAdd = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await api.post<Lead>("/crm/leads", {
        name: f.name.trim(),
        company_name: f.company_name.trim() || null,
        phone: f.phone.trim() || null,
        email: f.email.trim() || null,
        address: f.address.trim() || null,
        source: f.source,
        expected_value: f.expected_value.trim() === "" ? "0" : f.expected_value,
        assigned_rep_id: f.assigned_rep_id === "" ? null : Number(f.assigned_rep_id),
        next_follow_up_at: f.next_follow_up_at ? new Date(f.next_follow_up_at).toISOString() : null,
        notes: f.notes.trim() || null,
      });
      setOpenAdd(false);
      setDupMatches(null);
      board.reload();
      setF(emptyForm);
      setNote(`${t("تم إضافة العميل المحتمل «")}${created.name}${t("» بكود ")}${created.code}${t(".")}`);
      leads.reload();
    } catch (err) {
      const msg = (err as Error).message;
      if (msg.includes("duplicates") || msg.includes("بنفس رقم الهاتف")) {
        // استخرج المطابقات من تفاصيل الخطأ واعرض تأكيد المتابعة
        try {
          const parsed = JSON.parse(msg);
          if (parsed?.duplicates) { setDupMatches(parsed.duplicates); setError(null); setBusy(false); return; }
        } catch { /* التفاصيل ليست JSON — اعرض الرسالة كما هي */ }
        setDupMatches([]);
        setError(null);
        setBusy(false);
        return;
      }
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const forceCreate = () => {
    setDupMatches(null);
    void (async () => {
      setBusy(true);
      setError(null);
      try {
        await api.post<Lead>("/crm/leads?force=true", {
          name: f.name.trim(),
          company_name: f.company_name.trim() || null,
          phone: f.phone.trim() || null,
          email: f.email.trim() || null,
          address: f.address.trim() || null,
          source: f.source,
          expected_value: f.expected_value.trim() === "" ? "0" : f.expected_value,
          assigned_rep_id: f.assigned_rep_id === "" ? null : Number(f.assigned_rep_id),
          next_follow_up_at: f.next_follow_up_at ? new Date(f.next_follow_up_at).toISOString() : null,
          notes: f.notes.trim() || null,
        });
        setOpenAdd(false);
        board.reload();
        leads.reload();
        setNote(`${t("أُنشئ القائد رغم التكرار المحتمل.")}`);
        setF(emptyForm);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setBusy(false);
      }
    })();
  };

  const submitQuotation = async (e: FormEvent) => {
    e.preventDefault();
    if (!quoteLead) return;
    const items = quoteRows.filter((r) => r.product_id !== "" && Number(r.quantity) > 0 && Number(r.unit_price) >= 0)
      .map((r) => ({ product_id: Number(r.product_id), quantity: Number(r.quantity), unit_price: r.unit_price }));
    if (items.length === 0) return;
    setQuoteBusy(true);
    setError(null);
    try {
      const res = await api.post<{ quotation: { code: string } }>(`/crm/leads/${quoteLead.id}/quotation`, {
        warehouse_id: (warehouseList.data ?? [])[0]?.id ?? 0,
        items,
      });
      setQuoteLead(null);
      setQuoteRows([{ product_id: "", quantity: "1", unit_price: "" }]);
      setNote(`${t("أُنشئ عرض سعر")} ${res.quotation.code} ${t("— ستجده في أوامر البيع (عروض الأسعار).")}`);
      board.reload();
      leads.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setQuoteBusy(false);
    }
  };

  const openEdit = (l: Lead) => {
    setEditing(l);
    setF({
      name: l.name, company_name: l.company_name ?? "", phone: l.phone ?? "", email: l.email ?? "",
      address: l.address ?? "", source: l.source, status: l.status, expected_value: String(l.expected_value ?? "0"),
      assigned_rep_id: l.assigned_rep_id ? String(l.assigned_rep_id) : "",
      next_follow_up_at: dtLocal(l.next_follow_up_at), lost_reason: l.lost_reason ?? "", notes: l.notes ?? "",
    });
    setError(null);
  };

  const submitEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setError(null);
    setBusy(true);
    try {
      await api.patch(`/crm/leads/${editing.id}`, {
        name: f.name.trim(),
        company_name: f.company_name.trim() || null,
        phone: f.phone.trim() || null,
        email: f.email.trim() || null,
        address: f.address.trim() || null,
        source: f.source,
        status: f.status,
        expected_value: f.expected_value.trim() === "" ? "0" : f.expected_value,
        assigned_rep_id: f.assigned_rep_id === "" ? null : Number(f.assigned_rep_id),
        next_follow_up_at: f.next_follow_up_at ? new Date(f.next_follow_up_at).toISOString() : null,
        lost_reason: f.lost_reason.trim() || null,
        notes: f.notes.trim() || null,
      });
      setEditing(null);
      board.reload();
      setNote(`${t("تم تحديث «")}${editing.name}${t("».")}`);
      leads.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const doConvert = async (l: Lead) => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<Lead>(`/crm/leads/${l.id}/convert`);
      setConfirmConv(null);
      setNote(`${t("تحوّل «")}${res.name}${t("» إلى عميل فعلي — ستجده في صفحة العملاء.")}`);
      leads.reload();
    } catch (err) {
      setConfirmConv(null);
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async (l: Lead) => {
    setBusy(true);
    setError(null);
    try {
      await api.del(`/crm/leads/${l.id}`);
      setConfirmDel(null);
      setNote(`${t("تم حذف العميل المحتمل «")}${l.name}${t("».")}`);
      leads.reload();
    } catch (err) {
      setConfirmDel(null);
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title={t("العملاء المحتملون (CRM)")}>
        <button className="btn btn-primary" onClick={() => { setError(null); setF(emptyForm); setOpenAdd(true); }}>
          {"+ "}{t("إضافة عميل محتمل")}
        </button>
      </PageHeader>

      <div className="toolbar" style={{ marginBottom: 14, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <input placeholder={t("ابحث بالاسم أو الشركة أو الهاتف…")} value={search} onChange={(e) => setSearch(e.target.value)} style={{ maxWidth: 320 }} />
        <span style={{ display: "inline-flex", gap: 4 }}>
          <button className={`btn btn-sm${view === "kanban" ? " btn-primary" : ""}`} onClick={() => setView("kanban")}>📋 {t("خط البيع")}</button>
          <button className={`btn btn-sm${view === "table" ? " btn-primary" : ""}`} onClick={() => setView("table")}>📄 {t("جدول")}</button>
          <button className={`btn btn-sm${view === "analytics" ? " btn-primary" : ""}`} onClick={() => setView("analytics")}>📊 {t("تحليلات")}</button>
        </span>
        <select value={followUp} onChange={(e) => setFollowUp(e.target.value as "" | "today" | "overdue")}>
          <option value="">{t("كل المواعيد")}</option>
          <option value="today">{t("متابعات اليوم")}</option>
          <option value="overdue">{t("متابعات متأخرة")}</option>
        </select>
        <button className="btn btn-sm" style={{ background: stage === "" ? "var(--primary)" : undefined, color: stage === "" ? "#fff" : undefined }} onClick={() => setStage("")}>
          {t("الكل")}
        </button>
        {STAGES.map((s) => (
          <button key={s.key} className="btn btn-sm" style={{ background: stage === s.key ? s.bg : undefined, color: stage === s.key ? s.color : undefined, fontWeight: stage === s.key ? 800 : 400 }} onClick={() => setStage(s.key)}>
            {(STAGE_LABELS as any)[s.key]}
          </button>
        ))}
      </div>

      <Alert>{leads.error}</Alert>
      {error && <Alert>{error}</Alert>}
      {note && (
        <div dir="rtl" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, fontSize: 13, background: "var(--ok-bg)", color: "var(--ok)" }}>
          {note}
        </div>
      )}

      {view === "kanban" ? (
        <LeadKanban
          leads={board.data ?? []}
          loading={board.loading && !board.data}
          canUpdate={canUpdate}
          onMove={(leadId, newStatus) => {
            const lead = (board.data ?? []).find((x) => x.id === leadId);
            if (!lead || lead.status === newStatus) return;
            const apply = (extra?: Record<string, unknown>) => {
              void (async () => {
                try {
                  await api.patch(`/crm/leads/${leadId}`, { status: newStatus, ...extra });
                  board.reload();
                  leads.reload();
                } catch (err) {
                  setError((err as Error).message);
                }
              })();
            };
            if (newStatus === "lost") {
              const reason = window.prompt(t("سبب الفقد (مطلوب):"), "");
              if (!reason || !reason.trim()) return;
              apply({ lost_reason: reason.trim() });
            } else {
              apply();
            }
          }}
          onOpenActs={(l) => setActLead(l)}
          onEdit={(l) => openEdit(l)}
          onQuote={(l) => { setQuoteLead(l); setQuoteRows([{ product_id: "", quantity: "1", unit_price: l.expected_value && Number(l.expected_value) > 0 ? "" : "" }]); }}
        />
      ) : (
      <div className="card table-wrap">
        {leads.loading && !leads.data ? (
          <Loading />
        ) : leads.data && leads.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("الكود")}</th>
                <th>{t("الاسم")}</th>
                <th>{t("الشركة / النشاط")}</th>
                <th>{t("الهاتف")}</th>
                <th>{t("المصدر")}</th>
                <th>{t("المرحلة")}</th>
                <th className="num">{t("القيمة المتوقعة")}</th>
                <th>{t("المندوب المسؤول")}</th>
                <th>{t("أُنشئ في")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {leads.data.map((l) => (
                <tr key={l.id} style={l.converted_customer_id ? { opacity: 0.7 } : undefined}>
                  <td className="num-center" dir="ltr">{l.code}</td>
                  <td>{l.name}</td>
                  <td>{l.company_name ?? "—"}</td>
                  <td dir="ltr">{l.phone ?? "—"}</td>
                  <td>{t(SOURCE_LABELS[l.source] ?? l.source)}</td>
                  <td><StageBadge status={l.status} /></td>
                  <td className="num">{money(l.expected_value)}</td>
                  <td>{repName(l.assigned_rep_id)}</td>
                  <td>{dateTime(l.created_at)}</td>
                  <td className="actions">
                    <button className="btn-edit" onClick={() => openEdit(l)}>{t("تعديل")}</button>{" "}
                    <button className="btn btn-sm" style={{ color: "#6b21a8", borderColor: "#6b21a8" }} onClick={() => setActLead(l)}>
                      📞 {t("متابعة")}
                    </button>{" "}
                    {!l.converted_customer_id && l.status !== "won" && (
                      <button className="btn btn-sm" style={{ color: "#15803d", borderColor: "#15803d" }} onClick={() => setConfirmConv(l)}>
                        ✅ {t("تحويل لعميل")}
                      </button>
                    )}{" "}
                    <button
                      className="btn btn-sm"
                      style={{ color: "var(--danger)", borderColor: "var(--danger)" }}
                      onClick={() => setConfirmDel(l)}
                    >
                      {t("حذف")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{search || stage ? t("لا توجد نتائج مطابقة.") : t("لا يوجد عملاء محتملون — اضغط «إضافة عميل محتمل» للبدء.")}</Empty>
        )}
      </div>
      )}

      {view === "analytics" && funnel.data && (
        <div className="card card-pad">
          <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>📊 {t("قمع التحويل")}</h3>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
            <div className="card card-pad" style={{ flex: 1, minWidth: 140 }}>
              <div className="muted" style={{ fontSize: 12 }}>{t("Pipeline المفتوح")}</div>
              <div style={{ fontWeight: 800, fontSize: 18 }}>{money(funnel.data.open_pipeline_value)}</div>
            </div>
            <div className="card card-pad" style={{ flex: 1, minWidth: 140 }}>
              <div className="muted" style={{ fontSize: 12 }}>{t("معدل الفوز")}</div>
              <div style={{ fontWeight: 800, fontSize: 18 }}>{funnel.data.win_rate_pct != null ? `${funnel.data.win_rate_pct}%` : "—"}</div>
            </div>
            <div className="card card-pad" style={{ flex: 1, minWidth: 140 }}>
              <div className="muted" style={{ fontSize: 12 }}>{t("متوسط الصفقة الفائزة")}</div>
              <div style={{ fontWeight: 800, fontSize: 18 }}>{funnel.data.avg_won_value ? money(funnel.data.avg_won_value) : "—"}</div>
            </div>
            <div className="card card-pad" style={{ flex: 1, minWidth: 140 }}>
              <div className="muted" style={{ fontSize: 12 }}>{t("عمر القائد حتى الفوز")}</div>
              <div style={{ fontWeight: 800, fontSize: 18 }}>{funnel.data.avg_days_to_win != null ? `${funnel.data.avg_days_to_win} ${t("يوم")}` : "—"}</div>
            </div>
          </div>
          {funnel.data.stages.map((s) => {
            const maxCount = Math.max(...funnel.data!.stages.map((x) => x.count), 1);
            const color = STAGES.find((x) => x.key === s.stage)?.bg ?? "#eaeef2";
            const textColor = STAGES.find((x) => x.key === s.stage)?.color ?? "#57606a";
            return (
              <div key={s.stage} style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 2 }}>
                  <b style={{ color: textColor }}>{t((STAGE_LABELS as any)[s.stage])}</b>
                  <span>{s.count} · {money(s.expected_value)}</span>
                </div>
                <div style={{ background: "#f0f3f7", borderRadius: 6, height: 14 }}>
                  <div style={{ background: color, width: `${Math.max(4, (s.count / maxCount) * 100)}%`, height: "100%", borderRadius: 6 }} />
                </div>
              </div>
            );
          })}

          <h3 style={{ margin: "18px 0 8px", fontSize: 15 }}>🎯 {t("أداء مصادر البيع")}</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>{t("المصدر")}</th><th className="num">{t("القادة")}</th><th className="num">{t("فاز")}</th><th className="num">{t("فقد")}</th><th className="num">{t("مفتوح")}</th><th className="num">{t("قيمة الفوز")}</th><th className="num">{t("معدل الفوز")}</th></tr></thead>
              <tbody>
                {(sources.data ?? []).map((s) => (
                  <tr key={s.source}>
                    <td>{t(SOURCE_LABELS[s.source] ?? s.source)}</td>
                    <td className="num">{s.count}</td>
                    <td className="num" style={{ color: "#15803d", fontWeight: 700 }}>{s.won_count}</td>
                    <td className="num" style={{ color: "#b42318" }}>{s.lost_count}</td>
                    <td className="num">{s.open_count}</td>
                    <td className="num">{money(s.won_value)}</td>
                    <td className="num">{s.win_rate_pct != null ? `${s.win_rate_pct}%` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <Pager list={leads} style={view !== "table" ? { display: "none" } : undefined} />

      {dupMatches !== null && (
        <Modal title={t("⚠️ رقم هاتف موجود مسبقًا")} onClose={() => setDupMatches(null)}>
          <p style={{ margin: "0 0 8px" }}>{t("يوجد سجلات بنفس رقم الهاتف:")}</p>
          <div className="table-wrap" style={{ marginBottom: 10 }}>
            <table>
              <thead><tr><th>{t("النوع")}</th><th>{t("الاسم")}</th><th dir="ltr">{t("الكود")}</th></tr></thead>
              <tbody>
                {dupMatches.map((m, i) => (
                  <tr key={i}>
                    <td>{m.kind === "customer" ? t("عميل فعلي") : t("قائد")}</td>
                    <td>{m.name}</td>
                    <td dir="ltr">{m.code}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="form-actions">
            <button className="btn btn-primary" onClick={forceCreate}>{t("متابعة بالرغم من ذلك")}</button>
            <button className="btn" onClick={() => setDupMatches(null)}>{t("إلغاء")}</button>
          </div>
        </Modal>
      )}

      {quoteLead && (
        <Modal title={`🧾 ${t("عرض سعر — ")}${quoteLead.name}`} onClose={() => setQuoteLead(null)} wide>
          <Alert>{error}</Alert>
          <p className="muted" style={{ fontSize: 13, margin: "0 0 10px" }}>
            {t("سيُحوَّل القائد لعميل فعلي تلقائيًا (إن لم يتحول) وينشئ عرض سعر مربوطًا به.")}
            {warehouseList.data?.length ? "" : <><br />{t("⚠️ لا توجد مخازن — أنشئ مخزنًا أولًا")}</>}
          </p>
          <form onSubmit={submitQuotation}>
            {quoteRows.map((r, i) => (
              <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6, flexWrap: "wrap" }}>
                <select value={String(r.product_id)} onChange={(e) => {
                  const pid = e.target.value === "" ? "" : Number(e.target.value);
                  const price = (products.data ?? []).find((p) => p.id === pid)?.sale_price ?? "";
                  setQuoteRows((rows) => rows.map((x, xi) => (xi === i ? { ...x, product_id: pid, unit_price: x.unit_price || String(price) } : x)));
                }} style={{ flex: 2, minWidth: 180 }}>
                  <option value="">{t("اختر صنفًا…")}</option>
                  {(products.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
                <input dir="ltr" inputMode="decimal" placeholder={t("كمية")} value={r.quantity} onChange={(e) => setQuoteRows((rows) => rows.map((x, xi) => (xi === i ? { ...x, quantity: e.target.value.replace(/[^0-9.]/g, "") } : x)))} style={{ width: 90 }} />
                <input dir="ltr" inputMode="decimal" placeholder={t("سعر")} value={r.unit_price} onChange={(e) => setQuoteRows((rows) => rows.map((x, xi) => (xi === i ? { ...x, unit_price: e.target.value.replace(/[^0-9.]/g, "") } : x)))} style={{ width: 110 }} />
                {quoteRows.length > 1 && <button type="button" className="btn-delete" onClick={() => setQuoteRows((rows) => rows.filter((_, xi) => xi !== i))}>✕</button>}
              </div>
            ))}
            <button type="button" className="btn btn-sm" onClick={() => setQuoteRows((rows) => [...rows, { product_id: "", quantity: "1", unit_price: "" }])}>+ {t("صنف")}</button>
            <div className="form-actions" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={quoteBusy || quoteRows.every((r) => r.product_id === "")}>
                {quoteBusy ? t("جارٍ الإنشاء…") : t("إنشاء عرض السعر")}
              </button>
              <button type="button" className="btn" onClick={() => setQuoteLead(null)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}

      {(openAdd || editing) && (
        <Modal title={editing ? `${t("تعديل — ")}${editing.name}` : t("إضافة عميل محتمل")} onClose={() => { setOpenAdd(false); setEditing(null); }} wide>
          <form onSubmit={editing ? submitEdit : submitAdd}>
            <Alert>{error}</Alert>
            <div className="form-grid">
              <Field label={t("اسم الشخص المسؤول")}>
                <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={150} />
              </Field>
              <Field label={t("اسم الشركة / النشاط")}>
                <input value={f.company_name} onChange={(e) => setF({ ...f, company_name: e.target.value })} maxLength={150} placeholder={t("اختياري")} />
              </Field>
              <Field label={t("الهاتف")}>
                <input dir="ltr" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} maxLength={50} placeholder={t("اختياري")} />
              </Field>
              <Field label={t("البريد الإلكتروني")}>
                <input dir="ltr" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} maxLength={150} placeholder={t("اختياري")} />
              </Field>
              <Field label={t("المصدر")}>
                <select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}>
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>{t(SOURCE_LABELS[s] ?? s)}</option>
                  ))}
                </select>
              </Field>
              {editing ? (
                <>
                  <Field label={t("المرحلة")}>
                    <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
                      {STAGES.map((s) => (
                        <option key={s.key} value={s.key}>{(STAGE_LABELS as any)[s.key]}</option>
                      ))}
                    </select>
                  </Field>
                  {f.status === "lost" && (
                    <Field label={t("سبب الفقد")} hint={t("مطلوب عند النقل إلى مفقود")}>
                      <input value={f.lost_reason} onChange={(e) => setF({ ...f, lost_reason: e.target.value })} maxLength={200} placeholder={t("سعر منافس / بلا استجابة…")} />
                    </Field>
                  )}
                </>
              ) : null}
              <Field label={t("القيمة المتوقعة")}>
                <input dir="ltr" inputMode="decimal" value={f.expected_value} onChange={(e) => setF({ ...f, expected_value: e.target.value.replace(/[^0-9.]/g, "") })} placeholder="0" />
              </Field>
              <Field label={t("موعد المتابعة القادم")} hint={t("يقود تنبيهات «متابعات اليوم» وإشعارات المندوب")}>
                <input type="datetime-local" dir="ltr" value={f.next_follow_up_at} onChange={(e) => setF({ ...f, next_follow_up_at: e.target.value })} />
              </Field>
              <Field label={t("المندوب المسؤول")}>
                <select value={f.assigned_rep_id} onChange={(e) => setF({ ...f, assigned_rep_id: e.target.value })}>
                  <option value="">{t("بلا تعيين")}</option>
                  {(reps.data ?? []).map((r) => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label={t("العنوان")}>
              <input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} placeholder={t("اختياري")} />
            </Field>
            <Field label={t("ملاحظات")}>
              <textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder={t("اختياري")} />
            </Field>
            <div className="form-actions" style={{ marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy || !f.name.trim()}>
                {busy ? t("جارٍ الحفظ…") : editing ? t("حفظ التعديلات") : t("إنشاء")}
              </button>
              <button type="button" className="btn" onClick={() => { setOpenAdd(false); setEditing(null); }}>
                {t("إلغاء")}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {actLead && <ActivitiesModal lead={actLead} onClose={() => setActLead(null)} />}

      {confirmConv && (
        <Modal title={`${t("تحويل لعميل فعلي — ")}${confirmConv.name}`} onClose={() => setConfirmConv(null)}>
          <p style={{ margin: "0 0 6px" }}>
            {t("سيُنشأ سجل عميل جديد في صفحة العملاء باسم ")}
            <strong>{confirmConv.company_name || confirmConv.name}</strong>
            {t(" وستُعلَّم المرحلة «تحوّل لعميل». متابعة؟")}
          </p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button className="btn btn-primary" disabled={busy} onClick={() => void doConvert(confirmConv)}>
              {busy ? t("جارٍ التحويل…") : t("نعم، تحويل")}
            </button>
            <button type="button" className="btn" onClick={() => setConfirmConv(null)}>{t("إلغاء")}</button>
          </div>
        </Modal>
      )}

      {confirmDel && (
        <Modal title={`${t("حذف العميل المحتمل — ")}${confirmDel.name}`} onClose={() => setConfirmDel(null)}>
          <p style={{ margin: "0 0 6px" }}>
            {t("هل أنت متأكد من حذف ")}<strong>{confirmDel.name}</strong>{t(" (")}{confirmDel.code}{t(")؟ سيُحذف مع كل أنشطة المتابعة. لا يمكن الرجوع بعد الحذف.")}
          </p>
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button className="btn-delete" disabled={busy} onClick={() => void doDelete(confirmDel)}>
              {busy ? t("جارٍ الحذف…") : t("نعم، حذف")}
            </button>
            <button type="button" className="btn" onClick={() => setConfirmDel(null)}>{t("إلغاء")}</button>
          </div>
        </Modal>
      )}
    </>
  );
}

/** خط البيع المرئي: أعمدة المراحل بسحب وإفلات البطاقات (نمط ScheduleBoard). */
function LeadKanban({ leads, loading, canUpdate, onMove, onOpenActs, onEdit, onQuote }: {
  leads: Lead[];
  loading: boolean;
  canUpdate: boolean;
  onMove: (leadId: number, newStatus: string) => void;
  onOpenActs: (l: Lead) => void;
  onEdit: (l: Lead) => void;
  onQuote: (l: Lead) => void;
}) {
  const { t } = useI18n();
  const [dragId, setDragId] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  if (loading) return <div className="card"><Loading /></div>;
  const now = Date.now();
  const isOverdue = (l: Lead) => l.next_follow_up_at && new Date(l.next_follow_up_at).getTime() < now && !["won", "lost"].includes(l.status);
  const isToday = (l: Lead) => l.next_follow_up_at && !isOverdue(l) && new Date(l.next_follow_up_at).toDateString() === new Date().toDateString();
  return (
    <div className="crm-kanban">
      {STAGES.map((s) => {
        const col = leads.filter((l) => l.status === s.key);
        const total = col.reduce((sum, l) => sum + Number(l.expected_value || 0), 0);
        return (
          <div
            key={s.key}
            className={`crm-col${dragOver === s.key ? " drag-over" : ""}`}
            onDragOver={(e) => { if (canUpdate) { e.preventDefault(); setDragOver(s.key); } }}
            onDragLeave={() => setDragOver((cur) => (cur === s.key ? null : cur))}
            onDrop={(e) => { e.preventDefault(); setDragOver(null); const id = dragId; setDragId(null); if (id != null) onMove(id, s.key); }}
          >
            <div className="crm-col-head" style={{ background: s.bg, color: s.color }}>
              <b>{t((STAGE_LABELS as any)[s.key])}</b>
              <span>{col.length} · {money(total)}</span>
            </div>
            <div className="crm-col-body">
              {col.length === 0 ? <div className="muted" style={{ fontSize: 12, textAlign: "center", padding: 10 }}>—</div> : col.map((l) => (
                <div
                  key={l.id}
                  className={`crm-card${dragId === l.id ? " dragging" : ""}${isOverdue(l) ? " crm-overdue" : ""}`}
                  draggable={canUpdate && l.status !== "won"}
                  onDragStart={() => setDragId(l.id)}
                  onDragEnd={() => { setDragId(null); setDragOver(null); }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                    <b>{l.name}</b>
                    <small className="muted" dir="ltr">{l.code}</small>
                  </div>
                  {l.company_name && <div style={{ fontSize: 12 }} className="muted">{l.company_name}</div>}
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginTop: 4 }}>
                    <span>{money(l.expected_value)}</span>
                    {l.phone && <a dir="ltr" href={`tel:${l.phone}`}>{l.phone}</a>}
                  </div>
                  {l.next_follow_up_at && (
                    <div style={{ fontSize: 11.5, marginTop: 4, color: isOverdue(l) ? "#b42318" : isToday(l) ? "#9a6700" : "#57606a" }}>
                      ⏰ {isOverdue(l) ? t("متأخرة: ") : ""}{dtLocal(l.next_follow_up_at)}
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
                    <button className="btn btn-sm" title={t("متابعة")} onClick={() => onOpenActs(l)}>📞</button>
                    <button className="btn btn-sm" title={t("تعديل")} onClick={() => onEdit(l)}>✏️</button>
                    {l.status !== "won" && l.status !== "lost" && (
                      <button className="btn btn-sm" title={t("عرض سعر")} onClick={() => onQuote(l)}>🧾</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

const STAGE_LABELS: Record<string, string> = {
  new: "جديد",
  contacted: "تم التواصل",
  qualified: "مؤهل",
  won: "تحوّل لعميل",
  lost: "مفقود",
};

/** أنشطة المتابعة: قائمة + إضافة مكالمة/اجتماع/ملاحظة. */
function ActivitiesModal({ lead, onClose }: { lead: Lead; onClose: () => void }) {
  const { t } = useI18n();
  const list = usePagedList<Activity>(`/crm/leads/${lead.id}/activities`, {});
  const [kind, setKind] = useState("note");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const KIND_LABELS: Record<string, string> = { note: "📝 ملاحظة", call: "📞 مكالمة", meeting: "🤝 اجتماع" };
  const KIND_COLORS: Record<string, string> = { note: "#57606a", call: "#0d47a1", meeting: "#6b21a8" };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.post(`/crm/leads/${lead.id}/activities`, { kind, body: body.trim() });
      setBody("");
      list.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`📞 ${t("متابعة — ")}${lead.name}`} onClose={onClose} wide>
      <form onSubmit={submit} style={{ marginBottom: 14 }}>
        <Alert>{error}</Alert>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field label={t("نوع النشاط")}>
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.keys(KIND_LABELS).map((k) => (
                <option key={k} value={k}>{t(KIND_LABELS[k])}</option>
              ))}
            </select>
          </Field>
          <div style={{ flex: 1, minWidth: 220 }}>
            <Field label={t("التفاصيل")}>
              <input value={body} onChange={(e) => setBody(e.target.value)} required placeholder={t("ما الذي حدث في هذه المتابعة؟")} />
            </Field>
          </div>
          <button className="btn btn-primary" disabled={busy || !body.trim()}>{busy ? t("…") : t("تسجيل")}</button>
        </div>
      </form>
      <div className="table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("النوع")}</th>
                <th>{t("التفاصيل")}</th>
                <th>{t("التاريخ")}</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((a) => (
                <tr key={a.id}>
                  <td>
                    <span className="badge" style={{ background: "#f6f8fa", color: KIND_COLORS[a.kind] ?? "#57606a", borderRadius: 999, padding: "2px 10px", fontSize: 12, fontWeight: 700 }}>
                      {t(KIND_LABELS[a.kind] ?? a.kind)}
                    </span>
                  </td>
                  <td>{a.body}</td>
                  <td>{dateTime(a.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا أنشطة متابعة بعد — سجل أول مكالمة أو اجتماع.")}</Empty>
        )}
      </div>
      <Pager list={list} />
    </Modal>
  );
}
