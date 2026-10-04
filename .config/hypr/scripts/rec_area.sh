#!/bin/bash
# Recorder: запись области экрана в GIF, видео или стикер Telegram. 29.09.2026.
#
#   rec_area.sh          нет записи — начать; идёт запись — остановить и сохранить
#   rec_area.sh mic      во время записи ВИДЕО: микрофон вкл/выкл (клавиша M)
#   rec_area.sh stop ID  остановить, только если идёт запись с этим ID (автостоп)
#   rec_area.sh pause    пауза / продолжить (K и Space на время записи, кнопка ▶/⏸ плашки)
#   rec_area.sh halt     остановить, если идёт запись; иначе ничего (Esc на время записи)
#   rec_area.sh style [X] вид меню и плашки: напечатать / записать default|skeet|beta
#                        (~/.config/hypr/state/recorder-style; нет файла — default). Контракт
#                        со строкой в Настройках — не менять.
#
# Пауза (03.10.2026): ЛЮБАЯ запись начинается НА ПАУЗЕ — «я сам буду включать».
# K и Space (голые, только пока идёт запись — в программах они в это время не печатаются,
# так решил пользователь) и кнопка ▶/⏸ на плашке переключают паузу. gpu-screen-recorder
# паузу умеет сам (SIGUSR2); wf-recorder — нет, поэтому запись идёт сегментами
# (rec_session): пауза = дописать сегмент, продолжить = новый, stop() склеивает их
# ffmpeg concat без перекодирования — до сборки GIF/стикера. Лимиты GIF и стикера
# считаются по записанному времени, без пауз.
#
# Перетаскивание области (04.10.2026): рамку rec_frame.py тянут за полосу или
# плашку (перенос) и за уголки/метки сторон (размер). Пока тянут — $S/hold, сегмент
# дописан; отпустили — новая область в $S/geom, новый сегмент уже с ней. Сегменты
# разного размера join_segs собирает с перекодированием в размер ПЕРВОГО (scale+pad,
# без искажения пропорций); одного размера — как раньше, concat без перекодирования.
# Esc во время записи (бинд в rec-binds.kdl) — стоп, как ⏹. S — то же (04.10.2026, просьба: # «бинд, чтобы останавливать запись, пока идёт или на паузе»): оба бинда живут всю запись, и на паузе тоже.
#
# Запуск: Super+Shift+Print или пункт «Recorder» в меню (rofi drun,
# ~/.local/share/applications/jarvis-rec.desktop). Остановить — тот же бинд, пункт
# меню ещё раз или щелчок по плашке «● REC» над рамкой (rec_frame.py).
#
# Порядок, как просил просьба: выбор режима (Gif / Video / Sticker и подменю; Esc —
# выход) → выделение по живому экрану (Esc — выход) → запись с красной рамкой СНАРУЖИ области (в запись не
# попадает) → стоп → файл в ~/Videos и в буфер обмена.
#
# В буфер кладётся ССЫЛКА НА ФАЙЛ (text/uri-list), а не содержимое: Telegram,
# Discord и Dolphin вставляют его как файл в своём формате — GIF анимированным,
# видео видео, стикер стикером. Раньше GIF шёл картинкой (image/gif): Telegram
# вставлял первый кадр, а мегабайты оседали в истории буфера и та лагала.
#
# Звук (только видео): пишется с виртуального устройства jarvis_rec_mic, в которое
# всегда заведён звук системы, а микрофон M подключает или отключает (по умолчанию выкл).
# Клавиша M работает ТОЛЬКО во время записи видео: её бинд живёт в
# ~/.config/niri/cfg/rec-binds.kdl и снимается при остановке.
set -uo pipefail
STYLE_FILE="$HOME/.config/hypr/state/recorder-style"
if [ "${1:-}" = style ]; then   # до журнала: ответ и ошибка нужны вызывающему
    if [ -z "${2:-}" ]; then
        v=$(cat "$STYLE_FILE" 2>/dev/null | tr -d '[:space:]'); v=${v,,}
        case "$v" in skeet|beta) echo "$v" ;; *) echo default ;; esac
        exit 0
    fi
    v=${2,,}
    case "$v" in default|skeet|beta) ;; *) echo "стиль: default | skeet | beta" >&2; exit 2 ;; esac
    mkdir -p "${STYLE_FILE%/*}" && printf '%s\n' "$v" > "$STYLE_FILE.tmp" && mv "$STYLE_FILE.tmp" "$STYLE_FILE"
    exit 0
fi
# Журнал ошибок: запуск из niri не показывает stderr, и «Не удалось собрать файл»
# без него не разобрать (29.09.2026). Хранится последние ~200 КБ.
LOG="$HOME/.cache/jarvis/recorder.log"
mkdir -p "${LOG%/*}"; [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 200000 ] && : > "$LOG"
exec 2>>"$LOG"; echo "=== $(date '+%F %T') rec_area.sh $*" >&2

S="${XDG_RUNTIME_DIR:-/tmp}/jarvis-rec"
OUT_DIR="$HOME/Videos"
HERE="$(dirname "$(readlink -f "$0")")"
REC_BINDS="$HOME/.config/niri/cfg/rec-binds.kdl"
GIF_MAX=60
GIF_FPS=15
GIF_MAX_W=960
# Видеостикер Telegram: WEBM (VP9), бо́льшая сторона ровно 512, до 3 с, до 30 к/с,
# без звука, не больше 256 КБ. Запись останавливается сама через STICKER_MAX с.
STICKER_MAX=3
STICKER_KB=256
MIC_SINK=jarvis_rec_mic
# «Без фона» (нейросеть rembg, rec_nobg.py): ~0.7 с на кадр, поэтому живой стикер без
# фона обрабатывается при 15 к/с (~45 кадров, ~30 с), а GIF без фона — не дольше 10 с.
NOBG="$HERE/rec_nobg.py"
NOBG_PY="${REMBG_PYTHON:-$HOME/.local/share/uv/tools/rembg/bin/python}"
NOBG_FPS=15
GIF_NOBG_MAX=10

