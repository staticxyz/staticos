-- Клавиши ленты (раскладка scrolling, как в Niri) и переход фокуса.
-- Подключается из keybindings.lua. Раскладка проверяется в МОМЕНТ НАЖАТИЯ:
-- переключатель «Раскладка окон» в «Настройках» (scripts/layout_mode.py)
-- меняет её на ходу, и клавиши подстраиваются сами.

local function ribbon()
    return hl.get_config("general.layout") == "scrolling"
end

-- Отправить команду ленты; если Hyprland её не принял — второй вариант.
-- hl.dispatch при неудаче не падает, а возвращает { ok = false, error = … }
-- (проверено 11.09.2026), поэтому неудачная попытка ничего не делает.
local function layout(cmd, alt)
    local r = hl.dispatch(hl.dsp.layout(cmd))
    if alt and type(r) == "table" and r.ok == false then
        hl.dispatch(hl.dsp.layout(alt))
    end
end

-- Окна, развёрнутые через SUPER+= (адрес -> true). Уход фокуса на соседа
-- сворачивает развёрнутое окно (misc:on_focus_under_fullscreen = 2), и без
-- этой памяти при возврате оно оставалось колонкой на шаг уже полной ширины —
-- заметил пользователь 13.09.2026. ribbon_focus разворачивает такое окно снова,
-- SUPER+− снимает пометку.
--
-- 14.09.2026: ключ — адрес, но запоминаются ещё процесс и начальный заголовок.
-- Hyprland отдаёт адреса закрытых окон новым (проверено: пробное окно получило
-- ровно адрес недавно закрытого блокнота), и новое окно на чистом столе
-- «наследовало» пометку и разворачивалось само при SUPER+←/→. Теперь пометка
-- снимается при закрытии окна и сверяется с процессом и начальным заголовком.
--
-- 17.09.2026: память — в файле. Hyprland перечитывает конфиг при любой правке
-- его файлов, Lua начинается заново, и таблица пустела: развёрнутое окно после
-- этого сворачивалось уходом фокуса и назад уже не разворачивалось (просьба: -- «иногда воспроизводится»). Проверка по процессу и заголовку отсекает чужие
-- адреса после перезапуска программ.
local MAX_FILE = os.getenv("HOME") .. "/.cache/hypr-ribbon-maximized"
local maximized = {}

do
    local f = io.open(MAX_FILE, "r")
    if f then
        for line in f:lines() do
            local addr, pid, title = line:match("^(%S+)\t(%d+)\t(.*)$")
            if addr then maximized[addr] = { pid = tonumber(pid), initial_title = title } end
        end
        f:close()
    end
end

local function save_maximized()
    local f = io.open(MAX_FILE .. ".tmp", "w")
    if not f then return end
    for addr, m in pairs(maximized) do
        f:write(string.format("%s\t%d\t%s\n", addr, tonumber(m.pid) or 0,
            tostring(m.initial_title or ""):gsub("[\t\n]", " ")))
    end
    f:close()
    os.rename(MAX_FILE .. ".tmp", MAX_FILE)
end

local function remember(w)
    maximized[w.address] = { pid = w.pid, initial_title = w.initial_title }
    save_maximized()
end

-- Окна, развёрнутые в момент загрузки конфига (режим 1 ставит только SUPER+=),
-- — тоже в память: иначе правка, случившаяся до появления файла, их теряет.
do
    local ok, list = pcall(function() return hl.get_windows() end)
    local added = false
    if ok and type(list) == "table" then
        for _, w in ipairs(list) do
            if not w.floating and (w.fullscreen or 0) == 1 and not maximized[w.address] then
                maximized[w.address] = { pid = w.pid, initial_title = w.initial_title }
                added = true
            end
        end
    end
    if added then save_maximized() end
end

local function forget(addr)
    if maximized[addr] then
        maximized[addr] = nil
        save_maximized()
    end
end

-- id стола -> адреса обычных окон слева направо (заполняет ribbon_view_tick,
-- пока на столе нет развёрнутых окон; нужен и ribbon_focus, и закрытию окна).
local column_order = {}

-- Когда окно последний раз было активным (просто счётчик по порядку).
-- В колонке ленты может стоять несколько окон друг над другом; при переходе в
-- такую колонку Hyprland выбирает окно по геометрии, и с телеграма слева
-- фокус всегда уходил в нижнее (19.09.2026: «постоянно переходит в
-- терминал с покемоном, а не в appmem сверху»). Выбираем сами — то окно
-- колонки, в котором пользователь был последним, как в Niri.
local focus_seq, last_focus = 0, {}

local function remembered(w)
    local m = w and maximized[w.address]
    return m ~= nil and m.pid == w.pid and m.initial_title == w.initial_title
end

-- Развернуть / свернуть КОНКРЕТНОЕ окно (по адресу, а не активное).
local function set_max(w, on)
    hl.dispatch(hl.dsp.window.fullscreen({ mode = "maximized",
                                           action = on and "set" or "unset",
                                           layout_aware = false,
                                           window = "address:" .. w.address }))
end

-- Окна стола, где стоит окно w.
local function workspace_windows_of(w)
    local ok, list = pcall(function() return hl.get_workspace_windows(w.workspace) end)
    if ok and type(list) == "table" then return list end
    return {}
end

-- Поднять плавающие окна стола окна w над развёрнутым.
-- Зачем: развёрнутое окно Hyprland рисует ПОВЕРХ плавающих, и плавающее
-- «пропадало» из виду, стоило развернуть окно под ним (14.09.2026). Сначала
-- это решалось сворачиванием развёрнутого окна; пользователь попросил не сворачивать.
-- Опыт на пустом столе 14 (цветные окна, пиксель в центре плавающего):
-- после разворота плавающее спрятано, после alter_zorder "top" — видно, и
-- остаётся видно, даже когда фокус возвращается на развёрнутое окно.
-- Закрепление (pin) тоже держит поверх, но тащит окно на все столы — не взято.
local function raise(o)
    hl.dispatch(hl.dsp.window.alter_zorder({ mode = "top", window = "address:" .. o.address }))
end

local function raise_floats_on(w)
    for _, o in ipairs(workspace_windows_of(w)) do
        if o.floating and o.mapped and not o.hidden then
            raise(o)
        end
    end
