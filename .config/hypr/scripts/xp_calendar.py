#!/usr/bin/env python3
"""Календарь нижней XP-панели (xpbar.py) — три вида стиля системы. 04.10.2026.

Просьба: «пусть на клике на блок часы/дата открывается плашка календаря» — для
НИЖНЕЙ панели (xpbar.py), отдельно от календаря waybar (calendar_popup.py,
тот принадлежит верхней панели — не трогать). Затем: «можно в стиле Windows XP,
сделать его типом стиля default, и добавить типы для Skeet и Beta» — как у
Настроек/буфера обмена/Recorder (system_style.py: default/skeet/beta по монитору
в фокусе, ~/.config/hypr/state/calendar-style).

  default — окно XP: рамка 3px, полоса заголовка градиентом панели XP (как
            буфер обмена/Recorder в виде default), тёмное тело;
  skeet   — gamesense: слоистая рамка, полоска трёх тонов палитры сверху;
  beta    — плоско и прямоугольно, Light/Dark общий со всей системой
            (state/settings-mode).
Дней недели по-русски своих нет (GTK.Calendar берёт имена из системной локали,
а ru_RU в системе не установлена) — сетка своя, Grid из Label, имена месяцев
и дней зашиты в MONTHS/DAYS.
"""
import calendar as cal_mod
import json
import os
import subprocess
import sys
import time
import urllib.parse

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import popup_theme  # noqa: E402

STYLES = ("default", "skeet", "beta")
STYLE_FILE = os.path.expanduser("~/.config/hypr/state/calendar-style")
# Клик по часам при открытой плашке сначала уводит фокус (плашка закрывается сама),
# а потом тот же клик запускает её заново. Метка времени закрытия: свежая — значит,
# этот запуск и есть тот клик, и он должен только закрыть.
CLOSED_AT = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "xp-calendar-closed")
REOPEN_GUARD_S = 0.6
MODE_FILE = os.path.expanduser("~/.config/hypr/state/settings-mode")
VIVID = os.path.expanduser("~/.cache/matugen/vivid.txt")

FONT = "'PxPlus HP 100LX 6x8 Jarvis', 'JetBrainsMono NF', monospace"
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря")
DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def read_style():
    try:
        v = open(STYLE_FILE).read().strip().lower()
    except OSError:
        return "default"
    return v if v in STYLES else "default"


def _mix(a, b, t):
    a, b = a.lstrip("#")[:6], b.lstrip("#")[:6]
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(round(x * (1 - t) + y * t) for x, y in zip(ca, cb))


def _read(path):
    try:
        return open(path).read().strip().lower()
    except OSError:
        return ""


