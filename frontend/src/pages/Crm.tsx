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
  const [view, setView] = useState<"table" | "kanban">("kanban");
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
      board.reload();
      setF(emptyForm);
      setNote(`${t("تم إضافة العميل المحتمل «")}${created.name}${t("» بكود ")}${created.code}${t(".")}`);
      leads.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
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
      <Pager list={leads} style={view === "kanban" ? { display: "none" } : undefined} />

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
function LeadKanban({ leads, loading, canUpdate, onMove, onOpenActs, onEdit }: {
  leads: Lead[];
  loading: boolean;
  canUpdate: boolean;
  onMove: (leadId: number, newStatus: string) => void;
  onOpenActs: (l: Lead) => void;
  onEdit: (l: Lead) => void;
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
                    <button className="btn btn-sm" onClick={() => onOpenActs(l)}>📞</button>
                    <button className="btn btn-sm" onClick={() => onEdit(l)}>✏️</button>
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
