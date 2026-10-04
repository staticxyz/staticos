#!/usr/bin/env python3
"""Счётчик экранного времени: сколько секунд какая программа была в фокусе. 30.09.2026.

    screentime_daemon.py        запустить (второй экземпляр молча выходит)

пользователь захотел «Экранное время» как в Noctalia. Сама Noctalia считает его
внутри своей оболочки, а у нас оболочка — waybar, поэтому счётчик свой и
отдельный: живёт весь сеанс, окно показывает screentime.py.

Как считает
-----------
Следит за `niri msg -j event-stream` и знает, какое окно в фокусе. Время
начисляется приложению (app_id) по часам: ~/.local/share/jarvis/screentime/
ГГГГ-ММ-ДД.json, вид {"apps": {app_id: сек}, "hours": {"13": {app_id: сек}},
"details": {app_id: {что: сек}}}.

Подробности (30.09.2026, просьба: «kitty 1 ч 10 мин — а что именно в kitty?
Статистика должна быть точнее»): у терминалов — какая программа была на
экране (по заголовку окна: nvim, tmatrix, оболочка…), у браузеров —
сайт (по заголовку вкладки). Разбор заголовка — detail_of(). Не больше
MAX_DETAILS подписей на программу в день, остальное — «Другое».
На диск — раз в 30 с и при выходе (SIGTERM/SIGINT); SIGHUP — записать сразу
(так делает окно перед чтением, чтобы показать свежие цифры).

Процессор почти не тратит: спит в select() на потоке событий niri и
просыпается ещё раз в 10 с по таймеру — проверить блокировку и сбросить файл.

Что НЕ считается
----------------
* окна дашборда (app_id «dash-*»): они стоят на своём столе постоянно и
  фокус получают случайно — это не «сидел в программе»;
* нет окна в фокусе (пустой стол);
* экран заблокирован: запущен hyprlock (или swaylock/gtklock/waylock) этого
  сеанса — проверка раз в 10 с по /proc, как в scripts/lockscreen;
* простой. Свой маленький hypridle (второй экземпляр, только с одним
  слушателем) шлёт этому процессу SIGUSR1 после IDLE_SEC без ввода и SIGUSR2
  при возврате. Эти IDLE_SEC уже успели начислиться — их вычитаем задним
  числом (держим последние минуты начислений в памяти). Инхибиторы Wayland
  (видео в браузере, mpv) hypridle уважает: смотреть фильм без мыши — это
  экранное время. А systemd-инхибитор Savage Mode («24/7 mode», --what=idle)
  игнорируется: он про сон, не про присутствие человека.
* сон машины: время меряется по CLOCK_MONOTONIC, он во сне стоит.

Хранится 60 дней, старые файлы удаляются при запуске и при смене суток.
"""
import collections
import fcntl
import json
import os
import selectors
import signal
import subprocess
import sys
import time
import ctypes

DATA = os.path.expanduser("~/.local/share/jarvis/screentime")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
LOCK = os.path.join(RUNTIME, "jarvis-screentime.lock")
IDLE_CONF = os.path.join(RUNTIME, "jarvis-screentime-hypridle.conf")

IDLE_SEC = 300          # простой — столько же, сколько до блокировки (hypridle.conf)
FLUSH_SEC = 30
TICK_SEC = 10
KEEP_DAYS = 60
MAX_STEP = 60           # больше за один шаг не начисляем: страховка от скачков часов
LOCKERS = {"hyprlock", "swaylock", "gtklock", "waylock"}
PY_LOCKERS = (b"jarvis_lock.py",)   # свой экран блокировки — это python3, по comm не узнать
MAX_DETAILS = 40

TERMINALS = {"kitty", "foot", "Alacritty", "com.mitchellh.ghostty", "org.wezfurlong.wezterm"}
BROWSERS = {"zen": "Zen Browser", "librewolf": "LibreWolf", "firefox": "Mozilla Firefox",
            "helium": "Helium", "chromium": "Chromium", "brave-browser": "Brave"}
