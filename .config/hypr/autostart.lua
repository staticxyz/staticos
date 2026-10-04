-------------------
---- AUTOSTART ----
-------------------

hl.on("hyprland.start", function ()
    -- Обзор столов (SUPER+G): загрузка плагина плюс его настройки, строго в
    -- таком порядке. Почему скриптом, а не из конфига — в его же шапке.
    -- Автоматически float для новых окон Keypunch
    os.execute("lua ~/.config/hypr/scripts/keypunch_float.lua &")

    -- 1. Панель Waybar
    hl.exec_cmd("sh -c 'exec waybar >/dev/null 2>&1'")

    -- 2. Уведомления и демоны
    hl.exec_cmd("swaync")
    hl.exec_cmd("hypridle")
    -- Ночной режим по расписанию (22:00–5:00, ~/.config/hypr/hyprsunset.conf)
    -- и приглушение перед блокировкой (гамма, из hypridle).
    hl.exec_cmd("hyprsunset")
    hl.exec_cmd("gnome-keyring-daemon --start --components=secrets,pkcs11,ssh")

    -- Демон, помнящий последний активный плеер. Без него медиаклавиши при
    -- всех приостановленных плеерах выбирали произвольный — по алфавиту,
    -- то есть всегда Chromium, даже если музыка была в другом браузере.
    hl.exec_cmd("playerctld daemon")

    -- Гашение подсветки клавиатуры по бездействию ИМЕННО клавиш ноутбука.
    -- Не через hypridle: тот следит за вводом вообще, и подсветка загоралась
    -- бы от мыши и внешней клавиатуры.
    hl.exec_cmd("$HOME/.config/hypr/scripts/kbdlight_watch")

    -- Подсказка о смене раскладки, как в KDE. Событие activelayout приходит
    -- на каждое устройство ввода, поэтому скрипт схлопывает повторы.
    hl.exec_cmd("$HOME/.config/hypr/scripts/layout_osd")

    -- Буфер обмена
    hl.exec_cmd("wl-paste --type text --watch cliphist store")
    hl.exec_cmd("wl-paste --type image --watch cliphist store")

    -- 3. Демон обоев и восстановление картинки
    hl.exec_cmd("awww-daemon")
    hl.exec_cmd("waypaper --restore")

    -- Курсор: применить текущий и следить за сменой в nwg-look.
    -- Обе строки жили здесь напрямую, но первая не работала из-за кавычек —
    -- см. пояснение в самом скрипте.
    hl.exec_cmd("$HOME/.config/hypr/scripts/cursor_watch")

    -- Порядок столов в баре. Метки-подписи живут только в памяти Hyprland и
    -- после перезапуска пропадают — watch проставляет их при старте, а дальше
    -- следит за появлением новых столов, чтобы те не оставались без метки.
    hl.exec_cmd("python3 $HOME/.config/hypr/scripts/ws_order.py watch")

    -- 4. Виджеты Eww
    -- Большие часы (clock0/clock1) отключены по просьбе — верни, раскомментировав.
    -- hl.exec_cmd("eww daemon && eww open-many clock0 clock1")
    hl.exec_cmd("eww daemon")
    hl.exec_cmd("eww open volume-trigger")
end)
