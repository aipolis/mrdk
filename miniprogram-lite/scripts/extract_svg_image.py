import re
import base64
import os

path = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\Page 1.svg'
out = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\scripts\design-preview.png'

with open(path, 'r', encoding='utf-8') as f:
    s = f.read()

# extract first base64 png/jpeg
m = re.search(r'xlink:href="data:image/(png|jpeg);base64,([^"]+)"', s)
if not m:
    m = re.search(r'href="data:image/(png|jpeg);base64,([^"]+)"', s)
if m:
    ext, b64 = m.group(1), m.group(2)
    data = base64.b64decode(b64)
    out = out.replace('.png', f'.{ext}')
    with open(out, 'wb') as f:
        f.write(data)
    print('saved', out, len(data))
else:
    print('no embedded image')

# rects with position
rects = re.findall(r'<rect[^>]*x="([\d.]+)"[^>]*y="([\d.]+)"[^>]*width="([\d.]+)"[^>]*height="([\d.]+)"[^>]*fill="#([^"]+)"', s)
print('rect count', len(rects))
for r in rects[:30]:
    print('RECT', r)

# all elements with transform and class/id
ids = re.findall(r'id="([^"]+)"', s)
print('ids sample', ids[:30])
