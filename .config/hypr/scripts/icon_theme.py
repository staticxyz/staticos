#!/usr/bin/env python3
"""Пиксельные значки папок и файлов в цветах обоев — тема Jarvis-Pixel.

    icon_theme.py build [--force]     перерисовать тему под текущую палитру
    icon_theme.py get                 pixel | pixel-all | papirus
    icon_theme.py set pixel|pixel-all|papirus   выбрать тему значков
    icon_theme.py preview [файл.png] [--only=a,b]  лист значков (48 и 16 px)
    icon_theme.py names               что на что отображено (для проверки)
    icon_theme.py apps                какие значки программ берутся и откуда

Тема ~/.local/share/icons/Jarvis-Pixel переопределяет ТОЛЬКО папки, корзину,
диски и типы файлов; всё остальное (значки программ, действия, статусы)
наследуется: Papirus-Wall → Papirus-Dark → Papirus → breeze-dark → hicolor.
Поэтому бар, док, «Пуск» и уведомления остаются с прежними значками.

Рисунки — свои, пиксель-арт в сетке 16×16 (строки символов ниже, символ =
цвет палитры). В размеры 16…256 сетка увеличивается целым множителем без
сглаживания; 22 и 24 — та же сетка 16×16 с полем, чтобы не было каши.
Цвета берутся из ~/.cache/matugen/colors.json: папки — оттенки primary
(блик, тон, тень, глубокая тень), акценты файлов — tertiary/primary/error,
листы светлые, контур тёмный.

Имена значков — по freedesktop icon naming spec плюс синонимы, которые есть
в Papirus (их просит Dolphin): список имён читается из /usr/share/icons/Papirus
и раскладывается по рисункам правилами PLACE_RULES / MIME_RULES / DEVICE_RULES.

Состояние — ~/.config/hypr/state/icon-theme (pixel | papirus). При смене обоев
theme_changer.sh зовёт build, если выбрано pixel: шаблон matugen каждый раз
возвращает в kdeglobals Papirus-Wall, build ставит тему обратно.
Чужих картинок здесь нет (02.10.2026).

Режим pixel-all («Пиксельные везде», 05.10.2026). Просьба: «заменить все иконки
в системе на пиксельные, под общий стиль». Кроме своих рисунков в тему ложатся
пиксельные копии значков программ (Icon= из всех .desktop, app_id окон niri),
частых действий меню и значков трея. Копии делаются из наследуемой темы сами:
исходник 16 px (у Papirus он нарисован под 16) или крупный, обрезанный по
краям, → 16×16 → жёсткая альфа → до APP_COLORS цветов → ближайший сосед в
нужные размеры. Родные цвета программ сохраняются. Копии лежат в кэше
~/.cache/jarvis-pixel-apps (все размеры), в тему попадают жёсткими ссылками:
при смене обоев перерисовываются только папки, программы — только новые или
те, у которых сменился исходник. set заодно перезапускает нижнюю панель
(xpbar) и меню рабочего стола, если они работают.
"""
import colorsys
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys

HOME = os.path.expanduser("~")
NAME = "Jarvis-Pixel"
DST = os.path.join(HOME, ".local/share/icons", NAME)
STATE = os.path.join(HOME, ".config/hypr/state/icon-theme")
PALETTE = os.path.join(HOME, ".cache/matugen/colors.json")
PAPIRUS = "/usr/share/icons/Papirus"
INHERITS = "Papirus-Wall,Papirus-Dark,Papirus,breeze-dark,hicolor"
# 16 — сетка как есть; 22 и 24 — она же с полем; остальные кратны 16
# (80 и 112 — ступени масштаба Dolphin, иначе Qt сглаживал бы соседний размер).
SIZES = (16, 22, 24, 32, 48, 64, 80, 96, 112, 128, 256)
G = 16
MODES = ("pixel", "pixel-all", "papirus")
LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-icon-theme.lock")

# ------------------------------------------------------------------ палитра --

FALLBACK = {"primary": "#7aa2f7", "tertiary": "#bb9af7", "secondary": "#7dcfff",
            "error": "#f7768e"}


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def tone(hexc, light, cap=1.0):
    """Тот же оттенок с заданной светлотой; насыщенность не выше cap."""
    r, g, b = (c / 255 for c in _rgb(hexc))
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, light, min(s, cap))
    return (round(r * 255), round(g * 255), round(b * 255), 255)


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)


def palette_src():
    p = dict(FALLBACK)
    try:
        with open(PALETTE, encoding="utf-8") as f:
            raw = json.load(f)
        for k in p:
            v = raw.get(k)
            if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v):
                p[k] = v
    except Exception:
        pass
    return p


def colours(p=None):
    """Символ рисунка -> RGBA."""
    p = p or palette_src()
    pr, te, se, er = p["primary"], p["tertiary"], p["secondary"], p["error"]
    out = tone(pr, 0.21, 0.40)
    paper = mix((255, 255, 255, 255), tone(pr, 0.80, 0.9), 0.07)
    return {
        ".": (0, 0, 0, 0),
        "O": out,                                   # контур
        "H": tone(pr, 0.87, 0.90),                  # папка: блик
        "F": tone(pr, 0.73, 0.80),                  # папка: тон
        "S": tone(pr, 0.59, 0.70),                  # папка: тень
        "D": tone(pr, 0.42, 0.60),                  # папка: глубокая тень, эмблемы
        "W": paper,                                 # лист
        "w": mix(paper, out, 0.22),                 # лист: тень
        "L": mix(out, paper, 0.32),                 # строки текста
        "h": tone(te, 0.88, 0.90),                  # акцент tertiary: блик
        "A": tone(te, 0.73, 0.78),                  # акцент tertiary
        "a": tone(te, 0.56, 0.66),                  # акцент tertiary: тень
        "c": tone(pr, 0.86, 0.85),                  # акцент primary: блик
        "B": tone(pr, 0.66, 0.80),                  # акцент primary
        "b": tone(pr, 0.50, 0.68),                  # акцент primary: тень
        "q": tone(se, 0.86, 0.45),                  # картон (secondary): блик
        "P": tone(se, 0.70, 0.45),                  # картон
        "p": tone(se, 0.54, 0.40),                  # картон: тень
        "E": tone(er, 0.63, 0.75),                  # красный (pdf, кнопка окна)
        "e": tone(er, 0.48, 0.65),
        "K": tone(pr, 0.13, 0.30),                  # тёмный экран (темнее контура)
        "k": tone(pr, 0.10, 0.30),
    }


# ------------------------------------------------------------------ рисунки --

FOLDER = """
.OOOOOO.........
OHHHHHHO........
ODDDDDDDOOOOOOO.
ODWWWWWWWWWWWWDO
OOOOOOOOOOOOOOOO
OHHHHHHHHHHHHHHO
OFFFFFFFFFFFFFFO
OFFFFFFFFFFFFFFO
OFFFFFFFFFFFFFFO
OFFFFFFFFFFFFFFO
OFFFFFFFFFFFFFFO
OFFFFFFFFFFFFFFO
OFFFFFFFFFFFFFFO
OSSSSSSSSSSSSSSO
.OOOOOOOOOOOOOO.
................
"""

FOLDER_OPEN = """
.OOOOOO.........
OHHHHHHO........
ODDDDDDDOOOOOO..
ODWWWWWWWWWWWDO.
ODWWWWWWWWWWWDO.
ODWWWWWWWWWWWDO.
ODOOOOOOOOOOOOOO
ODOHHHHHHHHHHHHO
ODOFFFFFFFFFFFFO
OOFFFFFFFFFFFFO.
OOFFFFFFFFFFFFO.
OOFFFFFFFFFFFFO.
OFFFFFFFFFFFFO..
OSSSSSSSSSSSSO..
.OOOOOOOOOOOO...
................
"""

