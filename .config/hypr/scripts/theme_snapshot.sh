#!/usr/bin/env bash
# Снимки всей цветовой цепочки в git, с откатом.
#
# ЗАЧЕМ. Файлов, из которых собирается тема, два десятка, и лежат они в разных
# местах: скрипты в hypr/scripts, шаблоны в matugen, правила в waybar, стили в
# профиле браузера, симлинки в ~/.local/bin. Рядом с ними копились россыпью
# файлы вида *.bak.2026-09-05_044613 — по одному на каждую правку, без связи
# между собой и без ответа на вопрос «а что вообще менялось вместе».
# Здесь вместо этого одна история: снимок берёт всё разом, откат возвращает
# всё разом.
#
#   theme_snapshot.sh                      снять снимок (если что-то менялось)
#   theme_snapshot.sh снять "сообщение"    то же, со своим описанием
#   theme_snapshot.sh список               история снимков
#   theme_snapshot.sh diff [снимок]        чем диск отличается от снимка
#   theme_snapshot.sh откат <снимок>       вернуть ВСЁ из снимка
#   theme_snapshot.sh откат <снимок> <путь>  вернуть один файл
#
# Хранилище: ~/.local/share/theme-snapshots (обычный git-репозиторий, можно
# смотреть чем угодно). Генерируемые файлы (~/.cache/matugen, matugen.css в
# профилях) сюда НЕ попадают: они пересобираются из шаблонов за секунду, и
# держать их в истории значит утопить в шуме те правки, ради которых она есть.
set -uo pipefail

REPO="$HOME/.local/share/theme-snapshots"
LWCHROME=".config/librewolf/librewolf/xmfr3xyd.default-default/chrome"
LWEXT=".config/librewolf/librewolf/xmfr3xyd.default-default/extensions"

