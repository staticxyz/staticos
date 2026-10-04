#!/usr/bin/env bash
# Черновик на спецстоле: показать, спрятать или открыть новый чистый лист.
#
# Правила окна (плавающее, 900x600, по центру, спецстол notepad) живут в
# ~/.config/hypr/workspace.lua. Здесь они ставились через
# `hyprctl keyword windowrulev2` при каждом запуске, но в Hyprland 0.56
# keyword не работает вовсе — отвечает "keyword can't work with non-legacy
# parsers", то есть не применялось ни одно из четырёх правил.
#
# --disable-server УБРАН. Mousepad 0.7 хранит сессию в gsettings
# (org.xfce.mousepad.state.application session) и при session-restore='always'
# восстанавливает её на КАЖДОМ старте главного экземпляра. С --disable-server
# каждый запуск становился таким главным экземпляром, поэтому новое окно
# всегда приходило с полным набором прежних вкладок. Без него первый запуск
# регистрируется на D-Bus и восстанавливает сессию (это и нужно после
# включения ПК), а все последующие обращения идут к нему же и получают
# чистое окно.
#
# Аргумент "new" — всегда новый пустой лист, минуя показ/скрытие.
set -uo pipefail

FILE="$HOME/.scratchpad.txt"
CLASS="org.xfce.mousepad"
touch "$FILE"

# ── niri ───────────────────────────────────────────────────────────────────
# Спецстолов в niri нет, поэтому черновик прячется в «карман» — именованный стол
# карман (scripts/magic, ALT+Q; имя того стола — значок Telegram). SUPER+N
# приносит черновик на текущий стол и ставит в
# фокус, повторное нажатие отправляет обратно в карман. Ниже по файлу — ветка
# Hyprland со спецстолом special:notepad, она не тронута. (21.09.2026)
if [ -n "${NIRI_SOCKET:-}" ] && [ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
    # Без аргумента (SUPER+SHIFT+N) — про ГЛАВНЫЙ черновик:
    #   его нет вовсе       → открыть (~/.scratchpad.txt);
    #   есть, но не здесь   → принести на текущий стол и дать фокус;
    #   уже здесь           → просто перевести фокус.
    # Пустая заметка — это «new» (SUPER+N), отдельным нажатием: раньше она
    # пряталась за вторым нажатием, и с другого стола до неё было не добраться
    # (замечено пользователем 21.09.2026).
    # Плавающими их делает правило окна в config.kdl (open-floating для mousepad).
    scratch_id() {   # главный черновик: mousepad с ~/.scratchpad.txt в заголовке
        niri msg --json windows | jq -r --arg c "$CLASS" \
            '[.[] | select(.app_id==$c and (.title // "" | test("scratchpad")))][0].id // empty'
    }
    win_ws()  { niri msg --json windows    | jq -r --argjson i "$1" '.[]|select(.id==$i)|.workspace_id'; }
    here_id() { niri msg --json workspaces | jq -r '.[]|select(.is_focused)|.id'; }
    here_idx(){ niri msg --json workspaces | jq -r '.[]|select(.is_focused)|.idx'; }

    if [ "${1:-}" = "new" ]; then
        mousepad --opening-mode=window >/dev/null 2>&1 &
        exit 0
    fi

    id=$(scratch_id)
    if [ -z "$id" ]; then
        mousepad "$FILE" >/dev/null 2>&1 &
        exit 0
    fi

    if [ "$(win_ws "$id")" = "$(here_id)" ]; then
        niri msg action focus-window --id "$id"            # уже тут — просто в фокус
    else
        niri msg action move-window-to-workspace --window-id "$id" --focus false "$(here_idx)"
        niri msg action focus-window --id "$id"
    fi
    exit 0
fi

# Есть ли хоть одно окно блокнота и лежит ли оно на спецстоле notepad.
# Окно могли утащить в другое место (ALT+E на спецстол magic) — тогда
# переключать спецстол notepad бессмысленно, он пуст.
count_windows() {
    hyprctl clients -j 2>/dev/null | python3 -c "
import json, sys
ws = sys.argv[1] if len(sys.argv) > 1 else None
try:
    cs = json.load(sys.stdin)
except Exception:
    print(0); raise SystemExit
n = sum(1 for c in cs
        if c.get('class', '').lower() == '$CLASS'
        and (ws is None or c.get('workspace', {}).get('name') == ws))
print(n)
" "$@" 2>/dev/null || echo 0
}

special_shown() {
    hyprctl monitors -j 2>/dev/null | python3 -c "
import json, sys
try:
    ms = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if any(m.get('specialWorkspace', {}).get('name') == 'special:notepad'
                          for m in ms) else 1)
" 2>/dev/null
}