# Сайты, которые узнаём по слову в заголовке, где бы оно ни стояло.
SITES = ["YouTube", "GitHub", "Telegram", "Reddit", "Twitch",
         "Gmail", "Google", "Wikipedia", "Википедия", "Яндекс", "Kaspi", "hh.ru", "Хабр", "Habr",
         "Stack Overflow", "Instagram", "ВКонтакте", "VK", "Steam", "Discord", "Netflix",
         "Кинопоиск", "Notion", "Obsidian", "LeetCode", "Arch Wiki", "ArchWiki", "AUR"]
SHELLS = {"fish", "zsh", "bash", "sh"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def detail_of(app, title):
    """Что именно было на экране у программы: для терминала — программа
    в нём, для браузера — сайт. Для остальных — None (без подробностей)."""
    title = (title or "").strip()
    if not title:
        return None
    if app in TERMINALS:
        words = title.split()
        while words and words[0] in ("sudo", "doas", "exec", "nohup", "env"):
            words = words[1:]
        if not words:
            return "Оболочка"
        w = words[0]
        if w.startswith(("~", "/", ".")) or ":" in w or w in SHELLS or "@" in w:
            return "Оболочка"
        return os.path.basename(w)[:24] or "Оболочка"
    if app in BROWSERS:
        suffix = BROWSERS[app]
        for sep in (" — ", " – ", " - "):
            if title.endswith(sep + suffix):
                title = title[: -len(sep + suffix)]
        title = title.strip()
        if not title or title == suffix:
            return "Новая вкладка"
        if title == "Picture-in-Picture":
            return "Картинка в картинке"
        low = title.lower()
        for site in SITES:
            if site.lower() in low:
                return site
        for sep in (" — ", " – ", " - ", " | ", " · "):
            if sep in title:
                last = title.rsplit(sep, 1)[1].strip()
                if 0 < len(last) <= 28:
                    return last
        return "Другие страницы"
    return None


# ── хранение ──────────────────────────────────────────────────────────────

class Store:
    """Дни в памяти, запись на диск атомарно (tmp + rename): окно может
    читать файл в любой момент и не должно застать его наполовину записанным."""

    def __init__(self):
        os.makedirs(DATA, exist_ok=True)
        self.days = {}
        self.dirty = set()

    def path(self, day):
        return os.path.join(DATA, day + ".json")

    def day(self, day):
        if day not in self.days:
            d = {"apps": {}, "hours": {}, "details": {}}
            try:
                with open(self.path(day), encoding="utf-8") as f:
                    raw = json.load(f)
                d["apps"] = {k: float(v) for k, v in raw.get("apps", {}).items()}
                d["hours"] = {h: {k: float(v) for k, v in m.items()}
                              for h, m in raw.get("hours", {}).items()}
                d["details"] = {a: {k: float(v) for k, v in m.items()}
                                for a, m in raw.get("details", {}).items()}
            except (OSError, ValueError, AttributeError):
                pass
            self.days[day] = d
        return self.days[day]

    def add(self, app, t0, t1, sign=1, detail=None):
        """Начислить (или при sign=-1 вычесть) отрезок [t0, t1) настенного
        времени, разрезав его по границам часов — день и час берутся местные."""
        t = t0
        while t < t1 - 1e-6:
            lt = time.localtime(t)
            hour_end = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, 0, 0, 0, 0, -1)) + 3600
            end = min(t1, hour_end)
            sec = (end - t) * sign
            day = time.strftime("%Y-%m-%d", lt)
            d = self.day(day)
            h = d["hours"].setdefault(str(lt.tm_hour), {})
            for m in (d["apps"], h):
                v = m.get(app, 0.0) + sec
                if v > 0.05:
                    m[app] = v
                else:
                    m.pop(app, None)
            if not h:
                d["hours"].pop(str(lt.tm_hour), None)
            if detail:
                m = d["details"].setdefault(app, {})
                if detail not in m and len(m) >= MAX_DETAILS:
                    detail = "Другое"
                v = m.get(detail, 0.0) + sec
                if v > 0.05:
                    m[detail] = v
                else:
                    m.pop(detail, None)
                if not m:
                    d["details"].pop(app, None)
            self.dirty.add(day)
            t = end

    def flush(self):
        for day in list(self.dirty):
            d = self.days[day]
            out = {"apps": {k: round(v, 1) for k, v in sorted(d["apps"].items(), key=lambda x: -x[1])},
                   "hours": {h: {k: round(v, 1) for k, v in m.items()}
                             for h, m in sorted(d["hours"].items(), key=lambda x: int(x[0]))},
                   "details": {a: {k: round(v, 1) for k, v in sorted(m.items(), key=lambda x: -x[1])}
                               for a, m in d["details"].items()}}
            tmp = self.path(day) + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
                os.replace(tmp, self.path(day))
            except OSError as e:
                log("запись не удалась:", e)
                continue
            self.dirty.discard(day)
        # В памяти держим только сегодня и вчера: откат простоя дальше не заглядывает.
        keep = {time.strftime("%Y-%m-%d"), time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))}
        for day in list(self.days):
            if day not in keep and day not in self.dirty:
                del self.days[day]

    def prune(self):
        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - KEEP_DAYS * 86400))
        for name in os.listdir(DATA):
            if name.endswith(".json") and len(name) == 15 and name[:10] < cutoff:
                try:
                    os.remove(os.path.join(DATA, name))
                except OSError:
                    pass


