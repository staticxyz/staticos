#!/usr/bin/env python3
"""Предпросмотр обоев на настоящем столе — для ленты SUPER+W (13.10.2026).

Просьба: «внизу живое мини-превью текущего стола, где показываются новые цвета на окнах
и виджетах, что были открыты. Ничего не применяется, пока не нажмёшь „применить“».

Как сделано. Перед тем как лента закроет экран, снимаем каждый монитор (grim, в
масштабе SCALE). Потом для выбранных обоев:
  1. Палитра — `matugen --dry-run -j hex` теми же ключами, что theme_changer.sh
     (scheme-vibrant, --prefer saturation, превью 512 px). Ничего не пишется на диск,
     кроме кэша уменьшенных копий.
  2. Где на снимке видны обои — сравниваем снимок с картинкой, которую сейчас
     показывает awww на этом мониторе (с той же обрезкой fill). Там подставляем
     новые обои (с размытием, если оно включено на мониторе).
  3. Всё остальное — окна, бар, виджеты — перекрашиваем: каждый пиксель, близкий к
     цвету старой палитры, сдвигается на разницу «новая − старая» этой роли.
     Цвета, далёкие от палитры (видео, фото, картинки в окнах), остаются как есть.
Получается то, что увидишь после «применить», с точностью до перерисовки самих
программ. Пиксельный режим обоев (wallpaper_pixel.py) в превью не повторяется.

Проверка без экрана:  wallpaper_preview.py --png out.png --wall ПУТЬ [--mon DP-4]
"""
import hashlib
import json
import os
import subprocess
import sys

import numpy as np

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wp_grab import SCALE, grim_cmd, niri_env, outputs  # noqa: E402,F401  (снимки — wp_grab.py)
CACHE = os.path.expanduser("~/.cache/wallpaper-thumbs")
CURRENT = os.path.expanduser("~/.cache/matugen/wallpaper")
SIGMA = 12.0                  # «близко к цвету палитры», в единицах 0–255
FAR = 30.0                    # дальше этого — пиксель не трогаем
WALL_NEAR, WALL_FAR = 8.0, 26.0   # разница со старыми обоями: обои ↔ уже не обои


# ── картинки ↔ numpy ────────────────────────────────────────────────────
def pix_to_np(pix):
    w, h, n, rs = pix.get_width(), pix.get_height(), pix.get_n_channels(), pix.get_rowstride()
    buf = np.frombuffer(pix.get_pixels(), dtype=np.uint8)
    if buf.size < rs * h:                       # последняя строка бывает без хвоста
        buf = np.concatenate([buf, np.zeros(rs * h - buf.size, np.uint8)])
    return buf[:rs * h].reshape(h, rs)[:, :w * n].reshape(h, w, n)[:, :, :3].astype(np.float32)


def np_to_pix(arr):
    a = np.ascontiguousarray(np.clip(arr, 0, 255).astype(np.uint8))
    h, w, _ = a.shape
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(a.tobytes()),
        GdkPixbuf.Colorspace.RGB, False, 8, w, h, w * 3)


def grab(mon, w, h, raw=None):
    """Снимок монитора в размере w×h (до того, как лента его закроет). raw — готовые
    байты ppm от wp_grab (снят заранее, параллельно загрузке GTK)."""
    try:
        if raw is None:
            raw = subprocess.run(grim_cmd(mon), capture_output=True, timeout=5,
                                 env=niri_env()).stdout
        loader = GdkPixbuf.PixbufLoader()
        loader.write(raw)
        loader.close()
        pix = loader.get_pixbuf()
    except Exception:
        return None
    if pix.get_width() != w or pix.get_height() != h:
        pix = pix.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
    return pix_to_np(pix)


def cover_file(path, w, h):
    """Где лежит готовая копия cover(path, w, h) (13.10.2026, ускорение листания)."""
    st = os.stat(path)
    key = hashlib.sha1(("%s|%d|%dx%d" % (path, st.st_mtime, w, h)).encode()).hexdigest()[:16]
    return os.path.join(CACHE, "cov-%s.jpg" % key)


