#!/usr/bin/env python3
"""Стили Recorder (rec_area.sh): Default, Skeet, Beta — как одноимённые виды Настроек. 03.10.2026.

    rec_style.py rasi STYLE   собрать тему rofi для меню Recorder, напечатать путь
                              (~/.cache/jarvis/rec-menu-STYLE.rasi; default — пусто:
                              у него нет своей темы, это нынешний вид лаунчера)

Модулем его читает плашка записи rec_frame.py: colors(style) — цвета плашки.
Выбор стиля хранит rec_area.sh (`rec_area.sh style [X]`, ~/.config/hypr/state/recorder-style).

Цвета — палитра обоев, формулы те же, что у Настроек (settings_app.py: skeet_colors,
beta_colors) и у буфера обмена (clipboard_win.py: style_colors):
  skeet — серые оригинала gamesense (#131313, #282828, #3c3c3c…), чуть подкрашенные
          насыщенным тоном обоев (vivid.txt); полоска сверху — три тона палитры;
  beta  — плоско и прямоугольно, тёмный/светлый — общий режим Настроек (state/settings-mode);
  default — гамма лаунчера rofi (matugen colors.rasi: bg, акцент, outline).
"""
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import popup_theme  # noqa: E402

STYLES = ("default", "skeet", "beta")
STYLE_FILE = os.path.expanduser("~/.config/hypr/state/recorder-style")
MODE_FILE = os.path.expanduser("~/.config/hypr/state/settings-mode")
VIVID = os.path.expanduser("~/.cache/matugen/vivid.txt")
CACHE = os.path.expanduser("~/.cache/jarvis")
ROFI_BASE = os.path.expanduser("~/.config/rofi/config.rasi")


def read_style():
    try:
        v = open(STYLE_FILE).read().strip().lower()
    except OSError:
        return "default"
    return v if v in STYLES else "default"


def _mix(a, b, t):
    a, b = a.lstrip("#")[:6], b.lstrip("#")[:6]
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(round(x * (1 - t) + y * t) for x, y in zip(ca, cb))


def _read(path):
    try:
        return open(path).read().strip().lower()
    except OSError:
        return ""


def colors(style):
    """Словарь #rrggbb: общие имена (bg, field, text, dim, acc, line, sel, sel_text)
    и свои для рамки стиля. Ошибка/красный — «rec» (точка записи всегда красная)."""
    p = popup_theme.palette()
    if style == "skeet":
        acc = p["primary"]
        v = _read(VIVID)
        if v.startswith("#") and len(v) == 7:
            acc = v

        def g(level, t=0.05):
            return _mix("#%02x%02x%02x" % (level, level, level), acc, t)
        c = dict(acc=acc, acc_l=_mix(acc, "#ffffff", 0.22), acc_d=_mix(acc, "#000000", 0.40),
                 bg=g(0x13), field=g(0x1b), field_l=g(0x24),
                 line1=g(0x3c, 0.08), line2=g(0x28, 0.06), line3=g(0x0a, 0.03),
                 gline=g(0x30, 0.08), gdark=g(0x0e, 0.03),
                 text=_mix("#cdcdcd", p["on_surface"], 0.35), dim=g(0x92, 0.10),
                 strip=[acc, p["tertiary"], p["secondary"]])
        c.update(line=c["line1"], sel=c["field_l"], sel_text=c["acc_l"])
        return c
    if style == "beta":
        if _read(MODE_FILE) == "light":
            # как beta_colors() Настроек в режиме Light: тона «Пуска» XP-панели
            try:
                import xpbar_colors
                t = xpbar_colors.colors()
            except Exception:
                t = dict(p, base=p["surface"], st_hi="#9fb4f5", st_mid="#5f74b4", st_bot="#465a94")
            base = t.get("base", p["surface"])
            ink = _mix(base, "#000000", 0.15)
            ink2 = _mix(t["st_bot"], base, 0.35)
            bg = _mix(_mix(t["st_hi"], p["on_surface"], 0.85), "#ffffff", 0.20)
            rail = _mix(t["st_hi"], p["on_surface"], 0.62)
            acc = _mix(t["st_mid"], t["st_bot"], 0.40)
            c = dict(bg=bg, bar=_mix(t["st_hi"], p["on_surface"], 0.45), card=_mix(bg, "#ffffff", 0.45),
                     field=_mix(bg, ink2, 0.10), text=ink, dim=_mix(ink2, bg, 0.22),
                     acc=acc, on_acc=_mix(p["on_surface"], "#ffffff", 0.6),
                     sel=_mix(rail, acc, 0.38), sel_text=ink,
                     line=_mix(bg, ink2, 0.28), line_strong=_mix(bg, ink2, 0.55))
        else:
            bg = p["surface"]
            cont = p["surface_container"]
            c = dict(bg=bg, bar=_mix(bg, cont, 0.85), card=cont, field=p["surface_high"],
                     text=p["on_surface"], dim=_mix(p["on_surface_variant"], bg, 0.30),
                     acc=p["primary"], on_acc=p["on_primary"],
                     sel=_mix(bg, p["primary"], 0.30), sel_text=p["on_surface"],
                     line=_mix(cont, p["on_surface"], 0.16), line_strong=_mix(bg, p["on_surface"], 0.32))
        c["frame"] = p["primary"]
        return c
    # default — гамма лаунчера rofi (те же роли, что в matugen colors.rasi)
    return dict(bg=p.get("surface_lowest", p["surface"]), field=p["surface_high"],
                text=p["on_surface"], dim=p["on_surface_variant"], acc=p["primary"],
                line=p["outline_variant"], sel=_mix(p.get("surface_lowest", p["surface"]), p["primary"], 0.16),
                sel_text=p["primary"])