# ── блокировка экрана ─────────────────────────────────────────────────────

def screen_locked():
    """Запущен ли экран блокировки ЭТОГО сеанса. Осиротевший hyprlock прошлого
    сеанса niri не в счёт (так уже ломалось: см. комментарий в scripts/lockscreen)."""
    wl = ("WAYLAND_DISPLAY=" + os.environ.get("WAYLAND_DISPLAY", "")).encode()
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            with open("/proc/%s/comm" % p, "rb") as f:
                comm = f.read().strip().decode(errors="replace")
            if comm not in LOCKERS:
                if not comm.startswith("python"):
                    continue
                with open("/proc/%s/cmdline" % p, "rb") as f:
                    argv = f.read().split(b"\0")
                if not any(os.path.basename(a) in PY_LOCKERS for a in argv[1:3]):
                    continue
            with open("/proc/%s/environ" % p, "rb") as f:
                if wl in f.read().split(b"\0"):
                    return True
        except OSError:
            continue
    return False


# ── трекер ────────────────────────────────────────────────────────────────

class Tracker:
    def __init__(self, store):
        self.store = store
        self.windows = {}           # id -> app_id
        self.titles = {}            # id -> заголовок
        self.focused = None         # id окна в фокусе
        self.idle = False
        self.locked = False
        self.last_mono = time.monotonic()
        # Недавние начисления (t0, t1, app, detail) — для отката после простоя.
        self.recent = collections.deque()

    def current_app(self):
        if self.idle or self.locked or self.focused is None:
            return None
        app = self.windows.get(self.focused)
        if app is None or app.startswith("dash-"):
            return None
        return app or "unknown"

    def current_detail(self, app):
        return detail_of(app, self.titles.get(self.focused, ""))

    def commit(self):
        """Начислить время с прошлого шага приложению, которое было в фокусе.
        Зовётся ПЕРЕД любым изменением состояния — так каждый отрезок уходит
        тому, кто был в фокусе в течение этого отрезка."""
        now_m = time.monotonic()
        dt = now_m - self.last_mono
        self.last_mono = now_m
        app = self.current_app()
        if app is None or dt <= 0:
            return
        dt = min(dt, MAX_STEP)
        t1 = time.time()
        t0 = t1 - dt
        det = self.current_detail(app)
        self.store.add(app, t0, t1, detail=det)
        last = self.recent[-1] if self.recent else None
        if last and last[2] == app and last[3] == det and abs(last[1] - t0) < 1:
            self.recent[-1] = (last[0], t1, app, det)
        else:
            self.recent.append((t0, t1, app, det))
        horizon = t1 - IDLE_SEC - 120
        while self.recent and self.recent[0][1] < horizon:
            self.recent.popleft()

    def rollback(self, since):
        """Вычесть всё начисленное после момента `since` (начало простоя)."""
        kept = collections.deque()
        for t0, t1, app, det in self.recent:
            if t1 <= since:
                kept.append((t0, t1, app, det))
                continue
            cut = max(t0, since)
            self.store.add(app, cut, t1, sign=-1, detail=det)
            if cut > t0:
                kept.append((t0, cut, app, det))
        self.recent = kept

    # события niri
    def event(self, ev):
        if "WindowsChanged" in ev:
            self.commit()
            ws = ev["WindowsChanged"]["windows"]
            self.windows = {w["id"]: w.get("app_id") or "" for w in ws}
            self.titles = {w["id"]: w.get("title") or "" for w in ws}
            self.focused = next((w["id"] for w in ws if w.get("is_focused")), None)
        elif "WindowOpenedOrChanged" in ev:
            w = ev["WindowOpenedOrChanged"]["window"]
            if w.get("is_focused") or self.windows.get(w["id"]) != (w.get("app_id") or "") \
                    or (w["id"] == self.focused and self.titles.get(w["id"]) != (w.get("title") or "")):
                self.commit()
            self.windows[w["id"]] = w.get("app_id") or ""
            self.titles[w["id"]] = w.get("title") or ""
            if w.get("is_focused"):
                self.focused = w["id"]
        elif "WindowClosed" in ev:
            self.commit()
            wid = ev["WindowClosed"]["id"]
            self.windows.pop(wid, None)
            self.titles.pop(wid, None)
            if self.focused == wid:
                self.focused = None
        elif "WindowFocusChanged" in ev:
            self.commit()
            self.focused = ev["WindowFocusChanged"]["id"]

    def set_idle(self, idle):
        self.commit()
        if idle and not self.idle:
            # Последние IDLE_SEC человек уже не смотрел на экран — вернуть их.
            self.rollback(time.time() - IDLE_SEC)
            log("простой: откат %d с" % IDLE_SEC)
        elif not idle and self.idle:
            log("снова за компьютером")
        self.idle = idle

    def check_lock(self):
        locked = screen_locked()
        if locked != self.locked:
            self.commit()
            self.locked = locked
            log("экран заблокирован" if locked else "экран разблокирован")


