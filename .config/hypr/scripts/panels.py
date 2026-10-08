#!/usr/bin/env python3
"""Панели по мониторам: верхний бар и нижняя панель — своё на каждом мониторе. 06.10.2026.

    panels.py                      состояние (json)
    panels.py same                 yes | no — одинаково на всех мониторах?
    panels.py same on|off          переключить и применить (off — у каждого монитора свой выбор)
    panels.py set OUT top|bottom always|hover|off   выбор для монитора (eDP-1, DP-4…) и применить
    panels.py set OUT ws top|bottom   где список столов этого монитора
    panels.py apply [top|bottom]   применить заново (перезапуск верхних баров / нижней панели)
    panels.py outputs              мониторы для Настроек: «выход<TAB>название»
    panels.py launch-top           поднять waybar по мониторам (barfix / shell-switch / bar_style)

Пользователь (06.10.2026): «можно разделить настройки панелей в разных мониторах? Допустим в
левом мониторе (от ноута) видеть верхний waybar, а нижний скрывать»; «просто добавлять
кнопку „На всех мониторах“. Если убрано — покажутся настройки для разных».

Состояние — ~/.config/hypr/state/panels.json:
    {"same": true, "mon": {"eDP-1": {"top": "hover", "bottom": "off"}, "DP-4": {...}}}
Нет файла или same = true — всё ровно как раньше: общий режим верхнего бара
(state/top-bar, top_bar.py) и нижней панели (state/xpbar-show, bottom_bar.py). Выбор
монитора, которого нет в файле, — общий режим.

Как это сделано:
  * верх — по waybar на монитор (у каждого свой конфиг config-niri-<ВЫХОД>.jsonc с одним
    "output": hover-режиму нужен свой процесс — SIGUSR1 прячет все панели процесса разом);
    сторож наведения — свой на монитор: `top_bar.py watch <ВЫХОД>`;
  * низ — xpbar.py спрашивает bottom_for(выход) для каждой своей панели; off — панели нет.
    Вид нижней панели (XP / док / ничего) — общий, по мониторам не делится.
Откат: `panels.py same on` (или удалить panels.json) и `top_bar.py apply` — всё как было.
"""
import json
import os
import subprocess
import sys

STATE = os.path.expanduser("~/.config/hypr/state")
FILE = os.path.join(STATE, "panels.json")
TOP_FILE = os.path.join(STATE, "top-bar")
WS_FILE = os.path.join(STATE, "ws-place")
SHOW_FILE = os.path.join(STATE, "xpbar-show")
TOP_MODES = ("always", "hover", "off")
BOTTOM_MODES = ("always", "hover", "dock", "off")     # always/hover — XP-панель
WAYBAR_DIR = os.path.expanduser("~/.config/waybar")
CSS = os.path.join(WAYBAR_DIR, "style-niri.css")


def _read(path, allowed, default):
    try:
        v = open(path).read().strip()
        return v if v in allowed else default
    except OSError:
        return default


def load():
    try:
        d = json.load(open(FILE))
        if isinstance(d, dict):
            d.setdefault("same", True)
            if not isinstance(d.get("mon"), dict):
                d["mon"] = {}
            return d
    except (OSError, ValueError):
        pass
    return {"same": True, "mon": {}}


