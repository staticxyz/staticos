# Hub

[Русская версия](ru/hub.md)

Reminders, lists, timers and a spaced-repetition dictionary: fixed rules, a SQLite database you can read yourself, and (optionally) a Telegram bot
that reaches you when you are away from the computer. A separate background service
(`hub.service`) does the actual firing; the windows are just a view onto the same database.

---

## Quick start

1. Press **Super+M** to open reminders, **Super+Shift+M** for the dictionary.
2. Press **i** and type something like `купить молоко завтра в 9`, then **Enter**.
3. **j** / **k** move the selection, **d** marks a reminder done, **s** snoozes it an hour
   (**Shift+S** — tomorrow 9:00), **Shift+D** deletes, **Tab** switches tabs.
4. In the dictionary: **i**, type `word = translation`, **Enter**; **z** starts a review
   round (Leitner-style: **Space** reveals, **y** you knew it, **n** you didn't).
5. On the **Better** tab (each row compared with yesterday): **l** or a double click opens the
   row's 7-day chart, **h** / **Esc** goes back to the list, **j** / **k** switch rows inside
   the chart. Streak freeze (one worse day a week keeps the streak) is in Settings → Config.

A quick timer from a terminal, without opening the window:

```sh
hub timer 10m "чай"
```

There is no `add`/`list` on the command line on purpose — the window (**i** to add, **j**/**k**
to browse) and Telegram are the two entry points; the CLI (`hub`) only covers the service
itself: `on`/`off`/`restart`/`log`/`away`/`timer`, and bare `hub` for status.

---

## Due dates in plain text

`hub add` and the **i** key both parse the same patterns: `завтра`, `через 10 минут`,
`в 18:00`, `в пятницу`, a bare date — whatever is left over becomes the reminder's text.
Nothing is sent to any model to do this; it is pattern matching in `hublib.py`
(`parse_when`), so it is instant and works offline.

---

## Where it notifies you

A reminder or timer firing on the computer makes a sound and shows a notification — unless
you are not there. Hub treats you as "away" when you have been idle for 5 minutes **and**
no video is playing in focus; in that case it skips the computer entirely and sends it to
Telegram instead, so you never get a beep nobody heard.

---

## Telegram (optional)

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Find your chat id (for example with [@userinfobot](https://t.me/userinfobot)).
3. Create `~/.config/hub/env`:

   ```
   TOKEN=123456:ABC...
   OWNER=123456789
   ```

4. Restart the service: `systemctl --user restart hub.service`.

The bot only answers its owner — an empty or wrong `OWNER` means nobody gets a reply. From
there you can add reminders, snooze or finish them with buttons, and review dictionary
words, all without touching the computer.

`/pomo` opens a pomodoro control panel — the same `pomo` timer as on the PC, so a session
started in one place shows up in the other. Buttons start a focus block (preset lengths or
recent tasks), pause, skip, stop, add or remove minutes and rename the task; the panel keeps
itself up to date. Text works too: `/pomo 45m report`, `/pomo stop`. When a block ends and you
are away from the PC, the bot sends a separate message.

---

## Away mode

```sh
hub away on
hub away off
```

With it on, the service reports PC activity — any keyboard or mouse use, and a screenshot —
to Telegram while the screen is locked, so you know if someone touches your computer while
you are out. Turn it off yourself when you are back; it does not time out on its own. Hub
does not log which keys were pressed, and it does not use the microphone or camera.

---

## Better, the castle and interviews

The Better tab (`Mod + M`) tracks the day against a ladder: a level counts once it is reached on 5
days of 7. A day runs from waking up to going to sleep, and the new one starts at 07:00 at the
earliest, once you are at the computer. Waking and bedtime come from your own entry, the alarm, a long
sleep of the laptop or a silence in the screen time, in that order; `Space` on those rows types them in.

The castle (`Mod + Shift + B`, also a desktop widget) has no counter of its own: energy comes from the
same numbers as Better (market, code, speech, strength, chores, the daily block) and from going to
interviews, and it is spent on building. `block` sets the minutes of the daily block. Interviews are plain
notes in the vault's `Вакансии` folder: a table on `Mod + Shift + O`, a form on `Mod + Ctrl + O`, `iv` in
the terminal.

`Mod + Shift + I` opens the canvas for a thought that should not break the block; `later` puts a task
aside until the block is over.

## Files

| Path | What |
|---|---|
| `~/.local/share/hub/hub.db` | the database — reminders, words, log |
| `~/.config/hub/env` | Telegram token and owner id (optional) |
| `~/.config/systemd/user/hub.service` | the background daemon (`hubd.py`) |

If nothing fires, check the service:

```sh
systemctl --user status hub.service
journalctl --user -u hub.service -f
```
