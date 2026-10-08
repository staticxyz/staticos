#!/usr/bin/env python3
"""Discord в стиле системы — Default / Skeet / Beta, как меню «Пуск» (08.10.2026).

Первая версия (08.10, утро) — пиксельный Discord по снимку пользователя: пиксельный шрифт,
квадратные углы, заголовок XP, фон в сердечках. Затем: «сердечки убери, у меня же другой
стиль, можешь взять то, что в Пуске» и «Discord должен сам понимать, какая тема включена в
системе, и применять её сразу». Теперь тема Vencord `themes/pixel.css` (поверх matugen.css
и её «плавающего вида») собирается здесь, в Python, из тех же цветов, что меню «Пуск»:
xpbar_colors.colors() + start_menu.skeet_colors / beta_colors. Общее для всех трёх —
пиксельный шрифт 16 px и красные счётчики; дальше по стилю:
  * Default — шапка окна градиентом «Пуска» XP, рамки, выделение заливкой как в меню;
  * Skeet   — серые skeet, радуга 2 px сверху, двойные рамки, акцент текстом;
  * Beta    — шапка залита акцентом, мягкие скругления, выбор — заливка акцентом.

Какой стиль: стиль монитора, на котором окно Discord (state/system-style, по мониторам);
окна нет — общий стиль, если он один на все мониторы, иначе вид Настроек. Сторож (живёт
в staticos_host) следит за окном Discord и за файлом стиля и пересобирает тему сразу;
Vencord сам видит изменение файла — без перезапуска Discord. При смене обоев тему
пересобирает theme_changer.sh (`sync`). Шрифт Discord видит после своего перезапуска.

    discord_pixel.py            сторож (staticos_host)
    discord_pixel.py on | off | status
    discord_pixel.py sync       пересобрать сейчас (после matugen)
    discord_pixel.py style      какой стиль сейчас выбран и почему
    discord_pixel.py check      самопроверка (для jarvis-doctor)
"""
import json
import os
import shutil
import socket
import string
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
HOME = os.path.expanduser("~")
ST = os.path.join(HOME, ".config/hypr/state")
STATE = os.path.join(ST, "discord-pixel")
SYSSTYLE = os.path.join(ST, "system-style")
SKIN = os.path.join(ST, "settings-skin")
THEMES = os.path.join(HOME, ".config/Vencord/themes")
TARGET = os.path.join(THEMES, "pixel.css")
SETTINGS = os.path.join(HOME, ".config/Vencord/settings/settings.json")
LOG = os.path.join(HOME, ".cache/jarvis/discord-pixel.log")
NAME = "pixel.css"
STYLES = ("default", "skeet", "beta")
APP_IDS = ("discord", "vesktop", "webcord", "legcord")
# Заглушка вместо выключенной темы: файл остаётся в списке Vencord, но пустой —
# так выключение не требует правки settings.json и перезапуска Discord.
STUB = """/**
 * @name Pixel
 * @description Выключено: discord_pixel.py on — включить.
 * @author discord_pixel.py
 */
"""


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), msg))
    except OSError:
        pass


def enabled():
    try:
        return open(STATE).read().strip() != "off"
    except OSError:
        return True                      # по умолчанию включена: так её и просили


def write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


# ── какой стиль ─────────────────────────────────────────────────────────────

def niri_request(req):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(3)
    s.connect(os.environ["NIRI_SOCKET"])
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data).get("Ok") or {}


def is_discord(w):
    return (w.get("app_id") or "").lower() in APP_IDS


def discord_output():
    """Монитор окна Discord (первого найденного) или None."""
    try:
        wins = niri_request("Windows").get("Windows") or []
        ws = {x["id"]: x.get("output") for x in niri_request("Workspaces").get("Workspaces") or []}
        for w in wins:
            if is_discord(w):
                return ws.get(w.get("workspace_id"))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def system_styles():
    try:
        d = json.load(open(SYSSTYLE))
        if isinstance(d, dict):
            return {k: v for k, v in d.items() if v in STYLES}
    except (OSError, ValueError):
        pass
    return {}


def resolve(out):
    """(стиль, почему)."""
    d = system_styles()
    if out and out in d:
        return d[out], "монитор Discord %s" % out
    vals = set(d.values())
    if len(vals) == 1:
        return vals.pop(), "общий стиль системы"
    try:
        v = open(SKIN).read().strip()
        if v in STYLES:
            return v, "вид Настроек"
    except OSError:
        pass
    return "default", "по умолчанию"


