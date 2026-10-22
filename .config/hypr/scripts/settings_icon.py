#!/usr/bin/env python3
"""Свой значок Настроек — шестерёнка в цвет акцента обоев, без плитки. 22.10.2026, просьба: «сделай собственную иконку для Настроек»; из вариантов — «больше нравится
шестерёнка, но стиль как сделано в Reminders»; пиксельная сетка 16×16 — «через чур
пикселизировано», лучше гладкая (как значок-шрифт), но «чуть-чуть пикселизируй» — край
без сглаживания; плитка — «почему 2 фона?». Поэтому
шестерёнка рисуется шрифтом Nerd Font под каждый размер отдельно;
без шрифта — прежняя сетка GRID.

Значок называется jarvis-settings и лежит в ~/.local/share/icons/hicolor (как
jarvis-yazi): ни Papirus-Wall, ни Jarvis-Pixel его не перекрывают, он один во всех
темах. jarvis-settings.desktop (StartupWMClass=com.jarvis.settings) получает
Icon=jarvis-settings — по нему значок берут нижняя панель, док, Alt+Tab и лаунчеры.

  settings_icon.py apply    нарисовать под текущий акцент (зовёт theme_changer.sh)
  settings_icon.py check    значок на месте и цвета акцента (rc 1 — нет)
  settings_icon.py off      убрать значок, в .desktop вернуть preferences-system
  settings_icon.py sheet F  лист: значок 16/24/96 px рядом с Reminders (для проверки)
"""
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps

HOME = os.path.expanduser("~")
VIVID = os.path.join(HOME, ".cache/matugen/vivid.txt")
HICOLOR = os.path.join(HOME, ".local/share/icons/hicolor")
DESKTOP = os.path.join(HOME, ".local/share/applications/jarvis-settings.desktop")
NAME = "jarvis-settings"
OLD_ICON = "preferences-system"
SIZES = (16, 22, 24, 32, 48, 64, 96, 128, 256)
LIGHT = (242, 242, 242)
DARK_BG = (0x1d, 0x1f, 0x29)   # плитка jarvis-hub-reminders.svg
FONT = "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf"
GEAR = "\uf013"                # nf-fa-gear
GEAR_SCALE = 0.8               # кегль от стороны плитки

# Запасной вид без шрифта. W — светлый акцент (контур), A — акцент (заливка), . — тёмная плитка.
# Восемь зубцов: четыре прямых и четыре косых, дырка 2×2; сетка симметрична по диагонали.
GRID = [
    "................",
    "................",
    "......WWWW......",
    "...WW.WAAW.WW...",
    "...WAWWAAWWAW...",
    "....WAAAAAAW....",
    "..WWWAAWWAAWWW..",
    "..WAAAW..WAAAW..",
    "..WAAAW..WAAAW..",
    "..WWWAAWWAAWWW..",
    "....WAAAAAAW....",
    "...WAWWAAWWAW...",
    "...WW.WAAW.WW...",
    "......WWWW......",
    "................",
    "................",
]


def accent():
    try:
        s = open(VIVID).read().strip().lstrip("#")
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except (OSError, ValueError):
        return (0x68, 0x88, 0xf3)


def base(acc=None):
    acc = acc or accent()
    pale = tuple(int(a + (b - a) * 0.45) for a, b in zip(acc, LIGHT))
    im = Image.new("RGBA", (16, 16), DARK_BG + (255,))
    for y, row in enumerate(GRID):
        for x, ch in enumerate(row):
            if ch in "WA":
                im.putpixel((x, y), (pale if ch == "W" else acc) + (255,))
    return im


