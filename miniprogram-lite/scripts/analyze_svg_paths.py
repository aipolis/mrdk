import re

SVG = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\Page 1.svg'
SCREEN_X, SCREEN_Y = 39, 94.8

with open(SVG, 'r', encoding='utf-8') as f:
    s = f.read()

paths = []
for m in re.finditer(
    r'<path fill="(#[^"]+)" transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)" d="([^"]+)"',
    s,
):
    fill, x, y, d = m.groups()
    rx = round(float(x) - SCREEN_X, 1)
    ry = round(float(y) - SCREEN_Y, 1)
    paths.append({'fill': fill, 'x': rx, 'y': ry, 'd': d[:40]})

# group by y (within 8px)
paths.sort(key=lambda p: (p['y'], p['x']))
clusters = []
for p in paths:
    if not clusters or abs(p['y'] - clusters[-1]['y']) > 12:
        clusters.append({'y': p['y'], 'items': [p]})
    else:
        clusters[-1]['items'].append(p)

print('path clusters', len(clusters))
for c in clusters[:35]:
    fills = ', '.join(sorted(set(i['fill'] for i in c['items'])))
    xs = [i['x'] for i in c['items']]
    print(f"y={c['y']:6.1f} n={len(c['items']):2d} fills={fills} x_range={min(xs):.0f}-{max(xs):.0f}")

# E63838 text (brand/red)
red_text = [p for p in paths if p['fill'].upper() == '#E63838']
print('\nred text paths', len(red_text))
for p in sorted(red_text, key=lambda x: (x['y'], x['x']))[:15]:
    print(f"  y={p['y']} x={p['x']}")
