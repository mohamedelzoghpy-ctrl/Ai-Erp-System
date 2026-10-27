import { useState } from "react";
import { dateTime } from "../format";
import { usePagedList } from "../hooks";
import type { AuditEntry } from "../types";
import { Alert, Empty, Loading, PageHeader, Pager } from "../ui";

const ENTITY: Record<string, string> = {
  purchase_order: "أمر شراء",
  sales_order: "أمر بيع",
  payment: "سند",
  product: "منتج",
  customer: "عميل",
  supplier: "مورد",
  warehouse: "مخزن",
  user: "مستخدم",
  shift: "وردية",
  stocktake: "جرد",
  stock_transfer: "تحويل مخزني",
};

const ACTION: Record<string, string> = {
  create: "إنشاء",
  update: "edit",
  delete: "حذف",
  receive: "استلام",
  confirm: "تأكيد",
  cancel: "إلغاء",
  void: "إلغاء سند",
  adjust_stock: "تسوية مخزون",
  opening_balance: "تغيير رصيد أول المدة",
  login: "تسجيل دخول",
  open: "فتح",
  apply: "اعتماد",
  close: "إغلاق",
};

export default function AuditLog() {
  const [entity, setEntity] = useState("");
  const [action, setAction] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const valid = !from || !to || from <= to;
  const list = usePagedList<AuditEntry>("/audit-logs", valid ? { entity, action, date_from: from, date_to: to } : { entity, action });

  return (
    <>
      <PageHeader title="سجل النشاط" />
      <div className="card card-pad range-bar" style={{ marginBottom: 14 }}>
        <label className="range-field">
          <span className="field-label">النوع</span>
          <select value={entity} onChange={(e) => setEntity(e.target.value)}>
            <option value="">الكل</option>
            {Object.entries(ENTITY).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">الإجراء</span>
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">الكل</option>
            {Object.entries(ACTION).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">من تاريخ</span>
          <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="range-field">
          <span className="field-label">إلى تاريخ</span>
          <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>
      {!valid && <Alert>تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.</Alert>}
      <Alert>{list.error}</Alert>
      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>الوقت</th>
                <th>المستخدم</th>
                <th>الإجراء</th>
                <th>الكائن</th>
                <th>التفاصيل</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((x) => (
                <tr key={x.id}>
                  <td>{dateTime(x.created_at)}</td>
                  <td dir="ltr">{x.username ?? "—"}</td>
                  <td>{ACTION[x.action] ?? x.action}</td>
                  <td>
                    {ENTITY[x.entity] ?? x.entity}
                    {x.entity_id != null && x.action !== "login" ? ` #${x.entity_id}` : ""}
                  </td>
                  <td>{x.summary ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>لا توجد أحداث مطابقة.</Empty>
        )}
        <Pager list={list} />
      </div>
    </>
  );
}