end

-- SUPER+←/→/↑/↓: фокус В ПРЕДЕЛАХ МОНИТОРА. Обычный переход направлением на
-- краю стола уходит на соседний монитор (binds.window_direction_monitor_fallback)
-- — это и мешало, фокус случайно перескакивал. Здесь перескок выключается
-- только на время этого перехода и сразу возвращается, поэтому остальные
-- клавиши направлением (SUPER+ALT+стрелки и т. д.) ведут себя как раньше.
-- Глобальная — её зовёт и колёсико над картой ленты в баре.
-- Есть ли на столе текущего окна обычное окно левее (dir = "left") или
-- правее (dir = "right"). Считается по левому краю окон: колонки ленты стоят
-- в ряд, и у соседней колонки левый край строго меньше или больше.
function has_column_side(w, dir)
    if not w or not w.at then return false end
    -- Окна того стола, где стоит САМО окно, а не «активного». Когда фокус на
    -- спецстоле (ALT+E уносит окно туда и показывает его), hl.get_active_workspace()
    -- по-прежнему отдаёт обычный стол под ним, и сосед искался среди чужих окон:
    -- с крайнего левого окна спецстола SUPER+→ молчал, если на обычном столе
    -- правее никого не было (14.09.2026; воспроизведено на столе 14 —
    -- scratchpad/special_s3_test.py: соседи L/R = false/false при окне справа).
    local list = workspace_windows_of(w)
    local x = w.at.x
    for _, o in ipairs(list) do
        if o.address ~= w.address and not o.floating and o.at then
            if dir == "left" and o.at.x < x - 1 then return true end
            if dir == "right" and o.at.x > x + 1 then return true end
        end
    end
    return false
end

-- ПАРА ОКОН ВМЕСТО ЦЕНТРА (19.09.2026). В режиме «окно по центру»
-- (scrolling.focus_fit_method = 0, Настройки → Окна) Hyprland центрирует любое
-- окно, и два узких окна, которые целиком помещаются рядом, показывались
-- половинками по бокам (стол 9 пользователя: окна 900 и 900 при экране 1920).
-- Перед переходом считаем: помещается ли цель вместе с соседом? Если да —
-- ведём переход способом fit (минимальный сдвиг, пара видна целиком), иначе
-- оставляем центр. Сдвиг ленты командой move не годится: принят, но ленту не
-- двигает (проверено 19.09.2026).
local function gap_out()
    local ok, g = pcall(hl.get_config, "general.gaps_out")
    if ok and type(g) == "number" then return g end
    if ok and type(g) == "table" then return tonumber(g.left or g[4] or g[1]) or 20 end
    return 20
end

