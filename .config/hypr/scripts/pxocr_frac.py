#!/usr/bin/env python3
"""Запасное чтение PxPlus: дробная сетка, сглаживание, курсив, разные сетки в строке.

    pxocr_frac.py снимок.png       -> текст в stdout, оценка в stderr; код 1 — не уверен

Зачем (30.10.2026, просьба: «мне нужно копировать не только в терминале… в браузере
или в других окнах — там тоже нужны точные совпадения»). pxocr.py считает, что края
точек шрифта прижаты к пикселям (хинтинг). Браузер и kitty рисуют PxPlus без хинтинга:
при 13 px точка шрифта — 1.625 px, края размыты сглаживанием, курсив — наклон 1/4.
На таком снимке pxocr отказывался, и в буфер шёл tesseract.

Как. Закраска — расстояние цвета от фона, делённое на местный максимум (цветные
куски строки читаются одинаково). Точка шрифта = средняя закраска её прямоугольника
с дробными краями (интегральное изображение с интерполяцией). Сетка (масштаб, шаг
клетки, наклон, сдвиг) подбирается так, чтобы закраска точек была ближе к 0 или 1, а
первый столбец каждой клетки пуст. Курсив выпрямляется сдвигом рядов (0.25 — Skia,
0.2126 — FreeType). Строка режется на куски по просветам шире 1.6 клетки: у колонок
таблицы и подписи с числом справа своя сетка. Клетки сверяются с растрами pxocr
(Хэмминг); значок у края куска отбрасывается, но если так потеряно больше
LOST_MAX закраски — отказ.

Замер 30.10.2026 (Helium, 12–24 px × обычный/цветной/курсив/подчёркнутый): 99.4 %
символов, 0.6–2.5 с; Noto Sans/Serif, Inter, JetBrains Mono, Cozette — отказ.
"""
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pxocr as P  # noqa: E402

CW, CH = P.CW, P.CH
SKEWS = (0.0, 0.25, 0.2126)
MAX_ERR = 0.8          # средняя ошибка (бит на клетку), чтобы поверить
TIME_BUDGET = 3.5      # секунд; дольше — отказ
FOREIGN = 0.8          # не прочитано больше — чужой шрифт (Noto, Inter, Cozette: 96–99 %)
HINTED_ERR = 0.5      # такая ошибка — знак pxocr.py сперва попробовать целую сетку
FOREIGN_ERR = 99.0     # такая ошибка — знак pxocr.py не тратить время на целую сетку
EDGE_BAD = 4          # клетка с таким расхождением с любой буквой — не буква