# ── цвета: те же, что у меню «Пуск» ─────────────────────────────────────────

def dots_uri(color):
    """Плитка 4×4 с двумя точками (0,0) и (2,2) — узор фона, как у skeet в Настройках.
    SVG прямо в CSS: «#» в data-URI — %23."""
    c = color.lstrip("#")
    return ("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='4' height='4' "
            "shape-rendering='crispEdges'%3E%3Crect width='1' height='1' fill='%23" + c + "'/%3E"
            "%3Crect x='2' y='2' width='1' height='1' fill='%23" + c + "'/%3E%3C/svg%3E\")")


def palette(style):
    """Цвета стиля. Общие ключи для всех трёх: under/dot — подложка окна в цветах обоев
    и её точки; btn* — кнопки-коробочки (панель аккаунта, шапка канала, поле ввода)."""
    import xpbar_colors
    import start_menu
    mix = xpbar_colors.mix
    c = xpbar_colors.colors()
    red = mix(c["error"], "#c00000", 0.55)          # error тёмной схемы розоватый
    if style == "skeet":
        k = start_menu.skeet_colors(c)
        acc = k["acc"]

        def g(level, t=0.05):
            return mix("#%02x%02x%02x" % (level, level, level), acc, t)
        under = mix(k["rail"], acc, 0.16)
        return dict(
            under=under, dot=mix(under, k["acc_l"], 0.28),
            desk=k["rail"], card=k["bg"], deep=k["rail"], field=k["field"], field_l=k["field_l"],
            line1=k["line1"], line2=k["line2"], line3=k["line3"],
            line1_on=mix(k["line1"], acc, 0.45), gline=g(0x30, 0.08), gdark=g(0x0e, 0.03),
            sdot=g(0x18, 0.05), scroll=mix("#414141", acc, 0.06),
            strip_d=", ".join(mix(x, "#000000", 0.55) for x in (acc, k["tertiary"], k["secondary"])),
            text=k["text"], dim=k["text_dim"], icon=k["icon"], icon_on=k["icon_on"],
            acc=acc, acc_l=k["acc_l"], acc_d=k["acc_d"], on_acc="#ffffff",
            r1=acc, r2=k["tertiary"], r3=k["secondary"],
            sel_fg=k["acc_l"], red=red, radius="0px",
            btn1=k["field_l"], btn2=k["field"], btn_edge=k["line3"], btn_hi=g(0x30, 0.08),
            btn_fg=k["text_dim"], btn_hover1=k["field_l"], btn_hover2=k["field_l"],
            btn_hover_fg=k["acc_l"], btn_radius="0px")
    if style == "beta":
        b = start_menu.beta_colors(c)
        under = mix(b["rail"], c["primary"], 0.20)
        return dict(
            under=under, dot=mix(under, c["primary"], 0.40),
            desk=b["rail"], card=b["card"], deep=b["bg"], field=b["field"], bar=b["bar"],
            edge=b["line"], edge_soft=b["line_soft"], edge_strong=b["line_strong"],
            text=b["text"], dim=b["dim"], acc=b["acc"], on_acc=b["on_acc"],
            sel_bg=b["acc"], sel_fg=b["on_acc"], hover=b["hover"],
            t0=b["t0"], t1=b["t1"], t2=b["t2"], ink=b["tile_ink"],
            red=red, radius="8px",
            btn1=b["field"], btn2=b["field"], btn_edge=b["line"], btn_hi=b["line_soft"],
            btn_fg=b["dim"], btn_hover1=b["acc"], btn_hover2=b["acc"],
            btn_hover_fg=b["on_acc"], btn_radius="6px")
    base, p = c["base"], c["primary"]
    under = mix(base, p, 0.24)
    return dict(
        under=under, dot=mix(under, p, 0.40),
        st_hover=c["st_hover"], st_top=c["st_top"], st_mid=c["st_mid"], st_bot=c["st_bot"],
        st_hi=c["st_hi"], st_dark=c["st_dark"], tertiary=c["tertiary"],
        left_bg=mix(base, p, 0.07), right_bg=mix(base, p, 0.17),
        edge=mix(base, p, 0.55), line=mix(base, p, 0.30), hover=mix(base, p, 0.55),
        field=base, text=c["on_surface"], dim=c["on_surface_variant"],
        acc=p, on_acc=c["on_primary"], sel_bg=mix(base, p, 0.55), sel_fg="#ffffff",
        red=red, radius="0px",
        btn1=mix(base, p, 0.22), btn2=mix(base, p, 0.10), btn_edge=mix(base, p, 0.55),
        btn_hi=mix(base, p, 0.34), btn_fg=c["on_surface"],
        btn_hover1=c["st_top"], btn_hover2=c["st_bot"], btn_hover_fg="#ffffff", btn_radius="0px")


