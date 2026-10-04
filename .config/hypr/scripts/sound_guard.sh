#!/bin/sh
# Сторож звуковых потоков (23.09.2026).
#
# 1. Звонок терминала тише. «Капля» при упоре в край текста — это kitty
#    играет BEL через libcanberra: поток «kitty Terminal», роль event, 100 %
#    (журнал pactl subscribe 23.09.2026). Тема звуков тут ни при чём, а
#    enable_audio_bell в kitty.conf трогать нельзя: работающие kitty
#    перечитывают конфиг сами и сбрасывают размер шрифта окон. Поэтому каждому
#    новому потоку роли event сразу ставится EVENT_VOL.
# 2. «Не беспокоить» глушит системные звуки — потоки роли event (звонок
#    терминала и т. п.; swaync сам звуков не играет). Telegram и ZapZap не
#    трогаются: их уведомления не отличить от голосовых и видео (см. klass).
# 3. Тишина от DND не переживает DND (27.09.2026). WirePlumber запоминает mute
#    потока по его ключу — у Telegram это общее имя «Playback Stream» (имени
#    программы у потоков OpenAL нет), — и после выключения DND новые звуки
#    Telegram начинались заглушёнными: «звук иногда пропадает», чинилось
#    SUPER+ALT+=. Поэтому каждая наша тишина записывается в MUTED (класс звука),
#    а вне DND первый же поток этого класса, пришедший заглушённым, включается
#    обратно — и WirePlumber запоминает уже «звук есть». Тишину, поставленную
#    руками, сторож не трогает: её в MUTED нет.
# Журнал: $XDG_RUNTIME_DIR/sound_guard.log — что пришло и что сделано.
EVENT_VOL=22%
LOG="${XDG_RUNTIME_DIR:-/tmp}/sound_guard.log"
MUTED="$HOME/.cache/sound_guard.dnd-muted"
MAIN=$$          # фоновая часть живёт, пока жив этот процесс
: > "$LOG"

props() {   # свойства потока $1: роль, имя программы, бинарник (через клиента), mute
    pactl list sink-inputs 2>/dev/null | awk -v id="$1" '
        $0 ~ "^Sink Input #"id"$" {on=1; next}
        /^Sink Input #/ {on=0}
        on && /^\tClient:/ {c=$2}
        on && /^\tMute:/ {m=$2}
        on && /^\tSample Specification:/ {sub(/^[^:]*: /,""); ss=$0}
        on && /node.latency =/ {l=$3}
        on && /media.role =/ {r=$3}
        on && /application.name =/ {sub(/^[^=]*= /,""); n=$0}
        on && /application.process.binary =/ {b=$3}
        END {printf "%s|%s|%s|%s|%s|%s %s\n", r, n, b, c, m, ss, l}'
}

client_bin() {   # бинарник клиента $1 (для потоков OpenAL без имени программы)
    pactl list clients 2>/dev/null | awk -v id="$1" '
        $0 ~ "^Client #"id"$" {on=1; next}
        /^Client #/ {on=0}
        on && /application.process.binary =/ {print $3; exit}'
}

info() {   # разобрать поток $1 в role, name, bin, mute, key
    p=$(props "$1"); role=${p%%|*}; rest=${p#*|}; name=${rest%%|*}; rest=${rest#*|}; bin=${rest%%|*}
    rest=${rest#*|}; client=${rest%%|*}; rest=${rest#*|}; mute=${rest%%|*}; spec=${rest#*|}
    [ -z "$bin" ] && [ -n "$client" ] && bin=$(client_bin "$client")
    key="$role:$bin"
}

klass() {   # класс звука, который DND глушит, — в cls; пусто — не наш
    # Классы — как WirePlumber запоминает тишину: все звуки роли event под одним
    # ключом (media.role Notification), безымянные потоки OpenAL Telegram — под
    # общим «Playback Stream», ZapZap — по имени программы. Метка по программе
    # (роль:бинарник) промахивалась: заглушили звук kitty, а следующим пришёл
    # звук другой программы — и тишина роли event оставалась навсегда.
    # Telegram и ZapZap DND НЕ глушит (27.09.2026, вечер): голосовые, видео и
    # звуки уведомлений у них идут одинаковыми потоками («Playback Stream» у
    # Telegram), и тишина била по тому, что пользователь слушает, а WirePlumber
    # переносил её на следующие потоки — «звук из Telegram пропадает». Пока
    # уведомление от голосового не отличить, глушится только роль event.
    # Чем они отличаются, покажет журнал: у каждого потока пишется формат.
    case "$1" in
        '"event"':*) cls=event ;;
        *) cls="" ;;
    esac
}

