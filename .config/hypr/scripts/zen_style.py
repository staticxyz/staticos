#!/usr/bin/env python3
"""Вид Zen в стиле системы — Default / Skeet / Beta (13.10.2026).

    zen_style.py sync     пересобрать блок ZEN-STYLE в конце ~/.config/zen-jarvis/zen-ui.css
    zen_style.py check    совпадает ли блок с выбранным стилем; rc 1 — нет
    zen_style.py off      убрать блок (Zen — как был до 13.10)

Просьба: «Zen: привести к единому виду через userChrome по стилю системы — делай».
userChrome.css браузер читает один раз при запуске, а zen-ui.css live-theme.js сверяет раз
в 1,5 с и подменяет на лету — поэтому стиль живёт блоком в нём, между метками. Остальное в
zen-ui.css (вкладки, YouTube, полоса загрузки) не трогается. Стиль — монитора MSI, если он
подключён, иначе ноутбука (как у микшеров):
  default — ничего не добавляет: Zen как был (углы — как у окон niri);
  skeet   — квадратные углы, рамка страницы в 4 слоя и полоска палитры сверху, как у окна
            Настроек и Super+C; адресная строка — поле skeet; цвета — start_menu.skeet_colors;
  beta    — углы 8 px, рамка страницы и меню акцентом.
Цвета skeet зашиты в блок, поэтому sync зовёт и theme_changer.sh (новые обои), и
system_style.py set (новый стиль).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
UI_CSS = os.path.expanduser("~/.config/zen-jarvis/zen-ui.css")
BEGIN = "/* ZEN-STYLE BEGIN — блок пишет zen_style.py, руками не править */"
END = "/* ZEN-STYLE END */"
MONITORS = ("DP-4", "eDP-1")


def style():
    import system_style
    try:
        outs = system_style.outputs() or []
    except Exception:
        outs = []
    out = next((m for m in MONITORS if m in outs), outs[0] if outs else MONITORS[0])
    return system_style.style_of(out)


def mix(a, b, t):
    a, b = a.lstrip("#"), b.lstrip("#")
    return "#" + "".join("%02x" % round(int(a[i:i + 2], 16) * (1 - t) + int(b[i:i + 2], 16) * t)
                         for i in (0, 2, 4))


def palette():
    import start_menu
    import xpbar_colors
    c = start_menu.skeet_colors(xpbar_colors.colors())
    c["line1_on"] = mix(c["line1"], c["acc"], 0.45)
    return c


RADIUS = """    --jarvis-radius: {r}px !important;
    --zen-border-radius: {r}px !important;
    --zen-native-inner-radius: {r}px !important;
    --toolbarbutton-border-radius: {r}px !important;
    --tab-border-radius: {r}px !important;
    --arrowpanel-menuitem-border-radius: {r}px !important;
    --panel-border-radius: {r}px !important;
    --border-radius-small: {r}px !important;
    --border-radius-medium: {r}px !important;"""

SKEET = """@-moz-document url("chrome://browser/content/browser.xhtml") {{
  :root {{
{radius}
    --arrowpanel-border-color: {line1_on} !important;
    --panel-border-color: {line1_on} !important;
  }}
  /* Страница — в рамке skeet: снаружи внутрь {line1_on} 1 / {line2} 3 / {line1_on} 1 / {line3} 1.
     Сверху рамки нет (13.10, Просьба: «эту линию в браузере лучше убрать сверху») — clip-path
     срезает тень над страницей; полоска палитры и отступ под закладками ушли вместе с ней. */
  #tabbrowser-tabpanels .browserSidebarContainer {{
    border-radius: 0 !important;
    box-shadow: 0 0 0 1px {line3}, 0 0 0 2px {line1_on}, 0 0 0 5px {line2},
                0 0 0 6px {line1_on} !important;
    clip-path: inset(0 -6px -6px -6px) !important;
  }}
  /* Адресная строка — поле skeet; в фокусе обводка акцентом. */
  #urlbar-background {{
    border-radius: 0 !important;
    background-color: {field} !important;
    border: 1px solid {line3} !important;
    box-shadow: inset 0 0 0 1px {line2} !important;
  }}
  #urlbar:is([focused], [open]) > #urlbar-background {{
    box-shadow: inset 0 0 0 1px {acc} !important;
  }}
  /* Выбранная вкладка — полоска акцента слева, как пункт меню skeet. */
  .tabbrowser-tab:not([zen-essential="true"]):is([visuallyselected], [multiselected]) > .tab-stack > .tab-background {{
    border-radius: 0 !important;
    background-color: {field_l} !important;
    outline: 1px solid {line1_on} !important;
    box-shadow: inset 2px 0 0 {acc} !important;
  }}
  .tabbrowser-tab:not([zen-essential="true"]):hover > .tab-stack > .tab-background {{
    border-radius: 0 !important;
    background-color: {field} !important;
  }}
}}"""

BETA = """@-moz-document url("chrome://browser/content/browser.xhtml") {{
  :root {{
{radius}
    --arrowpanel-border-color: {acc} !important;
    --panel-border-color: {acc} !important;
  }}
  /* Страница — плоская карточка, рамка акцентом, углы 8 px. */
  #tabbrowser-tabpanels .browserSidebarContainer {{
    border-radius: 8px !important;
    outline: 1px solid {acc} !important;
    outline-offset: 0 !important;
  }}
  #urlbar-background {{
    border-radius: 8px !important;
    border: 1px solid color-mix(in srgb, {acc} 45%, transparent) !important;
  }}
  #urlbar:is([focused], [open]) > #urlbar-background {{
    border-color: {acc} !important;
  }}
}}"""


def build(st):
    if st == "skeet":
        c = palette()
        body = SKEET.format(radius=RADIUS.format(r=0), **c)
    elif st == "beta":
        c = palette()
        body = BETA.format(radius=RADIUS.format(r=8), **c)
    else:
        body = "/* стиль default — Zen как есть */"
    return "%s\n/* стиль системы: %s */\n%s\n%s\n" % (BEGIN, st, body, END)


def strip(text):
    """zen-ui.css без нашего блока (и без пустых строк, что он оставил в конце)."""
    i = text.find(BEGIN)
    if i < 0:
        return text
    j = text.find(END, i)
    tail = text[j + len(END):] if j >= 0 else ""
    return text[:i].rstrip("\n") + "\n" + tail.lstrip("\n")


def write(block):
    try:
        old = open(UI_CSS, encoding="utf-8").read()
    except OSError:
        return 1                         # Zen не настроен — нечего менять
    base = strip(old)
    new = base if block is None else base.rstrip("\n") + "\n\n" + block
    if new != old:
        tmp = UI_CSS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, UI_CSS)          # mtime сменился — live-theme.js подхватит
    return 0


def current_block():
    try:
        t = open(UI_CSS, encoding="utf-8").read()
    except OSError:
        return None
    i = t.find(BEGIN)
    j = t.find(END, i)
    return t[i:j + len(END)] + "\n" if i >= 0 and j >= 0 else None


def main(a):
    if a == ["sync"]:
        return write(build(style()))
    if a == ["off"]:
        return write(None)
    if a == ["check"]:
        st = style()
        ok = current_block() == build(st)
        print(json.dumps({"style": st, "block_ok": ok}))
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
