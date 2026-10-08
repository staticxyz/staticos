"""Плашка анализа Bluetooth — ЛКМ по значку Bluetooth в баре (08.10.2026).

Пара к плашкам «Сеть» и Wi-Fi (lan_popup.py): тот же вид — сверху крупный
вывод одной фразой, ниже главное, остальное под «Подробнее ▾». Пользователь выбрал:
«заряд наушников, качество звука (кодек)».

Что видно:
  * заряд подключённых наушников (BlueZ Battery1, `bluetoothctl info`);
  * кодек и его качество словами (свойство api.bluez5.codec у потока PipeWire);
  * режим: «Музыка» (A2DP) или «Гарнитура» (HFP — звук как по телефону,
    зато работает микрофон). В режиме гарнитуры — кнопка «Вернуть качество».
Сила сигнала (RSSI) без root не читается (btmgmt conn-info: Permission Denied) —
её нет. Список устройств и подключение — ПКМ (bluetooth_popup.py), вкл/выкл — СКМ.

Опрос — раз в 2 с, в потоке; живёт, только пока плашка открыта.
"""
import json
import os
import re
import subprocess
import sys
import threading

import gi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

popup_theme.single_instance(__file__)

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

WIDTH = 304          # 08.10.2026: компактнее (было 344)
POLL_MS = 2000
DETAILS_FILE = os.path.expanduser("~/.config/hypr/state/bt-popup-details")
OK_COLOR = "#9ece6a"
WARN_COLOR = "#e0af68"

# Кодек → (название, качество словом, класс цвета, подсказка).
# Битрейты — типичные значения кодеков, не замер.
CODECS = {
    "sbc": ("SBC", "обычное", None, "Базовый кодек, ~200–330 кбит/с. Слышно на тихих местах и тарелках."),
    "sbc_xq": ("SBC XQ", "хорошее", "ok", "SBC с повышенным битрейтом, ~450–550 кбит/с."),
    "aac": ("AAC", "хорошее", "ok", "Родной кодек AirPods, ~256 кбит/с. На слух близко к оригиналу."),
    "aptx": ("aptX", "хорошее", "ok", "~350 кбит/с."),
    "aptx_hd": ("aptX HD", "отличное", "ok", "~576 кбит/с, 24 бит."),
    "aptx_ll": ("aptX LL", "хорошее", "ok", "Низкая задержка."),
    "ldac": ("LDAC", "отличное", "ok", "До 990 кбит/с."),
    "lc3": ("LC3", "хорошее", "ok", "Кодек LE Audio."),
    "opus_05": ("Opus", "хорошее", "ok", ""),
    "msbc": ("mSBC", "как по телефону", "warn", "Режим гарнитуры: 16 кГц, один канал. Речь разборчиво, музыка — плоско."),
    "cvsd": ("CVSD", "плохое", "bad", "Режим гарнитуры: 8 кГц, один канал — как старый телефон."),
    "lc3_swb": ("LC3-SWB", "как по телефону", "warn", "Режим гарнитуры: 32 кГц, один канал."),
}

EXTRA_CSS = """
.popup-box { font-family: 'PxPlus HP 100LX 6x8 Jarvis', 'JetBrainsMono NF', sans-serif;
             font-size: 12px; padding: 8px 10px 8px 10px; }
label { font-weight: normal; font-size: 12px; }
label.title { font-size: 16px; }
label.big { font-size: 16px; }
label.verdict { font-size: 16px; }
label.dim { color: %(on_surface_variant)s; }
label.ok { color: %(ok)s; }
label.warn { color: %(warn)s; }
label.bad { color: %(error)s; }
separator { margin: 3px 0; }
button.go { font-size: 12px; font-weight: normal; padding: 6px 12px; }
button.small { font-size: 12px; font-weight: normal; padding: 1px 8px; min-height: 0; }
button.go:disabled { background-color: %(surface_high)s; color: %(on_surface_variant)s; }
button.more { font-size: 12px; font-weight: normal; padding: 2px 8px; min-height: 0;
              background: none; border: none; box-shadow: none;
              color: %(on_surface_variant)s; }
button.more:hover { color: %(primary)s; }
progressbar trough { min-height: 6px; border: none; border-radius: 3px;
                     background-color: %(surface_container)s; }
progressbar progress { min-height: 6px; border: none; border-radius: 3px;
                       background-color: %(primary)s; }
progressbar.warn progress { background-color: %(warn)s; }
progressbar.bad progress { background-color: %(error)s; }
"""