# Звук к итогу записи (02.10.2026): ui_sound.py сам молчит, если звуки выключены, DND или игра.
snd() { python3 "$HERE/ui_sound.py" play "$1" >/dev/null 2>&1 & }
say() {
    notify-send -a "Recorder" -h string:x-canonical-private-synchronous:jarvis-rec "$@" 2>/dev/null
    case "$1" in
        "Сохранено"*) snd done ;;
        "Не удалось"*|"Запись не"*) snd error ;;
    esac
}
running() { [ -f "$S/pid" ] && kill -0 "$(cat "$S/pid")" 2>/dev/null; }
bar_dot() { pkill -RTMIN+11 -x waybar 2>/dev/null; }   # красная точка в баре (rec_status.sh)
to_clip() { wl-copy --type text/uri-list "file://$1"; }

rec_binds() {   # on РЕЖИМ — K/Space на паузу, Esc и S на стоп (и M на микрофон у видео); off — снять
    if [ "$1" = on ]; then
        local mic=""
        [ "${2:-}" = video ] && mic="    M hotkey-overlay-title=\"Микрофон записи вкл/выкл\" { spawn \"$HERE/rec_area.sh\" \"mic\"; }"
        # layer-rule: плашка (pill) не попадает в захват экрана (в кадре вместо неё
        # чёрное) — важно для записи всего экрана, когда плашке некуда деться.
        # Рамку области (frame) НЕ прятать: её слой прозрачный и накрывает область (с
        # 04.10.2026 — весь монитор, ради перетаскивания), и block-out закрашивал чёрным
        # ВСЁ под ним — запись выходила серой, виден был только курсор (04.10.2026).
        # Рамка и так снаружи области: в кадр она не попадает.
        cat > "$REC_BINDS" <<EOF
// Временный файл rec_area.sh: существует ТОЛЬКО во время записи.
binds {
    K repeat=false hotkey-overlay-title="Запись: пауза / продолжить" { spawn "$HERE/rec_area.sh" "pause"; }
    Escape repeat=false hotkey-overlay-title="Запись: остановить и сохранить" { spawn "$HERE/rec_area.sh" "halt"; }
    Space repeat=false hotkey-overlay-title="Запись: пауза / продолжить" { spawn "$HERE/rec_area.sh" "pause"; }
    S repeat=false hotkey-overlay-title="Запись: остановить и сохранить" { spawn "$HERE/rec_area.sh" "halt"; }
$mic
}
layer-rule {
    match namespace="^jarvis-rec-pill$"
    block-out-from "screen-capture"
}
EOF
    else
        printf '// Бинды на время записи пишет сюда rec_area.sh (K/Space — пауза, Esc/S — стоп, M — микрофон).\n// Сейчас записи нет — пусто.\n' > "$REC_BINDS"
    fi
    niri msg action load-config-file >/dev/null 2>&1
}

mic_toggle() {
    running && [ "$(cat "$S/mode")" = video ] || exit 0
    if [ -f "$S/loop" ]; then
        pactl unload-module "$(cat "$S/loop")" 2>/dev/null
        rm -f "$S/loop"; echo off > "$S/mic"
    else
        id=$(pactl load-module module-loopback source="$(pactl get-default-source)" \
             sink="$MIC_SINK" latency_msec=20 2>/dev/null) && echo "$id" > "$S/loop" && echo on > "$S/mic"
    fi
}

# Время записи без пауз — для плашки и лимитов: $S/acc — записано до текущего куска (мкс),
# $S/t0 — начало текущего куска (мкс, только пока пишем), $S/paused — стоит пауза.
now_us() { echo "${EPOCHREALTIME//[.,]/}"; }
t_pause()  { local t0; t0=$(cat "$S/t0" 2>/dev/null) && echo $(( $(cat "$S/acc") + $(now_us) - t0 )) > "$S/acc"; rm -f "$S/t0"; : > "$S/paused"; }
t_resume() { now_us > "$S/t0"; rm -f "$S/paused"; }
rec_us()   { local a t0; a=$(cat "$S/acc" 2>/dev/null || echo 0); t0=$(cat "$S/t0" 2>/dev/null) && a=$(( a + $(now_us) - t0 )); echo "$a"; }

pause_toggle() {
    running || exit 0
    if [ "$(cat "$S/engine" 2>/dev/null)" = gsr ]; then
        [ -f "$S/gsr-ready" ] || exit 0      # gsr ещё не начал (выбор окна в портале)
        kill -USR2 "$(cat "$S/pid")" 2>/dev/null || exit 0
        if [ -f "$S/paused" ]; then t_resume; else t_pause; fi
        bar_dot
    else
        kill -USR1 "$(cat "$S/pid")" 2>/dev/null || exit 0   # переключит rec_session
    fi
    snd click
}

