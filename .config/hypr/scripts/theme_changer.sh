#!/usr/bin/env bash
# Rebuild the whole colour scheme from a wallpaper and push it into every
# running app that can accept colours without being restarted.
#
# Usage:  theme_changer.sh /path/to/wallpaper.png
#         theme_changer.sh --restore      (re-apply the last wallpaper)
#
# Called by waypaper (post_command) — see ~/.config/waypaper/config.ini

set -uo pipefail

CACHE="$HOME/.cache/matugen"
STATE="$CACHE/wallpaper"
MODE="${MATUGEN_MODE:-dark}"

mkdir -p "$CACHE"

if [ "${1:-}" = "--restore" ]; then
    WALLPAPER="$(cat "$STATE" 2>/dev/null)"
else
    WALLPAPER="${1:-}"
    # waypaper экранирует пробелы как «\ », а скобки — нет: без кавычек команда
    # «theme_changer.sh …wallhaven-zx2l1g\ (1)\ (1).jpg» падала на «(», и палитра,
    # Zen и лента SUPER+W оставались от прошлых обоев (28.09.2026). Теперь в
    # config.ini waypaper путь в кавычках, и «\ » приходит буквально — вернуть пробел.
    [ -f "$WALLPAPER" ] || WALLPAPER="${WALLPAPER//\\ / }"
fi

[ -z "$WALLPAPER" ] || [ ! -f "$WALLPAPER" ] && { echo "theme_changer: no usable wallpaper ('$WALLPAPER')" >&2; exit 1; }

# ---------------------------------------------------------------- generate --
# Extract the palette from a small thumbnail, not the full-size wallpaper:
# on a 7016x3600 JPEG that is 0.15 s / 25 MB instead of 0.71 s / 184 MB, and
# the resulting colours are identical to within one step of 255. The machine
# already runs close to its memory limit, and the allocation spike from
# decoding a huge image is exactly the wrong thing to do on every wallpaper
# change. `jpeg:size` lets libjpeg decode at reduced scale in the first place.
SRC="$WALLPAPER"
THUMB="$CACHE/wallpaper-thumb.png"
if command -v magick >/dev/null &&
   magick -define jpeg:size=1024x1024 "$WALLPAPER" -resize 512x512 "$THUMB" 2>/dev/null; then
    SRC="$THUMB"
fi

# scheme-fidelity keeps surface colours close to the source image's own hues;
# the default scheme-tonal-spot desaturates everything but the accent role
# down to ~9% saturation, which is why most of the desktop read as plain grey
# regardless of wallpaper. Measured: fidelity roughly doubles surface
# saturation (9% -> 21%) and text/background contrast actually improves
# (10:1 -> 14:1), so this is a straight upgrade, not a trade-off.
# 14.09.2026: fidelity -> vibrant. На почти одноцветных обоях (а их у пользователя
# большинство — сине-голубые) fidelity строит tertiary почти противоположным
# оттенком: на wallhaven-0wkqpq (туманный синий, 218°) tertiary был золотой
# #ecc15c (Δ175°), и жёлтые акценты расходились по 17 шаблонам из 26. Замер по
# 14 обоям из ~/wallpapers (matugen --dry-run): fidelity — tertiary в 130–168°
# от оттенков картинки, фоны 4–16%; vibrant — 1–34°, фоны 17–26%, primary тот же.
# Пользователь выбрал vibrant для всех обоев. Откат — theme_changer.sh.bak.vibrant-*.
if ! matugen image "$SRC" -t scheme-vibrant -m "$MODE" --prefer saturation; then
    echo "theme_changer: matugen failed" >&2
    exit 1
fi
printf '%s\n' "$WALLPAPER" > "$STATE"

# Шрифт темы Obsidian «Jarvis» из Настроек → Шрифты: matugen только что собрал
# theme.css со шрифтом по умолчанию, выбор вписывается поверх (app_fonts.py).
python3 "$HOME/.config/hypr/scripts/app_fonts.py" apply || \
    echo "theme_changer: не применился шрифт Obsidian" >&2