def colors(style):
    """Словарь #rrggbb для стиля: общие роли win_bg/text/dim/accent/sel_bg/sel_text/frame."""
    p = popup_theme.palette()
    if style == "skeet":
        acc = p["primary"]
        v = _read(VIVID)
        if v.startswith("#") and len(v) == 7:
            acc = v

        def g(level, t=0.05):
            return _mix("#%02x%02x%02x" % (level, level, level), acc, t)
        c = dict(acc=acc, acc_l=_mix(acc, "#ffffff", 0.22), acc_d=_mix(acc, "#000000", 0.40),
                 bg=g(0x13), field=g(0x1b), field_l=g(0x24),
                 line1=g(0x3c, 0.08), line2=g(0x28, 0.06), line3=g(0x0a, 0.03),
                 gline=g(0x30, 0.08), gdark=g(0x0e, 0.03),
                 text=_mix("#cdcdcd", p["on_surface"], 0.35), dim=g(0x92, 0.10),
                 strip=[acc, p["tertiary"], p["secondary"]])
        c.update(win_bg=c["bg"], frame=c["line1"], accent=c["acc_l"],
                 sel_bg=c["field_l"], sel_text=c["acc_l"])
        return c
    if style == "beta":
        if _read(MODE_FILE) == "light":
            try:
                import xpbar_colors
                t = xpbar_colors.colors()
            except Exception:
                t = dict(p, base=p["surface"], st_hi="#9fb4f5", st_mid="#5f74b4", st_bot="#465a94")
            base = t.get("base", p["surface"])
            ink = _mix(base, "#000000", 0.15)
            ink2 = _mix(t["st_bot"], base, 0.35)
            bg = _mix(_mix(t["st_hi"], p["on_surface"], 0.85), "#ffffff", 0.20)
            rail = _mix(t["st_hi"], p["on_surface"], 0.62)
            acc = _mix(t["st_mid"], t["st_bot"], 0.40)
            c = dict(bg=bg, bar=_mix(t["st_hi"], p["on_surface"], 0.45), card=_mix(bg, "#ffffff", 0.45),
                     field=_mix(bg, ink2, 0.10), text=ink, dim=_mix(ink2, bg, 0.22),
                     acc=acc, on_acc=_mix(p["on_surface"], "#ffffff", 0.6),
                     sel=_mix(rail, acc, 0.38), sel_text=ink,
                     line=_mix(bg, ink2, 0.28))
        else:
            bg = p["surface"]
            cont = p["surface_container"]
            c = dict(bg=bg, bar=_mix(bg, cont, 0.85), card=cont, field=p["surface_high"],
                     text=p["on_surface"], dim=_mix(p["on_surface_variant"], bg, 0.30),
                     acc=p["primary"], on_acc=p["on_primary"],
                     sel=_mix(bg, p["primary"], 0.30), sel_text=p["on_surface"],
                     line=_mix(cont, p["on_surface"], 0.16))
        c.update(win_bg=c["bg"], frame=p["primary"], accent=c["acc"],
                 sel_bg=c["sel"], sel_text=c["sel_text"])
        return c
    # default — окно XP, в гамме панели (xpbar_colors): градиент заголовка, тёмное тело
    try:
        import xpbar_colors
        t = xpbar_colors.colors()
    except Exception:
        t = dict(p, base=p["surface"], st_top=p["primary"], st_mid=p["primary"],
                  st_bot=p["surface_high"], st_hi=p["primary"], st_dark=p["surface"])
    base = t.get("base", p["surface"])
    c = dict(win_bg=_mix(base, p["surface"], 0.5), frame=t.get("st_mid", p["primary"]),
             st_top=t.get("st_top", p["primary"]), st_mid=t.get("st_mid", p["primary"]),
             st_bot=t.get("st_bot", p["surface_high"]), st_dark=t.get("st_dark", base),
             text=p["on_surface"], dim=p["on_surface_variant"],
             accent="#ffffff", sel_bg=_mix(t.get("st_hi", p["primary"]), "#ffffff", 0.18),
             sel_text=base, row=_mix(base, p["surface_high"], 0.55))
    return c


