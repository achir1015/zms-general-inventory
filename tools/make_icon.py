"""產生程式圖示：assets/icon.png（1024）、packaging/icon.ico、assets/icon.ico。

設計：深藍到青綠的圓角方塊，中間疊著三個貨箱，右上角金幣寫「存」。
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # 漸層底
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    c1, c2 = (15, 60, 110), (14, 150, 120)
    for y in range(S):
        for_x = lerp(c1, c2, y / S)
        gd.line([(0, y), (S, y)], fill=for_x + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # 光澤
    gloss = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse([-200, -520, S + 200, 420], fill=(255, 255, 255, 34))
    img = Image.alpha_composite(img, Image.composite(gloss, Image.new("RGBA", (S, S)), mask))
    d = ImageDraw.Draw(img)
    # 疊起來的貨箱（進銷存）
    def box(x0, y0, w, h, base, light, dark):
        global img
        shd = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(shd).rounded_rectangle([x0 + 12, y0 + 22, x0 + w + 12, y0 + h + 22], radius=34,
                                              fill=(0, 0, 0, 95))
        out = Image.alpha_composite(box.img, shd.filter(ImageFilter.GaussianBlur(18)))
        dd = ImageDraw.Draw(out)
        dd.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=34, fill=base)
        dd.rounded_rectangle([x0, y0, x0 + w, y0 + 70], radius=34, fill=light)
        dd.rectangle([x0, y0 + 40, x0 + w, y0 + 70], fill=light)
        cx0 = x0 + w // 2
        dd.rectangle([cx0 - 34, y0, cx0 + 34, y0 + h], fill=dark)          # 封箱膠帶
        dd.rounded_rectangle([x0 + 40, y0 + h - 92, x0 + 150, y0 + h - 40], radius=10, fill=(255, 255, 255, 235))
        box.img = out
    box.img = img
    box(170, 520, 330, 300, (214, 141, 64, 255), (232, 170, 96, 255), (186, 112, 44, 255))
    box(524, 520, 330, 300, (214, 141, 64, 255), (232, 170, 96, 255), (186, 112, 44, 255))
    box(347, 210, 330, 300, (236, 168, 80, 255), (248, 196, 120, 255), (204, 132, 52, 255))
    img = box.img
    d = ImageDraw.Draw(img)
    # 金幣
    cx, cy, r = 800, 230, 140
    coin_sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(coin_sh).ellipse([cx - r + 10, cy - r + 18, cx + r + 10, cy + r + 18], fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img, coin_sh.filter(ImageFilter.GaussianBlur(16)))
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(240, 180, 40, 255), outline=(255, 226, 140, 255), width=14)
    d.ellipse([cx - r + 30, cy - r + 30, cx + r - 30, cy + r - 30], outline=(201, 138, 20, 255), width=6)
    font_path = os.path.join(HERE, "assets", "fonts", "NotoSansTC-VF.ttf")
    try:
        font = ImageFont.truetype(font_path, 140)
        try:
            font.set_variation_by_name("Black")
        except Exception:
            try:
                font.set_variation_by_axes([900])
            except Exception:
                pass
    except Exception:
        font = ImageFont.load_default()
    d.text((cx, cy - 6), "存", font=font, fill=(20, 50, 92, 255), anchor="mm")
    out = os.path.join(HERE, "assets", "icon.png")
    img.save(out)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    for p in (os.path.join(HERE, "packaging", "icon.ico"), os.path.join(HERE, "assets", "icon.ico")):
        img.save(p, sizes=sizes)
    print("ok", out)


if __name__ == "__main__":
    main()
