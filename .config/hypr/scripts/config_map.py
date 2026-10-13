#!/usr/bin/env python3
"""Карта staticOS — какой файл за что отвечает и как запускается. 13.10.2026.

Просьба: «непонятные названия — нужна понятная Карта», «чтобы когда я зашёл в конфиги
нири, я не путал их с конфигами Hyprland». Скрипты не переименованы (на имена завязаны
бинды, бар, службы), вместо этого — карта по областям.

Что откуда берётся:
  область          — таблица AREAS ниже (руками; новый скрипт без области попадёт
                     в «Прочее», и `check` об этом скажет — так карта не устаревает);
  описание         — первая строка docstring или первого комментария файла,
                     для файлов без шапки — DESC;
  клавиши          — ~/.config/niri/cfg/binds.kdl;
  как запускается  — автозапуск niri, waybar, службы systemd --user, staticos-host,
                     hypridle/hyprlock;
  упоминают        — другие скрипты, где встречается имя (подсказка, не точный граф).

    config_map.py           окно (второй запуск закрывает его)
    config_map.py md [ФАЙЛ] записать карту в Markdown (по умолчанию ~/.config/0-КАРТА.md)
    config_map.py check     файлы без области и устаревшие строки AREAS
    config_map.py --shot ФАЙЛ [ЗАПРОС] [--area ОБЛАСТЬ] [--sel N] [--style default|skeet|beta]
                            снимок окна вне экрана
Окно: Super+Shift+Z, вид Recorder.exe по стилю системы. Сначала области, Enter — файлы
области, ещё Enter — открыть файл. Клавиши как в nvim: j/k, g/G, Ctrl+D/U, l/Enter вперёд,
h/Esc назад, / поиск (smart_search: синонимы, опечатки, раскладка), o папка, y путь,
q или Ctrl+Q — выход (Ctrl+Q закрывает карту, а не окно под ней: close-or-clipboard).
Мышью: кнопки Назад/Открыть/Папка/Путь, поле поиска, щелчок по области, двойной по файлу.
Скорость: результат scan() лежит в ~/.cache/jarvis/config-map.json, пока ни один файл
не менялся (подпись — время и размер, 3 мс); окно открывается за ~0,25 с вместо 1,5 с.
"""
import ast
import glob
import json
import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DIRS = (
    ("~/.config/hypr/scripts", "скрипт"),
    ("~/.config/niri/scripts", "niri"),
    ("~/.local/bin", "команда"),
)
SKIP = {"__pycache__"}
MD_PATH = "~/.config/0-КАРТА.md"
BINDS = "~/.config/niri/cfg/binds.kdl"
AUTOSTART = "~/.config/niri/cfg/autostart.kdl"
HOST = "~/.config/hypr/state/staticos-host.json"
HYPR_OFF = "~/.config/hyprland-off"

# ── области: (название, значок, имена файлов через пробел) — порядок = порядок в карте ──
AREAS = [
    ("Верхний бар", "▔", """
        bar_border.py bar_language.py bar_margins.py bar_rounding.py bar_style.py
        bar_window_title.py browser_status.py bongo_cat.py cava_bar.py mpris_common.py
        mpris_status.py mpris_focus privacy_status.py rec_status.sh ribbon_map.py
        sensor_colors.py start_button.py taskbar.py top_bar.py panels.py waybar_clock.py
        wb_hub.py wb_persist.py wb_share ws_labels.py ws_order.py lyrics_bar.py bar_volume.py bar_volume.sh
        savage_battery.py battery_mini.py build_bar_icons.py build_battery_font.py build_bongo_font.py
        build_wave_font.py build_wolf_font.py build_zen_font.py build_start_font.py
        build_taskbar_font.py bar_watch niri_bar.py waybar_niri.py barfix"""),
    ("Плашки бара", "▤", """
        appmem_popup.py battery_popup.py bluetooth_popup.py bt_stats_popup.py
        calendar_popup.py calendar_app.py control_center.py lan_popup.py mic_popup.py
        notif_log.py player_like.py player_like_key player_popup.py popup_theme.py
        power_view.py router_clients.py router_pass.py volume_popup.py wifi_net_popup.py
        wifi_popup.py popup-toggle"""),
    ("Нижняя панель, док, «Пуск»", "▁", """
        bottom_bar.py dock.py xpbar.py xpbar_colors.py xp_calendar.py start_menu.py
        super_tap.py app_search.py power_xp.py"""),
    ("Обои и цвета", "◐", """
        theme_changer.sh theme_changer.sh.bak-icons theme_snapshot.sh theme_doctor.py
        wallpaper_blur.py wallpaper_picker.py wallpaper_pixel.py wallpaper_preview.py
        wp_grab.py sparkle_wallpaper.py pixel_recolor.py gen_term_colors.py
        broadcast_colors.py gtk_live_colors.py gtk_tint.py gtk_guard.py merge_kdeglobals.py
        folder_colors.py kitty_icon.py widget_accent.py cava_colors.py fastfetch_colors.py tide_colors.py
        reload_btop.py wallpaper_watch theme-doctor theme-snapshot"""),
    ("Стиль системы и шрифты", "◆", """
        pixel_look.py pixel_mode.py system_style.py app_fonts.py cozette_fit.py
        rofi_style.py launcher_style.py mixer_style.py wlogout_icons.py icon_theme.py
        rofi fontprofile fontswap font-sample"""),
    ("Курсор", "➤", """
        cursor_colors.py cursor_shake.py cursor_theme.py bit_cursor.py
        tri_cursor.py jarvis_pebble.py yamikai_wall.py"""),
    ("Уведомления и звуки интерфейса", "✉", """
        notif_style.py track_notify.py dnd_sounds.py auto_dnd.py ui_sound.py
        ui_sound_retro.py ui_sound_watch.py layout_osd notif-look notify-send"""),
    ("Блокировка, сон, экран", "⏻", """
        jarvis_lock.py lock_battery.sh lock_layout.sh lock_net.sh lock_power.py
        lock_power_label.sh lock_style.py lockscreen avatar_picker.py login_theme.py
        login_theme/ idle_dim idle_guard.py idle_lock idle_suspend screen_awake.py
        screensaver.py power_menu.py wake_alarm.py wake_overlay.py screen_gamma.py
        night_mode.py alt-f4 vt_guard dpms screenon wake-alarm"""),
    ("Настройки и справка", "⚙", """
        settings_app.py niri_state.py niri_compositor.py keybinds_sheet.py smart_search.py exe_frame.py close_cap.py app_list.py
        config_map.py skeet_icons/ settings-open slashkey applist"""),
    ("Окна и столы niri", "▣", """
        alt_tab.py alt_tab.sh ribbon_center.py mouse_focus.py mouse_wait_release.py
        window_fx.py wm.py hot_corners.py
        pip_place.py ws_layout.py mousepad_place.py colexpand colwidth floattoggle magic
        move_all no_self_maximize.py pair_center.py winreset ws_insert close-or-clipboard
        dashboard shell-switch shell-do ws-anim"""),
    ("Звук и музыка", "♪", """
        app_volume.py audio_names.py audio_repair sound_guard.sh mic_monitor.py mediakey
        lyrics_sync.py lyrics_sync_asr.py lyrics_sync_sep.py ym_font.py ym_font_watch.py
        ym_launch.sh ym_theme.py ym_tweaks.py ytm_colors.py ytmd_auth.py
        audio-resume-fix mic-floor mic-guard"""),
    ("Железо: подсветка, яркость, питание", "⚡", """
        kbd_colors.py kbdlight kbdlight_watch razer_brightness.py razer_restore
        monitor_brightness.py fan power flash"""),
    ("Приложения", "◇", """
        discord_pixel.py discord_splash.js keepassxc_style.py zen_style.py steam_space.py
        telegram_colors.py vscode_colors.py obsidian_opacity.py matugen_native_host.py
        mousepad_retheme.sh notepad.sh office_setup.sh kitty_shader.py
        kitty_shader_colors.py kitty_shared.sh term_font.sh ttyper_colors.py game_guard.py
        susanoo_bake.py keepassxc keepassxc-setup zen-crt zen-browser termlook
        game-clip-push"""),
    ("Терминал: часы, fetch, игры", ">_", """
        tclock tdown tmatrix dateview.py ffetch archfetch brrt brrtfetch fetch3d jclock
        jtetris jtype text hollywood ccze timer nowrap ptyclean ptysync"""),
    ("Виджеты и меню рабочего стола", "▦", """
        desktop_widgets.py desktop_widgets_extra.py preset_ask.py desktop_menu.py
        timer_ask.sh"""),
    ("Инструменты: калькулятор, буфер, снимки, запись", "✂", """
        calc_copy.sh calc_menu.sh calc_qalc.py translate_popup.py translate_server.py
        clipboard_menu.py clipboard_win.py freeze_lib.sh
        freeze_screen.py pin_shot.py ocr_copy.sh pxocr.py term_text.py
        screenshot_annotate.sh rec_area.sh rec_frame.py rec_menu.py rec_nobg.py
        rec_style.py replay_saved.sh launcher.py app_launcher.py launcher_term.sh webapp screentime.py
        screentime_daemon.py clipboard-toggle cliphist-store xclip x-clip-pull
        x11-clip-bridge x11-clip-events wtype replay picker appmem jtop rembg"""),
    ("Discipline и hub", "⏱", """
        routine_app.py focus_mode.py alarm discipline routine pomo hub hub-open rem dict"""),
    ("Самопроверка и сторожа", "✚", """
        staticos_host.py cpu_hog_watch.py session_env.py staticos-doctor"""),
    ("Сторонние программы", "□", """
        uv uvx python3.12"""),
    ("Hyprland — не используется", "✕", """
        layout_mode.py window_rounding.py cursor_watch dim_toggle.py overview.py
        window_switcher.py window_switcher.sh move_all_windows.sh hypr-focus-guard.sh"""),
]
OTHER = ("Прочее", "?")

