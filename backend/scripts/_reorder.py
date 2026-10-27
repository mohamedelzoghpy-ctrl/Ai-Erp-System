p = "/Users/mohamedelzoghpy/Ai-Erp-System-1/frontend/src/pages/CompanyAdmin.tsx"
s = open(p, encoding="utf-8").read()

idx = s.find("            {memberCompany && (")
print("idx", idx)
end = s.find("            )}", idx)
print("end", end)
block = s[idx:end+ len("            )}")]
print("BLOCK LEN", len(block))

members_start = block.find("ربط المستخدمين")
branches_start = block.find("الفروع")
warehouses_start = block.find("المخازن")
print("members_start", members_start)
print("branches_start", branches_start)
print("warehouses_start", warehouses_start)