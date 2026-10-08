# Installing staticOS

## Arch Linux (and Arch-based: EndeavourOS, CachyOS, Garuda…)

```sh
git clone https://github.com/staticxyz/staticos.git ~/staticos
cd ~/staticos
./install.sh
```

Then log out, choose **niri** on the login screen and log in.

The installer asks before every step. It:

1. installs the packages with `pacman` (and the AUR ones with `paru` or `yay`, if you have one);
2. copies the files into your home folder — any file of yours it would replace is first
   **moved** to `~/.local/state/staticos-backup/<date>/`;
3. builds a small clipboard helper and the icon fonts used by the bars;
4. builds the first color palette (from your `--wallpaper`, or from a plain gradient);
5. enables the user services (night light schedule, alarm timer, focus guard);
6. checks that `~/.local/bin` is in your `PATH`.

Running it again is safe: files that did not change are left alone.

Afterwards, `staticos-doctor` checks that nothing is missing.

### Options

| Option | What it does |
|---|---|
| `--dry-run` | print what would happen, change nothing |
| `--yes` | do not ask questions |
| `--no-packages` | skip installing packages |
| `--link` | symlink the files with GNU Stow instead of copying — then `git pull` updates everything at once; keep the repository folder where it is |
| `--wallpaper FILE` | build the palette from this picture |
| `--no-theme` | do not build the palette now |

## Other distributions

Run `./install.sh --no-packages` and install these yourself. Names are the Arch ones; most
distributions use the same or similar names.

**Must have**

| Program | What for |
|---|---|
| niri, xwayland-satellite | the window manager, X11 apps |
| waybar, swaync | top bar, notifications |
| kitty (and foot as a spare) | terminal |
| rofi (+ rofi-calc, rofi-emoji) | launcher |
| python 3, python-gobject, gtk3, gtk4, gtk-layer-shell, python-cairo, python-pillow, python-numpy | almost every staticOS window is a Python GTK app |
| matugen | builds the palette from the wallpaper |
| awww | draws the wallpaper |
| hypridle, hyprlock, gtk-session-lock | idle, screen lock |
| pipewire, wireplumber, pipewire-pulse, libpulse (pactl), playerctl | sound and music |
| wl-clipboard, cliphist, wtype | clipboard |
| networkmanager, bluez-utils, brightnessctl | network, Bluetooth, brightness |
| ttf-jetbrains-mono-nerd, papirus-icon-theme | icons in the bar and menus |
| jq, git | used by scripts |

**Recommended**

| Program | What for |
|---|---|
| grim, slurp, satty | screenshots and drawing on them |
| tesseract (+ language data) | copy text from the screen |
| gpu-screen-recorder, ffmpeg, imagemagick | recording, GIFs, stickers |
| gammastep | warm light in the evening |
| eww | dashboard widgets |
| wlogout | power menu |
| cava, btop, fastfetch, termdown, tty-clock, libqalculate | terminal widgets, calculator |
| python-fonttools, potrace, librsvg | building the icon fonts |
| gcc, libx11, libxfixes | the X11 clipboard helper |
| python-requests, python-evdev, ddcutil | network devices, "shake the mouse", monitor brightness |
| waypaper, bemoji, papirus-folders, dolphin | wallpaper grid, emoji, folder colors, file manager |

niri, matugen, awww and gtk-session-lock are new; if your distribution does not have them,
build them from their GitHub pages.

## Updating

```sh
cd ~/staticos
git pull
./install.sh --no-packages
```

## Removing

1. Choose another session on the login screen.
2. Copy your old files back: `cp -a ~/.local/state/staticos-backup/<date>/. ~/`
3. Optionally disable the services:
   `systemctl --user disable night-schedule.timer gtk-guard.path wake-alarm.timer jarvis-focus.service`
