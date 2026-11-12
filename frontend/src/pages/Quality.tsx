/** إدارة الجودة: نماذج فحص بمعايير قابلة للقياس + ربطها بالمنتجات. */
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { num } from "../format";
import { useAction, useFetch } from "../hooks";
import { useI18n } from "../i18n";
import type { Product, QcTemplate } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader } from "../ui";

interface ParamDraft {
  name: string;
  unit: string;
  param_type: "number" | "bool";
  min_value: string;
  max_value: string;
}

const emptyParam = (): ParamDraft => ({ name: "", unit: "", param_type: "number", min_value: "", max_value: "" });

export default function Quality() {
  const { t } = useI18n();
  const templates = useFetch(() => api.get<QcTemplate[]>("/qc/templates"), "qc-templates");
  const products = useFetch(() => api.get<Product[]>("/products?limit=1000"), "qc-products");
  const { busy, error, run } = useAction();
  const [msg, setMsg] = useState<string | null>(null);

  // نموذج قيد التحرير
  const [editing, setEditing] = useState<QcTemplate | null>(null);
  const [creating, setCreating] = useState(false);
  const [tplName, setTplName] = useState("");
  const [tplDesc, setTplDesc] = useState("");
  const [tplActive, setTplActive] = useState(true);
  const [params, setParams] = useState<ParamDraft[]>([emptyParam()]);

  // ربط بالمنتجات
  const [bindProduct, setBindProduct] = useState("");
  const [bound, setBound] = useState<number[] | null>(null);
  const bindInfo = useFetch(
    () => (bindProduct ? api.get<{ product_id: number; template_ids: number[] }>(`/qc/products/${bindProduct}`) : Promise.resolve(null)),
    `qc-bind-${bindProduct}`
  );

  const openCreate = () => { setEditing(null); setCreating(true); setTplName(""); setTplDesc(""); setTplActive(true); setParams([emptyParam()]); };
  const openEdit = (tpl: QcTemplate) => {
    setEditing(tpl); setCreating(true); setTplName(tpl.name); setTplDesc(tpl.description ?? ""); setTplActive(tpl.is_active);
    setParams(tpl.parameters.map((p) => ({ name: p.name, unit: p.unit ?? "", param_type: p.param_type as "number" | "bool", min_value: p.min_value != null ? String(p.min_value) : "", max_value: p.max_value != null ? String(p.max_value) : "" })));
  };

  const saveTemplate = (e: FormEvent) => {
    e.preventDefault();
    const clean = params.filter((p) => p.name.trim());
    const body = {
      name: tplName.trim(),
      description: tplDesc || null,
      is_active: tplActive,
      parameters: clean.map((p) => ({
        name: p.name.trim(),
        unit: p.unit || null,
        param_type: p.param_type,
        min_value: p.param_type === "number" && p.min_value !== "" ? Number(p.min_value) : null,
        max_value: p.param_type === "number" && p.max_value !== "" ? Number(p.max_value) : null,
      })),
    };
    void run(async () => {
      if (editing) await api.put(`/qc/templates/${editing.id}`, body);
      else await api.post("/qc/templates", body);
      setCreating(false);
      setMsg(`✅ ${t("حُفظ نموذج الفحص")} «${tplName.trim()}»`);
      templates.reload();
    });
  };

  const deleteTemplate = (tpl: QcTemplate) => {
    if (!window.confirm(`${t("حذف نموذج الفحص")} «${tpl.name}»؟`)) return;
    void run(async () => {
      await api.del(`/qc/templates/${tpl.id}`);
      setMsg(`✅ ${t("حُذف النموذج")}`);
      templates.reload();
    });
  };

  const saveBinding = (e: FormEvent) => {
    e.preventDefault();
    if (!bindProduct) return;
    void run(async () => {
      const saved = await api.put<{ template_ids: number[] }>(`/qc/products/${bindProduct}`, { template_ids: bound ?? [] });
      setMsg(`✅ ${t("حُفظت نماذج فحص المنتج")}: ${saved.template_ids.length}`);
    });
  };

  const templatesList = templates.data ?? [];
  const productsList = products.data ?? [];

  return (
    <>
      <PageHeader title={t("🧪 إدارة الجودة")}>
        <button className="btn btn-primary" onClick={openCreate}>{t("+ نموذج فحص جديد")}</button>
      </PageHeader>

      {msg && <Alert kind="info">{msg}</Alert>}
      {error && <Alert kind="error">{error}</Alert>}

      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <h3 style={{ margin: "0 0 10px", fontSize: 15 }}>{t("🔗 ربط نماذج الفحص بالمنتجات")}</h3>
        <form onSubmit={saveBinding} className="toolbar page-actions" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
          <Field label={t("المنتج")}>
            <select
              value={bindProduct}
              onChange={(e) => { setBindProduct(e.target.value); setBound(null); }}
              style={{ minWidth: 220 }}
            >
              <option value="">— {t("اختر المنتج")} —</option>
              {productsList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
          {bindProduct && (
            <Field label={t("نماذج الفحص المطلوبة قبل اعتماد الدفعات")}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {templatesList.filter((tp) => tp.is_active).map((tp) => (
                  <label key={tp.id} className="check" style={{ margin: 0 }}>
                    <input
                      type="checkbox"
                      checked={bound ? bound.includes(tp.id) : (bindInfo.data?.template_ids ?? []).includes(tp.id)}
                      onChange={(e) => {
                        const current = bound ?? bindInfo.data?.template_ids ?? [];
                        setBound(e.target.checked ? [...current, tp.id] : current.filter((id) => id !== tp.id));
                      }}
                    />
                    <span>{tp.name} <span className="perm-count">{tp.parameters.length} معيار</span></span>
                  </label>
                ))}
                {templatesList.length === 0 && <small className="hint">{t("لا نماذج — أنشئ نموذج فحص أولًا")}</small>}
              </div>
            </Field>
          )}
          {bindProduct && <button type="submit" className="btn btn-primary" disabled={busy}>{t("حفظ الربط")}</button>}
        </form>
      </div>

      <div className="card table-wrap">
        {templates.loading && !templates.data ? (
          <Loading />
        ) : templatesList.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("النموذج")}</th><th>{t("الوصف")}</th><th>{t("المعايير")}</th><th>{t("الحالة")}</th><th />
              </tr>
            </thead>
            <tbody>
              {templatesList.map((tp) => (
                <tr key={tp.id}>
                  <td><b>{tp.name}</b></td>
                  <td className="muted">{tp.description ?? "—"}</td>
                  <td>
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      {tp.parameters.map((p) => (
                        <small key={p.id}>
                          • {p.name}{p.unit ? ` (${p.unit})` : ""} — {p.param_type === "number" ? `${num(p.min_value)} : ${num(p.max_value)}` : t("مطابق/غير مطابق")}
                        </small>
                      ))}
                      {tp.parameters.length === 0 && <small className="hint">—</small>}
                    </div>
                  </td>
                  <td><span className={`badge ${tp.is_active ? "badge-active" : "badge-inactive"}`}>{tp.is_active ? t("نشط") : t("موقوف")}</span></td>
                  <td className="actions">
                    <button className="btn-edit" onClick={() => openEdit(tp)}>{t("تعديل")}</button>
                    <button className="btn-delete" onClick={() => deleteTemplate(tp)}>{t("حذف")}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("لا نماذج فحص — أنشئ نموذجًا بمعايير قابلة للقياس ثم اربطه بالمنتجات.")}</Empty>
        )}
      </div>

      {(creating || editing) && (
        <Modal title={editing ? `${t("تعديل نموذج الفحص")} — ${editing.name}` : t("نموذج فحص جديد")} onClose={() => setCreating(false)} wide>
          <form onSubmit={saveTemplate}>
            {error && <Alert kind="error">{error}</Alert>}
            <Field label={t("اسم النموذج")}>
              <input value={tplName} onChange={(e) => setTplName(e.target.value)} maxLength={150} required />
            </Field>
            <Field label={t("الوصف (اختياري)")}>
              <input value={tplDesc} onChange={(e) => setTplDesc(e.target.value)} maxLength={255} />
            </Field>
            <label className="check" style={{ marginBottom: 10 }}>
              <input type="checkbox" checked={tplActive} onChange={(e) => setTplActive(e.target.checked)} />
              <span>{t("نشط")}</span>
            </label>

            <h4 style={{ margin: "4px 0 8px" }}>{t("معايير القياس")}</h4>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>{t("المعيار")}</th><th>{t("الوحدة")}</th><th>{t("النوع")}</th><th className="num">{t("الحد الأدنى")}</th><th className="num">{t("الحد الأعلى")}</th><th /></tr>
                </thead>
                <tbody>
                  {params.map((p, i) => (
                    <tr key={i}>
                      <td><input value={p.name} onChange={(e) => setParams((s) => s.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} maxLength={150} /></td>
                      <td><input dir="ltr" value={p.unit} onChange={(e) => setParams((s) => s.map((x, j) => (j === i ? { ...x, unit: e.target.value } : x)))} maxLength={30} style={{ width: 80 }} /></td>
                      <td>
                        <select value={p.param_type} onChange={(e) => setParams((s) => s.map((x, j) => (j === i ? { ...x, param_type: e.target.value as "number" | "bool" } : x)))}>
                          <option value="number">{t("رقمي بنطاق")}</option>
                          <option value="bool">{t("مطابق/غير مطابق")}</option>
                        </select>
                      </td>
                      <td className="num">
                        {p.param_type === "number" ? <input type="number" step="0.001" dir="ltr" value={p.min_value} onChange={(e) => setParams((s) => s.map((x, j) => (j === i ? { ...x, min_value: e.target.value } : x)))} style={{ width: 90 }} /> : <span className="muted">—</span>}
                      </td>
                      <td className="num">
                        {p.param_type === "number" ? <input type="number" step="0.001" dir="ltr" value={p.max_value} onChange={(e) => setParams((s) => s.map((x, j) => (j === i ? { ...x, max_value: e.target.value } : x)))} style={{ width: 90 }} /> : <span className="muted">—</span>}
                      </td>
                      <td>
                        {params.length > 1 && (
                          <button type="button" className="btn-delete" onClick={() => setParams((s) => s.filter((_, j) => j !== i))}>{t("حذف")}</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button type="button" className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => setParams((s) => [...s, emptyParam()])}>
              {t("+ معيار جديد")}
            </button>

            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={busy}>{t("حفظ النموذج")}</button>
              <button type="button" className="btn" onClick={() => setCreating(false)}>{t("إلغاء")}</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
