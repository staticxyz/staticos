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

/* Пустые столы в баре не показываются: в niri они появляются сами и их всегда
   как минимум один лишний в конце (21.09.2026). Тот, на котором вы сейчас,
   виден всегда — иначе, перейдя на пустой стол, вы бы потеряли его из бара.
   display:none в GTK нет, поэтому кнопка схлопывается до нулевой ширины. */
#workspaces button.empty:not(.focused) {
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
#workspaces button.empty:not(.focused) label {
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
#network, #bluetooth, #language, #custom-language, #pulseaudio, #custom-battery,
#network.eth { padding-left: 5px; padding-right: 5px; }
#group-system { padding-left: 3px; padding-right: 3px; }
#custom-pomo, #custom-pomo.idle { padding-left: 5px; padding-right: 7px; }
/* Кнопки столов в меру капсул 22 px. */
#workspaces button label { font-size: 14px; }
#workspaces button { min-width: 14px; padding: 4px 7px; margin: 5px 3px; }
#workspaces button.active { padding: 4px 11px; }
#workspaces button.empty:not(.focused) { padding: 0; margin: 0; }
"""


def build_style():
    try:
        base = open(STYLE_SRC, encoding="utf-8").read()
    except OSError:
        base = ""
    with open(STYLE_DST, "w", encoding="utf-8") as f:
        f.write(base + "\n" + STYLE_EXTRA)
        if os.path.exists(COZETTE_RULE) and os.path.exists(FIT_FLAG):
            f.write(STYLE_COZETTE)


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
    return int(m.group(1)) if m else default


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

    В файле «E W»: E — от края экрана, у которого стоит бар, W — до окон. У вида
    «Снизу» край — нижний, поэтому пара переворачивается. Нет файла — отступы
    остаются как у вида.
    """
    try:
        e, w = (max(0, min(32, int(x))) for x in open(BAR_MARGINS).read().split()[:2])
    except (OSError, ValueError):
        return None
    try:
        txt = open(os.path.expanduser("~/.config/waybar/looks/current.jsonc")).read()
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
    m = re.search(r'"custom/ribbon"\s*:', s)
    if m:
        s = s[:m.start()] + NIRI_WINDOW + s[m.start():]
    # упоминания в списках модулей
    s = s.replace('"hyprland/workspaces"', '"niri/workspaces"')
    s = s.replace('"hyprland/language"', '"custom/language"')
    s = fix_margins(s)
    head = "// СОБРАНО АВТОМАТИЧЕСКИ из config.jsonc скриптом ~/.config/niri/scripts/waybar_niri.py.\n" \
           "// Не править: при следующем входе в niri файл будет перезаписан.\n"
    with open(DST, "w", encoding="utf-8") as f:
        f.write(head + top_bar_mode(s))
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
                with open(path, "w", encoding="utf-8") as f:
                    f.write(head + top_bar_mode(t, mode, ws=panels.ws_for(out, d)))
                keep.add(path)
    except Exception as e:
        print("waybar_niri: панели по мониторам: %r" % e, file=sys.stderr)
    for path in glob.glob(os.path.join(os.path.dirname(DST), "config-niri-*.jsonc")):
        if path not in keep:
            os.remove(path)


if __name__ == "__main__":
    main()
