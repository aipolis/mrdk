"""全面解析 Page 1.svg 设计稿布局"""
import re
import base64
import os

SVG = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\Page 1.svg'
SX, SY = 39, 94.8
W = 390

with open(SVG, 'r', encoding='utf-8') as f:
    s = f.read()

def rel(x, y):
    return round(float(x) - SX, 1), round(float(y) - SY, 1)

print('=== CANVAS', W, 'x948 inner screen ===\n')

# all rects
rects = []
for m in re.finditer(
    r'<rect fill="(#[^"]+)" transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)" width="([\d.]+)" height="([\d.]+)"',
    s,
):
    fill, x, y, w, h = m.groups()
    rx, ry = rel(x, y)
    rects.append(dict(fill=fill, x=rx, y=ry, w=float(w), h=float(h)))

rects.sort(key=lambda r: (r['y'], r['x']))
for r in rects:
    print(f"rect {r['fill']:8s} ({r['x']:5.0f},{r['y']:5.0f}) {r['w']:5.0f}x{r['h']:4.0f}")

# path text clusters by y
paths = []
for m in re.finditer(
    r'<path fill="(#[^"]+)" transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)" d="([^"]+)"',
    s,
):
    fill, x, y, d = m.groups()
    rx, ry = rel(x, y)
    paths.append(dict(fill=fill, x=rx, y=ry))

paths.sort(key=lambda p: (p['y'], p['x']))
clusters = []
for p in paths:
    if not clusters or abs(p['y'] - clusters[-1]['y']) > 10:
        clusters.append(dict(y=p['y'], items=[p]))
    else:
        clusters[-1]['items'].append(p)

print('\n=== TEXT CLUSTERS (path outlines) ===')
for c in clusters:
    xs = [i['x'] for i in c['items']]
    fills = sorted(set(i['fill'] for i in c['items']))
    print(f"y={c['y']:6.1f}  x={min(xs):5.0f}-{max(xs):5.0f}  fills={fills}")

# images with parent transform
print('\n=== IMAGES ===')
for m in re.finditer(
    r'<g[^>]*transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)"[^>]*><image id="(img_\d+)" width="([\d.]+)" height="([\d.]+)"',
    s,
):
    x, y, iid, w, h = m.groups()
    rx, ry = rel(float(x), float(y))
    print(f'{iid} @ ({rx},{ry}) clip {w}x{h}')

for m in re.finditer(
    r'<image id="(img_\d+)" width="([\d.]+)" height="([\d.]+)"',
    s,
):
    iid, w, h = m.groups()
    start = max(0, m.start() - 400)
    chunk = s[start:m.start()]
    tm = re.search(r'transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)"', chunk)
    if tm:
        rx, ry = rel(float(tm.group(1)), float(tm.group(2)))
        print(f'{iid} (near) @ ({rx},{ry}) src {w}x{h}')

# measure key gaps
print('\n=== KEY MEASURES ===')
hero = [r for r in rects if 120 <= r['y'] <= 320]
quote = [r for r in rects if 520 <= r['y'] <= 760]
tab = [r for r in rects if r['y'] >= 850]
print('hero outer white:', [r for r in hero if r['fill']=='#FFF' and r['w']>300])
print('pills:', [r for r in hero if r['h']<=40 and r['w']>80])
print('quote boxes:', [r for r in quote if r['fill'] in ('#F0F9FF','#FEFCE8')])
print('tab bar:', tab)

# header date pill
hdr = [r for r in rects if r['y'] < 120]
print('header rects:', hdr)
