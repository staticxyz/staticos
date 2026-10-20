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
    config_map.py --shot ФАЙЛ [ЗАПРОС] [--section РАЗДЕЛ] [--area ОБЛАСТЬ] [--sel N] [--style default|skeet|beta]
                            снимок окна вне экрана
Окно: Super+Shift+Z, вид Recorder.exe по стилю системы. Три уровня (с 14.10.2026):
9 разделов плитками (только значок и заголовок) → области → файлы с описаниями, разбитые
на списки «Конфиги / Скрипты / Команды / Разовые…». Раздел из одной области («Где что
лежит» — папки конфигов) открывается сразу списком. Клавиши как в nvim: на плитках hjkl
ходят по сетке; дальше j/k, g/G, Ctrl+D/U, l/Enter вперёд, h/Esc назад, / поиск
(smart_search: синонимы, опечатки, раскладка), o файл в папке, y путь, c — папка
~/.config, q или Ctrl+Q — выход (Ctrl+Q закрывает карту, а не окно под ней).
Мышью: стрелка «назад», значок папки (~/.config), внизу карточки «Открыть в папке» / «Копировать путь», поле поиска,
щелчок по плитке и области, двойной по файлу.
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
# Это нижний уровень перед файлами; сверху их собирают разделы SECTIONS.
AREAS = [
    # Внешний вид
    ("Обои", "◐", """
        wallpaper_blur.py wallpaper_picker.py wallpaper_pixel.py wallpaper_preview.py
        wp_grab.py sparkle_wallpaper.py pixel_recolor.py wallpaper_watch"""),
    ("Цвета по обоям", "◑", """
        theme_changer.sh theme_changer.sh.bak-icons theme_snapshot.sh theme_doctor.py
        gen_term_colors.py broadcast_colors.py gtk_live_colors.py gtk_tint.py gtk_guard.py
        merge_kdeglobals.py folder_colors.py kitty_icon.py widget_accent.py cava_colors.py
        fastfetch_colors.py tide_colors.py reload_btop.py theme-doctor theme-snapshot"""),
    ("Стиль системы и шрифты", "◆", """
        pixel_look.py pixel_mode.py system_style.py app_fonts.py cozette_fit.py
        rofi_style.py launcher_style.py mixer_style.py wlogout_icons.py icon_theme.py
        rofi fontprofile fontswap font-sample"""),
    ("Курсор", "➤", """
        cursor_colors.py cursor_shake.py cursor_theme.py bit_cursor.py
        tri_cursor.py skeet_cursor.py jarvis_pebble.py yamikai_wall.py"""),
    ("Уведомления и звуки интерфейса", "✉", """
        notif_style.py track_notify.py island.py island_dl.py island_nudge.py island_sys.py dnd_sounds.py auto_dnd.py ui_sound.py
        ui_sound_retro.py ui_sound_watch.py layout_osd notif-look notify-send"""),
    # Панели
    ("Бар: устройство", "▔", """
        top_bar.py panels.py wb_hub.py wb_persist.py wb_share bar_watch niri_bar.py
        waybar_niri.py barfix bar_border.py bar_margins.py bar_rounding.py bar_style.py"""),
    ("Бар: модули", "▀", """
        bar_language.py bar_window_title.py browser_status.py bongo_cat.py cava_bar.py
        mpris_common.py mpris_status.py mpris_focus privacy_status.py rec_status.sh
        ribbon_map.py sensor_colors.py start_button.py start_glyphs.py taskbar.py waybar_clock.py
        ws_labels.py ws_order.py lyrics_bar.py bar_volume.py bar_volume.sh
        savage_battery.py battery_mini.py"""),
    ("Бар: шрифты значков", "Aa", """
        build_bar_icons.py build_battery_font.py build_bongo_font.py build_wave_font.py
        build_wolf_font.py build_zen_font.py build_start_font.py build_taskbar_font.py"""),
    ("Плашки бара", "▤", """
        appmem_popup.py battery_popup.py bluetooth_popup.py bt_stats_popup.py
        calendar_popup.py calendar_app.py control_center.py lan_popup.py mic_popup.py
        notif_log.py player_like.py player_like_key player_popup.py popup_theme.py
        power_view.py router_clients.py router_pass.py volume_popup.py wifi_net_popup.py
        wifi_popup.py popup-toggle"""),
    ("Нижняя панель, док, «Пуск»", "▁", """
        bottom_bar.py dock.py xpbar.py xpbar_colors.py xp_calendar.py start_menu.py
        super_tap.py app_search.py power_xp.py"""),
    ("Виджеты и меню рабочего стола", "▦", """
        desktop_widgets.py desktop_widgets_extra.py preset_ask.py banner_ask.py banner_fx.py desktop_menu.py
        timer_ask.sh"""),
    # Окна и клавиши
    ("Конфиг niri", "▣", ""),
    ("Окна и столы", "▢", """
        alt_tab.py alt_tab.sh ribbon_center.py mouse_focus.py mouse_wait_release.py
        window_fx.py wm.py hot_corners.py
        pip_place.py ws_layout.py mousepad_place.py colexpand colwidth floattoggle magic
        move_all no_self_maximize.py pair_center.py winreset ws_insert ws-step close-or-clipboard
        dashboard shell-switch shell-do ws-anim"""),
    ("Настройки и справка", "⚙", """
        settings_app.py niri_state.py niri_compositor.py keybinds_sheet.py binds_edit.py smart_search.py exe_frame.py close_cap.py scrim_layer.py menu_one.py app_list.py
        config_map.py skeet_icons/ settings-open slashkey applist"""),
    # Экран и звук
    ("Блокировка и вход", "⏻", """
        jarvis_lock.py lock_battery.sh lock_layout.sh lock_net.sh lock_power.py
        lock_power_label.sh lock_style.py lockscreen avatar_picker.py login_theme.py
        login_theme/ vt_guard"""),
    ("Простой, сон, заставка", "☾", """
        idle_dim idle_guard.py idle_lock idle_suspend screen_awake.py screensaver.py
        power_menu.py alt-f4 dpms screenon output-mode-fix"""),
    ("Яркость и ночной свет", "☀", """
        screen_gamma.py night_mode.py monitor_brightness.py"""),
    ("Звук и микрофон", "♪", """
        app_volume.py audio_names.py audio_repair sound_guard.sh mic_monitor.py mediakey
        audio-resume-fix mic-floor mic-guard"""),
    ("Музыка и тексты песен", "♫", """
        lyrics_sync.py lyrics_sync_asr.py lyrics_sync_sep.py ym_font.py ym_font_watch.py
        ym_launch.sh ym_theme.py ym_tweaks.py ytm_colors.py ytmd_auth.py"""),
    ("Подсветка Razer", "⌨", """
        kbd_colors.py kbdlight kbdlight_watch razer_brightness.py razer_restore"""),
    ("Питание, вентиляторы, видеокарта", "⚡", """
        fan power flash"""),
    # Программы
    ("Браузер и мессенджеры", "◇", """
        discord_pixel.py discord_splash.js zen_style.py telegram_colors.py
        matugen_native_host.py zen-crt zen-browser"""),
    ("Терминал kitty", ">_", """
        kitty_shader.py kitty_shader_colors.py kitty_shared.sh term_font.sh termlook
        susanoo_bake.py"""),
    ("Steam и игры", "◉", """
        steam_space.py game_guard.py game-clip-push"""),
    ("Другие программы", "□", """
        keepassxc_style.py vscode_colors.py obsidian_opacity.py mousepad_retheme.sh
        notepad.sh office_setup.sh ttyper_colors.py keepassxc keepassxc-setup"""),
    ("Часы и таймеры в терминале", "◷", """
        tclock tdown dateview.py jclock timer"""),
    ("fetch и забавы в терминале", "✦", """
        ffetch archfetch brrt brrtfetch fetch3d tmatrix text hollywood ccze
        nowrap ptyclean ptysync"""),
    ("Тетрис и тренажёр набора", "▙", """
        jtetris jtype"""),
    # Инструменты
    ("Калькулятор и перевод", "=", """
        calc_copy.sh calc_menu.sh calc_qalc.py translate_popup.py translate_server.py
        translate_best.sh translate_google.py"""),
    ("Буфер обмена", "⎘", """
        clipboard_menu.py clipboard_win.py clipboard-toggle cliphist-store xclip
        x-clip-pull x11-clip-bridge x11-clip-events wtype"""),
    ("Снимки и запись экрана", "✂", """
        freeze_lib.sh freeze_screen.py pin_shot.py ocr_copy.sh pxocr.py term_text.py
        screenshot_annotate.sh rec_area.sh rec_frame.py rec_menu.py rec_nobg.py
        rec_style.py replay_saved.sh replay picker rembg"""),
    ("Запуск программ", "▶", """
        launcher.py app_launcher.py launcher_term.sh webapp"""),
    ("Экранное время и нагрузка", "◔", """
        screentime.py screentime_daemon.py appmem jtop"""),
    ("Discipline и hub", "⏱", """
        routine_app.py focus_mode.py pomo_lock.py alarm discipline routine pomo hub hub-open rem dict wa tfa jchat jchat-tg jchat-wa"""),
    ("Будильник", "⏰", """
        wake_alarm.py jarvis-rtc-wake.sh wake_overlay.py wake-alarm"""),
    # Служебное
    ("Самопроверка и сторожа", "✚", """
        staticos_host.py cpu_hog_watch.py session_env.py staticos-doctor"""),
    ("Сторонние программы", "□", """
        uv uvx python3.12"""),
    ("Hyprland — не используется", "✕", """
        layout_mode.py window_rounding.py cursor_watch dim_toggle.py overview.py
        window_switcher.py window_switcher.sh move_all_windows.sh hypr-focus-guard.sh"""),
    ("Папки конфигов", "▭", ""),
]
OTHER = ("Прочее", "?")
FOLDERS_AREA = "Папки конфигов"     # до 14.10.2026 — «Где что лежит»