def np_css(style, c):
    """Стиль списка уведомлений (группы по приложению) и подвала — под каждый вид."""
    common = """
        .np-gname { font-size: 12px; }
        .np-gcount, .np-time, .np-empty, .np-more { font-size: 12px; }
        .np-summary, .np-body { font-size: 12px; }
        .np-empty { padding: 10px; }
        .np-gicon { margin-right: 2px; }
        .np-thumb, .np-icon { margin-top: 2px; }
        button.np-close { background: transparent; border: none; box-shadow: none;
                          padding: 0 4px; min-height: 0; min-width: 0; font-size: 12px; }
        button.np-more { background: transparent; background-image: none; border: none; box-shadow: none;
                         padding: 1px 6px; min-height: 0; }
        button.cal-nav:disabled { opacity: 0.5; }
        .np-scroll scrollbar { background-color: transparent; border: none; }
        .np-scroll scrollbar slider { min-width: 4px; border-radius: 0; }
    """
    if style == "skeet":
        return common + """
        .np-scroll { margin: 6px 8px 0 8px; border: 1px solid %(gline)s; box-shadow: inset 0 0 0 1px %(gdark)s; }
        .np-list { background-color: transparent; padding: 4px 6px; }
        .np-group { margin-bottom: 6px; border: 1px solid %(line2)s; }
        .np-ghead { background-color: %(field)s; padding: 2px 4px 2px 6px;
                    border-style: solid; border-width: 0 0 1px 0; border-color: %(line2)s; }
        .np-gname { color: %(acc_l)s; }
        .np-gcount { color: %(dim)s; }
        .np-item { background-color: transparent; padding: 3px 4px 4px 6px;
                   border-style: solid; border-width: 0 0 1px 0; border-color: %(line2)s; }
        .np-time { color: %(dim)s; }
        .np-summary { color: %(text)s; }
        .np-body { color: %(dim)s; }
        .np-empty { color: %(dim)s; }
        .np-foot { color: %(dim)s; font-size: 12px; padding: 2px 8px 4px 8px; background-color: transparent; }
        button.np-close { color: %(dim)s; }
        button.np-close:hover, button.np-more:hover label { color: %(acc_l)s; }
        button.np-more label { color: %(dim)s; font-size: 12px; }
        .np-scroll scrollbar slider { background-color: %(line1)s; }
        """ % c
    if style == "beta":
        return common + """
        .np-list { background-color: %(card)s; padding: 8px; }
        .np-group { margin-bottom: 6px; background-color: %(bg)s; border: 1px solid %(line)s; }
        .np-ghead { background-color: %(bar)s; padding: 3px 4px 3px 8px;
                    border-style: solid; border-width: 0 0 1px 0; border-color: %(line)s; }
        .np-gname { color: %(text)s; }
        .np-gcount { color: %(dim)s; }
        .np-item { padding: 4px 6px 5px 8px; border-style: solid; border-width: 0 0 1px 0; border-color: %(line)s; }
        .np-time { color: %(dim)s; }
        .np-summary { color: %(text)s; }
        .np-body { color: %(dim)s; }
        .np-empty { color: %(dim)s; }
        .np-foot { color: %(dim)s; font-size: 12px; padding: 4px 10px 6px 10px; background-color: %(bar)s;
                   border-style: solid; border-width: 1px 0 0 0; border-color: %(line)s; }
        button.np-close { color: %(dim)s; }
        button.np-close:hover, button.np-more:hover label { color: %(acc)s; }
        button.np-more label { color: %(dim)s; font-size: 12px; }
        .np-scroll scrollbar slider { background-color: %(line)s; }
        """ % c
    return common + """
        .np-list { background-color: %(win_bg)s; padding: 6px; }
        .np-group { margin-bottom: 6px; background-color: %(row)s;
                    border-style: solid; border-width: 0 0 0 3px; border-color: %(st_mid)s; }
        .np-ghead { padding: 3px 4px 3px 6px; background-image: linear-gradient(to bottom, %(st_top)s, %(st_bot)s); }
        .np-gname { color: %(accent)s; font-weight: bold; }
        .np-gcount { color: %(accent)s; }
        .np-item { padding: 4px 6px 5px 6px; border-style: solid; border-width: 1px 0 0 0; border-color: %(st_dark)s; }
        .np-time { color: %(dim)s; }
        .np-summary { color: %(text)s; font-weight: bold; }
        .np-body { color: %(dim)s; }
        .np-empty { color: %(dim)s; }
        .np-foot { color: %(dim)s; font-size: 12px; padding: 4px 8px 6px 8px; background-color: %(win_bg)s;
                   border-style: solid; border-width: 1px 0 0 0; border-color: %(st_dark)s; }
        button.np-close { color: %(dim)s; }
        .np-ghead button.np-close { color: %(accent)s; }
        button.np-close:hover, button.np-more:hover label { color: %(text)s; }
        button.np-more label { color: %(dim)s; font-size: 12px; }
        .np-scroll scrollbar slider { background-color: %(st_mid)s; }
        """ % c


NOTIF_LOG = os.path.expanduser("~/.cache/jarvis-notif-log.json")
NOTIF_SHOWN = 50
NOTIF_MAX_H = 330
GROUP_SHOWN = 3
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def read_notif_log():
    try:
        with open(NOTIF_LOG) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def write_notif_log(items):
    tmp = NOTIF_LOG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp, NOTIF_LOG)


