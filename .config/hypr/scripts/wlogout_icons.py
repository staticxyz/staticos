#!/usr/bin/env python3
"""Значки wlogout: старые (стандартные картинки wlogout) или новые. 30.09.2026.

    wlogout_icons.py new      значки как в power_menu.py (Material Design из Nerd Font)
    wlogout_icons.py old      стандартные /usr/share/wlogout/icons/*.png
    wlogout_icons.py status   new / old
    wlogout_icons.py regen    перерисовать новые под нынешнюю палитру (смена обоев)

пользователь вернул прежнее меню wlogout, но значки нового меню понравились больше —
поэтому выбор (Настройки → Внешний вид). Новые значки рисуются в PNG 256×256
цветом on_surface палитры обоев: так же светлые, как стандартные, и видны и на
кнопке, и при наведении. В style.css правятся только строки между метками.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

CSS = os.path.expanduser("~/.config/wlogout/style.css")
OUT = os.path.expanduser("~/.local/share/jarvis/wlogout-icons")
FLAG = os.path.expanduser("~/.config/hypr/state/wlogout-icons")
BEGIN, END = "/* >>> значки — пишет wlogout_icons.py */", "/* <<< значки */"
GLYPHS = {"lock": "\U000f033e", "suspend": "\U000f0904", "logout": "\U000f0343",
          "reboot": "\U000f0709", "shutdown": "\U000f0425",
          # «Заставка» (03.10.2026): телевизор — как логотип static
          "screensaver": "\U000f07f4"}
OLD_COLOR = (212, 191, 249, 255)   # цвет стандартных значков wlogout
FONT = "/usr/share/fonts/TTF/JetBrainsMonoNLNerdFontMono-Regular.ttf"


def render():
    from PIL import Image, ImageDraw, ImageFont
    os.makedirs(OUT, exist_ok=True)
    color = popup_theme.palette()["on_surface"]
    for name, ch in GLYPHS.items():
        # Рисунок — на всю картинку (большая сторона 236 из 256): у глифов Nerd
        # Font поля разные, и при общем кегле значки выходили мелкими и разными
        # (просьба: «иконки чуть больше», 30.09.2026).
        probe = ImageFont.truetype(FONT, 200)
        l, t, r, b = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), ch, font=probe)
        font = ImageFont.truetype(FONT, int(200 * 236 / max(r - l, b - t)))
        im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        l, t, r, b = d.textbbox((0, 0), ch, font=font)
        d.text(((256 - (r - l)) / 2 - l, (256 - (b - t)) / 2 - t), ch, font=font, fill=color)
        im.save(os.path.join(OUT, name + ".png"))


def render_old_saver():
    """«Заставка» в духе стандартных значков wlogout (у них такого нет): линии с
    круглыми концами, их сиреневый цвет, 512×512 — телевизор с антенной и
    четырёхлучевой искрой на экране."""
    from PIL import Image, ImageDraw
    os.makedirs(OUT, exist_ok=True)
    k = 4                                   # рисуем крупнее и уменьшаем — гладкие края
    S, c, lw = 512 * k, OLD_COLOR, 26 * k
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    def line(a, b):
        d.line([a, b], fill=c, width=lw)
        for x, y in (a, b):
            d.ellipse([x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2], fill=c)
    d.rounded_rectangle([40 * k, 150 * k, 472 * k, 440 * k], radius=36 * k, outline=c, width=lw)
    line((256 * k, 150 * k), (180 * k, 60 * k))
    line((256 * k, 150 * k), (332 * k, 60 * k))
    line((180 * k, 480 * k), (332 * k, 480 * k))
    cx, cy, r, w = 256 * k, 295 * k, 92 * k, 22 * k
    d.polygon([(cx, cy - r), (cx + w, cy - w), (cx + r, cy), (cx + w, cy + w),
               (cx, cy + r), (cx - w, cy + w), (cx - r, cy), (cx - w, cy - w)], fill=c)
    im.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "screensaver-old.png"))


def write_css(mode):
    text = open(CSS, encoding="utf-8").read()
    base = OUT if mode == "new" else "/usr/share/wlogout/icons"

    def path(n):
        if n == "screensaver" and mode != "new":
            if not os.path.exists(os.path.join(OUT, "screensaver-old.png")):
                render_old_saver()
            return os.path.join(OUT, "screensaver-old.png")
        return "%s/%s.png" % (base, n)
    block = BEGIN + "\n" + "\n".join(
        '#%s { background-image: url("%s"); }' % (n, path(n)) for n in GLYPHS) + "\n" + END
    if BEGIN in text:
        text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda m: block, text, flags=re.S)
    else:
        # первый раз: заменить прежние пять строк с картинками
        text = re.sub(r'(?m)^#(lock|suspend|shutdown|reboot|logout) \{ background-image:.*\}\n?', "", text)
        text = text.rstrip() + "\n" + block + "\n"
    with open(CSS, "w", encoding="utf-8") as f:
        f.write(text)


def status():
    try:
        return "new" if open(FLAG).read().strip() == "new" else "old"
    except OSError:
        return "old"


def main():
    arg = (sys.argv[1:] or ["status"])[0]
    if arg == "status":
        print(status())
        return
    if arg == "regen":
        if status() == "new":
            render()
        return
    if arg in ("new", "old"):
        if arg == "new":
            render()
        write_css(arg)
        os.makedirs(os.path.dirname(FLAG), exist_ok=True)
        with open(FLAG, "w") as f:
            f.write(arg + "\n")
        print(arg)
        return
    print(__doc__)


if __name__ == "__main__":
    main()
