#!/usr/bin/env python3
"""Чтение экранного текста точным совпадением с растрами шрифта PxPlus.

    pxocr.py снимок.png            -> текст в stdout, оценка в stderr; код 1 — не уверен

Зачем. Системный шрифт рабочего стола — PxPlus HP 100LX 6x8, растровый: буква
занимает сетку 6x8 точек. GTK/Qt/kitty рисуют его без сглаживания на целой
сетке (проверено 23.09.2026: подпись GTK в 12 pt — 2 уровня серого, клетка
12x16 px), браузер — на дробной (14 px = 1.75 точки на точку шрифта, 28 px =
3.5) и со сглаженными краями. Обычные распознаватели на таком шрифте гадают
(tesseract 87 %, RapidOCR 80 %: у «y» и «u» нет различающих пикселей для
модели, обученной на печатных шрифтах). А угадывать незачем: достаточно
сравнить каждую клетку с растрами самого шрифта — они извлекаются из того же
TTF (Pillow при 8 px даёт их точь-в-точь).

Как. Снимок бинаризуется (порог Оцу, текст — меньшинство; серая степень
закраски между фоном и текстом сохраняется), строки ищутся по горизонтальной
проекции. Масштаб s (пикселей на точку шрифта) и сдвиг сетки по x находит
разведка по профилю чернил столбцов опорной строки: первый столбец каждой
клетки в этом шрифте пуст, и при верных s и dx на эти столбцы приходится
почти ноль чернил. Вертикаль — отдельно: хинтинг прижимает к пикселям высоту
заглавных (7 строк) и строчных (5) независимо, поэтому перебираются пять
«зон». Точка шрифта горит при закраске ≥ 50 % её площади (интегральное
изображение), верхний ряд тянется на полстроки вверх за точками «i» и
крышечками «й». Клетки 6x8 сравниваются с шаблонами расстоянием Хэмминга
(48 бит, np.bitwise_count); ряды-обрывки в оценку не входят. Верим, если
средняя ошибка ≤ MAX_BITS и сошедшиеся клетки объясняют ≥ MIN_SHARE чернил;
иначе код 1, и ocr_copy.sh идёт к tesseract. Замер 23.09.2026: GTK 99.4 %,
Zen 12–28 px — 92–100 %, 11 px и чужие шрифты — отказ.

Одинаковые растры («a» латинская и «а» русская, «c»/«с», «p»/«р»…)
различаются по слову: какой письменности в слове больше однозначных букв,
та и берётся для двусмысленных; слово без однозначных — латиница. «—» и «-»
в этом шрифте один растр — читается дефис.
"""
import os
import sys
import time
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = os.path.expanduser("~/.local/share/fonts/PxPlus_HP_100LX_6x8.ttf")
CW, CH = 6, 8                    # клетка шрифта в точках
MAX_BITS = 1.05                  # средняя ошибка на непустую клетку, чтобы поверить:
                                 # свой шрифт даёт 0.00–0.35 (GTK, Zen 12–28 px), при 15 px с
                                 # хинтингом — 1.02 при 92 % верного текста; чужой сглаженный
                                 # растр (ImageMagick) — 1.12 при 72 % — уже за порогом
SURE_BITS = 0.3                  # с такой ошибкой масштаб точно верный — дальше не ищем
MIN_CELLS = 2                    # меньше непустых клеток — не о чем говорить
MIN_SHARE = 0.6                  # доля чернил в сошедшихся клетках, чтобы поверить (свой шрифт 80–100 %)
TIME_BUDGET = 2.5                # секунд на весь перебор; дольше — отказ
STEP = 1 / 8                     # шаг масштаба: размеры в px кратны 1/8 точки
CYR = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
LAT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
COMMON = LAT | CYR | set(" 0123456789.,:;!?-+=/\\()[]{}<>'\"@#$%^&*_~`|№«»…–—°€₽₸")
WEIGHTS = (np.uint64(1) << np.arange(CH * CW, dtype=np.uint64))


def pack(bits):
    """N x 48 bool → N uint64: сравнение клеток идёт одним XOR и подсчётом битов."""
    return (bits.astype(np.uint64) * WEIGHTS).sum(axis=1, dtype=np.uint64)