# Эмблемы папок: 5 строк, рисуются на передней стенке (строки 7–11) по центру.
EMBLEMS = {
    "folder-documents": """
DDDDDD
......
DDDDDD
......
DDDD..
""",
    "folder-download": """
..DD..
..DD..
DDDDDD
.DDDD.
..DD..
""",
    "folder-pictures": """
.....DD
..D..DD
.DDD...
DDDDD.D
DDDDDDD
""",
    "folder-music": """
..DDDD
..D..D
..D..D
.DD.DD
.DD.DD
""",
    "folder-videos": """
DD....
DDDD..
DDDDDD
DDDD..
DD....
""",
    "user-desktop": """
DDDDDDD
D.....D
DDDDDDD
..DDD..
.DDDDD.
""",
    "user-home": """
...D...
..DDD..
.DDDDD.
.DD.DD.
.DD.DD.
""",
    "folder-templates": """
DDDD..
D..DD.
D...D.
D...D.
DDDDD.
""",
    "folder-publicshare": """
..DD..
..DD..
......
.DDDD.
DDDDDD
""",
    "folder-network": """
.DDD.
D.D.D
DDDDD
D.D.D
.DDD.
""",
    "folder-remote": """
.D....
DDDDDD
......
DDDDDD
....D.
""",
    "folder-favorites": """
.D.D.
DDDDD
DDDDD
.DDD.
..D..
""",
    "folder-recent": """
.DDD.
D.D.D
D.DDD
D...D
.DDD.
""",
    "folder-locked": """
.DDD.
.D.D.
DDDDD
DD.DD
DDDDD
""",
    "folder-cloud": """
..DD...
.DDDDD.
DDDDDDD
DDDDDDD
.......
""",
    "folder-code": """
..D.D..
.D...D.
D.....D
.D...D.
..D.D..
""",
    "folder-games": """
.DDDDD.
DD.D.DD
D...DDD
DD.DDDD
D.....D
""",
}

TRASH = """
................
......OOOO......
..OOOOOOOOOOOO..
..OHHHHHHHHHHO..
..OOOOOOOOOOOO..
...OFFFFFFFFO...
...OFFDFFDFFO...
...OFFDFFDFFO...
...OFFDFFDFFO...
...OFFDFFDFFO...
...OFFDFFDFFO...
...OFFDFFDFFO...
...OFFFFFFFFO...
...OSSSSSSSSO...
....OOOOOOOO....
................
"""

TRASH_FULL = """
....OO...OOO....
...OWWO.OWWWO...
..OOOOOOOOOOOO..
..OHHHHHHHHHHO..
..OOOOOOOOOOOO..
...OFFFFFFFFO...
...OFFDFFDFFO...
...OFFDFFDFFO...
...OFFDFFDFFO...
...OFFDFFDFFO...
...OFFDFFDFFO...
...OFFDFFDFFO...
...OFFFFFFFFO...
...OSSSSSSSSO...
....OOOOOOOO....
................
"""

HDD = """
................
................
................
.OOOOOOOOOOOOOO.
OWWWWWWWWWWWWWWO
OWWWWWWWWWWWWWWO
OwwwwwwwwwwwwwwO
OOOOOOOOOOOOOOOO
OFFFFFFFFFFFFFFO
OFKKKKKKKKFFAAFO
OFFFFFFFFFFFFFFO
OSSSSSSSSSSSSSSO
.OOOOOOOOOOOOOO.
................
................
................
"""

USB = """
................
.....OOOOOO.....
.....OWWWWO.....
.....OKWWKO.....
.....OWWWWO.....
...OOOOOOOOOO...
...OHHHHHHHHO...
...OFFFFFFFFO...
...OFFFFFFFFO...
...OFFDDDDFFO...
...OFFDDDDFFO...
...OFFFFFFFFO...
...OFFFFFFFFO...
...OSSSSSSSSO...
....OOOOOOOO....
................
"""

SHEET = """
..OOOOOOOOO.....
..OWWWWWWWOO....
..OWWWWWWWOwO...
..OWWWWWWWOOOO..
..OWWWWWWWWWWO..
..OWWWWWWWWWWO..
..OWWWWWWWWWWO..
..OWWWWWWWWWWO..
..OWWWWWWWWWWO..
..OWWWWWWWWWWO..
..OWWWWWWWWWWO..
..OWWWWWWWWWWO..
..OWWWWWWWWWWO..
..OWWWWWWWWWWO..
..OwwwwwwwwwwO..
..OOOOOOOOOOOO..
"""

# Содержимое листов: (x, y, рисунок); «.» в рисунке — оставить лист как есть.
ON_SHEET = {
    "text-x-generic": (4, 5, """
LLLLLLLL
........
LLLLLLLL
........
LLLLLLLL
........
LLLLL...
"""),
    "unknown": (5, 5, """
.LLLL.
LL..LL
....LL
..LLL.
..LL..
......
..LL..
"""),
    "application-octet-stream": (4, 5, """
LL.L.LL.
........
L.LL.L.L
........
LL.LL.L.
........
L.L.LL.L
"""),
    "application-x-zerosize": (4, 5, "........"),
    "text-x-python": (4, 5, """
.BBBB..
.BcBB..
BBBBBAA
BBBAAAA
BBAAAAA
..AAhA.
..AAAA.
"""),
    "text-x-csrc": (4, 6, """
..B..B..
.B....B.
B......B
.B....B.
..B..B..
"""),
    "text-html": (4, 5, """
..BBB..
.B.B.B.
BBBBBBB
B..B..B
BBBBBBB
.B.B.B.
..BBB..
"""),
    "audio-x-generic": (4, 6, """
..AAAAA
..AAAAA
..A...A
..A...A
AAA.AAA
AAA.AAA
"""),
    "x-office-document": (4, 5, """
BBBBBBBB
BBBBBBBB
........
LLLLLLLL
........
LLLLLLLL
........
LLLLL...
"""),
    "x-office-spreadsheet": (4, 6, """
AAAAAAAA
A..A...A
AAAAAAAA
A..A...A
AAAAAAAA
A..A...A
AAAAAAAA
"""),
    "x-office-presentation": (4, 6, """
......EE
......EE
...AA.EE
...AA.EE
BB.AA.EE
BB.AA.EE
LLLLLLLL
"""),
    "font-x-generic": (4, 6, """
..LLLL..
.LL..LL.
.LL..LL.
.LLLLLL.
.LL..LL.
.LL..LL.
"""),
}

SCRIPT_PROMPT = (4, 6, """
h.......
.h......
..h.....
.h......
h...WWW.
""")

PDF_LABEL = """
.OOOOOOOOOOOOO..
.OEEEEEEEEEEEO..
.OWWEEWWEEWWWO..
.OWEWEWEWEWEEO..
.OWWEEWEWEWWEO..
.OWEEEWEWEWEEO..
.OWEEEWWEEWEEO..
.OeeeeeeeeeeeO..
.OOOOOOOOOOOOO..
"""

IMAGE = """
................
................
OOOOOOOOOOOOOOOO
OWWWWWWWWWWWWWWO
OWccccccccAAccWO
OWccccccccAAccWO
OWcccBccccccccWO
OWccBBBccccBccWO
OWcBBBBBccBBBcWO
OWBBBBBBBBBBBBWO
OWbbbbbbbbbbbbWO
OWWWWWWWWWWWWWWO
OOOOOOOOOOOOOOOO
................
................
................
"""

