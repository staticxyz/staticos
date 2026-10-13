#!/usr/bin/env python3
"""Уведомления swaync — пиксельные и в стиле системы (13.10.2026, П9).

    notif_style.py sync              пересобрать блок в ~/.config/swaync/style.css и перечитать CSS
    notif_style.py set pixel|normal  пиксельный вид уведомлений вкл/выкл (зовёт pixel_look.py)
    notif_style.py get               pixel | normal
    notif_style.py check             что выбрано и совпадает ли блок; rc 1 — нет
    notif_style.py css               напечатать CSS блока (для проверки)
    notif_style.py sync-noreload     то же, что sync, без swaync-client -rs (для notif-look)

Просьба: «Не хватает пиксельных уведомлений, в соответствии со стилем системы». Тот же
приём, что у микшеров (mixer_style.py): в пиксельном виде — прямые углы, шрифт PxPlus,
полоска-таймер блоками и ходом ступеньками; поверх — стиль монитора (mixer_style.style()):
  default — грань светлая сверху-слева, тёмная снизу-справа, полоса тонов «Пуска» сверху;
  skeet   — рамка в 4 слоя и полоска палитры, цвета start_menu.skeet_colors;
  beta    — плоская карточка, рамка акцентом, углы 8 px.
Блок вставляется в САМЫЙ КОНЕЦ style.css между метками PIXEL-LOOK — после вида Noctalia
(notif-look), иначе его правила перебили бы наши; notif-look on|off зовёт sync после себя.
Перечитывается только CSS (swaync-client -rs) — история центра уведомлений цела.
Зовут: pixel_look.py (часть «Уведомления»), system_style.py set, theme_changer.sh.
Откат: notif_style.py set normal (в блоке остаётся только шапка с крестиком, head_css).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ST = os.path.expanduser("~/.config/hypr/state")
MODE = os.path.join(ST, "notif-look")
CSS = os.path.expanduser("~/.config/swaync/style.css")
CACHE = os.path.expanduser("~/.cache/jarvis")
B, E = "/* PIXEL-LOOK-BEGIN */", "/* PIXEL-LOOK-END */"
FONT = "PxPlus HP 100LX 6x8 Jarvis"

ROW = ".notification-row .notification-background"
NOTI = ROW + " .notification"
FLOAT = ".floating-notifications"
FIRST = FLOAT + " *:first-child > .notification-row:not(:hover) .notification-background .notification"
OLDER = FLOAT + " *:not(:first-child) > .notification-row .notification-background .notification"
HEAD = ".widget-menubar .cc-head"      # шапка центра: «Clear All» и крестик (config.json)
TIMEOUTS = {"normal": 9, "low": 5}     # = config.json swaync (см. память notif-look)


def get_mode():
    try:
        v = open(MODE).read().strip()
        return v if v in ("pixel", "normal") else "normal"
    except OSError:
        return "normal"


def style():
    import mixer_style
    return mixer_style.style()


def colors(st):
    import start_menu
    import xpbar_colors
    c = start_menu.skeet_colors(xpbar_colors.colors())
    if st not in ("skeet", "beta"):
        import launcher_style
        x = launcher_style.xp_colors()
        c.update(bg=x["bg"], field=x["field"], text=x["text"], text_dim=x["dim"],
                 hi=x["st_hi"], top=x["st_top"], mid=x["st_mid"], bot=x["st_bot"],
                 dark=x["st_dark"], acc_l=x["st_hi"], acc_d=x["st_bot"], line1=x["st_mid"],
                 line3=x["st_dark"])
    return c


def css(st):
    c = colors(st)
    # Полоска-таймер: заливка сжимается к центру ступеньками, поверх — щели цвета карточки,
    # так что видны блоки по 6 px. Скин может добавить свою полосу сверху (extra).
    blocks = ("repeating-linear-gradient(to right, transparent 0px, transparent 6px, %s 6px, %s 8px)"
              % (c["bg"], c["bg"]))
    fill = "linear-gradient(to bottom, %s, %s)" % (c["acc_l"], c["acc"])
    if st == "skeet":
        extra = ("linear-gradient(to right, %s, %s, %s)" % (c["acc"], c["tertiary"], c["secondary"]),
                 "0 0", "100% 2px")
        ty, top_pad = 4, 11
    elif st == "beta":
        extra, ty, top_pad = None, 0, 7
    else:
        extra = ("linear-gradient(to bottom, %s, %s, %s)" % (c["top"], c["mid"], c["bot"]), "0 0", "100% 3px")
        ty, top_pad = 5, 12
    imgs, pos, full, empty = [blocks, fill], ["center %dpx" % ty] * 2, ["100% 4px"] * 2, ["100% 4px", "0% 4px"]
    if extra:
        imgs.append(extra[0])
        pos.append(extra[1])
        full.append(extra[2])
        empty.append(extra[2])
    J = ", ".join
    o = []
    o.append("""/* notif_style.py: пиксельный вид уведомлений, стиль %(st)s. Не править — пересобирается
   при смене обоев, стиля системы и вида (Настройки → Compositor → Стиль). */
