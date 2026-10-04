#!/usr/bin/env python3
"""Собрать шрифт значков для столов в баре: ВСЕ значки в одной рамке. 21.09.2026.

Зачем. Значки столов взяты из разных шрифтов: Font Awesome, Material Design,
Devicons (все три внутри Nerd Font), лев Brave из Symbola, волк и Zen из своих
шрифтов. У каждого семейства свои поля внутри ячейки и свой размер рисунка, и
выровнять их стилями нельзя: поправка, ровняющая один значок, уводит другой
(замер 21.09.2026: звёздочке нужно было +1,5 px, значку терминала −2,5 px).
Вариант «Mono» ровняет, но вписывает значок в одну ячейку, то есть мельчит.

Решение то же, что у build_wolf_font.py, только для всех разом: каждый значок
переносится в ОДИН шрифт и при переносе приводится к единому стандарту.

    Стандарт:
      • большая сторона рисунка  = ровно 1 em;
      • центр рисунка            = центр ячейки, по обеим осям;
      • высота строки            = ровно 1 em (ascent 900, descent −100).

Отсюда главное удобство: font-size в стилях — это БУКВАЛЬНО размер значка
в пикселях. 26px → значок 26 px по большей стороне, строка 26 px, и стоит он
по центру кнопки по построению, без подгоночных отступов.

Шрифт отвечает на ТЕ ЖЕ коды, что записаны в window-rewrite конфига waybar,
поэтому конфиг править не нужно: достаточно поставить это семейство первым
в font-family. Чего в шрифте нет — возьмётся из следующих по списку, как раньше.

Кроме значков внутри:
  • луковица Tor Browser на U+E105 — нарисована по пропорциям логотипа;
  • цифры 0–9 — их показывает пустой стол. Приведены к той же строке, иначе
    кнопка с цифрой была бы другой высоты, и бар дёргался бы при переходе;
  • U+200B (пробел нулевой ширины) — им niri_bar.py метит свои имена столов.
    Без него Pango взял бы этот символ из другого шрифта, и высоту строки
    задал бы уже тот шрифт, а не этот.

Запуск: без аргументов. Добавили правило в window-rewrite — запустить ещё раз
(waybar_niri.py делает это сам, если конфиг новее шрифта).
"""
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_wolf_font import parse_paths, trace  # noqa: E402  тот же путь PNG → контуры

HOME = os.path.expanduser("~")
WAYBAR_CONFIG = HOME + "/.config/waybar/config.jsonc"
OUT = HOME + "/.local/share/fonts/JarvisBarIcons-Regular.otf"
FAMILY = "JarvisBarIcons"

# Порядок тот же, что был в font-family у кнопок столов: каждый код находится
# в том же шрифте, что и раньше, и рисунок остаётся тем, к которому привыкли.
SOURCES = [
    HOME + "/.local/share/fonts/WolfGlyph-Regular.otf",
    HOME + "/.local/share/fonts/ZenGlyph-Regular.otf",
    "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf",
    "/usr/share/fonts/TTF/Symbola.ttf",
]
DIGITS_FROM = "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf"

YM_PNG = "/usr/share/icons/hicolor/256x256/apps/yandexmusic.png"
YM_CODE = 0xE103            # тоже свободен; звезда-вспышка Яндекс Музыки
CODE_CODE = 0xE104          # свободен; «</>» для окон Neovim, рисуется здесь же
TOR_CODE = 0xE105           # свободен; луковица Tor Browser, рисуется здесь же (28.09.2026)

# Свой код → символ, с которого снимается рисунок. Нужен льву Brave: U+1F981 для
# Pango — эмодзи, и он берёт его из цветного Noto Color Emoji, НЕ заглядывая в
# font-family (замер 21.09.2026: шрифт «Noto Color Emoji», ячейка 32x32 вместо
# 26x27). У кода из частной зоны такого свойства нет, и лев рисуется отсюда —
# одноцветный, из Symbola, в общей рамке.
ALIASES = {0xE103: 0x1F981}

