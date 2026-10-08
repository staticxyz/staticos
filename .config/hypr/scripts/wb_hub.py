#!/usr/bin/env python3
"""Один исполнитель модуля верхнего waybar на все мониторы (07.10.2026, оптимизация памяти).

Просьба: «можем ли оптимизировать потребление оперативы моих дотфайлов, но чтобы не
пострадал визуал». У каждого монитора свой waybar, и каждый запускал свою копию
модулей: часы, батарея, плеер, pomo, браузеры, эквалайзер, кошка, приватность, язык —
по два python на модуль, ~7 МиБ каждый, и вдвое больше процессора у эквалайзера.
Выводят они на оба бара одно и то же (от монитора зависят только список столов и
заголовок окна — их это не касается).

Теперь бар запускает `wb_share КЛЮЧ команда…` (sh + cat, ~1 МиБ): команда кладётся в
$XDG_RUNTIME_DIR/wbhub/КЛЮЧ.cmd, бар читает свою FIFO КЛЮЧ.<pid>.fifo. Этот процесс
(один на всех) запускает каждую команду ОДИН раз и раздаёт её строки во все FIFO;
новому бару сразу отдаёт последнюю строку. Бар ушёл — его FIFO отваливается (EPIPE);
у модуля 15 с нет читателей — он останавливается; нет никого минуту — выходит и сам.

    wb_hub.py serve     (запускает wb_share; второй экземпляр сразу выходит — flock)
    wb_hub.py status    что запущено и сколько читателей

Откат: в ~/.config/waybar/config.jsonc и waybar_niri.py убрать «wb_share КЛЮЧ» из exec
(копии .bak-wbhub), `python3 ~/.config/niri/scripts/waybar_niri.py`, barfix.
"""
import ctypes
import errno
import fcntl
import os
import select
import signal
import subprocess
import sys
import time

D = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "wbhub")
IDLE_MOD = 15          # с без читателей — остановить модуль
IDLE_HUB = 60          # с без модулей и читателей — выйти
_libc = ctypes.CDLL(None)


def die_with_parent():
    _libc.prctl(1, signal.SIGTERM, 0, 0, 0)     # PR_SET_PDEATHSIG: хаб умер — модули тоже


class Mod:
    def __init__(self, key):
        self.key = key
        self.proc = None
        self.buf = b""
        self.last = None
        self.fifos = {}          # путь → fd
        self.lonely = None       # с какого момента без читателей
        self.died = 0

    def argv(self):
        try:
            raw = open(os.path.join(D, self.key + ".cmd"), "rb").read()
        except OSError:
            return None
        a = [x.decode() for x in raw.split(b"\0") if x]
        return a or None

    def start(self):
        a = self.argv()
        if not a or time.time() - self.died < 1:
            return
        try:
            self.proc = subprocess.Popen(a, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                         preexec_fn=die_with_parent)
        except OSError:
            self.proc, self.died = None, time.time()
            return
        os.set_blocking(self.proc.stdout.fileno(), False)
        self.buf = b""

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def send(self, line):
        for path, fd in list(self.fifos.items()):
            try:
                os.write(fd, line)
            except BlockingIOError:
                pass                                 # читатель не успевает — строку пропустит
            except OSError:                          # бар ушёл (EPIPE)
                self.drop(path)

    def drop(self, path):
        fd = self.fifos.pop(path, None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.remove(path)
        except OSError:
            pass


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def scan(mods):
    """Новые FIFO баров → открыть на запись; мёртвые (pid читателя исчез) — убрать."""
    try:
        names = os.listdir(D)
    except OSError:
        return
    for n in names:
        if not n.endswith(".fifo"):
            continue
        key, _, rest = n[:-5].rpartition(".")
        path = os.path.join(D, n)
        m = mods.setdefault(key, Mod(key))
        if path in m.fifos:
            continue
        if rest.isdigit() and not pid_alive(int(rest)):
            m.drop(path)
            continue
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            if e.errno == errno.ENXIO:               # читатель ещё не открыл — в следующий раз
                continue
            continue
        m.fifos[path] = fd
        if m.last:
            try:
                os.write(fd, m.last)
            except OSError:
                pass


def serve():
    os.makedirs(D, exist_ok=True)
    lock = open(os.path.join(D, "hub.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0                                     # уже работает
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    mods = {}
    empty_since = time.time()
    next_scan = 0
    try:
        while True:
            now = time.time()
            if now >= next_scan:
                scan(mods)
                next_scan = now + 0.5
                for m in list(mods.values()):
                    if m.fifos and (m.proc is None or m.proc.poll() is not None):
                        if m.proc is not None:
                            m.proc, m.died = None, now
                        m.start()
                    if not m.fifos:
                        m.lonely = m.lonely or now
                        if now - m.lonely > IDLE_MOD:
                            m.stop()
                            del mods[m.key]
                    else:
                        m.lonely = None
                if mods:
                    empty_since = now
                elif now - empty_since > IDLE_HUB:
                    return 0
            outs = {m.proc.stdout.fileno(): m for m in mods.values() if m.proc and m.proc.poll() is None}
            if not outs:
                time.sleep(0.5)
                continue
            r, _, _ = select.select(list(outs), [], [], 0.5)
            for fd in r:
                m = outs[fd]
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                except OSError:
                    chunk = b""
                if not chunk:                        # модуль завершился — перезапуск при скане
                    m.proc.wait()
                    m.proc, m.died = None, time.time()
                    continue
                m.buf += chunk
                while b"\n" in m.buf:
                    line, m.buf = m.buf.split(b"\n", 1)
                    line += b"\n"
                    m.last = line
                    m.send(line)
    finally:
        for m in mods.values():
            m.stop()


def status():
    try:
        names = sorted(os.listdir(D))
    except OSError:
        print("хаб не запущен")
        return 0
    keys = {}
    for n in names:
        if n.endswith(".fifo"):
            keys.setdefault(n[:-5].rpartition(".")[0], []).append(n)
    for k, f in keys.items():
        print("%-28s читателей: %d" % (k, len(f)))
    return 0


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["status"])[0]
    sys.exit(serve() if cmd == "serve" else status())