def when_str(t):
    """«12:05» сегодня, «вчера 12:05», иначе «03.10 12:05» — как в Центре управления."""
    lt, now = time.localtime(t), time.localtime()
    hm = time.strftime("%H:%M", lt)
    if lt[:3] == now[:3]:
        return hm
    y = time.localtime(time.time() - 86400)
    return ("вчера " if lt[:3] == y[:3] else time.strftime("%d.%m ", lt)) + hm


def app_title(e):
    app = e.get("app") or ""
    return {"org.telegram.desktop": "Telegram", "notify-send": "Система"}.get(app, app) or "Уведомление"


# Значки (04.10.2026, просьба: «немного иконок, а не просто сухой текст»).
# Имя программы в уведомлении → значок темы, если своего значка она не прислала.
APP_ICONS = {"telegram desktop": "org.telegram.desktop", "telegram": "org.telegram.desktop",
             "niri": "accessories-screenshot", "network management": "network-wired",
             "networkmanager applet": "network-wired", "pomodoro": "chronometer",
             "timer": "chronometer", "music": "audio-x-generic", "notify-send": "dialog-information",
             "system notifications": "preferences-system-notifications"}


def _theme():
    return Gtk.IconTheme.get_default()


def icon_file(e):
    """Путь к картинке уведомления (снимок экрана, обложка), если файл на месте."""
    ic = e.get("icon") or ""
    if ic.startswith("file://"):
        ic = urllib.parse.unquote(ic[7:])
    return ic if ic.startswith("/") and os.path.isfile(ic) else ""


def icon_name(e):
    """Имя значка темы: свой значок уведомления, иначе по имени программы."""
    ic = e.get("icon") or ""
    if ic and not ic.startswith(("/", "file:")) and _theme().has_icon(ic):
        return ic
    return ""


def app_icon_name(app, ents):
    t = _theme()
    cand = [APP_ICONS.get(app.lower(), ""), app.lower(), app.lower().replace(" ", "-")]
    cand += [icon_name(x) for x in ents]
    for app_info in Gio.AppInfo.get_all():
        if (app_info.get_name() or "").lower() == app.lower():
            ic = app_info.get_icon()
            if ic is not None:
                cand.append(ic.to_string())
    for n in cand:
        if n and t.has_icon(n):
            return n
    return "preferences-system-notifications"


def thumb(path, w=44, h=32):
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, w, h, True)
    except GLib.Error:
        return None
    img = Gtk.Image.new_from_pixbuf(pb)
    img.get_style_context().add_class("np-thumb")
    img.set_valign(Gtk.Align.START)
    return img


