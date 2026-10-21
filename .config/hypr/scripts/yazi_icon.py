#!/usr/bin/env python3
"""Свой значок yazi — пиксельная папка с молнией в цвет акцента обоев, в манере
пиксельного kitty (квадрат акцента, светлый рисунок штрихом в 2 px). 21.10.2026, просьба: «иконку yazi нарисовать, чтобы было понятно, что это yazi, даже если открыт
в терминале; дефолтная утка не нравится».

Значок называется jarvis-yazi и лежит в ~/.local/share/icons/hicolor — его не
перекрывает ни Papirus-Wall, ни Jarvis-Pixel (там своего jarvis-yazi нет), поэтому
он один во всех темах. yazi.desktop в ~/.local/share/applications — копия системного
с Icon=jarvis-yazi (лаунчеры и панель берут значок оттуда). Окно kitty с yazi нижняя
панель узнаёт по заголовку (xpbar.py window_icon_id).

  yazi_icon.py apply    нарисовать под текущий акцент (зовёт theme_changer.sh)
  yazi_icon.py check    значок на месте и цвета акцента (rc 1 — нет)
  yazi_icon.py off      убрать значок и свой yazi.desktop — вернётся утка
  yazi_icon.py sheet F  лист: значок 16/24/96 px рядом с kitty (для проверки)
"""
import os
import subprocess
import sys

from PIL import Image

HOME = os.path.expanduser("~")
VIVID = os.path.join(HOME, ".cache/matugen/vivid.txt")
HICOLOR = os.path.join(HOME, ".local/share/icons/hicolor")
DESKTOP = os.path.join(HOME, ".local/share/applications/yazi.desktop")
SYS_DESKTOP = "/usr/share/applications/yazi.desktop"
NAME = "jarvis-yazi"
MARK = "X-Jarvis-Icon=yazi_icon.py"
SIZES = (16, 22, 24, 32, 48, 64, 96, 128, 256)
LIGHT = (242, 242, 242)        # как «>_» у пиксельного kitty

# W — светлый рисунок, . — акцент. Папка с язычком, внутри молния (yazi быстрый).
GRID = [
    "................",
    "................",
    "................",
    "..WWWWW.........",
    "..WW.WWW........",
    "..WW..WWWWWWWW..",
    "..WW........WW..",
    "..WW.....WW.WW..",
    "..WW....WW..WW..",
    "..WW...WWWW.WW..",
    "..WW....WW..WW..",
    "..WW...WW...WW..",
    "..WWWWWWWWWWWW..",
    "................",
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
    im = Image.new("RGBA", (16, 16), acc + (255,))
    for y, row in enumerate(GRID):
        for x, ch in enumerate(row):
            if ch == "W":
                im.putpixel((x, y), LIGHT + (255,))
    return im


def sized(im, s):
    """Целый множитель NEAREST; 22 и 24 — та же сетка 16 с полем (как в Jarvis-Pixel)."""
    if s % 16 == 0:
        return im.resize((s, s), Image.NEAREST)
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(im, ((s - 16) // 2, (s - 16) // 2))
    return out


def path(s):
    return os.path.join(HICOLOR, "%dx%d" % (s, s), "apps", NAME + ".png")


def write_desktop():
    if os.path.exists(DESKTOP) and MARK not in open(DESKTOP).read():
        return                                   # чужой yazi.desktop не трогаем
    try:
        src = open(SYS_DESKTOP).read().splitlines()
    except OSError:
        src = ["[Desktop Entry]", "Name=Yazi File Manager", "Type=Application",
               "Terminal=true", "Exec=yazi %u"]
    out = []
    for ln in src:
        if ln.startswith("Icon="):
            ln = "Icon=" + NAME
        out.append(ln)
        if ln.strip() == "[Desktop Entry]":
            out.append(MARK)
    if not any(ln.startswith("Icon=") for ln in out):
        out.append("Icon=" + NAME)
    tmp = DESKTOP + ".tmp"
    os.makedirs(os.path.dirname(DESKTOP), exist_ok=True)
    with open(tmp, "w") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, DESKTOP)


def refresh_cache():
    # у ~/.local/share/icons/hicolor есть icon-theme.cache — без обновления GTK
    # может не увидеть новый файл
    subprocess.run(["gtk-update-icon-cache", "-f", "-q", "-t", HICOLOR],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply():
    im = base()
    for s in SIZES:
        p = path(s)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        sized(im, s).save(p + ".tmp.png")
        os.replace(p + ".tmp.png", p)
    write_desktop()
    refresh_cache()


def check():
    ok = True
    for s in SIZES:
        if not os.path.exists(path(s)):
            print("нет %s" % path(s))
            ok = False
    if ok:
        px = Image.open(path(16)).convert("RGBA").getpixel((0, 0))[:3]
        if px != accent():
            print("цвет %s, акцент %s" % (px, accent()))
            ok = False
    if not (os.path.exists(DESKTOP) and "Icon=" + NAME in open(DESKTOP).read()):
        print("yazi.desktop без Icon=%s" % NAME)
        ok = False
    print("значок yazi: %s" % ("в порядке" if ok else "НЕ в порядке"))
    return ok


def off():
    for s in SIZES:
        try:
            os.remove(path(s))
        except OSError:
            pass
    if os.path.exists(DESKTOP) and MARK in open(DESKTOP).read():
        os.remove(DESKTOP)
    refresh_cache()


def sheet(out):
    kitty = os.path.join(HOME, ".local/share/icons/Jarvis-Pixel/16x16/apps/kitty.png")
    items = [base()]
    try:
        items.insert(0, Image.open(kitty).convert("RGBA"))
    except OSError:
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
