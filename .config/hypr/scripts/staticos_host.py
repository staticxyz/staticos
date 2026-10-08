#!/usr/bin/env python3
"""Хозяин staticOS: фоновые сторожа одним процессом, каждый в своём потоке. 07.10.2026.

Просьба: «попробуем оптимизацию, но по одному, чтобы ничего не сломать, и держи бэкап».
Каждый сторож (cpu_hog_watch, track_notify…) раньше был отдельным python: ~6 МиБ
своей памяти на сам интерпретатор, хотя скрипт почти ничего не держит. Здесь
интерпретатор один, а сторож запускается как __main__ своего файла (runpy) в потоке:
код сторожа не меняется, его вкл/выкл через файлы состояния работают как раньше.

Список — ~/.config/hypr/state/staticos-host.json: ["cpu_hog_watch.py", …] (пути от
scripts/, без аргументов). Упал или вышел сторож — перезапуск через 5 с (дальше реже,
до 5 мин); остальные работают. Сам хозяин в автозапуске niri под циклом sh: упал —
поднимется через 2 с.

Чего здесь быть не должно (такие сторожа оставлять отдельными процессами):
  * signal.signal — работает только в главном потоке (здесь вызов тихо игнорируется);
  * os._exit / os.exec* — убьют всех;
  * свой GLib/Gtk main loop — один на процесс;
  * поиск себя по /proc/*/cmdline, чтобы послать сигнал (своего процесса у сторожа нет).

    staticos_host.py            работать (второй экземпляр выходит — flock)
    staticos_host.py status     кто запущен, сколько перезапусков, последняя ошибка
Журнал — ~/.cache/staticos-host.log. Откат одного сторожа: убрать из списка, вернуть
его строку в ~/.config/niri/cfg/autostart.kdl (копии .bak-host-<имя>), перезапустить хозяин.
"""
import ctypes
import fcntl
import json
import os
import runpy
import signal
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.expanduser("~/.config/hypr/state/staticos-host.json")
RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
STATUS = os.path.join(RUN, "staticos-host.json")
LOG = os.path.expanduser("~/.cache/staticos-host.log")
_libc = ctypes.CDLL(None)
_log_lock = threading.Lock()
state = {}


def log(msg):
    with _log_lock:
        try:
            if os.path.getsize(LOG) > 1048576:
                os.replace(LOG, LOG + ".old")
        except OSError:
            pass
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), msg))


def write_status():
    try:
        with open(STATUS + ".tmp", "w") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(STATUS + ".tmp", STATUS)
    except OSError:
        pass


# signal.signal разрешён только главному потоку — сторожам вызов не ломает запуск
_real_signal = signal.signal


def _signal(sig, handler):
    if threading.current_thread() is threading.main_thread():
        return _real_signal(sig, handler)
    log("%s: signal.signal(%s) в потоке пропущен" % (threading.current_thread().name, sig))
    return signal.SIG_DFL


signal.signal = _signal


def run_one(name):
    path = os.path.join(HERE, name)
    st = state[name]
    delay = 5
    while True:
        st.update(status="running", started=time.time())
        write_status()
        t0 = time.time()
        try:
            _libc.prctl(15, ("jv:" + os.path.splitext(name)[0])[:15].encode(), 0, 0, 0)  # имя потока
            sys.argv = [path]
            runpy.run_path(path, run_name="__main__")
            why = "вышел сам"
        except SystemExit as e:
            why = "sys.exit(%s)" % (e.code,)
        except BaseException:
            why = traceback.format_exc().strip().splitlines()[-1]
            log("%s упал:\n%s" % (name, traceback.format_exc()))
        st["restarts"] = st.get("restarts", 0) + 1
        st.update(status="restarting", last=why)
        write_status()
        log("%s: %s — перезапуск через %d с" % (name, why, delay))
        time.sleep(delay)
        delay = 5 if time.time() - t0 > 600 else min(delay * 2, 300)


def serve():
    lock = open(os.path.join(RUN, "staticos-host.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0
    try:
        names = json.load(open(LIST))
    except (OSError, ValueError):
        names = []
    log("хозяин запущен, сторожей: %d (%s)" % (len(names), ", ".join(names)))
    for n in names:
        if not os.path.isfile(os.path.join(HERE, n)):
            log("%s: нет файла — пропущен" % n)
            continue
        state[n] = {"status": "starting", "restarts": 0}
        threading.Thread(target=run_one, args=(n,), name=n, daemon=True).start()
        time.sleep(0.2)          # по очереди: сторожа читают sys.argv при старте
    write_status()
    _real_signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        time.sleep(3600)


def status():
    try:
        st = json.load(open(STATUS))
    except (OSError, ValueError):
        print("хозяин не запущен")
        return 1
    for n, s in st.items():
        print("%-22s %-10s перезапусков %d%s" % (n, s.get("status"), s.get("restarts", 0),
                                                 ("  · " + s["last"]) if s.get("last") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(status() if sys.argv[1:2] == ["status"] else serve())
