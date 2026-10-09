#!/usr/bin/env bash
# staticOS installer.
#
#   ./install.sh                 install packages (Arch), copy the files, set everything up
#   ./install.sh --link          symlink the files with GNU Stow instead of copying
#   ./install.sh --no-packages   skip the package step (any distro)
#   ./install.sh --dry-run       only print what would happen
#   ./install.sh --yes           do not ask questions
#   ./install.sh --wallpaper F   build the first palette from this image
#   ./install.sh --no-theme      do not build the color palette now
#
# Your own files are never overwritten silently: every file that would be replaced is
# moved to ~/.local/state/staticos-backup/<date>/ first. To put them back, copy that
# folder over $HOME.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINK=0; PACKAGES=1; DRY=0; YES=0; WALL=""; THEME=1
while [ $# -gt 0 ]; do
    case "$1" in
        --link) LINK=1 ;;
        --no-packages) PACKAGES=0 ;;
        --dry-run) DRY=1 ;;
        --yes|-y) YES=1 ;;
        --no-theme) THEME=0 ;;
        --wallpaper) shift; WALL="${1:-}" ;;
        -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (see --help)"; exit 2 ;;
    esac
    shift
done

BOLD=$'\e[1m'; DIM=$'\e[2m'; GRN=$'\e[32m'; YLW=$'\e[33m'; RED=$'\e[31m'; RST=$'\e[0m'
step() { printf '\n%s==>%s %s%s%s\n' "$GRN" "$RST" "$BOLD" "$*" "$RST"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '    %s!%s %s\n' "$YLW" "$RST" "$*"; }
fail() { printf '%sError:%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }
run()  { if [ "$DRY" = 1 ]; then printf '    %s$ %s%s\n' "$DIM" "$*" "$RST"; else "$@"; fi; }
ask()  { [ "$YES" = 1 ] && return 0; read -r -p "    $1 [Y/n] " a; [ -z "$a" ] || [[ "$a" =~ ^[YyДд] ]]; }
have() { command -v "$1" >/dev/null 2>&1; }

[ "$(id -u)" = 0 ] && fail "run it as your normal user, not root (it will call sudo when needed)"
[ -d "$REPO/.config/niri" ] || fail "run it from the staticOS repository"

# ── packages ──────────────────────────────────────────────────────────────────────
# Official Arch repositories
PKG_REPO=(
    # desktop
    niri xwayland-satellite waybar swaync kitty foot rofi rofi-calc rofi-emoji
    hypridle hyprlock hyprpicker gammastep awww matugen gtk-session-lock
    xdg-desktop-portal-gnome polkit-kde-agent dolphin
    # sound, network, hardware
    pipewire wireplumber pipewire-pulse libpulse playerctl brightnessctl
    networkmanager bluez-utils ddcutil
    # python and GTK
    python python-gobject gtk3 gtk4 gtk-layer-shell python-cairo python-pillow
    python-numpy python-fonttools python-requests python-evdev
    # clipboard, screenshots, recording
    wl-clipboard cliphist wtype grim slurp satty tesseract tesseract-data-eng
    gpu-screen-recorder ffmpeg imagemagick
    # terminal tools and widgets
    cava termdown fastfetch btop libqalculate jq
    # fonts and icons
    ttf-jetbrains-mono-nerd papirus-icon-theme
    # build tools used by the installer
    git stow gcc libx11 libxfixes potrace librsvg
)
# AUR (installed only if paru or yay is present)
PKG_AUR=(eww waypaper wlogout bemoji tty-clock papirus-folders)

is_arch() {
    [ -r /etc/os-release ] || return 1
    . /etc/os-release
    [ "${ID:-}" = arch ] || [[ " ${ID_LIKE:-} " == *" arch "* ]]
}

install_packages() {
    step "Packages"
    if ! is_arch; then
        warn "This is not an Arch-based system, so packages are not installed automatically."
        info "The list of programs to look for in your distribution is in docs/install.md."
        info "niri, matugen, awww and gtk-session-lock may need to be built from source."
        return
    fi
    info "${#PKG_REPO[@]} packages from the official repositories (already installed ones are skipped)."
    if ask "Install them with pacman?"; then
        run sudo pacman -S --needed "${PKG_REPO[@]}" || warn "pacman reported a problem — check the output above"
    fi
    local helper=""
    have paru && helper=paru
    [ -z "$helper" ] && have yay && helper=yay
    if [ -n "$helper" ]; then
        if ask "Install ${PKG_AUR[*]} from the AUR with $helper?"; then
            run "$helper" -S --needed "${PKG_AUR[@]}" || warn "$helper reported a problem"
        fi
    else
        warn "No AUR helper (paru or yay) found. Install these yourself later: ${PKG_AUR[*]}"
    fi
}

# ── files ─────────────────────────────────────────────────────────────────────────
BACKUP="$HOME/.local/state/staticos-backup/$(date +%Y-%m-%d_%H%M%S)"
backed=0

repo_files() {
    (cd "$REPO" && find .config .local \( -type f -o -type l \) \
        ! -name '*.bak*' ! -path '*/__pycache__/*' | sed 's|^\./||' | sort)
}

backup_one() {          # $1 — path relative to $HOME
    local dst="$HOME/$1"
    [ -e "$dst" ] || [ -L "$dst" ] || return 0
    if [ "$LINK" = 1 ] && [ "$(readlink -f "$dst")" = "$(readlink -f "$REPO/$1")" ]; then
        return 0                                          # already our symlink
    fi
    if [ "$LINK" = 0 ] && [ ! -L "$dst" ] && cmp -s "$dst" "$REPO/$1"; then
        return 0                                          # same file
    fi
    run mkdir -p "$BACKUP/$(dirname "$1")"
    run mv "$dst" "$BACKUP/$1"
    backed=$((backed + 1))
}

install_files() {
    step "Files"
    local n; n=$(repo_files | wc -l)
    if [ "$LINK" = 1 ]; then
        have stow || fail "--link needs GNU Stow (pacman -S stow)"
        info "$n files will be symlinked into $HOME (the repository must stay where it is)."
    else
        info "$n files will be copied into $HOME."
    fi
    ask "Continue?" || { info "Skipped."; return; }
    while IFS= read -r f; do backup_one "$f"; done < <(repo_files)
    [ "$backed" -gt 0 ] && info "$backed existing files moved to $BACKUP"
    if [ "$LINK" = 1 ]; then
        run stow --dir="$REPO" --target="$HOME" --no-folding --restow . || fail "stow failed"
    else
        while IFS= read -r f; do
            run mkdir -p "$HOME/$(dirname "$f")"
            run cp -P "$REPO/$f" "$HOME/$f"
        done < <(repo_files)
    fi
    run chmod +x "$HOME"/.local/bin/* "$HOME"/.config/hypr/scripts/* "$HOME"/.config/niri/scripts/* 2>/dev/null
    info "done"
}

# ── setup ─────────────────────────────────────────────────────────────────────────
S="$HOME/.config/hypr/scripts"

build_helpers() {
    step "Small helpers and fonts"
    if have gcc; then
        run gcc -O2 -o "$HOME/.local/bin/x11-clip-events" \
            "$REPO/.local/src/x11-clip-events/x11-clip-events.c" -lX11 -lXfixes \
            && info "x11-clip-events built" || warn "x11-clip-events was not built (needs libx11, libxfixes)"
    else
        warn "gcc not found: x11-clip-events (clipboard bridge for X11 apps) is not built"
    fi
    run fc-cache -f >/dev/null 2>&1
    local b
    for b in build_wolf_font build_zen_font build_bar_icons build_taskbar_font \
             build_start_font build_bongo_font build_wave_font; do
        if [ "$DRY" = 1 ]; then run python3 "$S/$b.py"; continue; fi
        python3 "$S/$b.py" >/dev/null 2>&1 && info "$b: ok" \
            || warn "$b: skipped (its source icon is probably not installed — the bar still works)"
    done
    run fc-cache -f >/dev/null 2>&1
    run python3 "$S/ui_sound_retro.py" >/dev/null 2>&1 || warn "retro UI sounds were not generated"
}

first_palette() {
    step "Colors"
    if [ -s "$HOME/.cache/matugen/colors.css" ] && [ -z "$WALL" ]; then
        info "a palette already exists — keeping it"
        return
    fi
    if [ -z "$WALL" ]; then
        WALL="$HOME/wallpapers/main/staticos-default.png"
        info "no wallpaper given — making a simple one: $WALL"
        if [ "$DRY" = 0 ]; then
            mkdir -p "$(dirname "$WALL")"
            python3 - "$WALL" <<'PY' || warn "could not make a wallpaper (python-pillow missing?)"
import sys
from PIL import Image
w, h = 1920, 1080
im = Image.new("RGB", (w // 8, h // 8))
px = im.load()
for y in range(h // 8):
    for x in range(w // 8):
        t = (x + y) / (w // 8 + h // 8)
        px[x, y] = (int(24 + 40 * t), int(26 + 30 * t), int(58 + 90 * t))
im.resize((w, h), Image.NEAREST).save(sys.argv[1])
PY
        fi
    fi
    run "$S/theme_changer.sh" "$WALL" >/dev/null 2>&1 \
        && info "palette built from $(basename "$WALL")" \
        || warn "theme_changer.sh failed — run it again from inside niri: $S/theme_changer.sh IMAGE"
}

enable_services() {
    step "User services"
    run systemctl --user daemon-reload
    local u
    for u in night-schedule.timer gtk-guard.path wake-alarm.timer jarvis-focus.service hub.service; do
        run systemctl --user enable "$u" >/dev/null 2>&1 && info "enabled $u" || warn "could not enable $u"
    done
    info "${DIM}the alarm and the Watchman stay off until you turn them on (docs/alarm.md)${RST}"
}

check_path() {
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) warn "$HOME/.local/bin is not in your PATH. Add it to your shell config, e.g. for fish:"
           info "    fish_add_path ~/.local/bin" ;;
    esac
}

# ── main ──────────────────────────────────────────────────────────────────────────
printf '%sstaticOS installer%s  %s\n' "$BOLD" "$RST" "$REPO"
[ "$DRY" = 1 ] && info "${YLW}dry run: nothing will be changed${RST}"
[ "$PACKAGES" = 1 ] && install_packages
install_files
build_helpers
[ "$THEME" = 1 ] && first_palette
enable_services
check_path

step "Done"
info "Log out, pick the ${BOLD}niri${RST} session on the login screen and log in."
info "Then press ${BOLD}Super+/${RST} for Settings and ${BOLD}Super+Shift+/${RST} for all shortcuts."
info "Guide: $REPO/docs/guide.md   ·   check the setup any time: staticos-doctor"
[ "$backed" -gt 0 ] && info "Your previous files: $BACKUP"
exit 0
