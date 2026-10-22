#!/usr/bin/env python3
"""Значки файлов, открытых в nvim: .md и языки (java, python, php…). 21.10.2026, просьба: «новую иконку для файлов .md, которые открыты через nvim — снизу в панели и в
Alt Tab»; потом «на все популярные языки… рисунком, а если у языка нет своего рисунка —
текстом»; вид — как у значка Reminders: тёмная плитка, рисунок в цвет обоев.

Языки и расширения — nvim_lang.py (его же берут панель, Alt+Tab и полосы стопки).
Значки jarvis-nvim-<язык>; у .md ещё и скрытый .desktop (так его искала панель).

Значок называется jarvis-nvim-md и лежит в ~/.local/share/icons/hicolor (как
jarvis-yazi — один во всех темах). Нижняя панель берёт его через скрытый
jarvis-nvim-md.desktop (xpbar.py window_icon_id), Alt+Tab — по имени (alt_tab.py
term_view). Окно узнаётся по заголовку nvim: текущий файл первым, «nvim A.md · B.java».

  md_icon.py apply    нарисовать под текущий акцент (зовёт theme_changer.sh)
  md_icon.py check    значки на месте и цвета акцента (rc 1 — нет)
  md_icon.py off      убрать значки и .desktop — будет значок kitty
  md_icon.py sheet F  лист всех значков 16/32/64 px (для проверки)
"""
import os
import subprocess
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nvim_lang  # noqa: E402

HOME = os.path.expanduser("~")
VIVID = os.path.join(HOME, ".cache/matugen/vivid.txt")
HICOLOR = os.path.join(HOME, ".local/share/icons/hicolor")
DESKTOP = os.path.join(HOME, ".local/share/applications/jarvis-nvim-md.desktop")
NAME = "jarvis-nvim-md"
MARK = "X-Jarvis-Icon=md_icon.py"
SIZES = (16, 22, 24, 32, 48, 64, 96, 128, 256)
LIGHT = (242, 242, 242)        # как «>_» у пиксельного kitty
# 21.10.2026: вид как у значка Reminders (jarvis-hub-reminders.svg) — тёмная плитка,
# рисунок акцентом обоев: контур — акцент, высветленный к белому, знак внутри — сам акцент.
DARK_BG = (0x1d, 0x1f, 0x29)