def run(cmd, timeout=4):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def rfkill_blocked():
    base = "/sys/class/rfkill"
    try:
        for n in os.listdir(base):
            with open(os.path.join(base, n, "type")) as f:
                if f.read().strip() != "bluetooth":
                    continue
            with open(os.path.join(base, n, "soft")) as f:
                soft = f.read().strip() == "1"
            with open(os.path.join(base, n, "hard")) as f:
                hard = f.read().strip() == "1"
            return soft or hard
    except OSError:
        pass
    return False


def bt_info(mac):
    out = run(["bluetoothctl", "info", mac])
    d = {"mac": mac}
    for line in out.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if k == "Alias":
            d["name"] = v
        elif k == "Connected":
            d["connected"] = v == "yes"
        elif k == "Icon":
            d["icon"] = v
        elif k == "Battery Percentage":
            m = re.search(r"\((\d+)\)", v)
            if m:
                d["battery"] = int(m.group(1))
    return d


def pw_audio():
    """{MAC: {...}} — карточки и потоки bluez из PipeWire (pactl JSON)."""
    res = {}
    try:
        cards = json.loads(run(["pactl", "-f", "json", "list", "cards"]) or "[]")
        sinks = json.loads(run(["pactl", "-f", "json", "list", "sinks"]) or "[]")
        sources = json.loads(run(["pactl", "-f", "json", "list", "sources"]) or "[]")
    except ValueError:
        return res
    for c in cards:
        pr = c.get("properties", {})
        if pr.get("device.api") != "bluez5":
            continue
        mac = pr.get("api.bluez5.address", "").upper()
        profs = [(k, v.get("description", k), v.get("available", True), v.get("priority", 0))
                 for k, v in (c.get("profiles") or {}).items()]
        res[mac] = {"card": c.get("name"), "profile": c.get("active_profile", ""),
                    "profiles": profs}
    for kind, lst in (("sink", sinks), ("source", sources)):
        for s in lst:
            pr = s.get("properties", {})
            if pr.get("device.api") != "bluez5" or "monitor" in s.get("name", ""):
                continue
            mac = pr.get("api.bluez5.address", "").upper()
            d = res.setdefault(mac, {})
            info = {"codec": pr.get("api.bluez5.codec", ""),
                    "spec": s.get("sample_specification", ""),
                    "state": s.get("state", ""),
                    "mute": s.get("mute", False)}
            vol = s.get("volume") or {}
            vals = [v.get("value_percent", "") for v in vol.values()]
            if vals:
                info["volume"] = vals[0]
            d[kind] = info
    return res


def collect():
    blocked = rfkill_blocked()
    show = run(["bluetoothctl", "show"]) if not blocked else ""
    powered = "Powered: yes" in show
    m = re.search(r"Alias: (.+)", show)
    data = {"blocked": blocked, "powered": powered and not blocked,
            "adapter": m.group(1).strip() if m else "", "devices": [], "paired": []}
    if not data["powered"]:
        return data
    pw = pw_audio()
    for line in run(["bluetoothctl", "devices", "Paired"]).splitlines():
        p = line.split(" ", 2)
        if len(p) < 3 or p[0] != "Device":
            continue
        d = bt_info(p[1])
        d.setdefault("name", p[2])
        if d.get("connected"):
            d.update(pw.get(p[1].upper(), {}))
            data["devices"].append(d)
        else:
            data["paired"].append(d)
    return data