# ── внешние процессы ──────────────────────────────────────────────────────

_libc = ctypes.CDLL("libc.so.6", use_errno=True)


def _die_with_parent():
    # PR_SET_PDEATHSIG: потомки умирают вместе со счётчиком, даже от kill -9.
    _libc.prctl(1, signal.SIGTERM)


def start_idle_watch():
    """Второй hypridle только с одним слушателем — сигналы этому процессу.

    Основной hypridle (из niri autostart) не трогаем: у него свои ступени и
    ignore_inhibit, а здесь нужно ровно «человек ушёл / вернулся»."""
    pid = os.getpid()
    conf = """# Создан screentime_daemon.py, перезаписывается при каждом запуске.
general {
    ignore_dbus_inhibit = true      # D-Bus ScreenSaver держит сам niri и переводит в свои инхибиторы
    ignore_systemd_inhibit = true   # Savage Mode держит --what=idle ради сна, не ради присутствия
    ignore_wayland_inhibit = false  # видео в браузере/mpv — это экранное время
}
listener {
    timeout = %d
    on-timeout = kill -USR1 %d
    on-resume = kill -USR2 %d
}
""" % (IDLE_SEC, pid, pid)
    with open(IDLE_CONF, "w", encoding="utf-8") as f:
        f.write(conf)
    try:
        return subprocess.Popen(["hypridle", "-q", "-c", IDLE_CONF], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)
    except OSError as e:
        log("hypridle не запустился, простой не отслеживается:", e)
        return None