local function tiled_columns(w)
    local cols = {}
    for _, o in ipairs(workspace_windows_of(w)) do
        if not o.floating and o.at and o.size and (o.fullscreen or 0) == 0 then cols[#cols + 1] = o end
    end
    table.sort(cols, function(a, b) return a.at.x < b.at.x end)
    return cols
end

-- ПАРА ОКОН ВМЕСТО ЦЕНТРА (19.09.2026, пользователь про стол 9: «окна одного размера,
-- помещаются в один экран, а показываются в центре»). Центрировать узкое окно
-- незачем: рядом целиком помещается соседнее, и центр прячет обоих наполовину.
-- Если окно вместе с соседом влезает в экран — ведём переход способом fit
-- (сдвиг минимальный, пара видна целиком и у края пустоты не остаётся).
-- Широкое окно, рядом с которым сосед не помещается, по-прежнему по центру.
-- Пара — это окно, С КОТОРОГО уходим, и то, НА КОТОРОЕ идём. Сначала я брал
-- любое окно стола, и выходило неверно (19.09.2026): крайние окна
-- «цеплялись» за дальних узких соседей и не центрировались, а окно рядом с
-- развёрнутым или расширенным соседом тоже не центрировалось.
--
-- Мало «помещается» — пара должна ЗАПОЛНЯТЬ экран: после неё остаётся меньше
-- PAIR_SLACK, то есть соседнему окну показаться уже негде. Доля ширины (85%)
-- оказалась слишком мягкой: на столе 3 пара 915+712 — это 88%, и крайнее окно
-- не центрировалось, хотя справа оставалось 223 px (19.09.2026).
-- Замеры: 900+900 — остаток 50 px (центр не нужен), 915+712 — 223 px, на
-- карманном столе 900+524 — 426 px (центр нужен).
local PAIR_SLACK = 100

local function pair_fits(target, other)
    local mon = target and target.monitor
    if not (mon and type(mon.width) == "number" and target.size
            and other and other.size and not other.floating
            and other.address ~= target.address) then
        return false
    end
    if (other.fullscreen or 0) > 0 then return false end   -- развёрнутый занимает экран
    local room = mon.width - gap_out() * 2
    local gap_between = 30      -- gaps_in 15 с обеих сторон
    local pair = target.size.x + other.size.x + gap_between
    return pair <= room + 1 and room - pair < PAIR_SLACK
end

-- Перевести фокус на окно target: пара помещается — способом fit (оба окна
-- целиком), иначе обычным путём (Hyprland поставит по центру). true — сделано
-- здесь. Правило «крайние окна прижимать к краю» убрано 19.09.2026 по просьбе
-- пользователя: крайние центрируются как все.
function ribbon_focus_clamped(target, from)
    if not target or remembered(target) then return false end
    if hl.get_config("scrolling.focus_fit_method") ~= 0 or not pair_fits(target, from) then
        return false
    end
    hl.config({ scrolling = { focus_fit_method = 1 } })
    hl.dispatch(hl.dsp.focus({ window = "address:" .. target.address }))
    hl.config({ scrolling = { focus_fit_method = 0 } })
    return true
end

-- Соседняя колонка слева / справа от окна w (ближайшая по x).
-- Ближайшая колонка слева / справа: сначала её левый край, потом окно внутри —
-- то, что было активным позже других (в колонке их может быть несколько).
local function column_neighbour(w, dir)
    local cols = tiled_columns(w)
    local edge
    for _, o in ipairs(cols) do
        if o.address ~= w.address then
            if dir == "left" and o.at.x < w.at.x - 1 and (not edge or o.at.x > edge) then edge = o.at.x end
            if dir == "right" and o.at.x > w.at.x + 1 and (not edge or o.at.x < edge) then edge = o.at.x end
        end
    end
    if not edge then return nil end
    local best
    for _, o in ipairs(cols) do
        if math.abs(o.at.x - edge) <= 1 and o.address ~= w.address then
            local seen, seen_best = last_focus[o.address] or 0, best and (last_focus[best.address] or 0)
            -- Никто в колонке ещё не был активным — берём верхнее окно.
            if not best or seen > seen_best
               or (seen == seen_best and o.at and best.at and o.at.y < best.at.y) then
                best = o
            end
        end
    end
    return best
end

function ribbon_focus(dir)
    local cur = hl.get_active_window()
    local before = cur and cur.address

    -- Активного окна нет вовсе (так бывало после SUPER+N поверх развёрнутого
    -- окна, 14.09.2026): переход направлением от «ничего» Hyprland не делает,
    -- и стрелки молчали. Берём окно стола — развёрнутое, если есть, иначе
    -- первое обычное.
    if not cur and ribbon() then
        local ws = hl.get_active_workspace()
        local ok, list = pcall(function() return hl.get_workspace_windows(ws) end)
        if ws and ok and type(list) == "table" then
            local pick
            for _, o in ipairs(list) do
                if o.mapped and not o.hidden and not o.floating then
                    if (o.fullscreen or 0) > 0 then pick = o break end
                    pick = pick or o
                end
            end
            if pick then
                hl.dispatch(hl.dsp.focus({ window = "address:" .. pick.address }))
            end
        end
        return
    end

    -- У края ленты — ничего не делать. Сам Hyprland в ленте, не найдя окна в
    -- заданном направлении, всё равно переводит фокус на ближайшее окно стола:
    -- с самого правого окна SUPER+→ уводил на соседнее СЛЕВА, с самого левого
    -- SUPER+← — на соседнее справа. Изоляционный опыт 14.09.2026 на пустом
    -- столе: так ведёт себя голый hl.dsp.focus, при любом wrap_focus и с
    -- выключенным перескоком на монитор. Поэтому до перехода проверяем, есть ли
    -- сосед в эту сторону; плавающих окон проверка не касается.
    -- Развёрнутое окно: геометрии не верим. Hyprland отдаёт ему координаты всего
    -- экрана, и если лента не прокручена к его колонке, соседи стоят под ним с
    -- тем же левым краем — has_column_side не находил никого слева, SUPER+←/→
    -- молчали (стол 4 пользователя, 14.09.2026). Сама лента порядок колонок знает:
    -- "focus l|r" с выключенным закольцовыванием переходит к соседу и у края
    -- ничего не делает (опыт на столе 14: и в застрявшем состоянии, и у краёв).
    if ribbon() and (dir == "left" or dir == "right") and cur and not cur.floating
       and (cur.fullscreen or 0) == 1 then
        -- Режим «по центру»: уходим с развёрнутого окна на КРАЙНЮЮ колонку —
        -- без пустоты у края (19.09.2026, просьба: «не работает, когда рядом
        -- развёрнутое окно»). Координаты здесь врут, поэтому порядок колонок —
        -- из памяти ленты. fit держится 150 мс: развёрнутое окно сворачивается
        -- и лента пересчитывается чуть позже самого перехода.
        local fit_prev = hl.get_config("scrolling.focus_fit_method")
        local use_fit = false
        local order = cur.workspace and column_order[cur.workspace.id]
        if fit_prev == 0 and order then
            local idx
            for i, addr in ipairs(order) do if addr == cur.address then idx = i end end
            local ti = idx and (dir == "left" and idx - 1 or idx + 1)
            if ti and ti >= 1 and ti <= #order then
                local tw
                for _, o in ipairs(workspace_windows_of(cur)) do
                    if o.address == order[ti] then tw = o end
                end
                -- Уходим с РАЗВЁРНУТОГО окна: пара с ним никогда не помещается,
                -- поэтому цель центрируется (pair_fits вернёт false).
                use_fit = tw ~= nil and not tw.floating and not remembered(tw)
                       and pair_fits(tw, cur)
            end
        end
        if use_fit then hl.config({ scrolling = { focus_fit_method = 1 } }) end
        local wrap = hl.get_config("scrolling.wrap_focus")
        if wrap == nil then wrap = true end
        hl.config({ scrolling = { wrap_focus = false } })
        hl.dispatch(hl.dsp.layout(dir == "left" and "focus l" or "focus r"))
        hl.config({ scrolling = { wrap_focus = wrap } })
        if use_fit then
            hl.timer(function()
                if hl.get_config("scrolling.focus_fit_method") == 1 then
                    hl.config({ scrolling = { focus_fit_method = fit_prev } })
                end
            end, { timeout = 150, type = "oneshot" })
        end
        return
    end

    if ribbon() and (dir == "left" or dir == "right") and cur and not cur.floating
       and not has_column_side(cur, dir) then
        return
    end

    -- Режим «по центру»: у краёв ленты — без пустоты (см. ribbon_focus_clamped).
    if ribbon() and (dir == "left" or dir == "right") and cur and not cur.floating
       and (cur.fullscreen or 0) == 0 then
        -- Переход по адресу выбранного окна, а не направлением: так фокус
        -- попадает именно в то окно колонки, где пользователь был последним.
        local target = column_neighbour(cur, dir)
        if target then
            if not ribbon_focus_clamped(target, cur) then
                hl.dispatch(hl.dsp.focus({ window = "address:" .. target.address }))
            end
            return
        end
    end

    local prev = hl.get_config("binds.window_direction_monitor_fallback")
    if prev == nil then prev = true end
    hl.config({ binds = { window_direction_monitor_fallback = false } })
    hl.dispatch(hl.dsp.focus({ direction = dir }))
    hl.config({ binds = { window_direction_monitor_fallback = prev } })

    -- Запасной путь для ленты. Когда колонка растянута почти на весь экран
    -- (или развёрнута), соседние колонки целиком за краем монитора, и поиск
    -- «окно в направлении» их не видит. Тогда просим саму ленту перейти к
    -- соседу. Срабатывает ТОЛЬКО если обычный переход фокус не сдвинул.
    --
    -- Закольцовывание (scrolling.wrap_focus) на время шага выключаем, иначе с
    -- крайней колонки команда уводила бы на противоположный конец ленты.
    --
    -- Только "focus l" / "focus r" — так написано в вики Hyprland. Раньше здесь
    -- перебирались ещё "focus left/prev" и "focus right/next": у края ленты
    -- верный "focus l" законно не срабатывает (левее ничего нет), перебор шёл
    -- дальше, и "focus prev" принимался, но означал «предыдущее окно по истории
    -- фокуса» — фокус отскакивал с крайнего окна на соседнее (пошаговая
    -- трасса на пустом столе, 13.09.2026). У края теперь просто ничего не
    -- происходит, как у обычного перехода.
    --
    -- 13.09.2026, вторая правка: у самого края фокус всё равно отскакивал на
    -- соседнее окно даже с одним "focus l" — что именно делает эта команда на
    -- краю ленты, выяснить не удалось. Поэтому край теперь определяется по
    -- геометрии: запасной переход зовётся, только если на этом столе ЕСТЬ
    -- обычное (не плавающее) окно левее или правее текущего. Нет такого —
    -- ничего не делаем, как обычный переход до всех этих правок.
    if ribbon() and (dir == "left" or dir == "right") then
        local after = hl.get_active_window()
        if after and after.address == before and has_column_side(after, dir) then
            local wrap = hl.get_config("scrolling.wrap_focus")
            if wrap == nil then wrap = true end
            hl.config({ scrolling = { wrap_focus = false } })
            hl.dispatch(hl.dsp.layout(dir == "left" and "focus l" or "focus r"))
            hl.config({ scrolling = { wrap_focus = wrap } })
        end
    end
end
for _, d in ipairs({ "left", "right", "up", "down" }) do
    hl.bind("SUPER + " .. d, function() ribbon_focus(d) end)
end

-- SUPER+− / SUPER+=: колонка уже / шире на 10% рабочей ширины, как
-- Mod+Minus / Mod+Equal в Niri. Шаг относительный (colresize ±0.1) —
-- проверено 11.09.2026: +0.1 дал 915 → 1103 px, −0.1 вернул 915. Держать
-- клавишу можно (repeating). Пределы — чтобы не раздуть колонку шире экрана
-- и не сжать в щель. (До этого была подкарта SUPER+R → цифра; заменена по
-- просьбе на эти клавиши.) Глобальная — чтобы её можно было проверить из
-- hyprctl eval.
function ribbon_width(delta)
    if not ribbon() then return end
    local w = hl.get_active_window()
    if not w or w.floating then return end

    -- Развёрнутое окно: SUPER+− возвращает его в ленту, SUPER+= ничего не делает.
    if (w.fullscreen or 0) > 0 then
        if delta < 0 then
            forget(w.address)
            set_max(w, false)
        end
        return
    end

    local mon = w.monitor or hl.get_active_monitor()
    local sz = w.size
    local ww = type(sz) == "table" and (sz.x or sz.w or sz[1]) or sz
    if mon and mon.width and type(ww) == "number" then
        local frac = ww / mon.width
        -- Последний шаг SUPER+= — развернуть окно на всю рабочую область.
        --
        -- Почему не просто «колонка на 100%» (всё замерено 12.09.2026 на
        -- пустом столе 14): колонка шире 1.0 не бывает и всегда держит место
        -- под зазор до соседа (gaps_in 15 px), а у краёв ленты вид дальше не
        -- прокручивается — ни center, ни move ±px отступы не выравнивают:
        -- 25/40 у первой колонки, 35/20 у последней.
        --
        -- layout_aware = false ОБЯЗАТЕЛЕН. По умолчанию лента берёт
        -- развёртывание на себя («layout-handled fullscreen» из вики): окно
        -- помечается развёрнутым, но геометрия колонки не меняется, а при
        -- уходе фокуса пометка остаётся. С false работает обычное
        -- развёртывание Hyprland: 1870 px, поля 20/20 — как одинокое окно, а
        -- SUPER+← на соседа само сворачивает его (misc:on_focus_under_fullscreen = 2).
        if delta > 0 and frac >= 0.85 then
            remember(w)
            set_max(w, true)
            raise_floats_on(w)   -- разворот кладёт окно поверх плавающих
            return
        end
        if delta < 0 and frac <= 0.22 then return end   -- уже узкая
    end
    hl.dispatch(hl.dsp.layout(string.format("colresize %+.1f", delta)))
end
hl.bind("SUPER + minus", function() ribbon_width(-0.1) end, { repeating = true })
hl.bind("SUPER + equal", function() ribbon_width(0.1) end, { repeating = true })

-- Временно поменять настройки ленты на время fn() и вернуть как было.
-- Нужно проходам «до края»: у ленты включено закольцовывание (wrap_focus и
-- wrap_swapcol = true), и шаг с первой колонки влево уводит на последнюю —
-- повтор ходил бы по кругу.
local function with_scrolling(opts, fn)
    local saved = {}
    for k in pairs(opts) do
        local v = hl.get_config("scrolling." .. k)
        if v == nil then v = true end
        saved[k] = v
    end
    hl.config({ scrolling = opts })
    fn()
    hl.config({ scrolling = saved })
end

-- SUPER+ALT+←/→: в ленте переставить КОЛОНКУ целиком (в Niri — Mod+Ctrl+←/→).
-- Обычный window.move на ленте вкладывает окно в соседнюю колонку — это и
-- удивило при первой пробе. В классике — прежнее перемещение окна.
-- Написание направления у swapcol (l/r или prev/next) без перестановки чужих
-- окон проверить было нельзя — отсюда запасной вариант.
--
-- 14.09.2026: закольцовывание (wrap_swapcol) на время шага выключено. С ним
-- крайняя правая колонка по SUPER+ALT+→ уезжала в НАЧАЛО ленты, а крайняя
-- левая по SUPER+ALT+← — в конец (заметил пользователь). У края теперь ничего не
-- происходит — как у SUPER+←/→.
function ribbon_swap(dir)
    if ribbon() then
        with_scrolling({ wrap_swapcol = false }, function()
            if dir == "left" then
                layout("swapcol l", "swapcol prev")
            else
                layout("swapcol r", "swapcol next")
            end
        end)
    else
        hl.dispatch(hl.dsp.window.move({ direction = dir }))
    end
end
hl.bind("SUPER + ALT + right", function() ribbon_swap("right") end)
hl.bind("SUPER + ALT + left", function() ribbon_swap("left") end)

local function active_addr()
    local w = hl.get_active_window()
    return w and w.address
end

local function active_x()
    local w = hl.get_active_window()
    local at = w and w.at
    return type(at) == "table" and (at.x or at[1]) or at
end

-- SUPER+Home / SUPER+End: к первой / последней колонке, в пределах монитора
-- (в Niri — Mod+Home / Mod+End). Шагает тем же ribbon_focus, пока фокус не
-- перестанет меняться; не больше 50 шагов на всякий случай. В классике —
-- к самому левому / правому окну монитора.
function ribbon_edge_focus(dir)
    with_scrolling({ wrap_focus = false }, function()
        for _ = 1, 50 do
            local before = active_addr()
            ribbon_focus(dir)
            local after = active_addr()
            if not after or after == before then break end
        end
    end)
end
hl.bind("SUPER + Home", function() ribbon_edge_focus("left") end)
hl.bind("SUPER + End", function() ribbon_edge_focus("right") end)

-- SUPER+ALT+Home / SUPER+ALT+End: отправить текущую колонку в начало /
-- конец ленты (в Niri — Mod+Ctrl+Home / End). Переставляет колонку, пока
-- Hyprland не ответит «дальше некуда» (ok = false) или окно не перестанет
-- сдвигаться. Написание направления у swapcol (l/r или prev/next) выясняется
-- на первом шаге — как и в SUPER+ALT+←/→, без проверки на чужих окнах.
function ribbon_edge_move(dir)
    if not ribbon() then return end
    local tries = dir == "left" and { "swapcol l", "swapcol prev" }
                                 or { "swapcol r", "swapcol next" }
    -- Шагов не больше, чем окон на столе: колонок всегда не больше. Раньше
    -- цикл останавливался ещё и по «окно не сдвинулось» — сравнивал at.x до и
    -- после шага. Это и ломало перемещение: Hyprland в этот момент проигрывает
    -- анимацию и отдаёт прежние координаты, поэтому колонка уезжала ровно на
    -- одну позицию (замечено 12.09.2026). Теперь останавливаемся только по
    -- ответу «дальше некуда» (ok = false).
    local ws = hl.get_active_workspace()
    local limit = math.max(2, (ws and ws.windows) or 20)
    with_scrolling({ wrap_swapcol = false }, function()
        local cmd
        for _ = 1, limit do
            local ok = false
            for _, c in ipairs(cmd and { cmd } or tries) do
                local r = hl.dispatch(hl.dsp.layout(c))
                if not (type(r) == "table" and r.ok == false) then
                    cmd, ok = c, true
                    break
                end
            end
            if not ok then break end
        end
    end)
end
hl.bind("SUPER + ALT + Home", function() ribbon_edge_move("left") end)
hl.bind("SUPER + ALT + End", function() ribbon_edge_move("right") end)

-- SUPER+[ / SUPER+]: вложить окно в соседнюю колонку или вынуть его в свою
-- (в Niri — Mod+[ / Mod+]). Hyprland ждёт направление prev/next —
-- проверено по его ответу на неверный аргумент.
hl.bind("SUPER + bracketleft", function()
    if ribbon() then layout("consume_or_expel prev") end
end)
hl.bind("SUPER + bracketright", function()
    if ribbon() then layout("consume_or_expel next") end
end)

-- Вертикальное движение окна: SUPER + CTRL + вверх/вниз.
-- Раньше эта пара создавала и удаляла столы — она переехала на SUPER+SHIFT.
--
-- В scrolling колонка держит НЕСКОЛЬКО окон стопкой (SUPER+] закидывает окно в
-- соседнюю колонку, SUPER+[ выдёргивает обратно), поэтому обе оси работают на
-- каждом столе сразу: колонки листаются влево-вправо, окна внутри колонки
-- стоят друг под другом. Эта пара двигает окно по стопке вверх/вниз; на столе
-- с direction = "down" (стол 10) — вдоль самой ленты.
--
-- Почему с проверкой соседа, а не просто dispatch: когда двигать некуда (окно
-- уже сверху или снизу стопки), диспетчер отвечает "no target (invalid
-- direction?)", и Hyprland показывает красное «Runtime error in lua». pcall тут
-- не спасает — hl.dispatch не бросает ошибку, а возвращает { ok = false }, и
-- уведомление рисует сам Hyprland. Поэтому сначала ищем соседа по геометрии и
-- дёргаем диспетчер, только если он есть.
local function has_neighbour(dir)
    local me = hl.get_active_window()
    if me == nil or me.floating then return true end
    -- Стол самого окна, а не «активный» — см. has_column_side (спецстолы).
    local list = workspace_windows_of(me)
    if #list == 0 then return true end
    local x1, y1 = me.at.x, me.at.y
    local x2, y2 = x1 + me.size.x, y1 + me.size.y
    for _, w in ipairs(list) do
        if w.address ~= me.address and not w.floating then
            local ox1, oy1 = w.at.x, w.at.y
            local ox2, oy2 = ox1 + w.size.x, oy1 + w.size.y
            if ox1 < x2 and x1 < ox2 then           -- колонки пересекаются по ширине
                if dir == "up" and oy1 < y1 then return true end
                if dir == "down" and oy2 > y2 then return true end
            end
        end
    end
    return false
