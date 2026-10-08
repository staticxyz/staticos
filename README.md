<div align="center">

# staticOS

A pixel-styled [niri](https://github.com/YaLTeR/niri) desktop for Arch Linux.<br>
Every color comes from your wallpaper.

![Focus](assets/desktop-focus.png)

<p align="center"><i>With the top bar and Focus: block distracting sites and apps for a session.</i></p>

![Settings](assets/desktop-settings.png)

<p align="center"><i>Settings: one window for bars, fonts, widgets, lock screen and more.</i></p>

| | |
|:-:|:-:|
| ![Discipline: alarm](assets/alarm.png) | ![Discipline: focus](assets/focus.png) |
| Alarm plan for the week | Focus session |
| ![Wake-up check](assets/wake-check.png) | ![Alarm ringing](assets/wake-ring.png) |
| Morning check | The ring stops when you type the phrase |
| ![App list: packages](assets/app-list-packages.png) | ![App list: cleanup](assets/app-list-cleanup.png) |
| Packages with roll back | Cleanup |

<details>
<summary>Three looks: Default, Skeet, Beta</summary>

| Default | Skeet | Beta |
|:-:|:-:|:-:|
| ![Default](assets/alarm.png) | ![Skeet](assets/alarm-skeet.png) | ![Beta](assets/alarm-beta.png) |

</details>

## Install

```sh
git clone https://github.com/staticxyz/staticos.git ~/staticos
cd ~/staticos && ./install.sh
```

Log out, choose **niri** on the login screen, log in. Your own files are backed up first.
`staticos-doctor` checks that nothing is missing.
Other distributions, options and removal: [docs/install.md](docs/install.md).

## First keys

| Keys | |
|---|---|
| `Super+/` | Settings |
| `Super+Shift+/` | All shortcuts |
| `Super+Space` | Launch an app |
| `Super+Return` | Terminal |
| `Super+W` | Wallpaper (recolors everything) |
| `Super+Alt+F` | Alarm, focus, pomodoro |
| `Super+Alt+T` | App list |
| `Super+Alt+V` | Clipboard |
| `Super+C` | Calculator and translator |
| `Super+Print` / `Shift+Print` | Annotated screenshot / copy text from screen |
| `Super+O` / `Alt+F4` | Lock / power menu |

Everything else is in the **[user guide](docs/guide.md)**.

## Notes

- The interface is in Russian; the docs are in English (the alarm guide also [in Russian](docs/ru/alarm.md)).
- No keys, tokens, passwords, browser profiles or personal state are in the repository.
- Scripts live in `~/.config/hypr/scripts` — the setup started on Hyprland and moved to niri.
- Windows XP sounds are not included. Put your own `.wav` files into
  `~/.config/hypr/sounds/xp/`; the retro set is generated during install.
- `fan`, `power`, `kbd_colors.py` and the Razer scripts target one specific laptop and keyboard.
  Elsewhere they do nothing.

## License

[MIT](LICENSE) © 2026 staticxyz. Bundled fonts keep their own licenses —
see [FONTS-LICENSE.md](.local/share/fonts/FONTS-LICENSE.md).
