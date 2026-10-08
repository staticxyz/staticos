#!/usr/bin/env python3
"""Собрать палитру Telegram Desktop из цветов текущих обоев.

Почему не шаблон matugen. У Telegram палитра — это 328 ключей, из которых 206
задают цвет числом, а остальные ссылаются друг на друга. Расписать их вручную
нельзя, а урезанный файл клиент не примет. Поэтому берётся ШТАТНАЯ ночная
палитра клиента (вытащена из самого бинарника Telegram, см. templates/
telegram-night.palette) и перекрашивается по правилам:

  * почти серые цвета — интерфейсный каркас. Им подставляется тон обоев со
    слабой насыщенностью, светлота сохраняется. Так каркас перестаёт быть
    нейтрально-серым, но не разъезжается по контрасту.
  * синие — фирменный акцент Telegram и весь построенный на нём хром
    (кнопки, активный чат, свои сообщения). Их тон уводится к акценту обоев.
  * всё остальное — красный, зелёный, жёлтый — НЕ трогается. Это смысловые
    цвета: ошибка, «в сети», непрочитанное. Перекрасить их значит сломать
    язык интерфейса, а не тему.

Поверх этого несколько ключей задаются напрямую из ролей палитры — те, что
видно всегда: фон окна, текст, активный чат, пузыри сообщений, поле ввода.
"""
import colorsys
import json
import os
import re
import sys
import zipfile

BASE = os.environ.get("TG_BASE", os.path.expanduser(
    "~/.config/matugen/templates/telegram-night.palette"))
PALETTE = os.environ.get("TG_PALETTE", os.path.expanduser(
    "~/.cache/matugen/colors.json"))
OUT = os.environ.get("TG_OUT", os.path.expanduser(
    "~/.cache/matugen/matugen.tdesktop-palette"))
# Тот же файл, упакованный так, как Telegram принимает темы: zip с одним
# файлом colors.tdesktop-theme внутри и расширением .tdesktop-theme. Такой
# файл клиент понимает при перетаскивании в окно и при клике по нему в чате,
# а голый .tdesktop-palette — нет.
THEME_OUT = os.environ.get("TG_THEME_OUT", os.path.expanduser(
    "~/.cache/matugen/matugen.tdesktop-theme"))
# Плитка фона отдельно — на случай ручной установки в Настройках чатов.
TILE_OUT = os.environ.get("TG_TILE_OUT", os.path.expanduser(
    "~/.cache/matugen/telegram-tile.png"))

# Диапазон тонов, который в штатной палитре занимает фирменный синий Telegram.
BLUE_LO, BLUE_HI = 180.0, 260.0
NEUTRAL_SAT = 0.12          # ниже этого цвет считается серым
TINT_SAT = 0.10             # насыщенность, которую получает подкрашенный серый

LINE = re.compile(r"^([a-zA-Z][\w]*):\s*(#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?)\s*;(.*)$")