end

function ribbon_vmove(dir)
    if not has_neighbour(dir) then return end
    hl.dispatch(hl.dsp.window.move({ direction = dir }))
end

-- 14.09.2026: SUPER+CTRL+вверх/вниз вернулись к созданию/удалению стола
-- (keybindings.lua), поэтому движение окна по вертикали осталось без клавиш.
-- Функция ribbon_vmove сохранена, сейчас ни на что не назначена.


-- SUPER+V: плавающее окно (привязано в keybindings.lua).
-- Развёрнутое через SUPER+= окно Hyprland рисует поверх плавающих. Поэтому:
-- если переводимое окно само развёрнуто — сначала сворачиваем его; после
-- перевода поднимаем новое плавающее наверх, развёрнутые окна стола остаются
-- развёрнутыми (14.09.2026).
function ribbon_toggle_float()
    local w = hl.get_active_window()
    if not w then return end
    if (w.fullscreen or 0) > 0 then
        forget(w.address)
        set_max(w, false)
    end
    hl.dispatch(hl.dsp.window.float({ action = "toggle" }))
    local now = hl.get_active_window()
    if now and now.floating then
        raise(now)
    end
end

-- Закрытое окно забываем: его адрес достанется новому окну.
hl.on("window.close", function(w)
    if w and w.address then forget(w.address) end
end)

