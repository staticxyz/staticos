#!/usr/bin/env python3
"""Собирает конфиг waybar для niri из основного (21.09.2026).

Бар у Hyprland и niri общий: ~/.config/waybar/config.jsonc. Но три модуля в нём
говорят с Hyprland и под niri молчат: столы, раскладка и карта ленты. Держать
второй конфиг руками — значит забыть его при первой же правке основного, поэтому
вариант для niri СОБИРАЕТСЯ из основного при каждом входе:

    hyprland/workspaces → niri/workspaces     (показывает ИМЯ стола: туда служба
                                               niri_bar.py names вписывает значок первой
                                               программы. Пустой стол имени не имеет и
                                               показывает номер. Режим «значки/номера» —
                                               ws_labels.py, переключатель в «Настройках»)
    hyprland/language   → custom/language     (bar_language.py: раскладка + подсветка
                                               Caps Lock; щелчок — switch-layout next)
    custom/ribbon       → тот же модуль, но на niri_bar.py ribbon вместо ribbon_map.py
    + niri/window       → название окна в фокусе, правее столов и карты ленты

Остальное — оформление, порядок модулей, include с «видом» — остаётся как есть.
Запуск: из ~/.config/niri/config.kdl перед стартом waybar.
"""
import json
import os
import re
import subprocess

SRC = os.path.expanduser("~/.config/waybar/config.jsonc")
DST = os.path.expanduser("~/.config/waybar/config-niri.jsonc")
STYLE_SRC = os.path.expanduser("~/.config/waybar/style.css")
STYLE_DST = os.path.expanduser("~/.config/waybar/style-niri.css")

