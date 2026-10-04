#!/usr/bin/env python3
"""Шрифты приложений — раздел «Шрифты» в Настройках (17.09.2026).

    app_fonts.py get obsidian|system|kitty|termalt   выбранный шрифт
    app_fonts.py list obsidian|system|kitty|termalt  варианты: ключ<TAB>название
    app_fonts.py set obsidian|system|kitty|termalt КЛЮЧ  выбрать и применить сразу
    app_fonts.py scope                     new|all — трогать ли открытые окна kitty
    app_fonts.py scope new|all             переключить
    app_fonts.py zenfonts                  on|off — навязывать ли шрифт сайтам
    app_fonts.py zenfonts on|off           переключить
    app_fonts.py apply                     применить сохранённое для Obsidian
                                           (зовёт theme_changer.sh после matugen)

Obsidian: шрифт заметок и интерфейса темы Jarvis. Тему пересобирает matugen при
каждой смене обоев, а шаблон знает только шрифт по умолчанию (Hack), поэтому
выбор хранится здесь и после сборки вписывается в theme.css заново. Obsidian
перечитывает theme.css на лету. Если шрифт поменяли в Style Settings → Jarvis,
тот выбор главнее этого.

Система: одно правило fontconfig (~/.config/fontconfig/conf.d/60-jarvis-system-font.conf).
Когда программа просит обычный шрифт — sans-serif, serif, monospace, Noto Sans,
JetBrainsMono Nerd Font и т.п. (SYSTEM_FAMILIES), — перед ним подставляется Hack.
Режим prepend, а не prepend_first: fontconfig дописывает sans-serif в хвост любого
запроса, и prepend_first заменил бы Hack'ом даже шрифты-значки (WolfGlyph, ZenGlyph).
Названный шрифт остаётся следом, поэтому значки Nerd Font, которых в Hack нет,
берутся из JetBrainsMono Nerd Font. «Как было» — файл удаляется. Уже запущенные
программы подхватывают шрифт после перезапуска; waybar перезапускается сразу.
Telegram со своим встроенным шрифтом это не трогает — у него выбор в Настройках чатов.
Zen рисует Hack и без этого: моноширинный шрифт GNOME — Hack 10 (gsettings).

Яндекс Музыка: у неё свой путь — ym_font.py, стиль по порту отладки 9223.
Electron берёт список шрифтов при запуске процесса, поэтому только что
установленный шрифт увидят лишь заново открытые окна — это же касается
Obsidian и Zen.

kitty: строка font_family в ~/.config/kitty/kitty.conf, открытые окна перечитывают
конфиг kitten'ом reload_keep_font.py (как при смене обоев — размер шрифта окон не
сбивается). «Как было» — Noto Sans Mono: в kitty.conf стоял Hasklug Nerd Font,
которого в системе нет, и на деле терминалы рисовали Noto Sans Mono (по /proc maps,
17.09.2026). Имя пишется явно, иначе запасной шрифт подменило бы правило системы.
Значки kitty берёт из встроенного Symbols Nerd Font при любом выборе. После
перечитывания палитра заливается заново (см. apply_kitty) — иначе старые окна
откатываются к цветам обоев, при которых открылись, и btop теряет прозрачность.

scope — кого касается смена шрифта kitty (23.09.2026). По умолчанию "new":
правится только kitty.conf, открытые терминалы остаются как были. Причина —
у нового шрифта другая ширина клетки, и окна, размеры которых пользователь подгонял
руками, после перечитывания съезжают; размер шрифта reload_keep_font.py бережёт,
а сетку сберечь нечем. "all" — прежнее поведение: разослать перечитывание всем.

termalt — шрифт отдельного терминала на Mod+Grave (term_font.sh). Он передаётся
kitty аргументом -o, kitty.conf не трогается вовсе: так шрифт пробуют, ничем
не рискуя. Выбор хранится здесь же, применять нечего.

Список шрифтов больше не задан в коде: его отдаёт fontconfig (families()).
Поставили шрифт в ~/.local/share/fonts — он сам появится в Настройках.
"""
import subprocess
import glob
import json
import os
import re
import sys

