--------------------------------
---- WINDOWS AND WORKSPACES ----
--------------------------------

local suppressMaximizeRule = hl.window_rule({
    -- Ignore maximize requests from all apps. You'll probably like this.
    name  = "suppress-maximize-events",
    match = { class = ".*" },

    suppress_event = "maximize",
})
-- suppressMaximizeRule:set_enabled(false)

hl.window_rule({
    -- Fix some dragging issues with XWayland
    name  = "fix-xwayland-drags",
    match = {
        class      = "^$",
        title      = "^$",
        xwayland   = true,
        float      = true,
        fullscreen = false,
        pin        = false,
    },

    no_focus = true,
})

-- Layer rules also return a handle.
-- local overlayLayerRule = hl.layer_rule({
--     name  = "no-anim-overlay",
--     match = { namespace = "^my-overlay$" },
--     no_anim = true,
-- })
-- overlayLayerRule:set_enabled(false)

-- Hyprland-run windowrule
hl.window_rule({
    name  = "move-hyprland-run",
    match = { class = "hyprland-run" },

    move  = "20 monitor_h-120",
    float = true,
})

-- Плавающий режим для настроек звука
hl.window_rule({
    name  = "float-pavucontrol",
    match = { class = "org.pulseaudio.pavucontrol" },
    float  = true,
    size  = "480 380",
    move  = "100%-490 42",
    -- center = true,
})

-- Плавающий режим для Календаря
hl.window_rule({
    name  = "float-calendar",
    match = { class = "org.gnome.Calendar" },
    float  = true,
    center = true,
})

-- Плавающий режим для Keypunch
-- Правило живёт здесь, а не в windowrulev2 из visuals.lua: та таблица в
-- Hyprland 0.56 молча игнорируется, окно так и оставалось тайловым.
hl.window_rule({
    name   = "float-keypunch",
    match  = { class = "no\\.bragefuglseth\\.Keypunch\\..*" },
    float  = true,
    center = true,
    -- opacity здесь намеренно не задан: окно берёт глобальные 0.78/0.62,
    -- те же, что у всех прочих окон. Ставил 0.48 под стать терминалам —
    -- вышло нечитаемо: background_opacity у kitty гасит только фон, а
    -- правило opacity в Hyprland гасит окно целиком, вместе с текстом.
})

-- Черновик (notepad.sh): плавающее окно на спецстоле notepad.
-- Раньше эти правила ставил сам скрипт через `hyprctl keyword windowrulev2`
-- при каждом запуске. В Hyprland 0.56 keyword вообще не работает — отвечает
-- "keyword can't work with non-legacy parsers", то есть правила не
-- применялись ни разу.
-- Матч по классу, а НЕ по заголовку: title = ".*scratchpad\\.txt.*" промахивался
-- всякий раз, когда mousepad восстанавливал сессию и активной оказывалась другая
-- вкладка.
--
-- workspace здесь НЕ задан намеренно. Пока стояло workspace = "special:notepad",
-- на спецстол уезжало каждое окно блокнота, включая новые пустые; открытый
-- спецстол лежит поверх монитора и не пропускает ввод к окнам под ним, так что
-- после SUPER+SHIFT+N переставали кликаться терминалы на том же столе.
-- Теперь на спецстол уходит только главный черновик, и отправляет его сам
-- notepad.sh — адресно, по address окна.
-- Все окна блокнота — плавающие (14.09.2026 вернули по просьбе, для
-- проверки). Была попытка сделать пустые окна обычными: плавающее поверх
-- развёрнутого через SUPER+= окна не получало фокуса и пряталось под ним.
-- Теперь это решено в ribbon_binds.lua: появление или фокус плавающего окна
-- сворачивает развёрнутые обычные окна стола, а возврат на запомненное окно
-- без плавающих на столе разворачивает его снова.
hl.window_rule({
    name   = "float-scratchpad",
    match  = { class = "org\\.xfce\\.mousepad" },
    float     = true,
    size      = "900 600",
    center    = true,
})

-- На спецстол уходит ТОЛЬКО главный черновик. Матч по initial_title, а не по
-- title: заголовок меняется вместе с активной вкладкой, начальный — нет.
-- Главное окно запускается как `mousepad ~/.scratchpad.txt`, новые пустые
-- рождаются как "Untitled N" и под это правило не попадают, поэтому остаются
-- обычными плавающими окнами на текущем столе.
hl.window_rule({
    name   = "scratchpad-to-special",
    match  = { class = "org\\.xfce\\.mousepad", initial_title = ".*scratchpad\\.txt.*" },
    workspace = "special:notepad",
})

-- Видео — без прозрачности.
-- Wayland-клиенты сообщают тип содержимого поверхности, и Hyprland это
-- принимает (render:send_content_type = true). Пока в окне играет видео,
-- оно матчится как content:video и становится непрозрачным; как только
-- воспроизведение кончилось, правило перестаёт действовать само.
--
-- Два числа — активное и неактивное окно. Активное 1.0, чтобы картинка
-- была честной; неактивное оставлено на 0.62, как у всех прочих окон.
hl.window_rule({
    name    = "opaque-video",
    match   = { content = "video" },
    opacity = "1.0 0.62",
})