# Описания файлов без шапки (сверено с кодом 13.10.2026).
DESC = {
    "savage_battery.py": "Батарея в баре и переключатель Savage Mode (щелчок по батарее).",
    "pixel_look.py": "Вид системы: пиксельный, обычный или Minimalistic (капсула) — один переключатель на всё",
    "battery_mini.py": "Батарейка-капсула (картинка) в баре вида Minimalistic, без цифр.",
    "mic_popup.py": "Плашка «Уровень микрофона» — ПКМ по микрофону в баре.",
    "volume_popup.py": "Плашка громкости и источников — ПКМ по громкости в баре.",
    "skeet_icons/": "Значки вида Skeet для Настроек (в публичный репозиторий не идут).",
    "login_theme/": "Тема экрана входа SDDM (файлы для login_theme.py).",
    "theme_changer.sh.bak-icons": "Копия theme_changer.sh — её сам возвращает icon_theme.py; не трогать.",
    "fetch3d": "Программа: вращающийся 3D-логотип (её зовёт archfetch).",
    "x11-clip-events": "Программа: события буфера X11 (для x11-clip-bridge).",
    "wtype": "Программа: печать текста под Wayland (её зовут бинды и скрипты).",
    "uv": "Менеджер пакетов Python (сторонний).",
    "uvx": "Запуск утилит Python через uv (сторонний).",
    # Шапки на английском или в виде справки — своими словами.
    "mpris_status.py": "Модуль бара: что сейчас играет (или ничего)",
    "sensor_colors.py": "Цвета модулей CPU/RAM/температуры в баре и яркий акцент для мест, где он плохо читался",
    "waybar_clock.py": "Часы и календарь в баре — две синхронные копии, по одной на монитор",
    "calendar_app.py": "Календарь отдельным окном, в цветах обоев",
    "broadcast_colors.py": "Разослать палитру обоев во все открытые терминалы",
    "gen_term_colors.py": "Собрать 16 цветов терминала из акцента обоев",
    "merge_kdeglobals.py": "Влить цвета matugen в ~/.config/kdeglobals (программы Qt/KDE)",
    "reload_btop.py": "Велеть открытым btop перечитать свежую тему",
    "theme_changer.sh": "Пересобрать цвета по обоям и раздать их всем открытым программам",
    "dateview.py": "Крупный день недели и дата в окне терминала",
    "staticos-doctor": "Есть ли у staticOS всё нужное (ничего не меняет)",
    "rec_status.sh": "Красная точка в баре, пока идёт запись Recorder",
    "kbd_colors.py": "Подсветка Razer BlackWidow V3 в гамме обоев",
    "bar_volume.sh": "Щелчки и колёсико звука в баре: на динамики или микрофон — что показано",
    "wb_share": "Общий исполнитель модулей бара: команда идёт одна на оба монитора (через wb_hub.py)",
    "hub-open": "Открыть окно hub (одно на всех); hub-open dict — словарь",
    "fontprofile": "Профили файлов под шрифт системы: сохранить оригинал перед правкой под Cozette и вернуть",
    "fontswap": "Проба шрифта на всю систему одним правилом fontconfig (Cozette вместо PxPlus) и откат",
    "termlook": "Пробовать вид терминала вживую: шрифт, прозрачность, размытие",
    "game-clip-push": "Текст из буфера системы — в буфер игр под gamescope и X-программ (:1)",
    "keepassxc-setup": "Доводка KeePassXC после установки: пункт меню через обёртку (цвета обоев, пиксельный шрифт)",
}

# Скрипты, которые запускают руками или разово, — не «мёртвые».
MANUAL = {
    "build_bar_icons.py": "руками — пересобрать шрифт значков",
    "build_battery_font.py": "руками — пересобрать шрифт",
    "build_bongo_font.py": "руками — пересобрать шрифт",
    "build_start_font.py": "руками — пересобрать шрифт",
    "build_taskbar_font.py": "руками — пересобрать шрифт",
    "build_wave_font.py": "руками — пересобрать шрифт",
    "build_wolf_font.py": "руками — пересобрать шрифт",
    "build_zen_font.py": "руками — пересобрать шрифт",
    "office_setup.sh": "руками, один раз после установки LibreOffice",
    "ytmd_auth.py": "руками, один раз",
    "susanoo_bake.py": "руками — пересобрать шейдер kitty",
    "sparkle_wallpaper.py": "руками — нарисовать обои «искорки»",
    "clipboard_menu.py": "запасной: старое окно буфера (откат в binds.kdl)",
    "calc_menu.sh": "запасной: старый калькулятор на rofi (сейчас Super+C — translate_popup.py)",
}

# Главные конфиги: (путь, область, что это).
CONFIGS = [
    ("~/.config/niri/config.kdl", "Окна и столы niri", "Главный конфиг niri: подключает файлы cfg/*.kdl"),
    ("~/.config/niri/cfg/binds.kdl", "Настройки и справка", "Все клавиши niri (их показывает Super+Z)"),
    ("~/.config/niri/cfg/autostart.kdl", "Самопроверка и сторожа", "Что запускается при входе"),
    ("~/.config/niri/cfg/window-rules.kdl", "Окна и столы niri", "Правила окон: размеры, плавающие, прозрачность"),
    ("~/.config/niri/cfg/layer-rules.kdl", "Окна и столы niri", "Правила слоёв: бар, плашки, уведомления"),
    ("~/.config/niri/cfg/layout.kdl", "Окна и столы niri", "Раскладка: зазоры, рамки, ширина колонок"),
    ("~/.config/niri/cfg/workspaces.kdl", "Окна и столы niri", "Именованные столы"),
    ("~/.config/niri/cfg/outputs.kdl", "Окна и столы niri", "Мониторы: eDP-1 и MSI"),
    ("~/.config/niri/cfg/input.kdl", "Окна и столы niri", "Клавиатура, раскладки, тачпад, мышь"),
    ("~/.config/niri/cfg/animations.kdl", "Окна и столы niri", "Анимации niri"),
    ("~/.config/niri/cfg/misc.kdl", "Окна и столы niri", "Прочие настройки niri"),
    ("~/.config/niri/cfg/blur.kdl", "Окна и столы niri", "Размытие фона"),
    ("~/.config/niri/cfg/waybar-blur.kdl", "Верхний бар", "Размытие под баром — пишет top_bar.py"),
    ("~/.config/niri/cfg/look.kdl", "Стиль системы и шрифты", "Вид Minimalistic: без размытия под капсулой, тонкая белая рамка окон — пишет pixel_look.py"),
    ("~/.config/niri/cfg/window-fx.kdl", "Окна и столы niri", "Эффект окон — пишет window_fx.py"),
    ("~/.config/niri/cfg/ws-layout.kdl", "Окна и столы niri", "Раскладка по столам — пишет ws_layout.py"),
    ("~/.config/niri/cfg/rec-binds.kdl", "Инструменты: калькулятор, буфер, снимки, запись", "Клавиши на время записи — пишет rec_area.sh"),
    ("~/.config/niri/dashboard-rules.kdl", "Окна и столы niri", "Правила окон дашборда — для dashboard"),
    ("~/.config/waybar/config.jsonc", "Верхний бар", "Основной конфиг бара: модули и щелчки"),
    ("~/.config/waybar/config-niri.jsonc", "Верхний бар", "Конфиг бара под niri — собирает waybar_niri.py"),
    ("~/.config/waybar/style.css", "Верхний бар", "Вид бара (основной)"),
    ("~/.config/waybar/style-niri.css", "Верхний бар", "Вид бара под niri — собирается из style.css"),
    ("~/.config/waybar/looks", "Верхний бар", "Заготовки вида бара (bar_style.py); current.* — выбранная"),
    ("~/.config/waybar/rounding.css", "Верхний бар", "Скругление бара — пишет bar_rounding.py"),
    ("~/.config/waybar/widget-desks.css", "Виджеты и меню рабочего стола", "Вид виджетов-столов — пишет desktop_widgets.py"),
    ("~/.config/hypr/hypridle.conf", "Блокировка, сон, экран", "Простой: приглушение, блокировка, сон (hypridle)"),
    ("~/.config/hypr/hyprlock.conf", "Блокировка, сон, экран", "Экран блокировки hyprlock"),
    ("~/.config/hypr/hyprlock-astronaut.conf", "Блокировка, сон, экран", "Шаблон экрана блокировки для lock_style.py"),
    ("~/.config/hypr/ytm-glass.css", "Звук и музыка", "Тема YouTube Music — пишет ytm_colors.py"),
    ("~/.config/hypr/state", "Настройки и справка", "Выбранные настройки (по файлу на переключатель)"),
    ("~/.config/hypr/sounds", "Уведомления и звуки интерфейса", "Звуки интерфейса"),
    ("~/.config/hypr/udev", "Железо: подсветка, яркость, питание", "Правила udev"),
    ("~/.config/systemd/user", "Самопроверка и сторожа", "Службы: hub, будильник, сторожа, туннели"),
]

