#!/usr/bin/env python3
"""Курсор «Skeet» — пиксельный набор в цветах стиля Skeet (акцент обоев). 15.10.2026.

Просьба: «создай курсор, под стиль системы отдельный, и добавь его в Настройки список
курсоров. Под стиль Skeet». Показан лист из 4 вариантов (~/Pictures/cursor-skeet-variants.png);
выбора не было, а курсор он ждал в списке — встал вариант 2 «поле в рамке акцента»: тёмное
поле field_l, как у кнопок Skeet, рамка акцентом, тёмный ореол line3 — читается и на тёмном,
и на светлом фоне. Остальные варианты — в VARIANTS, сменить: VARIANT ниже + `build`.

Формы, клетка и острия — те же 14 масок, что у «Стрелки» (tri_cursor.SHAPES/SCALE), меняются
только цвета. Цвета — rec_style.colors("skeet"): акцент из vivid.txt, поэтому при смене обоев
курсор пересобирается (cursor_theme.py refresh). Тема — Jarvis-Skeet-A / -B попеременно
(niri не перечитывает курсор, пока имя темы то же).

    skeet_cursor.py build [ТЕКУЩЕЕ]   собрать в свободный A/B, имя — в stdout
    skeet_cursor.py sheet ФАЙЛ        лист: все формы, размеры 20 и 32
Включает cursor_theme.py (Настройки → Design → «Тема курсора» → «Skeet»).
"""
import math
import os
import pathlib
import shutil
import struct
import sys

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cursor_colors   # noqa: E402  (build — тема и синонимы, write_xcursor)
import rec_style       # noqa: E402  (colors("skeet"))
import tri_cursor      # noqa: E402  (SHAPES, SCALE, cells)

ICONS = pathlib.Path.home() / ".local/share/icons"
NAMES = ("Jarvis-Skeet-A", "Jarvis-Skeet-B")
VARIANT = 2
# Сглаженный вид (15.10.2026, просьба: «обводку лучше сделай тёмной более, можно даже менее
# пиксельной»): те же маски, но углы скруглены и края сглажены (рисуется в SS раз крупнее и
# уменьшается), снаружи тёмная обводка, акцент — тонкой кромкой внутри тела. False — прежний
# пиксельный вариант 2.
SMOOTH = True
SS = 8
SOFT = .4                   # сглаживание контура (доля клетки)
GROW = 1.25                 # 15.10: «слегка увеличить, слишком крошечный» — клетка ×1.25 к tri_cursor
# Вид Breeze (15.10.2026, просьба: «сделай её менее пиксельной, по типу breeze'а»): берутся
# сами картинки breeze_cursors всех размеров (векторная форма, своя отрисовка на каждый размер)
# и перекрашиваются: чёрное тело → field_l, белая кромка → акцент, цветные детали → акцент
# темнее (красный «нельзя» остаётся красным), тень Breeze как есть; снаружи — тёмная обводка
# line3. Размер 20 (наш по умолчанию) у Breeze нет — делается из 30 уменьшением.
# 15.10.2026 вечером Просьба: «ты просто скопировал стиль breeze, я этого не хотел… своя форма.
# Откати обратно и подравняй, сделав менее пиксельную версию» — снова свои маски (smooth),
# контур сглажен сильнее (SOFT .2 → .4; .6 уже съедает тонкие детали). breeze оставлен на откат.
STYLE = "smooth"            # smooth | breeze | pixel
# Свои формы поверх tri_cursor (15.10.2026, просьба: «рука не нравится, палец мелковат, что
# указательный что большой», «текстовый курсор чуть уменьшить»). (маска, остриё x, y, центр ли,
# доля клетки): рука — на сетке в полклетки, палец 2 клетки шириной, большой палец отдельно;
# I — та же маска, клетка ×0.8.
OWN = {
    "pointer": ("""
.....##.....
....####....
....####....
....####....
....####....
....####....
....######..
##..########
###.########
############
.###########
..##########
...#########
....########
....#######.
""", 6, 0, False, .5),
    "text": (tri_cursor.SHAPES["text"][0], 2, 3, True, .8),
}
BREEZE = pathlib.Path("/usr/share/icons/breeze_cursors/cursors")
XC_IMAGE = 0xFFFD0002
# 15.10.2026 ночью пользователь (сравнив руки): «твой вариант смотрится кривой, а вариант breeze
# аккуратным. Скопируй только форму этого указателя, остальное пусть стоит» — у руки берётся
# лишь силуэт Breeze (альфа самого крупного кадра, 96 px), а цвета, кромка, обводка и тень —
# свои, как у остальных форм. Высота тела — как у прежней своей руки. Пустой кортеж — своя маска.
BREEZE_FORM = ("pointer",)