# Стиль для niri = общий стиль плюс несколько правил, которые в Hyprland были бы
# лишними. Отдельным файлом, а не строкой в style.css: класс empty есть и у
# модуля Hyprland, и общее правило спрятало бы пустые столы и там, где пользователь
# создаёт их сам (ws_order.py) и должен их видеть.
STYLE_EXTRA = """
/* СОБРАНО АВТОМАТИЧЕСКИ из style.css скриптом ~/.config/niri/scripts/waybar_niri.py.
   Не править: при следующем входе в niri файл будет перезаписан. */

/* Стол-дашборд (имя U+F072C виджеты / U+F0437 терминалы) не прячется и пустым:
   виджеты на нём — слои, не окна, и niri считает его пустым (13.10.2026).
   Waybar зовёт кнопку niri-workspace-<имя стола>. */
/* Пустые столы в баре не показываются: в niri они появляются сами и их всегда
   как минимум один лишний в конце (21.09.2026). Тот, на котором вы сейчас,
   виден всегда — иначе, перейдя на пустой стол, вы бы потеряли его из бара.
   display:none в GTK нет, поэтому кнопка схлопывается до нулевой ширины. */
window#waybar #workspaces button.empty:not(.focused):not(#niri-workspace-\U000f072c):not(#niri-workspace-\U000f0437) {
    padding: 0;
    margin: 0;
    min-width: 0;
    border: none;
    font-size: 0;
    opacity: 0;
}

/* Значки столов — шрифт JarvisBarIcons (~/.config/hypr/scripts/build_bar_icons.py).

   Значки взяты из разных шрифтов (Font Awesome, Material Design, Devicons,
   Symbola, свои волк и Zen), и у каждого свои поля и свой размер рисунка.
   Стилями это не выравнивается: поправка, ровняющая один значок, уводит другой
   (замер 21.09.2026: звёздочке нужно было +1,5 px, терминалу −2,5 px). Поэтому
   все они перенесены в один шрифт и приведены к одному стандарту: большая
   сторона рисунка = 1 em, центр рисунка = центр ячейки, строка = 1 em.

   Следствие: font-size здесь — это БУКВАЛЬНО размер значка в пикселях, а
   отступы симметричные и ничего не «подгоняют». Хотите крупнее или мельче —
   меняйте одно число font-size (и min-width вслед за ним).

   Семейство стоит первым. Чего в нём нет (имя стола, данное руками) — возьмётся
   из следующих по списку. Цифры пустого стола тоже лежат в нём, в той же строке:
   иначе кнопка с цифрой была бы другой высоты и бар дёргался бы при переходе. */
/* ВАЖНО: шрифт задаётся НАДПИСИ (button label), а не кнопке. В начале style.css
   стоит «* { font-size: 13px; font-family: …; font-weight: bold }», и звёздочка
   попадает прямо в надпись — та ничего не наследует от кнопки. Пока размер
   стоял на кнопке, значки оставались 13 px, что бы там ни было написано
   (на этом я потерял десять попыток 21.09.2026). */
#workspaces button label {
    font-family: "JarvisBarIcons", "JetBrainsMono Nerd Font", "Symbola", "Noto Sans", sans-serif;
    /* 17 px — подбирается с пользователем 21.09.2026 (23, 21 и 19 показались крупно). Потолок — 23:
       значок 23 + отступы 2+2 = таблетка 27 px, плюс поля контейнера 2+2 = бар
       31 px. При 26 px бар вырастал до 34 px, и за ним вытягивались все плашки.
       Меняя размер, держите сумму «значок + два отступа» равной 27 — тогда
       таблетка остаётся той же высоты, что кнопка с логотипом Arch слева. */
    font-size: 17px;
    /* normal: жирного начертания у шрифта нет, и Pango «утолщал» бы контуры сам —
       значки заплывают и теряют мелкие детали. */
    font-weight: normal;
}
#workspaces button {
    min-width: 17px;
    padding: 5px 9px;
    margin: 0 3px;
}
#workspaces button.active {
    padding: 5px 13px;
}
/* Стол показан на мониторе, но фокус сейчас на ДРУГОМ мониторе. У waybar это два
   разных признака: active — стол виден на своём мониторе (такой есть на каждом),
   focused — фокус именно здесь (такой один на всю систему). В style.css яркая
   таблетка привязана к active, поэтому горела на обоих мониторах разом, и по
   бару было не понять, какой из них в работе (замечание пользователя 21.09.2026).
   Здесь таблетка остаётся — видно, какой стол открыт, — но приглушённая.
   Контур сделан тенью, а не border: рамка прибавила бы кнопке 2 px высоты,
   и бар бы вырос. */
#workspaces button.active:not(.focused) {
    background-color: alpha(@primary, 0.14);
    box-shadow: inset 0 0 0 1px alpha(@primary, 0.30);
    color: @foreground;
}
/* Скрытый пустой стол: надпись тоже надо схлопнуть, иначе невидимая цифра
   всё равно занимает место и раздвигает соседей. */
window#waybar #workspaces button.empty:not(.focused):not(#niri-workspace-\U000f072c):not(#niri-workspace-\U000f0437) label {
    font-size: 1px;
}
"""

NIRI_WORKSPACES = '''"niri/workspaces": {
        // Собрано waybar_niri.py из hyprland/workspaces — править там, не здесь.
        // {value} — имя стола, а у безымянного (пустого) — его номер.
        "all-outputs": false,
        "format": "{value}"
    }'''

NIRI_RIBBON = '''"custom/ribbon": {
        "exec": "python3 $HOME/.config/niri/scripts/niri_bar.py ribbon",
        "return-type": "json",
        "on-scroll-up": "niri msg action focus-column-left",
        "on-scroll-down": "niri msg action focus-column-right"
    }'''

NIRI_LANGUAGE = '''"custom/language": {
        // Раскладка + Caps Lock: скрипт печатает JSON с классом "caps", когда
        // Caps включён, и CSS красит модуль акцентом (23.09.2026). Штатный
        // niri/language про Caps не знает.
        "exec": "$HOME/.config/hypr/scripts/wb_share language python3 $HOME/.config/hypr/scripts/bar_language.py",
        "return-type": "json",
        "on-click": "niri msg action switch-layout next"
    }'''