STATE = os.path.expanduser("~/.config/hypr/state/app-fonts.json")
OBSIDIAN_THEME = os.path.expanduser("~/Documents/Obsidian/.obsidian/themes/Jarvis/theme.css")
KITTY_CONF = os.path.expanduser("~/.config/kitty/kitty.conf")
KITTY_KITTEN = os.path.expanduser("~/.config/kitty/reload_keep_font.py")
SYSTEM_RULE = os.path.expanduser("~/.config/fontconfig/conf.d/60-jarvis-system-font.conf")
SYSTEM_FAMILIES = [
    "sans-serif", "serif", "monospace", "Sans", "Sans Serif", "Serif", "Monospace", "system-ui",
    "Noto Sans", "Noto Serif", "Noto Sans Mono", "Open Sans", "Cantarell", "DejaVu Sans",
    "DejaVu Sans Mono", "JetBrainsMono Nerd Font", "JetBrains Mono", "JetBrainsMono Nerd Font Mono",
    "JetBrainsMono Nerd Font Propo", "JetBrainsMono NF",
]

ICON_FAMILIES = {
    "JarvisBarIcons", "WolfGlyph", "ZenGlyph", "Symbola", "Noto Color Emoji",
    "Noto Sans Symbols", "Noto Sans Symbols 2", "Noto Music", "mtx",
    "Noto Sans SignWriting", "Noto Sans Math", "Font Awesome 7 Brands",
    "Font Awesome 7 Free", "Font Awesome 7 Free Solid",
}
# «Hack Bold» — начертание, а не отдельный выбор; «JetBrainsMono NF» — то же
# семейство под сокращённым именем, в списке оно лишнее.
STYLE_SUFFIX = re.compile(r"[ ]?(Thin|ExtraLight|Light|Medium|SemiBold|Bold|"
                          r"ExtraBold|Black|Regular|Italic|Blk|Med|Lt|Th|Bk)$")
SHORT_NF = re.compile(r"\bNF[MP]?\b")
# Моноширинность по имени — для шрифтов, не объявивших spacing.
MONO_HINT = re.compile(r"(?i)(mono|code|terminus|cozette|pxplus|px437|fixed|console)")