# Пути относительно $HOME. Каталоги разворачиваются целиком.
TRACKED=(
    ".config/hypr/scripts"
    ".config/matugen/config.toml"
    ".config/matugen/templates"
    ".config/waybar/config.jsonc"
    ".config/waybar/style.css"
    # Скругление таблеток бара (генерирует scripts/bar_rounding.py).
    ".config/waybar/rounding.css"
    # Виды бара (bar_style.py): отступы/положение/высота и оформление подложки.
    ".config/waybar/looks"
    ".config/waypaper/config.ini"
    # Лаунчер WIN+SPACE и переключатель окон; палитру им даёт matugen.
    ".config/rofi"
    # Редактор снимков SHIFT+Print (глобальные клавиши в нём выключены — иначе падает).
    ".config/ksnip/ksnip.conf"
    # Команда лаунчера (menu) для WIN+SPACE — теперь обёртка rofi_launcher.py.
    ".config/hypr/programs.lua"
    # Правила окон (в том числе плавающий waypaper).
    ".config/hypr/workspace.lua"
    # Игровые правила и VRR (15.09.2026).
    ".config/hypr/gaming.lua"
    ".config/hypr/hyprland.lua"
    # Оболочка: свои функции fish (chat, и что появится дальше) — 23.09.2026.
    ".config/fish/functions"
    # Сеанс Niri: настройки и его скрипты (21.09.2026).
    ".config/niri/config.kdl"
    ".config/niri/scripts"
    # Zen: живая тема, загрузчик autoconfig, расширения, ярлык (15.09.2026).
    ".config/zen-jarvis"
    ".local/opt/zen/config.js"
    ".local/opt/zen/defaults/pref/config-prefs.js"
    ".local/opt/zen/distribution/policies.json"
    ".local/share/applications/zen.desktop"
    ".config/zen/yv7czwfm.Default (release)/user.js"
    # «Настройки» в меню
    ".local/share/applications/jarvis-settings.desktop"
    # тема значков GTK4
    ".config/gtk-4.0/settings.ini"
    # тема значков Qt
    ".config/qt6ct/qt6ct.conf"
    # выбор затемнения и его сила
    ".config/hypr/state"
    # скругление, затемнение, анимации
    ".config/hypr/visuals.lua"
    # автозапуск (hyprsunset и прочее)
    ".config/hypr/autostart.lua"
    # бинды
    # Раскладка клавиатуры, чувствительность мыши и режим фокуса при наведении.
    ".config/hypr/input.lua"
    ".config/hypr/keybindings.lua"
    # Клавиши ленты (scrolling), подключаются из keybindings.lua.
    ".config/hypr/ribbon_binds.lua"
    # Выбор раскладки (лента/классика), его читает visuals.lua.
    ".config/hypr/state/layout-mode"
    # Карта ленты в баре: включена или нет (ribbon_map.py on|off).
    ".config/hypr/state/ribbon-map"
    # простой: приглушение, блокировка, сон
    ".config/hypr/hypridle.conf"
    # ночной режим по расписанию
    ".config/hypr/hyprsunset.conf"
    # экран блокировки
    ".config/hypr/hyprlock.conf"
    # Стиль экрана блокировки «Астронавт» (выбор в Настройках, 14.09.2026).
    ".config/hypr/hyprlock-astronaut.conf"
    # kitten перечитывания конфига kitty без сброса размера шрифта (15.09.2026).
    ".config/kitty/reload_keep_font.py"
    # Конфиг kitty: шрифт выбирается в Настройках → Шрифты (app_fonts.py, 17.09.2026).
    ".config/kitty/kitty.conf"
    ".config/fontconfig/conf.d/60-jarvis-system-font.conf"
    # Уведомления swaync: вид (кнопки акцентом, компактные карточки) и
    # настройки окна — правились 20.09.2026, до этого снимками не покрывались.
    ".config/swaync/style.css"
    ".config/swaync/config.json"
    # Подсказка раскладки и CapsLock (окно eww layout-osd).
    ".config/eww/eww.yuck"
    ".config/eww/eww.scss"
    # пипетка
    ".local/bin/picker"
    # Блочные часы (tclock зовёт их вместо tty-clock) — 23.09.2026.
    ".local/bin/jclock"
    # пипетка в rofi
    ".local/share/applications/picker.desktop"
    ".config/cava/config"
    ".config/gtk-3.0/gtk.css"
    ".config/gtk-3.0/settings.ini"
    ".config/gtk-3.0/colors-breeze-base.css"
    ".config/gtk-4.0/gtk.css"
    "$LWCHROME/userChrome.css"
    "$LWCHROME/userContent.css"
    "$LWEXT/matugen-theme@local.xpi"
    ".librewolf/native-messaging-hosts/matugen_colors.json"
    # Настройки Sublime: в них выбор схемы, которую собирает matugen.
    # Сам файл схемы не пишем — он выходной, пересобирается из шаблона.
    ".config/sublime-text/Packages/User/Preferences.sublime-settings"
    # Сторож GTK-цветов от kded6/gtkconfig (сам скрипт — в hypr/scripts).
    ".config/systemd/user/gtk-guard.path"
    ".config/systemd/user/gtk-guard.service"
    ".local/bin/theme-doctor"
    ".local/bin/theme-snapshot"
    ".local/bin/tclock"
    # Вентиляторы Clevo через tuxedo_io (20.09.2026).
    # Меню питания (кнопка в баре): действия кнопок.
    ".config/wlogout/layout"
    ".local/bin/fan"
    ".local/share/fanctl"
    ".config/pipewire/pipewire-pulse.conf.d"
    ".local/bin/timer"
    ".local/bin/tmatrix"
    ".local/bin/tdown"
    ".local/bin/ffetch"
    ".config/spotify-launcher.conf"
    ".config/spicetify/config-xpui.ini"
    ".config/spicetify/Themes/Jarvis"
    ".config/matugen/templates/spicetify-color.ini"
    ".local/share/applications/spotify-launcher.desktop"
    ".config/lesskey"
)

# Мусор, который иначе утащит в историю сам себя.
EXCLUDE_RE='\.bak\.|\.negtest$|__pycache__|\.pyc$|\.new$'

die() { echo "theme_snapshot: $*" >&2; exit 1; }

init_repo() {
    if [ ! -d "$REPO/.git" ]; then
        mkdir -p "$REPO" || die "не создать $REPO"
        git -C "$REPO" init -q -b main || die "git init не прошёл"
        # Личность только для этого репозитория: глобальную не трогаем, а без
        # неё git откажется коммитить.
        git -C "$REPO" config user.name  "theme_snapshot"
        git -C "$REPO" config user.email "theme_snapshot@localhost"
    fi
}

# README пишется ПОСЛЕ сборки дерева, а не при init: sync_tree вычищает всё,
# кроме .git, и созданный заранее файл исчезал бы из первого же снимка.
write_readme() {
    cat > "$REPO/README" <<'EOF'
Снимки цветовой цепочки рабочего стола.

Собирает и откатывает ~/.config/hypr/scripts/theme_snapshot.sh — там же
в шапке список отслеживаемых путей и все команды. Короткая версия:

    theme-snapshot                  снять снимок
    theme-snapshot список           история
    theme-snapshot diff             чем диск отличается от последнего снимка
    theme-snapshot откат <снимок>   вернуть всё из снимка

Проверить, что цепочка цела, и понять, где палитра застряла:

    theme-doctor

Генерируемые файлы (~/.cache/matugen, matugen.css в профилях) сюда не
попадают: они пересобираются из шаблонов при следующей смене обоев.
Снимок берётся сам в конце каждой смены обоев, если что-то менялось.
EOF
}