# The 16 ANSI colours are not a plain template: they are harmonised towards the
# accent as hard as they can be while staying distinguishable. See the script.
python3 "$HOME/.config/hypr/scripts/gen_term_colors.py" || \
    echo "theme_changer: не собралась палитра терминала" >&2

# Three gently distinct hues for the waybar CPU/RAM/temperature modules.
python3 "$HOME/.config/hypr/scripts/sensor_colors.py" || \
    echo "theme_changer: не собрались цвета датчиков" >&2

# Оттенок обоев в фонах GTK4. Схема scheme-fidelity делает тёмные
# поверхности почти нейтральными, и окна выглядят чужими на цветных обоях.
python3 "$HOME/.config/hypr/scripts/gtk_tint.py" >/dev/null || \
    echo "theme_changer: не подкрасились фоны GTK4" >&2

# Конфиг fastfetch. Не шаблоном matugen, а скриптом: fastfetch ждёт цвет
# голыми числами "38;2;R;G;B", а matugen подставляет "rgb(R, G, B)".
python3 "$HOME/.config/hypr/scripts/fastfetch_colors.py" >/dev/null || \
    echo "theme_changer: не собрался конфиг fastfetch" >&2

# Шейдеры kitty (след курсора) — в цвете акцента обоев.
python3 "$HOME/.config/hypr/scripts/kitty_shader_colors.py" >/dev/null || \
    echo "  kitty_shader_colors.py не отработал"

# ttyper (тренажёр набора) — цвета из палитры обоев.
python3 "$HOME/.config/hypr/scripts/ttyper_colors.py" >/dev/null || \
    echo "  ttyper_colors.py не отработал"

# VS Code не читает внешних файлов цветов — единственный вход в него это ключ
# workbench.colorCustomizations в settings.json, поэтому не шаблон, а слияние
# в чужой файл. Тема пользователя не трогается: colorCustomizations ложатся
# поверх неё. Редактор перечитывает settings.json сам, без перезапуска.
python3 "$HOME/.config/hypr/scripts/vscode_colors.py" || \
    echo "theme_changer: не подкрасился VS Code" >&2

# YouTube Music Desktop следит за своим customCSSPath и подставляет файл на
# лету, поэтому цвета доезжают без перезапуска приложения.
python3 "$HOME/.config/hypr/scripts/ytm_colors.py" >/dev/null || \
    echo "theme_changer: не собралась тема YouTube Music" >&2

# Яндекс Музыка: при запуске CSS вставляет хук в её app.asar, а открытое окно
# получает свежую палитру через порт отладки 9223 (ym_theme.py). Нет окна или
# порта — тихо пропускается.
( python3 "$HOME/.config/hypr/scripts/ym_theme.py" >/dev/null 2>&1 ) &

# Telegram: палитра из 467 ключей на основе штатной ночной темы клиента
# (она вытащена из его же бинарника, см. templates/telegram-night.palette).
# Файл только СОБИРАЕТСЯ; применяется он в самом Telegram — клиент держит
# тему в своей базе tdata и внешних файлов не перечитывает.
python3 "$HOME/.config/hypr/scripts/telegram_colors.py" >/dev/null || \
    echo "theme_changer: не собралась палитра Telegram" >&2

# kdeglobals also holds fonts/locale/click settings, so the colour groups are
# merged into it atomically instead of the file being replaced.
python3 "$HOME/.config/hypr/scripts/merge_kdeglobals.py" || \
    echo "theme_changer: kdeglobals merge failed" >&2

# ------------------------------------------------------------------ reload --
# Everything below is independent, so it runs in parallel: the slowest single
# step (waybar) then bounds the total instead of the sum.

# Waybar reloads its stylesheet by itself ("reload_style_on_change": true in
# config.jsonc) as soon as the generated colours.css changes — no signal here.
# Do NOT go back to SIGUSR2: that recreates the bar, and with it the
# org.kde.StatusNotifierWatcher name, which hangs tray clients like Telegram.

