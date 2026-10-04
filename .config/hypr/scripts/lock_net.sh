#!/usr/bin/env bash
# Метка сети для экрана блокировки (левый верхний угол, см. hyprlock.conf).
# Отдельным скриптом, а не строкой прямо в конфиге: там awk не понимает
# кодов \U… для глифов, а знаки $ в команде hyprlock мог бы принять за
# свои переменные. Глифы — те же, что у модуля сети в баре.
line=$(nmcli -t -f TYPE,STATE,CONNECTION device 2>/dev/null |
       awk -F: '$2 == "connected" { print $1 ":" $3; exit }')
case "$line" in
    ethernet:*) printf '\U000f0200  LAN' ;;
    wifi:*)     printf '\U000f0928  %s' "${line#wifi:}" ;;
    *)          printf '\U000f092e  нет сети' ;;
esac
