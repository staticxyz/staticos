#!/bin/sh
# Качественный перевод для Enter в SUPER+C.
#
#     translate_best.sh "текст" rus_Cyrl eng_Latn      -> перевод в stdout
#
# С 17.10.2026 — Google (translate_google.py) с запасом времени побольше,
# чем у живого предпросмотра. Нет сети — код 1, вызывающий копирует черновик NLLB.
set -u
exec python3 "$(dirname "$0")/translate_google.py" "$1" "${2:-rus_Cyrl}" "${3:-eng_Latn}"