-- Плавающее окно открылось или получило фокус — поднимаем его над развёрнутым.
-- Обычное окно, запомненное как развёрнутое, при фокусе (клавишами ИЛИ мышью)
-- разворачиваем снова и поднимаем плавающие окна стола над ним.
local function on_focus_or_open(w)
    if not w or not w.address or not ribbon() then return end
    if w.floating then
        raise(w)
    elseif remembered(w) and (w.fullscreen or 0) == 0 then
        -- Сначала прокрутить ленту к колонке окна. Фокус по адресу (SUPER+Tab,
        -- клик в бар, обработчики) на окно, чья колонка за краем, лентой не
        -- прокручивается; разворот сразу оставлял соседние колонки на экране
        -- ПОД развёрнутым окном: карта в баре видела две точки из трёх, а
        -- SUPER+←/→ молчали (стол 4 пользователя, 14.09.2026). Опыт на столе 14:
        -- не застревает только с "center" перед разворотом; разворот таймером
        -- и "fit" — застревают.
        hl.dispatch(hl.dsp.layout("center"))
        set_max(w, true)
        raise_floats_on(w)
        -- Переход С ПЛАВАЮЩЕГО окна на такое окно после разворота оставлял
        -- стол вовсе без фокуса (активного окна нет, клавиши никуда не шли) —
        -- опыт 14.09.2026 на столе 14. Возвращаем фокус по адресу.
        hl.dispatch(hl.dsp.focus({ window = "address:" .. w.address }))
    end