NIRI_WINDOW = '''"custom/taskbar": {
        // Панель задач как в XP (taskbar.py, 30.09.2026): кнопки окон текущего
        // стола. Видна только в режиме «панель задач» (window-bar-mode), тогда
        // заголовок окна прячется. Щелчок на весь модуль один: ЛКМ/колесо —
        // следующее окно, ПКМ — предыдущее, СКМ — закрыть.
        "exec": "python3 $HOME/.config/hypr/scripts/taskbar.py",
        "return-type": "json",
        "restart-interval": 2,
        "tooltip": true,
        "on-click": "python3 $HOME/.config/hypr/scripts/taskbar.py next",
        "on-click-right": "python3 $HOME/.config/hypr/scripts/taskbar.py prev",
        "on-click-middle": "python3 $HOME/.config/hypr/scripts/taskbar.py close",
        "on-scroll-up": "python3 $HOME/.config/hypr/scripts/taskbar.py prev",
        "on-scroll-down": "python3 $HOME/.config/hypr/scripts/taskbar.py next"
    },
    "custom/lyrics": {
        // Караоке-строка песни (lyrics_bar.py, 30.09.2026): синхронный текст с
        // lrclib, спетое — акцентом. Пока она видна, заголовок окна прячется
        // (флаг $XDG_RUNTIME_DIR/jarvis-lyrics-on) — вдвоём им места нет.
        "exec": "python3 $HOME/.config/hypr/scripts/lyrics_bar.py",
        "return-type": "json",
        "restart-interval": 10,
        "tooltip": true
    },
    "custom/window-title": {
        // Заголовок окна в фокусе — scripts/bar_window_title.py (обрезка на 25 знаках
        // без пробела перед «…», полный заголовок в подсказке, у каждого монитора свой).
        "exec": "python3 $HOME/.config/hypr/scripts/bar_window_title.py",
        "return-type": "json",
        "restart-interval": 2,
        "tooltip": true
    },
    "niri/window": {
        // Название окна в фокусе. separate-outputs — у каждого монитора своё окно.
        // rewrite срезает хвосты с именем программы: оно и так видно по значку стола.
        "format": "{title}",
        "separate-outputs": true,
        // 25, а не 56 (24.09.2026): правее заголовка стоит pomo. Было 22 — пользователь
        // попросил чуть больше места для текста. Знак в баре 10 px: при 6 столах и
        // одной колонке заголовок кончается на ~531 px, pomo начинается на ~626;
        // при 6 колонках на ленте начало сдвигается на ~90 px — зазор ~5 px, впритык,
        // но не наезжает. Больше 25 — длинный заголовок начнёт толкать pomo.
        "max-length": 25,
        "rewrite": {
            "(.*) — Zen Browser": "$1",
            "(.*) - Helium": "$1",
            "(.*) — LibreWolf": "$1",
            "(.*) - Obsidian v[0-9.]+": "$1",
            "(.*) — Dolphin": "$1"
        }
    },
    '''


def block_end(s, start):
    """Индекс закрывающей скобки объекта, открытого на первой '{' после start.
    Скобки внутри строк и комментариев не считаются."""
    i = s.index("{", start)
    depth, in_str = 0, False
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif s.startswith("//", i):
            i = s.find("\n", i)
            if i < 0:
                break
            continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("не закрыт блок")


def replace_block(s, key, new):
    m = re.search(r'"%s"\s*:' % re.escape(key), s)
    if not m:
        return s
    return s[:m.start()] + new + s[block_end(s, m.end()) + 1:]


