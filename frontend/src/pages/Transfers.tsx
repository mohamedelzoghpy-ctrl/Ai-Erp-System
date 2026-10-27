import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { dateTime, num } from "../format";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Product, StockTransfer, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, Lookup, Modal, PageHeader, Pager } from "../ui";

interface Line {
  product: Product;
  quantity: string;
}

function NewTransfer({ onClose, onDone }: { onClose: () => void; onDone: (t: StockTransfer) => void }) {
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?is_active=true&limit=500"), "tr-wh");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [picked, setPicked] = useState<Product | null>(null);
  const act = useAction();

  const have = (p: Product) => p.warehouse_quantity ?? 0;
  const over = lines.filter((l) => Number(l.quantity) > have(l.product));
  const valid =
    !!from &&
    !!to &&
    from !== to &&
    lines.length > 0 &&
    lines.every((l) => Number.isInteger(Number(l.quantity)) && Number(l.quantity) > 0) &&
    over.length === 0;

  const addPicked = (p: Product | null) => {
    setPicked(null);
    if (!p) return;
    setLines((ls) => (ls.some((l) => l.product.id === p.id) ? ls : [...ls, { product: p, quantity: "1" }]));
  };
  const changeFrom = (v: string) => {
    setFrom(v);
    setLines([]); // available quantities belong to the source warehouse
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void act.run(async () => {
      const t = await api.post<StockTransfer>("/stock-transfers", {
        from_warehouse_id: Number(from),
        to_warehouse_id: Number(to),
        notes: notes || null,
        items: lines.map((l) => ({ product_id: l.product.id, quantity: Number(l.quantity) })),
      });
      onDone(t);
    });
  };

  return (
    <Modal title="تحويل بين المخازن" onClose={onClose} wide>
      <form onSubmit={submit}>
        <Alert>{act.error || warehouses.error}</Alert>
        <div className="grid-2">
          <Field label="من مخزن">
            <select value={from} onChange={(e) => changeFrom(e.target.value)} aria-label="من مخزن" required>
              <option value="">— اختر —</option>
              {warehouses.data?.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="إلى مخزن">
            <select value={to} onChange={(e) => setTo(e.target.value)} aria-label="إلى مخزن" required>
              <option value="">— اختر —</option>
              {warehouses.data
                ?.filter((w) => String(w.id) !== from)
                .map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
            </select>
          </Field>
        </div>
        {from && (
          <Field label="إضافة صنف" hint="تظهر الكمية المتاحة في المخزن المصدر.">
            <Lookup<Product>
              key={`${from}-${lines.length}`}
              path="/products"
              params={{ is_active: true, stock_warehouse_id: Number(from) }}
              value={picked}
              onChange={addPicked}
              label={(p) => `${p.name} (${p.sku}) — متاح ${num(p.warehouse_quantity ?? 0)}`}
              text={(p) => p.name}
              placeholder="ابحث عن صنف…"
            />
          </Field>
        )}
        {lines.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>الصنف</th>
                  <th className="num">المتاح</th>
                  <th className="num">الكمية</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.product.id}>
                    <td>
                      {l.product.name}{" "}
                      <span className="muted" dir="ltr">
                        {l.product.sku}
                      </span>
                    </td>
                    <td className="num">{num(have(l.product))}</td>
                    <td className="num">
                      <input
                        type="number"
                        min="1"
                        step="1"
                        style={{ width: 90 }}
                        value={l.quantity}
                        aria-label={`كمية ${l.product.name}`}
                        onChange={(e) => setLines((ls) => ls.map((x) => (x.product.id === l.product.id ? { ...x, quantity: e.target.value } : x)))}
                      />
                      {Number(l.quantity) > have(l.product) && <div className="muted">المتاح {num(have(l.product))} فقط</div>}
                    </td>
                    <td>
                      <button type="button" className="btn btn-sm" onClick={() => setLines((ls) => ls.filter((x) => x.product.id !== l.product.id))}>
                        حذف
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Field label="ملاحظات">
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="actions">
          <button className="btn btn-primary" disabled={!valid || act.busy}>
            تنفيذ التحويل
          </button>
          <button type="button" className="btn" onClick={onClose}>
            إلغاء
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ViewTransfer({ t, onClose, onApprove, onReject }: { t: StockTransfer; onClose: () => void; onApprove?: (t: StockTransfer) => void; onReject?: (t: StockTransfer) => void }) {
  const dl = useAction();
  return (
    <Modal title={`تحويل TR-${t.id}`} onClose={onClose}>
      <Alert>{dl.error}</Alert>
      <p>
        من <b>{t.from_warehouse_name}</b> إلى <b>{t.to_warehouse_name}</b> · {dateTime(t.created_at)} · {t.username ?? "—"}
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>الكود</th>
              <th>الصنف</th>
              <th className="num">الكمية</th>
            </tr>
          </thead>
          <tbody>
            {t.items.map((i) => (
              <tr key={i.product_id}>
                <td dir="ltr">{i.sku}</td>
                <td>{i.product_name}</td>
                <td className="num">{num(i.quantity)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {t.notes && <p className="muted">ملاحظات: {t.notes}</p>}
      {t.rejection_reason && <p className="muted" style={{ color: "var(--danger)" }}>سبب الرفض: {t.rejection_reason}</p>}
      <div className="actions">
        {t.status === "pending" && onApprove && (
          <button className="btn btn-primary" onClick={() => onApprove(t)}>
            اعتماد
          </button>
        )}
        {t.status === "pending" && onReject && (
          <button className="btn btn-danger" onClick={() => onReject(t)}>
            رفض
          </button>
        )}
        <button className="btn" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/stock-transfers/${t.id}/pdf`, `transfer-TR-${t.id}.pdf`))}>
          ⬇ سند التحويل PDF
        </button>
      </div>
    </Modal>
  );
}

export default function Transfers() {
  const { isManager } = useAuth();
  const [statusFilter, setStatusFilter] = useState("");
  const list = usePagedList<StockTransfer>("/stock-transfers", { status: statusFilter || undefined });
  const [creating, setCreating] = useState(false);
  const [view, setView] = useState<StockTransfer | null>(null);
  const act = useAction();

  const approve = (t: StockTransfer) => {
    void act.run(async () => {
      await api.post(`/stock-transfers/${t.id}/approve`);
      list.reload();
      if (view?.id === t.id) setView(null);
    });
  };
  const reject = (t: StockTransfer) => {
    const reason = prompt("سبب الرفض (اختياري):") ?? undefined;
    void act.run(async () => {
      await api.post(`/stock-transfers/${t.id}/reject${reason ? `?reason=${encodeURIComponent(reason)}` : ""}`);
      list.reload();
      if (view?.id === t.id) setView(null);
    });
  };
  const remove = (t: StockTransfer) => {
    if (!confirm(`حذف التحويل TR-${t.id}؟`)) return;
    void act.run(async () => {
      await api.del(`/stock-transfers/${t.id}`);
      list.reload();
    });
  };

  const statusBadge = (s: StockTransfer["status"]) => {
    const map: Record<string, { label: string; cls: string }> = {
      pending: { label: "قيد الانتظار", cls: "badge badge-warn" },
      approved: { label: "معتمد", cls: "badge badge-ok" },
      rejected: { label: "مرفوض", cls: "badge badge-off" },
    };
    const v = map[s] ?? { label: s, cls: "badge" };
    return <span className={v.cls}>{v.label}</span>;
  };

  return (
    <>
      <PageHeader title="التحويلات المخزنية">
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          تحويل جديد
        </button>
      </PageHeader>
      <Alert>{list.error || act.error}</Alert>
      <div className="toolbar page-actions" style={{ marginBottom: 14 }}>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="الحالة">
          <option value="">كل الحالات</option>
          <option value="pending">قيد الانتظار</option>
          <option value="approved">معتمد</option>
          <option value="rejected">مرفوض</option>
        </select>
      </div>
      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>رقم</th>
                <th>التاريخ</th>
                <th>من</th>
                <th>إلى</th>
                <th className="num">الأصناف</th>
                <th>الحالة</th>
                <th>المستخدم</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((t) => (
                <tr key={t.id}>
                  <td>TR-{t.id}</td>
                  <td>{dateTime(t.created_at)}</td>
                  <td>{t.from_warehouse_name}</td>
                  <td>{t.to_warehouse_name}</td>
                  <td className="num">{num(t.items.length)}</td>
                  <td>{statusBadge(t.status)}</td>
                  <td dir="ltr">{t.username ?? "—"}</td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => setView(t)}>
                      عرض
                    </button>
                    {isManager && t.status === "pending" && (
                      <>
                        <button className="btn btn-sm btn-primary" disabled={act.busy} onClick={() => approve(t)}>
                          اعتماد
                        </button>
                        <button className="btn btn-sm btn-danger" disabled={act.busy} onClick={() => reject(t)}>
                          رفض
                        </button>
                      </>
                    )}
                    {t.status === "pending" && (t.username === null || true) && (
                      <button className="btn btn-sm" disabled={act.busy} onClick={() => remove(t)}>
                        حذف
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>لا توجد تحويلات.</Empty>
        )}
        <Pager list={list} />
      </div>
      {creating && (
        <NewTransfer
          onClose={() => setCreating(false)}
          onDone={(t) => {
            setCreating(false);
            list.reload();
            setView(t);
          }}
        />
      )}
      {view && <ViewTransfer t={view} onClose={() => setView(null)} onApprove={isManager ? approve : undefined} onReject={isManager ? reject : undefined} />}
    </>
  );
}
