#!/usr/bin/env python3
"""Попап Bluetooth для waybar (правый клик по модулю).

Как пользоваться. Сверху — подключённые устройства (подсвечены), дальше
сопряжённые, дальше новые, найденные поиском (󰐷). Щелчок по устройству НЕ
подключает сразу, а раскрывает под ним панель: что это за устройство и
кнопки «Подключиться» / «Отключиться» / «Забыть» — та же схема, что в попапе
Wi-Fi. Пароля у Bluetooth нет: новое устройство при подключении сопрягается
и помечается доверенным, дальше подключается без вопросов. Справа в строке —
заряд, если устройство его сообщает. Список обновляется сам, пока попап
открыт; высота окна — по числу устройств, без пустого поля.

Что чинилось раньше и должно остаться починенным:

  * Выключатель звал только `bluetoothctl power on`. Когда адаптер заблокирован
    в rfkill — а на этой машине он именно в таком состоянии, `PowerState:
    off-blocked`, — эта команда молча не срабатывает. Теперь перед включением
    снимается блокировка rfkill.
  * bluetoothctl вызывается только в отдельном потоке: подключение занимает
    секунды, и в главном потоке попап был бы заморожен.
  * Ошибки показываются — прямо в панели устройства.
  * Цвета берутся из обоев (popup_theme), а не зашиты.
"""
import os
import subprocess
import sys
import threading
import time

import gi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

# Второй щелчок по модулю закрывает открытый попап — см. popup_theme.single_instance.
popup_theme.single_instance(__file__)

gi.require_version("Gtk", "3.0")
# Gdk явно: иначе gi может успеть подтянуть Gdk 4.0 от gtk4-layer-shell.
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

# Опрос состояния устройств, пока попап открыт. Замерено: info на устройство
# отрабатывает за ~3 мс, так что это дёшево.
POLL_MS = 2500
ANIM_MS = 200
# Предел высоты списка; меньше устройств — окно короче.
MAX_LIST_H = 360
SCAN_S = 8
CONFIRM = "Точно забыть?"

EXTRA_CSS = """
spinner { color: %(primary)s; }
label.dim { color: %(on_surface_variant)s; font-weight: normal; font-size: 11px; }
label.msg-err { color: %(error)s; font-weight: normal; font-size: 11px; }
.detail { padding: 2px 4px 6px 4px; }
button.small { padding: 2px 10px; font-size: 11px; margin: 0; min-height: 0; }
"""