# Cozette (08.10.2026, «сколько пустот внутри капсул»): текст 13 px вместо 16, капсулы
# бара ужаты до 22 px (поля 5 px сверху и снизу) — кнопки столов в ту же меру: значок
# 17 → 14 px (13/16), 14 + 4 + 4 = 22. Под PxPlus (правила 61 нет) всё как выше.
# Подгонка выключается флагом (Настройки → Шрифты → «Подгонка размеров под Cozette»,
# cozette_fit.py on|off) — тогда бар как до 08.10: капсулы 26 px, прежние поля.
COZETTE_RULE = os.path.expanduser("~/.config/fontconfig/conf.d/61-cozette-trial.conf")
FIT_FLAG = os.path.expanduser("~/.config/hypr/state/cozette-fit")
STYLE_COZETTE = """
/* Cozette: капсулы 26 → 22 px (поля 5 px сверху и снизу), горизонтальные поля на четверть
   меньше — «сколько пустот внутри капсул» (waybar_niri.py, STYLE_COZETTE). Только
   margin-top/bottom и padding-left/right — прочие поправки style.css не задеваются. */
#custom-launcher, #custom-clock, #cpu, #memory, #temperature, #custom-mpris,
#group-system, #custom-power, #custom-pomo, #custom-lyrics {
    margin-top: 5px;
    margin-bottom: 5px;
}
#custom-clock { padding-left: 5px; padding-right: 7px; }
#cpu, #memory, #temperature, #custom-mpris, #custom-lyrics { padding-left: 7px; padding-right: 7px; }
#network, #bluetooth, #language, #custom-language, #pulseaudio, #custom-volume, #custom-battery,
#network.eth { padding-left: 5px; padding-right: 5px; }
#group-system { padding-left: 3px; padding-right: 3px; }
#custom-pomo, #custom-pomo.idle { padding-left: 5px; padding-right: 7px; }
/* Кнопки столов в меру капсул 22 px. */
#workspaces button label { font-size: 14px; }
#workspaces button { min-width: 14px; padding: 4px 7px; margin: 5px 3px; }
#workspaces button.active { padding: 4px 11px; }
window#waybar #workspaces button.empty:not(.focused):not(#niri-workspace-\U000f072c):not(#niri-workspace-\U000f0437) { padding: 0; margin: 0; }
"""


# Вид системы «Minimalistic» (13.10.2026, просьба: «верхний бар в виде маленькой капсулы, где
# только рабочие столы, время, уровень вайфая и батарея… в виде островка с отступом сверху и
# снизу»; образец — тёмная таблетка по центру). Включает pixel_look.py set minimal. Бар
# остаётся во всю ширину (layer-shell), но прозрачный: видна только средняя группа — она и
# есть капсула. Размытие под баром в этом виде снимает niri/cfg/look.kdl, иначе была бы
# видна размытая полоса. Остальное в этом виде — как в «Гладком».
MINI_HEIGHT, MINI_TOP = 35, 10       # по образцу: капсула 35 px, сверху 10
MINI_MODULES = """"niri/workspaces#mini": {
        // Столы точками: активный — вытянутая таблетка (waybar_niri.py, вид Minimalistic)
        "all-outputs": false,
        "format": "{icon}",
        "format-icons": {"default": ""}
    },
    "clock#mini": {
        "format": "{:%H:%M}",
        "interval": 5,
        "tooltip": false,
        "on-click": "python3 $HOME/.config/hypr/scripts/waybar_clock.py popup"
    },
    "network#mini": {
        // Только уровень сигнала Wi-Fi столбиками (0–3); провод — свой значок
        "interface": "wlp0s20f3",
        "format-wifi": "{icon}",
        "format-icons": ["󰢿", "󰢼", "󰢽", "󰢾", "󰢾"],   // столбики сигнала, как в образце
        "format-ethernet": "󰈀",
        "format-disconnected": "󰤯",
        "format-disabled": "󰤮",
        "tooltip-format": "Сеть: {essid}, сигнал {signalStrength}%",
        "on-click": "python3 $HOME/.config/hypr/scripts/wifi_net_popup.py",
        "on-click-right": "python3 $HOME/.config/hypr/scripts/wifi_popup.py"
    },
    "image#battery-mini": {
        // Батарейка капсулой без цифр (картинка, battery_mini.py); цифры — в подсказке
        "exec": "python3 $HOME/.config/hypr/scripts/battery_mini.py",
        "interval": 15,
        "size": 28,
        "on-click": "python3 $HOME/.config/hypr/scripts/battery_popup.py",
        "on-click-right": "python3 $HOME/.config/hypr/scripts/savage_battery.py --toggle"
    },
    """
