#!/usr/bin/env python3
"""Размытие обоев — отдельно для каждого монитора.

    wallpaper_blur.py get [ВЫХОД]        -> on | off
    wallpaper_blur.py on|off|toggle [ВЫХОД]
    wallpaper_blur.py outputs            -> имя<TAB>подпись<TAB>состояние
    wallpaper_blur.py apply              применить состояние (после смены обоев)
    wallpaper_blur.py backdrop           фон обзора niri — размытые обои (2-й демон awww)
    wallpaper_blur.py level [1..3]       сила: 1 лёгкое, 2 среднее, 3 сильное

Без имени выхода команда действует на все мониторы сразу.

Как сделано. Размывать фон на лету демон обоев (awww) не умеет, и композитор
тоже: у Niri размытия обоев нет. Поэтому рядом лежит размытая копия картинки и
показывается вместо неё — на том мониторе, где включено. Копия делается один
раз на каждые обои (~2 с), дальше мгновенно.

Картинка ставится напрямую через awww, а не через waypaper: post_command
waypaper пересобирает палитру, и цвета интерфейса поехали бы за размытой
копией. Исходный путь берётся из ~/.cache/matugen/wallpaper — его пишет
theme_changer.sh, и он остаётся настоящим, пока на экране размытая копия.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

STATE = os.path.expanduser("~/.config/hypr/state/wallpaper-blur")
SOURCE = os.path.expanduser("~/.cache/matugen/wallpaper")
CACHE = os.path.expanduser("~/.cache/wallpaper-blur")
SOURCES = os.path.expanduser("~/.config/hypr/state/wallpaper-blur-src")
LEVEL_STATE = os.path.expanduser("~/.config/hypr/state/wallpaper-blur-level")
# Три ступени вместо числа: «пара слоёв» вместо тонкой настройки (21.09.2026).
LEVELS = {1: ("лёгкое", "0x10"), 2: ("среднее", "0x24"), 3: ("сильное", "0x40")}
DEFAULT_LEVEL = 2
TRANSITION = ["--transition-type", "fade", "--transition-duration", "0.6"]
# Пиксельные обои (03.10.2026, wallpaper_pixel.py): ещё одна производная копия. Порядок —
# сперва пиксели, потом размытие поверх; «настоящими» обоями не считается ни та, ни другая.
PIXEL_CACHE = os.path.expanduser("~/.cache/wallpaper-pixel")
BACKDROP_NS = "-backdrop"      # второй демон awww — фон обзора niri, см. backdrop();
                               # передавать как --namespace=…: «-n -backdrop» читается как флаги


def level():
    try:
        with open(LEVEL_STATE) as f:
            n = int(f.read().strip())
        return n if n in LEVELS else DEFAULT_LEVEL
    except (OSError, ValueError):
        return DEFAULT_LEVEL


def set_level(n):
    n = max(1, min(3, int(n)))
    os.makedirs(os.path.dirname(LEVEL_STATE), exist_ok=True)
    tmp = LEVEL_STATE + ".tmp"
    with open(tmp, "w") as f:
        f.write("%d\n" % n)
    os.replace(tmp, LEVEL_STATE)
    return n


def radius():
    return LEVELS[level()][1]


def shown(ns=""):
    """{имя выхода: показанная сейчас картинка} — по опросу самого демона обоев."""
    try:
        out = subprocess.run(["awww", "query"] + (["--namespace=" + ns] if ns else []),
                             capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    res = {}
    for line in out.splitlines():
        m = re.match(r"^:?\s*([\w-]+):.*currently displaying: image: (.+)$", line.strip())
        if m:
            res[m.group(1)] = m.group(2).strip()
    return res


def outputs():
    """[(имя, подпись)] подключённых мониторов, слева направо."""
    return [(n, label(n)) for n in shown()]


def label(name):
    """Человеческая подпись монитора: «экран ноутбука», «монитор MSI»."""
    if name.lower().startswith("edp"):
        return "экран ноутбука"
    try:
        info = json.loads(subprocess.run(["niri", "msg", "-j", "outputs"],
                                         capture_output=True, text=True,
                                         timeout=5).stdout or "{}")
        model = (info.get(name) or {}).get("model") or ""
        if "MAG" in model or "MSI" in model.upper():
            return "монитор MSI"
        if model:
            return "монитор %s" % model
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return "монитор %s" % name


def read_state():
    """{имя выхода: "on"|"off"}. Старый формат «on/off одной строкой» — на все."""
    try:
        with open(STATE) as f:
            text = f.read().strip()
    except OSError:
        return {}
    if text in ("on", "off"):
        return {name: text for name, _ in outputs()}
    try:
        data = json.loads(text)
        return {k: ("on" if v == "on" else "off") for k, v in data.items()}
    except ValueError:
        return {}


def write_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, STATE)


def get(name=None):
    state = read_state()
    if name:
        return state.get(name, "off")
    # Без имени: «включено», только если включено везде.
    values = [state.get(n, "off") for n, _ in outputs()]
    return "on" if values and all(v == "on" for v in values) else "off"


def original(name, display):
    """Настоящие обои монитора — не размытая копия.

    Источник истины — что показывает демон: файл в ~/.cache/matugen/wallpaper
    бывает другим (обои меняются и со стороны Noctalia), и из-за него
    переключатель размытия подменял картинку (замечено пользователем 21.09.2026).
    Если на экране уже наша размытая копия, берём запомненный исходник.
    """
    path = display.get(name)
    if path and not path.startswith((CACHE, PIXEL_CACHE)):
        remember(name, path)
        return path
    saved = read_sources().get(name)
    if saved and os.path.isfile(saved):
        return saved
    try:
        with open(SOURCE) as f:
            fallback = f.read().strip()
        return fallback if os.path.isfile(fallback) else None
    except OSError:
        return None


def read_sources():
    try:
        with open(SOURCES) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def remember(name, path):
    data = read_sources()
    if data.get(name) == path:
        return
    data[name] = path
    os.makedirs(os.path.dirname(SOURCES), exist_ok=True)
    tmp = SOURCES + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, SOURCES)


def blurred(path):
    """Путь к размытой копии; делается при первом обращении."""
    st = os.stat(path)
    soft = radius()
    key = hashlib.sha1(("%s%d%s" % (path, st.st_mtime_ns, soft)).encode()).hexdigest()[:16]
    out = os.path.join(CACHE, key + ".jpg")
    if os.path.isfile(out):
        return out
    os.makedirs(CACHE, exist_ok=True)
    tmp = out + ".tmp.jpg"
    r = subprocess.run(["magick", path, "-resize", "1920x1080^", "-gravity", "center",
                        "-extent", "1920x1080", "-blur", soft, "-quality", "92", tmp],
                       capture_output=True, timeout=120)
    if r.returncode != 0:
        return None
    os.replace(tmp, out)
    return out


def pixel_base(path):
    """Обои с учётом переключателя «Пиксельные обои»: пиксельная копия или оригинал."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import wallpaper_pixel
        if wallpaper_pixel.is_on():
            return wallpaper_pixel.pixelated(path) or path
    except Exception as e:
        print("пиксельные обои: %s" % e, file=sys.stderr)
    return path


