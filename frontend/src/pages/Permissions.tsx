import { useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useFetch } from "../hooks";
import type { AccessSection, CatalogModule, User, UserPermissionDetail } from "../types";
import { Alert, Empty, Field, Loading, PageHeader } from "../ui";

type Tab = "sections" | "users";

/** شاشة إدارة الصلاحيات: تبويبان — الأقسام (المصفوفة المشتركة) والمستخدمون (الوراثة + الاستثناءات). */
export default function Permissions() {
  const [tab, setTab] = useState<Tab>("sections");
  return (
    <div>
      <PageHeader title="🛡️ الصلاحيات والأقسام">
        <div className="perm-tabs">
          <button type="button" className={tab === "sections" ? "active" : ""} onClick={() => setTab("sections")}>
            أقسام الصلاحيات
          </button>
          <button type="button" className={tab === "users" ? "active" : ""} onClick={() => setTab("users")}>
            صلاحيات المستخدمين
          </button>
        </div>
      </PageHeader>
      {tab === "sections" ? <SectionsTab /> : <UsersTab />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* تبويب الأقسام — مصفوفة الموارد × الإجراءات                          */
/* ------------------------------------------------------------------ */

function SectionsTab() {
  const catalog = useFetch<CatalogModule[]>(() => api.get<{ modules: CatalogModule[]; total: number }>("/permissions/catalog").then((r) => r.modules), "perm-catalog");
  const sections = useFetch<AccessSection[]>(() => api.get<AccessSection[]>("/access-sections"), "perm-sections");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Set<string> | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [newName, setNewName] = useState("");
  const [newCode, setNewCode] = useState("");

  const selected = sections.data?.find((s) => s.id === selectedId) ?? sections.data?.[0] ?? null;
  const current: Set<string> = draft ?? new Set(selected?.permission_codes ?? []);

  const selectSection = (id: number) => {
    setSelectedId(id);
    setDraft(null);
    setMsg(null);
  };

  const toggle = (code: string) => {
    const next = new Set(draft ?? selected?.permission_codes ?? []);
    if (next.has(code)) next.delete(code);
    else next.add(code);
    setDraft(next);
  };

  const setAllForResource = (codes: string[], value: boolean) => {
    const next = new Set(draft ?? selected?.permission_codes ?? []);
    codes.forEach((c) => (value ? next.add(c) : next.delete(c)));
    setDraft(next);
  };

  const save = async () => {
    if (!selected) return;
    setSaving(true);
    setMsg(null);
    try {
      await api.put(`/access-sections/${selected.id}/permissions`, { permission_codes: [...current] });
      setDraft(null);
      sections.reload();
      setMsg({ kind: "info", text: "✅ حُفظت صلاحيات القسم وسُرّيت لكل أفراده فوراً" });
    } catch (e) {
      setMsg({ kind: "error", text: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  const createSection = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCode.trim() || !newName.trim()) return;
    try {
      const sec = await api.post<AccessSection>("/access-sections", { code: newCode.trim(), name: newName.trim() });
      setNewCode("");
      setNewName("");
      sections.reload();
      selectSection(sec.id);
    } catch (err) {
      setMsg({ kind: "error", text: (err as Error).message });
    }
  };

  const deleteSection = async (sec: AccessSection) => {
    if (!confirm(`حذف قسم «${sec.name}»؟`)) return;
    try {
      await api.del(`/access-sections/${sec.id}`);
      setSelectedId(null);
      sections.reload();
    } catch (err) {
      setMsg({ kind: "error", text: (err as Error).message });
    }
  };

  if (catalog.loading || sections.loading) return <Loading />;
  if (catalog.error) return <Alert>{catalog.error}</Alert>;

  const dirty = draft !== null && (() => {
    const base = new Set(selected?.permission_codes ?? []);
    if (base.size !== draft.size) return true;
    for (const c of base) if (!draft.has(c)) return true;
    return false;
  })();

  return (
    <div className="perm-layout">
      <aside className="perm-side card">
        <h4>الأقسام</h4>
        <ul className="perm-section-list">
          {(sections.data ?? []).map((s) => (
            <li key={s.id}>
              <button type="button" className={selected?.id === s.id ? "active" : ""} onClick={() => selectSection(s.id)}>
                {s.name}
                <span className="perm-count">{s.permission_codes.length}</span>
              </button>
            </li>
          ))}
        </ul>
        <form onSubmit={createSection} className="perm-new-section">
          <Field label="اسم قسم جديد">
            <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="مثال: المحاسبة" />
          </Field>
          <Field label="الكود (لاتيني)">
            <input value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="accounting" dir="ltr" />
          </Field>
          <button type="submit" className="btn">➕ إضافة قسم</button>
        </form>
      </aside>

      <div className="perm-main">
        {msg && <Alert kind={msg.kind === "error" ? "error" : "info"}>{msg.text}</Alert>}
        {!selected ? (
          <Empty>اختر قسماً من القائمة لتحرير صلاحياته</Empty>
        ) : (
          <>
            <div className="card perm-section-head">
              <div>
                <h3 style={{ margin: 0 }}>
                  {selected.name} {selected.is_system && <span className="perm-sys">نظامي</span>}
                </h3>
                <small style={{ color: "var(--muted)" }}>
                  {current.size} صلاحية مفعّلة — التغييرات تسري على كل مستخدمي القسم بعد الحفظ مباشرة
                </small>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" className="btn" disabled={!dirty || saving} onClick={save}>
                  {saving ? "…جارٍ الحفظ" : dirty ? "💾 حفظ التغييرات" : "محفوظ"}
                </button>
                {!selected.is_system && (
                  <button type="button" className="btn-delete" onClick={() => deleteSection(selected)}>حذف</button>
                )}
              </div>
            </div>

            {(catalog.data ?? []).map((mod) => {
              const allModuleCodes = mod.resources.flatMap((r) => r.permissions.map((p) => p.code));
              const enabledCount = allModuleCodes.filter((c) => current.has(c)).length;
              return (
                <div key={mod.module} className="card perm-module">
                  <div className="perm-module-head">
                    <h4>{mod.label}</h4>
                    <span>
                      {enabledCount}/{allModuleCodes.length}
                    </span>
                    <button type="button" className="btn btn-sm" onClick={() => setAllForResource(allModuleCodes, enabledCount < allModuleCodes.length)}>
                      {enabledCount < allModuleCodes.length ? "كل الوحدة" : "لا شيء"}
                    </button>
                  </div>
                  <table className="perm-matrix">
                    <tbody>
                      {mod.resources.map((res) => {
                        const resCodes = res.permissions.map((p) => p.code);
                        const allOn = resCodes.every((c) => current.has(c));
                        return (
                          <tr key={res.resource}>
                            <th>
                              {res.label}
                              <button type="button" className="perm-row-all" title="كل/لا شيء" onClick={() => setAllForResource(resCodes, !allOn)}>
                                {allOn ? "✓ الكل" : "لا شيء"}
                              </button>
                            </th>
                            <td>
                              <div className="perm-chips">
                                {res.permissions.map((p) => (
                                  <label key={p.code} className={`perm-chip ${current.has(p.code) ? "on" : ""} ${p.is_dangerous ? "danger" : ""} ${p.is_field ? "field" : ""}`} title={p.code}>
                                    <input type="checkbox" checked={current.has(p.code)} onChange={() => toggle(p.code)} />
                                    {p.label}
                                    {p.is_dangerous && " ⚠"}
                                    {p.is_field && " 🔒"}
                                  </label>
                                ))}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* تبويب المستخدمين — القسم + الاستثناءات + المعاينة الفعلية            */
/* ------------------------------------------------------------------ */

function UsersTab() {
  const { refreshPermissions, user: me } = useAuth();
  const users = useFetch<User[]>(() => api.get<User[]>("/auth/users"), "perm-users");
  const sections = useFetch<AccessSection[]>(() => api.get<AccessSection[]>("/access-sections"), "perm-sections-u");
  const catalog = useFetch<CatalogModule[]>(() => api.get<{ modules: CatalogModule[]; total: number }>("/permissions/catalog").then((r) => r.modules), "perm-catalog-u");
  const [userId, setUserId] = useState<number | null>(null);
  const detail = useFetch<UserPermissionDetail | null>(
    () => (userId ? api.get<UserPermissionDetail>(`/auth/users/${userId}/permissions`) : Promise.resolve(null)),
    `perm-user-${userId ?? 0}`,
  );
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [addCode, setAddCode] = useState("");
  const [addEffect, setAddEffect] = useState<"grant" | "deny">("grant");
  const [addReason, setAddReason] = useState("");

  const staffUsers = useMemo(() => (users.data ?? []).filter((u) => u.role === "staff"), [users.data]);
  const selectedUser = users.data?.find((u) => u.id === userId) ?? null;
  const overrideCodes = new Set((detail.data?.overrides ?? []).map((o) => o.code));

  const allPermOptions = useMemo(() => {
    const raw: { code: string; label: string; resource: string }[] = [];
    (catalog.data ?? []).forEach((m) =>
      m.resources.forEach((r) => r.permissions.forEach((p) => raw.push({ code: p.code, label: `${m.label} — ${p.label}`, resource: r.label }))),
    );
    // حماية من التكرار الظاهري: لو تسميتان متطابقتان نضيف اسم المورد للتمييز.
    const counts = new Map<string, number>();
    raw.forEach((o) => counts.set(o.label, (counts.get(o.label) ?? 0) + 1));
    return raw
      .map((o) => (counts.get(o.label)! > 1 ? { code: o.code, label: `${o.label} (${o.resource})` } : o))
      .sort((a, b) => a.label.localeCompare(b.label, "ar"));
  }, [catalog.data]);

  const run = async (fn: () => Promise<unknown>, okMsg?: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      detail.reload();
      users.reload();
      if (userId === me?.id) await refreshPermissions();
      if (okMsg) setMsg({ kind: "info", text: okMsg });
    } catch (e) {
      setMsg({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const assignSection = async (sectionIds: number[]) => {
    if (!userId) return;
    await run(
      () => api.put(`/auth/users/${userId}/section`, { section_ids: sectionIds }),
      sectionIds.length ? `✅ حُفظت ${sectionIds.length} أقسام — الصلاحية اتحادها` : "✅ أُلغيت كل الأقسام (baseline فقط)",
    );
  };

  const toggleSection = (sectionId: number) => {
    const current = detail.data?.section_ids ?? [];
    const next = current.includes(sectionId) ? current.filter((id) => id !== sectionId) : [...current, sectionId];
    void assignSection(next);
  };

  const addOverride = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId || !addCode) return;
    const overrides = [
      ...(detail.data?.overrides ?? []).filter((o) => o.code !== addCode),
      { permission_code: addCode, effect: addEffect, reason: addReason || null },
    ];
    await run(() => api.put(`/auth/users/${userId}/overrides`, { overrides }), addEffect === "grant" ? "✅ أُضيف منح فردي" : "✅ أُضيف سحب فردي");
    setAddCode("");
    setAddReason("");
  };

  const removeOverride = async (code: string) => {
    if (!userId) return;
    const overrides = (detail.data?.overrides ?? []).filter((o) => o.code !== code).map((o) => ({ permission_code: o.code, effect: o.effect, reason: o.reason }));
    await run(() => api.put(`/auth/users/${userId}/overrides`, { overrides }));
  };

  if (users.loading || catalog.loading) return <Loading />;
  if (users.error) return <Alert>{users.error}</Alert>;

  const inheritedMap = new Map((detail.data?.inherited ?? []).map((i) => [i.code, i.source]));

  return (
    <div className="perm-layout">
      <aside className="perm-side card">
        <h4>الموظفون (بصلاحيات أقسام)</h4>
        {staffUsers.length === 0 && <Empty>لا يوجد موظفون</Empty>}
        <ul className="perm-section-list">
          {staffUsers.map((u) => (
            <li key={u.id}>
              <button type="button" className={userId === u.id ? "active" : ""} onClick={() => { setUserId(u.id); setMsg(null); }}>
                {u.full_name || u.username}
                <span className="perm-count">{u.username}</span>
              </button>
            </li>
          ))}
        </ul>
        <p className="hint">
          أدوار «مدير/مدير عام» تتجاوز النظام كله ولا تظهر هنا.
        </p>
      </aside>

      <div className="perm-main">
        {msg && <Alert kind={msg.kind === "error" ? "error" : "info"}>{msg.text}</Alert>}
        {!userId || !selectedUser ? (
          <Empty>اختر موظفاً لعرض صلاحياته وإدارة استثناءاته</Empty>
        ) : detail.loading ? (
          <Loading />
        ) : (
          <>
            <div className="card perm-section-head">
              <div>
                <h3 style={{ margin: 0 }}>{selectedUser.full_name || selectedUser.username}</h3>
                <small style={{ color: "var(--muted)" }}>
                  الأقسام: {detail.data?.section_names.length ? detail.data.section_names.join("، ") : "بلا قسم"} — الصلاحيات الفعلية: {detail.data?.effective.length ?? 0}
                </small>
              </div>
              <Field label="أقسام الموظف (اختيار متعدد — الصلاحية اتحاد الأقسام المختارة)">
                <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 220, overflowY: "auto", minWidth: 260 }}>
                  {(sections.data ?? []).map((s) => (
                    <label key={s.id} className="check" style={{ margin: 0 }}>
                      <input
                        type="checkbox"
                        checked={(detail.data?.section_ids ?? []).includes(s.id)}
                        onChange={() => toggleSection(s.id)}
                        disabled={busy}
                      />
                      <span>
                        {s.name} <span className="perm-count">{s.permission_codes.length} صلاحية</span>
                      </span>
                    </label>
                  ))}
                  {(sections.data ?? []).length === 0 && <small style={{ color: "var(--muted)" }}>لا توجد أقسام — أنشئ أقساماً من تبويب «أقسام الصلاحيات»</small>}
                </div>
              </Field>
            </div>

            <div className="perm-two-col">
              <div className="card">
                <h4>➕➖ الاستثناءات الفردية (فوق القسم)</h4>
                <form onSubmit={addOverride} className="perm-override-form">
                  <Field label="الصلاحية">
                    <select value={addCode} onChange={(e) => setAddCode(e.target.value)}>
                      <option value="">— اختر صلاحية —</option>
                      {allPermOptions.map((o) => (
                        <option key={o.code} value={o.code}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="النوع">
                    <select value={addEffect} onChange={(e) => setAddEffect(e.target.value as "grant" | "deny")}>
                      <option value="grant">➕ منح (يضيف فوق القسم)</option>
                      <option value="deny">➖ سحب (يغلب حتى صلاحية القسم)</option>
                    </select>
                  </Field>
                  <Field label="السبب (يُوثق)">
                    <input value={addReason} onChange={(e) => setAddReason(e.target.value)} placeholder="مثال: يفحص الأصناف عند البيع" />
                  </Field>
                  <button type="submit" className="btn" disabled={!addCode || busy}>
                    إضافة استثناء
                  </button>
                </form>

                {(detail.data?.overrides ?? []).length === 0 ? (
                  <Empty>لا استثناءات — المستخدم يعمل بصلاحيات قسمه فقط</Empty>
                ) : (
                  <table className="table">
                    <thead>
                      <tr>
                        <th>الصلاحية</th>
                        <th>النوع</th>
                        <th>السبب</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail.data?.overrides ?? []).map((o) => (
                        <tr key={o.code}>
                          <td>
                            <code style={{ fontSize: 11 }}>{o.code}</code>
                            <br />
                            <small>{o.label}</small>
                          </td>
                          <td>{o.effect === "grant" ? "➕ منح" : "➖ سحب"}</td>
                          <td>{o.reason ?? "—"}</td>
                          <td>
                            <button type="button" className="btn btn-sm btn-danger" onClick={() => removeOverride(o.code)} disabled={busy}>
                              إزالة
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div className="card">
                <h4>🎯 الصلاحية الفعلية ({detail.data?.effective.length ?? 0})</h4>
                <p className="hint">🔒 حقلي · ⚠ خطر · المصدر: القسم أو منح فردي أو baseline</p>
                <div className="perm-chips">
                  {(detail.data?.effective ?? []).map((code) => {
                    const isOverride = overrideCodes.has(code);
                    const source = inheritedMap.get(code);
                    const label =
                      (detail.data?.inherited ?? []).find((i) => i.code === code)?.label ??
                      allPermOptions.find((o) => o.code === code)?.label ??
                      code;
                    return (
                      <span
                        key={code}
                        className={`perm-chip on static ${isOverride ? "override" : ""}`}
                        title={code + (source ? ` (المصدر: ${source})` : isOverride ? " (منح فردي)" : "")}
                      >
                        {label}
                        {isOverride ? " ✋" : ""}
                      </span>
                    );
                  })}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
