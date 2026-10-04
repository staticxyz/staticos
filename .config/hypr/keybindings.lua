---------------------
---- KEYBINDINGS ----
---------------------

local mainMod = "SUPER"

-- Запуск программ
hl.bind("CTRL + code:49", hl.dsp.exec_cmd(terminal))
hl.bind("CTRL + Q", hl.dsp.window.close())
hl.bind(mainMod .. " + SPACE", hl.dsp.exec_cmd(menu))
-- История буфера обмена (cliphist) с миниатюрами картинок — SUPER+ALT+V
-- (19.09.2026, перенесено с SUPER+SHIFT+V по просьбе).
hl.bind(mainMod .. " + ALT + V", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/clipboard_menu.py"))
-- Переключатель окон: держать SUPER, Tab листает, отпустить SUPER — переход.
hl.bind(mainMod .. " + TAB", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/window_switcher.sh"))
-- Обзор всех столов и лент — SUPER+G, тот же бинд, что в конфиге niri (21.09.2026).
-- Свой скрипт, а не плагин: плагинов обзора под ленту и 0.56 нет, разбор в
-- NOTES-обзор-столов.md. Повторное нажатие закрывает (single_instance в скрипте).
hl.bind(mainMod .. " + G", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/overview.py"))
-- Калькулятор (rofi-calc): ответ по мере набора, Enter — в буфер.
hl.bind(mainMod .. " + C", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/calc_menu.sh"))
hl.bind(mainMod .. " + E", hl.dsp.exec_cmd(fileManager))
-- Helium: второй браузер — SUPER+I (с 17.09.2026; SUPER+H отдан под столы).
hl.bind(mainMod .. " + I", hl.dsp.exec_cmd("helium-browser"))
-- Zen: основной браузер (с 15.09.2026), живая тема из обоев — SUPER+U (с 17.09.2026).
hl.bind(mainMod .. " + U", hl.dsp.exec_cmd("zen-browser"))
-- LibreWolf: запасной браузер.
hl.bind(mainMod .. " + B", hl.dsp.exec_cmd("librewolf"))
hl.bind(mainMod .. " + N", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/notepad.sh new"))
-- Всегда новое окно блокнота с одним пустым табом, без показа/скрытия
-- спецстола. CTRL+N внутри mousepad делает вкладку в текущем окне —
-- это его собственная горячая клавиша, снаружи её не переопределить.
hl.bind(mainMod .. " + SHIFT + N", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/notepad.sh"))
hl.bind(mainMod .. " + F6", hl.dsp.exec_cmd("bemoji -t"))

-- Выбор аватара для экрана блокировки
hl.bind(mainMod .. " + SHIFT + A", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/avatar_picker.py"))

-- Управление окнами
-- SUPER+V — через ribbon_toggle_float (ribbon_binds.lua): сворачивает развёрнутые
-- окна, иначе новое плавающее окно пряталось под развёрнутым (14.09.2026).
hl.bind(mainMod .. " + V", function() ribbon_toggle_float() end)
-- SUPER+F — через ribbon_toggle_fullscreen (ribbon_binds.lua): после выхода
-- из полного экрана возвращает развёрнутость, заданную SUPER+= (14.09.2026).
hl.bind(mainMod .. " + F", function() ribbon_toggle_fullscreen() end)
-- Блокировка экрана — SUPER+O (17.09.2026): SUPER+L отдан под «стол вправо», как l в Vim.
hl.bind(mainMod .. " + O", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/lockscreen"))
hl.bind("ALT + TAB", hl.dsp.focus({ monitor = "+1" }))

-- Перенос окна на другой монитор
hl.bind("CTRL + ALT + right", hl.dsp.window.move({ monitor = "+1" }))
hl.bind("CTRL + ALT + left", hl.dsp.window.move({ monitor = "-1" }))
-- CTRL+ALT+H / L — то же, vim-клавишами: H — монитор слева, L — справа (21.09.2026;
-- раньше J/K — оси приведены к niri: мониторы стоят по горизонтали, значит H/L).
hl.bind("CTRL + ALT + H", hl.dsp.window.move({ monitor = "-1" }))
hl.bind("CTRL + ALT + L", hl.dsp.window.move({ monitor = "+1" }))

-- Перенос ВСЕХ окон разом на СЛЕДУЮЩИЙ или ПРЕДЫДУЩИЙ рабочий стол
hl.bind("SUPER + ALT + SHIFT + right", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/move_all_windows.sh next"))
hl.bind("SUPER + ALT + SHIFT + left", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/move_all_windows.sh prev"))

-- ПОРЯДОК СТОЛОВ (ws_order.py) — свой порядок в баре без переноса окон.
-- Стол получает невидимую подпись-метку, waybar сортирует по ней, а показывает
-- номер. Окна при этом не двигаются вообще, поэтому размеры и раскладка внутри
-- столов не ломаются. Подробности — в шапке ws_order.py.
--
-- Не вешать на ALT+SHIFT: в раскладке стоит grp:alt_shift_toggle, переключение
-- языка висит ровно на этой паре и xkb перехватывает её раньше Hyprland.

-- Создать / удалить стол — одной парой стрелок, вверх и вниз.
-- Новый стол встаёт сразу после текущего и получает наименьший свободный номер.
-- 14.09.2026: вернулось на SUPER+CTRL+вверх/вниз (с 12.09 временно было на
-- SUPER+SHIFT, а CTRL двигал окно по вертикали — пользователь попросил вернуть).
hl.bind("SUPER + CTRL + up", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/ws_order.py insert"))

-- Удаление срабатывает только на ПУСТОМ столе: окна непустого пришлось бы либо
-- закрыть, либо перенести на соседний стол — а перенос заново раскладывает
-- окна, ровно то, из-за чего этот механизм и переписывался. В таком случае
-- скрипт показывает уведомление вместо молчаливого отказа.
hl.bind("SUPER + CTRL + down", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/ws_order.py remove"))

-- Подвинуть текущий стол влево/вправо в порядке бара
hl.bind("SUPER + SHIFT + left", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/ws_order.py move left"))
hl.bind("SUPER + SHIFT + right", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/ws_order.py move right"))

-- 16.09.2026: SUPER+O освобождён под переход на стол правее (см. блок
-- «Домашний ряд» ниже). Перенос стола на соседний монитор, который висел
-- здесь, никуда не делся — он на SUPER+CTRL+SHIFT+вправо/влево (ниже в этом
-- же файле), и пользователь пользуется именно тем сочетанием.

-- Перенос активного окна на соседний стол — ПО ВИДИМОМУ ПОРЯДКУ.
--
-- Раньше здесь стоял штатный hl.dsp.window.move({ workspace = "r+1" }), и это
-- была та же ошибка, которую мы уже чинили для перехода между столами: r+1
-- идёт по НОМЕРАМ, а при своём порядке (ws_order.py) номер и место в баре не
-- совпадают. Окно с первого стола вправо уезжало на стол №2, который в баре
-- может стоять пятым. Теперь перенос идёт тем же порядком, что и переход, и
-- так же ограничен столами текущего монитора.
local ws_order = "python3 $HOME/.config/hypr/scripts/ws_order.py "

hl.bind(mainMod .. " + CTRL + ALT + equal", hl.dsp.exec_cmd(ws_order .. "send next"))
hl.bind(mainMod .. " + CTRL + ALT + right", hl.dsp.exec_cmd(ws_order .. "send next"))
hl.bind(mainMod .. " + CTRL + ALT + kp_add", hl.dsp.exec_cmd(ws_order .. "send next"))

hl.bind(mainMod .. " + CTRL + ALT + minus", hl.dsp.exec_cmd(ws_order .. "send prev"))
hl.bind(mainMod .. " + CTRL + ALT + left", hl.dsp.exec_cmd(ws_order .. "send prev"))
hl.bind(mainMod .. " + CTRL + ALT + kp_subtract", hl.dsp.exec_cmd(ws_order .. "send prev"))

-- Нативный перенос рабочего стола (без консольных костылей)
hl.bind(mainMod .. " + CTRL + SHIFT + right", hl.dsp.workspace.move({ monitor = "+1" }))
hl.bind(mainMod .. " + CTRL + SHIFT + left", hl.dsp.workspace.move({ monitor = "-1" }))

-- Перемещение окон
-- SUPER+ALT+←/→ и клавиши ленты (SUPER+R, SUPER+[ ]) — в ribbon_binds.lua:
-- они проверяют раскладку в момент нажатия (лента или классика).
require("ribbon_binds")
hl.bind("SUPER + ALT + up", hl.dsp.window.move({ direction = "up" }))
hl.bind("SUPER + ALT + down", hl.dsp.window.move({ direction = "down" }))

-- Изменение размера окон убрано: висело на тех же SUPER+ALT+стрелка, что и
-- перемещение выше, Hyprland регистрировал оба бинда и срабатывали они разом.
-- Работать оно всё равно не могло — "hyprctl dispatch resizeactive 80 0" это
-- старый синтаксис, а конфиг здесь на Lua, и парсер отвечает
-- "')' expected near '80'". Если ресайз понадобится, вешай на СВОБОДНОЕ
-- сочетание и через hl.dsp: hl.bind("SUPER + CTRL + right", hl.dsp.window.resize(...))

-- Чистый рабочий стол и спец-область
hl.bind("SUPER + D", function() ws_goto(10) end)
hl.bind("ALT + E", hl.dsp.window.move({ workspace = "special:magic" }))
hl.bind("ALT + Q", hl.dsp.workspace.toggle_special("magic"))
hl.bind("ALT + SUPER + E", hl.dsp.window.move({ workspace = "+0" }))

-- Обои
-- Обои: SUPER+W — своя лента миниатюр поверх экрана (scripts/wallpaper_picker.py,
-- 19.09.2026, по скриншоту пользователя), SUPER+SHIFT+W — прежнее окно waypaper сеткой.
hl.bind(mainMod .. " + W", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/wallpaper_picker.py"))
hl.bind(mainMod .. " + SHIFT + W", hl.dsp.exec_cmd("waypaper"))

-- Переключение фокуса
-- SUPER+стрелки (фокус в пределах монитора) — в ribbon_binds.lua.

-- Прямые скан-коды Numpad (1-0)
local np_codes =
	{ "code:87", "code:88", "code:89", "code:83", "code:84", "code:85", "code:79", "code:80", "code:81", "code:90" }

for i = 1, 10 do
	local top_key = i % 10
	local np_key = np_codes[i]

	hl.bind(mainMod .. " + " .. top_key, function() ws_goto(i) end)   -- ws_anim.lua: сдвиг в верную сторону
	hl.bind(mainMod .. " + SHIFT + " .. top_key, hl.dsp.window.move({ workspace = i }))

	hl.bind(mainMod .. " + " .. np_key, function() ws_goto(i) end)
	hl.bind(mainMod .. " + SHIFT + " .. np_key, hl.dsp.window.move({ workspace = i }))
end

-- Скриншот
-- Снимок области. -z замораживает экран на время выделения: прежняя связка
-- grim -g "$(slurp)" выделяла по ЖИВОМУ экрану, и всё продолжало двигаться,
-- пока ты обводишь область.
-- Заморозку hyprshot делает через hyprpicker — без этого пакета флаг -z
-- молча не работает, снимок получится, но экран замирать не будет.
hl.bind("Print", hl.dsp.exec_cmd("hyprshot -m region -z --clipboard-only"))
-- Снимок области с разметкой (satty): стрелки, текст, размытие; Enter — в буфер.
-- Снимок области с редактором. Было SHIFT+Print — перенесено на SUPER+Print
-- по просьбе 11.09.2026.
hl.bind("SUPER + Print", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/screenshot_annotate.sh"))

-- Мышь: SUPER + колесо листает ОКНА ленты, как SUPER+←/→ (просьба пользователя
-- 19.09.2026; раньше здесь были столы — они остались на SUPER+H/L и
-- SUPER+CTRL+←/→, а также на колесе над картой ленты в баре).
hl.bind(mainMod .. " + mouse_down", function() ribbon_focus("right") end)
hl.bind(mainMod .. " + mouse_up", function() ribbon_focus("left") end)

-- Настройки рабочего стола (то же окно, что по шестерёнке в «Энергии»).
-- Второй запуск не плодит окна — Gtk.Application поднимает открытое.
hl.bind("SUPER + slash", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/settings_app.py"))

-- Вентиляторы: 100% ↔ автоматика контроллера (команда fan, ~/.local/bin/fan).
hl.bind(mainMod .. " + ALT + F", hl.dsp.exec_cmd("$HOME/.local/bin/fan toggle"))

hl.bind(mainMod .. " + CTRL + right", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/ws_order.py go next"))
hl.bind(mainMod .. " + CTRL + left", hl.dsp.exec_cmd("python3 $HOME/.config/hypr/scripts/ws_order.py go prev"))

-- Vim-клавиши. 21.09.2026 — оси приведены к тем же, что в конфиге niri
-- (~/.config/niri/config.kdl) и в обзоре (SUPER+G), чтобы пальцы не
-- переучивались между композиторами:
--
--   H / L — влево / вправо → КОЛОНКИ ленты и МОНИТОРЫ
--   K / J — вверх / вниз   → СТОЛЫ (K — предыдущий, J — следующий)
--
--   без модификатора — фокус            ALT          — двигать то, что в фокусе
--   CTRL + K / J     — окно в стопке    SHIFT + K/J  — двигать сам стол в порядке
--   CTRL + ALT + K/J — окно на стол     CTRL + SHIFT + H/L — стол на монитор
--
-- Прежняя схема (17.09.2026: H/L — столы, J/K — колонки) лежит в
-- keybindings.lua.bak.vimaxes-*. Стрелки НЕ тронуты — они как были.
-- Столы — через ws_order.py, а не штатный workspace r±1: порядок столов свой, и
-- соседний по номеру не равен соседнему в баре. Окна — через ribbon_focus /
-- ribbon_swap из ribbon_binds.lua: у края ленты не перескакивают на соседний монитор.
local ws_py = "python3 $HOME/.config/hypr/scripts/ws_order.py "

-- H / L — колонка левее / правее (как SUPER+←/→)
hl.bind(mainMod .. " + H", function() ribbon_focus("left") end)
hl.bind(mainMod .. " + L", function() ribbon_focus("right") end)
-- K / J — стол предыдущий / следующий (как SUPER+CTRL+←/→)
hl.bind(mainMod .. " + K", hl.dsp.exec_cmd(ws_py .. "go prev"))
hl.bind(mainMod .. " + J", hl.dsp.exec_cmd(ws_py .. "go next"))
-- CTRL+K / J — окно выше / ниже внутри колонки (как SUPER+↑/↓)
hl.bind(mainMod .. " + CTRL + K", function() ribbon_focus("up") end)
hl.bind(mainMod .. " + CTRL + J", function() ribbon_focus("down") end)
-- ALT+H / L — двигать колонку влево / вправо (как SUPER+ALT+←/→)
hl.bind(mainMod .. " + ALT + H", function() ribbon_swap("left") end)
hl.bind(mainMod .. " + ALT + L", function() ribbon_swap("right") end)
-- ALT+K / J — двигать окно вверх / вниз по стопке (как SUPER+ALT+↑/↓)
hl.bind(mainMod .. " + ALT + K", hl.dsp.window.move({ direction = "up" }))
hl.bind(mainMod .. " + ALT + J", hl.dsp.window.move({ direction = "down" }))
-- SHIFT+K / J — подвинуть сам стол в порядке бара: раньше / позже (как SUPER+SHIFT+←/→)
hl.bind(mainMod .. " + SHIFT + K", hl.dsp.exec_cmd(ws_py .. "move left"))
hl.bind(mainMod .. " + SHIFT + J", hl.dsp.exec_cmd(ws_py .. "move right"))
-- CTRL+ALT+K / J — окно на предыдущий / следующий стол (как SUPER+CTRL+ALT+←/→)
hl.bind(mainMod .. " + CTRL + ALT + K", hl.dsp.exec_cmd(ws_py .. "send prev"))
hl.bind(mainMod .. " + CTRL + ALT + J", hl.dsp.exec_cmd(ws_py .. "send next"))
-- CTRL+SHIFT+H / L — стол на монитор слева / справа (как SUPER+CTRL+SHIFT+←/→)
hl.bind(mainMod .. " + CTRL + SHIFT + H", hl.dsp.workspace.move({ monitor = "-1" }))
hl.bind(mainMod .. " + CTRL + SHIFT + L", hl.dsp.workspace.move({ monitor = "+1" }))
-- CTRL+H / L — новый стол слева / справа от текущего. Жили на ALT+H/L, но та пара
-- теперь двигает колонку (как в niri); в niri аналога нет — столы там создаются сами.
hl.bind(mainMod .. " + CTRL + H", hl.dsp.exec_cmd(ws_py .. "insert left"))
hl.bind(mainMod .. " + CTRL + L", hl.dsp.exec_cmd(ws_py .. "insert right"))

hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- Мультимедиа
hl.bind(
	"XF86AudioRaiseVolume",
	hl.dsp.exec_cmd("$HOME/.config/eww/scripts/volume_manager.sh up 5%"),
	{ locked = true }
)
hl.bind(
	"XF86AudioLowerVolume",
	hl.dsp.exec_cmd("$HOME/.config/eww/scripts/volume_manager.sh down 5%"),
	{ locked = true }
)
hl.bind("XF86AudioMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"), { locked = true })
hl.bind("XF86AudioMicMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"), { locked = true })
hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"), { locked = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"), { locked = true })

-- Подсветка клавиатуры ноутбука
hl.bind("SUPER + F3", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/kbdlight up"), { locked = true })
hl.bind("SUPER + F2", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/kbdlight down"), { locked = true })
hl.bind("SUPER + F1", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/kbdlight toggle"), { locked = true })

hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"), { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"), { locked = true })

-- F7/F8/F9 — управление воспроизведением.
-- В списке плееров не хватало firefox: Mercury это форк Firefox, и playerctl
-- видит его как "firefox.instance_...". Из-за этого F8 не делал ничего,
-- хотя Hyprland клавишу исправно перехватывал.
-- Перехват тут глобальный: до браузера F8 не доходит и дойти не может,
-- поэтому родное действие браузера на этой клавише работать не будет.
hl.bind("F7", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/mediakey previous"))
hl.bind("F8", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/mediakey play-pause"))
hl.bind("F9", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/mediakey next"))

hl.bind("F1", hl.dsp.exec_cmd("$HOME/.config/eww/scripts/volume_manager.sh down 5%"))
hl.bind("F2", hl.dsp.exec_cmd("$HOME/.config/eww/scripts/volume_manager.sh up 5%"))

-- F10 отправляет '+' (Лайк) в окно YouTube Music, даже если оно на другом воркспейсе
hl.bind("F10", hl.dsp.send_shortcut({
	mods = "NONE",
	key = "equal",
	window = "class:^(.*youtube-music.*)$",
}))

-- F11 отправляет '-' (Дизлайк) в окно YouTube Music
hl.bind("F11", hl.dsp.send_shortcut({
	mods = "NONE",
	key = "minus",
	window = "class:^(.*youtube-music.*)$",
}))

-------------------
---- ПОМИДОР ------
-------------------

-- Таймер живёт в ~/.local/bin/pomo и не держит фонового процесса, поэтому
-- бинд — это просто вызов команды: состояние лежит в файле, а pomo сам шлёт
-- waybar сигнал 8, и модуль в панели меняется в тот же миг.
-- SUPER+P — одна кнопка на весь цикл: стоим — старт, идём — пауза, на паузе —
-- дальше. Отдельного «старта» на клавише нет намеренно: помнить два бинда для
-- таймера незачем.
hl.bind("SUPER + P", hl.dsp.exec_cmd("$HOME/.local/bin/pomo toggle"))
hl.bind("SUPER + SHIFT + P", hl.dsp.exec_cmd("$HOME/.local/bin/pomo skip"))
hl.bind("SUPER + ALT + P", hl.dsp.exec_cmd("$HOME/.local/bin/pomo stop"))

-- SUPER+T — «на сколько ставим»: окно rofi, где набираешь своё время
-- (40m, 1h30m, 1ч20м, можно с задачей через пробел) или берёшь из недавних.
-- Дальше это обычный отрезок: SUPER+P пауза, SHIFT пропуск, ALT стоп.
-- Из терминала то же самое — pomo 1h30m.
hl.bind("SUPER + T", hl.dsp.exec_cmd("$HOME/.local/bin/pomo ask"))

-- Окно с живым отсчётом и статистикой за сегодня — на случай, когда цифры в
-- баре мало и хочется смотреть на полосу.
hl.bind("SUPER + CTRL + P", hl.dsp.exec_cmd(terminal .. " --title pomo -o initial_window_width=52c -o initial_window_height=3c $HOME/.local/bin/pomo watch"))

-- Картинка в картинке LibreWolf: Ctrl+Shift+] и на русской раскладке
-- (14.09.2026). LibreWolf узнаёт сочетание по символу, а на русской раскладке
-- та же клавиша даёт «ъ», и сочетание не срабатывало. Hyprland ловит клавишу по
-- первой раскладке (input:resolve_binds_by_sym = false), а send_shortcut
-- отправляет окну клавишу ВСЕГДА по английской: окно на GTK получило одинаково
-- keycode 35, group 0, Ctrl+Shift, «}» и при русской, и при английской
-- раскладке. Переключать раскладку не нужно — подсказка о ней не мигает.
-- Любому окну, кроме LibreWolf и Zen, нажатие передаётся как есть (hl.dsp.pass).
function pip_shortcut()
    local w = hl.get_active_window()
    if not w then return end
    -- Zen — тот же Firefox и тот же символьный разбор сочетаний (15.09.2026).
    if w.class == "librewolf" or w.class == "zen" then
        hl.dispatch(hl.dsp.send_shortcut({ mods = "CTRL SHIFT", key = "bracketright",
                                           window = "address:" .. w.address }))
    else
        hl.dispatch(hl.dsp.pass({ window = "address:" .. w.address }))
    end
end
hl.bind("CTRL + SHIFT + bracketright", function() pip_shortcut() end)
