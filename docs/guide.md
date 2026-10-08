# staticOS user guide

Everything you need to use staticOS day to day, by task. You do not need to know niri or
edit config files: almost everything is a key or a switch in **Settings**.

> The interface speaks Russian. Labels below are given as they appear on screen, with the
> translation next to them.

**Contents**

1. [First steps](#1-first-steps)
2. [Windows and workspaces](#2-windows-and-workspaces)
3. [Launching things](#3-launching-things)
4. [Wallpaper and colors](#4-wallpaper-and-colors)
5. [Bars and panels](#5-bars-and-panels)
6. [Settings](#6-settings)
7. [Widgets on the desktop](#7-widgets-on-the-desktop)
8. [Notifications and Control center](#8-notifications-and-control-center)
9. [Screenshots, text from screen, recording](#9-screenshots-text-from-screen-recording)
10. [Clipboard](#10-clipboard)
11. [Lock, screensaver, power](#11-lock-screensaver-power)
12. [Discipline: alarm, focus, pomodoro](#12-discipline-alarm-focus-pomodoro)
13. [Terminal tools](#13-terminal-tools)
14. [When something looks wrong](#14-when-something-looks-wrong)
15. [Updating and removing](#15-updating-and-removing)

---

## 1. First steps

After [installing](../README.md#install), log out, choose **niri** on the login screen and
log in. You will see the top bar, your wallpaper and nothing else — the desktop is yours.

Three keys to remember. **Super** is the Windows key.

| Key | What it does |
|---|---|
| **Super+Space** | find and start a program |
| **Super+/** | Settings |
| **Super+Shift+/** | list of every shortcut |

Then:

1. **Super+W** — pick a wallpaper. All colors in the system follow it.
2. **Super+Return** — open a terminal.
3. **Super+/** → **Config** → **Стиль системы** (system style) — choose **Default**,
   **Skeet** or **Beta**. It changes the look of all staticOS windows at once.

---

## 2. Windows and workspaces

niri places windows **side by side on an endless horizontal strip** instead of on top of
each other. New windows open to the right; you scroll the strip instead of hunting for
hidden windows. Workspaces are stacked **vertically**.

Movement follows vim: **h** left, **l** right, **k** up, **j** down.

| Key | What it does |
|---|---|
| Super+H / Super+L | focus the window on the left / right |
| Super+K / Super+J | workspace above / below |
| Super+1 … 9 | go to workspace 1 … 9 |
| Super+Shift+H/J/K/L | move the window / workspace |
| Super+Ctrl+H / L | insert an empty workspace before / after |
| Super+− / Super+= | narrower / wider window |
| Super+F | fullscreen |
| Super+V | make the window float / dock it back |
| Super+Alt+D | let the window take the whole width |
| Super+0 | reset the window size |
| Super+R | keep the focused window centered, or just make it fit |
| Super+G | overview of all workspaces |
| Alt+Tab | switch windows (hold Alt, tap Tab) |
| Ctrl+Q | close the window |
| Alt+F4 | power menu (it does not close windows) |
| Super+Escape | let a game or remote desktop take all keys (press again to undo) |

**Pocket workspace.** Alt+Q jumps to a hidden "pocket" workspace and back. Alt+E sends the
current window there; Super+Alt+E brings it back.

**Dashboard.** Super+D jumps to the first workspace, set up as a dashboard: clock, music
visualizer, system monitor. It is restored every time you log in. Choose between terminal
windows or desktop widgets in Settings → **Applications** → **Дашборд** (dashboard).

---

## 3. Launching things

| Key | What it does |
|---|---|
| Super+Space | program launcher |
| Super+Return or Ctrl+` | terminal (kitty) |
| Super+Shift+Return | spare terminal (foot), if kitty is broken |
| Super+E | file manager |
| Super+C | calculator and translator: type `5k usd`, `12*7`, or a phrase |
| Super+N / Super+Shift+N | new note / open notes |
| Super+F6 | emoji picker |
| Super+Alt+T | **App list**: installed programs, versions, roll back or hold a package |
| Super+Alt+X | which program eats how much memory |

**Right-click on empty wallpaper** for a Windows XP style menu: new folder or text file,
your folders, terminal, system monitor, screen time, timers and widgets.

Browser keys (Super+U, Super+Y, Super+I, Super+B) open the browsers the author uses. To change
them, edit `~/.config/niri/cfg/binds.kdl` — every line reads like
`Mod+U { spawn "zen-browser"; }`.

---

## 4. Wallpaper and colors

**Super+W** opens the wallpaper picker. When you choose a picture, staticOS builds a palette
from it and repaints everything: bars, terminal, menus, notifications, GTK and Qt apps,
cursor, icons, lock screen, even Telegram, Discord, Steam and the keyboard backlight (Razer).

Put your pictures in `~/wallpapers/main`. **Super+Shift+W** opens waypaper, a plain grid
picker; if you choose another folder there, Super+W follows it.

Related switches in Settings → **Visuals**: **Размытие обоев** (wallpaper blur),
**Пиксельные обои** (turn the wallpaper into pixel art), **Значки** (pixel or Papirus icons),
**Тёплый свет** (warm light in the evening).

From a terminal:

```sh
~/.config/hypr/scripts/theme_changer.sh ~/Pictures/wallpapers/sea.jpg
```

---

## 5. Bars and panels

**Top bar.** Workspaces on the left, music and clock in the middle, system on the right.
Most items react to clicks:

| Item | Left click | Right click | Middle click |
|---|---|---|---|
| clock | calendar | swap clock / date between monitors | |
| **lan** (wired network) | connection and other devices on your network | **Control center** | |
| Wi-Fi | connection details | choose a network | Wi-Fi on / off |
| Bluetooth | battery, codec and mode of the device | devices | Bluetooth on / off |
| volume | mute | outputs and per-app volume | |
| microphone | mute | microphone settings | |
| music | play / pause | player with cover and lyrics | jump to the player window |

Scroll over the volume to change it, over the music to switch tracks.

**Bottom panel** — Super+S shows or hides it. In Settings → **Config** → **Нижняя панель**
(bottom panel) choose: nothing, a dock, or a Windows XP taskbar with a **Start** button,
window buttons, tray, clock and the current song's lyrics. It can stay visible or appear when
the mouse touches the bottom edge.

**Top bar options** — Settings → **Waybar**: shape, corners, gaps; **Показ панелей** — always
visible, on mouse hover or hidden; on every monitor or only one.

**Hot corner.** Push the mouse into the top-right corner to open the notification center.

---

## 6. Settings

**Super+/**. Changes apply immediately; nothing needs a restart unless the text says so.
Use the search box at the top to find any switch by name.

| Page | What is there |
|---|---|
| **Waybar** | look of the top bar, when panels are shown, monitors, what is in the bar, popups |
| **Fonts** | system and app fonts, with a live preview (**Проба**); undo in the same place |
| **Cursors** | cursor theme — a click on a tile changes it everywhere |
| **Applications** | default apps, kitty, Neovim, Obsidian, Zen browser, dashboard |
| **Visuals** | brightness, warm light, wallpaper blur and pixel art, icons, widgets, login and lock screen |
| **Misc** | screenshots, windows, notifications, power, mouse, recording, sound and microphone, UI sounds |
| **Config** | system style (Default / Skeet / Beta, light or dark), bottom panel, widgets, Watchman |

**Sound and microphone** (Misc): **Послушать себя** plays your microphone back to you for up
to 5 minutes, so you can check how you sound.

**UI sounds** (Misc): Windows XP, retro or normal sounds for notifications, screenshots,
volume, plugging devices and more — or none.

---

## 7. Widgets on the desktop

Small XP-style windows that live on the wallpaper, under your windows: clock, date, calendar,
weather, system monitor, music player, visualizer, timer, stopwatch and more.

- **Add one:** right-click the wallpaper → widgets, or `desktop_widgets.py add clock`.
- **Arrange:** `desktop_widgets.py edit` — drag, resize, delete. Esc to finish.
- **See them over windows:** `desktop_widgets.py peek`.
- **Save the layout:** `desktop_widgets.py preset save work`, later `preset load work`.
- **Turn off:** Settings → Visuals → **Виджеты на обоях**.

`desktop_widgets.py types` lists every widget. The script is in `~/.config/hypr/scripts/`.

---

## 8. Notifications and Control center

- **Notification center:** push the mouse into the top-right corner. Do Not Disturb is
  there too — it also mutes notification sounds.
- **Control center:** right-click **lan** in the bar. Tiles for Wi-Fi, Bluetooth, Do Not
  Disturb, night light and **caffeine** (screen and laptop stay awake), sliders for volume,
  brightness and warmth, power profile.
- Privacy dots appear in the bar while the microphone, camera or screen sharing is in use.

---

## 9. Screenshots, text from screen, recording

| Key | What it does |
|---|---|
| Print | select an area; saved and copied |
| Alt+Print | the current window |
| Ctrl+Print | the whole screen |
| Super+Print | area, then draw arrows and text on it |
| **Shift+Print** | select an area and **copy its text** (OCR) |
| Super+Ctrl+V | show the copied screenshot in a small window that stays on top |
| **Super+Shift+Print** | **Recorder**: GIF, video or Telegram sticker of an area |
| Super+Alt+Print | save the last 5 minutes (replay, like a game recorder) |

Recordings go to `~/Videos` and are copied to the clipboard, ready to paste into a chat.
Do Not Disturb turns on by itself while you record.

---

## 10. Clipboard

**Super+Alt+V** — clipboard history: text, links and pictures, with tabs
(all · text · pictures · favourites). Just start typing to search.

| Key | What it does |
|---|---|
| ↑ ↓ | move through the list |
| Enter | view the item in full; Enter again copies it and closes |
| Space or right click | copy at once and close |
| Ctrl+S or the star | add to / remove from favourites — they survive clearing the history |
| Delete | remove the item |
| Shift+Delete | clear the history (asks first; favourites stay) |
| Esc | close |

**Ctrl+Q** hides the clipboard window when it is open; otherwise it closes the focused
window.

---

## 11. Lock, screensaver, power

| Key | What it does |
|---|---|
| Super+O | lock the screen |
| Alt+F4 | power menu: lock, log out, sleep, restart, shut down — with a 5-second countdown you can cancel |
| Super+Shift+\ | turn the monitors off |

After a few minutes without input the **screensaver** starts; later the screen locks and
the laptop sleeps. Watching a video in the focused window keeps the screen on. Power options
are in Settings → **Misc** → **Питание** (power).

On the lock screen, double-click the power buttons to use them (a single click does nothing,
so you cannot shut down by accident).

---

## 12. Discipline: alarm, focus, pomodoro

**Super+Alt+F** opens **Discipline** — three tabs, switched with Tab or Shift+H / Shift+L.
Keys work like in vim and do not depend on the keyboard layout. **?** shows help.

**Alarm** — an alarm clock that makes sure you are awake, plus the Watchman against
falling asleep during the day. It has its own page: **[docs/alarm.md](alarm.md)**.

**Focus** — blocks distractions for a while. While focus is on, a window whose title matches
a rule (YouTube, Twitch…) is covered with a "Focus" screen, and players matching a rule are
paused. **h / l** choose the length, **Enter** starts, **a** adds a rule.

```sh
~/.config/hypr/scripts/focus_mode.py on 1h      # one hour of focus
~/.config/hypr/scripts/focus_mode.py block reddit reddit.com
~/.config/hypr/scripts/focus_mode.py status
```

**Pomo** — pomodoro timer: 25 minutes of work, a short break, repeat.

| Key | What it does |
|---|---|
| Super+P | start / pause |
| Super+Shift+P | skip to the next part |
| Super+Alt+P | stop |
| Super+T | start a timer with your own name and length (`40m report`) |
| Super+Ctrl+P | small always-visible countdown window |

---

## 13. Terminal tools

| Command | What it does |
|---|---|
| `jtop` | like btop, but grouped by program |
| `appmem` | memory per program |
| `applist` | the App list window |
| `jtetris` | tetris in the terminal |
| `jtype` | typing practice |
| `jclock`, `tclock` | big clock |
| `timer 25m`, `tdown` | countdown |
| `brrtfetch` | system info with an animated picture |
| `tmatrix` | the Matrix |
| `termlook` | try terminal transparency, blur and fonts |
| `notif-look on/off` | Noctalia-style notifications |
| `zen-crt` | old CRT effect in the Zen browser |
| `fan`, `power` | laptop fan and power modes (for laptops with such controls) |

---

## 14. When something looks wrong

Start with **`staticos-doctor`** — it checks programs, Python modules, fonts, the palette,
services and the niri config, and tells you what to install or run. It changes nothing.

| Problem | Fix |
|---|---|
| The bar froze or vanished | `barfix` (or right-click wallpaper → **Обновить**) |
| Some app kept old colors | `theme-doctor` shows where the palette got stuck |
| No sound after sleep | `systemctl --user restart pipewire pipewire-pulse wireplumber` |
| A window is too big / small | Super+0 |
| Keys stopped working in a game | Super+Escape |
| Alarm does nothing | `systemctl --user status wake-alarm.timer` |

Logs of user services: `journalctl --user -e`.

Your own files that the installer replaced are in `~/.local/state/staticos-backup/`.

---

## 15. Updating and removing

**Update** (from the folder you cloned):

```sh
git pull
./install.sh --no-packages
```

Files you changed are moved to the backup folder first, never silently lost.
If you installed with `--link`, `git pull` alone is enough.

**Remove:** choose another session on the login screen, then copy your files back from
`~/.local/state/staticos-backup/<date>/` into your home folder.