# Значки не из window-rewrite, которым тоже нужна общая рамка.
#   U+F08C7 (md-arch) — логотип Arch в кнопке запуска слева. Своим шрифтом он
#   рисовался 12x12 при кегле 15 и стоял не по центру: в style.css под него были
#   подобраны неравные боковые отступы (12 px против 8). В общей рамке он встаёт
#   сам, а кегль равен размеру рисунка.
EXTRA = [0xF08C7, 0xF0437]   # 0xF0437 — радар, имя стола дашборда в niri (24.09.2026)

# Растяжение по ширине (центр на месте). Кристалл Obsidian узкий и высокий: при
# общем стандарте он выходил 13 px в ширину против 17 у соседей, и просвет справа
# от «</>» был на 2 px шире, чем слева (28.09.2026). ×1.15 — ~15 px, разница 1 px,
# форма почти прежняя. Откат — убрать строку и пересобрать; прежний шрифт лежит в
# ~/.cache/JarvisBarIcons-before-widen-2026-09-28.otf.
WIDEN = {0xE6BB: 1.15}

UPM = 1000
ASCENT, DESCENT = 900, -100
ADV = 1000                  # ячейка значка — квадрат 1 em
BOX = 1000                  # большая сторона рисунка
CX, CY = ADV / 2, (ASCENT + DESCENT) / 2
DIGIT_H = 640               # высота цифры: рядом со значком 26 px это ~17 px
DIGIT_ADV = 620


def wanted_codes():
    """Все символы из window-rewrite и window-rewrite-default конфига waybar."""
    raw = open(WAYBAR_CONFIG, encoding="utf-8").read()
    cfg = json.loads(re.sub(r"^\s*//.*$", "", raw, flags=re.M))
    ws = cfg.get("hyprland/workspaces") or cfg.get("niri/workspaces") or {}
    text = "".join((ws.get("window-rewrite") or {}).values())
    text += ws.get("window-rewrite-default", "")
    codes = {ord(c) for c in text if not c.isspace() and ord(c) > 0x7F}
    return sorted(codes | set(EXTRA))


def record(font, code):
    """Контур символа из шрифта, составные глифы разобраны. None — символа нет."""
    name = font.getBestCmap().get(code)
    if name is None:
        return None
    gs = font.getGlyphSet()
    rec = DecomposingRecordingPen(gs)
    gs[name].draw(rec)
    return rec


def bounds(rec):
    bp = BoundsPen(None)
    rec.replay(bp)
    return bp.bounds


def code_outline():
    """«</>» для окон Neovim — нарисован здесь, а не взят из шрифта (25.09.2026).

    пользователь прислал образцы: круглые толстые штрихи, скобки ниже косой, весь
    знак чуть наклонён вправо, между частями заметный зазор. Готовые «</>»
    из Nerd Font (U+F05C0 и соседи) тонкие и прямые. Рисуем на холсте 1024,
    трассируем тем же путём, что логотипы; центровку и размер в ячейке
    дальше приводит общий стандарт (to_standard) — как у всех значков.
    """
    import math
    from PIL import ImageDraw
    S = 1024
    im = Image.new("L", (S, S), 255)
    d = ImageDraw.Draw(im)
    k = S * 0.58                          # пикселей на единицу (высота косой = 1)
    cx = cy = S / 2
    w = 0.14 * k                          # толщина штриха
    t = math.tan(math.radians(8.0))       # наклон вправо: верх уходит вправо

    def P(x, y):
        return (cx + (x - y * t) * k, cy + y * k)

    def stroke(pts):
        pts = [P(*p) for p in pts]
        d.line(pts, fill=0, width=int(w), joint="curve")
        r = w / 2
        for x, y in (pts[0], pts[-1]):    # круглые концы
            d.ellipse([x - r, y - r, x + r, y + r], fill=0)

    stroke([(0.15, -0.5), (-0.15, 0.5)])  # косая, высота 1
    h, arm, tip = 0.25, 0.19, 0.59        # скобки: полувысота, вылет, край (+зазор)
    stroke([(-tip + arm, -h), (-tip, 0.0), (-tip + arm, h)])
    stroke([(tip - arm, -h), (tip, 0.0), (tip - arm, h)])

    with tempfile.TemporaryDirectory() as tmp:
        pbm = os.path.join(tmp, "m.pbm")
        im.convert("1").save(pbm)
        contours = parse_paths(trace(pbm))
    rec = RecordingPen()
    for c in contours:
        started = False
        for kind, val in c:
            if kind == "move":
                if started:
                    rec.closePath()
                rec.moveTo(val)
                started = True
            elif kind == "line":
                rec.lineTo(val)
            elif kind == "curve":
                rec.curveTo(*val)
        if started:
            rec.closePath()
    return rec