# ── CSS ─────────────────────────────────────────────────────────────────────
# $имя — цвет из palette(); CSS идёт через string.Template, чтобы не экранировать «%».
# Повтор класса (.visual-refresh.visual-refresh) поднимает вес над matugen.css, где те же
# переменные заданы на .theme-dark.visual-refresh.

HEAD = """/**
 * @name Pixel
 * @description Discord в стиле системы ($style) — как меню «Пуск», цвета из обоев.
 * @author discord_pixel.py
 */
/* Сгенерировано discord_pixel.py — не править: пересоберётся при смене обоев/стиля. */
"""

VARS_SEL = (":root:root, .theme-dark.theme-dark, .theme-darker.theme-darker, "
            ".theme-midnight.theme-midnight, .theme-dark.visual-refresh.visual-refresh, "
            ".theme-darker.visual-refresh.visual-refresh, .theme-midnight.visual-refresh.visual-refresh")

COMMON = VARS_SEL + """ {
  --px-font: "PxPlus HP 100LX 6x8 Jarvis", "PxPlus HP 100LX 6x8", monospace;
  --px-mono: "PxPlus HP 100LX 6x8", monospace;
  --px-red: $red;
  --font-primary: var(--px-font);
  --font-display: var(--px-font);
  --font-headline: var(--px-font);
  --font-code: var(--px-mono);
  --radius-xs: $radius; --radius-sm: $radius; --radius-md: $radius; --radius-lg: $radius;
  --radius-xl: $radius; --radius-xxl: $radius;
  --jv-radius: $radius;
  --badge-background-default: var(--px-red);
  --badge-text-default: #ffffff;
}

/* шрифт: везде пиксельный, 16 px, без жирного (у PxPlus его нет — браузер мылит) */
html body, html body *:not(svg):not(svg *) {
  font-family: var(--px-font) !important;
  font-size: 16px !important;
  font-weight: normal !important;
  font-synthesis: none !important;
  letter-spacing: 0 !important;
}
html body code, html body pre, html body code *, html body pre * { font-family: var(--px-mono) !important; }
html body [class^="numberBadge_"], html body [class*=" numberBadge_"],
html body [class^="textBadge_"], html body [class*=" textBadge_"],
html body [class^="lowerBadge_"] *, html body [class^="upperBadge_"] * {
  font-size: 8px !important;
  line-height: 8px !important;
}

/* красное: счётчики, «NEW», граница непрочитанного */
html body [class^="numberBadge_"], html body [class*=" numberBadge_"],
html body [class^="textBadge_"], html body [class*=" textBadge_"],
html body [class^="unreadPill_"], html body [class*=" unreadPill_"],
html body [class^="newMessagesBar_"] {
  background-color: var(--px-red) !important;
  color: #ffffff !important;
}
"""

