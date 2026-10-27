import { useState, useRef, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api, getToken } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
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
  const { t } = useI18n();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [notes, setNotes] = useState("");
  const [valuation, setValuation] = useState("cost");
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
        valuation,
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
          <Field label={t("transfers.from") + " " + t("common.warehouse")}>
            <select value={from} onChange={(e) => changeFrom(e.target.value)} aria-label={t("transfers.from")} required>
              <option value="">— {t("common.none")} —</option>
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
                        delete
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
        <Field label="تقييم التحويل">
          <select value={valuation} onChange={(e) => setValuation(e.target.value as "cost" | "sale")} aria-label="تقييم التحويل">
            <option value="cost">سعر التكلفة</option>
            <option value="sale">سعر البيع</option>
          </select>
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

function EditTransfer({ t, onClose, onDone }: { t: StockTransfer; onClose: () => void; onDone: () => void }) {
  const warehouses = useFetch(() => api.get<Warehouse[]>("warehouses?is_active=true&limit=500"), "edit-tr-wh");
  const products = useFetch(() => api.get<Product[]>("products?limit=1000&is_active=true"), "edit-tr-prod");
  const [from, setFrom] = useState(String(t.from_warehouse_id));
  const [to, setTo] = useState(String(t.to_warehouse_id));
  const [notes, setNotes] = useState(t.notes ?? "");
  const [valuation, setValuation] = useState(t.valuation ?? "cost");
  const [lines, setLines] = useState<Line[]>([]);
  const [picked, setPicked] = useState<Product | null>(null);
  const act = useAction();
  const initialized = useRef(false);

  // initialize lines once products load
  if (products.data && !initialized.current) {
    const byId = new Map(products.data.map((p) => [p.id, p]));
    const init: Line[] = [];
    for (const it of t.items) {
      const p = byId.get(it.product_id);
      if (p) init.push({ product: p, quantity: String(it.quantity) });
    }
    setLines(init);
    initialized.current = true;
  }

  const valid =
    !!from && !!to && from !== to && lines.length > 0 &&
    lines.every((l) => Number.isInteger(Number(l.quantity)) && Number(l.quantity) > 0);

  const addPicked = (p: Product | null) => {
    setPicked(null);
    if (!p) return;
    setLines((ls) => (ls.some((l) => l.product.id === p.id) ? ls : [...ls, { product: p, quantity: "1" }]));
  };
  const changeFrom = (v: string) => { setFrom(v); setLines([]); };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void act.run(async () => {
      await api.put(`/stock-transfers/${t.id}/edit`, {
        from_warehouse_id: Number(from),
        to_warehouse_id: Number(to),
        notes: notes || null,
        valuation,
        items: lines.map((l) => ({ product_id: l.product.id, quantity: Number(l.quantity) })),
      });
      onDone();
    });
  };

  return (
    <Modal title={`edit تحويل TR-${t.id}`} onClose={onClose} wide>
      <form onSubmit={submit}>
        <Alert>{act.error || warehouses.error || products.error}</Alert>
        {products.loading && !products.data ? <Loading /> : (
          <>
            <div className="grid-2">
              <Field label="من مخزن">
                <select value={from} onChange={(e) => changeFrom(e.target.value)} required>
                  <option value="">— اختر —</option>
                  {warehouses.data?.map((w) => (<option key={w.id} value={w.id}>{w.name}</option>))}
                </select>
              </Field>
              <Field label="إلى مخزن">
                <select value={to} onChange={(e) => setTo(e.target.value)} required>
                  <option value="">— اختر —</option>
                  {warehouses.data?.filter((w) => String(w.id) !== from).map((w) => (<option key={w.id} value={w.id}>{w.name}</option>))}
                </select>
              </Field>
            </div>
            <Field label="إضافة صنف">
              <Lookup<Product>
                key={`${from}-${lines.length}`}
                path="/products"
                params={{ is_active: true, ...(from ? { stock_warehouse_id: Number(from) } : {}) }}
                value={picked}
                onChange={addPicked}
                label={(p) => `${p.name} (${p.sku}) — متاح ${num(p.warehouse_quantity ?? 0)}`}
                text={(p) => p.name}
                placeholder="ابحث عن صنف…"
              />
            </Field>
            {lines.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>الصنف</th><th className="num">الكمية</th><th /></tr></thead>
                  <tbody>
                    {lines.map((l) => (
                      <tr key={l.product.id}>
                        <td>{l.product.name} ({l.product.sku})</td>
                        <td className="num">
                          <input type="number" min="1" step="1" style={{ width: 90 }} value={l.quantity}
                            onChange={(e) => setLines((ls) => ls.map((x) => x.product.id === l.product.id ? { ...x, quantity: e.target.value } : x))} />
                        </td>
                        <td className="actions">
                          <button type="button" className="btn btn-sm btn-danger" onClick={() => setLines((ls) => ls.filter((x) => x.product.id !== l.product.id))}>delete</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Field label="ملاحظات"><input value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
            <Field label="تقييم التحويل">
              <select value={valuation} onChange={(e) => setValuation(e.target.value as "cost" | "sale")}>
                <option value="cost">سعر التكلفة</option>
                <option value="sale">سعر البيع</option>
              </select>
            </Field>
            <div className="actions">
              <button className="btn btn-primary" disabled={!valid || act.busy}>حفظ الeditات</button>
              <button type="button" className="btn" onClick={onClose}>إلغاء</button>
            </div>
          </>
        )}
      </form>
    </Modal>
  );
}
function ViewTransfer({ t, onClose, onApprove, onReject, onEdit }: { t: StockTransfer; onClose: () => void; onApprove?: (t: StockTransfer) => void; onReject?: (t: StockTransfer) => void; onEdit?: (t: StockTransfer) => void }) {
  const dl = useAction();

  return (
    <Modal title={`تحويل TR-${t.id}`} onClose={onClose} wide>
      <Alert>{dl.error}</Alert>
      <p>
        من <b>{t.from_warehouse_name}</b> إلى <b>{t.to_warehouse_name}</b> · {dateTime(t.created_at)} · {t.username ?? "—"}
      </p>
      <p className="muted">تقييم التحويل: {t.valuation === "sale" ? "سعر البيع" : "سعر التكلفة"}</p>
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
        {t.status === "approved" && onEdit && (
          <button className="btn btn-primary" onClick={() => onEdit(t)}>
            edit
          </button>
        )}
        <button className="btn" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/stock-transfers/${t.id}/pdf`, `transfer-TR-${t.id}.pdf`))}>
          ⬇ سند التحويل PDF
        </button>
        <button className="btn" disabled={dl.busy} onClick={() => void dl.run(async () => {
          const url = `/api/stock-transfers/${t.id}/pdf?token=${encodeURIComponent(getToken() ?? "")}`;
          const res = await fetch(url);
          if (!res.ok) throw new Error("تعذّر تحميل السند");
          const blob = await res.blob();
          const objUrl = URL.createObjectURL(blob);
          const iframe = document.createElement("iframe");
          iframe.style.position = "fixed";
          iframe.style.right = "0";
          iframe.style.bottom = "0";
          iframe.style.width = "0";
          iframe.style.height = "0";
          iframe.style.border = "0";
          iframe.src = objUrl;
          document.body.appendChild(iframe);
          iframe.onload = () => {
            try {
              iframe.contentWindow?.focus();
              iframe.contentWindow?.print();
            } catch {
              window.open(objUrl, "_blank");
            }
            setTimeout(() => {
              document.body.removeChild(iframe);
              URL.revokeObjectURL(objUrl);
            }, 60_000);
          };
        })}>
          🖨 طباعة
        </button>
      </div>
    </Modal>
  );
}

export default function Transfers() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { isManager, user } = useAuth();
  const { t } = useI18n();
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") ?? "");
  // keep URL in sync when filter changes
  // (simple: update on change)
  const pending = useFetch(() => (isManager ? api.get<{ count: number }>("/stock-transfers/pending-count") : Promise.resolve({ count: 0 })), "pending-transfers");
  const pendingCount = pending.data?.count ?? 0;
  const list = usePagedList<StockTransfer>("/stock-transfers", { status: statusFilter || undefined });
  const [creating, setCreating] = useState(false);
  const [view, setView] = useState<StockTransfer | null>(null);
  const [editing, setEditing] = useState<StockTransfer | null>(null);
  const act = useAction();

  const approve = (trf: StockTransfer) => {
    void act.run(async () => {
      await api.post(`/stock-transfers/${trf.id}/approve`);
      list.reload();
      if (view?.id === trf.id) setView(null);
    });
  };
  const reject = (trf: StockTransfer) => {
    const reason = prompt(t("transfers.rejectionReason") + " (اختياري):") ?? undefined;
    void act.run(async () => {
      await api.post(`/stock-transfers/${trf.id}/reject${reason ? `?reason=${encodeURIComponent(reason)}` : ""}`);
      list.reload();
      if (view?.id === trf.id) setView(null);
    });
  };
  const remove = (trf: StockTransfer) => {
    if (!confirm(`${t("common.delete")} TR-${trf.id}؟`)) return;
    void act.run(async () => {
      await api.del(`/stock-transfers/${trf.id}`);
      list.reload();
    });
  };

  const statusBadge = (s: StockTransfer["status"]) => {
    const map: Record<string, { label: string; cls: string }> = {
      pending: { label: t("transfers.pending"), cls: "badge badge-warn" },
      approved: { label: t("transfers.approved"), cls: "badge badge-ok" },
      rejected: { label: t("transfers.rejected"), cls: "badge badge-off" },
    };
    const v = map[s] ?? { label: s, cls: "badge" };
    return <span className={v.cls}>{v.label}</span>;
  };

  return (
    <>
      <PageHeader title={t("transfers.title")}>
        {isManager && (
          <a
            className="btn"
            href="/transfers?status=pending"
            style={{ position: "relative", textDecoration: "none" }}
            title={t("transfers.pending")}
          >
            🔔
            {(pendingCount ?? 0) > 0 && (
              <span
                style={{
                  position: "absolute",
                  top: -6,
                  insetInlineEnd: -6,
                  background: "var(--danger, #dc2626)",
                  color: "#fff",
                  borderRadius: 999,
                  fontSize: 11,
                  padding: "1px 5px",
                  lineHeight: 1,
                }}
              >
                {pendingCount}
              </span>
            )}
          </a>
        )}
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          {t("transfers.new")}
        </button>
      </PageHeader>
      <Alert>{list.error || act.error}</Alert>
      <div className="toolbar page-actions" style={{ marginBottom: 14 }}>
        <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setSearchParams(e.target.value ? { status: e.target.value } : {}); }} aria-label={t("transfers.status")}>
          <option value="">{t("transfers.allStatuses")}</option>
          <option value="pending">{t("transfers.pending")}</option>
          <option value="approved">{t("transfers.approved")}</option>
          <option value="rejected">{t("transfers.rejected")}</option>
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
                <th>{t("common.date") ?? "التاريخ"}</th>
                <th>{t("transfers.from")}</th>
                <th>{t("transfers.to")}</th>
                <th className="num">{t("transfers.items")}</th>
                <th>{t("transfers.status")}</th>
                <th>{t("transfers.user")}</th>
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
                    {((t.status === "pending" && (isManager || t.username === user?.username)) || (t.status !== "pending" && isManager)) && (
                      <button className="btn btn-sm btn-danger" disabled={act.busy} onClick={() => remove(t)}>
                        delete
                      </button>
                    )}
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
                        delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("transfers.empty")}</Empty>
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
      {view && <ViewTransfer t={view} onClose={() => setView(null)} onApprove={isManager ? approve : undefined} onReject={isManager ? reject : undefined} onEdit={isManager ? (t) => { setView(null); setEditing(t); } : undefined} />}
      {editing && <EditTransfer t={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); list.reload(); }} />}
    </>
  );
}