def start_stream():
    return subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)


def main():
    lock = open(LOCK, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)             # уже работает
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()

    store = Store()
    store.prune()
    tr = Tracker(store)

    # Сигналы — через self-pipe в тот же select: обработчик Python может
    # сработать посреди начисления, а так всё идёт по очереди в главном цикле.
    rfd, wfd = os.pipe()
    os.set_blocking(wfd, False)
    os.set_blocking(rfd, False)
    signal.set_wakeup_fd(wfd)
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGUSR1, signal.SIGUSR2):
        signal.signal(s, lambda *_: None)

    sel = selectors.DefaultSelector()
    sel.register(rfd, selectors.EVENT_READ, "sig")

    idle_proc = start_idle_watch()
    stream, buf, backoff = None, b"", 1
    next_flush = time.monotonic() + FLUSH_SEC
    next_tick = 0.0
    next_retry = 0.0
    day = time.strftime("%Y-%m-%d")
    log("старт, pid", os.getpid())

    while True:
        now = time.monotonic()
        if stream is None and now >= next_retry:
            sock = os.environ.get("NIRI_SOCKET")
            if sock and not os.path.exists(sock):
                # Сокета нашего niri больше нет — сеанс закончился. Уйти, а не
                # висеть сиротой: иначе замок остался бы за нами, и счётчик
                # нового сеанса молча не запустился бы (у niri новый сокет).
                tr.commit()
                store.flush()
                log("niri этого сеанса больше нет, выход")
                return
            try:
                stream = start_stream()
                os.set_blocking(stream.stdout.fileno(), False)
                sel.register(stream.stdout, selectors.EVENT_READ, "niri")
                buf = b""
            except OSError:
                stream = None
                next_retry = now + backoff
                backoff = min(backoff * 2, 30)

        timeout = max(0.0, min(next_flush, next_tick, next_retry if stream is None else 1e18) - now)
        for key, _ in sel.select(timeout):
            if key.data == "sig":
                try:
                    sigs = os.read(rfd, 64)
                except BlockingIOError:
                    sigs = b""
                for s in sigs:
                    if s in (signal.SIGTERM, signal.SIGINT):
                        tr.commit()
                        store.flush()
                        if idle_proc:
                            idle_proc.terminate()
                        if stream:
                            stream.terminate()
                        log("выход")
                        return
                    if s == signal.SIGUSR1:
                        tr.set_idle(True)
                    elif s == signal.SIGUSR2:
                        tr.set_idle(False)
                    elif s == signal.SIGHUP:
                        tr.commit()
                        store.flush()
            else:
                try:
                    chunk = os.read(stream.stdout.fileno(), 65536)
                except (BlockingIOError, InterruptedError):
                    chunk = None
                except OSError:
                    chunk = b""
                if chunk:
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        try:
                            tr.event(json.loads(line))
                        except (ValueError, KeyError, TypeError):
                            pass
                    backoff = 1
                elif chunk == b"":
                    # niri закрыл поток (перезапуск niri, выход из сеанса):
                    # закрыть счёт текущему окну и переподключиться.
                    tr.commit()
                    tr.focused = None
                    sel.unregister(stream.stdout)
                    stream.wait(timeout=2)
                    stream = None
                    next_retry = time.monotonic() + backoff
                    backoff = min(backoff * 2, 30)
                    log("поток niri оборвался, переподключение")

        now = time.monotonic()
        if now >= next_tick:
            next_tick = now + TICK_SEC
            tr.check_lock()
            tr.commit()
            if idle_proc is not None and idle_proc.poll() is not None:
                log("hypridle счётчика умер, перезапуск")
                tr.set_idle(False)
                idle_proc = start_idle_watch()
            today = time.strftime("%Y-%m-%d")
            if today != day:
                day = today
                store.prune()
        if now >= next_flush:
            next_flush = now + FLUSH_SEC
            store.flush()


if __name__ == "__main__":
    main()
