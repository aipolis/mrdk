"""生成晴天大图标（龙）"""
from PIL import Image, ImageDraw
import os

out = os.path.join(os.path.dirname(__file__), '..', 'images', 'weather-sun.png')
size = 160
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
cx, cy = size // 2, size // 2
# 太阳主体
d.ellipse([cx - 28, cy - 28, cx + 28, cy + 28], fill=(255, 220, 50, 255))
# 光芒
for i in range(8):
    import math
    ang = math.radians(i * 45)
    x1 = cx + math.cos(ang) * 36
    y1 = cy + math.sin(ang) * 36
    x2 = cx + math.cos(ang) * 52
    y2 = cy + math.sin(ang) * 52
    d.line([(x1, y1), (x2, y2)], fill=(255, 200, 40, 255), width=8)
img.save(out)
print('ok', out)
