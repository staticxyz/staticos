#!/usr/bin/env python3
"""Обзор рабочих столов — SUPER+G. Сделан по образцу обзора niri (21.09.2026).

Зачем свой. Готовых плагинов обзора под ленту (раскладка scrolling) и
Hyprland 0.56 нет: hyprexpo снят с поддержки и ленту шире экрана рисует в
натуральную величину, hyprland-scroll-overview заканчивается на 0.55.4.
Разбор — в ~/.config/hypr/NOTES-обзор-столов.md. Этот обзор не плагин: он
живёт на `hyprctl -j`, grim и GTK-слое, поэтому обновления Hyprland его не ломают.

Как выглядит (как в niri). Экран «отъезжает» вдвое: текущий стол становится
уменьшенным экраном по центру, столы выше и ниже выглядывают сверху и снизу,
колонки ленты за краем экрана видны по бокам. У каждого монитора свой обзор
со своими столами; клавиатура — у монитора, на котором нажали SUPER+G.

Откуда картинка. Текущий стол — настоящий снимок экрана (grim), поэтому отъезд
начинается ровно с того, что было на экране. Hyprland не рисует окна неактивных
столов, так что их «экран» собирается: обои + полоса бара + последние снимки
окон из кэша (~/.cache/hypr-overview). Окно, которого ещё ни разу не было на
экране при открытом обзоре, показывается карточкой с иконкой и заголовком.

Клавиши — те же оси, что в конфиге niri и в биндах Hyprland:
    H / L, ← / →      колонка левее / правее
    J / K, ↓ / ↑      стол ниже / выше
    CTRL + J / K      окно ниже / выше внутри колонки (стопка)
    Enter             перейти           1..9, 0   сразу на стол N
    Esc, q, SUPER+G   закрыть           колесо    листать столы
Мышь: щелчок по окну — перейти к нему, по столу — на стол, мимо — закрыть.
Кириллица на тех же клавишах работает (р/д/о/л, й).

Проверка без вывода на экран:  overview.py --png /tmp/o.png [--mon DP-4] [--p 0.5]
"""
import json
import math
import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib, GtkLayerShell  # noqa: E402
from gi.repository import Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import popup_theme  # noqa: E402

CACHE = os.path.expanduser("~/.cache/hypr-overview")
WS_ORDER = os.path.expanduser("~/.local/state/hypr/ws-order.json")
WALL_STATE = os.path.expanduser("~/.cache/matugen/wallpaper")

ZOOM = 0.5            # во сколько раз уменьшается стол; в niri по умолчанию те же 0.5
WS_GAP = 56           # просвет между столами по вертикали
SIDE = 36             # выбранное окно не подпускаем к боковому краю ближе этого
RADIUS = 10           # скругление «экрана» стола
THUMB_MAX = 960       # ширина снимка окна в кэше: ровно под ZOOM 0.5 на 1920
OPEN_FRAMES = 14      # кадров на отъезд при открытии (~230 мс)
CLOSE_FRAMES = 9      # и на возврат
EASE = 0.24           # доля пути за кадр у прокрутки: меньше — мягче

KEYS_LEFT = ("Left", "h", "Cyrillic_er")
KEYS_RIGHT = ("Right", "l", "Cyrillic_de")
KEYS_DOWN = ("Down", "j", "Cyrillic_o")
KEYS_UP = ("Up", "k", "Cyrillic_el")
KEYS_CLOSE = ("Escape", "q", "Cyrillic_shorti")
KEYS_GO = ("Return", "KP_Enter", "space")


