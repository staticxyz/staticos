#!/usr/bin/env python3
"""Меню программ (rofi, SUPER+SPACE) в стиле системы. 05.10.2026.

    launcher_style.py            собрать тему для стиля монитора в фокусе, напечатать путь
    launcher_style.py STYLE      то же для default | skeet | beta

Просьба: «довести стиль до всех окон… если получится так же — оставим, держи бэкап».
Остальные окна (буфер обмена, Preset.exe, Alt+Tab, календарь) уже следуют стилю системы;
лаунчер был в своём «стеклянном» виде. Теперь тема поверх ~/.config/rofi/config.rasi:
окно с заголовком «Programs.exe», поле поиска, список со значками и подсказка снизу, —
в трёх видах: default — окно XP (полоса заголовка тонами «Пуска»), skeet — рамка
gamesense с полоской трёх тонов, beta — плоско с рамкой акцентом. Цвета — палитра обоев
(те же формулы, что rec_style.py / preset_ask.py). Стиль — state/clipboard-style (его
держит system_style.py по монитору в фокусе).

Грабли rofi (пойманы на окне пресетов): у listview с fixed-height НЕЛЬЗЯ ставить
padding/border — высота строк считается без них и последняя строка обрезается; вложенные
переопределения коробок темы-основы (sk-group/sk-body) ломают раскладку — поэтому своя
простая структура: panel → [заголовок, тело → [поиск, список, подсказка]].

Откат: в ~/.config/niri/scripts/shell-do убрать `-theme …` (копия shell-do.bak-launcher).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import rec_style  # noqa: E402

STYLE_FILE = os.path.expanduser("~/.config/hypr/state/clipboard-style")
CACHE = os.path.expanduser("~/.cache/jarvis")
BASE = os.path.expanduser("~/.config/rofi/config.rasi")
TITLE = "Programs.exe"
HINT = "Enter — открыть · Esc — закрыть"
FONT = "PxPlus HP 100LX 6x8 Jarvis"


def read_style():
    try:
        v = open(STYLE_FILE).read().strip().lower()
    except OSError:
        return "default"
    return v if v in ("default", "skeet", "beta") else "default"


def xp_colors():
    p = rec_style.popup_theme.palette()
    try:
        import xpbar_colors
        t = xpbar_colors.colors()
    except Exception:
        t = {}
    base = t.get("base", p["surface"])
    mix = rec_style._mix
    return dict(st_hi=t.get("st_hi", p["primary"]), st_top=t.get("st_top", p["primary"]),
                st_mid=t.get("st_mid", p["primary"]), st_bot=t.get("st_bot", p["surface_high"]),
                st_dark=t.get("st_dark", base), line2=t.get("line2", p["surface_high"]),
                bg=mix(base, p["surface"], 0.5), field=mix(base, p["surface_high"], 0.35),
                row=mix(base, p["surface_high"], 0.55),
                sel=mix(t.get("st_hi", p["primary"]), "#ffffff", 0.18), sel_text=base,
                text=p["on_surface"], dim=p["on_surface_variant"])


COMMON = """
/* {title} — меню программ в стиле «{style}» (собирает launcher_style.py, не править). */
@import "{base}"

* {{ font: "{font} 12"; }}
element-icon {{ size: 32px; }}   /* 32 = двойная сетка пиксельных значков */
listview {{ lines: 8; padding: 0; border: 0; margin: 0; spacing: {lsp}px; fixed-height: true; }}
element {{ padding: {epad}; spacing: 10px; border-radius: 0; }}
inputbar {{ children: [ "prompt", "entry" ]; spacing: 8px; border-radius: 0; }}
prompt {{ str: ""; }}
entry {{ placeholder: "поиск…"; }}
textbox-ltitle {{ expand: false; content: "{title}"; }}
textbox-lhint {{ expand: false; content: "{hint}"; horizontal-align: 1; }}
"""

DEFAULT = """
panel {{
    width: 560px; padding: 0; spacing: 0; border: 3px solid; border-color: {st_mid};
    border-radius: 0; background-color: {bg}; children: [ "textbox-ltitle", "lbody" ];
}}
textbox-ltitle {{
    padding: 4px 10px; text-color: #ffffff; border: 0 0 1px 0; border-color: {st_dark};
    background-image: linear-gradient(to bottom, {st_top}, {st_mid}, {st_bot});
}}
lbody {{ orientation: vertical; padding: 8px; spacing: 8px;
        children: [ "inputbar", "listview", "textbox-lhint" ]; }}