HYPR_OFF_DESC = {
    "hyprland.lua": "Главный конфиг Hyprland (подключает остальные *.lua)",
    "hyprpaper.conf": "Обои под Hyprland",
    "hyprsunset.conf": "Ночной свет под Hyprland (под niri — night_mode.py)",
    "shyprlock.conf": "Запасной экран блокировки",
    "NOTES-обзор-столов.md": "Заметка об обзоре столов",
    "workspace": "Пустой файл",
    ".vscode": "Настройки VS Code для папки",
}


def ex(p):
    return os.path.expanduser(p)


def short(p):
    return p.replace(HOME, "~", 1) if p.startswith(HOME) else p


def read(p):
    try:
        with open(p, "rb") as f:
            b = f.read()
    except OSError:
        return None
    if b"\0" in b[:4000]:
        return None
    return b.decode("utf-8", "replace")


def first_sentence(lines):
    """Первый абзац до первой точки: шапки часто переносят фразу на вторую строку."""
    para = []
    for line in lines:
        if not line.strip():
            if para:
                break
            continue
        para.append(line.strip())
    t = " ".join(para)
    t = re.split(r"(?<=[.!?])\s+(?=[A-ZА-ЯЁ«(\d])", t)[0]
    t = re.sub(r"\s*\((?:до |с )?\d\d\.\d\d(?:\.\d{4})?\b[^()]*\)", "", t)   # (30.09.2026, просьба …)
    t = re.sub(r"\s*\((?:до |с )?\d\d\.\d\d\.\d{4}\b[^)]*$", "", t)             # незакрытая скобка
    t = re.sub(r"[,;]\s*(?:до |с )?\d\d\.\d\d\.\d{4}\b[^,;)]*(?=\))", "", t)      # (…, 30.09.2026)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"[\s.,—-]*\d\d\.\d\d\.\d{4}\.?$", "", t).rstrip(" .,:;—")  # … 30.09.2026.
    return t[:157] + "…" if len(t) > 160 else t


def header(path, text):
    """Первая фраза docstring или первого комментария."""
    if text is None:
        return ""
    if path.endswith(".py") or re.match(r"#!.*python", text):
        try:
            d = ast.get_docstring(ast.parse(text))
            if d:
                return first_sentence(d.strip().split("\n"))
        except (SyntaxError, ValueError):
            pass
    lines = text.split("\n")
    out = []
    for line in lines[1 if lines and lines[0].startswith("#!") else 0:]:
        s = line.strip()
        if s.startswith(("#", "//")):
            s = s.lstrip("#/").strip()
            if s.startswith(("-*-", "shellcheck")):
                continue
            if not s and out:
                break
            out.append(s)
        elif s and not s.startswith("set -"):
            break
        elif out:
            break
    return first_sentence(out)


# ── источники ────────────────────────────────────────────────────────────────

RE_BIND = re.compile(r"^\s*([^\s/{}][^\s{}]*)\s+([^{\n]*)\{([^}]*)\}", re.M)


def load_binds():
    text = read(ex(BINDS)) or ""
    text = re.sub(r"//[^\n]*", "", text)
    return [(m.group(1), m.group(3)) for m in RE_BIND.finditer(text)]


def pretty(key):
    try:
        from keybinds_sheet import pretty_key
        return pretty_key(key)
    except Exception:
        return key.replace("Mod", "Super")


def tokens(text):
    """Имена файлов, которые встречаются в тексте как вызов: {имя: вид}.

    С точкой (calc_qalc.py) — любое вхождение. Без точки (rofi, text) — только путём
    (/rofi) или первым словом команды в кавычках ("rofi -dmenu"), иначе обычные слова
    вроде text/power/server давали бы ложные совпадения."""
    out = set()
    for m in re.finditer(r"(?:^|(?<=[/\"'\s=(]))([\w][\w.+-]*\w|\w)(?=(.?))", text):
        name, nxt = m.group(1), m.group(2)
        prev = text[m.start(1) - 1] if m.start(1) else ""
        if "." in name:
            out.add(name)
            if name.endswith(".py"):
                continue
        if prev == "/" or (prev in "\"'" and (nxt.isspace() or nxt == "")):
            out.add(name)
    for m in re.finditer(r"^\s*(?:from\s+(\w+)\s+import|import\s+([\w, ]+))", text, re.M):
        for mod in re.split(r"[,\s]+", m.group(1) or m.group(2)):
            if mod:
                out.add(mod + ".py")
    for m in re.finditer(r"_load\(\"(\w+)\"\)|spec_from_file_location\(\"(\w+)\"", text):
        out.add((m.group(1) or m.group(2)) + ".py")
    return out


def code_only(text):
    """Текст без комментариев и строк в тройных кавычках (там имена лишь упоминаются)."""
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    return re.sub(r"^\s*(#|//)[^\n]*", "", text, flags=re.M)


def scan():
    """Список записей карты."""
    area_of, order = {}, []
    for name, icon, names in AREAS:
        order.append((name, icon))
        for n in names.split():
            area_of.setdefault(n, name)
    entries = []
    for d, kind in DIRS:
        dd = ex(d)
        for n in sorted(os.listdir(dd)):
            if n in SKIP:
                continue
            p = os.path.join(dd, n)
            isdir = os.path.isdir(p) and not os.path.islink(p)
            key = n + "/" if isdir else n
            text = None if isdir or os.path.islink(p) else read(p)
            if os.path.islink(p):
                desc = "ссылка → " + short(os.path.realpath(p))
            else:
                desc = DESC.get(key) or header(p, text) or ("[программа]" if text is None and not isdir else "")
            desc = re.sub(r"^%s\s+—\s+" % re.escape(n), "", desc)    # «font-sample — font-sample — …»
            if re.match(r"[а-яё]", desc):
                desc = desc[:1].upper() + desc[1:]
            entries.append(dict(name=key, path=p, kind=kind, area=area_of.get(key, OTHER[0]),
                                desc=desc, text=text or "", keys=[], start=[], refs=[], callers=[]))
    for p, area, desc in CONFIGS:
        entries.append(dict(name=short(ex(p)).split("/", 2)[-1] if p.count("/") > 2 else p,
                            path=ex(p), kind="конфиг", area=area, desc=desc, text="",
                            keys=[], start=[], refs=[], callers=[]))
    off = ex(HYPR_OFF)
    try:
        moved = [x for x in open(os.path.join(off, ".moved")).read().split("\n") if x]
    except OSError:
        moved = []
    for n in moved:
        desc = HYPR_OFF_DESC.get(n) or ("Часть конфига Hyprland" if n.endswith(".lua") else
                                        "Старый снимок экрана Hyprland" if n.endswith(".png") else "")
        entries.append(dict(name=n, path=os.path.join(off, n), kind="hyprland-off",
                            area="Hyprland — не используется", desc=desc, text="",
                            keys=[], start=[], refs=[], callers=[]))

    by_name = {}
    for e in entries:
        if e["kind"] in ("скрипт", "niri", "команда"):
            by_name.setdefault(e["name"], []).append(e)

    def hits(text):
        return [by_name[t] for t in tokens(text) if t in by_name]

    for key, action in load_binds():
        for es in hits(action):
            for e in es:
                k = pretty(key)
                if k not in e["keys"]:
                    e["keys"].append(k)
    for line in (read(ex(AUTOSTART)) or "").split("\n"):
        if line.strip().startswith("spawn-at-startup"):
            for es in hits(line):
                for e in es:
                    e["start"].append("автозапуск niri")
    try:
        host = json.load(open(ex(HOST)))
    except (OSError, ValueError):
        host = []
    for n in host:
        for e in by_name.get(n, []):
            e["start"].append("сторож в staticos-host")
    bar = ""
    for p in ["~/.config/waybar/config.jsonc", "~/.config/waybar/config-niri.jsonc"] + \
            glob.glob(ex("~/.config/waybar/looks/*.jsonc")):
        bar += (read(ex(p)) or "") + "\n"
    for es in hits(bar):
        for e in es:
            e["start"].append("бар (waybar)")
    for unit in sorted(glob.glob(ex("~/.config/systemd/user/*.service"))):
        for es in hits(read(unit) or ""):
            for e in es:
                e["start"].append("служба " + os.path.basename(unit))
    outside = [("~/.config/hypr/hypridle.conf", "простой (hypridle)"),
               ("~/.config/hypr/hyprlock.conf", "блокировка (hyprlock)"),
               ("~/.config/hypr/hyprlock-astronaut.conf", "блокировка (hyprlock)")]
    outside += [(p, "LibreWolf (native messaging)") for p in
                glob.glob(ex("~/.librewolf/native-messaging-hosts/*.json"))]
    outside += [(p, "ярлык " + os.path.basename(p)) for p in
                glob.glob(ex("~/.local/share/applications/*.desktop"))]
    for p, what in outside:
        for es in hits(read(ex(p)) or ""):
            for e in es:
                e["start"].append(what)
    for src in entries:
        if not src["text"] or src["name"] == "config_map.py":   # в AREAS тут все имена
            continue
        code = set(map(id, (e for es in hits(code_only(src["text"])) for e in es)))
        for es in hits(src["text"]):
            for e in es:
                if e is not src and src["name"] not in e["refs"]:
                    e["refs"].append(src["name"])
                    if id(e) in code:               # не в комментарии — значит, зовёт
                        e["callers"].append(src["name"])
    for e in entries:
        e["start"] = list(dict.fromkeys(e["start"]))
        if "settings_app.py" in e["refs"]:
            e["start"].insert(0, "Настройки")
        del e["text"]
    return entries, order