# Общий слой всех трёх стилей (по образцу пользователя, снимок 25): раскладка Discord своя,
# просторная — 08.10 сжатые --space-* слепили значки серверов и строки ЛС («слишком
# прижаты»), так что отступы не трогаем. Мелким (8 px — родной размер PxPlus, чётко)
# делаем только второстепенный текст. Подложка — цвет обоев в точках; в рамках-
# коробочках только кнопки панели аккаунта, окна и вкладки, как на образце.
LAYOUT = """
""" + VARS_SEL + """ {
  --jv-gap: 4px;
  --jv-under: $under;
}

/* второстепенное — 8 px; [class*=] — у Discord нужный класс часто не первый */
html body [class*="timestamp_"], html body [class*="timestamp_"] *,
html body [class*="subText_"], html body [class*="subText_"] *,
html body [class*="panelSubtextContainer_"], html body [class*="panelSubtextContainer_"] *,
html body [class*="activityStatusText_"], html body [class*="customStatus_"],
html body [class*="customStatus_"] *,
html body nav[class*="guilds_"] [class*="acronym_"], html body nav[class*="guilds_"] [class*="acronym_"] *,
html body [class*="unreadMentionsIndicator"], html body [class*="unreadMentionsIndicator"] *,
html body [class*="unreadMentionsBar_"], html body [class*="unreadMentionsBar_"] * {
  font-size: 8px !important; line-height: 10px !important;
}
html body nav[class*="guilds_"] [class*="unreadMentionsBar_"] {
  background: var(--px-red) !important; color: #ffffff !important;
}

/* подложка окна — цвет обоев и мелкие точки */
html body [class^="bg_"], html body [class*=" bg_"] {
  background: $under_dots repeat, $under !important;
}

/* пиксельность: картинки без сглаживания при масштабе, значки ступеньками */
html body img, html body canvas { image-rendering: pixelated !important; }
html body svg * { shape-rendering: crispEdges; }

/* панель аккаунта — плашка в цвете обоев, кнопки в ней — коробочки */
html body section[class^="panels_"] {
  background: $under_dots repeat, $under !important;
}
html body section[class^="panels_"] [class^="buttons_"] { gap: 4px !important; }
html body section[class^="panels_"] [class^="buttons_"] > *,
html body section[class^="panels_"] [class^="actionButtons_"] > *,
html body [class^="winButton_"] {
  background: linear-gradient(to bottom, $btn1, $btn2) !important;
  border: 1px solid $btn_edge !important;
  box-shadow: inset 0 0 0 1px $btn_hi !important;
  border-radius: $btn_radius !important;
  color: $btn_fg !important;
  --interactive-normal: $btn_fg; --interactive-icon-default: $btn_fg;
  box-sizing: border-box !important;
}
html body section[class^="panels_"] [class^="buttons_"] > * {
  height: 32px !important; min-width: 32px !important; width: auto !important;
  display: flex !important; align-items: center !important; justify-content: center !important;
  padding: 0 !important; overflow: hidden !important;
}
html body section[class^="panels_"] [class^="buttons_"] > * button,
html body section[class^="panels_"] [class^="buttons_"] > * [class^="button_"] {
  background: transparent !important; border: none !important; box-shadow: none !important;
  height: 30px !important; min-height: 0 !important;
}
html body section[class^="panels_"] [class*="buttonChevron_"] {
  height: 30px !important; width: 14px !important; margin: 0 !important;
  background: transparent !important; border-left: 1px solid $btn_edge !important;
}
html body section[class^="panels_"] [class^="buttons_"] > :hover,
html body section[class^="panels_"] [class^="actionButtons_"] > :hover,
html body [class^="winButton_"]:hover {
  background: linear-gradient(to bottom, $btn_hover1, $btn_hover2) !important;
  color: $btn_hover_fg !important;
  --interactive-normal: $btn_hover_fg; --interactive-hover: $btn_hover_fg;
  --interactive-icon-default: $btn_hover_fg; --interactive-icon-hover: $btn_hover_fg;
}

/* вкладки (Друзья: В сети / Все / …) — сегменты */
html body [class^="tabBar_"] [class^="item_"] {
  background: linear-gradient(to bottom, $btn1, $btn2) !important;
  border: 1px solid $btn_edge !important; box-shadow: inset 0 0 0 1px $btn_hi !important;
  border-radius: $btn_radius !important; color: $btn_fg !important;
  padding: 2px 8px !important; margin: 0 2px !important;
}
html body [class^="tabBar_"] [class^="item_"][class*="selected_"] {
  background: linear-gradient(to bottom, $btn_hover1, $btn_hover2) !important;
  color: $btn_hover_fg !important;
}
"""

# квадратные углы — Default и Skeet; :not(#…) — вес id, иначе «плавающий вид» сильнее
SQUARE = """
html body *:not(#jv-px), html body *:not(#jv-px)::before, html body *:not(#jv-px)::after { border-radius: 0 !important; }
html body svg foreignObject[mask] { mask: none !important; }
html body nav[class^="guilds_"] [class^="wrapper_"] svg foreignObject { border-radius: 0 !important; }
"""

TITLE = """html body [class^="base_"] > [class^="bar_"],
html body [class^="bar_"]:has(> [class^="title_"]):has(> [class^="trailing_"])"""

