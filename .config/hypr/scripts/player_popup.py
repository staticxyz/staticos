#!/usr/bin/env python3
"""Попап плеера (щелчок по модулю плеера в баре).

Что было не так и что сделано (11.09.2026):

  * Значок ▶/⏸ ставился один раз при открытии и больше не менялся: кнопка
    ставила паузу, а значок оставался прежним. Теперь попап раз в POLL_MS
    спрашивает у плеера статус, позицию и трек и обновляет всё на месте;
    после нажатия значок меняется сразу, не дожидаясь опроса.
  * Полоса перемотки стояла на месте открытия. Теперь она идёт вместе с
    треком, под ней время «прошло / всего». Перемотка срабатывает только от
    движения самого ползунка (change-value), а не от обновления позиции,
    иначе опрос сам себя перематывал бы.
  * «Открыть источник» звал `hyprctl dispatch focuswindow …` — синтаксис
    старого конфига; с Lua-конфигом Hyprland такое не принимает, и кнопка не
    работала. К тому же окно искалось по имени плеера, а Яндекс Музыка, к
    примеру, называется в MPRIS «chromium». Теперь окно находится по процессу:
    PID владельца шины MPRIS через D-Bus, дальше вверх по родителям до
    процесса с окном, и фокус — hl.dsp.focus({ window = "pid:N" }).
  * Цвета из палитры обоев: название трека — акцентом (primary), а не
    tertiary — тот уходит в дополняющий тёплый оттенок; эмодзи 🚀 заменён
    одноцветным глифом. Кнопки — глифы Nerd Font, а не символы Unicode,
    которые рисовались запасным шрифтом.
  * Плеер выбирается тот же, что показывает бар: играющий, иначе на паузе;
    Blanket (шум фоном, не музыка) пропускается, как в mpris_status.py.
  * Попап — прямо под баром у точки щелчка (popup_theme.place_under_cursor).

Несколько плееров сразу (17.09.2026) — по карточке на каждый, играющий сверху.

Клавиши: пробел — пауза/воспроизведение первого плеера, любая другая — закрыть.
"""
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wm  # noqa: E402
import threading
import time
import urllib.request

import gi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mpris_common  # noqa: E402
import popup_theme  # noqa: E402

# Второй щелчок по модулю закрывает открытый попап — см. popup_theme.single_instance.
popup_theme.single_instance(__file__)

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

POLL_MS = 1000
COVER = 76          # обложка — квадрат со скруглёнными углами, как в «райсах» (30.09.2026):
                    # превью видео 16:9 обрезается по центру в квадрат, а не сжимается в полоску
COVER_RADIUS = 10
_card_seq = [0]     # номер карточки — для её собственного CSS (фон из обложки)
IGNORED = ("blanket",)
COVER_CACHE = os.path.expanduser("~/.cache/player-covers")
ICON_PREV, ICON_NEXT = "\U000f04ae", "\U000f04ad"
ICON_PLAY, ICON_PAUSE = "\U000f040a", "\U000f03e4"
ICON_OPEN = ""
ICON_LIKED, ICON_LIKE = "\U000f02d1", "\U000f02d5"
ICON_CLOSE = "\U000f0156"
LIKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "player_like.py")
SEP = "\x1f"
FMT = SEP.join(("{{title}}", "{{artist}}", "{{mpris:artUrl}}",
                "{{mpris:length}}", "{{status}}"))


