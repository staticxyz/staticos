----------------------------------------
---- СТОЛЫ: ВЕРТИКАЛЬ И ЧЕСТНЫЙ СДВИГ ----
----------------------------------------
-- 21.09.2026. Столы переключаются вертикальным сдвигом, как в niri: следующий
-- стол приезжает СНИЗУ, предыдущий — СВЕРХУ, и по движению видно, откуда пришёл.
--
-- В чём была беда. Hyprland берёт направление сдвига из НОМЕРОВ столов
-- (Monitor.cpp: новый id > старого — едем в одну сторону, иначе в другую). А
-- порядок столов у нас свой (scripts/ws_order.py): новый стол получает
-- наименьший свободный номер, но встаёт на нужное МЕСТО, так что номер и место
-- расходятся, и сдвиг врал. Из-за этого с 12.09 стоял fade — анимация без
-- направления.
--
-- Что изменилось. В 0.56.2 стиль анимации принимает явное направление вторым
-- словом (WorkspaceAnimationController.cpp): "slide top" / "slide bottom".
-- Поэтому перед каждым своим переключением мы считаем направление по порядку из
-- ws-order.json, ставим нужный стиль, переключаем и СРАЗУ возвращаем обычный
-- "slidevert". Сразу — потому что Hyprland читает стиль в момент старта анимации,
-- а чужие переключения (щелчок по бару, уведомление) не должны получить
-- направление, оставшееся от прошлого раза: им достаётся сдвиг по номерам,
-- который верен всегда, когда порядок совпадает с номерами.
--
-- Кто пользуется: цифры SUPER+1..0 и SUPER+D (keybindings.lua), K/J и стрелки
-- через ws_order.py (hyprctl eval 'ws_goto(N)'), перенос окна на стол
-- (ws_send), обзор SUPER+G (ws_goto / ws_focus_window).

local ORDER_FILE = os.getenv("HOME") .. "/.local/state/hypr/ws-order.json"

-- Скорость в децисекундах: 3.2 ≈ 320 мс, близко к пружине niri. Кривая — та же
-- easeOutQuint, что у рамок и слоёв (visuals.lua): быстрый старт, мягкая посадка.
local SPEED, CURVE = 3.2, "easeOutQuint"

local function set_style(style)
    hl.animation({ leaf = "workspaces", enabled = true, speed = SPEED, bezier = CURVE, style = style })
end

-- Мгновенная смена стола, без сдвига. Нужна обзору (SUPER+G): он сам наезжает на
-- выбранный стол, и сдвиг Hyprland под ним доигрывал бы уже после закрытия обзора.
local function set_instant()
    hl.animation({ leaf = "workspaces", enabled = false, speed = SPEED, bezier = CURVE, style = "slidevert" })
end

-- Место стола в видимом порядке. Столы, которых в файле ещё нет, идут после
-- известных по номеру — так же их расставляет ws_order.py.
local function place_of(id)
    local f = io.open(ORDER_FILE, "r")
    if f then
        local text = f:read("*a") or ""
        f:close()
        local i = 0
        for n in text:gmatch("%-?%d+") do
            i = i + 1
            if tonumber(n) == id then return i end
        end
    end
    return 100000 + id
end

-- Стол, который сейчас показан на мониторе, куда придёт target.
local function shown_on_monitor_of(target_id)
    local ok, cur = pcall(function()
        local ws = hl.get_workspace(target_id)
        local mon = ws and ws.monitor or hl.get_active_monitor()   -- стола ещё нет — он родится на активном
        return mon.active_workspace.id
    end)
    return ok and cur or nil
end

function ws_anim_prepare(target_id)
    local cur = shown_on_monitor_of(target_id)
    if not cur or cur == target_id or target_id < 0 then return end
    set_style(place_of(target_id) > place_of(cur) and "slide bottom" or "slide top")
end

function ws_anim_reset()
    set_style("slidevert")
end

-- Перейти на стол с честным направлением сдвига (instant = true — без анимации).
function ws_goto(id, instant)
    if instant then set_instant() else ws_anim_prepare(id) end
    hl.dispatch(hl.dsp.focus({ workspace = id }))
    ws_anim_reset()
end

-- Перенести активное окно на стол (и уйти за ним) — с тем же направлением.
function ws_send(id)
    ws_anim_prepare(id)
    hl.dispatch(hl.dsp.window.move({ workspace = id }))
    ws_anim_reset()
end

-- Фокус на окно по адресу; если оно на другом столе — сдвиг в верную сторону.
function ws_focus_window(addr, instant)
    if instant then
        set_instant()
    else
        pcall(function()
            local w = hl.get_window("address:" .. addr)
            if w and w.workspace then ws_anim_prepare(w.workspace.id) end
        end)
    end
    hl.dispatch(hl.dsp.focus({ window = "address:" .. addr }))
    ws_anim_reset()
end

-- Просвет между столами во время сдвига — как зазор между столами в niri.
hl.config({ general = { gaps_workspaces = 48 } })
ws_anim_reset()