# Сеанс записи wf-recorder сегментами. $S/pid — pid ЭТОГО сеанса, а не рекордера: он жив
# всю запись, и на паузе тоже (его ждут stop, сторож, бар и auto_dnd.py). USR1 — пауза /
# продолжить, TERM — дописать текущий сегмент и выйти. Сегменты $S/seg-NNN.mp4
# склеивает stop(). $1 — лимит записанного времени в мкс (0 — без лимита).
rec_session() {
    local lim=$1 n=0 wpid="" quit=0 tog=0 sp seg="" saved=0 resume=0 g
    trap 'quit=1' INT TERM
    trap 'tog=1' USR1
    seg_on() {
        g=$(cat "$S/geom" 2>/dev/null); [ -n "$g" ] && geom=$g   # область могли перетащить
        n=$((n + 1)); seg=$(printf '%s/seg-%03d.mp4' "$S" "$n")
        # REC_FAKE — подмена рекордера для проверок без записи экрана
        ${REC_FAKE:-wf-recorder} -y -g "$geom" -f "$seg" -c libx264 -p preset=veryfast -p crf=18 -x yuv420p "${audio[@]}" \
            >/dev/null 2>"$S/log" &
        wpid=$!; t_resume
    }
    seg_start() {
        seg_on; sleep 0.4
        if ! kill -0 "$wpid" 2>/dev/null; then
            say "Запись не началась" "$(tail -1 "$S/log")"; wpid=""; t_pause; rm -f "$seg"
        fi
    }
    seg_off() {
        kill -INT "$wpid" 2>/dev/null
        while kill -0 "$wpid" 2>/dev/null; do wait "$wpid"; done
        wpid=""; t_pause
    }
    while [ $quit = 0 ]; do
        sleep 0.2 & sp=$!; wait $sp; kill $sp 2>/dev/null
        if [ $tog = 1 ]; then
            tog=0
            # пауза нажата, пока тянут рамку, — после перетаскивания остаться на паузе
            if [ $resume = 1 ]; then resume=0
            elif [ -n "$wpid" ]; then seg_off
            else seg_start; fi
            bar_dot
        fi
        # Перетаскивание рамки (rec_frame.py): пока есть $S/hold — сегмент дописан;
        # hold снят — новый сегмент с новой областью. Область сменили так быстро, что
        # hold мы не застали, — всё равно новый сегмент.
        if [ -f "$S/hold" ]; then
            if [ -n "$wpid" ]; then seg_off; resume=1; bar_dot; fi
        elif [ $resume = 1 ]; then
            resume=0; seg_start; bar_dot
        elif [ -n "$wpid" ] && [ -s "$S/geom" ] && [ "$(cat "$S/geom")" != "$geom" ]; then
            seg_off; seg_start
        fi
        # рекордер умер сам посреди сегмента — сохранить, что успели
        if [ -n "$wpid" ] && ! kill -0 "$wpid" 2>/dev/null && [ $saved = 0 ]; then
            wpid=""; t_pause; saved=1; "$0" stop "$id" >/dev/null 2>&1 &
        fi
        if [ "$lim" -gt 0 ] && [ -n "$wpid" ] && [ "$(rec_us)" -ge "$lim" ]; then
            lim=0; "$0" stop "$id" >/dev/null 2>&1 &
        fi
    done
    [ -n "$wpid" ] && seg_off
    exit 0
}

