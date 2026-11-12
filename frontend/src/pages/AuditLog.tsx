import { useState } from "react";
import { dateTime } from "../format";
import { useI18n } from "../i18n";
import { usePagedList } from "../hooks";
import type { AuditEntry } from "../types";
import { Alert, Empty, Loading, PageHeader, Pager } from "../ui";

export default function AuditLog() {
  const { t } = useI18n();
  // Label maps moved into the component and built with t() so they render per-language.
  // Keys stay the raw API values (used only for select values / lookups, never compared).
  const ENTITY: Record<string, string> = {
    purchase_order: t("أمر شراء"),
    sales_order: t("أمر بيع"),
    payment: t("سند"),
    product: t("منتج"),
    customer: t("عميل"),
    supplier: t("مورد"),
    warehouse: t("مخزن"),
    user: t("مستخدم"),
    shift: t("وردية"),
    stocktake: t("جرد"),
    stock_transfer: t("تحويل مخزني"),
  };

  const ACTION: Record<string, string> = {
    create: t("إنشاء"),
    update: "edit",
    delete: "delete",
    receive: t("استلام"),
    confirm: t("تأكيد"),
    cancel: t("إلغاء"),
    void: t("إلغاء سند"),
    adjust_stock: t("تسوية مخزون"),
    opening_balance: t("تغيير رصيد أول المدة"),
    login: t("تسجيل دخول"),
    open: t("فتح"),
    apply: t("اعتماد"),
    close: t("إغلاق"),
  };
  const [entity, setEntity] = useState("");
  const [action, setAction] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const valid = !from || !to || from <= to;
  const list = usePagedList<AuditEntry>("/audit-logs", valid ? { entity, action, date_from: from, date_to: to } : { entity, action });

  return (
    <>
      <PageHeader title={t("سجل النشاط")} />
      <div className="card card-pad range-bar" style={{ marginBottom: 14 }}>
        <label className="range-field">
          <span className="field-label">{t("النوع")}</span>
          <select value={entity} onChange={(e) => setEntity(e.target.value)}>
            <option value="">{t("الكل")}</option>
            {Object.entries(ENTITY).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">{t("الإجراء")}</span>
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">{t("الكل")}</option>
            {Object.entries(ACTION).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="range-field">
          <span className="field-label">{t("من تاريخ")}</span>
          <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="range-field">
          <span className="field-label">{t("إلى تاريخ")}</span>
          <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>
      {!valid && <Alert>{t("تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.")}</Alert>}
      <Alert>{list.error}</Alert>
      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("الوقت")}</th>
                <th>{t("المستخدم")}</th>
                <th>{t("الإجراء")}</th>
                <th>{t("الكائن")}</th>
                <th>{t("التفاصيل")}</th>
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
          <Empty>{t("لا توجد أحداث مطابقة.")}</Empty>
        )}
        <Pager list={list} />
      </div>
    </>
  );
}
