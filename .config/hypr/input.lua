---------------
---- INPUT ----
---------------

-- Режим фокуса при наведении мыши: 2 «отделить» (по умолчанию) или
-- 1 «следовать». Выбор — в ~/.config/hypr/state/mouse-focus.
local mouse_focus = 2
local mf = io.open(os.getenv("HOME") .. "/.config/hypr/state/mouse-focus")
if mf then
    if mf:read("*l") == "follow" then mouse_focus = 1 end
    mf:close()
end

hl.config({
    input = {
        numlock_by_default = true,
        kb_layout  = "us,ru",
        kb_options = "grp:alt_shift_toggle",
        -- Наведение мыши: 1 — забирает фокус, 2 — отдаёт окну только МЫШЬ,
        -- а КЛАВИАТУРА остаётся там, где кликнул последний раз. С лентой
        -- значение 1 мешает: фокус тянет за собой вид, и задетая мышью
        -- соседняя колонка прокручивает ленту к себе. Выбор хранит
        -- scripts/mouse_focus.py (переключатель в «Настройках» → «Окна»).
        follow_mouse = mouse_focus,
        touchpad = {
            natural_scroll = true,
            tap_to_click = true,
        },
        sensitivity = -0.2,
        accel_profile = "flat",
        kb_variant = "",
        kb_model   = "",
        kb_rules   = "",
    },
})

-- Три пальца ВЕРТИКАЛЬНО — столы (21.09.2026): столы теперь едут по вертикали
-- (ws_anim.lua), и горизонтальный жест двигал бы экран поперёк пальцев. В niri так же.
hl.gesture({
    fingers = 3,
    direction = "vertical",
    action = "workspace"
})

hl.device({
    name        = "epic-mouse-v1",
})