toggle_special() {
    # Имя строкой, а НЕ таблицей. И { name = "notepad" }, и { workspace = "notepad" }
    # отвечают "ok", но переключают спецстол по умолчанию (special:special)
    # вместо нужного — промах молчаливый, в выводе никакой разницы.
    hyprctl dispatch 'hl.dsp.workspace.toggle_special("notepad")' >/dev/null
    # Показали спецстол — сразу фокус на окно черновика, по адресу.
    # Без этого поверх развёрнутого окна (SUPER+=) блокнот был виден, но клики
    # уходили развёрнутому окну под ним; кликаться он начинал, только если
    # переключиться на другой монитор и обратно (14.09.2026).
    special_shown && focus_notepad
}

focus_notepad() {
    local addr
    addr=$(hyprctl clients -j 2>/dev/null | python3 -c "
import json, sys
try:
    cs = json.load(sys.stdin)
except Exception:
    raise SystemExit
for c in cs:
    if c.get('class', '').lower() == '$CLASS' and c.get('workspace', {}).get('name') == 'special:notepad':
        print(c['address']); break
" 2>/dev/null)
    [ -n "$addr" ] && hyprctl dispatch "hl.dsp.focus({ window = \"address:$addr\" })" >/dev/null
}

mousepad_addrs() {
    hyprctl clients -j 2>/dev/null | python3 -c "
import json, sys
try:
    cs = json.load(sys.stdin)
except Exception:
    raise SystemExit
print(' '.join(c['address'] for c in cs if c.get('class', '').lower() == '$CLASS'))
" 2>/dev/null
}

new_blank_window() {
    # Спецстол сначала прячем. Новое окно рождается на активном столе, а при
    # показанном спецстоле активным считается он — окно уезжало туда же и
    # оказывалось под «крышкой», из-за которой не кликались окна под ней.
    special_shown && toggle_special
    local before addr i
    before=" $(mousepad_addrs) "
    # При живом главном экземпляре это открывает новое окно с одним пустым
    # табом; сессия не восстанавливается повторно, она уже восстановлена.
    mousepad --opening-mode=window >/dev/null 2>&1 &
    # Новое окно открывает уже работающий процесс mousepad (по D-Bus), и
    # Hyprland фокус ему не отдаёт: поверх развёрнутого окна (SUPER+=) фокус
    # оставался на развёрнутом, и блокнот не принимал ни клавиш, ни кликов
    # (14.09.2026). Ждём новое окно и переводим фокус на него по адресу.
    for i in $(seq 1 25); do
        sleep 0.1
        for addr in $(mousepad_addrs); do
            case "$before" in
                *" $addr "*) ;;
                *) hyprctl dispatch "hl.dsp.focus({ window = \"address:$addr\" })" >/dev/null
                   return ;;
            esac
        done
    done
}

TOTAL=$(count_windows)

if [ "${1:-}" = "new" ]; then
    if [ "$TOTAL" -eq 0 ]; then
        # Блокнота нет вовсе: поднимаем главный черновик, он по правилу
        # scratchpad-to-special уезжает на спецстол — его и показываем.
        mousepad "$FILE" >/dev/null 2>&1 &
        sleep 0.6
        special_shown || toggle_special
    else
        # Чистый лист — обычное плавающее окно на текущем столе,
        # спецстол при этом не поднимаем.
        new_blank_window
    fi
    exit 0
fi

if [ "$TOTAL" -eq 0 ]; then
    # Первый запуск после включения ПК: восстанавливаем прошлые вкладки
    # (это делает сам mousepad) и добавляем постоянный черновик.
    mousepad "$FILE" >/dev/null 2>&1 &
    sleep 0.6
    special_shown || toggle_special
    exit 0
fi

ON_SPECIAL=$(count_windows "special:notepad")

if [ "$ON_SPECIAL" -eq 0 ]; then
    # Блокнот жив, но утащен в другое место — спецстол пуст.
    # Показывать нечего, поэтому даём свежее окно с чистого листа
    # прямо на текущем столе.
    new_blank_window
else
    toggle_special
fi