STYLE_MINIMAL = """
/* ── Вид системы Minimalistic (waybar_niri.py, STYLE_MINIMAL) ─────────────────────────
   Бар прозрачный, капсула — средняя группа. Правила с window#waybar и в конце файла,
   поэтому перебивают вид бара (looks/current.css) и скругление (rounding.css).
   .mode-default — чтобы перебить и плотность фона из top_bar.py (looks/hover-opacity.css):
   без него за капсулой оставалась полоса alpha(@bar-bg, 0.80) во всю ширину (13.10.2026).
   13.10.2026 вечер, по образцу пользователя (Image #17): чёрная капсула во всю высоту, столы —
   вертикальные точки, время шрифтом Inter (~/.local/share/fonts/Inter), Wi-Fi — столбики,
   батарея — картинка battery_mini.py. */
window#waybar, window#waybar.mode-default,
window#waybar.tb-always.mode-default, window#waybar.tb-hover.mode-default {
    background: transparent;
    border: none;
    border-radius: 0;
    box-shadow: none;
}
window#waybar .modules-left, window#waybar .modules-right { background: transparent; }
window#waybar .modules-center {
    background-color: #000000;
    border-radius: 18px;
    padding: 0 16px;
    box-shadow: none;
    border: none;
}
window#waybar .modules-center > widget > * {
    background: transparent;
    box-shadow: none;
    border: none;
    margin: 0;
}
window#waybar #workspaces.mini button,
window#waybar #workspaces.mini button.active,
window#waybar #workspaces.mini button.active:not(.focused) {
    min-width: 7px;
    min-height: 11px;
    padding: 0;
    margin: 12px 2px;
    border-radius: 4px;
    background-color: alpha(@primary, 0.22);
    box-shadow: none;
    border: none;
}
window#waybar #workspaces.mini button.active {
    min-width: 9px;
    min-height: 14px;
    margin: 10px 2px;
    border-radius: 5px;
    background-color: @primary;
}
window#waybar #workspaces.mini button.active:not(.focused) { background-color: alpha(@primary, 0.55); }
window#waybar #workspaces.mini button:hover { background-color: alpha(@primary, 0.6); }
window#waybar #workspaces.mini button label { font-size: 1px; min-width: 0; padding: 0; }
window#waybar #workspaces.mini { margin-right: 14px; }
window#waybar #clock.mini {
    font-family: "Inter", sans-serif;
    font-weight: 500;
    font-size: 15px;
    font-feature-settings: "tnum";
    color: @foreground;
    padding: 0 14px 0 4px;
}
window#waybar #network.mini {
    font-family: "JetBrainsMono Nerd Font", sans-serif;
    font-weight: normal;
    font-size: 13px;
    color: @primary;
    padding: 0 7px 0 4px;
}
window#waybar #network.mini.disconnected, window#waybar #network.mini.disabled { color: alpha(@primary, 0.35); }
window#waybar #image.battery-mini { padding: 0 0 0 2px; }
"""


def minimal_on():
    try:
        with open(os.path.expanduser("~/.config/hypr/state/pixel-look.json"), encoding="utf-8") as f:
            return json.load(f).get("mode") == "minimal"
    except (OSError, ValueError):
        return False


def minimal_bar(s):
    """Конфиг под капсулу: слева и справа пусто, в середине столы, время, Wi-Fi, батарея."""
    s = re.sub(r'"modules-left"\s*:\s*\[[^\]]*\]', '"modules-left": []', s, count=1)
    s = re.sub(r'"modules-right"\s*:\s*\[[^\]]*\]', '"modules-right": []', s, count=1)
    s = re.sub(r'"modules-center"\s*:\s*\[[^\]]*\]', '"modules-center": ["niri/workspaces#mini", '
               '"clock#mini", "network#mini", "image#battery-mini"]', s, count=1)
    m = re.search(r'^(\s*)"include"\s*:.*,\s*$', s, re.M)
    if m:
        ins = ['"position": "top"', '"height": %d' % MINI_HEIGHT, '"margin-left": 0', '"margin-right": 0',
               '"margin-top": %d' % MINI_TOP, '"margin-bottom": 0']
        s = s[:m.end()] + "\n" + "\n".join(m.group(1) + i + "," for i in ins) + s[m.end():]
    m = re.search(r'"custom/ribbon"\s*:', s)
    if m:
        s = s[:m.start()] + MINI_MODULES + s[m.start():]
    return s


