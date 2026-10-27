# `kill steam` → steam-off (27.10.2026). Обычный kill по имени шлёт SIGTERM всем «steam»,
# клиент от этого зависал в выходе, и Steam потом не запускался. Остальное — как встроенный
# kill fish (embedded:functions/kill.fish).
function kill --description 'kill; «kill steam» выключает Steam правильно (steam-off)'
    if contains -- steam $argv
        steam-off
        set argv (string match -v -- steam $argv)
        string match -qrv -- '^-' $argv; or return 0
    end
    set -l args (__fish_expand_pid_args $argv)
    and command kill $args
end
