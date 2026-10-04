#!/usr/bin/env python3
"""Громкость ОТДЕЛЬНОГО приложения — того, чьё окно сейчас в фокусе.

    app_volume.py up [шаг]     громче (по умолчанию 5)
    app_volume.py down [шаг]   тише
    app_volume.py mute         заглушить/вернуть
    app_volume.py status       какой поток выбран и его громкость

Зачем. Системная громкость на мультимедийных клавишах крутит ВСЁ сразу.
Здесь громкость меняется у одного приложения — у того, в чьём окне Вы
работаете, а остальные звучат как звучали (24.09.2026).

Как находится поток. Окно даёт pid, но звук почти всегда идёт из другого
процесса: у браузера это вкладка-потомок, у Electron — своя дочерняя ветка.
Поэтому pid потока сверяется со ВСЕМ деревом процессов окна — вверх к предкам
и вниз к потомкам. Если у окна звука нет вовсе, берётся единственный звучащий
поток; если их несколько — ничего не трогаем и говорим об этом.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# audio_names и wm подключаются там, где нужны (streams, pick): в серии нажатий до них
# дело не доходит, а их загрузка — лишние 50 мс на каждое нажатие.

STEP_DEFAULT = 5
OSD_SECONDS = 1.6
OSD_UNTIL = os.path.expanduser("~/.cache/appvol-osd-until")
OSD_LOCK = os.path.expanduser("~/.cache/appvol-osd.lock")
# Плееры со СВОЕЙ громкостью, которую они сами переносят на поток. Spotify при
# смене трека ставит потоку свою внутреннюю громкость, и 70 %, выставленные
# биндом, через трек снова становились 100 % (28.09.2026). Им уровень сообщаем
# ещё и через MPRIS. Браузерным плеерам — нет: там MPRIS-громкость — отдельный
# регулятор на странице, и звук убавлялся бы дважды.
MPRIS_SYNC = {"spotify": "spotify"}      # слово имени потока → имя плеера в playerctl


def run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def streams():
    """[(id, имя, pid, слова для опознания)] — всё, что сейчас выводит звук.

    pid есть не у каждого потока: Telegram, к примеру, отдаёт только
    node.name «Telegram» (проверено 24.09.2026) — по дереву процессов такой
    поток не найти вовсе, поэтому рядом собираются слова имени.
    """
    import audio_names
    try:
        data = json.loads(run(["pw-dump"], timeout=8) or "[]")
    except ValueError:
        return []
    res = []
    for obj in data:
        props = ((obj.get("info") or {}).get("props") or {})
        if props.get("media.class") != "Stream/Output/Audio":
            continue
        # Имя — общим разбором (audio_names): Electron-приложения все
        # представляются «Chromium», и Яндекс Музыка значилась им же.
        name = audio_names.stream_name(props)
        pid = props.get("application.process.id")
        words = words_of(props.get("application.name"), props.get("node.name"),
                         props.get("application.process.binary"))
        res.append((obj.get("id"), name, int(pid) if pid else None, words))
    return res


def words_of(*values):
    """Набор опознавательных слов: «org.telegram.desktop» -> telegram, desktop, …"""
    out = set()
    for value in values:
        if not value:
            continue
        low = "".join(c if c.isalnum() else " " for c in str(value).lower())
        parts = [w for w in low.split() if len(w) >= 3]
        out.update(parts)
        if parts:
            out.add("".join(parts))
    return out


def window_words(win):
    """Слова окна: класс приложения и имя процесса (заголовок не берём —
    в нём бывает что угодно, вплоть до имени открытого файла)."""
    out = words_of(win.get("app"))
    pid = win.get("pid")
    if pid:
        try:
            with open("/proc/%d/comm" % int(pid)) as f:
                out |= words_of(f.read().strip())
        except (OSError, ValueError):
            pass
    return out


def same_app(stream_words, win_words):
    """Похожи ли имена: «chromium» и «chrome-music» — да, «zen» и «kitty» — нет."""
    for a in stream_words:
        for b in win_words:
            if a == b or (len(a) >= 4 and a in b) or (len(b) >= 4 and b in a):
                return True
    return False


def parents(pid, limit=6):
    """Цепочка предков процесса — до init или до предела."""
    chain = []
    for _ in range(limit):
        try:
            with open("/proc/%d/stat" % pid) as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        if pid <= 1:
            break
        chain.append(pid)
    return chain


def family(pid):
    """pid окна, его предки и все потомки — в них и ищем звук."""
    kin = {pid} | set(parents(pid))
    # Потомки: обходим таблицу процессов один раз и раскручиваем детей.
    children = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % entry) as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(entry))
    queue, seen = [pid], set()
    while queue:
        cur = queue.pop()
        if cur in seen:
            continue
        seen.add(cur)
        kin.add(cur)
        queue.extend(children.get(cur, ()))
    return kin


def pick():
    """(список потоков, имя, откуда) — чью громкость крутим.

    Порядок строгий: сперва окно в фокусе, и только если у него звука нет —
    играющий плеер. Окно ищется двумя способами подряд: по дереву процессов
    (pid окна, его предки и потомки — у браузера звук идёт из вкладки) и по
    именам, потому что pid есть не у каждого потока (пользователь 24.09.2026:
    «должно работать для окна в фокусе, а не только для Zen»).

    Потоков у приложения бывает несколько — вкладки браузера, звонок и
    уведомления в мессенджере. Крутим у всех сразу: «сделать тише это окно»
    означает всё, что из него звучит.

    «откуда»: app — звук самого окна, player — окно молчит и взят играющий
    плеер; подсказка рисует разный значок, чтобы не гадать, чью громкость
    крутишь.
    """
    found = streams()
    if not found:
        return [], "звука сейчас никто не выводит", None
    import wm
    win = wm.focused() or {}
    if win:
        kin = family(int(win["pid"])) if win.get("pid") else set()
        wwords = window_words(win)
        mine = [(sid, name) for sid, name, pid, words in found
                if (pid and pid in kin) or same_app(words, wwords)]
        if mine:
            # Окно в фокусе побеждает всегда, даже если сейчас молчит: Telegram в
            # фокусе — значит громкость Telegram (28.09.2026, пользователь; проверка
            # «звучит ли окно на самом деле» отдавала бинд играющему Spotify).
            live = alive([sid for sid, _ in mine])
            if live:
                return live, mine[0][1], "app"
    # Окно молчит — значит, речь скорее всего про музыку: берём поток того
    # плеера, который сейчас играет (тот же путь, что у кнопки «Нравится»).
    # Плеер ищется и по pid, и по имени (28.09.2026): у Spotify после
    # перезапуска звука живой поток пришёл без pid, а поток с pid оказался
    # призраком — поиск только по pid находил призрака и сдавался.
    # Ищем его только здесь (03.10.2026): когда звук есть у самого окна, плеер не
    # нужен, а его поиск — три лишних вызова на каждое нажатие.
    inst = mpris_instance()
    player = mpris_pid(inst)
    pkin = family(player) if player else set()
    pwords = words_of(inst.split(".")[0] if inst else None)
    if player:
        try:
            with open("/proc/%d/comm" % player) as f:
                pwords |= words_of(f.read().strip())
        except OSError:
            pass
    if player or inst:
        mine = [(sid, name) for sid, name, pid, words in found
                if (pid and pid in pkin) or same_app(words, pwords)]
        if mine:
            live = alive([sid for sid, _ in mine])
            if live:
                return live, mine[0][1], "player"
    # Звучит ровно одна программа — сомнений, чью громкость крутить, нет
    # (pid тут не требуем: у части потоков его вовсе не бывает).
    if len(found) == 1 and alive([found[0][0]]):
        return [found[0][0]], found[0][1], "player"
    return [], "у этого окна звука нет, а звучит несколько программ", None


def mpris_instance():
    """Имя шины плеера, который сейчас ИГРАЕТ («spotify», «chromium.instance123»).

    Никто не играет — первый по списку. Раньше брался просто первый: при Spotify
    на паузе и играющей Яндекс Музыке бинд уходил в Spotify без звука и сдавался
    (28.09.2026, «с Яндекс Музыкой из другого окна не могу менять звук»).
    """
    rows = [line.split("\t") for line in
            run(["playerctl", "-a", "metadata", "--format", "{{playerInstance}}\t{{status}}"]).splitlines()
            if "\t" in line]
    for inst, status in rows:
        if status == "Playing":
            return inst
    return rows[0][0] if rows else None


def mpris_pid(inst=None):
    """PID процесса, который держит шину этого плеера (или None)."""
    inst = inst or mpris_instance()
    if not inst:
        return None
    out = run(["busctl", "--user", "call", "org.freedesktop.DBus",
               "/org/freedesktop/DBus", "org.freedesktop.DBus",
               "GetConnectionUnixProcessID", "s",
               "org.mpris.MediaPlayer2." + inst]).split()
    return int(out[1]) if len(out) > 1 and out[1].isdigit() else None


def alive(sids):
    """Оставить потоки, которыми и правда можно управлять.

    В pw-dump попадают узлы, которых wpctl уже не знает («Node not found»):
    у Spotify таких оказалось два — один живой, другой призрак (25.09.2026,
    Просьба: «нажимаю, звук вырубается и больше не включается»). Громкость
    призрака не читается, и дальше всё шло вразнос: «тише» уходило в пустоту,
    а «громче» считало текущий уровень от нуля.
    """
    return [sid for sid in sids if volume(sid)[0] is not None]


_VOL = {}        # прочитанные уровни — в пределах одного запуска, до первой смены громкости


def volume(sid):
    if sid in _VOL:
        return _VOL[sid]
    out = run(["wpctl", "get-volume", str(sid)])
    muted = "[MUTED]" in out
    try:
        value = float(out.split("Volume:")[1].split()[0])
    except (IndexError, ValueError):
        return None, muted
    _VOL[sid] = (int(round(value * 100)), muted)
    return _VOL[sid]


def osd(name, percent, muted, kind):
    """Показать подсказку сверху по центру; гасит её единственный сторож.

    Раньше каждое нажатие плодило свой «sleep; eww close»: на серии нажатий
    первый же таймер закрывал плашку прямо под следующим нажатием, и она
    моргала (пользователь 24.09.2026: «нет той стабильности, как у микшера справа»).
    Теперь нажатие только отодвигает срок в файле, а закрывает плашку один
    процесс-сторож — второй не запустится, его не пускает блокировка файла.

    03.10.2026 — быстрее: четыре переменные уходят одним вызовом eww (было четыре,
    по ~40 мс), а открывать плашку и заводить сторожа заново незачем, пока сторож
    жив — она уже на экране.
    """
    try:
        with open(OSD_UNTIL, "w") as f:
            f.write("%.2f" % (time.time() + OSD_SECONDS))
    except OSError:
        pass
    subprocess.run(["eww", "update", "appvol-name=%s" % name, "appvol-level=%s" % percent,
                    "appvol-muted=%s" % ("yes" if muted else "no"),
                    "appvol-kind=%s" % (kind or "app")], capture_output=True)
    if guard_alive():
        return
    subprocess.Popen(["eww", "open", "app-volume-osd"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "guard"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def guard_alive():
    """Жив ли сторож плашки (он держит блокировку файла) — значит, плашка открыта."""
    import fcntl
    try:
        with open(OSD_LOCK, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def deadline():
    try:
        with open(OSD_UNTIL) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return 0.0


def guard():
    """Единственный сторож плашки: ждёт срок и закрывает её."""
    import fcntl
    try:
        lock = open(OSD_LOCK, "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0                      # сторож уже есть — он всё и сделает
    while True:
        left = deadline() - time.time()
        if left > 0:
            time.sleep(min(left, 0.25))   # срок мог отодвинуться новым нажатием
            continue
        subprocess.run(["eww", "close", "app-volume-osd"], capture_output=True)
        # Нажатие могло прийти, пока плашка закрывалась: оно увидело живого сторожа и
        # открывать её не стало — открываем сами и ждём дальше.
        if deadline() - time.time() > 0:
            subprocess.run(["eww", "open", "app-volume-osd"], capture_output=True)
            continue
        break
    return 0


# ── серия нажатий (03.10.2026) ──────────────────────────────────────────────
# Одно нажатие стоило ~0,7 с: поиск потока (pw-dump, плеер, дерево процессов) ~0,3 с,
# чтение громкости, четыре вызова eww. При удержании клавиши нажатия вставали в
# очередь, и плашка отставала от пальцев (просьба: «посмотри плавность»). Теперь первое
# нажатие ищет поток как раньше и запоминает его на несколько секунд; следующие, пока
# в фокусе то же окно, берут запомненное и только двигают громкость — ~0,15 с.
PICK_CACHE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "appvol-pick.json")
PICK_TTL = 4.0


def focused_id():
    """id окна в фокусе — напрямую из сокета niri (2 мс вместо 50 у `niri msg`)."""
    path = os.environ.get("NIRI_SOCKET")
    if not path:
        return None
    import socket
    try:
        with socket.socket(socket.AF_UNIX) as sk:
            sk.settimeout(0.5)
            sk.connect(path)
            sk.sendall(b'"FocusedWindow"\n')
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sk.recv(65536)
                if not chunk:
                    break
                buf += chunk
        win = ((json.loads(buf).get("Ok") or {}).get("FocusedWindow") or {})
        return win.get("id", 0)
    except (OSError, ValueError, AttributeError):
        return None


def recall():
    try:
        with open(PICK_CACHE) as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    if time.time() - c.get("t", 0) > PICK_TTL or not c.get("sids"):
        return None
    win = focused_id()
    return c if win is not None and win == c.get("win") else None


def remember(sids, name, kind, percent, muted, win=None):
    win = focused_id() if win is None else win
    if win is None:
        return
    try:
        with open(PICK_CACHE + ".tmp", "w") as f:
            json.dump({"t": time.time(), "win": win, "sids": sids, "name": name, "kind": kind,
                       "percent": percent, "muted": muted}, f)
        os.replace(PICK_CACHE + ".tmp", PICK_CACHE)
    except OSError:
        pass


def run_all(cmds):
    """Несколько команд разом (потоков у приложения бывает несколько); True — все удались."""
    procs = []
    for cmd in cmds:
        try:
            procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        except OSError:
            return False
    ok = True
    for p in procs:
        try:
            ok = p.wait(timeout=5) == 0 and ok
        except subprocess.SubprocessError:
            ok = False
    return ok


def mpris_sync(name, percent):
    for word, player in MPRIS_SYNC.items():
        if word in name.lower():
            subprocess.Popen(["playerctl", "-p", player, "volume", "%.2f" % (percent / 100)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def quick(action, step):
    """Нажатие из серии: поток известен, уровень известен. False — идти полным путём."""
    c = recall()
    if not c or c.get("percent") is None:
        return False
    sids, percent = c["sids"], int(c["percent"])
    if action == "up":
        percent = min(100, percent + step)
        cmds = [["wpctl", "set-volume", str(sid), "%d%%" % percent] for sid in sids]
        if c.get("muted"):
            cmds = [["wpctl", "set-mute", str(sid), "0"] for sid in sids] + cmds
    else:
        percent = max(0, percent - step)
        cmds = [["wpctl", "set-volume", str(sid), "%d%%-" % step] for sid in sids]
    muted = bool(c.get("muted")) and action != "up"
    # плашка и громкость — одновременно: итог нажатия известен заранее
    import threading
    show = threading.Thread(target=osd, args=(c["name"], percent, muted, c.get("kind")))
    show.start()
    ok = run_all(cmds)
    show.join()
    if not ok:
        try:
            os.remove(PICK_CACHE)             # поток пропал — следующее нажатие найдёт заново
        except OSError:
            pass
        return False                          # полный путь покажет плашку с настоящим уровнем
    remember(sids, c["name"], c.get("kind"), percent, muted, win=c.get("win"))
    mpris_sync(c["name"], percent)
    print("%s: %d%%%s" % (c["name"], percent, " (тихо)" if muted else ""))
    return True


def main():
    args = sys.argv[1:] or ["status"]
    action = args[0]
    if action == "guard":
        return guard()
    try:
        step = int(args[1]) if len(args) > 1 else STEP_DEFAULT
    except ValueError:
        step = STEP_DEFAULT

    if action in ("up", "down") and quick(action, step):
        return 0

    sids, name, kind = pick()
    if not sids:
        print(name)
        return 1

    if action == "up":
        # Потолок 100 %: выше wpctl уходит охотно, но звук начинает хрипеть.
        # Уровень берём максимальный по потокам приложения: они бывают разными,
        # и от самого тихого громкость ползла бы вниз.
        levels = [volume(sid)[0] for sid in sids]
        current = max([v for v in levels if v is not None] or [0])
        target = min(100, current + step)
        # Заглушённый поток «громче» обязан расглушить: иначе после нуля
        # звук не вернуть вовсе.
        run_all([["wpctl", "set-mute", str(sid), "0"] for sid in sids if volume(sid)[1]])
        run_all([["wpctl", "set-volume", str(sid), "%d%%" % target] for sid in sids])
    elif action == "down":
        run_all([["wpctl", "set-volume", str(sid), "%d%%-" % step] for sid in sids])
    elif action == "mute":
        muted_now = volume(sids[0])[1]
        run_all([["wpctl", "set-mute", str(sid), "0" if muted_now else "1"] for sid in sids])
    elif action != "status":
        print(__doc__, file=sys.stderr)
        return 1

    _VOL.clear()
    percent, muted = volume(sids[0])
    if percent is None:
        print("громкость потока не прочиталась")
        return 1
    if action in ("up", "down"):
        mpris_sync(name, percent)
    if action != "status":
        remember(sids, name, kind, percent, muted)
        osd(name, percent, muted, kind)
    print("%s: %d%%%s%s" % (name, percent, " (тихо)" if muted else "",
                            "" if len(sids) == 1 else " [потоков: %d]" % len(sids)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
