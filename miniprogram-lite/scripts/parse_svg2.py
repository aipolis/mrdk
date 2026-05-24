import re

path = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\Page 1.svg'
with open(path, 'r', encoding='utf-8') as f:
    s = f.read()

# svg root
print(s[:800])

# image tags
for m in re.finditer(r'<image[^>]+>', s):
    tag = m.group(0)
    if len(tag) > 300:
        tag = tag[:300] + '...'
    print('IMAGE TAG:', tag)

# find text-like content in any form
for kw in ['明日', '识别', '龙', '云', '订阅', '共勉', '走势', '出门', '带伞', '下雨']:
    if kw in s:
        idx = s.index(kw)
        print('FOUND', kw, 'at', idx, s[max(0,idx-50):idx+80])