def hx(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def palette(variant=VARIANT):
    """F тело, L светлый левый край, D деталь, O контур, H ореол, HA прозрачность ореола."""
    sk = rec_style.colors("skeet")
    acc, accl, accd = hx(sk["acc"]), hx(sk["acc_l"]), hx(sk["acc_d"])
    field, line1, line3, text = hx(sk["field_l"]), hx(sk["line1"]), hx(sk["line3"]), hx(sk["text"])
    return {
        1: dict(F=field, L=acc, D=accd, O=line1, H=line3, HA=255),
        2: dict(F=field, L=mix(field, text, .25), D=line3, O=acc, H=line3, HA=255),
        4: dict(F=field, L=accl, D=acc, O=line1, H=acc, HA=255),
    }.get(variant) or dict(F=field, L=mix(field, text, .25), D=line3, O=acc, H=line3, HA=255)


def _grow(m, r):
    """Расширить маску на круг радиуса r (в пикселях крупной картинки).
    Круг — по строкам: сперва полосы ширины 0..r по горизонтали (каждая из предыдущей двумя
    сдвигами), потом каждая строка круга — своя полоса со сдвигом по вертикали. ~4r сдвигов
    вместо ~πr² (15.10: сборка темы 5 с → доли секунды, результат тот же до пикселя)."""
    r = int(round(r))
    rows = [m]
    for w in range(1, r + 1):
        rows.append(rows[-1] | np.roll(m, w, 1) | np.roll(m, -w, 1))
    out = m.copy()
    for dy in range(-r, r + 1):
        out |= np.roll(rows[math.isqrt(r * r - dy * dy)], dy, 0)
    return out


def render_smooth(name, size):
    """Сглаженный курсор: тело field_l, кромка акцента внутри, тёмная обводка, мягкая тень."""
    sk = rec_style.colors("skeet")
    acc, field, dark = hx(sk["acc"]), hx(sk["field_l"]), hx(sk["line3"])
    det = mix(field, dark, .6)
    mask, hx_, hy_, center, k = OWN.get(name) or (tri_cursor.SHAPES[name] + (1,))
    f = tri_cursor.SCALE[size][0] * GROW * k   # клетка, px (дробная — считаем в подвыборке)
    ow = max(1.0, size / 20)                    # тёмная обводка, px
    edge = max(1.0, size / 22)                  # кромка акцента, px
    sh = max(1.0, size / 24)                    # тень, px
    body = tri_cursor.cells(mask)
    pad = int(ow + sh + 2)
    cw, ch = max(x for x, _ in body) + 1, max(y for _, y in body) + 1
    S = SS
    if name in BREEZE_FORM:
        form, bx, by = breeze_form(name, ch * f * S)
        fh, fw = form.shape
        w, h = int(math.ceil(fw / S)) + 2 * pad, int(math.ceil(fh / S)) + 2 * pad
        solid = np.zeros((h * S, w * S), bool)
        solid[pad * S:pad * S + fh, pad * S:pad * S + fw] = form
        dmask = np.zeros_like(solid)
        hot = (int(pad + bx / S), int(pad + by / S))
    else:
        w, h = int(math.ceil(cw * f)) + 2 * pad, int(math.ceil(ch * f)) + 2 * pad
        q = lambda v: int(round(v * S))  # noqa: E731
        cell = np.zeros((h * S, w * S), bool)
        dmask = np.zeros_like(cell)
        for (x, y), c in body.items():
            sl = (slice(q(pad + y * f), q(pad + y * f + f)), slice(q(pad + x * f), q(pad + x * f + f)))
            cell[sl] = True
            if c == "D":
                dmask[sl] = True
        # скругление: размыть и обрезать по середине — выпуклые углы срезаются, лесенка сглаживается
        blur = Image.fromarray((cell * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(f * S * SOFT))
        solid = np.array(blur) > 127
        off = f / 2 if center else 0
        hot = (int(pad + hx_ * f + off), int(pad + hy_ * f + off))
    inner = ~_grow(~solid, edge * S)            # тело без кромки
    rim = _grow(solid, ow * S) & ~solid
    shadow = _grow(solid | rim, sh * S) & ~(solid | rim)
    rgba = np.zeros((h * S, w * S, 4), np.float32)
    rgba[shadow] = (0, 0, 0, 60)
    rgba[rim] = dark + (255,)
    rgba[solid] = acc + (255,)
    rgba[inner] = field + (255,)
    rgba[inner & dmask] = det + (255,)
    # уменьшение с усреднением по альфе (премультипликация — без светлой бахромы)
    a = rgba[..., 3:4] / 255
    pm = np.concatenate([rgba[..., :3] * a, rgba[..., 3:4]], -1)
    pm = pm.reshape(h, S, w, S, 4).mean((1, 3))
    al = pm[..., 3:4]
    col = np.where(al > 0, pm[..., :3] / np.maximum(al, 1e-6) * 255, 0)
    out = np.concatenate([col, al], -1).clip(0, 255).astype(np.uint8)
    return (Image.fromarray(out, "RGBA"),) + hot


def breeze_form(name, height):
    """Силуэт формы Breeze высотой height px (крупная картинка): (маска, остриё x, y).
    Берётся всё непрозрачное (тело + белая кромка Breeze), тень Breeze — нет."""
    n, im, xh, yh, _ = max(xc_read((BREEZE / name).resolve()), key=lambda t: t[0])
    al = np.asarray(im, np.float32)[..., 3]
    ys, xs = np.nonzero(al >= 100)
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    k = height / (y1 - y0)
    a = Image.fromarray(np.where(al >= 100, al, 0)[y0:y1, x0:x1].astype(np.uint8))
    a = a.resize((round((x1 - x0) * k), round(height)), Image.LANCZOS)
    return np.asarray(a) > 127, (xh - x0) * k, max(0, yh - y0) * k


def render(name, size, pal):
    """(картинка, остриё x, y) для размера темы — как tri_cursor.render, свои цвета."""
    if SMOOTH:
        return render_smooth(name, size)
    mask, hx_, hy_, center = tri_cursor.SHAPES[name]
    f, ow, h = tri_cursor.SCALE[size]
    body = tri_cursor.cells(mask)
    pad = ow + h
    w = (max(x for x, _ in body) + 1) * f + 2 * pad
    ht = (max(y for _, y in body) + 1) * f + 2 * pad
    im = Image.new("RGBA", (w, ht), (0, 0, 0, 0))
    out = im.load()
    solid = set()
    for (x, y), c in body.items():
        if c == "D":
            col = pal["D"]
        elif (x - 1, y) not in body and (x + 1, y) in body:
            col = pal["L"]
        else:
            col = pal["F"]
        for i in range(f):
            for j in range(f):
                q = (pad + x * f + i, pad + y * f + j)
                out[q] = col + (255,)
                solid.add(q)
    rim = {(x + dx, y + dy) for x, y in solid
           for dx in range(-ow, ow + 1) for dy in range(-ow, ow + 1)} - solid
    for q in rim:
        out[q] = pal["O"] + (255,)
    halo = {(x + dx, y + dy) for x, y in solid | rim
            for dx in range(-h, h + 1) for dy in range(-h, h + 1)
            if abs(dx) + abs(dy) <= h} - solid - rim
    for q in halo:
        out[q] = pal["H"] + (pal["HA"],)
    off = f // 2 if center else 0
    return im, pad + hx_ * f + off, pad + hy_ * f + off


def images(name, pal):
    return [(s,) + render(name, s, pal) + (0,) for s in tri_cursor.SCALE]


def xc_read(path):
    """Все картинки xcursor: [(номинал, Image RGBA (прямая альфа), xhot, yhot, delay)]."""
    data = pathlib.Path(path).read_bytes()
    n = struct.unpack_from("<I", data, 12)[0]
    out = []
    for i in range(n):
        typ, sub, pos = struct.unpack_from("<III", data, 16 + i * 12)
        if typ != XC_IMAGE:
            continue
        w, h, xh, yh, delay = struct.unpack_from("<9I", data, pos)[4:]
        a = np.frombuffer(data, np.uint8, w * h * 4, pos + 36).reshape(h, w, 4).astype(np.float32)
        rgb, al = a[..., [2, 1, 0]], a[..., 3:4]
        rgb = np.where(al > 0, rgb * 255 / np.maximum(al, 1), 0)      # из предумноженной
        out.append((sub, Image.fromarray(np.concatenate([rgb, al], -1).clip(0, 255)
                                         .astype(np.uint8), "RGBA"), xh, yh, delay))
    return out


def xc_write(dest, images):
    """Как cursor_colors.write_xcursor, но с честным предумножением полупрозрачных краёв."""
    header = 16 + 12 * len(images)
    toc, chunks, pos = [], [], header
    for nominal, im, xh, yh, delay in images:
        a = np.asarray(im.convert("RGBA"), np.float32)
        pre = np.concatenate([a[..., :3] * a[..., 3:4] / 255, a[..., 3:4]], -1)
        raw = pre.round().clip(0, 255).astype(np.uint8)[..., [2, 1, 0, 3]].tobytes()
        data = struct.pack("<9I", 36, XC_IMAGE, nominal, 1, im.width, im.height,
                           xh, yh, delay) + raw
        toc.append(struct.pack("<III", XC_IMAGE, nominal, pos))
        chunks.append(data)
        pos += len(data)
    dest.write_bytes(struct.pack("<4sIII", b"Xcur", 16, 0x10000, len(images))
                     + b"".join(toc) + b"".join(chunks))


def breeze_recolor(im, nominal):
    """Картинка Breeze → Skeet: тело field_l, кромка акцентом, тёмная обводка снаружи."""
    sk = rec_style.colors("skeet")
    acc, accd, field, dark = (np.array(hx(sk[k]), np.float32)
                              for k in ("acc", "acc_d", "field_l", "line3"))
    a = np.asarray(im, np.float32)
    rgb, al = a[..., :3], a[..., 3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    lum = (rgb @ np.array([.299, .587, .114], np.float32))[..., None] / 255
    shape = al >= 100                                   # тень Breeze — слабая альфа, не трогать
    sat = (mx - mn) > 60
    red = sat & (rgb[..., 0] > 180) & (rgb[..., 1] < 90) & (rgb[..., 2] < 90)
    gray_col = field + (acc - field) * lum              # чёрное → поле, белое → акцент
    sat_col = dark + (accd - dark) * (0.5 + lum * .8)   # цветные детали → тёмный акцент
    col = np.where(sat[..., None], sat_col, gray_col)
    col = np.where(red[..., None], rgb, col)
    body = np.zeros_like(a)
    body[..., :3] = np.where(shape[..., None], col, 0)
    body[..., 3] = np.where(shape, al, 0)
    shadow = a.copy()
    shadow[..., 3] = np.where(shape, 0, al)
    shadow[..., :3] = 0
    r = 1 if nominal <= 36 else 2
    grow = Image.fromarray(body[..., 3].astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * r + 1))
    rim = np.zeros_like(a)
    rim[..., :3] = dark
    rim[..., 3] = np.asarray(grow, np.float32)
    out = Image.fromarray(shadow.astype(np.uint8), "RGBA")
    out.alpha_composite(Image.fromarray(rim.clip(0, 255).astype(np.uint8), "RGBA"))
    out.alpha_composite(Image.fromarray(body.clip(0, 255).astype(np.uint8), "RGBA"))
    return out


def breeze_images(path):
    src = xc_read(path)
    out = [(n, breeze_recolor(im, n), xh, yh, d) for n, im, xh, yh, d in src]
    have = {n for n, *_ in src}
    for want, base in ((20, 30),):                    # наш размер 20 — из Breeze 30
        if want in have or base not in have:
            continue
        f = want / base
        for n, im, xh, yh, d in src:
            if n != base:
                continue
            sm = _scale_premul(im, f)
            out.append((want, breeze_recolor(sm, want), round(xh * f), round(yh * f), d))
    out.sort(key=lambda t: t[0])                      # кадры одного размера — подряд, по порядку
    return out


def _scale_premul(im, f):
    a = np.asarray(im, np.float32)
    pre = np.concatenate([a[..., :3] * a[..., 3:4] / 255, a[..., 3:4]], -1)
    w, h = round(im.width * f), round(im.height * f)
    ch = [np.asarray(Image.fromarray(pre[..., i]).resize((w, h), Image.LANCZOS)) for i in range(4)]
    p = np.stack(ch, -1).clip(0, 255)
    rgb = np.where(p[..., 3:4] > 0, p[..., :3] * 255 / np.maximum(p[..., 3:4], 1e-3), 0)
    return Image.fromarray(np.concatenate([rgb, p[..., 3:4]], -1).clip(0, 255).astype(np.uint8), "RGBA")


def build_breeze(name):
    """Тема name из перекрашенного Breeze: все файлы, синонимы — те же ссылки, что у Breeze."""
    tmp = ICONS / (".%s.tmp-%d" % (name, os.getpid()))
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "cursors").mkdir(parents=True)
    for p in sorted(BREEZE.iterdir()):
        if p.is_symlink():
            (tmp / "cursors" / p.name).symlink_to(os.readlink(p))
        else:
            xc_write(tmp / "cursors" / p.name, breeze_images(p))
    (tmp / "index.theme").write_text(
        "[Icon Theme]\nName=%s\nComment=Skeet (Breeze в цветах Skeet) — skeet_cursor.py\n"
        "Inherits=breeze_cursors\n" % name)
    target = ICONS / name
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return name


def build(current=""):
    name = NAMES[1] if current == NAMES[0] else NAMES[0]
    if STYLE == "breeze":
        return build_breeze(name)
    cursor_colors.build(name)                       # тема, синонимы-ссылки
    cur = ICONS / name / "cursors"
    pal = palette()
    for shape in tri_cursor.SHAPES:
        tmp = cur / (".%s.tmp" % shape)
        cursor_colors.write_xcursor(tmp, images(shape, pal))
        os.replace(tmp, cur / shape)                # синонимы — ссылки на эти файлы
    (ICONS / name / "index.theme").write_text(
        "[Icon Theme]\nName=%s\nComment=Skeet — skeet_cursor.py\n"
        "Inherits=breeze_cursors\n" % name)
    return name


def sheet(path, sizes=(20, 32)):
    pal = palette()
    rows = []
    if STYLE == "breeze":
        names = ("default", "pointer", "text", "wait", "help", "not-allowed", "move",
                 "crosshair", "nwse-resize", "grabbing")
        for s, k in ((20, 6), (48, 3)):
            r = []
            for n in names:
                ims = [im for z, im, *_ in breeze_images((BREEZE / n).resolve()) if z == s]
                if ims:
                    r.append(ims[0].resize((ims[0].width * k, ims[0].height * k), Image.NEAREST))
            rows.append(r)
        sizes = ()
    for s in sizes:
        k = 6 if s <= 24 else 4
        rows.append([im.resize((im.width * k, im.height * k), Image.NEAREST)
                     for im, _, _ in (render(n, s, pal) for n in tri_cursor.SHAPES)])
    W = max(sum(i.width + 24 for i in r) for r in rows) + 24
    H = sum(max(i.height for i in r) + 24 for r in rows) + 24
    out = Image.new("RGBA", (W, H), hx(rec_style.colors("skeet")["bg"]) + (255,))
    y = 24
    for r in rows:
        x = 24
        for im in r:
            out.alpha_composite(im, (x, y))
            x += im.width + 24
        y += max(i.height for i in r) + 24
    out.save(path)


def main():
    a = sys.argv[1:]
    if a[:1] == ["build"]:
        print(build(a[1] if len(a) > 1 else ""))
    elif a[:1] == ["sheet"] and len(a) > 1:
        sheet(a[1])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
