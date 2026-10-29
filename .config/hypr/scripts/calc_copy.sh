#!/usr/bin/env bash
# Копирование ответа калькулятора (Enter в calc_menu.sh, rofi-calc).
#
# Ответ берётся не из {result}, а из файла, который calc_qalc.py пишет на
# каждом вводе: rofi-calc подставляет {result} в строку для /bin/sh -c, и
# узкие пробелы разбивки по тысячам доезжали битыми байтами — «9�200257111.78».
# В файле лежит чистое значение: у денег — число без разбивки («2277.95»).
#
# Пустой ответ (недописанное выражение) буфер не трогает.
#
# Перевод (23.09.2026): если последний ввод был текстом, calc_qalc.py оставил
# ~/.cache/calc_qalc.translate. С 17.10.2026 перевод уже от Google — он
# копируется как есть. Если сети не было и показан черновик NLLB, по Enter
# Google спрашивается ещё раз (translate_best.sh); снова нет — черновик.
v=$(cat ~/.cache/calc_qalc.answer 2>/dev/null)
[ -n "${v// /}" ] || exit 0
req=~/.cache/calc_qalc.translate
if [ -f "$req" ]; then
    # три строки, текст последним: read делит по пробелам, и фраза резалась до первого слова
    { read -r src; read -r tgt; read -r text; } < <(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["src"]); print(d["tgt"]); print(d["text"].replace("\n"," "))' "$req")
    engine=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("engine",""))' "$req" 2>/dev/null)
    rm -f "$req"
    if [ "$engine" = google ]; then      # ответ уже от Google (17.10.2026) — копировать как есть
        printf '%s' "$v" | wl-copy --type text/plain
        exit 0
    fi
    nid=$(notify-send -p -a "Переводчик" -t 15000 "Перевожу через Google…" "$text")
    if best=$(timeout 30 ~/.config/hypr/scripts/translate_best.sh "$text" "$src" "$tgt" 2>/dev/null) && [ -n "$best" ]; then
        printf '%s' "$best" | wl-copy --type text/plain
        notify-send -r "${nid:-0}" -a "Переводчик" -t 8000 "Скопировано (Google)" "$best"
    else
        printf '%s' "$v" | wl-copy --type text/plain
        notify-send -r "${nid:-0}" -a "Переводчик" -t 8000 "Нет сети — скопирован офлайн-перевод" "$v"
    fi
    exit 0
fi
printf '%s' "$v" | wl-copy --type text/plain