def orphan(e):
    """Скрипт, который ничто не вызывает (команды из ~/.local/bin зовут руками)."""
    return (e["kind"] in ("скрипт", "niri") and not e["keys"] and not e["start"]
            and not e["callers"] and not e["name"].endswith("/")
            and e["area"] != "Hyprland — не используется" and ".bak" not in e["name"]
            and e["name"] not in MANUAL)


def direct(e):
    return ([", ".join(e["keys"])] if e["keys"] else []) + e["start"]


def via(e, by_name, depth=3, seen=None):
    """[(кто зовёт, его запуск)] — вверх по цепочке вызовов до depth шагов."""
    seen = seen if seen is not None else {id(e)}
    out = []
    for r in e["callers"]:
        for x in by_name.get(r, []):
            if id(x) in seen:
                continue
            seen.add(id(x))
            if direct(x):
                out.append((r, direct(x)[0]))
            elif depth > 1:
                out += [(r + " ← " + a, b) for a, b in via(x, by_name, depth - 1, seen)]
    return out


def how(e, by_name=None):
    """Клавиши и запуск; если своих нет — через кого (тот, кто зовёт, и его запуск)."""
    parts = direct(e)
    if not parts and by_name:
        parts += ["через %s (%s)" % v for v in via(e, by_name)[:2]]
    if not parts and e["name"] in MANUAL:
        parts.append(MANUAL[e["name"]])
    if not parts and e["refs"]:
        parts.append("упоминается в " + ", ".join(e["refs"][:3]) + ("…" if len(e["refs"]) > 3 else ""))
    if not parts and e["kind"] == "команда":
        parts.append("командой в терминале")
    return "; ".join(parts)


def index(entries):
    by = {}
    for e in entries:
        by.setdefault(e["name"], []).append(e)
    return by


def grouped(entries, order):
    names = [a for a, _ in order] + [OTHER[0]]
    icons = dict(order + [OTHER])
    out = []
    for a in names:
        es = [e for e in entries if e["area"] == a]
        if es:
            kinds = {"конфиг": 0, "скрипт": 1, "niri": 2, "команда": 3, "hyprland-off": 4}
            es.sort(key=lambda e: (kinds.get(e["kind"], 9), e["name"].lower()))
            out.append((a, icons[a], es))
    return out


# ── Markdown ─────────────────────────────────────────────────────────────────

def md(path=None):
    entries, order = scan()
    path = ex(path or MD_PATH)
    L = ["# Карта staticOS",
         "",
         "Какой файл за что отвечает и как запускается. Собрано `config_map.py md`; "
         "окно с поиском — **Super+Shift+Z**. Руками не править — перезапишется.",
         "",
         "| Где | Что |", "|---|---|",
         "| `~/.config/hypr/scripts` | скрипты системы (папка зовётся hypr по истории — работают под niri) |",
         "| `~/.config/niri/scripts` | скрипты, нужные только niri (окна, столы, бар) |",
         "| `~/.config/niri/cfg` | конфиг niri по частям |",
         "| `~/.local/bin` | команды для терминала |",
         "| `~/.config/hyprland-off` | Hyprland — отложен, не используется |",
         ""]
    orph = [e for e in entries if orphan(e)]
    if orph:
        L += ["## Похоже, не используются", "",
              "Их не зовут ни клавиши, ни бар, ни автозапуск, ни службы, ни другие скрипты. "
              "Перед удалением — проверить.", ""]
        L += ["- `%s` — %s" % (short(e["path"]), e["desc"] or "без описания") for e in orph]
        L.append("")
    L += ["## Оглавление", ""]
    groups = grouped(entries, order)
    by = index(entries)
    for a, icon, es in groups:
        L.append("- [%s](#%s) — %d" % (a, re.sub(r"[^\w\- ]", "", a.lower()).replace(" ", "-"), len(es)))
    L.append("")
    for a, icon, es in groups:
        L += ["## %s" % a, "", "| Файл | Что делает | Как запускается |", "|---|---|---|"]
        for e in es:
            name = short(e["path"])
            cell = lambda s: s.replace("|", "\\|")
            L.append("| `%s` | %s | %s |" % (name, cell(e["desc"]), cell(how(e, by))))
        L.append("")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(L))
    os.replace(tmp, path)
    print("записал", short(path), "—", len(entries), "записей,", len(orph), "без вызова")


def check():
    entries, order = scan()
    all_names = [n for _, _, ns in AREAS for n in ns.split()]
    listed = set(all_names)
    twice = sorted({n for n in all_names if all_names.count(n) > 1})
    have = {e["name"] for e in entries}
    other = sorted(e["name"] for e in entries if e["area"] == OTHER[0])
    stale = sorted(listed - have)
    missing = [p for p, _, _ in CONFIGS if not os.path.exists(ex(p))]
    print("check: %d записей, %d областей" % (len(entries), len(order)))
    if other:
        print("без области (допишите в AREAS config_map.py):", " ".join(other))
    if stale:
        print("в AREAS, но файла нет:", " ".join(stale))
    if missing:
        print("в CONFIGS, но нет:", " ".join(missing))
    if twice:
        print("в двух областях сразу:", " ".join(twice))
    return 1 if other or stale or missing or twice else 0


# ── кэш ──────────────────────────────────────────────────────────────────────
# scan() читает и разбирает ~430 файлов — 1,3 с. Окно берёт готовый результат из кэша,
# пока ни один источник не менялся (подпись — время и размер каждого файла, ~10 мс).

CACHE = "~/.cache/jarvis/config-map.json"


def sources():
    out = [os.path.abspath(__file__), ex(BINDS), ex(AUTOSTART), ex(HOST),
           os.path.join(ex(HYPR_OFF), ".moved"),
           ex("~/.config/hypr/hypridle.conf"), ex("~/.config/hypr/hyprlock.conf"),
           ex("~/.config/hypr/hyprlock-astronaut.conf"),
           ex("~/.config/waybar/config.jsonc"), ex("~/.config/waybar/config-niri.jsonc")]
    for d, _ in DIRS:
        try:
            out += [os.path.join(ex(d), n) for n in sorted(os.listdir(ex(d))) if n not in SKIP]
        except OSError:
            pass
    for pat in ("~/.config/waybar/looks/*.jsonc", "~/.config/systemd/user/*.service",
                "~/.librewolf/native-messaging-hosts/*.json", "~/.local/share/applications/*.desktop"):
        out += sorted(glob.glob(ex(pat)))
    return out + [ex(p) for p, _, _ in CONFIGS]