inputbar {{ padding: 5px 8px; border: 1px solid; border-color: {st_mid};
           background-image: linear-gradient({field}, {field}); }}
prompt {{ text-color: {st_hi}; }}
entry {{ text-color: {text}; placeholder-color: {dim}; }}
element normal.normal, element alternate.normal {{ background-color: {row}; text-color: {text}; }}
element selected.normal {{ background-color: {sel}; text-color: {sel_text}; }}
textbox-lhint {{ text-color: {dim}; }}
"""

SKEET = """
panel {{
    width: 560px; padding: 0; spacing: 0; border: 1px solid; border-color: {line1};
    border-radius: 0; background-color: {bg};
    children: [ "lstrip", "lstrip-d", "lbody" ];
}}
lstrip   {{ expand: false; padding: 1px 0 0 0; background-image: linear-gradient(to right, {s0}, {s1}, {s2}); }}
lstrip-d {{ expand: false; padding: 1px 0 0 0; background-image: linear-gradient(to right, {s0d}, {s1d}, {s2d}); }}
lbody {{ orientation: vertical; padding: 8px 10px 10px 10px; spacing: 6px;
        children: [ "textbox-ltitle", "inputbar", "listview", "textbox-lhint" ]; }}
textbox-ltitle {{ padding: 0 2px; text-color: {text}; }}
inputbar {{ padding: 4px 6px; border: 1px solid; border-color: {line1}; background-color: {field}; }}
prompt {{ text-color: {acc}; }}
entry {{ text-color: {text}; placeholder-color: {dim}; }}
listview {{ background-color: {gdark}; }}
element {{ border: 0 0 0 2px; border-color: transparent; }}
element normal.normal, element alternate.normal {{ background-color: transparent; text-color: {text}; }}
element selected.normal {{ background-color: {sel}; border-color: {acc}; text-color: {sel_text}; }}
textbox-lhint {{ padding: 0 2px; text-color: {dim}; }}
"""

BETA = """
panel {{
    width: 560px; padding: 0; spacing: 0; border: 1px solid; border-color: {frame};
    border-radius: 0; background-color: {bg}; children: [ "textbox-ltitle", "lbody" ];
}}
textbox-ltitle {{ padding: 6px 12px; text-color: {text}; background-color: {bar};
                 border: 0 0 1px 0; border-color: {line}; }}
lbody {{ orientation: vertical; padding: 10px; spacing: 8px;
        children: [ "inputbar", "listview", "textbox-lhint" ]; }}
inputbar {{ padding: 5px 8px; border: 1px solid; border-color: {line_strong}; background-color: {field}; }}
prompt {{ text-color: {acc}; }}
entry {{ text-color: {text}; placeholder-color: {dim}; }}
listview {{ background-color: {card}; }}
element {{ border: 1px solid; border-color: transparent; }}
element normal.normal, element alternate.normal {{ background-color: transparent; text-color: {text}; }}
element selected.normal {{ background-color: {sel}; border-color: {frame}; text-color: {sel_text}; }}
textbox-lhint {{ text-color: {dim}; }}
"""


def build(style):
    if style == "skeet":
        c = rec_style.colors("skeet")
        for i, s in enumerate(c["strip"]):
            c["s%d" % i] = s
            c["s%dd" % i] = rec_style._mix(s, "#000000", 0.55)
        body, lsp, epad = SKEET, 1, "3px 8px"
    elif style == "beta":
        c = rec_style.colors("beta")
        c.setdefault("frame", c.get("acc"))
        body, lsp, epad = BETA, 2, "3px 10px"
    else:
        c = xp_colors()
        body, lsp, epad = DEFAULT, 3, "3px 10px"
    text = COMMON.format(title=TITLE, style=style, base=BASE, font=FONT, hint=HINT,
                         lsp=lsp, epad=epad) + body.format(**c)
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "launcher-%s.rasi" % style)
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)
    return path


if __name__ == "__main__":
    st = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("default", "skeet", "beta") else read_style()
    print(build(st))
