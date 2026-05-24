import re

SVG = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\Page 1.svg'
SCREEN_X, SCREEN_Y = 39, 94.8

with open(SVG, 'r', encoding='utf-8') as f:
    s = f.read()

# hero card rects
for m in re.finditer(
    r'<rect fill="(#[^"]+)" transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)" width="([\d.]+)" height="([\d.]+)"',
    s,
):
    fill, x, y, w, h = m.groups()
    rx, ry = float(x) - SCREEN_X, float(y) - SCREEN_Y
    if 120 <= ry <= 320:
        print(f'hero area: {fill} ({rx:.0f},{ry:.0f}) {w}x{h}')

# quote area
for m in re.finditer(
    r'<rect fill="(#[^"]+)" transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)" width="([\d.]+)" height="([\d.]+)"',
    s,
):
    fill, x, y, w, h = m.groups()
    rx, ry = float(x) - SCREEN_X, float(y) - SCREEN_Y
    if 520 <= ry <= 760:
        print(f'quote area: {fill} ({rx:.0f},{ry:.0f}) {w}x{h}')

# path clusters in hero 125-320
paths = []
for m in re.finditer(
    r'<path fill="(#[^"]+)" transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)" d="([^"]+)"',
    s,
):
    fill, x, y, d = m.groups()
    rx, ry = float(x) - SCREEN_X, float(y) - SCREEN_Y
    if 125 <= ry <= 320:
        paths.append((ry, rx, fill))

paths.sort()
for p in paths:
    print(f'hero path y={p[0]:.0f} x={p[1]:.0f} {p[2]}')

# quote text paths
paths2 = []
for m in re.finditer(
    r'<path fill="(#[^"]+)" transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)" d="([^"]+)"',
    s,
):
    fill, x, y, d = m.groups()
    rx, ry = float(x) - SCREEN_X, float(y) - SCREEN_Y
    if 520 <= ry <= 760:
        paths2.append((ry, rx, fill))
paths2.sort()
for p in paths2:
    print(f'quote path y={p[0]:.0f} x={p[1]:.0f} {p[2]}')
