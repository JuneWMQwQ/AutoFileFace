# -*- coding: utf-8 -*-
"""生成程序图标 AutoFillFace.ico（Pillow 绘制）"""
import os
from PIL import Image, ImageDraw, ImageFont

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角深蓝底
def rounded_rect(draw, xy, radius, fill):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)

rounded_rect(d, (8, 8, 248, 248), 48, (30, 58, 138, 255))

# 渐变感：叠一个浅色高光弧
d.ellipse([40, 30, 216, 160], fill=(64, 100, 200, 255))
d.ellipse([40, 30, 216, 160], outline=None)

# 钥匙
key_color = (255, 214, 90, 255)
# 钥匙环
d.ellipse([70, 70, 130, 130], outline=key_color, width=10)
# 钥匙柄
d.rectangle([116, 96, 172, 116], fill=key_color)
# 齿
d.rectangle([168, 96, 176, 140], fill=key_color)
d.rectangle([156, 120, 164, 138], fill=key_color)

# 人脸弧线（下方）
face_color = (255, 255, 255, 230)
d.arc([70, 150, 190, 230], start=180, end=360, fill=face_color, width=8)
# 眼睛
d.ellipse([104, 168, 116, 180], fill=face_color)
d.ellipse([142, 168, 154, 180], fill=face_color)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AutoFillFace.ico")
img.save(out, sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
print("icon saved:", out, os.path.getsize(out), "bytes")
