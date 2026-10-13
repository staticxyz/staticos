#!/usr/bin/env bash
# Метка сети для экрана блокировки (левый верхний угол, см. hyprlock.conf).
# Отдельным скриптом, а не строкой прямо в конфиге: там awk не понимает
# кодов \U… для глифов, а знаки $ в команде hyprlock мог бы принять за
# свои переменные. Глифы — те же, что у модулей сети в баре.
# 13.10.2026: при кабеле — только значок провода (надпись LAN убрана); при кабеле рядом — значок Wi-Fi, если
# Wi-Fi включён (только значок, без названия): подключён — полный веер,
# включён без сети — пустой контур. Выключен — значка нет.
dev=$(nmcli -t -f TYPE,STATE,CONNECTION device 2>/dev/null)
line=$(awk -F: '$2 == "connected" && ($1 == "ethernet" || $1 == "wifi") { print $1 ":" $3; exit }' <<<"$dev")
case "$line" in
    ethernet:*)
        printf ''   # только значки (Просьба: «lan вообще убрать»)
        if [ "$(nmcli radio wifi 2>/dev/null)" = enabled ]; then
            if grep -q '^wifi:connected:' <<<"$dev"; then printf '  \U000f0928'
            else printf '  \U000f092f'; fi
        fi ;;
    wifi:*)     printf '\U000f0928  %s' "${line#wifi:}" ;;
    *)          printf '\U000f092e  нет сети' ;;
esac
