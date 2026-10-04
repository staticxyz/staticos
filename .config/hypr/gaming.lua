----------------
---- ИГРЫ  -----
----------------
-- 15.09.2026. CS2 (через gamescope) и игры Proton (класс steam_app_<id>).
--
-- Что и зачем:
--   immediate        — разрешить разрывы кадра вместо ожидания vsync: меньше
--                      задержка, нет «ступенек», когда кадр не успел к развёртке.
--   misc.vrr = 3     — переменная частота только для полноэкранного окна с типом
--                      содержимого «игра». MSI MAG 255XF держит FreeSync 48–300 Гц
--                      по DisplayPort; на рабочем столе VRR не включается, чтобы
--                      не мерцало.
--   render_unfocused — игра продолжает рисоваться, даже если фокус ушёл на
--                      другое окно: не замирает и не теряет поверхность.
--   idle_inhibit     — пока окно игры открыто, система не считает простой.
--                      (Приглушение и блокировку hypridle держит отдельно —
--                      проверка игры в scripts/game_guard.py.)
--
-- Фокус. Глобально стоит misc.on_focus_under_fullscreen = 2: новое окно
-- сворачивает развёрнутое — на этом держится лента (ribbon_binds.lua). Для игры
-- это значит «пришло окно Steam или чата — игра выпала из полноэкранного
-- режима». Пока открыто хоть одно окно игры, ставим 0 (фокус остаётся у
-- полноэкранного окна), после закрытия последнего возвращаем 2.

local function is_game(class)
    if type(class) ~= "string" then return false end
    return class == "cs2" or class == "gamescope" or class:match("^steam_app_%d+$") ~= nil
end

hl.config({
    general = { allow_tearing = true },
    misc    = { vrr = 3 },
})

hl.window_rule({
    name  = "game-smooth",
    match = { class = "^(cs2|gamescope|steam_app_[0-9]+)$" },

    immediate        = true,
    content          = "game",
    idle_inhibit     = "always",
    render_unfocused = true,
    no_blur          = true,
    no_shadow        = true,
    no_anim          = true,
})

local RIBBON_FOCUS_MODE = 2   -- то, что нужно ленте; см. комментарий выше
local games = {}              -- адреса открытых окон игр

local function count()
    local n = 0
    for _ in pairs(games) do n = n + 1 end
    return n
end

local function track(w)
    if not w or not w.address or not is_game(w.class) then return end
    if not games[w.address] then
        games[w.address] = true
        if count() == 1 then
            hl.config({ misc = { on_focus_under_fullscreen = 0 } })
        end
    end
end

-- Класс XWayland-окна иногда приходит уже после открытия — ловим и его.
hl.on("window.open",  track)
hl.on("window.class", track)

hl.on("window.close", function(w)
    if not w or not w.address or not games[w.address] then return end
    games[w.address] = nil
    if count() == 0 then
        hl.config({ misc = { on_focus_under_fullscreen = RIBBON_FOCUS_MODE } })
    end
end)