def pc(*args, timeout=3):
    try:
        return subprocess.run(["playerctl", *args], capture_output=True,
                              text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def window_title(player):
    """Название вкладки из заголовка окна — когда MPRIS его не даёт."""
    for r in mpris_common.players():
        if r["instance"] == player:
            return r["title"]
    return ""


def metadata(player):
    parts = pc("-p", player, "metadata", "--format", FMT).split(SEP)
    if len(parts) < 5:
        # playerctl отвечает "No player could handle this command", пока плеер
        # ещё не наполнил метаданные — helium так делает первые секунды после
        # запуска видео, и попап показывал «Сейчас ничего не играет» при
        # играющем ролике. Берём то немногое, что известно с шины и из окна.
        for r in mpris_common.players(include_ignored=True):
            if r["instance"] == player:
                return {"title": r["title"] or "Без названия", "artist": r["artist"],
                        "art": "", "length": 0.0, "status": r["status"],
                        "position": 0.0}
        return None
    try:
        length = int(parts[3] or 0) / 1e6
    except ValueError:
        length = 0.0
    try:
        pos = float(pc("-p", player, "position") or 0)
    except ValueError:
        pos = 0.0
    artist = mpris_common.clean_artist(parts[1])
    if "blanket" in player.lower():
        artist = blanket_line()
    return {"title": mpris_common.clean_title(parts[0]) or window_title(player) or "Без названия",
            "artist": artist,
            "art": parts[2], "length": length, "status": parts[4],
            "position": pos}


def blanket_line():
    """«Blanket · 2 звука»: какие именно звуки включены, Blanket наружу не сообщает (настройки
    пишет только при выходе, потоки в PipeWire безымянные) — видно лишь, сколько его потоков
    играет: по потоку на звук."""
    try:
        objs = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=3).stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return "Blanket"
    n = 0
    for o in objs:
        info = o.get("info") or {}
        props = info.get("props") or {}
        if props.get("application.name") == "Blanket" and info.get("state") == "running" \
                and props.get("media.class", "Stream/Output/Audio") == "Stream/Output/Audio":
            n += 1
    if not n:
        return "Blanket"
    word = "звук" if n % 10 == 1 and n % 100 != 11 else ("звука" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "звуков")
    return "Blanket · %d %s" % (n, word)


