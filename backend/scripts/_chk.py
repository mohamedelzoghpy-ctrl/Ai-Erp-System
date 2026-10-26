s=open('/Users/mohamedelzoghpy/Ai-Erp-System-1/frontend/src/pages/CompanyAdmin.tsx').read()
print('brace', s.count('{'), s.count('}'))
print('paren', s.count('('), s.count(')'))
print('bracket', s.count('['), s.count(']'))