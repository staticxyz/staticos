#!/usr/bin/env bash
# Терминальные пункты меню Super+X (app_launcher.py) — как «Install / Remove / Update /
# About» у Omarchy (bin/omarchy-menu, v3.1): список пакетов в fzf с описанием справа,
# Tab — отметить несколько, Enter — выполнить. 13.10.2026.
#
#     launcher_term.sh install | aur | font      поставить пакет (pacman / AUR / шрифт)
#     launcher_term.sh install-pkg ПАКЕТ         поставить один (каталог «Установить › Браузер…»)
#     launcher_term.sh remove | remove-aur       удалить явно поставленный / из AUR
#     launcher_term.sh remove-pkg ПАКЕТ | remove-flatpak ID   удалить программу (меню «Удалить»)
#     launcher_term.sh update-aur ПАКЕТ          обновить одну программу из AUR
#     launcher_term.sh orphans | cache           ненужные зависимости / старый кэш пакетов
#     launcher_term.sh update | update-repo      всё (yay -Syu) / только pacman -Syu
#     launcher_term.sh webapp-add | webapp-rm    веб-приложение: сайт окном Helium (~/.local/bin/webapp)
#     launcher_term.sh passwd | timezone | about
#     launcher_term.sh open КОМАНДА              открыть в плавающем kitty (так зовёт меню)
#
# В отличие от Omarchy — без --noconfirm: pacman сам спросит [Y/n] перед изменением.
# sudo спрашивает пароль здесь, в терминале (в фоне его звать нельзя — faillock).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ "${1:-}" = open ]; then
    shift
    exec kitty --class com.jarvis.menu.term --title "${TITLE:-staticOS}" "$0" "$@"
fi

FZF_KEYS=(--multi --height=100% --layout=reverse --border=none
          --preview-window='right,60%,wrap'
          --bind 'alt-p:toggle-preview,alt-j:preview-down,alt-k:preview-up,ctrl-q:abort'
          --header 'Tab — отметить несколько · Enter — выбрать · Alt+P — описание · Esc — выход')

done_wait() {
    echo
    read -r -n 1 -s -p "Готово. Любая клавиша — закрыть." || true
}

notify() { notify-send -a "staticOS" "$1" "${2:-}" 2>/dev/null || true; }

pick() {   # pick "заголовок" "preview" < список  →  выбранное на stdout
    local label=$1 prev=$2
    fzf "${FZF_KEYS[@]}" --prompt "$label › " --preview "$prev"
}

