-----------------------
---- LOOK AND FEEL ----
-----------------------

-- Скругление углов окон: из ~/.config/hypr/state/window-rounding (его пишет
-- ползунок в «Настройках» → «Окна» через scripts/window_rounding.py).
-- Нет файла или в нём мусор — 4 px.
local window_rounding = 4
local wr = io.open(os.getenv("HOME") .. "/.config/hypr/state/window-rounding")
if wr then
	local n = tonumber(wr:read("*l") or "")
	if n then
		window_rounding = math.max(0, math.min(24, math.floor(n)))
	end
	wr:close()
end

-- Безопасная загрузка динамической палитры Matugen
local ok, wal = pcall(dofile, os.getenv("HOME") .. "/.cache/matugen/colors.lua")

-- Цвета по умолчанию
-- Рамка активного окна — градиент из двух цветов палитры: его медленно
-- вращает анимация borderangle (ниже).
-- Рамка активного окна — градиент из двух цветов палитры: его медленно
-- вращает анимация borderangle (ниже). Градиент задаётся таблицей: строку
-- "цвет цвет 45deg" Lua-конфиг не принимает.
local active_border = { colors = { "rgba(7aa2f7ff)", "rgba(bb9af7ff)" }, angle = 45 }
local inactive_border = "rgba(00000000)"

if ok and wal then
	active_border = { colors = { "rgba(" .. wal.color4 .. "99)",
	                            "rgba(" .. wal.color2 .. "66)" }, angle = 45 }
	-- Тот же акцент, что у активной рамки, но на ~треть непрозрачности.
	-- Раньше брался wal.background — почти цвет фона, поэтому у неактивных
	-- окон рамки фактически не было видно. Должно совпадать с
	-- M_INACTIVE_BORDER в ~/.config/matugen/templates/hypr-colors.sh.
	inactive_border = "rgba(" .. wal.color4 .. "22)"
end

-- Неактивные окна: затемнять (по умолчанию) или делать полупрозрачными, как
-- раньше. Выбор хранит scripts/dim_toggle.py (переключатель в панели
-- «Энергия»); здесь он читается при загрузке конфига.
local dim_on = true
local dim_file = io.open(os.getenv("HOME") .. "/.config/hypr/state/dim-inactive")
if dim_file then
	dim_on = (dim_file:read("*l") ~= "off")
	dim_file:close()
end
-- Сила затемнения — тоже из «Настроек» (dim_toggle.py strength), по умолчанию 0.22.
local dim_power = 0.22
local power_file = io.open(os.getenv("HOME") .. "/.config/hypr/state/dim-strength")
if power_file then
	dim_power = tonumber(power_file:read("*l")) or 0.22
	power_file:close()
end

-- Раскладка окон: лента (scrolling, как в Niri) или классика Hyprland
-- (dwindle). Выбор хранит scripts/layout_mode.py (переключатель в
-- «Настройках» → «Внешний вид» → «Окна»); здесь он читается при загрузке.
local tiled_layout = "scrolling"
local layout_file = io.open(os.getenv("HOME") .. "/.config/hypr/state/layout-mode")
if layout_file then
	local v = layout_file:read("*l")
	if v == "scrolling" or v == "dwindle" then
		tiled_layout = v
	end
	layout_file:close()
end

-- Прокрутка ленты при смене фокуса: center (окно по центру, 0) или fit (1).
-- Выбор хранит scripts/ribbon_center.py (Настройки → Окна), 19.09.2026.
local focus_fit = 1
local fit_file = io.open(os.getenv("HOME") .. "/.config/hypr/state/ribbon-center")
if fit_file then
	if fit_file:read("*l") == "center" then
		focus_fit = 0
	end
	fit_file:close()
end