mark()    { grep -qxF "$1" "$MUTED" 2>/dev/null || echo "$1" >> "$MUTED"; }
marked()  { grep -qxF "$1" "$MUTED" 2>/dev/null; }
unmark()  { grep -vxF "$1" "$MUTED" > "$MUTED.tmp" 2>/dev/null; mv "$MUTED.tmp" "$MUTED"; }
log()     { printf '%s %s\n' "$(date +%T)" "$*" >> "$LOG"; }

# 4. Переходы DND (27.09.2026). Глушить только НОВЫЕ потоки мало: Telegram
#    держит поток OpenAL открытым минутами и играет уведомления через него —
#    такой звук проходил, а поток, заглушённый в DND, оставался немым и после
#    («звук с Telegram ломается»). Поэтому на входе в DND глушатся и уже
#    открытые потоки этого класса — WirePlumber заодно запоминает тишину, и
#    новые потоки стартуют немыми с первого сэмпла, без «секунды звука». На
#    выходе из DND наша тишина снимается с открытых потоков. Состояние DND —
#    подпиской swaync-client -swb (строка на каждое изменение).
dnd_follow() {
    # Сторожа перезапускают, убивая основной процесс, — фоновая подписка
    # сама не умирает и продолжала бы глушить вторым экземпляром. Поэтому
    # она проверяет, жив ли основной, на каждом шаге.
    while kill -0 "$MAIN" 2>/dev/null; do
        prev=""
        swaync-client -swb 2>/dev/null | while read -r line; do
            kill -0 "$MAIN" 2>/dev/null || exit 0
            case "$line" in *'"alt": "dnd'*|*'"alt":"dnd'*) now=true ;; *) now=false ;; esac
            [ "$now" = "$prev" ] && continue
            prev=$now
            done_keys=""
            for id in $(pactl list sink-inputs short 2>/dev/null | cut -f1); do
                info "$id"
                klass "$key"; [ -n "$cls" ] || continue
                if [ "$now" = true ] && [ "$mute" = no ]; then
                    pactl set-sink-input-mute "$id" 1 2>/dev/null && mark "$cls" \
                        && log "#$id бин=${bin:-—} → заглушен (вход в DND)"
                elif [ "$now" = false ] && [ "$mute" = yes ] && marked "$cls"; then
                    pactl set-sink-input-mute "$id" 0 2>/dev/null \
                        && log "#$id бин=${bin:-—} → тишина снята (выход из DND)"
                    done_keys="$done_keys
$cls"
                fi
            done
            printf '%s\n' "$done_keys" | while IFS= read -r k; do [ -n "$k" ] && unmark "$k"; done
            log "DND: $now"
        done
        sleep 2          # swaync перезапустился — подписаться заново
    done
}
dnd_follow &

# Звуковой сервер перезапустили (systemctl --user restart pipewire…) — pactl
# subscribe завершается; подписываемся заново, а не умираем до перезахода.
while :; do
    pactl subscribe 2>/dev/null | while read -r line; do
        case "$line" in *"Event 'new' on sink-input"*) ;; *) continue ;; esac
        id=${line##*#}
        sleep 0.05
        info "$id"
        did=""
        if [ "$role" = '"event"' ]; then
            pactl set-sink-input-volume "$id" "$EVENT_VOL" 2>/dev/null && did="громкость $EVENT_VOL"
        fi
        klass "$key"
        if [ -n "$cls" ]; then
            if [ "$(swaync-client -D 2>/dev/null)" = true ]; then
                if [ "$mute" = no ]; then
                    pactl set-sink-input-mute "$id" 1 2>/dev/null && did="$did${did:+, }заглушен (DND)"
                else
                    did="$did${did:+, }уже немой (DND)"
                fi
                mark "$cls"
            elif [ "$mute" = yes ] && marked "$cls"; then
                pactl set-sink-input-mute "$id" 0 2>/dev/null && did="$did${did:+, }тишина от DND снята"
                unmark "$cls"
            fi
        fi
        log "#$id роль=${role:-—} прог=${name:-—} бин=${bin:-—} [$spec] → ${did:-ничего}"
    done
    sleep 2
done
