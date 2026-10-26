p = "/Users/mohamedelzoghpy/Ai-Erp-System-1/frontend/src/pages/CompanyAdmin.tsx"
lines = open(p, encoding="utf-8").read().split("\n")
# Insert before line index 102 (0-based) = line 103
lines.insert(102, "  const removeMember = (userId: number) => {")
open(p, "w", encoding="utf-8").write("\n".join(lines))
print("done")