hl.config({
	general = {
		gaps_in = 15,
		gaps_out = 20,
		border_size = 5,
		col = {
			active_border = active_border,
			inactive_border = inactive_border,
		},
		-- Лента (как в Niri) или классика — см. tiled_layout выше. Лента
		-- опробована на столе 10 11.09.2026 и включена на всех столах.
		-- Плавающих окон раскладка не касается.
		layout = tiled_layout,
	},
	decoration = {
		-- Единое скругление: окна, бар, попапы, rofi, уведомления. Было 12;
		-- 14.09.2026 пользователь попросил углы квадратнее — окна сначала 6, потом 4.
		-- Значение теперь задаётся ползунком в «Настройках» (window_rounding
		-- выше). У бара, попапов и rofi радиус прописан в их файлах отдельно —
		-- держать их близко к окнам, иначе система перестаёт выглядеть единой.
		rounding = window_rounding,
		-- Максимальная прозрачность с сильным размытием: содержимое окна
		-- читается, а фон уходит в размытую муть — тот самый эффект
		-- «затягивания». Активное окно чуть плотнее неактивного, чтобы
		-- фокус был виден без рамки.
		-- active_opacity = 0.78,
		active_opacity = 1,
		-- Затемнение вместо прозрачности: фокус видно, а текст в соседних
		-- окнах остаётся чётким (сквозь прозрачность проступал фон).
		inactive_opacity = dim_on and 1 or 0.82,
		dim_inactive = dim_on,
		dim_strength = dim_power, -- 0.22 по умолчанию (0.15 — мало, 0.3 — много); меняется в «Настройках»
		-- inactive_opacity = 0.62,
		blur = {
			enabled = true,
			-- Сильное размытие ради «затягивающего» фона под прозрачными
			-- окнами. В прошлый раз поднятие size само по себе сделало окна
			-- тёмными — потому что размытие по умолчанию слегка гасит и
			-- поднимает контраст. Здесь это компенсировано явно: brightness
			-- выше единицы возвращает яркость, vibrancy держит насыщенность
			-- обоев, contrast не даёт картинке стать плоской.
			-- 12.09.2026: пробовали удешевить до 5/2 и вернули обратно.
			-- Замер под играющим видео: 5/2 — 24%, размытие выключено — 32%,
			-- 7/3 — 35%. Разброс больше эффекта, то есть греет не размытие, а
			-- вывод кадров видео. Значит, экономить тут нечего.
			size = 7,
			passes = 3,
			brightness = 1.15,
			contrast = 1.0,
			vibrancy = 0.35,
			noise = 0.008,
		},
	},
	layerrule = {
		"blur, eww",
		"ignorealpha 0.5, eww",

		-- Waybar: блюр под панелью, чтобы прозрачный фон бара размывал обои,
		-- а не показывал их резко. ignorealpha 0.1 — порог, ниже которого
		-- пиксель считается полностью прозрачным и не блюрится; при почти
		-- прозрачном фоне бара порог должен быть низким, иначе Hyprland
		-- сочтёт всю панель прозрачной и блюр не применится вовсе.
		"blur, waybar",
		"ignorealpha 0.1, waybar",
	},
	windowrulev2 = {
		"workspace 1 silent, class:^(hack-.*)$",
		"opacity 0.78 0.70, class:^(YouTube Music)$",
		"opacity 0.78 0.70, class:^(youtube-music)$",
		"opacity 0.78 0.70, class:^(com.github.th_ch.youtube_music)$",

		-- Obsidian (прозрачность под обои)
		"opacity 0.88 0.80, class:^(obsidian|Obsidian)$",

		-- Календарь плавает не по windowrule: GTK4 выставляет app_id уже
		-- после маппинга окна, поэтому class: тут не матчится и правило
		-- молча не срабатывает. Окно само просит float по своему pid —
		-- см. _float_self() в ~/.config/hypr/scripts/calendar_app.py
	},

	dwindle = {
		preserve_split = true,
	},
	master = {
		new_status = "master",
	},
	scrolling = {
		-- Одинокая колонка НЕ растягивается на весь экран (19.09.2026, просьба: -- «на пустом столе SUPER+= и SUPER+− не меняют размер»): при true
		-- ширина менялась, но её не было видно, пока не появится второе окно.
		-- Разворот SUPER+= (window.fullscreen mode maximized) это не затрагивает.
		fullscreen_on_one_column = false,
		focus_fit_method = focus_fit,
	},
})

-- Helium (Chromium). Окно рисуется с альфа-каналом, сквозь него проступают
-- размытые обои, а видео вдобавок уезжает отдельным слоем Wayland и ловит
-- затемнение второй раз — на вкладке с роликом это видно сильнее всего.
-- Firefox рисует фон непрозрачным, поэтому у Librewolf такого нет.
--
-- Задаётся через hl.window_rule, а НЕ строкой в windowrulev2: строковый
-- разбор в 0.56 принимает "nodim" молча, но не применяет его — проверено
-- замером (при dim_strength 0.6 окно темнело на 32 пункта из 255). Lua-имена
-- полей другие: no_dim, no_blur, opaque — с подчёркиванием.
-- 12.09.2026: no_dim убран по просьбе — он хочет видеть затемнение
-- неактивного helium, как у остальных окон. opaque = true остаётся: именно
-- он гасит главную часть проблемы (альфа-канал окна). Если видео снова начнёт
-- темнеть вдвое сильнее остального окна — вернуть no_dim = true.
hl.window_rule({ match = { class = "helium" }, no_blur = true, opaque = true })