DEFAULT = """
/* ── Default: «Пуск» XP — шапка градиентом, рамки, выделение заливкой ─────── */
""" + VARS_SEL + """ {
  --jv-card: $left_bg;
  --jv-edge: $edge;
  --border-subtle: $line; --border-normal: $line; --border-strong: $edge;
}
""" + TITLE + """ {
  background: linear-gradient(to bottom, $st_hover, $st_top 18%, $st_mid 70%, $st_bot) !important;
  box-shadow: inset 0 1px $st_hi, inset 0 -2px $tertiary !important;
  --interactive-normal: #ffffff; --interactive-icon-default: #ffffff;
  --text-default: #ffffff; --text-muted: #ffffff;
}
""" + TITLE.replace(",\n", " *,\n") + """ * { color: #ffffff !important; text-shadow: 1px 1px 1px rgba(0,0,0,.7); }

html body section[class^="title_"] {
  background: linear-gradient(to bottom, $st_mid, $st_bot) !important;
  box-shadow: inset 0 1px $st_hi !important;
  --interactive-normal: #ffffff; --interactive-hover: #ffffff; --interactive-icon-default: #ffffff;
  --header-primary: #ffffff; --header-secondary: #ffffff; --text-default: #ffffff;
  --text-muted: #ffffff; --channel-icon: #ffffff;
}
html body section[class^="panels_"] {
  box-shadow: inset 0 1px $st_hi !important;
  border: 1px solid $edge !important;
}
html body [class^="sidebar_"], html body [class^="chat_"],
html body [class^="membersWrap_"], html body [class^="profilePanel_"] {
  border: 1px solid $edge !important;
}
html body [class^="membersWrap_"], html body [class^="profilePanel_"] { background: $right_bg !important; }

/* выбранный канал / ЛС — как пункт меню под мышью */
html body [class^="sidebar_"] [class*="selected_"] > [class^="link_"],
html body [class^="privateChannels_"] [class*="selected_"] {
  background: $sel_bg !important; color: $sel_fg !important;
  --channels-default: $sel_fg; --interactive-active: $sel_fg;
}
html body [class^="sidebar_"] [class*="selected_"] > [class^="link_"] *,
html body [class^="privateChannels_"] [class*="selected_"] [class^="name_"] { color: $sel_fg !important; }

/* поле ввода и поиск — как строка поиска в «Пуске» */
html body [class^="channelTextArea_"] [class^="scrollableContainer_"],
html body [class^="searchBar_"] {
  background: $field !important; border: 1px solid $line !important;
  box-shadow: inset 1px 1px 2px rgba(0,0,0,.5) !important;
}
html body button[class*="lookFilled_"] {
  background: linear-gradient(to bottom, $st_top, $st_bot) !important;
  border: 1px solid $st_hi !important; color: #ffffff !important;
  text-shadow: 1px 1px rgba(0,0,0,.6);
}
html body ::-webkit-scrollbar-thumb { background-color: $st_mid !important; border: 1px solid $st_hi !important; }
"""