# ── темы rofi ──────────────────────────────────────────────────────────────
# Основа — ~/.config/rofi/config.rasi (окно на весь экран, поля вокруг панели —
# кнопки «выйти», шрифт, клавиши). Здесь только облик панели. Заголовок меню —
# кнопка button-back (её свойства задаёт rec_area.sh через -theme-str; её цвет —
# переменная @accent, поэтому переопределяем саму переменную).

SKEET_RASI = """/* Меню Recorder — вид Skeet (собирает rec_style.py, не править: перепишется). */
@import "%(base)s"

* {
    font:             "PxPlus HP 100LX 6x8 Jarvis 9";
    accent:           %(acc_l)s;
    fg:               %(text)s;
    fg-alt:           %(dim)s;
}

/* рамка слоями, как у gamesense: 1px тёмная, 1px светлая, 3px средняя, 1px светлая */
panel {
    width:            340px;
    padding:          0;
    spacing:          0;
    border:           1px solid;
    border-color:     %(line3)s;
    border-radius:    0;
    background-color: %(bg)s;
    children:         [ "sk-l1" ];
}
sk-l1 { border: 1px solid; border-color: %(line1)s; children: [ "sk-l2" ]; }
sk-l2 { border: 3px solid; border-color: %(line2)s; children: [ "sk-l3" ]; }
sk-l3 { border: 1px solid; border-color: %(line1)s; children: [ "sk-strip", "sk-strip-d", "sk-body" ];
        background-color: %(bg)s; }
/* полоска трёх тонов палитры сверху, под ней та же темнее */
sk-strip   { expand: false; padding: 1px 0 0 0; background-image: linear-gradient(to right, %(s0)s, %(s1)s, %(s2)s); }
sk-strip-d { expand: false; padding: 1px 0 0 0; background-image: linear-gradient(to right, %(s0d)s, %(s1d)s, %(s2d)s); }
sk-body    { padding: 8px 10px 10px 10px; spacing: 6px; children: [ "inputbar", "sk-group" ]; }

/* заголовок — подпись группы */
inputbar {
    padding:          0 2px;
    border-radius:    0;
    background-color: transparent;
}
/* группа: двойная внутренняя рамка */
sk-group {
    border:           1px solid;
    border-color:     %(gline)s;
    children:         [ "sk-group-in" ];
}
sk-group-in {
    border:           1px solid;
    border-color:     %(gdark)s;
    padding:          4px;
    children:         [ "listview" ];
}
listview { spacing: 1px; }
element {
    padding:          4px 8px;
    border-radius:    0;
    border:           0 0 0 2px;
    border-color:     transparent;
}
element normal.normal, element alternate.normal { background-color: transparent; }
element selected.normal {
    background-color: %(field_l)s;
    border-color:     %(acc)s;
    text-color:       %(acc_l)s;
}
"""