def bt(*args, timeout=45):
    """bluetoothctl -> (успех, текст). Возвращаемый код у него не всегда
    честный, поэтому неудача определяется ещё и по слову Failed в выводе."""
    try:
        r = subprocess.run(["bluetoothctl", *args], capture_output=True,
                           text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        ok = r.returncode == 0 and "Failed" not in out and "not available" not in out
        return ok, out
    except subprocess.TimeoutExpired:
        return False, "истекло время ожидания"
    except OSError as e:
        return False, str(e)


def bt_error(out):
    lines = [l for l in out.splitlines() if "Failed" in l or "Error" in l]
    return (lines[-1] if lines else (out.splitlines()[-1] if out else "не удалось")).strip()


def powered():
    ok, out = bt("show", timeout=5)
    return ok and "Powered: yes" in out


def blocked():
    try:
        out = subprocess.check_output(["rfkill", "list", "bluetooth"], text=True,
                                      timeout=5)
        return "Soft blocked: yes" in out or "Hard blocked: yes" in out
    except Exception:
        return False


def device_icon(kind):
    k = (kind or "").lower()
    if "headset" in k or "headphone" in k or "audio" in k:
        return "󰋋"
    if "mouse" in k:
        return "󰍽"
    if "keyboard" in k:
        return "󰌌"
    if "phone" in k:
        return "󰄜"
    if "computer" in k:
        return "󰟀"
    if "watch" in k:
        return "󰖉"
    return "󰂯"


def devices():
    """Список устройств: mac, name, conn, pair, kind, batt — один info на каждое."""
    ok, out = bt("devices", timeout=8)
    if not ok:
        return []
    res = []
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 3 or parts[0] != "Device":
            continue
        mac, name = parts[1], parts[2]
        _iok, info = bt("info", mac, timeout=8)
        kind = batt = ""
        for l in info.splitlines():
            l = l.strip()
            if l.startswith("Icon:"):
                kind = l.split(":", 1)[1].strip()
            elif l.startswith("Battery Percentage:") and "(" in l:
                batt = l.split("(", 1)[1].rstrip(")").strip()
        res.append({"mac": mac, "name": name, "conn": "Connected: yes" in info,
                    "pair": "Paired: yes" in info, "kind": kind, "batt": batt})
    # Подключённые вверх, затем сопряжённые, затем остальные.
    res.sort(key=lambda d: (not d["conn"], not d["pair"], d["name"].lower()))
    return res


class BluetoothPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Bluetooth")
        self.busy = False          # идёт действие с устройством
        self.scanning = False      # идёт поиск
        self.polling = False       # в полёте опрос
        self.rows = {}             # mac -> виджеты и данные строки
        self.expanded = None       # mac раскрытой строки

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        provider = Gtk.CssProvider()
        provider.load_from_data(popup_theme.css(popup_theme.COMPACT_CSS + EXTRA_CSS))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.bg = Gtk.EventBox()
        self.bg.connect("button-press-event", lambda w, e: sys.exit(0))
        self.add(self.bg)

        self.align = Gtk.Box()
        self.bg.add(self.align)
        # Прямо под баром и серединой под точкой щелчка — см. popup_theme.
        popup_theme.place_under_cursor(self.align)

        self.popup_event = Gtk.EventBox()
        self.popup_event.connect("button-press-event", lambda w, e: True)
        self.align.add(self.popup_event)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.get_style_context().add_class("popup-box")
        # Только ширина. Раньше высота была жёсткой, 430, и при выключенном
        # Bluetooth окно было почти пустым коробом. 260, а не 300 (24.09.2026,
        # «сделай компактнее»): строк длиннее в окне больше нет.
        vbox.set_size_request(260, -1)
        self.popup_event.add(vbox)

        # ── шапка ──
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.pack_start(Gtk.Label(label="  Bluetooth", xalign=0), True, True, 0)
        # Кнопка поиска и крутилка делят одно место: пока идёт поиск, на месте
        # кнопки вращается индикатор.
        self.scan_stack = Gtk.Stack()
        self.scan_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.scan_stack.set_transition_duration(150)
        scan_btn = Gtk.Button(label="󰐷")
        scan_btn.get_style_context().add_class("item")
        scan_btn.get_style_context().add_class("icon")
        scan_btn.set_tooltip_text("Искать новые устройства")
        scan_btn.connect("clicked", self.start_scan)
        self.spinner = Gtk.Spinner()
        self.scan_stack.add_named(scan_btn, "idle")
        self.scan_stack.add_named(self.spinner, "busy")
        header.pack_start(self.scan_stack, False, False, 0)
        self.bt_switch = Gtk.Switch()
        self.bt_switch.set_active(powered())
        self.switch_handler = self.bt_switch.connect("notify::active", self.on_toggle)
        header.pack_start(self.bt_switch, False, False, 4)
        vbox.pack_start(header, False, False, 0)

        # ── список ──
        # Список прячется, когда показывать нечего (выключено или устройств нет):
        # пустая прокрутка всё равно занимала высоту, и между шапкой и надписью
        # стояла пустая полоса (24.09.2026). Показывает её update_empty.
        self.scroll = scroll = Gtk.ScrolledWindow()
        scroll.set_no_show_all(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(MAX_LIST_H)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroll.add(self.list_box)
        vbox.pack_start(scroll, True, True, 0)

        self.empty = Gtk.Label(label="")
        self.empty.set_justify(Gtk.Justification.CENTER)
        self.empty.get_style_context().add_class("dim")
        self.empty.set_no_show_all(True)
        vbox.pack_start(self.empty, False, False, 2)

        # Сообщения о питании и поиске. Пустая — не видна и места не занимает.
        self.status = Gtk.Label(label="", xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(30)
        self.status.set_no_show_all(True)
        vbox.pack_start(self.status, False, False, 0)

        self.connect("key-press-event", self.on_key)
        self.poll()
        GLib.timeout_add(POLL_MS, self.poll)

    # ── ввод ──────────────────────────────────────────────────────────────
    def on_key(self, _w, event):
        """Escape сворачивает раскрытое устройство, а если свёрнуто — закрывает."""
        if event.keyval == Gdk.KEY_Escape:
            if self.expanded:
                self.collapse()
                return True
            sys.exit(0)
        return False

    def set_status(self, text, error=False):
        ctx = self.status.get_style_context()
        ctx.remove_class("dim")
        ctx.remove_class("msg-err")
        ctx.add_class("msg-err" if error else "dim")
        self.status.set_text(text)
        self.status.set_visible(bool(text))
        return False

    # ── питание ───────────────────────────────────────────────────────────
    def on_toggle(self, sw, _g):
        want = sw.get_active()
        self.set_status("Включаю…" if want else "Выключаю…")

        def work():
            if want:
                # Снять блокировку ОБЯЗАТЕЛЬНО до power on: у заблокированного
                # адаптера состояние off-blocked, и power on на нём просто не
                # срабатывает. Именно из-за этого тумблер раньше выглядел мёртвым.
                subprocess.run(["rfkill", "unblock", "bluetooth"],
                               capture_output=True, timeout=10)
                ok, out = False, ""
                # Адаптеру нужно мгновение, чтобы появиться после разблокировки.
                for _ in range(6):
                    ok, out = bt("power", "on", timeout=10)
                    if ok:
                        break
                    time.sleep(0.3)
            else:
                ok, out = bt("power", "off", timeout=10)
                subprocess.run(["rfkill", "block", "bluetooth"],
                               capture_output=True, timeout=10)
            GLib.idle_add(self.after_power, ok, out, want)
        threading.Thread(target=work, daemon=True).start()

    def after_power(self, ok, out, want):
        if not ok:
            self.set_status(out.splitlines()[-1] if out else "не удалось переключить",
                            error=True)
            # Вернуть тумблер в реальное положение, не вызывая обработчик заново.
            self.bt_switch.handler_block(self.switch_handler)
            self.bt_switch.set_active(powered())
            self.bt_switch.handler_unblock(self.switch_handler)
        else:
            self.set_status("")
        self.poll()
        return False

    # ── поиск и опрос ─────────────────────────────────────────────────────
    def start_scan(self, *_a):
        if self.scanning or not self.bt_switch.get_active():
            return False
        self.scanning = True
        # Stack не переключается на невидимый элемент — крутилка делает себя
        # видимой сама.
        self.spinner.show()
        self.scan_stack.set_visible_child_name("busy")
        self.spinner.start()

        def work():
            # Эта команда держится все SCAN_S секунд — ровно столько и крутится
            # индикатор, а опрос тем временем вносит найденное в список.
            bt("--timeout", str(SCAN_S), "scan", "on", timeout=SCAN_S + 15)
            GLib.idle_add(self.scan_done)
        threading.Thread(target=work, daemon=True).start()
        self.update_empty()
        return False

    def scan_done(self):
        self.scanning = False
        self.spinner.stop()
        self.scan_stack.set_visible_child_name("idle")
        self.poll()
        return False

    def poll(self):
        if self.polling:
            return True
        if not self.bt_switch.get_active():
            self.show_off()
            return True
        self.polling = True

        def work():
            GLib.idle_add(self.apply, devices())
        threading.Thread(target=work, daemon=True).start()
        return True

    # ── строки ────────────────────────────────────────────────────────────
    def make_row(self, dev):
        mac = dev["mac"]
        rev = Gtk.Revealer()
        rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        rev.set_transition_duration(ANIM_MS)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        btn = Gtk.Button()
        btn.get_style_context().add_class("item")
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Label()
        name = Gtk.Label(xalign=0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_hexpand(True)
        mark = Gtk.Label()
        mark.get_style_context().add_class("dim")
        h.pack_start(icon, False, False, 0)
        h.pack_start(name, True, True, 0)
        h.pack_end(mark, False, False, 0)
        btn.add(h)
        btn.connect("clicked", lambda _b, m=mac: self.toggle_row(m))

        drev = Gtk.Revealer()
        drev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        drev.set_transition_duration(ANIM_MS)
        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        detail.get_style_context().add_class("detail")
        drev.add(detail)

        box.pack_start(btn, False, False, 0)
        box.pack_start(drev, False, False, 0)
        rev.add(box)
        self.list_box.pack_start(rev, False, False, 0)
        rev.show_all()
        row = {"rev": rev, "btn": btn, "icon": icon, "name": name, "mark": mark,
               "drev": drev, "detail": detail, "dev": dev, "gone": False,
               "key": None, "msg": None, "btns": None}
        self.update_row(row, dev)
        return row

    def update_row(self, row, dev):
        row["dev"] = dev
        pairs = ((row["icon"], device_icon(dev["kind"])),
                 (row["name"], dev["name"]),
                 (row["mark"], f"{dev['batt']}%" if dev["batt"] else ""))
        for lbl, text in pairs:
            if lbl.get_text() != text:
                lbl.set_text(text)
        ctx = row["btn"].get_style_context()
        want, drop = ("item-active", "item") if dev["conn"] else ("item", "item-active")
        if not ctx.has_class(want):
            ctx.remove_class(drop)
            ctx.add_class(want)
        # Состояние поменялось, пока панель раскрыта, — перерисовать кнопки.
        if (self.expanded == dev["mac"] and not self.busy
                and row["key"] != (dev["conn"], dev["pair"], dev["batt"])):
            self.fill_detail(row)

    def toggle_row(self, mac):
        if self.busy:
            return
        if self.expanded == mac:
            self.collapse()
            return
        self.collapse()
        row = self.rows.get(mac)
        if not row:
            return
        self.expanded = mac
        self.fill_detail(row)
        row["drev"].set_reveal_child(True)

    def collapse(self):
        row = self.rows.get(self.expanded) if self.expanded else None
        if row:
            row["drev"].set_reveal_child(False)
        self.expanded = None

    def small_button(self, label, cls, cb):
        b = Gtk.Button(label=label)
        b.get_style_context().add_class(cls)
        b.get_style_context().add_class("small")
        b.connect("clicked", cb)
        return b

    def fill_detail(self, row):
        detail = row["detail"]
        for c in detail.get_children():
            detail.remove(c)
        dev = row["dev"]
        row["key"] = (dev["conn"], dev["pair"], dev["batt"])

        if dev["conn"]:
            caption = "Подключено" + (f" · заряд {dev['batt']}%" if dev["batt"] else "")
        elif dev["pair"]:
            caption = "Сопряжено — подключится без подтверждения"
        else:
            caption = "Новое устройство — при подключении будет сопряжено"
        cap = Gtk.Label(label=caption, xalign=0)
        cap.set_line_wrap(True)
        cap.set_max_width_chars(34)
        cap.get_style_context().add_class("dim")
        detail.pack_start(cap, False, False, 0)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if dev["conn"]:
            btns.pack_start(self.small_button(
                "Отключиться", "item", lambda _b: self.do_disconnect(row)), True, True, 0)
        else:
            btns.pack_start(self.small_button(
                "Подключиться", "go", lambda _b: self.do_connect(row)), True, True, 0)
        if dev["pair"]:
            btns.pack_start(self.small_button(
                "Забыть", "item", lambda b: self.do_forget(row, b)), True, True, 0)
        detail.pack_start(btns, False, False, 0)

        msg = Gtk.Label(xalign=0)
        msg.set_line_wrap(True)
        msg.set_max_width_chars(34)
        msg.set_no_show_all(True)
        detail.pack_start(msg, False, False, 0)
        row["msg"], row["btns"] = msg, btns
        detail.show_all()

    def set_msg(self, row, text, error=False):
        msg = row["msg"]
        if msg is None:
            return
        ctx = msg.get_style_context()
        ctx.remove_class("dim")
        ctx.remove_class("msg-err")
        ctx.add_class("msg-err" if error else "dim")
        msg.set_text(text)
        msg.set_visible(bool(text))

    # ── действия ──────────────────────────────────────────────────────────
    def run(self, row, text, work, on_ok):
        self.busy = True
        row["btns"].set_sensitive(False)
        self.set_msg(row, text)

        def th():
            ok, out = work()
            GLib.idle_add(self.finish, row, ok, out, on_ok)
        threading.Thread(target=th, daemon=True).start()

    def finish(self, row, ok, out, on_ok):
        self.busy = False
        if row["btns"]:
            row["btns"].set_sensitive(True)
        if ok:
            on_ok()
        else:
            self.set_msg(row, bt_error(out), error=True)
        self.poll()
        return False

    def do_connect(self, row):
        if self.busy:
            return
        mac, paired = row["dev"]["mac"], row["dev"]["pair"]

        def work():
            if not paired:
                # Незнакомое устройство: сопряжение, доверие, потом
                # подключение. Без trust bluez будет переспрашивать при каждом
                # следующем соединении.
                ok, out = bt("pair", mac)
                if not ok:
                    return ok, out
                bt("trust", mac, timeout=10)
            return bt("connect", mac)
        self.run(row, "Сопряжение и подключение…" if not paired else "Подключение…",
                 work, lambda: self.set_msg(row, "Подключено"))

    def do_disconnect(self, row):
        if self.busy:
            return
        mac = row["dev"]["mac"]
        self.run(row, "Отключение…", lambda: bt("disconnect", mac),
                 lambda: self.set_msg(row, "Отключено"))

    def do_forget(self, row, btn):
        """Забыть = удалить сопряжение (bluetoothctl remove). Поэтому в два
        щелчка: первый только спрашивает, и через 3 с вопрос снимается."""
        if self.busy:
            return
        if btn.get_label() != CONFIRM:
            btn.set_label(CONFIRM)

            def reset():
                if btn.get_label() == CONFIRM:
                    btn.set_label("Забыть")
                return False
            GLib.timeout_add(3000, reset)
            return
        mac = row["dev"]["mac"]
        self.run(row, "Удаляю сопряжение…", lambda: bt("remove", mac),
                 lambda: self.set_msg(row, "Устройство забыто"))

    # ── список ────────────────────────────────────────────────────────────
    def apply(self, devs):
        self.polling = False
        if not self.bt_switch.get_active():
            return False
        order = []
        first = not getattr(self, "filled", False)
        self.filled = True
        for dev in devs:
            row = self.rows.get(dev["mac"])
            if row is None:
                row = self.make_row(dev)
                if first:
                    # Первый список — сразу, без выезда: анимация Revealer идёт по кадрам
                    # окна, и у только что показанного слоя строки оставались высотой 1 px —
                    # плашка открывалась пустой, хотя наушники подключены (04.10.2026).
                    row["rev"].set_transition_duration(0)
                    GLib.timeout_add(ANIM_MS + 50, lambda r=row["rev"]: r.set_transition_duration(ANIM_MS) or False)
                self.rows[dev["mac"]] = row
            else:
                self.update_row(row, dev)
            row["gone"] = False
            row["rev"].set_reveal_child(True)
            order.append(row)

        fresh = {d["mac"] for d in devs}
        for mac, row in list(self.rows.items()):
            if mac not in fresh and not row["gone"]:
                row["gone"] = True
                row["rev"].set_reveal_child(False)
                GLib.timeout_add(ANIM_MS + 60, self.drop_row, mac)

        # Пока устройство раскрыто, порядок не трогаем: строка не должна
        # уезжать из-под руки.
        if self.expanded is None:
            children = self.list_box.get_children()
            for i, row in enumerate(order):
                if i >= len(children) or children[i] is not row["rev"]:
                    self.list_box.reorder_child(row["rev"], i)
                    children = self.list_box.get_children()
        self.update_empty()
        return False

    def drop_row(self, mac):
        row = self.rows.get(mac)
        if row and row["gone"]:
            if self.expanded == mac:
                self.expanded = None
            self.list_box.remove(row["rev"])
            del self.rows[mac]
        return False

    def update_empty(self):
        if any(not r["gone"] for r in self.rows.values()):
            # У прокрутки no_show_all, и show_all окна не показал ни её, ни список
            # внутри: scroll.show() открывал пустую рамку — плашка была пустой при
            # подключённых наушниках (04.10.2026). Показываем всю цепочку.
            self.scroll.show()
            if self.scroll.get_child():
                self.scroll.get_child().show()
            self.list_box.show()
            self.empty.hide()
            return
        self.scroll.hide()
        self.empty.set_text("Ищу устройства…" if self.scanning
                            else "Устройств нет — 󰐷 найдёт новые")
        self.empty.show()

    def show_off(self):
        self.collapse()
        for row in self.rows.values():
            row["rev"].set_reveal_child(False)
        self.scroll.hide()
        # Две короткие строки: одна длинная растягивала окно до 431 px.
        note = "Bluetooth выключен"
        if blocked():
            note = "Выключен и заблокирован —\nтумблер снимет блокировку"
        if self.empty.get_text() != note:
            self.empty.set_text(note)
        self.empty.show()


if __name__ == "__main__":
    win = BluetoothPopup()
    win.show_all()
    Gtk.main()
