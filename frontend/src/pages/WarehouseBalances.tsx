import { useState } from "react";
import { api } from "../api";
import { money, num } from "../format";
import { useFetch } from "../hooks";
import type { Product, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, PageHeader } from "../ui";

export default function WarehouseBalances() {
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
      <PageHeader title="أرصدة المخازن" />
      <Alert>{products.error || warehouses.error}</Alert>

      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <div className="form-grid">
          <Field label="المخزن">
            <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} aria-label="المخزن">
              <option value="">— اختر مخزناً —</option>
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
                  <th>الكود</th>
                  <th>اسم المنتج</th>
                  <th className="num">الكمية</th>
                  <th className="num">سعر التكلفة</th>
                  <th className="num">سعر البيع</th>
                  <th className="num">قيمة التكلفة</th>
                  <th className="num">قيمة البيع</th>
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
                  <td colSpan={2}>الإجمالي</td>
                  <td className="num">{num(totalQty)}</td>
                  <td className="num">—</td>
                  <td className="num">—</td>
                  <td className="num">{money(totalCost)}</td>
                  <td className="num">{money(totalSale)}</td>
                </tr>
              </tbody>
            </table>
          ) : (
            <Empty>لا توجد منتجات في هذا المخزن.</Empty>
          )}
        </div>
      )}
    </>
  );
}