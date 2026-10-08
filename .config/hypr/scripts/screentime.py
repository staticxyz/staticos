#!/usr/bin/env python3
"""Экранное время — окно в духе Noctalia и сводка текстом. 30.09.2026.

    screentime.py                     окно сверху по центру монитора под указателем
                                      (второй запуск закрывает его)
    screentime.py --week              то же, сразу на вкладке «7 дней»
    screentime.py --text [today|week] сводка простым текстом (для терминала и скриптов)
    screentime.py --json [today|week] то же в JSON
    screentime.py --render PNG [today|week]
                                      нарисовать окно без показа на экране (проверка вида)

Считает не это окно, а screentime_daemon.py: он пишет по файлу на день в
~/.local/share/jarvis/screentime/. Здесь — только чтение и показ.

Цвета программ на графиках выводятся из акцента обоев: первая берёт оттенок
акцента, остальные подбираются перебором так, чтобы соседние полосы в стопке
различались и при цветовой слепоте (протанопия/дейтеранопия, модель Machado
2009) — проверка та же, что у валидатора палитр из навыка dataviz. Пастельные
primary/secondary/tertiary matugen для этого не годятся: они почти одного
оттенка, и пять программ в стопке сливались бы.
"""
import datetime
import itertools
import json
import math
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# JARVIS_SCREENTIME_DIR — подложить другие данные (проверка вида на выдуманных днях).
DATA = os.environ.get("JARVIS_SCREENTIME_DIR") or os.path.expanduser("~/.local/share/jarvis/screentime")
LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "jarvis-screentime.lock")
FONT = "PxPlus HP 100LX 6x8 Jarvis"
TOP = 5                 # программ со своим цветом; остальные — «другие»
LIST_ROWS = 8           # строк в списке
WIDTH = 520             # ширина содержимого окна
DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
             "августа", "сентября", "октября", "ноября", "декабря"]

# Имена, которые .desktop даёт неудачно или не даёт вовсе. Английские —
# Пользователь просил названия программ по-английски (память appmem-names).
NAMES = {
    "kitty": "kitty terminal",
    "zen": "Zen Browser",
    "org.telegram.desktop": "Telegram",
    "YandexMusic": "Yandex Music",
    "org.xfce.mousepad": "Mousepad",
    "gamescope": "Game (gamescope)",
    "steam": "Steam",
    "unknown": "Unknown window",
}


# ── данные ────────────────────────────────────────────────────────────────

def poke_daemon():
    """Попросить счётчик записать свежие цифры (SIGHUP) и чуть подождать.
    Без этого окно показывало бы состояние до 30 с давности."""
    try:
        with open(LOCK) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGHUP)
        time.sleep(0.12)
        return True
    except (OSError, ValueError):
        return False


def daemon_running():
    import fcntl
    try:
        with open(LOCK) as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True         # замок занят — счётчик жив
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        pass
    return False


DETAIL_ROWS = 4            # сколько подстрок «что именно» показывать под программой


def load_day(date):
    try:
        with open(os.path.join(DATA, date.strftime("%Y-%m-%d") + ".json"), encoding="utf-8") as f:
            d = json.load(f)
        return {"apps": d.get("apps", {}), "hours": d.get("hours", {}),
                "details": d.get("details", {})}
    except (OSError, ValueError):
        return {"apps": {}, "hours": {}, "details": {}}


def week_dates(today=None):
    today = today or datetime.date.today()
    return [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]


def ranked(apps):
    return sorted(((a, s) for a, s in apps.items() if s >= 1), key=lambda x: -x[1])


def sum_details(days):
    """{app: {что: сек}} за несколько дней."""
    out = {}
    for d in days:
        for a, m in d.get("details", {}).items():
            o = out.setdefault(a, {})
            for k, v in m.items():
                o[k] = o.get(k, 0) + v
    return out


def detail_rows(app, sec, details, top=DETAIL_ROWS):
    """Подстроки под программой: что именно в ней было. Время без подписи
    (до 30.09.2026 счётчик подробностей не писал) не показываем: пользователь попросил
    убрать «Без разбивки»."""
    m = details.get(app) or {}
    if not m:
        return []
    rows = ranked(m)
    out = rows[:top]
    rest = sum(v for _k, v in rows[top:])
    if rest >= 1:
        out.append(("Другое", rest))
    return [(k, v) for k, v in out if v >= 30]


def sum_apps(dicts):
    out = {}
    for d in dicts:
        for a, s in d.items():
            out[a] = out.get(a, 0) + s
    return out