def _cover_pix(path, w, h):
    _fmt, iw, ih = GdkPixbuf.Pixbuf.get_file_info(path)
    s = max(w / iw, h / ih)
    sw, sh = max(w, round(iw * s)), max(h, round(ih * s))
    pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, sw, sh, False)
    return pix.new_subpixbuf((sw - w) // 2, (sh - h) // 2, w, h).copy()


def warm_cover(path, w, h):
    """Положить в кэш копию обоев в размере снимка — фоном, пока лента открыта.
    Полноразмерная картинка декодируется 0,1–0,3 с, копия 1152×648 — сотые доли."""
    try:
        out = cover_file(path, w, h)
        if os.path.isfile(out):
            return out
        os.makedirs(CACHE, exist_ok=True)
        tmp = "%s.%x.tmp" % (out, id(object()))   # лента и превью могут писать разом
        _cover_pix(path, w, h).savev(tmp, "jpeg", ["quality"], ["94"])
        os.replace(tmp, out)
        return out
    except Exception:
        return None


def cover(path, w, h, cached=False):
    """Картинка «fill», как её кладёт awww: заполнить и обрезать по центру.
    cached — взять копию из кэша (warm_cover); для маски «где обои» — точная, без него."""
    try:
        if cached:
            f = warm_cover(path, w, h)
            if f:
                pix = GdkPixbuf.Pixbuf.new_from_file(f)
                if pix.get_width() == w and pix.get_height() == h:
                    return pix_to_np(pix)
        pix = _cover_pix(path, w, h)
    except Exception:
        return None
    return pix_to_np(pix)


def box_blur(a, sigma):
    """Гаусс ≈ три прохода прямоугольником (то же размытие, что magick -blur 0xσ)."""
    r = max(1, int(round(sigma)))
    for axis in (0, 1):
        for _ in range(3):
            pad = [(0, 0)] * 3
            pad[axis] = (r + 1, r)
            c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float32)
            hi = np.take(c, range(2 * r + 1, c.shape[axis]), axis=axis)
            lo = np.take(c, range(0, c.shape[axis] - 2 * r - 1), axis=axis)
            a = (hi - lo) / (2 * r + 1)
    return a


def blur_for(mon):
    """σ размытия обоев на мониторе в масштабе снимка; 0 — размытие выключено."""
    try:
        sys.path.insert(0, HERE)
        import wallpaper_blur
        if wallpaper_blur.get(mon) != "on":
            return 0.0
        return float(wallpaper_blur.radius().split("x")[-1]) * SCALE
    except Exception:
        return 0.0