# Собрать рабочее дерево заново: так удаление файла на диске честно
# становится удалением в истории, а не остаётся навсегда в снимке.
sync_tree() {
    find "$REPO" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} + || \
        die "не очистить рабочее дерево"
    local n=0
    while IFS= read -r rel; do
        [ -z "$rel" ] && continue
        mkdir -p "$REPO/$(dirname "$rel")"
        cp -a "$HOME/$rel" "$REPO/$rel" && n=$((n + 1))
    done < <(list_files)
    write_readme
    echo "$n"
}

list_files() {
    local p
    for p in "${TRACKED[@]}"; do
        if [ -d "$HOME/$p" ] && [ ! -L "$HOME/$p" ]; then
            find "$HOME/$p" -type f -o -type l | sed "s|^$HOME/||"
        elif [ -e "$HOME/$p" ] || [ -L "$HOME/$p" ]; then
            printf '%s\n' "$p"
        fi
    done | grep -Ev "$EXCLUDE_RE" | sort -u
}

cmd_snapshot() {
    init_repo
    local msg="${1:-снимок $(date +'%d.%m.%Y %H:%M')}"
    local n; n=$(sync_tree)
    git -C "$REPO" add -A || die "git add не прошёл"
    if git -C "$REPO" diff --cached --quiet; then
        echo "изменений нет — снимок не нужен ($n файлов под наблюдением)"
        return 0
    fi
    git -C "$REPO" commit -q -m "$msg" || die "коммит не прошёл"
    echo "снимок сделан: $(git -C "$REPO" log -1 --format='%h  %s')"
    git -C "$REPO" show --stat --oneline HEAD | tail -n +2
}

cmd_list() {
    init_repo
    git -C "$REPO" log --format='%h  %ad  %s' --date=format:'%d.%m %H:%M' || \
        echo "снимков ещё нет"
}

cmd_diff() {
    init_repo
    local ref="${1:-HEAD}"
    sync_tree >/dev/null
    git -C "$REPO" add -A
    if git -C "$REPO" diff --cached --quiet "$ref" 2>/dev/null; then
        echo "диск совпадает со снимком $ref"
    else
        git -C "$REPO" diff --cached "$ref"
    fi
    git -C "$REPO" reset -q
}

cmd_restore() {
    init_repo
    local ref="${1:-}"; local only="${2:-}"
    [ -z "$ref" ] && die "нужен снимок: theme_snapshot.sh откат <снимок> [путь]"
    git -C "$REPO" rev-parse --verify "$ref^{commit}" >/dev/null 2>&1 || \
        die "нет такого снимка: $ref"

    # Страховка перед откатом: то, что сейчас на диске, тоже попадает в
    # историю — иначе откат был бы дорогой в одну сторону.
    cmd_snapshot "перед откатом на $ref" >/dev/null

    # Режим из ls-tree, а не догадки: 120000 — симлинк, 100755 — исполняемый.
    # Без этого разбора откат превратил бы ~/.local/bin/tclock из ссылки в
    # текстовый файл с путём внутри, и команда перестала бы запускаться —
    # ровно та поломка, от которой снимки и заводились.
    local restored=0 links=0 mode type sha rel
    while read -r mode type sha rel; do
        [ "$type" = "blob" ] || continue
        # README принадлежит хранилищу, а не $HOME: без этой строки откат
        # создавал бы ~/README.
        [ "$rel" = "README" ] && continue
        [ -n "$only" ] && [ "$rel" != "$only" ] && continue
        mkdir -p "$HOME/$(dirname "$rel")"
        if [ "$mode" = "120000" ]; then
            local target; target=$(git -C "$REPO" show "$ref:$rel")
            ln -sfn "$target" "$HOME/$rel" && links=$((links + 1))
            continue
        fi
        # Через временный файл и mv: обрыв на полпути не оставит обрубок
        # вместо рабочего конфига.
        local tmp="$HOME/$rel.restoring.$$"
        if git -C "$REPO" show "$ref:$rel" > "$tmp" 2>/dev/null; then
            [ "$mode" = "100755" ] && chmod +x "$tmp"
            mv -f "$tmp" "$HOME/$rel" && restored=$((restored + 1))
        else
            rm -f "$tmp"
        fi
    done < <(git -C "$REPO" ls-tree -r "$ref" | tr '\t' ' ')

    echo "восстановлено: $restored файлов, $links симлинков (из снимка $ref)"
}

case "${1:-снять}" in
    снять|snapshot|"")   shift 2>/dev/null; cmd_snapshot "${1:-}" ;;
    список|list)         cmd_list ;;
    diff|разница)        cmd_diff "${2:-}" ;;
    откат|restore)       cmd_restore "${2:-}" "${3:-}" ;;
    файлы|files)         init_repo; list_files ;;
    *) die "неизвестная команда '$1'. Есть: снять, список, diff, откат, файлы" ;;
esac
