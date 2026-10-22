#!/usr/bin/env python3
"""Wi-Fi и Bluetooth внутри плашки «Энергия» нижней панели (battery_popup.py). 22.10.2026.

Просьбы пользователя: «Wifi & Bluetooth должны быть под ночным режимом, и до
Энергосбережения… не нравится что после клика открывается другая плашка, уже не
стилизованная»; затем «Убираем "выкл". Стрелки делаем чуть больше. При клике на Wifi или
Bluetooth, открывается новая плашка вместо плашки Энергия, где будет кнопка Назад»;
«Размер новой плашки желательно такой же как у энергии».

На главной странице — строка: тумблер радио, серым подключённая сеть, стрелка. Щелчок по
строке — плашка листается на страницу Wi-Fi/Bluetooth (Gtk.Stack той же высоты):
«‹ Назад», тумблер, список с прокруткой. Щелчок по сети/устройству раскрывает кнопки
«Подключиться», «Отключиться», «Забыть» (в два щелчка), у закрытой незнакомой сети — поле
пароля. Логика та же, что в wifi_popup.py / bluetooth_popup.py (их импортировать нельзя:
при импорте они закрывают свой открытый экземпляр). nmcli и bluetoothctl — только в
потоках: подключение длится секунды.
"""
import math
import re
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

CONFIRM = "Точно забыть?"
MAX_ITEMS = 30
POLL_MS = 2500
BT_SCAN_S = 8
CHEV_RIGHT, CHEV_LEFT = "\U000f0142", "\U000f0141"
RESCAN = "\U000f0450"
LOCK = "\U000f033e"


