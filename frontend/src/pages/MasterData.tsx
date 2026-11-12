import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Branch, Party, Warehouse } from "../types";
import { balanceNote, money } from "../format";
import { ActiveBadge, Alert, Empty, Field, Loading, Modal, PageHeader, Pager } from "../ui";
import { PaymentDialog, StatementDialog } from "./Accounts";

/** Shared shape of the three master-data screens. */
interface Column<T> {
  header: string;
  cell: (row: T) => React.ReactNode;
}

function useCrud<T extends { id: number }>(path: string) {
  const list = useFetch(() => api.get<T[]>(`${path}?limit=500`), path);
  const action = useAction();
  return { list, action };
}

// ---------------------------------------------------------------- Warehouses
export function Warehouses() {
  const { isManager } = useAuth();
  const { t } = useI18n();
  const { list, action } = useCrud<Warehouse>("/warehouses");
  const branches = useFetch(() => api.get<Branch[]>("/company/branches"), "warehouse-branches");
  const [editing, setEditing] = useState<Warehouse | "new" | null>(null);

  const remove = (w: Warehouse) => {
    if (!confirm(`${t('حذف المخزن "')}${w.name}${t("؟")}`)) return;
    void action.run(async () => {
      await api.del(`/warehouses/${w.id}`);
      list.reload();
    });
  };

  return (
    <>
      <PageHeader title={t("warehouses.title")}>
        {isManager && (
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            {t("warehouses.new")}
          </button>
        )}
        {list.data && list.data.length > 0 && (
          <button className="btn" onClick={() => {
            const w = window.open("", "_blank");
            if (!w) return;
            const rowsHtml = (list.data ?? []).map((wh) => `
              <tr>
                <td>${wh.name}</td>
                <td>${wh.code}</td>
                <td>${branches.data?.find((b) => b.id === wh.branch_id)?.name || "—"}</td>
                <td>${wh.location || "—"}</td>
                <td>${wh.is_active ? "نشط" : "موقوف"}</td>
              </tr>`).join("");
            w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>${t("warehouses.title")}</title>
              <style>
                body { font-family: Tahoma, Arial, sans-serif; padding: 16px; }
                h1 { text-align: center; }
                table { width: 100%; border-collapse: collapse; }
                th, td { border: 1px solid #999; padding: 6px 8px; text-align: center; }
                th { background: #eee; }
              </style></head><body>
              <h1>${t("قائمة المخازن")}</h1>
              <table>
                <thead><tr>
                  <th>${t("warehouses.name")}</th><th>${t("warehouses.code")}</th><th>${t("warehouses.branch")}</th><th>${t("warehouses.location")}</th><th>${t("warehouses.status")}</th>
                </tr></thead>
                <tbody>${rowsHtml}</tbody>
              </table>
              <script>window.onload = () => { window.print(); };</script>
              </body></html>`);
            w.document.close();
          }}>
            🖨 {t("طباعة")}
          </button>
        )}
      </PageHeader>
      <Alert>{list.error || action.error}</Alert>
      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("warehouses.name")}</th>
                <th>{t("warehouses.code")}</th>
                <th>{t("warehouses.branch")}</th>
                <th>{t("warehouses.location")}</th>
                <th>{t("warehouses.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((w) => (
                <tr key={w.id}>
                  <td>{w.name}</td>
                  <td>{w.code}</td>
                  <td>{branches.data?.find((branch) => branch.id === w.branch_id)?.name || "—"}</td>
                  <td>{w.location || "—"}</td>
                  <td>
                    <ActiveBadge active={w.is_active} />
                  </td>
                  <td className="actions">
                    <button className="btn-edit" onClick={() => setEditing(w)}>{t("تعديل")}</button>
                    {isManager && (
                      <button className="btn-delete" onClick={() => remove(w)}>
                        {t("حذف")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("warehouses.empty")}</Empty>
        )}
      </div>
      {editing && (
        <WarehouseForm
          initial={editing === "new" ? null : editing}
          branches={branches.data ?? []}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function WarehouseForm({ initial, branches, onClose, onSaved }: { initial: Warehouse | null; branches: Branch[]; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(initial?.name ?? "");
  const [code, setCode] = useState(initial?.code ?? "");
  const [location, setLocation] = useState(initial?.location ?? "");
  const [branchId, setBranchId] = useState(initial?.branch_id ?? branches[0]?.id ?? 0);
  const [active, setActive] = useState(initial?.is_active ?? true);
  const { t } = useI18n();
  const { busy, error, run } = useAction();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = { name: name.trim(), ...(!initial && !code.trim() ? {} : { code: code.trim() }), location: location.trim() || null, is_active: active, branch_id: branchId || null };
    void run(async () => {
      if (initial) await api.patch(`/warehouses/${initial.id}`, body);
      else await api.post("/warehouses", body);
      onSaved();
    });
  };

  return (
    <Modal title={initial ? t("تعديل مخزن") : t("مخزن جديد")} onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <div className="form-grid">
          <Field label={t("اسم المخزن")}>
            <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
          </Field>
          <Field label={t("الكود")} hint={initial ? t("فريد، مثل W1") : t("اتركه فارغًا للتوليد التلقائي")}>
            <input value={code} onChange={(e) => setCode(e.target.value)} placeholder={initial ? undefined : t("يُولّد تلقائيًا عند الحفظ")} />
          </Field>
        </div>
        {!initial && (
          <Field label={t("الفرع")}>
            <select value={branchId} onChange={(e) => setBranchId(Number(e.target.value))} required>
              {branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}
            </select>
          </Field>
        )}
        <Field label={t("الموقع")}>
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </Field>
        <label className="check">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> active
        </label>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy}>
            {busy ? t("جارٍ الحفظ…") : t("حفظ")}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            {t("إلغاء")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ------------------------------------------------- Suppliers & customers
function PartyScreen({ title, singular, path, kind }: { title: string; singular: string; path: string; kind: "customer" | "supplier" }) {
  const { isManager } = useAuth();
  const { t, lang } = useI18n();
  const [search, setSearch] = useState("");
  const list = usePagedList<Party>(path, { search: search.trim() });
  const action = useAction();
  const [editing, setEditing] = useState<Party | "new" | null>(null);
  const [paying, setPaying] = useState<Party | null>(null);
  const [statement, setStatement] = useState<Party | null>(null);

  const rows = list.data ?? [];

  const columns: Column<Party>[] = [
    { header: t("party.code") ?? "الكود", cell: (p) => <span dir="ltr">{p.code || "—"}</span> },
    { header: t("common.name") ?? "الاسم", cell: (p) => p.name },
    ...(lang === "en" ? [] : [{ header: t("party.contactPerson") ?? "المسؤول", cell: (p: Party) => p.contact_person || "—" }]),
    { header: t("party.phone") ?? "الهاتف", cell: (p) => <span dir="ltr">{p.phone || "—"}</span> },
    { header: t("party.email") ?? "البريد", cell: (p) => <span dir="ltr">{p.email || "—"}</span> },
    {
      header: t("party.balance") ?? "الرصيد",
      cell: (p) => (
        <span title={balanceNote(kind, p.balance)} style={Number(p.balance) > 0 ? { color: "var(--danger, #b42318)", fontWeight: 600 } : undefined}>
          {money(p.balance)}
        </span>
      ),
    },
    { header: t("common.status") ?? "الحالة", cell: (p) => <ActiveBadge active={p.is_active} /> },
  ];

  const remove = (p: Party) => {
    if (!confirm(`${t("حذف ")}${singular}${t(' "')}${p.name}${t("؟")}`)) return;
    void action.run(async () => {
      await api.del(`${path}/${p.id}`);
      list.reload();
    });
  };

  return (
    <>
      <PageHeader title={title}>
        <input placeholder={t("بحث…")} value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 200 }} />
        {rows.length > 0 && (
          <button className="btn btn-primary" onClick={() => {
            const w = window.open("", "_blank");
            if (!w) return;
            const rowsHtml = rows.map((p) => `
              <tr>
                <td>${p.code || "—"}</td>
                <td>${p.name}</td>
                <td>${p.contact_person || "—"}</td>
                <td>${p.phone || "—"}</td>
                <td>${p.email || "—"}</td>
                <td>${money(p.balance)}</td>
                <td>${p.is_active ? t("نشط") : t("موقوف")}</td>
              </tr>`).join("");
            w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>${title}</title>
              <style>
                body { font-family: Tahoma, Arial, sans-serif; padding: 16px; }
                h1 { text-align: center; }
                table { width: 100%; border-collapse: collapse; }
                th, td { border: 1px solid #999; padding: 6px 8px; text-align: center; }
                th { background: #eee; }
              </style></head><body>
              <h1>${title}</h1>
              <table>
                <thead><tr><th>${t("الكود")}</th><th>${t("الاسم")}</th><th>${t("المسؤول")}</th><th>${t("الهاتف")}</th><th>${t("البريد")}</th><th>${t("الرصيد")}</th><th>${t("الحالة")}</th></tr></thead>
                <tbody>${rowsHtml}</tbody>
              </table>
              <script>window.onload = () => { window.print(); };</script>
              </body></html>`);
            w.document.close();
          }}>
            🖨 {t("طباعة")}
          </button>
        )}
        <button className="btn btn-primary" onClick={() => setEditing("new")}>
          {"+ "}{singular} {t("جديد")}
        </button>
      </PageHeader>
      <Alert>{list.error || action.error}</Alert>
      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : rows.length > 0 ? (
          <table>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.header}>{c.header}</th>
                ))}
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  {columns.map((c) => (
                    <td key={c.header}>{c.cell(p)}</td>
                  ))}
                  <td className="actions">
                    <button className="btn btn-sm" onClick={() => setPaying(p)}>
                      {kind === "customer" ? t("قبض") : t("دفع")}
                    </button>
                    <button className="btn btn-sm" onClick={() => setStatement(p)}>
                      {t("كشف حساب")}
                    </button>
                    <button className="btn-edit" onClick={() => setEditing(p)}>{t("تعديل")}</button>
                    {isManager && (
                      <button className="btn-delete" onClick={() => remove(p)}>
                        {t("حذف")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{search ? t("لا نتائج مطابقة") : `${t("لا يوجد ")}${singular}${t(" بعد.")}`}</Empty>
        )}
        <Pager list={list} />
      </div>
      {paying && (
        <PaymentDialog
          kind={kind}
          partyId={paying.id}
          partyName={paying.name}
          balance={paying.balance}
          onClose={() => setPaying(null)}
          onSaved={() => {
            setPaying(null);
            list.reload();
          }}
        />
      )}
      {statement && <StatementDialog kind={kind} partyId={statement.id} partyName={statement.name} onClose={() => setStatement(null)} />}
      {editing && (
        <PartyForm
          canSetOpening={isManager}
          singular={singular}
          path={path}
          initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function PartyForm({
  canSetOpening,
  singular,
  path,
  initial,
  onClose,
  onSaved,
}: {
  canSetOpening: boolean;
  singular: string;
  path: string;
  initial: Party | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [f, setF] = useState({
    name: initial?.name ?? "",
    contact_person: initial?.contact_person ?? "",
    phone: initial?.phone ?? "",
    email: initial?.email ?? "",
    address: initial?.address ?? "",
    opening_balance: initial?.opening_balance ?? "0",
    credit_limit: initial?.credit_limit ?? "",
    tax_registration_number: initial?.tax_registration_number ?? "",
    price_list_id: initial?.price_list_id ? String(initial.price_list_id) : "",
    is_active: initial?.is_active ?? true,
  });
  const { busy, error, run } = useAction();
  const priceLists = useFetch(
    () => (path.endsWith("/customers") ? api.get<any[]>("/price-lists") : Promise.resolve([])),
    `pl-for-${path}`,
  );
  const { t } = useI18n();
  const set = (k: keyof typeof f, v: string | boolean) => setF((p) => ({ ...p, [k]: v }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = {
      name: f.name.trim(),
      contact_person: f.contact_person.trim() || null,
      phone: f.phone.trim() || null,
      email: f.email.trim() || null,
      address: f.address.trim() || null,
      is_active: f.is_active,
      // Only managers/admins may set it; omitting it keeps the server value (staff would get a 403 otherwise).
      ...(canSetOpening ? { opening_balance: f.opening_balance || "0" } : {}),
      // الحد الائتماني للعملاء فقط: فارغ = بلا حد (null)
      ...(path.endsWith("/customers") ? { credit_limit: f.credit_limit === "" ? null : f.credit_limit, tax_registration_number: f.tax_registration_number?.trim() || null, price_list_id: f.price_list_id ? Number(f.price_list_id) : null } : {}),
    };
    void run(async () => {
      if (initial) await api.patch(`${path}/${initial.id}`, body);
      else await api.post(path, body);
      onSaved();
    });
  };

  return (
    <Modal title={initial ? `${t("تعديل ")}${singular}` : `${singular}${t(" جديد")}`} onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <Field label={t("الاسم")}>
          <input value={f.name} onChange={(e) => set("name", e.target.value)} required autoFocus />
        </Field>
        {initial && (
          <Field label={t("الكود")} hint={t("يُولَّد تلقائيًا إذا تُرك فاضيًا عند الاستيراد أو الإضافة — يُعدَّل من الاستيراد فقط")}>
            <input dir="ltr" value={initial.code || "—"} readOnly style={{ background: "#f6f7f9" }} />
          </Field>
        )}
        <div className="form-grid">
          <Field label={t("المسؤول")}>
            <input value={f.contact_person} onChange={(e) => set("contact_person", e.target.value)} />
          </Field>
          <Field label={t("الهاتف")}>
            <input dir="ltr" value={f.phone} onChange={(e) => set("phone", e.target.value)} />
          </Field>
        </div>
        <Field label={t("البريد الإلكتروني")}>
          <input dir="ltr" type="email" value={f.email} onChange={(e) => set("email", e.target.value)} />
        </Field>
        <Field label={t("العنوان")}>
          <textarea rows={2} value={f.address} onChange={(e) => set("address", e.target.value)} />
        </Field>
        {canSetOpening && (
          <Field label={t("رصيد أول المدة")} hint={`${t("موجب = مستحق ")}${singular === "عميل" ? t("على العميل") : t("للمورد")}${t(" · سالب = رصيد دائن")}`}>
            <input dir="ltr" type="number" step="0.01" value={f.opening_balance} onChange={(e) => set("opening_balance", e.target.value)} />
          </Field>
        )}
        {path.endsWith("/customers") && (
          <Field label={t("قائمة الأسعار")} hint={t("تُطبَّق أسعارها تلقائيًا على فواتير هذا العميل")}>
            <select value={f.price_list_id ?? ""} onChange={(e) => set("price_list_id", e.target.value)}>
              <option value="">— سعر البيع العام —</option>
              {(priceLists.data ?? []).filter((l: any) => l.is_active).map((l: any) => (
                <option key={l.id} value={l.id}>{l.name} ({l.items.length} سعر)</option>
              ))}
            </select>
          </Field>
        )}
        {path.endsWith("/customers") && (
          <Field label={t("الرقم الضريبي للعميل")} hint={t("للفواتير B2B على منظومة الضرائب — اختياري")}>
            <input dir="ltr" value={f.tax_registration_number ?? ""} onChange={(e) => set("tax_registration_number", e.target.value)} placeholder="مثال: 300012345600003" />
          </Field>
        )}
        {path.endsWith("/customers") && (
          <Field label={t("الحد الائتماني")} hint={t("أقصى مديونية مسموحة — فارغ = بلا حد · يتجاوزه من يملك صلاحية «تجاوز الحد الائتماني»")}>
            <input dir="ltr" type="number" step="0.01" min="0" value={f.credit_limit} onChange={(e) => set("credit_limit", e.target.value)} placeholder={t("بلا حد")} />
          </Field>
        )}
        <label className="check">
          <input type="checkbox" checked={f.is_active} onChange={(e) => set("is_active", e.target.checked)} /> active
        </label>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy}>
            {busy ? t("جارٍ الحفظ…") : t("حفظ")}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            {t("إلغاء")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export const Suppliers = () => {
  const { t } = useI18n();
  return <PartyScreen title={t("suppliers.title")} singular={t("suppliers.singular")} path="/suppliers" kind="supplier" />;
};
export const Customers = () => {
  const { t } = useI18n();
  return <PartyScreen title={t("customers.title")} singular={t("customers.singular")} path="/customers" kind="customer" />;
};
