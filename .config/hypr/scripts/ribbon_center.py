#!/usr/bin/env python3
"""Как лента прокручивается при смене фокуса (19.09.2026).

    ribbon_center.py get           center / fit
    ribbon_center.py center|fit    переключить (сразу, без перезагрузки)
    ribbon_center.py toggle        туда-обратно, вид меняется сразу (SUPER+R)

center (scrolling:focus_fit_method = 0) — окно с фокусом всегда встаёт по центру
       экрана, соседи видны по краям. Вид предсказуемый: вернулся к окну — тот же
       обзор, что был (просьба: сузил окна SUPER+−, видел три разом, а при переходах
       «не могу поймать тот обзор»). Запоминать прокрутку для каждого окна
       Hyprland не умеет — центрирование даёт тот же результат.
fit    (= 1, по умолчанию Hyprland) — лента сдвигается ровно настолько, чтобы
       окно влезло целиком; вид зависит от того, откуда пришёл.

Выбор хранится в ~/.config/hypr/state/ribbon-center; visuals.lua читает его при
загрузке. Переключатель — «Настройки» → «Окна».
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wm  # noqa: E402
import niri_state  # noqa: E402

STATE = os.path.expanduser("~/.config/hypr/state/ribbon-center")
MODES = {"center": 0, "fit": 1}
DEFAULT = "fit"


def get():
    try:
        with open(STATE) as f:
            v = f.read().strip()
        return v if v in MODES else DEFAULT
    except OSError:
        return DEFAULT


def save(mode):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        f.write(mode + "\n")
    os.replace(tmp, STATE)


def apply(mode):
    if wm.which() == "niri":
        # У Niri это layout/center-focused-column в конфиге (21.09.2026).
        return niri_state.apply()
    r = subprocess.run(["hyprctl", "eval",
                        "hl.config({ scrolling = { focus_fit_method = %d } })" % MODES[mode]],
                       capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def apply_and_wait(mode, limit=0.6):
    """Применить и дождаться, пока niri ПРИМЕНИТ конфиг (событие ConfigLoaded).

    load-config-file отвечает раньше, чем настройка вступает в силу: без ожидания
    сдвиг ленты шёл, пока центрирование ещё было включено, и вид оставался по центру
    (28.09.2026 — «перестал работать»). Прежняя пауза 0,25 с была вслепую; событие
    приходит быстрее и наверняка. Первое ConfigLoaded — из начального состояния
    потока, его пропускаем.
    """
    import json
    import select
    import socket
    import time
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(os.environ["NIRI_SOCKET"])
        sock.sendall(b'"EventStream"\n')
    except (OSError, KeyError):
        apply(mode)
        time.sleep(0.25)
        return False
    buf = b""

    def events(deadline):
        nonlocal buf
        while time.time() < deadline:
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    yield json.loads(line)
                except ValueError:
                    pass
            r, _, _ = select.select([sock], [], [], max(0.0, deadline - time.time()))
            if not r:
                return
            chunk = sock.recv(65536)
            if not chunk:
                return
            buf += chunk

    # начальное состояние потока (в нём уже есть ConfigLoaded) — дочитать и пропустить
    for ev in events(time.time() + 0.15):
        if "ConfigLoaded" in ev:
            break
    apply(mode)
    got = False
    for ev in events(time.time() + limit):
        if "ConfigLoaded" in ev:
            got = True
            break
    sock.close()
    return got


def niri_view(mode):
    """Сразу показать новый вид, с анимацией niri (28.09.2026, SUPER+R).

    Включили — центрировать окно с фокусом. Выключили — центрирование само вид не
    возвращает: окна стоят, где их поставил центр, до следующей смены фокуса. Прежнее
    место не узнать (у окон в ленте niri не отдаёт положения на экране), поэтому
    ставим обычный вид: фокус на миг уходит к соседней колонке и обратно, и niri
    плавно сдвигает ленту так, чтобы окно стояло рядом с соседом у края экрана —
    как после обычной навигации. Просьба: «можно даже зафорсить не центрированный».
    """
    import json
    act = lambda *a: subprocess.run(["niri", "msg", "action", *a], capture_output=True)
    if mode == "center":
        act("center-column")
        return
    try:
        wins = json.loads(subprocess.run(["niri", "msg", "-j", "windows"],
                                         capture_output=True, text=True).stdout)
    except ValueError:
        return
    me = next((w for w in wins if w.get("is_focused")), None)
    if not me or me.get("is_floating"):
        return
    cols = {(w.get("layout") or {}).get("pos_in_scrolling_layout", [0])[0]
            for w in wins if w.get("workspace_id") == me.get("workspace_id") and not w.get("is_floating")}
    col = (me.get("layout") or {}).get("pos_in_scrolling_layout", [0])[0]
    if len(cols) < 2:
        return
    if col > min(cols):
        act("focus-column-left"); act("focus-column-right")
    else:
        act("focus-column-right"); act("focus-column-left")


def main():
    args = sys.argv[1:] or ["get"]
    if args == ["get"]:
        print(get())
        return 0
    if len(args) == 1 and args[0] in MODES:
        save(args[0])
        print("лента: %s (%s)" % (args[0], apply(args[0])))
        return 0
    if args == ["toggle"]:
        # SUPER+R (28.09.2026): переключить и сразу показать новый вид; без уведомлений.
        mode = "fit" if get() == "center" else "center"
        save(mode)
        if wm.which() == "niri":
            applied = apply_and_wait(mode)
            niri_view(mode)
            print("лента:", mode, "" if applied else "(ConfigLoaded не дождался — сдвиг наугад)")
        else:
            apply(mode)
            print("лента:", mode)
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