def hex_to_hls(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


def hls_to_hex(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in (r, g, b))


def mix(a, b, t):
    """Смешать два #rrggbb: t=0 -> a, t=1 -> b."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    f = lambda x: x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (f(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    l1, l2 = sorted((_lum(a), _lum(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def active_bg(surface, primary, fg):
    """Фон активных элементов: примесь акцента к фону окна.

    Долю нельзя зашить числом: на голубых обоях акцент светлый, и та же доля
    даёт фон, на котором светлый текст читается на 2.8:1 — замерено на
    wallhaven-3k37p6. Поэтому доля подбирается: берётся та, при которой текст
    даёт не меньше 4.5:1, а сам фон отделяется от окна не меньше чем на 3:1.
    Если оба условия несовместимы (очень светлый акцент), выигрывает
    читаемость текста.
    """
    best, best_score = None, -1.0
    for step in range(20, 66, 5):
        t = step / 100
        bg = mix(surface, primary, t)
        c_text, c_sep = contrast(fg, bg), contrast(bg, surface)
        if c_text >= 4.5 and c_sep >= 3.0:
            return bg
        score = min(c_text / 4.5, c_sep / 3.0)
        if c_text >= 4.5 and score > best_score:
            best, best_score = bg, score
    return best or mix(surface, primary, 0.35)


# Пары «текст / фон», за читаемость которых отвечаем явно. Пересчёт по тону
# сохраняет светлоту исходного цвета, но не контраст: у голубого акцента та же
# светлота воспринимается ярче, и белая цифра на значке непрочитанного давала
# 2.8:1 при штатных 4.1 (замерено на wallhaven-3k37p6). Поэтому после сборки
# фон таких пар при необходимости притемняется до нормы.
ENFORCE = [
    ("dialogsUnreadFg", "dialogsUnreadBg", 4.5),
    ("windowFgActive", "windowBgActive", 4.5),
    ("activeButtonFg", "activeButtonBg", 4.5),
    ("historyTextOutFg", "msgOutBg", 4.5),
    ("dialogsNameFgActive", "dialogsBgActive", 4.5),
]


def resolve(table, key, depth=0):
    v = table.get(key, "")
    while v and not v.startswith("#") and depth < 10:
        v = table.get(v, "")
        depth += 1
    return v


def darken_to(fg, bg, ratio):
    """Притемнить фон, пока текст на нём не станет читаемым."""
    h, l, s = hex_to_hls(bg[:7])
    for _ in range(50):
        cand = hls_to_hex(h, l, s)
        if contrast(fg, cand) >= ratio or l <= 0.02:
            return cand + (bg[7:] if len(bg) == 9 else "")
        l -= 0.02
    return bg


def load_roles():
    with open(PALETTE, encoding="utf-8") as f:
        p = json.load(f)
    return {k: v for k, v in p.items() if isinstance(v, str) and v.startswith("#")}


def recolor(value, accent_h, surface_h):
    """Перекрасить один литеральный цвет. Альфа сохраняется как есть."""
    alpha = value[7:] if len(value) == 9 else ""
    h, l, s = hex_to_hls(value[:7])
    if s < NEUTRAL_SAT:                       # серый каркас — подкрасить тоном обоев
        return hls_to_hex(surface_h, l, TINT_SAT if l > 0.02 else 0.0) + alpha
    deg = h * 360
    if BLUE_LO <= deg <= BLUE_HI:             # фирменный синий — увести к акценту
        return hls_to_hex(accent_h, l, s) + alpha
    return value                              # смысловой цвет — не трогать


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _solid_png(hex_color, size=64):
    """PNG size×size одного цвета, без внешних библиотек (zlib + struct)."""
    return _png([[_rgb(hex_color)] * size for _ in range(size)])


# Узор фона чата (08.10.2026, Просьба: «как у angelOS, только не сердечки, а то,
# что у меня» — искорка кнопки «Пуск», xpbar.Sparkle). Пиксели 1:1, без
# сглаживания; цвета — примесь акцента к фону, чтобы узор шёл фоном, а не
# спорил с сообщениями. Каждая метка: (x, y, вид); плитка повторяется.
TILE = 144
TILE_MARKS = [(36, 40, "spark"), (108, 112, "spark"),
              (100, 30, "plus"), (24, 104, "plus"), (66, 76, "plus"),
              (130, 66, "twinkle"), (58, 10, "twinkle"), (8, 70, "dot"),
              (84, 132, "dot"), (122, 12, "dot"), (46, 128, "twinkle")]


def _sparkle_tile(bg, acc, gain=1.0):
    """Плитка TILE×TILE: фон bg, искорки цветом acc (#rrggbb) разной силы.
    gain усиливает звёзды (обоям sparkle_wallpaper.py нужно ярче, чем чату)."""
    base = _rgb(bg)
    a = _rgb(acc)
    px = [[base] * TILE for _ in range(TILE)]

    def put(x, y, t):
        x, y = x % TILE, y % TILE                 # плитка бесшовная
        old = px[y][x]
        t = min(1.0, t * gain)
        px[y][x] = tuple(round(o + (c - o) * t) for o, c in zip(old, a))

    def rect(x, y, w, h, t):
        for j in range(h):
            for i in range(w):
                put(x + i, y + j, t)

    for cx, cy, kind in TILE_MARKS:
        if kind == "spark":                       # как Sparkle в xpbar.py
            rect(cx - 5, cy - 5, 11, 11, 0.06)    # свечение
            rect(cx - 7, cy - 2, 15, 5, 0.04)
            rect(cx - 2, cy - 7, 5, 15, 0.04)
            rect(cx, cy - 8, 1, 17, 0.30)         # лучи
            rect(cx - 8, cy, 17, 1, 0.30)
            rect(cx - 1, cy - 3, 3, 7, 0.38)
            rect(cx - 3, cy - 1, 7, 3, 0.38)
            rect(cx - 1, cy - 1, 3, 3, 0.55)      # ядро
            rect(cx - 8, cy - 8, 2, 2, 0.22)      # пара крошечных искр
            rect(cx + 7, cy + 7, 2, 2, 0.22)
        elif kind == "plus":                      # «+» 5×5
            rect(cx, cy - 2, 1, 5, 0.22)
            rect(cx - 2, cy, 5, 1, 0.22)
        elif kind == "twinkle":                   # крестик 3×3
            rect(cx, cy - 1, 1, 3, 0.18)
            rect(cx - 1, cy, 3, 1, 0.18)
        else:                                     # точка 2×2
            rect(cx, cy, 2, 2, 0.16)
    return px


def _png(px):
    """PNG из строк пикселей (r, g, b), без внешних библиотек (zlib + struct)."""
    import struct
    import zlib
    h, w = len(px), len(px[0])
    raw = b"".join(b"\x00" + bytes(c for p in row for c in p) for row in px)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def main():
    try:
        roles = load_roles()
        base = open(BASE, encoding="utf-8").read()
    except OSError as e:
        print("telegram_colors: %s" % e, file=sys.stderr)
        return 1

    accent_h = hex_to_hls(roles["primary"])[0]
    surface_h = hex_to_hls(roles["surface"])[0]

    # Ключи, которые видно всегда — их берём прямо из ролей, без пересчёта.
    #
    # Список НАМЕРЕННО короткий. Всё, что в штатной палитре было приглушённым
    # синим (фон своих сообщений #2b5278, активный чат в списке, значок
    # непрочитанного), сюда не входит: подстановка яркой роли primary делала
    # эти места кричащими, а текст на них — нечитаемым (замерено: свой текст
    # на своём пузыре давал контраст 2.6:1 при норме 4.5). Пересчёт по тону
    # сохраняет исходную светлоту, то есть и приглушённость, и контраст.
    direct = {
        "windowBg": roles["surface"],
        "windowFg": roles["on_surface"],
        "windowBgOver": roles["surface_container"],
        "windowBgRipple": roles["surface_high"],
        "windowSubTextFg": roles["on_surface_variant"],
        "windowBoldFg": roles["on_surface"],
        # НЕ чистый primary. Этот цвет служит фоном и ярким кнопкам, и
        # тексту на тёмном активном чате: в штатной палитре он средней
        # светлоты (#5288c1), и белый текст читался и там, и там. Светлая
        # роль primary ломала второй случай — тёмный on_primary на тёмном
        # фоне активного чата давал 1.5:1. Доля 0.45 подобрана замером:
        # светлый текст на нём 4.6:1 (норма 4.5), а сам он отделяется от
        # фона окна на 3.1:1 (норма для элементов интерфейса — 3).
        "windowBgActive": active_bg(roles["surface"], roles["primary"], roles["on_surface"]),
        "windowFgActive": roles["on_surface"],
        "windowActiveTextFg": roles["primary"],
        "titleBg": roles["surface_lowest"],
        "titleBgActive": roles["surface_lowest"],
        "dialogsBg": roles["surface"],
        "dialogsBgOver": roles["surface_container"],
        "menuBg": roles["surface_container"],
        "activeButtonBg": active_bg(roles["surface"], roles["primary"], roles["on_surface"]),
        "activeButtonFg": roles["on_surface"],
        "sideBarBg": roles["surface_lowest"],
    }

    out, changed = [], 0
    for line in base.split("\n"):
        m = LINE.match(line)
        if not m:
            out.append(line)
            continue
        key, value, tail = m.group(1), m.group(2), m.group(3)
        # Аватарки-заглушки (буквы на цветном круге) не перекрашиваем: их
        # восемь палитровых цветов — смысловые, как красный/зелёный. Синие и
        # голубые из них уезжали в акцент, и на жёлтых обоях аватарка
        # сливалась с фоном уведомления (замечено пользователем 22.09.2026).
        if key.startswith("historyPeer") and ("Userpic" in key or "NameFg" in key):
            out.append(line)
            continue
        new = direct.get(key) or recolor(value, accent_h, surface_h)
        if new.lower() != value.lower():
            changed += 1
        out.append("%s: %s;%s" % (key, new, tail))

    # Проверка и правка пар из ENFORCE — по готовой таблице, чтобы видеть
    # значения после всех подстановок, включая ссылочные ключи.
    table = {}
    for line in out:
        m = LINE.match(line)
        if m:
            table[m.group(1)] = m.group(2)
        else:
            m2 = re.match(r"^([a-zA-Z][\w]*):\s*([a-zA-Z][\w]*)\s*;", line)
            if m2:
                table[m2.group(1)] = m2.group(2)
    fixed = 0
    for fg_key, bg_key, ratio in ENFORCE:
        fg, bg = resolve(table, fg_key), resolve(table, bg_key)
        if not fg or not bg or contrast(fg, bg[:7]) >= ratio:
            continue
        new = darken_to(fg, bg, ratio)
        table[bg_key] = new
        for i, line in enumerate(out):
            m = LINE.match(line)
            if m and m.group(1) == bg_key:
                out[i] = "%s: %s;%s" % (bg_key, new, m.group(3))
                fixed += 1
                break

    content = "\n".join(out)
    open(OUT, "w", encoding="utf-8").write(content)
    # Фон чата — tiled.png одного цвета, из роли surface_container. Две
    # причины (22.09.2026):
    #  * так фон следует за палитрой, как и просил пользователь;
    #  * без картинки в архиве клиент при каждом обращении к теме пишет
    #    «could not locate 'background.jpg' in a zip file», и ровно в эти
    #    секунды в журнале появлялось «corrupted double-linked list»; в 19:15
    #    Telegram 7.2.8 упал с SIGSEGV в отрисовке (после drag-and-drop фото).
    #    Связь не доказана, но файл без фона — единственное отклонение от
    #    формата, и убрать его дешевле, чем гадать.
    # Самый тёмный из ролей — surface: пользователь просил фон потемнее, чтобы
    # акцент на его фоне читался (22.09.2026). Файл — background.png, а не
    # tiled.png: с tiled.png клиент показал штатный светлый узор, то есть
    # плитку не взял; background.png — основной путь формата.
    #
    # 08.10.2026: пробовали узор искорок файлом tiled.png — клиент опять его
    # не взял (как 22.09), фон слетел на штатный. Поэтому по умолчанию снова
    # одноцветный background.png; узор — только TG_TILE=sparkle (и копия
    # плитки в TILE_OUT для ручной установки «Мозаикой»).
    bg = roles.get("surface") or roles.get("surface_container") or "#141414"
    if os.environ.get("TG_TILE") != "sparkle":
        name, tile = "background.png", _solid_png(bg, size=512)
    else:
        name, tile = "tiled.png", _png(_sparkle_tile(bg, roles["primary"]))
        with open(TILE_OUT + ".tmp", "wb") as f:
            f.write(tile)
        os.replace(TILE_OUT + ".tmp", TILE_OUT)
    tmp = THEME_OUT + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("colors.tdesktop-theme", content)
        z.writestr(name, tile)
    os.replace(tmp, THEME_OUT)
    if fixed:
        print("telegram_colors: контраст поправлен у %d пар" % fixed)
    print("telegram_colors: перекрашено %d цветов из %d, акцент %s"
          % (changed, len(LINE.findall(base)) if False else
             sum(1 for l in base.split("\n") if LINE.match(l)), roles["primary"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