VIDEO = """
................
................
OOOOOOOOOOOOOOOO
OKWKWKWKKWKWKWKO
OBBBBBBBBBBBBBBO
OBBBBWWBBBBBBBBO
OBBBBWWWWBBBBBBO
OBBBBWWWWWWBBBBO
OBBBBWWWWBBBBBBO
OBBBBWWBBBBBBBBO
OBBBBBBBBBBBBBBO
OKWKWKWKKWKWKWKO
OOOOOOOOOOOOOOOO
................
................
................
"""

ARCHIVE = """
................
...OOOOOOOOOO...
..OhhhhWOhhhhO..
..OAAAAOWAAAAO..
..OAAAAWOAAAAO..
..OAAAAOWAAAAO..
..OAAAAWOAAAAO..
..OAAAAOWAAAAO..
..OAAAOOOOAAAO..
..OAAAOWWOAAAO..
..OAAAOWWOAAAO..
..OAAAAOOAAAAO..
..OAAAAAAAAAAO..
..OaaaaaaaaaaO..
...OOOOOOOOOO...
................
"""

PACKAGE = """
................
................
..OOOOOOOOOOOO..
.OqqqqqWWqqqqqO.
OOOOOOOOOOOOOOOO
.OPPPPPWWPPPPPO.
.OPPPPPWWPPPPPO.
.OPPPPPPPPPPPPO.
.OPPPPPPPPPPPPO.
.OPPPPPPPPPPPPO.
.OPPPPPPOOOOPPO.
.OPPPPPPOWWOPPO.
.OPPPPPPOOOOPPO.
.OppppppppppppO.
.OOOOOOOOOOOOOO.
................
"""

WINDOW = """
................
OOOOOOOOOOOOOOOO
OBBBBBBBBBBWBEBO
OOOOOOOOOOOOOOOO
OWWWWWWWWWWWWWWO
OWWW.b.b.b.WWWWO
OWWWbbbbbbbWWWWO
OWWW.bbbbb.WWWWO
OWWWbbb.bbbWWWWO
OWWW.bbbbb.WWWWO
OWWWbbbbbbbWWWWO
OWWW.b.b.b.WWWWO
OWWWWWWWWWWWWWWO
OwwwwwwwwwwwwwwO
OOOOOOOOOOOOOOOO
................
"""


def rows(text):
    return [r for r in text.strip("\n").split("\n")]


def grid(text, name="?"):
    g = rows(text)
    if len(g) != G or any(len(r) != G for r in g):
        raise ValueError("рисунок %s: нужна сетка %dx%d, а строки: %s"
                         % (name, G, G, [len(r) for r in g]))
    return [list(r) for r in g]


def over(g, glyph, x, y, keep="."):
    for j, row in enumerate(rows(glyph)):
        for i, ch in enumerate(row):
            if ch != keep and 0 <= y + j < G and 0 <= x + i < G:
                g[y + j][x + i] = ch
    return g


def swap(g, table):
    return [[table.get(ch, ch) for ch in row] for row in g]


