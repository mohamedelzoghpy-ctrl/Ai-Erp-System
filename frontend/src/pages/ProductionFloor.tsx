import { useEffect, useState } from "react";
import { api } from "../api";
import { num } from "../format";
import { useAction, useFetch } from "../hooks";
import type { ProductionOrder } from "../types";
import { Alert, Empty, Field, Loading, Modal } from "../ui";
import type { FormEvent } from "react";

/** نقطة التشغيل: للعاملين — أوامر قيد التنفيذ فقط، بدون أي أرقام مالية. */
export default function ProductionFloor() {
  const orders = useFetch(() => api.get<ProductionOrder[]>("/production-orders?status=in_progress&limit=1000"), "floor-orders");
  const [produceFor, setProduceFor] = useState<ProductionOrder | null>(null);
  const [produceQty, setProduceQty] = useState("");
  const act = useAction();

  // تحديث دوري حتى يرى العامل الأوامر الجديدة بدون إعادة تحميل الصفحة
  useEffect(() => {
    const id = window.setInterval(() => orders.reload(), 30000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doProduce = (e: FormEvent) => {
    e.preventDefault();
    if (!produceFor) return;
    void act.run(async () => {
      await api.post(`/production-orders/${produceFor.id}/produce`, { qty: Number(produceQty) });
      setProduceFor(null);
      setProduceQty("");
      orders.reload();
    });
  };

  return (
    <>
      <Alert>{orders.error || act.error}</Alert>
      <div className="card table-wrap">
        {orders.loading && !orders.data ? (
          <Loading />
        ) : orders.data && orders.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>الرقم</th>
                <th>المنتج</th>
                <th>المخطط</th>
                <th>المنتج حتى الآن</th>
                <th>الهالك</th>
                <th>المتبقي</th>
                <th>إجراءات</th>
              </tr>
            </thead>
            <tbody>
              {orders.data.map((o) => {
                const remaining = o.qty_planned - o.qty_produced - o.qty_scrapped;
                return (
                  <tr key={o.id}>
                    <td dir="ltr">{o.code}</td>
                    <td>{o.product_name ?? `#${o.product_id}`}</td>
                    <td className="num">{num(o.qty_planned)}</td>
                    <td className="num">{num(o.qty_produced)}</td>
                    <td className="num">{o.qty_scrapped ? num(o.qty_scrapped) : "—"}</td>
                    <td className="num">{num(remaining)}</td>
                    <td className="actions">
                      <button className="btn btn-sm btn-primary" disabled={remaining <= 0} onClick={() => { setProduceFor(o); setProduceQty(String(remaining)); }}>
                        + تسجيل إنتاج
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <Empty>لا توجد أوامر قيد التنفيذ حاليًا.</Empty>
        )}
      </div>

      {produceFor && (
        <Modal title={`تسجيل إنتاج — ${produceFor.code}`} onClose={() => { setProduceFor(null); setProduceQty(""); }}>
          <form onSubmit={doProduce}>
            <Alert>{act.error}</Alert>
            <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
              المنتج: <b>{produceFor.product_name}</b> · المخطط: <b>{num(produceFor.qty_planned)}</b> · المنتج حتى الآن: <b>{num(produceFor.qty_produced)}</b> · المتبقي: <b>{num(produceFor.qty_planned - produceFor.qty_produced - produceFor.qty_scrapped)}</b>
            </p>
            <Field label="كمية الدفعة المنتجة">
              <input type="number" min="1" max={produceFor.qty_planned - produceFor.qty_produced - produceFor.qty_scrapped} step="1" value={produceQty} onChange={(e) => setProduceQty(e.target.value)} required autoFocus />
            </Field>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={act.busy}>
                {act.busy ? "جارٍ التسجيل…" : "تسجيل الإنتاج"}
              </button>
              <button type="button" className="btn" onClick={() => { setProduceFor(null); setProduceQty(""); }}>
                إلغاء
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
