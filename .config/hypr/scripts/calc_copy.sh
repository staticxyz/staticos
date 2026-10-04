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
# ~/.cache/calc_qalc.translate. Если рядом лежит исполняемый translate_refine.sh
# (необязательный, свой: `translate_refine.sh ТЕКСТ SRC TGT` → перевод в stdout),
# по Enter копируется его перевод — с уведомлением о ходе дела. Его нет или он
# не ответил — копируется офлайн-черновик NLLB.
v=$(cat ~/.cache/calc_qalc.answer 2>/dev/null)
[ -n "${v// /}" ] || exit 0
req=~/.cache/calc_qalc.translate
if [ -f "$req" ]; then
    # три строки, текст последним: read делит по пробелам, и фраза резалась до первого слова
    { read -r src; read -r tgt; read -r text; } < <(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["src"]); print(d["tgt"]); print(d["text"].replace("\n"," "))' "$req")
    rm -f "$req"
    refine=~/.config/hypr/scripts/translate_refine.sh
    if [ ! -x "$refine" ]; then
        printf '%s' "$v" | wl-copy
        notify-send -a "Переводчик" -t 5000 "Скопировано" "$v"
        exit 0
    fi
    nid=$(notify-send -p -a "Переводчик" -t 15000 "Уточняю перевод…" "$text")
    if best=$(timeout 30 "$refine" "$text" "$src" "$tgt" 2>/dev/null) && [ -n "$best" ]; then
        printf '%s' "$best" | wl-copy
        notify-send -r "${nid:-0}" -a "Переводчик" -t 8000 "Скопировано" "$best"
    else
        printf '%s' "$v" | wl-copy
        notify-send -r "${nid:-0}" -a "Переводчик" -t 8000 "Уточнение не ответило — скопирован черновик" "$v"
    fi
    exit 0
fi
printf '%s' "$v" | wl-copy