# Kitty: push the palette straight into every running instance through its
# control socket (instant, no flicker).
#
# 15.09.2026: перечитывание конфига (нужно для kitty-opacity.conf —
# transparent_background_colors зависит от палитры) больше НЕ через
# `pkill -SIGUSR1 kitty`. kitty при перечитывании ставит каждому окну font_size
# из kitty.conf, и размер, уменьшенный вручную (Ctrl+Shift+−), сбрасывался при
# каждой смене обоев . Теперь по сокету запускается kitten
# ~/.config/kitty/reload_keep_font.py: запоминает размер окон, перечитывает
# конфиг, возвращает размер. Проверено на пробном окне: scrollback_lines из
# конфига обновился, размер 8/13 остался; SIGUSR1 для сравнения сбросил на 11.
# SIGUSR1 остаётся только kitty без сокета — у них иначе не обновится прозрачность.
#
# 16.09.2026: ПЕРЕЧИТЫВАНИЯ БОЛЬШЕ НЕТ ВОВСЕ — ни kitten, ни SIGUSR1. Оно
# затевалось ради одного ключа, transparent_background_colors, и до живых окон
# этот ключ не доезжал никогда: kitty на каждом перечитывании накладывает
# сверху ~/.config/kitty/dark-theme.auto.conf (apply_new_options ->
# theme_colors.apply_theme -> patch_colors) и ставит окнам ровно тот набор
# прозрачных фонов, какой нашёлся в теме, — то есть пустой. Замер в живом окне:
# color_profile.get_transparent_background_color(0) = None и
# opts.transparent_background_colors = () и до перечитывания, и сразу после,
# при том что разбор самого kitty.conf отдаёт обе пары цветов.
#
# Включать ключ через тему пробовали (16.09) — он даёт полосу по краю
# каждого окна: отступ (window_padding_width 8) рисуется фоном окна, сетка —
# своей альфой, и они не совпадают ни при каком значении. Замер по скриншотам
# угла tty-clock: без ключа отступ и фон содержимого оба #121c33, с @0.85
# содержимое темнее отступа, с @0.62 и @1.0 — светлее. Обещание «removes the
# solid rectangle inside the translucent window padding» не подтвердилось.
#
# Заливки палитры по сокету и OSC-последовательностей ниже достаточно: цвета
# доезжают без перечитывания. Зато исчезла его цена — kitty при перечитывании
# сбрасывал font_size, и всё, что было правее новой (более узкой) сетки, окно
# теряло безвозвратно: у termdown от длинной надписи оставался обрубок. Откат — theme_changer.sh.bak.noreload-*.
#
# 04.10.2026 (Просьба: «смена обоев медленная»): замер — заливка 9 окон kitty шла
# по одному (0,67 с), spicetify/btop/cava/экран входа — друг за другом (0,9 с),
# и акцент виджетов доезжал только на 2,1 с. Теперь окна kitty заливаются
# параллельно, а spicetify/btop/cava/экран входа идут отдельными задачами — они
# палитру окон kitty не трогают. Бэкап theme_changer.sh.bak-parallel.
(
    for sock in /tmp/kitty-*; do
        [ -S "$sock" ] || continue
        kitty @ --to "unix:$sock" set-colors --all --configured \
            "$CACHE/colors-kitty.conf" >/dev/null 2>&1 &
    done
    wait
    # …and OSC colour escapes straight into every pty, which is what recolours
    # terminal windows that predate the socket, with no restart.
    python3 "$HOME/.config/hypr/scripts/broadcast_colors.py" >/dev/null 2>&1
    # СТРОГО ПОСЛЕ заливки и broadcast. Каждый из способов выше затирает подмену
    # акцента: заливка по сокету, перечитка конфига по SIGUSR1 и OSC-последовательности
    # broadcast_colors. Пока этот вызов стоял сразу после заливки, акцент честно
    # ставился — и тут же сбивался следующей строкой; замерено: после прогона у часов
    # был палитровый цвет, а ручной запуск этого же скрипта возвращал акцент.
    python3 "$HOME/.config/hypr/scripts/widget_accent.py" >/dev/null 2>&1
) &
# Spotify (spicetify, тема Jarvis): color.ini уже пересобран matugen,
# refresh вкладывает его в клиент; открытый Spotify подхватывает после
# перезагрузки окна (23.09.2026, вживую не проверено).
if command -v spicetify >/dev/null 2>&1 && [ -f "$HOME/.config/spicetify/Themes/Jarvis/color.ini" ]; then
    ( spicetify -q refresh >/dev/null 2>&1 ) &
