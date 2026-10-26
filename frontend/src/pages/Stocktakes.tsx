import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { dateTime, num } from "../format";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Stocktake, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader, Pager } from "../ui";

const STATUS: Record<Stocktake["status"], string> = { open: "مفتوح", applied: "تم الاعتماد", cancelled: "ملغي" };

function NewDialog({ onClose, onDone }: { onClose: () => void; onDone: (id: number) => void }) {
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?is_active=true&limit=500"), "st-wh");
  const [wh, setWh] = useState("");
  const [notes, setNotes] = useState("");
  const act = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void act.run(async () => {
      const s = await api.post<Stocktake>("/stocktakes", { warehouse_id: Number(wh), notes: notes || null });
      onDone(s.id);
    });
  };
  return (
    <Modal title="جرد جديد" onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{act.error || warehouses.error}</Alert>
        <Field label="المخزن" hint="يُعدّ مخزن واحد في كل مرة، وتُقارن الكميات المعدودة بما يخصه فقط.">
          <select value={wh} required onChange={(e) => setWh(e.target.value)} aria-label="مخزن الجرد">
            <option value="">— اختر المخزن —</option>
            {warehouses.data?.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="ملاحظات">
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="actions">
          <button className="btn btn-primary" disabled={act.busy || !wh}>إنشاء ورقة الجرد</button>
          <button type="button" className="btn" onClick={onClose}>إلغاء</button>
        </div>
      </form>
    </Modal>
  );
}

function DetailDialog({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const { isManager } = useAuth();
  const data = useFetch(() => api.get<Stocktake>(`/stocktakes/${id}`), `st-${id}`);
  const [draft, setDraft] = useState<Record<number, string>>({});
  const [confirmApply, setConfirmApply] = useState(false);
  const act = useAction();
  const s = data.data;
  const open = s?.status === "open";
  const dl = useAction();

  const shown = (productId: number, saved: number | null) => (productId in draft ? draft[productId] : saved === null ? "" : String(saved));
  const dirty = Object.keys(draft).length > 0;
  const bad = Object.values(draft).some((v) => v !== "" && (!/^\d+$/.test(v)));

  const save = () =>
    act.run(async () => {
      await api.put<Stocktake>(`/stocktakes/${id}/counts`, {
        counts: Object.entries(draft).map(([pid, v]) => ({ product_id: Number(pid), counted_qty: v === "" ? null : Number(v) })),
      });
      setDraft({});
      data.reload();
      onChanged();
    });
  const call = (path: string) =>
    act.run(async () => {
      await api.post<Stocktake>(`/stocktakes/${id}/${path}`);
      setConfirmApply(false);
      data.reload();
      onChanged();
    });

  return (
    <Modal title={`جرد #${id}${s?.warehouse_name ? ` — ${s.warehouse_name}` : ""}`} onClose={onClose} wide>
      <Alert>{act.error || data.error || dl.error}</Alert>
      {data.loading && !s ? (
        <Loading />
      ) : (
        s && (
          <>
            <p className="muted">
              {STATUS[s.status]} · أنشأه {s.username ?? "—"} · {dateTime(s.created_at)} · تم عدّ {num(s.lines_counted)} من {num(s.lines_total)} · فروقات: {num(s.lines_with_difference)}
            </p>
            <div className="table-wrap" style={{ maxHeight: "50vh", overflow: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>الكود</th>
                    <th>الصنف</th>
                    <th className="num">كمية النظام</th>
                    <th className="num">المعدود</th>
                    <th className="num">الفرق</th>
                  </tr>
                </thead>
                <tbody>
                  {s.lines?.map((l) => {
                    const v = shown(l.product_id, l.counted_qty);
                    const diff = v === "" || !/^\d+$/.test(v) ? null : Number(v) - l.system_qty;
                    return (
                      <tr key={l.product_id}>
                        <td dir="ltr">{l.sku}</td>
                        <td>{l.product_name}</td>
                        <td className="num">{num(l.system_qty)}</td>
                        <td className="num">
                          {open ? (
                            <input
                              type="number"
                              min="0"
                              step="1"
                              style={{ width: 90 }}
                              value={v}
                              aria-label={`المعدود ${l.product_name}`}
                              onChange={(e) => setDraft((d) => ({ ...d, [l.product_id]: e.target.value }))}
                            />
                          ) : l.counted_qty === null ? (
                            "—"
                          ) : (
                            num(l.counted_qty)
                          )}
                        </td>
                        <td className="num" style={diff ? { color: diff < 0 ? "#b42318" : "#1a7f37", fontWeight: 600 } : undefined}>
                          {diff === null ? "" : diff > 0 ? `+${diff}` : diff}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {confirmApply && (
              <Alert kind="info">
                سيتم تعديل كميات {num(s.lines_with_difference)} صنف بحسب الفروقات، ولا يمكن التراجع. هل تؤكد الاعتماد؟{" "}
                <button className="btn btn-sm btn-primary" disabled={act.busy} onClick={() => void call("apply")}>
                  نعم، اعتمد
                </button>{" "}
                <button className="btn btn-sm" onClick={() => setConfirmApply(false)}>
                  لا
                </button>
              </Alert>
            )}
            <div className="actions" style={{ marginTop: 12 }}>
              {open && (
                <button className="btn btn-primary" disabled={act.busy || !dirty || bad} onClick={() => void save()}>
                  حفظ الكميات المعدودة
                </button>
              )}
              {open && isManager && (
                <button className="btn" disabled={act.busy || dirty || s.lines_counted === 0} title={dirty ? "احفظ الكميات أولاً" : undefined} onClick={() => setConfirmApply(true)}>
                  اعتماد الفروقات
                </button>
              )}
              {open && (
                <button className="btn" disabled={act.busy} onClick={() => void call("cancel")}>
                  إلغاء الجرد
                </button>
              )}
              <button className="btn" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/stocktakes/${id}/xlsx`, `stocktake-${id}.xlsx`))}>
                ⬇ ورقة Excel
              </button>
            </div>
          </>
        )
      )}
    </Modal>
  );
}

export default function Stocktakes() {
  const list = usePagedList<Stocktake>("/stocktakes", {});
  const [creating, setCreating] = useState(false);
  const [viewId, setViewId] = useState<number | null>(null);
  return (
    <>
      <PageHeader title="الجرد">
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          جرد جديد
        </button>
      </PageHeader>
      <Alert>{list.error}</Alert>
      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>رقم</th>
                <th>التاريخ</th>
                <th>المخزن</th>
                <th>الحالة</th>
                <th className="num">المعدود</th>
                <th className="num">فروقات</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((s) => (
                <tr key={s.id}>
                  <td>#{s.id}</td>
                  <td>{dateTime(s.created_at)}</td>
                  <td>{s.warehouse_name ?? "كل المخازن"}</td>
                  <td>{STATUS[s.status]}</td>
                  <td className="num">
                    {num(s.lines_counted)} / {num(s.lines_total)}
                  </td>
                  <td className="num">{num(s.lines_with_difference)}</td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => setViewId(s.id)}>
                      فتح
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>لا توجد عمليات جرد بعد.</Empty>
        )}
        <Pager list={list} />
      </div>
      {creating && (
        <NewDialog
          onClose={() => setCreating(false)}
          onDone={(id) => {
            setCreating(false);
            list.reload();
            setViewId(id);
          }}
        />
      )}
      {viewId !== null && <DetailDialog id={viewId} onClose={() => setViewId(null)} onChanged={list.reload} />}
    </>
  );
}
