#!/usr/bin/env python3
"""Виджеты на обоях: часы, дата, матрица, эквалайзер, осьминог, система. 02.10.2026.

    desktop_widgets.py              сторож (автозапуск niri; второй экземпляр выходит)
    desktop_widgets.py on|off       включить / выключить (Настройки → Visuals)
    desktop_widgets.py status       on | off
    desktop_widgets.py edit         режим расстановки: двигать, растягивать, удалять, добавлять
                                    (кнопка «Очистить стол» и Shift+Delete — убрать все виджеты стола)
    desktop_widgets.py peek         показать виджеты поверх окон / убрать обратно под окна
    desktop_widgets.py list         что и где стоит
    desktop_widgets.py types        какие виджеты бывают
    desktop_widgets.py add ТИП [МОНИТОР]    добавить (в середину монитора)
    desktop_widgets.py timer [название] [время]   таймер-виджет (25m, 1h30m, 07:30; без времени — секундомер)
    desktop_widgets.py look [МОНИТОР|all [xp|skeet|beta|classic]]   вид окон: общий или для монитора
    desktop_widgets.py remove ИМЯ   убрать
    desktop_widgets.py clear        убрать все (раскладка перед этим запоминается)
    desktop_widgets.py preset save|restore|status   пресет: запомнить раскладку / вернуть её
    desktop_widgets.py reset        расставить заново по образцу дашборда
    desktop_widgets.py reload       перечитать desktop-widgets.json

Просьба: «мой первый стол Dashboard — окна, которые я использую как виджеты: день
недели, время в секундах, cava и красивые без пользы — осьминог, фастфетч,
хакерские окна. Можешь взять пример с них». Идея «виджеты на обоях» — из
дотфайлов AngelOS, код свой.

Что это. Каждый виджет — свой слой на ФОНЕ (поверх обоев, под окнами), на всех
столах монитора сразу; при смене стола едет вместе с обоями, как нарисованный на
них. Вид — как у окон дашборда: тёмная полупрозрачная плашка с размытием и
тонкой рамкой, содержимое акцентом обоев, пиксельный шрифт. Один процесс вместо
восьми терминалов. Щелчки проходят сквозь виджеты: ПКМ по обоям и всё прочее
работает как раньше.

Виджеты:
    clock    время ЧЧ:ММ:СС цифрами 3×5, как tty-clock
    date     день недели и дата блочным шрифтом (те же шрифты, что у dateview.py)
    pomo     строка помодоро: полоса, остаток, фаза, задача
    matrix   «цифровой дождь», как unimatrix
    cava     эквалайзер (настоящий cava с сырым выводом)
    sprite   гифка точками — осьминог из brrtfetch (opts.gif — другая)
    sysinfo  fastfetch: логотип и сведения, обновляется раз в минуту
    cmd      вывод любой команды (opts.cmd, opts.interval) с цветами ANSI

Расстановка — desktop_widgets.py edit (кнопка в Настройках): виджеты всплывают
поверх окон, ЛКМ — тащить, уголок — растянуть, × — убрать, ПКМ — плашка вкл/выкл,
кнопки сверху — добавить; Esc или «Готово» — сохранить и выйти. Раскладка —
~/.config/hypr/state/desktop-widgets.json (имя, тип, монитор, x/y/w/h, opts).

Нагрузка. Анимация (матрица, осьминог, cava) идёт, только когда виджет видно:
если окна закрывают его на 85 % и больше — анимация стоит (и cava не запущен), но сам
виджет остаётся на месте: окна полупрозрачные, и исчезающий под ними виджет заметен.
С экрана виджет снимается только на чужом столе (если не закреплён). Часы, дата и
помодоро тикают раз в секунду всегда — это ничего не стоит. В игре (cs2,
gamescope) стоит всё. Подписка на события niri и cava — с PDEATHSIG.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)          # dateview.py — шрифты даты
STATE = os.path.expanduser("~/.config/hypr/state")
CONF = os.environ.get("JARVIS_WIDGETS_CONF") or os.path.join(STATE, "desktop-widgets.json")
OFF = os.path.join(STATE, "desktop-widgets-off")
CACHE = os.path.expanduser("~/.cache/jarvis-widgets")
MATUGEN = os.path.expanduser("~/.cache/matugen")
DASH_JSON = os.path.expanduser("~/.config/niri/dashboard.json")
BRRT_GIF = os.path.expanduser("~/Pictures/brrtfetch/gifs/defaults/brrt.gif")
FONT = "PxPlus HP 100LX 6x8 Jarvis"
GAMES = (b"cs2", b"gamescope")

# тип → (название, ширина, высота по умолчанию)
TYPES = {
    "clock": ("Часы", 612, 133),
    "date": ("Дата", 799, 152),
    "pomo": ("Помодоро", 798, 71),
    "matrix": ("Матрица", 424, 309),
    "cava": ("Эквалайзер", 900, 155),
    "sprite": ("Осьминог", 440, 409),
    "sysinfo": ("Система (fastfetch)", 957, 411),
    "sysmon": ("Монитор ресурсов", 300, 236),
    "banner": ("Бегущая надпись", 700, 110),
    "player": ("Плеер", 380, 132),
    "playermini": ("Плеер в одну строку", 460, 66),
    "calendar": ("Календарь", 300, 250),
    "timer": ("Таймер", 420, 150),
    "weather": ("Погода", 400, 200),
    "screentime": ("Экранное время", 320, 196),
    "miku": ("Мику", 200, 236),
    "fire": ("Огонь", 320, 222),
    "life": ("Жизнь", 320, 262),
    "cmd": ("Команда", 520, 300),
}
# Имя в полосе заголовка (просьба: «названия на англ., в конце приписка .exe»).
EXE = {"clock": "clock.exe", "date": "today.exe", "pomo": "pomodoro.exe", "matrix": "matrix.exe",
       "cava": "visualizer.exe", "sprite": "octopus.exe", "sysinfo": "fetch.exe",
       "sysmon": "sysmon.exe", "banner": "banner.exe", "player": "player.exe", "playermini": "nowplaying.exe",
       "calendar": "calendar.exe", "timer": "timer.exe", "weather": "weather.exe", "screentime": "screentime.exe",
       "miku": "miku.exe", "fire": "fire.exe", "life": "life.exe", "cmd": "cmd.exe"}
# Общий вид плашек (Настройки → Visuals → Виджеты): прозрачный фон или сплошной,
# насколько прозрачный и насколько размыты обои под ним.
# Пресет — сохранённая раскладка (кто где стоит, размеры, столы); «отмена» — раскладка
# перед «Удалить все виджеты». Пункты — меню ПКМ → «Управление виджетами».
PRESET = os.path.join(STATE, "desktop-widgets-preset.json")
UNDO = os.path.join(STATE, "desktop-widgets-undo.json")
STYLE = os.path.join(STATE, "desktop-widgets-style.json")
# look: "xp" — окно с полосой заголовка (в Настройках «Обычный»); "skeet" и "beta" — окна
# в духе одноимённых видов Настроек (03.10.2026, «переключение стилей и для виджетов, такие
# же как у Настроек»); "classic" — как было до 02.10 («Без рамок»): плашка с тонкой рамкой
# без заголовка (двигать и убирать — через «Расставить»).
# looks — вид отдельно для монитора ({"eDP-1": "classic"}); нет записи — берётся look.
# under — анимировать ли виджеты, закрытые окнами. пользователь сперва попросил «пусть двигаются
# и под окнами», а узнав цену (четверть ядра) — «остановим, если их не видно на мониторе».
# shadow — маленькая «пиксельная» тень справа и снизу (03.10.2026, по образцу AngelOS).
LOOKS = ("xp", "skeet", "beta", "classic")
STYLE_DEFAULT = {"look": "xp", "looks": {}, "transparent": True, "opacity": 62, "blur": 16,
                 "under": False, "shadow": False}
PEEK_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "desktop-widgets-peek")


def load_style():
    st = dict(STYLE_DEFAULT)
    try:
        st.update({k: v for k, v in json.load(open(STYLE)).items() if k in STYLE_DEFAULT})
    except (OSError, ValueError):
        pass
    st["opacity"] = max(0, min(100, int(st["opacity"])))
    st["blur"] = max(0, min(40, int(st["blur"])))
    st["transparent"] = bool(st["transparent"])
    st["under"] = bool(st["under"])
    st["shadow"] = bool(st["shadow"])
    st["look"] = st["look"] if st["look"] in LOOKS else "xp"
    st["looks"] = {k: v for k, v in (st.get("looks") or {}).items() if v in LOOKS} \
        if isinstance(st.get("looks"), dict) else {}
    return st


def look_of(st, output):
    return st["looks"].get(output, st["look"])


def save_style(st):
    os.makedirs(STATE, exist_ok=True)
    with open(STYLE + ".tmp", "w") as f:
        json.dump(st, f)
    os.replace(STYLE + ".tmp", STYLE)


DASH_TYPES = {"tmatrix": "matrix", "tmatrix2": "matrix", "date": "date", "pomo": "pomo",
              "tclock": "clock", "cava": "cava", "brrt": "sprite", "ffetch": "sysinfo"}


# ── раскладка ───────────────────────────────────────────────────────────────

def niri_json(*args):
    try:
        out = subprocess.run(["niri", "msg", "-j", *args], capture_output=True, text=True,
                             timeout=2).stdout
        return json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


DESKS = os.path.join(STATE, "desktop-widgets-desks.json")
DESKS_UNDO = os.path.join(STATE, "desktop-widgets-desks-undo.json")


def desk_at(at):
    """Точка «X,Y» → (монитор, его активный стол {slot, idx, name})."""
    try:
        x, y = (int(float(v)) for v in at.split(","))
    except ValueError:
        return None, None
    out = None
    for name, o in (niri_json("outputs") or {}).items():
        lg = o.get("logical") or {}
        if lg and lg["x"] <= x < lg["x"] + lg["width"] and lg["y"] <= y < lg["y"] + lg["height"]:
            out = name
    for w in niri_json("workspaces") or []:
        if w.get("output") == out and w.get("is_active"):
            name = w.get("name") or ""
            slot = len(name) - len(name.lstrip("\u2060"))      # метка стола, как slot_of (MK)
            return out, {"slot": slot, "idx": w.get("idx"), "name": w.get("name")}
    return out, None


def on_desk(w, out, cur):
    """Виден ли виджет на этом столе — как Manager.desk_widgets: этот монитор, не
    закреплён на всех столах; без привязки к столу — виден на любом."""
    if w.get("output") != out or w.get("pinned"):
        return False
    ws = w.get("ws") or {}
    if not ws:
        return True
    if ws.get("slot"):
        return ws["slot"] == cur.get("slot")
    if ws.get("name"):
        return ws["name"] == cur.get("name")
    return ws.get("idx") == cur.get("idx")


def desk_load(path, key):
    try:
        return json.load(open(path)).get(key, {}).get("widgets")
    except (OSError, ValueError, AttributeError):
        return None


def desk_store(path, key, widgets):
    try:
        d = json.load(open(path))
    except (OSError, ValueError):
        d = {}
    d[key] = {"saved": int(time.time()), "widgets": widgets}
    with open(path + ".tmp", "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def default_layout():
    """Раскладка по образцу дашборда: живые окна dash-*, иначе dashboard.json."""
    try:
        dash = json.load(open(DASH_JSON))
    except (OSError, ValueError):
        dash = {}
    out = dash.get("output", "")
    live = {}
    for w in niri_json("windows") or []:
        app = w.get("app_id") or ""
        lay = w.get("layout") or {}
        pos = lay.get("tile_pos_in_workspace_view")
        if app.startswith("dash-") and pos:
            # плитка целиком, с рамкой niri: рамка виджета ляжет точно на рамку окна
            size = lay.get("tile_size") or [300, 200]
            live[app[5:]] = (int(pos[0]), int(pos[1]), int(size[0]), int(size[1]))
    items = []
    for w in dash.get("windows", []):
        kind = DASH_TYPES.get(w.get("name"))
        if not kind:
            continue
        x, y, ww, hh = live.get(w["name"], (w.get("x", 0), w.get("y", 0), w.get("w", 300), w.get("h", 200)))
        items.append({"name": w["name"], "type": kind, "output": out, "x": x, "y": y,
                      "w": ww, "h": hh + 22, "pinned": True, "v": 2, "opts": {}})
    if not items:
        outs = niri_json("outputs") or {}
        out = next(iter(outs), "")
        lg = (outs.get(out) or {}).get("logical") or {"width": 1920, "height": 1080}
        cx = lg["width"] // 2
        items = [{"name": "date", "type": "date", "output": out, "x": cx - 400, "y": 60,
                  "w": 799, "h": 130, "opts": {}},
                 {"name": "clock", "type": "clock", "output": out, "x": cx - 306, "y": 220,
                  "w": 612, "h": 111, "opts": {}}]
    return {"widgets": items}


def load_conf():
    try:
        c = json.load(open(CONF))
        if isinstance(c.get("widgets"), list):
            changed = False
            for w in c["widgets"]:
                # раскладки до 02.10 (до кнопки «закрепить») показывались на всех столах
                w.setdefault("pinned", True)
                if w.get("v", 1) < 2:
                    # у окна появилась полоса заголовка: растём вверх на её высоту, чтобы
                    # содержимое осталось того же размера и на том же месте
                    w["v"] = 2
                    w["h"] = int(w["h"]) + 22
                    w["y"] = max(0, int(w["y"]) - 22)
                    changed = True
            if changed:
                save_conf(c)
            return c
    except (OSError, ValueError):
        pass
    c = default_layout()
    save_conf(c)
    return c


def niri_request(obj):
    """Запрос в сокет niri (то, чего нет в `niri msg`: действия по id стола)."""
    import socket
    try:
        sk = socket.socket(socket.AF_UNIX)
        sk.settimeout(2)
        sk.connect(os.environ["NIRI_SOCKET"])
        sk.sendall(json.dumps(obj).encode() + b"\n")
        r = sk.makefile().readline()
        sk.close()
        return json.loads(r)
    except (OSError, ValueError, KeyError):
        return None


def save_conf(c):
    os.makedirs(STATE, exist_ok=True)
    with open(CONF + ".tmp", "w") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    os.replace(CONF + ".tmp", CONF)


def daemon_pids():
    me, out = os.getpid(), []
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) != me:
            try:
                argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if len(argv) >= 2 and b"python" in os.path.basename(argv[0]) \
                    and os.path.basename(argv[1]) == b"desktop_widgets.py" \
                    and (len(argv) == 2 or argv[2] == b""):
                out.append(int(p))
    return out


def start_daemon():
    if daemon_pids():
        return
    log = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "desktop-widgets.log")
    if os.environ.get("NIRI_SOCKET"):
        r = subprocess.run(["niri", "msg", "action", "spawn", "--", "sh", "-c",
                            'exec python3 "$0" 2>>"$1"', os.path.abspath(__file__), log],
                           capture_output=True)
        if r.returncode == 0:
            return
    subprocess.Popen([sys.executable, os.path.abspath(__file__)], stdout=subprocess.DEVNULL,
                     stderr=open(log, "a"), start_new_session=True)


def send(sig):
    pids = daemon_pids()
    for pid in pids:
        try:
            os.kill(pid, sig)
        except OSError:
            pass
    return bool(pids)


def unique_name(conf, base):
    names = {w.get("name") for w in conf["widgets"]}
    if base not in names:
        return base
    i = 2
    while "%s%d" % (base, i) in names:
        i += 1
    return "%s%d" % (base, i)


def fixed_ws_name(name):
    """Имя стола задано руками/в конфиге: без меток служб (ZWSP у значков, U+2060 у виджетов)."""
    return bool(name) and "\u200b" not in name and "\u2060" not in name


def parse_timer(words):
    """Слова как у команды timer → (надпись, конец отсчёта или None — секундомер).
    Время: 25m, 1h30m, 90s, 90 (секунды, как у termdown), 07:30 (ближайшие такие часы);
    всё прочее — надпись."""
    import datetime
    label, secs, end = [], 0, None
    for w in words:
        if re.fullmatch(r"(\d+[dhmsDHMS]?)+", w):
            for n, u in re.findall(r"(\d+)([dhms]?)", w.lower()):
                secs += int(n) * {"d": 86400, "h": 3600, "m": 60, "s": 1, "": 1}[u]
        elif re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", w):
            p = [int(v) for v in w.split(":")] + [0]
            now = datetime.datetime.now()
            t = now.replace(hour=p[0] % 24, minute=p[1] % 60, second=p[2] % 60, microsecond=0)
            if t <= now:
                t += datetime.timedelta(days=1)
            end = t.timestamp()
        else:
            label.append(w)
    if end is None and secs:
        end = time.time() + secs
    return " ".join(label), end


def ask_timer(prompt="timer.exe"):
    """Окно ввода «название и время» (rofi) → слова, как их набрали бы в терминале."""
    r = subprocess.run(["rofi", "-dmenu", "-i", "-p", prompt, "-theme-str",
                        'entry { placeholder: "название и время: tea 5m, work 25m, 07:30"; }'],
                       input="5m\n10m\n15m\n25m\n45m\n1h\n", capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return r.stdout.split()


def parse_value(v):
    if v in ("true", "on", "yes"):
        return True
    if v in ("false", "off", "no"):
        return False
    for t in (int, float):
        try:
            return t(v)
        except ValueError:
            pass
    return v


def cli(a):
    if a[0] in ("on", "off", "status"):
        if a[0] == "on":
            try:
                os.remove(OFF)
            except OSError:
                pass
            start_daemon()
        elif a[0] == "off":
            os.makedirs(STATE, exist_ok=True)
            open(OFF, "w").close()
            send(signal.SIGTERM)
        print("off" if os.path.exists(OFF) else "on")
    elif a[0] == "edit":
        if os.path.exists(OFF):
            os.remove(OFF)
        if not send(signal.SIGUSR1):
            start_daemon()
            for _ in range(40):
                time.sleep(0.1)
                if daemon_pids():
                    break
            time.sleep(0.8)
            send(signal.SIGUSR1)
    elif a[0] == "peek":
        # peek — переключить; peek on|off — привести к нужному; peek status — on|off
        now = os.path.exists(PEEK_FLAG)
        if len(a) > 1 and a[1] == "status":
            print("on" if now else "off")
        elif len(a) == 1 or (a[1] == "on") != now:
            send(signal.SIGUSR2)
    elif a[0] == "look":
        # look [МОНИТОР] — вид (xp|skeet|beta|classic); look МОНИТОР ВИД — задать монитору;
        # look all ВИД — всем сразу
        st = load_style()
        if len(a) >= 3 and a[2] in LOOKS:
            if a[1] == "all":
                st["look"], st["looks"] = a[2], {}
            else:
                st["looks"][a[1]] = a[2]
            save_style(st)
            print(a[2])
        else:
            print(look_of(st, a[1]) if len(a) > 1 else st["look"])
    elif a[0] == "list":
        for w in load_conf()["widgets"]:
            where = "все столы" if w.get("pinned") else "стол %s (метка %s)" % (
                (w.get("ws") or {}).get("idx", "?"), (w.get("ws") or {}).get("slot", "—"))
            print("%-12s %-10s %-7s %4d,%-4d %4dx%-4d %-10s %s" % (
                w["name"], w["type"], w.get("output", ""), w["x"], w["y"], w["w"], w["h"], where,
                json.dumps(w.get("opts") or {}, ensure_ascii=False) if w.get("opts") else ""))
    elif a[0] == "types":
        for k, (title, w, h) in TYPES.items():
            print("%-11s %-16s %-22s %dx%d" % (k, EXE.get(k, ""), title, w, h))
    elif a[0] == "add" and len(a) > 1 and a[1] in TYPES:
        # add ТИП [МОНИТОР] [at=X,Y] [pinned=1] [ключ=значение…] — at: точка на общем
        # полотне мониторов (меню ПКМ передаёт место щелчка), остальное — в opts
        c = load_conf()
        outs = niri_json("outputs") or {}
        kv = dict(x.split("=", 1) for x in a[2:] if "=" in x)
        pos = [x for x in a[2:] if "=" not in x]
        out = pos[0] if pos else ((niri_json("focused-output") or {}).get("name") or next(iter(outs), ""))
        _t, w, h = TYPES[a[1]]
        at = None
        if "at" in kv:
            try:
                gx, gy = (int(float(v)) for v in kv.pop("at").split(","))
                for name, o in outs.items():
                    lg = o.get("logical") or {}
                    if lg and lg["x"] <= gx < lg["x"] + lg["width"] and lg["y"] <= gy < lg["y"] + lg["height"]:
                        out, at = name, (gx - lg["x"], gy - lg["y"])
            except ValueError:
                pass
        lg = (outs.get(out) or {}).get("logical") or {"width": 1920, "height": 1080}
        w, h = min(w, lg["width"]), min(h, lg["height"])
        x, y = at if at else ((lg["width"] - w) // 2, (lg["height"] - h) // 2)
        if at:
            x, y = x - w // 2, y - 11
        pinned = kv.pop("pinned", "0") in ("1", "true", "on", "yes")
        if a[1] == "banner" and kv.pop("ask", None) is not None and "text" not in kv:
            r = subprocess.run(["rofi", "-dmenu", "-p", "banner.exe", "-lines", "0",
                                "-theme-str", 'entry { placeholder: "текст надписи"; }'],
                               input="", capture_output=True, text=True)
            if r.returncode != 0 or not r.stdout.strip():
                return
            kv["text"] = r.stdout.strip()
        name = unique_name(c, a[1])
        c["widgets"].append({"name": name, "type": a[1], "output": out,
                             "x": max(0, min(lg["width"] - w, x)), "y": max(0, min(lg["height"] - h, y)),
                             "w": w, "h": h, "pinned": pinned, "v": 2, "autoplace": True,
                             "opts": {k: parse_value(v) for k, v in kv.items()}})
        save_conf(c)
        if not send(signal.SIGHUP):
            start_daemon()
        print(name)
    elif a[0] == "timer":
        # timer [at=X,Y] [ask=1] [название] [время] — таймер-виджет; без времени — секундомер.
        # Не закреплён, как и прочие (просьба: «почему таймер закреплён по умолчанию?»).
        # Таймер с таким же названием уже есть — перезапускается он, второй не создаётся.
        kv = [x for x in a[1:] if re.match(r"^(at|ask|url)=", x)]
        words = [x for x in a[1:] if x not in kv]
        url = next((x[4:] for x in kv if x.startswith("url=")), "")
        if any(x.startswith("ask=") for x in kv):
            words = ask_timer()
            if not words:
                return
        label, end = parse_timer(words)
        opts = {"label": label} if label else {}
        if url:
            opts["url"] = url          # что открыть, когда таймер дозвонит (кнопка в уведомлении)
        if end:
            opts.update(end=int(end), dur=int(end - time.time()))
        else:
            opts["start"] = int(time.time())
        c = load_conf()
        old = next((w for w in c["widgets"] if w.get("type") == "timer" and label
                    and str((w.get("opts") or {}).get("label", "")) == label), None)
        if old:
            keep = {k: v for k, v in (old.get("opts") or {}).items() if k in ("frame", "title", "url")}
            old["opts"] = {**keep, **opts}
            save_conf(c)
            send(signal.SIGHUP)
            print(old["name"])
            return
        args = ["add", "timer"] + [x for x in kv if x.startswith("at=")]
        cli(args + ["%s=%s" % (k, v) for k, v in opts.items()])
    elif a[0] in ("preset", "clear") and any(x.startswith("here=") for x in a):
        # «Управление виджетами» из меню рабочего стола — только стол, где открыли меню
        # (05.10.2026). here=X,Y — точка щелчка; по ней монитор и его стол.
        # Свои файлы на каждый стол: desktop-widgets-desks.json (пресеты) и
        # desktop-widgets-desks-undo.json (что было перед «Удалить»).
        at = next(x for x in a if x.startswith("here="))[5:]
        out, cur = desk_at(at)
        if not out or not cur:
            print("стол не найден")
            return
        key = "%s#%s" % (out, cur.get("slot") or "idx%s" % cur.get("idx"))
        c = load_conf()
        mine = [w for w in c["widgets"] if on_desk(w, out, cur)]
        verb = a[1] if a[0] == "preset" and len(a) > 1 else "clear"
        if verb == "save":
            desk_store(DESKS, key, mine)
            subprocess.run(["notify-send", "-a", "Widgets", "Пресет стола сохранён",
                            "Виджетов: %d" % len(mine)], capture_output=True)
            print(len(mine))
        elif verb == "status":
            print("preset" if desk_load(DESKS, key) is not None else
                  "undo" if desk_load(DESKS_UNDO, key) is not None else "none")
        elif verb == "restore":
            saved = desk_load(DESKS, key)
            if saved is None:
                saved = desk_load(DESKS_UNDO, key)
            if saved is None:
                print("нечего восстанавливать")
                return
            for w in saved:
                w["output"] = out
                if not w.get("pinned"):
                    w["ws"] = {k: v for k, v in cur.items() if v}
                o = w.get("opts") or {}
                if w.get("type") == "timer" and "dur" in o:
                    for k in ("end", "rang", "paused_elapsed"):
                        o.pop(k, None)
                    o["paused_left"] = int(o["dur"])
            names = {w.get("name") for w in saved}
            rest = [w for w in c["widgets"] if not on_desk(w, out, cur) and w.get("name") not in names]
            save_conf({"widgets": rest + saved})
            if not send(signal.SIGHUP):
                start_daemon()
            print(len(saved))
        elif verb == "clear":
            if mine:
                desk_store(DESKS_UNDO, key, mine)
            save_conf({"widgets": [w for w in c["widgets"] if not on_desk(w, out, cur)]})
            send(signal.SIGHUP)
            print(len(mine))
    elif a[0] == "preset" and len(a) > 1:
        # preset save — запомнить нынешнюю раскладку; preset restore — вернуть её (нет
        # пресета — вернуть то, что было перед «clear»); preset status — есть ли что вернуть
        if a[1] == "save":
            c = load_conf()
            with open(PRESET + ".tmp", "w") as f:
                json.dump({"saved": int(time.time()), "widgets": c["widgets"]}, f, ensure_ascii=False, indent=1)
            os.replace(PRESET + ".tmp", PRESET)
            subprocess.run(["notify-send", "-a", "Widgets", "Пресет сохранён",
                            "Виджетов: %d" % len(c["widgets"])], capture_output=True)
            print(len(c["widgets"]))
        elif a[1] == "status":
            print("preset" if os.path.exists(PRESET) else "undo" if os.path.exists(UNDO) else "none")
        elif a[1] == "restore":
            src = PRESET if os.path.exists(PRESET) else UNDO
            try:
                saved = json.load(open(src))["widgets"]
            except (OSError, ValueError, KeyError):
                print("нечего восстанавливать")
                return
            for w in saved:
                ws = w.get("ws") or {}
                # метка стола (slot) к этому моменту могла достаться другому столу —
                # возвращаем по номеру стола (или постоянному имени), метку сторож даст заново
                w["ws"] = {k: v for k, v in ws.items() if k in ("idx", "name") and
                           (k != "name" or fixed_ws_name(v))} or None
                o = w.get("opts") or {}
                if w.get("type") == "timer" and "dur" in o:
                    # таймер из пресета не «досчитывает» старое время: ждёт на паузе с полным сроком
                    for k in ("end", "rang", "paused_elapsed"):
                        o.pop(k, None)
                    o["paused_left"] = int(o["dur"])
            save_conf({"widgets": saved})
            if not send(signal.SIGHUP):
                start_daemon()
            print(len(saved))
    elif a[0] == "clear":
        # убрать все виджеты; раскладка перед этим сохраняется — «Восстановить» её вернёт,
        # если своего пресета нет
        c = load_conf()
        if c["widgets"]:
            with open(UNDO + ".tmp", "w") as f:
                json.dump({"saved": int(time.time()), "widgets": c["widgets"]}, f, ensure_ascii=False, indent=1)
            os.replace(UNDO + ".tmp", UNDO)
        save_conf({"widgets": []})
        send(signal.SIGHUP)
        print(0)
    elif a[0] == "set" and len(a) > 2:
        # set ИМЯ x=.. y=.. w=.. h=.. pinned=0|1 output=.. ключ=значение (прочее — в opts)
        c = load_conf()
        for w in c["widgets"]:
            if w.get("name") == a[1]:
                for item in a[2:]:
                    k, _, v = item.partition("=")
                    if k in ("x", "y", "w", "h"):
                        w[k] = int(float(v))
                    elif k == "pinned":
                        w[k] = v in ("1", "true", "on", "yes")
                    elif k == "output":
                        w[k] = v
                    else:
                        w.setdefault("opts", {})[k] = parse_value(v)
        save_conf(c)
        send(signal.SIGHUP)
    elif a[0] == "style":
        # style → всё; style КЛЮЧ → значение; style КЛЮЧ ЗНАЧЕНИЕ → записать
        st = load_style()
        if len(a) == 1:
            print(json.dumps(st))
        elif len(a) == 2:
            v = st.get(a[1], "")
            print(("on" if v else "off") if isinstance(v, bool) else v)
        elif a[1] in STYLE_DEFAULT:
            if a[1] == "looks" or (a[1] == "look" and a[2] not in LOOKS):
                return
            st[a[1]] = (a[2] in ("1", "on", "true", "yes")) if a[1] in ("transparent", "under", "shadow") else (
                a[2] if a[1] == "look" else int(float(a[2])))
            if a[1] == "look":
                st["looks"] = {}             # общий вид задан заново — поштучные сброшены
            save_style(st)
            print(a[2])
    elif a[0] == "remove" and len(a) > 1:
        c = load_conf()
        c["widgets"] = [w for w in c["widgets"] if w.get("name") != a[1]]
        save_conf(c)
        send(signal.SIGHUP)
    elif a[0] == "reset":
        save_conf(default_layout())
        send(signal.SIGHUP)
    elif a[0] == "reload":
        send(signal.SIGHUP)
    else:
        print(__doc__)


if sys.argv[1:]:
    cli(sys.argv[1:])
    sys.exit(0)
# JARVIS_WIDGETS_TEST=1 — для проверок вне экрана: не выходить при живом стороже
# (раскладку тогда берут из JARVIS_WIDGETS_CONF, чтобы не трогать настоящую).
if (os.path.exists(OFF) or daemon_pids()) and os.environ.get("JARVIS_WIDGETS_TEST") != "1":
    sys.exit(0)
# Пока грузится GTK, сигналы управления игнорируем: SIGHUP/USR1/USR2, пришедшие в
# первые полсекунды (on → reset подряд), по умолчанию убивают процесс.
for _sig in (signal.SIGHUP, signal.SIGUSR1, signal.SIGUSR2):
    signal.signal(_sig, signal.SIG_IGN)

# ── дальше — сторож ─────────────────────────────────────────────────────────
import ctypes  # noqa: E402
import datetime  # noqa: E402
import math  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

_libc = ctypes.CDLL(None, use_errno=True)


def _pdeathsig():
    _libc.prctl(1, signal.SIGTERM, 0, 0, 0)      # PR_SET_PDEATHSIG


def gaming():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open("/proc/%s/comm" % p, "rb").read().strip() in GAMES:
                    return True
            except OSError:
                pass
    return False


# ── цвета ───────────────────────────────────────────────────────────────────

def hexrgb(h, default=(0.5, 0.6, 1.0)):
    try:
        h = h.strip().lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, IndexError, AttributeError):
        return default


XTERM16 = ["#000000", "#cd0000", "#00cd00", "#cdcd00", "#0000ee", "#cd00cd", "#00cdcd", "#e5e5e5",
           "#7f7f7f", "#ff0000", "#00ff00", "#ffff00", "#5c5cff", "#ff00ff", "#00ffff", "#ffffff"]
T = {}


def load_theme():
    """Акцент — vivid.txt (чистый акцент обоев, как у часов и даты дашборда),
    «голова» струи и рамка — primary из colors.json, фон и 16 цветов — палитра kitty."""
    def read(name):
        try:
            return open(os.path.join(MATUGEN, name)).read()
        except OSError:
            return ""
    T["accent"] = hexrgb(read("vivid.txt") or "#7aa2f7")
    try:
        cj = json.loads(read("colors.json") or "{}")
    except ValueError:
        cj = {}
    T["primary"] = hexrgb(cj.get("primary", "#b4c5ff"))
    kitty = dict(l.split(None, 1) for l in read("colors-kitty.conf").splitlines()
                 if len(l.split(None, 1)) == 2 and not l.startswith("#"))
    T["bg"] = hexrgb(kitty.get("background", "#10131c"), (0.06, 0.07, 0.11))
    T["fg"] = hexrgb(kitty.get("foreground", "#e1e1ef"), (0.88, 0.88, 0.94))
    T["ansi"] = [hexrgb(kitty.get("color%d" % i, XTERM16[i])) for i in range(16)]
    # полоса заголовка — те же тона, что у «Пуска», XP-панели и заголовка Настроек
    try:
        import xpbar_colors
        xc = xpbar_colors.colors()
    except Exception:
        xc = {}
    for k, d in (("st_hi", "#9fb4f5"), ("st_top", "#7f95d8"), ("st_mid", "#5f74b4"),
                 ("st_bot", "#465a94"), ("st_hover", "#8ea4e8"), ("st_dark", "#0a0c12"),
                 ("line2", "#3a4a7a"), ("on_surface", "#e1e1ef"), ("error", "#ffb4ab")):
        T[k] = hexrgb(xc.get(k, d), hexrgb(d))
    T["style"] = load_style()
    pal = {k: hexrgb(cj.get(k, d), hexrgb(d)) for k, d in (
        ("primary", "#b4c5ff"), ("on_primary", "#002979"), ("secondary", "#c5c2ea"),
        ("tertiary", "#d2bdf6"), ("surface", "#10131c"), ("surface_container", "#1d1f29"),
        ("surface_high", "#272a34"), ("on_surface", "#e1e1ef"),
        ("on_surface_variant", "#c4c6d3"), ("error", "#ffb4ab"))}
    T["sk"] = skeet_colors(T["accent"], pal)
    T["bt"] = beta_colors(pal)


def mix(a, b, t):
    """Смесь двух цветов (r, g, b) 0…1: t=0 — a, t=1 — b."""
    return tuple(x * (1 - t) + y * t for x, y in zip(a, b))


def skeet_colors(acc, p):
    """Цвета вида skeet — те же формулы, что у skeet_colors() в settings_app.py: серые
    оригинала (#131313, #282828, #3c3c3c…) чуть подкрашены акцентом обоев (vivid.txt)."""
    def g(level, t=0.05):
        return mix((level / 255,) * 3, acc, t)
    line1 = g(0x3c, 0.08)
    return {
        "acc": acc, "acc_l": mix(acc, (1, 1, 1), 0.22), "acc_d": mix(acc, (0, 0, 0), 0.40),
        "bg": g(0x13), "field": g(0x1b), "field_l": g(0x24),
        "line1": mix(line1, acc, 0.45),          # светлые линии рамки — как у активного окна
        "line2": g(0x28, 0.06), "line3": g(0x0a, 0.03), "gline": g(0x30, 0.08),
        "icon": g(0x5c, 0.10), "dot": g(0x18, 0.05),
        "text": mix((0xcd / 255,) * 3, p["on_surface"], 0.35), "text_dim": g(0x92, 0.10),
        # полоска сверху — три тона палитры, под ней та же полоска темнее
        "strip": [acc, p["tertiary"], p["secondary"]],
        "err": p["error"],
    }


def beta_colors(p):
    """Цвета вида beta — как у Beta·Dark в settings_app.py (beta_colors): плоская полоса
    заголовка тоном surface_container, линии — on_surface поверх фона, акцент — primary."""
    bg = p["surface"]
    return {
        "bg": bg, "bar": mix(bg, p["surface_container"], 0.85), "field": p["surface_high"],
        "text": p["on_surface"], "dim": mix(p["on_surface_variant"], bg, 0.30),
        "acc": p["primary"], "on_acc": p["on_primary"],
        "line": mix(p["surface_container"], p["on_surface"], 0.16),
        "line_strong": mix(bg, p["on_surface"], 0.32),
        "tiles": beta_tiles(p), "ink": hexrgb("#f4f4fa"), "err": p["error"],
    }


def beta_tiles(p, n=6):
    """Плитки-значки Beta (как beta_tiles в settings_app.py): тон primary / tertiary /
    secondary, у каждой следующей тройки сдвинутый; светлота и насыщенность общие."""
    import colorsys
    out = []
    shifts = (0.0, 60.0, -60.0, 120.0)
    bases = [p["primary"], p["tertiary"], p["secondary"]]
    for i in range(n):
        h, _l, _s = colorsys.rgb_to_hls(*bases[i % 3])
        h = (h + shifts[(i // 3) % len(shifts)] / 360.0) % 1.0
        out.append(colorsys.hls_to_rgb(h, 0.47, 0.46))
    return out


def font_desc(px):
    fd = Pango.FontDescription(FONT)
    fd.set_absolute_size(px * Pango.SCALE)
    return fd


# Адаптивная вёрстка (02.10.2026: «как адаптивный дизайн в вебе — сжимаю, и всё
# сжимается и умещается; растягиваю — тянется под размер»): кегль подбирается под место.
SIZES = (8, 10, 12, 14, 16, 20, 24, 28, 32, 40, 48, 56, 64)
_ADV = {}


def adv(px):
    """Ширина знака шрифта при кегле px (шрифт моноширинный; спрашиваем у Pango)."""
    if px not in _ADV:
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8))
        crisp(cr)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(font_desc(px))
        lay.set_text("M" * 20, -1)
        _ADV[px] = lay.get_pixel_size()[0] / 20
    return _ADV[px]


def fit_px(chars, w, h, top=64, low=8):
    """Самый крупный кегль, при котором строка из chars знаков входит в w×h."""
    best = low
    for px in SIZES:
        if low <= px <= top and px <= h and chars * adv(px) <= w:
            best = px
    return best


def draw_digits(cr, text, x, y, w, h, color):
    """Время цифрами 3×5 во весь прямоугольник — глифы и раскладка jclock."""
    widest = sum(2 if c == ":" else 6 for c in text) + len(text) - 1
    cw = max(1, int(min(w / widest, h * 0.75 / 5)))
    ch = max(1, round(cw / 0.75))
    cells = sum(2 * len(DIGITS.get(c, ("000",))[0]) for c in text) + len(text) - 1
    cx = x + (w - cells * cw) // 2
    y0 = y + (h - 5 * ch) // 2
    cr.set_source_rgb(*color)
    for c in text:
        g = DIGITS.get(c)
        if not g:
            continue
        draw_bitmap(cr, [[bit == "1" for bit in row] for row in g], cx, y0, 2 * cw, ch)
        cx += (2 * len(g[0]) + 1) * cw
    return cw


def crisp(cr):
    fo = cairo.FontOptions()
    fo.set_antialias(cairo.ANTIALIAS_GRAY)
    fo.set_hint_style(cairo.HINT_STYLE_FULL)
    fo.set_hint_metrics(cairo.HINT_METRICS_ON)
    PangoCairo.context_set_font_options(PangoCairo.create_context(cr), fo)
    cr.set_font_options(fo)


def draw_bitmap(cr, bmp, x, y, pw, ph):
    """Пиксели глифов прямоугольниками pw×ph; соседние в строке сливаются в один."""
    for r, row in enumerate(bmp):
        c, n = 0, len(row)
        while c < n:
            if row[c]:
                e = c
                while e < n and row[e]:
                    e += 1
                cr.rectangle(x + c * pw, y + r * ph, (e - c) * pw, ph)
                c = e
            else:
                c += 1
    cr.fill()


class Backdrop:
    """Размытые обои под плашкой — считаем сами, а не просим niri.

    Виджет лежит прямо на обоях, значит «что под ним» известно заранее: берём
    картинку, которую показывает awww на этом мониторе, вписываем как он (заполнить
    с обрезкой по центру), размываем с нужной силой — и каждый виджет рисует свой
    кусок. Плюсы: сила размытия настраивается ползунком (у правила слоя niri её
    нет), а niri не тратит кадр на размытие под восемью слоями (было +10 % CPU).
    """

    def __init__(self):
        self.cache = {}

    def invalidate(self):
        self.cache = {}

    @staticmethod
    def sources():
        out = {}
        try:
            txt = subprocess.run(["awww", "query"], capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return out
        for l in txt.splitlines():
            m = re.match(r"^:?\s*([\w-]+):.*?image:\s*(.+?)\s*$", l)
            if m:
                out[m.group(1)] = m.group(2)
        return out

    def get(self, output, w, h):
        blur = T["style"]["blur"]
        key = (output, w, h, blur)
        if key not in self.cache:
            self.cache = {k: v for k, v in self.cache.items() if k[0] != output}
            self.cache[key] = self.build(output, w, h, blur)     # (поверхность, её буфер)
        return self.cache[key][0]

    def build(self, output, w, h, blur):
        try:
            import numpy as np
            from PIL import Image, ImageFilter, ImageOps
            path = self.sources().get(output)
            if not path or not os.path.exists(path):
                return None, None
            im = Image.open(path)
            im.seek(0)
            # размываем уменьшенную вчетверо копию: после размытия разницы не видно,
            # а считается в шестнадцать раз быстрее
            k = 4
            small = ImageOps.fit(im.convert("RGB"), (max(1, w // k), max(1, h // k)), Image.BILINEAR)
            small = small.filter(ImageFilter.GaussianBlur(blur / k))
            arr = np.asarray(small.resize((w, h), Image.BILINEAR).convert("RGBA"))
            buf = np.ascontiguousarray(arr[..., [2, 1, 0, 3]])
            surf = cairo.ImageSurface.create_for_data(memoryview(buf), cairo.FORMAT_RGB24, w, h, w * 4)
            return surf, buf                  # буфер держим рядом: cairo его не копирует
        except Exception as e:
            print("подложка %s: %s" % (output, e), file=sys.stderr)
            return None, None


MK = "\u2060"        # невидимый знак-метка в начале имени стола с виджетами (см. Manager.bind_ws)


def fixed_name(name):
    """Имя стола задано руками/в конфиге: без меток служб (ZWSP у значков, MK у виджетов)."""
    return bool(name) and "\u200b" not in name and MK not in name


def slot_of(name):
    """Метка стола: сколько знаков MK в начале имени (0 — стол не наш)."""
    n = 0
    for ch in name or "":
        if ch != MK:
            break
        n += 1
    return n


VISIBLE, FROZEN, HIDDEN = 0, 1, 2
LAYOUT_KDL = os.path.expanduser("~/.config/niri/cfg/layout.kdl")


# ── что видно: столы и окна niri ────────────────────────────────────────────

class Niri:
    """Следит за потоком событий niri: активный стол каждого монитора и окна на нём."""

    def __init__(self, on_change):
        self.on_change = on_change
        self.lock = threading.Lock()
        self.ws, self.win = {}, {}
        self.overview = False
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while True:
            try:
                p = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, preexec_fn=_pdeathsig)
                for line in p.stdout:
                    try:
                        self.handle(json.loads(line))
                    except ValueError:
                        pass
                p.wait()
            except OSError:
                pass
            time.sleep(2)

    def handle(self, ev):
        with self.lock:
            if "WorkspacesChanged" in ev:
                self.ws = {w["id"]: w for w in ev["WorkspacesChanged"]["workspaces"]}
            elif "WorkspaceActivated" in ev:
                wid = ev["WorkspaceActivated"]["id"]
                out = (self.ws.get(wid) or {}).get("output")
                for w in self.ws.values():
                    if w.get("output") == out:
                        w["is_active"] = w["id"] == wid
            elif "WorkspaceActiveWindowChanged" in ev:
                e = ev["WorkspaceActiveWindowChanged"]
                if e["workspace_id"] in self.ws:
                    self.ws[e["workspace_id"]]["active_window_id"] = e.get("active_window_id")
            elif "OverviewOpenedOrClosed" in ev:
                self.overview = bool(ev["OverviewOpenedOrClosed"].get("is_open"))
            elif "WindowsChanged" in ev:
                self.win = {w["id"]: w for w in ev["WindowsChanged"]["windows"]}
            elif "WindowOpenedOrChanged" in ev:
                w = ev["WindowOpenedOrChanged"]["window"]
                self.win[w["id"]] = w
            elif "WindowClosed" in ev:
                self.win.pop(ev["WindowClosed"]["id"], None)
            elif "WindowLayoutsChanged" in ev:
                for wid, lay in ev["WindowLayoutsChanged"]["changes"]:
                    if wid in self.win:
                        self.win[wid]["layout"] = lay
            else:
                return
        # смена стола — срочно (виджеты должны появиться вместе со столом); окна — не к спеху
        GLib.idle_add(self.on_change, "Workspace" in next(iter(ev)))

    def active_ws(self, output):
        """{"name": …, "idx": …} активного стола монитора (для привязки виджета к столу)."""
        with self.lock:
            ws = next((s for s in self.ws.values()
                       if s.get("output") == output and s.get("is_active")), None)
            return {"name": ws.get("name"), "idx": ws.get("idx")} if ws else None

    def on_ws(self, output, want):
        """Активен ли сейчас стол, к которому привязан виджет (по метке стола — числу
        невидимых знаков MK в начале его имени, см. Manager.bind_ws)."""
        if not want or not (want.get("slot") or want.get("name")):
            return True
        cur = self.active_ws(output)
        if cur is None:
            return True
        if want.get("slot"):
            return slot_of(cur.get("name")) == want["slot"]
        return cur.get("name") == want["name"]           # стол с постоянным именем из конфига

    def workspaces(self, output):
        with self.lock:
            return sorted((dict(w) for w in self.ws.values() if w.get("output") == output),
                          key=lambda w: w.get("idx", 0))

    def all_names(self):
        with self.lock:
            return {w.get("name") for w in self.ws.values() if w.get("name")}

    def set_name(self, ws_id, name):
        """Назвать стол (и сразу отметить у себя — событие от niri придёт позже)."""
        niri_request({"Action": {"SetWorkspaceName": {"name": name, "workspace": {"Id": ws_id}}}})
        with self.lock:
            if ws_id in self.ws:
                self.ws[ws_id]["name"] = name

    def unset_name(self, ws_id):
        niri_request({"Action": {"UnsetWorkspaceName": {"reference": {"Id": ws_id}}}})
        with self.lock:
            if ws_id in self.ws:
                self.ws[ws_id]["name"] = None

    def snapshot(self):
        with self.lock:
            return [dict(w) for w in self.ws.values()], [dict(w) for w in self.win.values()]

    def layout_conf(self):
        now = time.monotonic()
        if now - getattr(self, "_lc_at", -99) > 10:
            self._lc_at = now
            try:
                txt = open(LAYOUT_KDL).read()
            except OSError:
                txt = ""
            g = re.search(r"^\s*gaps\s+(\d+)", txt, re.M)
            c = re.search(r'^\s*center-focused-column\s+"(\w+)"', txt, re.M)
            self._lc = (int(g.group(1)) if g else 16, (c.group(1) if c else "never") == "always")
        return self._lc

    def tiled_cover(self, ws, mon_w):
        """Полоса экрана по горизонтали, НАВЕРНЯКА закрытая колонками ленты: (x0, x1) или
        None. Мест окон в ленте niri не сообщает (только плавающих), но их можно
        вывести: колонки стоят вплотную через зазор, а сдвиг ленты ограничен тем, что
        колонка с фокусом целиком на экране.
          * одна колонка — по центру (always-center-single-column);
          * center-focused-column "always" — колонка с фокусом по центру, место точное;
          * иначе сдвиг известен только в пределах; закрытым считаем то, что закрыто при
            ЛЮБОМ допустимом сдвиге. Не уверены — считаем видимым (пусть лучше двигается
            лишний раз, чем замирает на виду: так было с осьминогом).
        Пример пользователя — «виджеты слева, а я прокрутил ленту к другим окнам»: лента шире
        экрана, фокус правее — левая часть экрана закрыта при любом сдвиге."""
        tiled = [w for w in self.win.values()
                 if w.get("workspace_id") == ws["id"] and not w.get("is_floating")]
        if not tiled:
            return None
        cols = {}
        for w in tiled:
            lay = w.get("layout") or {}
            c = (lay.get("pos_in_scrolling_layout") or [1, 1])[0]
            cols[c] = max(cols.get(c, 0), (lay.get("tile_size") or [0, 0])[0])
        gap, center = self.layout_conf()
        order = sorted(cols)
        act = next((w for w in tiled if w["id"] == ws.get("active_window_id")), None) or max(
            tiled, key=lambda w: ((w.get("focus_timestamp") or {}).get("secs", 0),
                                  (w.get("focus_timestamp") or {}).get("nanos", 0)))
        ac = ((act.get("layout") or {}).get("pos_in_scrolling_layout") or [order[0], 1])[0]
        if ac not in cols:
            ac = order[0]
        off = sum(cols[c] + gap for c in order if c < ac)       # начало колонки с фокусом в ленте
        total = sum(cols.values()) + gap * (len(cols) - 1)
        wf = cols[ac]
        if len(cols) == 1 or center:
            lo = hi = (mon_w - wf) / 2 - off
        elif wf >= mon_w - 2 * gap:
            lo = hi = gap - off
        else:
            lo, hi = gap - off, mon_w - gap - wf - off
        x0, x1 = hi, lo + total
        return (x0, x1) if x1 > x0 else None

    def obstacles(self, output, mon_w):
        """Что на активном столе монитора точно закрывает виджет: (прямоугольники плавающих
        окон, полосы колонок ленты). Те же данные, что у state(); для подбора места новому
        виджету (Manager.find_spot)."""
        with self.lock:
            ws = next((s for s in self.ws.values()
                       if s.get("output") == output and s.get("is_active")), None)
            if ws is None:
                return [], []
            rects = []
            for win in self.win.values():
                if win.get("workspace_id") != ws["id"] or not win.get("is_floating"):
                    continue
                lay = win.get("layout") or {}
                pos, size = lay.get("tile_pos_in_workspace_view"), lay.get("tile_size")
                if pos and size:
                    rects.append((pos[0], pos[1], pos[0] + size[0], pos[1] + size[1]))
            cover = self.tiled_cover(ws, mon_w)
            return rects, ([cover] if cover else [])

    def state(self, output, x, y, w, h, mon_w, mon_h):
        """Что с виджетом на активном столе его монитора:
        VISIBLE — виден, анимация идёт;
        FROZEN  — закрыт окнами на 85 % и больше: стоит на месте, анимация остановлена.
        С экрана из-за окон виджет больше НЕ снимается (02.10.2026): окна у пользователя
        полупрозрачные, и под плавающим окном было видно, как виджеты «испаряются», а
        после закрытия окна возвращаются. Снимать их ради экономии незачем — размытие
        под плашкой теперь своё, niri на закрытые слои ничего не тратит.
        Места плавающих окон niri сообщает; колонки ленты — вычисляем (tiled_spans),
        считая, что колонка занимает экран по всей высоте. Покрытие меряется по сетке
        точек, поэтому перекрывающие друг друга окна не считаются дважды."""
        with self.lock:
            if self.overview:
                return VISIBLE
            ws = next((s for s in self.ws.values()
                       if s.get("output") == output and s.get("is_active")), None)
            if ws is None:
                return VISIBLE
            if T["style"]["under"]:
                return VISIBLE                 # «пусть двигаются и под окнами»
            rects = []
            for win in self.win.values():
                if win.get("workspace_id") != ws["id"] or not win.get("is_floating"):
                    continue
                lay = win.get("layout") or {}
                pos, size = lay.get("tile_pos_in_workspace_view"), lay.get("tile_size")
                if pos and size:
                    rects.append((pos[0], pos[1], pos[0] + size[0], pos[1] + size[1]))
            cover = self.tiled_cover(ws, mon_w)
            spans = [cover] if cover else []
            n = hit = 0
            for i in range(8):
                px = x + (i + 0.5) * w / 8
                in_span = any(a <= px < b for a, b in spans)
                for j in range(6):
                    py = y + (j + 0.5) * h / 6
                    n += 1
                    if in_span or any(r[0] <= px < r[2] and r[1] <= py < r[3] for r in rects):
                        hit += 1
            return FROZEN if hit >= 0.85 * n else VISIBLE


# ── виджет ──────────────────────────────────────────────────────────────────

BORDER = 3          # рамка окна в цвет заголовка, как у окон XP
RING = 5            # прежний вид: полупрозрачная рамка, как у окон niri
TB = 22             # высота полосы заголовка
PAD = 8
CAP = 16            # кнопки в заголовке
GRIP = 14           # уголок для растягивания
MIN_W, MIN_H = 90, 60

PIN_BMP = ("..####..", "..####..", "..####..", ".######.", "...##...", "...##...", "...##...", "........")
X_BMP = ("#.....#", ".#...#.", "..#.#..", "...#...", "..#.#..", ".#...#.", "#.....#")
# значки нечётной ширины — чтобы вставали в кнопку ровно по центру
PIN7_BMP = (".#####.", "..###..", "..###..", "#######", "...#...", "...#...", "...#...")
PIN5_BMP = (".###.", ".###.", "#####", "..#..", "..#..")
X5_BMP = ("#...#", ".#.#.", "..#..", ".#.#.", "#...#")

# Геометрия окна каждого вида с заголовком (03.10.2026: к «xp» добавлены «skeet» и «beta» —
# родственники одноимённых видов Настроек). side — рамка слева, справа и снизу; head — где
# начинается содержимое (рамка сверху + полоса заголовка); bar — (y, высота) строки, в которой
# по центру стоят кнопки; cap — сторона кнопки; rm — от кнопки «закрыть» до рамки справа;
# gap — между кнопками. Высота строки и сторона кнопки одной чётности — кнопка встаёт ровно.
#   xp    — рамка 3 px, полоса 22 px в градиенте заголовка Настроек (как было);
#   skeet — рамка gamesense в шесть линий (1 + 3 + 1 + 1), под ней полоска-градиент 2 px,
#           строка 15 px с мелким (8 px) заголовком, снизу две линии-разделителя;
#   beta  — рамка в 1 px, плоская полоса 21 px и линия под ней, как шапка Beta.
FRAMES = {
    "xp": dict(side=BORDER, head=BORDER + TB, bar=(BORDER, TB), cap=CAP, rm=3, gap=3),
    "skeet": dict(side=6, head=25, bar=(8, 15), cap=13, rm=4, gap=2),
    "beta": dict(side=1, head=23, bar=(1, 21), cap=15, rm=3, gap=3),
}


def bmp(rows):
    return [[c == "#" for c in r] for r in rows]


SHADOW = 5
_SK_DOTS = {}       # узор фона skeet по цвету точки (одна плитка 4×4 на всех)


class Widget(Gtk.Window):
    """Окно-виджет в стиле XP: рамка, полоса заголовка «имя.exe», «закрепить» и
    «закрыть», уголок для размера. За полосу виджет таскают мышью (02.10.2026)."""
    interval = 0          # мс между кадрами анимации; 0 — анимации нет
    clickable = False     # True — виджет принимает щелчки и по содержимому (on_click)

    def __init__(self, mgr, spec, monitor):
        super().__init__()
        self.mgr, self.spec, self.monitor = mgr, spec, monitor
        self.opts = spec.get("opts") or {}
        self.timer = None
        self.running = False
        self.ghosted = False           # идёт перенос: сам виджет не рисуется, рисуется его «призрак»
        # «Плащ»: на чужом столе слой НЕ снимается, а рисуется пустым и не принимает мышь.
        # Снятие/возврат слоя занимали заметное время — при переходе между столами
        # виджеты появлялись с опозданием (02.10.2026: «пользователь не должен
        # замечать, что виджеты пропадают»). Пустой слой ничего не стоит, а «появиться» —
        # это один перерисованный кадр.
        self.cloaked = True
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-widget")
        # BOTTOM, а не BACKGROUND: над обоями и над слоем меню рабочего стола (тот
        # на фоне и во весь экран — он забирал бы щелчки по заголовку), под окнами.
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_monitor(self, monitor)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.area.connect("size-allocate", lambda *_a: (self.update_input(), self.resized()))
        self.add(self.area)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("motion-notify-event", self.on_motion)
        for sig in ("realize", "map"):
            self.connect(sig, lambda *_a: self.update_input())
        self.place()
        self.setup()

    # геометрия
    def place(self):
        s = self.spec
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, int(s["x"]))
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, int(s["y"]))
        sh = self.shadow()                 # тень — за пределами самого виджета: слой на неё шире
        self.area.set_size_request(int(s["w"]) + sh, int(s["h"]) + sh)
        self.resize(int(s["w"]) + sh, int(s["h"]) + sh)
        self.queue_resize()
        self.area.queue_draw()

    def set_cloaked(self, on):
        if on != self.cloaked:
            self.cloaked = on
            self.update_input()
            self.area.queue_draw()

    def on_screen(self):
        """Виджет сейчас показан (его стол активен) — для тех, кто опрашивает данные."""
        return not self.cloaked

    def shadow(self):
        """Ширина тени справа и снизу, px (0 — выключена; у виджета без рамки тени нет)."""
        return SHADOW if T["style"].get("shadow") and self.framed() else 0

    def size(self):
        """Размер самого виджета — без полосы под тень."""
        a = self.area.get_allocation()
        sh = self.shadow()
        return (a.width - sh, a.height - sh) if a.width > 1 + sh else (int(self.spec["w"]), int(self.spec["h"]))

    def inner(self):
        w, h = self.size()
        if not self.framed():
            return 2, 2, max(1, w - 4), max(1, h - 4)
        if not self.titled():
            m = RING + PAD
            return m, m, max(1, w - 2 * m), max(1, h - 2 * m)
        f = self.fr()
        m = f["side"] + PAD
        return m, f["head"] + PAD, max(1, w - 2 * m), max(1, h - f["head"] - f["side"] - 2 * PAD)

    def framed(self):
        return self.opts.get("frame", True)

    def look(self):
        """Вид этого виджета: xp | skeet | beta | classic (вид его монитора или общий)."""
        return look_of(T["style"], self.spec.get("output"))

    def titled(self):
        """Окно с полосой заголовка (xp, skeet, beta) или прежняя плашка («classic»)."""
        return self.framed() and self.look() in FRAMES

    xp = titled                        # прежнее имя: «окно с заголовком»

    def fr(self):
        """Геометрия рамки текущего вида (FRAMES); у плашки — как у xp, но не используется."""
        return FRAMES.get(self.look(), FRAMES["xp"])

    def head(self):
        """Где кончается полоса заголовка (выше — перенос и кнопки)."""
        return self.fr()["head"]

    def exe(self):
        return str(self.opts.get("title") or EXE.get(self.spec.get("type"), "widget.exe"))

    # зоны заголовка: (x, y, w, h)
    def zone_close(self):
        w, _h = self.size()
        f = self.fr()
        c, (by, bh) = f["cap"], f["bar"]
        return (w - f["side"] - f["rm"] - c, by + (bh - c) // 2, c, c)

    def zone_pin(self):
        x, y, cw, ch = self.zone_close()
        return (x - self.fr()["gap"] - cw, y, cw, ch)

    def zone_grip(self):
        w, h = self.size()
        return (w - GRIP, h - GRIP, GRIP, GRIP)

    def update_input(self):
        """Мышь принимают только полоса заголовка и уголок; остальное — насквозь
        (ПКМ по обоям под виджетом работает). В расстановке — насквозь всё: там
        мышью заведует слой правки."""
        win = self.get_window()
        if not win:
            return
        reg = cairo.Region()
        if not self.mgr.edit and not self.cloaked:
            w, h = self.size()
            if self.clickable:                 # таймер: щелчок по самому виджету что-то делает
                reg.union(cairo.RectangleInt(0, 0, w, h))
            elif self.titled():
                reg.union(cairo.RectangleInt(0, 0, w, self.head()))
                reg.union(cairo.RectangleInt(*self.zone_grip()))
        win.input_shape_combine_region(reg, 0, 0)

    @staticmethod
    def inside(zone, x, y):
        return zone[0] <= x < zone[0] + zone[2] and zone[1] <= y < zone[1] + zone[3]

    def on_press(self, _w, e):
        if e.type != Gdk.EventType.BUTTON_PRESS or self.mgr.edit or self.cloaked:
            return True
        if e.button == 3:                      # ПКМ — только по содержимому «щёлкаемого» виджета
            if self.clickable and (not self.titled() or e.y >= self.head()):
                self.on_click(e.x, e.y, 3)
            return True
        if e.button != 1:
            return True
        if not self.titled():                  # вид «Без рамок»: только щелчок по содержимому
            if self.clickable:
                self.on_click(e.x, e.y)
            return True
        if self.inside(self.zone_close(), e.x, e.y):
            self.mgr.remove(self)
        elif self.inside(self.zone_pin(), e.x, e.y):
            self.mgr.toggle_pin(self)
        elif self.inside(self.zone_grip(), e.x, e.y):
            self.mgr.drag_begin(self, "size", e.x, e.y)
        elif e.y < self.head():
            self.mgr.drag_begin(self, "move", e.x, e.y)
        elif self.clickable:
            self.on_click(e.x, e.y)
        return True

    def on_click(self, x, y, button=1):
        pass

    def on_motion(self, _w, e):
        if self.mgr.drag and self.mgr.drag["w"] is self:
            self.mgr.drag_motion(e.x, e.y)
        else:
            if not self.titled() or (e.y >= self.head() and not self.inside(self.zone_grip(), e.x, e.y)):
                name = "pointer"               # тело виджета, который принимает щелчки
            else:
                name = "nwse-resize" if self.inside(self.zone_grip(), e.x, e.y) else (
                    "default" if self.inside(self.zone_close(), e.x, e.y)
                    or self.inside(self.zone_pin(), e.x, e.y) else "move")
            if name != getattr(self, "_cursor", None) and self.get_window():
                self._cursor = name
                self.get_window().set_cursor(Gdk.Cursor.new_from_name(self.get_display(), name))
        return True

    def on_release(self, _w, e):
        if e.button == 1 and self.mgr.drag and self.mgr.drag["w"] is self:
            self.mgr.drag_end()
        return True

    # жизнь
    def setup(self):
        pass

    def resized(self):
        pass

    def theme_changed(self):
        pass

    def tick(self):
        return False

    def dirty_rect(self):
        """Какую часть перерисовывать на кадр анимации (None — всю)."""
        return None

    def on_start(self):
        pass

    def on_stop(self):
        pass

    def set_running(self, on):
        if on == self.running:
            return
        self.running = on
        if on:
            self.on_start()
            if self.interval:
                self.timer = GLib.timeout_add(self.interval, self._tick)
        else:
            if self.timer:
                GLib.source_remove(self.timer)
                self.timer = None
            self.on_stop()

    def _tick(self):
        try:                                   # исключение сняло бы таймер молча
            if self.tick() and not self.ghosted:
                r = self.dirty_rect()
                if r:
                    self.area.queue_draw_area(*r)
                else:
                    self.area.queue_draw()
        except Exception as e:
            print("%s: %s" % (self.spec.get("name"), e), file=sys.stderr)
        return True

    def close_widget(self):
        self.set_running(False)
        self.cleanup()
        self.destroy()

    def cleanup(self):
        pass

    # рисование
    def on_draw(self, _a, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if not self.ghosted and not self.cloaked:
            self.render_all(cr)
        return True

    def snapshot(self):
        w, h = self.size()
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        self.render_all(cairo.Context(s))
        return s

    def render_all(self, cr):
        w, h = self.size()
        sh = self.shadow()
        if sh:
            # Маленькая жёсткая тень, как у окон в пиксельной графике: сдвинутый вправо-вниз
            # тёмный прямоугольник без размытия (03.10.2026, образец — AngelOS).
            cr.set_source_rgba(*(c * 0.25 for c in T["bg"]), 0.72)
            cr.rectangle(w, sh, sh, h)
            cr.rectangle(sh, h, w - sh, sh)
            cr.fill()
        look = self.look() if self.framed() else "classic"
        if look == "xp":
            self.draw_back(cr, w, h, BORDER)
            self.draw_frame(cr, w, h)
        elif look == "skeet":
            self.draw_skeet(cr, w, h)
        elif look == "beta":
            self.draw_beta(cr, w, h)
        elif self.framed():
            self.draw_back(cr, w, h, RING)
            cr.set_source_rgba(*T["primary"], 0.16)
            cr.rectangle(0, 0, w, h)
            cr.rectangle(RING, RING, w - 2 * RING, h - 2 * RING)
            cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            cr.fill()
            cr.set_fill_rule(cairo.FILL_RULE_WINDING)
        x, y, iw, ih = self.inner()
        cr.save()
        cr.rectangle(x, y, iw, ih)
        cr.clip()
        try:
            self.paint(cr, x, y, iw, ih)
        except Exception as e:
            print("%s: %s" % (self.spec.get("name"), e), file=sys.stderr)
        cr.restore()

    def draw_back(self, cr, w, h, b, col=None):
        """Фон плашки по общим настройкам: сплошной, либо прозрачный — размытые обои
        (сила размытия) под слоем цвета фона (непрозрачность). col — цвет фона вида
        (skeet и beta берут свой серый, остальные — фон палитры kitty)."""
        st = T["style"]
        col = col or T["bg"]
        cr.save()
        cr.rectangle(b, b, w - 2 * b, h - 2 * b)
        cr.clip()
        if not st["transparent"]:
            cr.set_source_rgb(*col)
            cr.paint()
        else:
            if st["blur"] > 0:
                g = self.monitor.get_geometry() if self.monitor else None
                back = self.mgr.backdrop.get(self.spec.get("output"), g.width, g.height) if g else None
                if back is not None:
                    cr.set_source_surface(back, -int(self.spec["x"]), -int(self.spec["y"]))
                    cr.paint()
            cr.set_source_rgba(*col, st["opacity"] / 100)
            cr.paint()
        cr.restore()

    def draw_frame(self, cr, w, h):
        # рамка
        cr.set_source_rgb(*T["st_mid"])
        cr.rectangle(0, 0, w, h)
        cr.rectangle(BORDER, BORDER, w - 2 * BORDER, h - 2 * BORDER)
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.fill()
        cr.set_fill_rule(cairo.FILL_RULE_WINDING)
        # полоса заголовка — тот же градиент, что у заголовка Настроек в виде XP
        g = cairo.LinearGradient(0, BORDER, 0, BORDER + TB)
        for off, key in ((0, "st_hi"), (0.12, "st_top"), (0.5, "st_mid"), (0.88, "st_bot"), (1, "line2")):
            g.add_color_stop_rgb(off, *T[key])
        cr.set_source(g)
        cr.rectangle(BORDER, BORDER, w - 2 * BORDER, TB)
        cr.fill()
        cr.set_source_rgb(*T["st_dark"])
        cr.rectangle(BORDER, BORDER + TB - 1, w - 2 * BORDER, 1)
        cr.fill()
        # значок-квадратик и имя
        ix, iy = BORDER + 6, BORDER + (TB - 10) // 2
        cr.set_source_rgb(*T["st_dark"])
        cr.rectangle(ix + 1, iy + 1, 10, 10)
        cr.fill()
        cr.set_source_rgb(*T["on_surface"])
        cr.rectangle(ix, iy, 10, 10)
        cr.fill()
        cr.set_source_rgb(*T["st_mid"])
        cr.rectangle(ix + 3, iy + 3, 4, 4)
        cr.fill()
        cx, cy, cw, ch = self.zone_close()
        px = self.zone_pin()[0]
        crisp(cr)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(font_desc(16))
        lay.set_text(self.exe(), -1)
        lay.set_width(max(1, px - ix - 22) * Pango.SCALE)
        lay.set_ellipsize(Pango.EllipsizeMode.END)
        _lw, lh = lay.get_pixel_size()
        ty = BORDER + (TB - lh) // 2
        cr.set_source_rgb(*T["st_dark"])
        cr.move_to(ix + 17, ty + 1)
        PangoCairo.show_layout(cr, lay)
        cr.set_source_rgb(*T["on_surface"])
        cr.move_to(ix + 16, ty)
        PangoCairo.show_layout(cr, lay)
        # кнопки: закрепить и закрыть
        pinned = bool(self.spec.get("pinned"))
        for zx, kind in ((px, "pin"), (cx, "close")):
            g = cairo.LinearGradient(0, cy, 0, cy + ch)
            if kind == "close":
                er = T["error"]
                top = tuple(0.5 * er[i] + 0.5 * T["st_hover"][i] for i in range(3))
                bot = tuple(0.55 * er[i] * 0.6 + 0.45 * T["st_bot"][i] for i in range(3))
            elif pinned:
                top, bot = T["st_bot"], T["st_mid"]          # утоплена
            else:
                top, bot = T["st_hover"], T["st_bot"]
            g.add_color_stop_rgb(0, *top)
            g.add_color_stop_rgb(1, *bot)
            cr.set_source(g)
            cr.rectangle(zx, cy, cw, ch)
            cr.fill()
            cr.set_source_rgb(*(T["st_dark"] if (kind == "pin" and pinned) else T["st_hi"]))
            cr.set_line_width(1)
            cr.rectangle(zx + 0.5, cy + 0.5, cw - 1, ch - 1)
            cr.stroke()
            b = bmp(PIN_BMP if kind == "pin" else X_BMP)
            cr.set_source_rgb(*(T["st_hi"] if (kind == "pin" and pinned) else T["on_surface"]))
            draw_bitmap(cr, b, zx + (cw - len(b[0])) // 2, cy + (ch - len(b)) // 2, 1, 1)
        # уголок размера — три штриха, как у окон XP
        cr.set_source_rgba(*T["st_hi"], 0.9)
        for i in (0, 4, 8):
            for j in range(0, 10 - i, 2):
                cr.rectangle(w - BORDER - 2 - j - i * 0 - 1, h - BORDER - 2 - (10 - i - j) + 1 - 1, 1, 1)
        cr.new_path()
        for k in (3, 7, 11):
            for t in range(k):
                cr.rectangle(w - BORDER - 2 - t, h - BORDER - 2 - (k - 1 - t), 1, 1)
        cr.fill()

    # ── виды skeet и beta (03.10.2026) ──
    @staticmethod
    def frame_ring(cr, w, h, i, t, col):
        """Рамка толщиной t, отступив i от края."""
        cr.set_source_rgb(*col)
        cr.rectangle(i, i, w - 2 * i, h - 2 * i)
        cr.rectangle(i + t, i + t, w - 2 * (i + t), h - 2 * (i + t))
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.fill()
        cr.set_fill_rule(cairo.FILL_RULE_WINDING)

    def title_text(self, cr, x, y, px, col, right):
        """«имя.exe» кеглем px от x до right (дальше — многоточие)."""
        crisp(cr)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(font_desc(px))
        lay.set_text(self.exe(), -1)
        lay.set_width(max(1, right - x) * Pango.SCALE)
        lay.set_ellipsize(Pango.EllipsizeMode.END)
        cr.set_source_rgb(*col)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)

    @staticmethod
    def grip_lines(cr, w, h, b, col, lens, step):
        """Уголок размера — косые штрихи длиной lens у правого нижнего угла внутри рамки b;
        step 2 — пунктир."""
        cr.set_source_rgb(*col)
        for k in lens:
            for t in range(0, k, step):
                cr.rectangle(w - b - 2 - t, h - b - 2 - (k - 1 - t), 1, 1)
        cr.fill()

    def accent(self):
        """Светлый тон вида — рамка нового размера у «призрака»."""
        look = self.look()
        return T["sk"]["acc"] if look == "skeet" else T["bt"]["acc"] if look == "beta" else T["st_hi"]

    def draw_skeet(self, cr, w, h):
        """Окно в духе меню gamesense/skeet, как вид Skeet у Настроек: рамка в шесть линий
        (светлая 1, средняя 3, светлая 1, почти чёрная 1), сверху внутри — полоска
        градиентом в три тона палитры и та же полоска темнее, тёмная строка с мелким
        светлым заголовком, под ней две линии; фон — серый skeet с точечным узором."""
        c, f = T["sk"], FRAMES["skeet"]
        b, (by, bh) = f["side"], f["bar"]
        st = T["style"]
        self.draw_back(cr, w, h, b, c["bg"])
        # полоса заголовка — сплошная, как шапка окна (содержимое — по общим настройкам)
        cr.set_source_rgb(*c["bg"])
        cr.rectangle(b, by, w - 2 * b, bh)
        cr.fill()
        # точечный узор: точка в клетках (0, 0) и (2, 2) из 4×4, от угла виджета
        pat = _SK_DOTS.get(c["dot"])
        if pat is None:
            dots = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
            dc = cairo.Context(dots)
            dc.set_source_rgb(*c["dot"])
            dc.rectangle(0, 0, 1, 1)
            dc.rectangle(2, 2, 1, 1)
            dc.fill()
            pat = cairo.SurfacePattern(dots)
            pat.set_extend(cairo.EXTEND_REPEAT)
            _SK_DOTS.clear()                     # обои сменились — прежний узор не нужен
            _SK_DOTS[c["dot"]] = pat
        body_a = st["opacity"] / 100 if st["transparent"] else 1.0
        for y0, y1, a in ((by, by + bh, 1.0), (f["head"], h - b, body_a)):
            cr.save()
            cr.rectangle(b, y0, w - 2 * b, y1 - y0)
            cr.clip()
            cr.set_source(pat)
            cr.paint_with_alpha(a)
            cr.restore()
        # рамка слоями, снаружи внутрь
        for i, t, key in ((0, 1, "line1"), (1, 3, "line2"), (4, 1, "line1"), (5, 1, "line3")):
            self.frame_ring(cr, w, h, i, t, c[key])
        # полоска-градиент 1 px и под ней она же темнее
        for dy, k in ((0, 0.0), (1, 0.55)):
            g = cairo.LinearGradient(b, 0, w - b, 0)
            for off, col in zip((0, 0.5, 1), c["strip"]):
                g.add_color_stop_rgb(off, *mix(col, (0, 0, 0), k))
            cr.set_source(g)
            cr.rectangle(b, b + dy, w - 2 * b, 1)
            cr.fill()
        # разделитель под строкой заголовка: средняя линия, под ней почти чёрная
        for dy, key in ((0, "line2"), (1, "line3")):
            cr.set_source_rgb(*c[key])
            cr.rectangle(b, by + bh + dy, w - 2 * b, 1)
            cr.fill()
        cx, cy, cs, _ = self.zone_close()
        px = self.zone_pin()[0]
        self.title_text(cr, b + 5, by + (bh - 8) // 2, 8, c["text"], px - 6)
        # кнопки: квадратик с двойной рамкой и градиентом поля; закреплённая — «нажата»
        pinned = bool(self.spec.get("pinned"))
        for zx, kind in ((px, "pin"), (cx, "close")):
            on = kind == "pin" and pinned
            cr.set_source_rgb(*c["line3"])
            cr.rectangle(zx, cy, cs, cs)
            cr.fill()
            cr.set_source_rgb(*(c["acc_d"] if on else c["gline"]))
            cr.rectangle(zx + 1, cy + 1, cs - 2, cs - 2)
            cr.fill()
            g = cairo.LinearGradient(0, cy + 2, 0, cy + cs - 2)
            top, bot = (c["field"], c["field_l"]) if on else (c["field_l"], c["field"])
            g.add_color_stop_rgb(0, *top)
            g.add_color_stop_rgb(1, *bot)
            cr.set_source(g)
            cr.rectangle(zx + 2, cy + 2, cs - 4, cs - 4)
            cr.fill()
            bm = bmp(PIN5_BMP if kind == "pin" else X5_BMP)
            cr.set_source_rgb(*(c["acc_l"] if on else c["text_dim"]))
            draw_bitmap(cr, bm, zx + (cs - len(bm[0])) // 2, cy + (cs - len(bm)) // 2, 1, 1)
            cr.fill()
        # уголок размера — пунктирные штрихи
        self.grip_lines(cr, w, h, b, c["icon"], (3, 7, 11), 2)

    def draw_beta(self, cr, w, h):
        """Окно в духе вида Beta у Настроек (по образцу AngelOS): тонкая рамка, плоская
        полоса заголовка с линией снизу, цветная плитка-значок, заголовок обычным кеглем,
        кнопки — прямоугольники в рамке; закреплённая залита акцентом, как выбранный
        сегмент Настроек."""
        c, f = T["bt"], FRAMES["beta"]
        b, (by, bh) = f["side"], f["bar"]
        self.draw_back(cr, w, h, b, c["bg"])
        cr.set_source_rgb(*c["bar"])
        cr.rectangle(b, by, w - 2 * b, bh)
        cr.fill()
        cr.set_source_rgb(*c["line"])
        cr.rectangle(b, by + bh, w - 2 * b, 1)
        cr.fill()
        self.frame_ring(cr, w, h, 0, b, c["line_strong"])
        # плитка-значок: у каждого типа свой тон (как плитки меню Beta), внутри — окошко
        types = list(EXE)
        t = self.spec.get("type")
        tile = c["tiles"][(types.index(t) if t in types else 0) % len(c["tiles"])]
        ts = 13
        ix, iy = b + 5, by + (bh - ts) // 2
        cx, cy, cs, _ = self.zone_close()
        px = self.zone_pin()[0]
        tx = ix + ts + 6
        if px - 6 - tx < 3 * adv(16):            # тесно: плитку убрать, имени — всё место
            tx = ix
        else:
            cr.set_source_rgb(*tile)
            cr.rectangle(ix, iy, ts, ts)
            cr.fill()
            cr.set_source_rgb(*c["ink"])
            draw_bitmap(cr, bmp(("#########", "#########", "#.......#", "#.......#", "#.......#",
                                 "#.......#", "#########")), ix + 2, iy + 3, 1, 1)
            cr.fill()
        self.title_text(cr, tx, by + (bh - 16) // 2, 16, c["text"], px - 6)
        pinned = bool(self.spec.get("pinned"))
        for zx, kind in ((px, "pin"), (cx, "close")):
            on = kind == "pin" and pinned
            cr.set_source_rgb(*(c["acc"] if on else c["line_strong"]))
            cr.rectangle(zx, cy, cs, cs)
            cr.fill()
            cr.set_source_rgb(*(c["acc"] if on else c["field"]))
            cr.rectangle(zx + 1, cy + 1, cs - 2, cs - 2)
            cr.fill()
            bm = bmp(PIN7_BMP if kind == "pin" else X_BMP)
            cr.set_source_rgb(*(c["on_acc"] if on else c["text"]))
            draw_bitmap(cr, bm, zx + (cs - len(bm[0])) // 2, cy + (cs - len(bm)) // 2, 1, 1)
            cr.fill()
        self.grip_lines(cr, w, h, b, c["dim"], (4, 8), 1)

    def paint(self, cr, x, y, w, h):
        pass


class SecondTicker:
    """Раз в секунду, по границе секунды."""

    def start_seconds(self):
        self.sec_id = GLib.timeout_add(1000 - int(time.time() * 1000) % 1000 + 8, self._second)

    def _second(self):
        if self.second():
            self.area.queue_draw()
        self.sec_id = GLib.timeout_add(1000 - int(time.time() * 1000) % 1000 + 8, self._second)
        return False

    def stop_seconds(self):
        if getattr(self, "sec_id", None):
            GLib.source_remove(self.sec_id)
            self.sec_id = None


# Глифы и раскладка — как у ~/.local/bin/jclock (часы дашборда): точка глифа — две
# клетки терминала в ширину и одна в высоту, между глифами одна клетка; единица и
# двоеточие — в одну точку шириной (просьба пользователя 23.09.2026: иначе «1» отходила
# от соседей втрое дальше обычного).
DIGITS = {
    "0": ("111", "101", "101", "101", "111"), "1": ("1", "1", "1", "1", "1"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    ":": ("0", "1", "0", "1", "0"),
}


class Clock(Widget, SecondTicker):
    """Время цифрами 3×5, как jclock/tty-clock на дашборде."""

    def setup(self):
        self.text = ""
        self.start_seconds()

    def fmt(self):
        return "%H:%M:%S" if self.opts.get("seconds", True) else "%H:%M"

    def second(self):
        t = time.strftime(self.fmt())
        if t != self.text:
            self.text = t
            return True
        return False

    def cleanup(self):
        self.stop_seconds()

    def paint(self, cr, x, y, w, h):
        text = self.text or time.strftime(self.fmt())
        # узкий виджет: с секундами цифры вышли бы мелкими — показываем ЧЧ:ММ
        if len(text) > 5 and min(w / 47, h * 0.75 / 5) < 4 and min(w / 29, h * 0.75 / 5) >= 1.5 * min(w / 47, h * 0.75 / 5):
            text = text[:5]
        draw_digits(cr, text, x, y, w, h, T["accent"])


class DateW(Widget, SecondTicker):
    """День недели и дата блочным шрифтом — те же шрифты figlet, что у dateview.py."""

    def setup(self):
        self.key = None
        self.cache = None
        self.start_seconds()

    def second(self):
        k = time.strftime("%Y%m%d")
        if k != self.key:
            self.key, self.cache = k, None
            return True
        return False

    def cleanup(self):
        self.stop_seconds()

    def resized(self):
        self.cache = None

    CW, CH = 6, 8        # клетка терминала дашборда при его кегле 6 pt

    def bitmaps(self, w, h):
        """Тот же подбор шрифта и масштаба, что у dateview.py в окне такого размера:
        виджет считается терминалом из клеток 6×8, блок █ — одна клетка."""
        import dateview as dv
        now = datetime.datetime.now()
        cols, rows = w // self.CW, h // self.CH
        top, bot = dv.fit(now.strftime(self.opts.get("top", "%A")),
                          now.strftime(self.opts.get("bottom", "%d %B")), cols, rows)
        # Блочные шрифты не влезли — dateview отдаёт запасные линейные (_ | / \) или просто
        # строки текста: каждый знак «клеткой» 6×8 превращался в кляксу, а не в буквы
        # (04.10.2026: «в уменьшенном today.exe какие-то непонятные пиксели»).
        # Тогда рисуем обычным пиксельным шрифтом, см. paint_text.
        if any(c not in " \u2588" for r in top + bot for c in r):
            return "text"
        width = max([len(r) for r in top + bot] or [1])
        block = []
        for part in (top, bot):
            bw = max([len(r) for r in part] or [1])
            pad = " " * ((width - bw) // 2)
            block += [pad + r for r in part]
            if part is top:
                block += [""] * dv.LINE_GAP
        return [[c != " " for c in r.ljust(width)] for r in block]

    def paint(self, cr, x, y, w, h):
        if self.cache is None:
            try:
                self.cache = self.bitmaps(w, h) or False
            except Exception as e:
                print("date:", e, file=sys.stderr)
                self.cache = False
        if not self.cache:
            return
        bmp = self.cache
        if bmp == "text":
            return self.paint_text(cr, x, y, w, h)
        cr.set_source_rgb(*T["accent"])
        draw_bitmap(cr, bmp, x + (w - len(bmp[0]) * self.CW) // 2,
                    y + (h - len(bmp) * self.CH) // 2, self.CW, self.CH)

    def paint_text(self, cr, x, y, w, h):
        """Тесно для блочных букв: день недели и дата обычным пиксельным шрифтом, по центру,
        два ряда (или один «SUN 04 OCT», если и так не помещается по ширине)."""
        now = datetime.datetime.now()
        top = now.strftime(self.opts.get("top", "%A")).upper()
        bot = now.strftime(self.opts.get("bottom", "%d %B")).upper()
        pad = 8
        lines = [top, bot]
        px = fit_px(max(len(top), len(bot)), w - 2 * pad, (h - 2 * pad) / 2 * 0.85, top=48)
        if max(len(top), len(bot)) * adv(px) > w - 2 * pad or 2 * px > h - pad:
            lines = [now.strftime("%a %d %b").upper()]
            px = fit_px(len(lines[0]), w - 2 * pad, h - 2 * pad, top=48)
        crisp(cr)
        gap = max(2, px // 4)
        total = len(lines) * px + (len(lines) - 1) * gap
        cr.set_source_rgb(*T["accent"])
        for i, line in enumerate(lines):
            lay = PangoCairo.create_layout(cr)
            lay.set_font_description(font_desc(px))
            lay.set_text(line, -1)
            lay.set_width(max(1, w - 2 * pad) * Pango.SCALE)
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            lw, lh = lay.get_pixel_size()
            cr.move_to(int(x + (w - lw) // 2), int(y + (h - total) // 2 + i * (px + gap)))
            PangoCairo.show_layout(cr, lay)


class Pomo(Widget, SecondTicker):
    """Строка помодоро: состояние читается из файла pomo, без запуска самой программы."""
    STATE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "pomo", "state")
    PHASES = {"work": "Фокус", "break": "Перерыв", "short": "Перерыв", "long": "Длинный перерыв"}

    def setup(self):
        self.line = None
        self.start_seconds()

    def cleanup(self):
        self.stop_seconds()

    def read(self):
        st = {}
        try:
            for l in open(self.STATE):
                k, _, v = l.rstrip("\n").partition("=")
                st[k] = v
        except OSError:
            pass
        phase = st.get("phase", "idle")
        try:
            started, dur, paused = int(st.get("started") or 0), int(st.get("duration") or 0), int(st.get("paused") or 0)
        except ValueError:
            started = dur = paused = 0
        if phase == "idle" or not dur:
            return (0.0, "--:--", "Помодоро не запущен")
        left = max(0, dur - ((paused or int(time.time())) - started))
        label = self.PHASES.get(phase, phase) + (" (пауза)" if paused else "")
        if st.get("task"):
            label += " · " + st["task"]
        mm = "%d:%02d:%02d" % (left // 3600, left % 3600 // 60, left % 60) if left >= 3600 \
            else "%02d:%02d" % (left // 60, left % 60)
        return (1 - left / dur, mm, label)

    def second(self):
        line = self.read()
        if line != self.line:
            self.line = line
            return True
        return False

    def paint(self, cr, x, y, w, h):
        frac, mm, label = self.line or self.read()
        # что показать — по месту: полная строка → только время; кегль — по высоте,
        # но не мельче 60 % от неё, пока есть что убрать
        hp = fit_px(1, w, h)
        bw = int(w * (0.36 if w >= 420 else 0.26))
        gap = max(6, hp // 2)
        choice = None
        for cand in ("%s  %s" % (mm, label), "%s  %s" % (mm, label.split(" · ")[0]), mm):
            px = fit_px(len(cand), w - bw - gap, h, top=hp)
            if px >= max(8, hp * 0.6) or cand == mm:
                choice = (cand, px)
                break
        cand, px = choice
        bh = max(3, min(px - 2, h - 4))
        by = y + (h - bh) // 2
        cr.set_source_rgba(*T["fg"], 0.28)
        cr.rectangle(x, by, bw, bh)
        cr.fill()
        cr.set_source_rgb(*T["accent"])
        cr.rectangle(x, by, int(bw * frac), bh)
        cr.fill()
        crisp(cr)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(font_desc(px))
        lay.set_text(cand, -1)
        lay.set_width(max(1, w - bw - gap) * Pango.SCALE)
        lay.set_ellipsize(Pango.EllipsizeMode.END)
        _lw, lh = lay.get_pixel_size()
        cr.set_source_rgb(*T["fg"])
        cr.move_to(x + bw + gap, y + (h - lh) // 2)
        PangoCairo.show_layout(cr, lay)


class Matrix(Widget):
    """«Цифровой дождь» по образцу unimatrix: струи через столбец, белая голова."""
    interval = 80
    CELL_H = 16
    CHARS = [chr(c) for c in range(0xFF66, 0xFF9E)] + list("0123456789") + list("=*+-<>|:.\"")

    def setup(self):
        self.buf = None
        self.atlas = {}

    def theme_changed(self):
        self.atlas = {}
        self.buf = None

    def resized(self):
        self.buf = None

    def glyph(self, ch, level):
        key = (ch, level)
        s = self.atlas.get(key)
        if s is None:
            cw, chh = self.cw, self.CELL_H
            s = cairo.ImageSurface(cairo.FORMAT_ARGB32, cw * 2, chh)
            cr = cairo.Context(s)
            crisp(cr)
            lay = PangoCairo.create_layout(cr)
            lay.set_font_description(font_desc(chh))
            lay.set_text(ch, -1)
            lw, lh = lay.get_pixel_size()
            color = {0: (*T["primary"], 1.0), 1: (*T["accent"], 1.0), 2: (*T["accent"], 0.45)}[level]
            cr.set_source_rgba(*color)
            cr.move_to((cw * 2 - lw) // 2, (chh - lh) // 2)
            PangoCairo.show_layout(cr, lay)
            self.atlas[key] = s
        return s

    def build(self):
        _x, _y, w, h = self.inner()
        cell = 8 if min(w, h) < 110 else (24 if min(w, h) >= 520 else 16)
        if cell != self.CELL_H:
            self.CELL_H, self.atlas = cell, {}
        self.cw = self.CELL_H * 3 // 4
        self.rows = max(1, h // self.CELL_H)
        self.ncols = max(1, w // (self.cw * 2))
        self.buf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        self.bcr = cairo.Context(self.buf)
        self.cols = [self.new_col(first=True) for _ in range(self.ncols)]

    def new_col(self, first=False):
        return {"head": -random.randint(0, self.rows * (2 if first else 1)),
                "len": random.randint(4, max(5, self.rows - 2)),
                "speed": random.choice((1, 1, 2, 2, 3)), "cnt": 0,
                "chars": [None] * self.rows}

    def put(self, c, r, ch, level):
        cr = self.bcr
        x, y = c * self.cw * 2, r * self.CELL_H
        cr.set_operator(cairo.OPERATOR_SOURCE)
        if ch is None:
            cr.set_source_rgba(0, 0, 0, 0)
        else:
            cr.set_source_surface(self.glyph(ch, level), x, y)
        cr.rectangle(x, y, self.cw * 2, self.CELL_H)
        cr.fill()

    def tick(self):
        if self.buf is None:
            self.build()
        rows = self.rows
        for c, col in enumerate(self.cols):
            col["cnt"] += 1
            if col["cnt"] < col["speed"]:
                continue
            col["cnt"] = 0
            y, chars = col["head"], col["chars"]
            if 0 <= y - 1 < rows and chars[y - 1]:
                self.put(c, y - 1, chars[y - 1], 1)
            if 0 <= y < rows:
                chars[y] = random.choice(self.CHARS)
                self.put(c, y, chars[y], 0)
            t = y - col["len"]
            if 0 <= t < rows:
                chars[t] = None
                self.put(c, t, None, 0)
            if 0 <= t + 1 < rows and chars[t + 1] and t + 1 < y - 1:
                self.put(c, t + 1, chars[t + 1], 2)
            lo, hi = max(0, t + 2), min(rows - 1, y - 2)
            if lo <= hi and random.random() < 0.04:    # «сбой»: символ в струе меняется
                r = random.randint(lo, hi)
                if chars[r]:
                    chars[r] = random.choice(self.CHARS)
                    self.put(c, r, chars[r], 1)
            col["head"] += 1
            if t >= rows:
                self.cols[c] = self.new_col()
        return True

    def paint(self, cr, x, y, w, h):
        if self.buf is None:
            self.build()
            for _ in range(self.rows * 2):         # не начинать с пустого экрана
                self.tick()
        ox = (w - self.ncols * self.cw * 2) // 2
        cr.set_source_surface(self.buf, x + ox, y)
        cr.paint()


class Cava(Widget):
    """Эквалайзер: настоящий cava с сырым выводом, столбики рисуем сами."""
    interval = 16                  # 60 к/с — как cava в терминале (04.10.2026, «работает странно»)
    CONF_PATH = os.path.join(CACHE, "cava-%s.conf")
    RANGE = 1000

    @staticmethod
    def bars_for(w):
        """Узкому виджету — столбики потоньше, чтобы их оставалось достаточно."""
        n = max(6, w // (32 if w >= 600 else 20 if w >= 300 else 12))
        return n + n % 2          # чётное: при нечётном cava отказывался работать (02.10.2026)

    def setup(self):
        self.proc = None
        self.vals = []
        self.shown = None
        self.nbars = 0

    def resized(self):
        _x, _y, w, _h = self.inner()
        n = self.bars_for(w)
        if n != self.nbars:
            self.nbars = n
            if self.proc:                            # другое число полос — cava заново
                self.kill()
                self.on_start()

    def on_start(self):
        if not self.nbars or (self.proc and self.proc.poll() is None):
            return                                   # уже играет (не останавливали)
        os.makedirs(CACHE, exist_ok=True)
        path = self.CONF_PATH % self.spec["name"]
        with open(path, "w") as f:
            f.write("[general]\nframerate = 60\nautosens = 1\nbars = %d\n"
                    "lower_cutoff_freq = 50\nhigher_cutoff_freq = 10000\nsleep_timer = 5\n"
                    "[input]\nmethod = pipewire\nsource = auto\n"
                    "[output]\nmethod = raw\nraw_target = /dev/stdout\ndata_format = ascii\n"
                    "ascii_max_range = %d\nbar_delimiter = 59\nframe_delimiter = 10\n"
                    "channels = stereo\n"
                    "[smoothing]\nnoise_reduction = 77\n" % (self.nbars, self.RANGE))
        try:
            self.proc = subprocess.Popen(["cava", "-p", path], stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, preexec_fn=_pdeathsig)
        except OSError:
            self.proc = None
            return
        threading.Thread(target=self.reader, args=(self.proc,), daemon=True).start()

    def reader(self, proc):
        for line in proc.stdout:
            try:
                # Стерео, как cava в терминале: левый канал развёрнут, басы посередине,
                # верхи к краям (04.10.2026: «почему не по центру, как в cava?»;
                # зеркало одного моно-канала выглядело «странно» — каналы одинаковые)
                self.vals = [int(x) for x in line.split(b";") if x.strip()]
            except ValueError:
                pass
        # cava вышел сам (не мы его остановили) — сказать почему: молчаливый отказ
        # выглядел как «визуализатор не работает»
        if proc is self.proc:
            err = (proc.stderr.read() or b"").decode(errors="replace").strip()
            print("%s: cava завершился: %s" % (self.spec.get("name"), err[:200] or "без сообщения"),
                  file=sys.stderr)

    def on_stop(self):
        # Ушли со стола или закрыли окнами — cava НЕ останавливаем: после перезапуска он
        # заново подбирал чувствительность и «начинал с нуля» (04.10.2026: «пусть
        # работает всегда, только этот виджет»). Рисовать при этом нечего — кадров нет.
        # Игра — останавливаем по-настоящему (правило: при CS2 ничего лишнего).
        if self.mgr.game:
            self.kill()

    def kill(self):
        if self.proc:
            try:
                self.proc.terminate()
            except OSError:
                pass
            self.proc = None
        self.vals = []

    def cleanup(self):
        self.kill()

    def tick(self):
        if self.vals != self.shown:
            return True
        return False

    def dirty_rect(self):
        return self.inner()

    def paint(self, cr, x, y, w, h):
        vals = self.vals
        self.shown = vals
        n = self.nbars or self.bars_for(w)
        step = w / n
        bw = max(2, int(step * 0.68))
        cr.set_source_rgb(*T["accent"])
        for i in range(n):
            v = vals[i] if i < len(vals) else 0
            bh = max(3, int(h * v / self.RANGE))
            cr.rectangle(x + int(i * step + (step - bw) / 2), y + h - bh, bw, bh)
        cr.fill()


class Sprite(Widget):
    """Гифка точками — как brrtfetch рисует осьминога, только без терминала."""
    interval = 70
    PITCH = 7

    def setup(self):
        self.frames = None
        self.i = 0
        self.surf = None
        self.grid = 0
        self.loading = False

    GRID = 52            # клеток по стороне: картинка растёт вместе с виджетом, а не дробится

    def resized(self):
        _x, _y, w, h = self.inner()
        side = min(w, h)
        g = max(8, min(self.GRID, side // 4))
        pitch = max(4, side // g)
        if g != self.grid or pitch != self.PITCH:
            self.grid, self.PITCH = g, pitch
            self.frames = None
            self.surf = None

    def theme_changed(self):
        self.surf = None

    def load(self):
        """Кадры → яркость по клеткам g×g; считается один раз и кешируется на диске."""
        import numpy as np
        path = os.path.expanduser(self.opts.get("gif", BRRT_GIF))
        g = self.grid
        try:
            st = os.stat(path)
            key = os.path.join(CACHE, "sprite-%s-%d-%d.npy" % (
                os.path.basename(path), int(st.st_mtime), g))
            if os.path.exists(key):
                arr = np.load(key)
            else:
                from PIL import Image, ImageSequence
                im = Image.open(path)
                fr = []
                for f in ImageSequence.Iterator(im):
                    rgba = f.convert("RGBA")
                    bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
                    lum = Image.alpha_composite(bg, rgba).convert("L")
                    side = max(lum.size)
                    sq = Image.new("L", (side, side), 0)
                    sq.paste(lum, ((side - lum.size[0]) // 2, (side - lum.size[1]) // 2))
                    fr.append(np.asarray(sq.resize((g, g), Image.BOX), dtype=np.uint8))
                arr = np.stack(fr)
                os.makedirs(CACHE, exist_ok=True)
                np.save(key, arr)
            self.interval_ms = 70
        except Exception as e:
            print("sprite:", e, file=sys.stderr)
            arr = None
        GLib.idle_add(self.loaded, g, arr)

    def loaded(self, g, arr):
        self.loading = False
        if g == self.grid and arr is not None:
            import numpy as np
            self.frames = arr.astype(np.float32) / max(1, int(arr.max()))
            p = self.PITCH
            yy, xx = np.mgrid[0:p, 0:p]
            d = np.sqrt((xx - (p - 1) / 2) ** 2 + (yy - (p - 1) / 2) ** 2)
            dot = np.clip(p * 0.43 - d + 0.5, 0, 1).astype(np.float32)
            self.mask = np.tile(dot, (g, g))
            self.area.queue_draw()
        return False

    def tick(self):
        if self.frames is None:
            if not self.loading and self.grid:
                self.loading = True
                threading.Thread(target=self.load, daemon=True).start()
            return False
        self.i = (self.i + 1) % len(self.frames)
        self.surf = None
        return True

    def dirty_rect(self):
        x, y, w, h = self.inner()
        side = self.grid * self.PITCH
        return (x + (w - side) // 2, y + (h - side) // 2, side, side)

    def render(self):
        import numpy as np
        p, g = self.PITCH, self.grid
        lum = self.frames[self.i]
        big = np.repeat(np.repeat(lum, p, axis=0), p, axis=1)
        # тёмные места силуэта (глаза, рот) остаются тусклыми точками, фон — пустой
        alpha = self.mask * np.where(big > 0.04, 0.16 + 0.84 * big, 0.0)
        r, gr, b = T["accent"]
        buf = np.empty((g * p, g * p, 4), dtype=np.uint8)
        buf[..., 0] = (alpha * b * 255).astype(np.uint8)
        buf[..., 1] = (alpha * gr * 255).astype(np.uint8)
        buf[..., 2] = (alpha * r * 255).astype(np.uint8)
        buf[..., 3] = (alpha * 255).astype(np.uint8)
        self._data = buf                         # держим: cairo не копирует
        self.surf = cairo.ImageSurface.create_for_data(memoryview(buf), cairo.FORMAT_ARGB32,
                                                       g * p, g * p, g * p * 4)

    def paint(self, cr, x, y, w, h):
        if self.frames is None:
            self.tick()
            return
        if self.surf is None:
            self.render()
        side = self.grid * self.PITCH
        cr.set_source_surface(self.surf, x + (w - side) // 2, y + (h - side) // 2)
        cr.paint()


CSI = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def ansi_rows(text):
    """Вывод с цветами ANSI → строки клеток (символ, цвет, фон). Только SGR."""
    rows, fg, bg, i = [[]], None, None, 0

    def color(ps, j):
        if j + 1 < len(ps) and ps[j + 1] == 2 and j + 4 < len(ps):
            return (ps[j + 2] / 255, ps[j + 3] / 255, ps[j + 4] / 255), j + 4
        if j + 2 < len(ps) and ps[j + 1] == 5:
            n = ps[j + 2]
            if n < 16:
                return T["ansi"][n], j + 2
            if n < 232:
                n -= 16
                return tuple((0 if v == 0 else 55 + 40 * v) / 255 for v in (n // 36, n // 6 % 6, n % 6)), j + 2
            return ((8 + 10 * (n - 232)) / 255,) * 3, j + 2
        return None, j

    while i < len(text):
        m = CSI.match(text, i) if text[i] == "\x1b" else None
        if m:
            i = m.end()
            if m.group(2) == "m":
                ps = [int(p) if p.isdigit() else 0 for p in (m.group(1) or "0").split(";")]
                j = 0
                while j < len(ps):
                    p = ps[j]
                    if p == 0:
                        fg = bg = None
                    elif 30 <= p <= 37:
                        fg = T["ansi"][p - 30]
                    elif 90 <= p <= 97:
                        fg = T["ansi"][p - 82]
                    elif p == 39:
                        fg = None
                    elif 40 <= p <= 47:
                        bg = T["ansi"][p - 40]
                    elif 100 <= p <= 107:
                        bg = T["ansi"][p - 92]
                    elif p == 49:
                        bg = None
                    elif p == 38:
                        c, j = color(ps, j)
                        fg = c or fg
                    elif p == 48:
                        c, j = color(ps, j)
                        bg = c or bg
                    j += 1
            continue
        ch = text[i]
        i += 1
        if ch == "\n":
            rows.append([])
        elif ch == "\t":
            rows[-1] += [(" ", fg, bg)] * (8 - len(rows[-1]) % 8)
        elif ch >= " ":
            rows[-1].append((ch, fg, bg))
    for r in rows:                                   # хвостовые пробелы без фона
        while r and r[-1][0] == " " and not r[-1][2]:
            r.pop()
    while rows and not rows[-1]:
        rows.pop()
    return rows


class Cmd(Widget):
    """Вывод команды с цветами ANSI пиксельным шрифтом; перечитывается по таймеру."""
    DEFAULT_CMD = "true"
    DEFAULT_INTERVAL = 60

    def setup(self):
        self.rows = []
        self.surf = None
        self.busy = False
        self.poll = GLib.timeout_add_seconds(
            max(2, int(self.opts.get("interval", self.DEFAULT_INTERVAL))), self.refresh)
        self.refresh()

    def cleanup(self):
        GLib.source_remove(self.poll)

    def theme_changed(self):
        self.surf = None
        GLib.timeout_add(3000, lambda: self.refresh() and False)   # конфиг fastfetch перекрашивается позже

    def resized(self):
        self.surf = None

    def refresh(self):
        if not self.busy:
            self.busy = True
            threading.Thread(target=self.run_cmd, daemon=True).start()
        return True

    def run_cmd(self):
        try:
            out = subprocess.run(["sh", "-c", self.opts.get("cmd") or getattr(self, "opts_cmd", self.DEFAULT_CMD)],
                                 capture_output=True, text=True, timeout=20,
                                 env=dict(os.environ, TERM="xterm-256color", COLUMNS="200")).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        GLib.idle_add(self.got, out)

    def got(self, out):
        self.busy = False
        rows = ansi_rows(out)
        if rows != self.rows:
            self.rows, self.surf = rows, None
            self.area.queue_draw()
        return False

    def variants(self):
        """Варианты вывода от полного к сжатому (у fastfetch — с логотипом и без)."""
        return [self.rows]

    def render(self, w, h):
        # из вариантов берём первый, что помещается кеглем не мельче 10; иначе — тот,
        # что помещается самым крупным (узкому виджету — вывод без логотипа)
        best = None
        for rows in self.variants():
            ncols = max((len(r) for r in rows), default=0)
            if not ncols:
                continue
            px = 8
            for p in SIZES:
                if ncols * adv(p) <= w and len(rows) * p <= h:
                    px = p
            fits = ncols * adv(px) <= w and len(rows) * px <= h
            # при равном кегле сжатый вариант лучше: сюда доходят, только если полный мелок
            if best is None or (fits, px) >= (best[2], best[1]):
                best = (rows, px, fits)
            if fits and px >= getattr(self, "FULL_MIN", 10):
                break
        if best is None:
            return None
        rows, px, _fits = best
        ncols = max(len(r) for r in rows)
        cw = adv(px)
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, math.ceil(ncols * cw)),
                               max(1, len(rows) * px))
        cr = cairo.Context(s)
        crisp(cr)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(font_desc(px))
        for r, row in enumerate(rows):
            c = 0
            while c < len(row):
                ch, fg, bg = row[c]
                e = c
                while e < len(row) and row[e][1] == fg and row[e][2] == bg:
                    e += 1
                if bg:
                    cr.set_source_rgb(*bg)
                    cr.rectangle(round(c * cw), r * px, round((e - c) * cw), px)
                    cr.fill()
                txt = "".join(cell[0] for cell in row[c:e])
                if txt.strip():
                    cr.set_source_rgb(*(fg or T["fg"]))
                    lay.set_text(txt, -1)
                    cr.move_to(round(c * cw), r * px)
                    PangoCairo.show_layout(cr, lay)
                c = e
        return s

    def paint(self, cr, x, y, w, h):
        if self.surf is None:
            self.surf = self.render(w, h) or False
        if not self.surf:
            return
        cr.set_source_surface(self.surf, x + max(0, (w - self.surf.get_width()) // 2),
                              y + max(0, (h - self.surf.get_height()) // 2))
        cr.paint()


class SysInfo(Cmd):
    """fastfetch с конфигом пользователя, но без строк Shell / Terminal / Terminal Font:
    виджет не в терминале, и там стояло бы «sh» и «python3»."""
    DEFAULT_CMD = "fastfetch --pipe false"
    SKIP = ("shell", "terminal", "terminalfont")

    def run_cmd(self):
        if "cmd" not in self.opts:
            src = os.path.expanduser("~/.config/fastfetch/config.jsonc")
            dst = os.path.join(CACHE, "fastfetch.jsonc")
            try:
                raw = "\n".join(l for l in open(src).read().splitlines()
                                if not l.lstrip().startswith("//"))
                cfg = json.loads(raw)
                cfg["modules"] = [m for m in cfg.get("modules", [])
                                  if (m if isinstance(m, str) else m.get("type")) not in self.SKIP]
                os.makedirs(CACHE, exist_ok=True)
                with open(dst, "w") as f:
                    json.dump(cfg, f)
                self.opts_cmd = "fastfetch -c %s --pipe false" % GLib.shell_quote(dst)
            except (OSError, ValueError):
                self.opts_cmd = self.DEFAULT_CMD
            # второй вариант — без логотипа: его покажем, когда виджет узкий
            try:
                out = subprocess.run(["sh", "-c", self.opts_cmd + " --logo none"], capture_output=True,
                                     text=True, timeout=20,
                                     env=dict(os.environ, TERM="xterm-256color", COLUMNS="200")).stdout
                self.plain = ansi_rows(out)
            except (OSError, subprocess.SubprocessError):
                self.plain = []
        super().run_cmd()

    def variants(self):
        """Полный вывод, а тесно — ОДИН ЛОГОТИП (не текст). пользователь, 02.10.2026: «я хотел
        видеть логотип арча больше, а не текст… если сжимать, логотип в приоритете».
        Логотип вырезается из полного вывода: это его левые колонки до начала сведений
        (ширина = длина полной строки минус длина той же строки без логотипа)."""
        plain = getattr(self, "plain", None) or []
        full = self.rows
        if not plain or not full:
            return [full]
        cut = None
        for a, b in zip(full, plain):
            ta, tb = "".join(c[0] for c in a), "".join(c[0] for c in b)
            if tb.strip() and ta.endswith(tb):
                cut = len(ta) - len(tb)
                break
        if not cut:
            return [full]
        logo = [r[:cut] for r in full]
        for r in logo:
            while r and r[-1][0] == " " and not r[-1][2]:
                r.pop()
        while logo and not logo[-1]:
            logo.pop()
        return [full, logo] if logo else [full]

    FULL_MIN = 12          # полный вывод показываем, только если он читается таким кеглем


CLASSES = {"clock": Clock, "date": DateW, "pomo": Pomo, "matrix": Matrix, "cava": Cava,
           "sprite": Sprite, "sysinfo": SysInfo, "cmd": Cmd}


# вторая пачка виджетов — отдельным файлом (sysmon, banner, player, calendar, weather, …)
try:
    import desktop_widgets_extra
    desktop_widgets_extra.register(globals())
except Exception as _e:
    print("desktop_widgets_extra: %s" % _e, file=sys.stderr)


# ── расстановка ─────────────────────────────────────────────────────────────

EDIT_CSS = b"""
.wedit-bar { background-color: rgba(16, 19, 28, 0.92); border: 2px solid @accent;
             padding: 6px 8px; }
.wedit-bar button { background: transparent; background-image: none; border: 1px solid alpha(@accent, 0.5);
             border-radius: 0; box-shadow: none; color: #e1e1ef; padding: 2px 8px; min-height: 0;
             font-family: "PxPlus HP 100LX 6x8 Jarvis"; font-size: 12pt; }
.wedit-bar button:hover { background-color: alpha(@accent, 0.25); }
.wedit-bar button.done, .wedit-bar button.done:hover { background-color: @accent; }
.wedit-bar button.done label { color: #10131c; }
.wedit-bar button.armed, .wedit-bar button.armed:hover { background-color: rgba(224, 82, 82, 0.55); border-color: #e05252; }
.wedit-bar label { color: #a9b1d6; font-family: "PxPlus HP 100LX 6x8 Jarvis"; font-size: 12pt; }
"""
HANDLE = 16
SNAP = 7


class Editor(Gtk.Window):
    """Прозрачный слой поверх всего на время расстановки: вся мышь — здесь."""

    def __init__(self, mgr, monitor, output):
        super().__init__()
        self.mgr, self.monitor, self.output = mgr, monitor, output
        self.drag = None
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-widget-edit")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(self, monitor)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        ov = Gtk.Overlay()
        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                             | Gdk.EventMask.POINTER_MOTION_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("button-release-event", self.on_release)
        self.area.connect("motion-notify-event", self.on_motion)
        ov.add(self.area)
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        bar.get_style_context().add_class("wedit-bar")
        bar.set_halign(Gtk.Align.CENTER)
        bar.set_valign(Gtk.Align.START)
        bar.set_margin_top(40)
        bar.set_margin_bottom(44)
        kinds = [k for k in TYPES if k != "cmd" and k in CLASSES]
        half = (len(kinds) + 1) // 2
        for part in (kinds[:half], kinds[half:]):
            r = Gtk.Box(spacing=6)
            r.set_halign(Gtk.Align.CENTER)
            for kind in part:
                b = Gtk.Button(label="+ " + EXE.get(kind, kind).replace(".exe", ""))
                b.set_tooltip_text(TYPES[kind][0])
                b.connect("clicked", lambda _b, k=kind: self.mgr.add(k, self.output))
                r.pack_start(b, False, False, 0)
            bar.pack_start(r, False, False, 0)
        row = Gtk.Box(spacing=6)
        row.set_halign(Gtk.Align.CENTER)
        done = Gtk.Button(label="Готово")
        done.get_style_context().add_class("done")
        done.connect("clicked", lambda _b: self.mgr.set_edit(False))
        row.pack_start(done, False, False, 0)
        flip = Gtk.Button(label="↕")          # панель мешает виджету под ней — перекинуть вниз/вверх
        flip.set_tooltip_text("Панель вверх / вниз")

        def do_flip(_b):
            top = bar.get_valign() == Gtk.Align.START
            bar.set_valign(Gtk.Align.END if top else Gtk.Align.START)
        flip.connect("clicked", do_flip)
        row.pack_start(flip, False, False, 0)
        # «Очистить стол» (04.10.2026): убрать разом все виджеты текущего стола.
        # Кнопка взводится первым щелчком («Убрать N?») и срабатывает вторым в течение
        # 3 с; Shift+Delete — то же без вопроса. Закреплённые на всех столах остаются.
        self.clear_btn, self.clear_armed = Gtk.Button(label="Очистить стол"), None
        self.clear_btn.set_tooltip_text("Убрать все виджеты этого стола (Shift+Delete). "
                                        "Закреплённые на всех столах остаются; «Восстановить» вернёт раскладку")
        self.clear_btn.connect("clicked", lambda _b: self.on_clear_click())
        row.pack_start(self.clear_btn, False, False, 0)
        bar.pack_start(row, False, False, 0)
        bar.pack_start(Gtk.Label(label="ЛКМ — двигать · уголок — растянуть · × — убрать · булавка — на всех столах · "
                                       "ПКМ — рамка вкл/выкл · Shift+Delete — очистить стол · Esc — готово"),
                       False, False, 0)
        ov.add_overlay(bar)
        self.add(ov)
        self.connect("key-press-event", self.on_key)

    def on_key(self, _w, e):
        if e.keyval == Gdk.KEY_Escape:
            self.mgr.set_edit(False)
        elif e.keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete) and e.state & Gdk.ModifierType.SHIFT_MASK:
            self.disarm_clear()
            self.mgr.clear_desk(self.output)
        return False

    def on_clear_click(self):
        n = len(self.mgr.desk_widgets(self.output))
        if not n:
            return
        if self.clear_armed is None:
            self.clear_btn.get_child().set_text("Убрать %d?" % n)
            self.clear_btn.get_style_context().add_class("armed")
            self.clear_armed = GLib.timeout_add(3000, lambda: self.disarm_clear(True))
            return
        self.disarm_clear()
        self.mgr.clear_desk(self.output)

    def disarm_clear(self, from_timer=False):
        if self.clear_armed is not None and not from_timer:
            GLib.source_remove(self.clear_armed)
        self.clear_armed = None
        self.clear_btn.get_child().set_text("Очистить стол")
        self.clear_btn.get_style_context().remove_class("armed")
        return False

    def mine(self):
        return [w for w in self.mgr.widgets
                if w.spec.get("output") == self.output and not w.cloaked]

    def on_draw(self, _a, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0.30)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        crisp(cr)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(font_desc(16))
        for w in self.mine():
            s = w.spec
            x, y, ww, hh = s["x"], s["y"], s["w"], s["h"]
            cr.set_source_rgba(*T["primary"], 0.95)
            cr.set_line_width(2)
            cr.rectangle(x + 1, y + 1, ww - 2, hh - 2)
            cr.stroke()
            cr.rectangle(x + ww - HANDLE, y + hh - HANDLE, HANDLE, HANDLE)       # уголок
            cr.fill()
            cr.rectangle(x + ww - HANDLE - 4, y, HANDLE + 4, HANDLE + 4)         # ×
            cr.fill()
            lay.set_text("×", -1)
            cr.set_source_rgb(*T["bg"])
            cr.move_to(x + ww - HANDLE + 1, y + 1)
            PangoCairo.show_layout(cr, lay)
            # «закрепить» — левее крестика; закреплённый залит светлым
            pxx = x + ww - 2 * (HANDLE + 4) - 2
            pinned = bool(s.get("pinned"))
            cr.set_source_rgba(*(T["st_hi"] if pinned else T["primary"]), 0.95)
            cr.rectangle(pxx, y, HANDLE + 4, HANDLE + 4)
            cr.fill()
            cr.set_source_rgb(*T["bg"])
            pb = bmp(PIN_BMP)
            draw_bitmap(cr, pb, pxx + 6, y + 6, 1, 1)
            if not pinned:
                cr.set_source_rgba(*T["bg"], 0.55)
                cr.rectangle(pxx + 2, y + 2, HANDLE, HANDLE)
                cr.fill()
            lay.set_text(" %s  %d×%d%s " % (w.exe(), ww, hh, "  ⚲" if s.get("pinned") else ""), -1)
            lw, lh = lay.get_pixel_size()
            cr.set_source_rgba(*T["primary"], 0.95)
            cr.rectangle(x, y, lw, lh + 2)
            cr.fill()
            cr.set_source_rgb(*T["bg"])
            cr.move_to(x, y + 1)
            PangoCairo.show_layout(cr, lay)
        return True

    def hit(self, px, py):
        for w in reversed(self.mine()):
            s = w.spec
            if s["x"] <= px < s["x"] + s["w"] and s["y"] <= py < s["y"] + s["h"]:
                if px >= s["x"] + s["w"] - HANDLE - 4 and py < s["y"] + HANDLE + 4:
                    return w, "close"
                if px >= s["x"] + s["w"] - 2 * (HANDLE + 4) - 2 and py < s["y"] + HANDLE + 4:
                    return w, "pin"
                if px >= s["x"] + s["w"] - HANDLE and py >= s["y"] + s["h"] - HANDLE:
                    return w, "size"
                return w, "move"
        return None, None

    def on_press(self, _a, e):
        w, what = self.hit(e.x, e.y)
        if not w:
            return True
        if e.button == 3:
            w.opts["frame"] = not w.framed()
            w.spec["opts"] = w.opts
            w.resized()
            w.update_input()
            w.area.queue_draw()
            self.mgr.save()
        elif e.button == 1 and what == "close":
            self.mgr.remove(w)
        elif e.button == 1 and what == "pin":
            self.mgr.toggle_pin(w)
            self.area.queue_draw()
        elif e.button == 1:
            s = w.spec
            self.drag = (w, what, e.x, e.y, s["x"], s["y"], s["w"], s["h"])
        return True

    def snap(self, w, x, y):
        return self.mgr.snap(w, x, y, self.monitor, self.output)

    def on_motion(self, _a, e):
        if not self.drag:
            return True
        w, what, px, py, x0, y0, w0, h0 = self.drag
        g = self.monitor.get_geometry()
        s = w.spec
        if what == "move":
            x, y = self.snap(w, int(x0 + e.x - px), int(y0 + e.y - py))
            s["x"] = max(0, min(g.width - s["w"], x))
            s["y"] = max(0, min(g.height - s["h"], y))
        else:
            s["w"] = max(MIN_W, min(g.width - s["x"], int(w0 + e.x - px)))
            s["h"] = max(MIN_H, min(g.height - s["y"], int(h0 + e.y - py)))
        w.place()
        self.area.queue_draw()
        return True

    def on_release(self, _a, _e):
        if self.drag:
            self.drag = None
            self.mgr.save()
        return True


class Ghost(Gtk.Window):
    """Прозрачный слой поверх всего на время переноса/растягивания: рисует снимок
    виджета (или рамку нового размера) там, где он окажется.

    Сам виджет при переносе стоит на месте и не рисуется. Двигать его слой прямо под
    курсором нельзя: координаты мыши отсчитываются от слоя, слой уезжает — и перенос
    дрожит. Снимок на отдельном неподвижном слое едет гладко и заодно может уйти на
    соседний монитор."""

    def __init__(self, mgr, monitor):
        super().__init__()
        self.mgr, self.monitor = mgr, monitor
        self.last = None
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-widget-ghost")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(self, monitor)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.connect("draw", self.on_draw)
        self.connect("realize", lambda *_a: self.get_window().input_shape_combine_region(
            cairo.Region(), 0, 0))

    def rect(self):
        d = self.mgr.drag
        if not d:
            return None
        g = self.monitor.get_geometry()
        return (d["gx"] - g.x, d["gy"] - g.y, d["nw"], d["nh"])

    def update(self):
        r = self.rect()
        for q in (self.last, r):
            if q:
                self.queue_draw_area(int(q[0]) - 4, int(q[1]) - 4, int(q[2]) + 8, int(q[3]) + 8)
        self.last = r

    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        d, r = self.mgr.drag, self.rect()
        if not d or not r:
            return True
        x, y, w, h = r
        if d["what"] == "move":
            cr.set_source_surface(d["snap"], x, y)
            cr.paint_with_alpha(0.92)
        else:
            # рамка нового размера — в тонах вида виджета (xp — как было)
            hi = d["w"].accent()
            mid = T["st_mid"] if hi is T["st_hi"] else hi
            cr.set_source_rgba(*mid, 0.25)
            cr.rectangle(x, y, w, h)
            cr.fill()
            cr.set_source_rgb(*hi)
            cr.set_line_width(2)
            cr.rectangle(x + 1, y + 1, w - 2, h - 2)
            cr.stroke()
            crisp(cr)
            lay = PangoCairo.create_layout(cr)
            lay.set_font_description(font_desc(16))
            lay.set_text(" %d×%d " % (w, h), -1)
            lw, lh = lay.get_pixel_size()
            cr.rectangle(x + 2, y + 2, lw, lh + 2)
            cr.fill()
            cr.set_source_rgb(*T["st_dark"])
            cr.move_to(x + 2, y + 3)
            PangoCairo.show_layout(cr, lay)
        return True


# ── всё вместе ──────────────────────────────────────────────────────────────

class Manager:
    def __init__(self):
        self.widgets, self.editors = [], []
        self.edit = False
        self.peek = False
        self.hide_id = None
        self.game = False
        self.conf = {"widgets": []}
        self.pending = None
        self.drag = None
        self.ghosts = []
        self.known = set()      # имена, которые сторож уже загружал
        self.gone = set()       # удалённые им самим
        self.rebound = {}       # пропавшая метка стола → новая привязка (в пределах запуска)
        self.backdrop = Backdrop()
        self.niri = Niri(self.schedule)
        self.build()
        self.style_mon = Gio.File.new_for_path(STYLE).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.style_mon.connect("changed", lambda *_a: self.theme_soon())
        GLib.timeout_add_seconds(10, self.check_game)
        Gdk.Screen.get_default().connect("monitors-changed", lambda *_a: GLib.timeout_add(700, self.rebuild))
        self.mons = []
        for name in ("vivid.txt", "colors.json", "colors-kitty.conf"):
            m = Gio.File.new_for_path(os.path.join(MATUGEN, name)).monitor_file(Gio.FileMonitorFlags.NONE, None)
            m.connect("changed", lambda *_a: self.theme_soon())
            self.mons.append(m)
        self.theme_id = None

    def monitors(self):
        outs = niri_json("outputs") or {}
        d = Gdk.Display.get_default()
        res = {}
        for i in range(d.get_n_monitors()):
            m = d.get_monitor(i)
            g = m.get_geometry()
            for name, o in outs.items():
                lg = o.get("logical") or {}
                if lg.get("x") == g.x and lg.get("y") == g.y:
                    res[name] = m
        return res

    def build(self):
        self.conf = load_conf()
        self.known = {s.get("name") for s in self.conf["widgets"]}
        self.outs = self.monitors()
        for spec in self.conf["widgets"]:
            self.spawn(spec)
        self.refreeze()

    # ── место новому виджету ──────────────────────────────────────────────
    # пользователь (04.10.2026): новый виджет вставал в точку щелчка (или в середину) и целиком
    # или частью оказывался под окнами стола — кнопка «закрыть» и уголок размера были
    # закрыты, ни убрать, ни уменьшить. Теперь он ищет СВОБОДНОЕ место на текущем столе:
    # не под колонками ленты, не под плавающими окнами, не на других виджетах стола;
    # ближе всего к желаемой точке; не помещается — уменьшается (до ~40 % типового размера,
    # но не меньше MIN_W×MIN_H). Места нет вовсе — встаёт по центру уменьшенным, и
    # приходит уведомление (тогда виджет придётся двигать в режиме «Редактировать виджеты»,
    # он рисуется поверх окон).
    SPOT_M = 16          # поля от края монитора
    SPOT_GAP = 10        # зазор до окон и других виджетов
    SPOT_STEP = 20

    def find_spot(self, output, cx, cy, ww, hh):
        """(x, y, w, h, поместился) для виджета типового размера ww×hh с желаемым центром."""
        mon = self.outs.get(output)
        if mon is None:
            return None
        g = mon.get_geometry()
        W, H, M, gap = g.width, g.height, self.SPOT_M, self.SPOT_GAP
        rects, spans = self.niri.obstacles(output, W)
        obst = [(a, 0, b, H) for a, b in spans] + list(rects)
        for w in self.widgets:
            sp = w.spec
            if sp.get("output") == output and not w.cloaked:
                obst.append((sp["x"], sp["y"], sp["x"] + sp["w"], sp["y"] + sp["h"]))
        base = min(1.0, (W - 2 * M) / ww, (H - 2 * M) / hh)

        def free(x, y, w, h):
            return all(x + w + gap <= r[0] or x >= r[2] + gap or y + h + gap <= r[1] or y >= r[3] + gap
                       for r in obst)
        for k in (1.0, 0.85, 0.72, 0.6, 0.5, 0.42):
            w, h = max(MIN_W, int(ww * base * k)), max(MIN_H, int(hh * base * k))
            w, h = min(w, W - 2 * M), min(h, H - 2 * M)
            best = None
            for y in range(M, H - M - h + 1, self.SPOT_STEP):
                for x in range(M, W - M - w + 1, self.SPOT_STEP):
                    if free(x, y, w, h):
                        d = (x + w / 2 - cx) ** 2 + (y + h / 2 - cy) ** 2
                        if best is None or d < best[0]:
                            best = (d, x, y)
            if best:
                return best[1], best[2], w, h, True
        w, h = max(MIN_W, int(ww * base * 0.6)), max(MIN_H, int(hh * base * 0.6))
        return (W - w) // 2, (H - h) // 2, w, h, False

    def autoplace(self, spec):
        """Новому виджету (флаг autoplace) — свободное место на столе; флаг снимается."""
        spec.pop("autoplace", None)
        try:
            r = self.find_spot(spec.get("output"), spec["x"] + spec["w"] / 2, spec["y"] + spec["h"] / 2,
                               spec["w"], spec["h"])
        except Exception as e:
            print("подбор места: %s" % e, file=sys.stderr)
            return
        if not r:
            return
        spec["x"], spec["y"], spec["w"], spec["h"], fits = r
        if not fits:
            subprocess.Popen(["notify-send", "-a", "Widgets", "Виджет не поместился на свободное место",
                              "Стол занят окнами. Виджет по центру под ними: двигайте его в режиме "
                              "«Редактировать виджеты»."], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # записать место сразу после того, как виджет появится в self.widgets (save() пишет
        # именно их); до этого в файле остаётся прежнее место с флагом
        GLib.idle_add(lambda: self.save() or False)

    def spawn(self, spec):
        mon = self.outs.get(spec.get("output"))
        cls = CLASSES.get(spec.get("type"))
        if not mon or not cls:
            return None
        if spec.get("autoplace"):
            self.autoplace(spec)
        try:
            w = cls(self, spec, mon)
        except Exception as e:
            print("виджет %s: %s" % (spec.get("name"), e), file=sys.stderr)
            return None
        if self.edit or self.peek:
            GtkLayerShell.set_layer(w, GtkLayerShell.Layer.TOP if self.edit else GtkLayerShell.Layer.OVERLAY)
        w.show_all()                       # слой есть всегда; виден ли он — решает «плащ» (refreeze)
        self.widgets.append(w)
        return w

    def rebuild(self):
        """Перечитать раскладку (SIGHUP, смена мониторов). Виджет, у которого сменились
        только место, размер или закрепление, остаётся тем же окном — без мигания."""
        self.drag_cancel()
        conf = load_conf()
        self.known |= {s.get("name") for s in conf["widgets"]}
        self.gone -= {s.get("name") for s in conf["widgets"]}
        outs = self.monitors()
        same_outs = set(outs) == set(getattr(self, "outs", {}))
        old = {w.spec.get("name"): w for w in self.widgets}
        keep = []
        self.conf, self.outs = conf, outs
        for spec in conf["widgets"]:
            w = old.pop(spec.get("name"), None)
            if w is not None and same_outs and all(
                    w.spec.get(k) == spec.get(k) for k in ("type", "output")) and \
                    (w.spec.get("opts") or {}) == (spec.get("opts") or {}):
                w.spec.update(spec)
                spec = w.spec
                w.place()
                keep.append(w)
            else:
                if w is not None:
                    w.close_widget()
                self.widgets = keep
                nw = self.spawn(spec)
                keep = self.widgets if nw else keep
        for w in old.values():
            w.close_widget()
        self.widgets = keep
        self.conf["widgets"] = [w.spec for w in self.widgets] + [
            sp for sp in conf["widgets"] if sp.get("output") not in outs]
        for e in self.editors:
            e.area.queue_draw()
        self.refreeze()
        return False

    def save(self):
        """Записать раскладку. В файле могут быть виджеты, добавленные командой `add`
        уже после нашей последней загрузки (сторож узнаёт о них по SIGHUP чуть позже) —
        их сохраняем как есть: иначе запись из памяти стирала только что добавленное
        (так пропал один из девяти виджетов, добавленных подряд, 02.10.2026)."""
        mine = [w.spec for w in self.widgets] + [
            s for s in self.conf["widgets"] if s.get("output") not in self.outs]
        names = {s.get("name") for s in mine} | self.gone
        try:
            fresh = [s for s in json.load(open(CONF)).get("widgets", [])
                     if s.get("name") not in names and s.get("name") not in self.known]
        except (OSError, ValueError):
            fresh = []
        self.conf["widgets"] = mine
        save_conf({"widgets": mine + fresh})

    def add(self, kind, output):
        _t, ww, hh = TYPES[kind]
        g = self.outs[output].get_geometry()
        spec = {"name": unique_name(self.conf, kind), "type": kind,
                "output": output, "x": (g.width - ww) // 2, "y": (g.height - hh) // 2,
                "w": min(ww, g.width), "h": min(hh, g.height), "pinned": False, "v": 2, "opts": {},
                "autoplace": True}
        if self.spawn(spec):
            self.known.add(spec["name"])
            self.conf["widgets"].append(spec)
            self.save()
            self.refreeze()
            for e in self.editors:
                e.area.queue_draw()

    def desk_widgets(self, output):
        """Виджеты текущего стола монитора, которые «Очистить стол» уберёт: закреплённые
        на всех столах не трогаем."""
        return [w for w in self.widgets if w.spec.get("output") == output and not w.cloaked
                and not w.spec.get("pinned")]

    def clear_desk(self, output):
        victims = self.desk_widgets(output)
        if not victims:
            return 0
        # раскладка до очистки — в файл «отменить», как у команды clear: «Восстановить» вернёт
        with open(UNDO + ".tmp", "w") as f:
            json.dump({"saved": int(time.time()), "widgets": self.conf["widgets"]}, f,
                      ensure_ascii=False, indent=1)
        os.replace(UNDO + ".tmp", UNDO)
        for w in victims:
            self.remove(w)
        return len(victims)

    def remove(self, w):
        self.widgets.remove(w)
        self.gone.add(w.spec.get("name"))
        self.conf["widgets"] = [s for s in self.conf["widgets"] if s is not w.spec]
        w.close_widget()
        self.save()
        for e in self.editors:
            e.area.queue_draw()

    # ── стол с виджетом не исчезает ───────────────────────────────────────
    # пользователь (02.10.2026): «если на столе был виджет — пусть стол считается так, будто
    # там есть окно, и не исчезает; только если закрою все виджеты — пусть исчезает».
    #
    # Как устроено. niri убирает пустой стол без имени и сдвигает номера остальных, а
    # именованный стол не убирает никогда. Поэтому столу с виджетами сторож даёт имя.
    # Имена столов у пользователя уже ведёт служба `niri_bar.py names`: значок первой
    # программы с невидимыми ZWSP впереди, а у пустого стола имя снимает. Первая версия
    # привязывала виджет к ЭТИМ именам — и виджеты пропадали, стоило открыть, закрыть
    # или перекинуть окно (имя менялось вместе со значком и номером); свои имена с ZWSP
    # служба тут же стирала. Теперь у стола с виджетами СВОЯ метка: в начале имени —
    # N невидимых знаков U+2060 (N — «метка», своя у каждого такого стола), дальше та
    # же подпись, что поставила бы служба (значок или номер). Имя без ZWSP служба
    # считает «заданным руками» и не трогает. Виджет помнит метку; подпись может
    # меняться сколько угодно. Не осталось виджетов — имя снимается, столом снова
    # занимается служба.

    def ws_label(self, ws):
        """Подпись стола, какой её сделала бы служба значков: значок первой программы,
        а нет его — номер стола."""
        try:
            sys.path.insert(0, os.path.expanduser("~/.config/niri/scripts"))
            import niri_bar
            wss, wins = self.niri.snapshot()
            name = niri_bar.wanted_names(wss, wins).get(ws["id"])
            if name:
                return name.lstrip(niri_bar.ZW)
        except Exception as e:
            print("подпись стола: %s" % e, file=sys.stderr)
        return str(ws.get("idx"))

    def used_slots(self):
        wss, _ = self.niri.snapshot()
        specs = [w.spec for w in self.widgets] + self.conf["widgets"]
        return {slot_of(w.get("name")) for w in wss} | {(sp.get("ws") or {}).get("slot") for sp in specs}

    def bind_ws(self, spec):
        """Привязать незакреплённый виджет к столу; True — привязан."""
        out = spec.get("output")
        wss = self.niri.workspaces(out)
        if not wss:
            return False                           # niri ещё не рассказал о столах
        want = spec.get("ws") or {}
        slot = want.get("slot")
        # Стол с постоянным именем (задано в конфиге niri: дашборд, «карман») не
        # переименовываем — на его имя завязаны правила окон; привязка — по самому имени.
        if not slot and want.get("name") and fixed_name(want["name"]) and \
                any(w.get("name") == want["name"] for w in wss):
            return True
        if slot:
            ws = next((w for w in wss if slot_of(w.get("name")) == slot), None)
            if ws:
                if want.get("idx") != ws.get("idx"):
                    want["idx"] = ws.get("idx")    # номер помним — на случай перезапуска niri
                    spec["ws"] = want
                return True
        # Стол жив, но стоит на другом мониторе (монитор отключили — столы уехали на
        # оставшийся; вернули — уехали обратно, а мы об этом мониторе ещё не знаем).
        # Привязку не трогаем: виджет переедет за столом в follow_desks. До 03.10.2026
        # здесь виджет перепривязывался к пустому столу своего монитора и оставался на
        # ноутбуке насовсем («столы встают на место, а виджеты нет»).
        everywhere, _ = self.niri.snapshot()
        if slot and any(slot_of(w.get("name")) == slot for w in everywhere):
            return True
        if not slot and want.get("name") and fixed_name(want["name"]) and \
                any(w.get("name") == want["name"] for w in everywhere):
            return True
            if slot in self.rebound:               # метка пропала, соседний виджет уже перепривязан
                spec["ws"] = dict(self.rebound[slot])
                return True
        # Метки нет (новый виджет, старая запись) или стол с ней пропал (имена, данные на
        # лету, niri после перезапуска не помнит). Новый — на активный стол; старая
        # запись — на стол с прежним именем или номером; такого номера уже нет — на
        # последний пустой стол (назвав его, заставим niri завести следующий пустой).
        target = None
        if want.get("name"):
            target = next((w for w in wss if w.get("name") == want["name"]), None)
        if target is None and want.get("idx") is not None:
            target = next((w for w in wss if w.get("idx") == want["idx"]), None)
            if target is None:
                if slot_of(wss[-1].get("name")):
                    return False                   # новый пустой стол ещё не появился
                target = wss[-1]
        if target is None:
            target = next((w for w in wss if w.get("is_active")), wss[-1])
        if fixed_name(target.get("name")):
            spec["ws"] = {"name": target["name"], "idx": target.get("idx")}
            return True
        new = slot_of(target.get("name"))
        if not new:
            used = self.used_slots()
            new = next(n for n in range(1, 500) if n not in used)
            self.niri.set_name(target["id"], MK * new + self.ws_label(target))
        spec["ws"] = {"slot": new, "idx": target.get("idx")}
        if slot:
            self.rebound[slot] = dict(spec["ws"])
        return True

    def tidy_ws(self):
        """Столы с нашей меткой: без виджетов — снять имя; с виджетами — держать подпись
        (значок или номер) такой же, какой её показала бы служба значков."""
        specs = [w.spec for w in self.widgets] + [
            sp for sp in self.conf["widgets"] if sp.get("output") not in self.outs]
        used = {(sp.get("ws") or {}).get("slot") for sp in specs if not sp.get("pinned")}
        for out in self.outs:
            for ws in self.niri.workspaces(out):
                slot = slot_of(ws.get("name"))
                if not slot:
                    continue
                if slot not in used:
                    self.niri.unset_name(ws["id"])
                else:
                    name = MK * slot + self.ws_label(ws)
                    if name != ws.get("name"):
                        self.niri.set_name(ws["id"], name)
        return False

    BAR_CSS = os.path.expanduser("~/.config/waybar/widget-desks.css")
    BAR_STYLE = os.path.expanduser("~/.config/waybar/style-niri.css")

    def write_bar_css(self, off=False):
        """Бар прячет пустые столы без фокуса; стол с виджетами пусть будет виден (чуть
        приглушённым) — иначе кажется, что он пропал (02.10.2026). У кнопки стола
        в waybar есть id «niri-workspace-<имя>» — по нему правило и пишется. Файл
        подключён в style.css через @import; чтобы бар перечитал стиль, трогаем его."""
        names = set()
        if not off:
            wss, _ = self.niri.snapshot()
            names = {w["name"] for w in wss if slot_of(w.get("name"))}
            names |= {(w.spec.get("ws") or {}).get("name") for w in self.widgets
                      if not w.spec.get("pinned") and not (w.spec.get("ws") or {}).get("slot")} - {None}
        if names == getattr(self, "bar_names", None):
            return
        self.bar_names = names
        css = ["/* Пишет desktop_widgets.py — не править: столы с виджетами видны в баре и пустыми. */"]
        for n in sorted(names):
            sel = "#workspaces button#niri-workspace-%s.empty:not(.focused)" % n
            css.append("%s { padding: 5px 9px; margin: 0 3px; min-width: 17px; font-size: 13px; opacity: 0.55; }" % sel)
            # «*», а не «label»: с label правило к надписи не применялось (проверено
            # снимками 02.10.2026), и стол оставался пустой таблеткой
            css.append("%s * { font-size: 17px; }" % sel)
        try:
            with open(self.BAR_CSS + ".tmp", "w", encoding="utf-8") as f:
                f.write("\n".join(css) + "\n")
            os.replace(self.BAR_CSS + ".tmp", self.BAR_CSS)
            # waybar перечитывает стиль по записи в его файл (смены времени мало) —
            # переписываем тот же текст
            if os.path.exists(self.BAR_STYLE):
                txt = open(self.BAR_STYLE, encoding="utf-8").read()
                with open(self.BAR_STYLE, "w", encoding="utf-8") as f:
                    f.write(txt)
        except OSError as e:
            print("бар:", e, file=sys.stderr)

    def toggle_pin(self, w):
        """Закреплён — виден на всех столах своего монитора; нет — только на том столе,
        где его открепили (или создали). По умолчанию новые не закреплены."""
        s = w.spec
        s["pinned"] = not s.get("pinned")
        s["ws"] = None                      # открепили — привяжется к активному столу в refreeze
        w.area.queue_draw()
        self.save()
        self.refreeze()

    # перенос и растягивание мышью (за полосу заголовка и за уголок)
    def drag_begin(self, w, what, px, py):
        g = w.monitor.get_geometry()
        s = w.spec
        self.drag = {"w": w, "what": what, "px": px, "py": py, "mon": w.monitor,
                     "out": s.get("output"), "gx": g.x + s["x"], "gy": g.y + s["y"],
                     "nw": s["w"], "nh": s["h"], "snap": w.snapshot() if what == "move" else None}
        if what == "move":
            w.ghosted = True
            w.area.queue_draw()
        for mon in self.outs.values():
            gh = Ghost(self, mon)
            gh.show_all()
            self.ghosts.append(gh)

    def drag_motion(self, ex, ey):
        d = self.drag
        w, s = d["w"], d["w"].spec
        g0 = w.monitor.get_geometry()
        if d["what"] == "move":
            # указатель на общем полотне: слой виджета стоит на месте, поэтому это честно
            pgx, pgy = g0.x + s["x"] + ex, g0.y + s["y"] + ey
            out, mon = d["out"], d["mon"]
            for name, m in self.outs.items():
                g = m.get_geometry()
                if g.x <= pgx < g.x + g.width and g.y <= pgy < g.y + g.height:
                    out, mon = name, m
            g = mon.get_geometry()
            x, y = self.snap(w, int(pgx - d["px"] - g.x), int(pgy - d["py"] - g.y), mon, out)
            x = max(0, min(g.width - s["w"], x))
            y = max(0, min(g.height - s["h"], y))
            d.update(out=out, mon=mon, gx=g.x + x, gy=g.y + y)
        else:
            d["nw"] = max(MIN_W, min(g0.width - s["x"], int(s["w"] + ex - d["px"])))
            d["nh"] = max(MIN_H, min(g0.height - s["y"], int(s["h"] + ey - d["py"])))
        for gh in self.ghosts:
            gh.update()

    def drag_end(self):
        d = self.drag
        if not d:
            return
        w, s = d["w"], d["w"].spec
        g = d["mon"].get_geometry()
        moved_out = d["out"] != s.get("output")
        if d["what"] == "move":
            s["x"], s["y"] = int(d["gx"] - g.x), int(d["gy"] - g.y)
        else:
            s["w"], s["h"] = int(d["nw"]), int(d["nh"])
        self.drag_cancel()
        if moved_out:                       # на другой монитор — слой создаётся заново
            s["output"] = d["out"]
            s["ws"] = None
            self.widgets.remove(w)
            w.close_widget()
            self.spawn(s)
        else:
            w.place()
        self.save()
        self.refreeze()

    def drag_cancel(self):
        if self.drag:
            self.drag["w"].ghosted = False
            self.drag["w"].area.queue_draw()
        self.drag = None
        for gh in self.ghosts:
            gh.destroy()
        self.ghosts = []

    def snap(self, w, x, y, mon, output):
        """Прилипание к краям и серединам экрана и соседних виджетов (в пределах SNAP)."""
        g = mon.get_geometry()
        s = w.spec
        xs = [0, g.width, g.width // 2]
        ys = [0, g.height, g.height // 2]
        for o in self.widgets:
            if o is not w and o.spec.get("output") == output and not o.cloaked:
                xs += [o.spec["x"], o.spec["x"] + o.spec["w"], o.spec["x"] + o.spec["w"] // 2]
                ys += [o.spec["y"], o.spec["y"] + o.spec["h"], o.spec["y"] + o.spec["h"] // 2]

        def best(pos, offs, lines):
            dd = min((l - (pos + o) for o in offs for l in lines), key=abs)
            return pos + dd if abs(dd) <= SNAP else pos
        return (best(x, (0, s["w"], s["w"] // 2), xs), best(y, (0, s["h"], s["h"] // 2), ys))

    # что анимировать
    def schedule(self, fast=False):
        """Пересчёт после событий niri. Смена стола — через 10 мс (она на виду); события
        окон сыплются пачками (заголовок терминала меняется по нескольку раз в секунду) —
        их копим 150 мс."""
        if fast:
            if self.pending is not None:
                GLib.source_remove(self.pending)
            self.pending = GLib.timeout_add(10, self.refreeze)
        elif self.pending is None:
            self.pending = GLib.timeout_add(150, self.refreeze)
        return False

    def check_game(self):
        g = gaming()
        if g != self.game:
            self.game = g
            self.refreeze()
        return True

    def set_peek(self, on):
        """Поверх окон без расстановки: посмотреть на виджеты, не уходя со стола."""
        if self.edit:
            return True
        self.peek = on
        self.peek_flag()
        self.relayer()
        self.refreeze()
        return True

    def peek_flag(self):
        """Файл-признак «виджеты сейчас поверх окон» — по нему Настройки рисуют выключатель."""
        try:
            if self.peek:
                open(PEEK_FLAG, "w").close()
            elif os.path.exists(PEEK_FLAG):
                os.remove(PEEK_FLAG)
        except OSError:
            pass

    def relayer(self):
        """Фон ↔ поверх всего (OVERLAY — чтобы и над полноэкранным окном). Смена слоя
        уходит композитору только со следующим кадром, поэтому — перерисовка: без неё
        неподвижные виджеты оставались наверху (замерено 02.10.2026)."""
        # расстановка — TOP: слой правки (OVERLAY) обязан быть выше виджетов; на одном
        # слое виджеты, сменившие слой позже, оказывались поверх него и закрывали кнопки
        layer = GtkLayerShell.Layer.TOP if self.edit else (
            GtkLayerShell.Layer.OVERLAY if self.peek else GtkLayerShell.Layer.BOTTOM)
        for w in self.widgets:
            GtkLayerShell.set_layer(w, layer)
            w.update_input()
            w.area.queue_draw()

    def follow_desks(self):
        """Стол с виджетами перенесли на другой монитор (Super+Ctrl+Shift+H/L) — виджеты
        переезжают вместе с ним. Слой привязан к монитору, поэтому создаётся заново там;
        место то же, с поправкой на размер нового экрана. До 02.10.2026 виджеты оставались
        на старом мониторе, где их стола уже нет, — и «просто пропадали»."""
        wss, _ = self.niri.snapshot()
        where = {}
        for ws in wss:
            if slot_of(ws.get("name")):
                where[("slot", slot_of(ws["name"]))] = ws.get("output")
            elif fixed_name(ws.get("name")):
                where[("name", ws["name"])] = ws.get("output")
        def target(s):
            if s.get("pinned"):
                return None
            ws = s.get("ws") or {}
            key = ("slot", ws["slot"]) if ws.get("slot") else ("name", ws.get("name"))
            out = where.get(key)
            return out if out and out != s.get("output") and out in self.outs else None

        def move(s, out):
            """Место на каждом мониторе помним отдельно (`at`): вернулся стол на свой
            монитор — виджет встаёт туда же, где стоял, а не куда его прижало на чужом."""
            g = self.outs[out].get_geometry()
            s.setdefault("at", {})[s.get("output")] = [s["x"], s["y"], s["w"], s["h"]]
            back = s["at"].pop(out, None)
            if back and len(back) == 4:
                s["x"], s["y"], s["w"], s["h"] = (int(v) for v in back)
            s["output"] = out
            s["w"], s["h"] = min(s["w"], g.width), min(s["h"], g.height)
            s["x"] = max(0, min(g.width - s["w"], s["x"]))
            s["y"] = max(0, min(g.height - s["h"], s["y"]))

        moved = False
        for w in list(self.widgets):
            out = target(w.spec)
            if out:
                move(w.spec, out)
                self.widgets.remove(w)
                w.close_widget()
                self.spawn(w.spec)
                moved = True
        # виджеты отключённого монитора (слоя у них нет): стол переехал на живой — и они с ним
        shown = {id(w.spec) for w in self.widgets}
        for s in self.conf["widgets"]:
            if id(s) in shown or s.get("output") in self.outs:
                continue
            out = target(s)
            if out:
                move(s, out)
                self.spawn(s)
                moved = True
        return moved

    def refreeze(self):
        """Кого показывать и кого анимировать. Виджет виден, если закреплён или активен
        его стол; анимация идёт, пока его не закрыли окна (см. Niri.state)."""
        self.pending = None
        dirty = self.follow_desks()
        for w in self.widgets:
            s = w.spec
            g = w.monitor.get_geometry()
            if not s.get("pinned"):
                before = json.dumps(s.get("ws"), sort_keys=True)
                self.bind_ws(s)
                dirty = dirty or json.dumps(s.get("ws"), sort_keys=True) != before
            mine = bool(s.get("pinned")) or self.niri.on_ws(s.get("output"), s.get("ws"))
            # показать/убрать — сразу, одним кадром: стол въезжает уже со своими виджетами
            w.set_cloaked(not mine)
            if not mine:
                w.set_running(False)
                continue
            st = VISIBLE if (self.edit or self.peek) else self.niri.state(
                s.get("output"), s["x"], s["y"], s["w"], s["h"], g.width, g.height)
            w.set_running(st == VISIBLE and not self.game)
        if self.niri.workspaces(next(iter(self.outs), "")) or not self.outs:
            dirty = self.tidy_ws() or dirty
        if dirty:
            self.save()
        self.write_bar_css()
        return False

    # тема
    def theme_soon(self):
        if self.theme_id:
            GLib.source_remove(self.theme_id)
        self.theme_id = GLib.timeout_add(400, self.retheme)

    def retheme(self):
        """Сменились обои/палитра или общий вид плашек — перечитать и перерисовать."""
        self.theme_id = None
        load_theme()
        self.backdrop.invalidate()
        # awww меняет картинку с переходом ~1 с: подложку пересчитать ещё раз позже
        GLib.timeout_add(1800, lambda: (self.backdrop.invalidate(),
                                        [w.area.queue_draw() for w in self.widgets]) and False)
        for w in self.widgets:
            w.theme_changed()
            w.place()                        # тень включили/выключили — слой другого размера
            w.resized()                      # вид (xp/skeet/beta/classic) меняет место под содержимое
            w.update_input()
            w.area.queue_draw()
        return False

    # расстановка
    def set_edit(self, on):
        if on == self.edit:
            return True
        self.peek = False
        self.peek_flag()
        self.edit = on
        self.relayer()
        if on:
            for name, mon in self.outs.items():
                e = Editor(self, mon, name)
                e.show_all()
                self.editors.append(e)
        else:
            for e in self.editors:
                e.destroy()
            self.editors = []
            self.save()
        self.refreeze()
        return True


def main():
    load_theme()
    prov = Gtk.CssProvider()
    r, g, b = (int(v * 255) for v in T["primary"])
    prov.load_from_data(b"@define-color accent rgb(%d,%d,%d);" % (r, g, b) + EDIT_CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    mgr = Manager()
    mgr.peek_flag()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1,
                         lambda: mgr.set_edit(not mgr.edit) or True)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2,
                         lambda: mgr.set_peek(not mgr.peek) or True)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, lambda: mgr.rebuild() or True)

    def bye():
        for w in mgr.widgets:
            w.cleanup()
        if os.path.exists(OFF):              # виджеты выключают совсем — столы снова обычные
            for ws in mgr.niri.snapshot()[0]:
                if slot_of(ws.get("name")):
                    mgr.niri.unset_name(ws["id"])
            mgr.write_bar_css(off=True)
        mgr.peek = False
        mgr.peek_flag()
        os._exit(0)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, bye)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, bye)
    Gtk.main()


if __name__ == "__main__":
    main()
