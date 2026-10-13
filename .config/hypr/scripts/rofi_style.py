#!/usr/bin/env python3
"""Все меню rofi — в пиксельном виде и в стиле системы (13.10.2026).

    rofi_style.py sync              пересобрать ~/.cache/jarvis/rofi-*.rasi
    rofi_style.py set pixel|normal  пиксельный вид rofi вкл/выкл (зовёт pixel_look.py)
    rofi_style.py get               pixel | normal
    rofi_style.py check             что выбрано и совпадают ли файлы; rc 1 — нет

Просьба: «Rofi тоже в стиле Skeet… после выбора режима Пиксельный в системе всё должно
стать пиксельным, без исключения». Две части:
  1. rofi-look-STYLE.rasi — вид главного меню (config.rasi подключает в конце
     ~/.cache/jarvis/rofi-look.rasi; это ссылка, её переводит обёртка ~/.local/bin/rofi
     на стиль монитора в фокусе, state/clipboard-style). skeet — рамка line1 и полоска
     палитры в два ряда, как «Programs.exe» launcher_style.py; beta — рамка акцентом;
     default — окно с полосой тонов «Пуска». В обычном виде — пустой файл.
  2. rofi-pixel.rasi — пиксельный шрифт, углы 0 и значки 32 px для ЛЮБОГО меню rofi:
     обёртка ~/.local/bin/rofi передаёт его первым -theme-str, то есть поверх -theme
     файлов (буфер обмена, запись, «Programs.exe»), но раньше -theme-str вызывающего —
     его правки раскладки остаются в силе.
Откат: rofi_style.py set normal (или удалить ~/.local/bin/rofi и строку @import в config.rasi).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
ST = os.path.expanduser("~/.config/hypr/state")
MODE = os.path.join(ST, "rofi-look")
CACHE = os.path.expanduser("~/.cache/jarvis")
PIXEL = os.path.join(CACHE, "rofi-pixel.rasi")
STYLES = ("default", "skeet", "beta")
FONT = "PxPlus HP 100LX 6x8 Jarvis 12"     # 12 pt = 16 px — чёткая сетка 6x8 x2

# Коробки, у которых в темах есть скругления. `*` их не перебивает — правило виджета
# весомее, поэтому перечислены поимённо.
BOXES = ("window", "mainbox", "panel", "lbody", "inputbar", "entry", "prompt", "listview",
         "element", "element-icon", "element-text", "message", "textbox", "button",
         "textbox-ltitle", "textbox-lhint", "button-back", "sk-group", "sk-body", "mode-switcher")


def get_mode():
    try:
        v = open(MODE).read().strip()
        return v if v in ("pixel", "normal") else "normal"
    except OSError:
        return "normal"


def pixel_text():
    return ('* { font: "%s"; } %s { border-radius: 0; } element-icon { size: 32px; }\n'
            % (FONT, ", ".join(BOXES)))


SKEET = """
panel {{
    padding: 0 0 10px 0; spacing: 0; border: 1px solid; border-color: {line1};
    border-radius: 0; background-color: {bg};
    children: [ "lstrip", "lstrip-d", "inputbar", "listview" ];
}}
lstrip   {{ expand: false; padding: 1px 0 0 0; background-image: linear-gradient(to right, {s0}, {s1}, {s2}); }}
lstrip-d {{ expand: false; padding: 1px 0 0 0; background-image: linear-gradient(to right, {s0d}, {s1d}, {s2d}); }}
inputbar {{ margin: 8px 10px 6px 10px; padding: 4px 6px; border: 1px solid; border-color: {line1};
           border-radius: 0; background-color: {field}; }}
