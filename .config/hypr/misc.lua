----------------
----  MISC  ----
----------------

hl.config({
    misc = {
        force_default_wallpaper = 0,    -- Set to 0 or 1 to disable the anime mascot wallpapers
        disable_hyprland_logo   = true, -- If true disables the random hyprland logo / anime girl bac>

        -- Будить экраны от любого ввода. По умолчанию в Hyprland обе опции
        -- выключены: погашенный экран не реагирует ни на клавиатуру, ни на
        -- мышь, и вернуть его может только внешняя команда. Именно поэтому
        -- экран оставался чёрным до перезагрузки — команда пробуждения в
        -- hypridle не срабатывала, а сам Hyprland просыпаться не умел.
        key_press_enables_dpms  = true,
        mouse_move_enables_dpms = true,
    },
})
