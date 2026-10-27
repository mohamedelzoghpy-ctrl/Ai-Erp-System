import { useState, type FormEvent } from "react";
import { api, getToken } from "../api";
import { useAuth } from "../auth";
import { dateTime, money, num, REASON_LABEL } from "../format";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Party, Product, StockMovement, ProductStockRow, Warehouse } from "../types";
import { Alert, Empty, Field, Loading, Modal, nameOf, PageHeader, Pager } from "../ui";

export default function Products() {
  const { isManager } = useAuth();
  const [search, setSearch] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const [adjusting, setAdjusting] = useState<Product | null>(null);
  const [history, setHistory] = useState<Product | null>(null);

  const products = usePagedList<Product>("/products", { search: search.trim(), low_stock: lowOnly });
  const warehouses = useFetch(() => api.get<Warehouse[]>("/warehouses?limit=500"), "wh");
  const suppliers = useFetch(() => api.get<Party[]>("/suppliers?limit=500"), "sup");
  const action = useAction();

  const remove = (p: Product) => {
    if (!confirm(`حذف المنتج "${p.name}"؟`)) return;
    void action.run(async () => {
      await api.del(`/products/${p.id}`);
      products.reload();
    });
  };

  const rows = products.data ?? [];

  return (
    <>
      <PageHeader title="المنتجات">
        <button className="btn btn-primary" onClick={() => setEditing("new")}>
          + منتج جديد
        </button>
        <a
          className="btn"
          href={`/api/products/export/xlsx?token=${encodeURIComponent(getToken() ?? "")}`}
          download="products.xlsx"
        >
          ⬇ تصدير Excel
        </a>
        <label className="btn" style={{ cursor: "pointer" }}>
          ⬆ استيراد Excel
          <input type="file" accept=".xlsx,.xls" style={{ display: "none" }} onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            void action.run(async () => {
              const res = await api.upload<{ updated: number; created: number; errors: string[] }>("/products/import/xlsx", f);
              alert(`تم: ${res.updated} تحديث، ${res.created} جديد` + (res.errors.length ? `\\nأخطاء: ${res.errors.join(", ")}` : ""));
              products.reload();
            });
            e.target.value = "";
          }} />
        </label>
        <button className="btn" onClick={() => {
          const w = window.open("", "_blank");
          if (!w) return;
          const rowsHtml = rows.map((p) => `
            <tr>
              <td>${p.sku}</td>
              <td>${p.name}</td>
              <td>${nameOf(suppliers.data, p.supplier_id) ?? ""}</td>
              <td>${nameOf(warehouses.data, p.warehouse_id) ?? ""}</td>
              <td>${money(p.cost_price)}</td>
              <td>${money(p.sale_price)}</td>
              <td>${num(p.quantity)} ${p.unit}</td>
              <td>${money(Number(p.quantity) * Number(p.sale_price))}</td>
              <td>${money(Number(p.quantity) * Number(p.cost_price))}</td>
            </tr>`).join("");
          const totalQty = rows.reduce((s, p) => s + Number(p.quantity), 0);
          const totalSale = rows.reduce((s, p) => s + Number(p.quantity) * Number(p.sale_price), 0);
          const totalCost = rows.reduce((s, p) => s + Number(p.quantity) * Number(p.cost_price), 0);
          w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>قائمة المنتجات</title>
            <style>
              body { font-family: Tahoma, Arial, sans-serif; padding: 16px; }
              h1 { text-align: center; }
              table { width: 100%; border-collapse: collapse; }
              th, td { border: 1px solid #999; padding: 6px 8px; text-align: center; }
              th { background: #eee; }
              tfoot td { font-weight: bold; background: #f3f4f6; }
              .num { text-align: center; }
            </style></head><body>
            <h1>قائمة المنتجات</h1>
            <table>
              <thead><tr>
                <th>الكود</th><th>الاسم</th><th>المورد</th><th>المخزن</th><th>التكلفة</th><th>سعر البيع</th><th>الكمية</th><th>إجمالي القيمة بالبيع</th><th>إجمالي القيمة بالتكلفة</th>
              </tr></thead>
              <tbody>${rowsHtml}</tbody>
              <tfoot><tr>
                <td colspan="6" style="text-align:end;font-weight:bold;">الإجمالي</td>
                <td class="num">${num(totalQty)}</td>
                <td class="num">${money(totalSale)}</td>
                <td class="num">${money(totalCost)}</td>
              </tr></tfoot>
            </table>
            <script>window.onload = () => { window.print(); };</script>
            </body></html>`);
          w.document.close();
        }}>
          🖨 طباعة
        </button>
      </PageHeader>

      <div className="toolbar page-actions" style={{ marginBottom: 14 }}>
        <input placeholder="بحث بالاسم أو الكود…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <label className="check">
          <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} /> تحت حد إعادة الطلب فقط
        </label>
      </div>

      <Alert>{products.error || action.error}</Alert>

      <div className="card table-wrap">
        {products.loading && !products.data ? (
          <Loading />
        ) : rows.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>الكود</th>
                <th>الاسم</th>
                <th>المورد</th>
                <th>المخزن</th>
                <th className="num">التكلفة</th>
                <th className="num">سعر البيع</th>
                <th className="num">الكمية</th>
                <th className="num">إجمالي القيمة بالبيع</th>
                <th className="num">إجمالي القيمة بالتكلفة</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const low = p.quantity <= p.reorder_level;
                return (
                  <tr key={p.id} style={p.is_active ? undefined : { opacity: 0.55 }}>
                    <td dir="ltr">{p.sku}</td>
                    <td>
                      {p.name}
                      {!p.is_active && <span className="badge badge-off" style={{ marginInlineStart: 8 }}>معطّل</span>}
                    </td>
                    <td>{nameOf(suppliers.data, p.supplier_id)}</td>
                    <td>{nameOf(warehouses.data, p.warehouse_id)}</td>
                    <td className="num">{money(p.cost_price)}</td>
                    <td className="num">{money(p.sale_price)}</td>
                    <td className={`num${low ? " low" : ""}`}>
                      {num(p.quantity)} {p.unit}
                    </td>
                    <td className="num">{money(Number(p.quantity) * Number(p.sale_price))}</td>
                    <td className="num">{money(Number(p.quantity) * Number(p.cost_price))}</td>
                    <td className="actions">
                      <button className="btn btn-sm" onClick={() => setEditing(p)}>
                        تعديل
                      </button>
                      <button className="btn btn-sm" onClick={() => setAdjusting(p)}>
                        تسوية
                      </button>
                      <button className="btn btn-sm" onClick={() => setHistory(p)}>
                        الحركات
                      </button>
                      {isManager && (
                        <button className="btn btn-sm btn-danger" onClick={() => remove(p)}>
                          حذف
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr style={{ fontWeight: 600 }}>
                <td colSpan={6} style={{ textAlign: "end" }}>الإجمالي</td>
                <td className="num">
                  {num(rows.reduce((s, p) => s + Number(p.quantity), 0))}
                </td>
                <td className="num">
                  {money(rows.reduce((s, p) => s + Number(p.quantity) * Number(p.sale_price), 0))}
                </td>
                <td className="num">
                  {money(rows.reduce((s, p) => s + Number(p.quantity) * Number(p.cost_price), 0))}
                </td>
                <td />
              </tr>
            </tfoot>

          </table>
        ) : (
          <Empty>{search || lowOnly ? "لا نتائج مطابقة" : "لا توجد منتجات بعد. أضف منتجاً للبدء."}</Empty>
        )}
        <Pager list={products} />
      </div>

      {editing && (
        <ProductForm
          initial={editing === "new" ? null : editing}
          isManager={isManager}
          warehouses={warehouses.data ?? []}
          suppliers={suppliers.data ?? []}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            products.reload();
          }}
        />
      )}
      {adjusting && (
        <AdjustForm
          product={adjusting}
          onClose={() => setAdjusting(null)}
          onSaved={() => {
            setAdjusting(null);
            products.reload();
          }}
        />
      )}
      {history && <MovementsModal product={history} onClose={() => setHistory(null)} />}
    </>
  );
}

function ProductForm({
  initial,
  isManager,
  warehouses,
  suppliers,
  onClose,
  onSaved,
}: {
  initial: Product | null;
  isManager: boolean;
  warehouses: Warehouse[];
  suppliers: Party[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [f, setF] = useState({
    sku: initial?.sku ?? "",
    name: initial?.name ?? "",
    description: initial?.description ?? "",
    unit: initial?.unit ?? "قطعة",
    cost_price: initial?.cost_price ?? "0",
    sale_price: initial?.sale_price ?? "0",
    quantity: "0",
    reorder_level: String(initial?.reorder_level ?? 0),
    warehouse_id: initial?.warehouse_id ? String(initial.warehouse_id) : "",
    supplier_id: initial?.supplier_id ? String(initial.supplier_id) : "",
    is_active: initial?.is_active ?? true,
  });
  const { busy, error, run } = useAction();
  const set = (k: keyof typeof f, v: string | boolean) => setF((p) => ({ ...p, [k]: v }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const common = {
      name: f.name.trim(),
      description: f.description.trim() || null,
      unit: f.unit.trim() || "قطعة",
      sale_price: f.sale_price || "0",
      reorder_level: Number(f.reorder_level) || 0,
      is_active: f.is_active,
      warehouse_id: f.warehouse_id ? Number(f.warehouse_id) : null,
      supplier_id: f.supplier_id ? Number(f.supplier_id) : null,
      ...(isManager ? { cost_price: f.cost_price || "0" } : {}),
    };
    void run(async () => {
      if (initial) await api.patch(`/products/${initial.id}`, common);
      else
        await api.post("/products", {
          ...common,
          sku: f.sku.trim(),
          ...(isManager ? { quantity: Number(f.quantity) || 0 } : {}),
        });
      onSaved();
    });
  };

  return (
    <Modal title={initial ? "تعديل منتج" : "منتج جديد"} onClose={onClose} wide>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <div className="form-grid">
          <Field label="الكود (SKU)" hint={initial ? "لا يمكن تغيير الكود بعد الإنشاء" : "فريد لكل منتج"}>
            <input dir="ltr" value={f.sku} onChange={(e) => set("sku", e.target.value)} required disabled={!!initial} autoFocus={!initial} />
          </Field>
          <Field label="اسم المنتج">
            <input value={f.name} onChange={(e) => set("name", e.target.value)} required autoFocus={!!initial} />
          </Field>
          <Field label="سعر التكلفة">
            <input
              type="number"
              min="0"
              step="0.01"
              value={f.cost_price}
              readOnly={!isManager}
              title={isManager ? undefined : "تعديل سعر التكلفة للمدير فقط"}
              onChange={(e) => set("cost_price", e.target.value)}
            />
          </Field>
          <Field label="سعر البيع">
            <input type="number" min="0" step="0.01" value={f.sale_price} onChange={(e) => set("sale_price", e.target.value)} />
          </Field>
          <Field label="الوحدة">
            <input value={f.unit} onChange={(e) => set("unit", e.target.value)} />
          </Field>
          <Field label="حد إعادة الطلب">
            <input type="number" min="0" step="1" value={f.reorder_level} onChange={(e) => set("reorder_level", e.target.value)} />
          </Field>
          <Field label="المخزن">
            <select value={f.warehouse_id} onChange={(e) => set("warehouse_id", e.target.value)}>
              <option value="">— بدون —</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="المورد">
            <select value={f.supplier_id} onChange={(e) => set("supplier_id", e.target.value)}>
              <option value="">— بدون —</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {!initial && isManager && (
          <Field label="الرصيد الافتتاحي" hint="بعد الإنشاء تتغير الكمية فقط عبر المشتريات والمبيعات والتسوية">
            <input type="number" min="0" step="1" value={f.quantity} onChange={(e) => set("quantity", e.target.value)} />
          </Field>
        )}
        <Field label="الوصف">
          <textarea rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} />
        </Field>
        <label className="check">
          <input type="checkbox" checked={f.is_active} onChange={(e) => set("is_active", e.target.checked)} /> نشط
        </label>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy}>
            {busy ? "جارٍ الحفظ…" : "حفظ"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            إلغاء
          </button>
        </div>
      </form>
    </Modal>
  );
}

function AdjustForm({ product, onClose, onSaved }: { product: Product; onClose: () => void; onSaved: () => void }) {
  const [change, setChange] = useState("");
  const [reference, setReference] = useState("");
  const { busy, error, run } = useAction();
  const delta = Number(change);
  const valid = Number.isInteger(delta) && delta !== 0;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    void run(async () => {
      await api.post(`/products/${product.id}/adjust-stock`, { change: delta, reference: reference.trim() || null });
      onSaved();
    });
  };

  return (
    <Modal title={`تسوية مخزون — ${product.name}`} onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <p className="muted" style={{ marginTop: 0 }}>
          الكمية الحالية: <b>{num(product.quantity)}</b> {product.unit}
        </p>
        <Field label="التغيير" hint="رقم موجب للإضافة وسالب للخصم، مثل 5 أو -3">
          <input dir="ltr" type="number" step="1" value={change} onChange={(e) => setChange(e.target.value)} required autoFocus />
        </Field>
        {valid && (
          <p style={{ marginTop: 0 }}>
            الكمية بعد التسوية: <b>{num(product.quantity + delta)}</b>
          </p>
        )}
        <Field label="السبب / المرجع">
          <input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="جرد، تالف، …" />
        </Field>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy || !valid}>
            {busy ? "جارٍ الحفظ…" : "تطبيق"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            إلغاء
          </button>
        </div>
      </form>
    </Modal>
  );
}

function MovementsModal({ product, onClose }: { product: Product; onClose: () => void }) {
  const moves = useFetch(() => api.get<StockMovement[]>(`/products/${product.id}/movements`), `m${product.id}`);
  const where = useFetch(() => api.get<ProductStockRow[]>(`/products/${product.id}/stock`), `w${product.id}`);
  return (
    <Modal title={`حركة المخزون — ${product.name}`} onClose={onClose} wide>
      <Alert>{moves.error || where.error}</Alert>
      {where.data && where.data.length > 0 && (
        <p data-testid="stock-by-warehouse">
          الكمية حسب المخزن:{" "}
          {where.data.map((r, i) => (
            <span key={r.warehouse_id}>
              {i > 0 && " · "}
              {r.warehouse_name}: <b>{num(r.quantity)}</b>
            </span>
          ))}
        </p>
      )}
      {moves.loading && !moves.data ? (
        <Loading />
      ) : moves.data && moves.data.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>التاريخ</th>
                <th>النوع</th>
                <th>المرجع</th>
                <th className="num">التغيير</th>
              </tr>
            </thead>
            <tbody>
              {moves.data.map((m) => (
                <tr key={m.id}>
                  <td>{dateTime(m.created_at)}</td>
                  <td>{REASON_LABEL[m.reason] ?? m.reason}</td>
                  <td>{m.reference || "—"}</td>
                  <td className="num" dir="ltr" style={{ color: m.change < 0 ? "var(--danger)" : "var(--ok)", fontWeight: 600 }}>
                    {m.change > 0 ? `+${m.change}` : m.change}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>لا توجد حركات لهذا المنتج.</Empty>
      )}
    </Modal>
  );
}