# Верхний уровень карты: (раздел, значок темы, области). Раздел с одной областью
# открывается сразу файлами. Область, не попавшая ни в один раздел, — в «Служебное».
SECTIONS = [
    ("Внешний вид", "preferences-desktop-theme-global",
     ["Обои", "Цвета по обоям", "Стиль системы и шрифты", "Курсор", "Уведомления и звуки интерфейса"]),
    ("Панели", "preferences-desktop",
     ["Бар: устройство", "Бар: модули", "Плашки бара", "Нижняя панель, док, «Пуск»",
      "Виджеты и меню рабочего стола", "Бар: шрифты значков"]),
    ("Окна и клавиши", "view-grid", ["Конфиг niri", "Окна и столы", "Настройки и справка"]),
    ("Экран и звук", "preferences-desktop-sound",
     ["Блокировка и вход", "Простой, сон, заставка", "Яркость и ночной свет", "Звук и микрофон",
      "Музыка и тексты песен", "Подсветка Razer", "Питание, вентиляторы, видеокарта"]),
    ("Программы", "preferences-desktop-default-applications",
     ["Браузер и мессенджеры", "Терминал kitty", "Steam и игры", "Другие программы",
      "Часы и таймеры в терминале", "fetch и забавы в терминале", "Тетрис и тренажёр набора"]),
    ("Инструменты", "applets-screenshooter",
     ["Калькулятор и перевод", "Буфер обмена", "Снимки и запись экрана", "Запуск программ",
      "Экранное время и нагрузка", "Discipline и hub", "Будильник"]),
    ("Служебное", "utilities-system-monitor",
     ["Самопроверка и сторожа", "Сторонние программы", "Hyprland — не используется", "Прочее"]),
    ("Папки конфигов", "folder", ["Папки конфигов"]),
]

# Папки конфигов — раздел «Папки конфигов» и таблица в 0-КАРТА.md: (путь, что там).
FOLDERS = [                    # (путь, что там, чьё) — «чьё» делит раздел на списки (FOLDER_KINDS)
    ("~/.config/niri/cfg", "Конфиг niri по частям (*.kdl)", "niri"),
    ("~/.config/niri/scripts", "Скрипты только для niri: окна, столы, бар", "niri"),
    ("~/.config/niri/state", "Состояние: режим дашборда, анимация столов", "niri"),
    ("~/.config/hypr/scripts", "Скрипты системы (имя hypr — по истории)", "мои"),
    ("~/.config/hypr/state", "Выбранные настройки: файл на переключатель", "мои"),
    ("~/.local/bin", "Команды для терминала", "мои"),
    ("~/.local/share/hub", "hub: напоминания, словарь, база hub.db", "мои"),
    ("~/.config/waybar", "Верхний бар: конфиги, стили, заготовки", "программы"),
    ("~/.config/systemd/user", "Службы: hub, будильник, сторожа, туннели", "программы"),
    ("~/.config/hyprland-off", "Hyprland — отложен, не используется", "служебное"),
]
FOLDER_KINDS = {"niri": "niri", "мои": "Мои (staticOS)", "программы": "Программы", "служебное": "Служебное"}

# Что должно стоять на ПК, чтобы область или файл показывались (14.10.2026: «карта должна
# отражать, что у пользователя действительно установлено»). Любой из вариантов: имя
# программы ищется в PATH без ~/.local/bin (там обёртки staticOS), путь — проверяется.
AREA_NEEDS = {
    "Подсветка Razer": ["openrazer-daemon"],
    "Steam и игры": ["steam"],
    "Hyprland — не используется": ["Hyprland", "hyprland"],
}
FILE_NEEDS = [
    ("discord_pixel.py discord_splash.js", ["discord", "Discord", "vesktop"]),
    ("zen_style.py zen-crt zen-browser", ["~/.local/opt/zen", "zen-browser", "/opt/zen-browser-bin"]),
    ("telegram_colors.py", ["Telegram", "telegram-desktop"]),
    ("matugen_native_host.py", ["librewolf"]),
    ("keepassxc_style.py keepassxc keepassxc-setup", ["keepassxc"]),
    ("vscode_colors.py", ["code", "codium"]),
    ("obsidian_opacity.py", ["obsidian"]),
    ("mousepad_retheme.sh mousepad_place.py", ["mousepad"]),
    ("ym_font.py ym_font_watch.py ym_launch.sh ym_theme.py ym_tweaks.py", ["yandex-music", "/opt/yandex-music"]),
    ("ytm_colors.py ytmd_auth.py ytm-glass.css", ["youtube-music-desktop-app", "youtube-music"]),
    ("steam_space.py", ["steam"]),
    ("hyprlock.conf hyprlock-astronaut.conf lock_style.py", ["hyprlock"]),
    ("hypridle.conf", ["hypridle"]),
]
FILE_NEED = {n: needs for names, needs in FILE_NEEDS for n in names.split()}


def have(what):
    """Есть ли на ПК программа или путь (см. AREA_NEEDS)."""
    import shutil
    if what.startswith(("/", "~")):
        return os.path.exists(ex(what))
    if what not in _HAVE:
        local = ex("~/.local/bin")
        path = os.pathsep.join(d for d in os.environ.get("PATH", "/usr/bin").split(os.pathsep)
                               if d and os.path.realpath(d) != os.path.realpath(local))
        _HAVE[what] = bool(shutil.which(what, path=path))
    return _HAVE[what]


_HAVE = {}


def present(entries):
    """Только то, что есть на этом ПК: файл существует, нужная программа установлена."""
    out = []
    for e in entries:
        if e["kind"] in ("конфиг", "папка") and not os.path.exists(e["path"]):
            continue
        need = AREA_NEEDS.get(e["area"]) or FILE_NEED.get(os.path.basename(e["path"].rstrip("/")))
        if need and not any(have(n) for n in need):
            continue
        out.append(e)
    return out