# W — светлый акцент, A — акцент, . и D — тёмная плитка (D — прорезь внутри заливки:
# 21.10 пользователь — «текст внутри рисунков не особо виден»). .md — лист с «#» (12×14).
GRID = [
    "................",
    "..WWWWWWWW......",
    "..W......WW.....",
    "..W......W.W....",
    "..W......W..W...",
    "..W......WWWWW..",
    "..W..........W..",
    "..W...A..A...W..",
    "..W.AAAAAAAA.W..",
    "..W...A..A...W..",
    "..W...A..A...W..",
    "..W.AAAAAAAA.W..",
    "..W...A..A...W..",
    "..W..........W..",
    "..WWWWWWWWWWWW..",
    "................",
]
GRIDS = {
    "md": GRID,
    "java": [                    # код «</>», скобки в акценте (21.10.2026)
        "................",
        "................",
        ".........WW.....",
        ".........WW.....",
        "........WW......",
        "...AA...WW.AA...",
        "..AA....WW..AA..",
        ".AA....WW....AA.",
        ".AA....WW....AA.",
        "..AA..WW....AA..",
        "...AA.WW...AA...",
        "......WW........",
        ".....WW.........",
        ".....WW.........",
        "................",
        "................",
    ],
    "python": [
        "................",
        ".....WWWWW......",
        "....WW.WWWW.....",
        "....WWWWWWW.....",
        ".........WW.....",
        "..WWWWWWWWW.AA..",
        ".WWWWWWWWWW.AAA.",
        ".WWWW......AAAA.",
        ".WWWW......AAAA.",
        ".WWW.AAAAAAAAAA.",
        "..WW.AAAAAAAAA..",
        ".....AA.........",
        ".....AAAAAAA....",
        ".....AAAA.AA....",
        "......AAAAA.....",
        "................",
    ],
    "php": [
        "................",
        "................",
        "....WWWWWWWW....",
        "...WWWWWWWWWW...",
        "..WWWDDWWWWWWW..",
        "..WDWD.DWWWWWWW.",
        ".WWWWD.DWWWWWWW.",
        ".WW.WDDWWWWWWWW.",
        ".WW.WWWWWWWWWWW.",
        ".WW..WWWWWWWWWW.",
        ".WW..WW..WW..WW.",
        "..W..WW..WW..WW.",
        ".....WW..WW..WW.",
        "................",
        "................",
        "................",
    ],
    "rust": [
        "................",
        "................",
        ".WW..........WW.",
        "WWW..W....W..WWW",
        ".WW..W....W..WW.",
        "..W..........W..",
        "..WWWWWWWWWWWW..",
        ".WWWWWWWWWWWWWW.",
        ".WWWWDWWWWDWWWW.",
        "..WWWWDDDDWWWW..",
        ".W.W.W....W.W.W.",
        "W..W..W..W..W..W",
        "................",
        "................",
        "................",
        "................",
    ],
    "go": [
        "................",
        "..W..........W..",
        ".WWWWWWWWWWWWWW.",
        ".WDDDDWWWWDDDDW.",
        ".WDWWDWWWWDWWDW.",
        ".WDWDDWWWWDWDDW.",
        ".WDDDDWWWWDDDDW.",
        ".WWWWWWDDWWWWWW.",
        ".WWWWWDWWDWWWWW.",
        ".WWWWWWWWWWWWWW.",
        ".WWWWWWWWWWWWWW.",
        ".WWWWWWWWWWWWWW.",
        "..WWWWWWWWWWWW..",
        "..W..........W..",
        "................",
        "................",
    ],
    "ruby": [
        "................",
        "................",
        "....WWWWWWWW....",
        "...WDWWWWWWDW...",
        "..WWWDWWWWDWWW..",
        ".DDDDDDDDDDDDDD.",
        "..WWWWDWWDWWWW..",
        "...WWWWDDWWWW...",
        "....WWWWWWWW....",
        ".....WWDDWW.....",
        "......WWWW......",
        ".......WW.......",
        "................",
        "................",
        "................",
        "................",
    ],
    "lua": [
        "................",
        "............WWW.",
        "............WWW.",
        ".....WWWW...WWW.",
        "...WWWWWWWW.....",
        "..WWWWWW...W....",
        "..WWWWWW...W....",
        ".WWWWWWW...WW...",
        ".WWWWWWWWWWWW...",
        ".WWWWWWWWWWWW...",
        ".WWWWWWWWWWWW...",
        "..WWWWWWWWWW....",
        "..WWWWWWWWWW....",
        "...WWWWWWWW.....",
        ".....WWWW.......",
        "................",
    ],
    "shell": [
        "................",
        "................",
        "................",
        "......WWWW....W.",
        "....WWWWWWW..WW.",
        "..WWWDWWWWWWWWW.",
        ".WWWWWWWWWWWWW..",
        "..WWWWWWWWWWWWW.",
        "....WWWWWWW..WW.",
        "......WWWW....W.",
        "................",
        "................",
        "................",
        "................",
        "................",
        "................",
    ],
    "kotlin": [
        "................",
        ".WWWWWWWWWWWWWW.",
        ".WWWWWWWWWWWWW..",
        ".WWWWWWWWWWWW...",
        ".WWWWWWWWWWW....",
        ".WWWWWWWWWW.....",
        ".WWWWWWWWW......",
        ".WWWWWWWW.......",
        ".WWWWWWWW.......",
        ".WWWWWWWWW......",
        ".WWWWWWWWWW.....",
        ".WWWWWWWWWWW....",
        ".WWWWWWWWWWWW...",
        ".WWWWWWWWWWWWW..",
        ".WWWWWWWWWWWWWW.",
        "................",
    ],
    "c": [
        "................",
        "....WWWWWWWW....",
        "...WWWWWWWWWW...",
        "..WWWWWWWWWWWW..",
        ".WWWWWDDDDWWWWW.",
        ".WWWWDDWWDDWWWW.",
        ".WWWWDDWWWWWWWW.",
        ".WWWWDDWWWWWWWW.",
        ".WWWWDDWWWWWWWW.",
        ".WWWWDDWWDDWWWW.",
        ".WWWWWDDDDWWWWW.",
        ".WWWWWWWWWWWWWW.",
        "..WWWWWWWWWWWW..",
        "...WWWWWWWWWW...",
        "....WWWWWWWW....",
        "................",
    ],
    "cpp": [
        "................",
        "....WWWWWWWW....",
        "...WWWWWWWWWW...",
        "..WWWWWWWWWWWW..",
        ".WWDDDDWWWDWWWW.",
        ".WDDWWDDWDDDWWW.",
        ".WDDWWWWWWDWWWW.",
        ".WDDWWWWWWWWWWW.",
        ".WDDWWWWWWDWWWW.",
        ".WDDWWDDWDDDWWW.",
        ".WWDDDDWWWDWWWW.",
        ".WWWWWWWWWWWWWW.",
        "..WWWWWWWWWWWW..",
        "...WWWWWWWWWW...",
        "....WWWWWWWW....",
        "................",
    ],
    "csharp": [
        "................",
        "....WWWWWWWW....",
        "...WWWWWWWWWW...",
        "..WWWWWWWWWWWW..",
        ".WWDDDDWWDWWDWW.",
        ".WDDWWDDWDWWDWW.",
        ".WDDWWWWDDDDDDW.",
        ".WDDWWWWWDWWDWW.",
        ".WDDWWWWWDWWDWW.",
        ".WDDWWDDDDDDDDW.",
        ".WWDDDDWWDWWDWW.",
        ".WWWWWWWWWWWWWW.",
        "..WWWWWWWWWWWW..",
        "...WWWWWWWWWW...",
        "....WWWWWWWW....",
        "................",
    ],
    "html": [
        "................",
        "................",
        "................",
        "..........W.....",
        "...W......W..W..",
        "..WW.....W...WW.",
        ".WW......W....WW",
        "WW......W......W",
        ".WW.....W.....WW",
        "..WW...W.....WW.",
        "...W...W.....W..",
        "................",
        "................",
        "................",
        "................",
        "................",
    ],
    "css": [
        "................",
        "............WW..",
        "...........WWWW.",
        "..........WWWW..",
        ".........WWWW...",
        "........WWWW....",
        ".......DWWW.....",
        "......DDDW......",
        ".....WDDD.......",
        "....WWWD........",
        "...WWWW.........",
        "..WWWW..........",
        ".WWW............",
        "................",
        "................",
        "................",
    ],
    "sql": [
        "................",
        "....WWWWWWWW....",
        "..WWWWWWWWWWWW..",
        "..WWWWWWWWWWWW..",
        "..DWWWWWWWWWWD..",
        "..WDDDDDDDDDDW..",
        "..WWWWWWWWWWWW..",
        "..DWWWWWWWWWWD..",
        "..WDDDDDDDDDDW..",
        "..WWWWWWWWWWWW..",
        "..DWWWWWWWWWWD..",
        "..WDDDDDDDDDDW..",
        "..WWWWWWWWWWWW..",
        "....WWWWWWWW....",
        "................",
        "................",
    ],
    "json": [
        "................",
        "................",
        "....WW....WW....",
        "...WW......WW...",
        "...WW......WW...",
        "...WW......WW...",
        "..WW...WW...WW..",
        ".WW....WW....WW.",
        "..WW........WW..",
        "...WW......WW...",
        "...WW......WW...",
        "...WW......WW...",
        "....WW....WW....",
        "................",
        "................",
        "................",
    ],
    "config": [
        ".......WW.......",
        ".......WW.......",
        "..WW.WWWWWW.WW..",
        "..WWWWWWWWWWWW..",
        "...WWWWWWWWWW...",
        "..WWWWWWWWWWWW..",
        "..WWWW....WWWW..",
        "WWWWWW....WWWWWW",
        "WWWWWW....WWWWWW",
        "..WWWW....WWWW..",
        "..WWWWWWWWWWWW..",
        "...WWWWWWWWWW...",
        "..WWWWWWWWWWWW..",
        "..WW.WWWWWW.WW..",
        ".......WW.......",
        ".......WW.......",
    ],
    "js": [
        "................",
        "................",
        "................",
        ".....WW....WWWW.",
        ".....WW....WWWW.",
        ".....WW..WW.....",
        ".....WW..WW.....",
        ".....WW....WW...",
        ".....WW....WW...",
        ".WW..WW......WW.",
        ".WW..WW......WW.",
        "...WW....WWWW...",
        "...WW....WWWW...",
        "................",
        "................",
        "................",
    ],
    "ts": [
        "................",
        "................",
        "................",
        ".WWWWWW....WWWW.",
        ".WWWWWW....WWWW.",
        "...WW....WW.....",
        "...WW....WW.....",
        "...WW......WW...",
        "...WW......WW...",
        "...WW........WW.",
        "...WW........WW.",
        "...WW....WWWW...",
        "...WW....WWWW...",
        "................",
        "................",
        "................",
    ],
}



