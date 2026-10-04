#!/usr/bin/env python3
"""Bongo Cat для waybar: кот бьёт лапами по столу в такт нажатиям клавиш,
а когда вы не печатаете — в такт музыке. 30.09.2026, по мотивам плагина
Bongo Cat у Noctalia.

Рисунок — шрифт JarvisBongo (build_bongo_font.py), четыре знака U+E400..E403:
покой, левая лапа, правая, обе. Скрипт печатает по строке на каждый СМЕНИВШИЙСЯ
кадр, не чаще 20 раз в секунду; цвет кота — color из CSS модуля.

Клавиатура. Читается /dev/input/event* напрямую (пользователь в группе input),
без python-evdev: его нет
в системном python, а для «было нажатие» хватает разбора struct input_event.
Устройство только читается, НИКОГДА не захватывается (EVIOCGRAB не вызывается)
— клавиши работают как обычно. Код клавиши не смотрится вовсе, кроме отсева
кнопок мыши (код ≥ 256), никуда не пишется и не хранится: учитывается только
факт нажатия (type=EV_KEY, value=1; автоповтор value=2 не считается).
Клавиатуры — устройства, которые умеют KEY_A, KEY_Z и пробел; виртуальное
устройство espanso отброшено, чтобы его подстановки не били лапой дважды.
Подключение/отключение клавиатур подхватывается: список устройств
перечитывается раз в 3 с, пропавшее устройство тихо закрывается.

Музыка. Пока какой-нибудь MPRIS-плеер в состоянии Playing, работает cava с
сырым выводом и 8 полосами; простой детектор долей по басам (первые две
полосы): резкий рост выше скользящего среднего → удар, лапы чередуются. Доли
идут в лапы, только если 2 с не было нажатий. Плееры отслеживаются
«playerctl -a -F status» — событиями, без опроса; на каждое событие один раз
спрашивается полный список. cava гасится через 5 с после паузы.
Почему не состояние ALSA в /proc/asound: cava бара сам держит выход в RUNNING
(захват монитора не даёт PipeWire его усыпить), и признак всегда «играет».

Выключатель — файл ~/.config/hypr/state/bongo-off. Есть файл — модуль пуст
(waybar прячет его), устройства и cava отпущены. Файл проверяется раз в
секунду, так что переключатель в Настройках действует сразу.

    bongo_cat.py            — режим waybar (exec модуля custom/bongo)
    bongo_cat.py on|off     — включить/выключить
    bongo_cat.py status     — on / off
"""
import os
import selectors
import signal
import struct
import subprocess
import sys
import time

OFF_FILE = os.path.expanduser("~/.config/hypr/state/bongo-off")
GLYPH = {"idle": "", "left": "", "right": "", "both": ""}
OPEN = '<span font="JarvisBongo 18" letter_spacing="0">'
CLOSE = "</span>"

HOLD_S = 0.15            # столько лапа лежит на столе после нажатия
CHORD_S = 0.05           # два нажатия ближе этого — обе лапы разом
MIN_FRAME_S = 0.05       # не чаще 20 кадров в секунду
MUSIC_AFTER_S = 2.0      # столько без нажатий — и кот слушает музыку
BEAT_HOLD_S = 0.12
BEAT_GAP_S = 0.22        # не чаще ~270 ударов в минуту
AUDIO_CHECK_S = 1.0
AUDIO_GRACE_S = 5.0      # пауза дольше — cava гасится
WATCH_RETRY_S = 10.0     # упавший playerctl --follow поднимается заново
FLAG_CHECK_S = 1.0
RESCAN_S = 3.0

EV_KEY = 1
EVENT = struct.Struct("llHHi")          # struct input_event на 64-битном ядре
KEY_A, KEY_Z, KEY_SPACE = 30, 44, 57

CAVA_CONF = """[general]
framerate = 40
autosens = 1
sensitivity = 100
bars = 8
lower_cutoff_freq = 40
higher_cutoff_freq = 6000
[input]
method = pipewire
source = auto
[output]
method = raw
channels = mono
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 1000
bar_delimiter = 59
frame_delimiter = 10
[smoothing]
noise_reduction = 20
monstercat = 0
"""


# ── Выключатель ────────────────────────────────────────────────────────────
def is_off():
    return os.path.exists(OFF_FILE)


def cli(cmd):
    if cmd == "off":
        os.makedirs(os.path.dirname(OFF_FILE), exist_ok=True)
        open(OFF_FILE, "w").close()
    elif cmd == "on":
        try:
            os.remove(OFF_FILE)
        except FileNotFoundError:
            pass
    elif cmd != "status":
        print("usage: bongo_cat.py [on|off|status]", file=sys.stderr)
        return 2
    print("off" if is_off() else "on")
    return 0


# ── Клавиатуры ─────────────────────────────────────────────────────────────
def _has_bit(words, bit):
    """Битовая маска из /proc/bus/input/devices: слова по 64 бита, старшее первым."""
    idx = len(words) - 1 - bit // 64
    return idx >= 0 and (int(words[idx], 16) >> (bit % 64)) & 1


