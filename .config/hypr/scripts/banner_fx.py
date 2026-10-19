#!/usr/bin/env python3
"""Эффекты banner.exe — те же, что у команды `text` (флаги -f -R -w -l -r -p -b -t -g -s).
19.10.2026.

Просьба: «я должен иметь возможность создавать просто статичный текст… и дополнительно
выбрать вот эти настройки, можно отдельно, можно все вместе». Рисует надпись виджет
banner (desktop_widgets_extra.py) и превью в окне создания (banner_ask.py) — одной
функцией, чтобы превью показывало ровно то, что встанет на обои.

    small(text, fd)                      надпись мелким шрифтом, белым (маска), без сглаживания
    Text(text, fd)                       то же с переносом: статичная сама встаёт в 1–4 строки
    paint(cr, sm, x, y, w, h, t, fx, pace, accent, speed=90, st=None)
                                         кадр в момент t (секунды): sm — Text или растр, fx — строка флагов
                                         («» — статичный текст), pace — множитель скорости (-s),
                                         speed — бег строки в px/с при pace 1, st — словарь
                                         состояния глитча (свой у каждого виджета)
    animated(fx)                         нужна ли анимация (иначе кадр один)

Надпись — мелкий растр, увеличенный по пикселям (как раньше у виджета): волна, глитч и
каретка сдвигают её на целые «пиксели» шрифта, поэтому буквы остаются чёткими.
"""
import colorsys
import math
import random

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

EFFECTS = "fRwlrpbtg"
# (флаг, подпись в окне) — порядок как в справке `text`
LABELS = (("f", "Бег ←"), ("R", "Бег →"), ("w", "Волна"), ("l", "Блик"), ("r", "Радуга"),
          ("p", "Пульс"), ("b", "Мигание"), ("t", "Машинка"), ("g", "Глитч"))
PACES = (0.5, 1.0, 1.5, 2.0, 3.0)
TYPE_HOLD = 2.0       # машинка: сколько секунд стоит готовая надпись (как у `text`)
TYPE_GAP = 0.5        # и сколько пусто перед повтором


def clean(fx):
    """Только известные флаги, без повторов; -f и -R вместе не бывают (останется -R)."""
    out = "".join(c for c in EFFECTS if c in str(fx or ""))
    return out.replace("f", "") if "R" in out else out


def animated(fx):
    return bool(clean(fx))


def small(text, fd):
    """Растр надписи белым по прозрачному: потом служит маской под любой цвет."""
    probe = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8))
    lay = PangoCairo.create_layout(probe)
    lay.set_font_description(fd)
    lay.set_text(text, -1)
    lay.set_alignment(Pango.Alignment.CENTER)    # строки статичной надписи — по центру
    lw, lh = lay.get_pixel_size()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, lw), max(1, lh))
    cr = cairo.Context(surf)
    fo = cairo.FontOptions()
    fo.set_antialias(cairo.ANTIALIAS_NONE)       # чистые пиксели: их потом увеличивать
    fo.set_hint_style(cairo.HINT_STYLE_FULL)
    PangoCairo.context_set_font_options(PangoCairo.create_context(cr), fo)
    lay = PangoCairo.create_layout(cr)
    PangoCairo.context_set_font_options(lay.get_context(), fo)
    lay.set_font_description(fd)
    lay.set_text(text, -1)
    lay.set_alignment(Pango.Alignment.CENTER)
    cr.set_source_rgb(1, 1, 1)
    PangoCairo.show_layout(cr, lay)
    return surf