.floating-notifications, .control-center, .control-center * , %(row)s, %(row)s * {
    font-family: "%(font)s";
}
%(row)s, %(row)s:hover, %(row)s:focus, %(row)s:active,
.control-center %(row)s, .control-center %(row)s:hover,
.notification-group %(row)s {
    border-radius: 0;
    background-color: %(bg)s;
}
/* Внутренние узлы базовой темы скруглены (--border-radius 12) и обрезали полоски по дуге */
:root { --border-radius: 0; }
%(noti)s, %(noti)s .notification-default-action, %(noti)s .notification-default-action .notification-content,
%(noti)s .notification-alt-actions, .notification-group, .notification-group .notification-row .notification {
    border-radius: 0;
}
%(noti)s .notification-default-action .notification-content .image {
    border-radius: 0;            /* аватарка — квадратом, как пиксель */
}
%(noti)s .notification-default-action { padding-top: %(tp)dpx; }
%(noti)s.critical .notification-default-action { padding-top: 1px; }   /* у срочных (таймер) полоски нет — и места под неё не нужно (13.10) */
%(noti)s .notification-action > button, %(noti)s .notification-default-action + * button,
%(noti)s .notification-action, .widget-title > button, %(head)s button:first-child, %(noti)s .inline-reply .inline-reply-button,
%(noti)s .inline-reply .inline-reply-entry, .control-center .notification-action > button {
    border-radius: 0;
    border: 1px solid %(line1)s;
    background-color: %(field)s;
    background-image: none;
    box-shadow: none;
    color: %(text)s;
}
%(noti)s .notification-action > button:hover, .widget-title > button:hover, %(head)s button:first-child:hover,
.control-center .notification-action > button:hover {
    background-color: %(acc_d)s;
    border-color: %(acc_l)s;
}
.close-button {
    border-radius: 0;
    min-width: 16px;
    min-height: 16px;
}
.close-button:hover { background: %(acc_d)s; color: %(text)s; }
%(noti)s .notification-default-action .notification-content .text-box .summary { color: %(text)s; }
%(noti)s .notification-default-action .notification-content .text-box .body { color: %(text_dim)s; }
.control-center switch, .control-center switch slider, .control-center progressbar,
.control-center progressbar progress, .control-center progressbar trough,
.control-center trough, .control-center slider, .notification-group-buttons button {
    border-radius: 0;
}
.control-center {
    border-radius: 0;
    background-color: %(bg)s;
}
@keyframes jarvis-noti-timer-px {
    from { background-size: %(full)s; }
    to   { background-size: %(empty)s; }
}
%(float)s %(row)s .notification.normal,
%(float)s %(row)s .notification.low {
    background-image: %(imgs)s;
    background-repeat: no-repeat;
    background-position: %(pos)s;
    background-size: %(full)s;
}
%(first)s.normal { animation: jarvis-noti-timer-px %(tn)ds steps(48) 1 forwards; }
%(first)s.low    { animation: jarvis-noti-timer-px %(tl)ds steps(48) 1 forwards; }
%(older)s.normal, %(older)s.low {
    background-image: %(older_img)s;
    background-position: 0 0;
    background-size: %(older_size)s;
    animation: none;
}
""" % dict(c, st=st, font=FONT, row=ROW, noti=NOTI, head=HEAD, tp=top_pad, float=FLOAT, first=FIRST, older=OLDER,
           imgs=J(imgs), pos=J(pos), full=J(full), empty=J(empty),
           tn=TIMEOUTS["normal"], tl=TIMEOUTS["low"],
           older_img=extra[0] if extra else "none", older_size=extra[2] if extra else "auto"))

    frame_rows = "%s, .control-center %s, .notification-group %s" % (ROW, ROW, ROW)
    if st == "skeet":
        o.append("""/* Skeet: рамка в 4 слоя (#0a / #3c / #28 / #3c), как окно Настроек и «Пуск» */
%(fr)s, .control-center {
    border: 1px solid %(line3)s;
    /* GTK 4 кладёт внутренние тени последнюю поверх первой (не как в браузере):
       в обратном порядке 4 px легли сверху и залили всю рамку одним цветом. */
    box-shadow: inset 0 0 0 4px %(line1)s, inset 0 0 0 3px %(line2)s, inset 0 0 0 1px %(line1)s;
}
%(fr)s, .floating-notifications %(row)s { padding: 5px 7px; }   /* у Noctalia-правила .floating-… вес больше */
%(row)s:hover, .control-center %(row)s:hover { background-color: %(field)s; }
/* Внешний край центра уведомлений — акцентом (13.10.2026, просьба: «рамку, чтобы
   была видна, где заканчивается»): тёмные слои на тёмных обоях сливались. */
.control-center { border: 2px solid %(acc)s; }
""" % dict(c, fr=frame_rows, row=ROW))
    elif st == "beta":
        o.append("""/* Beta: плоская карточка, рамка акцентом, углы 8 px (как микшеры Beta) */