# Сегменты wf-recorder → один файл $1. Пустые и битые (пауза сразу после старта)
# пропускаются. Все одного размера — concat без перекодирования. Область меняли на ходу
# (перетаскивание рамки) — перекодировать в размер ПЕРВОГО сегмента: вписать без
# искажения пропорций и добить чёрными полями (scale+pad). Код 1 — склеивать нечего.
join_segs() {
    local f d i W H a=1 segs=() sizes=() ins=() fc="" cat="" map=()
    for f in "$S"/seg-*.mp4; do
        [ -s "$f" ] || continue
        d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null)
        [ -n "$d" ] && [ "$d" != N/A ] && awk "BEGIN{exit !($d > 0.05)}" || continue
        segs+=("$f")
        sizes+=("$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$f")")
        [ -n "$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$f")" ] || a=0
    done
    [ ${#segs[@]} -gt 0 ] || return 1
    if [ ${#segs[@]} = 1 ]; then mv "${segs[0]}" "$1"; return; fi
    if [ "$(printf '%s\n' "${sizes[@]}" | sort -u | wc -l)" = 1 ]; then
        for f in "${segs[@]}"; do printf "file '%s'\n" "$f"; done > "$S/segs.txt"
        ffmpeg -loglevel error -y -f concat -safe 0 -i "$S/segs.txt" -c copy "$1"
        return
    fi
    W=${sizes[0]%x*}; H=${sizes[0]#*x}
    for i in "${!segs[@]}"; do
        ins+=(-i "${segs[$i]}")
        fc+="[$i:v]scale=$W:$H:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        fc+="pad=$W:$H:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v$i];"
        cat+="[v$i]"; [ $a = 1 ] && cat+="[$i:a]"
    done
    fc+="${cat}concat=n=${#segs[@]}:v=1:a=$a[v]"; map=(-map "[v]")
    [ $a = 1 ] && { fc+="[a]"; map+=(-map "[a]" -c:a aac -b:a 160k); }
    # passthrough — сохранить время кадров как есть: wf-recorder пишет с переменной
    # частотой, а постоянная (по умолчанию для mp4) плодила бы дубли кадров.
    ffmpeg -loglevel error -y "${ins[@]}" -filter_complex "$fc" "${map[@]}" \
        -c:v libx264 -preset veryfast -crf 18 -fps_mode passthrough "$1"
}

audio_down() {
    [ -f "$S/desk" ] && pactl unload-module "$(cat "$S/desk")" 2>/dev/null
    [ -f "$S/loop" ] && pactl unload-module "$(cat "$S/loop")" 2>/dev/null
    [ -f "$S/sink" ] && pactl unload-module "$(cat "$S/sink")" 2>/dev/null
    rm -f "$S/loop" "$S/sink" "$S/desk"
}

# Кадры ролика → нейросеть убирает фон → собрать обратно с прозрачностью.
# Низший приоритет (nice 19): обработка не должна тормозить остальное.
stop_nobg() {
    local mode=$1 tmp=$2 id=$3 work=$4 out crf
    mkdir -p "$work/in" "$work/out" "$OUT_DIR"
    if [ "$mode" = sticker ]; then
        ffmpeg -loglevel error -y -t 2.95 -i "$tmp" -vf \
            "fps=$NOBG_FPS,scale='if(gte(iw,ih),512,-2)':'if(gte(iw,ih),-2,512)':flags=lanczos" "$work/in/%04d.png"
    else
        ffmpeg -loglevel error -y -i "$tmp" -vf \
            "fps=$NOBG_FPS,scale='min(iw,$GIF_MAX_W)':-2:flags=lanczos" "$work/in/%04d.png"
    fi
    say "Убираю фон…" "$(ls "$work/in" | wc -l) кадров, это займёт немного времени"
    nice -n 19 "$NOBG_PY" "$NOBG" "$work/in" "$work/out"
    if [ "$mode" = sticker ]; then
        out="$OUT_DIR/sticker-$id-nobg.webm"
        for crf in 30 36 42 48 54 60; do
            ffmpeg -loglevel error -y -framerate "$NOBG_FPS" -i "$work/out/%04d.png" -an \
                -c:v libvpx-vp9 -b:v 0 -crf "$crf" -deadline good -row-mt 1 -pix_fmt yuva420p "$out" || break
            [ "$(stat -c %s "$out")" -le $(( STICKER_KB * 1024 )) ] && break
        done
    else
        # GIF собирает ImageMagick: у ffmpeg прозрачный GIF оставляет «шлейф» от
        # прошлых кадров, а -dispose Background стирает кадр перед следующим.
        out="$OUT_DIR/gif-$id-nobg.gif"
        magick -delay "1x$NOBG_FPS" -dispose Background "$work/out/"*.png -loop 0 -layers OptimizeTransparency "$out"
    fi
    rm -rf "$work"
    if [ -s "$out" ]; then
        to_clip "$out"
        hint=""
        # Telegram любой GIF перекодирует в MP4 — прозрачность там становится белой
        # (проверено пользователем 30.09.2026). Прозрачная анимация в Telegram — только видеостикер.
        [ "$mode" = gif ] && hint=$'\nВ Telegram фон станет белым — там берите Sticker (animated, background)'
        say "Сохранено и скопировано" "$(basename "$out")  ·  $(du -h "$out" | cut -f1)$hint"
    else
        say "Не удалось собрать файл"
    fi
}

stop() {
    local pid mode tmp id out
    local engine; engine=$(cat "$S/engine" 2>/dev/null || echo wf)
    pid=$(cat "$S/pid"); mode=$(cat "$S/mode"); tmp=$(cat "$S/file"); id=$(cat "$S/id")
    # Сеансу rec_session — TERM: фоновому bash-процессу INT приходит «игнорируемым»,
    # и trap на него не ставится. Рекордеру (gsr) — INT, как раньше.
    if [ "$engine" = wf ]; then kill -TERM "$pid" 2>/dev/null; else kill -INT "$pid" 2>/dev/null; fi
    for _ in $(seq 100); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done   # дописать файл
    [ -f "$S/frame" ] && kill "$(cat "$S/frame")" 2>/dev/null
    rm -f "$S/pid"
    [ "$mode" = video ] && audio_down
    rec_binds off
    mkdir -p "$OUT_DIR"
    [ "$engine" = wf ] && join_segs "$tmp"
    # gsr начинает писать до своей паузы (доли секунды) — без «продолжить» это не запись
    [ "$engine" = gsr ] && [ "$(rec_us)" -lt 300000 ] && rm -f "$tmp"
    if [ ! -s "$tmp" ]; then say "Запись пустая" "Пауза так и не снималась (Space/K или ▶)"; rm -rf "$S"; bar_dot; return 1; fi
    nobg=$(cat "$S/nobg" 2>/dev/null || echo 0)
    # Сырую запись — в свою папку, а папку записи освободить сразу. Обработка (особенно
    # без фона) идёт долго, и новый запуск принимал её папку за остатки оборванной
    # записи и стирал посреди работы — «Не удалось собрать файл» (29.09.2026).
    local work="${XDG_RUNTIME_DIR:-/tmp}/jarvis-rec-work-$id"
    mkdir -p "$work"; mv "$tmp" "$work/"; tmp="$work/$(basename "$tmp")"
    rm -rf "$S"
    bar_dot
    if [ "$nobg" = 1 ]; then stop_nobg "$mode" "$tmp" "$id" "$work"; return; fi
    case "$mode" in
    sticker)
        say "Собираю стикер…" "пара секунд"
        out="$OUT_DIR/sticker-$id.webm"
        # Качество снижаем, пока файл не влезет в лимит Telegram.
        for crf in 30 36 42 48 54 60; do
            ffmpeg -loglevel error -y -t 2.95 -i "$tmp" -an -vf \
                "fps=30,scale='if(gte(iw,ih),512,-2)':'if(gte(iw,ih),-2,512)':flags=lanczos" \
                -c:v libvpx-vp9 -b:v 0 -crf "$crf" -deadline good -row-mt 1 -pix_fmt yuva420p "$out" || break
            [ "$(stat -c %s "$out")" -le $(( STICKER_KB * 1024 )) ] && break
        done ;;
    gif)
        say "Собираю GIF…" "пара секунд"
        out="$OUT_DIR/gif-$id.gif"
        # Своя палитра на каждый ролик + diff_mode: мало «ряби» и маленький файл.
        ffmpeg -loglevel error -y -i "$tmp" -vf \
            "fps=$GIF_FPS,scale='min(iw,$GIF_MAX_W)':-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
            -loop 0 "$out" ;;
    *)
        out="$OUT_DIR/video-$id.mp4"
        mv "$tmp" "$out" ;;
    esac
    rm -rf "$work"
    if [ -s "$out" ]; then
        to_clip "$out"
        say "Сохранено и скопировано" "$(basename "$out")  ·  $(du -h "$out" | cut -f1)"
    else
        say "Не удалось собрать файл"
    fi
}