def templates():
    """(массив T uint64, список вариантов символа для каждого шаблона)."""
    font = ImageFont.truetype(FONT, CH)
    from fontTools.ttLib import TTFont
    cmap = TTFont(FONT).getBestCmap()
    groups = {}
    for cp in sorted(cmap):
        if cp < 32 or (unicodedata.category(chr(cp))[0] in "CZ" and cp != 32):
            continue
        ch = chr(cp)
        img = Image.new("1", (CW, CH), 0)
        ImageDraw.Draw(img).text((0, 0), ch, font=font, fill=1)
        bits = np.array(img, dtype=bool).reshape(-1)
        if not bits.any() and cp != 32:
            continue
        groups.setdefault(bits.tobytes(), []).append(ch)
    keys = list(groups)
    arr = np.array([np.frombuffer(k, dtype=bool) for k in keys])
    chars = [groups[k] for k in keys]
    # Редкие символы (ı без точки, надстрочные, значки) стоят на бит дороже:
    # иначе «i» с потерянной точкой читалась как «ı» — точное совпадение, но
    # не то, что на экране (Zen 22 px, 23.09.2026).
    penalty = np.array([0 if any(c in COMMON for c in cs) else 1 for cs in chars], dtype=np.uint8)
    # Краевые шаблоны: чернила только в двух верхних или двух нижних строках
    # клетки (¯ ˙ ¨ ˘ сверху, _ ¸ снизу). Ряд из них — не текст, а верхушки
    # или хвосты соседней строки, попавшие в свой ряд клеток («‾‾‾» над
    # словами в Zen, 23.09.2026).
    rows_ink = arr.reshape(-1, CH, CW).any(axis=2)
    marginal = np.array([bool(r.any()) and (not r[2:].any() or not r[:6].any()) for r in rows_ink])
    return pack(arr), chars, penalty, marginal


