function weekday --description "Большой день недели и дата в окне терминала"
    # Тот же dateview.py, что висит на десятом столе, но под рукой из любого
    # терминала. Аргументы передаются как есть: -C N — свой цвет, --plain —
    # без цвета, --fmt-top/--fmt-bottom — своя надпись (просьба пользователя
    # 23.09.2026).
    python3 $HOME/.config/hypr/scripts/dateview.py $argv
end
