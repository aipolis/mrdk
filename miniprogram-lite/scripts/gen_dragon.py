"""中国龙剪纸风剪影 — 红金双色，小尺寸可辨认"""
from PIL import Image, ImageDraw
import math
import os

root = os.path.join(os.path.dirname(__file__), '..', 'images')
os.makedirs(root, exist_ok=True)

SIZE = 512
img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

RED = (255, 77, 79, 255)
RED_DEEP = (207, 19, 34, 255)
GOLD = (250, 173, 20, 255)
GOLD_PALE = (255, 214, 102, 255)
WHITE = (255, 255, 255, 255)


def ribbon_polygon(centerline, half_widths):
    """中心线 + 半宽 → 闭合多边形"""
    left, right = [], []
    n = len(centerline)
    for i, (x, y) in enumerate(centerline):
        hw = half_widths[min(i, len(half_widths) - 1)]
        if i == 0:
            dx, dy = centerline[1][0] - x, centerline[1][1] - y
        elif i == n - 1:
            dx, dy = x - centerline[i - 1][0], y - centerline[i - 1][1]
        else:
            dx = centerline[i + 1][0] - centerline[i - 1][0]
            dy = centerline[i + 1][1] - centerline[i - 1][1]
        ln = math.hypot(dx, dy) or 1
        nx, ny = -dy / ln, dx / ln
        left.append((x + nx * hw, y + ny * hw))
        right.append((x - nx * hw, y - ny * hw))
    return left + right[::-1]


# ── 蛇身 S 形（从尾到头）──
spine = [
    (88, 368), (108, 332), (140, 295), (185, 262), (240, 242),
    (300, 238), (358, 258), (405, 295), (430, 340), (420, 378),
    (385, 405), (330, 412), (270, 395), (215, 360), (165, 330),
    (125, 320), (98, 345),
]
widths = [18, 22, 28, 36, 42, 46, 44, 38, 32, 28, 24, 22, 20, 18, 16, 14, 12]
d.polygon(ribbon_polygon(spine, widths), fill=RED)

# 背鳍
fins = [
    [(240, 210), (255, 175), (270, 210)],
    [(300, 205), (318, 168), (335, 205)],
    [(360, 220), (378, 185), (395, 225)],
    [(400, 265), (418, 235), (430, 275)],
]
for f in fins:
    d.polygon(f, fill=GOLD)

# ── 龙头（侧脸，占视觉焦点）──
d.ellipse([368, 248, 468, 348], fill=RED)          # 头
d.polygon([(448, 278), (498, 268), (518, 288), (505, 308), (455, 312)], fill=RED_DEEP)  # 吻
d.polygon([(455, 312), (505, 308), (498, 328), (460, 332)], fill=(180, 30, 40, 255))    # 下颚
d.ellipse([488, 282, 496, 290], fill=RED_DEEP)     # 鼻孔

# 眼
d.ellipse([408, 278, 436, 306], fill=WHITE)
d.ellipse([416, 286, 428, 298], fill=(20, 20, 30, 255))
d.ellipse([418, 288, 422, 292], fill=WHITE)

# 龙角（鹿角分叉 — 最识别特征）
d.polygon([(390, 252), (375, 195), (398, 230), (410, 255)], fill=GOLD)
d.polygon([(375, 195), (358, 158), (382, 188)], fill=GOLD_PALE)
d.polygon([(375, 195), (345, 175), (368, 198)], fill=GOLD_PALE)

d.polygon([(430, 248), (448, 188), (438, 225), (425, 252)], fill=GOLD)
d.polygon([(448, 188), (468, 148), (455, 182)], fill=GOLD_PALE)
d.polygon([(448, 188), (478, 168), (458, 195)], fill=GOLD_PALE)

# 龙须
for pts in [
    [(505, 308), (545, 292), (575, 285)],
    [(500, 318), (540, 328), (570, 338)],
    [(492, 328), (525, 352), (555, 365)],
]:
    d.line(pts, fill=GOLD, width=7, joint='curve')
    d.ellipse([pts[2][0] - 5, pts[2][1] - 5, pts[2][0] + 5, pts[2][1] + 5], fill=GOLD_PALE)

# 龙爪
for claw in [
    [(185, 295), (162, 272), (178, 262), (198, 278)],
    [(330, 405), (352, 430), (368, 420), (348, 400)],
    [(270, 395), (248, 418), (262, 428), (282, 408)],
]:
    d.polygon(claw[:3], fill=GOLD)
    d.polygon([(claw[1][0], claw[1][1]), (claw[1][0] - 5, claw[1][1] + 12), (claw[1][0] + 5, claw[1][1] + 12)], fill=GOLD_PALE)

# 火焰尾
d.polygon([(88, 368), (58, 382), (48, 358), (62, 338), (82, 342)], fill=RED)
d.polygon([(58, 382), (32, 395), (42, 372)], fill=GOLD)
d.polygon([(48, 358), (28, 345), (45, 335)], fill=GOLD_PALE)

out = os.path.join(root, 'icon-dragon.png')
img.save(out)
print('saved', out)
