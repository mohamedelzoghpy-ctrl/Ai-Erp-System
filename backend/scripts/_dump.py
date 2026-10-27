s=open("/Users/mohamedelzoghpy/Ai-Erp-System-1/frontend/src/pages/CompanyAdmin.tsx", encoding="utf-8").read()
idx = s.find("            {memberCompany && (")
end = s.find("            )}", idx)
block = s[idx:end+14]
open("/tmp/block.txt","w",encoding="utf-8").write(block)
print("len", len(block))