def save(d):
    os.makedirs(STATE, exist_ok=True)
    with open(FILE + ".tmp", "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(FILE + ".tmp", FILE)


def per_monitor(d=None):
    """True — у мониторов свой выбор: переключатель «На всех мониторах» снят И подключено
    не меньше двух мониторов. С одним ноутбуком (MSI отключён) — общий режим, как раньше;
    выбор по мониторам хранится и вернётся, когда второй монитор подключат (06.10.2026,
    Просьба: «настройки такие должны появляться тогда, когда доп. монитор вообще подключён»).
    niri не ответил — верим файлу."""
    if (d or load()).get("same", True):
        return False
    n = connected_count()
    return True if n is None else n >= 2


def stored_split(d=None):
    """Снят ли переключатель «На всех мониторах» (без оглядки на число мониторов)."""
    return not (d or load()).get("same", True)


def connected_count():
    outs = _outputs()
    return None if outs is None else len(outs)


def global_top():
    return _read(TOP_FILE, TOP_MODES, "always")


def global_bottom():
    """Общий выбор нижней панели в терминах «по мониторам»: док, ничего или XP (её «по
    кнопке» — как «всегда»)."""
    try:
        import bottom_bar
        kind = bottom_bar.get()
    except Exception:
        kind = "xp"
    if kind == "dock":
        return "dock"
    if kind == "none":
        return "off"
    v = _read(SHOW_FILE, ("always", "hover", "button"), "always")
    return "hover" if v == "hover" else "always"


def top_for(out, d=None):
    d = d or load()
    if not per_monitor(d):
        return global_top()
    v = (d["mon"].get(out) or {}).get("top")
    return v if v in TOP_MODES else global_top()


def bottom_for(out, d=None):
    """Режим нижней панели на мониторе: None — общий (как раньше), иначе always|hover|off."""
    d = d or load()
    if not per_monitor(d):
        return None
    v = (d["mon"].get(out) or {}).get("bottom")
    return v if v in BOTTOM_MODES else global_bottom()


def _outputs():
    """{выход: описание} включённых мониторов; None — niri не ответил."""
    try:
        r = subprocess.run(["niri", "msg", "-j", "outputs"], capture_output=True, text=True, timeout=3)
        return {n: o for n, o in json.loads(r.stdout).items() if o.get("logical")}
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None


def global_ws():
    return _read(WS_FILE, ("top", "bottom"), "top")


def ws_for(out, d=None):
    """Где список столов монитора: top | bottom. Без верхнего бара — только внизу; без
    XP-панели внизу (док / ничего) — только наверху (иначе столов не видно нигде)."""
    d = d or load()
    if not per_monitor(d):
        return "bottom" if global_top() == "off" else global_ws()
    v = (d["mon"].get(out) or {}).get("ws")
    v = v if v in ("top", "bottom") else global_ws()
    if top_for(out, d) == "off":
        return "bottom"
    if bottom_for(out, d) in ("dock", "off"):
        return "top"
    return v


def niri_outputs():
    """{выход: описание} включённых мониторов; {} — niri не ответил."""
    return _outputs() or {}


def config_outputs():
    """Мониторы из "output" основного конфига бара (["DP-4", "eDP-1"])."""
    import re
    try:
        raw = open(os.path.join(WAYBAR_DIR, "config.jsonc")).read()
        m = re.search(r'"output"\s*:\s*\[([^\]]*)\]', raw)
        return re.findall(r'"([^"]+)"', m.group(1)) if m else []
    except OSError:
        return []


def top_outputs(d=None):
    """Мониторы, для которых держим свой waybar: из конфига, из файла и подключённые.
    Отключённый монитор тоже получает свой бар: waybar ждёт выход и поднимает панель,
    когда монитор возвращается."""
    d = d or load()
    return sorted(set(config_outputs()) | set(d["mon"]) | set(niri_outputs()))


def label(out, info=None):
    if out.startswith("eDP"):
        return "Ноутбук"
    info = info or {}
    make = (info.get("make") or "").split()
    name = {"Microstep": "MSI"}.get(make[0], make[0]) if make else ""
    return name or info.get("model") or out


def bar_config(out):
    return os.path.join(WAYBAR_DIR, "config-niri-%s.jsonc" % out)


def launch_top(log=None):
    """Поднять waybar по мониторам. Вызывать, когда старые панели уже погашены."""
    d = load()
    n = 0
    for out in top_outputs(d):
        if top_for(out, d) == "off" or not os.path.exists(bar_config(out)):
            continue
        argv = ["waybar", "-c", bar_config(out)] + (["-s", CSS] if os.path.exists(CSS) else [])
        out_f = open(log, "a") if log else subprocess.DEVNULL
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out_f, stderr=subprocess.STDOUT,
                         start_new_session=True)
        n += 1
    return n