case "${1:-}" in
    stop) running && [ "$(cat "$S/id" 2>/dev/null)" = "${2:-}" ] && stop; exit 0 ;;
    mic)  mic_toggle; exit 0 ;;
    pause) pause_toggle; exit 0 ;;
    halt) running && stop; exit 0 ;;   # Esc: только остановить, никогда не начинать
esac

if running; then stop; exit 0; fi

# Повторное нажатие, пока открыто выделение или выбор режима, — выход, а не второе
# выделение поверх первого (29.09.2026). SEL — pid того запуска, что сейчас
# ждёт выделения; закрываем его slurp/rofi, и он завершается сам.
SEL="${XDG_RUNTIME_DIR:-/tmp}/jarvis-rec.select"
descendants() { local c; for c in $(pgrep -P "$1"); do echo "$c"; descendants "$c"; done; }
if [ -f "$SEL" ] && kill -0 "$(cat "$SEL")" 2>/dev/null; then
    # Сам ожидающий запуск — тоже: иначе Esc-логика подменю приняла бы закрытый
    # rofi за «шаг назад» и открыла меню снова.
    p=$(cat "$SEL"); kids=$(descendants "$p")
    kill "$p" 2>/dev/null; kill $kids 2>/dev/null
    rm -f "$SEL"
    exit 0
fi
echo $$ > "$SEL"
trap 'rm -f "$SEL"' EXIT
# Остатки прошлой записи, если она оборвалась (выключение, падение): снять бинд M и звук.
if [ -d "$S" ]; then audio_down; rec_binds off; rm -rf "$S"; fi

