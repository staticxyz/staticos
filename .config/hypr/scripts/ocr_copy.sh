#!/bin/sh
# ocr_copy.sh — выделить область экрана, распознать текст, положить в буфер.
#                                                              23.09.2026
# Shift+Print. Отдельным сочетанием, а не кнопкой в экране выбора niri:
# тот экран рисует сам композитор (Print { screenshot; }), его кнопки
# («снимок», «курсор») встроенные, свою туда не добавить.
#
# Порядок: slurp даёт область → grim снимает её в файл → ImageMagick готовит
# картинку под распознавание → tesseract читает → wl-copy кладёт в буфер.
#
# Подготовка картинки важнее выбора языка: tesseract рассчитан на скан ~300
# dpi, а с экрана приходит ~96. Поэтому область увеличивается втрое и
# переводится в серый — на мелком шрифте это разница между связным текстом
# и мусором.
#
# Порядок чтения: pxocr.py (точно по растрам системного шрифта) → tesseract →
# если область была на окне kitty, распознанное служит приметой, а текст
# берётся у самого терминала (term_text.py).
#
#   ocr_copy.sh            распознать и скопировать
#   OCR_LANG=eng ocr_copy.sh   другой язык (по умолчанию rus+eng)
#   OCR_RAW=1 ocr_copy.sh      не подставлять текст терминала

set -u
LANGS=${OCR_LANG:-rus+eng}

say() { notify-send -a "Распознавание" "$1" "${2:-}" 2>/dev/null; }

# Языки могут быть не установлены — tesseract тогда молча падает.
have=$(tesseract --list-langs 2>/dev/null | tail -n +2)
want_ok=1
for l in $(printf '%s' "$LANGS" | tr '+' ' '); do
    printf '%s\n' "$have" | grep -qx "$l" || want_ok=0
done
if [ "$want_ok" -eq 0 ]; then
    say "Нет языковых данных" "Поставьте: sudo pacman -S tesseract-data-rus tesseract-data-eng"
    exit 1
fi

# Заморозка экрана на время выделения — общая с Super+Print (freeze_lib.sh):
# снимок делается в момент нажатия, показывается поверх, область вырезается
# из него. Без заморозки движение мыши под slurp прокручивало ленту niri и
# переводило фокус — «экран двигается» (23.09.2026), а hyprpicker, стоявший
# тут прежде, картинку не замораживал вовсе (29.09.2026).
. "$HOME/.config/hypr/scripts/freeze_lib.sh"
freeze_start
geom=$(pick_area) || { freeze_cleanup; exit 0; }          # Esc — тихий выход
[ -n "$geom" ] || { freeze_cleanup; exit 0; }
unfreeze                                                   # экран отпускаем сразу

tmp=$(mktemp -t ocr-XXXXXX.png) || { freeze_cleanup; exit 1; }
trap 'freeze_cleanup; rm -f "$tmp" "$tmp.prep.png"' EXIT HUP INT TERM

crop_area "$geom" "$tmp" || { say "Не вышло снять область"; exit 1; }

# Сначала — точное чтение по растрам системного шрифта (pxocr.py): весь стол
# рисуется PxPlus 6x8 без сглаживания, и клетки сравниваются с самим шрифтом
# (99 % на образцах, 0.3 с). Не тот шрифт или дробный масштаб — он честно
# выходит с кодом 1, и в дело идёт tesseract.
source="точно по шрифту"
text=$(python3 "$HOME/.config/hypr/scripts/pxocr.py" "$tmp" 2>/dev/null) || text=""
if [ -z "$text" ]; then
    source="распознано"
    magick "$tmp" -colorspace gray -resize 300% -sharpen 0x1 "$tmp.prep.png" 2>/dev/null \
        || cp "$tmp" "$tmp.prep.png"
    # --psm 6: «один сплошной блок текста». Для куска экрана это вернее, чем
    # разбор страницы по умолчанию, который ищет колонки и ломает строки.
    text=$(tesseract "$tmp.prep.png" - -l "$LANGS" --psm 6 2>/dev/null)
    text=$(printf '%s' "$text" | sed -e 's/[[:space:]]*$//' -e '/./,$!d')
fi

if [ -z "$(printf '%s' "$text" | tr -d '[:space:]')" ]; then
    say "Текст не распознан" "Попробуйте выделить крупнее или ровнее"
    exit 1
fi

# Если это был терминал — берём его текст дословно, а распознанное служит
# только приметой, по которой ищется окно. Шрифт PxPlus 6x8 растровый, и
# tesseract на нём выдаёт 88 % символов: строку не вставить и не выполнить.
# term_text.py молчит (код 1), если окно не опознано уверенно.
exact=""
[ "${OCR_RAW:-0}" = 1 ] || [ "$source" != "распознано" ] \
    || exact=$(printf '%s' "$text" | python3 "$HOME/.config/hypr/scripts/term_text.py" 2>/dev/null)
if [ -n "$exact" ]; then
    text=$exact
    source="из терминала, дословно"
fi

printf '%s' "$text" | wl-copy
lines=$(printf '%s\n' "$text" | wc -l)
say "Скопировано, строк: $lines ($source)" "$(printf '%s' "$text" | head -c 120)"
