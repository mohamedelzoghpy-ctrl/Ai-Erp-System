import { useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";
import { money, num } from "../format";
import { useFetch } from "../hooks";
import type { Product, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, PageHeader } from "../ui";

export default function WarehouseBalances() {
  const { t } = useI18n();
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?is_active=true&limit=500"), "wb-wh");
  const [warehouseId, setWarehouseId] = useState("");

  const products = useFetch(
    () => (warehouseId ? api.get<Product[]>(`/products?stock_warehouse_id=${warehouseId}&limit=1000&is_active=true`) : Promise.resolve([])),
    `wb-prod-${warehouseId}`,
  );

  const rows = products.data ?? [];
  const totalQty = rows.reduce((s, p) => s + (p.warehouse_quantity ?? 0), 0);
  const totalCost = rows.reduce((s, p) => s + (p.warehouse_quantity ?? 0) * Number(p.cost_price), 0);
  const totalSale = rows.reduce((s, p) => s + (p.warehouse_quantity ?? 0) * Number(p.sale_price), 0);

  const selWarehouse = warehouses.data?.find((w) => String(w.id) === warehouseId);

  return (
    <>
      <PageHeader title={t("warehouseBalances.title")}>
        {warehouseId && rows.length > 0 && (
          <button className="btn" onClick={() => {
            const w = window.open("", "_blank");
            if (!w) return;
            const rowsHtml = rows.map((p) => {
              const q = p.warehouse_quantity ?? 0;
              return `<tr>
                <td>${p.sku}</td>
                <td>${p.name}</td>
                <td>${num(q)}</td>
                <td>${money(p.cost_price)}</td>
                <td>${money(p.sale_price)}</td>
                <td>${money(q * Number(p.cost_price))}</td>
                <td>${money(q * Number(p.sale_price))}</td>
              </tr>`;
            }).join("");
            w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>${t("warehouseBalances.title")}</title>
              <style>
                body { font-family: Tahoma, Arial, sans-serif; padding: 16px; }
                h1 { text-align: center; }
                table { width: 100%; border-collapse: collapse; }
                th, td { border: 1px solid #999; padding: 6px 8px; text-align: center; }
                th { background: #eee; }
                tfoot td { font-weight: bold; background: #f3f4f6; }
              </style></head><body>
              <h1>${t("warehouseBalances.title")} — ${selWarehouse?.name ?? ""}</h1>
              <table>
                <thead><tr>
                  <th>${t("warehouseBalances.code")}</th><th>${t("warehouseBalances.productName")}</th><th>${t("warehouseBalances.qty")}</th><th>${t("warehouseBalances.costPrice")}</th><th>${t("warehouseBalances.salePrice")}</th><th>${t("warehouseBalances.costValue")}</th><th>${t("warehouseBalances.saleValue")}</th>
                </tr></thead>
                <tbody>${rowsHtml}</tbody>
                <tfoot><tr>
                  <td colspan="2" style="text-align:end;font-weight:bold;">${t("warehouseBalances.total")}</td>
                  <td>${num(totalQty)}</td>
                  <td>—</td>
                  <td>—</td>
                  <td>${money(totalCost)}</td>
                  <td>${money(totalSale)}</td>
                </tr></tfoot>
              </table>
              <script>window.onload = () => { window.print(); };</script>
              </body></html>`);
            w.document.close();
          }}>
            {t("warehouseBalances.print")}
          </button>
        )}
      </PageHeader>
      <Alert>{products.error || warehouses.error}</Alert>

      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <div className="form-grid">
          <Field label={t("common.warehouse")}>
            <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} aria-label={t("common.warehouse")}>
              <option value="">— {t("warehouseBalances.selectWarehouse")} —</option>
              {warehouses.data?.map((w) => (
                <option key={w.id} value={w.id}>{w.name} ({w.code})</option>
              ))}
            </select>
          </Field>
        </div>
        {selWarehouse && (
          <p className="muted" style={{ marginTop: 8, marginBottom: 0 }}>
            {selWarehouse.name} · {selWarehouse.location || "—"}
          </p>
        )}
      </div>

      {warehouseId && (
        <div className="card table-wrap">
          {products.loading && !products.data ? (
            <Loading />
          ) : rows.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>{t("warehouseBalances.code")}</th>
                  <th>{t("warehouseBalances.productName")}</th>
                  <th className="num">{t("warehouseBalances.qty")}</th>
                  <th className="num">{t("warehouseBalances.costPrice")}</th>
                  <th className="num">{t("warehouseBalances.salePrice")}</th>
                  <th className="num">{t("warehouseBalances.costValue")}</th>
                  <th className="num">{t("warehouseBalances.saleValue")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const q = p.warehouse_quantity ?? 0;
                  return (
                    <tr key={p.id}>
                      <td dir="ltr">{p.sku}</td>
                      <td>{p.name}</td>
                      <td className="num">{num(q)}</td>
                      <td className="num">{money(p.cost_price)}</td>
                      <td className="num">{money(p.sale_price)}</td>
                      <td className="num">{money(q * Number(p.cost_price))}</td>
                      <td className="num">{money(q * Number(p.sale_price))}</td>
                    </tr>
                  );
                })}
                <tr style={{ fontWeight: 700, background: "#f7f9fb" }}>
                  <td colSpan={2}>{t("warehouseBalances.total")}</td>
                  <td className="num">{num(totalQty)}</td>
                  <td className="num">—</td>
                  <td className="num">—</td>
                  <td className="num">{money(totalCost)}</td>
                  <td className="num">{money(totalSale)}</td>
                </tr>
              </tbody>
            </table>
          ) : (
            <Empty>{t("warehouseBalances.noProducts")}</Empty>
          )}
        </div>
      )}
    </>
  );
}