def tor_outline():
    """Логотип Tor: круг, левая половина сплошная, справа — точка и дуги вокруг неё.

    Снимать с иконки пакета (default128.png) нельзя: она вся в оттенках фиолетового,
    и порог по цвету рвёт дуги. Рисуем по пропорциям логотипа, но полосы шире — при
    значке ~17 px в баре настоящие дуги в пиксель толщиной слипаются. 28.09.2026.
    """
    n = 1024
    c, R = n / 2, n / 2 - 8
    bmp = Image.new("L", (n, n), 255)
    d = ImageDraw.Draw(bmp)
    circle = lambda r, fill: d.ellipse((c - r, c - r, c + r, c + r), fill=fill)
    # от внешнего к внутреннему: ободок, щель, дуга, щель, точка (доли радиуса)
    for r, fill in ((1.0, 0), (0.82, 255), (0.64, 0), (0.46, 255), (0.28, 0)):
        circle(r * R, fill)
    d.pieslice((c - R, c - R, c + R, c + R), 90, 270, fill=0)   # левая половина
    with tempfile.TemporaryDirectory() as tmp:
        pbm = os.path.join(tmp, "m.pbm")
        bmp.convert("1").save(pbm)
        return contours_to_rec(parse_paths(trace(pbm)))


def contours_to_rec(contours):
    """Контуры potrace (parse_paths) → RecordingPen."""
    rec = RecordingPen()
    for c in contours:
        started = False
        for kind, val in c:
            if kind == "move":
                if started:
                    rec.closePath()
                rec.moveTo(val)
                started = True
            elif kind == "line":
                rec.lineTo(val)
            else:
                rec.curveTo(*val)
        if started:
            rec.closePath()
    return rec


def ym_outline():
    """Логотип Яндекс Музыки: жёлтая звезда-вспышка на чёрной подложке.

    В Nerd Font её нет, а обычная звезда (U+F005) на логотип не похожа —
    пользователь сравнил со значком приложения и попросил такую же (25.09.2026).
    """
    src = Image.open(YM_PNG).convert("RGBA")
    w, h = src.size
    bmp = Image.new("L", (w, h), 255)
    sp, bp = src.load(), bmp.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = sp[x, y]
            # подложка чёрная, вспышка жёлтая: красного и зелёного много, синего мало
            if a > 200 and r > 150 and g > 120 and b < 130:
                bp[x, y] = 0
    with tempfile.TemporaryDirectory() as tmp:
        pbm = os.path.join(tmp, "m.pbm")
        bmp.save(pbm)
        contours = parse_paths(trace(pbm))
    rec = RecordingPen()
    for c in contours:
        started = False
        for kind, val in c:
            if kind == "move":
                if started:
                    rec.closePath()
                rec.moveTo(val)
                started = True
            elif kind == "line":
                rec.lineTo(val)
            elif kind == "curve":
                rec.curveTo(*val)
        if started:
            rec.closePath()
    return rec



def widen(rec, f):
    """Растянуть рисунок по ширине в f раз, центр на месте (см. WIDEN)."""
    x0, _, x1, _ = bounds(rec)
    cx = (x0 + x1) / 2
    out = RecordingPen()
    rec.replay(TransformPen(out, (f, 0, 0, 1, cx - f * cx, 0)))
    return out


def place(rec, scale, dx, dy, adv):
    """Перенести контур в шрифт с преобразованием. Вернёт (charstring, lsb)."""
    pen = T2CharStringPen(adv, None)
    rec.replay(TransformPen(pen, (scale, 0, 0, scale, dx, dy)))
    bp = BoundsPen(None)
    rec.replay(TransformPen(bp, (scale, 0, 0, scale, dx, dy)))
    return pen.getCharString(), round(bp.bounds[0]) if bp.bounds else 0