class XPCalendar(Gtk.Window):
    """Панель как в Windows: уведомления сверху, календарь снизу (04.10.2026, просьба: «сделай полноценную плашку, туда ещё уведомления, как в Windows, в стиле XP»).
    Уведомления — журнал notif_log.py: у swaync по D-Bus текста нет, только число."""

    def __init__(self):
        super().__init__()
        self.set_decorated(False)
        self.style = read_style()
        self.c = colors(self.style)

        GtkLayerShell.init_for_window(self)
        mon = popup_theme.pointer_monitor()
        if mon:
            GtkLayerShell.set_monitor(self, mon)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        now = time.localtime()
        self.year, self.month = now.tm_year, now.tm_mon
        self.today = (now.tm_year, now.tm_mon, now.tm_mday)
        self.log_mtime = None
        self.armed = None
        self.expanded = set()

        self.apply_css()

        bg = Gtk.EventBox()
        bg.connect("button-press-event", lambda w, e: self.destroy())
        self.add(bg)

        align = Gtk.Box()
        bg.add(align)

        card = Gtk.EventBox()
        card.connect("button-press-event", lambda w, e: True)
        align.add(card)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.get_style_context().add_class("cal-box")
        outer.set_size_request(340, -1)
        card.add(outer)

        # ── уведомления ──
        nhead = Gtk.Box(spacing=6)
        nhead.get_style_context().add_class("cal-head")
        ntitle = Gtk.Label(label="Уведомления", xalign=0)
        ntitle.get_style_context().add_class("cal-title")
        ntitle.set_hexpand(True)
        self.clear_btn = Gtk.Button(label="Очистить")
        self.clear_btn.get_style_context().add_class("cal-nav")
        self.clear_btn.connect("clicked", self.on_clear)
        nhead.pack_start(ntitle, True, True, 0)
        nhead.pack_start(self.clear_btn, False, False, 0)
        outer.pack_start(nhead, False, False, 0)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_max_content_height(NOTIF_MAX_H)
        self.scroll.get_style_context().add_class("np-scroll")
        self.nlist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.nlist.get_style_context().add_class("np-list")
        self.scroll.add(self.nlist)
        outer.pack_start(self.scroll, False, False, 0)

        # ── календарь ──
        header = Gtk.Box(spacing=6)
        header.get_style_context().add_class("cal-head")
        prev_btn = Gtk.Button(label="<")
        prev_btn.get_style_context().add_class("cal-nav")
        prev_btn.connect("clicked", lambda _b: self.shift_month(-1))
        next_btn = Gtk.Button(label=">")
        next_btn.get_style_context().add_class("cal-nav")
        next_btn.connect("clicked", lambda _b: self.shift_month(1))
        self.title_lbl = Gtk.Label()
        self.title_lbl.get_style_context().add_class("cal-title")
        self.title_lbl.set_hexpand(True)
        header.pack_start(prev_btn, False, False, 0)
        header.pack_start(self.title_lbl, True, True, 0)
        header.pack_start(next_btn, False, False, 0)
        outer.pack_start(header, False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        body.get_style_context().add_class("cal-body")
        outer.pack_start(body, False, False, 0)

        self.grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True,
                              column_spacing=2, row_spacing=2)
        body.pack_start(self.grid, False, False, 0)

        foot = Gtk.Label(label="%s, %d %s %d" % (WEEKDAYS[now.tm_wday], now.tm_mday,
                                                MONTHS[now.tm_mon - 1], now.tm_year))
        foot.get_style_context().add_class("np-foot")
        outer.pack_start(foot, False, False, 0)

        # Свой угол, а не popup_theme.place_side: тот приклеивает «уши» к верхнему
        # waybar. Здесь — правый нижний угол над XP-панелью, где часы.
        align.set_valign(Gtk.Align.END)
        align.set_halign(Gtk.Align.END)
        align.set_margin_bottom(6 + popup_theme.bottom_overlap())
        align.set_margin_end(8)

        self.fill_grid()
        self.fill_notifs()
        GLib.timeout_add_seconds(2, self.poll_log)
        self.connect("destroy", self.on_destroy)
        self.connect("key-press-event", self.on_key_press)
        # Первое focus-out прилетает сразу при открытии — без задержки окно
        # закрывалось, не успев показаться (так же сделано в calendar_popup.py).
        self.ready = False
        self.connect("focus-out-event", self.on_focus_out)
        GLib.timeout_add(400, self.arm)
        self.show_all()

    def arm(self):
        self.ready = True
        return False

    def on_destroy(self, *_a):
        try:
            with open(CLOSED_AT, "w") as f:
                f.write(str(time.time()))
        except OSError:
            pass
        Gtk.main_quit()

    def on_focus_out(self, *_a):
        if self.ready:
            self.destroy()
        return False

    # ── уведомления ──
    def poll_log(self):
        try:
            m = os.stat(NOTIF_LOG).st_mtime
        except OSError:
            m = None
        if m != self.log_mtime:
            self.fill_notifs()
        return True

    def fill_notifs(self):
        """Группы по приложению, как в Windows (04.10.2026, просьба: «сделай разбивку,
        группировать их как-то»): шапка — имя, число, крестик всей группы; группы по
        свежести; в группе видно GROUP_SHOWN, остальные — по кнопке «ещё N»."""
        try:
            self.log_mtime = os.stat(NOTIF_LOG).st_mtime
        except OSError:
            self.log_mtime = None
        for ch in list(self.nlist.get_children()):
            self.nlist.remove(ch)
        items = read_notif_log()[:NOTIF_SHOWN]
        if not items:
            empty = Gtk.Label(label="Новых уведомлений нет")
            empty.get_style_context().add_class("np-empty")
            self.nlist.pack_start(empty, False, False, 0)
        groups = {}
        for e in items:                          # журнал — новые сверху, порядок сохраняется
            groups.setdefault(app_title(e), []).append(e)
        rows = 0
        for app, ents in groups.items():
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.get_style_context().add_class("np-group")
            head = Gtk.Box(spacing=6)
            head.get_style_context().add_class("np-ghead")
            name = Gtk.Label(label=app, xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.get_style_context().add_class("np-gname")
            cnt = Gtk.Label(label=str(len(ents)))
            cnt.get_style_context().add_class("np-gcount")
            close = Gtk.Button(label="×")
            close.get_style_context().add_class("np-close")
            close.set_tooltip_text("Убрать все от «%s»" % app)
            close.connect("clicked", lambda _b, ts={x.get("t") for x in ents}: self.drop_many(ts))
            gicon = Gtk.Image.new_from_icon_name(app_icon_name(app, ents), Gtk.IconSize.MENU)
            gicon.set_pixel_size(16)
            gicon.get_style_context().add_class("np-gicon")
            head.pack_start(gicon, False, False, 0)
            head.pack_start(name, True, True, 0)
            head.pack_start(cnt, False, False, 0)
            head.pack_start(close, False, False, 0)
            box.pack_start(head, False, False, 0)
            open_all = app in self.expanded
            shown = ents if open_all else ents[:GROUP_SHOWN]
            for e in shown:
                box.pack_start(self.notif_item(e), False, False, 0)
            rows += 1 + len(shown)
            rest = len(ents) - GROUP_SHOWN
            if rest > 0:
                more = Gtk.Button(label="свернуть" if open_all else "ещё %d" % rest)
                more.get_style_context().add_class("np-more")
                more.connect("clicked", lambda _b, a=app: self.toggle_group(a))
                box.pack_start(more, False, False, 0)
                rows += 1
            self.nlist.pack_start(box, False, False, 0)
        # Высота — явно: строки с переносом GTK3 меряет по ширине в один знак, и
        # прокрутка «по содержимому» схлопывалась до полоски в одну строку.
        self.scroll.set_min_content_height(min(NOTIF_MAX_H, 20 + 52 * rows) if items else 44)
        self.clear_btn.set_sensitive(bool(items))
        self.nlist.show_all()

    def toggle_group(self, app):
        self.expanded.symmetric_difference_update({app})
        self.fill_notifs()

    def notif_item(self, e):
        row = Gtk.Box(spacing=6)
        row.get_style_context().add_class("np-item")
        path = icon_file(e)
        lead = thumb(path) if path else None
        if lead is None and icon_name(e):
            lead = Gtk.Image.new_from_icon_name(icon_name(e), Gtk.IconSize.LARGE_TOOLBAR)
            lead.set_pixel_size(24)
            lead.set_valign(Gtk.Align.START)
            lead.get_style_context().add_class("np-icon")
        if lead is not None:
            row.pack_start(lead, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        row.pack_start(box, True, True, 0)
        top = Gtk.Box(spacing=6)
        s = Gtk.Label(label=e.get("summary") or app_title(e), xalign=0)
        s.set_ellipsize(Pango.EllipsizeMode.END)
        s.get_style_context().add_class("np-summary")
        when = Gtk.Label(label=when_str(e.get("t", 0)), xalign=1)
        when.get_style_context().add_class("np-time")
        close = Gtk.Button(label="×")
        close.get_style_context().add_class("np-close")
        close.set_tooltip_text("Убрать")
        close.connect("clicked", lambda _b, t=e.get("t"): self.drop_many({t}))
        top.pack_start(s, True, True, 0)
        top.pack_start(when, False, False, 0)
        top.pack_start(close, False, False, 0)
        box.pack_start(top, False, False, 0)
        text = " ".join((e.get("body") or "").split())
        if text:
            b = Gtk.Label(label=text, xalign=0)
            b.set_line_wrap(True)
            b.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            b.set_lines(2)
            b.set_ellipsize(Pango.EllipsizeMode.END)
            b.set_max_width_chars(1)
            b.get_style_context().add_class("np-body")
            box.pack_start(b, False, False, 0)
        return row

    def drop_many(self, ts):
        write_notif_log([x for x in read_notif_log() if x.get("t") not in ts])
        self.fill_notifs()

    def on_clear(self, _b):
        # Два щелчка, как в Центре управления: стирается и журнал, и история swaync.
        if self.armed is None:
            self.clear_btn.set_label("Точно?")
            self.armed = GLib.timeout_add(3000, self.disarm)
            return
        GLib.source_remove(self.armed)
        self.disarm()
        write_notif_log([])
        subprocess.Popen(["swaync-client", "-C"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.fill_notifs()

    def disarm(self):
        self.armed = None
        self.clear_btn.set_label("Очистить")
        return False

    # ── календарь ──
    def shift_month(self, delta):
        self.month += delta
        if self.month < 1:
            self.month, self.year = 12, self.year - 1
        elif self.month > 12:
            self.month, self.year = 1, self.year + 1
        self.fill_grid()

    def fill_grid(self):
        for child in list(self.grid.get_children()):
            self.grid.remove(child)
        self.title_lbl.set_text("%s %d" % (MONTHS[self.month - 1], self.year))
        for col, name in enumerate(DAYS):
            lbl = Gtk.Label(label=name)
            ctx = lbl.get_style_context()
            ctx.add_class("cal-dow")
            if col == 6:
                ctx.add_class("cal-dow-sun")
            self.grid.attach(lbl, col, 0, 1, 1)
        weeks = cal_mod.Calendar(firstweekday=0).monthdayscalendar(self.year, self.month)
        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                if day == 0:
                    continue
                lbl = Gtk.Label(label=str(day))
                ctx = lbl.get_style_context()
                ctx.add_class("cal-day")
                if col == 6:
                    ctx.add_class("cal-day-sun")
                if (self.year, self.month, day) == self.today:
                    ctx.add_class("cal-today")
                self.grid.attach(lbl, col, row, 1, 1)
        self.grid.show_all()

    def on_key_press(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        if event.keyval == Gdk.KEY_Left:
            self.shift_month(-1)
            return True
        if event.keyval == Gdk.KEY_Right:
            self.shift_month(1)
            return True
        return False

    def apply_css(self):
        c = dict(self.c)
        c["font"] = FONT
        if self.style == "skeet":
            # Окно Skeet — один в один с Настройками (settings_app.skeet_css, 04.10.2026:
            # «как здесь»): рамка слоями ВНУТРЬ (снаружи: почти чёрная 1, светлая с
            # акцентом 1, средняя 3, светлая 1 — тени по порядку, широкая первой),
            # под ней полоска трёх тонов палитры и та же темнее, заголовок тёмный,
            # группы — в тонкой двойной рамке, шрифт 12 px.
            dark = ", ".join(_mix(x, "#000000", 0.55) for x in c["strip"])
            c.update(strip=", ".join(c["strip"]), strip_d=dark,
                     line1_on=_mix(c["line1"], c["acc"], 0.45))
            css = """
            window { background-color: transparent; }
            .cal-box {
                background-color: %(bg)s; font-family: %(font)s; font-size: 12px; color: %(text)s;
                background-image: linear-gradient(to right, %(strip)s), linear-gradient(to right, %(strip_d)s);
                background-size: 100%% 1px, 100%% 1px; background-repeat: no-repeat, no-repeat;
                background-position: 0 6px, 0 7px;
                box-shadow: inset 0 0 0 6px %(line3)s, inset 0 0 0 5px %(line1_on)s,
                            inset 0 0 0 4px %(line2)s, inset 0 0 0 1px %(line1_on)s;
                border: none; border-radius: 0; margin: 2px; padding: 8px 6px 6px 6px;
            }
            .cal-head {
                background-color: transparent; background-image: none; padding: 2px 8px;
                border-bottom: 1px solid %(line3)s; box-shadow: inset 0 -1px 0 0 %(line2)s;
            }
            .cal-title { color: %(text)s; font-size: 12px; }
            button.cal-nav {
                background-color: transparent; background-image: none; color: %(dim)s;
                border: 1px solid %(line3)s; border-radius: 0; box-shadow: inset 0 0 0 1px %(gline)s;
                padding: 0 6px; min-width: 16px; min-height: 16px; font-size: 12px;
            }
            button.cal-nav:hover { color: %(acc_l)s; }
            .cal-body {
                background-color: transparent; padding: 6px; margin: 6px 8px 4px 8px;
                border: 1px solid %(gline)s; box-shadow: inset 0 0 0 1px %(gdark)s;
            }
            .cal-dow { color: %(dim)s; font-size: 12px; }
            .cal-dow-sun { color: %(acc_l)s; }
            .cal-day { color: %(text)s; padding: 2px; font-size: 12px; }
            .cal-day-sun { color: %(acc_l)s; }
            .cal-today { color: %(acc_l)s; background-color: %(field_l)s; border: 1px solid %(acc_d)s; border-radius: 0; }
            """ % c
        elif self.style == "beta":
            css = """
            window { background-color: transparent; }
            .cal-box {
                background-color: %(bg)s; font-family: %(font)s; font-size: 12px;
                border: 1px solid %(frame)s; border-radius: 0;
                margin: 2px; box-shadow: 0 0 0 1px rgba(0,0,0,0.5);
            }
            .cal-head {
                background-color: %(bar)s; padding: 6px 10px;
                border-style: solid; border-width: 0 0 1px 0; border-color: %(line)s;
            }
            .cal-title { color: %(text)s; font-size: 12px; }
            button.cal-nav {
                background-color: transparent; color: %(text)s; border: none;
                padding: 0 4px; min-width: 16px;
            }
            .cal-body { background-color: %(card)s; padding: 10px; }
            .cal-dow { color: %(dim)s; font-size: 11px; }
            .cal-dow-sun { color: %(acc)s; }
            .cal-day { color: %(text)s; padding: 3px; font-size: 12px; }
            .cal-day-sun { color: %(acc)s; }
            .cal-today { color: %(on_acc)s; background-color: %(acc)s; border-radius: 0; }
            """ % c
        else:
            css = """
            window { background-color: transparent; }
            .cal-box {
                background-color: %(win_bg)s; font-family: %(font)s; font-size: 12px;
                border: 3px solid %(frame)s; border-radius: 0;
                margin: 2px; box-shadow: 0 0 0 1px rgba(0,0,0,0.6);
            }
            .cal-head {
                background-image: linear-gradient(to bottom, %(st_top)s, %(st_mid)s, %(st_bot)s);
                padding: 3px 8px;
                border-style: solid; border-width: 0 0 1px 0; border-color: %(st_dark)s;
                min-height: 20px;
            }
            .cal-title { color: %(accent)s; font-size: 12px; }
            button.cal-nav {
                background-color: transparent; color: %(accent)s; border: none;
                padding: 0 5px; min-width: 18px;
            }
            .cal-body { background-color: %(win_bg)s; padding: 8px; }
            .cal-dow { color: %(dim)s; font-size: 11px; }
            .cal-dow-sun { color: %(sel_bg)s; }
            .cal-day { color: %(text)s; padding: 4px; font-size: 12px; background-color: %(row)s; }
            .cal-day-sun { color: %(sel_bg)s; }
            .cal-today { color: %(sel_text)s; background-color: %(sel_bg)s; border-radius: 0; }
            """ % c
        css += np_css(self.style, c)
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def main():
    a = sys.argv[1:]
    if a[:1] == ["style"]:
        if len(a) > 1 and a[1] in STYLES:
            os.makedirs(os.path.dirname(STYLE_FILE), exist_ok=True)
            with open(STYLE_FILE + ".tmp", "w") as f:
                f.write(a[1] + "\n")
            os.replace(STYLE_FILE + ".tmp", STYLE_FILE)
        print(read_style())
        return
    popup_theme.single_instance(__file__)       # уже открыт — закрыть (второй клик)
    try:
        if time.time() - float(open(CLOSED_AT).read()) < REOPEN_GUARD_S:
            os.remove(CLOSED_AT)
            return                              # плашку только что закрыл этот же клик
    except (OSError, ValueError):
        pass
    XPCalendar()
    Gtk.main()


if __name__ == "__main__":
    main()