def fmt_dur(sec, short=False):
    """«2 ч 13 мин», «13 мин», «40 с». short — для подписей на графике: «2:13»."""
    sec = int(round(sec))
    h, m = sec // 3600, (sec % 3600) // 60
    if short:
        return "%d:%02d" % (h, m) if h else "%d м" % m
    if h:
        return "%d ч %d мин" % (h, m) if m else "%d ч" % h
    if m:
        return "%d мин" % m
    return "%d с" % sec


# ── названия и значки ─────────────────────────────────────────────────────

_app_cache = {}


def _gio():
    """Gio и класс DesktopAppInfo: в новых PyGObject он переехал в GioUnix,
    старое имя сыплет предупреждениями в вывод --text."""
    from gi.repository import Gio
    try:
        import gi
        gi.require_version("GioUnix", "2.0")
        from gi.repository import GioUnix
        return Gio, GioUnix.DesktopAppInfo
    except (ImportError, ValueError):
        return Gio, Gio.DesktopAppInfo


def _desktop_for(app_id):
    """.desktop по app_id — тот же порядок поиска, что у dock.app_info()."""
    Gio, DAI = _gio()
    if app_id.startswith("steam_app_"):
        # Игры Steam: app_id — номер игры, а ярлык ссылается на steam://rungameid/N.
        gid = app_id[len("steam_app_"):]
        for a in Gio.AppInfo.get_all():
            if isinstance(a, DAI) and ("rungameid/%s" % gid) in (a.get_commandline() or ""):
                return a
        return None
    for cand in (app_id, app_id.lower(), app_id.split(".")[-1].lower()):
        try:
            info = DAI.new(cand + ".desktop")
        except TypeError:
            info = None
        if info:
            return info
    for group in DAI.search(app_id) or []:
        for did in group:
            try:
                info = DAI.new(did)
            except TypeError:
                info = None
            if info:
                return info
    for a in Gio.AppInfo.get_all():
        if isinstance(a, DAI) and (a.get_startup_wm_class() or "").lower() == app_id.lower():
            return a
    return None


def app_info(app_id):
    """(английское имя, Gio.Icon или None)."""
    if app_id in _app_cache:
        return _app_cache[app_id]
    from gi.repository import Gio
    info = None
    try:
        info = _desktop_for(app_id)
    except Exception:
        info = None
    # get_string("Name") — непереведённое имя из .desktop; get_display_name()
    # отдал бы перевод по локали.
    name = NAMES.get(app_id) or (info.get_string("Name") if info else None)
    if not name:
        name = app_id.split(".")[-1].replace("-", " ").replace("_", " ")
        name = name[:1].upper() + name[1:]
    icon = info.get_icon() if info else None
    if icon is None:
        icon = Gio.ThemedIcon.new_with_default_fallbacks(app_id.lower())
    _app_cache[app_id] = (name, icon)
    return name, icon


def app_name(app_id):
    try:
        return app_info(app_id)[0]
    except Exception:
        return NAMES.get(app_id, app_id)


# ── сводки ────────────────────────────────────────────────────────────────