# 1. Режим — СНАЧАЛА выбор, потом выделение (просьба пользователя 29.09.2026).
# Верхнее меню: Gif / Video / Sticker; у Gif и Sticker — подменю с вариантами
# «без фона». Esc на любом шаге — выход. REC_MODE (gif, gif-nobg, video, sticker,
# sticker-nobg, sticker-image, sticker-image-nobg) — обход меню для проверок.
menu() {   # $1 — заголовок, остальное — пункты
    # Клавиши как в vim (30.09.2026): j/k — вниз/вверх, l — войти (как Enter),
    # h — шаг назад (как Esc: из подменю в верхнее меню, из верхнего — выход).
    # На русской раскладке те же клавиши — о/л/д/р (Cyrillic_*): иначе на русской не работали.
    # Строки поиска нет (не нужна в меню из 2–4 пунктов) — остался только заголовок.
    # Мышь (02.10.2026): у rofi один щелчок только выделял пункт, открывал двойной —
    # и второй щелчок прилетал уже в следующее меню или в выделение области
    # («перекликивается либо не открывается»). Теперь пункт открывается одним
    # щелчком, а дальше ждём, пока кнопку отпустят (mouse_wait_release.py).
    #
    # Щелчки (02.10.2026): по заголовку — шаг назад, мимо панели — выйти совсем.
    # Заголовок теперь кнопка темы (button-back) с действием kb-custom-1 — на нём же
    # Esc и h. Поля вокруг панели в теме rofi — кнопки kb-cancel; раньше cancel значил
    # «назад», теперь это «выйти». Итог: код 0 — выбран пункт (он в $MENU),
    # 10 — назад, прочее — выйти из Recorder.
    #
    # Ctrl+J/K/H/L (и русские Ctrl+о/л/р/д) — то же, что j/k/h/l (03.10.2026).
    # Для этого Ctrl+J снят с «выбрать», Ctrl+H — со «стереть символ», Ctrl+L — с
    # «дополнить»: клавиша, занятая дважды, у rofi — окно с ошибкой вместо меню.
    # Вид — стиль Recorder (rec_area.sh style): default — как было (тема лаунчера),
    # skeet/beta — тема из rec_style.py поверх config.rasi.
    local p=$1 rc th=(); shift
    case "$REC_STYLE" in default|skeet|beta) th=(-theme "$(rec_rasi "$REC_STYLE")") ;; esac   # default — окно XP (как буфер)
    MENU=$(printf '%s\n' "$@" | rofi -dmenu -i -p "$p" -no-custom -lines $# "${th[@]}" \
        -kb-row-down "Down,Control+n,j,Cyrillic_o,Control+j,Control+Cyrillic_o" \
        -kb-row-up "Up,Control+p,k,Cyrillic_el,Control+k,Control+Cyrillic_el" \
        -kb-accept-entry "Return,KP_Enter,Control+m,l,Cyrillic_de,Control+l,Control+Cyrillic_de" \
        -kb-remove-char-back "BackSpace,Shift+BackSpace" -kb-mode-complete "" \
        -kb-cancel "Control+g" \
        -kb-custom-1 "Escape,Control+bracketleft,h,Cyrillic_er,Control+h,Control+Cyrillic_er" \
        -me-select-entry "" -me-accept-entry "MousePrimary" \
        -theme-str 'inputbar { children: [ button-back ]; }' \
        -theme-str 'button-back { action: "kb-custom-1"; text-color: @accent; horizontal-align: 0; expand: true; }' \
        -theme-str "button-back { content: \"$p\"; }" 2>/dev/null)
    # (две строки в кавычках в одном -theme-str rofi склеивал в одну — заголовок
    # показывал «Replay"; action: "kb-custom-1», поэтому свойства разнесены)
    rc=$?
    python3 "$HERE/mouse_wait_release.py" 2>/dev/null
    [ $rc -eq 0 ] || MENU=""
    return $rc
}
REC_STYLE=$("$0" style)
rec_rasi() {   # $1 — стиль; путь темы rofi. Свежая (палитра не менялась) — без питона.
    local f="$HOME/.cache/jarvis/rec-menu-$1.rasi" src
    for src in "$HOME/.cache/matugen/colors.json" "$HOME/.cache/matugen/vivid.txt" \
               "$HOME/.config/hypr/state/settings-mode" "$HERE/rec_style.py"; do
        if [ ! -f "$f" ] || [ "$src" -nt "$f" ]; then python3 "$HERE/rec_style.py" rasi "$1"; return; fi
    done
    echo "$f"
}
# sub ЗАГОЛОВОК ПУНКТЫ… — подменю: выбор в $MENU; «назад» — пусто (верхнее меню
# покажется снова); щелчок мимо панели — выход из скрипта.
BACK="󰁍  Назад"
sub() {
    # Первый пункт подменю — «Назад» (04.10.2026: «сделай кнопки вернуться назад»;
    # раньше назад вели только заголовок, Esc и h — их было не видно).
    local t=$1; shift
    menu "$t" "$BACK" "$@"
    case $? in 0|10) ;; *) exit 0 ;; esac
    [ "$MENU" = "$BACK" ] && MENU=""
    return 0
}
# Replay — запись «задним числом» (~/.local/bin/replay): здесь только
# включить/выключить/сохранить, выделение не нужно. $1 — выбранный пункт.
replay_do() {
    case "$1" in
        *"5 min"*) replay save ;;
        *"1 min"*) replay save60 ;;
        *": off"*) replay off ;;
        *": on"*)  replay on ;;
    esac
}
# Меню одним окном (04.10.2026, просьба: rofi на каждое подменю — «ощущение, будто
# окно пересоздаётся»): rec_menu.py получает всё дерево разом и ходит по подменю
# внутри своего окна. Пункты Replay зависят от состояния — дерево собирается перед
# показом. Код rec_menu: 0 — выбор в $MENU, 1 (и убит сигналом) — выход; прочее
# (упал, нет GTK) — 2, и тогда ниже прежнее меню rofi (menu/sub — запасные).
gtk_menu() {
    local rp rc
    if [ "$(replay status)" = on ]; then
        rp='{"label":"󰑙  Replay: save last 5 min"},{"label":"󰑙  Replay: save last 1 min"},{"label":"󰑙  Replay: off"}'
    else
        rp='{"label":"󰑙  Replay: on (keeps last 5 min)"}'
    fi
    MENU=$(PYTHONPATH="$HERE" python3 -P -m rec_menu ${REC_TOP:+--start "$REC_TOP"} <<EOF
{"title":"Recorder","back":"$BACK","items":[
 {"label":"󰵸  Gif","title":"Gif","items":[{"label":"󰵸  Gif"},{"label":"󰵸  Gif (background)"}]},
 {"label":"󰕧  Video","title":"Video","items":[{"label":"󰕧  Video (area)"},{"label":"󰍹  Video (full screen)"},{"label":"󰖯  Video (window)"}]},
 {"label":"󰙯  Sticker","title":"Sticker","items":[{"label":"󰙯  Sticker (animated)"},{"label":"󰙯  Sticker (animated, background)"},{"label":"󰋩  Sticker (image)"},{"label":"󰋩  Sticker (image, background)"}]},
 {"label":"󰑙  Replay","title":"Replay","items":[$rp]}
]}
EOF
)
    rc=$?
    python3 "$HERE/mouse_wait_release.py" 2>/dev/null
    case $rc in
        0) [ -n "$MENU" ] && return 0; return 1 ;;
        1|130|143) return 1 ;;
        *) echo "rec_menu.py: код $rc — меню rofi" >&2; MENU=""; return 2 ;;
    esac
}
if [ -n "${REC_MODE:-}" ]; then
    choice=$REC_MODE
else
    choice=""
    gtk_menu; rc=$?
    [ $rc -eq 1 ] && exit 0
    if [ $rc -eq 0 ]; then
        case "$MENU" in *Replay:*) replay_do "$MENU"; exit 0 ;; esac
        choice=$MENU
    fi
    # Запасное меню rofi — только если rec_menu.py не смог (код 2).
    # Esc в подменю — шаг назад, в верхнее меню; Esc в верхнем — выход (30.09.2026).
    while [ -z "$choice" ]; do
        # REC_TOP=Video (или Gif, Sticker, Replay) — сразу в это подменю: так делает пункт
        # «Записать видео» в меню рабочего стола. «Назад» оттуда ведёт в общее меню.
        if [ -n "${REC_TOP:-}" ]; then
            top=$REC_TOP; REC_TOP=
        else
            menu "Recorder" "󰵸  Gif" "󰕧  Video" "󰙯  Sticker" "󰑙  Replay" || exit 0
            top=$MENU
        fi
        case "$top" in
            *Replay*)
                if [ "$(replay status)" = on ]; then
                    sub "Replay" "󰑙  Replay: save last 5 min" "󰑙  Replay: save last 1 min" "󰑙  Replay: off"
                else
                    sub "Replay" "󰑙  Replay: on (keeps last 5 min)"
                fi
                [ -n "$MENU" ] || continue
                replay_do "$MENU"
                exit 0 ;;
            *Gif*)     sub "Gif" "󰵸  Gif" "󰵸  Gif (background)"; choice=$MENU ;;
            *Video*)   sub "Video" "󰕧  Video (area)" "󰍹  Video (full screen)" "󰖯  Video (window)"; choice=$MENU ;;
            *Sticker*) sub "Sticker" "󰙯  Sticker (animated)" "󰙯  Sticker (animated, background)" \
                                     "󰋩  Sticker (image)" "󰋩  Sticker (image, background)"; choice=$MENU ;;
            *) exit 0 ;;
        esac
    done