def write_if_changed(path, text):
    """Записать, только если содержимое другое (16.10.2026): у waybar включён
    reload_style_on_change — перезапись того же стиля перерисовывала бары на всех
    мониторах при каждой смене панели одного из них. True — файл изменился."""
    try:
        if open(path, encoding="utf-8").read() == text:
            return False
    except OSError:
        pass
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)
    return True


def build_style():
    try:
        base = open(STYLE_SRC, encoding="utf-8").read()
    except OSError:
        base = ""
    text = base + "\n" + STYLE_EXTRA
    if os.path.exists(COZETTE_RULE) and os.path.exists(FIT_FLAG):
        text += STYLE_COZETTE
    if minimal_on():
        text += STYLE_MINIMAL
    write_if_changed(STYLE_DST, text)


def niri_gaps(default=16):
    """Зазор из конфига niri — строка вида `gaps 16` внутри блока layout.

    С 29.09.2026 конфиг разложен по файлам, и layout живёт в cfg/layout.kdl.
    Ищем сперва там, потом в самом config.kdl — на случай отката к единому файлу.
    """
    txt = ""
    for rel in ("cfg/layout.kdl", "config.kdl"):
        try:
            txt = open(os.path.expanduser("~/.config/niri/" + rel), encoding="utf-8").read()
        except OSError:
            continue
        if re.search(r"^\s*gaps\s+\d+", txt, re.M):
            break
    if not txt:
        return default
    m = re.search(r"^\s*gaps\s+(\d+)", txt, re.M)
    gaps = int(m.group(1)) if m else default
    # Отступ окон от края экрана = gaps + struts (Настройки → «Отступы от краёв
    # экрана», 13.10.2026) — «парящий» бар ровняется по нему, а не по зазору.
    st = re.search(r"^\s*struts\s*\{[^}]*?^\s*left\s+(-?\d+)", txt, re.M | re.S)
    return gaps + (int(st.group(1)) if st else 0)


def look_margin():
    """Боковой отступ текущего вида бара (looks/current.jsonc), 0 — «во всю ширину»."""
    try:
        txt = open(os.path.expanduser("~/.config/waybar/looks/current.jsonc")).read()
    except OSError:
        return 0
    m = re.search(r'"margin-left"\s*:\s*(\d+)', txt)
    return int(m.group(1)) if m else 0


def fix_margins(s):
    """Боковые отступы бара — под зазор niri, а не Hyprland.

    Вид бара (~/.config/waybar/looks/<имя>.jsonc) общий с Hyprland, и отступы
    в «парящем» там равны 20 — это gaps_out из visuals.lua. В niri зазор другой
    (layout.gaps, сейчас 16), поэтому бар стоял на 4 px уже окон: край бара на
    20, край окна на 16 (замерено по снимку 21.09.2026). Свой ключ перебивает
    значение из подключённого файла — проверено, бар встал ровно.

    Но только для «парящих» видов. У вида «во всю ширину» отступы нулевые и
    углы не скруглены — навязанные 16 px оставляли бар обрезанной полосой,
    не достающей до краёв экрана (замечено пользователем 21.09.2026).

    Сам файл вида не трогаем: он общий, и правка сдвинула бы бар в Hyprland.

    Плюс отступы сверху и снизу, если они заданы в «Настройках» → Waybar →
    «Скругления и отступы» (vertical_margins, 01.10.2026) — при любом виде.
    """
    ins = []
    if look_margin() != 0:
        gaps = niri_gaps()
        ins += ['"margin-left": %d' % gaps, '"margin-right": %d' % gaps]
    vm = vertical_margins()
    if vm:
        ins += ['"margin-top": %d' % vm[0], '"margin-bottom": %d' % vm[1]]
    if not ins:
        return s
    m = re.search(r'^(\s*)"include"\s*:.*,\s*$', s, re.M)
    if m:
        return s[:m.end()] + "\n" + "\n".join(m.group(1) + i + "," for i in ins) + s[m.end():]
    return s