# Описания файлов без шапки (сверено с кодом 13.10.2026).
DESC = {
    "savage_battery.py": "Батарея в баре и переключатель Savage Mode (щелчок по батарее).",
    "pixel_look.py": "Вид системы: пиксельный, обычный или Minimalistic (капсула) — один переключатель на всё",
    "zen-browser": "Запуск Zen только на Intel (Mesa), чтобы RTX 3050 спала; откат — ссылка на ~/.local/opt/zen/zen",
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
    "jchat": "Свои чаты WhatsApp+Telegram в терминале; демон живёт, пока открыт jchat",
    "start_glyphs.py": "Символы кнопки «Пуск»: ярлык/значок × 8 символов",
    "wa": "Отложенные сообщения WhatsApp: очередь, wa new, wa add, wa app — окно; вход по паролю sudo",
    "tfa": "Второй ключ для Telegram: одноразовый код из приложения на телефоне (tfa setup / status / unlock)",
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
    "clipboard_menu.py": "запасной: старое окно буфера; нужен hyprland-off (Super+Alt+V там) и откат в binds.kdl",
    "calc_menu.sh": "запасной: старый калькулятор на rofi; нужен hyprland-off (Super+C там), в niri — translate_popup.py",
    "battery_mini.py": "его зовёт waybar_niri.py для бара вида Minimalistic",
    "jarvis-rtc-wake.sh": "образец root-хука /usr/lib/systemd/system-sleep/jarvis-rtc-wake (ставится руками через sudo)",
}

