"""从 Figma 导出 SVG 提取布局元素（坐标相对画布 468x1137）"""
import re
import base64
import os
import json

SVG = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\Page 1.svg'
OUT_DIR = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\scripts\svg-assets'

with open(SVG, 'r', encoding='utf-8') as f:
    s = f.read()

# 主屏幕区域
SCREEN = {'x': 39, 'y': 94.8, 'w': 390, 'h': 948}

def rel(x, y):
    return round(x - SCREEN['x'], 1), round(y - SCREEN['y'], 1)

elements = []

# rects with transform
for m in re.finditer(
    r'<rect fill="(#[^"]+)" transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)" width="([\d.]+)" height="([\d.]+)"',
    s,
):
    fill, x, y, w, h = m.groups()
    rx, ry = rel(float(x), float(y))
    elements.append({
        'type': 'rect', 'fill': fill, 'x': rx, 'y': ry,
        'w': float(w), 'h': float(h),
    })

# rects without transform (absolute)
for m in re.finditer(r'<rect fill="(#[^"]+)" (?!transform)(?:[^>]*?)width="([\d.]+)" height="([\d.]+)"', s):
    pass

# paths with transform + fill (text is path)
path_count = 0
text_paths = []
for m in re.finditer(
    r'<path fill="(#[^"]+)" transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)" d="([^"]{20,200})"',
    s,
):
    fill, x, y, d = m.groups()
    rx, ry = rel(float(x), float(y))
    text_paths.append({'fill': fill, 'x': rx, 'y': ry, 'd_len': len(d)})
    path_count += 1

# images with transform
os.makedirs(OUT_DIR, exist_ok=True)
img_idx = 0
images = []
for m in re.finditer(
    r'<image id="(img_\d+)" width="([\d.]+)" height="([\d.]+)"[^>]*xlink:href="data:image/(png|jpeg);base64,([^"]+)"',
    s,
):
    iid, w, h, ext, b64 = m.groups()
    # find transform before this image (look back 200 chars)
    start = max(0, m.start() - 300)
    chunk = s[start:m.start()]
    tm = re.search(r'transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)"', chunk)
    x, y = (float(tm.group(1)), float(tm.group(2))) if tm else (0, 0)
    rx, ry = rel(x, y)
    data = base64.b64decode(b64)
    fp = os.path.join(OUT_DIR, f'{iid}.png')
    with open(fp, 'wb') as f:
        f.write(data)
    images.append({'id': iid, 'x': rx, 'y': ry, 'w': float(w), 'h': float(h)})
    img_idx += 1

# Also search image with transform after id
for m in re.finditer(
    r'<g[^>]*transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)"[^>]*><image id="(img_\d+)"',
    s,
):
    x, y, iid = m.groups()
    rx, ry = rel(float(x), float(y))
    print('g image', iid, rx, ry)

# rounded card-like rects: white/large
cards = [e for e in elements if e['w'] > 200 and e['h'] > 80]
bars = [e for e in elements if e['h'] > 20 and e['w'] < 40 and e['w'] > 8]

print('=== SCREEN', SCREEN)
print('rects', len(elements))
print('text paths', len(text_paths))
print('images', len(images))
for e in sorted(elements, key=lambda x: (x['y'], x['x'])):
    print(f"RECT {e['fill']} @ ({e['x']},{e['y']}) {e['w']}x{e['h']}")
for im in images:
    print(f"IMG {im['id']} @ ({im['x']},{im['y']}) {im['w']}x{im['h']}")

# y-cluster text paths for line detection
text_paths.sort(key=lambda t: (t['y'], t['x']))
print('=== TEXT Y clusters (top 25)')
for t in text_paths[:25]:
    print(f"  y={t['y']:6.1f} x={t['x']:6.1f} fill={t['fill']}")

# red accent elements
reds = [e for e in elements if 'E63838' in e['fill'].upper() or e['fill'].upper() in ('#E63838', '#FF4D4F')]
print('red rects', len(reds))
for e in reds:
    print(f"  RED {e}")