prompt {{ text-color: {acc}; }}
entry {{ text-color: {text}; placeholder-color: {dim}; }}
listview {{ margin: 0 10px; spacing: 1px; background-color: {gdark}; }}
message {{ margin: 0 10px; padding: 4px 6px; background-color: {gdark}; }}
textbox {{ text-color: {text}; }}
element {{ padding: 3px 8px; border: 0 0 0 2px; border-color: transparent; border-radius: 0; }}
element normal.normal, element alternate.normal {{ background-color: transparent; text-color: {text}; }}
element selected.normal {{ background-color: {sel}; border-color: {acc}; text-color: {sel_text}; }}
"""

BETA = """
panel {{ border: 1px solid; border-color: {frame}; border-radius: 0; background-color: {bg}; }}
inputbar {{ border: 1px solid; border-color: {line_strong}; border-radius: 0; background-color: {field}; }}
prompt {{ text-color: {acc}; }}
entry {{ text-color: {text}; placeholder-color: {dim}; }}
listview {{ background-color: {card}; }}
element {{ border: 1px solid; border-color: transparent; border-radius: 0; }}
element normal.normal, element alternate.normal {{ background-color: transparent; text-color: {text}; }}
element selected.normal {{ background-color: {sel}; border-color: {frame}; text-color: {sel_text}; }}
"""

DEFAULT = """
panel {{ border: 3px solid; border-color: {st_mid}; border-radius: 0; background-color: {bg};
        padding: 0 0 8px 0; children: [ "lstrip", "inputbar", "listview" ]; }}
lstrip {{ expand: false; padding: 3px 0 0 0;
         background-image: linear-gradient(to bottom, {st_top}, {st_mid}, {st_bot}); }}
inputbar {{ margin: 8px 8px 6px 8px; padding: 5px 8px; border: 1px solid; border-color: {st_mid};
           border-radius: 0; background-image: linear-gradient({field}, {field}); }}
prompt {{ text-color: {st_hi}; }}
entry {{ text-color: {text}; placeholder-color: {dim}; }}
listview {{ margin: 0 8px; }}
message {{ margin: 0 8px; }}
element normal.normal, element alternate.normal {{ background-color: {row}; text-color: {text}; }}
element selected.normal {{ background-color: {sel}; text-color: {sel_text}; }}
"""


def look_text(mode, st):
    # 13.10.2026, просьба: меню программ уже было — launcher.py + launcher_style.py
    # («Programs.exe», меняется со стилем системы). Свой вид главного меню отсюда снят,
    # config.rasi его больше не подключает; файлы остаются пустыми ради обёртки.
    if True:
        return "/* rofi_style.py: обычный вид — ничего */\n"
    import rec_style
    import launcher_style
    if st == "skeet":
        c = rec_style.colors("skeet")
        for i, s in enumerate(c["strip"]):
            c["s%d" % i] = s
            c["s%dd" % i] = rec_style._mix(s, "#000000", 0.55)
        body = SKEET
    elif st == "beta":
        c = rec_style.colors("beta")
        c.setdefault("frame", c.get("acc"))
        c.setdefault("line_strong", c.get("line", c.get("acc")))
        c.setdefault("card", c.get("field"))
        body = BETA
    else:
        c = launcher_style.xp_colors()
        body = DEFAULT
    return ("/* rofi_style.py: вид главного меню rofi, стиль %s. Не править — пересобирается. */\n"
            % st) + body.format(**c)


def wanted():
    mode = get_mode()
    files = {os.path.join(CACHE, "rofi-look-%s.rasi" % s): look_text(mode, s) for s in STYLES}
    files[PIXEL] = pixel_text() if mode == "pixel" else ""
    return files


def write(path, txt):
    with open(path + ".tmp", "w") as f:
        f.write(txt)
    os.replace(path + ".tmp", path)


def sync():
    os.makedirs(CACHE, exist_ok=True)
    for path, txt in wanted().items():
        try:
            if open(path).read() == txt:
                continue
        except OSError:
            pass
        write(path, txt)
    link = os.path.join(CACHE, "rofi-look.rasi")
    if not os.path.exists(link):          # обёртка переводит ссылку при каждом запуске
        os.symlink(os.path.join(CACHE, "rofi-look-default.rasi"), link)
    return 0


def main(a):
    if a == ["sync"]:
        return sync()
    if a == ["get"]:
        print(get_mode())
        return 0
    if len(a) == 2 and a[0] == "set" and a[1] in ("pixel", "normal"):
        os.makedirs(ST, exist_ok=True)
        write(MODE, a[1] + "\n")
        return sync()
    if a == ["check"]:
        ok = True
        for path, txt in wanted().items():
            try:
                ok = ok and open(path).read() == txt
            except OSError:
                ok = False
        wrap = os.access(os.path.expanduser("~/.local/bin/rofi"), os.X_OK)
        inc = "rofi-look.rasi" not in open(os.path.expanduser("~/.config/rofi/config.rasi")).read()
        print(json.dumps({"mode": get_mode(), "files_ok": ok, "wrapper": wrap, "no_dup_import": inc}))
        return 0 if ok and wrap and inc else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