def shown_now():
    """{монитор: картинка, которую awww показывает сейчас} (бывает размытая копия)."""
    out = {}
    try:
        txt = subprocess.run(["awww", "query"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return out
    for line in txt.splitlines():
        name = line.split(":")[1].strip() if line.count(":") >= 2 else ""
        if "image:" in line and name:
            out[name] = line.split("image:", 1)[1].strip()
    return out


# ── палитра ─────────────────────────────────────────────────────────────
def small_copy(path):
    """Уменьшенная копия, как в theme_changer.sh (512 px) — палитра выйдет та же."""
    st = os.stat(path)
    key = hashlib.sha1(("%s|%d" % (path, st.st_mtime)).encode()).hexdigest()[:16]
    out = os.path.join(CACHE, "pal-%s.png" % key)
    if not os.path.isfile(out):
        os.makedirs(CACHE, exist_ok=True)
        tmp = out + ".tmp.png"
        r = subprocess.run(["magick", "-define", "jpeg:size=1024x1024", path,
                            "-resize", "512x512", tmp], capture_output=True, timeout=60)
        if r.returncode != 0:
            return path
        os.replace(tmp, out)
    return out


def palette_of(path, mode=None):
    """{роль: (r,g,b)} — matugen --dry-run, ничего не применяет."""
    mode = mode or os.environ.get("MATUGEN_MODE", "dark")
    r = subprocess.run(["matugen", "image", small_copy(path), "-t", "scheme-vibrant", "-m", mode,
                        "--prefer", "saturation", "--dry-run", "-j", "hex", "-q"],
                       capture_output=True, text=True, timeout=30)
    data = json.loads(r.stdout)
    pal = {}
    for role, v in data.get("colors", {}).items():
        c = (v.get(mode) or v.get("default") or {}).get("color") if isinstance(v, dict) else None
        if not c and isinstance(v, str):
            c = v
        if c:
            pal[role] = c
    for role, v in data.get("base16", {}).items():
        c = (v.get(mode) or v.get("default") or {}).get("color")
        if c:
            pal["b16_" + role] = c
    # тоновые шкалы (primary 0–100 и т.д.): акценты виджетов и терминала берутся из них
    for name, tones in data.get("palettes", {}).items():
        for tone, v in (tones or {}).items():
            c = v.get("color") if isinstance(v, dict) else v
            if isinstance(c, str) and c.startswith("#"):
                pal["t_%s_%s" % (name, tone)] = c
    return {k: tuple(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) for k, c in pal.items()}


def remap(img, old, new):
    """Сдвинуть пиксели, близкие к старой палитре, на разницу «новая − старая».

    Сдвиг плавный по цвету, поэтому считаем его не для каждого пикселя, а таблицей
    на 32³ цветов (по 5 бит на канал) и берём по индексу: 0,05 с вместо 1,8 с.
    """
    roles = sorted(set(old) & set(new))
    o = np.array([old[k] for k in roles], np.float32)
    d = np.array([new[k] for k in roles], np.float32) - o
    o, idx = np.unique(o, axis=0, return_index=True)       # одинаковые роли — одна
    d = d[idx]
    g = (np.arange(32, dtype=np.float32) * 8 + 4)
    grid = np.stack(np.meshgrid(g, g, g, indexing="ij"), -1).reshape(-1, 3)
    d2 = np.maximum((grid ** 2).sum(1, keepdims=True) - 2 * grid @ o.T + (o ** 2).sum(1)[None], 0)
    w = np.exp(-d2 / (2 * SIGMA ** 2))
    far = np.exp(-(FAR ** 2) / (2 * SIGMA ** 2))           # вес «оставить как есть»
    shift = (w @ d) / (w.sum(1, keepdims=True) + far)
    q = img.astype(np.int32) >> 3
    return img + shift[(q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]]


# ── сборка превью ───────────────────────────────────────────────────────
def niri_json(what):
    try:
        return json.loads(subprocess.run(["niri", "msg", "-j", what], env=niri_env(),
                                         capture_output=True, timeout=3).stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def layout_edges():
    """Отступ от края экрана = gaps + struts (cfg/layout.kdl), и сами gaps."""
    gaps, struts = 16, {}
    try:
        txt = open(os.path.expanduser("~/.config/niri/cfg/layout.kdl")).read()
        import re
        m = re.search(r"^\s*gaps\s+(-?\d+)", txt, re.M)
        gaps = int(m.group(1)) if m else gaps
        for side in ("left", "right", "top", "bottom"):
            m = re.search(r"struts\s*\{[^}]*\b%s\s+(-?\d+)" % side, txt, re.S)
            struts[side] = int(m.group(1)) if m else 0
    except (OSError, ValueError):
        pass
    return gaps, {k: gaps + v for k, v in struts.items()}


def kitty_opacity():
    try:
        for line in open(os.path.expanduser("~/.config/kitty/kitty.conf")):
            if line.split()[:1] == ["background_opacity"]:
                return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 1.0


def window_rects(mon, W, H):
    """([варианты [(x, y, w, h, app_id)]], высота бара) — окна активного стола монитора.

    Своих координат у окон ленты niri не отдаёт (tile_pos_in_workspace_view пуст), и сдвиг
    ленты (куда она прокручена) тоже не сообщает. Порядок и ширины колонок известны, поэтому
    раскладку повторяем с точностью до одного числа — сдвига. С 13.10 center-focused-column
    "never": niri двигает ленту ровно настолько, чтобы колонка в фокусе влезла, значит, сдвиг —
    один из немногих: какая-то колонка прижата к левому или правому краю (или по центру).
    Варианты отдаём все, первый — «по центру»; какой верный, решает Shot.prepare по снимку.
    Вертикаль: стопка колонки прижата к низу рабочей зоны, сверху остаётся бар.
    """
    gaps, edge = layout_edges()
    wss = niri_json("workspaces") or []
    ws = next((w for w in wss if w.get("output") == mon and w.get("is_active")), None)
    wins = [w for w in (niri_json("windows") or []) if ws and w.get("workspace_id") == ws["id"]]
    bar = None
    cols = {}
    floats = []
    for w in wins:
        lay = w.get("layout") or {}
        pos = lay.get("pos_in_scrolling_layout")
        tw, th = lay.get("tile_size") or (0, 0)
        if w.get("is_floating") or not pos:
            p = lay.get("tile_pos_in_workspace_view")
            if p:
                floats.append((p[0], p[1], tw, th, w.get("app_id") or ""))
            continue
        cols.setdefault(pos[0], []).append((pos[1], tw, th, w))
    if not cols:
        return [floats], bar
    order = sorted(cols)
    widths = {c: max(t[1] for t in cols[c]) for c in order}
    focus = ws.get("active_window_id")
    fc = next((c for c in order for t in cols[c] if t[3]["id"] == focus), order[0])
    rel, x = {}, 0.0                                   # колонки на ленте, от первой
    for c in order:
        rel[c] = x
        x += widths[c] + gaps
    left, right = edge.get("left", gaps), W - edge.get("right", gaps)
    offs = [(W - widths[fc]) / 2 - rel[fc] if widths[fc] < W else -rel[fc]]   # по центру
    for c in order:
        offs += [left - rel[c], right - widths[c] - rel[c]]
    fx0 = lambda o: rel[fc] + o
    seen, cands = set(), []
    for o in offs:
        # колонка в фокусе видна целиком (если вообще влезает)
        if widths[fc] < W and (fx0(o) < -1 or fx0(o) + widths[fc] > W + 1):
            continue
        if round(o) in seen:
            continue
        seen.add(round(o))
        rects = []
        for c in order:
            stack = sorted(cols[c], key=lambda t: t[0])
            total = sum(t[2] for t in stack) + gaps * (len(stack) - 1)
            if total >= H:
                y = 0.0
            else:
                y = H - edge.get("bottom", 0) - total
                b = y - edge.get("top", 0)
                bar = b if bar is None else min(bar, b)
            for _, tw, th, w in stack:
                rects.append((rel[c] + o, y, tw, th, w.get("app_id") or ""))
                y += th + gaps
        cands.append(rects + floats)
    return cands or [floats], bar


def pick_layout(cands, shot, s):
    """Вариант раскладки, лучше всех совпавший со снимком: на предсказанных левых и правых
    краях колонок на снимке должен быть резкий перепад (рамка окна, край окна об обои).
    Сравнивать «где видны обои» нельзя: у Telegram фон чата — те же обои (13.10)."""
    if len(cands) < 2:
        return cands[0]
    gx = np.abs(np.diff(shot, axis=1)).max(-1)               # перепад по горизонтали
    h, w = gx.shape
    best, best_score = cands[0], 0.0
    for rects in cands:
        edges = []
        for x, y, rw, rh, _app in rects:
            y0, y1 = max(0, int(y * s)), min(h, int((y + rh) * s))
            for e in (int(x * s), int((x + rw) * s)):
                if 3 < e < w - 3 and y1 > y0:
                    edges.append(gx[y0:y1, e - 3:e + 2].max(1).mean())
        score = sum(edges) / len(edges) if edges else 0.0
        if score > best_score * 1.15:                        # центр — пока другой не лучше заметно
            best, best_score = rects, score
    return best


def widget_rects(mon):
    """Кандидаты-виджеты на мониторе: свои места и места «в гостях»."""
    try:
        conf = json.load(open(os.path.expanduser("~/.config/hypr/state/desktop-widgets.json")))
    except (OSError, ValueError):
        return []
    out = []
    for w in conf.get("widgets", []):
        ww, hh = int(w.get("w", 0)), int(w.get("h", 0))
        if w.get("output") == mon:
            out.append((int(w.get("x", 0)), int(w.get("y", 0)), ww, hh))
        g = w.get("guest") or {}
        if g.get("output") == mon:
            out.append((int(g.get("x", 0)), int(g.get("y", 0)), ww, hh))
    return out


class Desk:
    """Снимок одного монитора и всё, что нужно, чтобы перекрасить его под другие обои."""

    def __init__(self, name, w, h, raw=None):
        self.name = name
        self.W, self.H = w, h
        self.w, self.h = int(w * SCALE), int(h * SCALE)
        self.shot = grab(name, self.w, self.h, raw)
        self.mask = None          # 1 — тут видны обои
        self.see = None           # доля обоев, просвечивающих сквозь окно (kitty)
        self.old_wall = None
        self.sigma = blur_for(name)
        # раскладку снимаем сразу, вместе со снимком: через секунду она уже другая
        self.layouts, self.bar = window_rects(name, w, h)
        self.wins = self.layouts[0]
        self.widgets = widget_rects(name)

    def prepare(self, shown_path):
        """Где на снимке обои. Звать в фоне.

        Окна и бар — по раскладке niri; виджеты — по их конфигу, но только те, у которых
        рамка действительно видна на снимке (у скрытых на этом столе там просто обои).
        """
        if self.shot is None:
            return
        s = SCALE
        if shown_path and os.path.isfile(shown_path):
            self.old_wall = cover(shown_path, self.w, self.h)
        mask = np.ones((self.h, self.w, 1), np.float32)
        see = np.zeros((self.h, self.w, 1), np.float32)
        bar = self.bar if self.bar is not None else 26
        mask[:max(0, int(round(bar * s))), :] = 0
        op = kitty_opacity()
        self.wins = pick_layout(self.layouts, self.shot, s)
        for x, y, w, h, app in self.wins:
            x0, y0 = max(0, int(x * s)), max(0, int(y * s))
            x1, y1 = min(self.w, int((x + w) * s)), min(self.h, int((y + h) * s))
            if x1 > x0 and y1 > y0:
                mask[y0:y1, x0:x1] = 0
                if app == "kitty":
                    see[y0:y1, x0:x1] = 1 - op
        diff = None
        if self.old_wall is not None:
            diff = np.abs(self.shot - self.old_wall).max(-1)
        for x, y, w, h in self.widgets:
            x0, y0 = max(0, int(x * s)), max(0, int(y * s))
            x1, y1 = min(self.w, int((x + w) * s)), min(self.h, int((y + h) * s))
            if x1 - x0 < 6 or y1 - y0 < 6:
                continue
            if diff is not None:
                band = np.concatenate([diff[y0:y0 + 2, x0:x1].ravel(), diff[y1 - 2:y1, x0:x1].ravel(),
                                       diff[y0:y1, x0:x0 + 2].ravel(), diff[y0:y1, x1 - 2:x1].ravel()])
                if np.median(band) < WALL_FAR:      # рамки не видно — виджета здесь нет
                    continue
            mask[y0:y1, x0:x1] = 0
        self.mask, self.see = mask, see

    def render(self, wall, old_pal, new_pal):
        """numpy-кадр H×W×3: этот стол с обоями wall и палитрой new_pal."""
        if self.shot is None:
            return None
        img = remap(self.shot, old_pal, new_pal) if old_pal and new_pal else self.shot
        if self.mask is not None and wall:
            nw = cover(wall, self.w, self.h, cached=True)
            if nw is not None:
                if self.sigma:
                    nw = box_blur(nw, self.sigma)
                if self.old_wall is not None:
                    img = img + self.see * (nw - self.old_wall)
                img = img * (1 - self.mask) + nw * self.mask
        return img


def grab_all(early=None):
    """Снять все мониторы. Вернуть ({имя: Desk}, порядок слева направо, имя в фокусе).
    early — wp_grab.Grabs, запущенный заранее: тогда grim уже отработал."""
    if early is not None:
        mons, focused = early.mons, early.focused
        desks = {m[0]: Desk(m[0], m[3], m[4], early.raw(m[0])) for m in mons}
    else:
        mons, focused = outputs()
        desks = {m[0]: Desk(m[0], m[3], m[4]) for m in mons}
    return desks, [m[0] for m in mons], focused


def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", required=True)
    ap.add_argument("--wall", required=True)
    ap.add_argument("--mon")
    a = ap.parse_args(argv)
    desks, order, focused = grab_all()
    mon = a.mon or focused or (order[0] if order else None)
    desk = desks.get(mon)
    if desk is None or desk.shot is None:
        print("нет снимка монитора %s" % mon, file=sys.stderr)
        return 1
    desk.prepare(shown_now().get(mon))
    cur = open(CURRENT).read().strip()
    img = desk.render(a.wall, palette_of(cur), palette_of(a.wall))
    np_to_pix(img).savev(a.png, "png", [], [])
    print("%s → %s" % (mon, a.png))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