def find_keyboards(text):
    paths = []
    for block in text.split("\n\n"):
        name, handlers, ev, key = "", [], None, None
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line[8:].strip('"')
            elif line.startswith("H: Handlers="):
                handlers = line[12:].split()
            elif line.startswith("B: EV="):
                ev = line[6:].split()
            elif line.startswith("B: KEY="):
                key = line[7:].split()
        if not ev or not key or "virtual" in name.lower():
            continue
        if not _has_bit(ev, EV_KEY):
            continue
        if not all(_has_bit(key, k) for k in (KEY_A, KEY_Z, KEY_SPACE)):
            continue
        for h in handlers:
            if h.startswith("event"):
                paths.append("/dev/input/" + h)
    return paths


def players_playing():
    """Играет ли хоть один MPRIS-плеер (браузер, YouTube Music, mpv…)."""
    try:
        out = subprocess.run(["playerctl", "-a", "status"], capture_output=True,
                             text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.strip() == "Playing" for line in out.splitlines())


class Cat:
    def __init__(self):
        self.sel = selectors.DefaultSelector()
        self.devs = {}                  # path -> fd
        self.proc_text = None
        self.cava = None
        self.cava_buf = b""
        self.shown = None               # последняя отданная строка
        self.last_out = 0.0
        self.left_until = 0.0
        self.right_until = 0.0
        self.next_left = True
        self.last_press = 0.0
        self.last_hit = 0.0
        self.last_beat = 0.0
        self.bass_avg = 0.0
        self.bass_prev = 0.0
        self.audio_on_at = 0.0          # когда последний раз звук шёл
        self.audio_checked = 0.0
        self.playing = False
        self.play_refreshed = 0.0
        self.watch = None               # playerctl --follow
        self.watch_buf = b""
        self.watch_started = -WATCH_RETRY_S
        self.rescanned = 0.0
        self.flag_checked = 0.0
        self.off = None

    # ── вывод ──
    def emit(self, text):
        if text == self.shown:
            return
        self.shown = text
        self.last_out = time.monotonic()
        try:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            self.shutdown()
            os._exit(0)

    def frame(self, now):
        l, r = now < self.left_until, now < self.right_until
        return "both" if l and r else "left" if l else "right" if r else "idle"

    # ── устройства ──
    def rescan(self):
        try:
            with open("/proc/bus/input/devices") as f:
                text = f.read()
        except OSError:
            return
        if text == self.proc_text:
            return
        self.proc_text = text
        want = set(find_keyboards(text))
        for path in list(self.devs):
            if path not in want:
                self.close_dev(path)
        for path in want - set(self.devs):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                continue
            self.devs[path] = fd
            self.sel.register(fd, selectors.EVENT_READ, ("dev", path))

    def close_dev(self, path):
        fd = self.devs.pop(path, None)
        if fd is None:
            return
        try:
            self.sel.unregister(fd)
        except (KeyError, ValueError):
            pass
        try:
            os.close(fd)
        except OSError:
            pass

    def read_dev(self, path, now):
        fd = self.devs.get(path)
        try:
            data = os.read(fd, EVENT.size * 64)
        except BlockingIOError:
            return
        except OSError:                 # устройство пропало (отключили, сон)
            self.close_dev(path)
            self.proc_text = None       # на следующем обходе открыть заново
            return
        presses = 0
        for off in range(0, len(data) - EVENT.size + 1, EVENT.size):
            _, _, typ, code, val = EVENT.unpack_from(data, off)
            if typ == EV_KEY and val == 1 and code < 256:
                presses += 1
        del data
        for _ in range(presses):
            self.press(now, HOLD_S)
        if presses:
            self.last_press = now

    def press(self, now, hold):
        """Удар лапой. Лапы чередуются: новая бьёт, прежняя поднимается —
        иначе при быстром наборе обе лапы всё время лежали бы на столе.
        Два нажатия почти разом (сочетание клавиш) — обе лапы."""
        chord = now - self.last_hit < CHORD_S
        self.last_hit = now
        if self.next_left:
            self.left_until = now + hold
            if not chord:
                self.right_until = min(self.right_until, now)
        else:
            self.right_until = now + hold
            if not chord:
                self.left_until = min(self.left_until, now)
        self.next_left = not self.next_left

    # ── музыка ──
    def start_watch(self):
        self.watch_started = time.monotonic()
        try:
            self.watch = subprocess.Popen(
                ["playerctl", "-a", "-F", "status"], stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError:
            self.watch = None
            return
        os.set_blocking(self.watch.stdout.fileno(), False)
        self.sel.register(self.watch.stdout.fileno(), selectors.EVENT_READ, ("watch", None))
        self.watch_buf = b""
        self.playing = players_playing()

    def stop_watch(self):
        if not self.watch:
            return
        try:
            self.sel.unregister(self.watch.stdout.fileno())
        except (KeyError, ValueError):
            pass
        self.watch.terminate()
        try:
            self.watch.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.watch.kill()
        self.watch.stdout.close()
        self.watch = None

    def read_watch(self):
        try:
            data = os.read(self.watch.stdout.fileno(), 4096)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self.stop_watch()
            self.playing = False
            return
        # Строка от --follow говорит лишь про один плеер — узнаём про все.
        self.playing = players_playing()
        if self.playing:
            self.audio_on_at = time.monotonic()

    def start_cava(self):
        if self.cava:
            return
        conf = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "bongo-cava.conf")
        try:
            with open(conf, "w") as f:
                f.write(CAVA_CONF)
            self.cava = subprocess.Popen(["cava", "-p", conf], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError:
            self.cava = None
            return
        os.set_blocking(self.cava.stdout.fileno(), False)
        self.sel.register(self.cava.stdout.fileno(), selectors.EVENT_READ, ("cava", None))
        self.cava_buf = b""
        self.bass_avg = self.bass_prev = 0.0

    def stop_cava(self):
        if not self.cava:
            return
        try:
            self.sel.unregister(self.cava.stdout.fileno())
        except (KeyError, ValueError):
            pass
        self.cava.terminate()
        try:
            self.cava.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.cava.kill()
        self.cava.stdout.close()
        self.cava = None

    def read_cava(self, now):
        try:
            data = os.read(self.cava.stdout.fileno(), 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:                    # cava умер — поднимем при следующей проверке
            self.stop_cava()
            return
        self.cava_buf += data
        *lines, self.cava_buf = self.cava_buf.split(b"\n")
        for line in lines:
            vals = [int(p) for p in line.strip().strip(b";").split(b";") if p.isdigit()]
            if len(vals) >= 2:
                self.onset((vals[0] + vals[1]) / 2000.0, now)

    def onset(self, bass, now):
        """Доля = бас резко вырос и заметно выше своего скользящего среднего."""
        rise = bass - self.bass_prev
        self.bass_prev = bass
        avg = self.bass_avg
        self.bass_avg += (bass - avg) * 0.08
        if now - self.last_press < MUSIC_AFTER_S:
            return
        if bass > 0.15 and rise > 0.06 and bass > avg * 1.2 and now - self.last_beat > BEAT_GAP_S:
            self.last_beat = now
            self.press(now, BEAT_HOLD_S)

    # ── цикл ──
    def shutdown(self):
        self.stop_cava()
        self.stop_watch()
        self.playing = False
        for path in list(self.devs):
            self.close_dev(path)
        self.proc_text = None

    def tick(self, now):
        if now - self.flag_checked >= FLAG_CHECK_S or self.off is None:
            self.flag_checked = now
            off = is_off()
            if off != self.off:
                self.off = off
                if off:
                    self.shutdown()
                    self.emit("")
                else:
                    self.rescanned = 0.0
                    self.watch_started = -WATCH_RETRY_S
        if self.off:
            return
        if now - self.rescanned >= RESCAN_S:
            self.rescanned = now
            self.rescan()
        if now - self.audio_checked >= AUDIO_CHECK_S:
            self.audio_checked = now
            if not self.watch and now - self.watch_started >= WATCH_RETRY_S:
                self.start_watch()
            if self.playing and now - self.play_refreshed >= 15:
                # страховка: плеер мог исчезнуть молча (закрыли вкладку)
                self.play_refreshed = now
                self.playing = players_playing()
            if self.playing:
                self.audio_on_at = now
                self.start_cava()
            elif self.cava and now - self.audio_on_at > AUDIO_GRACE_S:
                self.stop_cava()

    def run(self):
        while True:
            now = time.monotonic()
            self.tick(now)
            if self.off:
                time.sleep(FLAG_CHECK_S)
                continue
            # Кадр: отдать, если сменился и прошло ≥ 50 мс с прошлого.
            want = OPEN + GLYPH[self.frame(now)] + CLOSE
            wait = 1.0
            if want != self.shown:
                gap = MIN_FRAME_S - (now - self.last_out)
                if gap <= 0:
                    self.emit(want)
                else:
                    wait = gap
            # Разбудиться, когда лапа должна подняться.
            for t in (self.left_until, self.right_until):
                if t > now:
                    wait = min(wait, t - now + 0.001)
            wait = min(wait, FLAG_CHECK_S)
            for key, _ in self.sel.select(timeout=max(0.0, wait)):
                kind, path = key.data
                now = time.monotonic()
                if kind == "dev":
                    if path in self.devs:
                        self.read_dev(path, now)
                elif kind == "watch":
                    if self.watch:
                        self.read_watch()
                elif self.cava:
                    self.read_cava(now)


def main():
    if len(sys.argv) > 1:
        sys.exit(cli(sys.argv[1]))
    cat = Cat()

    def bye(*_):
        cat.shutdown()
        os._exit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGHUP, bye)
    try:
        cat.run()
    except KeyboardInterrupt:
        pass
    finally:
        cat.shutdown()


if __name__ == "__main__":
    main()
