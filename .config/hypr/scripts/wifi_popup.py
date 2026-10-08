#!/usr/bin/env python3
"""Попап Wi-Fi для waybar (правый клик по модулю сети).

Как пользоваться. Сверху — подключённая сеть, она подсвечена. Щелчок по
любой сети НЕ подключает сразу, а раскрывает под ней маленькую панель: что
это за сеть и кнопки «Подключиться» / «Отключиться» / «Забыть». Для закрытой
незнакомой сети там же поле пароля. Значок замка у сети — «нужен пароль»:
для открытых и уже сохранённых сетей его нет, они подключаются без вопросов.

Раньше щелчок подключал сразу, а у сохранённых сетей стояла галочка ✓, смысл
которой приходилось объяснять; забыть сеть было нельзя вовсе.

Живой список. При открытии сразу запускается поиск (`list --rescan yes`
ждёт конца скана, в отличие от `device wifi rescan`, который выходит сразу —
замерено 3.2 с против 0.0 с), а раз в POLL_MS список спрашивает у
NetworkManager, что тот уже нашёл, и правит строки на месте: новые выезжают,
пропавшие сворачиваются. Поле поиска фильтрует сети по имени.

nmcli всегда запускается в отдельном потоке: connect держит соединение до
ответа NetworkManager, и в главном потоке попап на это время замерзал бы.
"""
import os
import re
import subprocess
import sys
import threading

import gi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

SELF = os.path.abspath(__file__)

# Как часто спрашивать у NetworkManager свежий список. Дешёвый запрос
# (--rescan no, только чтение того, что NM уже знает), а не пересканирование.
POLL_MS = 2000
# Длительность выезда/сворачивания строк.
ANIM_MS = 200
# Предел высоты списка. Выше — прокрутка; меньше сетей — окно короче, без
# пустого поля снизу (раньше высота была жёсткой, 430).
MAX_LIST_H = 360
CONFIRM = "Точно забыть?"


def _is_this_popup(p):
    """Точно ли это ещё один экземпляр попапа, а не случайный процесс.

    Раньше здесь было `pgrep -f wifi_popup.py` + `kill -9` по всем найденным
    PID. pgrep -f сравнивает со ВСЕЙ командной строкой, поэтому под раздачу
    попадал любой процесс, у которого имя скрипта просто встречается в
    аргументах, — редактор с открытым файлом, оболочка с этой командой в
    строке. Теперь совпадение подтверждается по /proc: argv[0] должен быть
    питоном, а argv[1] — этим самым файлом.
    """
    try:
        with open(f"/proc/{p}/cmdline", "rb") as f:
            argv = f.read().split(b"\0")
    except OSError:
        return False
    argv = [a.decode("utf-8", "replace") for a in argv if a]
    if len(argv) < 2 or "python" not in os.path.basename(argv[0]):
        return False
    return os.path.abspath(argv[1]) == SELF


pid = os.getpid()
try:
    pids = subprocess.check_output(
        ["pgrep", "-f", os.path.basename(SELF)], text=True).strip().split()
    other = [p for p in pids if int(p) != pid and _is_this_popup(p)]
    if other:
        # Повторный вызов закрывает открытый попап — это переключатель.
        for p in other:
            subprocess.run(["kill", p])
        sys.exit(0)
except Exception:
    pass

gi.require_version("Gtk", "3.0")
# Gdk явно: иначе gi может успеть подтянуть Gdk 4.0 от gtk4-layer-shell.
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

EXTRA_CSS = """
/* Поиск и поле пароля — одного компактного размера. */
entry.search, entry.compact { min-height: 20px; padding: 0 6px; font-size: 11px; }
spinner { color: %(primary)s; }
label.dim { color: %(on_surface_variant)s; font-weight: normal; font-size: 11px; }
label.msg-err { color: %(error)s; font-weight: normal; font-size: 11px; }
.detail { padding: 2px 4px 6px 4px; }
button.small { padding: 2px 10px; font-size: 11px; margin: 0; min-height: 0; }
"""


