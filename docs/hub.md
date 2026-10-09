# Hub

[Русская версия](ru/hub.md)

Reminders, lists, timers and a spaced-repetition dictionary, with no AI anywhere in the
loop: fixed rules, a SQLite database you can read yourself, and (optionally) a Telegram bot
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