BAR_MARGINS = os.path.expanduser("~/.config/hypr/state/bar-margins")


def vertical_margins():
    """(margin-top, margin-bottom) из состояния hypr/scripts/bar_margins.py или None.

    В файле «E W ВИД»: E — от края экрана, у которого стоит бар, W — до окон. У вида
    «Снизу» край — нижний, поэтому пара переворачивается. Нет файла — отступы
    остаются как у вида.

    Отступы действуют только у того вида, при котором заданы (третье поле — имя
    вида, 17.10.2026): 0/0 от «во всю ширину» прижимали к краю и «парящий».
    """
    cur = os.path.expanduser("~/.config/waybar/looks/current.jsonc")
    try:
        e, w, look = open(BAR_MARGINS).read().split()[:3]
        if look != os.path.basename(os.readlink(cur))[:-len(".jsonc")]:
            return None
        e, w = (max(-16, min(32, int(x))) for x in (e, w))
    except (OSError, ValueError):
        return None
    try:
        txt = open(cur).read()
    except OSError:
        txt = ""
    m = re.search(r'"position"\s*:\s*"(\w+)"', txt)
    return (w, e) if m and m.group(1) == "bottom" else (e, w)


def ensure_icon_font():
    """Пересобрать шрифт значков, если его нет или конфиг waybar новее него.

    Значки столов лежат в собственном шрифте (см. STYLE_EXTRA). Новое правило в
    window-rewrite без пересборки взялось бы из Nerd Font — другого размера и не
    по центру, то есть ровно та кривизна, от которой шрифт и избавляет.
    """
    font = os.path.expanduser("~/.local/share/fonts/JarvisBarIcons-Regular.otf")
    builder = os.path.expanduser("~/.config/hypr/scripts/build_bar_icons.py")
    try:
        fresh = os.path.getmtime(font) >= os.path.getmtime(SRC)
    except OSError:
        fresh = False
    if not fresh and os.path.exists(builder):
        subprocess.run(["python3", builder], capture_output=True)


def top_bar_mode(s, mode=None, ws=None):
    """Режим верхнего бара и место столов (03.10.2026, hypr/scripts/top_bar.py).

    hover — бар стартует спрятанным и не резервирует место (ложится поверх окон, когда
    сторож top_bar.py показывает его по наведению). Столы внизу (ws-place = bottom) —
    модуль столов из левой группы убирается: их рисует нижняя XP-панель."""
    state = os.path.expanduser("~/.config/hypr/state/")

    def read(name, default):
        try:
            return open(state + name).read().strip() or default
        except OSError:
            return default
    mode = mode or read("top-bar", "always")
    if mode == "hover":
        s = s.replace('"layer": "top",', '"layer": "top",\n    "exclusive": false,\n    "start_hidden": true,', 1)
    # ws — панели по мониторам: место столов именно этого монитора (panels.ws_for)
    if mode == "off" or (ws or read("ws-place", "top")) == "bottom":
        s = re.sub(r'\n[ \t]*"niri/workspaces",[ \t]*(?=\n[ \t]*"custom/ribbon")', "", s, count=1)
    return s


def pixel_look_on():
    try:
        with open(os.path.expanduser("~/.config/hypr/state/pixel-look.json"), encoding="utf-8") as f:
            return json.load(f).get("mode") == "pixel"
    except (OSError, ValueError):
        return False


