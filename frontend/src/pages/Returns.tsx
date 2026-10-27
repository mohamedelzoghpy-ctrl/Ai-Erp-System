import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";
import { dateTime, METHOD_LABEL, money, num } from "../format";
import { useAction, usePagedList } from "../hooks";
import type { Order, PaymentMethod, ReturnDoc } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader, Pager } from "../ui";

interface DialogCfg {
  returnPath: string;
  returnWord: string;
  refundLabel: string;
  priceField: "unit_cost" | "unit_price";
}

/** Records a return against a confirmed sale / received purchase order. */
export function ReturnDialog({ cfg, order, onClose, onDone }: { cfg: DialogCfg; order: Order; onClose: () => void; onDone: () => void }) {
  const lines = order.items.map((i) => ({ item: i, left: i.quantity - (i.returned_quantity ?? 0), price: Number(i[cfg.priceField] ?? 0) }));
  const [qty, setQty] = useState<Record<number, string>>({});
  const [refund, setRefund] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [notes, setNotes] = useState("");
  const { busy, error, run } = useAction();

  const chosen = lines.filter((l) => Number(qty[l.item.id]) > 0);
  const total = chosen.reduce((s, l) => s + Number(qty[l.item.id]) * l.price, 0);
  const refundNum = refund === "" ? 0 : Number(refund);
  const valid = chosen.length > 0 && chosen.every((l) => Number.isInteger(Number(qty[l.item.id])) && Number(qty[l.item.id]) <= l.left) && refundNum >= 0 && refundNum <= total + 1e-9;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    void run(async () => {
      await api.post(cfg.returnPath, {
        order_id: order.id,
        items: chosen.map((l) => ({ order_item_id: l.item.id, quantity: Number(qty[l.item.id]) })),
        refund_amount: String(refundNum),
        method,
        notes: notes.trim() || null,
      });
      onDone();
    });
  };

  return (
    <Modal title={`${cfg.returnWord} — أمر #${order.id}`} onClose={onClose} wide>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <table className="lines">
          <thead>
            <tr>
              <th>المنتج</th>
              <th className="num">المباع/المستلم</th>
              <th className="num">سبق إرجاعه</th>
              <th style={{ width: 110 }}>كمية المرتجع</th>
              <th className="num">القيمة</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.item.id}>
                <td>{l.item.product_name ?? `#${l.item.product_id}`}</td>
                <td className="num">{num(l.item.quantity)}</td>
                <td className="num">{num(l.item.returned_quantity ?? 0)}</td>
                <td>
                  <input
                    type="number"
                    min="0"
                    max={l.left}
                    step="1"
                    disabled={l.left === 0}
                    aria-label={`كمية مرتجع ${l.item.product_name ?? l.item.product_id}`}
                    value={qty[l.item.id] ?? ""}
                    onChange={(e) => setQty((q) => ({ ...q, [l.item.id]: e.target.value }))}
                  />
                </td>
                <td className="num">{money((Number(qty[l.item.id]) || 0) * l.price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="total-row">
          <span>إجمالي المرتجع</span>
          <span>{money(total)}</span>
        </div>
        <div className="form-grid">
          <Field label={cfg.refundLabel} hint={`الباقي (${money(Math.max(total - refundNum, 0))}) يُخصم من الرصيد`}>
            <input dir="ltr" type="number" min="0" max={total || undefined} step="0.01" value={refund} placeholder="0" onChange={(e) => setRefund(e.target.value)} />
          </Field>
          <Field label="طريقة الرد">
            <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}>
              {(Object.keys(METHOD_LABEL) as PaymentMethod[]).map((m) => (
                <option key={m} value={m}>
                  {METHOD_LABEL[m]}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="ملاحظات / سبب الإرجاع">
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>المرتجع نهائي ولا يمكن editه أو إلغاؤه بعد الحفظ؛ يتم تحديث المخزون والرصيد فوراً.</p>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy || !valid}>
            {busy ? "جارٍ الحفظ…" : "تسجيل المرتجع"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            إلغاء
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** List of all returns, one tab per direction. */
export default function Returns() {
  const { t } = useI18n();
  const [kind, setKind] = useState<"sales" | "purchase">("sales");
  const list = usePagedList<ReturnDoc>(kind === "sales" ? "/sales-returns" : "/purchase-returns", {});
  const [open, setOpen] = useState<ReturnDoc | null>(null);

  return (
    <>
      <PageHeader title={t("returns.title")} />
      <div className="tabs" role="tablist">
        {(["sales", "purchase"] as const).map((k) => (
          <button key={k} role="tab" aria-selected={kind === k} className={`tab${kind === k ? " active" : ""}`} onClick={() => setKind(k)}>
            {k === "sales" ? t("returns.sales") : t("returns.purchases")}
          </button>
        ))}
      </div>
      <p className="muted" style={{ marginTop: 0 }}>لتسجيل مرتجع افتح الأمر الأصلي من «أوامر البيع/الشراء» واضغط «تسجيل مرتجع».</p>
      <Alert>{list.error}</Alert>
      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>الرقم</th>
                <th>التاريخ</th>
                <th>الأمر</th>
                <th>{kind === "sales" ? "العميل" : "المورد"}</th>
                <th className="num">الإجمالي</th>
                <th className="num">رد نقدي</th>
                <th>ملاحظات</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((r) => (
                <tr key={r.id}>
                  <td dir="ltr">
                    {kind === "sales" ? "SR" : "PR"}-{r.id}
                  </td>
                  <td>{dateTime(r.created_at)}</td>
                  <td>#{r.order_id}</td>
                  <td>{r.party_name ?? "—"}</td>
                  <td className="num">{money(r.total_amount)}</td>
                  <td className="num">{Number(r.refund_amount) ? money(r.refund_amount) : "—"}</td>
                  <td>{r.notes ?? ""}</td>
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => setOpen(r)}>
                      عرض
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("returns.empty")}</Empty>
        )}
        <Pager list={list} />
      </div>
      {open && (
        <Modal title={`${kind === "sales" ? "SR" : "PR"}-${open.id} — ${open.party_name ?? ""}`} onClose={() => setOpen(null)}>
          <table>
            <thead>
              <tr>
                <th>{t("returns.product")}</th>
                <th className="num">{t("returns.qty")}</th>
                <th className="num">{t("returns.price")}</th>
                <th className="num">{t("returns.value")}</th>
              </tr>
            </thead>
            <tbody>
              {open.items.map((i) => (
                <tr key={i.id}>
                  <td>{i.product_name ?? `#${i.product_id}`}</td>
                  <td className="num">{num(i.quantity)}</td>
                  <td className="num">{money(i.unit_price)}</td>
                  <td className="num">{money(Number(i.unit_price) * i.quantity)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ marginBottom: 0 }}>
            الإجمالي: <b>{money(open.total_amount)}</b> · مردود نقداً: <b>{money(open.refund_amount)}</b> ({METHOD_LABEL[open.method]})
          </p>
        </Modal>
      )}
    </>
  );
}
