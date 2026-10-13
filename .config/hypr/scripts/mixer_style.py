#!/usr/bin/env python3
"""Вид микшеров eww — боковой и громкость приложения — в стиле системы (13.10.2026).

    mixer_style.py sync              пересобрать ~/.config/eww/mixer-look.scss (и eww reload)
    mixer_style.py set pixel|normal  пиксельный вид микшеров вкл/выкл (зовёт pixel_look.py)
    mixer_style.py get               pixel | normal
    mixer_style.py check             что выбрано и совпадает ли файл; rc 1 — не совпадает

Просьба: «как они выглядят, мне уже нравится, только сделай чуть-чуть в стиле системы, сейчас
выбран Skeet». Основа — пиксельные правила eww/mixer-pixel.scss; поверх них — стиль монитора,
где показываются микшеры (MSI, если подключён, иначе ноутбук — как :monitor в eww.yuck):
  default — основа как есть (грань светлая сверху-слева, тёмная снизу-справа);
  skeet   — рамка в 4 слоя и полоска палитры сверху, как у окна Настроек; заливка — градиент
            акцента, цвета — start_menu.skeet_colors (те же, что у «Пуска» и Discord);
  beta    — плоская карточка, рамка акцентом, углы 8 px.
Зовут: pixel_look.py (часть «Микшеры»), system_style.py set, theme_changer.sh (новые обои).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ST = os.path.expanduser("~/.config/hypr/state")
MODE = os.path.join(ST, "mixer-look")
OUT = os.path.expanduser("~/.config/eww/mixer-look.scss")
BASE = os.path.expanduser("~/.config/eww/mixer-pixel.scss")
MONITORS = ("DP-4", "eDP-1")       # порядок как у :monitor '["MAG 255XF", 0]'


def get_mode():
    try:
        v = open(MODE).read().strip()
        return v if v in ("pixel", "normal") else "normal"
    except OSError:
        return "normal"


def style():
    import system_style
    try:
        outs = system_style.outputs() or []
    except Exception:
        outs = []
    out = next((m for m in MONITORS if m in outs), outs[0] if outs else MONITORS[0])
    return system_style.style_of(out)


def palette():
    import start_menu
    import xpbar_colors
    return start_menu.skeet_colors(xpbar_colors.colors())


def blocks(direction, gap):
    """Деления полосы: прозрачные 4 px, цвет щели gap 2 px — кладётся поверх заливки."""
    return ("repeating-linear-gradient(%s, transparent 0px, transparent 4px, %s 4px, %s 6px)"
            % (direction, gap, gap))


SKEET = """
// ── Skeet: рамка в 4 слоя (#0a / #3c / #28 / #3c), полоска палитры сверху ──
.vol-container, .appvol {{
  border-radius: 0;
  border: 1px solid {line3};
  background-color: {bg};
  box-shadow: inset 0 0 0 1px {line1}, inset 0 0 0 3px {line2}, inset 0 0 0 4px {line1};
}}
.vol-container {{ padding: 5px 5px 10px 5px; }}
.appvol {{ padding: 5px 12px 6px 12px; }}
.vol-strip {{
  min-height: 2px;
  margin-bottom: 8px;
  background-image: linear-gradient(to right, {acc}, {tertiary}, {secondary});
}}
.appvol .vol-strip {{ margin: 0 -7px 5px -7px; }}
.vol-icon, .appvol-icon {{ color: {icon_on}; }}
.vol-text, .appvol-name {{ color: {text}; }}
.appvol-level {{ color: {acc_l}; }}
.vol-icon.muted, .vol-text.muted {{ color: {err}; }}
.appvol-icon.off {{ color: {text_dim}; }}
scale.vol-slider trough, .appvol-bar {{
  border: 1px solid {line3};
  background-color: {field};
  box-shadow: inset 0 0 0 1px {line2};
}}
scale.vol-slider highlight {{
  background-color: transparent;
  background-image: {vblocks}, linear-gradient(to top, {acc_d}, {acc_l});
}}
scale.vol-slider.muted highlight {{
  background-image: {vblocks}, linear-gradient(to top, {line1}, {text_dim});
}}
.appvol-bar progress {{
  background-color: transparent;
  background-image: {hblocks}, linear-gradient(to bottom, {acc_l}, {acc_d});
}}
"""

BETA = """
// ── Beta: плоская карточка, рамка акцентом, углы 8 px ──
.vol-container, .appvol {{
  border-radius: 8px;
  border: 1px solid {acc};
  background-color: {bg};
  box-shadow: none;
}}
.vol-icon, .appvol-icon, .appvol-level {{ color: {acc_l}; }}
scale.vol-slider trough, .appvol-bar {{ border-radius: 2px; }}
"""


def build(mode, st):
    if mode != "pixel":
        return "// mixer_style.py: обычный вид микшеров — ничего\n"
    head = ("// mixer_style.py: пиксельный вид микшеров, стиль %s. Не править — пересобирается\n"
            "// при смене обоев и стиля системы.\n@import \"%s\";\n" % (st, BASE))
    if st not in ("skeet", "beta"):
        return head
    c = palette()
    c["vblocks"] = blocks("to top", c["field"])
    c["hblocks"] = blocks("to right", c["field"])
    return head + (SKEET if st == "skeet" else BETA).format(**c)


def sync():
    txt = build(get_mode(), style())
    try:
        old = open(OUT).read()
    except OSError:
        old = None
    if txt != old:
        with open(OUT + ".tmp", "w") as f:
            f.write(txt)
        os.replace(OUT + ".tmp", OUT)
        subprocess.run(["eww", "reload"], capture_output=True, timeout=20)
    return 0


def main(a):
    if a == ["sync"]:
        return sync()
    if a == ["get"]:
        print(get_mode())
        return 0
    if len(a) == 2 and a[0] == "set" and a[1] in ("pixel", "normal"):
        os.makedirs(ST, exist_ok=True)
        with open(MODE, "w") as f:
            f.write(a[1] + "\n")
        return sync()
    if a == ["check"]:
        mode, st = get_mode(), style()
        try:
            ok = open(OUT).read() == build(mode, st)
        except OSError:
            ok = False
        print(json.dumps({"mode": mode, "style": st, "file_ok": ok}))
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