BETA_RASI = """/* Меню Recorder — вид Beta (собирает rec_style.py, не править: перепишется). */
@import "%(base)s"

* {
    font:             "PxPlus HP 100LX 6x8 Jarvis 12";
    accent:           %(text)s;
    fg:               %(text)s;
    fg-alt:           %(dim)s;
}

/* плоско и прямоугольно: рамка 1px акцентом, полоса заголовка, список в карточке */
panel {
    width:            470px;
    padding:          0;
    spacing:          0;
    border:           1px solid;
    border-color:     %(frame)s;
    border-radius:    0;
    background-color: %(bg)s;
}
inputbar {
    padding:          6px 12px;
    border:           0 0 1px 0;
    border-color:     %(line)s;
    border-radius:    0;
    background-color: %(bar)s;
}
listview {
    margin:           10px;
    padding:          4px;
    spacing:          2px;
    border:           1px solid;
    border-color:     %(line)s;
    background-color: %(card)s;
}
element {
    padding:          6px 10px;
    border-radius:    0;
    border:           1px solid;
    border-color:     transparent;
}
element normal.normal, element alternate.normal { background-color: transparent; }
element selected.normal {
    background-color: %(sel)s;
    border-color:     %(acc)s;
    text-color:       %(sel_text)s;
}
"""


# Default — окно XP, как буфер обмена в стиле default (03.10.2026: «Default должен
# быть как в буфере обмена»): рамка 3px, полоса заголовка градиентом панели XP, тёмное
# тело, выбранная строка — светлая заливка с тёмным текстом. Цвета — xpbar_colors.
DEFAULT_RASI = """/* Меню Recorder — вид Default, окно XP (собирает rec_style.py, не править). */
@import "%(base)s"

* {
    font:             "PxPlus HP 100LX 6x8 Jarvis 12";
    accent:           #ffffff;
    fg:               %(text)s;
    fg-alt:           %(dim)s;
}
panel {
    width:            470px;
    padding:          0;
    spacing:          0;
    border:           3px solid;
    border-color:     %(st_mid)s;
    border-radius:    0;
    background-color: %(body)s;
}
inputbar {
    padding:          4px 10px;
    border:           0 0 1px 0;
    border-color:     %(st_dark)s;
    border-radius:    0;
    background-image: linear-gradient(to bottom, %(st_top)s, %(st_mid)s, %(st_bot)s);
}
listview {
    margin:           8px;
    padding:          0;
    spacing:          4px;
    background-color: transparent;
}
element {
    padding:          7px 10px;
    border-radius:    0;
    border:           0;
    background-color: %(row)s;
}
element normal.normal, element alternate.normal { background-color: %(row)s; text-color: %(text)s; }
element selected.normal {
    background-color: %(sel)s;
    text-color:       %(sel_text)s;
}
"""


def rasi(style):
    """Записать тему rofi стиля и вернуть путь."""
    if style not in ("skeet", "beta", "default"):
        return ""
    if style == "default":
        try:
            import xpbar_colors
            t = xpbar_colors.colors()
        except Exception:
            t = {}
        p = popup_theme.palette()
        base = t.get("base", p["surface"])
        c = dict(base=ROFI_BASE, st_mid=t.get("st_mid", p["primary"]), st_hi=t.get("st_hi", p["primary"]),
                 st_top=t.get("st_top", p["primary"]), st_bot=t.get("st_bot", p["surface_high"]),
                 line2=t.get("line2", p["surface_high"]), st_dark=t.get("st_dark", base),
                 body=_mix(base, p["surface"], 0.5), row=_mix(base, p["surface_high"], 0.55),
                 text=p["on_surface"], dim=p["on_surface_variant"],
                 sel=_mix(t.get("st_hi", p["primary"]), "#ffffff", 0.18), sel_text=base)
        text = DEFAULT_RASI % c
        os.makedirs(CACHE, exist_ok=True)
        path = os.path.join(CACHE, "rec-menu-default.rasi")
        with open(path + ".tmp", "w") as f:
            f.write(text)
        os.replace(path + ".tmp", path)
        return path
    c = colors(style)
    c["base"] = ROFI_BASE
    if style == "skeet":
        for i, s in enumerate(c["strip"]):
            c["s%d" % i] = s
            c["s%dd" % i] = _mix(s, "#000000", 0.55)
        text = SKEET_RASI % c
    else:
        text = BETA_RASI % c
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "rec-menu-%s.rasi" % style)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "rasi":
        print(rasi(sys.argv[2]))
    else:
        print(__doc__.split("\n\n")[1])
        sys.exit(2)