# ── данные Hyprland ─────────────────────────────────────────────────────────
def hypr(*args):
    out = subprocess.run(["hyprctl", *args, "-j"], capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except ValueError:
        return []


def dispatch(expr):
    subprocess.run(["hyprctl", "dispatch", expr], capture_output=True, text=True)


def lua_call(call, fallback):
    """Глобальная Lua-функция конфига (ws_anim.lua) либо, если её нет, прежний
    диспетчер. Из обзора стол меняется МГНОВЕННО (второй аргумент true): обзор сам
    наезжает на выбранный стол, и сдвиг Hyprland под ним был бы виден хвостом."""
    r = subprocess.run(["hyprctl", "eval", call], capture_output=True, text=True)
    if (r.stdout or "").strip() != "ok":
        dispatch(fallback)


def ws_order():
    try:
        with open(WS_ORDER) as f:
            return [int(x) for x in json.load(f)["order"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def hexrgb(color):
    c = color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


def to_surface(pixbuf):
    """Pixbuf → поверхность cairo один раз. Gdk.cairo_set_source_pixbuf делает
    это преобразование на КАЖДЫЙ кадр, а для снимка 1920×1080 это миллисекунды."""
    return Gdk.cairo_surface_create_from_pixbuf(pixbuf, 1, None)


class Win:
    def __init__(self, c):
        self.addr = c["address"]
        self.cls = c.get("class") or c.get("initialClass") or ""
        self.title = c.get("title") or self.cls
        self.pid = c.get("pid", 0)
        self.x, self.y = c["at"]
        self.w, self.h = c["size"]
        self.ws = c["workspace"]["id"]
        self.floating = bool(c.get("floating"))
        self.fullscreen = (c.get("fullscreen") or 0) > 0
        self.fh = c.get("focusHistoryID", 999)
        self.thumb = None                  # поверхность cairo
        self.thumb_pix = None              # свежий снимок, ждёт записи в кэш
        self.on_shot = False               # окно целиком видно на снимке экрана

    def cache_path(self):
        # Адрес закрытого окна Hyprland отдаёт новому (проверено 14.09.2026 в
        # ribbon_binds.lua), поэтому в ключе ещё процесс и класс.
        safe = "".join(ch if ch.isalnum() else "_" for ch in self.cls)[:40]
        return os.path.join(CACHE, "%s-%s-%s.png" % (self.addr, self.pid, safe))


class Row:
    def __init__(self, wsid, name, mon):
        self.id, self.name, self.mon = wsid, name, mon
        self.wins = []
        self.active = False                # активный стол своего монитора
        self.shown = False                 # сейчас на экране (в т.ч. открытый спецстол)
        self.shot = self.shot_small = None # снимок экрана: полный и уменьшенный
        self.pan = self.pan_to = 0.0       # горизонтальный сдвиг ленты в обзоре

    def label(self):
        return self.name.replace("special:", "") if self.id < 0 else str(self.id)


def collect():
    """{имя монитора: [Row…]}, список мониторов, адрес активного окна."""
    mons = hypr("monitors")
    for m in mons:
        k = m.get("scale") or 1            # width/height у hyprctl физические,
        m["lw"], m["lh"] = m["width"] / k, m["height"] / k   # координаты окон — логические
    clients = [Win(c) for c in hypr("clients")
               if c.get("mapped") and not c.get("hidden") and c["size"][0] > 1]
    spaces = {w["id"]: w for w in hypr("workspaces")}
    active = hypr("activewindow")
    active_addr = active.get("address") if isinstance(active, dict) else None
    rank = {wsid: i for i, wsid in enumerate(ws_order())}

    per_mon = {}
    for m in mons:
        ids = [i for i, w in spaces.items() if w.get("monitor") == m["name"]]
        special_open = m.get("specialWorkspace", {}).get("id") or 0
        rows = []
        # Порядок — как в баре (ws_order.py), спецстолы в конце: они вне счёта.
        for wsid in sorted(ids, key=lambda i: (i < 0, rank.get(i, 10 ** 6), i)):
            r = Row(wsid, spaces[wsid].get("name", str(wsid)), m)
            r.wins = sorted((c for c in clients if c.ws == wsid), key=lambda c: (c.floating, c.x, c.y))
            r.active = (m["activeWorkspace"]["id"] == wsid)
            r.shown = (special_open == wsid) if special_open else r.active
            if r.wins or r.active:
                rows.append(r)
        per_mon[m["name"]] = rows
    return per_mon, mons, active_addr


# ── снимки ──────────────────────────────────────────────────────────────────
def grab(mon_name):
    """Снимок монитора без сжатия (ppm быстрее png в разы). None, если экран
    недоступен — например, Hyprland сейчас на неактивном терминале."""
    try:
        raw = subprocess.run(["grim", "-t", "ppm", "-o", mon_name, "-"],
                             capture_output=True, timeout=0.8).stdout
        if not raw:
            return None
        loader = GdkPixbuf.PixbufLoader.new_with_type("pnm")
        loader.write(raw)
        loader.close()
        return loader.get_pixbuf()
    except Exception:
        return None


def overlaps(a, b):
    return not (a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y)


def take_shots(per_mon):
    """Снимает каждый монитор, отдаёт снимок видимому столу и режет из него окна."""
    os.makedirs(CACHE, exist_ok=True)
    dead = False
    for name, rows in per_mon.items():
        row = next((r for r in rows if r.shown), None)
        if row is None or dead:
            continue
        pix = grab(name)
        if pix is None:                     # один не снялся — не снимутся и остальные
            dead = True
            continue
        m = row.mon
        k = pix.get_width() / m["lw"]
        row.shot = to_surface(pix)
        row.shot_small = to_surface(pix.scale_simple(
            max(1, int(m["lw"] * ZOOM)), max(1, int(m["lh"] * ZOOM)), GdkPixbuf.InterpType.BILINEAR))
        full = [w for w in row.wins if w.fullscreen]
        for w in row.wins:
            inside = (w.x >= m["x"] and w.y >= m["y"]
                      and w.x + w.w <= m["x"] + m["lw"] and w.y + w.h <= m["y"] + m["lh"])
            covered = (full and w not in full) or any(
                o is not w and o.floating and not w.floating and overlaps(o, w) for o in row.wins)
            w.on_shot = inside
            if not inside or covered:       # иначе в кэш уйдёт огрызок
                continue
            try:
                sub = pix.new_subpixbuf(int((w.x - m["x"]) * k), int((w.y - m["y"]) * k),
                                        max(1, int(w.w * k)), max(1, int(w.h * k)))
                f = min(1.0, THUMB_MAX / sub.get_width())
                small = sub.scale_simple(max(1, int(sub.get_width() * f)),
                                         max(1, int(sub.get_height() * f)),
                                         GdkPixbuf.InterpType.BILINEAR)
                w.thumb, w.thumb_pix = to_surface(small), small
            except Exception:
                pass


def load_cached(per_mon):
    alive = set()
    for rows in per_mon.values():
        for r in rows:
            for w in r.wins:
                alive.add(os.path.basename(w.cache_path()))
                if w.thumb is None and os.path.exists(w.cache_path()):
                    try:
                        w.thumb = to_surface(GdkPixbuf.Pixbuf.new_from_file(w.cache_path()))
                    except Exception:
                        pass
    return alive


def save_cache(per_mon, alive):
    """Запись свежих снимков и уборка старых — в фоне, уже после показа обзора."""
    for rows in per_mon.values():
        for r in rows:
            for w in r.wins:
                if w.thumb_pix is not None:
                    try:
                        w.thumb_pix.savev(w.cache_path(), "png", ["compression"], ["1"])
                    except Exception:
                        pass
                    w.thumb_pix = None
    try:
        for name in os.listdir(CACHE):
            if name.endswith(".png") and name not in alive:
                os.remove(os.path.join(CACHE, name))
    except OSError:
        pass


def wallpapers():
    """{монитор: путь к обоям}. awww знает обои каждого монитора; запасной путь —
    файл состояния matugen (он один на всех и бывает от прошлых обоев)."""
    found = {}
    try:
        out = subprocess.run(["awww", "query"], capture_output=True, text=True, timeout=0.5).stdout
        for line in out.splitlines():
            if "image:" in line:
                name = line.lstrip(": ").split(":")[0].strip()
                found[name] = line.split("image:", 1)[1].strip()
    except Exception:
        pass
    try:
        with open(WALL_STATE) as f:
            found.setdefault("*", f.read().strip())
    except OSError:
        pass
    return found


def cover(path, w, h):
    """Картинка, вписанная в w×h с обрезкой краёв (как обои на экране)."""
    try:
        _fmt, pw, ph = GdkPixbuf.Pixbuf.get_file_info(path)
        k = max(w / pw, h / ph)
        pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, int(pw * k) + 1, int(ph * k) + 1, True)
        x, y = (pix.get_width() - w) // 2, (pix.get_height() - h) // 2
        return to_surface(pix.new_subpixbuf(max(0, x), max(0, y), w, h))
    except Exception:
        return None


# ── иконки ──────────────────────────────────────────────────────────────────
class Icons:
    """Иконка по классу окна. Обход всех .desktop-файлов стоит ~100 мс — почти
    половину запуска, — поэтому найденное имя иконки запоминается в icons.json,
    и обход нужен только для класса, который встретился впервые."""
    MEMO = os.path.join(CACHE, "icons.json")

    def __init__(self):
        self.index = None
        self.cache = {}
        self.theme = Gtk.IconTheme.get_default()
        self.dirty = False
        try:
            with open(self.MEMO, encoding="utf-8") as f:
                self.memo = json.load(f)
        except (OSError, ValueError):
            self.memo = {}

    def save(self):
        if not self.dirty:
            return
        try:
            os.makedirs(CACHE, exist_ok=True)
            with open(self.MEMO, "w", encoding="utf-8") as f:
                json.dump(self.memo, f, ensure_ascii=False)
            self.dirty = False
        except OSError:
            pass

    def build(self):
        self.index = {}
        for info in Gio.AppInfo.get_all():
            icon = info.get_icon()
            if icon is None:
                continue
            name = icon.to_string()
            keys = set()
            wm = getattr(info, "get_startup_wm_class", lambda: None)()
            if wm:
                keys.add(wm.lower())
            did = (info.get_id() or "").lower()
            if did.endswith(".desktop"):
                did = did[:-8]
            if did:
                keys.update((did, did.split(".")[-1]))
            exe = os.path.basename(info.get_executable() or "").lower()
            if exe:
                keys.add(exe)
            for k in keys:
                self.index.setdefault(k, name)

    def get(self, cls, size):
        size = max(16, int(size))
        key = (cls, size)
        if key in self.cache:
            return self.cache[key]
        pix = self.load(self.memo.get(cls), size)
        if pix is None:
            if self.index is None:
                self.build()
            low = cls.lower()
            tries = [low, low.split(".")[-1], low.split("-")[0], low.split(" ")[0]]
            names = [self.index[t] for t in tries if t in self.index] + tries
            for n in names + ["application-x-executable"]:
                pix = self.load(n, size)
                if pix:
                    if self.memo.get(cls) != n:
                        self.memo[cls], self.dirty = n, True
                    break
        self.cache[key] = to_surface(pix) if pix else None
        return self.cache[key]

    def load(self, name, size):
        if not name:
            return None
        try:
            if os.path.isabs(name):
                return GdkPixbuf.Pixbuf.new_from_file_at_size(name, size, size)
            if self.theme.has_icon(name):
                return self.theme.load_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE)
        except Exception:
            pass
        return None


# ── сцена одного монитора ───────────────────────────────────────────────────
class Scene:
    def __init__(self, mon, rows, active_addr, pal, icons, wall):
        self.mon, self.rows, self.pal, self.icons = mon, rows, pal, icons
        self.W, self.H = int(mon["lw"]), int(mon["lh"])
        self.vw, self.vh = self.W * ZOOM, self.H * ZOOM
        self.wall = wall                                   # обои, уже в размер стола
        self.bar = None                                    # полоса бара со снимка
        self.home = next((i for i, r in enumerate(rows) if r.shown),
                         next((i for i, r in enumerate(rows) if r.active), 0))
        self.row_i = self.home
        self.scroll = float(self.home)
        self.hover = None

        home = rows[self.home] if rows else None
        self.sel = None
        if home:
            self.sel = next((w for w in home.wins if w.addr == active_addr), None) or min(
                home.wins, key=lambda w: w.fh, default=None)
            top = int(mon.get("reserved", [0, 0, 0, 0])[1] * ZOOM)
            if home.shot_small is not None and top > 0 and not any(w.fullscreen for w in home.wins):
                self.bar = (home.shot_small, top)

    # геометрия
    def row_rect(self, i):
        r = self.rows[i]
        return ((self.W - self.vw) / 2 + r.pan,
                (self.H - self.vh) / 2 + (i - self.scroll) * (self.vh + WS_GAP),
                self.vw, self.vh)

    def win_rect(self, i, w):
        vx, vy, _vw, _vh = self.row_rect(i)
        m = self.mon
        return (vx + (w.x - m["x"]) * ZOOM, vy + (w.y - m["y"]) * ZOOM, w.w * ZOOM, w.h * ZOOM)

    def retarget(self):
        """Лента выбранного стола сдвигается, чтобы выбранное окно было видно."""
        if self.sel is None or not self.rows:
            return
        r = self.rows[self.row_i]
        base = (self.W - self.vw) / 2 + (self.sel.x - self.mon["x"]) * ZOOM
        x0, x1 = base + r.pan_to, base + r.pan_to + self.sel.w * ZOOM
        if x1 > self.W - SIDE:
            r.pan_to -= x1 - (self.W - SIDE)
            x0 = base + r.pan_to
        if x0 < SIDE:
            r.pan_to += SIDE - x0

    def advance(self):
        """Шаг плавной прокрутки. True, пока что-то ещё едет."""
        moving = False
        d = self.row_i - self.scroll
        if abs(d) > 0.002:
            self.scroll += d * EASE
            moving = True
        else:
            self.scroll = float(self.row_i)
        for r in self.rows:
            d = r.pan_to - r.pan
            if abs(d) > 0.4:
                r.pan += d * EASE
                moving = True
            else:
                r.pan = r.pan_to
        return moving

    # рисование
    @staticmethod
    def rounded(cr, x, y, w, h, rad):
        rad = max(0.0, min(rad, w / 2, h / 2))
        cr.new_sub_path()
        cr.arc(x + w - rad, y + rad, rad, -math.pi / 2, 0)
        cr.arc(x + w - rad, y + h - rad, rad, 0, math.pi / 2)
        cr.arc(x + rad, y + h - rad, rad, math.pi / 2, math.pi)
        cr.arc(x + rad, y + rad, rad, math.pi, 1.5 * math.pi)
        cr.close_path()

    def text(self, cr, s, x, y, width, size, color, alpha=1.0, bold=False, align="left"):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription(
            "JetBrainsMono Nerd Font %s%d" % ("Bold " if bold else "", size)))
        lay.set_width(int(max(1, width) * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
        lay.set_alignment({"left": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER,
                           "right": Pango.Alignment.RIGHT}[align])
        lay.set_text(s, -1)
        cr.set_source_rgba(*hexrgb(color), alpha)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)

    def transform(self, cr, p, focus_i):
        """p = 1 — обзор; p = 0 — стол focus_i занимает весь экран.
        Отъезд при открытии и наезд при закрытии — одно и то же преобразование."""
        if p >= 1 or not self.rows:
            return
        vx, vy, vw, vh = self.row_rect(focus_i)
        cx, cy = vx + vw / 2, vy + vh / 2
        g = 1 / ZOOM + (1 - 1 / ZOOM) * p
        cr.translate(self.W / 2 + (cx - self.W / 2) * p, self.H / 2 + (cy - self.H / 2) * p)
        cr.scale(g, g)
        cr.translate(-cx, -cy)

    def draw(self, cr, p=1.0, focus_i=None):
        pal = self.pal
        # подложка: темнее самого стола, как backdrop в niri; под ней — размытие Hyprland
        r, g, b = hexrgb(pal["surface"])
        cr.set_source_rgba(r * 0.45, g * 0.45, b * 0.45, 0.88 * p)
        cr.paint()
        cr.save()
        self.transform(cr, p, self.home if focus_i is None else focus_i)
        for i in range(len(self.rows)):
            _vx, vy, _vw, vh = self.row_rect(i)
            if p >= 1 and (vy > self.H + 40 or vy + vh < -40):
                continue                                   # за экраном — не рисуем
            self.draw_row(cr, i, p < 1)
        cr.restore()

    def draw_row(self, cr, i, sharp):
        pal, r = self.pal, self.rows[i]
        vx, vy, vw, vh = self.row_rect(i)

        for k, a in ((14, 0.05), (9, 0.08), (5, 0.12), (2, 0.16)):     # мягкая тень стола
            self.rounded(cr, vx - k, vy - k + 4, vw + 2 * k, vh + 2 * k, RADIUS + k)
            cr.set_source_rgba(0, 0, 0, a)
            cr.fill()

        if r.shot_small is not None:
            # Сначала окна за краем экрана (видны по бокам), поверх — настоящий
            # снимок: всё, что было на экране, выглядит ровно как было.
            for w in r.wins:
                if not w.on_shot:
                    self.draw_win(cr, i, w)
            cr.save()
            self.rounded(cr, vx, vy, vw, vh, RADIUS)
            cr.clip()
            if sharp and r.shot is not None:               # на отъезде — полный снимок: резкий
                cr.translate(vx, vy)
                cr.scale(vw / r.shot.get_width(), vh / r.shot.get_height())
                cr.set_source_surface(r.shot, 0, 0)
                cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            else:
                cr.set_source_surface(r.shot_small, vx, vy)
            cr.paint()
            cr.restore()
        else:
            cr.save()
            self.rounded(cr, vx, vy, vw, vh, RADIUS)
            cr.clip()
            if self.wall is not None:
                cr.set_source_surface(self.wall, vx, vy)
            else:
                cr.set_source_rgba(*hexrgb(pal["surface_container"]), 1)
            cr.paint()
            if self.bar is not None:
                surf, top = self.bar
                cr.rectangle(vx, vy, vw, top)
                cr.clip()
                cr.set_source_surface(surf, vx, vy)
                cr.paint()
            cr.restore()
            for w in r.wins:
                self.draw_win(cr, i, w)

        # рамка выбора и наведения — поверх всего, в том числе поверх снимка
        for w in r.wins:
            if w is self.sel or w is self.hover:
                x, y, ww, hh = self.win_rect(i, w)
                self.rounded(cr, x - 1.5, y - 1.5, ww + 3, hh + 3, 4)
                cr.set_source_rgba(*hexrgb(pal["primary"]), 1.0 if w is self.sel else 0.5)
                cr.set_line_width(3 if w is self.sel else 2)
                cr.stroke()

        # номер стола — единственная подпись; в niri её нет, но столы здесь нумерованы
        left = min([self.win_rect(i, w)[0] for w in r.wins] + [vx])
        self.text(cr, r.label(), left - 150, vy + vh / 2 - 12, 132, 14,
                  pal["on_surface"], 0.85 if i == self.row_i else 0.35, bold=True, align="right")

    def draw_win(self, cr, i, w):
        pal = self.pal
        x, y, ww, hh = self.win_rect(i, w)
        if ww < 3 or hh < 3:
            return
        cr.save()
        self.rounded(cr, x, y, ww, hh, 3)
        cr.clip()
        if w.thumb is not None:
            cr.translate(x, y)
            cr.scale(ww / w.thumb.get_width(), hh / w.thumb.get_height())
            cr.set_source_surface(w.thumb, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            cr.paint()
        else:
            cr.set_source_rgba(*hexrgb(pal["surface_container"]), 0.97)
            cr.paint()
            size = min(64, ww * 0.5, hh * 0.42)
            icon = self.icons.get(w.cls, size) if size >= 14 else None
            if icon is not None:
                cr.set_source_surface(icon, x + (ww - icon.get_width()) / 2,
                                      y + (hh - icon.get_height()) / 2 - (10 if hh > 80 else 0))
                cr.paint()
            if ww > 80 and hh > 80:
                self.text(cr, w.title, x + 8, y + hh / 2 + size / 2, ww - 16, 9,
                          pal["on_surface"], 0.85, align="center")
        cr.restore()
        self.rounded(cr, x, y, ww, hh, 3)                  # тонкая рамка, как у неактивного окна
        cr.set_source_rgba(*hexrgb(pal["primary"]), 0.22)
        cr.set_line_width(1)
        cr.stroke()

    # навигация
    def hit(self, px, py):
        """(окно, индекс стола) под точкой; (None, i) — пустое место стола; (None, None) — мимо."""
        for i, r in enumerate(self.rows):
            for w in reversed(r.wins):                     # плавающие нарисованы поверх
                x, y, ww, hh = self.win_rect(i, w)
                if x <= px <= x + ww and y <= py <= y + hh:
                    return w, i
        for i in range(len(self.rows)):
            vx, vy, vw, vh = self.row_rect(i)
            if vx <= px <= vx + vw and vy <= py <= vy + vh:
                return None, i
        return None, None

    def columns(self, r):
        cols = []
        for w in sorted(r.wins, key=lambda w: (w.x, w.y)):
            if cols and not w.floating and not cols[-1][0].floating and abs(cols[-1][0].x - w.x) <= 2:
                cols[-1].append(w)                         # та же колонка — стопка
            else:
                cols.append([w])
        return cols

    def move_col(self, d):
        if self.sel is None:
            return
        cols = self.columns(self.rows[self.row_i])
        ci = next(k for k, c in enumerate(cols) if self.sel in c) + d
        if 0 <= ci < len(cols):
            cy = self.sel.y + self.sel.h / 2
            self.sel = min(cols[ci], key=lambda w: abs(w.y + w.h / 2 - cy))

    def move_stack(self, d):
        if self.sel is None:
            return
        col = next(c for c in self.columns(self.rows[self.row_i]) if self.sel in c)
        k = col.index(self.sel) + d
        if 0 <= k < len(col):
            self.sel = col[k]

    def move_row(self, d):
        i = self.row_i + d
        if not 0 <= i < len(self.rows):
            return
        self.row_i = i
        # На новом столе — окно, бывшее в фокусе последним.
        self.sel = min(self.rows[i].wins, key=lambda w: w.fh, default=None)


# ── окна-слои ───────────────────────────────────────────────────────────────
def go_window(w):
    lua_call('ws_focus_window("%s", true)' % w.addr, 'hl.dsp.focus({ window = "address:%s" })' % w.addr)


def go_row(r):
    if r.id < 0:
        if not r.shown:
            dispatch('hl.dsp.workspace.toggle_special("%s")' % r.label())
    else:
        lua_call("ws_goto(%d, true)" % r.id, "hl.dsp.focus({ workspace = %d })" % r.id)


class Overlay(Gtk.Window):
    def __init__(self, app, scene, keyboard):
        super().__init__()
        self.app, self.scene = app, scene
        self.p, self.phase, self.frame, self.focus_i = 0.0, "open", 0, scene.home
        self.timer = None
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-overview")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, -1)         # поверх бара, на весь экран
        GtkLayerShell.set_keyboard_mode(
            self, GtkLayerShell.KeyboardMode.EXCLUSIVE if keyboard else GtkLayerShell.KeyboardMode.NONE)
        gm = self.gdk_monitor(scene.mon)
        if gm is not None:
            GtkLayerShell.set_monitor(self, gm)
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        area = Gtk.DrawingArea()
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        area.connect("draw", self.on_draw)
        area.connect("button-press-event", self.on_click)
        area.connect("motion-notify-event", self.on_motion)
        area.connect("scroll-event", self.on_scroll)
        self.add(area)
        self.area = area
        self.connect("key-press-event", self.on_key)
        self.kick()

    @staticmethod
    def gdk_monitor(mon):
        # У Gdk на Wayland нет имени разъёма — сопоставляем по геометрии.
        d = Gdk.Display.get_default()
        for i in range(d.get_n_monitors()):
            g = d.get_monitor(i).get_geometry()
            if (g.x, g.y) == (mon["x"], mon["y"]):
                return d.get_monitor(i)
        return None

    def kick(self):
        if self.timer is None:
            self.timer = GLib.timeout_add(16, self.tick)

    def tick(self):
        moving = self.scene.advance()
        if self.phase == "open":
            self.frame += 1
            k = min(1.0, self.frame / OPEN_FRAMES)
            self.p = 1 - (1 - k) ** 3
            if k >= 1:
                self.phase, self.p = "idle", 1.0
            moving = True
        elif self.phase == "close":
            self.frame += 1
            k = min(1.0, self.frame / CLOSE_FRAMES)
            self.p = 1 - k * k * (3 - 2 * k)
            if k >= 1:
                self.timer = None
                self.app.closed(self)
                return False
            moving = True
        self.area.queue_draw()
        if not moving:
            self.timer = None
        return moving

    def begin_close(self, focus_i):
        if self.phase == "close":
            return
        self.phase, self.frame, self.focus_i = "close", 0, focus_i
        self.kick()

    def on_draw(self, _area, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.scene.draw(cr, self.p, self.focus_i)

    # ввод
    def on_motion(self, _a, ev):
        if self.phase != "idle":
            return
        w, _i = self.scene.hit(ev.x, ev.y)
        if w is not self.scene.hover:
            self.scene.hover = w
            self.area.queue_draw()

    def on_scroll(self, _a, ev):
        if self.phase != "idle":
            return
        d = 0
        if ev.direction == Gdk.ScrollDirection.DOWN:
            d = 1
        elif ev.direction == Gdk.ScrollDirection.UP:
            d = -1
        elif ev.direction == Gdk.ScrollDirection.SMOOTH:
            _ok, _dx, dy = ev.get_scroll_deltas()
            d = 1 if dy > 0.5 else -1 if dy < -0.5 else 0
        if d:
            self.scene.move_row(d)
            self.scene.retarget()
            self.kick()

    def on_click(self, _a, ev):
        if self.phase != "idle":
            return
        s = self.scene
        w, i = s.hit(ev.x, ev.y)
        if w is not None:
            go_window(w)
            self.app.finish(self, i)
        elif i is not None:
            go_row(s.rows[i])
            self.app.finish(self, i)
        else:
            self.app.finish(None, None)

    def on_key(self, _w, ev):
        if self.phase == "close":
            return True
        s = self.scene
        name = Gdk.keyval_name(ev.keyval) or ""
        key = name if len(name) > 1 else name.lower()
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        if key in KEYS_CLOSE or (key in ("g", "Cyrillic_pe") and ev.state & Gdk.ModifierType.SUPER_MASK):
            self.app.finish(None, None)
            return True
        if key in KEYS_LEFT:
            s.move_col(-1)
        elif key in KEYS_RIGHT:
            s.move_col(1)
        elif key in KEYS_DOWN:
            s.move_stack(1) if ctrl else s.move_row(1)
        elif key in KEYS_UP:
            s.move_stack(-1) if ctrl else s.move_row(-1)
        elif key in KEYS_GO:
            if s.sel is not None:
                go_window(s.sel)
            elif s.rows:
                go_row(s.rows[s.row_i])
            self.app.finish(self, s.row_i)
            return True
        elif key in tuple("0123456789") or (key.startswith("KP_") and key[3:].isdigit()):
            n = int(key[-1]) or 10
            lua_call("ws_goto(%d, true)" % n, "hl.dsp.focus({ workspace = %d })" % n)
            i = next((k for k, r in enumerate(s.rows) if r.id == n), None)
            self.app.finish(self if i is not None else None, i)
            return True
        s.retarget()
        self.kick()
        return True


class App:
    def __init__(self, scenes, focused_name):
        self.overlays = [Overlay(self, sc, sc.mon["name"] == focused_name) for sc in scenes]
        self.open = len(self.overlays)

    def show(self):
        for o in self.overlays:
            o.show_all()

    def finish(self, chooser, row_i):
        """Выбор сделан (или отмена): каждый слой наезжает на свой стол и гаснет."""
        for o in self.overlays:
            o.begin_close(row_i if (o is chooser and row_i is not None) else o.scene.home)

    def closed(self, overlay):
        overlay.hide()
        self.open -= 1
        if self.open <= 0:
            Gtk.main_quit()


def build_scenes(per_mon, mons, active_addr):
    pal, icons, walls = popup_theme.palette(), Icons(), wallpapers()
    scenes = []
    for m in mons:
        rows = per_mon.get(m["name"]) or []
        if not rows:
            continue
        path = walls.get(m["name"]) or walls.get("*")
        wall = cover(path, int(m["lw"] * ZOOM), int(m["lh"] * ZOOM)) if path else None
        scenes.append(Scene(m, rows, active_addr, pal, icons, wall))
    return scenes, icons


def main():
    png = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv else None
    if png is None:
        popup_theme.single_instance(__file__)             # повторный SUPER+G закрывает

    per_mon, mons, active_addr = collect()
    take_shots(per_mon)                                   # ДО показа — иначе снимем сами себя
    alive = load_cached(per_mon)
    scenes, icons = build_scenes(per_mon, mons, active_addr)
    focused = next((m["name"] for m in mons if m.get("focused")), mons[0]["name"] if mons else "")

    if png:                                               # проверка без вывода на экран
        want = sys.argv[sys.argv.index("--mon") + 1] if "--mon" in sys.argv else focused
        sc = next((s for s in scenes if s.mon["name"] == want), scenes[0])
        p = float(sys.argv[sys.argv.index("--p") + 1]) if "--p" in sys.argv else 1.0
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, sc.W, sc.H)
        cr = cairo.Context(surf)
        cr.set_source_rgb(0.20, 0.24, 0.32)               # условные «размытые обои» под подложкой
        cr.paint()
        sc.retarget()
        sc.draw(cr, p, sc.home)
        surf.write_to_png(png)
        icons.save()
        print("монитор %s: столов %d, окон %d, со снимком %d, снимок экрана: %s, обои: %s" % (
            sc.mon["name"], len(sc.rows), sum(len(r.wins) for r in sc.rows),
            sum(1 for r in sc.rows for w in r.wins if w.thumb is not None),
            "есть" if any(r.shot for r in sc.rows) else "нет", "есть" if sc.wall else "нет"))
        return

    app = App(scenes, focused)
    app.show()
    threading.Thread(target=lambda: (save_cache(per_mon, alive), icons.save()), daemon=True).start()
    Gtk.main()


if __name__ == "__main__":
    main()