def arts():
    """{контекст: {каноническое имя: сетка 16×16}}"""
    places, mimes, devices = {}, {}, {}
    places["folder"] = grid(FOLDER, "folder")
    places["folder-open"] = grid(FOLDER_OPEN, "folder-open")
    for name, glyph in EMBLEMS.items():
        w = max(len(r) for r in rows(glyph))
        places[name] = over(grid(FOLDER), glyph, 1 + (14 - w) // 2, 7)
    places["user-trash"] = grid(TRASH, "trash")
    places["user-trash-full"] = grid(TRASH_FULL, "trash-full")

    devices["drive-harddisk"] = grid(HDD, "hdd")
    devices["drive-removable-media"] = grid(USB, "usb")

    for name, (x, y, glyph) in ON_SHEET.items():
        mimes[name] = over(grid(SHEET, "sheet"), glyph, x, y)
    dark = swap(grid(SHEET), {"W": "K", "w": "k"})
    mimes["text-x-script"] = over(dark, SCRIPT_PROMPT[2], SCRIPT_PROMPT[0], SCRIPT_PROMPT[1])
    mimes["application-pdf"] = over(grid(SHEET), PDF_LABEL, 0, 7, keep=None)
    mimes["image-x-generic"] = grid(IMAGE, "image")
    mimes["video-x-generic"] = grid(VIDEO, "video")
    mimes["application-x-archive"] = grid(ARCHIVE, "archive")
    mimes["application-x-tar"] = swap(grid(ARCHIVE), {"A": "B", "a": "b", "h": "c"})
    mimes["application-x-pacman-package"] = grid(PACKAGE, "package")
    mimes["application-x-executable"] = over(grid(WINDOW, "window"), "", 0, 0)
    # В окне «.» внутри шестерёнки — это лист, а не дырка.
    g = mimes["application-x-executable"]
    for y in range(5, 12):
        for x in range(4, 11):
            if g[y][x] == ".":
                g[y][x] = "W"
    return {"places": places, "mimetypes": mimes, "devices": devices}


# ---------------------------------------------------------- имена и синонимы --

# Первое подошедшее правило выигрывает. None — «не наш значок, оставить Papirus».
PLACE_RULES = [
    ("user-trash-full", r"trash.*full"),
    ("user-trash", r"trash"),
    ("folder-open", r"[-_]open$|drag-accept|visiting"),
    ("folder-documents", r"document|wordprocessing|text|txt|notes|books"),
    ("folder-download", r"download|torrent"),
    ("folder-videos", r"video"),
    ("folder-pictures", r"picture|image|photo|camera"),
    ("folder-music", r"music|sound|audio"),
    ("user-desktop", r"desktop"),
    ("user-home", r"home"),
    ("folder-templates", r"template"),
    ("folder-publicshare", r"public"),
    ("folder-remote", r"remote|knetattach"),
    ("folder-network", r"network|wifi"),
    ("folder-favorites", r"favorite|bookmark|important"),
    ("folder-recent", r"recent|backup|temp$"),
    ("folder-locked", r"(?<!un)locked|private|encrypted"),
    ("folder-cloud", r"cloud|dropbox|gdrive|google-drive|mega|onedrive|yandex|sync"),
    ("folder-games", r"games|steam|wine"),
    ("folder-code", r"code|development|projects|script|git|html|java|docker|systemd"),
    ("folder", r""),
]
# Какие имена из places вообще считать папками/местами.
PLACE_OK = re.compile(
    r"^(folder([-_].*)?|inode-directory|gtk-directory|stock_folder|stock_open|"
    r"user-(desktop|home|home-open|trash|trash-full|bookmarks)|desktop|gnome-home|"
    r"trashcan_(empty|full)|network|network-workgroup|gtk-network|library-music|"
    r"knetattach|insync-folder)$")

B0 = r"(?<![a-z0-9])"
B1 = r"(?![a-z0-9])"
MIME_RULES = [
    ("application-pdf", r"pdf"),
    ("text-x-python", r"python|ipynb"),
    ("x-office-spreadsheet", r"spreadsheet|excel|" + B0 + r"(csv|ods|xlsx?)" + B1),
    ("x-office-presentation", r"presentation|powerpoint|" + B0 + r"(odp|pptx?)" + B1),
    ("x-office-document", r"x-office-document|msword|wordprocessing|opendocument\.text|"
                          + B0 + r"(rtf|odt|docx?|abiword)" + B1),
    (None, r"epub|comicbook|fictionbook|fb2|ebook|opendocument|officedocument|"
           r"openxmlformats|virtualbox|vmware|disk|iso|-rom$|kicad|vnd\.sun\.xml|stardivision"),
    ("application-x-pacman-package",
     r"pacman|alpm|debian|" + B0 + r"(deb|rpm|msi|apk|snap)" + B1
     + r"|appimage|flatpak|android\.package|package-repository"),
    ("application-x-tar", B0 + r"(g?tar|tarz|gzip|gz|bzip2?|bz2|xz|lzma|zstd|zst|lzip|lzop|lz4|compress)" + B1),
    ("application-x-archive",
     B0 + r"(zip|7z|rar|ark|cpio|ace|arj|lha|lzh|cab|jar|archive|stuffit)" + B1
     + r"|zip-compressed|7z-compressed|^package-x-generic$"),
    ("image-x-generic", r"^(gnome-mime-)?image-"),
    ("video-x-generic", r"^(gnome-mime-)?video-|flash\.movie|shockwave|matroska"),
    ("audio-x-generic", r"^(gnome-mime-)?audio-|^playlist$"),
    ("text-html", r"html|mswinurl"),
    ("text-x-script", r"shellscript|text-x-script|executable-script|pkgbuild|justfile|"
                      + B0 + r"x-(sh|csh|bash|zsh|fish|awk|bat)$"),
    ("text-x-generic",
     r"^text-(plain|asciidoc|enriched|org|vcard|markdown|troff|x-(generic|generic-template|"
     r"log|readme|changelog|copying|authors|install|markdown|tex|texmacs|typst|po|credits|"
     r"nfo|bibtex|plain))$|^(txt|text|ascii)$|-srt$|x-subrip|mbox|rfc822"),
    ("font-x-generic", r"font"),
    ("text-x-csrc", r"^text-|json|xml|yaml|toml|javascript|typescript|x-php|x-perl|x-ruby|"
                    r"x-asp$|wasm|x-cson|x-designer|x-java$|x-m4$|x-sql$|gettext"),
    ("application-x-executable", r"x-executable|x-desktop|msdos-program|ms-dos-executable|"
                                 r"msdownload|x-elf|application-default-icon"),
    ("application-octet-stream", r"octet-stream|x-sharedlib|x-object|x-core$|x-firmware"),
    ("application-x-zerosize", r"zerosize"),
    ("unknown", r"^(unknown|empty|gtk-file|application-x-generic|none)$"),
]
# Имена, которых в Papirus может не быть, а программы их спрашивают.
MIME_EXTRA = """
text-plain text-x-generic text-x-log text-markdown text-x-readme unknown
application-octet-stream application-x-zerosize
application-x-shellscript text-x-script text-x-sh application-x-sh
text-x-python text-x-python3 application-x-python-bytecode
application-zip application-x-zip application-x-zip-compressed application-x-7z-compressed
application-vnd.rar application-x-rar application-x-rar-compressed application-x-archive
application-x-java-archive application-x-cpio package-x-generic
application-x-tar application-gzip application-x-gzip application-x-bzip application-x-bzip2
application-x-xz application-zstd application-x-zstd application-x-lzma application-x-compress
application-x-compressed-tar application-x-bzip-compressed-tar application-x-bzip2-compressed-tar
application-x-xz-compressed-tar application-x-zstd-compressed-tar application-x-lzma-compressed-tar
application-x-lz4-compressed-tar application-x-tarz application-x-gtar
application-x-pacman-package application-x-alpm-package application-vnd.debian.binary-package
application-x-deb application-x-rpm application-vnd.appimage application-vnd.flatpak
image-x-generic image-png image-jpeg image-gif image-webp image-bmp image-svg+xml image-tiff
image-avif image-heif image-x-icon
video-x-generic video-mp4 video-x-matroska video-webm video-quicktime video-x-msvideo video-mpeg
audio-x-generic audio-mpeg audio-flac audio-ogg audio-x-wav audio-mp4 audio-aac audio-x-vorbis+ogg
application-pdf text-html application-xhtml+xml
text-x-csrc text-x-chdr text-x-c++src text-x-c++hdr text-x-java text-x-go text-x-rust
text-css application-json application-xml text-xml application-javascript text-javascript
application-x-yaml application-yaml application-toml text-x-makefile text-x-cmake
application-x-executable application-x-desktop application-x-ms-dos-executable
application-x-sharedlib font-x-generic font-ttf font-otf application-x-font-ttf
x-office-document x-office-spreadsheet x-office-presentation
application-msword application-vnd.ms-excel application-vnd.ms-powerpoint text-csv
""".split()

DEVICE_RULES = [
    (None, r"optical|cdrom|disc|dvd|floppy|ipod|tape|zip|jaz|virtual"),
    ("drive-removable-media", r"removable|pendrive|usb|media-flash|media-(cf|ms|sm|sd)"),
    ("drive-harddisk", r"harddisk|harddrive|multidisk|^hdd"),
]
DEVICE_OK = re.compile(r"^(drive-|media-|gnome-dev-(harddisk|removable|media)|harddrive|hdd|usbpendrive)")
DEVICE_EXTRA = ["drive-harddisk", "drive-harddisk-root", "drive-harddisk-system",
                "drive-harddisk-solidstate", "drive-harddisk-usb", "drive-removable-media",
                "drive-removable-media-usb", "drive-removable-media-usb-pendrive",
                "media-removable", "media-flash"]
PLACE_EXTRA = ["folder", "folder-open", "inode-directory", "folder-documents",
               "folder-download", "folder-downloads", "folder-pictures", "folder-images",
               "folder-music", "folder-sound", "folder-videos", "folder-video",
               "user-desktop", "folder-desktop", "desktop", "user-home", "folder-home",
               "folder-templates", "folder-publicshare", "folder-public", "user-trash",
               "user-trash-full", "folder-network", "network-workgroup", "folder-remote",
               "folder-favorites", "user-bookmarks", "folder-recent", "folder-locked",
               "folder-cloud", "folder-code", "folder-development", "folder-games",
               "folder-drag-accept", "folder-visiting"]


def papirus_names(ctx):
    """{имя: имя настоящего файла, на который оно ссылается} из Papirus."""
    out = {}
    for size in ("64x64", "48x48", "22x22", "16x16"):
        d = os.path.join(PAPIRUS, size, ctx)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            n, ext = os.path.splitext(f)
            if ext != ".svg" or n.endswith("-symbolic") or n in out:
                continue
            real = os.path.basename(os.path.realpath(os.path.join(d, f)))
            out[n] = os.path.splitext(real)[0]
    return out


def classify(name, rules):
    """-> (нашлось ли правило, имя рисунка или None)"""
    for target, rx in rules:
        if re.search(rx, name):
            return True, target
    return False, None


def name_map():
    """{контекст: {имя значка: каноническое имя рисунка}}"""
    res = {"places": {}, "mimetypes": {}, "devices": {}}

    pl = papirus_names("places")
    colours_ = {m.group(1) for n in pl for m in [re.fullmatch(r"folder-([a-z]+)-documents", n)] if m}
    for n in list(pl) + PLACE_EXTRA:
        if not PLACE_OK.match(n):
            continue
        if re.match(r"^(folder|user)-(%s)(-|$)" % "|".join(sorted(colours_) or ["blue"]), n):
            continue                      # цветовые наборы Papirus никто не просит
        res["places"][n] = classify(n, PLACE_RULES)[1]

    mi = papirus_names("mimetypes")
    for n in list(mi) + MIME_EXTRA:
        hit, target = classify(n, MIME_RULES)
        if not hit and mi.get(n, n) != n:   # имя ничего не сказало — смотрим, куда ссылка
            hit, target = classify(mi[n], MIME_RULES)
        if hit and target:
            res["mimetypes"][n] = target
    res["mimetypes"]["inode-directory"] = None
    res["mimetypes"] = {k: v for k, v in res["mimetypes"].items() if v}

    dv = papirus_names("devices")
    for n in list(dv) + DEVICE_EXTRA:
        if not DEVICE_OK.match(n):
            continue
        target = classify(n, DEVICE_RULES)[1]
        if target:
            res["devices"][n] = target
    return res


# ------------------------------------------------- значки программ (pixel-all) --

CACHE = os.path.join(HOME, ".cache/jarvis-pixel-apps")
# 20 — «Пуск»/меню просят 20 px; без своей папки GTK мылил бы 22 → 20.
APP_SIZES = (16, 20, 22, 24, 32, 48, 64, 80, 96, 112, 128, 256)
APP_COLORS = 12
APP_ALGO = "4"          # поменять при правке pixelate(): кэш перерисуется весь
APP_CTX = {"apps": "Applications", "actions": "Actions", "status": "Status"}

# Частые действия меню и панелей инструментов (Dolphin, Kate, диалоги).
ACTION_NAMES = """
document-new document-open document-open-recent document-save document-save-as document-print
document-print-preview document-properties document-close document-edit document-export
document-import document-revert document-send document-share
edit-copy edit-cut edit-paste edit-delete edit-undo edit-redo edit-find edit-find-replace
edit-select-all edit-clear edit-rename
view-refresh view-fullscreen view-restore view-sort-ascending view-sort-descending
view-list-details view-list-icons view-list-tree view-preview view-hidden view-filter view-grid
zoom-in zoom-out zoom-original zoom-fit-best
go-previous go-next go-up go-down go-home go-first go-last go-top go-bottom go-jump
list-add list-remove window-close window-new window-maximize window-minimize window-restore
tab-new tab-close application-exit system-run system-search system-shutdown system-reboot
system-log-out system-lock-screen system-suspend system-hibernate system-switch-user
help-about help-contents help-browser preferences-system preferences-desktop configure
media-playback-start media-playback-pause media-playback-stop media-skip-forward
media-skip-backward media-record media-eject mail-send mail-message-new bookmark-new
bookmarks-organize insert-image insert-link insert-text format-text-bold format-text-italic
format-text-underline object-rotate-left object-rotate-right object-flip-horizontal
object-flip-vertical process-stop dialog-information dialog-warning dialog-error
dialog-question dialog-password dialog-ok dialog-cancel
audio-volume-high audio-volume-medium audio-volume-low audio-volume-muted
""".split()
# Семейства значков трея из Papirus (сеть, Bluetooth, звук) — по началу имени.
TRAY_FAMILIES = re.compile(r"^(nm-|blueman|audio-volume-|microphone-sensitivity-)")

_THEMES = {}


def icon_bases():
    dirs = [os.path.join(HOME, ".local/share/icons"), os.path.join(HOME, ".icons")]
    xdg = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs += [os.path.join(d, "icons") for d in xdg.split(":") if d]
    dirs += ["/usr/share/icons", "/var/lib/flatpak/exports/share/icons",
             os.path.join(HOME, ".local/share/flatpak/exports/share/icons")]
    out = []
    for d in dirs:
        if os.path.isdir(d) and d not in out:
            out.append(d)
    return out


def theme_info(name):
    """(корни темы, [(папка, размер, масштаб)], родители) по index.theme."""
    if name in _THEMES:
        return _THEMES[name]
    roots = [os.path.join(b, name) for b in icon_bases() if os.path.isdir(os.path.join(b, name))]
    dirs, parents, sec, info = [], [], None, {}
    for r in roots:
        try:
            text = open(os.path.join(r, "index.theme"), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            m = re.fullmatch(r"\[(.*)\]", line)
            if m:
                sec = m.group(1)
                info.setdefault(sec, {})
            elif sec and "=" in line:
                k, v = line.split("=", 1)
                info[sec][k.strip()] = v.strip()
        break
    head = info.get("Icon Theme", {})
    parents = [p.strip() for p in head.get("Inherits", "").split(",") if p.strip()]
    for d in (head.get("Directories", "") + "," + head.get("ScaledDirectories", "")).split(","):
        d = d.strip()
        if d in info:
            try:
                dirs.append((d, int(info[d].get("Size", "0")), int(info[d].get("Scale", "1"))))
            except ValueError:
                pass
    _THEMES[name] = (roots, dirs, parents)
    return _THEMES[name]


def source_chain():
    """Порядок поиска, как у GTK: каждая тема из INHERITS, вглубь по родителям."""
    out = []

    def walk(t):
        if t in out or t == "hicolor":
            return
        out.append(t)
        for p in theme_info(t)[2]:
            walk(p)
    for t in INHERITS.split(","):
        walk(t)
    return out + ["hicolor"]


def find_source(name, chain):
    """-> (путь, размер, контекст) лучшего исходника для сетки 16×16 или None.
    Лучший — нарисованный под 16 px; затем векторный; затем самый крупный."""
    for t in chain:
        roots, dirs, _ = theme_info(t)
        found = []
        for d, size, scale in dirs:
            for r in roots:
                for ext in (".svg", ".png", ".xpm"):
                    p = os.path.join(r, d, name + ext)
                    if os.path.isfile(p):
                        found.append((size != G or scale != 1, ext != ".svg", scale != 1,
                                      -size, p, size, d.rsplit("/", 1)[-1]))
        if found:
            best = min(found)
            return best[4], best[5], best[6]
    for ext in (".svg", ".png", ".xpm"):
        p = os.path.join("/usr/share/pixmaps", name + ext)
        if os.path.isfile(p):
            return p, 0, "apps"
    return None


def app_ctx(srcdir):
    if srcdir in ("actions",):
        return "actions"
    if srcdir in ("panel", "status", "animations"):
        return "status"
    return "apps"


def desktop_icons():
    """Имена из Icon= всех .desktop (пути к файлам тема заменить не может)."""
    dirs = [os.path.join(HOME, ".local/share/applications"), "/usr/share/applications",
            "/usr/local/share/applications", "/var/lib/flatpak/exports/share/applications",
            os.path.join(HOME, ".local/share/flatpak/exports/share/applications")]
    out = set()
    for d in dirs:
        try:
            files = os.listdir(d)
        except OSError:
            continue
        for f in files:
            if not f.endswith(".desktop"):
                continue
            try:
                text = open(os.path.join(d, f), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in re.finditer(r"^Icon=(.+)$", text, re.M):
                n = re.sub(r"\.(png|svg|xpm)$", "", m.group(1).strip())
                if n and "/" not in n and " " not in n:
                    out.add(n)
    return out


def window_ids():
    """app_id открытых окон niri — и как есть, и в нижнем регистре."""
    try:
        r = subprocess.run(["niri", "msg", "-j", "windows"], capture_output=True, text=True, timeout=2)
        wins = json.loads(r.stdout or "[]")
    except Exception:
        return set()
    out = set()
    for w in wins:
        a = (w.get("app_id") or "").strip()
        if a and "/" not in a and " " not in a:
            out |= {a, a.lower(), a.split(".")[-1].lower()}
    return out


def tray_names():
    """IconName значков трея, что висят сейчас (через StatusNotifierWatcher)."""
    def call(dest, path, iface, prop):
        r = subprocess.run(["gdbus", "call", "--session", "--dest", dest, "--object-path", path,
                            "--method", "org.freedesktop.DBus.Properties.Get", iface, prop],
                           capture_output=True, text=True, timeout=2)
        return r.stdout
    out = set()
    try:
        items = re.findall(r"'([^']+)'", call("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                                              "org.kde.StatusNotifierWatcher",
                                              "RegisteredStatusNotifierItems"))
        for it in items:
            dest, _, path = it.partition("/")
            for prop in ("IconName", "AttentionIconName"):
                for n in re.findall(r"'([^']*)'", call(dest, "/" + path, "org.kde.StatusNotifierItem", prop)):
                    if n and "/" not in n:
                        out.add(n)
    except Exception:
        pass
    return out


def load_manifest():
    try:
        with open(os.path.join(CACHE, "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        if m.get("algo") == APP_ALGO:
            m.setdefault("icons", {})
            m.setdefault("seen", [])
            return m
    except (OSError, ValueError):
        pass
    return {"algo": APP_ALGO, "icons": {}, "seen": []}


def save_manifest(m):
    os.makedirs(CACHE, exist_ok=True)
    tmp = os.path.join(CACHE, "manifest.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, os.path.join(CACHE, "manifest.json"))


# Свой исходник вместо найденного в теме (07.10.2026, Просьба: «в Alt+Tab фон значка Zen
# стал белый») — у Papirus Zen светлый с розовыми кольцами, родной — тёмный, но в 16 px
# его кольца сливаются в серое пятно; поэтому нарисован вручную по сетке: (путь, размер).
SOURCE_OVERRIDE = {
    "zen-browser": (os.path.expanduser("~/.local/share/icons/jarvis-src/zen-browser-16.png"), 16),
}


def wanted_apps(manifest):
    """{имя: (путь, размер, контекст)} — что перерисовать в пиксели."""
    own = set()
    for ctx, m in name_map().items():
        own |= set(m)
    for pics in arts().values():
        own |= set(pics)
    ids = window_ids()
    manifest["seen"] = sorted(set(manifest.get("seen", [])) | ids)
    names = desktop_icons() | set(manifest["seen"]) | set(ACTION_NAMES) | tray_names()
    for d in ("16x16/panel", "22x22/panel"):
        try:
            names |= {os.path.splitext(f)[0] for f in os.listdir(os.path.join(PAPIRUS, d))
                      if TRAY_FAMILIES.match(f)}
        except OSError:
            pass
    chain = source_chain()
    out = {}
    for n in sorted(names):
        if n in own or n.endswith("-symbolic") or n.startswith("."):
            continue
        hit = find_source(n, chain)
        if n in SOURCE_OVERRIDE and os.path.isfile(SOURCE_OVERRIDE[n][0]):
            hit = SOURCE_OVERRIDE[n] + ("apps",)
        if hit:
            out[n] = hit
    return out


SS = 4                  # подвыборка: каждый пиксель сетки — блок 4×4 исходника


def load_square(path, size):
    """Исходник -> RGBA (G·SS)². Нарисованный под 16 px — во весь холст как есть;
    крупный обрезается по прозрачным полям и вписывается в 15×15 по центру."""
    from PIL import Image
    native = size == G
    full = G * SS
    if path.endswith(".svg"):
        px = full if native else G * 32
        r = subprocess.run(["rsvg-convert", "-w", str(px), "-h", str(px), "-a", path],
                           capture_output=True, timeout=20)
        if r.returncode != 0 or not r.stdout:
            raise ValueError("rsvg-convert: %s" % r.stderr.decode(errors="replace").strip()[:120])
        img = Image.open(io.BytesIO(r.stdout)).convert("RGBA")
    else:
        img = Image.open(path).convert("RGBA")
    if native and img.size == (full, full):
        return img
    if native and img.size == (G, G):            # PNG 16 px: блоки однородные
        return img.resize((full, full), Image.NEAREST)
    box = img.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
    if box:
        img = img.crop(box)
    w, h = img.size
    k = (G - 1) * SS / max(w, h)
    nw, nh = max(1, round(w * k)), max(1, round(h * k))
    out = Image.new("RGBA", (full, full))
    # смещение кратно SS, чтобы рисунок ложился на сетку целыми пикселями
    out.paste(img.resize((nw, nh), Image.BOX),
              (((full - nw) // 2) // SS * SS, ((full - nh) // 2) // SS * SS))
    return out


def pixelate(img, ncol=APP_COLORS):
    """-> RGBA 16×16: пиксель занят, если накрыт исходником хотя бы на 45 %
    (края жёсткие), цвет — среднее накрытой части; не больше ncol цветов.
    Нарочно полупрозрачное (серые деления сигнала, «выключенный» значок)
    остаётся полупрозрачным, но ровным: несколько ступеней, без мягких краёв."""
    from PIL import Image
    src = img.load()
    n = img.size[0] // G
    a_max = max(src[x, y][3] for y in range(img.size[1]) for x in range(img.size[0]))
    if not a_max:
        return Image.new("RGBA", (G, G))
    low, high = a_max * 0.2, a_max * 0.8
    full = 255 if a_max > 200 else max(48, int(round(a_max / 32.0)) * 32)
    cells = {}
    for gy in range(G):
        for gx in range(G):
            r = g = b = a = cov = top = 0
            for y in range(gy * n, gy * n + n):
                for x in range(gx * n, gx * n + n):
                    p = src[x, y]
                    if p[3] >= low:
                        cov += 1
                        r += p[0] * p[3]
                        g += p[1] * p[3]
                        b += p[2] * p[3]
                        a += p[3]
                        top = max(top, p[3])
            if cov >= 0.45 * n * n:
                # есть хоть один плотный подпиксель — это край фигуры: пиксель целый
                lvl = full if top >= high else max(48, int(round(a / cov / 32.0)) * 32)
                cells[gx, gy] = ((round(r / a), round(g / a), round(b / a)), lvl)
    if not cells:
        return Image.new("RGBA", (G, G))
    pts = list(cells)
    strip = Image.new("RGB", (len(pts), 1))
    sp = strip.load()
    for i, xy in enumerate(pts):
        sp[i, 0] = cells[xy][0]
    q = strip.quantize(colors=max(1, min(ncol, len(pts))), method=Image.Quantize.MEDIANCUT,
                       kmeans=3, dither=Image.Dither.NONE).convert("RGB").load()
    out = Image.new("RGBA", (G, G))
    op = out.load()
    for i, xy in enumerate(pts):
        op[xy] = q[i, 0] + (cells[xy][1],)
    return out


def _cache_path(size, name):
    return os.path.join(CACHE, "%d" % size, name + ".png")


def sync_apps(log=print):
    """Дорисовать в кэш недостающие значки программ. -> {имя: контекст}."""
    import time
    t0 = time.time()
    m = load_manifest()
    want = wanted_apps(m)
    todo = []
    for n, (path, size, srcdir) in want.items():
        try:
            mt = os.stat(path).st_mtime
        except OSError:
            continue
        e = m["icons"].get(n)
        if e and e.get("src") == path and e.get("mt") == mt and (e.get("empty") or all(
                os.path.exists(_cache_path(s, n)) for s in APP_SIZES)):
            continue
        todo.append((n, path, size, srcdir, mt))
    if todo:
        log("значки программ: нужно %d из %d (остальные уже в кэше)" % (len(todo), len(want)))
    tty = sys.stdout.isatty()
    bad = 0
    for i, (n, path, size, srcdir, mt) in enumerate(todo, 1):
        try:
            img = pixelate(load_square(path, size))
            if not img.getbbox():        # пустышка-накладка: пусть остаётся из Papirus
                m["icons"][n] = {"src": path, "mt": mt, "ctx": app_ctx(srcdir), "empty": True}
                continue
            for s in APP_SIZES:
                p = _cache_path(s, n)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                tmp = p + ".tmp"
                sized(img, s).save(tmp, format="PNG", optimize=s >= 64)
                os.replace(tmp, p)       # старая копия в теме — отдельная ссылка, не портится
            m["icons"][n] = {"src": path, "mt": mt, "ctx": app_ctx(srcdir)}
        except Exception as e:
            bad += 1
            m["icons"].pop(n, None)
            print("  %s: %s" % (n, e), file=sys.stderr)
        if tty:
            sys.stdout.write("\r  [%d/%d] %-40s" % (i, len(todo), n[:40]))
            sys.stdout.flush()
        elif i % 25 == 0 or i == len(todo):
            log("  [%d/%d] %s" % (i, len(todo), n))
        if i % 50 == 0:
            save_manifest(m)
    if tty and todo:
        sys.stdout.write("\n")
    save_manifest(m)
    if todo:
        log("значки программ: нарисовано %d, ошибок %d, %.1f с" % (len(todo) - bad, bad, time.time() - t0))
    return {n: m["icons"][n]["ctx"] for n in want
            if n in m["icons"] and not m["icons"][n].get("empty")}


def _link(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


# -------------------------------------------------------------------- сборка --

def render(g, pal):
    from PIL import Image
    img = Image.new("RGBA", (G, G))
    img.putdata([pal.get(ch, (255, 0, 255, 255)) for row in g for ch in row])
    return img


def sized(img, size):
    from PIL import Image
    k = max(1, size // G)
    big = img.resize((G * k, G * k), Image.NEAREST) if k > 1 else img
    if G * k == size:
        return big
    out = Image.new("RGBA", (size, size))
    off = (size - G * k) // 2
    out.paste(big, (off, off))
    return out


def signature():
    p = palette_src()
    try:
        src = os.path.getmtime(os.path.abspath(__file__))
    except OSError:
        src = 0
    return "%s %s %s %s %d" % (p["primary"], p["tertiary"], p["secondary"], p["error"], src)


def build(force=False, apps=None, log=print):
    """apps: класть ли пиксельные значки программ (None — по выбранному режиму)."""
    if apps is None:
        apps = get() == "pixel-all"
    with Locked():
        return _build(force, apps, log)


class Locked:
    """Замок на сборку и смену темы: две сборки разом портили бы .new, а
    быстрые щелчки в Настройках не должны применяться наперегонки."""
    def __enter__(self):
        self.f = open(LOCK, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)

    def __exit__(self, *_):
        self.f.close()


def _build(force, apps, log):
    app_set = sync_apps(log) if apps else {}
    sig = signature()
    if apps:
        h = hashlib.sha1()
        m = load_manifest()["icons"]
        for n in sorted(app_set):
            h.update(("%s %s %s\n" % (n, m[n]["src"], m[n]["mt"])).encode())
        sig += " apps:%s" % h.hexdigest()[:16]
    try:
        cur = open(os.path.join(DST, ".signature")).read().strip()
    except OSError:
        cur = ""
    if cur == sig and not force and os.path.exists(os.path.join(DST, "index.theme")):
        return "значки уже под текущую палитру — без изменений"

    pal = colours()
    drawn = arts()
    names = name_map()
    tmp = DST + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    dirs, files, links = [], 0, 0
    ctx_title = {"places": "Places", "mimetypes": "MimeTypes", "devices": "Devices"}
    for ctx, pics in drawn.items():
        base = {n: render(g, pal) for n, g in pics.items()}
        for size in SIZES:
            sub = "%dx%d/%s" % (size, size, ctx)
            d = os.path.join(tmp, sub)
            os.makedirs(d)
            dirs.append((sub, size, ctx_title[ctx]))
            for n, img in base.items():
                sized(img, size).save(os.path.join(d, n + ".png"), optimize=True)
                files += 1
            for alias, target in names[ctx].items():
                if alias in base or target not in base:
                    continue
                os.symlink(target + ".png", os.path.join(d, alias + ".png"))
                links += 1

    # Значки программ: готовые PNG из кэша — жёсткими ссылками, это миллисекунды.
    n_apps = 0
    for size in APP_SIZES if app_set else ():
        made = set()
        for n, ctx in app_set.items():
            sub = "%dx%d/%s" % (size, size, ctx)
            if sub not in made:
                os.makedirs(os.path.join(tmp, sub), exist_ok=True)
                dirs.append((sub, size, APP_CTX[ctx]))
                made.add(sub)
            _link(_cache_path(size, n), os.path.join(tmp, sub, n + ".png"))
            n_apps += 1

    with open(os.path.join(tmp, "index.theme"), "w", encoding="utf-8") as f:
        f.write("[Icon Theme]\nName=%s\n"
                "Comment=Пиксельные папки и файлы в цветах обоев (icon_theme.py)\n"
                "Inherits=%s\nDirectories=%s\n" % (NAME, INHERITS, ",".join(d[0] for d in dirs)))
        # Все папки — Fixed (PNG точного размера, без масштаба), кроме самой
        # крупной: она Scalable от 129 до 512, чтобы Qt/GTK не искали SVG выше.
        for sub, size, ctx in dirs:
            f.write("\n[%s]\nSize=%d\nContext=%s\n" % (sub, size, ctx))
            if size == SIZES[-1]:
                f.write("Type=Scalable\nMinSize=%d\nMaxSize=512\n" % (SIZES[-2] + 1))
            else:
                f.write("Type=Fixed\n")
    with open(os.path.join(tmp, ".signature"), "w") as f:
        f.write(sig + "\n")

    old = DST + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.lexists(DST):
        os.rename(DST, old)
    os.rename(tmp, DST)
    shutil.rmtree(old, ignore_errors=True)
    if shutil.which("gtk-update-icon-cache"):
        subprocess.run(["gtk-update-icon-cache", "-q", "-f", "-t", DST], capture_output=True)
    return "значки собраны: %d рисунков, %d файлов, %d ссылок%s" % (
        sum(len(p) for p in drawn.values()), files, links,
        "; программ %d (%d файлов)" % (len(app_set), n_apps) if app_set else "")


def _original(path, px):
    """Исходник программы как есть — для сравнения на листе превью."""
    from PIL import Image
    try:
        if path.endswith(".svg"):
            r = subprocess.run(["rsvg-convert", "-w", str(px), "-h", str(px), "-a", path],
                               capture_output=True, timeout=20)
            img = Image.open(io.BytesIO(r.stdout)).convert("RGBA")
        else:
            img = Image.open(path).convert("RGBA")
        img.thumbnail((px, px), Image.LANCZOS)
        return img
    except Exception:
        return None


def preview(path, only=None):
    """Лист: свои рисунки (48 и 16 px), затем значки программ из кэша —
    пиксельный 48, пиксельный 16 и исходник 24 px для сравнения.
    only — список имён программ (через запятую в командной строке)."""
    from PIL import Image, ImageDraw
    pal = colours()
    items = [(n, render(g, pal), None) for pics in arts().values() for n, g in pics.items()]
    icons = load_manifest()["icons"]
    for n in sorted(icons):
        if (only and n not in only) or icons[n].get("empty"):
            continue
        p = _cache_path(G, n)
        if os.path.exists(p):
            items.append((n, Image.open(p).convert("RGBA"), icons[n]["src"]))
    if only:
        items = [it for it in items if it[2]]
    cols, cell_w, cell_h = 8, 104, 96
    n_rows = (len(items) + cols - 1) // cols
    bg = tone(palette_src()["primary"], 0.09, 0.25)
    sheet = Image.new("RGBA", (cols * cell_w, max(1, n_rows) * cell_h), bg)
    draw = ImageDraw.Draw(sheet)
    for i, (n, img, src) in enumerate(items):
        x, y = (i % cols) * cell_w, (i // cols) * cell_h
        sheet.alpha_composite(sized(img, 48), (x + 12, y + 10))
        sheet.alpha_composite(sized(img, 16), (x + 72, y + 12 if src else y + 26))
        if src:
            orig = _original(src, 24)
            if orig:
                sheet.alpha_composite(orig, (x + 68 + (24 - orig.width) // 2, y + 36))
        label = n.replace("application-", "").replace("x-office-", "office-")[:16]
        draw.text((x + 4, y + 68), label, fill=(200, 205, 225, 255))
    sheet.save(path)
    return path


# ---------------------------------------------------------------- применение --

def papirus_theme():
    for n in ("Papirus-Wall", "Papirus-Dark", "Papirus"):
        for root in (os.path.join(HOME, ".local/share/icons"), "/usr/share/icons"):
            if os.path.exists(os.path.join(root, n, "index.theme")):
                return n
    return "Papirus-Dark"


def get():
    try:
        v = open(STATE).read().strip()
        if v in MODES:
            return v
    except OSError:
        pass
    try:
        cur = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "icon-theme"],
                             capture_output=True, text=True, timeout=5).stdout.strip().strip("'")
    except Exception:
        cur = ""
    return "pixel" if cur == NAME else "papirus"


def _sub_line(path, pattern, repl):
    """Заменить строку в файле настроек, если такая там есть. -> изменено ли."""
    path = os.path.realpath(path)
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return False
    new, n = re.subn(pattern, repl, text, flags=re.M)
    if not n or new == text:
        return False
    bak = path + ".bak-icons"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    tmp = path + ".icons-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    shutil.copymode(path, tmp)
    os.replace(tmp, path)
    return True


def apply(theme):
    """Прописать тему значков всюду, где она задана. Пишет только отличия."""
    cfg = os.path.join(HOME, ".config")
    try:
        cur = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "icon-theme"],
                             capture_output=True, text=True, timeout=5).stdout.strip().strip("'")
        if cur != theme:
            subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "icon-theme", theme],
                           capture_output=True, timeout=5)
    except Exception:
        pass

    # kdeglobals: [Icons] Theme. Без --notify: на сигнал ConfigChanged Dolphin
    # раздувается до 2 ГБ (см. theme_changer.sh), новую тему он берёт при запуске.
    kde = os.path.join(cfg, "kdeglobals")
    have = ""
    try:
        m = re.search(r"^\[Icons\]\n(?:(?!\[).*\n)*?Theme=(.*)$",
                      open(kde, encoding="utf-8").read(), re.M)
        have = m.group(1).strip() if m else ""
    except OSError:
        pass
    if have != theme:
        if os.path.exists(kde) and not os.path.exists(kde + ".bak-icons"):
            shutil.copy2(kde, kde + ".bak-icons")
        done = False
        if shutil.which("kwriteconfig6"):
            done = subprocess.run(["kwriteconfig6", "--file", "kdeglobals", "--group", "Icons",
                                   "--key", "Theme", theme], capture_output=True).returncode == 0
        if not done:
            _sub_line(kde, r"^(\[Icons\]\n(?:(?!\[).*\n)*?Theme=).*$", r"\g<1>" + theme)

    for ini in ("gtk-3.0/settings.ini", "gtk-4.0/settings.ini"):
        _sub_line(os.path.join(cfg, ini), r"^gtk-icon-theme-name=.*$", "gtk-icon-theme-name=" + theme)
    _sub_line(os.path.join(HOME, ".gtkrc-2.0"), r'^gtk-icon-theme-name=.*$',
              'gtk-icon-theme-name="%s"' % theme)
    for qt in ("qt6ct/qt6ct.conf", "qt5ct/qt5ct.conf"):
        _sub_line(os.path.join(cfg, qt), r"^icon_theme=.*$", "icon_theme=" + theme)
    if _sub_line(os.path.join(cfg, "xsettingsd/xsettingsd.conf"),
                 r'^Net/IconThemeName .*$', 'Net/IconThemeName "%s"' % theme):
        try:    # xsettingsd перечитывает файл по SIGHUP; только по PID
            pids = subprocess.run(["pgrep", "-x", "-u", str(os.getuid()), "xsettingsd"],
                                  capture_output=True, text=True).stdout.split()
            for pid in pids:
                os.kill(int(pid), signal.SIGHUP)
        except Exception:
            pass


def restart_panels():
    """Перезапустить то, что держит значки программ в памяти: нижнюю панель
    (xpbar) и меню рабочего стола — только если они сейчас работают."""
    here = os.path.dirname(os.path.abspath(__file__))
    xp = os.path.join(here, "xpbar.py")
    try:
        if subprocess.run(["python3", xp, "status"], capture_output=True, text=True,
                          timeout=5).stdout.strip() == "on":
            subprocess.run(["python3", xp, "restart"], capture_output=True, timeout=15)
    except Exception:
        pass
    # desktop_menu: pid из его замка, проверка cmdline, TERM, ждём выхода, поднимает niri.
    menu = os.path.join(here, "desktop_menu.py")
    try:
        lock = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-desktop-menu.lock")
        pid = int(open(lock).read().strip() or 0)
        argv = open("/proc/%d/cmdline" % pid, "rb").read().split(b"\0")
        if pid and any(a.endswith(b"desktop_menu.py") for a in argv):
            import time
            os.kill(pid, signal.SIGTERM)
            for _ in range(60):
                if not os.path.exists("/proc/%d" % pid):
                    break
                time.sleep(0.05)
            subprocess.run(["niri", "msg", "action", "spawn", "--", "python3", menu],
                           capture_output=True, timeout=5)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def set_theme(which):
    before = get()
    with Locked():
        if which in ("pixel", "pixel-all"):
            msg = _build(False, which == "pixel-all", print)
            print(msg)
            if not os.path.exists(os.path.join(DST, "index.theme")):
                print("тема не собралась: " + msg, file=sys.stderr)
                return 1
            apply(NAME)
        else:
            apply(papirus_theme())
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as f:
            f.write(which + "\n")
    if before != which:
        restart_panels()
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "build":
        print(build(force="--force" in argv))
        if get() in ("pixel", "pixel-all"):
            apply(NAME)                 # matugen вернул в kdeglobals Papirus-Wall
        return 0
    if cmd == "get":
        print(get())
        return 0
    if cmd == "set" and len(argv) > 2 and argv[2] in MODES:
        return set_theme(argv[2])
    if cmd == "preview":
        rest = [a for a in argv[2:] if not a.startswith("--")]
        only = None
        for a in argv[2:]:
            if a.startswith("--only="):
                only = set(a[7:].split(","))
        print(preview(rest[0] if rest else "/tmp/jarvis-pixel-preview.png", only))
        return 0
    if cmd == "names":
        for ctx, m in name_map().items():
            by = {}
            for alias, target in m.items():
                by.setdefault(target, []).append(alias)
            for target in sorted(by, key=str):
                print("%s/%s: %s" % (ctx, target, " ".join(sorted(by[target]))))
        return 0
    if cmd == "apps":
        for n, (path, size, srcdir) in sorted(wanted_apps(load_manifest()).items()):
            print("%s/%s: %s (%s px)" % (app_ctx(srcdir), n, path, size or "?"))
        return 0
    print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