case "${1:-}" in
    install)
        mapfile -t P < <(pacman -Slq | sort -u | pick "Установить" 'pacman -Sii {1}')
        [ ${#P[@]} -eq 0 ] && exit 0
        sudo pacman -S --needed "${P[@]}" && notify "Установлено" "${P[*]}"
        done_wait ;;
    aur)
        command -v yay >/dev/null || { echo "yay не установлен"; done_wait; exit 1; }
        echo "Загружаю список AUR…"
        mapfile -t P < <(yay -Slqa | pick "Установить из AUR" 'yay -Siia {1}')
        [ ${#P[@]} -eq 0 ] && exit 0
        yay -S --needed "${P[@]}" && notify "Установлено из AUR" "${P[*]}"
        done_wait ;;
    font)
        mapfile -t P < <(pacman -Slq | grep -E '^(ttf|otf)-|nerd-fonts|^noto-fonts' | sort -u \
                         | pick "Шрифт" 'pacman -Sii {1}')
        [ ${#P[@]} -eq 0 ] && exit 0
        sudo pacman -S --needed "${P[@]}" && fc-cache -f && notify "Шрифт установлен" "${P[*]}"
        done_wait ;;
    remove)
        mapfile -t P < <(pacman -Qqe | pick "Удалить" 'pacman -Qi {1}')
        [ ${#P[@]} -eq 0 ] && exit 0
        sudo pacman -Rns "${P[@]}" && notify "Удалено" "${P[*]}"
        done_wait ;;
    remove-aur)
        mapfile -t P < <(pacman -Qqm | pick "Удалить (AUR)" 'pacman -Qi {1}')
        [ ${#P[@]} -eq 0 ] && exit 0
        sudo pacman -Rns "${P[@]}" && notify "Удалено" "${P[*]}"
        done_wait ;;
    remove-pkg)     # из «Удалить» в меню: один пакет программы (13.10.2026)
        pkg=${2:?пакет}
        pacman -Qi "$pkg" | grep -E '^(Name|Version|Description|Installed Size|Required By) ' \
            | sed 's/^Name /Пакет /;s/^Version /Версия /;s/^Description /Описание /;s/^Installed Size /Размер /;s/^Required By /Нужен для /'
        echo
        echo "Удалить вместе с ненужными больше никому зависимостями (pacman -Rns)."
        echo "Если пакет нужен другим — pacman откажет и скажет кому."
        echo
        sudo pacman -Rns "$pkg" && notify "Удалено" "$pkg"
        done_wait ;;
    remove-flatpak)
        flatpak uninstall "${2:?приложение}" && notify "Удалено" "$2"
        done_wait ;;
    orphans)
        mapfile -t P < <(pacman -Qdtq)
        if [ ${#P[@]} -eq 0 ]; then
            echo "Ненужных зависимостей нет."
        else
            echo "Пакеты, которые поставились как зависимости и больше никому не нужны:"
            printf '  %s\n' "${P[@]}"
            echo
            sudo pacman -Rns "${P[@]}"
        fi
        done_wait ;;
    cache)
        command -v paccache >/dev/null || { echo "нет paccache (пакет pacman-contrib)"; done_wait; exit 1; }
        echo "Оставить по одной прошлой версии каждого пакета (для отката), остальное удалить:"
        paccache -dk1 | tail -3
        echo
        sudo paccache -rk1 && sudo paccache -ruk0
        done_wait ;;
    update)
        if command -v yay >/dev/null; then yay -Syu; else sudo pacman -Syu; fi
        done_wait ;;
    install-pkg)    # один пакет из каталога «Установить» (репозиторий или AUR — yay сам поймёт)
        if command -v yay >/dev/null; then yay -S --needed "${2:?пакет}"; else sudo pacman -S --needed "${2:?пакет}"; fi \
            && notify "Установлено" "$2"
        done_wait ;;
    update-aur)     # одна программа из AUR (из «Обновить › Приложения»)
        yay -S "${2:?пакет}" && notify "Обновлено" "$2"
        done_wait ;;
    update-repo)
        sudo pacman -Syu
        done_wait ;;
    webapp-add)     # 13.10.2026: как Install › Web App у Omarchy
        echo "Веб-приложение — сайт отдельным окном со своим значком (Helium --app)."
        echo
        read -r -p "Название: " NAME; [ -z "$NAME" ] && exit 0
        read -r -p "Адрес (например music.youtube.com): " URL; [ -z "$URL" ] && exit 0
        read -r -p "Адрес значка PNG (Enter — значок сайта): " ICON
        webapp add "$NAME" "$URL" ${ICON:+"$ICON"} && notify "Веб-приложение добавлено" "$NAME — в Super+X и лаунчере"
        done_wait ;;
    webapp-rm)
        mapfile -t P < <(webapp ls | pick "Убрать веб-приложение" 'echo {}' | cut -f1)
        [ ${#P[@]} -eq 0 ] && exit 0
        for n in "${P[@]}"; do webapp rm "$n"; done && notify "Веб-приложение убрано" "${P[*]}"
        done_wait ;;
    passwd)
        passwd
        done_wait ;;
    timezone)
        echo "Сейчас: $(timedatectl show -p Timezone --value)"
        tz=$(timedatectl list-timezones | fzf --height=100% --layout=reverse --prompt "Часовой пояс › " \
             --query "${TZQ:-Asia/}") || exit 0
        sudo timedatectl set-timezone "$tz" && notify "Часовой пояс" "$tz"
        done_wait ;;
    about)
        clear
        fastfetch
        read -r -n 1 -s ;;
    *)
        sed -n '2,15p' "$0"
        exit 2 ;;
esac