-- VS Code: лёгкая прозрачность (14.09.2026) — активное 0.95, неактивное 0.92.
-- У Electron на Linux своей прозрачности фона нет, поэтому её даёт Hyprland,
-- а он делает прозрачным окно ЦЕЛИКОМ, вместе с текстом. Отсюда осторожные
-- значения: 5 % почти не мешают читать код, а размытый фон уже чувствуется.
-- Формат проверен на пробном окне через `hyprctl getprop … opacity`:
-- opacity = "0.95 0.92" и opacity = 0.95 работают, таблица { … } отвергается.
-- Цвета VS Code — отдельно, из обоев: scripts/vscode_colors.py.
hl.window_rule({ match = { class = "^code$" }, opacity = "0.95 0.92" })

-- Obsidian: прозрачность из ~/.config/hypr/state/obsidian-opacity (проценты,
-- 70..100; пишет ползунок «Настроек» через scripts/obsidian_opacity.py).
-- Неактивное окно на 3% прозрачнее. Цвета не страдают: палитра обоев приходит в
-- Obsidian CSS-сниппетом matugen (templates/obsidian.css).
--
-- 14.09.2026: сначала стояло постоянное 0.92/0.88 — пользователь попросил «менее
-- прозрачно» и вынести в настройки; по умолчанию теперь 96. Класс окна —
-- md.obsidian.Obsidian; старая строка "opacity 0.88 0.80, class:^(obsidian|Obsidian)$"
-- в windowrulev2 выше не срабатывала (не тот класс, legacy-строки Lua-конфиг не
-- применяет): getprop opacity до правок = 1.
--
-- Три пути, чтобы значение было верным всегда:
--   правило окна       — значение на момент загрузки конфига;
--   window.open        — новое окно получает значение из файла прямо сейчас;
--   obsidian_opacity_apply() — зовёт скрипт после записи: открытые окна.
local OBSIDIAN_CLASS = "md.obsidian.Obsidian"

local function obsidian_opacity()
	local f = io.open(os.getenv("HOME") .. "/.config/hypr/state/obsidian-opacity")
	local n = 96
	if f then
		n = tonumber(f:read("*l") or "") or 96
		f:close()
	end
	n = math.max(70, math.min(100, math.floor(n)))
	return n / 100, math.max(0.5, (n - 3) / 100)
end

local function obsidian_apply_to(w)
	if not w or w.class ~= OBSIDIAN_CLASS then return end
	local active, inactive = obsidian_opacity()
	local target = "address:" .. w.address
	hl.dispatch(hl.dsp.window.set_prop({ prop = "opacity", value = string.format("%.2f", active), window = target }))
	hl.dispatch(hl.dsp.window.set_prop({ prop = "opacity_inactive", value = string.format("%.2f", inactive), window = target }))
end

function obsidian_opacity_apply()
	local ok, list = pcall(function() return hl.get_windows() end)
	if not ok or type(list) ~= "table" then return end
	for _, w in ipairs(list) do
		obsidian_apply_to(w)
	end
end

do
	local active, inactive = obsidian_opacity()
	hl.window_rule({ match = { class = "^md\\.obsidian\\.Obsidian$" },
	                 opacity = string.format("%.2f %.2f", active, inactive) })
end
hl.on("window.open", obsidian_apply_to)

-- Кривые
hl.curve("easeOutQuint", { type = "bezier", points = { { 0.23, 1 }, { 0.32, 1 } } })
hl.curve("easeInOutCubic", { type = "bezier", points = { { 0.65, 0.05 }, { 0.36, 1 } } })
hl.curve("linear", { type = "bezier", points = { { 0, 0 }, { 1, 1 } } })
hl.curve("almostLinear", { type = "bezier", points = { { 0.5, 0.5 }, { 0.75, 1 } } })
hl.curve("quick", { type = "bezier", points = { { 0.15, 0 }, { 0.1, 1 } } })
hl.curve("easy", { type = "spring", mass = 1, stiffness = 238.1191, dampening = 24.21279333 })
-- Жёстче и суше, чем easy: перестановка окон в ленте не должна «желеить».
hl.curve("snappy", { type = "spring", mass = 1, stiffness = 320, dampening = 30 })