def wrap(words, n):
    """Слова в n строк (или меньше) почти равной длины."""
    target = -(-len(" ".join(words)) // n)
    while True:
        lines = [""]
        for wd in words:
            if not lines[-1]:
                lines[-1] = wd
            elif len(lines[-1]) + 1 + len(wd) <= target:
                lines[-1] += " " + wd
            else:
                lines.append(wd)
        if len(lines) <= n:
            return tuple(lines)
        target += 1


class Text:
    """Надпись, которая сама переносится на строки. Статичный текст должен целиком влезть
    в ширину виджета, и длинная фраза одной строкой выходила крошечной — ×2 вместо ×11
    у бегущей (19.10.2026, просьба: «почему текст не такой большой, как был раньше?»).
    fit() выбирает 1–4 строки так, чтобы увеличение было наибольшим; бегущей — одна строка."""

    def __init__(self, text, fd):
        self.text = " ".join(str(text).split()) or " "
        self.fd = fd
        self.surfs, self.fits = {}, {}

    def surf(self, lines):
        if lines not in self.surfs:
            self.surfs[lines] = small("\n".join(lines), self.fd)
        return self.surfs[lines]

    def line(self):
        return self.surf((self.text,))

    def amp(self, wave):
        return max(1, round(self.line().get_height() * 0.15)) if wave else 0

    def fit(self, w, h, wave):
        key = (w, h, wave)
        if key not in self.fits:
            words, amp = self.text.split(), self.amp(wave)
            best, best_k = (self.text,), -1
            for n in range(1, min(4, len(words)) + 1):
                lines = wrap(words, n)
                sm = self.surf(lines)
                k = min(h // (sm.get_height() + 2 * amp), w // max(1, sm.get_width()))
                if k > best_k:
                    best, best_k = lines, k
            self.fits[key] = self.surf(best)
        return self.fits[key]


def _source(x, w, T, fx, accent, alpha):
    """Цвет надписи по колонкам экрана: акцент или радуга, пульс — прозрачностью."""
    if "r" not in fx:
        return cairo.SolidPattern(*accent, alpha)
    g = cairo.LinearGradient(x, 0, x + max(1, w), 0)
    n = 32
    for i in range(n + 1):
        f = i / n
        hue = (f * 0.9 + T * 0.25) % 1.0
        g.add_color_stop_rgba(f, *colorsys.hsv_to_rgb(hue, 0.55, 1.0), alpha)
    return g


def paint(cr, sm, x, y, w, h, t, fx, pace=1.0, accent=(0.48, 0.64, 0.97), speed=90, st=None):
    fx = clean(fx)
    pace = max(0.05, float(pace or 1.0))
    T = t * pace
    if "b" in fx and int(T * 2) % 2:             # мигание: полсекунды нет
        return
    marquee = "f" in fx or "R" in fx
    # волне нужен запас по высоте: буквы ходят вверх-вниз на amp «пикселей» шрифта
    if isinstance(sm, Text):
        amp = sm.amp("w" in fx)
        sm = sm.line() if marquee else sm.fit(w, h, "w" in fx)
    else:
        amp = max(1, round(sm.get_height() * 0.15)) if "w" in fx else 0
    sw, sh = sm.get_width(), sm.get_height()
    k = max(1, h // (sh + 2 * amp))
    if not marquee:
        k = max(1, min(k, w // max(1, sw)))
    tw = sw * k
    if marquee:
        span = w + tw
        shift = (T * speed) % span
        ox = x + (w - shift if "R" not in fx else shift - tw)
    else:
        ox = x + (w - tw) // 2
    oy = y + (h - sh * k) // 2

    # машинка: сколько колонок надписи уже напечатано; бегущей строке не нужна (как у `text`)
    show, caret = sw, None
    if "t" in fx and not marquee:
        rate = max(30.0, sw / 2.5)                # колонок в секунду (T уже со скоростью)
        cycle = sw / rate + TYPE_HOLD + TYPE_GAP
        done = (T % cycle) * rate
        show = int(max(0, min(sw, done)))
        if 0 < done < sw and int(t * 4) % 2 == 0:
            caret = show

    # глитч: изредка на 0.08–0.2 с полосы строк сдвигаются и меняют цвет
    bands = {}
    if "g" in fx:
        st = st if st is not None else {}
        if t >= st.get("until", 0.0):
            st["rows"] = {}
            if random.random() < 0.02 * pace:
                for _ in range(random.randint(1, 3)):
                    r0 = random.randrange(max(1, sh))
                    for dy in range(random.randint(1, max(1, sh // 4))):
                        st["rows"][r0 + dy] = random.choice((-3, -2, -1, 1, 2, 3))
                st["until"] = t + random.uniform(0.08, 0.2)
        bands = st.get("rows") or {}

    alpha = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(T * 3.5)) if "p" in fx else 1.0
    src = _source(x, w, T, fx, accent, alpha)
    mask = cairo.SurfacePattern(sm)
    mask.set_filter(cairo.FILTER_NEAREST)

    # видимые колонки надписи (в «пикселях» шрифта)
    c0 = max(0, int((x - ox) // k))
    c1 = min(show, int(math.ceil((x + w - ox) / k)))
    if c1 <= c0 and caret is None:
        return

    def wave(c):
        return round(amp * math.sin(c / 6.0 - T * 5.0)) if amp else 0

    def runs():
        """Отрезки колонок с одинаковым сдвигом волны: (от, до, сдвиг)."""
        c = c0
        while c < c1:
            d, e = wave(c), c + 1
            while e < c1 and wave(e) == d:
                e += 1
            yield c, e, d
            c = e

    hot = (1 - accent[0], 80 / 255, 1.0)
    band = None
    if "l" in fx:                                # блик — белая полоса бежит слева направо
        bc = x + ((T * 0.45) % 1.6 - 0.3) * w
        bw = max(6 * k, w / 10)
        band = cairo.LinearGradient(bc - bw, 0, bc + bw, 0)
        band.add_color_stop_rgba(0, 1, 1, 1, 0)
        band.add_color_stop_rgba(0.5, 1, 1, 1, 0.85 * alpha)
        band.add_color_stop_rgba(1, 1, 1, 1, 0)

    def masked(source, a, b, r0, r1, gx, d):
        """Кусок надписи (колонки a..b, строки r0..r1), сдвинутый на gx, d «пикселей»."""
        cr.save()
        cr.rectangle(x, y, w, h)
        cr.clip()
        cr.set_source(source)                    # цвет — в координатах виджета
        cr.translate(int(ox) + gx * k, oy + d * k)
        cr.scale(k, k)
        cr.rectangle(a, r0, b - a, r1 - r0)
        cr.clip()
        cr.mask(mask)
        cr.restore()

    # строки без глитча — одним куском, строки глитча — со сдвигом и чужим цветом
    rows = [(0, sh, 0)]
    if bands:
        rows, r = [], 0
        while r < sh:
            g = bands.get(r, 0)
            e = r + 1
            while e < sh and bands.get(e, 0) == g:
                e += 1
            rows.append((r, e, g))
            r = e
    for a, b, d in runs():
        for r0, r1, gx in rows:
            masked(cairo.SolidPattern(*hot, alpha) if gx else src, a, b, r0, r1, gx, d)
            if band is not None:
                masked(band, a, b, r0, r1, gx, d)
    if caret is not None:                        # каретка машинки мигает у края печати
        cr.save()
        cr.rectangle(x, y, w, h)
        cr.clip()
        cr.set_source_rgba(*accent, alpha)
        cr.rectangle(int(ox) + caret * k, oy + wave(caret) * k, max(1, k), sh * k)
        cr.fill()
        cr.restore()
