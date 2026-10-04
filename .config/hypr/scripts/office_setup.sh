#!/bin/sh
# Настройка LibreOffice после установки. 02.10.2026.
#
#   1. пользователь ставит сам (sudo — только его руками):
#        sudo pacman -Syu libreoffice-fresh libreoffice-fresh-ru hunspell-ru hunspell-en_us hyphen ttf-carlito ttf-caladea
#   2. Затем: office_setup.sh  — без sudo.
#
# Что делает:
#   * файлы Word/Excel/PowerPoint и их открытые аналоги открываются LibreOffice
#     (doc, docx, rtf, odt → Writer; xls, xlsx, ods, csv → Calc; ppt, pptx, odp → Impress);
#   * проверяет, что .doc и .docx действительно читаются (пробное преобразование в PDF);
#   * включает автосохранение раз в 5 минут и резервную копию.
# Шрифты Carlito и Caladea — метрические двойники Calibri и Cambria: документы из
# Word не «поедут» по страницам. Русский интерфейс — libreoffice-fresh-ru, проверка
# орфографии — hunspell-ru.
set -u
command -v soffice >/dev/null 2>&1 || { echo "LibreOffice ещё не установлен — сначала команда из шапки этого файла."; exit 1; }

set_default() {  # $1 — ярлык, остальное — типы
    app=$1; shift
    for t in "$@"; do xdg-mime default "$app" "$t"; done
}
set_default libreoffice-writer.desktop \
    application/msword application/vnd.openxmlformats-officedocument.wordprocessingml.document \
    application/vnd.oasis.opendocument.text application/rtf text/rtf \
    application/vnd.ms-word.document.macroEnabled.12 application/vnd.openxmlformats-officedocument.wordprocessingml.template
set_default libreoffice-calc.desktop \
    application/vnd.ms-excel application/vnd.openxmlformats-officedocument.spreadsheetml.sheet \
    application/vnd.oasis.opendocument.spreadsheet text/csv application/vnd.ms-excel.sheet.macroEnabled.12
set_default libreoffice-impress.desktop \
    application/vnd.ms-powerpoint application/vnd.openxmlformats-officedocument.presentationml.presentation \
    application/vnd.oasis.opendocument.presentation
echo "Открытие по умолчанию:"
for t in application/msword application/vnd.openxmlformats-officedocument.wordprocessingml.document \
         application/vnd.ms-excel application/vnd.openxmlformats-officedocument.presentationml.presentation; do
    printf '  %-75s %s\n' "$t" "$(xdg-mime query default "$t")"
done

# Проверка чтения .doc/.docx: делаем документ, сохраняем в оба формата, читаем обратно в PDF.
T=$(mktemp -d)
printf 'Проверка LibreOffice: русский текст и English text.\n' > "$T/probe.txt"
soffice --headless --convert-to doc  --outdir "$T" "$T/probe.txt"  >/dev/null 2>&1
soffice --headless --convert-to docx --outdir "$T" "$T/probe.txt"  >/dev/null 2>&1
mkdir "$T/pdf"
for f in "$T/probe.doc" "$T/probe.docx"; do
    if [ -s "$f" ] && soffice --headless --convert-to pdf --outdir "$T/pdf" "$f" >/dev/null 2>&1 \
       && [ -s "$T/pdf/$(basename "${f%.*}").pdf" ]; then
        echo "  читается и сохраняется: .${f##*.}"
    else
        echo "  НЕ получилось: .${f##*.}"
    fi
    rm -f "$T/pdf/"*.pdf
done
rm -rf "$T"

# Автосохранение: профиль появляется после первого запуска (он уже был — пробные преобразования).
REG="$HOME/.config/libreoffice/4/user/registrymodifications.xcu"
if [ -f "$REG" ] && ! grep -q 'TimeIntervall' "$REG"; then
    cp "$REG" "$REG.bak-jarvis"
    sed -i 's#</oor:items>#<item oor:path="/org.openoffice.Office.Recovery/AutoSave"><prop oor:name="Enabled" oor:op="fuse"><value>true</value></prop></item><item oor:path="/org.openoffice.Office.Recovery/AutoSave"><prop oor:name="TimeIntervall" oor:op="fuse"><value>5</value></prop></item><item oor:path="/org.openoffice.Office.Common/Save/Document"><prop oor:name="CreateBackup" oor:op="fuse"><value>true</value></prop></item></oor:items>#' "$REG"
    echo "Автосохранение раз в 5 минут и резервная копия включены (копия настроек: $REG.bak-jarvis)."
fi
echo "Готово."