%(fr)s, .control-center {
    border: 1px solid %(acc)s;
    border-radius: 8px;
    box-shadow: none;
}
%(row)s:hover, .control-center %(row)s:hover { border-color: %(acc_l)s; background-color: %(field)s; }
""" % dict(c, fr=frame_rows, row=ROW))
    else:
        o.append("""/* Default: окно XP — грань светлая сверху-слева, тёмная снизу-справа, полоса тонов «Пуска» */
%(fr)s, .control-center {
    border: 1px solid;
    border-color: %(hi)s %(dark)s %(dark)s %(hi)s;
    box-shadow: inset 0 0 0 1px %(mid)s;
}
%(fr)s, .floating-notifications %(row)s { padding: 4px 6px; }   /* у Noctalia-правила .floating-… вес больше */
%(row)s:hover, .control-center %(row)s:hover { background-color: %(field)s; }
""" % dict(c, fr=frame_rows, row=ROW))
    return "".join(o)


def close_pngs(st):
    """PNG общего крестика системы (close_cap.py) — обычный и под мышью. В имени —
    отпечаток картинки: GTK держит картинку по адресу, а цвета меняются с обоями."""
    import hashlib
    import close_cap
    out = []
    for hov in (False, True):
        tmp = os.path.join(CACHE, "notif-close.tmp.png")
        close_cap.png(st, tmp, hov)
        h = hashlib.md5(open(tmp, "rb").read()).hexdigest()[:8]
        path = os.path.join(CACHE, "notif-close-%s-%s%s.png" % (st, "h" if hov else "n", h))
        os.replace(tmp, path)
        out.append(path)
    for f in os.listdir(CACHE):                     # старые отпечатки
        if f.startswith("notif-close-") and os.path.join(CACHE, f) not in out:
            try:
                os.remove(os.path.join(CACHE, f))
            except OSError:
                pass
    return out


def head_css(st):
    """Шапка центра уведомлений (13.10.2026, Просьба: «В плашке Уведомлений тоже добавь
    кнопку закрыть»). Виджет title крестика не умеет, поэтому шапка — menubar из
    config.json: слева надпись (кнопка без вида), справа «Clear All» и крестик —
    тот же, что у буфера обмена и всех окон (close_cap.py). Пишется в обоих видах."""
    import close_cap
    n, h = close_pngs(st)
    s = close_cap.size(st)
    return """/* Шапка центра: надпись · Clear All · крестик (notif_style.py head_css) */
.widget-menubar > .menu-button-bar > .start, .widget-menubar > .menu-button-bar > .end { margin: 0; }
.widget-menubar .cc-name button, .widget-menubar .cc-name button:hover {
    background: none; border: none; box-shadow: none; padding: 0; margin: 0;
    min-height: 0; font-size: 16px; color: var(--text-color);
}
%(head)s button:first-child { font-size: 12px; padding: 2px 10px; min-height: 22px; margin: 0 6px 0 0; }
%(head)s button:last-child, %(head)s button:last-child:hover {
    background: url("file://%(n)s") center / %(s)dpx %(s)dpx no-repeat;
    border: none; box-shadow: none; border-radius: 0;
    min-width: %(s)dpx; min-height: %(s)dpx; padding: 0; margin: 0;
}
%(head)s button:last-child:hover { background-image: url("file://%(h)s"); }
""" % dict(head=HEAD, n=n, h=h, s=s)


def block(mode, st):
    body = (css(st) if mode == "pixel" else "") + head_css(st)
    return "%s\n%s%s\n" % (B, body, E)


def split(text):
    """(style.css без нашего блока, наш блок или '')."""
    i = text.find(B)
    if i < 0:
        return text, ""
    j = text.find(E, i)
    j = len(text) if j < 0 else j + len(E)
    if text[j:j + 1] == "\n":
        j += 1
    return text[:i] + text[j:], text[i:j]


def wanted_text(cur, mode, st):
    rest, _old = split(cur)
    blk = block(mode, st)
    if blk and not rest.endswith("\n"):
        rest += "\n"
    return rest + blk


def sync(reload=True):
    cur = open(CSS, encoding="utf-8").read()
    txt = wanted_text(cur, get_mode(), style())
    if txt != cur:
        with open(CSS + ".tmp", "w", encoding="utf-8") as f:
            f.write(txt)
        os.replace(CSS + ".tmp", CSS)
        if reload:
            subprocess.run(["swaync-client", "-rs"], capture_output=True, timeout=10)
    return 0


def main(a):
    if a == ["sync"]:
        return sync()
    if a == ["sync-noreload"]:          # для notif-look: он перечитывает CSS сам
        return sync(reload=False)
    if a == ["get"]:
        print(get_mode())
        return 0
    if a == ["css"]:
        print(css(style()))
        return 0
    if len(a) == 2 and a[0] == "set" and a[1] in ("pixel", "normal"):
        os.makedirs(ST, exist_ok=True)
        with open(MODE, "w") as f:
            f.write(a[1] + "\n")
        return sync()
    if a == ["check"]:
        mode, st = get_mode(), style()
        cur = open(CSS, encoding="utf-8").read()
        ok = cur == wanted_text(cur, mode, st)
        print(json.dumps({"mode": mode, "style": st, "block_ok": ok}))
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