def apply(which=("top", "bottom")):
    """Перезапустить то, что зависит от выбора: верхние бары (top_bar.py apply — конфиги,
    стиль, сторожа) и нижнюю XP-панель (если выбрана она)."""
    here = os.path.dirname(os.path.abspath(__file__))
    q = dict(capture_output=True, timeout=60)
    if "top" in which:
        subprocess.run([sys.executable, os.path.join(here, "top_bar.py"), "apply"], **q)
    if "bottom" in which:
        xp, dock, bb = (os.path.join(here, n) for n in ("xpbar.py", "dock.py", "bottom_bar.py"))
        d = load()
        if per_monitor(d):
            # у каждого монитора своё: XP там, где always/hover, док — где dock
            want = {bottom_for(o, d) for o in niri_outputs()}
            if want & {"always", "hover"}:
                subprocess.run([sys.executable, xp, "restart"], **q)
            else:
                subprocess.run([sys.executable, xp, "stop"], **q)
            subprocess.run([sys.executable, dock, "off"], **q)       # док строит панели при старте
            if "dock" in want:
                subprocess.run([sys.executable, dock, "on"], **q)
        else:
            # общий выбор — как было: bottom_bar.py поднимает выбранное, XP перечитывает режим
            subprocess.run([sys.executable, bb], **q)
            kind = subprocess.run([sys.executable, bb, "get"], capture_output=True, text=True).stdout.strip()
            if kind == "xp":
                subprocess.run([sys.executable, xp, "restart"], **q)


def set_same(on):
    """Записать переключатель «На всех мониторах» (без применения)."""
    d = load()
    d["same"] = bool(on)
    if not d["same"]:
        # первый раз — у каждого монитора тот же выбор, что был общим
        for out in top_outputs(d):
            m = d["mon"].setdefault(out, {})
            m.setdefault("top", global_top())
            m.setdefault("bottom", global_bottom())
            m.setdefault("ws", global_ws())
    save(d)
    return d


def main(a):
    if not a:
        print(json.dumps(load(), ensure_ascii=False, indent=1))
    elif a[0] == "same" and len(a) == 1:
        print("no" if per_monitor() else "yes")
    elif a[0] == "active":
        # для сторожа bar_watch: действует ли сейчас раздельный режим
        print("split" if per_monitor() else "same")
    elif a[0] == "same" and a[1] in ("on", "off"):
        d = set_same(a[1] == "on")
        apply()
        print("yes" if d["same"] else "no")
    elif a[0] == "set" and len(a) == 4 and a[2] in ("top", "bottom", "ws") and \
            a[3] in {"top": TOP_MODES, "bottom": BOTTOM_MODES, "ws": ("top", "bottom")}[a[2]]:
        d = load()
        was = (d["mon"].get(a[1]) or {}).get(a[2])
        d["mon"].setdefault(a[1], {})[a[2]] = a[3]
        save(d)
        if per_monitor(d):
            # верхний бар включили/выключили — нижней панели показать/убрать столы
            off_changed = a[2] == "top" and "off" in (was, a[3])
            # низ стал/перестал быть XP — столы переезжают в верхний бар этого монитора/обратно
            xp = ("always", "hover")
            xp_changed = a[2] == "bottom" and (was in xp) != (a[3] in xp)
            # столы переезжают — верхний бар (его конфиг) и нижняя панель, обе
            both = off_changed or xp_changed or a[2] == "ws"
            apply(("top", "bottom") if both else (a[2],))
        print(a[3])
    elif a[0] == "apply":
        apply(tuple(a[1:]) or ("top", "bottom"))
    elif a[0] == "outputs":
        outs = niri_outputs()
        for out in sorted(outs, key=lambda o: (not o.startswith("eDP"), o)):
            print("%s\t%s" % (out, label(out, outs[out])))
    elif a[0] == "launch-top":
        print(launch_top(a[1] if len(a) > 1 else None))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