def fg_distance(img):
    a = np.asarray(img.convert("RGB"), dtype=np.float64)
    q = (a // 8).astype(np.int64)
    key = (q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]
    vals, cnt = np.unique(key, return_counts=True)
    bg = a[key == vals[cnt.argmax()]].mean(axis=0)
    return np.sqrt(((a - bg) ** 2).sum(axis=2))


def bands_of(ink):
    """Полосы строк. Строки, где закрашено всего пару точек (рамка окна, вертикальная
    черта), полосы не склеивают: ядро — ряды гуще порога, края добираются до пустоты."""
    cnt = ink.sum(axis=1)
    thr = max(2, 0.04 * cnt.max())
    cores, start = [], None
    for y, v in enumerate(cnt > thr):
        if v and start is None:
            start = y
        elif not v and start is not None:
            cores.append([start, y])
            start = None
    if start is not None:
        cores.append([start, len(cnt)])
    # верх строки с редкими точками (выносные у «З», «h») мог отколоться в тонкое
    # ядро — прирастить его к соседу, если между ними нет пустого ряда
    if cores:
        hmax = max(b - a for a, b in cores)
        n = 0
        while n < len(cores):
            a, b = cores[n]
            if b - a < 0.45 * hmax:
                if n + 1 < len(cores) and cnt[b:cores[n + 1][0]].all():
                    cores[n + 1][0] = a
                    del cores[n]
                    continue
                if n and cnt[cores[n - 1][1]:a].all():
                    cores[n - 1][1] = b
                    del cores[n]
                    continue
            n += 1
    # края добираются до пустого ряда, но не дальше середины просвета и не больше
    # половины высоты: рамка окна или фон под полупрозрачной плашкой дают «чернила»
    # в каждом ряду и иначе тянули полосу до соседней строки
    floor = cnt.min()                      # столько дают вертикальные рамки в любом ряду
    orig = [tuple(c) for c in cores]
    for n, (a, b) in enumerate(orig):
        lo = (orig[n - 1][1] + a) // 2 if n else 0
        hi = (b + orig[n + 1][0] + 1) // 2 if n + 1 < len(orig) else len(cnt)
        reach = max(2, int(0.5 * (b - a)))
        lo, hi = max(lo, a - reach), min(hi, b + reach)
        while a > lo and cnt[a - 1] > floor:
            a -= 1
        while b < hi and cnt[b] > floor:
            b += 1
        cores[n] = [a, b]
    return [tuple(c) for c in cores]


def run_max(v, r):
    pad = np.concatenate((np.zeros(r), v, np.zeros(r)))
    return np.lib.stride_tricks.sliding_window_view(pad, 2 * r + 1).max(axis=1)


def band_level(sub, r=10):
    """Закраска 0..1: расстояние от фона, делённое на местный максимум."""
    colmax = run_max(sub.max(axis=0), r)
    lv = np.clip(sub / np.maximum(colmax, 1.0)[None, :], 0.0, 1.0)
    lv[:, colmax < 25] = 0.0
    return lv


def unshear(lv, k, yref):
    """Выпрямить наклон: строка y сдвигается влево на k*(yref - y)."""
    if not k:
        return lv
    H, W = lv.shape
    margin = int(np.ceil(k * H)) + 2
    out = np.zeros((H, W + margin))
    xs = np.arange(out.shape[1], dtype=np.float64)
    src_x = np.arange(W)
    for y in range(H):
        out[y] = np.interp(xs + k * (yref - y) - margin, src_x, lv[y], left=0.0, right=0.0)
    return out


def integral(lv):
    I = np.zeros((lv.shape[0] + 1, lv.shape[1] + 1))
    I[1:, 1:] = np.cumsum(np.cumsum(lv, axis=0), axis=1)
    return I


def lerp_idx(n, v):
    v = np.clip(v, 0, n - 1)
    i0 = np.floor(v).astype(int)
    return i0, np.minimum(i0 + 1, n - 1), v - i0


def coverage(I, s, xs0, y0, ncols, pitch=None):
    """Закраска точек: для каждого сдвига xs0 (массив) — (len(xs0), 8, ncols*6).
    pitch — шаг клетки; больше 6*s, когда у текста задан межбуквенный интервал."""
    pitch = pitch or CW * s
    ys = y0 + np.arange(CH + 1) * s
    a, b, f = lerp_idx(I.shape[0], ys)
    R = I[a] * (1 - f)[:, None] + I[b] * f[:, None]            # (9, W+1)
    edge = (np.arange(ncols)[:, None] * pitch + np.arange(CW + 1)[None, :] * s).ravel()
    xs = xs0[:, None] + edge[None, :]                            # (n, ncols*7)
    a, b, f = lerp_idx(R.shape[1], xs)
    C = R[:, a] * (1 - f) + R[:, b] * f                          # (9, n, ncols*7)
    C = C.reshape(CH + 1, len(xs0), ncols, CW + 1)
    S = C[1:, ..., 1:] - C[:-1, ..., 1:] - C[1:, ..., :-1] + C[:-1, ..., :-1]
    return (S / (s * s)).reshape(CH, len(xs0), ncols * CW).transpose(1, 0, 2)


def align(I, s, ytop, step, pitch=None):
    """[(оценка, dx, dy)]: при верной сетке закраска точек близка к 0 или 1,
    а первый столбец каждой клетки пуст."""
    cw = pitch or CW * s
    ncols = int((I.shape[1] - 1) / cw) + 2
    dxs = np.arange(0, cw, step)
    out = []
    for dy in np.arange(-2.6 * s, 0.6 * s, step):
        c = coverage(I, s, dxs - cw, ytop + dy, ncols, cw).clip(0, 1)
        amb = np.minimum(c, 1 - c).sum(axis=(1, 2))
        air = c.reshape(len(dxs), CH, -1, CW)[..., 0].sum(axis=(1, 2))
        tot = c.sum(axis=(1, 2)) + 1e-9
        sc = (amb + air) / tot
        for i in np.argsort(sc)[:3]:
            out.append((float(sc[i]), float(dxs[i]), float(dy)))
    out.sort()
    return out


def read_cells(I, s, dx, dy, ytop, tmpl, pitch=None):
    tmpl_u, chars, penalty = tmpl
    cw = pitch or CW * s
    ncols = int((I.shape[1] - 1) / cw) + 2
    c = coverage(I, s, np.array([dx - cw]), ytop + dy, ncols, cw)[0]
    cells = (c >= 0.5).reshape(CH, -1, CW).transpose(1, 0, 2).reshape(-1, CH * CW)
    ne = cells.any(axis=1)
    if not ne.any():
        return None
    idx, dist = P.match(P.pack(cells), tmpl_u, penalty)
    # значок или картинка вплотную к тексту: несхожие клетки по краям — не буквы
    nz = np.flatnonzero(ne)
    a, b = 0, len(nz)
    while a < b and dist[nz[a]] > EDGE_BAD:
        a += 1
    while b > a and dist[nz[b - 1]] > EDGE_BAD:
        b -= 1
    if a == b:
        return None
    ne = ne.copy()
    ne[nz[:a]] = False
    ne[nz[b:]] = False
    return float(dist[ne].mean()), idx, ne, float(dist[ne].sum()), int(ne.sum())


def prepare(path):
    img = Image.open(path)
    d = fg_distance(img)
    thr = max(25.0, 0.15 * np.percentile(d, 99.5))
    bands = bands_of(d > thr)
    if not bands:
        return []
    hmax = max(b - a for a, b in bands)
    out = []
    for yt, yb in bands:
        if yb - yt < 0.45 * hmax:              # подчёркивания, рамки, полоски
            continue
        pad = yb - yt
        lv = band_level(d[yt:yb])
        lv = np.pad(lv, ((pad, pad), (0, 0)))
        out.append((yt, yb, lv, pad))
    return out


def scale_cands(h):
    c = set()
    for n in (8, 7, 6, 5):
        base = h / n
        for d in (-1, 0, 1):
            v = round(base * 8) / 8 + d / 8
            if 1.0 <= v <= 5.0:
                c.add(v)
    return sorted(c)


PITCH_EXTRA = (1, 2, 3, 4)      # межбуквенный интервал, пикселей


def geometry(band, debug=False):
    """[(оценка, масштаб, шаг клетки)] по одной полосе, грубым шагом: сперва
    масштаб и наклон без интервала, потом интервал для двух лучших масштабов."""
    yt, yb, lv, pad = band
    # мерить по самому широкому куску: у кусков строки сетки разные
    segs = segments(lv, 0.75 * (yb - yt))
    if segs:
        x0, x1 = max(segs, key=lambda c: c[1] - c[0])
        lv = lv[:, max(0, x0 - (yb - yt)):x1 + (yb - yt)]
    best = []
    Is = {k: integral(unshear(lv, k, pad + (yb - yt))) for k in SKEWS}
    for k, I in Is.items():
        for s in scale_cands(yb - yt):
            a = align(I, s, pad, 0.5)
            if a:
                best.append((a[0][0], s, CW * s, k))
    best.sort()
    tops = []
    for b in best:
        if b[1] not in [t[1] for t in tops]:
            tops.append(b)
    for sc, s, _, k in tops[:2]:
        for e in PITCH_EXTRA:
            a = align(Is[k], s, pad, 0.5, CW * s + e)
            if a:
                best.append((a[0][0], s, CW * s + e, k))
    best.sort()
    out = []
    for sc, s, p, k in best:
        if (s, p) not in [(o[1], o[2]) for o in out]:
            out.append((sc, s, p))
    if debug:
        print("сетки:", [(round(a, 3), b, c) for a, b, c in out[:4]], file=sys.stderr)
    return out[:2]


def segments(lv, pitch):
    """Куски строки, разделённые просветом шире двух клеток: у колонок таблицы,
    подписи и значения справа своя сетка, общей для всей строки нет."""
    cols = np.flatnonzero(lv.max(axis=0) > 0.3)
    if not len(cols):
        return []
    out, a = [], cols[0]
    for p, q in zip(cols[:-1], cols[1:]):
        if q - p > 1.6 * pitch:
            out.append((a, p + 1))
            a = q
    out.append((a, cols[-1] + 1))
    return out


def read_segment(band, x0, x1, s, pitch, tmpl):
    yt, yb, lv, pad = band
    m = int(2 * pitch)
    lo = max(0, x0 - m)
    sub = lv[:, lo:x1 + m].copy()
    sub[:, :x0 - lo] = 0                   # соседние куски в запасе по краям не читать
    sub[:, x1 - lo:] = 0
    got = None
    for k in SKEWS:
        I = integral(unshear(sub, k, pad + (yb - yt)))
        for sc, dx, dy in align(I, s, pad, 0.25, pitch)[:5]:
            r = read_cells(I, s, dx, dy, pad, tmpl, pitch)
            if r and (got is None or r[0] < got[0]):
                got = r + (k, lo + dx - pitch - (k * (yb - yt) + 2 if k else 0))
        if got and got[0] == 0:
            break
    return got


SEG_MAX_ERR = 1.5        # кусок с большей ошибкой — не текст этим шрифтом (значок, картинка)
LOST_MAX = 0.15          # столько закраски можно потерять на таких кусках, не больше


def read_band(band, s, pitch, tmpl):
    """(оценка, [(x, символы)], сумма ошибок, клеток, потерянная закраска)"""
    chars = tmpl[1]
    lv = band[2]
    parts, es, nn, lost = [], 0.0, 0, 0.0
    for x0, x1 in segments(lv, pitch):
        r = read_segment(band, x0, x1, s, pitch, tmpl)
        if r is None or r[0] > SEG_MAX_ERR:
            lost += lv[:, x0:x1].sum()
            continue
        e, idx, ne, se, sn, k, xorg = r
        cells = [chars[i] if ok else [" "] for i, ok in zip(idx, ne)]
        first = int(np.argmax(ne))
        last = len(ne) - int(np.argmax(ne[::-1]))
        # что осталось за обрезанными краями — потеряно
        xa = int(max(x0, xorg + first * pitch))
        xb = int(min(x1, xorg + last * pitch + (k * (band[1] - band[0]) if k else 0)))
        lost += lv[:, x0:x1].sum() - lv[:, xa:max(xa, xb)].sum()
        parts.append((xorg + first * pitch, cells[first:last]))
        es += se
        nn += sn
    share = lost / max(lv.sum(), 1e-9)
    return (es / nn if nn else 9.0) + 4 * share, parts, es, nn, lost


def join_parts(parts, pitch, x_base):
    line = []
    for x, cells in parts:
        col = max(int(round((x - x_base) / pitch)), len(line) + 1 if line else 0)
        line += [[" "]] * (col - len(line)) + cells
    return line


def read(path, debug=False):
    t0 = time.time()
    bands = prepare(path)
    if not bands:
        return None, "пусто", 9.0
    tmpl = P.templates()[:3]
    # сетка — по самой «чернильной» полосе; строка, которая с ней не читается
    # (заголовок крупнее, подпись мельче), ищет свою
    common = geometry(max(bands, key=lambda b: b[2].sum()), debug)
    rows, esum, n, lost, scales = [], 0.0, 0, 0.0, set()
    for band in bands:
        if time.time() - t0 > TIME_BUDGET:
            return None, "долго (%.2f с)" % (time.time() - t0), 9.0
        got = None
        for tries in (common, None):
            if tries is None:
                if got and got[0] <= 1.0:
                    break
                tries = geometry(band, debug)
            for _, s, pitch in tries:
                r = read_band(band, s, pitch, tmpl)
                if got is None or r[0] < got[0]:
                    got = r + (s, pitch)
                if got[0] <= 0.3:
                    break
            if got[0] <= 0.3:
                break
        sc, parts, es, nn, ls, s, pitch = got
        if debug:
            print("  полоса %d-%d x%.3f шаг %.3g кусков %d оценка %.2f"
                  % (band[0], band[1], s, pitch, len(parts), sc), file=sys.stderr)
        lost += ls
        if parts:
            rows.append((parts, pitch))
            scales.add(s)
            esum += es
            n += nn
    total = sum(b[2].sum() for b in bands)
    share = lost / max(total, 1e-9)
    if not n:
        return None, "разбора нет (%.2f с)" % (time.time() - t0), FOREIGN_ERR
    err = esum / n
    x_base = min(p[0][0] for p, _ in rows)
    lines = [P.resolve(join_parts(p, pitch, x_base)).rstrip() for p, pitch in rows]
    kept = [l for l in lines if l.strip()]
    indent = min((len(l) - len(l.lstrip(" ")) for l in kept), default=0)
    text = "\n".join(l[indent:] for l in kept)
    note = "дробная сетка, ошибка %.2f, не прочитано %.0f%%, %.2f с" % (
        err, share * 100, time.time() - t0)
    if share > FOREIGN:
        return None, note, FOREIGN_ERR
    if err > MAX_ERR or share > LOST_MAX or not text:
        return None, note, err
    # Масштаб, кратный половине пикселя (12 px = 1.5, 16 px = 2), — у GTK это хинтинг:
    # края точек прижаты к пикселям, и целая сетка pxocr там точнее (запятые
    # в 1–2 пикселя дробная теряет). Пусть pxocr.py попробует первым.
    if all((2 * s).is_integer() for s in scales):
        err = max(err, HINTED_ERR)
    return text, note, err


if __name__ == "__main__":
    text, note, _ = read(sys.argv[1], debug=bool(os.environ.get("PXOCR_DEBUG")))
    print(note, file=sys.stderr)
    if text is None:
        sys.exit(1)
    sys.stdout.write(text)