def focus_stats(date):
    """Фокус и помидор за день (focus_mode.day_stats) или None, если модуля нет."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import focus_mode
        return focus_mode.day_stats(date)
    except Exception:
        return None


def focus_line(st):
    """«Фокус 1 ч 20 мин · помидоров 3 · отвлечений 2» — или пусто."""
    if not st or (st["focus"] < 60 and not st["pomos"] and not st["blocks"]):
        return ""
    parts = ["Фокус " + fmt_dur(st["focus"])]
    if st["pomos"]:
        parts.append("помидоров %d" % st["pomos"])
    if st["blocks"]:
        parts.append("отвлечений %d" % st["blocks"])
    return " · ".join(parts)


def summary(kind):
    poke_daemon()
    today = datetime.date.today()
    if kind == "week":
        dates = week_dates(today)
        days = [load_day(d) for d in dates]
        apps = sum_apps(d["apps"] for d in days)
        det = sum_details(days)
        return {
            "period": "week", "from": dates[0].isoformat(), "to": today.isoformat(),
            "total": round(sum(apps.values())),
            "days": [{"date": d.isoformat(), "total": round(sum(x["apps"].values()))}
                     for d, x in zip(dates, days)],
            "apps": [{"app_id": a, "name": app_name(a), "seconds": round(s),
                      "details": [{"name": k, "seconds": round(v)} for k, v in detail_rows(a, s, det)]}
                     for a, s in ranked(apps)],
        }
    day = load_day(today)
    return {
        "period": "today", "date": today.isoformat(),
        "total": round(sum(day["apps"].values())),
        "hours": {h: round(sum(m.values())) for h, m in sorted(day["hours"].items(), key=lambda x: int(x[0]))},
        "apps": [{"app_id": a, "name": app_name(a), "seconds": round(s),
                  "details": [{"name": k, "seconds": round(v)} for k, v in detail_rows(a, s, day["details"])]}
                 for a, s in ranked(day["apps"])],
    }


def print_text(kind):
    s = summary(kind)
    if kind == "week":
        # Среднее — по дням, когда счётчик что-то записал: дни до его появления
        # и выключенный ноутбук не должны тянуть среднее к нулю.
        active = [d for d in s["days"] if d["total"] >= 60]
        avg = s["total"] / len(active) if active else 0
        print("Экранное время за 7 дней (%s — %s): %s, в среднем %s в день"
              % (s["from"], s["to"], fmt_dur(s["total"]), fmt_dur(avg)))
        fs = [focus_stats(datetime.date.fromisoformat(d["date"])) for d in s["days"]]
        if all(fs):
            tot = {"focus": sum(f["focus"] for f in fs), "pomos": sum(f["pomos"] for f in fs),
                   "blocks": sum(f["blocks"] for f in fs)}
            fl = focus_line(tot)
            if fl:
                print("  " + fl)
        for d in s["days"]:
            dt = datetime.date.fromisoformat(d["date"])
            print("  %s %s  %s" % (DAYS_RU[dt.weekday()], dt.strftime("%d.%m"),
                                   fmt_dur(d["total"]) if d["total"] >= 60 else "—"))
    else:
        print("Экранное время сегодня (%s): %s" % (s["date"], fmt_dur(s["total"])))
        fl = focus_line(focus_stats(datetime.date.today()))
        if fl:
            print("  " + fl)
        if s["hours"]:
            peak = max(s["hours"].items(), key=lambda x: x[1])
            print("  Больше всего в час %s:00–%s:00 — %s"
                  % (peak[0], (int(peak[0]) + 1) % 24, fmt_dur(peak[1])))
    print("Программы:")
    for a in s["apps"][:15]:
        pct = 100 * a["seconds"] / s["total"] if s["total"] else 0
        print("  %-24s %12s  %3.0f%%" % (a["name"][:24], fmt_dur(a["seconds"]), pct))
        for x in a.get("details", []):
            print("      %-24s %8s" % (x["name"][:24], fmt_dur(x["seconds"])))
    if len(s["apps"]) > 15:
        rest = sum(a["seconds"] for a in s["apps"][15:])
        print("  %-24s %12s" % ("другие (%d)" % (len(s["apps"]) - 15), fmt_dur(rest)))
    if not daemon_running():
        print("(счётчик screentime_daemon.py сейчас не запущен)")


# ── цвета программ ────────────────────────────────────────────────────────
# OKLab/OKLCH и симуляция цветовой слепоты — как в validate_palette.js.

_MACHADO = {
    "protan": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216),
               (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413),
               (-0.011820, 0.042940, 0.968881)),
}


def _s2l(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _l2s(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _lin(h):
    h = h.lstrip("#")
    return tuple(_s2l(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))


def _oklab(rgb):
    r, g, b = rgb
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _from_oklch(L, C, H):
    a, b = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def _hex(rgb):
    return "#" + "".join("%02x" % round(_l2s(c) * 255) for c in rgb)


def _sim(rgb, kind):
    M = _MACHADO[kind]
    return tuple(max(0.0, min(1.0, sum(M[i][k] * rgb[k] for k in range(3)))) for i in range(3))


def _de(a, b, kind=None):
    if kind:
        a, b = _sim(a, kind), _sim(b, kind)
    return 100 * math.dist(_oklab(a), _oklab(b))


def _lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def series_colors(anchor, surface, n=TOP):
    """n цветов для стопки: первый — оттенок акцента, соседние различимы.

    Светлота чередуется в тёмной полосе валидатора (OKLCH L 0.48–0.67), хрома
    не ниже 0.10 (иначе цвет читается серым), контраст с подложкой ≥ 3:1.
    Перебор ~16 тыс. наборов оттенков — около 0.1 с при открытии окна.
    """
    L0, a0, b0 = _oklab(_lin(anchor))
    h0 = math.degrees(math.atan2(b0, a0)) % 360
    ls = _lum(_lin(surface))
    cache = {}

    def color(L, H):
        key = (L, round(H % 360))
        if key not in cache:
            C, rgb = 0.14, None
            while C >= 0.10:
                cand = _from_oklch(L, C, H)
                if all(-1e-4 <= c <= 1.0001 for c in cand):
                    rgb = tuple(min(1.0, max(0.0, c)) for c in cand)
                    break
                C -= 0.005
            if rgb is not None:
                hi, lo = max(_lum(rgb), ls), min(_lum(rgb), ls)
                if (hi + 0.05) / (lo + 0.05) < 3.0:
                    rgb = None
            cache[key] = rgb
        return cache[key]

    best, best_score = None, -1.0
    for Ls in ((0.66, 0.54), (0.64, 0.52)):
        for perm in itertools.permutations(range(30, 360, 30), n - 1):
            hues = (0,) + perm
            cols = [color(Ls[i % 2], h0 + hues[i]) for i in range(n)]
            if any(c is None for c in cols):
                continue
            score = 99.0
            for i in range(n - 1):
                x, y = cols[i], cols[i + 1]
                # Худшая соседняя пара: слепота (цель ≥ 8) и обычное зрение (≥ 15,
                # поэтому -7 — обе шкалы сводятся к одной планке).
                score = min(score, _de(x, y, "protan"), _de(x, y, "deutan"), _de(x, y) - 7)
                if score <= best_score:
                    break
            if score > best_score:
                best, best_score = cols, score
    if best is None:
        return [anchor] * n
    return [_hex(c) for c in best]


# ── окно ──────────────────────────────────────────────────────────────────

def gui_imports():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Gdk, Gtk, Pango, PangoCairo  # noqa: F401
    return Gdk, Gtk, Pango, PangoCairo


def build_view_class():
    Gdk, Gtk, Pango, PangoCairo = gui_imports()
    import popup_theme

    def rgba(hexcolor, alpha=1.0):
        c = Gdk.RGBA()
        c.parse(hexcolor)
        return c.red, c.green, c.blue, alpha

    def top_rounded(cr, x, y, w, h, r):
        """Прямоугольник со скруглённым верхом: концы столбиков, низ — на оси."""
        r = min(r, w / 2, h)
        cr.new_sub_path()
        cr.move_to(x, y + h)
        cr.line_to(x, y + r)
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
        cr.line_to(x + w, y + h)
        cr.close_path()

    class Chart(Gtk.DrawingArea):
        """Столбики со стопками по программам. Подпись при наведении — в
        строке над графиком (hover), а не во всплывающей подсказке GTK: у
        слоя layer-shell подсказки встают как попало."""

        H = 150

        def __init__(self, view):
            super().__init__()
            self.view = view
            self.set_size_request(WIDTH - 24, self.H)
            self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
            self.connect("draw", self.on_draw)
            self.connect("motion-notify-event", self.on_motion)
            self.connect("leave-notify-event", lambda *_: self.set_hover(None))
            self.hover = None
            self.slots = []          # [(x0, x1, индекс)] для наведения

        def set_hover(self, i):
            if i != self.hover:
                self.hover = i
                self.view.show_hover(i)
                self.queue_draw()

        def on_motion(self, _w, ev):
            for x0, x1, i in self.slots:
                if x0 <= ev.x < x1:
                    self.set_hover(i)
                    return
            self.set_hover(None)

        def text(self, cr, s, x, y, color, px=12, align="center"):
            layout = self.create_pango_layout(s)
            fd = Pango.FontDescription.from_string(FONT)
            fd.set_absolute_size(px * Pango.SCALE)
            layout.set_font_description(fd)
            _ink, log = layout.get_pixel_extents()
            if align == "center":
                x -= log.width / 2
            elif align == "right":
                x -= log.width
            cr.move_to(round(x), round(y))
            cr.set_source_rgba(*color)
            PangoCairo.show_layout(cr, layout)
            return log.width

        def on_draw(self, _w, cr):
            v = self.view
            pal = v.pal
            w, h = self.get_allocated_width(), self.get_allocated_height()
            bars = v.bars()                 # [(подпись, {app: сек}, текущий?)]
            n = len(bars)
            grid = rgba(pal["on_surface_variant"], 0.16)
            dim = rgba(pal["on_surface_variant"], 0.85)
            hourly = v.mode == "today"

            left = 46 if hourly else 0     # место под «30 м» / «1 ч» слева
            top = 12 if hourly else 22      # у недели сверху подписи сумм
            base = h - 24                  # ось; под ней полоса фокуса и подписи
            ch = base - top
            if hourly:
                vmax = 3600
                ticks = [(1800, "30 м"), (3600, "1 ч")]
            else:
                peak = max([sum(b[1].values()) for b in bars] + [1])
                step = next(s for s in (1800, 3600, 7200, 10800, 14400, 21600, 28800, 43200)
                            if peak / s <= 4)
                vmax = max(step, math.ceil(peak / step) * step)
                ticks = [(t, fmt_dur(t, short=True)) for t in range(step, vmax + 1, step)]
            # Сетка — приглушённо, под столбиками.
            cr.set_line_width(1)
            for val, lab in ticks:
                y = round(base - ch * val / vmax) + 0.5
                cr.set_source_rgba(*grid)
                cr.move_to(left, y)
                cr.line_to(w, y)
                cr.stroke()
                if hourly:
                    self.text(cr, lab, left - 6, y - 6, dim, px=8, align="right")   # 16 px не влезает в левое поле
            cr.set_source_rgba(*rgba(pal["on_surface_variant"], 0.40))
            cr.move_to(left, base + 0.5)
            cr.line_to(w, base + 0.5)
            cr.stroke()

            pitch = (w - left) / n
            gap = 3 if hourly else 14
            bw = max(2, math.floor(pitch - gap))
            self.slots = []
            order = v.order                  # программы по убыванию: снизу — главная
            for i, (label, apps, current) in enumerate(bars):
                x = round(left + i * pitch + (pitch - bw) / 2)
                self.slots.append((left + i * pitch, left + (i + 1) * pitch, i))
                if self.hover == i:
                    cr.set_source_rgba(*rgba(pal["on_surface"], 0.07))
                    cr.rectangle(round(left + i * pitch), top - 4, math.ceil(pitch), base - top + 4)
                    cr.fill()
                total = sum(apps.values())
                segs = [(a, apps.get(a, 0)) for a in order]
                segs.append(("__other__", total - sum(s for _a, s in segs)))
                segs = [(a, s) for a, s in segs if s * ch / vmax >= 1]
                y = base
                for k, (a, s) in enumerate(segs):
                    sh = ch * min(s, vmax) / vmax
                    last = k == len(segs) - 1
                    # Зазор 2 px цвета подложки между кусками стопки — соседние
                    # цвета не сливаются (правило dataviz).
                    gh = sh - (0 if last else 2)
                    if gh >= 1:
                        cr.set_source_rgba(*v.color_of(a))
                        if last:
                            top_rounded(cr, x, y - sh, bw, sh, 3 if hourly else 4)
                        else:
                            cr.rectangle(x, y - gh, bw, gh)
                        cr.fill()
                    y -= sh
                # Полоса фокуса под осью: доля часа (дня — доля экранного времени),
                # проведённая в фокусе или на рабочем отрезке помидора (06.10.2026).
                fsec = v.focus_of(i)
                if fsec >= 60:
                    frac = min(1.0, fsec / (3600 if hourly else max(total, fsec)))
                    cr.set_source_rgba(*rgba(pal["primary"], 0.25))
                    cr.rectangle(x, base + 2, bw, 3)
                    cr.fill()
                    cr.set_source_rgba(*rgba(pal["primary"]))
                    cr.rectangle(x, base + 2, max(2, round(bw * frac)), 3)
                    cr.fill()
                if not hourly and total >= 60:
                    self.text(cr, fmt_dur(total, short=True), x + bw / 2, y - 18,
                              rgba(pal["on_surface"] if current else pal["on_surface_variant"]))
                # Подписи оси: у часов — каждые 3 часа, у недели — каждый день.
                if hourly and i % 3 != 0 and not current:
                    continue
                if hourly and current and i % 3 != 0:
                    # Текущий час отмечен точкой: число здесь налезло бы на соседние.
                    cr.set_source_rgba(*rgba(pal["primary"]))
                    cr.rectangle(x + bw / 2 - 2, base + 8, 4, 4)
                    cr.fill()
                    continue
                col = rgba(pal["primary"]) if current else dim
                self.text(cr, label, left + i * pitch + pitch / 2, base + 7, col)
            return True

    class View(Gtk.Box):
        """Содержимое окна; одно и то же для слоя на экране и для --render."""

        def __init__(self, mode="today", on_close=None):
            super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            self.pal = pal = popup_theme.palette()
            self.colors = [rgba(c) for c in series_colors(pal["primary"], pal["surface_container"])]
            self.other = rgba(pal["on_surface_variant"], 0.38)
            self.mode = mode
            self.on_close = on_close
            self.get_style_context().add_class("popup-box")
            self.set_size_request(WIDTH, -1)

            head = Gtk.Box(spacing=8)
            title = Gtk.Label(label="Экранное время", xalign=0)
            title.get_style_context().add_class("title")
            head.pack_start(title, True, True, 0)
            self.tabs = {}
            seg = Gtk.Box(spacing=0)
            seg.get_style_context().add_class("seg")
            for key, lab in (("today", "Сегодня"), ("week", "7 дней")):
                b = Gtk.Button(label=lab)
                b.get_style_context().add_class("tab")
                b.connect("clicked", lambda _b, k=key: self.set_mode(k))
                seg.pack_start(b, False, False, 0)
                self.tabs[key] = b
            head.pack_start(seg, False, False, 0)
            self.pack_start(head, False, False, 0)

            tot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self.lbl_total = Gtk.Label(xalign=0)
            self.lbl_total.get_style_context().add_class("total")
            self.lbl_sub = Gtk.Label(xalign=0)
            self.lbl_sub.get_style_context().add_class("sub")
            tot.pack_start(self.lbl_total, False, False, 0)
            tot.pack_start(self.lbl_sub, False, False, 0)
            self.lbl_focus = Gtk.Label(xalign=0)
            self.lbl_focus.get_style_context().add_class("sub")
            self.lbl_focus.get_style_context().add_class("focus")
            self.lbl_focus.set_no_show_all(True)
            tot.pack_start(self.lbl_focus, False, False, 0)
            self.pack_start(tot, False, False, 0)

            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.get_style_context().add_class("card")
            self.lbl_hover = Gtk.Label(xalign=0)
            self.lbl_hover.get_style_context().add_class("hover")
            self.lbl_hover.set_ellipsize(3)
            card.pack_start(self.lbl_hover, False, False, 0)
            self.chart = Chart(self)
            card.pack_start(self.chart, False, False, 0)
            self.pack_start(card, False, False, 0)

            self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            self.pack_start(self.list, False, False, 0)

            self.lbl_foot = Gtk.Label(xalign=0)
            self.lbl_foot.get_style_context().add_class("foot")
            self.lbl_foot.set_line_wrap(True)
            self.lbl_foot.set_max_width_chars(60)
            self.pack_start(self.lbl_foot, False, False, 0)
            self.set_mode(mode)

        # данные текущей вкладки
        def load(self):
            today = datetime.date.today()
            now_h = datetime.datetime.now().hour
            if self.mode == "today":
                d = load_day(today)
                self.apps = d["apps"]
                self.details = d["details"]
                self._bars = [("%d" % hh, d["hours"].get(str(hh), {}), hh == now_h) for hh in range(24)]
                self._bar_names = ["%02d:00–%02d:00" % (hh, (hh + 1) % 24) for hh in range(24)]
            else:
                dates = week_dates(today)
                days = [load_day(x) for x in dates]
                self.apps = sum_apps(x["apps"] for x in days)
                self.details = sum_details(days)
                self._bars = [(DAYS_RU[x.weekday()], y["apps"], x == today) for x, y in zip(dates, days)]
                self._bar_names = ["%s, %d %s" % (DAYS_RU[x.weekday()], x.day, MONTHS_RU[x.month - 1])
                                   for x in dates]
            self.rank = ranked(self.apps)
            self.order = [a for a, _s in self.rank[:TOP]]
            # фокус и помидор: по часам сегодня или по дням недели
            if self.mode == "today":
                st = focus_stats(today)
                self._focus = [(st or {}).get("hours", {}).get(hh, 0) for hh in range(24)]
                self._focus_total = st
            else:
                sts = [focus_stats(x) for x in dates]
                self._focus = [(x or {}).get("focus", 0) for x in sts]
                self._focus_total = None if not all(sts) else {
                    "focus": sum(x["focus"] for x in sts), "pomos": sum(x["pomos"] for x in sts),
                    "blocks": sum(x["blocks"] for x in sts)}

        def focus_of(self, i):
            try:
                return self._focus[i]
            except (AttributeError, IndexError):
                return 0

        def bars(self):
            return self._bars

        def color_of(self, app):
            if app in self.order:
                return self.colors[self.order.index(app)]
            return self.other

        def set_mode(self, mode):
            self.mode = mode
            for k, b in self.tabs.items():
                ctx = b.get_style_context()
                (ctx.add_class if k == mode else ctx.remove_class)("active")
            self.load()
            total = sum(self.apps.values())
            self.lbl_total.set_text(fmt_dur(total) if total >= 60 else "меньше минуты")
            today = datetime.date.today()
            if mode == "today":
                week = [load_day(x) for x in week_dates(today)[:-1]]
                past = [sum(x["apps"].values()) for x in week if x["apps"]]
                sub = "Сегодня, %d %s" % (today.day, MONTHS_RU[today.month - 1])
                if past:
                    sub += " · в среднем %s в день" % fmt_dur(sum(past) / len(past))
            else:
                active = [b for b in self._bars if sum(b[1].values()) >= 60]
                sub = "За 7 дней"
                if active:
                    sub += " · в среднем %s в день" % fmt_dur(total / len(active))
            self.lbl_sub.set_text(sub)
            fl = focus_line(self._focus_total)
            self.lbl_focus.set_text(fl)
            self.lbl_focus.set_visible(bool(fl))
            self.show_hover(None)
            self.fill_list()
            self.lbl_foot.set_text(
                "Без простоя дольше 5 мин, блокировки и дашборда."
                if daemon_running() else
                "Счётчик screentime_daemon.py не запущен — цифры не растут.")
            self.chart.queue_draw()

        def show_hover(self, i):
            if i is None:
                # Без наведения — самый загруженный столбик.
                sums = [sum(b[1].values()) for b in self._bars]
                if max(sums or [0]) < 60:
                    self.lbl_hover.set_text("Пока пусто")
                    return
                i = max(range(len(sums)), key=lambda k: sums[k])
                self.lbl_hover.set_text("Больше всего: %s — %s" % (self._bar_names[i], fmt_dur(sums[i])))
                return
            apps = self._bars[i][1]
            tot = sum(apps.values())
            if tot < 60:
                self.lbl_hover.set_text("%s — пусто" % self._bar_names[i])
                return
            top = ranked(apps)[:2]
            parts = ", ".join("%s %s" % (app_name(a), fmt_dur(s)) for a, s in top)
            fsec = self.focus_of(i)
            if fsec >= 60:
                parts += " · фокус " + fmt_dur(fsec)
            self.lbl_hover.set_text("%s — %s: %s" % (self._bar_names[i], fmt_dur(tot), parts))

        def fill_list(self):
            for c in self.list.get_children():
                self.list.remove(c)
            rows = self.rank[:LIST_ROWS]
            if not rows:
                lb = Gtk.Label(label="Данных пока нет — счётчик копит время.", xalign=0)
                lb.get_style_context().add_class("sub")
                self.list.pack_start(lb, False, False, 6)
            peak = rows[0][1] if rows else 1
            for a, s in rows:
                self.list.pack_start(self.row(a, s, s / peak, self.color_of(a)), False, False, 0)
                for k, v in detail_rows(a, s, self.details):
                    self.list.pack_start(self.subrow(k, v, v / peak, self.color_of(a)), False, False, 0)
            rest = self.rank[LIST_ROWS:]
            if rest:
                s = sum(x[1] for x in rest)
                self.list.pack_start(self.row(None, s, s / peak, self.other,
                                              "Другие (%d)" % len(rest)), False, False, 0)
            self.list.show_all()

        def subrow(self, name, sec, frac, color):
            """Строка «что именно» под программой: мельче, с отступом под значок,
            полоска того же цвета, но бледнее."""
            box = Gtk.Box(spacing=10)
            box.get_style_context().add_class("subrow")
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            line = Gtk.Box(spacing=8)
            ln = Gtk.Label(label=name, xalign=0)
            ln.set_ellipsize(3)
            ln.get_style_context().add_class("subname")
            lt = Gtk.Label(label=fmt_dur(sec))
            lt.get_style_context().add_class("subtime")
            line.pack_start(ln, True, True, 0)
            line.pack_start(lt, False, False, 0)
            col.pack_start(line, False, False, 0)
            bar = Gtk.DrawingArea()
            bar.set_size_request(-1, 3)
            faded = (color[0], color[1], color[2], color[3] * 0.55)

            def draw(w, cr):
                ww, hh = w.get_allocated_width(), w.get_allocated_height()
                cr.set_source_rgba(*faded)
                cr.rectangle(0, 0, max(hh, round(ww * frac)), hh)
                cr.fill()
                return True
            bar.connect("draw", draw)
            col.pack_start(bar, False, False, 0)
            box.pack_start(col, True, True, 0)
            return box

        def row(self, app, sec, frac, color, name=None):
            box = Gtk.Box(spacing=10)
            box.get_style_context().add_class("row")
            if app is not None:
                nm, icon = app_info(app)
            else:
                nm, icon = name, None
            img = Gtk.Image()
            if icon is not None:
                img.set_from_gicon(icon, Gtk.IconSize.DND)
            else:
                img.set_from_icon_name("view-more-horizontal-symbolic", Gtk.IconSize.DND)
            img.set_pixel_size(24)
            box.pack_start(img, False, False, 0)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            line = Gtk.Box(spacing=8)
            ln = Gtk.Label(label=nm, xalign=0)
            ln.set_ellipsize(3)
            ln.get_style_context().add_class("name")
            lt = Gtk.Label(label=fmt_dur(sec))
            lt.get_style_context().add_class("time")
            line.pack_start(ln, True, True, 0)
            line.pack_start(lt, False, False, 0)
            col.pack_start(line, False, False, 0)
            bar = Gtk.DrawingArea()
            bar.set_size_request(-1, 6)
            track = rgba(self.pal["on_surface"], 0.10)

            def draw(w, cr):
                ww, hh = w.get_allocated_width(), w.get_allocated_height()
                cr.set_source_rgba(*track)
                cr.rectangle(0, 0, ww, hh)
                cr.fill()
                fw = max(hh, round(ww * frac))
                cr.set_source_rgba(*color)
                top_rounded(cr, 0, 0, fw, hh, 0)
                cr.fill()
                return True
            bar.connect("draw", draw)
            col.pack_start(bar, False, False, 0)
            box.pack_start(col, True, True, 0)
            return box

    def style():
        pal = popup_theme.palette()
        css = popup_theme.css("""
        .popup-box {
            /* Пиксельный шрифт — только 12/16/24/32 px: так он чёткий
               (память pixel-font-system). Рамка — общая, из BASE_CSS. */
            font-family: '%(font)s', 'JetBrainsMono NF', sans-serif;
            font-size: 16px; font-weight: normal;
            border-radius: 14px; padding: 14px;
        }
        label.title { color: %(primary)s; font-size: 16px; }
        label.total { color: %(on_surface)s; font-size: 32px; }
        label.sub { color: %(on_surface_variant)s; font-size: 12px; }
        label.focus { color: %(primary)s; }
        label.hover { color: %(on_surface_variant)s; font-size: 12px; }
        label.foot { color: alpha(%(on_surface_variant)s, 0.7); font-size: 12px; }
        label.name { color: %(on_surface)s; font-size: 16px; }
        label.time { color: %(on_surface_variant)s; font-size: 16px; }
        .card { background-color: %(card_bg)s; border: 1px solid %(line)s;
                border-radius: 14px; padding: 10px 12px 8px 12px; }
        .row { padding: 5px 2px; }
        .subrow { padding: 1px 2px 3px 36px; }
        label.subname { color: %(on_surface_variant)s; font-size: 12px; }
        label.subtime { color: alpha(%(on_surface_variant)s, 0.8); font-size: 12px; }
        .seg { background-color: %(card_bg)s; border: 1px solid %(line)s; border-radius: 10px; padding: 2px; }
        button.tab {
            background: transparent; background-image: none; border: none; box-shadow: none;
            color: %(on_surface_variant)s; font-size: 12px; border-radius: 8px;
            padding: 4px 10px; min-height: 0;
        }
        button.tab:hover { color: %(primary)s; }
        button.tab.active { background-color: %(primary)s; color: %(on_primary)s; }
        """, card_bg=popup_theme.rgba(pal["surface_container"], "0.80"),
            line=popup_theme.rgba(pal["primary"], "0.40"), font=FONT)
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    return View, style


def run_popup(mode):
    import popup_theme
    popup_theme.single_instance(__file__)
    import gi
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
    Gdk, Gtk, _P, _PC = gui_imports()
    poke_daemon()
    View, style = build_view_class()
    style()

    win = Gtk.Window(title="Экранное время")
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.TOP)
    GtkLayerShell.set_namespace(win, "jarvis-screentime")
    # Слой на весь экран, прозрачный: щелчок мимо карточки закрывает окно.
    for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                 GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
        GtkLayerShell.set_anchor(win, edge, True)
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
    mon = popup_theme.pointer_monitor()
    if mon is not None:
        GtkLayerShell.set_monitor(win, mon)

    bg = Gtk.EventBox()
    bg.connect("button-press-event", lambda *_: Gtk.main_quit())
    win.add(bg)
    align = Gtk.Box()
    align.set_halign(Gtk.Align.CENTER)
    if popup_theme.bar_position() == "bottom":
        align.set_valign(Gtk.Align.END)
        align.set_margin_bottom(6)
    else:
        align.set_valign(Gtk.Align.START)
        align.set_margin_top(6)
    bg.add(align)
    stop = Gtk.EventBox()
    stop.connect("button-press-event", lambda *_: True)
    align.add(stop)
    view = View(mode)
    stop.add(view)

    def on_key(_w, ev):
        if ev.keyval == Gdk.KEY_Tab:
            view.set_mode("week" if view.mode == "today" else "today")
            return True
        Gtk.main_quit()
        return True
    win.connect("key-press-event", on_key)
    # Второй запуск (single_instance) шлёт SIGTERM — выйти сразу.
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    win.show_all()
    Gtk.main()


def render_png(path, mode):
    """Нарисовать окно в Gtk.OffscreenWindow и сохранить PNG — без показа на экране."""
    Gdk, Gtk, _P, _PC = gui_imports()
    from gi.repository import GLib
    poke_daemon()
    View, style = build_view_class()
    style()
    win = Gtk.OffscreenWindow()
    view = View(mode)
    win.add(view)
    win.show_all()

    def snap():
        pix = win.get_pixbuf()
        pix.savev(path, "png", [], [])
        Gtk.main_quit()
        return False
    GLib.timeout_add(400, snap)
    Gtk.main()
    print(path)


def main():
    argv = sys.argv[1:]
    kind = "week" if "week" in argv or "--week" in argv else "today"
    if "--text" in argv:
        print_text(kind)
    elif "--json" in argv:
        print(json.dumps(summary(kind), ensure_ascii=False, indent=1))
    elif "--render" in argv:
        render_png(argv[argv.index("--render") + 1], kind)
    else:
        run_popup(kind)


if __name__ == "__main__":
    main()
