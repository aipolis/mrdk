"""生成今日天气大图标（透明底，用于彩色方块内）"""
import math
import os
from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'images')
SIZE = 160


def save(name, img):
    path = os.path.join(OUT_DIR, name)
    img.save(path)
    print('ok', path)


def draw_sun(d, cx, cy, r=28, ray_inner=36, ray_outer=52, color=(255, 220, 50, 255)):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    for i in range(8):
        ang = math.radians(i * 45)
        x1 = cx + math.cos(ang) * ray_inner
        y1 = cy + math.sin(ang) * ray_inner
        x2 = cx + math.cos(ang) * ray_outer
        y2 = cy + math.sin(ang) * ray_outer
        d.line([(x1, y1), (x2, y2)], fill=color, width=8)


def gen_sun():
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    draw_sun(d, SIZE // 2, SIZE // 2)
    save('weather-sun.png', img)


def gen_cloud():
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = SIZE // 2, SIZE // 2 + 8
    d.ellipse([cx - 46, cy - 22, cx + 46, cy + 22], fill=(255, 255, 255, 255))
    d.ellipse([cx - 30, cy - 34, cx + 10, cy + 6], fill=(255, 255, 255, 255))
    d.ellipse([cx + 4, cy - 30, cx + 44, cy + 6], fill=(255, 255, 255, 255))
    draw_sun(d, cx - 34, cy - 38, r=18, ray_inner=24, ray_outer=34, color=(255, 210, 40, 255))
    save('weather-cloud.png', img)


def gen_rain():
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = SIZE // 2, SIZE // 2 - 10
    d.ellipse([cx - 44, cy - 20, cx + 44, cy + 20], fill=(255, 255, 255, 255))
    d.ellipse([cx - 28, cy - 32, cx + 12, cy + 4], fill=(255, 255, 255, 255))
    d.ellipse([cx + 6, cy - 28, cx + 42, cy + 4], fill=(255, 255, 255, 255))
    for i, ox in enumerate([-24, -8, 8, 24]):
        top = cy + 28 + (i % 2) * 10
        d.polygon([
            (cx + ox, top),
            (cx + ox - 6, top + 14),
            (cx + ox + 6, top + 14),
        ], fill=(120, 200, 255, 255))
    save('weather-rain.png', img)


if __name__ == '__main__':
    gen_sun()
    gen_cloud()
    gen_rain()