# ── Wi-Fi: nmcli ─────────────────────────────────────────────────────────────
def run(cmd, timeout=45):
    """(успех, текст); stderr важен — в нём текст ошибки."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "истекло время ожидания"
    except OSError as e:
        return False, str(e)


def nmcli(*args, timeout=45):
    return run(["nmcli", *args], timeout)


def wifi_on():
    ok, out = nmcli("radio", "wifi", timeout=3)
    return ok and out.strip() == "enabled"


def wifi_saved():
    ok, out = nmcli("-t", "-f", "NAME,TYPE", "connection", "show", timeout=5)
    return {l.rsplit(":", 1)[0] for l in out.splitlines()
            if l.endswith(":802-11-wireless")} if ok else set()


def wifi_iface():
    ok, out = nmcli("-t", "-f", "DEVICE,TYPE", "device", timeout=5)
    for line in out.splitlines() if ok else ():
        dev, _, kind = line.rpartition(":")
        if kind == "wifi":
            return dev
    return None


def wifi_list(rescan=False):
    """Сети: одно имя — самая сильная точка; подключённая — первой."""
    ok, out = nmcli("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
                    "--rescan", "yes" if rescan else "no", timeout=20 if rescan else 5)
    if not ok:
        return None
    known, nets = wifi_saved(), {}
    for line in out.splitlines():
        parts = [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]
        if len(parts) < 4 or not parts[1]:
            continue
        ssid = parts[1]
        try:
            sig = int(parts[2])
        except ValueError:
            sig = 0
        cur = nets.get(ssid)
        on = parts[0] == "*" or bool(cur and cur["on"])
        if cur is None or sig > cur["signal"]:
            nets[ssid] = {"key": ssid, "name": ssid, "signal": sig, "on": on,
                          "secured": bool(parts[3]) and parts[3] != "--", "known": ssid in known}
        else:
            cur["on"] = on
    return sorted(nets.values(), key=lambda n: (not n["on"], not n["known"], -n["signal"], n["name"].lower()))


def signal_icon(sig):
    return "󰤨" if sig >= 75 else "󰤥" if sig >= 50 else "󰤢" if sig >= 25 else "󰤟"


# ── Bluetooth: bluetoothctl ──────────────────────────────────────────────────
def bt(*args, timeout=45):
    ok, out = run(["bluetoothctl", *args], timeout)
    return ok and "Failed" not in out and "not available" not in out, out


def bt_on():
    ok, out = bt("show", timeout=3)
    return ok and "Powered: yes" in out


def bt_error(out):
    lines = [l for l in out.splitlines() if "Failed" in l or "Error" in l]
    return (lines[-1] if lines else (out.splitlines()[-1] if out else "не удалось")).strip()


def bt_icon(kind):
    k = (kind or "").lower()
    for word, g in (("head", "󰋋"), ("audio", "󰋋"), ("mouse", "󰍽"), ("keyboard", "󰌌"),
                    ("phone", "󰄜"), ("computer", "󰟀"), ("watch", "󰖉")):
        if word in k:
            return g
    return "󰂯"


def bt_list():
    ok, out = bt("devices", timeout=8)
    if not ok:
        return None
    res = []
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 3 or parts[0] != "Device":
            continue
        _i, info = bt("info", parts[1], timeout=8)
        kind = batt = ""
        for l in info.splitlines():
            l = l.strip()
            if l.startswith("Icon:"):
                kind = l.split(":", 1)[1].strip()
            elif l.startswith("Battery Percentage:") and "(" in l:
                batt = l.split("(", 1)[1].rstrip(")").strip() + "%"
        on, known = "Connected: yes" in info, "Paired: yes" in info
        # без имени bluetoothctl подставляет адрес «5D-71-E4-…» — чужие метки из поиска
        # (22.10.2026, просьба: «что это за странные названия?»); своё сопряжённое — оставить
        if not (on or known) and parts[2].replace("-", ":").upper() == parts[1].upper():
            continue
        res.append({"key": parts[1], "name": parts[2], "on": on,
                    "known": known, "kind": kind, "batt": batt})
    return sorted(res, key=lambda d: (not d["on"], not d["known"], d["name"].lower()))


# ── оформление ───────────────────────────────────────────────────────────────
def css(style, p, c, hover):
    """Добавка к CSS плашки: строки списка, кнопки, поле пароля — по стилю."""
    base = """
        .net { border-radius: 8px; padding: 2px 6px; }
        .net:hover { background-color: %(hover)s; }
        .net label.icon { font-size: 12px; }
        label.net-name { font-size: 12px; color: %(on_surface)s; }
        .net.on label.net-name { color: %(primary)s; font-weight: bold; }
        label.dim { color: %(on_surface_variant)s; font-size: 11px; }
        label.big { font-size: 15px; }
        .spin { color: %(on_surface_variant)s; font-size: 15px; }
        .spin.hot, .spin.busy { color: %(primary)s; }
        scrolledwindow.nets, scrolledwindow.nets viewport { background: transparent; border: none; }
        scrolledwindow.nets scrollbar { background: transparent; border: none; }
        scrolledwindow.nets scrollbar slider { min-width: 3px; border: none; border-radius: 3px;
                                               background-color: %(outline_variant)s; }
        label.err { color: %(error)s; font-size: 11px; }
        button.act { min-height: 0; padding: 1px 10px; font-size: 11px; border: none; box-shadow: none;
                     border-radius: 8px; background-image: none;
                     background-color: %(surface_container)s; color: %(primary)s; }
        button.act:hover { background-color: %(surface_high)s; }
        entry.pw { min-height: 20px; padding: 0 6px; font-size: 11px; border-radius: 8px;
                   border: 1px solid %(outline_variant)s; box-shadow: none; background-image: none;
                   background-color: %(surface_container)s; color: %(on_surface)s; }
    """ % dict(p, hover=hover)
    if style == "skeet":
        return base + """
        .net { border-radius: 0; }
        .net:hover { background-color: %(field)s; }
        label.net-name { color: %(text)s; }
        .net.on label.net-name { color: %(acc_l)s; }
        label.dim { color: %(dim)s; }
        .spin { color: %(dim)s; }
        .spin.hot, .spin.busy { color: %(acc_l)s; }
        button.act { border-radius: 0; border: 1px solid %(line2)s; box-shadow: inset 0 0 0 1px %(gdark)s;
                     background-image: linear-gradient(to bottom, %(field_l)s, %(field)s); color: %(text)s; }
        button.act:hover { border-color: %(acc_d)s; color: %(acc_l)s; }
        entry.pw { border-radius: 0; border: 1px solid %(line3)s; background-color: %(field)s;
                   color: %(text)s; box-shadow: inset 0 1px 0 0 alpha(black, 0.25); }
        """ % c
    if style == "beta":
        return base + """
        .net { border-radius: 0; }
        .net:hover { background-color: %(sel)s; }
        label.net-name { color: %(text)s; }
        .net.on label.net-name { color: %(acc)s; }
        label.dim { color: %(dim)s; }
        .spin { color: %(dim)s; }
        .spin.hot, .spin.busy { color: %(acc)s; }
        button.act { border-radius: 0; border: 1px solid %(line)s; background-color: %(field)s; color: %(text)s; }
        button.act:hover { background-color: %(sel)s; }
        entry.pw { border-radius: 0; border: 1px solid %(line)s; background-color: %(field)s; color: %(text)s; }
        """ % c
    return base


def label(text, cls, xalign=0.0):
    w = Gtk.Label(label=text, xalign=xalign)
    w.get_style_context().add_class(cls)
    return w


class Spin(Gtk.EventBox):
    """Кнопка «искать заново»: горит при наведении, крутится, пока идёт поиск.

    22.10.2026, просьба: «не полностью влезла… сделай визуально живую кнопку… при нажатии
    показывать что она обновляется, и закончится когда обновление закончится». Значок
    рисуется сам (DrawingArea): Label в GTK3 не вращается, а глиф шрифта значков шире
    своей клетки — у Label его правый край срезался.
    """
    MIN_MS = 700                 # хоть один оборот: быстрый поиск иначе выглядит как мигание

    def __init__(self, glyph, cb):
        super().__init__()
        self.glyph, self.cb = glyph, cb
        self.angle, self.tick, self.since, self.want = 0.0, 0, 0, False
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(24, 20)
        self.area.get_style_context().add_class("spin")
        self.area.connect("draw", self.draw)
        self.add(self.area)
        self.set_tooltip_text("Искать заново")
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("enter-notify-event", lambda *_: self.mark("hot", True))
        self.connect("leave-notify-event", lambda _w, e: e.detail != Gdk.NotifyType.INFERIOR
                     and self.mark("hot", False))
        self.connect("button-press-event", lambda _w, e: (e.button == 1 and not self.tick
                                                          and self.cb()) or True)

    def mark(self, cls, on):
        ctx = self.area.get_style_context()
        (ctx.add_class if on else ctx.remove_class)(cls)
        self.area.queue_draw()

    def busy(self, on):
        self.want = on
        if on and not self.tick:
            self.since = GLib.get_monotonic_time()
            self.mark("busy", True)
            self.tick = GLib.timeout_add(30, self.step)
        elif not on and self.tick:
            left = self.MIN_MS - (GLib.get_monotonic_time() - self.since) // 1000
            if left > 0:
                GLib.timeout_add(left, lambda: (not self.want and self.stop()) and False)
            else:
                self.stop()

    def stop(self):
        if self.tick:
            GLib.source_remove(self.tick)
        self.tick, self.angle = 0, 0.0
        self.mark("busy", False)

    def step(self):
        self.angle = (self.angle + 0.24) % (2 * math.pi)
        self.area.queue_draw()
        return True

    def draw(self, w, cr):
        ctx = w.get_style_context()
        col = ctx.get_color(ctx.get_state())
        layout = w.create_pango_layout(self.glyph)
        ink, _log = layout.get_pixel_extents()
        cr.translate(w.get_allocated_width() / 2, w.get_allocated_height() / 2)
        cr.rotate(self.angle)
        cr.translate(-(ink.x + ink.width / 2), -(ink.y + ink.height / 2))
        if ctx.has_class("hot") or ctx.has_class("busy"):
            # свечение: тот же значок полупрозрачно со сдвигом на пиксель во все стороны
            cr.set_source_rgba(col.red, col.green, col.blue, col.alpha * 0.22)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                cr.move_to(dx, dy)
                PangoCairo.show_layout(cr, layout)
            cr.move_to(0, 0)
        cr.set_source_rgba(col.red, col.green, col.blue, col.alpha)
        PangoCairo.show_layout(cr, layout)
        return False


# ── раздел ───────────────────────────────────────────────────────────────────
class Radio:
    """Одна строка (Wi-Fi или Bluetooth) на главной странице и своя страница со списком."""

    def __init__(self, sec, kind):
        self.sec, self.kind, self.win = sec, kind, sec.win
        self.wifi = kind == "wifi"
        self.title = "Wi-Fi" if self.wifi else "Bluetooth"
        self.glyph = "󰖩" if self.wifi else "󰂯"
        self.rows = {}               # key -> {"box", "rev", "icon", "name", "right", "item"}
        self.open_key = None         # раскрытая строка списка
        self.busy = self.polling = self.scanning = self.syncing = self.shown = False
        self.poll_id = 0

        on = wifi_on() if self.wifi else bt_on()
        # серым — подключённая сеть/устройство; выключено — пусто (22.10.2026: «убираем выкл»)
        self.hint = label("", "chev")
        self.hint.set_valign(Gtk.Align.CENTER)
        self.hint.set_ellipsize(Pango.EllipsizeMode.END)
        self.hint.set_max_width_chars(11)
        self.chev = label(CHEV_RIGHT, "chev")
        self.chev.get_style_context().add_class("big")
        self.chev.set_valign(Gtk.Align.CENTER)
        self.switch = self.win.pill(on, self.on_switch)
        ctl = Gtk.Box(spacing=6)
        ctl.pack_start(self.hint, False, False, 0)
        ctl.pack_start(self.chev, False, False, 0)
        ctl.pack_start(self.switch, False, False, 0)
        self.head = self.win.row(self.glyph, self.title, ctl)
        # щелчок мимо тумблера — своя страница (тумблер свой щелчок забирает сам)
        self.head.connect("button-press-event", lambda _w, e: e.button == 1 and self.sec.show(self))
        self.page_switch = self.win.pill(on, self.on_switch)
        self.page = self.build_page()
        self.set_hint()

    def build_page(self):
        """Страница вместо «Энергии»: «‹ Назад» и обновить, тумблер, список.

        Высота — как у главной страницы (стек однородный), список прокручивается:
        у ScrolledWindow без propagate высота своя маленькая, поэтому страницу по
        высоте задаёт «Энергия», а список занимает остаток (22.10.2026, просьба: «Размер новой плашки желательно такой же как у энергии»).
        """
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.spin = Spin(RESCAN, lambda: self.refresh(scan=True))
        back = self.win.row(CHEV_LEFT, "Назад", self.spin)
        back.get_child().get_children()[0].get_style_context().add_class("big")
        back.connect("button-press-event", lambda _w, e: e.button == 1 and self.sec.back())
        page.pack_start(back, False, False, 0)
        page.pack_start(self.win.rule(), False, False, 0)
        page.pack_start(self.win.row(self.glyph, self.title, self.page_switch), False, False, 0)
        page.pack_start(self.win.rule(), False, False, 0)

        self.status = label("", "dim")
        self.status.set_line_wrap(True)
        self.status.set_margin_start(6)
        self.status.set_no_show_all(True)
        page.pack_start(self.status, False, False, 0)
        self.items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.items.set_valign(Gtk.Align.START)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.get_style_context().add_class("nets")
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_min_content_height(40)
        self.scroll.add(self.items)
        self.scroll.get_child().set_shadow_type(Gtk.ShadowType.NONE)
        page.pack_start(self.scroll, True, True, 0)
        return page

    # ── шапка ──
    def set_hint(self, items=None):
        if items is None:
            threading.Thread(target=lambda: GLib.idle_add(
                self.set_hint, (wifi_list() if self.wifi else bt_list()) or []), daemon=True).start()
            return False
        on = self.switch.get_active()
        self.hint.set_text(next((i["name"] for i in items if i["on"]), "") if on else "")
        return False

    def on_switch(self, on):
        # два тумблера (главная и страница) — одно радио
        if self.syncing:
            return
        self.syncing = True
        for sw in (self.switch, self.page_switch):
            if sw.get_active() != on:
                sw.set_active(on)
        self.syncing = False
        if self.wifi:
            cmd = ["nmcli", "radio", "wifi", "on" if on else "off"]
        else:
            # выключенный через rfkill адаптер bluetoothctl не включит
            cmd = (["sh", "-c", "rfkill unblock bluetooth; bluetoothctl power on"] if on
                   else ["bluetoothctl", "power", "off"])

        def work():
            run(cmd, 10)
            GLib.timeout_add(800 if self.wifi else 400, self.after_switch)
        threading.Thread(target=work, daemon=True).start()

    def after_switch(self):
        self.set_hint()
        if self.shown:
            self.refresh(scan=self.switch.get_active())
        return False

    # ── страница открыта / закрыта ──
    def set_shown(self, show):
        self.shown = show
        if show:
            self.refresh(scan=True)
            if not self.poll_id:
                self.poll_id = GLib.timeout_add(POLL_MS, self.poll)
        elif self.poll_id:
            GLib.source_remove(self.poll_id)
            self.poll_id = 0

    def poll(self):
        if not self.shown:
            self.poll_id = 0
            return False
        self.refresh()
        return True

    def say(self, text, err=False):
        ctx = self.status.get_style_context()
        (ctx.add_class if err else ctx.remove_class)("err")
        self.status.set_text(text)
        self.status.set_visible(bool(text))

    def refresh(self, scan=False):
        if not self.switch.get_active():
            self.apply([])
            self.say(("Wi-Fi" if self.wifi else "Bluetooth") + " выключен")
            return
        # поиск — сам по себе: щелчок по «искать заново» во время опроса не теряется
        if scan and not self.scanning:
            self.scanning = True
            self.spin.busy(True)
            if not self.rows:
                self.say("Поиск…")

            def scan_work():
                if self.wifi:
                    items = wifi_list(rescan=True)
                else:
                    bt("--timeout", str(BT_SCAN_S), "scan", "on", timeout=BT_SCAN_S + 15)
                    items = bt_list()
                GLib.idle_add(self.scan_done, items)
            threading.Thread(target=scan_work, daemon=True).start()
        if self.polling:
            return
        self.polling = True

        def work():
            GLib.idle_add(self.apply, wifi_list() if self.wifi else bt_list())
        threading.Thread(target=work, daemon=True).start()

    def scan_done(self, items):
        self.scanning = False
        self.spin.busy(False)
        if items is not None and self.shown:
            self.polling = True
            self.apply(items)
        return False

    # ── список ──
    def apply(self, items):
        self.polling = False
        if items is None:
            self.say("NetworkManager не ответил" if self.wifi else "bluetoothctl не ответил", err=True)
            return False
        if self.switch.get_active():
            if items:
                if self.status.get_text() in ("Поиск…", "Ничего не найдено"):
                    self.say("")
            elif not self.scanning:
                self.say("Ничего не найдено")
        hint_items = items
        # подключённая и сохранённые — первыми (сортировка), дальше самые сильные
        items = items[:MAX_ITEMS]
        if self.open_key and self.open_key not in [i["key"] for i in items]:
            items += [i for i in hint_items if i["key"] == self.open_key]
        keys = [i["key"] for i in items]
        for key in list(self.rows):
            if key not in keys and key != self.open_key:
                self.rows.pop(key)["box"].destroy()
        for n, item in enumerate(items):
            r = self.rows.get(item["key"]) or self.make_row(item)
            self.update_row(r, item)
            self.items.reorder_child(r["box"], n)
        self.set_hint(hint_items)
        return False

    def make_row(self, item):
        key = item["key"]
        line = Gtk.EventBox()
        line.get_style_context().add_class("net")
        hb = Gtk.Box(spacing=8)
        icon = label("", "icon")
        name = label("", "net-name")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(16)
        right = label("", "dim", 1.0)
        hb.pack_start(icon, False, False, 0)
        hb.pack_start(name, True, True, 0)
        hb.pack_start(right, False, False, 0)
        line.add(hb)
        line.connect("button-press-event", lambda _w, e: e.button == 1 and self.toggle_row(key) or True)
        rev = Gtk.Revealer()
        rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        rev.set_transition_duration(150)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(line, False, False, 0)
        box.pack_start(rev, False, False, 0)
        box.show_all()
        self.items.pack_start(box, False, False, 0)
        r = {"box": box, "line": line, "rev": rev, "icon": icon, "name": name, "right": right, "item": item}
        self.rows[key] = r
        return r

    def update_row(self, r, item):
        old = r["item"]
        r["item"] = item
        ctx = r["line"].get_style_context()
        (ctx.add_class if item["on"] else ctx.remove_class)("on")
        r["name"].set_text(item["name"])
        if self.wifi:
            r["icon"].set_text(signal_icon(item["signal"]))
            r["right"].set_text(LOCK if item["secured"] and not item["known"] else "")
        else:
            r["icon"].set_text(bt_icon(item["kind"]))
            r["right"].set_text(item["batt"])
        # раскрытая строка поменяла состояние (подключилась/отключилась) — кнопки заново
        if self.open_key == item["key"] and not self.busy and (
                (old["on"], old["known"]) != (item["on"], item["known"])):
            self.fill_detail(r)

    def toggle_row(self, key):
        if self.open_key and self.open_key in self.rows:
            self.rows[self.open_key]["rev"].set_reveal_child(False)
        if self.open_key == key:
            self.open_key = None
            return
        self.open_key = key
        r = self.rows[key]
        self.fill_detail(r)
        r["rev"].set_reveal_child(True)

    def button(self, text, cb):
        b = Gtk.Button(label=text)
        b.get_style_context().add_class("act")
        b.connect("clicked", cb)
        return b

    def fill_detail(self, r, msg=None, err=False):
        child = r["rev"].get_child()
        if child:
            child.destroy()
        it = r["item"]
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        v.set_margin_start(20)
        v.set_margin_top(2)
        v.set_margin_bottom(4)
        if msg is None:
            if self.wifi:
                msg = "Подключено" if it["on"] else (
                    "Сохранённая сеть" if it["known"] else "Нужен пароль" if it["secured"] else "Открытая сеть")
                msg += " · сигнал %d%%" % it["signal"]
            else:
                msg = "Подключено" if it["on"] else "Сопряжено" if it["known"] else "Новое устройство"
        m = label(msg, "err" if err else "dim")
        m.set_line_wrap(True)
        m.set_max_width_chars(28)
        v.pack_start(m, False, False, 0)
        r["msg"] = m
        entry = None
        if self.wifi and not it["on"] and not it["known"] and it["secured"]:
            entry = Gtk.Entry()
            entry.get_style_context().add_class("pw")
            entry.set_visibility(False)
            entry.set_placeholder_text("Пароль")
            entry.connect("activate", lambda _e: self.connect_item(r, entry))
            v.pack_start(entry, False, False, 0)
        btns = Gtk.Box(spacing=6)
        if it["on"]:
            btns.pack_start(self.button("Отключиться", lambda _b: self.disconnect_item(r)), False, False, 0)
        else:
            btns.pack_start(self.button("Подключиться", lambda _b: self.connect_item(r, entry)), False, False, 0)
        if it["known"]:
            btns.pack_start(self.button("Забыть", lambda b: self.forget_item(r, b)), False, False, 0)
        v.pack_start(btns, False, False, 0)
        r["rev"].add(v)
        v.show_all()
        if entry is not None:
            # в поле печатают — клавиатура плашке нужна только сейчас
            GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.ON_DEMAND)
            GLib.idle_add(lambda: entry.grab_focus() and False)

    def act(self, r, text, work, done_text):
        if self.busy:
            return
        self.busy = True
        r["msg"].set_text(text)
        r["msg"].get_style_context().remove_class("err")

        def th():
            ok, out = work()
            GLib.idle_add(self.finished, r, ok, out, done_text)
        threading.Thread(target=th, daemon=True).start()

    def finished(self, r, ok, out, done_text):
        self.busy = False
        if ok:
            self.refresh()
            self.fill_detail(r, done_text)
        else:
            err = bt_error(out) if not self.wifi else (out.splitlines()[-1] if out else "не удалось")
            err = re.sub(r"^Error:\s*", "", err)
            self.fill_detail(r, err[:120], err=True)
        return False

    def connect_item(self, r, entry):
        it = r["item"]
        key = it["key"]
        if self.wifi:
            pw = entry.get_text() if entry is not None else ""
            if entry is not None and not pw:
                r["msg"].set_text("Введите пароль")
                return

            def work():
                if it["known"]:
                    return nmcli("connection", "up", "id", key)
                if pw:
                    return nmcli("device", "wifi", "connect", key, "password", pw)
                return nmcli("device", "wifi", "connect", key)
        else:
            def work():
                if not it["known"]:
                    ok, out = bt("pair", key)
                    if not ok:
                        return ok, out
                    bt("trust", key, timeout=10)
                return bt("connect", key)
        self.act(r, "Подключение…", work, "Подключено")

    def disconnect_item(self, r):
        key = r["item"]["key"]
        if self.wifi:
            def work():
                dev = wifi_iface()
                return nmcli("device", "disconnect", dev) if dev else (False, "нет Wi-Fi адаптера")
        else:
            def work():
                return bt("disconnect", key)
        self.act(r, "Отключение…", work, "Отключено")

    def forget_item(self, r, b):
        """Забыть — в два щелчка: первый спрашивает, через 3 с вопрос снимается."""
        if b.get_label() != CONFIRM:
            b.set_label(CONFIRM)
            GLib.timeout_add(3000, lambda: b.get_label() == CONFIRM and b.set_label("Забыть") and False)
            return
        key = r["item"]["key"]
        self.act(r, "Удаление…", (lambda: nmcli("connection", "delete", "id", key)) if self.wifi
                 else (lambda: bt("remove", key)), "Забыто")


class Radios:
    """Wi-Fi и Bluetooth: две строки на главной, у каждой своя страница в стеке плашки."""

    def __init__(self, win):
        self.win = win
        self.wifi, self.bt = Radio(self, "wifi"), Radio(self, "bt")
        self.stack = None

    def widget(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for r in (self.wifi, self.bt):
            box.pack_start(r.head, False, False, 0)
        return box

    def wrap(self, main):
        """Стек «Энергия» ⇄ страницы; однородный — страница того же размера, что главная."""
        self.stack = Gtk.Stack()
        self.stack.set_homogeneous(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(180)
        self.stack.add_named(main, "main")
        for r in (self.wifi, self.bt):
            self.stack.add_named(r.page, r.kind)
        return self.stack

    def show(self, radio):
        for r in (self.wifi, self.bt):
            r.set_shown(r is radio)
        self.stack.set_visible_child_name(radio.kind)

    def back(self):
        for r in (self.wifi, self.bt):
            r.set_shown(False)
        self.stack.set_visible_child_name("main")
        GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.NONE)
