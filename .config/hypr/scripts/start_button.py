#!/usr/bin/env python3
"""Кнопка «Пуск» в баре: вид значка (custom/launcher). 30.09.2026.

Вид хранится в ~/.config/hypr/state/start-icon:
    nerd   (по умолчанию) — прежний знак 󰣇 (md-arch), шрифт JarvisBarIcons из CSS;
    pixel  — пиксельный логотип Arch 16×16, шрифт JarvisStart (build_start_font.py).
Место под будущий вид «xp» (зелёная кнопка с флажком) оставлено в VARIANTS:
неизвестный или ещё не нарисованный вид показывается как nerd.

    start_button.py                  модуль waybar: печатает JSON и выходит
                                     ("interval": "once" + "signal": 12)
    start_button.py set nerd|pixel   сменить вид и обновить бар (SIGRTMIN+12)
    start_button.py toggle           nerd ↔ pixel
    start_button.py status|get       текущий вид

Сигнал 12: заняты 5 (mpris), 8 (pomo), 9 (часы), 11 (запись экрана).
"""
import json
import os
import subprocess
import sys

STATE = os.path.expanduser("~/.config/hypr/state/start-icon")
SIGNAL = 12

# Вид → разметка значка. Класс кнопки = имя вида (#custom-launcher.pixel в CSS).
# weight="normal": в style.css «* { font-weight: bold }», и Pango утолщал бы
# пиксели сам — рисунок расплылся бы.
VARIANTS = {
    "nerd": "\U000f08c7",
    "pixel": '<span font="JarvisStart 16px" weight="normal"></span>',
    # "xp": ...  — зарезервировано: JarvisStart U+E501
}
DEFAULT = "nerd"


def current():
    try:
        v = open(STATE).read().strip()
    except OSError:
        return DEFAULT
    return v if v in VARIANTS else DEFAULT


def set_variant(v):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE + ".tmp", "w") as f:
        f.write(v + "\n")
    os.replace(STATE + ".tmp", STATE)
    subprocess.run(["pkill", "-RTMIN+%d" % SIGNAL, "-x", "waybar"], capture_output=True)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if not cmd:
        v = current()
        print(json.dumps({"text": VARIANTS[v], "class": v, "tooltip": ""}, ensure_ascii=False))
        return 0
    if cmd in ("status", "get"):
        print(current())
        return 0
    if cmd == "toggle":
        v = "pixel" if current() == "nerd" else "nerd"
        set_variant(v)
        print(v)
        return 0
    if cmd == "set" and len(sys.argv) > 2:
        v = sys.argv[2]
        if v not in VARIANTS:
            print("виды: " + ", ".join(VARIANTS) + (" (xp — ещё не нарисован)" if v == "xp" else ""),
                  file=sys.stderr)
            return 2
        set_variant(v)
        print(v)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