def binarize(img):
    """(bool-массив «чернила», степень закраски 0..1): порог Оцу, текст — меньшинство.

    Степень закраски — серый между уровнем фона и уровнем текста: у
    сглаженного края пиксель закрашен наполовину, и считать его целиком
    чернилами или целиком фоном — терять информацию, которой при дробном
    масштабе как раз не хватает (14 px в Zen, 23.09.2026).
    """
    g = np.asarray(img.convert("L"), dtype=np.float64)
    hist, _ = np.histogram(g, bins=256, range=(0, 256))
    p = hist / hist.sum()
    w0 = np.cumsum(p)
    m = np.cumsum(p * np.arange(256))
    mt = m[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        var = (mt * w0 - m) ** 2 / (w0 * (1 - w0))
    t = int(np.nanargmax(var))
    ink = g > t
    if ink.mean() > 0.5:
        ink = ~ink
        g = 255 - g
    if not ink.any():
        return ink, np.zeros_like(g)
    bg, fg = np.median(g[~ink]) if (~ink).any() else 0.0, np.median(g[ink])
    level = np.clip((g - bg) / max(fg - bg, 1.0), 0.0, 1.0)
    return ink, level


def bands(ink):
    """Полосы строк [(верх, низ)) по горизонтальной проекции.

    Склеенные строки (выносной элемент упёрся в следующую) не режем: полоса
    выше клетки читается как несколько рядов сетки в read_band.
    """
    rows = ink.any(axis=1)
    out, start = [], None
    for y, v in enumerate(rows):
        if v and start is None:
            start = y
        elif not v and start is not None:
            out.append((start, y))
            start = None
    if start is not None:
        out.append((start, len(rows)))
    return out


def integral(level):
    """Интегральное изображение закраски: сумма в любом прямоугольнике за O(1)."""
    I = np.zeros((level.shape[0] + 1, level.shape[1] + 1), dtype=np.float64)
    I[1:, 1:] = np.cumsum(np.cumsum(level, axis=0), axis=1)
    return I


def edges(origin, n, s, limit):
    """Границы n точек шрифта от origin: край каждой прижат к пикселю, как у
    FreeType с хинтингом — при 1.75 px на точку штрихи идут 2, 1, 2, 1."""
    e = np.floor(origin + np.arange(n + 1) * s + 0.5).astype(int)
    return np.clip(e, 0, limit)


def cells_of(I, sx, zone, x0, y0, nrows, ncols, extra=0):
    """Клетки (nrows*ncols) uint64: точка шрифта горит, если закрашено ≥ 50 % её.

    Начало каждой клетки — целый пиксель (round(x0 + i*6s)): рендерер ставит
    глиф на целый пиксель, и при дробном масштабе соседние буквы стоят со
    сдвигом в полпикселя друг относительно друга (замер 23.09.2026: шаг 11,
    10, 11, 10 при номинальных 10.5). Внутри клетки края точек тоже целые.
    Масштабы по осям разные: хинтинг FreeType растягивает буквы по вертикали
    до целых пикселей (при 14 px семь строк шрифта — 13 px, а не 12.25), а
    по горизонтали оставляет как есть (растр «File» при 14 px, 23.09.2026).
    """
    H, W = I.shape[0] - 1, I.shape[1] - 1
    cw, ch = CW * sx + extra, zone[0] + zone[2]
    # Клетка шириной 6 точек + разрядка (letter-spacing виджетов): точки
    # глифа занимают первые 6·sx пикселей клетки, остаток — воздух.
    xa, xb = [], []
    for i in range(ncols):
        e = edges(np.floor(x0 + i * cw + 0.5), CW, sx, W)
        xa.append(e[:-1])
        xb.append(e[1:])
    xa, xb = np.concatenate(xa), np.concatenate(xb)
    ys = np.concatenate([np.clip(row_edges(y0 + r * ch, zone), 0, H)[:-1] for r in range(nrows)]
                        + [np.array([np.clip(int(np.floor(y0 + nrows * ch + 0.5)), 0, H)])])
    ya, yb = ys[:-1].copy(), ys[1:]
    # Самый верхний ряд точек тянется на полстроки вверх: хинтинг выталкивает
    # точку «i» и крышечку «й» выше клетки, и без этого они терялись
    # («Fıle», «Фаил» — Zen, 23.09.2026). Площадь при этом считается по
    # штатной высоте, чтобы захваченная точка зажигала ряд, а не гасила.
    ya[0] = max(0, int(ya[0] - np.floor(zone[0] / 14 + 0.5)))
    S = I[yb][:, xb] - I[ya][:, xb] - I[yb][:, xa] + I[ya][:, xa]
    area = (yb - ya)[:, None] * (xb - xa)[None, :]
    area[0, :] = (yb[0] - ys[0]) * (xb - xa)
    grid = (2 * S >= area) & (area > 0)
    cells = grid.reshape(nrows, CH, ncols, CW).transpose(0, 2, 1, 3).reshape(nrows * ncols, CH * CW)
    inkcells = S.reshape(nrows, CH, ncols, CW).sum(axis=(1, 3)).reshape(nrows * ncols)
    return pack(cells), cells.any(axis=1), inkcells


def match(cells_u, tmpl_u, penalty=None):
    """(индекс лучшего шаблона, расстояние Хэмминга) для каждой клетки."""
    d = np.bitwise_count(cells_u[:, None] ^ tmpl_u[None, :])
    if penalty is not None:
        d = d + penalty[None, :]
    idx = d.argmin(axis=1)
    return idx, d[np.arange(len(cells_u)), idx]


def vertical_zones(s):
    """Кандидаты вертикали: (высота заглавных, высота строчных, нижний выносной).

    Автохинтер FreeType прижимает к пикселям ДВЕ линии отдельно — верх
    заглавных (7 строк шрифта) и верх строчных (5 строк), — и при 15 px (1.875
    на точку) заглавные становятся 13 или 14 px, а строчные 9 или 10, причём
    независимо; один общий вертикальный масштаб не попадал ни в те, ни в
    другие (ошибка 1.0 бита при верном масштабе, 23.09.2026). Первый кандидат —
    без прижатия, как в GTK и kitty.
    """
    out = [(7 * s, 5 * s, s)]
    for cap in (np.floor(7 * s), np.ceil(7 * s)):
        for xh in (np.floor(5 * s), np.ceil(5 * s)):
            z = (float(cap), float(xh), float(np.ceil(s)))
            if cap > xh and z not in out:
                out.append(z)
    return out


def row_edges(y0, zone):
    """9 границ строк шрифта от y0: 2 строки над строчными, 5 строчных, выносной."""
    cap, xh, desc = zone
    top = cap - xh
    e = [y0 + top * k / 2 for k in range(3)]
    e += [y0 + top + xh * k / 5 for k in range(1, 6)]
    e.append(y0 + cap + desc)
    return np.floor(np.array(e) + 0.5).astype(int)


def band_score(dist, nonempty):
    """Средняя ошибка полосы по хорошим рядам.

    Ряд из обрывков (крышечка «й», точки, вытолкнутые хинтингом выше клетки)
    даёт 5 бит и, попав в среднее, заставлял выбирать неверную вертикаль
    с «Докџмоит» вместо верной с чистым «Документ» (Zen 22 px, 23.09.2026).
    Если хоть один ряд читается, обрывки в оценку не входят.
    """
    good_e, good_c, all_e, all_c = 0.0, 0, 0.0, 0
    for row in range(dist.shape[0]):
        ne = nonempty[row]
        if not ne.any():
            continue
        e, c = float(dist[row][ne].sum()), int(ne.sum())
        all_e += e
        all_c += c
        if e / c <= MAX_BITS:
            good_e += e
            good_c += c
    if good_c:
        return good_e / good_c
    return all_e / all_c if all_c else float("inf")


def read_band(I, tmpl_u, s, y_top, y_bot, dx_fixed=None, zone=None, penalty=None, refine=True,
              step=None, extra=0):
    """Лучшая сетка для полосы строк: (ошибка, индексы, расстояния, непустые, dx).

    Сдвиг по x у всех строк одного окна общий, поэтому его ищут один раз на
    самой «чернильной» полосе и дальше передают dx_fixed — остальным полосам
    остаётся перебрать только сдвиги по y.
    """
    H, W = I.shape[0] - 1, I.shape[1] - 1
    zone = zone or (7 * s, 5 * s, s)
    cw, ch = CW * s + extra, zone[0] + zone[2]
    sy = ch / CH
    ncols = int(W / cw) + 1
    best = None

    def probe(dx, dy):
        nonlocal best
        y0 = y_top - dy
        nrows = max(1, int(np.ceil((y_bot - y0) / ch)))
        cells_u, nonempty, inkcells = cells_of(I, s, zone, -dx, y0, nrows, ncols, extra)
        if not nonempty.any():
            return
        idx, dist = match(cells_u, tmpl_u, penalty)
        score = band_score(dist.reshape(nrows, ncols), nonempty.reshape(nrows, ncols))
        if best is None or score < best[0]:
            best = (score, idx.reshape(nrows, ncols), dist.reshape(nrows, ncols),
                    nonempty.reshape(nrows, ncols), dx, dy, inkcells.reshape(nrows, ncols))

    # Сначала грубо, с шагом в полточки шрифта, потом точно вокруг лучшего:
    # при 3.5 px на точку полный перебор — 21 x 28 сеток на строку, а так
    # вчетверо меньше (28 px в Zen искался 2.6 с — 23.09.2026).
    step_x, step_y = max(1, int(s / 2)), max(1, int(sy / 2))
    if step:                               # грубая разведка масштаба — крупный шаг
        step_x = step_y = step
    dxs = range(0, int(np.ceil(cw)), step_x) if dx_fixed is None else (dx_fixed,)
    for dy in range(0, int(np.ceil(ch)), step_y):
        for dx in dxs:
            probe(dx, dy)
    if best is None or not refine:
        return (best[:5] + (best[6],)) if best else None
    cx, cy = best[4], best[5]
    for dy in range(max(0, cy - step_y + 1), min(int(np.ceil(ch)), cy + step_y)):
        for dx in ((cx,) if dx_fixed is not None else
                   range(max(0, cx - step_x + 1), min(int(np.ceil(cw)), cx + step_x))):
            if (dx, dy) != (cx, cy):
                probe(dx, dy)
    return best[:5] + (best[6],)


def choose(chars, script):
    """Из вариантов одного растра — символ нужной письменности."""
    for c in chars:
        if (script == "cyr" and c in CYR) or (script == "lat" and c in LAT):
            return c
    for c in chars:
        if ord(c) < 128:
            return c
    return chars[0]


def resolve(line_groups):
    """Список вариантов на клетку → строка; двусмысленные буквы по слову."""
    out, word = [], []

    def flush():
        cyr = sum(1 for g in word if len(g) == 1 and g[0] in CYR)
        lat = sum(1 for g in word if len(g) == 1 and g[0] in LAT)
        script = "cyr" if cyr > lat else "lat"
        out.extend(choose(g, script) for g in word)
        word.clear()

    for g in line_groups:
        if g == [" "]:
            flush()
            out.append(" ")
        else:
            word.append(g)
    flush()
    return "".join(out).rstrip()


def stroke_width(ink):
    """Оценка масштаба: самая частая длина горизонтального штриха чернил.

    В пиксельном шрифте большинство штрихов — в одну точку, то есть ровно s
    пикселей экрана (при дробном s — floor/ceil, оба рядом). Высота строки
    для оценки не годится: строки без просвета между ними (нижний выносной
    элемент упёрся в следующую) сливаются в одну полосу.
    """
    runs = []
    for row in ink:
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        runs.append(ends - starts)
    runs = np.concatenate(runs) if runs else np.array([], dtype=int)
    runs = runs[(runs >= 1) & (runs <= 40)]
    if runs.size == 0:
        return 2.0
    hist = np.bincount(runs)
    mode = int(hist.argmax())
    # При дробном масштабе штрих в одну точку рисуется то floor(s), то ceil(s)
    # пикселей (3 и 4 при 3.5): мода даёт крайнее, а среднее по этому
    # кластеру — сам масштаб. Без этого 28 px (3.5) искался восьмым и не
    # успевал в бюджет времени (23.09.2026).
    lo, hi = max(1, int(np.floor(0.6 * mode))), int(np.ceil(1.5 * mode))
    cluster = runs[(runs >= lo) & (runs <= hi)]
    return float(cluster.mean()) if cluster.size else float(mode)


def scale_candidates(ink):
    """Все масштабы 1..5 с шагом 1/8, ближайшие к оценке по штриху — первыми.

    Верный масштаб обычно в первой пятёрке, и перебор кончается по SURE_BITS;
    чужой шрифт перебирает всё, пока не выйдет TIME_BUDGET. (Автокорреляция
    профиля чернил как оценка шага пробована и отброшена: пик попадал на
    расстояние между штрихами, а не между буквами — 23.09.2026.)
    """
    est = stroke_width(ink)
    cands = [n * STEP for n in range(8, 41)]
    return sorted(cands, key=lambda s: abs(s - est))


def recognize(path):
    img = Image.open(path)
    ink, level = binarize(img)
    if not ink.any():
        return None, "пусто"
    tmpl_u, chars, penalty, marginal = templates()
    tmpl_ink = np.bitwise_count(tmpl_u).astype(np.float64)
    rows_all = bands(ink)
    # Строки разного цвета (яркий заголовок и тусклая подпись в виджете даты):
    # общий порог терял тусклую строку целиком — порог и уровни считаются
    # заново внутри каждой полосы.
    for (yt, yb) in rows_all:
        sub_ink, sub_level = binarize(img.crop((0, yt, img.width, yb)))
        ink[yt:yb], level[yt:yb] = sub_ink, sub_level
    I = integral(level)
    total_ink = float(level.sum()) or 1.0
    anchor = max(rows_all, key=lambda b: ink[b[0]:b[1]].sum())
    started = time.time()
    best = None
    # Разведка масштаба и сдвига по x — по профилю чернил столбцов опорной
    # строки: у каждой буквы этого шрифта первый столбец клетки пуст, и при
    # верных s и dx на эти столбцы приходится почти ноль чернил. Дёшево
    # (33 масштаба × ≤30 сдвигов × одно сложение), не зависит от вертикали и
    # хинтинга. Прежние оценки подводили: по ширине штриха — при 28 px с
    # хинтингом штрихи ровно 4 px; по грубой сетке — путала соседние масштабы
    # (23.09.2026).
    prof = level[anchor[0]:anchor[1]].sum(axis=0)
    cum = np.concatenate(([0.0], np.cumsum(prof)))
    total = cum[-1] or 1.0
    W = level.shape[1]
    # Разведка масштаба, разрядки и сдвига — по «воздуху» клетки: чернила в
    # первом столбце (пустом у всех букв) и в разрядке после 6-й точки. Ищется
    # для каждой полосы отдельно: разрядка (letter-spacing у виджетов eww —
    # «С Р Е Д А») у строк разная, а масштаб один. Узкая щель в один столбец
    # различала плохо: при разрядке пустого места много, и ложные шаги тоже
    # находили себе нули (23.09.2026).
    W = level.shape[1]
    cums = []
    for (yt, yb) in rows_all:
        prof = level[yt:yb].sum(axis=0)
        cums.append((np.concatenate(([0.0], np.cumsum(prof))), float(prof.sum()) or 1.0))
    scout = {}                              # s -> (оценка, [(extra, dx) по полосам])
    for c in scale_candidates(ink):
        gap = max(1, int(np.floor(c + 0.5)))
        glyph = int(np.floor(CW * c + 0.5))
        per_band, weighted, wsum = [], 0.0, 0.0
        for cum, tot in cums:
            top = None
            plain = None                    # лучший сдвиг без разрядки — вторая гипотеза
            for extra in range(0, int(3 * c) + 1):
                pitch = CW * c + extra
                ncols = int(W / pitch) + 1
                for dx in range(int(np.ceil(pitch))):
                    o = np.floor(-dx + np.arange(ncols + 1) * pitch + 0.5).astype(int)
                    o0, o1 = np.clip(o[:-1], 0, W), np.clip(o[1:], 0, W)
                    g0, g1 = np.clip(o[:-1] + gap, 0, W), np.clip(o[:-1] + glyph, 0, W)
                    air = (cum[g0] - cum[o0]).sum()
                    if extra:
                        air += (cum[o1] - cum[np.minimum(g1, o1)]).sum()
                    score = air / tot + 0.004 * extra
                    if top is None or score < top[0]:
                        top = (score, extra, dx)
                    if extra == 0 and (plain is None or score < plain[0]):
                        plain = (score, extra, dx)
            # Разведка по воздуху при хинтинге (шаг 9, 10, 9…) иногда предпочитает
            # ложную разрядку в пиксель; полный разбор проверяет обе гипотезы и
            # берёт ту, где меньше ошибка по клеткам (12 и 15 px, 23.09.2026).
            hyps = [(top[1], top[2])] + ([(plain[1], plain[2])] if plain[1:] != top[1:] else [])
            per_band.append(hyps)
            weighted += top[0] * tot
            wsum += tot
        # Третья гипотеза — сдвиг самой «чернильной» полосы: строки одного окна
        # выровнены по одной сетке, а у короткой или тусклой строки собственная
        # разведка ошибается (12 и 15 px в Zen, 23.09.2026).
        anchor_i = max(range(len(cums)), key=lambda i: cums[i][1])
        anchor_dx = per_band[anchor_i][0]
        for hyps in per_band:
            if (0, anchor_dx[1]) not in hyps:
                hyps.append((0, anchor_dx[1]))
        scout[c] = (weighted / wsum, per_band)
    order = sorted(scout, key=lambda c: scout[c][0])
    tried = 0
    for s in order:
        if time.time() - started > TIME_BUDGET:
            break
        # Разведка ставит верный масштаб первым; если среди первых трёх уже есть
        # приемлемый разбор, остальные тридцать не нужны (12 и 15 px тратили
        # весь бюджет на заведомо худшие масштабы — 23.09.2026).
        if tried >= 3 and best is not None and best[0] <= MAX_BITS and best[4] >= MIN_SHARE:
            break
        tried += 1
        per_band = scout[s][1]
        lines, errs, cnt, explained, used_extra = [], 0.0, 0, 0.0, []
        for (yt, yb), hyps in zip(rows_all, per_band):
            found = []
            for extra, dx in hyps:
                r = min((x for x in (read_band(I, tmpl_u, s, yt, yb, dx, zone, penalty, extra=extra)
                                     for zone in vertical_zones(s)) if x is not None),
                        key=lambda x: x[0], default=None)
                if r is not None:
                    found.append((r, extra))
            if not found:
                continue
            r, extra = min(found, key=lambda fe: fe[0][0])
            used_extra.append(extra)
            _, idx, dist, nonempty, _, inkcells = r
            zone_px = (yb - yt) / max(1, idx.shape[0]) / CH   # пикселей на строку шрифта
            got = []
            for row in range(idx.shape[0]):
                if not nonempty[row].any():
                    continue
                groups = [chars[i] if ne else [" "] for i, ne in zip(idx[row], nonempty[row])]
                dots = float(inkcells[row][nonempty[row]].mean()) / (s * s) if nonempty[row].any() else 0.0
                edge = float(marginal[idx[row]][nonempty[row]].mean()) if nonempty[row].any() else 0.0
                got.append((resolve(groups), float(dist[row][nonempty[row]].sum()),
                            int(nonempty[row].sum()), dots, edge))
                # чернила в клетках, которые сошлись с шаблоном (≤ 2 бита), —
                # «объяснённые»; их доля от всех чернил и есть честность разбора
                ok = nonempty[row] & (dist[row] <= 2)
                # Вклад клетки — не больше чернил её шаблона (с запасом 2: хинтинг
                # и сглаживание делают штрихи толще, при 28 px без запаса
                # объяснялось лишь 66 %):
                # иначе на большом масштабе одна клетка накрывала полслова,
                # усреднялась почти в пустоту, сходилась с точкой или пробелом
                # и «объясняла» всё разом (x5 при 15 px, 23.09.2026).
                cap = tmpl_ink[idx[row]] * (s * zone_px) * 2.0
                explained += float(np.minimum(inkcells[row], cap)[ok].sum())
            # Ряд из обрывков — крышечка «й» или точки, которые хинтинг вытолкнул
            # выше клетки, — читается мусором с ошибкой в 5 бит и тянет среднюю
            # вверх, хотя сама строка под ним читается с 0.06 (Zen, 23.09.2026).
            # Если в полосе есть хороший ряд, плохие отбрасываем.
            # Ряд из почти пустых клеток (< 3 точек шрифта в среднем) — обрывки
            # точек и крышечек: они «сходятся» с «_» и «¸» на 1 бит и проходили
            # как хорошие (12 px в Zen, 23.09.2026). При настоящем ряде рядом —
            # долой.
            solid = [g for g in got if g[3] >= 3.0 and g[4] < 0.5]
            if solid and len(solid) < len(got):
                got = solid
            good = [g for g in got if g[1] / g[2] <= MAX_BITS]
            # Тонкая полоса без единого хорошего ряда — это точки и крышечки,
            # ставшие своей полосой после порога по полосам; не текст (23.09.2026).
            if not good and (yb - yt) < 0.35 * max(b - a for a, b in rows_all):
                continue
            for text_row, e, c, _, _ in (good or got):
                lines.append(text_row)
                errs += e
                cnt += c
        if cnt == 0:
            continue
        avg = errs / cnt
        share = explained / total_ink
        # Разбор, объясняющий меньше половины чернил, в сравнение не допускается:
        # при 15 px масштаб x5 с пятью клетками и ошибкой 1.0 обгонял верный
        # x1.875 с ошибкой 1.02 на 45 клетках (23.09.2026).
        if share < 0.5:
            continue
        if best is None or avg < best[0]:
            best = (avg, s, cnt, lines, share, max(used_extra or [0]))
        if avg <= SURE_BITS:
            break
    if best is None:
        return None, "разбора нет (%.2f с)" % (time.time() - started)
    avg, s, cnt, lines, share, extra = best
    kept = [l for l in lines if l.strip()]
    indent = min((len(l) - len(l.lstrip(" ")) for l in kept), default=0)
    text = "\n".join(l[indent:] for l in kept)      # общий отступ — это место на экране, не текст
    # Доля объяснённых чернил — вторая проверка после ошибки: чужой шрифт может
    # набрать десяток случайно совпавших клеток при малой ошибке, но чернила
    # он не объясняет (Noto Sans: 11 клеток, 0.45 бита — 23.09.2026).
    note = "масштаб x%.3g%s, клеток %d, ошибка %.2f бит/клетку, объяснено %.0f%% чернил, %.2f с" % (
        s, " +%dpx" % extra if extra else "", cnt, avg, share * 100, time.time() - started)
    if os.environ.get("PXOCR_DEBUG"):
        print(text, file=sys.stderr)
    if avg > MAX_BITS or cnt < MIN_CELLS or share < MIN_SHARE or not text:
        return None, note
    return text, note


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    text, note = recognize(sys.argv[1])
    print(note, file=sys.stderr)
    if text is None:
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