SKEET = """
/* ── Skeet: как окно Настроек в виде skeet — рамка в 4 слоя, полоска палитры
      сверху, серые карточки в точках, кнопки-коробочки, акцент текстом ─────── */
""" + VARS_SEL + """ {
  --jv-card: $card; --jv-edge: $gline;
  --background-base-lowest: $deep; --background-base-lower: $card; --background-base-low: $card;
  --background-surface-high: $field; --background-surface-higher: $field_l;
  --background-surface-highest: $field_l;
  --chat-background-default: $card; --app-frame-background: $deep;
  --input-background-default: $field; --modal-background: $card;
  --background-mod-subtle: $field; --background-mod-normal: $field_l; --background-mod-strong: $field_l;
  --interactive-background-hover: $field; --interactive-background-selected: $field_l;
  --border-subtle: $line2; --border-normal: $line1; --border-strong: $line1;
  --text-default: $text; --text-normal: $text; --text-muted: $dim; --text-secondary: $dim;
  --header-primary: $text; --header-secondary: $dim;
  --interactive-normal: $dim; --interactive-hover: $text; --interactive-active: $acc_l;
  --interactive-muted: $icon; --channels-default: $dim; --channel-icon: $icon;
  --text-link: $acc_l; --text-brand: $acc;
  --button-filled-brand-background: $field_l; --button-filled-brand-background-hover: $field_l;
  --button-filled-brand-text: $acc_l;
}

/* окно: отступ под рамку; рамка и полоска палитры — слоем поверх (::after) */
html body [class^="base_"]:has(> [class^="bar_"]) { padding: 8px 6px 6px 6px !important; position: relative !important; }
html body [class^="base_"]:has(> [class^="bar_"])::after {
  content: ""; position: absolute; inset: 0; pointer-events: none; z-index: 10000;
  background:
    linear-gradient(to right, $r1, $r2, $r3) 0 6px / 100% 1px no-repeat,
    linear-gradient(to right, $strip_d) 0 7px / 100% 1px no-repeat;
  box-shadow: inset 0 0 0 1px $line1_on, inset 0 0 0 2px $line2, inset 0 0 0 3px $line2,
              inset 0 0 0 4px $line2, inset 0 0 0 5px $line1_on, inset 0 0 0 6px $line3;
}
""" + TITLE + """ {
  background: $card !important;
  border-bottom: 1px solid $line3 !important;
  box-shadow: inset 0 -1px $line2 !important;
  --interactive-normal: $icon; --interactive-icon-default: $icon;
}
""" + TITLE.replace(",\n", " [class^=\"title_\"],\n") + """ [class^="title_"] { color: $text !important; }

/* колонка серверов — прозрачная: под ней подложка в цветах обоев с точками */
html body nav[class^="guilds_"] { background: transparent !important; }

/* карточки — фон skeet в точках, рамка-группа */
html body [class^="sidebar_"], html body [class^="chat_"],
html body [class^="membersWrap_"], html body [class^="profilePanel_"] {
  background: $card_dots repeat, $card !important;
  border: 1px solid $gline !important;
  box-shadow: inset 0 0 0 1px $gdark !important;
}
html body [class^="sidebar_"] > *, html body [class^="chat_"] > [class^="content_"],
html body main[class^="chatContent_"], html body [class^="membersWrap_"] > *,
html body [class^="members_"], html body [class^="scroller_"], html body [class^="messagesWrapper_"] {
  background: transparent !important;
}
html body section[class^="title_"] {
  background: $card !important;
  border-bottom: 1px solid $line3 !important; box-shadow: inset 0 -1px $line2 !important;
}
html body section[class^="panels_"] {
  border: 1px solid $gline !important; box-shadow: inset 0 0 0 1px $gdark !important;
}

/* выбранный канал / ЛС — как выбранная вкладка: светлые линии сверху и снизу */
html body [class^="sidebar_"] [class*="selected_"] > [class^="link_"],
html body [class^="privateChannels_"] [class*="selected_"] {
  background: $field !important; color: $sel_fg !important;
  --channels-default: $sel_fg; --interactive-active: $sel_fg;
  box-shadow: inset 0 1px $line1, inset 0 -1px $line1, inset 0 2px $line3, inset 0 -2px $line3 !important;
}
html body [class^="sidebar_"] [class*="selected_"] > [class^="link_"] *,
html body [class^="privateChannels_"] [class*="selected_"] [class^="name_"] { color: $sel_fg !important; }

/* поле ввода и поиск — как поиск в Настройках */
html body [class^="channelTextArea_"] [class^="scrollableContainer_"],
html body [class^="searchBar_"] {
  background: $field !important; border: 1px solid $line3 !important;
  box-shadow: inset 0 0 0 1px $gline !important;
}
/* кнопки с текстом — сегмент skeet; акцентная — с полоской акцента снизу */
html body button[class*="lookFilled_"], html body button[class*="lookOutlined_"] {
  background: linear-gradient(to bottom, $field_l, $field) !important;
  border: 1px solid $line3 !important; color: $acc_l !important;
  box-shadow: inset 0 0 0 1px $gline, inset 0 -2px $acc !important;
}
html body [class^="tabBar_"] [class^="item_"][class*="selected_"] { box-shadow: inset 0 0 0 1px $gline, inset 0 -2px $acc !important; }
html body ::-webkit-scrollbar-thumb { background-color: $scroll !important; border: 1px solid $line3 !important; }
html body ::-webkit-scrollbar-track { background-color: transparent !important; }
"""

