import re
import json

path = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\Page 1.svg'
with open(path, 'r', encoding='utf-8') as f:
    s = f.read()

print('len', len(s))
for pat, name in [
    (r'viewBox="([^"]+)"', 'viewBox'),
    (r'width="(\d+)"', 'width'),
    (r'height="(\d+)"', 'height'),
]:
    m = re.search(pat, s[:5000])
    print(name, m.group(1) if m else 'none')

# tspan and text
texts = re.findall(r'>([^<>]{1,80})</tspan>', s)
texts += re.findall(r'<text[^>]*>([^<]+)</text>', s)
seen = set()
for t in texts:
    t = t.strip()
    if t and t not in seen and not t.startswith('http'):
        seen.add(t)
        print('TEXT:', t)

# fill colors used
fills = re.findall(r'fill="#([0-9A-Fa-f]{3,8})"', s)
from collections import Counter
c = Counter(fills)
print('TOP FILLS:', c.most_common(20))

# font sizes
fonts = re.findall(r'font-size="(\d+)"', s)
print('font sizes', sorted(set(fonts)))

# look for foreignObject or embedded png
print('has image', 'xlink:href' in s or 'base64' in s[:50000])
