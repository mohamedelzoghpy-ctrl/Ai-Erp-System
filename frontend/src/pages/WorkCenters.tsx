/** مراكز العمل: CRUD كامل + أداء كل مركز (أوامر/كميات منفذة/هالك/دقائق) — الـbackend جاهز في /work-centers. */
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { num } from "../format";
import { useAction, useFetch } from "../hooks";
import { useI18n } from "../i18n";
import type { WorkCenterPerfOut } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

interface WorkCenter {
  id: number;
  name: string;
  capacity_per_hour?: number | null;
  hourly_cost?: string | null;
  notes?: string | null;
  is_active: boolean;
}

export default function WorkCenters() {
  const { t } = useI18n();
  const centers = useFetch(() => api.get<WorkCenter[]>("/work-centers"), "work-centers");
  const perf = useFetch(
    () => api.get<WorkCenterPerfOut>("/production-orders/reports/work-centers"),
    "work-centers-perf"
  );
  const { busy, error, run } = useAction();
  const [msg, setMsg] = useState<string | null>(null);
  const [editing, setEditing] = useState<WorkCenter | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [name, setName] = useState("");
  const [capacity, setCapacity] = useState("");
  const [hourlyCost, setHourlyCost] = useState("");
  const [notes, setNotes] = useState("");

  const openCreate = () => {
    setEditing(null);
    setName("");
    setCapacity("");
    setHourlyCost("");
    setNotes("");
    setShowForm(true);
  };

  const openEdit = (wc: WorkCenter) => {
    setEditing(wc);
    setName(wc.name);
    setCapacity(wc.capacity_per_hour ? String(wc.capacity_per_hour) : "");
    setHourlyCost(wc.hourly_cost ? String(wc.hourly_cost) : "");
    setNotes(wc.notes ?? "");
    setShowForm(true);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    const payload = {
      name: name.trim(),
      capacity_per_hour: capacity ? Number(capacity) : null,
      hourly_cost: hourlyCost || null,
      notes: notes || null,
    };
    void run(async () => {
      if (editing) {
        await api.patch<WorkCenter>(`/work-centers/${editing.id}`, payload);
        setMsg(`✅ ${t("تم تحديث مركز العمل")}`);
      } else {
        await api.post<WorkCenter>("/work-centers", payload);
        setMsg(`✅ ${t("تمت إضافة مركز العمل")}`);
      }
      setShowForm(false);
      centers.reload();
      perf.reload();
    });
  };

  const remove = (wc: WorkCenter) => {
    if (!confirm(t("حذف مركز العمل؟ — يُرفض إن كان مرتبطاً بأوامر إنتاج"))) return;
    void run(async () => {
      await api.del(`/work-centers/${wc.id}`);
      setMsg(`🗑️ ${t("تم حذف مركز العمل")}`);
      centers.reload();
    });
  };

  const perfRow = (id: number) => (perf.data?.rows ?? []).find((r) => r.work_center_id === id);
  const centersList = centers.data ?? [];

  return (
    <>
      <PageHeader title={t("🏭 مراكز العمل")}>
        <button className="btn btn-primary" onClick={openCreate}>
          {t("+ مركز عمل")}
        </button>
      </PageHeader>

      {msg && <Alert kind="info">{msg}</Alert>}
      {error && <Alert kind="error">{error}</Alert>}
      {centers.loading && <Loading />}
      {centers.error && <Alert kind="error">{centers.error}</Alert>}

      {!centers.loading && centersList.length === 0 && <Empty>{t("لا مراكز عمل — أضف أول مركز لتوزيع عمليات التصنيع عليه")}</Empty>}

      {centersList.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("المركز")}</th>
                <th>{t("الطاقة/ساعة")}</th>
                <th>{t("تكلفة الساعة")}</th>
                <th>{t("أوامر منفذة")}</th>
                <th>{t("كمية منفذة")}</th>
                <th>{t("هالك")}</th>
                <th>{t("دقائق مخططة")}</th>
                <th>{t("الحالة")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {centersList.map((wc) => {
                const p = perfRow(wc.id);
                return (
                  <tr key={wc.id}>
                    <td>
                      <b>{wc.name}</b>
                      {wc.notes && <div className="muted" style={{ fontSize: 12 }}>{wc.notes}</div>}
                    </td>
                    <td className="num">{wc.capacity_per_hour ? num(wc.capacity_per_hour) : "—"}</td>
                    <td className="num">{wc.hourly_cost ? num(wc.hourly_cost) : "—"}</td>
                    <td className="num">{p ? num(p.orders_count) : "—"}</td>
                    <td className="num">{p ? num(p.qty_done) : "—"}</td>
                    <td className="num">{p ? num(p.qty_scrapped) : "—"}</td>
                    <td className="num">{p ? num(p.planned_minutes) : "—"}</td>
                    <td>
                      <span className={`badge ${wc.is_active ? "badge-confirmed" : "badge-off"}`}>
                        {wc.is_active ? t("نشط") : t("موقوف")}
                      </span>
                    </td>
                    <td>
                      <button className="btn-edit" onClick={() => openEdit(wc)}>{t("تعديل")}</button>{" "}
                      <button className="btn-del" onClick={() => remove(wc)}>{t("حذف")}</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <Modal title={editing ? t("تعديل مركز عمل") : t("مركز عمل جديد")} onClose={() => setShowForm(false)}>
          <form onSubmit={submit}>
            {error && <Alert kind="error">{error}</Alert>}
            <Field label={t("الاسم")}>
              <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus maxLength={150} />
            </Field>
            <Field label={t("الطاقة/ساعة (اختياري)")} hint={t("الكمية القابلة للتنفيذ في الساعة — تستخدم في جدولة الأوامر")}>
              <input type="number" min="0" step="0.01" value={capacity} onChange={(e) => setCapacity(e.target.value)} />
            </Field>
            <Field label={t("تكلفة الساعة (اختياري)")} hint={t("تُرحَّل تلقائياً كتكلفة عمالة على أوامر الإنتاج")}>
              <input type="number" min="0" step="0.01" value={hourlyCost} onChange={(e) => setHourlyCost(e.target.value)} />
            </Field>
            <Field label={t("ملاحظات (اختياري)")}>
              <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={200} />
            </Field>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={busy}>{t("حفظ")}</button>
              <button type="button" className="btn" onClick={() => setShowForm(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