BETA = """
/* ── Beta: шапка залита акцентом, мягкие углы, выбор — заливка акцентом ───── */
""" + VARS_SEL + """ {
  --jv-card: $card; --jv-edge: $edge;
  --background-base-lowest: $deep; --background-base-lower: $card; --background-base-low: $card;
  --background-surface-high: $field; --background-surface-higher: $field;
  --background-surface-highest: $field;
  --chat-background-default: $deep; --app-frame-background: $desk;
  --input-background-default: $deep; --modal-background: $card;
  --background-mod-subtle: $hover; --background-mod-normal: $hover;
  --border-subtle: $edge_soft; --border-normal: $edge; --border-strong: $edge_strong;
  --text-default: $text; --text-normal: $text; --text-muted: $dim; --header-primary: $text;
  --header-secondary: $dim; --channels-default: $dim;
  --button-filled-brand-background: $acc; --button-filled-brand-text: $on_acc;
}
""" + TITLE + """ {
  background: $acc !important;
  box-shadow: none !important;
  --interactive-normal: $on_acc; --interactive-icon-default: $on_acc;
  --text-default: $on_acc; --text-muted: $on_acc;
}
""" + TITLE.replace(",\n", " *,\n") + """ * { color: $on_acc !important; }

html body section[class^="title_"] {
  background: $bar !important;
  box-shadow: inset 0 -1px $edge !important;
}
html body section[class^="panels_"] {
  border: 1px solid $edge !important;
}
html body [class^="sidebar_"], html body [class^="chat_"],
html body [class^="membersWrap_"], html body [class^="profilePanel_"] {
  border: 1px solid $edge !important;
}
html body [class^="sidebar_"] [class*="selected_"] > [class^="link_"],
html body [class^="privateChannels_"] [class*="selected_"] {
  background: $sel_bg !important; color: $sel_fg !important;
  --channels-default: $sel_fg; --interactive-active: $sel_fg;
}
html body [class^="sidebar_"] [class*="selected_"] > [class^="link_"] *,
html body [class^="privateChannels_"] [class*="selected_"] [class^="name_"] { color: $sel_fg !important; }
html body [class^="channelTextArea_"] [class^="scrollableContainer_"],
html body [class^="searchBar_"] {
  background: $deep !important; border: 1px solid $edge !important; box-shadow: none !important;
}
html body button[class*="lookFilled_"] { background: $acc !important; color: $on_acc !important; border: none !important; }
html body ::-webkit-scrollbar-thumb { background-color: $acc !important; }
"""


def build(style):
    pal = palette(style)
    pal["style"] = style.capitalize()
    pal["under_dots"] = dots_uri(pal["dot"])
    if "sdot" in pal:
        pal["card_dots"] = dots_uri(pal["sdot"])
    pal.setdefault("radius", "0px")
    body = {"default": DEFAULT, "skeet": SKEET, "beta": BETA}[style]
    css = HEAD + COMMON + LAYOUT + ("" if style == "beta" else SQUARE) + body
    return string.Template(css).substitute(pal)


def current_style():
    """Стиль, записанный в теме сейчас (из шапки файла), или None."""
    try:
        head = open(TARGET).read(400)
    except OSError:
        return None
    for s in STYLES:
        if "в стиле системы (%s)" % s.capitalize() in head:
            return s
    return "off" if "Выключено" in head else None


def sync(out=None, style=None):
    """Пересобрать тему. Файл пишется, только если текст поменялся: каждая запись —
    перезагрузка стилей в открытом Discord."""
    os.makedirs(THEMES, exist_ok=True)
    if enabled():
        style = style or resolve(out if out is not None else discord_output())[0]
        try:
            css = build(style)
        except Exception as e:                  # палитры нет, сменился формат — тему не трогаем
            log("ОШИБКА сборки %s: %r" % (style, e))
            return "не собралась тема: %r" % (e,)
    else:
        css = STUB
    try:
        if open(TARGET).read() == css:
            return None
    except OSError:
        pass
    write(TARGET, css)
    log("тема: %s" % (style if enabled() else "выкл"))
    return None


def discord_running():
    r = subprocess.run(["pgrep", "-x", "-i", "discord|Discord"], capture_output=True)
    return r.returncode == 0


def ensure_listed():
    """pixel.css в enabledThemes, после matugen.css. Правим, только пока Discord закрыт:
    открытый Vencord держит настройки в памяти и при первой же их смене перезапишет файл."""
    try:
        data = json.load(open(SETTINGS))
    except (OSError, ValueError):
        return "нет настроек Vencord"
    themes = data.get("enabledThemes") or []
    if NAME in themes:
        return None
    if discord_running():
        return "Discord открыт — включите тему Pixel в Vencord → Themes или перезапустите Discord и повторите"
    shutil.copy2(SETTINGS, SETTINGS + ".bak-pixel")
    data["enabledThemes"] = themes + [NAME]
    write(SETTINGS, json.dumps(data, indent=4, ensure_ascii=False) + "\n")
    return None


# ── сторож ──────────────────────────────────────────────────────────────────