def fmt_time(sec):
    sec = int(max(0, sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def window_pid_for(player):
    """PID процесса, у которого есть окно, для данного плеера MPRIS."""
    try:
        out = subprocess.run(
            ["busctl", "--user", "call", "org.freedesktop.DBus", "/",
             "org.freedesktop.DBus", "GetConnectionUnixProcessID", "s",
             "org.mpris.MediaPlayer2." + player],
            capture_output=True, text=True, timeout=3).stdout.split()
        pid = int(out[1])
        clients = {w["pid"] for w in wm.windows()}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None
    while pid > 1:
        if pid in clients:
            return pid
        try:
            with open("/proc/%d/stat" % pid) as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return None
    return None


def player_rows():
    """Все плееры для попапа, в порядке бара: играющий первым, потом свежее окно."""
    # Остановленные (крестик на карточке шлёт stop) в попап не попадают.
    # Blanket — тоже (07.10.2026, Просьба: «добавить в плеер, если запущу Blanket… только один»):
    # у него один плеер MPRIS на все звуки, так что карточка одна.
    rows = [r for r in mpris_common.players(include_ignored=True) if r["status"] != "Stopped"]
    order = {"Playing": 0, "Paused": 1}
    return sorted(rows, key=lambda r: (order.get(r["status"], 2), r["hist"]))


class PlayerCard(Gtk.Box):
    """Карточка одного плеера: обложка, название, перемотка, кнопки.

    17.09.2026 (Просьба: «включаю и музыку, и видос в браузере — может показать
    оба?»): попап раньше знал один плеер; теперь по карточке на каждый, у каждой
    своё состояние и свои кнопки.
    """

    def __init__(self, player, meta):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.player = player
        self.meta = meta
        self.art = None
        self.seek_hold = 0.0       # после перемотки не дёргать ползунок назад

        # ── трек ──
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        # Обложка рисуется сама: квадрат со скруглёнными углами (у Gtk.Image их нет).
        # Место резервируется сразу — картинка приезжает из сети потоком, и без
        # этого окно подпрыгивало в размере (замечено пользователем 21.09.2026).
        self.cover_pix = None
        self.cover = Gtk.DrawingArea()
        self.cover.set_size_request(COVER, COVER)
        self.cover.set_valign(Gtk.Align.CENTER)
        self.cover.connect("draw", self.draw_cover)
        # Фон карточки — размытая затемнённая обложка трека (как в «райсах»).
        _card_seq[0] += 1
        self.card_class = "card%d" % _card_seq[0]
        self.get_style_context().add_class("card")
        self.get_style_context().add_class(self.card_class)
        self.bg_provider = Gtk.CssProvider()
        self.get_style_context().add_provider(self.bg_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        top.pack_start(self.cover, False, False, 0)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_valign(Gtk.Align.CENTER)
        self.lbl_title = Gtk.Label(xalign=0)
        self.lbl_title.get_style_context().add_class("title")
        self.lbl_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_title.set_max_width_chars(16)
        self.lbl_artist = Gtk.Label(xalign=0)
        self.lbl_artist.get_style_context().add_class("artist")
        self.lbl_artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_artist.set_max_width_chars(16)
        # Ширина подписей фиксирована в знаках, а не по тексту: иначе короткое
        # название давало узкую карточку, а через секунду приходило настоящее
        # и окно уезжало вбок на пару десятков пикселей (21.09.2026).
        # 18, а не 24 (23.09.2026): с широким пиксельным шрифтом 24 знака
        # раздували карточку, справа от названия оставалась пустота.
        self.lbl_artist.set_width_chars(16)
        self.lbl_title.set_width_chars(16)
        self.actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_open = Gtk.Button(label=ICON_OPEN + " Источник")   # короче: плеер был слишком широким (29.09.2026)
        btn_open.get_style_context().add_class("open")
        btn_open.set_halign(Gtk.Align.START)
        btn_open.connect("clicked", self.on_open)
        self.actions.pack_start(btn_open, False, False, 0)
        # «Нравится» — только у плееров, где его умеет player_like.py (Яндекс
        # Музыка через порт отладки). Состояние спрашиваем в потоке: вызов
        # занимает десятки миллисекунд, и окно не должно подвисать.
        self.btn_like = Gtk.Button(label=ICON_LIKE)
        self.btn_like.get_style_context().add_class("like")
        # Кнопка ВСЕГДА занимает своё место, даже когда плеер «Нравится» не
        # умеет: ответ приходит через секунду, и если её тогда показать или
        # спрятать, карточка меняет ширину и окно дёргается вбок (замечено
        # Пользователем 21.09.2026). Невидимой её делает прозрачность, а не hide().
        self.btn_like.set_opacity(0.0)
        self.btn_like.set_sensitive(False)
        self.btn_like.set_valign(Gtk.Align.CENTER)
        btn_open.set_valign(Gtk.Align.CENTER)
        self.btn_like.connect("clicked", self.on_like)
        self.actions.pack_start(self.btn_like, False, False, 0)
        self.like_busy = False
        info.pack_start(self.lbl_title, False, False, 0)
        info.pack_start(self.lbl_artist, False, False, 0)
        info.pack_start(self.actions, False, False, 4)
        top.pack_start(info, True, True, 0)
        # Крестик — остановить плеер и убрать карточку (17.09.2026, пользователь:
        # «маленькие крестики, чтобы закрывать если что»).
        btn_close = Gtk.Button(label=ICON_CLOSE)
        btn_close.get_style_context().add_class("close")
        btn_close.set_valign(Gtk.Align.START)
        btn_close.set_tooltip_text("Остановить и убрать")
        btn_close.connect("clicked", self.on_close)
        top.pack_start(btn_close, False, False, 0)
        self.pack_start(top, False, False, 0)

        # ── перемотка и время ──
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.connect("change-value", self.on_seek)
        # Время — по краям полосы в одну строку, а не отдельной строкой под ней:
        # карточка ниже на строку (30.09.2026, Просьба: «ужать сверху и снизу»).
        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.lbl_pos = Gtk.Label(xalign=0)
        self.lbl_len = Gtk.Label(xalign=1)
        for lbl in (self.lbl_pos, self.lbl_len):
            lbl.get_style_context().add_class("time")
        times.pack_start(self.lbl_pos, False, False, 0)
        times.pack_start(self.scale, True, True, 0)
        times.pack_start(self.lbl_len, False, False, 0)
        self.pack_start(times, False, False, 0)

        # ── управление ──
        ctrls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        ctrls.set_halign(Gtk.Align.CENTER)
        prev = Gtk.Button(label=ICON_PREV)
        self.btn_play = Gtk.Button()
        nxt = Gtk.Button(label=ICON_NEXT)
        for b in (prev, self.btn_play, nxt):
            b.get_style_context().add_class("ctrl")
        self.btn_play.get_style_context().add_class("play")
        prev.connect("clicked", lambda b: self.step("previous"))
        nxt.connect("clicked", lambda b: self.step("next"))
        self.btn_play.connect("clicked", self.on_play)
        for b in (prev, self.btn_play, nxt):
            ctrls.pack_start(b, False, False, 0)
        self.pack_start(ctrls, False, False, 0)

        self.show_meta(meta)
        self.poll_like()

    # ── обновление ────────────────────────────────────────────────────────
    def show_meta(self, m):
        if self.lbl_title.get_text() != m["title"]:
            self.lbl_title.set_text(m["title"])
        artist = m["artist"] or "Неизвестный исполнитель"
        if self.lbl_artist.get_text() != artist:
            self.lbl_artist.set_text(artist)
        self.set_play_icon(m["status"] == "Playing")
        length = m["length"] if m["length"] > 0 else max(m["position"], 1)
        adj = self.scale.get_adjustment()
        if abs(adj.get_upper() - length) > 0.5:
            adj.set_upper(length)
        if time.time() > self.seek_hold:
            self.scale.set_value(min(m["position"], length))
        self.lbl_pos.set_text(fmt_time(m["position"]))
        self.lbl_len.set_text(fmt_time(m["length"]) if m["length"] > 0 else "")
        if m["art"] != self.art:
            self.art = m["art"]
            threading.Thread(target=self.load_cover, args=(m["art"],), daemon=True).start()

    def refresh(self):
        """False — плеер пропал, карточку пора убрать."""
        m = metadata(self.player)
        if m is None:
            return False
        # Лайк спрашиваем при смене трека, а не каждую секунду: у YouTube
        # каждый запрос идёт через файл в live-theme.js.
        changed = self.meta is None or (m["title"], m["artist"]) != (self.meta["title"], self.meta["artist"])
        self.meta = m
        self.show_meta(m)
        if changed:
            self.poll_like()
        return True

    def poll_like(self, action="state"):
        if self.like_busy:
            return
        self.like_busy = True

        def work():
            try:
                out = subprocess.run(["python3", LIKE, action, self.player], capture_output=True,
                                     text=True, timeout=6).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                out = "unsupported"
            GLib.idle_add(self.show_like, out)
        threading.Thread(target=work, daemon=True).start()

    def show_like(self, state):
        self.like_busy = False
        if state == "keep":                  # сервер плеера занят — ничего не менять
            return False
        if state not in ("liked", "not"):
            self.btn_like.set_opacity(0.0)
            self.btn_like.set_sensitive(False)
            return False
        self.btn_like.set_label(ICON_LIKED if state == "liked" else ICON_LIKE)
        ctx = self.btn_like.get_style_context()
        (ctx.add_class if state == "liked" else ctx.remove_class)("liked")
        self.btn_like.set_tooltip_text("Убрать из «Мне нравится»" if state == "liked" else "Нравится")
        self.btn_like.set_opacity(1.0)
        self.btn_like.set_sensitive(True)
        return False

    def on_like(self, _b):
        # Нажатие важнее опроса: даже если опрос ещё идёт, лайк отправляется.
        self.like_busy = False
        self.poll_like("toggle")

    def set_play_icon(self, playing):
        want = ICON_PAUSE if playing else ICON_PLAY
        if self.btn_play.get_label() != want:
            self.btn_play.set_label(want)

    def load_cover(self, url):
        """Обложка: локальный файл или загрузка в кэш — в потоке, не в окне.
        Заодно — размытая затемнённая копия для фона карточки."""
        path = None
        blur = None
        try:
            if url.startswith("file://"):
                path = url[len("file://"):]
            elif url.startswith("http"):
                os.makedirs(COVER_CACHE, exist_ok=True)
                path = os.path.join(COVER_CACHE, hashlib.sha1(url.encode()).hexdigest())
                if not os.path.exists(path):
                    urllib.request.urlretrieve(url, path)
            pix = None
            if path:
                full = GdkPixbuf.Pixbuf.new_from_file(path)
                w, h = full.get_width(), full.get_height()
                side = min(w, h)
                pix = full.new_subpixbuf((w - side) // 2, (h - side) // 2, side, side) \
                          .scale_simple(COVER, COVER, GdkPixbuf.InterpType.HYPER)
                os.makedirs(COVER_CACHE, exist_ok=True)
                blur = os.path.join(COVER_CACHE, hashlib.sha1((path + ":blur2").encode()).hexdigest() + ".png")
                if not os.path.exists(blur):
                    from PIL import Image, ImageEnhance, ImageFilter
                    im = Image.open(path).convert("RGB")
                    im.thumbnail((96, 96))
                    im = im.filter(ImageFilter.GaussianBlur(6))
                    im = ImageEnhance.Brightness(im).enhance(0.75)
                    im = ImageEnhance.Color(im).enhance(1.25)
                    im.save(blur)
        except Exception:
            pix = None
            blur = None
        GLib.idle_add(self.set_cover, pix, blur)

    def set_cover(self, pix, blur=None):
        self.cover_pix = pix
        self.cover.queue_draw()
        # Фон карточки: размытая обложка под тёмной вуалью — текст читается на любой.
        if blur:
            css = ("." + self.card_class + " { background-image: linear-gradient("
                   "rgba(10,12,20,0.30), rgba(10,12,20,0.68)), url('" + blur + "'); "
                   "background-size: cover; background-position: center; }")
        else:
            css = "." + self.card_class + " { }"
        try:
            self.bg_provider.load_from_data(css.encode())
        except Exception:
            pass
        return False

    def draw_cover(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        r = COVER_RADIUS
        cr.new_sub_path()
        cr.arc(w - r, r, r, -1.5708, 0)
        cr.arc(w - r, h - r, r, 0, 1.5708)
        cr.arc(r, h - r, r, 1.5708, 3.1416)
        cr.arc(r, r, r, 3.1416, 4.7124)
        cr.close_path()
        if self.cover_pix is not None:
            Gdk.cairo_set_source_pixbuf(cr, self.cover_pix, (w - self.cover_pix.get_width()) / 2,
                                        (h - self.cover_pix.get_height()) / 2)
        else:
            c = Gdk.RGBA(); c.parse(popup_theme.palette()["surface_container"])
            cr.set_source_rgba(c.red, c.green, c.blue, 1)
        cr.fill()
        return True

    # ── действия ──────────────────────────────────────────────────────────
    def on_play(self, _b=None):
        pc("-p", self.player, "play-pause")
        # Значок — сразу, не дожидаясь следующего опроса.
        self.set_play_icon(self.btn_play.get_label() == ICON_PLAY)
        GLib.timeout_add(350, lambda: (self.refresh(), False)[1])

    def step(self, what):
        pc("-p", self.player, what)
        GLib.timeout_add(450, lambda: (self.refresh(), False)[1])

    def on_seek(self, _scale, _scroll, value):
        self.seek_hold = time.time() + 1.5
        pc("-p", self.player, "position", "%.1f" % max(0.0, value))
        self.lbl_pos.set_text(fmt_time(value))
        return False

    def on_close(self, _b):
        # Метка для player.exe (06.10.2026): Яндекс на «стоп» может ответить паузой —
        # виджет всё равно уберёт этот трек сразу, пока он не заиграет снова.
        try:
            import os as _os
            title = subprocess.run(["playerctl", "-p", self.player, "metadata", "title"],
                                   capture_output=True, text=True, timeout=2).stdout.strip()
            path = _os.path.join(_os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-player-dismissed")
            with open(path, "a") as f:
                f.write("%s\t%s\n" % (self.player, title))
        except Exception:
            pass
        pc("-p", self.player, "stop")          # после метки: событие плеера придёт уже к ней
        # Карточку убираем сразу, не дожидаясь, пока плеер доложит «Stopped».
        popup = self.get_toplevel()
        if hasattr(popup, "dismiss"):
            popup.dismiss(self)

    def on_open(self, _b):
        pid = window_pid_for(self.player)
        target = None
        if pid:
            for w in wm.windows():
                if w["pid"] == pid:
                    target = w
                    break
        if target is None:
            # По pid не нашлось (окно за XWayland числится за xwayland-satellite,
            # как было у Spotify 23.09.2026) — ищем по имени приложения или
            # заголовку: «spotify» в «Spotify», «chromium.instance…» → chromium.
            key = self.player.split(".")[0].lower()
            for w in wm.windows():
                hay = "%s %s" % (w.get("app") or "", w.get("title") or "")
                if key and key in hay.lower():
                    target = w
                    break
        if target is not None:
            wm.focus(target)
        sys.exit(0)


class PlayerPopup(Gtk.Window):
    def bar_pill_width(self):
        """Ширина пилюли плеера в баре в пикселях, или None."""
        import json
        try:
            out = subprocess.run(
                ["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)), "mpris_status.py")],
                capture_output=True, text=True, timeout=3).stdout.strip().splitlines()[-1]
            text = json.loads(out).get("text", "")
        except Exception:
            return None
        if not text:
            return None
        layout = self.create_pango_layout("")
        # Шрифт и кегль пилюли — как у бара: семейство подменяет то же правило
        # fontconfig, что и у waybar, так что ширина совпадёт.
        layout.set_font_description(Pango.FontDescription("JetBrainsMono Nerd Font 9.75"))
        # Текст приходит с разметкой (<i>…</i>) — как у waybar; раньше она мерилась
        # как буквы, и ширина выходила 228 px вместо 155 (30.09.2026).
        try:
            layout.set_markup(text, -1)
        except Exception:
            layout.set_text(text, -1)
        w, _ = layout.get_pixel_size()
        return w + 20

    def __init__(self):
        super().__init__(title="Плеер")

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        pal = popup_theme.palette()
        css = popup_theme.css(popup_theme.SCALE_CSS + """
        .popup-box {
            /* Пиксельный шрифт — явно и ТОЛЬКО 16 px (= 12 pt): у PxPlus сетка 8 px,
               на 10–14 px буквы мылились, и плеер выглядел не пиксельным (29.09.2026).
               Иконки кнопок приходят из Nerd Font запасным шрифтом, их размеры прежние. */
            font-family: 'PxPlus HP 100LX 6x8 Jarvis', 'JetBrainsMono NF', sans-serif;
            border-radius: 14px; padding: 6px;
        }
        /* Карточка трека: фон — размытая обложка (задаётся из кода, свой класс cardN). */
        .card { border-radius: 11px; padding: 8px 12px 6px 12px; }
        label.title { font-size: 16px; font-weight: normal; color: #ffffff; }
        label.artist { font-size: 16px; font-weight: normal; color: alpha(#ffffff, 0.62); }
        /* Время — 12 px: 16 было крупно, 8 — мелко (30.09.2026). У PxPlus чётко
           только кратное 8, на 12 края чуть мягче — как у самого бара на 13 px. */
        label.time { font-size: 12px; font-weight: normal; color: alpha(#ffffff, 0.62); }
        label.idle { font-weight: normal; color: %(on_surface_variant)s; }
        separator.cards { background-color: %(outline_variant)s; min-height: 1px; margin: 4px 0; }
        /* Управление как в «райсах»: боковые кнопки — прозрачные круги, «плей» —
           крупный акцентный круг посередине (30.09.2026). */
        button.ctrl {
            background-color: transparent; color: #ffffff;
            background-image: none; border: none; box-shadow: none;
            border-radius: 999px; padding: 0; font-size: 15px;
            min-width: 30px; min-height: 30px;
        }
        button.ctrl:hover { background-color: alpha(#ffffff, 0.12); color: %(primary)s; }
        button.play { background-color: %(primary)s; color: %(on_primary)s;
                      min-width: 36px; min-height: 36px; font-size: 16px; }
        button.play:hover { background-color: shade(%(primary)s, 1.12); color: %(on_primary)s; }
        /* Прогресс — тонкая полоса, как в «райсах». */
        scale trough { min-height: 4px; border-radius: 2px; background-color: alpha(#ffffff, 0.18); }
        scale highlight { min-height: 4px; border-radius: 2px; }
        button.open {
            background-color: %(open_bg)s; color: %(primary)s; background-image: none;
            border: 1px solid %(open_border)s; box-shadow: none;
            border-radius: 7px; padding: 0 6px; font-size: 12px; min-height: 18px;
        }
        button.open:hover { background-color: %(primary)s; color: %(on_primary)s; }
        button.close {
            background: transparent; background-image: none; border: none; box-shadow: none;
            color: %(on_surface_variant)s; padding: 0 4px; min-height: 18px; min-width: 18px;
            font-size: 12px; border-radius: 6px;
        }
        button.close:hover { background-color: %(surface_high)s; color: %(error)s; }
        button.like {
            background-color: %(open_bg)s; color: %(primary)s; background-image: none;
            border: 1px solid %(open_border)s; box-shadow: none;
            /* глиф сердца в Nerd Font сидит на 1 px правее середины своей
               клетки — правый отступ 2 px возвращает его в центр кнопки */
            border-radius: 7px; padding: 0 2px 0 0; font-size: 12px;
            min-height: 18px; min-width: 20px;
        }
        button.like:hover, button.like.liked { background-color: %(primary)s; color: %(on_primary)s; }
        scale slider { min-width: 12px; min-height: 12px; margin: -4px 0; }
        """, accent="primary", knob="on_surface",
                              open_bg=popup_theme.rgba(pal["primary"], "0.18"),
                              open_border=popup_theme.rgba(pal["primary"], "0.35"))
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.bg = Gtk.EventBox()
        self.bg.connect("button-press-event", lambda w, e: sys.exit(0))
        self.add(self.bg)
        self.align = Gtk.Box()
        self.bg.add(self.align)
        # Ровно под пилюлей плеера, а не под точкой щелчка (23.09.2026).
        # Пилюля плеера вплотную примыкает к системной группе, и по картинке
        # её правый край не отделить; поэтому ширина считается: тот же текст,
        # что сейчас в баре, тем же шрифтом, плюс отступы пилюли (padding 0 10px).
        popup_theme.place_under_cursor(self.align, snap_to_pill=True,
                                       pill_width=self.bar_pill_width())
        self.popup_event = Gtk.EventBox()
        self.popup_event.connect("button-press-event", lambda w, e: True)
        self.align.add(self.popup_event)

        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.vbox.get_style_context().add_class("popup-box")
        self.vbox.set_size_request(280, -1)
        self.popup_event.add(self.vbox)
        self.connect("key-press-event", self.on_key)

        self.cards = []
        self.idle = None
        self.dismissed = set()
        self.rebuild()
        GLib.timeout_add(POLL_MS, self.refresh)

    def rebuild(self):
        """Собрать карточки заново: по одной на плеер, между ними линия."""
        for child in self.vbox.get_children():
            self.vbox.remove(child)
        self.cards = []
        for r in player_rows():
            if r["instance"] in self.dismissed:
                continue
            m = metadata(r["instance"])
            if not m:
                continue
            if self.cards:
                sep = Gtk.Separator()
                sep.get_style_context().add_class("cards")
                self.vbox.pack_start(sep, False, False, 0)
            card = PlayerCard(r["instance"], m)
            self.vbox.pack_start(card, False, False, 0)
            self.cards.append(card)
        if not self.cards:
            idle = Gtk.Label(label="Сейчас ничего не играет")
            idle.get_style_context().add_class("idle")
            self.vbox.pack_start(idle, True, True, 8)
        self.vbox.show_all()

    def refresh(self):
        # Появился или пропал плеер — пересобрать; иначе обновить на месте.
        now = [r["instance"] for r in player_rows() if r["instance"] not in self.dismissed]
        if sorted(now) != sorted(c.player for c in self.cards):
            self.rebuild()
            return True
        for card in self.cards:
            card.refresh()
        return True

    def dismiss(self, card):
        """Убрать карточку остановленного плеера до конца жизни попапа."""
        self.dismissed.add(card.player)
        self.rebuild()

    def on_key(self, _w, event):
        # Пробел — пауза у первого плеера (того, что показан в баре).
        if event.keyval == Gdk.KEY_space and self.cards:
            self.cards[0].on_play()
            return True
        sys.exit(0)


if __name__ == "__main__":
    win = PlayerPopup()
    win.show_all()
    Gtk.main()