end

-- Последнее открытое плавающее окно: адрес, процесс, время (с).
local last_float = nil

hl.on("window.open", function(w)
    if w and w.address and w.floating then
        last_float = { address = w.address, pid = w.pid, t = os.time() }
    end
    on_focus_or_open(w)
    -- Новое плавающее окно должно получить фокус. Сразу из обработчика это не
    -- выходит: событие window.active приходит, но пока окно появляется,
    -- Hyprland молча возвращает фокус окну под ним (через 150 мс фокус ещё
    -- отбирался, через 400 мс держался — журнал 14.09.2026). Поэтому
    -- несколько попыток таймером; каждая срабатывает, только если фокус
    -- по-прежнему у ОБЫЧНОГО окна того же стола, чтобы не перебить клик или
    -- переход, сделанный за это время.
    --
    -- 19.09.2026: раньше это делалось, только если на столе было развёрнутое
    -- окно — просьба: «если окно среднего размера и на экране два
    -- окна, плавающее не захватывается». Ограничение снято.
    -- Окно-пустышка XWayland (пустые класс и заголовок) пропускается: у него
    -- правило no_focus в workspace.lua, фокус ему не нужен.
    if w and w.address and w.floating and ribbon()
       and not (tostring(w.class or "") == "" and tostring(w.title or "") == "") then
        local addr, ws_id = w.address, w.workspace and w.workspace.id
        for _, ms in ipairs({ 150, 400, 800, 1200 }) do
            hl.timer(function()
                local a = hl.get_active_window()
                local stolen = a and a.address ~= addr and not a.floating
                               and a.workspace and a.workspace.id == ws_id
                if stolen then
                    hl.dispatch(hl.dsp.focus({ window = "address:" .. addr }))
                end
            end, { timeout = ms, type = "oneshot" })
        end
    end
end)
-- Стол без фокуса. SUPER+N поверх развёрнутого окна: блокнот открывает уже
-- работающий mousepad по D-Bus, фокус переходит на новое окно, а следом
-- Hyprland присылает window.active с пустым окном — активного окна нет,
-- клавиши никуда не идут, стрелки молчат (опыт 14.09.2026 на столе 14,
-- scratchpad/notepadmax_test.py). Причину пустого события установить не
-- удалось. Если в ближайшие секунды открывалось плавающее окно и оно на
-- текущем столе — возвращаем фокус ему; попытки таймером, каждая только если
-- фокуса по-прежнему нет.
local function recover_focus()
    if hl.get_active_window() or not ribbon() or not last_float then return end
    if os.time() - last_float.t > 10 then return end
    local ws = hl.get_active_workspace()
    local ok, list = pcall(function() return hl.get_workspace_windows(ws) end)
    if not ws or not ok or type(list) ~= "table" then return end
    for _, o in ipairs(list) do
        if o.address == last_float.address and o.pid == last_float.pid
           and o.mapped and not o.hidden then
            hl.dispatch(hl.dsp.focus({ window = "address:" .. o.address }))
            return
        end
    end
end

hl.on("window.active", function(w)
    if w and w.address then
        focus_seq = focus_seq + 1
        last_focus[w.address] = focus_seq
        on_focus_or_open(w)
        return
    end
    for _, ms in ipairs({ 100, 400, 900 }) do
        hl.timer(recover_focus, { timeout = ms, type = "oneshot" })
    end
end)