class Watcher:
    """Окно Discord переехало на монитор другого стиля, сменили стиль системы или вид
    Настроек — пересобрать тему. События niri — для окна, файлы стиля — проверка mtime
    раз в 2 с (дёшево: stat двух файлов)."""

    def __init__(self):
        self.ws_output = {}
        self.dwins = {}                 # id окна Discord → id стола
        self.lock = threading.Lock()
        self.last = None

    def out(self):
        for wsid in self.dwins.values():
            o = self.ws_output.get(wsid)
            if o:
                return o
        return None

    def apply(self):
        with self.lock:
            want = (resolve(self.out())[0], enabled())
            if want != self.last:
                self.last = want
                sync(self.out(), want[0])

    def files_loop(self):
        stamp = None
        while True:
            try:
                s = tuple(os.path.getmtime(p) if os.path.exists(p) else 0 for p in (SYSSTYLE, SKIN, STATE))
                if s != stamp:
                    stamp = s
                    self.apply()
            except Exception as e:
                log("ОШИБКА проверки файлов: %r" % (e,))
            time.sleep(2)

    def handle(self, ev):
        changed = False
        if "WorkspacesChanged" in ev:
            self.ws_output = {x["id"]: x.get("output") for x in ev["WorkspacesChanged"]["workspaces"]}
            changed = True
        elif "WindowsChanged" in ev:
            self.dwins = {w["id"]: w.get("workspace_id") for w in ev["WindowsChanged"]["windows"] if is_discord(w)}
            changed = True
        elif "WindowOpenedOrChanged" in ev:
            w = ev["WindowOpenedOrChanged"]["window"]
            if is_discord(w) and self.dwins.get(w["id"]) != w.get("workspace_id"):
                self.dwins[w["id"]] = w.get("workspace_id")
                changed = True
        elif "WindowClosed" in ev:
            changed = self.dwins.pop(ev["WindowClosed"]["id"], None) is not None
        if changed:
            self.apply()

    def run(self):
        threading.Thread(target=self.files_loop, daemon=True).start()
        s = socket.socket(socket.AF_UNIX)
        s.connect(os.environ["NIRI_SOCKET"])
        s.sendall(b'"EventStream"\n')
        for line in s.makefile("rb"):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                try:
                    self.handle(ev)
                except Exception as e:          # одно странное событие не роняет сторожа
                    log("ОШИБКА в событии %s: %r" % (next(iter(ev), "?"), e))
        return 1                                # niri закрылся — хозяин перезапустит


def check():
    bad = []
    for st in STYLES:
        try:
            css = build(st)
            if "$" in css.split("*/", 2)[-1]:
                bad.append("%s: в теме осталась $переменная" % st)
        except Exception as e:
            bad.append("%s: не собирается (%r)" % (st, e))
    try:
        if NAME not in (json.load(open(SETTINGS)).get("enabledThemes") or []):
            bad.append("pixel.css не включена в Vencord (enabledThemes)")
    except (OSError, ValueError):
        bad.append("не читаются настройки Vencord")
    r = subprocess.run(["fc-list", ":family=PxPlus HP 100LX 6x8 Jarvis"], capture_output=True, text=True)
    if not r.stdout.strip():
        bad.append("шрифт PxPlus HP 100LX 6x8 Jarvis не установлен")
    try:
        if "discord_pixel.py" not in json.load(open(os.path.join(ST, "staticos-host.json"))):
            bad.append("сторожа нет в staticos-host.json — стиль не будет меняться сам")
    except (OSError, ValueError):
        bad.append("не читается staticos-host.json")
    for p in bad:
        print("✗", p)
    print("discord_pixel: в порядке" if not bad else "discord_pixel: проблем %d" % len(bad))
    return 1 if bad else 0


def main():
    cmd = (sys.argv[1:] or ["run"])[0]
    if cmd in ("on", "off"):
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        write(STATE, cmd + "\n")
        for err in (sync(), ensure_listed() if cmd == "on" else None):
            if err:
                print(err)
        print("Discord в стиле системы:", "вкл" if cmd == "on" else "выкл")
        return 0
    if cmd == "sync":
        err = sync()
        if err:
            print(err, file=sys.stderr)
            return 1
        return 0
    if cmd == "style":
        out = discord_output()
        st, why = resolve(out)
        print("%s (%s); в файле: %s" % (st, why, current_style()))
        return 0
    if cmd == "check":
        return check()
    if cmd == "status":
        print("вкл" if enabled() else "выкл")
        return 0
    if cmd == "run":
        return Watcher().run()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
