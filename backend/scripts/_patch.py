import re

path = "/Users/mohamedelzoghpy/Ai-Erp-System-1/frontend/src/pages/CompanyAdmin.tsx"
s = open(path, encoding="utf-8").read()

# Find the addMember form's closing: the line with "إضافة عضوية" button followed by </form>
needle = '''                  <button className="btn btn-primary" disabled={busy}>إضافة عضوية</button>
                </form>'''
assert needle in s, "needle not found"

insertion = '''                  <button className="btn btn-primary" disabled={busy}>إضافة عضوية</button>
                 </form>

                 <h3 style={{ marginTop: 16 }}>الفروع</h3>
                 {platformBranches.length > 0 ? (
                   <div className="table-wrap" style={{ marginBottom: 12 }}>
                     <table>
                       <thead><tr><th>الاسم</th><th>الرمز</th><th>الموقع</th><th>الحالة</th></tr></thead>
                       <tbody>{platformBranches.map((b) => (
                         <tr key={b.id}><td>{b.name}</td><td dir="ltr">{b.code}</td><td>{b.location || "—"}</td><td>{b.is_active ? "نشط" : "معطّل"}</td></tr>
                       ))}</tbody>
                     </table>
                   </div>
                 ) : <Empty>لا توجد فروع.</Empty>}
                 <form onSubmit={addPlatformBranch} className="form-grid" style={{ marginBottom: 16 }}>
                   <Field label="اسم الفرع"><input value={newBranchName} onChange={(e) => setNewBranchName(e.target.value)} required /></Field>
                   <Field label="رمز الفرع"><input dir="ltr" value={newBranchCode} onChange={(e) => setNewBranchCode(e.target.value)} required /></Field>
                   <button className="btn btn-primary" disabled={busy}>إضافة فرع</button>
                 </form>

                 <h3>المخازن</h3>
                 {platformWarehouses.length > 0 ? (
                   <div className="table-wrap" style={{ marginBottom: 12 }}>
                     <table>
                       <thead><tr><th>الاسم</th><th>الكود</th><th>الفرع</th><th>الموقع</th><th>الحالة</th></tr></thead>
                       <tbody>{platformWarehouses.map((w) => (
                         <tr key={w.id}><td>{w.name}</td><td>{w.code}</td><td>{platformBranches.find((b) => b.id === w.branch_id)?.name || "—"}</td><td>{w.location || "—"}</td><td>{w.is_active ? "نشط" : "معطّل"}</td></tr>
                       ))}</tbody>
                     </table>
                   </div>
                 ) : <Empty>لا توجد مخازن.</Empty>}
                 <form onSubmit={addPlatformWarehouse} className="form-grid">
                   <Field label="اسم المخزن"><input value={newWhName} onChange={(e) => setNewWhName(e.target.value)} required /></Field>
                   <Field label="كود المخزن"><input dir="ltr" value={newWhCode} onChange={(e) => setNewWhCode(e.target.value)} required /></Field>
                   <Field label="الفرع">
                     <select value={newWhBranch ?? ""} onChange={(e) => setNewWhBranch(Number(e.target.value) || null)}>
                       <option value="">— اختر فرع —</option>
                       {platformBranches.map((b) => (<option key={b.id} value={b.id}>{b.name}</option>))}
                     </select>
                   </Field>
                   <Field label="الموقع"><input value={newWhLocation} onChange={(e) => setNewWhLocation(e.target.value)} /></Field>
                   <button className="btn btn-primary" disabled={busy}>إضافة مخزن</button>
                 </form>'''

s = s.replace(needle, insertion, 1)
open(path, "w", encoding="utf-8").write(s)
print("done")