-- Анимации
hl.animation({ leaf = "global", enabled = true, speed = 10, bezier = "default" })
hl.animation({ leaf = "border", enabled = true, speed = 5.39, bezier = "easeOutQuint" })
hl.animation({ leaf = "windows", enabled = true, speed = 4.79, spring = "easy" })
hl.animation({ leaf = "windowsIn", enabled = true, speed = 4.1, spring = "easy", style = "popin 87%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 1.49, bezier = "linear", style = "popin 87%" })
hl.animation({ leaf = "fadeIn", enabled = true, speed = 1.73, bezier = "almostLinear" })
hl.animation({ leaf = "fadeOut", enabled = true, speed = 1.46, bezier = "almostLinear" })
hl.animation({ leaf = "fade", enabled = true, speed = 3.03, bezier = "quick" })
hl.animation({ leaf = "layers", enabled = true, speed = 3.81, bezier = "easeOutQuint" })
hl.animation({ leaf = "layersIn", enabled = true, speed = 4, bezier = "easeOutQuint", style = "fade" })
hl.animation({ leaf = "layersOut", enabled = true, speed = 1.5, bezier = "linear", style = "fade" })
hl.animation({ leaf = "fadeLayersIn", enabled = true, speed = 1.79, bezier = "almostLinear" })
hl.animation({ leaf = "fadeLayersOut", enabled = true, speed = 1.39, bezier = "almostLinear" })
-- Анимация столов задаётся в ws_anim.lua: вертикальный сдвиг с честным
-- направлением (21.09.2026). Раньше здесь стоял fade — Hyprland считал
-- направление по номерам столов, а порядок у нас свой, и сдвиг врал; в 0.56.2
-- направление можно задать явно, подробности — в шапке ws_anim.lua.
hl.animation({ leaf = "zoomFactor", enabled = true, speed = 7, bezier = "quick" })

-- Перестановка окон в ленте (SUPER+ALT+J/K) своей пружиной: открытие окна
-- может быть мягким, а перестановка должна ощущаться точной.
hl.animation({ leaf = "windowsMove", enabled = true, speed = 6, spring = "snappy" })

-- Карманный стол (SUPER+ALT+Q) выезжает сверху и уходит обратно: ящик, а не
-- подмена экрана. Вертикаль выбрана намеренно — порядок столов в баре свой
-- (см. выше), и горизонтальное движение врало бы про сторону.
hl.animation({ leaf = "specialWorkspace", enabled = true, speed = 4, bezier = "easeOutQuint", style = "slidefadevert 20%" })
hl.animation({ leaf = "specialWorkspaceIn", enabled = true, speed = 4, bezier = "easeOutQuint", style = "slidefadevert 20%" })
hl.animation({ leaf = "specialWorkspaceOut", enabled = true, speed = 3, bezier = "almostLinear", style = "slidefadevert 20%" })

-- Градиент рамки активного окна медленно вращается: speed здесь — время
-- полного оборота в десятых долях секунды (150 = 15 с). Только для активного
-- окна: у неактивного рамка прозрачная.
hl.animation({ leaf = "borderangle", enabled = true, speed = 100, bezier = "linear", style = "loop" })

-- rofi (лаунчер WIN+SPACE): «стекло» — размытие под полупрозрачной панелью —
-- и мягкое появление. Поверхность rofi на весь экран и прозрачная вокруг
-- панели (см. ~/.config/rofi/config.rasi), поэтому ignore_alpha 0.3: прозрачную
-- часть не размываем, размывается только сама панель (её фон на 85%).
-- Проверено 11.09.2026 этим же вызовом через hyprctl eval.
-- Лента обоев (SUPER+W, scripts/wallpaper_picker.py): фон под полупрозрачной
-- карточкой размывается, появление — мягкое, как у rofi (19.09.2026).
hl.layer_rule({
	name = "wallpapers-glass",
	match = { namespace = "^jarvis-wallpapers$" },
	blur = true,
	ignore_alpha = 0.3,
	animation = "popin 92%",
})

-- Попапы eww (громкость, раскладка, календарь, плееры) всплывают так же, как
-- rofi и лента обоев: eww не задаёт своего имени слоя, поэтому правило ловит
-- весь gtk-layer-shell — кроме бара и уведомлений, у них имена свои.
hl.layer_rule({
	name = "eww-popin",
	match = { namespace = "^gtk-layer-shell$" },
	animation = "popin 92%",
})

-- Обзор столов (SUPER+G, scripts/overview.py): то же «стекло», что у ленты обоев.
-- Появление обзор рисует сам (плавный отъезд), поэтому у слоя — простой fade.
hl.layer_rule({
	name = "overview-glass",
	match = { namespace = "^jarvis-overview$" },
	blur = true,
	ignore_alpha = 0.3,
	animation = "fade",
})

hl.layer_rule({
	name = "rofi-glass",
	match = { namespace = "^rofi$" },
	blur = true,
	ignore_alpha = 0.3,
	animation = "popin 90%",
})