fi
nobg=0
# «(background)» — вариант БЕЗ фона: так пользователь попросил подписать (30.09.2026).
case "$choice" in *background*|*-nobg) nobg=1 ;; esac
# «full screen» — весь монитор с фокусом, без выделения (30.09.2026).
full=0
case "$choice" in *"full screen"*|video-full) full=1 ;; esac
# «window» — конкретное окно через системный показ экрана (portal): niri/GNOME-портал
# сам предлагает выбрать окно, и запись следует за окном, даже если его двигать.
# wf-recorder так не умеет (только области экрана), поэтому здесь gpu-screen-recorder.
# Для окон в ленте niri не сообщает их координаты — другого честного пути нет.
win=0
case "$choice" in *"(window)"*|video-window) win=1 ;; esac
case "$choice" in
    *Gif*|gif*)                mode=gif ;;
    *video*|*Video*)           mode=video ;;
    *image*|sticker-image*)    mode=sticker-image ;;
    *animated*|sticker*)       mode=sticker ;;
    *) exit 0 ;;
esac

# 2. Область — по живому экрану, без заморозки (просьба пользователя). Esc — выход.
# REC_GEOM — заранее заданная область (проверки, свои бинды).
# Весь экран: область = монитор с фокусом (его логические координаты из niri).
if [ "$win" = 1 ]; then
    geom=""
    command -v gpu-screen-recorder >/dev/null || { say "Нет gpu-screen-recorder" "sudo pacman -S xdg-desktop-portal-gnome gpu-screen-recorder"; exit 0; }
elif [ "$full" = 1 ]; then
    geom=$(niri msg --json focused-output | python3 -c 'import json,sys;l=json.load(sys.stdin)["logical"];print("%d,%d %dx%d"%(l["x"],l["y"],l["width"],l["height"]))') || exit 0
else
    geom=${REC_GEOM:-$(slurp -d 2>/dev/null)} || exit 0
fi
if [ "$win" != 1 ]; then
    [ -n "$geom" ] || exit 0
    # x264 требует чётных ширины и высоты — округляем вниз.
    xy=${geom%% *}; wh=${geom#* }; w=${wh%x*}; h=${wh#*x}
    w=$(( w / 2 * 2 )); h=$(( h / 2 * 2 ))
    [ "$w" -ge 16 ] && [ "$h" -ge 16 ] || { say "Слишком маленькая область"; exit 0; }
    geom="$xy ${w}x$h"
fi

rm -f "$SEL"          # выделение и выбор позади

# Стикер-картинка — без записи: снимок области, 512 по бо́льшей стороне, WEBP.
if [ "$mode" = sticker-image ]; then
    mkdir -p "$OUT_DIR"
    out="$OUT_DIR/sticker-$(date +%Y-%m-%d_%H-%M-%S).webp"
    png=$(mktemp -t sticker-XXXXXX.png)
    grim -g "$geom" "$png" && magick "$png" -resize 512x512 "$png"
    if [ "$nobg" = 1 ]; then
        out="${out%.webp}-nobg.webp"
        d=$(mktemp -d); cp "$png" "$d/0001.png"
        say "Убираю фон…" "секунду"
        nice -n 19 "$NOBG_PY" "$NOBG" "$d" "$d/out" && cp "$d/out/0001.png" "$png"
        rm -rf "$d"
    fi
    magick "$png" -quality 90 "$out"
    rm -f "$png"
    if [ -s "$out" ]; then
        to_clip "$out"
        say "Стикер сохранён и скопирован" "$(basename "$out")  ·  $(magick identify -format '%wx%h' "$out")"
    else
        say "Стикер не получился"
    fi
    exit 0
fi

# 3. Запись.
mkdir -p "$S"
id=$(date +%Y-%m-%d_%H-%M-%S)
tmp="$S/rec-$id.mp4"
echo "$mode" > "$S/mode"; echo "$tmp" > "$S/file"; echo "$id" > "$S/id"; echo "$nobg" > "$S/nobg"
audio=()
if [ "$mode" = video ]; then
    sid=$(pactl load-module module-null-sink sink_name=$MIC_SINK \
          sink_properties=device.description=Jarvis-Rec-Mic 2>/dev/null) && echo "$sid" > "$S/sink"
    [ -f "$S/sink" ] && audio=(-a"$MIC_SINK.monitor")
    # Звук системы (то, что играет в наушниках) — в ту же смесь, всегда. Раньше в
    # запись шёл только микрофон, а он по умолчанию выключен, и видео выходило
    # немым (30.09.2026). Микрофон по-прежнему добавляется клавишей M.
    # Иногда первая загрузка модуля сразу после создания устройства отказывает
    # (раз из трёх проверок 30.09.2026) — пробуем до трёх раз.
    for _ in 1 2 3; do
        [ -f "$S/sink" ] || break
        did=$(pactl load-module module-loopback source="$(pactl get-default-sink).monitor" \
              sink="$MIC_SINK" latency_msec=20 2>/dev/null) && { echo "$did" > "$S/desk"; break; }
        sleep 0.2
    done
    echo off > "$S/mic"
fi
echo 0 > "$S/acc"; : > "$S/paused"          # старт — на паузе (03.10.2026)
[ -n "$geom" ] && echo "$geom" > "$S/geom"   # область; rec_frame.py меняет её перетаскиванием
if [ "$win" = 1 ]; then
    echo gsr > "$S/engine"
    gaudio=(); [ -f "$S/sink" ] && gaudio=(-a "$MIC_SINK.monitor")
    gpu-screen-recorder -w portal -c mp4 -k h264 -ac aac -q very_high -f 60 "${gaudio[@]}" -o "$tmp" \
        >/dev/null 2>"$S/log" &
    echo $! > "$S/pid"
    # Паузу gsr ставим, как только он начал писать (файл появился — окно выбрано в
    # портале, обработчики сигналов уже стоят); раньше SIGUSR2 мог бы его убить.
    ( g=$(cat "$S/pid")
      while kill -0 "$g" 2>/dev/null && [ ! -s "$tmp" ]; do sleep 0.1; done
      kill -0 "$g" 2>/dev/null && kill -USR2 "$g" && : > "$S/gsr-ready" ) >/dev/null 2>&1 &
    sleep 1.5   # время на выбор окна в диалоге портала
else
    echo wf > "$S/engine"
    case "$mode" in
        sticker) lim_us=$(( STICKER_MAX * 1000000 + 300000 )) ;;
        gif)     lim_us=$(( $([ "$nobg" = 1 ] && echo "$GIF_NOBG_MAX" || echo "$GIF_MAX") * 1000000 )) ;;
        *)       lim_us=0 ;;
    esac
    rec_session "$lim_us" >/dev/null 2>>"$LOG" &
    echo $! > "$S/pid"
    sleep 0.1
