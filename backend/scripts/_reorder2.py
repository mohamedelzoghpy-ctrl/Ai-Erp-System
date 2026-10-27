p = "/Users/mohamedelzoghpy/Ai-Erp-System-1/frontend/src/pages/CompanyAdmin.tsx"
s = open(p, encoding="utf-8").read()

# The member block: from "{members.length > 0 ? (" up to and including the addMember form closing "</form>"
m_start = s.find("                {members.length > 0 ? (")
# find the closing of addMember form: the </form> after memberUsername
m_form_end_marker = '                  <button className="btn btn-primary" disabled={busy}>إضافة عضوية</button>\n                </form>'
m_form_end = s.find(m_form_end_marker, m_start) + len(m_form_end_marker)
members_block = s[m_start:m_form_end]
print("members_block len", len(members_block))

# Remove members block from current location
s2 = s[:m_start] + s[m_form_end:]

# Now insert members block after the warehouse form. Find warehouse form's closing </form> followed by "              </>"
wh_marker = '                  <button className="btn btn-primary" disabled={busy}>إضافة مخزن</button>\n                 </form>'
wh_end = s2.find(wh_marker) + len(wh_marker)
# insert before the following "              </>"
insert_point = s2.find("              </>", wh_end)
print("insert_point", insert_point)

# Build new: add a header before members block
members_with_header = "\n                <h3>3.3 الأعضاء (الخزن)</h3>\n" + members_block + "\n"

new_s = s2[:insert_point] + members_with_header + s2[insert_point:]
open(p, "w", encoding="utf-8").write(new_s)
print("done")