def main():
    ensure_icon_font()
    build_style()
    s = open(SRC, encoding="utf-8").read()
    s = replace_block(s, "hyprland/workspaces", NIRI_WORKSPACES)
    s = replace_block(s, "hyprland/language", NIRI_LANGUAGE)
    s = replace_block(s, "custom/ribbon", NIRI_RIBBON)
    # название окна: в список модулей — сразу после карты ленты, определение — перед ней
    # Заголовок окна — свой модуль custom/window-title (24.09.2026): без пробела перед
    # «…» и с полным заголовком в подсказке. Откат — вернуть здесь "niri/window"
    # (его описание NIRI_WINDOW выше оставлено как есть).
    # Панель задач XP и текст песен (30.09.2026) переехали в нижнюю XP-панель
    # (hypr/scripts/xpbar.py): пользователь — «верни как было, в верхний не добавляем».
    # Описания модулей в NIRI_WINDOW оставлены, в ряд они не ставятся.
    s = s.replace('"custom/ribbon"\n', '"custom/ribbon",\n        "custom/window-title"\n', 1)
    # pomo — в конце ЛЕВОЙ группы, сразу за заголовком (13.10.2026, просьба: середину «прибить
    # гвоздями, чтобы её ничего не двигало»). В средней группе остались только датчики, и
    # waybar держит их по центру, пока правая группа не шире ~870 px. Раньше pomo стоял в
    # средней группе с распорками 234/249 px: правая распорка оставляла правой группе ~610 px,
    # и пиксельный шрифт или выдвижной микшер при наведении сдвигали датчики и выдавливали
    # часы за край. Место pomo держит заголовок: bar_window_title.py добивает его пробелами
    # до POMO_X. Откат — .bak-pinCenter.
    # 13.10.2026: перенос pomo в левую группу отменён — вид бара возвращён к 09.10
    # (pomo в средней группе с распоркой custom/gap). Было:
    # s = s.replace('"custom/window-title"\n', '"custom/window-title",\n        "custom/pomo"\n', 1)
    # max-length 12 у network/bluetooth в пиксельном виде снят 13.10.2026: Bluetooth из бара
    # убран, а имя Wi-Fi пользователь хочет видеть целиком.
    m = re.search(r'"custom/ribbon"\s*:', s)
    if m:
        s = s[:m.start()] + NIRI_WINDOW + s[m.start():]
    # упоминания в списках модулей
    s = s.replace('"hyprland/workspaces"', '"niri/workspaces"')
    s = s.replace('"hyprland/language"', '"custom/language"')
    s = minimal_bar(s) if minimal_on() else fix_margins(s)
    head = "// СОБРАНО АВТОМАТИЧЕСКИ из config.jsonc скриптом ~/.config/niri/scripts/waybar_niri.py.\n" \
           "// Не править: при следующем входе в niri файл будет перезаписан.\n"
    write_if_changed(DST, head + top_bar_mode(s))
    per_output(s, head)


def per_output(s, head):
    """Панели по мониторам (hypr/scripts/panels.py, 06.10.2026): свой конфиг на монитор —
    config-niri-<ВЫХОД>.jsonc с одним "output" и режимом этого монитора. Класс tb-always /
    tb-hover (ключ "name") — чтобы плотность фона из Настроек красила каждый бар по его
    режиму (top_bar.opacity_rule). Общий режим — старые файлы убираются."""
    import glob
    import sys
    sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
    keep = set()
    try:
        import panels
        d = panels.load()
        if panels.per_monitor(d):
            for out in panels.top_outputs(d):
                mode = panels.top_for(out, d)
                if mode == "off":
                    continue
                t = re.sub(r'"output"\s*:\s*\[[^\]]*\]', '"output": ["%s"]' % out, s, count=1)
                t = t.replace('"layer": "top",', '"layer": "top",\n    "name": "tb-%s",' % mode, 1)
                path = panels.bar_config(out)
                write_if_changed(path, head + top_bar_mode(t, mode, ws=panels.ws_for(out, d)))
                keep.add(path)
    except Exception as e:
        print("waybar_niri: панели по мониторам: %r" % e, file=sys.stderr)
    for path in glob.glob(os.path.join(os.path.dirname(DST), "config-niri-*.jsonc")):
        if path not in keep:
            os.remove(path)


if __name__ == "__main__":
    main()