def signature():
    parts = []
    for p in sources():
        try:
            if os.path.isdir(p):      # у папки — состав, не время: state/ и config-bak/ меняются
                parts.append("%s|%s" % (p, ",".join(sorted(os.listdir(p)))))   # каждую минуту
                continue
            st = os.stat(p)
            parts.append("%s|%d|%d" % (p, st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append(p + "|-")
    import hashlib
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()


STALE = []      # cached_scan(stale_ok=True) вернул устаревшее — окно пересканирует в фоне


def cached_scan(stale_ok=False):
    """Разбор из кэша, если файлы не менялись. stale_ok — окну: устаревший кэш отдать
    сразу (окно открывается без задержки ~1,3 с), свежий разбор — в фоне (13.10.2026)."""
    sig = signature()
    path = ex(CACHE)
    try:
        with open(path) as f:
            d = json.load(f)
        if d.get("sig") == sig or stale_ok:
            if d.get("sig") != sig:
                STALE.append(sig)
            return d["entries"], [tuple(x) for x in d["order"]]
    except (OSError, ValueError, KeyError):
        pass
    return rescan(sig)


def rescan(sig=None):
    sig = sig or signature()
    path = ex(CACHE)
    entries, order = scan()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w") as f:
            json.dump(dict(sig=sig, entries=entries, order=order), f, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except OSError:
        pass
    return entries, order


# ── значки ───────────────────────────────────────────────────────────────────
# Картинка в окне — из темы значков системы (Jarvis-Pixel, иначе Papirus): у области
# своя, у файла — по имени (kitty, discord, обои…), иначе — значок его области.

AREA_INFO = {
    "Верхний бар": ("preferences-desktop", "Полоса сверху: модули, часы, столы, музыка"),
    "Плашки бара": ("preferences-system-windows-actions", "Окошки по щелчку на модули бара"),
    "Нижняя панель, док, «Пуск»": ("start-here-kde-plasma", "XP-панель снизу, док и меню «Пуск»"),
    "Обои и цвета": ("preferences-desktop-wallpaper", "Смена обоев и раскраска всего под них"),
    "Стиль системы и шрифты": ("preferences-desktop-theme-global", "Default/Skeet/Beta, пиксельный вид, шрифты"),
    "Курсор": ("preferences-desktop-cursors", "Свой курсор в цветах обоев"),
    "Уведомления и звуки интерфейса": ("preferences-desktop-notification-bell", "Вид уведомлений, «не беспокоить», щелчки"),
    "Блокировка, сон, экран": ("system-lock-screen", "Экран блокировки, простой, заставка, питание"),
    "Настройки и справка": ("systemsettings", "Окно Настроек, Super+Z, эта карта"),
    "Окна и столы niri": ("view-grid", "Конфиг niri, Alt+Tab, раскладки, окна"),
    "Звук и музыка": ("preferences-desktop-sound", "Громкость, микрофон, Яндекс Музыка, тексты"),
    "Железо: подсветка, яркость, питание": ("input-keyboard", "Подсветка Razer, яркость, вентиляторы"),
    "Приложения": ("preferences-desktop-default-applications", "Discord, Zen, Steam, Telegram, kitty — под стиль"),
    "Терминал: часы, fetch, игры": ("utilities-terminal", "Часы, fetch, тетрис, тренажёр — в терминале"),
    "Виджеты и меню рабочего стола": ("preferences-desktop-activities", "Окна-виджеты на обоях и меню ПКМ"),
    "Инструменты: калькулятор, буфер, снимки, запись": ("applets-screenshooter", "Super+C, буфер, снимки, Recorder"),
    "Discipline и hub": ("jarvis-discipline", "Будильник, фокус, помидор, напоминания"),
    "Самопроверка и сторожа": ("utilities-system-monitor", "staticos-doctor, сторожа в одном процессе"),
    "Сторонние программы": ("package-x-generic", "Чужие программы в ~/.local/bin"),
    "Hyprland — не используется": ("dialog-cancel", "Отложено: ~/.config/hyprland-off"),
    "Прочее": ("help-about", "Файлы без области — допишите их в AREAS"),
}

FILE_ICONS = [(re.compile(rx), icon) for rx, icon in (
    (r"kitty|term_font|termlook", "kitty"), (r"discord", "discord"), (r"^zen|zen_", "zen-browser"),
    (r"steam", "steam"), (r"telegram", "org.telegram.desktop"), (r"keepass", "keepassxc"),
    (r"obsidian", "obsidian"), (r"vscode", "vscode"), (r"office", "libreoffice-startcenter"),
    (r"mousepad|notepad", "mousepad"), (r"btop|jtop|appmem", "btop"), (r"rofi|launcher|app_search", "rofi"),
    (r"cursor|bit_cursor|pebble", "preferences-desktop-cursors"), (r"lock", "system-lock-screen"),
    (r"wallpaper|^wp_|sparkle", "preferences-desktop-wallpaper"), (r"font", "preferences-desktop-font"),
    (r"calc", "org.speedcrunch.SpeedCrunch"), (r"clip|xclip", "jarvis-clipboard"),
    (r"^rec_|replay", "simplescreenrecorder"), (r"screenshot|pin_shot|freeze|ocr", "applets-screenshooter"),
    (r"bluetooth|^bt_", "blueman"), (r"wifi", "nm-device-wireless"), (r"lan_|router", "network-wired"),
    (r"^mic", "audio-input-microphone"), (r"volume|audio|sound", "preferences-desktop-sound"),
    (r"^ym_|yandex", "yandexmusic"), (r"ytm", "youtube-music-desktop-app"),
    (r"kbd|razer", "input-keyboard"), (r"battery|power", "preferences-system-power-management"),
    (r"calendar", "org.gnome.Calendar"), (r"clock|timer|alarm|wake", "org.gnome.clocks"),
    (r"notif", "preferences-desktop-notification-bell"), (r"translate", "accessories-character-map"),
    (r"keybind|binds", "preferences-desktop-keyboard-shortcut"), (r"settings", "systemsettings"),
    (r"app_list|applist", "jarvis-applist"), (r"^hub|^rem$", "jarvis-hub-reminders"),
    (r"^dict$", "jarvis-hub-dict"), (r"routine|discipline|focus|pomo", "jarvis-discipline"),
    (r"color|tint|theme", "preferences-desktop-color"), (r"dock|xpbar|bottom_bar|start_", "start-here-kde-plasma"),
    (r"bar|waybar|wb_", "preferences-desktop"), (r"jtetris|jtype|ttyper", "preferences-desktop-gaming"),
    (r"doctor", "utilities-system-monitor"), (r"backup", "folder-backup"),
)]
DIR_ICONS = {"systemd/user": "folder-systemd", "config-bak": "folder-backup", "sounds": "folder-sound",
             "state": "folder-script", "udev": "folder-script", "looks": "folder-templates"}


def icon_for(e):
    n, p = e["name"], e["path"]
    base = AREA_INFO.get(e["area"], AREA_INFO["Прочее"])[0]
    if e["kind"] == "конфиг":
        for k, v in DIR_ICONS.items():
            if p.endswith(k):
                return v
        if os.path.isdir(p):
            return "folder"
        return base
    if n.endswith("/"):
        return "folder"
    for rx, icon in FILE_ICONS:
        if rx.search(n):
            return icon
    return base


# ── окно ─────────────────────────────────────────────────────────────────────
# Вид — как Recorder.exe (rec_menu.py): окно XP / skeet / beta по стилю системы
# (state/settings-skin), те же цвета, рамки и крестик. Два уровня: области → файлы.

W, H = 1060, 800
TITLE = "Карта.exe"
ANIM_MS = 130
ROW_A, ROW_F = 40, 30          # строка области и строка файла
TOOL_H = 30
DETAIL_H = 140
STATUS_H = 28
MAP_BMP = ("#.##..##", "##..##.#", "#.##..##", "##..##.#", "#.##..##", "##..##.#", "#.##..##")
BUTTONS = [("back", "Назад", "h"), ("open", "Открыть", "Enter"), ("dir", "Папка", "o"),
           ("copy", "Путь", "y")]


def make_view(test=False, style=None):
    import rec_menu as R
    import exe_frame
    from app_launcher import style_name
    cairo, Gdk, GLib, Gtk, Pango, PangoCairo = R.cairo, R.Gdk, R.GLib, R.Gtk, R.Pango, R.PangoCairo
    from gi.repository import Gio, GdkPixbuf  # noqa: F401
    mix = R.mix

    class View(R.App):
        """Рисование и логика; окно GTK — отдельно (Win), снимок — без окна."""

        def __init__(self):                        # App.__init__ не зовём: там окно меню
            self.test = test
            exe_frame.look(self, style or style_name())
            self.warn = self.C.get("err") or self.C.get("error")
            self.SW, self.SH = W, H
            entries, order = cached_scan(stale_ok=not test)
            self.by = index(entries)
            self.groups = grouped(entries, order)
            self.items = [e for _a, _i, es in self.groups for e in es]
            self.level, self.area, self.sel, self.scroll = 0, 0, 0, 0
            self.saved = 0                          # выбранная область — вернуться на неё
            self.mode, self.buf = "normal", ""
            self.max_vis = 10
            self.anim = None
            self.hover = None                       # строка или кнопка под мышью
            self.flash = None                       # (текст, время) — «путь скопирован»
            self.win = None
            th = Gtk.IconTheme.new()
            try:
                th.set_custom_theme(Gio.Settings.new("org.gnome.desktop.interface").get_string("icon-theme"))
            except Exception:
                pass
            self.theme, self.pix = th, {}

        # ── данные ─────────────────────────────────────────────────────────
        def rows(self):
            """[("area", i)] или [("item", e)] — что сейчас в списке."""
            if self.buf:
                if getattr(self, "_rows_key", None) == (self.buf, id(self.items), self.by):   # кадр зовёт rows() раз семь
                    return self._rows
                from smart_search import search
                found = search(self.buf, self.items, lambda e: (e["name"], e["desc"]),
                               weak=lambda e: (e["area"], how(e, self.by), short(e["path"])))
                found.sort(key=lambda e: e["kind"] == "hyprland-off")    # отложенное — в конец
                self._rows_key, self._rows = (self.buf, id(self.items), self.by), [("item", e) for e in found]
                return self._rows
            if self.level == 0:
                return [("area", i) for i in range(len(self.groups))]
            return [("item", e) for e in self.groups[self.area][2]]

        def reload(self, entries, order):
            """Свежий разбор из фона: подменить данные, выбор оставить на месте."""
            self.by = index(entries)
            self.groups = grouped(entries, order)
            self.items = [e for _a, _i, es in self.groups for e in es]
            self._rows_key = None
            self.area = min(self.area, max(0, len(self.groups) - 1))
            self.sel = min(self.sel, max(0, len(self.rows()) - 1))
            self.redraw()

        def current(self):
            rows = self.rows()
            if rows and 0 <= self.sel < len(rows):
                return rows[self.sel]
            return None

        def row_h(self):
            return ROW_F if self.buf or self.level else ROW_A

        def crumbs(self):
            if self.buf:
                return "Поиск"
            return "Области" if self.level == 0 else self.groups[self.area][0]

        def title_text(self):
            return TITLE if self.level == 0 and not self.buf else "%s » %s" % (TITLE, self.crumbs())

        # ── переходы ───────────────────────────────────────────────────────
        def snapshot(self):
            return (self.rows(), self.sel, self.scroll, self.row_h())

        def start_anim(self, d, old):
            self.anim = (time.monotonic(), d) + old
            self.redraw()

        def enter(self, i):
            old = self.snapshot()
            self.saved, self.area, self.level, self.sel, self.scroll = i, i, 1, 0, 0
            self.start_anim(1, old)

        def back(self):
            if self.buf:
                self.buf, self.mode, self.sel, self.scroll = "", "normal", 0, 0
                if self.level == 0:
                    self.sel = self.saved
                self.redraw()
            elif self.level == 1:
                old = self.snapshot()
                self.level, self.sel, self.scroll = 0, self.saved, 0
                self.start_anim(-1, old)
            else:
                self.close()

        def activate(self):
            r = self.current()
            if not r:
                return
            if r[0] == "area":
                self.enter(r[1])
            else:
                self.open_file(r[1])

        def open_file(self, e):
            if os.path.isdir(e["path"]):
                self.open_dir(e)
                return
            self.spawn("mousepad", os.path.realpath(e["path"]))
            self.close()

        def open_dir(self, e):
            """Папка — в Dolphin (Super+E), файл в ней выделен. Не xdg-open: папки по
            mimeapps открывает `kitty +open`, и окно не появлялось (13.10.2026)."""
            import shutil
            p = os.path.realpath(e["path"])
            if shutil.which("dolphin"):
                self.spawn("dolphin", "--new-window", p) if os.path.isdir(p) else \
                    self.spawn("dolphin", "--new-window", "--select", p)
            else:
                self.spawn("xdg-open", p if os.path.isdir(p) else os.path.dirname(p))
            self.close()

        def copy(self, e):
            self.spawn("wl-copy", short(e["path"]))
            self.flash = ("Скопировано: " + short(e["path"]), time.monotonic())
            if not self.test:
                GLib.timeout_add(1600, lambda: self.redraw() or False)
            self.redraw()

        def button(self, key):
            r = self.current()
            e = r[1] if r and r[0] == "item" else None
            if key == "back":
                self.back()
            elif key == "open":
                self.activate()
            elif key == "dir" and e:
                self.open_dir(e)
            elif key == "copy" and e:
                self.copy(e)
            elif key == "search":
                self.mode = "search"
                self.redraw()
            elif key == "close":
                self.close()

        def move(self, d, to=None):
            n = len(self.rows())
            if not n:
                return
            self.sel = max(0, min(n - 1, to if to is not None else self.sel + d))
            self.redraw()

        def spawn(self, *cmd):
            if self.test:
                return
            subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)

        def close(self):
            if self.test:
                return
            os._exit(0)                 # как Recorder: без Gtk.main_quit (зависал в gdk_flush)

        def redraw(self):
            if self.win is not None:
                self.win.area.queue_draw()

        # ── размеры ────────────────────────────────────────────────────────
        def panel_rect(self):
            return 0, 0, self.SW, self.SH

        def box(self):
            """Внутренняя область: x0, x1 и верх под строкой кнопок."""
            G = self.G
            x0 = G["BORDER"] + G["PAD"] + (8 if self.style == "skeet" else 0)
            return x0, self.SW - x0, G["TOP"] + G["TB"] + 12

        def tool_zones(self, cr=None):
            """[(ключ, x, y, w, h)] — кнопки и поле поиска."""
            x0, x1, y = self.box()
            out, x = [], x0
            for key, label, hint in BUTTONS:
                w = 24 + self.text_w(label + "  " + hint)
                out.append((key, x, y, w, TOOL_H))
                x += w + 8
            out.append(("search", x + 8, y, x1 - x - 8, TOOL_H))
            return out

        def list_rect(self):
            x0, x1, y = self.box()
            top = y + TOOL_H + (26 if self.style == "skeet" else 12)
            bottom = self.SH - self.G["BORDER"] - 10 - STATUS_H - DETAIL_H - 10
            return x0, top, x1 - x0, bottom - top

        def text_w(self, s):
            cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
            cr.set_font_options(self.fo)
            return self.layout(cr, s).get_pixel_size()[0]

        # ── значки ─────────────────────────────────────────────────────────
        def icon(self, name, size):
            k = (name, size)
            if k not in self.pix:
                pb = None
                for n in (name, "text-x-generic"):
                    try:
                        pb = self.theme.load_icon(n, size, Gtk.IconLookupFlags.FORCE_SIZE)
                        break
                    except Exception:
                        continue
                self.pix[k] = pb
            return self.pix[k]

        def draw_icon(self, cr, name, x, y, size):
            pb = self.icon(name, size)
            if pb is None:
                return
            cr.save()
            Gdk.cairo_set_source_pixbuf(cr, pb, x, y)
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint()
            cr.restore()

        # ── рисование ──────────────────────────────────────────────────────
        def txt(self, cr, s, x, y, color, width=None, bold=False, lines=1):
            lay = self.layout(cr, s, width)
            if bold:
                fd = self.fd.copy()
                fd.set_weight(Pango.Weight.BOLD)
                lay.set_font_description(fd)
            if lines > 1 and width:
                lay.set_wrap(Pango.WrapMode.WORD_CHAR)
                lay.set_height(-lines)
            cr.set_source_rgb(*color)
            cr.move_to(int(x), int(y))
            PangoCairo.show_layout(cr, lay)
            return lay.get_pixel_size()

        def progress(self):
            if not self.anim:
                return None
            p = (time.monotonic() - self.anim[0]) * 1000 / ANIM_MS
            if p >= 1 or self.test:
                self.anim = None
                return None
            return 1 - (1 - p) ** 3

        def on_draw(self, _a, cr):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.set_font_options(self.fo)
            try:
                self.render(cr)
            except Exception as err:
                print("config_map: кадр: %s" % err, file=sys.stderr)
            if self.anim:
                self.redraw()
            return True

        def render(self, cr):
            C, G = self.C, self.G
            W_, H_ = self.SW, self.SH
            cr.set_source_rgb(*C["win_bg"])
            cr.rectangle(0, 0, W_, H_)
            cr.fill()
            if self.dots is not None:
                cr.set_source(self.dots)
                cr.paint()
            self.frame(cr, W_, H_)
            self.close_btn(cr)
            self.toolbar(cr)
            lx, top, lw, lh = self.list_rect()
            self.group(cr, lx, top, lw, lh, self.crumbs())
            cr.save()
            cr.rectangle(lx, top, lw, lh)
            cr.clip()
            rows = self.rows()
            e = self.progress()
            if e is None:
                self.draw_list(cr, rows, self.sel, lx, top, lw, lh, self.row_h(), True)
            else:
                d, slide = self.anim[1], lw + 2 * G["PAD"]
                o_rows, o_sel, o_scroll, o_rh = self.anim[2:6]
                keep = self.scroll
                self.scroll = o_scroll
                self.draw_list(cr, o_rows, o_sel, lx - d * e * slide, top, lw, lh, o_rh, False)
                self.scroll = keep
                self.draw_list(cr, rows, self.sel, lx + d * (1 - e) * slide, top, lw, lh, self.row_h(), True)
            cr.restore()
            dy = top + lh + 10
            self.detail(cr, lx, dy, lw, DETAIL_H)
            self.status(cr, lx, H_ - G["BORDER"] - STATUS_H - 4, lw)

        def frame(self, cr, W_, H_):
            exe_frame.frame(self, cr, W_, H_, MAP_BMP)

        def btn_box(self, cr, x, y, w, h, hov, on=False):
            """Кнопка в стиле окна: XP — выпуклая, skeet — градиент, beta — плоская."""
            C = self.C
            if self.style == "skeet":
                g = cairo.LinearGradient(0, y, 0, y + h)
                g.add_color_stop_rgb(0, *(mix(C["field_l"], self.acc, 0.25) if hov or on else C["field_l"]))
                g.add_color_stop_rgb(1, *C["field"])
                cr.set_source(g)
                cr.rectangle(x, y, w, h)
                cr.fill()
                self.rect_line(cr, x, y, w, h, C["line3"])
                self.rect_line(cr, x + 1, y + 1, w - 2, h - 2, C["gline"] if not on else self.acc)
            elif self.style == "beta":
                self.rect_fill(cr, x, y, w, h, C["hover"] if hov else C["field"])
                self.rect_line(cr, x, y, w, h, self.acc if on else C["line_strong"])
            else:
                top = mix(C["st_top"], (1, 1, 1), 0.15) if hov else C["st_top"]
                g = cairo.LinearGradient(0, y, 0, y + h)
                g.add_color_stop_rgb(0, *top)
                g.add_color_stop_rgb(1, *C["st_bot"])
                cr.set_source(g)
                cr.rectangle(x, y, w, h)
                cr.fill()
                self.rect_line(cr, x, y, w, h, C["st_hi"] if on else C["st_dark"])

        def toolbar(self, cr):
            C = self.C
            r = self.current()
            has_file = bool(r and r[0] == "item")
            for key, x, y, w, h in self.tool_zones():
                hov = self.hover == ("btn", key)
                if key == "search":
                    on = self.mode == "search"
                    self.rect_fill(cr, x, y, w, h, C.get("field") or mix(C["win_bg"], (0, 0, 0), 0.25))
                    self.rect_line(cr, x, y, w, h, self.acc if on or hov else self.soft)
                    ty = y + (h - self.LH) // 2 + 1
                    if self.buf or on:
                        tw = self.txt(cr, self.buf, x + 10, ty, C["text"], w - 24)[0]
                        if on:
                            self.rect_fill(cr, x + 10 + tw + 1, y + 6, 2, h - 12, self.acc)
                    else:
                        self.txt(cr, "/  Поиск: скриншот, курсор, бар…", x + 10, ty, self.faint, w - 20)
                    continue
                label, hint = [(b[1], b[2]) for b in BUTTONS if b[0] == key][0]
                off = (key in ("dir", "copy") and not has_file) or (key == "back" and self.level == 0 and not self.buf)
                self.btn_box(cr, x, y, w, h, hov and not off)
                ty = y + (h - self.LH) // 2 + 1
                ink = C["on_surface"] if self.style == "default" else C["text"]
                if off:
                    ink = mix(ink, C["win_bg"], 0.55)
                tw = self.txt(cr, label, x + 12, ty, ink)[0]
                self.txt(cr, hint, x + 12 + tw + self.text_w("  "), ty,
                         mix(ink, C["win_bg"], 0.45) if not off else mix(ink, C["win_bg"], 0.4))

        def group(self, cr, x, y, w, h, label):
            """Подложка списка: skeet — группа с подписью, beta — карточка, XP — рамка."""
            C = self.C
            if self.style == "skeet":
                gx, gy, gw, gh = x - 10, y - 12, w + 20, h + 20
                self.rect_line(cr, gx, gy, gw, gh, C["gline"])
                self.rect_line(cr, gx + 1, gy + 1, gw - 2, gh - 2, C["gdark"])
                lw = self.text_w(label)
                self.rect_fill(cr, gx + 10, gy - 1, lw + 8, 3, C["bg"])
                if self.dots is not None:
                    cr.save()
                    cr.rectangle(gx + 10, gy - 1, lw + 8, 3)
                    cr.clip()
                    cr.set_source(self.dots)
                    cr.paint()
                    cr.restore()
                self.txt(cr, label, gx + 14, gy - self.G["PX"] // 2 - 1, C["text"])
            elif self.style == "beta":
                self.rect_fill(cr, x - 1, y - 1, w + 2, h + 2, C["card"])
                self.rect_line(cr, x - 1, y - 1, w + 2, h + 2, C["line"])
            else:
                self.rect_line(cr, x - 1, y - 1, w + 2, h + 2, C["st_mid"])

        def draw_list(self, cr, rows, sel, x, top, w, h, R_, live):
            C, st = self.C, self.style
            vis = max(1, h // R_)
            if live:
                self.max_vis = vis
            if not rows:
                if live:
                    self.txt(cr, "Ничего не найдено. Попробуйте другое слово.", x + 16, top + 10, self.faint)
                return
            sel = max(0, min(sel, len(rows) - 1))
            off = min(self.scroll, sel)
            if sel >= off + vis:
                off = sel - vis + 1
            off = max(0, min(off, len(rows) - vis))
            if live:
                self.sel, self.scroll = sel, off
            for i in range(off, min(off + vis, len(rows))):
                y = top + (i - off) * R_
                on = i == sel
                hov = live and self.hover == ("row", i) and not on
                ry, rh = y + 1, R_ - 2
                if on:
                    self.rect_fill(cr, x, ry, w, rh, C["sel_bg"])
                    if st == "skeet":
                        self.rect_line(cr, x, ry, w, rh, C["gline"])
                    if st != "default":
                        self.rect_fill(cr, x, ry, 3, rh, self.acc)
                elif hov:
                    self.rect_fill(cr, x, ry, w, rh, C["text"], 0.07)
                elif st == "default":
                    self.rect_fill(cr, x, ry, w, rh, C["row"], 0.045)
                fg = C["sel_text"] if on else C["text"]
                dim = C["sel_text"] if on else C["dim"]
                ty = ry + (rh - self.LH) // 2 + 1
                r = rows[i]
                if r[0] == "area":
                    a, _ch, es = self.groups[r[1]]
                    icon, desc = AREA_INFO.get(a, AREA_INFO["Прочее"])
                    self.draw_icon(cr, icon, x + 10, ry + (rh - 32) // 2, 32)
                    self.txt(cr, a, x + 54, ty, fg, 380)
                    self.txt(cr, desc, x + 54 + 396, ty, dim, w - 54 - 396 - 70)
                    self.txt(cr, str(len(es)), x + w - 52, ty, dim)
                    cr.set_source_rgb(*(C["sel_text"] if on else C["arrow"]))
                    R.draw_bitmap(cr, R.ARROW_BMP, x + w - 22, ry + (rh - 14) // 2, 2)
                else:
                    e = r[1]
                    self.draw_icon(cr, icon_for(e), x + 10, ry + (rh - 24) // 2, 24)
                    nm = e["name"] if e["kind"] != "команда" else "$ " + e["name"]
                    col = self.faint if e["kind"] == "hyprland-off" and not on else fg
                    self.txt(cr, nm, x + 44, ty, col, 280)
                    mark = "⚠ " if orphan(e) else ""
                    self.txt(cr, mark + (e["desc"] or "—"), x + 340, ty, dim, w - 350)
            if len(rows) > vis and live:
                bh = max(14, h * vis / len(rows))
                by = top + (h - bh) * off / max(1, len(rows) - vis)
                self.rect_fill(cr, x + w - 3, by, 3, bh, self.faint)

        def detail(self, cr, x, y, w, h):
            C = self.C
            self.rect_fill(cr, x, y, w, 1, self.soft)
            r = self.current()
            if not r:
                return
            big = 96
            ix = x + w - big - 12
            iy = y + (h - big) // 2 + 2
            if r[0] == "area":
                a, _ch, es = self.groups[r[1]]
                icon, desc = AREA_INFO.get(a, AREA_INFO["Прочее"])
                nconf = sum(1 for e in es if e["kind"] == "конфиг")
                norph = sum(1 for e in es if orphan(e))
                stat = "%d файлов" % len(es) + (" · %d конфигов" % nconf if nconf else "") + \
                       (" · ⚠ %d без вызова" % norph if norph else "")
                lines = [(None, a), ("Что здесь", desc), ("Всего", stat),
                         ("Например", ", ".join(e["name"] for e in es[:6]) + ("…" if len(es) > 6 else ""))]
            else:
                e = r[1]
                icon = icon_for(e)
                lines = [(None, e["desc"] or e["name"]),
                         ("Файл", short(e["path"])),
                         ("Область", e["area"] + ("  ·  " + e["kind"] if e["kind"] != "скрипт" else "")),
                         ("Запуск", how(e, self.by) or ("никто не вызывает — кандидат на чистку"
                                                       if orphan(e) else "—")),
                         ("Упоминают", ", ".join(e["refs"]) or "—")]
            # подложка картинки
            self.rect_fill(cr, ix - 8, iy - 8, big + 16, big + 16, self.field)
            self.rect_line(cr, ix - 8, iy - 8, big + 16, big + 16, self.soft)
            self.draw_icon(cr, icon, ix, iy, big)
            ty, tw = y + 10, ix - 8 - x - 16
            for k, v in lines:
                if k is None:
                    self.txt(cr, v, x + 4, ty, self.acc if self.style != "default" else C["primary"], tw, bold=True)
                    ty += self.LH + 6
                    continue
                self.txt(cr, k, x + 4, ty, self.faint)
                self.txt(cr, v, x + 136, ty, C["text"], tw - 132)
                ty += self.LH + 4

        def status(self, cr, x, y, w):
            C = self.C
            self.rect_fill(cr, x, y - 4, w, 1, self.soft)
            badge = "SEARCH" if self.mode == "search" else "NORMAL"
            bw = self.text_w(badge) + 14
            self.rect_fill(cr, x, y, bw, 22, self.field)
            self.txt(cr, badge, x + 7, y + (22 - self.LH) // 2 + 1, self.acc)
            if self.flash and time.monotonic() - self.flash[1] < 1.5:
                hint = self.flash[0]
            elif self.mode == "search":
                hint = "печатайте · ↑↓ выбор · Enter — к списку · Esc — сброс"
            elif self.level == 0 and not self.buf:
                hint = "j/k ↕ · l/Enter войти · / поиск · g/G · q, Ctrl+Q выход"
            else:
                hint = "j/k ↕ · Enter открыть · h назад · o папка · y путь · q выход"
            self.txt(cr, hint, x + bw + 10, y + (22 - self.LH) // 2 + 1, self.faint, w - bw - 120)
            n = len(self.items)
            self.txt(cr, "%d файлов" % n, x + w - self.text_w("%d файлов" % n), y + (22 - self.LH) // 2 + 1,
                     self.faint)

        # ── мышь ───────────────────────────────────────────────────────────
        def zone_at(self, x, y):
            cx, cy, cw, ch = self.cap_zone()
            if cx <= x < cx + cw and cy <= y < cy + ch:
                return ("btn", "close")
            G = self.G
            if y < G["TOP"] + G["TB"]:
                return ("title", None)
            for key, bx, by, bw, bh in self.tool_zones():
                if bx <= x < bx + bw and by <= y < by + bh:
                    return ("btn", key)
            lx, top, lw, lh = self.list_rect()
            if lx <= x < lx + lw and top <= y < top + lh:
                i = self.scroll + int((y - top) // self.row_h())
                if i < len(self.rows()):
                    return ("row", i)
            return None

        def click(self, z, double=False):
            if not z:
                return
            kind, v = z
            if kind == "btn":
                self.button(v)
            elif kind == "title" and (self.level or self.buf):
                self.back()
            elif kind == "row":
                r = self.rows()[v]
                if r[0] == "area":
                    self.sel = v
                    self.enter(r[1])
                elif double:
                    self.sel = v
                    self.open_file(r[1])
                else:
                    self.sel = v
                    if self.mode == "search":
                        self.mode = "normal"
                    self.redraw()

        # ── клавиши ────────────────────────────────────────────────────────
        def key(self, ch, name, ctrl, shift, uni):
            if ctrl and ch == "q":
                self.close()
                return
            if self.mode == "search":
                if name == "Escape":
                    if self.buf:
                        self.buf, self.sel, self.scroll = "", 0, 0
                    self.mode = "normal"
                    if self.level == 0:
                        self.sel = self.saved
                elif name in ("Return", "KP_Enter"):
                    self.mode, self.sel = "normal", 0
                elif name in ("Down", "Up") or (ctrl and ch in ("j", "k", "n", "p")):
                    self.move(1 if name == "Down" or ch in ("j", "n") else -1)
                elif name == "BackSpace":
                    self.buf = self.buf[:-1]
                    self.sel = self.scroll = 0
                    if not self.buf and self.level == 0:
                        self.sel = self.saved
                elif uni and uni.isprintable() and len(self.buf) < 60:
                    self.buf += uni
                    self.sel = self.scroll = 0
                self.redraw()
                return
            r = self.current()
            e = r[1] if r and r[0] == "item" else None
            if ch == "q" and not ctrl:
                self.close()
            elif name in ("Escape", "BackSpace", "Left") or ch == "h":
                self.back()
            elif ch == "j" or name == "Down" or (ctrl and ch == "n"):
                self.move(1)
            elif ch == "k" or name == "Up" or (ctrl and ch == "p"):
                self.move(-1)
            elif ctrl and ch in ("d", "u"):
                self.move(max(1, self.max_vis // 2) * (1 if ch == "d" else -1))
            elif ch == "g" or name in ("Home", "End"):
                self.move(0, len(self.rows()) - 1 if shift or name == "End" else 0)
            elif ch == "l" or name in ("Return", "KP_Enter", "Right"):
                self.activate()
            elif ch == "/":
                self.mode = "search"
                self.redraw()
            elif ch == "o" and e:
                self.open_dir(e)
            elif ch == "y" and e:
                self.copy(e)

    return View


def shot(path, query="", area=None, sel=0, style=None):
    v = make_view(test=True, style=style)()
    if area is not None:
        names = [a for a, _i, _e in v.groups]
        v.enter(names.index(area) if area in names else int(area))
    v.sel = sel
    if query:
        v.buf, v.mode = query, "normal"
    v.anim = None
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    v.on_draw(None, cr)
    surf.write_to_png(path)
    print("saved", path)


def window():
    # Импорт gi тянет asyncio (~150 мс) — пустышка на время импорта, как в rec_menu.py.
    stub = None
    if "gi" not in sys.modules and "asyncio" not in sys.modules:
        import types
        stub = types.ModuleType("asyncio")
        stub.InvalidStateError = type("InvalidStateError", (Exception,), {})
        stub._get_running_loop = stub.get_running_loop = lambda: None
        sys.modules["asyncio"] = stub
    try:
        View = make_view()
    finally:
        if stub is not None and sys.modules.get("asyncio") is stub:
            del sys.modules["asyncio"]
    import rec_menu as R
    from keybinds_sheet import KEYS
    Gdk, Gtk, GtkLayerShell = R.Gdk, R.Gtk, R.GtkLayerShell

    v = View()
    if STALE:                                       # кэш устарел: показали старое, свежее — в фоне
        import threading
        from gi.repository import GLib

        def fresh():
            try:
                entries, order = rescan()
            except Exception as err:
                print("config_map: фоновый разбор: %s" % err, file=sys.stderr)
                return
            GLib.idle_add(lambda: v.reload(entries, order) or False)
        threading.Thread(target=fresh, daemon=True).start()

    class Win(Gtk.Window):
        def __init__(self):
            super().__init__(title="Карта staticOS")
            self.set_decorated(False)
            self.set_app_paintable(True)
            vis = self.get_screen().get_rgba_visual()
            if vis:
                self.set_visual(vis)
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, "jarvis-config-map")
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
            self.area = Gtk.DrawingArea()
            self.area.set_size_request(W, H)
            self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                                 | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                                 | Gdk.EventMask.SCROLL_MASK)
            self.area.connect("draw", v.on_draw)
            self.area.connect("button-press-event", self.on_press)
            self.area.connect("button-release-event", self.on_release)
            self.area.connect("motion-notify-event", self.on_motion)
            self.area.connect("leave-notify-event", self.on_leave)
            self.area.connect("scroll-event", self.on_scroll)
            self.add(self.area)
            self.connect("key-press-event", self.on_key)
            self.press = None

        def on_key(self, _w, ev):
            u = Gdk.keyval_to_unicode(ev.keyval)
            v.key(KEYS.get(ev.hardware_keycode, ""), Gdk.keyval_name(ev.keyval) or "",
                  bool(ev.state & Gdk.ModifierType.CONTROL_MASK),
                  bool(ev.state & Gdk.ModifierType.SHIFT_MASK), chr(u) if u else "")
            return True

        def on_press(self, _w, ev):
            if ev.button != 1:
                return True
            z = v.zone_at(ev.x, ev.y)
            if ev.type == Gdk.EventType._2BUTTON_PRESS:
                if z and z[0] == "row":
                    v.click(z, double=True)
                self.press = None
                return True
            self.press = z
            return True

        def on_release(self, _w, ev):
            if ev.button != 1 or self.press is None:
                return True
            z, self.press = self.press, None
            if v.zone_at(ev.x, ev.y) == z:     # отпустили там же, где нажали
                v.click(z)
            return True

        def on_motion(self, _w, ev):
            z = v.zone_at(ev.x, ev.y)
            if z != v.hover:
                v.hover = z
                cx = z == ("btn", "close")
                v.hover_cap = cx
                self.area.queue_draw()
            return True

        def on_leave(self, *_a):
            if v.hover is not None:
                v.hover, v.hover_cap = None, False
                self.area.queue_draw()
            return False

        def on_scroll(self, _w, ev):
            d = -3 if ev.direction == Gdk.ScrollDirection.UP else 3 \
                if ev.direction == Gdk.ScrollDirection.DOWN else 0
            if d:
                v.move(d)
            return True

    w = Win()
    v.win = w
    w.show_all()
    Gtk.main()
    os._exit(0)


def toggle_pidfile():
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-config-map.pid")


def main():
    a = sys.argv[1:]
    if a[:1] == ["md"]:
        md(a[1] if len(a) > 1 else None)
    elif a[:1] == ["check"]:
        return check()
    elif a[:1] == ["--shot"]:
        rest, opts = [], {}
        it = iter(a[1:])
        for x in it:
            if x in ("--area", "--query", "--sel", "--style"):
                opts[x[2:]] = next(it, "")
            else:
                rest.append(x)
        shot(rest[0] if rest else "/tmp/config_map.png",
             opts.get("query") or (rest[1] if len(rest) > 1 else ""),
             opts.get("area"), int(opts.get("sel", 0)), opts.get("style"))
    elif not a:
        pf = toggle_pidfile()                       # второй запуск закрывает окно
        try:
            pid = int(open(pf).read())
            if open("/proc/%d/cmdline" % pid, "rb").read().find(b"config_map.py") >= 0:
                os.kill(pid, 15)
                return 0
        except (OSError, ValueError):
            pass
        with open(pf, "w") as f:
            f.write(str(os.getpid()))
        window()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