-- Наведение курсора на плавающее окно поверх развёрнутого забирает фокус.
-- Когда фокус у развёрнутого окна, Hyprland блокирует ввод остальным окнам
-- стола (INPUT_BLOCK_BELOW_FULLSCREEN): у плавающего accepts_input = false,
-- клики и наведение уходят развёрнутому, и штатный перехват фокуса при
-- наведении (input:float_switch_override_focus = 1) не срабатывает — просьба: -- «кликаю обратно в браузер, и это окно уже не могу трогать никак» (14.09.2026).
-- Вернуть ввод без фокуса не вышло (опыты на столе 14): set_prop
-- allowed_over_fullscreen ничего не меняет, закрепление помогает только пока
-- окно закреплено, а постоянно закреплённое уезжало бы на другие столы.
--
-- Поэтому раз в 100 мс: если курсор СДВИНУЛСЯ и стоит над заблокированным
-- плавающим окном, а фокус у развёрнутого — фокус этому окну (развёрнутое не
-- сворачивается). Только при движении: иначе SUPER+стрелки не могли бы вернуть
-- фокус развёрнутому, пока курсор просто лежит над блокнотом. Обратно на
-- развёрнутое фокус при наведении отдаёт уже сам Hyprland.
-- Таймеры сбрасываются при перечитывании конфига (проверено) — не копятся.
-- x, y, st — для проверки из hyprctl eval без движения курсора.
local hover_state = {}
function ribbon_hover_tick(x, y, st)
    st = st or hover_state
    if not ribbon() then return end
    if not x then
        local ok, c = pcall(hl.get_cursor_pos)
        if not ok or type(c) ~= "table" then return end
        x, y = c.x or c[1], c.y or c[2]
    end
    -- Сдвиг курсора вместе со сменой активного окна — не движение мыши:
    -- перевод фокуса командой (SUPER+стрелки, обработчики ленты) переносит
    -- курсор в центр окна, а там часто и лежит плавающее. Без этой проверки
    -- возврат на развёрнутое окно тут же отдавал фокус плавающему (тест
    -- nounmax_test.py на столе 14, 14.09.2026).
    local a = hl.get_active_window()
    local addr = a and a.address
    local focus_changed = st.active ~= addr
    local moved = st.x ~= nil and (x ~= st.x or y ~= st.y) and not focus_changed
    st.x, st.y, st.active = x, y, addr
    if not moved then return end
    if not a or a.floating or (a.fullscreen or 0) == 0 then return end
    for _, o in ipairs(workspace_windows_of(a)) do
        if o.floating and o.mapped and not o.hidden and o.accepts_input == false
           and o.at and o.size
           and x >= o.at.x and x < o.at.x + o.size.x
           and y >= o.at.y and y < o.at.y + o.size.y then
            hl.dispatch(hl.dsp.focus({ window = "address:" .. o.address }))
            return
        end
    end
end
hl.timer(function() ribbon_hover_tick() end, { timeout = 100, type = "repeat" })

-- SUPER+F: полный экран (привязано в keybindings.lua).
-- Выход из полного экрана сбрасывает окну и развёрнутость, заданную SUPER+=:
-- после второго SUPER+F окно возвращалось обычной колонкой (14.09.2026).
-- Поэтому при выходе запомненное развёрнутое окно разворачиваем снова и
-- поднимаем плавающие окна стола над ним.
function ribbon_toggle_fullscreen()
    local w = hl.get_active_window()
    if not w then return end
    local was_full = (w.fullscreen or 0) >= 2
    hl.dispatch(hl.dsp.window.fullscreen({ mode = "fullscreen", action = was_full and "unset" or "set" }))
    if was_full then
        local now = hl.get_active_window()
        if now and remembered(now) and (now.fullscreen or 0) == 0 then
            set_max(now, true)
            raise_floats_on(now)
        end
    end
end

-- ВОЗВРАТ ВИДА ЛЕНТЫ ПОСЛЕ ПОЛНОГО ЭКРАНА (17.09.2026).
-- Полный экран прокручивает ленту к колонке окна, и обратно Hyprland её не
-- возвращает: после выхода окно вставало к левому краю, соседи слева уходили за
-- экран. Так было и с SUPER+F, и с окнами, которые сами открываются в полный
-- экран — просмотр фото в Telegram: закрыл фото, и окна «уехали».
--
-- Как чинится. Раз в 100 мс запоминается спокойный вид стола: активное окно,
-- его x и окно, видимое крайним слева (хотя бы частью — браузер у пользователя
-- обрезан краем экрана). Спокойный — одинаковый 3 проверки подряд и без окон в
-- полном экране: промежуточные кадры открытия окна не запоминаются. Когда окно
-- выходит из полного экрана, и активно то же окно, но
-- сдвинутое, фокус на миг уходит к крайнему левому и возвращается: лента (fit)
-- прокручивается ровно как было. Журнал 17.09.2026: в момент выхода окно уже у
-- края, а возврат в тот же миг затирается, поэтому проверки через 40 и 250 мс.

-- Крайнее левое обычное окно стола, хотя бы частью видимое на мониторе окна w.
local function leftmost_visible(w)
    local mon = w.monitor
    if not (mon and type(mon.x) == "number" and type(mon.width) == "number") then return nil end
    local best
    for _, o in ipairs(workspace_windows_of(w)) do
        local ow = o.size and o.size.x
        if not o.floating and o.at and type(ow) == "number"
           and o.at.x + ow > mon.x + 1 and o.at.x < mon.x + mon.width
           and (not best or o.at.x < best.at.x) then
            best = o
        end
    end
    return best
end

local stable_view = {}   -- id стола -> { active, anchor, x }
local pending_view = {}  -- id стола -> { sig, n }

local function ws_id(w)
    return w and w.workspace and w.workspace.id
end

-- Страховка SUPER+= (17.09.2026): активное окно помечено развёрнутым, но стоит
-- свёрнутым 3 проверки подряд (0,3 с) — какое-то событие фокуса прошло мимо
-- on_focus_or_open. Разворачиваем тем же путём. Пауза — чтобы не спорить с
-- переходами, которые разворачивают окно сами.
local unmax_ticks = { addr = nil, n = 0 }
local last_active = nil      -- адрес активного окна на последней проверке
local last_fullscreen = {}   -- адрес -> последний режим (0, 1 — SUPER+=, 2 — полный экран)