-- То же для видео в браузере, но по заголовку окна.
-- Правило выше на браузер не действует: Chromium (а значит и Thorium) не
-- реализует протокол, которым клиент сообщает композитору тип содержимого,
-- и его окна отдают contentType = "none" даже с играющим видео. Проверено —
-- ни одно окно браузера ни разу не отдало "video".
--
-- Поэтому цепляемся за заголовок: у вкладки YouTube он всегда оканчивается
-- на " - YouTube - Thorium". Правило переоценивается при смене заголовка,
-- поэтому прозрачность возвращается сама, стоит переключить вкладку.
hl.window_rule({
    name    = "opaque-youtube",
    match   = { title = ".*- YouTube -.*" },
    opacity = "1.0 0.62",
})



-- Плавающий режим для Часов
hl.window_rule({
    name  = "float-clocks",
    match = { class = "org.gnome.clocks" },
    float  = true,
    center = true,
})

-- Микшер громкости приложения под иконкой звука (справа под баром)
hl.window_rule({
    name  = "float-pwvucontrol",
    match = { class = "pwvucontrol|com.saivert.pwvucontrol|pavucontrol" },

    float = true,
    size  = "450 380",
    move  = "100%-465 42",
})

-- Мини-окно громкости в правом верхнем углу под Waybar
hl.window_rule({
    name  = "small-top-right-sound",
    match = { class = "pwvucontrol|com.saivert.pwvucontrol|pavucontrol" },

    float = true,
    size  = "460 380",
    move  = "100%-470 42",
})

-- Плавающее окно Wi-Fi (nmtui)
hl.window_rule({
    name  = "float-nmtui",
    match = { class = "float-nmtui" },

    float  = true,
    size   = "600 450",
    center = true,
})

-- Микшер громкости приложения под иконкой звука
hl.window_rule({
    name  = "pwvucontrol-top-right",
    match = { class = "pwvucontrol|com.saivert.pwvucontrol|pavucontrol" },

    float = true,
    size  = "450 380",
    move  = "100%-465 42",
})

-- Окно управления Сетью под баром
hl.window_rule({
    name  = "float-nm-editor",
    match = { class = "nm-connection-editor" },

    float = true,
    size  = "500 420",
    move  = "100%-515 42",
})

-- Окно Bluetooth под баром
hl.window_rule({
    name  = "float-blueman",
    match = { class = "blueman-manager" },

    float = true,
    size  = "480 380",
    move  = "100%-495 42",
})

-- Плавающий терминал-календарь с возможностью изменения размера
hl.window_rule({
    name  = "terminal-calendar",
    match = { title = "^TerminalCalendar$" },

    float  = true,
    size   = "280 200", -- Стартовый компактный размер
    center = true,      -- Откроется по центру экрана
})

--------------------------------
---- WORKSPACE ASSIGNMENTS -----
--------------------------------


-- Выбор обоев (waypaper, WIN+W) — плавающим окном по центру. В мозаике оно
-- растягивалось на всю колонку и ломало раскладку стола.
hl.window_rule({
    name   = "float-waypaper",
    match  = { class = "^waypaper$" },
    float  = true,
    size   = "860 900",
    center = true,
})

-- Редактор скриншотов satty — плавающим окном по центру, а не в мозаике.
hl.window_rule({
    name   = "float-satty",
    match  = { class = "^com.gabm.satty$" },
    float  = true,
    center = true,
})

-- Редактор снимков ksnip (Qt) — тоже плавающим по центру, как satty.
hl.window_rule({
    name   = "float-ksnip",
    match  = { class = "(?i).*ksnip.*" },
    float  = true,
    size   = "1200 800",
    center = true,
})

-- Приложение «Настройки» (scripts/settings_app.py) — плавающим окном по центру.
hl.window_rule({
    name   = "float-settings",
    match  = { class = "^com.jarvis.settings$" },
    float  = true,
    size   = "780 560",
    center = true,
})

-- Проба вертикальной ленты на столе 10 убрана 12.09.2026 по итогу проверки.
--
-- Чего хотелось: чтобы окна уезжали за верхний и нижний край экрана, как
-- колонки уезжают за боковые. Чего Hyprland даёт: либо горизонтальная лента со
-- стопками внутри колонок (стопка всегда делит высоту экрана и никуда не
-- уезжает), либо `layout_opts = { direction = "down" }` — та же самая лента,
-- повёрнутая на 90°, где за край уезжает уже горизонталь. Двух прокруток сразу
-- нет: у ленты одно направление на стол. Выбрана горизонталь.
--
-- Если когда-нибудь понадобится вернуть поворот на отдельном столе:
--     hl.workspace_rule({
--         workspace = "10",
--         layout = "scrolling",
--         layout_opts = { direction = "down" },
--     })
-- Поля `name` у hl.workspace_rule НЕТ — конфиг падает с "unknown field 'name'".

-- Картинка в картинке LibreWolf и Zen (Ctrl+Shift+] на видео) — сразу плавающее
-- окно в правом нижнем углу, 640x360 (16:9), 14.09.2026. Раньше окно
-- вставало колонкой в ленту. Матч по начальному заголовку: у окна видео он
-- «Picture-in-Picture» и не меняется.
hl.window_rule({
    name  = "float-browser-pip",
    -- Zen добавлен 15.09.2026: у него окно видео с тем же заголовком.
    match = { class = "^(librewolf|zen)$", initial_title = "^Picture-in-Picture$" },
    float = true,
    size  = "640 360",
    move  = "monitor_w-660 monitor_h-380",
})