def nmcli(*args, timeout=45):
    """Вернуть (успех, текст). stderr важен: в нём текст ошибки от NM."""
    try:
        r = subprocess.run(["nmcli", *args], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "истекло время ожидания"
    except OSError as e:
        return False, str(e)


def saved_profiles():
    ok, out = nmcli("-t", "-f", "NAME,TYPE", "connection", "show", timeout=5)
    if not ok:
        return set()
    names = set()
    for line in out.splitlines():
        parts = line.rsplit(":", 1)
        if len(parts) == 2 and parts[1] == "802-11-wireless":
            names.add(parts[0])
    return names


def wifi_iface():
    ok, out = nmcli("-t", "-f", "DEVICE,TYPE", "device", timeout=5)
    for line in out.splitlines() if ok else ():
        dev, _, kind = line.rpartition(":")
        if kind == "wifi":
            return dev
    return None


def list_networks():
    """Сети, которые NetworkManager уже видит, — без пересканирования.

    Одно имя часто светится несколькими точками доступа (2.4 и 5 ГГц под
    одним SSID, репитеры). Берётся самая сильная, а отметка «подключено»
    ставится, если она стоит хоть на одной из них.
    """
    ok, out = nmcli("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                    "dev", "wifi", "list", "--rescan", "no", timeout=5)
    if not ok:
        return None
    nets = {}
    for line in out.splitlines():
        # SSID может содержать ':', и nmcli экранирует его как '\:'.
        parts = [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]
        if len(parts) < 4 or not parts[1]:
            continue
        in_use, ssid, sig, sec = parts[0] == "*", parts[1], parts[2], parts[3]
        try:
            sig = int(sig)
        except ValueError:
            sig = 0
        cur = nets.get(ssid)
        if cur is None or sig > cur["signal"]:
            nets[ssid] = {"ssid": ssid, "signal": sig,
                          "secured": bool(sec) and sec != "--",
                          "in_use": in_use or bool(cur and cur["in_use"])}
        elif in_use:
            cur["in_use"] = True
    return sorted(nets.values(),
                  key=lambda n: (not n["in_use"], -n["signal"], n["ssid"].lower()))


def signal_icon(sig):
    return "󰤨" if sig >= 75 else "󰤥" if sig >= 50 else "󰤢" if sig >= 25 else "󰤟"


class WifiPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Wi-Fi")
        self.busy = False          # идёт действие с сетью
        self.scanning = False      # идёт скан
        self.polling = False       # в полёте запрос списка
        self.rows = {}             # ssid -> виджеты и данные строки
        self.known = set()
        self.query = ""
        self.expanded = None       # ssid раскрытой строки

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        # В попапе печатают — поиск и пароль, — поэтому клавиатура своя.
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
        # Прямо под баром, серединой под точкой щелчка — см. popup_theme.
        popup_theme.place_under_cursor(self.align)

        self.popup_event = Gtk.EventBox()
        self.popup_event.connect("button-press-event", lambda w, e: True)
        self.align.add(self.popup_event)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.get_style_context().add_class("popup-box")
        # Только ширина. Высота — по содержимому (см. MAX_LIST_H).
        vbox.set_size_request(300, -1)
        self.popup_event.add(vbox)

        # ── шапка ──
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.pack_start(Gtk.Label(label="󰤨  Wi-Fi", xalign=0), True, True, 0)
        # Кнопка обновления и крутилка делят одно место: пока идёт скан, на
        # месте кнопки вращается индикатор.
        self.scan_stack = Gtk.Stack()
        self.scan_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.scan_stack.set_transition_duration(150)
        rescan = Gtk.Button(label="󰑐")
        rescan.get_style_context().add_class("item")
        rescan.get_style_context().add_class("icon")
        rescan.set_tooltip_text("Искать сети заново")
        rescan.connect("clicked", self.start_scan)
        self.spinner = Gtk.Spinner()
        self.scan_stack.add_named(rescan, "idle")
        self.scan_stack.add_named(self.spinner, "busy")
        header.pack_start(self.scan_stack, False, False, 0)
        self.wifi_switch = Gtk.Switch()
        try:
            on = "enabled" in subprocess.check_output(["nmcli", "radio", "wifi"], text=True)
        except Exception:
            on = False
        self.wifi_switch.set_active(on)
        self.wifi_switch.connect("notify::active", self.on_toggle)
        header.pack_start(self.wifi_switch, False, False, 4)
        vbox.pack_start(header, False, False, 0)

        # ── поиск ──
        self.search = Gtk.SearchEntry()
        self.search.get_style_context().add_class("pw")
        self.search.get_style_context().add_class("search")
        self.search.set_placeholder_text("Поиск")
        self.search.connect("search-changed", self.on_search)
        # Enter в поиске раскрывает первую подходящую сеть — не подключает.
        self.search.connect("activate", self.on_search_activate)
        vbox.pack_start(self.search, False, False, 0)

        # ── список ──
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(MAX_LIST_H)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroll.add(self.list_box)
        vbox.pack_start(scroll, True, True, 0)
        self.empty = Gtk.Label(label="")
        self.empty.get_style_context().add_class("dim")
        self.empty.set_no_show_all(True)
        vbox.pack_start(self.empty, False, False, 6)

        self.connect("key-press-event", self.on_key)

        self.poll()
        GLib.timeout_add(POLL_MS, self.poll)
        GLib.idle_add(self.start_scan)
        GLib.idle_add(self.search.grab_focus)

    # ── ввод ──────────────────────────────────────────────────────────────
    def on_key(self, _w, event):
        """Escape сворачивает раскрытую сеть, а если свёрнуто — закрывает."""
        if event.keyval == Gdk.KEY_Escape:
            if self.expanded:
                self.collapse()
                self.search.grab_focus()
                return True
            sys.exit(0)
        return False

    def on_search(self, entry):
        self.query = entry.get_text().strip().lower()
        self.apply_filter()

    def on_search_activate(self, _entry):
        rows = self.visible_rows()
        if rows and not self.expanded:
            self.toggle_row(rows[0]["net"]["ssid"])

    # ── скан и опрос ──────────────────────────────────────────────────────
    def start_scan(self, *_a):
        if self.scanning or not self.wifi_switch.get_active():
            return False
        self.scanning = True
        # Stack не переключается на невидимый элемент — крутилка делает себя
        # видимой сама, не полагаясь на порядок показа окна.
        self.spinner.show()
        self.scan_stack.set_visible_child_name("busy")
        self.spinner.start()

        def work():
            nmcli("-t", "-f", "SSID", "device", "wifi", "list",
                  "--rescan", "yes", timeout=20)
            GLib.idle_add(self.scan_done)
        threading.Thread(target=work, daemon=True).start()
        self.apply_filter()
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
        if not self.wifi_switch.get_active():
            self.show_off()
            return True
        self.polling = True

        def work():
            known = saved_profiles()
            nets = list_networks()
            GLib.idle_add(self.apply, nets, known)
        threading.Thread(target=work, daemon=True).start()
        return True

    # ── строки ────────────────────────────────────────────────────────────
    def make_row(self, net):
        ssid = net["ssid"]
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
        btn.connect("clicked", lambda _b, s=ssid: self.toggle_row(s))

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
               "drev": drev, "detail": detail, "net": net, "gone": False,
               "key": None, "msg": None, "btns": None}
        self.update_row(row, net)
        return row

    def update_row(self, row, net):
        row["net"] = net
        known = net["ssid"] in self.known
        pairs = ((row["icon"], signal_icon(net["signal"])),
                 (row["name"], net["ssid"]),
                 # Замок — «нужен пароль». У открытых и сохранённых сетей его
                 # нет: они подключаются без вопросов.
                 (row["mark"], "󰌾" if net["secured"] and not known else ""))
        for lbl, text in pairs:
            if lbl.get_text() != text:
                lbl.set_text(text)
        ctx = row["btn"].get_style_context()
        want, drop = ("item-active", "item") if net["in_use"] else ("item", "item-active")
        if not ctx.has_class(want):
            ctx.remove_class(drop)
            ctx.add_class(want)
        # Состояние сети поменялось, пока панель раскрыта (подключились,
        # забыли) — перерисовать кнопки под новое состояние.
        if (self.expanded == net["ssid"] and not self.busy
                and row["key"] != (net["in_use"], known, net["secured"])):
            self.fill_detail(row)

    def toggle_row(self, ssid):
        if self.busy:
            return
        if self.expanded == ssid:
            self.collapse()
            return
        self.collapse()
        row = self.rows.get(ssid)
        if not row:
            return
        self.expanded = ssid
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
        net = row["net"]
        known = net["ssid"] in self.known
        row["key"] = (net["in_use"], known, net["secured"])

        caption = ("Подключено" if net["in_use"] else
                   "Сохранена — подключится без пароля" if known else
                   "Нужен пароль" if net["secured"] else "Открытая сеть")
        cap = Gtk.Label(label=caption, xalign=0)
        cap.get_style_context().add_class("dim")
        detail.pack_start(cap, False, False, 0)

        entry = None
        if not net["in_use"] and net["secured"] and not known:
            entry = Gtk.Entry()
            entry.get_style_context().add_class("pw")
            entry.get_style_context().add_class("compact")
            entry.set_visibility(False)
            entry.set_placeholder_text("Пароль")
            entry.connect("activate", lambda _e: self.do_connect(row, entry))
            detail.pack_start(entry, False, False, 0)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if net["in_use"]:
            btns.pack_start(self.small_button(
                "Отключиться", "item", lambda _b: self.do_disconnect(row)), True, True, 0)
        else:
            btns.pack_start(self.small_button(
                "Подключиться", "go", lambda _b: self.do_connect(row, entry)), True, True, 0)
        if known:
            btns.pack_start(self.small_button(
                "Забыть", "item", lambda b: self.do_forget(row, b)), True, True, 0)
        detail.pack_start(btns, False, False, 0)

        msg = Gtk.Label(xalign=0)
        msg.set_line_wrap(True)
        msg.set_max_width_chars(25)   # 34 знака при 11 px; кегль 16 (сетка шрифта) — та же ширина
        msg.set_no_show_all(True)
        detail.pack_start(msg, False, False, 0)
        row["msg"], row["btns"] = msg, btns
        detail.show_all()
        if entry:
            GLib.idle_add(entry.grab_focus)

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
            # Показать причину, а не молча ничего не сделать.
            line = out.splitlines()[-1] if out else "не получилось"
            self.set_msg(row, line.replace("Error: ", ""), error=True)
        self.poll()
        return False

    def do_connect(self, row, entry):
        if self.busy:
            return
        ssid = row["net"]["ssid"]
        known = ssid in self.known
        pw = entry.get_text() if entry else ""
        if entry is not None and not pw:
            self.set_msg(row, "Введите пароль", error=True)
            return

        def work():
            if known:
                # Сохранённый профиль поднимается по имени: пароль лежит в нём.
                return nmcli("connection", "up", "id", ssid)
            if pw:
                return nmcli("device", "wifi", "connect", ssid, "password", pw)
            return nmcli("device", "wifi", "connect", ssid)

        def ok():
            self.set_msg(row, "Подключено")
            GLib.timeout_add(1200, lambda: sys.exit(0))
        self.run(row, "Подключение…", work, ok)

    def do_disconnect(self, row):
        if self.busy:
            return

        def work():
            dev = wifi_iface()
            if not dev:
                return False, "не найден Wi-Fi адаптер"
            return nmcli("device", "disconnect", dev)
        self.run(row, "Отключение…", work, lambda: self.set_msg(row, "Отключено"))

    def do_forget(self, row, btn):
        """Забыть = удалить сохранённый профиль вместе с паролем. Поэтому в
        два щелчка: первый только спрашивает, и через 3 с вопрос снимается."""
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
        ssid = row["net"]["ssid"]

        def ok():
            self.known.discard(ssid)
            self.set_msg(row, "Сеть забыта")
        self.run(row, "Удаляю сохранённую сеть…",
                 lambda: nmcli("connection", "delete", "id", ssid), ok)

    # ── список ────────────────────────────────────────────────────────────
    def apply(self, nets, known):
        self.polling = False
        if not self.wifi_switch.get_active():
            return False
        if nets is None:
            self.empty.set_text("nmcli не ответил — NetworkManager запущен?")
            self.empty.show()
            return False
        self.known = known
        order = []
        for net in nets:
            row = self.rows.get(net["ssid"])
            if row is None:
                row = self.make_row(net)
                self.rows[net["ssid"]] = row
            else:
                self.update_row(row, net)
            row["gone"] = False
            order.append(row)

        fresh = {n["ssid"] for n in nets}
        for ssid, row in list(self.rows.items()):
            if ssid not in fresh and not row["gone"]:
                row["gone"] = True
                row["rev"].set_reveal_child(False)
                GLib.timeout_add(ANIM_MS + 60, self.drop_row, ssid)

        # Пока сеть раскрыта, порядок не трогаем: строка не должна уезжать из-
        # под руки, пока в неё вводят пароль или целятся в кнопку.
        if self.expanded is None:
            children = self.list_box.get_children()
            for i, row in enumerate(order):
                if i >= len(children) or children[i] is not row["rev"]:
                    self.list_box.reorder_child(row["rev"], i)
                    children = self.list_box.get_children()
        self.apply_filter()
        return False

    def drop_row(self, ssid):
        row = self.rows.get(ssid)
        # Сеть могла вернуться, пока строка сворачивалась, — тогда оставляем.
        if row and row["gone"]:
            if self.expanded == ssid:
                self.expanded = None
            self.list_box.remove(row["rev"])
            del self.rows[ssid]
        return False

    def visible_rows(self):
        return [r for r in self.list_box_order() if r["rev"].get_reveal_child()]

    def list_box_order(self):
        by_widget = {id(r["rev"]): r for r in self.rows.values()}
        return [by_widget[id(c)] for c in self.list_box.get_children() if id(c) in by_widget]

    def apply_filter(self):
        q = self.query
        shown = 0
        for row in self.rows.values():
            vis = not row["gone"] and (not q or q in row["net"]["ssid"].lower())
            if not vis and self.expanded == row["net"]["ssid"]:
                self.collapse()
            if row["rev"].get_reveal_child() != vis:
                row["rev"].set_reveal_child(vis)
            shown += vis
        if shown:
            self.empty.hide()
        else:
            self.empty.set_text("Ничего не найдено" if q else
                                "Ищу сети…" if self.scanning else "Сети не найдены")
            self.empty.show()

    def show_off(self):
        self.collapse()
        for row in self.rows.values():
            row["rev"].set_reveal_child(False)
        self.empty.set_text("Wi-Fi выключен")
        self.empty.show()

    def on_toggle(self, sw, _g):
        subprocess.run(["nmcli", "radio", "wifi", "on" if sw.get_active() else "off"])
        if sw.get_active():
            GLib.timeout_add(400, self.poll)
            # Сразу после включения NM ещё не готов искать — даём ему секунду.
            GLib.timeout_add(1500, self.start_scan)
        else:
            self.show_off()


if __name__ == "__main__":
    win = WifiPopup()
    win.show_all()
    Gtk.main()
