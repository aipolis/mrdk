from PIL import Image, ImageDraw
import os

root = os.path.join(os.path.dirname(__file__), '..', 'images')
os.makedirs(root, exist_ok=True)


def tab(name, active=False):
    s = 81
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = (255, 77, 79, 255) if active else (107, 114, 128, 255)
    if name == 'home':
        d.ellipse([18, 18, 63, 63], outline=c, width=4)
        d.polygon([(40, 28), (52, 44), (28, 44)], fill=c)
    elif name == 'history':
        d.rounded_rectangle([20, 22, 61, 59], radius=6, outline=c, width=4)
        d.line([(28, 34), (53, 34)], fill=c, width=3)
        d.line([(28, 44), (48, 44)], fill=c, width=3)
    else:
        d.ellipse([24, 18, 57, 51], outline=c, width=4)
        d.arc([18, 36, 63, 72], 0, 180, fill=c, width=4)
    suffix = '-active' if active else ''
    img.save(os.path.join(root, 'tab-%s%s.png' % (name, suffix)))


for n in ['home', 'history', 'my']:
    tab(n, False)
    tab(n, True)

logo = Image.new('RGBA', (192, 192), (255, 77, 79, 255))
d = ImageDraw.Draw(logo)
d.ellipse([8, 8, 184, 184], fill=(255, 77, 79, 255))
logo.save(os.path.join(root, 'logo-192.png'))
print('ok')
