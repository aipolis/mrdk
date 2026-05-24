"""从设计稿导出 Tab 图标 81×81"""
from PIL import Image
import os

src = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\scripts\svg-assets'
dst = r'c:\Users\Administrator\Desktop\量化交易\明日当空\miniprogram-lite\images'

pairs = [
    ('img_3.png', 'tab-home.png', 'tab-home-active.png'),
    ('img_5.png', 'tab-history.png', 'tab-history-active.png'),
    ('img_6.png', 'tab-profile.png', 'tab-profile-active.png'),
]

os.makedirs(dst, exist_ok=True)
size = 81

for src_name, normal, active in pairs:
    path = os.path.join(src, src_name)
    if not os.path.exists(path):
        print('skip', src_name)
        continue
    img = Image.open(path).convert('RGBA')
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    img.save(os.path.join(dst, normal))

    # 选中态：略提亮 + 蓝色调
    active_img = img.copy()
    px = active_img.load()
    for y in range(size):
        for x in range(size):
            r, g, b, a = px[x, y]
            if a > 20:
                px[x, y] = (min(255, int(r * 0.7 + 2 * 40)), min(255, int(g * 0.7 + 132 * 0.3)), min(255, int(b * 0.7 + 199 * 0.3)), a)
    active_img.save(os.path.join(dst, active))

print('tab icons done')