def show(name, path):
    r = subprocess.run(["awww", "img", "--outputs", name, *TRANSITION, path],
                       capture_output=True, text=True)
    return r.returncode == 0


def apply():
    display = shown()
    if not display:
        return "демон обоев не отвечает"
    state = read_state()
    done = []
    for name in display:
        path = original(name, display)
        if not path:
            done.append("%s: обоев не знаю" % name)
            continue
        want_blur = state.get(name, "off") == "on"
        base = pixel_base(path)
        target = blurred(base) if want_blur else base
        if want_blur and not target:
            done.append("%s: размыть не вышло" % name)
            continue
        # Лишний раз картинку не пересылаем: это и есть та самая «смена обоев».
        if display.get(name) != target:
            show(name, target)
        done.append("%s: %s%s" % (name, "размыто" if want_blur else "чётко",
                                  ", пиксели" if base != path else ""))
    backdrop()
    return ", ".join(done)


def backdrop():
    """Фон обзора niri — размытые обои каждого монитора (28.09.2026).

    Обзор уменьшает столы, а вокруг них niri рисует свой фон — был серый.
    Картинку туда кладёт второй демон awww со своим namespace (awww-daemon-backdrop):
    правило place-within-backdrop в config.kdl уносит его слой в фон обзора, а
    столы остаются с обычными обоями. Кэш awww не трогаем (--no-cache): иначе
    основной демон после перезапуска мог бы поднять размытую картинку.
    """
    display = shown()
    now = shown(BACKDROP_NS)
    done = []
    for name in display:
        path = original(name, display)
        target = blurred(path) if path else None
        if not target:
            continue
        if now.get(name) != target:
            r = subprocess.run(["awww", "img", "--namespace=" + BACKDROP_NS, "--no-cache",
                                "--outputs", name, "--transition-type", "none", target],
                               capture_output=True, text=True)
            if r.returncode != 0:
                done.append("%s: демон фона обзора не отвечает" % name)
                continue
        done.append("%s: фон обзора" % name)
    return ", ".join(done)


def set_value(value, name=None):
    state = read_state()
    targets = [name] if name else [n for n, _ in outputs()]
    for target in targets:
        state[target] = value
    write_state(state)
    return apply()


def main():
    args = sys.argv[1:] or ["get"]
    cmd = args[0]
    name = args[1] if len(args) > 1 else None
    if cmd == "get":
        print(get(name))
        return 0
    if cmd == "outputs":
        for out_name, text in outputs():
            print("%s\t%s\t%s" % (out_name, text, get(out_name)))
        return 0
    if cmd in ("on", "off"):
        print(set_value(cmd, name))
        return 0
    if cmd == "toggle":
        print(set_value("off" if get(name) == "on" else "on", name))
        return 0
    if cmd == "backdrop":
        # При входе оба демона поднимаются параллельно — ждём их до 15 с.
        import time
        for _ in range(30):
            if shown() and subprocess.run(["awww", "query", "--namespace=" + BACKDROP_NS],
                                          capture_output=True).returncode == 0:
                break
            time.sleep(0.5)
        print(backdrop())
        return 0
    if cmd == "apply":
        print(apply())
        return 0
    if cmd == "level":
        if name is None:
            print(level())
            return 0
        set_level(name)
        print("%s размытие; %s" % (LEVELS[level()][0], apply()))
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