def to_standard(rec):
    """Стандарт: большая сторона = BOX, центр рисунка = центр ячейки."""
    x0, y0, x1, y1 = bounds(rec)
    scale = BOX / max(x1 - x0, y1 - y0)
    dx = CX - (x0 + x1) / 2 * scale
    dy = CY - (y0 + y1) / 2 * scale
    return place(rec, scale, dx, dy, ADV)


def main():
    fonts = [TTFont(p) for p in SOURCES if os.path.exists(p)]
    glyphs, metrics, cmap, missing = {}, {}, {}, []

    empty = T2CharStringPen(ADV, None)
    glyphs[".notdef"], metrics[".notdef"] = empty.getCharString(), (ADV, 0)

    for code in wanted_codes():
        if code in (YM_CODE, CODE_CODE, TOR_CODE):   # их нет ни в одном шрифте — рисуются/снимаются ниже
            continue
        src = ALIASES.get(code, code)
        rec = next((r for r in (record(f, src) for f in fonts) if r and bounds(r)), None)
        if rec is None:
            missing.append(code)
            continue
        name = "u%04X" % code
        if code in WIDEN:
            rec = widen(rec, WIDEN[code])
        glyphs[name], lsb = to_standard(rec)
        metrics[name], cmap[code] = (ADV, lsb), name

    if CODE_CODE in wanted_codes():
        name = "u%04X" % CODE_CODE
        glyphs[name], lsb = to_standard(code_outline())
        metrics[name], cmap[CODE_CODE] = (ADV, lsb), name

    if TOR_CODE in wanted_codes():
        name = "u%04X" % TOR_CODE
        glyphs[name], lsb = to_standard(tor_outline())
        metrics[name], cmap[TOR_CODE] = (ADV, lsb), name

    if YM_CODE in wanted_codes() and os.path.isfile(YM_PNG):
        name = "u%04X" % YM_CODE
        glyphs[name], lsb = to_standard(ym_outline())
        metrics[name], cmap[YM_CODE] = (ADV, lsb), name

    # Цифры: один масштаб и одна базовая линия на все десять (меряем по нулю),
    # а по горизонтали каждая ставится по центру собственного рисунка —
    # иначе единица стояла бы в кнопке левее середины.
    dfont = TTFont(DIGITS_FROM)
    zx0, zy0, zx1, zy1 = bounds(record(dfont, ord("0")))
    dscale = DIGIT_H / (zy1 - zy0)
    ddy = CY - (zy0 + zy1) / 2 * dscale
    for ch in "0123456789":
        rec = record(dfont, ord(ch))
        x0, _, x1, _ = bounds(rec)
        name = "digit%s" % ch
        glyphs[name], lsb = place(rec, dscale, DIGIT_ADV / 2 - (x0 + x1) / 2 * dscale, ddy, DIGIT_ADV)
        metrics[name], cmap[ord(ch)] = (DIGIT_ADV, lsb), name

    zw = T2CharStringPen(0, None)
    glyphs["zwsp"], metrics["zwsp"], cmap[0x200B] = zw.getCharString(), (0, 0), "zwsp"

    order = [".notdef"] + sorted(n for n in glyphs if n != ".notdef")
    fb = FontBuilder(UPM, isTTF=False)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupCFF(FAMILY + "-Regular", {"FullName": FAMILY, "FamilyName": FAMILY}, glyphs, {})
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    fb.setupNameTable({"familyName": FAMILY, "styleName": "Regular", "psName": FAMILY + "-Regular"})
    fb.setupOS2(sTypoAscender=ASCENT, sTypoDescender=DESCENT, sTypoLineGap=0,
                usWinAscent=ASCENT, usWinDescent=-DESCENT)
    fb.setupPost()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # Новый файл и подмена, а не запись поверх: шрифт держат открытым waybar и
    # другие, и перезапись на месте роняет их (SIGBUS — так упал Telegram 23.09).
    tmp = OUT + ".tmp"
    fb.save(tmp)
    os.replace(tmp, OUT)
    subprocess.run(["fc-cache", "-f", os.path.dirname(OUT)], capture_output=True)

    print("шрифт: %s" % OUT)
    print("значков: %d; плюс цифры и U+200B" % (len(cmap) - 11))
    if missing:
        print("НЕ НАЙДЕНЫ ни в одном источнике: " + " ".join("U+%04X" % c for c in missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
