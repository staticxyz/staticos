#!/usr/bin/env python3
"""Вторая пачка виджетов для desktop_widgets.py. 02.10.2026.

Не запускается сам: desktop_widgets.py зовёт register(globals()) и получает классы.
(Импортировать сам desktop_widgets.py отсюда нельзя — он при загрузке разбирает
argv и стартует сторожем; поэтому всё нужное передаётся словарём.)

Просьба: «виджеты добавь новые, которые были бы полезны, да и просто красиво
дополняли систему… необязательно консольные», и два по образцам со снимков.

    sysmon      sysmon.exe      CPU/GPU/RAM/VRAM с полосками, сеть ↓↑ (по снимку)
    banner      banner.exe      крупная надпись, бегущая строка — как `text … -f`
    player      player.exe      что играет: обложка, название, исполнитель, ход
    playermini  nowplaying.exe  то же одной строкой — минималистичный
    calendar    calendar.exe    месяц сеткой, сегодня выделено
    timer       timer.exe       таймер (или секундомер) крупными цифрами, со звонком
    screentime  screentime.exe  экранное время сегодня: всего и первые программы
    miku        miku.exe        пиксельная Мику с «Пуска», в гамме обоев
    fire        fire.exe        огонь из Doom (PSX) в цветах обоев
    life        life.exe        «Жизнь» Конвея
    weather     weather.exe     погода сейчас и на три дня (wttr.in, город по IP или opts.city)
"""
import calendar as _cal
import datetime
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

HOME = os.path.expanduser("~")



