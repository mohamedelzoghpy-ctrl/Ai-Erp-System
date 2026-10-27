import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Branch, Party, Warehouse } from "../types";
import { balanceNote, money } from "../format";
import { Alert, Empty, Field, Loading, Modal, PageHeader, Pager } from "../ui";
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

function ActiveBadge({ active }: { active: boolean }) {
  return active ? <span className="badge badge-confirmed">نشط</span> : <span className="badge badge-off">معطّل</span>;
}

// ---------------------------------------------------------------- Warehouses
export function Warehouses() {
  const { isManager } = useAuth();
  const { list, action } = useCrud<Warehouse>("/warehouses");
  const branches = useFetch(() => api.get<Branch[]>("/company/branches"), "warehouse-branches");
  const [editing, setEditing] = useState<Warehouse | "new" | null>(null);

  const remove = (w: Warehouse) => {
    if (!confirm(`حذف المخزن "${w.name}"؟`)) return;
    void action.run(async () => {
      await api.del(`/warehouses/${w.id}`);
      list.reload();
    });
  };

  return (
    <>
      <PageHeader title="المخازن">
        {isManager && (
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            + مخزن جديد
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
                <td>${wh.is_active ? "نشط" : "معطّل"}</td>
              </tr>`).join("");
            w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>المخازن</title>
              <style>
                body { font-family: Tahoma, Arial, sans-serif; padding: 16px; }
                h1 { text-align: center; }
                table { width: 100%; border-collapse: collapse; }
                th, td { border: 1px solid #999; padding: 6px 8px; text-align: center; }
                th { background: #eee; }
              </style></head><body>
              <h1>قائمة المخازن</h1>
              <table>
                <thead><tr>
                  <th>الاسم</th><th>الكود</th><th>الفرع</th><th>الموقع</th><th>الحالة</th>
                </tr></thead>
                <tbody>${rowsHtml}</tbody>
              </table>
              <script>window.onload = () => { window.print(); };</script>
              </body></html>`);
            w.document.close();
          }}>
            🖨 طباعة
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
                <th>الاسم</th>
                <th>الكود</th>
                <th>الفرع</th>
                <th>الموقع</th>
                <th>الحالة</th>
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
                    <button className="btn btn-sm" onClick={() => setEditing(w)}>
                      تعديل
                    </button>
                    {isManager && (
                      <button className="btn btn-sm btn-danger" onClick={() => remove(w)}>
                        حذف
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>لا توجد مخازن بعد. أضف مخزناً للبدء.</Empty>
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
  const { busy, error, run } = useAction();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = { name: name.trim(), code: code.trim(), location: location.trim() || null, is_active: active, branch_id: branchId || null };
    void run(async () => {
      if (initial) await api.patch(`/warehouses/${initial.id}`, body);
      else await api.post("/warehouses", body);
      onSaved();
    });
  };

  return (
    <Modal title={initial ? "تعديل مخزن" : "مخزن جديد"} onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <div className="form-grid">
          <Field label="اسم المخزن">
            <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
          </Field>
          <Field label="الكود" hint="فريد، مثل W1">
            <input value={code} onChange={(e) => setCode(e.target.value)} required />
          </Field>
        </div>
        {!initial && (
          <Field label="الفرع">
            <select value={branchId} onChange={(e) => setBranchId(Number(e.target.value))} required>
              {branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="الموقع">
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </Field>
        <label className="check">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> نشط
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

// ------------------------------------------------- Suppliers & customers
function PartyScreen({ title, singular, path, kind }: { title: string; singular: string; path: string; kind: "customer" | "supplier" }) {
  const { isManager } = useAuth();
  const [search, setSearch] = useState("");
  const list = usePagedList<Party>(path, { search: search.trim() });
  const action = useAction();
  const [editing, setEditing] = useState<Party | "new" | null>(null);
  const [paying, setPaying] = useState<Party | null>(null);
  const [statement, setStatement] = useState<Party | null>(null);

  const rows = list.data ?? [];

  const columns: Column<Party>[] = [
    { header: "الاسم", cell: (p) => p.name },
    { header: "المسؤول", cell: (p) => p.contact_person || "—" },
    { header: "الهاتف", cell: (p) => <span dir="ltr">{p.phone || "—"}</span> },
    { header: "البريد", cell: (p) => <span dir="ltr">{p.email || "—"}</span> },
    {
      header: "الرصيد",
      cell: (p) => (
        <span title={balanceNote(kind, p.balance)} style={Number(p.balance) > 0 ? { color: "var(--danger, #b42318)", fontWeight: 600 } : undefined}>
          {money(p.balance)}
        </span>
      ),
    },
    { header: "الحالة", cell: (p) => <ActiveBadge active={p.is_active} /> },
  ];

  const remove = (p: Party) => {
    if (!confirm(`حذف ${singular} "${p.name}"؟`)) return;
    void action.run(async () => {
      await api.del(`${path}/${p.id}`);
      list.reload();
    });
  };

  return (
    <>
      <PageHeader title={title}>
        <input placeholder="بحث…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 200 }} />
        <button className="btn btn-primary" onClick={() => setEditing("new")}>
          + {singular} جديد
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
                      {kind === "customer" ? "قبض" : "دفع"}
                    </button>
                    <button className="btn btn-sm" onClick={() => setStatement(p)}>
                      كشف حساب
                    </button>
                    <button className="btn btn-sm" onClick={() => setEditing(p)}>
                      تعديل
                    </button>
                    {isManager && (
                      <button className="btn btn-sm btn-danger" onClick={() => remove(p)}>
                        حذف
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{search ? "لا نتائج مطابقة" : `لا يوجد ${singular} بعد.`}</Empty>
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
    is_active: initial?.is_active ?? true,
  });
  const { busy, error, run } = useAction();
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
    };
    void run(async () => {
      if (initial) await api.patch(`${path}/${initial.id}`, body);
      else await api.post(path, body);
      onSaved();
    });
  };

  return (
    <Modal title={initial ? `تعديل ${singular}` : `${singular} جديد`} onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{error}</Alert>
        <Field label="الاسم">
          <input value={f.name} onChange={(e) => set("name", e.target.value)} required autoFocus />
        </Field>
        <div className="form-grid">
          <Field label="المسؤول">
            <input value={f.contact_person} onChange={(e) => set("contact_person", e.target.value)} />
          </Field>
          <Field label="الهاتف">
            <input dir="ltr" value={f.phone} onChange={(e) => set("phone", e.target.value)} />
          </Field>
        </div>
        <Field label="البريد الإلكتروني">
          <input dir="ltr" type="email" value={f.email} onChange={(e) => set("email", e.target.value)} />
        </Field>
        <Field label="العنوان">
          <textarea rows={2} value={f.address} onChange={(e) => set("address", e.target.value)} />
        </Field>
        {canSetOpening && (
          <Field label="رصيد أول المدة" hint={`موجب = مستحق ${singular === "عميل" ? "على العميل" : "للمورد"} · سالب = رصيد دائن`}>
            <input dir="ltr" type="number" step="0.01" value={f.opening_balance} onChange={(e) => set("opening_balance", e.target.value)} />
          </Field>
        )}
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

export const Suppliers = () => <PartyScreen title="الموردون" singular="مورد" path="/suppliers" kind="supplier" />;
export const Customers = () => <PartyScreen title="العملاء" singular="عميل" path="/customers" kind="customer" />;