fi
if ! running; then
    say "Запись не началась" "$(tail -1 "$S/log" 2>/dev/null)"; audio_down; rm -rf "$S"; exit 1
fi
bar_dot
rec_binds on "$mode"
case "$mode" in gif) label=GIF ;; sticker) label=STICKER ;; *) label=REC ;; esac
# Рамка — снаружи области. У всего экрана и окна рамки нет — только плашка: при записи
# всего экрана — на ДРУГОМ мониторе (если он есть), иначе на том же, но слой закрыт от
# захвата (layer-rule в rec-binds.kdl: в кадре на её месте чёрный прямоугольник);
# окно через портал пишет только само окно — плашка ему не мешает.
if [ "$full" != 1 ] && [ "$win" != 1 ]; then
    python3 "$HERE/rec_frame.py" "$geom" "$label" "$S" >/dev/null 2>&1 &
else
    fo=$(niri msg --json focused-output | python3 -c 'import json,sys;l=json.load(sys.stdin)["logical"];print("%d,%d"%(l["x"],l["y"]))')
    pgeom=$(niri msg --json outputs 2>/dev/null | python3 -c '
import json, sys
o = [v["logical"] for v in json.load(sys.stdin).values() if v.get("logical")]
x, y = map(int, sys.argv[1].split(","))
own = [l for l in o if l["x"] <= x < l["x"] + l["width"] and l["y"] <= y < l["y"] + l["height"]]
other = [l for l in o if l not in own]
l = (other if sys.argv[2] == "1" and other else own or o)[0]
print("%d,%d %dx%d" % (l["x"], l["y"], l["width"], l["height"]))' "$fo" "$full")
    python3 "$HERE/rec_frame.py" "pill:$pgeom" "$label" "$S" >/dev/null 2>&1 &
fi
echo $! > "$S/frame"
lim=$([ "$nobg" = 1 ] && echo "$GIF_NOBG_MAX" || echo "$GIF_MAX")
go="На паузе: Space/K или ▶ на плашке — начать"
case "$mode" in
    sticker) say "Запись стикера" "$go. Остановится сама через $STICKER_MAX с записи" ;;
    gif)     say "Запись GIF" "$go. Рамку можно тащить и растягивать. Стоп: Esc, S или ⏹ (не дольше $lim с записи)" ;;
    video)   say "Запись видео" "$go. M — микрофон (выкл). Рамку можно тащить и растягивать. Стоп: Esc, S или ⏹" ;;
esac
# Сторож (01.10.2026): запись умерла сама (отменён диалог портала, упал рекордер) —
# убрать за ней: иначе оставались бинд голой M (М/Ь не печаталась без Shift),
# петля микрофона и служебный выход jarvis_rec_mic. Штатный stop стирает $S/pid
# первым, поэтому здесь срабатываем, только если pid-файл всё ещё наш.
(
    rpid=$(cat "$S/pid" 2>/dev/null)
    while kill -0 "$rpid" 2>/dev/null; do sleep 1; done
    sleep 0.5
    if [ "$(cat "$S/pid" 2>/dev/null)" = "$rpid" ]; then
        [ -f "$S/frame" ] && kill "$(cat "$S/frame")" 2>/dev/null
        audio_down
        rec_binds off
        rm -rf "$S"
        bar_dot
        say "Запись оборвалась" "Бинды и звук возвращены"
    fi
) >/dev/null 2>&1 &