def accent():
    try:
        s = open(VIVID).read().strip().lstrip("#")
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except (OSError, ValueError):
        return (0x68, 0x88, 0xf3)


def base(acc=None, grid=GRID):
    acc = acc or accent()
    pale = tuple(int(a + (b - a) * 0.45) for a, b in zip(acc, LIGHT))
    im = Image.new("RGBA", (16, 16), DARK_BG + (255,))
    for y, row in enumerate(grid):
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


def path(s, lang="md"):
    return os.path.join(HICOLOR, "%dx%d" % (s, s), "apps", nvim_lang.PREFIX + lang + ".png")


def write_desktop():
    if os.path.exists(DESKTOP) and MARK not in open(DESKTOP).read():
        return
    tmp = DESKTOP + ".tmp"
    os.makedirs(os.path.dirname(DESKTOP), exist_ok=True)
    with open(tmp, "w") as f:
        f.write("[Desktop Entry]\n%s\nType=Application\nName=Markdown (nvim)\n"
                "Exec=kitty nvim %%F\nIcon=%s\nNoDisplay=true\n"
                % (MARK, NAME))
    os.replace(tmp, DESKTOP)


def refresh_cache():
    # у ~/.local/share/icons/hicolor есть icon-theme.cache — без обновления GTK
    # может не увидеть новый файл
    subprocess.run(["gtk-update-icon-cache", "-f", "-q", "-t", HICOLOR],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply():
    acc = accent()
    for lang, grid in GRIDS.items():
        im = base(acc, grid)
        for s in SIZES:
            p = path(s, lang)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            sized(im, s).save(p + ".tmp.png")
            os.replace(p + ".tmp.png", p)
    write_desktop()
    refresh_cache()


def check():
    ok = True
    for lang in GRIDS:
        for s in SIZES:
            if not os.path.exists(path(s, lang)):
                print("нет %s" % path(s, lang))
                ok = False
    miss = sorted(set(nvim_lang.LANGS) - set(GRIDS))
    if miss:
        print("в nvim_lang.py есть языки без рисунка:", " ".join(miss))
        ok = False
    if ok:
        px = Image.open(path(16)).convert("RGBA").getpixel((6, 7))[:3]   # «#» — акцент
        if px != accent():
            print("цвет %s, акцент %s" % (px, accent()))
            ok = False
    if not (os.path.exists(DESKTOP) and "Icon=" + NAME in open(DESKTOP).read()):
        print("jarvis-nvim-md.desktop без Icon=%s" % NAME)
        ok = False
    print("значки nvim (%d): %s" % (len(GRIDS), "в порядке" if ok else "НЕ в порядке"))
    return ok


def off():
    for lang in GRIDS:
        for s in SIZES:
            try:
                os.remove(path(s, lang))
            except OSError:
                pass
    if os.path.exists(DESKTOP) and MARK in open(DESKTOP).read():
        os.remove(DESKTOP)
    refresh_cache()


def sheet(out):
    acc = accent()
    items = list(GRIDS.items())
    im = Image.new("RGBA", (len(items) * 74 + 10, 130), (24, 26, 36, 255))
    for i, (_lang, grid) in enumerate(items):
        ic = base(acc, grid)
        x = 10 + i * 74
        im.paste(ic.resize((64, 64), Image.NEAREST), (x, 10))
        im.paste(ic.resize((32, 32), Image.NEAREST), (x, 84))
        im.paste(ic, (x + 40, 92))
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