def families(mono=False):
    """Установленные шрифты, которыми можно набрать русский текст.

    Отбор по :lang=ru — интерфейс тут русский, шрифт без кириллицы сделает из
    Настроек кашу. Значковые шрифты и начертания отсеиваются, иначе список не
    читается.

    mono=True — только для терминала, ему нужна ровная сетка. Одного
    :spacing=100 мало: Noto Sans Mono и CozetteVector моноширинные, но свойство
    spacing у них не выставлено (проверено 23.09.2026), и фильтр выбрасывал их
    из списка. Поэтому моноширинным считается либо объявленный spacing, либо
    говорящее имя.
    """
    try:
        out = subprocess.run(["fc-list", ":lang=ru", "family", "spacing"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ["Hack"]
    names = {}
    for line in out.splitlines():
        head, _, tail = line.partition(":spacing=")
        try:
            spacing = int(tail)
        except ValueError:
            spacing = 0
        for fam in head.split(","):
            fam = fam.strip()
            if not fam or fam in ICON_FAMILIES:
                continue
            if STYLE_SUFFIX.search(fam) or SHORT_NF.search(fam):
                continue
            names[fam] = max(names.get(fam, 0), spacing)
    if mono:
        # «...Nerd Font Propo» — пропорциональный вариант того же семейства,
        # в терминале он не нужен, хотя имя и говорит «Mono».
        names = {f: sp for f, sp in names.items()
                 if (sp >= 90 or MONO_HINT.search(f)) and "Propo" not in f}
    return sorted(names, key=str.lower) or ["Hack"]


APPS = ("obsidian", "system", "kitty", "termalt")


def choices(app):
    """Варианты для выпадающего списка: [(ключ, подпись), ...]."""
    if app == "obsidian":
        return [(f, f) for f in families()] + [("default", "Как в Obsidian")]
    if app == "system":
        return [(f, f) for f in families()] + [("default", "Как было")]
    if app in ("kitty", "termalt"):
        return [(f, f) for f in families(mono=True)]
    raise ValueError("нет раздела %r" % app)


DEFAULTS = {"obsidian": "Hack", "system": "default", "kitty": "Noto Sans Mono",
            "termalt": "PxPlus HP 100LX 6x8"}


def load():
    try:
        with open(STATE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(updates):
    """Дописать ключи в состояние, не потеряв остальные."""
    data = load()
    data.update(updates)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def get(app):
    value = load().get(app, DEFAULTS[app])
    return value if value in dict(choices(app)) else DEFAULTS[app]


def scope():
    """Кого касается смена шрифта kitty: "new" — только новые окна, "all" — все."""
    value = load().get("kitty_scope", "new")
    return value if value in ("new", "all") else "new"


def zen_fonts():
    """Навязывать ли выбранный шрифт содержимому страниц в Zen."""
    value = load().get("zen_document_fonts", "off")
    return value if value in ("on", "off") else "off"


def set_zen_fonts(value):
    if value not in ("on", "off"):
        raise ValueError("zenfonts: on или off, не %r" % value)
    save({"zen_document_fonts": value})
    apply_zen(get("system"))
    return value


def browser_fonts(name):
    """Навязывать ли шрифт содержимому страниц: "librewolf" | "helium"."""
    value = load().get("%s_document_fonts" % name, "off")
    return value if value in ("on", "off") else "off"


def set_browser_fonts(name, value):
    if value not in ("on", "off"):
        raise ValueError("%sfonts: on или off, не %r" % (name, value))
    save({"%s_document_fonts" % name: value})
    font = get("system")
    return apply_librewolf(font) if name == "librewolf" else apply_helium(font)


def set_scope(value):
    if value not in ("new", "all"):
        raise ValueError("scope: new или all, не %r" % value)
    save({"kitty_scope": value})
    return value


def apply_obsidian(font):
    """Вписать шрифт в --jv-font-text и --jv-font-ui темы Jarvis."""
    try:
        with open(OBSIDIAN_THEME, encoding="utf-8") as f:
            css = f.read()
    except OSError:
        return False
    # Имя в кавычках: без них CSS роняет всё правило, если в названии есть
    # слово, начинающееся с цифры («PxPlus HP 100LX 6x8» → «6x8» — недопустимый
    # идентификатор), и Obsidian молча рисует шрифтом по умолчанию (23.09.2026).
    value = "var(--font-default)" if font == "default" else '"%s"' % font
    new, n = re.subn(r"(--jv-font-(?:text|ui): )[^;]*;", lambda m: m.group(1) + value + ";", css)
    if n == 0:
        return False
    if new != css:
        tmp = OBSIDIAN_THEME + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, OBSIDIAN_THEME)
    return True


def system_rule(font):
    from xml.sax.saxutils import escape
    blocks = "".join(
        '  <match target="pattern">\n'
        '    <test name="family" compare="eq" qual="any"><string>%s</string></test>\n'
        '    <edit name="family" mode="prepend" binding="strong"><string>%s</string></edit>\n'
        '  </match>\n' % (escape(fam), escape(font)) for fam in SYSTEM_FAMILIES)
    return ('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n'
            '<!-- Шрифт системы — %s. Пишет ~/.config/hypr/scripts/app_fonts.py\n'
            '     (Настройки → Шрифты), руками не править: «Как было» удаляет файл. -->\n'
            '<fontconfig>\n%s</fontconfig>\n' % (escape(font), blocks))


# Имена шрифтов в настройках GTK и Qt. Правило fontconfig подменяет шрифт при
# отрисовке, но в НАСТРОЙКАХ по-прежнему стоит прежнее имя — и программы,
# которые читают именно настройку (fastfetch, «О системе»), показывают «Sans
# Serif» и «Noto Sans», хотя на экране Hack (замечено пользователем 21.09.2026).
# Поэтому имя пишется и туда: правило fontconfig остаётся страховкой для тех,
# кто настройку не читает.
GTK_SETTINGS = [os.path.expanduser("~/.config/gtk-3.0/settings.ini"),
                os.path.expanduser("~/.config/gtk-4.0/settings.ini")]
QT6CT = os.path.expanduser("~/.config/qt6ct/qt6ct.conf")
UI_FONT_DEFAULT = ("Noto Sans", 10)      # как было до выбора Hack
QT_FONT_DEFAULT = ("Sans Serif", 9)
UI_SIZE_DEFAULT = 10
# Кегль для шрифтов, у которых рисунок пиксельный: они чёткие только когда
# пиксель попадает в пиксель, то есть на кратных размерах. У PxPlus HP 100LX
# 6x8 клетка 8 px по высоте, при 96 dpi это 6, 12, 18 pt; стандартные 10 pt
# дают 13.3 px — буквы мылит (23.09.2026, бар и уведомления).
# «… Jarvis» — та же PxPlus, но длинное тире в две клетки (в оригинале тире и дефис
# нарисованы одинаково); ~/.local/share/fonts/PxPlus_HP_100LX_6x8_Jarvis.ttf, 23.09.2026.
UI_SIZE = {"PxPlus HP 100LX 6x8": 12, "PxPlus HP 100LX 6x8 Jarvis": 12}


def apply_ui_font(family, size):
    """Вписать имя шрифта в настройки GTK, GNOME и Qt."""
    for path in GTK_SETTINGS:
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        new_text = re.sub(r"(?m)^gtk-font-name\s*=.*$",
                          "gtk-font-name=%s %d" % (family, size), text)
        if new_text != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
    subprocess.run(["gsettings", "set", "org.gnome.desktop.interface",
                    "font-name", "%s %d" % (family, size)], capture_output=True)
    # Моноширинный шрифт GNOME — отдельная настройка, и её мало кто вспоминает.
    # Её берут виджеты GTK со свойством monospace: текст в Keypunch, поля ввода
    # в GNOME-программах, терминал GNOME. Без этой строки они оставались на
    # Hack, пока весь остальной интерфейс уже был на выбранном шрифте
    # (замечено пользователем на Keypunch 23.09.2026).
    subprocess.run(["gsettings", "set", "org.gnome.desktop.interface",
                    "monospace-font-name", "%s %d" % (family, size)],
                   capture_output=True)
    try:
        text = open(QT6CT, encoding="utf-8").read()
    except OSError:
        return
    qt_family, qt_size = (family, size) if family != QT_FONT_DEFAULT[0] else QT_FONT_DEFAULT
    new_text = re.sub(r'(?m)^(general|fixed)="[^",]+,\d+',
                      lambda m: '%s="%s,%d' % (m.group(1), qt_family, qt_size), text)
    if new_text != text:
        with open(QT6CT, "w", encoding="utf-8") as f:
            f.write(new_text)


ZEN_PROFILES = os.path.expanduser("~/.config/zen")
ZEN_MARK_OPEN = "// >>> шрифт системы — пишет app_fonts.py, руками не править"
ZEN_MARK_CLOSE = "// <<< шрифт системы"


def apply_zen(font):
    """Шрифт интерфейса Zen — в user.js каждого профиля.

    Страницы шрифт подхватывают и так: Zen просит у fontconfig sans-serif,
    а тот по правилу системы отдаёт выбранный шрифт. А вот интерфейс Zen
    рисует своим ключом темы theme.custom_uifont.custom (мод Zen, оттуда
    берётся --theme-custom_uifont-custom в chrome/zen-themes.css) — его
    fontconfig не касается, поэтому имя пишется туда явно.

    user.js применяется при КАЖДОМ запуске браузера: правка вступит в силу
    после перезапуска Zen, зато переживёт сброс настроек.
    """
    value = '"JetBrainsMono Nerd Font", monospace' if font == "default" else '"%s", monospace' % font
    # use_document_fonts = 0 — запретить сайтам ставить свои шрифты. Только так
    # шрифт доходит до страниц, которые везут шрифт с собой (чат YouTube и
    # прочие рамки с @font-face): подстановка fontconfig таким не указ. Цена —
    # сайты, рисующие значки шрифтом (Material Icons, Font Awesome), покажут
    # вместо значков буквы. Поэтому это отдельный переключатель в Настройках,
    # а не часть выбора шрифта.
    lines = [
        ZEN_MARK_OPEN,
        'user_pref("theme.custom_uifont.custom", %s);' % json.dumps(value),
        'user_pref("theme.custom_uifont.default", "Custom");',
        'user_pref("browser.display.use_document_fonts", %d);'
        % (0 if zen_fonts() == "on" else 1),
    ]
    if zen_fonts() == "on" and font != "default":
        for group in ("x-western", "x-cyrillic"):
            for kind in ("serif", "sans-serif", "monospace"):
                lines.append('user_pref("font.name.%s.%s", %s);'
                             % (kind, group, json.dumps(font)))
    lines.append(ZEN_MARK_CLOSE)
    block = "\n".join(lines)
    done = False
    try:
        names = os.listdir(ZEN_PROFILES)
    except OSError:
        return False
    for name in names:
        path = os.path.join(ZEN_PROFILES, name, "user.js")
        if not os.path.exists(path):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        if ZEN_MARK_OPEN in text and ZEN_MARK_CLOSE in text:
            head, _, rest = text.partition(ZEN_MARK_OPEN)
            _, _, tail = rest.partition(ZEN_MARK_CLOSE)
            new = head + block + tail
        else:
            new = text.rstrip("\n") + "\n\n" + block + "\n"
        if new != text:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(new)
            os.replace(tmp, path)
        done = True
    return done


# Куда класть overrides: LibreWolf ищет его рядом с профилем. У нас профиль
# лежит по XDG (~/.config/librewolf/librewolf/<id>.default-default), а не в
# ~/.librewolf — поэтому 25.09.2026 файл в ~/.librewolf просто не читался.
LW_DIRS = [os.path.expanduser("~/.config/librewolf"),
           os.path.expanduser("~/.librewolf")]
LW_MARK_OPEN = "// >>> шрифт системы — пишет app_fonts.py, руками не править"
LW_MARK_CLOSE = "// <<< шрифт системы"
HE_EXT = os.path.expanduser("~/.config/hypr/state/helium-font")
HE_FLAGS = os.path.expanduser("~/.config/helium-browser-flags.conf")


def apply_librewolf(font):
    """Шрифт страниц LibreWolf — через его же overrides.cfg (25.09.2026).

    У LibreWolf есть свой autoconfig: ~/.librewolf/librewolf.overrides.cfg
    читается при каждом запуске и действует на ВСЕ профили — значит не нужно
    искать папку профиля, как у Zen, и правка переживает создание нового.

    `pref` (а не `defaultPref`): значение ставится при каждом старте, иначе
    прежний ручной выбор в настройках оказался бы главнее.
    """
    on = browser_fonts("librewolf") == "on" and font != "default"
    lines = [LW_MARK_OPEN]
    # lockPref, а не pref: значения из prefs.js профиля применяются ПОЗЖЕ
    # autoconfig и перебили бы обычный pref — шрифт на страницах не менялся.
    if font != "default":
        for group in ("x-western", "x-cyrillic"):
            for kind in ("serif", "sans-serif", "monospace"):
                lines.append('lockPref("font.name.%s.%s", %s);' % (kind, group, json.dumps(font)))
    # 0 — сайтам свой шрифт не отдаём; 1 — как было. Цена «0» та же, что у Zen:
    # сайты со значками-шрифтами (Material Icons) покажут буквы.
    lines.append('lockPref("browser.display.use_document_fonts", %d);' % (0 if on else 1))
    lines.append(LW_MARK_CLOSE)
    block = "\n".join(lines)

    # user.js каждого профиля — главный путь (25.09.2026). overrides.cfg этой
    # сборки не читался вовсе: при трёх запусках браузера время доступа к
    # файлу не менялось ни в ~/.librewolf, ни в ~/.config/librewolf. user.js
    # же Firefox применяет при каждом старте — тот же приём, что у Zen.
    ulines = [LW_MARK_OPEN]
    if font != "default":
        for group in ("x-western", "x-cyrillic"):
            for kind in ("serif", "sans-serif", "monospace"):
                ulines.append('user_pref("font.name.%s.%s", %s);' % (kind, group, json.dumps(font)))
    ulines.append('user_pref("browser.display.use_document_fonts", %d);' % (0 if on else 1))
    ulines.append(LW_MARK_CLOSE)
    ublock = "\n".join(ulines)
    done = False
    for base in LW_DIRS:
        for prof in glob.glob(os.path.join(base, "librewolf", "*.default*")) + \
                    glob.glob(os.path.join(base, "*.default*")):
            if not os.path.isdir(prof):
                continue
            path = os.path.join(prof, "user.js")
            try:
                text = open(path, encoding="utf-8").read()
            except OSError:
                text = ""
            if LW_MARK_OPEN in text and LW_MARK_CLOSE in text:
                head, _, rest = text.partition(LW_MARK_OPEN)
                _, _, tail = rest.partition(LW_MARK_CLOSE)
                new = head + ublock + tail
            else:
                new = (text.rstrip("\n") + "\n\n" if text else "") + ublock + "\n"
            if new != text:
                try:
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write(new)
                    os.replace(tmp, path)
                except OSError:
                    continue
            done = True
    for base in LW_DIRS:
        if not os.path.isdir(base):
            continue
        path = os.path.join(base, "librewolf.overrides.cfg")
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            text = "// Создан app_fonts.py\n"
        if LW_MARK_OPEN in text and LW_MARK_CLOSE in text:
            head, _, rest = text.partition(LW_MARK_OPEN)
            _, _, tail = rest.partition(LW_MARK_CLOSE)
            new = head + block + tail
        else:
            new = text.rstrip("\n") + "\n\n" + block + "\n"
        if new != text:
            try:
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(new)
                os.replace(tmp, path)
            except OSError:
                continue
        done = True
    return done


def apply_helium(font):
    """Шрифт страниц Helium — маленьким расширением (25.09.2026).

    Helium на Chromium, а там нет ни user.js, ни «не доверять шрифтам сайта»:
    настройки шрифтов действуют только на страницы БЕЗ своих @font-face.
    Поэтому шрифт навязывает расширение с таблицей стилей; оно всегда
    подключено флагом --load-extension (рядом с темой matugen), а когда
    переключатель выключен — его CSS пуст, и браузер работает как обычно.
    """
    on = browser_fonts("helium") == "on" and font != "default"
    css = ""
    if on:
        # Значки-шрифты (Material Icons и подобные) объявляют себя семейством
        # с «icon» в имени — их не трогаем, иначе вместо значков будут буквы.
        css = ('*:not([class*="icon" i]):not([class*="material-symbols" i]) {\n'
               '  font-family: %s, monospace !important;\n}\n' % json.dumps(font))
    manifest = {
        "manifest_version": 3,
        "name": "Jarvis system font",
        "version": "1.0",
        "description": "Шрифт системы на страницах — пишет app_fonts.py",
        "content_scripts": [{"matches": ["<all_urls>"], "css": ["font.css"],
                             "run_at": "document_start", "all_frames": True}],
    }
    try:
        os.makedirs(HE_EXT, exist_ok=True)
        with open(os.path.join(HE_EXT, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        with open(os.path.join(HE_EXT, "font.css"), "w", encoding="utf-8") as f:
            f.write(css)
    except OSError:
        return False
    return add_helium_flag()


def add_helium_flag():
    """Прописать расширение в строку --load-extension, не тронув остальные."""
    try:
        text = open(HE_FLAGS, encoding="utf-8").read()
    except OSError:
        return False
    if HE_EXT in text:
        return True
    out, done = [], False
    for line in text.split("\n"):
        if line.startswith("--load-extension=") and not done:
            line = line.rstrip() + "," + HE_EXT
            done = True
        out.append(line)
    if not done:
        out.append("--load-extension=" + HE_EXT)
    try:
        tmp = HE_FLAGS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        os.replace(tmp, HE_FLAGS)
    except OSError:
        return False
    return True


def apply_system(font):
    if font == "default":
        try:
            os.remove(SYSTEM_RULE)
        except FileNotFoundError:
            pass
    else:
        os.makedirs(os.path.dirname(SYSTEM_RULE), exist_ok=True)
        tmp = SYSTEM_RULE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(system_rule(font))
        os.replace(tmp, SYSTEM_RULE)
    # Ключ выбора и есть имя семейства («Hack», «Noto Sans», …).
    family, size = UI_FONT_DEFAULT if font == "default" else (font, UI_SIZE.get(font, UI_SIZE_DEFAULT))
    apply_ui_font(family, size)
    # Бар — сразу: остальное (попапы, лаунчер, блокировка, Настройки) запускается
    # заново при каждом открытии и подхватит шрифт само.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bar_style", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bar_style.py"))
    bar = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bar)
    bar.restart_waybar()
    apply_zen(font)
    apply_librewolf(font)
    apply_helium(font)
    # Яндекс Музыка — Electron с веб-плеером, шрифт ему приходит с сервера, и
    # правило fontconfig до него не достаёт; стиль вливается в окно по порту
    # отладки (ym_font.py). Плеер может быть не запущен — это не ошибка.
    subprocess.run(["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "ym_font.py")], capture_output=True, timeout=15)
    return True


def apply_kitty(font):
    """Заменить font_family в kitty.conf и перечитать конфиг в открытых окнах."""
    try:
        with open(KITTY_CONF, encoding="utf-8") as f:
            conf = f.read()
    except OSError:
        return False
    new, n = re.subn(r"(?m)^font_family[ \t]+.*$", lambda m: "font_family\t" + font, conf, count=1)
    if n == 0:
        return False
    if new != conf:
        tmp = KITTY_CONF + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, KITTY_CONF)
    if scope() != "all":
        # Открытые окна не трогаем: у другого шрифта другая ширина клетки, и
        # подогнанные руками размеры окон съезжают. Новые терминалы прочтут
        # конфиг сами. Включается в Настройках → Шрифты.
        return True
    # Сокет /tmp/kitty-PID остаётся и после выхода kitty — берём только живые.
    for pid in subprocess.run(["pgrep", "-x", "kitty"], capture_output=True, text=True).stdout.split():
        sock = "/tmp/kitty-" + pid
        if os.path.exists(sock):
            try:
                subprocess.run(["kitty", "@", "--to", "unix:" + sock, "kitten", KITTY_KITTEN],
                               capture_output=True, timeout=5)
            except subprocess.TimeoutExpired:
                pass
        else:
            subprocess.run(["kill", "-USR1", pid], capture_output=True)
    # Перечитывание возвращает окну палитру тех обоев, при которых kitty ЗАПУСТИЛСЯ
    # (файл темы он запоминает при старте): 17.09.2026 у 22 окон из 29 фон стал
    # #10131c вместо #14121c, и btop с явным фоном темы перестал быть прозрачным —
    # kitty прозрачит только клетки цвета фона окна. Поэтому текущая палитра
    # заливается заново, как в theme_changer.sh: по сокету и OSC-последовательностями.
    colors = os.path.expanduser("~/.cache/matugen/colors-kitty.conf")
    for pid in subprocess.run(["pgrep", "-x", "kitty"], capture_output=True, text=True).stdout.split():
        sock = "/tmp/kitty-" + pid
        if os.path.exists(sock) and os.path.exists(colors):
            try:
                subprocess.run(["kitty", "@", "--to", "unix:" + sock, "set-colors", "--all",
                                "--configured", colors], capture_output=True, timeout=5)
            except subprocess.TimeoutExpired:
                pass
    subprocess.run(["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "broadcast_colors.py")], capture_output=True, timeout=20)
    return True


def apply_termalt(font):
    """Ничего не применяет: шрифт читает term_font.sh при запуске терминала."""
    return True


APPLY = {"obsidian": apply_obsidian, "system": apply_system, "kitty": apply_kitty,
         "termalt": apply_termalt}


def set_font(app, key):
    if key not in dict(choices(app)):
        raise ValueError("%s: нет варианта %r" % (app, key))
    save({app: key})
    return APPLY[app](key)


def main():
    args = sys.argv[1:]
    try:
        if len(args) == 2 and args[0] == "get" and args[1] in APPS:
            print(get(args[1]))
        elif len(args) == 2 and args[0] == "list" and args[1] in APPS:
            for k, t in choices(args[1]):
                print("%s\t%s" % (k, t))
        elif args == ["scope"]:
            print(scope())
        elif len(args) == 2 and args[0] == "scope":
            print(set_scope(args[1]))
        elif args == ["zenfonts"]:
            print(zen_fonts())
        elif len(args) == 2 and args[0] == "zenfonts":
            print(set_zen_fonts(args[1]))
        elif args and args[0] in ("lwfonts", "hefonts"):
            name = "librewolf" if args[0] == "lwfonts" else "helium"
            if len(args) == 1:
                print(browser_fonts(name))
            else:
                ok = set_browser_fonts(name, args[1])
                print("%s%s" % (args[1], "" if ok else " (сохранено, применить не удалось)"))
        elif len(args) == 3 and args[0] == "set" and args[1] in APPS:
            ok = set_font(args[1], args[2])
            print("%s: %s%s" % (args[1], args[2], "" if ok else " (сохранено, применить не удалось)"))
        elif args == ["apply"]:
            apply_obsidian(get("obsidian"))
        else:
            print(__doc__, file=sys.stderr)
            return 1
    except ValueError as e:
        print("app_fonts: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