# Главные конфиги: (путь, область, что это).
CONFIGS = [
    ("~/.config/niri/config.kdl", "Конфиг niri", "Главный конфиг niri: подключает файлы cfg/*.kdl"),
    ("~/.config/niri/cfg/binds.kdl", "Конфиг niri", "Все клавиши niri (их показывает Super+Z, меняет Настройки → Binds)"),
    ("~/.config/niri/cfg/binds.default.kdl", "Конфиг niri", "Клавиши по умолчанию — к ним сбрасывает Настройки → Binds; niri его не читает"),
    ("~/.config/niri/cfg/autostart.kdl", "Конфиг niri", "Что запускается при входе"),
    ("~/.config/niri/cfg/window-rules.kdl", "Конфиг niri", "Правила окон: размеры, плавающие, прозрачность"),
    ("~/.config/niri/cfg/layer-rules.kdl", "Конфиг niri", "Правила слоёв: бар, плашки, уведомления"),
    ("~/.config/niri/cfg/layout.kdl", "Конфиг niri", "Раскладка: зазоры, рамки, ширина колонок"),
    ("~/.config/niri/cfg/workspaces.kdl", "Конфиг niri", "Именованные столы"),
    ("~/.config/niri/cfg/outputs.kdl", "Конфиг niri", "Мониторы: eDP-1 и MSI"),
    ("~/.config/niri/cfg/input.kdl", "Конфиг niri", "Клавиатура, раскладки, тачпад, мышь"),
    ("~/.config/niri/cfg/animations.kdl", "Конфиг niri", "Анимации niri"),
    ("~/.config/niri/cfg/misc.kdl", "Конфиг niri", "Прочие настройки niri"),
    ("~/.config/niri/cfg/blur.kdl", "Конфиг niri", "Размытие фона"),
    ("~/.config/niri/cfg/window-fx.kdl", "Конфиг niri", "Эффект окон — пишет window_fx.py"),
    ("~/.config/niri/cfg/ws-layout.kdl", "Конфиг niri", "Раскладка по столам — пишет ws_layout.py"),
    ("~/.config/niri/cfg/waybar-blur.kdl", "Бар: устройство", "Размытие под баром — пишет top_bar.py"),
    ("~/.config/niri/cfg/look.kdl", "Стиль системы и шрифты", "Вид Minimalistic: без размытия под капсулой, тонкая белая рамка окон — пишет pixel_look.py"),
    ("~/.config/niri/cfg/rec-binds.kdl", "Снимки и запись экрана", "Клавиши на время записи — пишет rec_area.sh"),
    ("~/.config/niri/dashboard-rules.kdl", "Окна и столы", "Правила окон дашборда — пишет dashboard"),
    ("~/.config/niri/dashboard.json", "Окна и столы", "Где стоят окна дашборда — пишет dashboard save"),
    ("~/.config/waybar/config.jsonc", "Бар: устройство", "Основной конфиг бара: модули и щелчки"),
    ("~/.config/waybar/config-niri.jsonc", "Бар: устройство", "Конфиг бара под niri — собирает waybar_niri.py"),
    ("~/.config/waybar/style.css", "Бар: устройство", "Вид бара (основной)"),
    ("~/.config/waybar/style-niri.css", "Бар: устройство", "Вид бара под niri — собирается из style.css"),
    ("~/.config/waybar/looks", "Бар: устройство", "Заготовки вида бара (bar_style.py); current.* — выбранная"),
    ("~/.config/waybar/rounding.css", "Бар: устройство", "Скругление бара — пишет bar_rounding.py"),
    ("~/.config/waybar/widget-desks.css", "Виджеты и меню рабочего стола", "Вид виджетов-столов — пишет desktop_widgets.py"),
    ("~/.config/hypr/hyprlock.conf", "Блокировка и вход", "Экран блокировки hyprlock"),
    ("~/.config/hypr/hyprlock-astronaut.conf", "Блокировка и вход", "Шаблон экрана блокировки для lock_style.py"),
    ("~/.config/hypr/hypridle.conf", "Простой, сон, заставка", "Простой: приглушение, блокировка, сон (hypridle)"),
    ("~/.config/hypr/ytm-glass.css", "Музыка и тексты песен", "Тема YouTube Music — пишет ytm_colors.py"),
    ("~/.config/hypr/sounds", "Уведомления и звуки интерфейса", "Звуки интерфейса"),
    ("~/.config/hypr/udev", "Питание, вентиляторы, видеокарта", "Правила udev"),
    ("~/.local/share/fonts/Inter", "Стиль системы и шрифты", "Шрифт Inter (OFL) — только часы капсулы в виде Minimalistic"),
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


def editor_cmd(path):
    """Редактор из Настроек → Приложения по умолчанию → «Текстовый редактор» (text/plain).
    Консольный (nvim, Terminal=true) — в kitty. Не выбран или не прочитался — mousepad.
    До 14.10.2026 был всегда mousepad (просьба: открывать в выбранном nvim)."""
    import shlex
    try:
        from gi.repository import Gio
        app = Gio.AppInfo.get_default_for_type("text/plain", False)
        args = [a for a in shlex.split(app.get_commandline() or "")
                if not re.fullmatch(r"%[a-zA-Z]", a)] if app else []
    except Exception:
        app, args = None, []
    if not args:
        return ["mousepad", path]
    if isinstance(app, Gio.DesktopAppInfo) and app.get_boolean("Terminal"):
        return ["kitty", "--directory", os.path.dirname(path), *args, path]
    return [*args, path]


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
    for p, desc, whose in FOLDERS:
        entries.append(dict(name=p, path=ex(p), kind="папка", whose=whose, area=FOLDERS_AREA, desc=desc, text="",
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


# Списки внутри области: (ключ, подпись) — порядок = порядок в окне и в Markdown.
# 14.10.2026: подписано, чьё это — конфиги niri отдельно от конфигов программ, «мои» —
# скрипты и команды staticOS (карта — только про staticOS, не про весь ~/.config).
HEADS = [("конфиг-niri", "Конфиги niri"), ("конфиг", "Конфиги программ"),
         ("dir-niri", "Папки niri"), ("dir-мои", "Мои папки (staticOS)"), ("dir-программы", "Папки программ"),
         ("dir-служебное", "Бэкапы и отложенное"),
         ("скрипт", "Мои скрипты"), ("niri", "Мои скрипты для niri"),
         ("команда", "Мои команды в терминале"), ("manual", "Разовые и запасные"),
         ("hyprland-off", "Файлы Hyprland — отложены")]
HEAD_RANK = {k: i for i, (k, _l) in enumerate(HEADS)}
HEAD_LABEL = dict(HEADS)


def head_of(e):
    if e["name"] in MANUAL:
        return "manual"
    if e["kind"] == "папка":
        return "dir-" + e.get("whose", "мои")
    if e["kind"] == "конфиг" and "/.config/niri/" in e["path"]:
        return "конфиг-niri"
    return e["kind"]


def grouped(entries, order):
    names = [a for a, _ in order] + [OTHER[0]]
    icons = dict(order + [OTHER])
    folder = {f[0]: i for i, f in enumerate(FOLDERS)}
    out = []
    for a in names:
        es = [e for e in entries if e["area"] == a]
        if es:
            es.sort(key=lambda e: (HEAD_RANK.get(head_of(e), 9), folder.get(e["name"], 0), e["name"].lower()))
            out.append((a, icons[a], es))
    return out


def sections(groups):
    """[[раздел, значок, [номера в groups]]] — пустые пропускаются, ничейные — в «Служебное»."""
    idx = {a: i for i, (a, _c, _e) in enumerate(groups)}
    out, used = [], set()
    for name, icon, areas in SECTIONS:
        gi = [idx[a] for a in areas if a in idx]
        used.update(gi)
        if gi:
            out.append([name, icon, gi])
    rest = [i for i in range(len(groups)) if i not in used]
    if rest:
        tail = [s for s in out if s[0] == "Служебное"]
        if tail:
            tail[0][2] += rest
        else:
            out.append(["Служебное", "utilities-system-monitor", rest])
    return out


# ── Markdown ─────────────────────────────────────────────────────────────────

def md(path=None):
    entries, order = scan()
    entries = present(entries)
    path = ex(path or MD_PATH)
    L = ["# Карта staticOS",
         "",
         "Какой файл за что отвечает и как запускается. Собрано `config_map.py md`; "
         "окно с поиском — **Super+Shift+Z**. Руками не править — перезапишется.",
         "",
         "## Папки конфигов", "",
         "| Папка | Что там |", "|---|---|"]
    L[-2:] = ["| Папка | Чья | Что там |", "|---|---|---|"]
    L += ["| `%s` | %s | %s |" % (p, FOLDER_KINDS[w], d) for p, d, w in FOLDERS]
    L.append("")
    orph = [e for e in entries if orphan(e)]
    if orph:
        L += ["## Похоже, не используются", "",
              "Их не зовут ни клавиши, ни бар, ни автозапуск, ни службы, ни другие скрипты. "
              "Перед удалением — проверить.", ""]
        L += ["- `%s` — %s" % (short(e["path"]), e["desc"] or "без описания") for e in orph]
        L.append("")
    L += ["## Оглавление", ""]
    groups = grouped(entries, order)
    secs = [s for s in sections(groups) if s[0] != FOLDERS_AREA]
    by = index(entries)
    anchor = lambda a: re.sub(r"[^\w\- ]", "", a.lower()).replace(" ", "-")
    for name, _icon, gi in secs:
        L.append("- **%s**: " % name + ", ".join("[%s](#%s) — %d" % (groups[i][0], anchor(groups[i][0]),
                                                                     len(groups[i][2])) for i in gi))
    L.append("")
    cell = lambda s: s.replace("|", "\\|")
    for name, _icon, gi in secs:
        L += ["## %s" % name, ""]
        for i in gi:
            a, _c, es = groups[i]
            L += ["### %s" % a, "", "| Файл | Что делает | Как запускается |", "|---|---|---|"]
            for e in es:
                L.append("| `%s` | %s | %s |" % (short(e["path"]), cell(e["desc"]), cell(how(e, by))))
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
    missing += [f[0] for f in FOLDERS if not os.path.isdir(ex(f[0]))]
    areas = [a for a, _, _ in AREAS]
    in_sec = [a for _, _, ns in SECTIONS for a in ns]
    nosec = [a for a in areas if a not in in_sec]
    badsec = [a for a in in_sec if a not in areas and a != OTHER[0]]
    badconf = sorted({a for _, a, _ in CONFIGS if a not in areas})
    known = {e["name"].rstrip("/") for e in entries} | {os.path.basename(e["path"]) for e in entries}
    badneed = sorted(n for n in FILE_NEED if n not in known) + [a for a in AREA_NEEDS if a not in areas]
    print("check: %d записей, %d областей, %d разделов" % (len(entries), len(order), len(SECTIONS)))
    if badneed:
        print("в FILE_NEEDS/AREA_NEEDS неизвестное имя:", " ".join(badneed))
    if other:
        print("без области (допишите в AREAS config_map.py):", " ".join(other))
    if stale:
        print("в AREAS, но файла нет:", " ".join(stale))
    if missing:
        print("в CONFIGS, но нет:", " ".join(missing))
    if twice:
        print("в двух областях сразу:", " ".join(twice))
    if nosec:
        print("область без раздела (допишите в SECTIONS):", "; ".join(nosec))
    if badsec:
        print("в SECTIONS, но такой области нет:", "; ".join(badsec))
    if badconf:
        print("в CONFIGS неизвестная область:", "; ".join(badconf))
    return 1 if other or stale or missing or twice or nosec or badsec or badconf or badneed else 0


# ── кэш ──────────────────────────────────────────────────────────────────────
# scan() читает и разбирает ~430 файлов — 1,3 с. Окно берёт готовый результат из кэша,
# пока ни один источник не менялся (подпись — время и размер каждого файла, ~10 мс).

CACHE = "~/.cache/jarvis/config-map.json"
POS = "~/.cache/jarvis/config-map-pos.json"      # где карта стояла при закрытии


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
    "Обои": ("preferences-desktop-wallpaper", "Смена обоев: Super+W, размытие, пиксельные обои"),
    "Цвета по обоям": ("preferences-desktop-color", "Раскраска всего под обои: терминал, GTK, KDE, папки"),
    "Стиль системы и шрифты": ("preferences-desktop-theme-global", "Default/Skeet/Beta, пиксельный вид, шрифты"),
    "Курсор": ("preferences-desktop-cursors", "Свой курсор в цветах обоев"),
    "Уведомления и звуки интерфейса": ("preferences-desktop-notification-bell", "Вид уведомлений, «не беспокоить», щелчки"),
    "Бар: устройство": ("preferences-desktop", "Как бар запускается и выглядит: режимы, мониторы, рамка, конфиги"),
    "Бар: модули": ("preferences-desktop-display", "Что внутри бара: часы, столы, музыка, батарея, кошка"),
    "Бар: шрифты значков": ("preferences-desktop-font", "Сборка шрифтов со значками бара — руками, редко"),
    "Плашки бара": ("preferences-system-windows-actions", "Окошки по щелчку на модули бара"),
    "Нижняя панель, док, «Пуск»": ("start-here-kde-plasma", "XP-панель снизу, док и меню «Пуск»"),
    "Виджеты и меню рабочего стола": ("preferences-desktop-activities", "Окна-виджеты на обоях и меню ПКМ"),
    "Конфиг niri": ("preferences-system-windows", "Файлы *.kdl: клавиши, правила окон, мониторы, автозапуск"),
    "Окна и столы": ("view-grid", "Alt+Tab, ширина колонок, раскладки, дашборд"),
    "Настройки и справка": ("systemsettings", "Окно Настроек, Super+Z, эта карта"),
    "Блокировка и вход": ("system-lock-screen", "Экран блокировки и экран входа"),
    "Простой, сон, заставка": ("preferences-system-power-management", "Что делать, когда не трогаешь ПК: затемнить, заблокировать, усыпить"),
    "Яркость и ночной свет": ("preferences-desktop-display-color", "Яркость мониторов, гамма, ночной режим"),
    "Звук и микрофон": ("preferences-desktop-sound", "Громкость программ, микрофон, починка звука"),
    "Музыка и тексты песен": ("yandexmusic", "Яндекс Музыка, YouTube Music, караоке-тексты"),
    "Подсветка Razer": ("input-keyboard", "Подсветка клавиатуры в цветах обоев"),
    "Питание, вентиляторы, видеокарта": ("battery", "Режимы питания, вентиляторы, сон RTX"),
    "Браузер и мессенджеры": ("zen-browser", "Zen, Discord, Telegram — под стиль системы"),
    "Терминал kitty": ("kitty", "Шейдеры, шрифт, общая копия kitty"),
    "Steam и игры": ("steam", "Тема Steam, сторож игр, буфер для gamescope"),
    "Другие программы": ("preferences-desktop-default-applications", "KeePassXC, VS Code, Obsidian, LibreOffice, блокнот"),
    "Часы и таймеры в терминале": ("org.gnome.clocks", "tclock, jclock, обратный отсчёт"),
    "fetch и забавы в терминале": ("utilities-terminal", "fetch, матрица, крупные надписи, hollywood"),
    "Тетрис и тренажёр набора": ("preferences-desktop-gaming", "jtetris и jtype"),
    "Калькулятор и перевод": ("org.speedcrunch.SpeedCrunch", "Super+C: калькулятор, тенге, перевод"),
    "Буфер обмена": ("jarvis-clipboard", "Окно буфера, история, мост X11 ⇄ Wayland"),
    "Снимки и запись экрана": ("applets-screenshooter", "Снимки, заморозка, Recorder, распознавание текста"),
    "Запуск программ": ("rofi", "Super+X, Super+Space, веб-приложения"),
    "Экранное время и нагрузка": ("utilities-system-monitor", "Сколько сидишь в программах и кто сколько ест"),
    "Discipline и hub": ("jarvis-discipline", "Фокус, помидор, напоминания, словарь"),
    "Будильник": ("org.gnome.clocks", "Будильник режима сна и пробуждение по RTC"),
    "Самопроверка и сторожа": ("utilities-system-monitor", "staticos-doctor, сторожа в одном процессе"),
    "Сторонние программы": ("package-x-generic", "Чужие программы в ~/.local/bin"),
    "Hyprland — не используется": ("dialog-cancel", "Отложено: ~/.config/hyprland-off"),
    "Папки конфигов": ("folder", "Где что лежит: Enter — открыть папку"),
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
             "state": "folder-script", "udev": "folder-script", "looks": "folder-templates",
             "scripts": "folder-script", "bin": "folder-script", "hyprland-off": "folder-locked",
             "share/hub": "folder-documents", "waybar": "folder-templates", "cfg": "folder-script"}


def icon_for(e):
    n, p = e["name"], e["path"]
    base = AREA_INFO.get(e["area"], AREA_INFO["Прочее"])[0]
    if e["kind"] in ("конфиг", "папка"):
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
# (state/settings-skin), те же цвета, рамки и крестик. Три уровня (14.10.2026, просьба
# «максимально упростить»): разделы списком (значок и заголовок) → области → файлы
# списками «Конфиги / Скрипты / Команды…». Раздел с одной областью — сразу файлы.

W, H = 600, 740                # было 1060×800 → 900 → 700 → 600×740 (14.10.2026, «меньше, больше по горизонтали»)
TITLE = "Config.exe"
ANIM_MS = 130
ROW_A, ROW_F = 44, 30          # строка области и строка файла
ROW_S = 50                     # строка раздела: список, как Super+X (плитки отменены 14.10.2026)
TOOL_H = 22                    # было 30 → 26 → 22 (14.10.2026, «кнопки поменьше»)
BTN_PAD = 6                    # поле слева/справа от подписи кнопки (было 10)
DETAIL_H = 136                 # +строка кнопок; было 168 (14.10.2026, «чуть компактнее»)
STATUS_H = 28
CONFIG_DIR = "~/.config"       # кнопка-папка в строке кнопок
MAP_BMP = ("#.##..##", "##..##.#", "#.##..##", "##..##.#", "#.##..##", "##..##.#", "#.##..##")
# 14.10.2026: «Назад» — значок-стрелка, «Открыть» убрана (щелчок по строке и так открывает),
# «В папке» и «Путь» — полными именами внизу, в карточке файла.
BUTTONS = [("dir", "Открыть в папке"), ("copy", "Копировать путь")]
TOP_H = 38                     # строка сверху: «назад», папка, поиск (14.10.2026, «увеличь ещё больше»)
ICON_W = 50                    # ширина кнопок-значков «назад» и ~/.config
BACK_BMP = ("...#....", "..##....", ".#######", "########", ".#######", "..##....", "...#....")
HINT_PX = 12
CLEAR_BMP = ("#.....#", ".#...#.", "..#.#..", "...#...", "..#.#..", ".#...#.", "#.....#")   # крестик очистки поиска                   # подсказки в строке статуса — мельче основного (16)


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
            self.set_data(entries, order)
            self.level, self.sec, self.area, self.sel, self.scroll = 0, 0, 0, 0, 0
            self.saved0 = self.saved1 = 0           # где стоял выбор на уровнях выше
            self.direct = False                     # раздел из одной области: файлы сразу
            self.mode, self.buf = "normal", ""
            self.max_vis = 10
            self.anim = None
            self.hover = None                       # строка, плитка или кнопка под мышью
            self.flash = None                       # (текст, время) — «путь скопирован»
            self.win = None
            th = Gtk.IconTheme.new()
            try:
                th.set_custom_theme(Gio.Settings.new("org.gnome.desktop.interface").get_string("icon-theme"))
            except Exception:
                pass
            self.theme, self.pix = th, {}

        # ── данные ─────────────────────────────────────────────────────────
        def set_data(self, entries, order):
            entries = present(entries)              # чего нет на ПК — не показывать
            self.by = index(entries)
            self.groups = grouped(entries, order)
            self.secs = sections(self.groups)
            self.items = [e for _a, _i, es in self.groups for e in es]
            self._rows_key = None

        def rows(self):
            """Что сейчас в списке: ("sec", i) | ("area", i) | ("head", подпись) | ("item", e)."""
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
                return [("sec", i) for i in range(len(self.secs))]
            if self.level == 1:
                return [("area", i) for i in self.secs[self.sec][2]]
            out, last = [], None
            for e in self.groups[self.area][2]:
                h = head_of(e)
                if h != last:
                    out.append(("head", HEAD_LABEL.get(h, h)))
                    last = h
                out.append(("item", e))
            return out

        def reload(self, entries, order):
            """Свежий разбор из фона: подменить данные, выбор оставить на месте."""
            self.set_data(entries, order)
            self.sec = min(self.sec, max(0, len(self.secs) - 1))
            self.area = min(self.area, max(0, len(self.groups) - 1))
            self.sel = min(self.sel, max(0, len(self.rows()) - 1))
            self.redraw()

        def current(self):
            rows = self.rows()
            if rows and 0 <= self.sel < len(rows):
                return rows[self.sel]
            return None

        def row_h(self):
            return ROW_F if self.buf or self.level == 2 else ROW_S if self.level == 0 else ROW_A

        def crumbs(self):
            if self.buf:
                return ["Поиск"]
            if self.level == 0:
                return []
            out = [self.secs[self.sec][0]]
            if self.level == 2 and not self.direct:
                out.append(self.groups[self.area][0])
            return out

        def title_text(self):
            return "".join([TITLE] + [" » " + c for c in self.crumbs()])

        # ── переходы ───────────────────────────────────────────────────────
        def snapshot(self):
            return (self.rows(), self.sel, self.scroll, self.row_h())

        def start_anim(self, d, old):
            self.anim = (time.monotonic(), d) + old
            self.redraw()

        def first_item(self):
            rows = self.rows()
            return next((i for i, r in enumerate(rows) if r[0] != "head"), 0)

        def enter_sec(self, i):
            old = self.snapshot()
            self.saved0, self.sec, self.sel, self.scroll = i, i, 0, 0
            gi = self.secs[i][2]
            self.direct = len(gi) == 1
            if self.direct:
                self.level, self.area = 2, gi[0]
                self.sel = self.first_item()
            else:
                self.level = 1
            self.start_anim(1, old)

        def enter_area(self, row):
            old = self.snapshot()
            self.saved1 = row
            self.level, self.area, self.scroll = 2, self.rows()[row][1], 0
            self.sel = self.first_item()
            self.start_anim(1, old)

        def goto_area(self, name):
            """Сразу к файлам области (для --shot --area)."""
            names = [a for a, _i, _e in self.groups]
            gi = names.index(name) if name in names else int(name)
            for si, (_n, _ic, ids) in enumerate(self.secs):
                if gi in ids:
                    self.enter_sec(si)
                    if not self.direct:
                        self.enter_area(ids.index(gi))
                    return

        def restore_sel(self):
            self.sel, self.scroll = 0, 0
            if self.level == 0:
                self.sel = self.saved0
            elif self.level == 1:
                self.sel = self.saved1
            else:
                self.sel = self.first_item()

        def back(self):
            if self.buf:
                self.buf, self.mode = "", "normal"
                self.restore_sel()
                self.redraw()
            elif self.level == 2 and not self.direct:
                old = self.snapshot()
                self.level, self.sel, self.scroll = 1, self.saved1, 0
                self.start_anim(-1, old)
            elif self.level:
                old = self.snapshot()
                self.level, self.sel, self.scroll, self.direct = 0, self.saved0, 0, False
                self.start_anim(-1, old)
            else:
                self.close()

        def activate(self):
            r = self.current()
            if not r:
                return
            if r[0] == "sec":
                self.enter_sec(r[1])
            elif r[0] == "area":
                self.enter_area(self.sel)
            elif r[0] == "item":
                self.open_file(r[1])

        def open_file(self, e):
            if os.path.isdir(e["path"]):
                self.open_dir(e)
                return
            self.spawn(*editor_cmd(os.path.realpath(e["path"])))
            self.close()

        def open_dir(self, e):
            self.open_path(e["path"])

        def here_dir(self):
            """Папка для кнопки-папки и «c» — по тому, что открыто (14.10.2026, «пусть папка
            смотрит, какая категория открыта»): в главном меню и поиске — ~/.config, в разделе
            и области — папка, где лежит больше всего их файлов (отложенный Hyprland не в счёт)."""
            if self.buf or self.level == 0:
                return CONFIG_DIR
            if self.level == 2:
                if self.groups[self.area][0] == "Папки конфигов":
                    return CONFIG_DIR
                es = self.groups[self.area][2]
            else:
                es = [e for i in self.secs[self.sec][2] for e in self.groups[i][2]]
                es = [e for e in es if e["kind"] != "hyprland-off"] or es
            from collections import Counter
            dirs = Counter(os.path.dirname(os.path.realpath(e["path"])) for e in es)
            return dirs.most_common(1)[0][0] if dirs else CONFIG_DIR

        def open_path(self, p):
            """Папка — в Dolphin (Super+E), файл в ней выделен. Не xdg-open: папки по
            mimeapps открывает `kitty +open`, и окно не появлялось (13.10.2026)."""
            import shutil
            p = os.path.realpath(ex(p))
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
            elif key == "dir" and e:
                self.open_dir(e)
            elif key == "copy" and e:
                self.copy(e)
            elif key == "cfg":
                self.open_path(self.here_dir())
            elif key == "clear":
                self.buf, self.mode = "", "search"
                self.restore_sel()
                self.redraw()
            elif key == "search":
                self.mode = "search"
                self.redraw()
            elif key == "close":
                self.close()

        def move(self, d, to=None):
            """Сдвиг выбора; подписи списков («Скрипты») пропускаются."""
            rows = self.rows()
            n = len(rows)
            if not n:
                return
            s = max(0, min(n - 1, to if to is not None else self.sel + d))
            step = (1 if s == 0 else -1) if to is not None else (1 if d >= 0 else -1)
            while 0 <= s < n and rows[s][0] == "head":
                s += step
            if not 0 <= s < n:
                s = self.sel
            self.sel = s
            self.redraw()

        def spawn(self, *cmd):
            if self.test:
                return
            subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)

        # Где стояла карта — запомнить при закрытии и вернуть при открытии (14.10.2026:
        # «захожу в файл — меню закрывается… а обратно приходится заново искать»).
        def save_pos(self):
            d = {k: getattr(self, k) for k in ("level", "sec", "area", "sel", "scroll",
                                                "saved0", "saved1", "direct", "buf")}
            try:
                os.makedirs(os.path.dirname(ex(POS)), exist_ok=True)
                with open(ex(POS), "w") as f:
                    json.dump(d, f, ensure_ascii=False)
            except OSError:
                pass

        def load_pos(self):
            try:
                with open(ex(POS)) as f:
                    d = json.load(f)
                lv, sec, area = int(d["level"]), int(d["sec"]), int(d["area"])
                if not (0 <= lv <= 2 and 0 <= sec < len(self.secs)
                        and 0 <= area < len(self.groups)):
                    return
                if lv and area not in self.secs[sec][2] and lv == 2:
                    return
                self.level, self.sec, self.area = lv, sec, area
                self.direct = bool(d.get("direct")) and lv == 2
                self.saved0 = min(int(d.get("saved0", 0)), max(0, len(self.secs) - 1))
                self.saved1 = int(d.get("saved1", 0))
                self.buf = str(d.get("buf") or "")
                self.mode = "normal"
                n = len(self.rows())
                self.sel = min(max(0, int(d.get("sel", 0))), max(0, n - 1))
                if self.current() and self.current()[0] == "head":
                    self.sel = self.first_item()
                self.scroll = min(max(0, int(d.get("scroll", 0))), self.sel)
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                pass

        def close(self):
            if self.test:
                return
            self.save_pos()
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
            return x0, self.SW - x0, G["TOP"] + G["TB"] + 10

        def tool_zones(self, cr=None):
            """[(ключ, x, y, w, h)] — кнопки, кнопка-папка ~/.config и поле поиска."""
            x0, x1, y = self.box()
            # от края до края рамки списка, без пустот по бокам (14.10.2026, «убери пустоты»)
            o = 10 if self.style == "skeet" else 1
            x0, x1 = x0 - o, x1 + o
            out, x = [], x0
            for key in ("back", "cfg"):
                out.append((key, x, y, ICON_W, TOP_H))
                x += ICON_W + 6
            if self.buf:                           # крестик очистки — справа в поле (14.10.2026)
                out.append(("clear", x1 - TOP_H, y, TOP_H, TOP_H))
            out.append(("search", x, y, x1 - x, TOP_H))
            return out

        def file_zones(self):
            """[(ключ, x, y, w, h)] — «Открыть в папке» и «Копировать путь» внизу карточки
            файла; пусто, если карточки нет или выбран не файл."""
            r = self.current()
            if not (r and r[0] == "item") or (self.level == 0 and not self.buf):
                return []
            lx, top, lw, lh = self.list_rect()
            out, x = [], lx + 4
            y = top + lh + 10 + DETAIL_H - TOOL_H - 2
            for key, label in BUTTONS:
                w = 2 * BTN_PAD + self.text_w(label)
                out.append((key, x, y, w, TOOL_H))
                x += w + 6
            return out

        def list_rect(self):
            x0, x1, y = self.box()
            # подпись группы skeet не липнет к кнопкам (14.10.2026, «добавь пространства»)
            top = y + TOP_H + (24 if self.style == "skeet" else 12)   # «чуть меньше пространства»
            detail = 0 if self.level == 0 and not self.buf else DETAIL_H + 10
            bottom = self.SH - self.G["BORDER"] - 10 - STATUS_H - detail
            return x0, top, x1 - x0, bottom - top

        def font(self, px=None, bold=False):
            fd = self.fd.copy()
            if px:
                fd.set_absolute_size(px * Pango.SCALE)
            if bold:
                fd.set_weight(Pango.Weight.BOLD)
            return fd

        def text_w(self, s, px=None, bold=False):
            cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
            cr.set_font_options(self.fo)
            lay = self.layout(cr, s)
            if px or bold:
                lay.set_font_description(self.font(px, bold))
            return lay.get_pixel_size()[0]

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
            Gdk.cairo_set_source_pixbuf(cr, pb, int(x), int(y))
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint()
            cr.restore()

        # ── рисование ──────────────────────────────────────────────────────
        def txt(self, cr, s, x, y, color, width=None, bold=False, lines=1, px=None):
            lay = self.layout(cr, s, width)
            if bold or px:
                lay.set_font_description(self.font(px, bold))
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
            # в корне подписи нет: «Разделы» и так понятно (14.10.2026, просьба)
            self.group(cr, lx, top, lw, lh, "  ›  ".join(self.crumbs()))
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
            if self.level or self.buf:
                self.detail(cr, lx, top + lh + 10, lw, DETAIL_H)
                self.file_buttons(cr)
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
            for key, x, y, w, h in self.tool_zones():
                hov = self.hover == ("btn", key)
                if key == "clear":
                    continue                                       # рисуется поверх поля, ниже
                if key == "search":
                    on = self.mode == "search"
                    self.rect_fill(cr, x, y, w, h, C.get("field") or mix(C["win_bg"], (0, 0, 0), 0.25))
                    self.rect_line(cr, x, y, w, h, self.acc if on or hov else self.soft)
                    ty = y + (h - self.LH) // 2 + 1
                    if self.buf or on:
                        tw = self.txt(cr, self.buf, x + 10, ty, C["text"],
                                      w - 24 - (h if self.buf else 0))[0]
                        if on:
                            self.rect_fill(cr, x + 10 + tw + 1, y + 5, 2, h - 10, self.acc)
                    if self.buf:
                        ink = self.acc if self.hover == ("btn", "clear") else self.faint
                        k = 3 if h >= 36 else 2
                        bx, by = x + w - h + (h - 7 * k) // 2, y + (h - 7 * k) // 2
                        for j, row in enumerate(CLEAR_BMP):
                            for i, ch in enumerate(row):
                                if ch == "#":
                                    self.rect_fill(cr, bx + i * k, by + j * k, k, k, ink)
                    else:
                        self.txt(cr, "/  Поиск: курсор, бар…", x + 10, ty, self.faint, w - 20)
                    continue
                if key == "cfg":
                    self.btn_box(cr, x, y, w, h, hov)
                    self.draw_icon(cr, "folder", x + (w - 32) // 2, y + (h - 32) // 2, 32)
                    continue
                off = self.level == 0 and not self.buf             # «назад» некуда
                self.btn_box(cr, x, y, w, h, hov and not off)
                ink = C["on_surface"] if self.style == "default" else C["text"]
                if off:
                    ink = mix(ink, C["win_bg"], 0.55)
                k = 4 if h >= 36 else 3 if h >= 28 else 2            # стрелка 8×7 клеток по k px
                bx, by = x + (w - 8 * k) // 2, y + (h - 7 * k) // 2
                for j, row in enumerate(BACK_BMP):
                    for i, ch in enumerate(row):
                        if ch == "#":
                            self.rect_fill(cr, bx + i * k, by + j * k, k, k, ink)

        def file_buttons(self, cr):
            C = self.C
            ink = C["on_surface"] if self.style == "default" else C["text"]
            for key, x, y, w, h in self.file_zones():
                self.btn_box(cr, x, y, w, h, self.hover == ("btn", key))
                self.txt(cr, dict(BUTTONS)[key], x + BTN_PAD, y + (h - self.LH) // 2 + 1, ink)

        def group(self, cr, x, y, w, h, label):
            """Подложка списка: skeet — группа с подписью, beta — карточка, XP — рамка."""
            C = self.C
            if self.style == "skeet":
                gx, gy, gw, gh = x - 10, y - 12, w + 20, h + 20
                self.rect_line(cr, gx, gy, gw, gh, C["gline"])
                self.rect_line(cr, gx + 1, gy + 1, gw - 2, gh - 2, C["gdark"])
                if not label:
                    return
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

        def tile_bg(self, cr, x, y, w, h, on, hov):
            C, st = self.C, self.style
            if on:
                self.rect_fill(cr, x, y, w, h, C["sel_bg"])
                if st == "skeet":
                    self.rect_line(cr, x, y, w, h, C["gline"])
                if st != "default":
                    self.rect_fill(cr, x, y, 3, h, self.acc)
            elif hov:
                self.rect_fill(cr, x, y, w, h, C["text"], 0.07)
            elif st == "default":
                self.rect_fill(cr, x, y, w, h, C["row"], 0.045)

        def draw_list(self, cr, rows, sel, x, top, w, h, R_, live):
            C = self.C
            vis = max(1, h // R_)
            if live:
                self.max_vis = vis
            if not rows:
                if live:
                    self.txt(cr, "Ничего не найдено. Попробуйте другое слово.", x + 16, top + 10, self.faint)
                return
            sel = max(0, min(sel, len(rows) - 1))
            off = min(self.scroll, sel - 1 if sel and rows[sel - 1][0] == "head" else sel)   # подпись — видна
            if sel >= off + vis:
                off = sel - vis + 1
            off = max(0, min(off, len(rows) - vis))
            if live:
                self.sel, self.scroll = sel, off
            for i in range(off, min(off + vis, len(rows))):
                y = top + (i - off) * R_
                r = rows[i]
                ry, rh = y + 1, R_ - 2
                ty = ry + (rh - self.LH) // 2 + 1
                if r[0] == "head":
                    lab = r[1].upper() if self.style != "default" else r[1]
                    tw = self.txt(cr, lab, x + 10, ty + 2, self.acc if self.style != "default" else C["primary"])[0]
                    self.rect_fill(cr, x + 20 + tw, ry + rh // 2 + 2, w - 30 - tw, 1, self.soft)
                    continue
                on = i == sel
                self.tile_bg(cr, x, ry, w, rh, on, live and self.hover == ("row", i) and not on)
                fg = C["sel_text"] if on else C["text"]
                dim = C["sel_text"] if on else C["dim"]
                if r[0] == "sec":                   # раздел: крупный значок и заголовок
                    name, icon, _gi = self.secs[r[1]]
                    self.draw_icon(cr, icon, x + 12, ry + (rh - 32) // 2, 32)
                    self.txt(cr, name, x + 60, ty, fg, w - 60 - 40, bold=True)
                    cr.set_source_rgb(*(C["sel_text"] if on else C["arrow"]))
                    R.draw_bitmap(cr, R.ARROW_BMP, x + w - 22, ry + (rh - 14) // 2, 2)
                elif r[0] == "area":
                    a, _ch, es = self.groups[r[1]]
                    icon = AREA_INFO.get(a, AREA_INFO["Прочее"])[0]
                    self.draw_icon(cr, icon, x + 10, ry + (rh - 32) // 2, 32)
                    self.txt(cr, a, x + 54, ty, fg, w - 54 - 90, bold=True)
                    self.txt(cr, str(len(es)), x + w - 58, ty, dim)
                    cr.set_source_rgb(*(C["sel_text"] if on else C["arrow"]))
                    R.draw_bitmap(cr, R.ARROW_BMP, x + w - 22, ry + (rh - 14) // 2, 2)
                else:
                    e = r[1]
                    self.draw_icon(cr, icon_for(e), x + 10, ry + (rh - 24) // 2, 24)
                    nm = "$ " + e["name"] if e["kind"] == "команда" else \
                        os.path.basename(e["path"]) if e["kind"] == "конфиг" else e["name"]   # путь — в карточке
                    col = self.faint if e["kind"] == "hyprland-off" and not on else fg
                    nw = 330 if e["kind"] == "папка" else 270
                    self.txt(cr, nm, x + 44, ty, col, nw - 54)
                    mark = "⚠ " if orphan(e) else ""
                    self.txt(cr, mark + (e["desc"] or "—"), x + nw, ty, dim, w - nw - 10)
            if len(rows) > vis and live:
                bh = max(14, h * vis / len(rows))
                by = top + (h - bh) * off / max(1, len(rows) - vis)
                self.rect_fill(cr, x + w - 3, by, 3, bh, self.faint)

        def detail(self, cr, x, y, w, h):
            C = self.C
            self.rect_fill(cr, x, y, w, 1, self.soft)
            r = self.current()
            if not r or r[0] in ("head", "sec"):
                return
            big = 64
            ix = x + w - big - 12
            iy = y + max(8, (h - TOOL_H - 4 - big) // 2)       # по середине над кнопками
            if r[0] == "area":
                a, _ch, es = self.groups[r[1]]
                icon, desc = AREA_INFO.get(a, AREA_INFO["Прочее"])
                nconf = sum(1 for e in es if e["kind"] == "конфиг")
                norph = sum(1 for e in es if orphan(e))
                stat = "%d файлов" % len(es) + (" · %d конфигов" % nconf if nconf else "") + \
                       (" · ⚠ %d без вызова" % norph if norph else "")
                lines = [(None, a), ("Что здесь", desc), ("Всего", stat),
                         ("Например", ", ".join(e["name"] for e in es[:6]) + ("…" if len(es) > 6 else ""))]
            elif r[1]["kind"] == "папка":
                e = r[1]
                icon = icon_for(e)
                try:
                    n = len([f for f in os.listdir(e["path"]) if f not in SKIP])
                except OSError:
                    n = 0
                lines = [(None, e["desc"]), ("Папка", e["name"]), ("Внутри", "%d файлов и папок" % n),
                         ("Открыть", "Enter или двойной щелчок — в Dolphin")]
            else:
                e = r[1]
                icon = icon_for(e)
                sec = next((s[0] for s in self.secs if any(self.groups[i][0] == e["area"] for i in s[2])), "")
                lines = [(None, e["desc"] or e["name"]),
                         ("Файл", short(e["path"])),
                         ("В карте", "  ›  ".join(x for x in (sec, e["area"]) if x)),
                         ("Запуск", how(e, self.by) or ("никто не вызывает — кандидат на чистку"
                                                       if orphan(e) else "—")),
                         ("Упоминают", ", ".join(e["refs"]) or "—")]
            self.rect_fill(cr, ix - 8, iy - 8, big + 16, big + 16, self.field)
            self.rect_line(cr, ix - 8, iy - 8, big + 16, big + 16, self.soft)
            self.draw_icon(cr, icon, ix, iy, big)
            ty, tw = y + 6, ix - 8 - x - 16
            for k, v in lines:
                if k is None:
                    self.txt(cr, v, x + 4, ty, self.acc if self.style != "default" else C["primary"], tw, bold=True)
                    ty += self.LH + 2
                    continue
                self.txt(cr, k, x + 4, ty, self.faint)
                self.txt(cr, v, x + 136, ty, C["text"], tw - 132)
                ty += self.LH

        def status(self, cr, x, y, w):
            C = self.C
            self.rect_fill(cr, x, y - 4, w, 1, self.soft)
            badge = "SEARCH" if self.mode == "search" else "NORMAL"
            bw = self.text_w(badge) + 14
            self.rect_fill(cr, x, y, bw, 22, self.field)
            self.txt(cr, badge, x + 7, y + (22 - self.LH) // 2 + 1, self.acc)
            tip = {"back": "h, Esc — назад", "dir": "o — показать файл в папке",
                   "copy": "y — скопировать путь", "clear": "Ctrl+U — стереть поиск", "cfg": "c — открыть папку " + short(self.here_dir())}
            if self.flash and time.monotonic() - self.flash[1] < 1.5:
                hint = self.flash[0]
            elif self.hover and self.hover[0] == "btn" and self.hover[1] in tip:
                hint = tip[self.hover[1]]
            elif self.mode == "search":
                hint = "печатайте · ↑↓ выбор · Enter — к списку · Esc — сброс"
            elif self.level == 0 and not self.buf:
                hint = "j/k · Enter войти · / поиск · c ~/.config · q выход"
            elif self.level == 1 and not self.buf:
                hint = "l/Enter войти · h назад · / поиск · c папка · q выход"
            else:
                hint = "Enter открыть · h назад · o в папке · y путь"
            cnt = "%d файлов" % len(self.items)
            cw = self.text_w(cnt, px=HINT_PX)
            hy = y + (22 - HINT_PX) // 2
            self.txt(cr, hint, x + bw + 10, hy, self.faint, w - bw - 10 - cw - 16, px=HINT_PX)
            self.txt(cr, cnt, x + w - cw, hy, self.faint, px=HINT_PX)

        # ── мышь ───────────────────────────────────────────────────────────
        def zone_at(self, x, y):
            cx, cy, cw, ch = self.cap_zone()
            if cx <= x < cx + cw and cy <= y < cy + ch:
                return ("btn", "close")
            G = self.G
            if y < G["TOP"] + G["TB"]:
                return ("title", None)
            for key, bx, by, bw, bh in self.tool_zones() + self.file_zones():
                if bx <= x < bx + bw and by <= y < by + bh:
                    return ("btn", key)
            lx, top, lw, lh = self.list_rect()
            if not (lx <= x < lx + lw and top <= y < top + lh):
                return None
            rows = self.rows()
            i = self.scroll + int((y - top) // self.row_h())
            if i < len(rows) and rows[i][0] != "head":
                return ("row", i)
            return None

        def click(self, z, double=False):
            if not z:
                return
            kind, v = z
            if kind == "btn":
                self.button(v)
            elif kind == "row":
                r = self.rows()[v]
                self.sel = v
                if r[0] == "sec":
                    self.enter_sec(r[1])
                elif r[0] == "area":
                    self.enter_area(v)
                elif double:
                    self.open_file(r[1])
                else:
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
                        self.buf = ""
                        self.restore_sel()
                    self.mode = "normal"
                elif name in ("Return", "KP_Enter"):
                    self.mode, self.sel = "normal", 0
                elif name in ("Down", "Up") or (ctrl and ch in ("j", "k", "n", "p")):
                    self.move(1 if name == "Down" or ch in ("j", "n") else -1)
                elif ctrl and ch == "u":                 # стереть всё, как крестик в поле
                    self.buf = ""
                    self.restore_sel()
                elif name == "BackSpace":
                    self.buf = self.buf[:-1]
                    self.sel = self.scroll = 0
                    if not self.buf:
                        self.restore_sel()
                elif uni and uni.isprintable() and len(self.buf) < 60:
                    self.buf += uni
                    self.sel = self.scroll = 0
                self.redraw()
                return
            r = self.current()
            e = r[1] if r and r[0] == "item" else None
            if ch == "q" and not ctrl:
                self.close()
            elif self.level == 0 and not self.buf and (ch == "h" or name == "Left"):
                pass                                # выше разделов идти некуда (Esc — закрыть)
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
            elif ch == "c":
                self.open_path(self.here_dir())
            elif ch == "o" and e:
                self.open_dir(e)
            elif ch == "y" and e:
                self.copy(e)

    return View


def shot(path, query="", area=None, sel=0, style=None, section=None):
    v = make_view(test=True, style=style)()
    if section is not None:
        names = [s[0] for s in v.secs]
        v.enter_sec(names.index(section) if section in names else int(section))
    if area is not None:
        v.goto_area(area)
    if sel or v.level != 2:
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
    v.load_pos()
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
            # Слой, как до 14.10.2026: окном (чтобы таскать) пользователь не захотел — «лучше как
            # было… если это заблокирует перемещение, тогда без перемещения». Слой не двигается.
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

    # щелчок мимо карты — закрыть (14.10.2026, «должна закрываться, если кликнуть в любое
    # место кроме окна карты»), и затемнение за ней, как у Super+X (14.10.2026) —
    # scrim_layer: слои во весь каждый монитор под картой, тёмный — на мониторе карты
    from scrim_layer import cover
    w = Win()
    v.win = w
    cover(w, "jarvis-config-map-catch", v.close)
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
            if x in ("--area", "--section", "--query", "--sel", "--style"):
                opts[x[2:]] = next(it, "")
            else:
                rest.append(x)
        shot(rest[0] if rest else "/tmp/config_map.png",
             opts.get("query") or (rest[1] if len(rest) > 1 else ""),
             opts.get("area"), int(opts.get("sel", 0)), opts.get("style"), opts.get("section"))
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
        from menu_one import close_others           # другое меню открыто — закрыть (14.10.2026)
        close_others(__file__)
        window()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