def battery_cls(p):
    return "bad" if p <= 15 else "warn" if p <= 30 else "ok"


def codec_of(d):
    """Ключ кодека: свойство потока, иначе — по имени профиля."""
    codec = (d.get("sink") or {}).get("codec") or (d.get("source") or {}).get("codec")
    if codec:
        return codec.lower()
    prof = d.get("profile", "")
    m = re.match(r"(?:a2dp-sink|headset-head-unit)-(.+)", prof)
    if m:
        return m.group(1).lower()
    return "cvsd" if prof.startswith("headset") else ""


def is_headset(d):
    p = d.get("profile", "")
    return p.startswith("headset") or p.startswith("handsfree") or codec_of(d) in ("msbc", "cvsd", "lc3_swb")


def best_a2dp(d):
    """Лучший доступный профиль музыки — для кнопки «Вернуть качество»."""
    cands = [p for p in d.get("profiles", []) if p[0].startswith("a2dp") and p[2]]
    if not cands:
        return None
    plain = [p for p in cands if p[0] == "a2dp-sink"]
    return (plain or sorted(cands, key=lambda p: -p[3]))[0][0]


class BtPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Bluetooth")
        self.pal = popup_theme.palette()
        self.data = None
        self.busy = False
        self.cards = {}

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        provider = Gtk.CssProvider()
        provider.load_from_data(popup_theme.css(EXTRA_CSS, ok=OK_COLOR, warn=WARN_COLOR))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        bg = Gtk.EventBox()
        bg.connect("button-press-event", lambda w, e: sys.exit(0))
        self.add(bg)
        self.align = Gtk.Box()
        bg.add(self.align)
        popup_theme.place_under_cursor(self.align)
        ev = Gtk.EventBox()
        ev.connect("button-press-event", lambda w, e: True)
        self.align.add(ev)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("popup-box")
        box.set_size_request(WIDTH, -1)
        ev.add(box)

        # Шапка: название и тумблер вкл/выкл, как в списке устройств (Пользователь,
        # 08.10.2026: «а где мой переключатель?»). Имя адаптера — в подсказке.
        head = Gtk.Box(spacing=8)
        self.title_lbl = self.label("󰂯  Bluetooth", "title")
        head.pack_start(self.title_lbl, False, False, 0)
        self.switch = Gtk.Switch()
        self.switch.set_valign(Gtk.Align.CENTER)
        self.switch.set_tooltip_text("Включить или выключить Bluetooth (то же — средняя кнопка по значку)")
        self.switch_handler = self.switch.connect("notify::active", self.on_toggle)
        self.toggling = False
        head.pack_end(self.switch, False, False, 0)
        box.pack_start(head, False, False, 0)

        self.verdict = self.label("Проверяю…", "verdict", xalign=0.5)
        self.verdict.set_line_wrap(True)
        self.verdict.set_max_width_chars(28)
        self.verdict.set_justify(Gtk.Justification.CENTER)
        box.pack_start(self.verdict, False, False, 2)

        # Сюда перерисовывается содержимое при каждой смене состояния.
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(self.content, False, False, 0)

        self.msg = self.label("", "dim", xalign=0.5)
        self.msg.set_line_wrap(True)
        self.msg.set_max_width_chars(40)
        self.msg.set_no_show_all(True)
        box.pack_start(self.msg, False, False, 0)

        try:
            with open(DETAILS_FILE) as f:
                self.details_on = f.read().strip() == "on"
        except OSError:
            self.details_on = False
        self.sig = None

        self.connect("key-press-event", self.on_key)
        self.poll()
        GLib.timeout_add(POLL_MS, self.poll)

    # ── helpers ──
    def label(self, text, cls=None, xalign=0):
        lb = Gtk.Label(label=text, xalign=xalign)
        if cls:
            for c in cls.split():
                lb.get_style_context().add_class(c)
        return lb

    @staticmethod
    def set_cls(w, cls):
        ctx = w.get_style_context()
        for c in ("ok", "warn", "bad", "dim"):
            if c != cls and ctx.has_class(c):
                ctx.remove_class(c)
        if cls and not ctx.has_class(cls):
            ctx.add_class(cls)

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            sys.exit(0)
        return False

    def say(self, text, cls="dim"):
        self.msg.set_text(text)
        self.set_cls(self.msg, cls)
        self.msg.set_visible(bool(text))

    def hint(self, text):
        """Серая подсказка по центру; переносится, а не раздвигает плашку."""
        lb = self.label(text, "dim", xalign=0.5)
        # Pango занижает ширину пиксельного шрифта и переносил даже 30 знаков.
        lb.set_line_wrap(len(text) > 32)
        lb.set_max_width_chars(40)
        lb.set_justify(Gtk.Justification.CENTER)
        return lb

    def button(self, text, cb, cls="go"):
        b = Gtk.Button(label=text)
        b.get_style_context().add_class(cls)
        b.connect("clicked", cb)
        return b

    def grid_rows(self, rows):
        g = Gtk.Grid(column_spacing=10, row_spacing=2)
        for i, (title, val, cls, tip) in enumerate(rows):
            t = self.label(title, "dim")
            v = self.label(val, cls)
            v.set_hexpand(True)
            v.set_ellipsize(Pango.EllipsizeMode.END)
            if tip:
                t.set_tooltip_text(tip)
                v.set_tooltip_text(tip)
            g.attach(t, 0, i, 1, 1)
            g.attach(v, 1, i, 1, 1)
        return g

    # ── опрос ──
    def poll(self):
        if not self.busy:
            self.busy = True

            def work():
                d = collect()
                GLib.idle_add(self.apply, d)
            threading.Thread(target=work, daemon=True).start()
        return True

    def apply(self, d):
        self.busy = False
        # Перерисовываем, только если что-то поменялось: иначе каждые 2 с
        # мигали бы подсказки и терялось наведение на кнопки.
        sig = json.dumps(d, sort_keys=True, default=str)
        if sig == self.sig:
            return False
        self.sig = sig
        self.data = d
        self.title_lbl.set_tooltip_text(("Адаптер: " + d["adapter"]) if d.get("adapter") else None)
        if not self.toggling:
            self.switch.handler_block(self.switch_handler)
            self.switch.set_active(d["powered"])
            self.switch.handler_unblock(self.switch_handler)
        for ch in self.content.get_children():
            self.content.remove(ch)
            ch.destroy()
        if d["blocked"] or not d["powered"]:
            self.show_off(d)
        elif not d["devices"]:
            self.show_none(d)
        else:
            self.show_devices(d)
        self.content.show_all()
        if hasattr(self, "details"):
            self.details.set_visible(self.details_on)
        return False

    # ── состояния ──
    def show_off(self, d):
        self.verdict.set_text("Выключен")
        self.set_cls(self.verdict, "dim")

    def show_none(self, d):
        self.verdict.set_text("Ничего не подключено")
        self.set_cls(self.verdict, None)
        audio = [p for p in d["paired"] if (p.get("icon") or "").startswith("audio")]
        if audio:
            for p in audio:
                row = Gtk.Box(spacing=8)
                row.pack_start(self.label(p.get("name", p["mac"])), True, True, 0)
                b = self.button("Подключить", lambda _b, m=p["mac"], n=p.get("name"): self.do_connect(m, n),
                                "small")
                row.pack_end(b, False, False, 0)
                self.content.pack_start(row, False, False, 0)
        self.content.pack_start(self.hint("Все устройства — ПКМ по значку"), False, False, 2)

    def show_devices(self, d):
        devs = d["devices"]
        # Вывод — по самому важному у первого аудиоустройства.
        main = next((x for x in devs if (x.get("icon") or "").startswith("audio")), devs[0])
        codec = codec_of(main)
        bat = main.get("battery")
        if is_headset(main):
            self.verdict.set_text("Режим гарнитуры — звук как по телефону")
            self.set_cls(self.verdict, "warn")
        elif bat is not None and bat <= 15:
            self.verdict.set_text("Наушники садятся — %d %%" % bat)
            self.set_cls(self.verdict, "bad")
        elif codec and CODECS.get(codec, (0, 0, None))[2] == "ok":
            self.verdict.set_text("Звук %s — %s" % (CODECS[codec][1], CODECS[codec][0]))
            self.set_cls(self.verdict, "ok")
        elif codec:
            self.verdict.set_text("Звук %s — %s" % (CODECS.get(codec, (codec.upper(), "обычное"))[1],
                                                    CODECS.get(codec, (codec.upper(),))[0]))
            self.set_cls(self.verdict, None)
        else:
            self.verdict.set_text("Подключено")
            self.set_cls(self.verdict, None)

        details = []
        for i, dev in enumerate(devs):
            if i:
                self.content.pack_start(Gtk.Separator(), False, False, 0)
            self.device_card(dev)
            details.append(dev)

        more = self.button("Скрыть подробности ▴" if self.details_on else "Подробнее ▾",
                           self.toggle_details, "more")
        more.set_halign(Gtk.Align.CENTER)
        self.more_btn = more
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for dev in details:
            self.details.pack_start(Gtk.Separator(), False, False, 0)
            self.details.pack_start(self.detail_grid(dev), False, False, 0)
        self.details.set_no_show_all(not self.details_on)
        self.content.pack_start(self.details, False, False, 0)
        self.content.pack_start(more, False, False, 0)

    def device_card(self, dev):
        top = Gtk.Box(spacing=8)
        name = self.label(dev.get("name", dev["mac"]), "big")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        top.pack_start(name, True, True, 0)
        bat = dev.get("battery")
        if bat is not None:
            top.pack_end(self.label("%d %%" % bat, "big " + battery_cls(bat), xalign=1), False, False, 0)
        self.content.pack_start(top, False, False, 2)
        if bat is not None:
            pb = Gtk.ProgressBar()
            pb.set_fraction(bat / 100)
            c = battery_cls(bat)
            if c != "ok":
                pb.get_style_context().add_class(c)
            self.content.pack_start(pb, False, False, 2)

        rows = []
        codec = codec_of(dev)
        if codec:
            nm, word, cls, tip = CODECS.get(codec, (codec.upper(), "", None, ""))
            rows.append(("Звук", "%s · %s" % (nm, word) if word else nm, cls, tip))
        if dev.get("profile") or dev.get("sink") or dev.get("source"):
            if is_headset(dev):
                rows.append(("Режим", "гарнитура + микрофон", "warn",
                             "Пока какая-то программа держит микрофон наушников (звонок, Discord), "
                             "Bluetooth переходит в режим гарнитуры: звук один канал и 8–16 кГц."))
            else:
                rows.append(("Режим", "музыка, без микрофона", None,
                             "A2DP: стерео в полном качестве. Микрофон наушников в этом режиме не работает."))
        if bat is None:
            rows.append(("Заряд", "не сообщает", "dim",
                         "BlueZ не получил уровень заряда. AirPods сообщают его, когда подключены как аудио."))
        if rows:
            self.content.pack_start(self.grid_rows(rows), False, False, 2)

        if is_headset(dev) and best_a2dp(dev) and dev.get("card"):
            b = self.button("Вернуть качество",
                            lambda _b, c=dev["card"], p=best_a2dp(dev): self.do_profile(c, p))
            b.set_tooltip_text("Переключить на музыку (A2DP). Микрофон наушников тогда отключится.")
            self.content.pack_start(b, False, False, 2)

    def detail_grid(self, dev):
        rows = [("Устройство", dev.get("name", ""), None, None),
                ("Адрес", dev["mac"], "dim", None)]
        sink = dev.get("sink") or {}
        if sink.get("spec"):
            rows.append(("Поток", sink["spec"], None, "Формат, каналы и частота потока PipeWire"))
        if sink.get("volume"):
            rows.append(("Громкость", sink["volume"] + (" (выкл.)" if sink.get("mute") else ""), None, None))
        src = dev.get("source") or {}
        if src.get("spec"):
            rows.append(("Микрофон", src["spec"], "warn", "Микрофон наушников открыт"))
        if dev.get("profile"):
            rows.append(("Профиль", dev["profile"], "dim", "Профиль карты PipeWire"))
        avail = [p for p in dev.get("profiles", []) if p[2] and p[0] != "off"]
        if avail:
            codecs = []
            for p in avail:
                c = re.sub(r"^(a2dp-sink|headset-head-unit)-?", "", p[0])
                c = CODECS.get(c, (c.upper(),))[0] if c else ""
                if c and c not in codecs:
                    codecs.append(c)
            if codecs:
                rows.append(("Умеет", ", ".join(codecs), None, "Кодеки, которые доступны с этими наушниками"))
        rows.append(("Сигнал", "нужен root", "dim",
                     "Сила сигнала (RSSI) подключённого устройства — только btmgmt от root."))
        return self.grid_rows(rows)

    def toggle_details(self, _b):
        self.details_on = not self.details_on
        self.more_btn.set_label("Скрыть подробности ▴" if self.details_on else "Подробнее ▾")
        self.details.set_no_show_all(not self.details_on)
        if self.details_on:
            self.details.show_all()
        else:
            self.details.hide()
        try:
            os.makedirs(os.path.dirname(DETAILS_FILE), exist_ok=True)
            with open(DETAILS_FILE, "w") as f:
                f.write("on" if self.details_on else "off")
        except OSError:
            pass

    # ── действия (в потоках: bluetoothctl думает секундами) ──
    def act(self, text, work):
        self.say(text)

        def th():
            ok, out = work()
            GLib.idle_add(self.after_act, ok, out)
        threading.Thread(target=th, daemon=True).start()

    def after_act(self, ok, out):
        self.toggling = False
        self.say("" if ok else (out or "Не вышло"), None if ok else "bad")
        self.sig = None
        self.poll()
        return False

    def on_toggle(self, sw, _g):
        want = sw.get_active()
        self.toggling = True

        def work():
            if want:
                # Сперва снять блокировку: на заблокированном адаптере power on
                # молча не срабатывает (как в bluetooth_popup.py).
                subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True)
                for _ in range(6):
                    if "succeeded" in run(["bluetoothctl", "power", "on"], timeout=6):
                        return True, ""
                    threading.Event().wait(0.4)
                return False, "Адаптер не включился"
            run(["bluetoothctl", "power", "off"], timeout=6)
            subprocess.run(["rfkill", "block", "bluetooth"], capture_output=True)
            return True, ""
        self.act("Включаю…" if want else "Выключаю…", work)

    def do_connect(self, mac, name):
        def work():
            out = run(["bluetoothctl", "connect", mac], timeout=20)
            ok = "Connection successful" in out
            return ok, "" if ok else "%s не подключились — откройте кейс рядом с ноутбуком" % (name or mac)
        self.act("Подключаю %s…" % (name or mac), work)

    def do_profile(self, card, prof):
        def work():
            r = subprocess.run(["pactl", "set-card-profile", card, prof], capture_output=True, text=True)
            return r.returncode == 0, r.stderr.strip()
        self.act("Переключаю на музыку…", work)


if __name__ == "__main__":
    win = BtPopup()
    win.show_all()
    Gtk.main()