def sized(im, s):
    """Целый множитель NEAREST; 22 и 24 — та же сетка 16 с полем (как в Jarvis-Pixel)."""
    if s % 16 == 0:
        return im.resize((s, s), Image.NEAREST)
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(im, ((s - 16) // 2, (s - 16) // 2))
    return out


def smooth(s, acc=None):
    """Шестерёнка шрифтом ровно в s px, край без полупрозрачной каймы.

    «чуть-чуть пикселизируй для приличия, но не сильно», затем «края не ровные»
    (22.10.2026): порог по растру шрифта давал несимметричную лесенку. Теперь глиф
    рисуется в 8 раз крупнее, сжимается по покрытию (BOX) и усредняется со своими
    зеркалами — шестерёнка симметрична по обеим осям — и только потом порог 50 %."""
    acc = acc or accent()
    n = s * 8
    big = Image.new("L", (n, n), 0)
    ft = ImageFont.truetype(FONT, max(8, round(n * GEAR_SCALE)))
    d = ImageDraw.Draw(big)
    x0, y0, x1, y1 = d.textbbox((0, 0), GEAR, font=ft)
    d.text(((n - (x1 - x0)) / 2 - x0, (n - (y1 - y0)) / 2 - y0), GEAR, font=ft, fill=255)
    a = big.resize((s, s), Image.BOX)
    a = Image.blend(a, ImageOps.mirror(a), 0.5)
    a = Image.blend(a, ImageOps.flip(a), 0.5)
    im = Image.new("RGBA", (s, s), acc + (255,))
    im.putalpha(a.point(lambda v: 255 if v >= 128 else 0))
    return im


def render(s, acc=None):
    try:
        return smooth(s, acc)
    except OSError:                      # нет шрифта — пиксельная сетка
        return sized(base(acc), s)


def path(s):
    return os.path.join(HICOLOR, "%dx%d" % (s, s), "apps", NAME + ".png")


def set_desktop_icon(icon):
    try:
        lines = open(DESKTOP).read().splitlines()
    except OSError:
        return
    out = ["Icon=" + icon if ln.startswith("Icon=") else ln for ln in lines]
    if out == lines:
        return
    tmp = DESKTOP + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, DESKTOP)


def refresh_cache():
    # у ~/.local/share/icons/hicolor есть icon-theme.cache — без обновления GTK
    # может не увидеть новый файл
    subprocess.run(["gtk-update-icon-cache", "-f", "-q", "-t", HICOLOR],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply():
    acc = accent()
    for s in SIZES:
        p = path(s)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        render(s, acc).save(p + ".tmp.png")
        os.replace(p + ".tmp.png", p)
    set_desktop_icon(NAME)
    refresh_cache()


def check():
    ok = True
    for s in SIZES:
        if not os.path.exists(path(s)):
            print("нет %s" % path(s))
            ok = False
    if ok:
        im = Image.open(path(64)).convert("RGBA")
        px = max(im.getcolors(64 * 64), key=lambda c: c[0] if c[1][3] == 255 else -1)[1][:3]
        if px != accent():                          # самый частый цвет кроме плитки — заливка
            print("цвет %s, акцент %s" % (px, accent()))
            ok = False
    if not (os.path.exists(DESKTOP) and "Icon=" + NAME in open(DESKTOP).read()):
        print("jarvis-settings.desktop без Icon=%s" % NAME)
        ok = False
    print("значок Настроек: %s" % ("в порядке" if ok else "НЕ в порядке"))
    return ok


def off():
    for s in SIZES:
        try:
            os.remove(path(s))
        except OSError:
            pass
    set_desktop_icon(OLD_ICON)
    refresh_cache()


def sheet(out):
    rem = os.path.join(HOME, ".local/share/icons/hicolor/scalable/apps/jarvis-hub-reminders.svg")
    items = [render(16)]
    try:
        r = subprocess.run(["rsvg-convert", "-w", "16", "-h", "16", rem],
                           capture_output=True, check=True).stdout
        import io
        items.insert(0, Image.open(io.BytesIO(r)).convert("RGBA"))
    except (OSError, subprocess.CalledProcessError):
        pass
    im = Image.new("RGBA", (len(items) * 116 + 10, 160), (24, 26, 36, 255))
    for i, ic in enumerate(items):
        x = 10 + i * 116
        im.paste(ic.resize((96, 96), Image.NEAREST), (x, 10))
        im.paste(ic, (x + 10, 124))
        im.paste(ic.resize((24, 24), Image.NEAREST), (x + 40, 120))
    im.save(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    if cmd == "apply":
        apply()
    elif cmd == "check":
        sys.exit(0 if check() else 1)
    elif cmd == "off":
        off()
    elif cmd == "sheet" and len(sys.argv) > 2:
        sheet(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)
