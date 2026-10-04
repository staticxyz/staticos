#!/usr/bin/env bash
# Перезапустить блокнот (mousepad), чтобы он подхватил новую палитру.
#
# Зачем. Рамку и меню GTK3 перекрашивает colorreload-gtk-module на лету, а
# ПОЛЕ ТЕКСТА — это GtkSourceView со своей схемой цветов
# (~/.local/share/gtksourceview-4/styles/matugen.xml). Схему менеджер читает
# один раз при старте приложения и держит в памяти; повторный выбор в меню
# отдаёт ту же копию. Единственный путь — перезапуск (22.09.2026).
#
# Безопасность. mousepad 0.7 хранит сессию в gsettings
# (org.xfce.mousepad.state.application session) и при
# session-restore='always' поднимает те же вкладки при следующем старте —
# открытые файлы не теряются. Но НЕСОХРАНЁННЫЙ текст пропал бы, поэтому:
# если хоть у одного окна в заголовке звёздочка («*autostart.txt - Mousepad»),
# ничего не трогаем и выходим. Ждём, пока пользователь сохранит; следующая смена
# обоев попробует снова.
#
# Вызывается из theme_changer.sh; вручную: mousepad_retheme.sh [--force]
set -uo pipefail

CLASS="org.xfce.mousepad"
[ -n "${NIRI_SOCKET:-}" ] || exit 0            # только под niri

titles=$(niri msg --json windows 2>/dev/null | jq -r --arg c "$CLASS" \
    '.[] | select(.app_id==$c) | .title // ""')
[ -n "$titles" ] || exit 0                     # блокнот не запущен — нечего делать

if [ "${1:-}" != "--force" ] && printf '%s\n' "$titles" | grep -q '^\*'; then
    echo "mousepad_retheme: есть несохранённые вкладки, перезапуск отложен" >&2
    exit 0
fi

restore=$(gsettings get org.xfce.mousepad.preferences.file session-restore 2>/dev/null)
if [ "$restore" != "'always'" ] && [ "${1:-}" != "--force" ]; then
    echo "mousepad_retheme: session-restore=$restore, вкладки не восстановятся — пропуск" >&2
    exit 0
fi

# Где стоят окна блокнота и что в фокусе — чтобы вернуть всё как было. Без этого
# восстановленное окно открывалось плавающим посреди ТЕКУЩЕГО стола, даже если
# блокнот был убран на другой (24.09.2026). См. mousepad_place.py.
SNAP=$(mktemp -t mousepad-place.XXXXXX)
python3 "$HOME/.config/hypr/scripts/mousepad_place.py" snapshot "$SNAP"

pkill -x mousepad
for _ in $(seq 1 30); do pgrep -x mousepad >/dev/null || break; sleep 0.1; done
pgrep -x mousepad >/dev/null && pkill -KILL -x mousepad
sleep 0.2
# Первый экземпляр после закрытия сам восстанавливает сессию (см. notepad.sh).
setsid mousepad >/dev/null 2>&1 < /dev/null &
python3 "$HOME/.config/hypr/scripts/mousepad_place.py" restore "$SNAP"
rm -f "$SNAP"