fi
# btop renders 24-bit colour read from its theme file at startup, so the
# palette escapes above do nothing for it. Ctrl+R makes it re-read the
# theme in place — no restart, the window and its history stay put.
( python3 "$HOME/.config/hypr/scripts/reload_btop.py" >/dev/null 2>&1 ) &
# cava берёт цвет столбиков из своего конфига, а не из палитры окна:
# в noncurses-выводе шестнадцатеричный foreground работает только в
# кавычках (проверено в псевдотерминале — без кавычек cava молча
# игнорирует ключ). live-config = 1, поэтому запущенные экземпляры
# перечитывают конфиг сами, без перезапуска.
( python3 "$HOME/.config/hypr/scripts/cava_colors.py" >/dev/null 2>&1 ) &
# Экран входа «Как рабочий стол»: новые обои и палитра — в тему SDDM, если
# этот вариант выбран (иначе скрипт ничего не делает). Помощник от root
# через sudo -n, см. login_theme.py (14.09.2026).
( python3 "$HOME/.config/hypr/scripts/login_theme.py" sync >/dev/null 2>&1 ) &

# Fish stores its syntax colours in universal variables, so sourcing them once
# updates every running shell instantly.
( command -v fish >/dev/null && fish -c "source $CACHE/colors.fish" >/dev/null 2>&1 ) &

# Размытие обоев (переключатель в «Настройках»): новые обои приходят чёткими,
# поэтому после смены их надо размыть заново. Когда переключатель выключен,
# скрипт просто ставит исходную картинку и ничего не делает лишнего.
( python3 "$HOME/.config/hypr/scripts/wallpaper_blur.py" apply >/dev/null 2>&1 ) &
# Steam (SpaceTheme через Millennium) — цвета палитры и шрифт системы; Steam
# подхватывает их при перезапуске (28.09.2026).
( python3 "$HOME/.config/hypr/scripts/steam_space.py" apply >/dev/null 2>&1 ) &

# Discord, пиксельный вид (08.10.2026): matugen собрал тему в кэш, sync кладёт её в
# themes/ Vencord (или заглушку, если выключена) — открытый Discord подхватит сам.
( python3 "$HOME/.config/hypr/scripts/discord_pixel.py" sync >/dev/null 2>&1 ) &

# Приглашение fish (Tide): сегмент пути красится акцентом обоев напрямую.
# Через ANSI-слот «blue» он уезжал в розовое: генератор палитры поворачивает
# все слоты к акценту, и при тёплых обоях «синий» переставал быть синим
# (замерено 21.09.2026).
( python3 "$HOME/.config/hypr/scripts/tide_colors.py" >/dev/null 2>&1 ) &