def register(ns):
    Widget, SecondTicker, T = ns["Widget"], ns["SecondTicker"], ns["T"]
    GLib, PangoCairo, Pango, cairo = ns["GLib"], ns["PangoCairo"], ns["Pango"], ns["cairo"]
    font_desc, crisp, CACHE, _pdeathsig = ns["font_desc"], ns["crisp"], ns["CACHE"], ns["_pdeathsig"]
    fit_px, adv, draw_digits = ns["fit_px"], ns["adv"], ns["draw_digits"]
    SIZES = ns["SIZES"]
    # подгонка размеров под Cozette — снимается флагом (cozette_fit.py off)
    COZ = ns.get("COZETTE", False) and os.path.exists(os.path.expanduser("~/.config/hypr/state/cozette-fit"))

    def text(cr, s, x, y, px, color, alpha=1.0, right=None, width=None, center=None):
        """Строка пиксельным шрифтом. right — правый край (выравнивание вправо),
        center — ширина, по которой центрировать; width — обрезать с многоточием."""
        crisp(cr)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(font_desc(px))
        lay.set_text(s, -1)
        if width:
            lay.set_width(max(1, int(width)) * Pango.SCALE)
            lay.set_ellipsize(Pango.EllipsizeMode.END)
        lw, lh = lay.get_pixel_size()
        if right is not None:
            x = right - lw
        elif center is not None:
            x = x + (center - lw) // 2
        cr.set_source_rgba(*color, alpha)
        cr.move_to(int(x), int(y))
        PangoCairo.show_layout(cr, lay)
        return lw, lh

    def bar(cr, x, y, w, h, frac, seg, color=None):
        """Полоска из отрезков, как на образце: заполненные — акцентом (или color)."""
        n = max(1, int(w // (seg + 2)))
        on = round(max(0.0, min(1.0, frac)) * n)
        for i in range(n):
            if i < on:
                cr.set_source_rgb(*(color or T["accent"]))
            else:
                cr.set_source_rgba(*T["fg"], 0.16)
            cr.rectangle(x + i * (seg + 2), y, seg, h)
            cr.fill()

    def SIZES_DOWN(px):
        """На ступень мельче: длинной строке можно чуть ужаться, прежде чем ставить «…».
        Было ×0.55 — длинное название в player.exe выходило «крайне мелковато» (06.10.2026)."""
        return max([p for p in SIZES if p <= px * 0.8] or [8])

    def font_for(row_h):
        """Кегль (кратный 8 — пиксельный шрифт чёткий только так) под высоту строки."""
        return 8 * max(1, min(4, int(row_h // 13)))

    # ── sysmon.exe ──────────────────────────────────────────────────────────
    class SysMon(Widget, SecondTicker):
        """CPU, GPU, память, видеопамять и сеть — раз в две секунды.

        GPU — NVIDIA через один долгий `nvidia-smi -l 2` (а не запуск каждые две
        секунды) и только пока виджет на виду и карта не спит: опрос не даёт ей
        уснуть, поэтому спящую карту не трогаем и пишем «sleep»."""

        def setup(self):
            self.d = {}
            self.pc = self.pn = None
            self.gpu = None
            self.gproc = None
            self.n = 0
            self.sample()
            self.start_seconds()

        def cleanup(self):
            self.stop_seconds()
            self.on_stop()

        @staticmethod
        def nvidia_awake():
            try:
                for dev in os.listdir("/sys/bus/pci/devices"):
                    base = "/sys/bus/pci/devices/" + dev
                    if open(base + "/vendor").read().strip() == "0x10de" and \
                            open(base + "/class").read().startswith("0x03"):
                        return open(base + "/power/runtime_status").read().strip() == "active"
            except OSError:
                pass
            return False

        def on_start(self):
            if self.gproc or not self.nvidia_awake():
                return
            try:
                self.gproc = subprocess.Popen(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
                     "--format=csv,noheader,nounits", "-l", "2"], stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, preexec_fn=_pdeathsig)
            except OSError:
                self.gproc = None
                return
            threading.Thread(target=self.gpu_reader, args=(self.gproc,), daemon=True).start()

        def gpu_reader(self, proc):
            for line in proc.stdout:
                try:
                    self.gpu = [float(v) for v in line.split(",")]
                except ValueError:
                    pass

        def on_stop(self):
            if self.gproc:
                try:
                    self.gproc.terminate()
                except OSError:
                    pass
                self.gproc = None
            self.gpu = None

        def sample(self):
            d = {}
            try:
                f = [int(v) for v in open("/proc/stat").readline().split()[1:9]]
                tot, idle = sum(f), f[3] + f[4]
                if self.pc:
                    dt = tot - self.pc[0]
                    d["cpu"] = 100 * (1 - (idle - self.pc[1]) / dt) if dt > 0 else 0
                self.pc = (tot, idle)
            except (OSError, ValueError):
                pass
            try:
                for h in os.listdir("/sys/class/hwmon"):
                    if open("/sys/class/hwmon/%s/name" % h).read().strip() == "coretemp":
                        d["ctemp"] = int(open("/sys/class/hwmon/%s/temp1_input" % h).read()) / 1000
            except (OSError, ValueError):
                pass
            try:
                mi = dict(l.split(":") for l in open("/proc/meminfo"))
                tot = int(mi["MemTotal"].split()[0])
                d["ram"] = ((tot - int(mi["MemAvailable"].split()[0])) / 1048576, tot / 1048576)
            except (OSError, ValueError, KeyError):
                pass
            try:
                rx = tx = 0
                for l in open("/proc/net/dev").read().splitlines()[2:]:
                    name, rest = l.split(":", 1)
                    if name.strip() != "lo":
                        v = rest.split()
                        rx, tx = rx + int(v[0]), tx + int(v[8])
                now = time.monotonic()
                if self.pn:
                    dt = max(0.1, now - self.pn[0])
                    d["net"] = ((rx - self.pn[1]) / dt, (tx - self.pn[2]) / dt)
                self.pn = (now, rx, tx)
            except (OSError, ValueError):
                pass
            self.d = d

        def second(self):
            self.n += 1
            if self.n % 2 or not self.on_screen() or self.mgr.game:
                return False
            self.sample()
            return True

        @staticmethod
        def rate(v):
            v = max(0.0, v)
            if v >= 1048576:
                mb = v / 1048576
                return "%.1f MB/s" % mb if mb < 100 else "%d MB/s" % mb   # не длиннее 9 знаков
            return "%d KB/s" % (v / 1024)

        def paint(self, cr, x, y, w, h):
            d, g = self.d, self.gpu
            narrow = w < 190                      # узкому — короткие значения
            rows = [("CPU", d.get("cpu", 0) / 100, "%d%%" % d.get("cpu", 0),
                     "%d°" % d["ctemp"] if "ctemp" in d else "")]
            if g:
                rows.append(("GPU", g[0] / 100, "%d%%" % g[0], "%d°" % g[1]))
            else:
                rows.append(("GPU", 0, "sleep" if not self.gproc else "…", ""))
            if "ram" in d:
                rows.append(("RAM", d["ram"][0] / d["ram"][1],
                             "%.1fG" % d["ram"][0] if narrow else "%.1f / %d GB" % (d["ram"][0], round(d["ram"][1])), ""))
            if g:
                rows.append(("VRAM", g[2] / max(1, g[3]),
                             "%.1fG" % (g[2] / 1024) if narrow else "%.1f / %d GB" % (g[2] / 1024, round(g[3] / 1024)), ""))
            net = None
            if "net" in d and h >= 90:
                full = "↓ %s  ↑ %s" % (self.rate(d["net"][0]), self.rate(d["net"][1]))
                net = (("↓ " + self.rate(d["net"][0]), "↑ " + self.rate(d["net"][1])), len(full))
            rh = h / (len(rows) + (0.75 if net else 0))
            longest = max(len(n) + 1 + len(v) + (1 + len(e) if e else 0) for n, _f, v, e in rows)
            px = fit_px(longest, w, rh * 0.62)
            bh = max(2, px // 4)
            for i, (name, frac, val, extra) in enumerate(rows):
                ry = y + i * rh
                text(cr, name, x, ry, px, T["fg"])
                r = x + w
                if extra:
                    lw, _ = text(cr, extra, 0, ry, px, T["fg"], 0.7, right=r)
                    r -= lw + adv(px) / 2
                text(cr, val, 0, ry, px, T["fg"], 0.7, right=r)
                bar(cr, x, ry + px + max(2, (rh - px - bh) / 3), w, bh, frac, max(3, px // 2))
            if net:
                # Кегль и место «↑» — по самой длинной строке («↓ 1023 KB/s»), а не по
                # текущей: иначе цифры то крупнее, то мельче (06.10.2026, пользователь).
                (dn, up), _n = net
                col = 2 + 9 + 2
                npx = fit_px(col * 2 - 2, w, rh * 0.62, top=px)
                ny = y + h - npx - 1
                text(cr, dn, x, ny, npx, T["ansi"][2])
                ux = x + adv(npx) * col
                text(cr, up, ux, ny, npx, T["fg"], 0.7, width=x + w - ux)

    # ── banner.exe ──────────────────────────────────────────────────────────
    class Banner(Widget):
        """Крупная надпись — как `text gamesense -f`: шрифт 6x8, увеличенный по пикселям
        во всю высоту; scroll (по умолчанию да) — бегущая строка справа налево."""
        interval = 33

        def setup(self):
            self.small = None
            self.off = None
            self.t = None

        def theme_changed(self):
            self.small = None

        def build(self):
            s = str(self.opts.get("text", "gamesense"))
            # Cozette (08.10.2026): font_desc(8) давал 10 px — не родной кегль, буквы выходили
            # кривыми и потом увеличивались вместе с кривизной. Родной — 13.
            bpx = 13 if ns.get("COZETTE", False) else 8
            probe = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8))
            crisp(probe)
            lay = PangoCairo.create_layout(probe)
            lay.set_font_description(font_desc(bpx))
            lay.set_text(s, -1)
            lw, lh = lay.get_pixel_size()
            self.small = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, lw), max(1, lh))
            cr = cairo.Context(self.small)
            fo = cairo.FontOptions()
            fo.set_antialias(cairo.ANTIALIAS_NONE)       # чистые пиксели: их потом увеличивать
            PangoCairo.context_set_font_options(PangoCairo.create_context(cr), fo)
            lay = PangoCairo.create_layout(cr)
            PangoCairo.context_set_font_options(lay.get_context(), fo)
            lay.set_font_description(font_desc(bpx))
            lay.set_text(s, -1)
            cr.set_source_rgb(*T["accent"])
            PangoCairo.show_layout(cr, lay)

        def scrolling(self):
            return bool(self.opts.get("scroll", True))

        def tick(self):
            if not self.scrolling():
                return False
            now = time.monotonic()
            if self.off is not None and self.t is not None:
                self.off -= float(self.opts.get("speed", 90)) * (now - self.t)
            self.t = now
            return True

        def on_stop(self):
            self.t = None

        def dirty_rect(self):
            return self.inner()

        def paint(self, cr, x, y, w, h):
            if self.small is None:
                self.build()
            sw, sh = self.small.get_width(), self.small.get_height()
            k = max(1, h // sh)
            if self.scrolling():
                if self.off is None or self.off < -sw * k:
                    self.off = w
                ox = x + self.off
            else:
                k = max(1, min(k, w // max(1, sw)))
                ox = x + (w - sw * k) // 2
            cr.save()
            cr.translate(int(ox), y + (h - sh * k) // 2)
            cr.scale(k, k)
            cr.set_source_surface(self.small, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint()
            cr.restore()

    # ── player.exe ──────────────────────────────────────────────────────────
    class Player(Widget, SecondTicker):
        """Что играет: один долгий `playerctl -a -F` сообщает о смене трека и паузе у всех
        плееров, ход между событиями досчитывается по часам.

        Кого показывать (05.10.2026, Просьба: «через какое-то время начинает показывать, что
        играет что-то в браузере, а не в плеере Яндекс Музыки… приоритет — Yandex Music,
        YouTube Music, Spotify»). Раньше виджет слушал один «текущий» плеер playerctl, и
        любая вкладка браузера, сообщившая о себе, перебивала музыку. Теперь состояние
        хранится по каждому плееру, а выбирается: играющий раньше приостановленного; среди
        равных — музыкальный сервис (приложение Яндекс Музыки/Spotify или вкладка
        music.youtube.com, music.yandex…, open.spotify.com), потом прочие плееры, браузер
        последним; дальше — кто сообщил о себе позже. Кнопки управляют выбранным плеером."""
        SEP = "\x1f"
        FMT = SEP.join(("{{playerInstance}}", "{{status}}", "{{title}}", "{{artist}}",
                        "{{mpris:artUrl}}", "{{mpris:length}}", "{{position}}", "{{xesam:url}}"))
        BROWSERS = {"firefox", "zen", "librewolf", "chromium", "chrome", "helium", "brave",
                    "thorium", "vivaldi", "opera", "edge", "floorp", "waterfox", "epiphany",
                    "falkon", "qutebrowser", "mercury", "midori", "browser", "mozilla"}
        MUSIC_APPS = ("yandexmusic", "yandex music", "spotify", "youtube music", "youtube-music")
        MUSIC_HOSTS = ("music.youtube.com", "open.spotify.com", "music.yandex.")

        def setup(self):
            self.st = None
            self.at = 0.0
            self.cover = None
            self.cover_url = None
            self.proc = None
            self.players = {}          # instance → состояние
            self.ident = {}            # instance → MPRIS Identity
            self.inst = None           # кого показываем и кем управляем
            threading.Thread(target=self.follow, daemon=True).start()
            # Снимок всех плееров при старте и раз в 10 с, пока ничего не играет (06.10.2026):
            # `playerctl -a -F` при запуске сообщил только о Telegram, о играющей Яндекс Музыке —
            # ни слова, и виджет стоял на «Nothing playing», хотя трек играл.
            GLib.timeout_add(1500, self.snapshot)
            GLib.timeout_add_seconds(10, self.snapshot)
            self.start_seconds()

        def follow(self):
            n = 0
            while not getattr(self, "dead", False):
                try:
                    self.proc = subprocess.Popen(["playerctl", "-a", "metadata", "-F", "--format", self.FMT],
                                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                                 text=True, preexec_fn=_pdeathsig)
                    for line in self.proc.stdout:
                        f = line.rstrip("\n").split(self.SEP)
                        if f and f[0] and f[0] not in self.ident:
                            self.ident[f[0]] = self.identity(f[0])
                        GLib.idle_add(self.got, f)
                    self.proc.wait()
                except OSError:
                    pass
                time.sleep(3)

        def snapshot(self):
            if getattr(self, "dead", False):
                return False
            if self.st and self.st.get("playing"):
                return True                       # играет и видно — снимок не нужен

            def work():
                try:
                    out = subprocess.run(["playerctl", "-a", "metadata", "--format", self.FMT],
                                         capture_output=True, text=True, timeout=3).stdout
                except (OSError, subprocess.SubprocessError):
                    return
                for line in out.splitlines():
                    f = line.split(self.SEP)
                    if f and f[0] and f[0] not in self.ident:
                        self.ident[f[0]] = self.identity(f[0])
                    GLib.idle_add(self.got, f)
            threading.Thread(target=work, daemon=True).start()
            return True

        def drop(self, inst, stamp):
            """Плеер сообщил «трека нет»/Stopped и за 1,5 с не появился снова — убрать."""
            p = self.players.get(inst)
            if p and p.get("gone") == stamp:
                self.players.pop(inst, None)
                self.choose()
            return False

        @staticmethod
        def identity(inst):
            try:
                out = subprocess.run(["busctl", "--user", "get-property", "org.mpris.MediaPlayer2." + inst,
                                      "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2", "Identity"],
                                     capture_output=True, text=True, timeout=2).stdout
                return out.strip()[2:].strip().strip('"') if out.startswith("s ") else ""
            except (OSError, subprocess.SubprocessError):
                return ""

        @staticmethod
        def mpris_names():
            """Плееры на шине — то же, что печатает `playerctl -l` (без playerctld). None — ошибка."""
            try:
                from gi.repository import Gio
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                r = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                  "ListNames", None, None, Gio.DBusCallFlags.NONE, 2000, None)
                pre = "org.mpris.MediaPlayer2."
                return {n[len(pre):] for n in r.unpack()[0]
                        if n.startswith(pre) and n[len(pre):] != "playerctld"}
            except Exception:
                return None

        def rank(self, inst, url):
            """0 — музыкальный сервис, 1 — прочий плеер, 2 — браузер."""
            import re
            import urllib.parse
            name = (self.ident.get(inst) or inst).lower()
            if any(m in name for m in self.MUSIC_APPS):
                return 0
            if not set(re.split(r"[^a-z0-9]+", name)) & self.BROWSERS:
                return 1
            host = urllib.parse.urlsplit(url or "").netloc.lower()
            return 0 if host and any(host.startswith(h) or host.endswith("." + h)
                                     for h in self.MUSIC_HOSTS) else 2

        def got(self, f):
            # «Stopped» — ничего не играет (Telegram после голосового оставлял «yesterday at
            # 4:05 AM xXx» — Просьба: «странное значение, лучше Nothing playing»)
            if len(f) < 8 or not f[0]:
                return False
            inst = f[0]
            if not f[2] or f[1] == "Stopped":
                # Не сразу: при смене трека Яндекс на миг сообщает «трека нет», и виджет
                # мигал «Nothing playing» (06.10.2026). Уберём, если за 1,5 с нового нет.
                p = self.players.get(inst)
                if p is not None and not p.get("gone"):
                    p["gone"] = stamp = time.monotonic()
                    GLib.timeout_add(1500, self.drop, inst, stamp)
                return False
            else:
                def num(v):
                    try:
                        return int(v) / 1e6
                    except ValueError:
                        return 0.0
                prev = self.players.get(inst) or {}
                playing = f[1] == "Playing"
                # когда встал на паузу (для удержания на экране, см. choose)
                paused_at = prev.get("paused_at") if not playing and not prev.get("playing", True) \
                    else (time.monotonic() if not playing else None)
                # Длина трека: часть событий playerctl приходит без mpris:length — у того же
                # трека прежняя длина не теряется (06.10.2026, Просьба: «время в плеере иногда
                # пропадает само, появляется снова, когда ставлю на паузу»)
                length = num(f[5])
                if not length and prev.get("title") == f[2]:
                    length = prev.get("len", 0.0)
                self.players[inst] = {"playing": playing, "title": f[2], "artist": f[3],
                                      "art": f[4] or (prev.get("art", "") if prev.get("title") == f[2] else ""),
                                      "len": length, "pos": num(f[6]),
                                      "at": time.monotonic(), "rank": self.rank(inst, f[7]),
                                      "paused_at": paused_at}
            self.choose()
            return False

        def choose(self):
            alive = self.players
            if alive and len(alive) > 1:
                # закрытые плееры -F не сообщает — сверяемся со списком на шине
                try:
                    # 05.10.2026, оптимизация: список плееров — прямо с шины (ListNames, ~0,2 мс),
                    # а не запуском `playerctl -l` (~5 мс) на КАЖДОЕ событие: при видео в браузере
                    # события идут раз в секунду на каждый виджет-плеер. Не вышло — как раньше.
                    have = self.mpris_names()
                    if have is None:
                        have = set(subprocess.run(["playerctl", "-l"], capture_output=True, text=True,
                                                  timeout=2).stdout.split())
                    for k in [k for k in alive if k not in have]:
                        del alive[k]
                except (OSError, subprocess.SubprocessError):
                    pass
            # Правила показа (06.10.2026, пользователь): играющее — всегда, музыка раньше видео.
            # Ничего не играет: музыка на паузе держится 5 минут, видео в браузере — 2,5
            # (потом показывается музыка), дальше «Nothing playing». Крестик в плеере верхнего
            # бара (player_popup.py) убирает плеер сразу — метка DISMISS.
            now = time.monotonic()
            gone = self.dismissed()
            live = {k: v for k, v in alive.items() if (k, v["title"]) not in gone or v["playing"]}
            best = None
            playing = [k for k, v in live.items() if v["playing"]]
            if playing:
                best = min(playing, key=lambda k: (live[k]["rank"], -live[k]["at"]))
            else:
                def until(k):
                    v = live[k]
                    base = max(v.get("paused_at") or 0, v.get("shown_from") or 0)
                    return base + (self.PAUSE_VIDEO if v["rank"] == 2 else self.PAUSE_MUSIC)
                vis = [k for k in live if now < until(k)]
                if self.inst in vis:
                    best = self.inst
                elif vis:
                    best = min(vis, key=lambda k: (live[k]["rank"], -(live[k].get("paused_at") or 0)))
                    live[best]["shown_from"] = now
                if vis:
                    # проснуться, когда истечёт ближайший срок
                    left = min(until(k) for k in vis) - now
                    if getattr(self, "_hold_t", None):
                        GLib.source_remove(self._hold_t)

                    def again():
                        self._hold_t = None
                        self.choose()
                        return False
                    self._hold_t = GLib.timeout_add(int(max(0.5, left) * 1000) + 200, again)
            if best is None:
                self.inst, self.st = None, None
            else:
                self.inst = best
                p = alive[self.inst]
                self.st = {k: p[k] for k in ("playing", "title", "artist", "len", "pos")}
                self.at = p["at"]
                if p["art"] != self.cover_url:
                    # Прежняя обложка остаётся, пока не загрузится новая (06.10.2026, пользователь:
                    # «при переключении треков виджет трясётся»): сброс в None убирал место под
                    # обложку — текст прыгал влево и через миг обратно. Нет обложки у нового
                    # трека — убрать старую через 2 с.
                    self.cover_url = p["art"]
                    if p["art"]:
                        threading.Thread(target=self.load_cover, args=(p["art"],), daemon=True).start()
                    else:
                        def clear(url=p["art"]):
                            if self.cover_url == url:
                                self.cover = None
                                self.area.queue_draw()
                            return False
                        GLib.timeout_add(2000, clear)
            self.area.queue_draw()

        PAUSE_MUSIC = 300    # музыка на паузе — 5 минут на экране (06.10.2026)
        PAUSE_VIDEO = 150    # видео в браузере на паузе — 2,5 минуты, потом музыка
        DISMISS = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-player-dismissed")

        def dismissed(self):
            """{(плеер, название)} — убранные крестиком в плеере верхнего бара (player_popup.py
            пишет строку «плеер<TAB>название»). Пока трек тот же и не играет — не показываем."""
            out = set()
            try:
                for line in open(self.DISMISS):
                    a, _, t = line.rstrip("\n").partition("\t")
                    out.add((a, t))
            except OSError:
                pass
            return out

        def ctl(self, cmd):
            args = ["playerctl"] + (["-p", self.inst] if self.inst else []) + [cmd]
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)

        def load_cover(self, url):
            path = None
            if url.startswith("file://"):
                from urllib.parse import unquote
                path = unquote(url[7:])
            elif url.startswith("http"):
                d = os.path.join(CACHE, "covers")
                os.makedirs(d, exist_ok=True)
                path = os.path.join(d, hashlib.md5(url.encode()).hexdigest())
                if not os.path.exists(path):
                    try:
                        import urllib.request
                        with urllib.request.urlopen(url, timeout=8) as r, open(path + ".tmp", "wb") as f:
                            f.write(r.read())
                        os.replace(path + ".tmp", path)
                    except Exception:
                        path = None
            GLib.idle_add(self.set_cover, url, path)

        def set_cover(self, url, path):
            if url == self.cover_url:
                self.cover = None
                if path:
                    try:
                        from gi.repository import GdkPixbuf
                        self.cover = GdkPixbuf.Pixbuf.new_from_file(path)
                    except Exception:
                        self.cover = None          # не загрузилась — не держать чужую обложку
                self.area.queue_draw()
            return False

        def second(self):
            return bool(self.st and self.st["playing"] and self.on_screen())

        def cleanup(self):
            self.dead = True
            self.stop_seconds()
            if self.proc:
                try:
                    self.proc.terminate()
                except OSError:
                    pass

        @staticmethod
        def mmss(v):
            v = int(max(0, v))
            return "%d:%02d:%02d" % (v // 3600, v % 3600 // 60, v % 60) if v >= 3600 else "%d:%02d" % (v // 60, v % 60)

        # Вид по образцу пользователя (02.10.2026, «более компактный и аккуратный»): обложка с
        # полями, компактные название и исполнитель, тонкая линия (она же ход трека) и
        # три кнопки — назад, пауза/играть, вперёд. Кнопки нажимаются мышью.
        clickable = True
        # Значки кнопок — одна сетка 8×7 точек у всех (02.10.2026: первые были разной ширины
        # и с узким «лестничным» треугольником — Просьба: «неровные, растянутые»). Треугольник
        # растёт по две точки на строку — выходит ровный, как в пиксельном шрифте.
        ICON = {
            "prev": ("##....##", "##..####", "########", "########", "########", "##..####", "##....##"),
            "next": ("##....##", "####..##", "######.#", "########", "######.#", "####..##", "##....##"),
            "pause": (".##..##.", ".##..##.", ".##..##.", ".##..##.", ".##..##.", ".##..##.", ".##..##."),
            "play": (".##.....", ".####...", ".######.", ".#######", ".######.", ".####...", ".##....."),
        }

        def on_click(self, x, y, button=1):
            if button != 1:
                return
            for name, (bx, by, bw, bh) in getattr(self, "btns", {}).items():
                if bx <= x < bx + bw and by <= y < by + bh:
                    self.ctl({"prev": "previous", "toggle": "play-pause", "next": "next"}[name])
                    return

        def draw_cover(self, cr, x, y, side):
            from gi.repository import Gdk, GdkPixbuf
            cw, chh = self.cover.get_width(), self.cover.get_height()
            k = max(side / cw, side / chh)
            pb = self.cover.scale_simple(max(1, int(cw * k)), max(1, int(chh * k)),
                                         GdkPixbuf.InterpType.BILINEAR)
            cr.save()
            cr.rectangle(x, y, side, side)
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, pb, x - (pb.get_width() - side) // 2,
                                        y - (pb.get_height() - side) // 2)
            cr.paint()
            cr.restore()

        def paint(self, cr, x, y, w, h):
            st = self.st
            self.btns = {}
            if not st:
                px = fit_px(15, w, h * 0.5, top=24)
                text(cr, "Nothing playing", x, y + (h - px) // 2, px, T["fg"], 0.5, center=w, width=w)
                return
            # раскладка по форме виджета: широкий — обложка слева, высокий — сверху,
            # совсем тесный — без обложки; все размеры — доли высоты, поэтому при
            # растягивании и сжатии пропорции сохраняются
            pad = max(3, int(min(w, h) * 0.07))
            have = self.cover is not None
            tall = h >= w * 0.6 and h >= 110
            if tall:
                side = int(min(w - 2 * pad, h * 0.5)) if have else 0
                if side:
                    self.draw_cover(cr, x + (w - side) // 2, y + pad, side)
                tx, tw = x + pad, w - 2 * pad
                ty, th = y + (side + 2 * pad if side else pad), h - (side + 3 * pad if side else 2 * pad)
            else:
                side = h - 2 * pad if (have and h >= 40 and w >= h * 1.6) else 0
                if side:
                    self.draw_cover(cr, x + pad, y + pad, side)
                tx = x + (side + 3 * pad if side else pad)
                tw = x + w - tx - pad
                ty, th = y + pad, h - 2 * pad
            # строки: название, исполнитель, линия хода, кнопки — что влезает по высоте
            rows = 3 if th >= 50 else (2 if th >= 30 else 1)
            tpx = fit_px(1, tw, th * (0.26 if rows == 3 else 0.42 if rows == 2 else 0.9), top=24)
            apx = max(8, [p for p in (8, 10, 12, 14, 16, 20) if p <= tpx * 0.8 + 0.5][-1]) if rows == 3 else 0
            # значки мелкие и аккуратные, как на образце: 7 точек в высоту, удваиваются
            # только в крупном виджете
            bh = 7 if rows >= 2 else 0
            k = 2 if tpx >= 24 else 1
            gap = max(4, tpx // 2)
            total = tpx + (gap // 2 + apx if apx else 0) + (gap + 2 + gap + 7 * k if bh else 0)
            yy = ty + max(0, (th - total) // 2)
            fpx = max(fit_px(len(st["title"]), tw, tpx), min(tpx, max(8, SIZES_DOWN(tpx))))
            text(cr, st["title"], tx, yy + (tpx - fpx) // 2, fpx, T["on_surface"], width=tw)
            yy += tpx
            if apx:
                yy += gap // 2
                text(cr, st["artist"] or "—", tx, yy, apx, T["fg"], 0.6, width=tw)
                yy += apx
            if not bh:
                return
            pos = st["pos"] + (time.monotonic() - self.at if st["playing"] else 0)
            frac = min(1.0, pos / st["len"]) if st["len"] > 0 else 0
            yy += gap
            cr.set_source_rgba(*T["fg"], 0.16)                 # тонкая линия — она же ход трека
            cr.rectangle(tx, yy, tw, 2)
            cr.fill()
            cr.set_source_rgb(*T["accent"])
            cr.rectangle(tx, yy, int(tw * frac), 2)
            cr.fill()
            yy += 2 + gap
            # кнопки: значок 7 точек в высоту, зона нажатия шире самого значка
            names = ("prev", "pause" if st["playing"] else "play", "next")
            step = 8 * k + 12 * k                     # значок 8 точек и просвет в полтора значка
            bx = tx + (max(0, (tw - (2 * step + 8 * k)) // 2) if tall else 0)
            cr.set_source_rgba(*T["fg"], 0.85)
            for i, name in enumerate(names):
                ns["draw_bitmap"](cr, [[c == "#" for c in r] for r in self.ICON[name]],
                                  bx + i * step, yy, k, k)
                # зона нажатия — шире значка: по половине просвета в стороны и по высоте строки
                self.btns[("prev", "toggle", "next")[i]] = (bx + i * step - 6 * k, yy - gap,
                                                            step, 7 * k + 2 * gap)
            # время «1:23 / 3:45» справа в ряду кнопок — мелко и приглушённо, чтобы сливалось
            # с окружением (05.10.2026, пользователь); нет места рядом с кнопками — не рисуется
            if st["len"] > 0:
                tpx2 = 16 if k == 2 else 8
                msg = "%s / %s" % (self.mmss(pos), self.mmss(st["len"]))
                mw = len(msg) * adv(tpx2)
                if tx + tw - mw > bx + 2 * step + 8 * k + gap:
                    text(cr, msg, 0, yy + (7 * k - tpx2) // 2 + 1, tpx2, T["fg"], 0.45, right=tx + tw)

    # ── nowplaying.exe ──────────────────────────────────────────────────────
    class PlayerMini(Player):
        """Плеер в одну строку (Просьба: «виджет с плеером, минималистичный»): значок
        играет/пауза, «название — исполнитель», время и тонкая линия хода под ними."""

        def on_click(self, x, y, button=1):
            if button == 1:                    # одна строка — один щелчок: пауза / играть
                self.ctl("play-pause")

        def paint(self, cr, x, y, w, h):
            st = self.st
            px = fit_px(1, w, h - 5, top=40)
            ty = y + max(0, (h - 6 - px) // 2)
            if not st:
                text(cr, "Nothing playing", x, ty, px, T["fg"], 0.5)
                return
            cr.set_source_rgb(*T["accent"])
            # значок — как на кнопке плеера: трек идёт — «пауза», стоит — «играть»
            # (02.10.2026; сперва было наоборот — значок состояния)
            s = px - 4
            if not st["playing"]:
                cr.move_to(x, ty + 2)
                cr.line_to(x + s, ty + 2 + s / 2)
                cr.line_to(x, ty + 2 + s)
                cr.close_path()
            else:
                cr.rectangle(x, ty + 2, s * 0.35, s)
                cr.rectangle(x + s * 0.6, ty + 2, s * 0.35, s)
            cr.fill()
            pos = st["pos"] + (time.monotonic() - self.at if st["playing"] else 0)
            if st["len"] > 0:
                pos = min(pos, st["len"])
            lw = 0
            if w >= adv(px) * 18:              # время — только если останется место названию
                lw, _ = text(cr, self.mmss(pos), 0, ty, px, T["fg"], 0.6, right=x + w)
            tx = x + s + px // 2 + 4
            lw2, _ = text(cr, st["title"], tx, ty, px, T["accent"], width=x + w - lw - px - tx)
            rest = x + w - lw - px - (tx + lw2 + px)
            if st["artist"] and rest > px * 4:
                text(cr, "— " + st["artist"], tx + lw2 + px // 2, ty, px, T["fg"], 0.65, width=rest + px // 2)
            cr.set_source_rgba(*T["fg"], 0.16)
            cr.rectangle(x, y + h - 3, w, 3)
            cr.fill()
            if st["len"] > 0:
                cr.set_source_rgb(*T["accent"])
                cr.rectangle(x, y + h - 3, int(w * pos / st["len"]), 3)
                cr.fill()

    # ── timer.exe ───────────────────────────────────────────────────────────
    class Timer(Widget, SecondTicker):
        """Таймер: opts.end — когда закончится (секунды эпохи), opts.dur — на сколько был
        поставлен, opts.label — надпись; без end — секундомер от opts.start.

        Щелчки по самому виджету (02.10.2026):
          * идёт — щелчок ставит на паузу, ещё щелчок — продолжает;
          * истёк («TIME IS UP») — щелчок показывает две кнопки: REPLAY (тот же отсчёт
            заново) и NEW (окно ввода нового названия и времени);
          * ПКМ в любой момент — сброс отсчёта заново: вопрос «Вы уверены?» и кнопки
            RESET / CANCEL (щелчок мимо кнопок или ещё один ПКМ — отмена).
        По истечении — звук, уведомление и мигающие нули. Отсчёт переживает перезапуск:
        хранится время конца (на паузе — остаток), а не «сколько прошло».

        Звук (08.10.2026, Просьба: «верни родной звук, продолжительный, и не заканчиваться,
        пока я не уберу уведомление, не закрою таймер или не включу его заново»): свой
        alarm-clock-elapsed (не из набора звуков интерфейса — там XP-шный tada), по кругу,
        пока не закрыли уведомление, не закрыли виджет, не запустили заново (REPLAY,
        NEW, сброс по ПКМ) или не щёлкнули по самому виджету. Во время игры молчит.
        Если уведомление не удалось показать, звонок от него не зависит — гасится щелчком."""
        clickable = True
        ALARM = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
        ALARM_VOLUME = 0.3                    # прежняя громкость его родного звонка

        def setup(self):
            self.menu = False                 # показаны ли кнопки REPLAY / NEW
            self.confirm = False              # показан ли вопрос «Вы уверены?» (сброс по ПКМ)
            self.btns = {}
            self.alarm = None                 # threading.Event звонка, пока звенит
            self.alarm_proc = None
            self.note_id = None               # id уведомления — закрыть, когда звонок сняли
            self.start_seconds()

        def cleanup(self):
            self.stop_alarm()
            self.stop_seconds()

        # состояние
        def paused(self):
            return "paused_left" in self.opts or "paused_elapsed" in self.opts

        def left(self):
            if "paused_left" in self.opts:
                return float(self.opts["paused_left"])
            if "end" in self.opts:
                return float(self.opts["end"]) - time.time()
            return None                       # секундомер

        def elapsed(self):
            if "paused_elapsed" in self.opts:
                return float(self.opts["paused_elapsed"])
            return time.time() - float(self.opts.get("start", time.time()))

        def done(self):
            left = self.left()
            return left is not None and left <= 0 and not self.paused()

        def keep(self):
            self.spec["opts"] = self.opts
            self.mgr.save()
            self.area.queue_draw()

        def second(self):
            if self.done() and not self.opts.get("rang"):
                self.opts["rang"] = True
                self.keep()
                self.ring()
            return self.on_screen() and not self.paused()

        # действия
        def toggle_pause(self):
            o = self.opts
            if "paused_left" in o:
                o["end"] = int(time.time() + o.pop("paused_left"))
            elif "paused_elapsed" in o:
                o["start"] = int(time.time() - o.pop("paused_elapsed"))
            elif "end" in o:
                o["paused_left"] = max(1, int(o.pop("end") - time.time() + 0.5))
            else:
                o["paused_elapsed"] = int(self.elapsed())
            self.keep()

        def replay(self):
            self.stop_alarm()
            o = self.opts
            dur = int(o.get("dur") or 0)
            if dur > 0:
                o["end"] = int(time.time() + dur)
            else:
                o.pop("end", None)
                o["start"] = int(time.time())
            for k in ("rang", "paused_left", "paused_elapsed"):
                o.pop(k, None)
            self.menu = False
            self.keep()

        def ask_new(self):
            words = ns["ask_timer"]()
            GLib.idle_add(self.set_new, words)

        def set_new(self, words):
            if words:
                self.stop_alarm()
                label, end = ns["parse_timer"](words)
                frame = {k: v for k, v in self.opts.items() if k in ("frame", "title")}
                self.opts = dict(frame)                 # новый таймер — адрес прежнего не наследует
                if label:
                    self.opts["label"] = label
                if end:
                    self.opts.update(end=int(end), dur=int(end - time.time()))
                else:
                    self.opts["start"] = int(time.time())
                self.menu = False
                self.keep()
            return False

        def on_click(self, x, y, button=1):
            if self.alarm is not None:         # звенит: первый щелчок только снимает звонок
                self.stop_alarm()
                if button == 1 and self.done():
                    self.menu = True
                    self.area.queue_draw()
                return
            if button == 3:                    # ПКМ: спросить про сброс (или убрать вопрос)
                self.confirm = not self.confirm
                self.menu = False
                self.area.queue_draw()
                return
            if self.confirm:
                hit = next((n for n, (bx, by, bw, bh) in self.btns.items()
                            if bx <= x < bx + bw and by <= y < by + bh), None)
                self.confirm = False
                if hit == "reset":
                    self.replay()
                else:
                    self.area.queue_draw()
                return
            if self.done():
                if self.menu:
                    for name, (bx, by, bw, bh) in self.btns.items():
                        if bx <= x < bx + bw and by <= y < by + bh:
                            if name == "replay":
                                self.replay()
                            else:
                                self.menu = False
                                threading.Thread(target=self.ask_new, daemon=True).start()
                            return
                self.menu = not self.menu
                self.area.queue_draw()
            else:
                self.toggle_pause()

        def ring(self):
            label = str(self.opts.get("label") or "timer")
            self.stop_alarm()
            ev = self.alarm = threading.Event()
            threading.Thread(target=self.alarm_loop, args=(ev,), daemon=True).start()
            url = str(self.opts.get("url") or "")
            threading.Thread(target=self.notify_wait, args=(ev, label, url), daemon=True).start()

        def alarm_loop(self, ev):
            """Родной звонок по кругу, пока ev не выставлен. Каждый проигрыш — отдельный
            pw-play (6 с) с timeout: если демон виджетов умрёт, звук стихнет сам."""
            props = ('{ application.name = "Таймер" node.description = "Таймер" '
                     'media.name = "Таймер" application.icon-name = "alarm-clock" '
                     'state.restore-props = false }')
            while not ev.is_set():
                if self.mgr.game or not os.path.exists(self.ALARM):
                    ev.wait(2)
                    continue
                try:
                    p = subprocess.Popen(["timeout", "15", "pw-play", "-P", props,
                                          "--volume", str(self.ALARM_VOLUME), self.ALARM],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
                except OSError:
                    ev.wait(2)
                    continue
                self.alarm_proc = p
                while p.poll() is None and not ev.is_set():
                    ev.wait(0.2)
                if p.poll() is None:
                    p.terminate()
                if p.returncode not in (None, 0):
                    ev.wait(1)                     # pw-play не смог — не крутить вхолостую
                ev.wait(0.4)

        def notify_wait(self, ev, label, url):
            """Уведомление ждёт закрытия (-p -w печатает id и ждёт); закрыли его — звонок
            снимается. Не показалось (нет демона уведомлений) — звонок не трогаем."""
            args = ["notify-send", "-a", "Timer", "-u", "critical", "-p", "-w"]
            if url:
                # у таймера есть адрес (пресет hh — «Мои резюме»): кнопка его открывает
                args += ["-A", "open=Открыть", "Таймер: " + label, "Время вышло — " + url.split("//")[-1]]
            else:
                args += ["Таймер: " + label, "Время вышло"]
            try:
                p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, start_new_session=True)
                first = p.stdout.readline().strip()
                if not first.isdigit():
                    return
                self.note_id = int(first)
                out = p.stdout.read().strip()
                p.wait()
                if self.alarm is ev:
                    self.note_id = None
                    GLib.idle_add(lambda: self.alarm is ev and self.stop_alarm() and False)
                if out == "open" and url:
                    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                print("timer:", e, file=sys.stderr)

        def stop_alarm(self):
            ev, self.alarm = self.alarm, None
            if ev is None:
                return
            ev.set()
            p, self.alarm_proc = self.alarm_proc, None
            if p and p.poll() is None:
                try:
                    p.terminate()
                except OSError:
                    pass
            nid, self.note_id = self.note_id, None
            if nid:                                # звонок сняли не через уведомление — убрать и его
                subprocess.Popen(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                                  "--object-path", "/org/freedesktop/Notifications", "--method",
                                  "org.freedesktop.Notifications.CloseNotification", str(nid)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)

        def paint(self, cr, x, y, w, h):
            left = self.left()
            done = self.done()
            v = int(self.elapsed()) if left is None else int(max(0, left) + 0.999)
            s = "%d:%02d:%02d" % (v // 3600, v % 3600 // 60, v % 60) if v >= 3600 else "%02d:%02d" % (v // 60, v % 60)
            label = str(self.opts.get("label") or "").upper()
            if self.confirm:
                label = "Вы уверены?"
            elif done:
                label = (label + " — " if label else "") + "TIME IS UP"
            elif self.paused():
                label = (label + " — " if label else "") + "PAUSED"
            ly = y
            if label and h >= 44:
                lpx = fit_px(len(label), w, h * 0.24, top=32)
                hot = done or self.confirm
                text(cr, label, x, y, lpx, T["primary"] if hot else T["fg"], 1.0 if hot else 0.75, center=w, width=w)
                ly = y + lpx + max(4, lpx // 3)
            body_h = y + h - ly
            if self.confirm or (done and self.menu):
                # две кнопки вместо цифр
                gap = max(6, w // 30)
                bw, bh = (w - gap) // 2, min(body_h, max(18, int(body_h * 0.8)))
                by = ly + (body_h - bh) // 2
                a, b = ("reset", "cancel") if self.confirm else ("replay", "new")
                self.btns = {a: (x, by, bw, bh), b: (x + bw + gap, by, bw, bh)}
                for name, (bx, byy, bww, bhh) in self.btns.items():
                    cr.set_source_rgb(*T["st_mid"])
                    cr.rectangle(bx, byy, bww, bhh)
                    cr.fill()
                    cr.set_source_rgb(*T["st_hi"])
                    cr.set_line_width(1)
                    cr.rectangle(bx + 0.5, byy + 0.5, bww - 1, bhh - 1)
                    cr.stroke()
                    px = fit_px(len(name), bww - 8, bhh - 4, top=32)
                    text(cr, name.upper(), bx, byy + (bhh - px) // 2, px, T["on_surface"], center=bww)
                return
            if done and int(time.time()) % 2:
                return                                   # нули мигают
            col = T["primary"] if done else T["accent"]
            if self.paused():
                col = tuple(0.5 * col[i] + 0.5 * T["bg"][i] for i in range(3))
            draw_digits(cr, s, x, ly, w, body_h, col)

    # ── calendar.exe ────────────────────────────────────────────────────────
    class Calendar(Widget, SecondTicker):
        def setup(self):
            self.day = None
            self.start_seconds()

        def cleanup(self):
            self.stop_seconds()

        def second(self):
            d = datetime.date.today()
            if d != self.day:
                self.day = d
                return True
            return False

        def paint(self, cr, x, y, w, h):
            today = datetime.date.today()
            weeks = _cal.Calendar(firstweekday=0).monthdayscalendar(today.year, today.month)
            rh = h / (len(weeks) + 2)
            cw = w / 7
            px = fit_px(3, cw, rh - 2, top=40)           # два знака числа и просвет между столбцами
            head = today.strftime("%B %Y").upper()
            if len(head) * adv(px) > w:
                head = today.strftime("%b %Y").upper()
            hpx = fit_px(len(head), w, rh - 1, top=px + 8)
            text(cr, head, x, y + (rh - hpx) // 2, hpx, T["accent"], center=w)
            names = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
            for i, name in enumerate(names):
                text(cr, name if adv(px) * 2 <= cw - 2 else name[0], x + i * cw, y + rh + (rh - px) // 2,
                     px, T["fg"], 0.45, center=cw)
            for r, week in enumerate(weeks):
                for c, day in enumerate(week):
                    if not day:
                        continue
                    cx, cy = x + c * cw, y + (r + 2) * rh
                    if day == today.day:
                        cr.set_source_rgb(*T["accent"])
                        cr.rectangle(int(cx + 1), int(cy + 1), int(cw - 2), int(rh - 2))
                        cr.fill()
                        col, al = T["bg"], 1.0
                    else:
                        col, al = (T["primary"], 0.85) if c >= 5 else (T["fg"], 0.9)
                    text(cr, str(day), cx, cy + (rh - px) // 2, px, col, al, center=cw)

    # ── screentime.exe ──────────────────────────────────────────────────────
    class ScreenTime(Widget, SecondTicker):
        """Экранное время сегодня: всего и первые программы. Раз в минуту спрашивает
        screentime.py --text (тот же отчёт, что и в терминале)."""

        def setup(self):
            self.total, self.rows = "", []
            self.n = 59
            self.busy = False
            self.start_seconds()

        def cleanup(self):
            self.stop_seconds()

        def second(self):
            self.n += 1
            if self.n % 60 == 0 and not self.busy and not self.mgr.game:
                self.busy = True
                threading.Thread(target=self.fetch, daemon=True).start()
            return False

        def fetch(self):
            import re
            total, rows = "", []
            try:
                out = subprocess.run([sys.executable, os.path.join(ns["HERE"], "screentime.py"), "--text"],
                                     capture_output=True, text=True, timeout=20).stdout
                for l in out.splitlines():
                    m = re.match(r"^Экранное время сегодня.*?:\s*(.+)$", l)
                    if m:
                        total = m.group(1)
                    m = re.match(r"^  (\S.*?)\s{2,}(\S.*?)\s+(\d+)%\s*$", l)
                    if m:
                        rows.append((m.group(1), m.group(2), int(m.group(3))))
            except (OSError, subprocess.SubprocessError):
                pass
            GLib.idle_add(self.got, total, rows)

        def got(self, total, rows):
            self.busy = False
            self.total, self.rows = total, rows
            self.area.queue_draw()
            return False

        def paint(self, cr, x, y, w, h):
            # кегль — по ширине (чтобы влезли «название … время»), строк — сколько войдёт
            # по высоте: выше виджет — длиннее список
            longest = max([len(n) + 2 + len(d) for n, d, _p in self.rows[:8]] + [14])
            px = fit_px(min(longest, 26), w, 32, top=24)
            while px > 8 and (h - px * 1.5) / (px + 8) < min(4, max(1, len(self.rows))):
                px = [s for s in (8, 10, 12, 14, 16, 20, 24) if s < px][-1]
            rh = px + max(6, px // 2 + 3)
            n = max(0, min(len(self.rows), int((h - px * 1.5) // rh)))
            text(cr, "TODAY", x, y, px, T["accent"])
            text(cr, self.total or "…", 0, y, px, T["fg"], right=x + w)
            for i, (name, dur, pct) in enumerate(self.rows[:n]):
                ry = y + px * 1.5 + i * rh
                lw, _ = text(cr, dur, 0, ry, px, T["fg"], 0.7, right=x + w)
                text(cr, name, x, ry, px, T["fg"], width=w - lw - adv(px))
                bar(cr, x, ry + px + 2, w, max(2, px // 5), pct / 100, max(3, px // 2))

    # ── miku.exe ────────────────────────────────────────────────────────────
    class Miku(Widget):
        """Пиксельная Мику с «Пуска» в исходном размере (59×64), увеличенная по пикселям;
        бирюза перекрашена в оттенок обоев, как на панели (pixel_recolor)."""
        BASE = os.path.join(HOME, "Pictures/logo/anime-sprite")

        def setup(self):
            self.frames, self.delays, self.i = [], [], 0
            self.next_id = None
            self.load()

        def theme_changed(self):
            self.load()

        def load(self):
            self.frames, self.delays, self.bufs = [], [], []
            try:
                import numpy as np
                from PIL import Image
                import pixel_recolor
                d = os.path.join(self.BASE, "candidates/c01")
                if not os.path.isdir(os.path.join(d, "frames")):
                    d = os.path.join(self.BASE, "chosen")
                info = json.load(open(os.path.join(d, "info.json")))
                hue = pixel_recolor.target_hue()
                for n in sorted(f for f in os.listdir(os.path.join(d, "frames")) if f.endswith(".png")):
                    im = Image.open(os.path.join(d, "frames", n)).convert("RGBA")
                    im = pixel_recolor.recolor(im, hue, pixel_recolor.miku_select, ref=pixel_recolor.MIKU_REF)
                    a = np.asarray(im.convert("RGBA")).astype(np.float32)
                    al = a[..., 3:4] / 255
                    buf = np.empty(a.shape, dtype=np.uint8)
                    buf[..., 0:3] = (a[..., [2, 1, 0]] * al).astype(np.uint8)   # BGRA, premultiplied
                    buf[..., 3] = a[..., 3].astype(np.uint8)
                    buf = np.ascontiguousarray(buf)
                    s = cairo.ImageSurface.create_for_data(memoryview(buf), cairo.FORMAT_ARGB32,
                                                           im.size[0], im.size[1], im.size[0] * 4)
                    self.bufs.append(buf)          # cairo буфер не копирует — держим сами
                    self.frames.append(s)
                ms = info.get("frame_ms") or 120
                self.delays = (ms if isinstance(ms, list) else [ms]) * (1 if isinstance(ms, list) else len(self.frames))
                self.delays += [120] * (len(self.frames) - len(self.delays))
            except Exception as e:
                print("miku:", e, file=sys.stderr)
                self.frames = []

        def on_start(self):
            if self.frames and not self.next_id:
                self.next_id = GLib.timeout_add(self.delays[self.i], self.step)

        def on_stop(self):
            if self.next_id:
                GLib.source_remove(self.next_id)
                self.next_id = None

        def step(self):
            self.i = (self.i + 1) % len(self.frames)
            if not self.ghosted:
                self.area.queue_draw_area(*self.inner())
            self.next_id = GLib.timeout_add(self.delays[self.i], self.step)
            return False

        def cleanup(self):
            self.on_stop()

        def paint(self, cr, x, y, w, h):
            if not self.frames:
                return
            f = self.frames[self.i % len(self.frames)]
            fw, fh = f.get_width(), f.get_height()
            k = max(1, min(w // fw, h // fh))
            cr.save()
            cr.translate(x + (w - fw * k) // 2, y + (h - fh * k) // 2)
            cr.scale(k, k)
            cr.set_source_surface(f, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint()
            cr.restore()

    # ── fire.exe и life.exe: пиксельные картинки из numpy ───────────────────
    class Grid(Widget):
        """Общая часть: поле клеток CELL×CELL, раскрашенное по таблице цветов."""
        CELL = 4

        def setup(self):
            self.field = None
            self.surf = None

        def resized(self):
            self.field = None
            self.surf = None

        def theme_changed(self):
            self.lut = None
            self.surf = None

        def dims(self):
            _x, _y, w, h = self.inner()
            return max(4, w // self.CELL), max(4, h // self.CELL)

        def dirty_rect(self):
            return self.inner()

        def to_surface(self, idx):
            import numpy as np
            if getattr(self, "lut", None) is None:
                self.lut = self.make_lut()
            img = self.lut[idx]
            img = np.repeat(np.repeat(img, self.CELL, axis=0), self.CELL, axis=1)
            buf = np.ascontiguousarray(img)
            hh, ww = buf.shape[:2]
            s = cairo.ImageSurface.create_for_data(memoryview(buf), cairo.FORMAT_ARGB32, ww, hh, ww * 4)
            self._buf = buf                    # cairo буфер не копирует — держим сами
            return s

        def paint(self, cr, x, y, w, h):
            if self.field is None:
                self.reset()
            if self.surf is None:
                self.surf = self.to_surface(self.cells())
            cr.set_source_surface(self.surf, x + (w - self.surf.get_width()) // 2,
                                  y + h - self.surf.get_height())
            cr.paint()

    class Fire(Grid):
        """Огонь из Doom для PlayStation: жар поднимается снизу и гаснет; палитра — от
        фона через акцент обоев к белому."""
        interval = 50
        LEVELS = 37

        def make_lut(self):
            import numpy as np
            lut = np.zeros((self.LEVELS, 4), dtype=np.uint8)
            stops = [(0.0, T["bg"], 0.0), (0.25, T["accent"], 0.55), (0.6, T["accent"], 1.0),
                     (0.85, T["primary"], 1.0), (1.0, (1.0, 1.0, 1.0), 1.0)]
            for i in range(self.LEVELS):
                t = i / (self.LEVELS - 1)
                for (t0, c0, a0), (t1, c1, a1) in zip(stops, stops[1:]):
                    if t0 <= t <= t1:
                        k = (t - t0) / (t1 - t0)
                        a = a0 + (a1 - a0) * k
                        r, g, b = (c0[j] + (c1[j] - c0[j]) * k for j in range(3))
                        lut[i] = (int(b * a * 255), int(g * a * 255), int(r * a * 255), int(a * 255))
                        break
            return lut

        def reset(self):
            import numpy as np
            w, h = self.dims()
            self.field = np.zeros((h, w), dtype=np.int16)
            self.field[-1, :] = self.LEVELS - 1
            self.rng = np.random.default_rng()
            self.cols = np.arange(w)

        def cells(self):
            return self.field

        def tick(self):
            import numpy as np
            if self.field is None:
                self.reset()
            f = self.field
            hh, ww = f.shape
            # жар у основания гуляет по столбцам — от этого языки разной высоты
            f[-1] = np.clip(f[-1] + self.rng.integers(-4, 5, size=ww), self.LEVELS // 2, self.LEVELS - 1)
            r = self.rng.integers(0, 3, size=(hh - 1, ww))
            src = np.take_along_axis(f[1:], (self.cols[None, :] + r - 1) % ww, axis=1)
            # остывание подобрано под высоту: языки достают примерно до двух третей поля
            mean = self.LEVELS / (0.62 * hh)
            cool = np.floor(self.rng.random((hh - 1, ww)) * 2 * mean + self.rng.random((hh - 1, ww)))
            f[:-1] = np.maximum(src - cool.astype(np.int16), 0)
            self.surf = None
            return True

    class Life(Grid):
        """«Жизнь» Конвея на торе; застоявшееся поле засевается заново."""
        interval = 130
        CELL = 6

        def make_lut(self):
            import numpy as np
            a, p = T["accent"], T["primary"]
            return np.array([(0, 0, 0, 0),
                             (int(a[2] * 255), int(a[1] * 255), int(a[0] * 255), 255),
                             (int(p[2] * 255), int(p[1] * 255), int(p[0] * 255), 255)], dtype=np.uint8)

        def reset(self):
            import numpy as np
            w, h = self.dims()
            self.rng = np.random.default_rng()
            self.field = (self.rng.random((h, w)) < 0.22).astype(np.int8)
            self.born = np.zeros((h, w), dtype=np.int8)
            self.hist = []

        def cells(self):
            return self.field + self.born          # только что родившиеся — светлее

        def tick(self):
            import numpy as np
            if self.field is None:
                self.reset()
            f = self.field
            n = sum(np.roll(np.roll(f, dy, 0), dx, 1)
                    for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0))
            new = ((n == 3) | ((f == 1) & (n == 2))).astype(np.int8)
            self.born = ((new == 1) & (f == 0)).astype(np.int8)
            self.field = new
            self.hist = (self.hist + [int(new.sum())])[-40:]
            if len(self.hist) == 40 and (len(set(self.hist[-12:])) <= 2 or self.hist[-1] < new.size * 0.02):
                self.reset()
            self.surf = None
            return True

    # ── weather.exe ─────────────────────────────────────────────────────────
    ICONS = {
        "sun": (".....##.....", ".#...##...#.", "..#......#..", "....####....", "...######...",
                "##.######.##", "##.######.##", "...######...", "....####....", "..#......#..",
                ".#...##...#.", ".....##....."),
        "partly": ("...#........", ".#.#.#......", "..###.......", "#####.###...", "..###.#####.",
                   ".#.########.", "..##########", ".###########", "############", "############",
                   ".##########.", "............"),
        "cloud": ("............", "............", ".....###....", "....#####...", "..#########.",
                  ".###########", "############", "############", ".##########.", "............",
                  "............", "............"),
        "rain": (".....###....", "....#####...", "..#########.", ".###########", "############",
                 "############", ".##########.", "............", "..#..#..#...", ".#..#..#....",
                 "............", "..#..#..#..."),
        "snow": (".....###....", "....#####...", "..#########.", ".###########", "############",
                 "############", ".##########.", "............", "..#...#...#.", "....#...#...",
                 "..#...#...#.", "............"),
        "storm": (".....###....", "....#####...", "..#########.", ".###########", "############",
                  "############", ".##########.", ".....##.....", "....##......", "...####.....",
                  ".....##.....", "....#......."),
        "fog": ("............", "............", ".##########.", "............", "############",
                "............", ".##########.", "............", "############", "............",
                "..########..", "............"),
    }

    def icon_for(code):
        code = int(code)
        if code == 113:
            return "sun"
        if code == 116:
            return "partly"
        if code in (119, 122):
            return "cloud"
        if code in (143, 248, 260):
            return "fog"
        if code in (200, 386, 389, 392, 395):
            return "storm"
        if code in (179, 182, 185, 227, 230, 317, 320, 323, 326, 329, 332, 335, 338, 350,
                    362, 365, 368, 371, 374, 377):
            return "snow"
        return "rain"

    class Weather(Widget, SecondTicker):
        """Погода с wttr.in (без ключа). Город — opts.city; не задан — служба определяет
        его по IP (с VPN будет чужой город — тогда задать: set ИМЯ city=Almaty).
        Обновление раз в полчаса; нет сети — показывается последнее сохранённое.

        Живой фон по погоде (06.10.2026, Просьба: «хотелось бы, чтобы он реагировал на погодные
        условия»): пиксели цвета акцента под данными — дождь косыми каплями, снег хлопьями,
        гроза — дождь со вспышками, облака и туман плывут, ясно — мерцающие блики днём и
        звёзды ночью (по восходу/закату из прогноза). Кадры: осадки ~8 в секунду, прочее ~3;
        как у всех виджетов — замирает под окнами и в игре. Выключить: opts fx=false."""
        FILE = os.path.join(CACHE, "weather.json")
        interval = 125

        def setup(self):
            self.data = None
            self.n = 0
            self.busy = False
            self.fx_t = 0
            self.fx_parts = None
            self.fx_size = None
            self.flash = 0
            try:
                self.data = json.load(open(self.FILE))
            except (OSError, ValueError):
                pass
            self.fetch_soon()
            self.start_seconds()

        def cleanup(self):
            self.stop_seconds()

        def second(self):
            self.n += 1
            if self.n % 1800 == 0:
                self.fetch_soon()
            return False

        def fetch_soon(self):
            if not self.busy and not self.mgr.game:
                self.busy = True
                threading.Thread(target=self.fetch, daemon=True).start()

        def fetch(self):
            data = None
            try:
                import urllib.parse
                import urllib.request
                city = urllib.parse.quote(str(self.opts.get("city", "")))
                req = urllib.request.Request("https://wttr.in/%s?format=j1" % city,
                                             headers={"User-Agent": "curl/8"})
                with urllib.request.urlopen(req, timeout=12) as r:
                    d = json.load(r)
                c, a = d["current_condition"][0], d["nearest_area"][0]
                data = {"at": time.time(), "city": a["areaName"][0]["value"],
                        "temp": int(c["temp_C"]), "feels": int(c["FeelsLikeC"]),
                        "code": int(c["weatherCode"]), "desc": c["weatherDesc"][0]["value"],
                        "wind": int(c["windspeedKmph"]), "hum": int(c["humidity"]),
                        "days": [{"date": w["date"], "min": int(w["mintempC"]), "max": int(w["maxtempC"]),
                                  "code": int(w["hourly"][4]["weatherCode"])} for w in d["weather"][:3]]}
                try:
                    astro = d["weather"][0]["astronomy"][0]
                    data["sun"] = [astro["sunrise"], astro["sunset"]]
                except (KeyError, IndexError, TypeError):
                    pass
                os.makedirs(CACHE, exist_ok=True)
                with open(self.FILE + ".tmp", "w") as f:
                    json.dump(data, f)
                os.replace(self.FILE + ".tmp", self.FILE)
            except Exception as e:
                print("weather:", e, file=sys.stderr)
            GLib.idle_add(self.got, data)

        def got(self, data):
            self.busy = False
            if data:
                self.data = data
                self.area.queue_draw()
            return False

        # ── живой фон ─────────────────────────────────────────────────────
        def fx_kind(self):
            d = self.data
            if not d or not self.opts.get("fx", True):
                return None
            kind = icon_for(d["code"])
            if kind == "sun" or kind == "partly":
                night = self.is_night()
                if kind == "sun":
                    return "night" if night else "sun"
                return "cloud-night" if night else "cloud"
            return kind                     # cloud, fog, storm, snow, rain

        def is_night(self):
            now = datetime.datetime.now()
            try:
                rise, sset = (datetime.datetime.strptime(v, "%I:%M %p").time() for v in self.data.get("sun") or ())
                return not (rise <= now.time() <= sset)
            except (ValueError, TypeError):
                return now.hour < 6 or now.hour >= 20

        def fx_init(self, w, h, kind):
            import random
            rnd = random.Random(7)
            area = max(1, w * h)
            parts = []
            if kind in ("rain", "storm"):
                for _ in range(int(area / 900)):
                    parts.append([rnd.random() * w, rnd.random() * h, 0.8 + rnd.random() * 0.6])
            elif kind == "snow":
                for _ in range(int(area / 1100)):
                    parts.append([rnd.random() * w, rnd.random() * h, rnd.random() * 6.28, 0.3 + rnd.random() * 0.4])
            elif kind in ("night", "cloud-night"):
                for _ in range(max(6, int(area / 2600))):
                    parts.append([rnd.random() * w, rnd.random() * h * 0.8, rnd.random() * 6.28, 0.5 + rnd.random()])
            elif kind == "sun":
                for _ in range(max(4, int(area / 4500))):
                    parts.append([rnd.random() * w, rnd.random() * h, rnd.random() * 6.28, 0.6 + rnd.random() * 0.8])
            elif kind in ("cloud", "fog"):
                n = 3 if kind == "cloud" else 4
                for i in range(n):
                    parts.append([rnd.random() * w, (i + 0.5) * h / n + (rnd.random() - 0.5) * h * 0.15,
                                  0.15 + rnd.random() * 0.2, 0.7 + rnd.random() * 0.6])
            self.fx_parts, self.fx_size, self.fx_for = parts, (w, h), kind

        def tick(self):
            kind = self.fx_kind()
            if not kind:
                return False
            self.fx_t += 1
            fast = kind in ("rain", "storm", "snow")
            if kind == "storm":
                import random
                if self.flash:
                    self.flash -= 1
                elif random.random() < 1 / 70:
                    self.flash = 2
            return fast or self.fx_t % 3 == 0 or self.flash > 0

        def paint_fx(self, cr, x, y, w, h):
            kind = self.fx_kind()
            if not kind:
                return
            if self.fx_size != (w, h) or getattr(self, "fx_for", None) != kind:
                self.fx_init(w, h, kind)
            import math
            k = max(2, int(round(min(w, h) / 55)))          # «пиксель» эффекта
            r, g, b = T["accent"]
            t = self.fx_t
            snap = lambda v: int(v // k) * k
            cr.save()
            cr.rectangle(x, y, w, h)
            cr.clip()
            if self.flash:
                cr.set_source_rgba(1, 1, 1, 0.10 * self.flash)
                cr.paint()
            for p in self.fx_parts:
                if kind in ("rain", "storm"):
                    p[1] = (p[1] + p[2] * k * 2.2) % (h + 3 * k)
                    p[0] = (p[0] - p[2] * k * 0.6) % w
                    cr.set_source_rgba(r, g, b, 0.30)
                    px_, py_ = snap(p[0]), snap(p[1]) - 2 * k
                    cr.rectangle(x + px_, y + py_, k, k)
                    cr.rectangle(x + px_ + k * 0.5 // 1, y + py_ + k, k, k)
                    cr.fill()
                elif kind == "snow":
                    p[1] = (p[1] + p[3] * k) % (h + k)
                    p[0] = (p[0] + math.sin(t * 0.08 + p[2]) * k * 0.4) % w
                    cr.set_source_rgba(r, g, b, 0.38)
                    cr.rectangle(x + snap(p[0]), y + snap(p[1]), k, k)
                    cr.fill()
                elif kind in ("night", "cloud-night", "sun"):
                    a = 0.5 + 0.5 * math.sin(t * 0.07 * p[3] + p[2])
                    cr.set_source_rgba(r, g, b, (0.10 + 0.32 * a) if kind != "sun" else (0.06 + 0.22 * a))
                    sx, sy = x + snap(p[0]), y + snap(p[1])
                    cr.rectangle(sx, sy, k, k)
                    if a > 0.75:                                  # яркая — крестиком
                        cr.rectangle(sx - k, sy, k, k)
                        cr.rectangle(sx + k, sy, k, k)
                        cr.rectangle(sx, sy - k, k, k)
                        cr.rectangle(sx, sy + k, k, k)
                    cr.fill()
            if kind in ("cloud", "cloud-night", "fog"):
                bands = [p for p in self.fx_parts if len(p) == 4 and kind != "cloud-night"] \
                    if kind != "cloud-night" else []
                if kind == "cloud-night" and not getattr(self, "cn_parts", None):
                    import random
                    rnd = random.Random(3)
                    self.cn_parts = [[rnd.random() * w, (i + 0.5) * h / 3, 0.15 + rnd.random() * 0.2,
                                      0.7 + rnd.random() * 0.6] for i in range(3)]
                if kind == "cloud-night":
                    bands = self.cn_parts
                for p in bands:
                    p[0] = (p[0] + p[2] * k * 0.5) % (w + w * 0.5)
                    cw = w * 0.35 * p[3]
                    cx0 = x + snap(p[0] - w * 0.4)
                    cy0 = y + snap(p[1])
                    cr.set_source_rgba(r, g, b, 0.12 if kind == "fog" else 0.16)
                    if kind == "fog":
                        for i in range(0, int(cw * 1.6), 2 * k):
                            cr.rectangle(cx0 + i, cy0, k * 1.5 // 1 + k, k)
                    else:
                        # облако из пиксельных ступенек: низ шире, верх — две «шапки»
                        cr.rectangle(cx0, cy0, snap(cw), 2 * k)
                        cr.rectangle(cx0 + snap(cw * 0.15), cy0 - 2 * k, snap(cw * 0.45), 2 * k)
                        cr.rectangle(cx0 + snap(cw * 0.5), cy0 - 3 * k, snap(cw * 0.3), 3 * k)
                    cr.fill()
            cr.restore()

        def paint(self, cr, x, y, w, h):
            d = self.data
            if not d:
                px = fit_px(11, w, h * 0.5, top=16)
                text(cr, "no data yet", x, y + (h - px) // 2, px, T["fg"], 0.5, center=w)
                return
            try:
                self.paint_fx(cr, x, y, w, h)
            except Exception as e:
                print("weather fx:", e, file=sys.stderr)
            dbm = lambda code: [[c == "#" for c in r] for r in ICONS[icon_for(code)]]
            days = d.get("days") or []
            # прогноз снизу — если хватает и высоты, и ширины на три столбца
            fore = bool(days) and h >= 96 and w >= 190
            fpx = fit_px(7, w / max(1, len(days)) - 16, h * 0.14, top=24) if fore else 0
            top = h - (fpx + max(6, fpx // 2) if fore else 0)
            tiny = w < 150 or top < 46                    # совсем тесно: значок и температура
            k = max(1, int(min(top, w * (0.42 if tiny else 0.24)) // 12))
            cr.set_source_rgb(*T["accent"])
            # значок — напротив текста: в высоком виджете текст сверху, значок тоже
            block = top if tiny else min(top, max(12 * k, top * 0.5 + 44))
            ns["draw_bitmap"](cr, dbm(d["code"]), x, y + int((block - 12 * k) // 2), k, k)
            tx = x + 12 * k + max(6, k * 2)
            tw = x + w - tx
            temp = "%d°" % d["temp"]
            if tiny:
                big = fit_px(len(temp), tw, top, top=64)
                text(cr, temp, tx, y + (top - big) // 2, big, T["accent"])
            else:
                big = fit_px(len(temp), tw * 0.5, top * 0.5, top=64)
                lw, _ = text(cr, temp, tx, y, big, T["accent"])
                rest = tw - lw - adv(big) * 0.5
                cpx = fit_px(len(d["city"]), rest, big, top=24)
                if rest >= adv(cpx) * 4:
                    text(cr, d["city"], tx + lw + adv(big) * 0.5, y, cpx, T["fg"], 0.7, width=rest)
                left = top - big - 2
                feels = "feels %d° · %d km/h · %d%%" % (d["feels"], d["wind"], d["hum"])
                two = left >= 22                           # две строки под температурой или одна
                spx = fit_px(len(d["desc"]), tw, left / (2.15 if two else 1.1), top=24)
                text(cr, d["desc"], tx, y + big + 2, spx, T["fg"], width=tw)
                if two:
                    for cand in (feels, "feels %d° · %d%%" % (d["feels"], d["hum"]), "feels %d°" % d["feels"]):
                        qpx = fit_px(len(cand), tw, spx, top=spx)
                        if len(cand) * adv(qpx) <= tw and qpx >= max(8, spx * 0.7):
                            break
                    text(cr, cand, tx, y + big + spx + 5, qpx, T["fg"], 0.6, width=tw)
            if fore:
                cw = w / len(days)
                by = y + h - fpx - 1
                kk = max(1, fpx // 12)
                # одинаково для всех дней: «FR 8/18», а если хоть один не входит — «FR 18»
                roomy = all(len("XX %d/%d" % (dd["min"], dd["max"])) * adv(fpx) <= cw - 12 * kk - 8 for dd in days)
                for i, day in enumerate(days):
                    try:
                        name = datetime.date.fromisoformat(day["date"]).strftime("%a").upper()[:2]
                    except ValueError:
                        name = "--"
                    sx = x + i * cw
                    cr.set_source_rgba(*T["accent"], 0.9)
                    ns["draw_bitmap"](cr, dbm(day["code"]), sx, by + (fpx - 12 * kk) // 2, kk, kk)
                    lab = "%s %d/%d" % (name, day["min"], day["max"]) if roomy else "%s %d" % (name, day["max"])
                    text(cr, lab, sx + 12 * kk + 5, by, fpx, T["fg"], 0.8, width=cw - 12 * kk - 6)

    # ── visualizer.exe: автоподстройка под громкость (05.10.2026) ──────────
    # Просьба: «когда звук приложения тихий, виджет как будто не реагирует; cava в
    # терминале реагировала на любой звук». Причина: с 04.10 cava виджета не
    # перезапускается, а её autosens после громкого звука (видео, уведомление)
    # поднимает чувствительность лишь на ~5 %/с — тихий звук (−40 дБ) 1–2 минуты
    # оставался столбиками в 1 % высоты. Свежая cava (терминал) подстраивается за 1 с.
    # Замер на синтетике через fifo: громко 5 с → тихо: 1 % → 4 % за 25 с.
    # Сама cava — в desktop_widgets.py (класс Cava); здесь — только подкласс:
    # сырой вывод точнее (0…65535 вместо 0…1000) и своё усиление по скользящему пику
    # поверх autosens cava: пик — максимум за WINDOW с (держится между ударами),
    # вверх сразу, вниз вдвое за HALF с; усиление ≥ 1 — свежую cava не трогает.
    # Громко → тихо (−40 дБ): нормальная высота через ~3 с (было — минуты).
    Cava = ns.get("Cava")
    if Cava is not None:
        import collections

        class CavaAGC(Cava):
            RANGE = 65535              # ascii_max_range: тихие значения не ступеньками
            WINDOW = 1.0               # с: пик — максимум за это время
            HALF = 0.35                # с: за сколько пик спадает вдвое, когда окно опустело
            GMAX = 100.0               # усиление не больше (тишина и шум не раздуваются)
            FILL = 0.9                 # пик — на эту долю высоты

            def agc(self, raw):
                """Сырые столбики cava → те же, усиленные под нынешнюю громкость."""
                now = time.monotonic()
                top = max(raw) if raw else 0
                tops = getattr(self, "agc_tops", None)
                if tops is None:
                    tops = self.agc_tops = collections.deque()
                tops.append((now, top))
                while tops and tops[0][0] < now - self.WINDOW:
                    tops.popleft()
                target = float(max(t for _, t in tops))
                last = getattr(self, "agc_t", None)
                peak = getattr(self, "agc_peak", 0.0)
                if last is not None:
                    peak *= 0.5 ** ((now - last) / self.HALF)
                peak = max(peak, target)
                self.agc_t, self.agc_peak = now, peak
                gain = min(self.GMAX, max(1.0, self.FILL * self.RANGE / max(peak, self.RANGE / 1000)))
                if gain == 1.0:
                    return raw
                R = self.RANGE
                return [min(R, int(v * gain)) for v in raw]

            def reader(self, proc):
                for line in proc.stdout:
                    try:
                        self.vals = self.agc([int(x) for x in line.split(b";") if x.strip()])
                    except ValueError:
                        pass
                if proc is self.proc:      # как у Cava.reader: сказать, почему cava вышел
                    err = (proc.stderr.read() or b"").decode(errors="replace").strip()
                    print("%s: cava завершился: %s" % (self.spec.get("name"), err[:200] or "без сообщения"),
                          file=sys.stderr)

        ns["CLASSES"]["cava"] = CavaAGC

    ns["CLASSES"]["weather"] = Weather
    ns["CLASSES"].update({"sysmon": SysMon, "banner": Banner, "player": Player,
                          "playermini": PlayerMini, "timer": Timer,
                          "calendar": Calendar, "screentime": ScreenTime,
                          "miku": Miku, "fire": Fire, "life": Life})
