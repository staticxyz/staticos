#!/bin/sh
# Пробуждение по часам (RTC) к будильнику и Сторожу staticOS — 14.10.2026.
# Ставится root'ом в /usr/lib/systemd/system-sleep/jarvis-rtc-wake, systemd зовёт его
# при КАЖДОМ сне (по простою, из меню, крышкой): pre — перед сном, post — после.
# Время берётся из файла, который раз в минуту пишет wake_alarm.py (epoch, одно число).
# Здесь только читаются цифры — код пользователя от root не выполняется.
# @HOME@ подставляет install.sh; вручную:
#   sed "s|@HOME@|$HOME|" jarvis-rtc-wake.sh | sudo install -m 755 /dev/stdin /usr/lib/systemd/system-sleep/jarvis-rtc-wake
PLAN=@HOME@/.local/state/jarvis-wake/rtc-wake
RTC=/sys/class/rtc/rtc0/wakealarm
say() { logger -t jarvis-rtc-wake "$*"; }

case "$1" in
pre)
    echo 0 > "$RTC" 2>/dev/null
    [ -r "$PLAN" ] || { say "плана нет — сплю без пробуждения"; exit 0; }
    t=$(tr -cd 0-9 < "$PLAN" | head -c 11)
    [ -n "$t" ] && [ "$t" -gt 0 ] || { say "будить не к чему — сплю без пробуждения"; exit 0; }
    now=$(date +%s)
    if [ "$t" -le $((now + 30)) ]; then
        # срок уже наступил: свежий план (идёт серия, звонок вот-вот) — через минуту;
        # старый — не будить, иначе с закрытой крышкой сон-пробуждение по кругу
        if [ "$t" -gt $((now - 180)) ]; then t=$((now + 60))
        else say "план устарел ($(date -d @"$t" '+%F %T')) — сплю без пробуждения"; exit 0; fi
    fi
    [ "$t" -lt $((now + 8 * 86400)) ] || { say "план дальше 8 дней — пропущен"; exit 0; }
    if echo "$t" > "$RTC"; then say "проснуться в $(date -d @"$t" '+%F %T')"
    else say "ОШИБКА: не смог завести часы на $t"; fi
    ;;
post)
    echo 0 > "$RTC" 2>/dev/null
    say "проснулся"
    ;;
esac
exit 0