# Hyprland window borders. Deliberately NOT `hyprctl reload`: a full config
# reload throws away the cursor theme applied at login with `hyprctl setcursor`
# (verified — the pointer turns into Hyprland's default white cross), and it is
# far heavier than setting the two colours that actually changed.
# Только под Hyprland: в niri hyprctl падал с «HYPRLAND_INSTANCE_SIGNATURE not set»
# и печатал ошибку при каждой смене обоев (04.10.2026).
[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] && (
    # shellcheck source=/dev/null
    if . "$CACHE/hypr-colors.sh" 2>/dev/null; then
        # This config is Lua, and `hyprctl keyword` refuses to touch a
        # non-legacy parser ("Use eval"), so the setting goes through eval.
        # Errors are NOT hidden here: a silent failure is how the borders
        # quietly stopped following the wallpaper once already.
        : "${M_ACTIVE_BORDER2:=$M_ACTIVE_BORDER}"   # старый кэш без второго цвета
        out=$(hyprctl eval "hl.config({ general = { col = {
                  active_border = { colors = { \"$M_ACTIVE_BORDER\", \"$M_ACTIVE_BORDER2\" }, angle = 45 },
                  inactive_border = \"$M_INACTIVE_BORDER\" } } })" 2>&1)
        [ "$out" = "ok" ] || echo "theme_changer: рамки не применились: $out" >&2
    fi
) &

# GTK3. Прежняя строка тут делала touch по gtk.css — и не делала ничего:
# замерено на скрытом пробнике, что GTK3 читает пользовательский CSS ровно
# один раз при старте и не перечитывает его ни на touch, ни на перезапись,
# ни на смену gtk-theme-name. Поэтому окна, открытые до смены обоев (тот же
# блокнот), оставались в старой палитре до перезапуска.
# Работает единственный путь: colorreload-gtk-module из kde-gtk-config (он
# прописан в gtk-modules, то есть загружен в каждом приложении GTK3) следит
# за ~/.config/gtk-3.0/colors.css и на изменение цепляет его провайдером
# поверх gtk.css. Скрипт собирает туда текущую палитру и ПОДМЕНЯЕТ файл
# через rename: запись на месте модуль не замечает вовсе, подмену — за
# доли секунды (обе ветки проверены отдельно).
( python3 "$HOME/.config/hypr/scripts/gtk_live_colors.py" ) &
# Папки в значках Papirus — в цвет обоев (пользовательская тема Papirus-Wall).
( python3 "$HOME/.config/hypr/scripts/folder_colors.py" ) &
# Пиксельные значки папок и файлов (тема Jarvis-Pixel) — под новую палитру,
# только если они выбраны (Настройки → Значки; состояние state/icon-theme).
# build заодно возвращает тему в kdeglobals: шаблон matugen выше каждый раз
# пишет туда Papirus-Wall. Сборка ~0,5 с. См. icon_theme.py (02.10.2026).
# pixel-all (05.10.2026): значки программ не зависят от обоев — они берутся
# из кэша готовыми, перерисовываются только папки.
case "$(cat "$HOME/.config/hypr/state/icon-theme" 2>/dev/null)" in
    pixel|pixel-all)
        ( python3 "$HOME/.config/hypr/scripts/icon_theme.py" build >/dev/null 2>&1 ) & ;;
esac

# Блокнот (mousepad). Рамку ему перекрашивает модуль выше, а поле текста —
# схема GtkSourceView, которую приложение читает один раз при старте. Поэтому
# блокнот перезапускается: сессия у него в gsettings (session-restore=always),
# вкладки вернутся сами. Если есть несохранённый текст (звёздочка в
# заголовке), скрипт ничего не трогает — см. mousepad_retheme.sh (22.09.2026).
( bash "$HOME/.config/hypr/scripts/mousepad_retheme.sh" ) &

# Подсветка Razer BlackWidow V3 — в гамме обоев по профилю пользователя
# (static-white: три цвета на карте клавиш, раскладка сохраняется, цвета
# берутся из палитры). См. kbd_colors.py (23.09.2026).
( python3 "$HOME/.config/hypr/scripts/kbd_colors.py" >/dev/null 2>&1 ) &

# Курсор Jarvis — MSTCRSR в гамме обоев: форма одна, палитра из matugen
# (23.09.2026). Тема пересобирается попеременно в Jarvis-Cursor-A/B — при
# прежнем имени niri картинки курсора не перечитывает (проверено снимком с
# курсором) — и имя уходит в ~/.cache/matugen/niri-cursor.kdl, gsettings и
# index.theme для Xwayland. Сборка ~0,1 с. Выключить: cursor_colors.py --off.
# Через cursor_theme.py: он пересобирает тот курсор, что выбран в «Настройках» —
# Jarvis или «гальку в цветах обоев»; остальные от обоев не зависят (28.09.2026).
# Значки wlogout (если выбраны новые) — под новую палитру.
( python3 "$HOME/.config/hypr/scripts/wlogout_icons.py" regen >/dev/null 2>&1 ) &
( python3 "$HOME/.config/hypr/scripts/cursor_theme.py" refresh > "$CACHE/cursor_colors.log" 2>&1 ) &

# GTK4 такого модуля не имеет: там палитра доезжает только при следующем
# запуске приложения. Файл всё равно обновлён шаблоном matugen выше.

# Qt: qt6ct re-reads its palette when its own config file changes; KDE/KF6 apps
# watch kdeglobals over D-Bus (KConfigWatcher), so tell them it changed.
(
    touch "$HOME/.config/qt6ct/qt6ct.conf"
    # No kconfig ConfigChanged broadcast here. Measured: on that signal Dolphin
    # goes from 107 MB to over 2 GB within seconds and gets OOM-killed, which
    # is exactly the "froze for a few seconds and the window vanished" symptom.
    # A control run without the signal holds steady at 107 MB. Touching
    # qt6ct.conf above is the safe path and still updates Qt apps live.
) &

# Notification centre and eww widgets.
( command -v swaync-client >/dev/null && swaync-client --reload-css >/dev/null 2>&1 ) &
( command -v eww >/dev/null && eww reload >/dev/null 2>&1 ) &

wait

# ------------------------------------------------------------------ проверка --
# Каждая поломка в этой цепочке была тихой: правило waybar искало класс окна,
# которого приложение больше не имеет; `touch gtk.css` не делал ничего; имя
# цвета никем не определялось. Ни одна не давала ошибки — всё «работало»,
# просто цвет был не тот. Поэтому в конце цепочка проверяется сама.
#
# Уведомление только на СЛОМАНО (код 1). Предупреждения — вроде окна без своей
# иконки или приложения, которое старше палитры, — в лог, но не в лицо: иначе
# всплывашка на каждую смену обоев быстро перестанет читаться.
# Снимок конфигов в git — молча и только если что-то реально менялось (при
# отсутствии изменений скрипт не делает коммита). Смена обоев — единственный
# момент, когда вся цепочка заведомо прогоняется целиком, так что точка
# отката всегда свежая, и её не надо помнить снимать руками.
( "$HOME/.config/hypr/scripts/theme_snapshot.sh" снять \
      "авто: смена обоев $(date +'%d.%m %H:%M')" >/dev/null 2>&1 ) &

(
    doctor="$HOME/.config/hypr/scripts/theme_doctor.py"
    log="$CACHE/doctor.log"

    # Отпечаток палитры — защита от ложной тревоги при быстром перелистывании
    # обоев. Полный прогон цепочки занимает ~2.6 с (замер 16.09.2026), а
    # Пользователь, подбирая обои, менял их каждые 3 с — шесть смен за 19 с. Прогоны
    # накладываются, и доктор СТАРОГО прогона читает уже новый vivid.txt:
    # цвет у cava от прошлых обоев, акцент от следующих, и проверка честно
    # докладывает расхождение, которого через секунду уже нет. Две таких
    # всплывашки «цепочка сломана» пользователь и увидел.
    #
    # Поэтому отпечаток снимается до проверки и сверяется после. Изменился —
    # значит уже идёт следующий прогон, и ругаться должен его доктор, а не наш.
    # Молчком это не проглатывается: строка уходит в лог, иначе получилась бы
    # ровно та тихая поломка, ради ловли которой доктор и написан.
    fingerprint() { cat "$CACHE/vivid.txt" "$STATE" 2>/dev/null | md5sum; }

    if [ -f "$doctor" ]; then
        before="$(fingerprint)"
        if ! python3 "$doctor" > "$log" 2>&1; then
            if [ "$before" = "$(fingerprint)" ]; then
                command -v notify-send >/dev/null && notify-send -u critical \
                    "Тема обоев: цепочка сломана" \
                    "$(grep '^X ' "$log" | head -3)
Подробности: $log"
                cat "$log" >&2
            else
                printf '\n%s\n' "проверка пришлась на смену обоев: палитра" \
                    "сменилась прямо во время неё, уведомление подавлено —" \
                    "доложит доктор следующего прогона" >> "$log"
            fi
        fi
    fi
) &

wait
exit 0