function ribbon_view_tick()
    if not ribbon() then return end
    local a = hl.get_active_window()
    local id = ws_id(a)
    last_active = a and a.address
    if a and not a.floating and remembered(a) and (a.fullscreen or 0) == 0 then
        if unmax_ticks.addr == a.address then unmax_ticks.n = unmax_ticks.n + 1
        else unmax_ticks.addr, unmax_ticks.n = a.address, 1 end
        if unmax_ticks.n >= 3 then
            unmax_ticks.n = 0
            on_focus_or_open(a)
            return
        end
    else
        unmax_ticks.addr, unmax_ticks.n = nil, 0
    end
    if not a or a.floating or not id or not a.at then return end
    for _, o in ipairs(workspace_windows_of(a)) do
        if not o.floating and (o.fullscreen or 0) > 0 then
            pending_view[id] = nil
            return
        end
    end
    local cols = {}
    for _, o in ipairs(workspace_windows_of(a)) do
        if not o.floating and o.at then cols[#cols + 1] = o end
    end
    table.sort(cols, function(x, y) return x.at.x < y.at.x end)
    local order = {}
    for i, o in ipairs(cols) do order[i] = o.address end
    column_order[id] = order
    local left = leftmost_visible(a)
    if not left then return end
    local sig = a.address .. " " .. left.address .. " " .. a.at.x
    local p = pending_view[id]
    if p and p.sig == sig then p.n = p.n + 1 else p = { sig = sig, n = 1 } pending_view[id] = p end
    if p.n == 3 then
        stable_view[id] = { active = a.address, anchor = left.address, x = a.at.x }
    end
end
hl.timer(function() ribbon_view_tick() end, { timeout = 100, type = "repeat" })

local function restore_view(id, tag)
    local rec = stable_view[id]
    local cur = hl.get_active_window()
    if not (rec and cur and ribbon() and ws_id(cur) == id) then return end
    if cur.address ~= rec.active or (cur.fullscreen or 0) ~= 0 or not cur.at then return end
    if math.abs(cur.at.x - rec.x) <= 2 or rec.anchor == rec.active then return end
    local a
    for _, o in ipairs(workspace_windows_of(cur)) do
        if o.address == rec.anchor then a = o end
    end
    -- Сосед, развёрнутый через SUPER+=, при фокусе развернулся бы сам
    -- (on_focus_or_open) — через него вид не возвращаем.
    if not a or a.floating or remembered(a) then return end
    hl.dispatch(hl.dsp.focus({ window = "address:" .. rec.anchor }))
    hl.dispatch(hl.dsp.focus({ window = "address:" .. cur.address }))
end

local function schedule_restore(w, why)
    local id = ws_id(w)
    if not id then return end
    hl.timer(function() restore_view(id, "r40") end, { timeout = 40, type = "oneshot" })
    hl.timer(function() restore_view(id, "r250") end, { timeout = 250, type = "oneshot" })
end

-- Только выход из ПОЛНОГО экрана (2 -> 0). Выход из разворота SUPER+= (1 -> 0)
-- случается при каждом уходе фокуса с развёрнутого окна, и возврат вида там
-- лишь гонял фокус (17.09.2026).
hl.on("window.fullscreen", function(w)
    if not (w and w.address) then return end
    local prev = last_fullscreen[w.address]
    last_fullscreen[w.address] = w.fullscreen or 0
    if not w.floating and (w.fullscreen or 0) == 0 and prev == 2 then schedule_restore(w, "unfullscreen") end
end)
-- ЗАКРЫЛИ ОКНО — ФОКУС ЛЕВОМУ СОСЕДУ (17.09.2026, просьба: «после закрытия окна
-- фокус должен вернуться на левое окно, а не правое»). Hyprland отдаёт фокус
-- колонке справа, лента прокручивается к ней, и окна «уезжали». Сосед берётся из
-- порядка колонок, который ribbon_view_tick запоминает раз в 100 мс. Окно, что
-- открылось сразу в полном экране (фото в Telegram), колонкой в порядке не
-- было — фокус возвращается окну, активному до него. Закрыли крайнее левое —
-- Hyprland решает сам.
hl.on("window.close", function(w)
    local was_fs = w and w.address and last_fullscreen[w.address]
    if w and w.address then last_fullscreen[w.address] = nil end
    if not (w and w.address and not w.floating and ribbon()) then return end
    -- Только если закрыли АКТИВНОЕ окно. Закрытие чужих окон стола (меню,
    -- подсказки, фоновые окна программ) переводило фокус, развёрнутое через
    -- SUPER+= окно от этого сворачивалось и назад не разворачивалось —
    -- «начал часто воспроизводиться» (17.09.2026).
    if w.address ~= last_active then return end
    local id = ws_id(w)
    if not id then return end
    local candidates = {}
    local order = column_order[id] or {}
    local idx
    for i, addr in ipairs(order) do
        if addr == w.address then idx = i end
    end
    if idx then
        for i = idx - 1, 1, -1 do candidates[#candidates + 1] = order[i] end
    elseif (w.fullscreen or 0) == 2 or was_fs == 2 then
        local rec = stable_view[id]
        if rec and rec.active ~= w.address then candidates[1] = rec.active end
    end
    if #candidates == 0 then return end
    local closed = w.address
    hl.timer(function()
        local cur = hl.get_active_window()
        if cur and ws_id(cur) ~= id then return end   -- ушли на другой стол — не трогаем
        local here = {}
        local ref = cur
        if not ref then
            for _, addr in ipairs(candidates) do here[addr] = true end
        else
            for _, o in ipairs(workspace_windows_of(ref)) do
                if not o.floating and o.address ~= closed then here[o.address] = true end
            end
        end
        for _, addr in ipairs(candidates) do
            if here[addr] then
                local tw
                for _, o in ipairs(cur and workspace_windows_of(cur) or {}) do
                    if o.address == addr then tw = o end
                end
                if not (tw and ribbon_focus_clamped(tw, cur)) and (not cur or cur.address ~= addr) then
                    hl.dispatch(hl.dsp.focus({ window = "address:" .. addr }))
                end
                return
            end
        end
    end, { timeout = 40, type = "oneshot" })
end)

-- Новое окно встаёт справа от активного. Если активное — последняя колонка,
-- новое станет последним, и «по центру» оставило бы пустоту справа: на время
-- открытия включаем fit (окно прижмётся к правому краю), потом возвращаем.
local open_fit_restore = nil
hl.on("window.open_early", function(w)
    if not ribbon() or hl.get_config("scrolling.focus_fit_method") ~= 0 then return end
    local a = hl.get_active_window()
    if not a or a.floating or (a.fullscreen or 0) ~= 0 then return end
    if column_neighbour(a, "right") then return end
    open_fit_restore = 0
    hl.config({ scrolling = { focus_fit_method = 1 } })
    hl.timer(function()
        if open_fit_restore ~= nil then
            hl.config({ scrolling = { focus_fit_method = open_fit_restore } })
            open_fit_restore = nil
        end
    end, { timeout = 300, type = "oneshot" })
end)
