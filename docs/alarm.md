# Alarm and Watchman

[Русская версия](ru/alarm.md)

An alarm clock that makes sure you are actually up, not just tapping "snooze" in your sleep.
It does not stop when you press a button: it stops when you **type a phrase** on the
computer (or answer a small math question in Telegram, if you set that up), and it checks on
you a few more times afterwards.

Both the alarm and the Watchman are **off** after installation.

---

## Quick start

1. Press **Super+Alt+F**. The **Discipline** window opens on the **Alarm** tab.
2. Press **Space** to turn the alarm on.
3. Use **h** / **l** to move the time by 15 minutes, or press **i** and type it (`06:30`).
4. Press **t** for a 10-second test ring, **s** to stop it.
5. Close with **q**. Changes are saved at once.

The same from a terminal:

```sh
wake-alarm on
wake-alarm default 06:30     # every day without its own time
wake-alarm status            # is it on, next ring, plan
wake-alarm test              # 10-second test ring
```

---

## What happens in the morning

Say the alarm is set to **07:00**.

| Time | What you see |
|---|---|
| 06:55 | **Check.** A window with a short phrase appears on every monitor. Type the phrase and press Enter — that counts as one confirmation. No sound yet. |
| 07:00 | **Ring**, if you did not confirm. The volume starts low and grows to full in two minutes, through the speakers and whatever you are listening on. |
| 07:08 → 07:10 | Next check two minutes before the next ring, then the ring if you did not answer. |
| 07:18 → 07:20 | Same. |
| 07:28 → 07:30 | Last ring. It keeps going for up to 30 minutes. |

**Two confirmations in a row end the morning.** Confirm at 06:55 and again at 07:08 and the
alarm never makes a sound.

A ring stops only when you type its phrase (or answer the Telegram question). The phrase
changes every time, so you cannot learn one by heart. Phrases are short sentences in Russian
and English, sometimes mixed, so you may have to switch the keyboard layout halfway — that
helps you wake up.

**Control check.** About 50 minutes after you first confirmed, one more quiet check appears.
Answer within 5 minutes or it rings again (for up to 30 minutes). It catches the "got up,
went back to bed" case.

If the computer was asleep at alarm time and wakes up within 30 minutes, it still rings.

While a morning series is running, today's alarm cannot be changed or turned off — not in
Discipline, not from the terminal. Plan the evening before.

---

## Planning days

Each day uses its own time if it has one, otherwise the default time.

```sh
wake-alarm default 07:00            # the usual time
wake-alarm set 06:00 2026-10-12     # one day earlier
wake-alarm set 06:00                # the next ring only
wake-alarm skip 2026-10-11          # no alarm that day
wake-alarm off                      # turn it off completely
```

In Discipline (Alarm tab):

| Key | Action |
|---|---|
| j / k | move between days |
| h / l | −15 / +15 minutes |
| − / = (or Ctrl+X / Ctrl+A) | −1 / +1 hour |
| i, Enter or a digit | type the time |
| x | skip this day |
| dd | reset the day to the default time |
| yy / p | copy / paste a time |
| u / Ctrl+R | undo / redo |
| Space | alarm on / off |
| t / s | test ring / stop |
| ? | help |

Useful for shifting your sleep: move the time 15–30 minutes earlier every day or two until
you reach your goal, then let the default take over.

---

## Watchman

The Watchman is for days when you must not fall asleep during the day. From **06:00 to
21:00** it asks "are you awake?" about every 45 minutes — the same phrase window and, if
you do not answer, the same ring.

It stays quiet while you use the computer: a check comes only after 30 minutes without any
key press or mouse movement, and never more often than every 45 minutes. On a day with an
alarm, it starts after the morning series is over.

**Turning it on:** Settings (**Super+/**) → **Config** → **Сторож**, or

```sh
wake-alarm watch daily on
```

**Turning it off is made deliberately harder**, so you do not switch it off half-asleep:

- forever — Settings → Config → Сторож: asks for your system password and a reason;
- for one day — in Discipline (key **o** on the Alarm tab), after a confirmation;
- from the terminal — the reason is required:

```sh
wake-alarm watch daily off --reason "on vacation"
wake-alarm watch skip 2026-10-12 --reason "travel day"
wake-alarm watch skip off 2026-10-12      # take the day back
```

Every switch-off is written to a log with the time and the reason:

```sh
wake-alarm watch log
```

A one-off Watchman for a single day with your own hours:

```sh
wake-alarm watch 2026-10-12 08:00-20:00 30    # check every 30 minutes
wake-alarm watch                              # list
```

---

## Telegram (optional)

The alarm can also message you in Telegram: each check sends a small math question
(like `47 + 38`).

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Find your chat id (for example with [@userinfobot](https://t.me/userinfobot)).
3. Create `~/.config/wake-alarm/env`:

   ```
   TOKEN=123456:ABC...
   OWNER=123456789
   ```

That is enough to **receive** the questions. To **confirm by answering** them, your bot
needs a small handler that passes your reply on:

```sh
wake-alarm tg-code "85"      # exit code: 0 accepted, 1 wrong, 2 nothing to answer
```

Once such a handler is running, add `REPLY=1` to the same file. Without it, messages tell
you to confirm on the computer.

---

## Sound

```sh
wake-alarm sound t3        # default: 520 Hz square wave in bursts of three
wake-alarm sound classic   # the soft freedesktop alarm
```

The `t3` pattern is the fire-alarm signal; in studies it woke people from deep sleep better
than ordinary beeps. Your speaker volume is restored after the ring, even if the alarm was
killed.

---

## All commands

```
wake-alarm status                        on/off, next ring, plan
wake-alarm on | off
wake-alarm default HH:MM
wake-alarm set HH:MM [DATE]
wake-alarm skip [DATE]
wake-alarm test [SECONDS]                test ring (10 s)
wake-alarm stop                          stop a test ring
wake-alarm series                        how the last morning went
wake-alarm test-series [K] [--dry]       a whole series, fast (K seconds per "minute")
wake-alarm woke [HH:MM] [DATE]           record when you got up ("-" clears)
wake-alarm sound [t3|classic]
wake-alarm tg-code TEXT
wake-alarm watch DATE HH:MM-HH:MM [MIN]
wake-alarm watch off [DATE]
wake-alarm watch daily [on | off --reason TEXT]
wake-alarm watch skip [DATE] --reason TEXT | watch skip off [DATE]
wake-alarm watch log [N]
```

`discipline`, `routine` and `alarm` all open the Discipline window.

## Files

| Path | What |
|---|---|
| `~/.config/hypr/state/wake-alarm.json` | schedule and settings |
| `~/.config/wake-alarm/env` | Telegram (optional) |
| `~/.local/state/jarvis-wake/` | series state, logs, Watchman log |
| `~/.config/systemd/user/wake-alarm.timer` | runs `wake-alarm check` every minute |

If nothing happens at all, check the timer:

```sh
systemctl --user status wake-alarm.timer
systemctl --user enable --now wake-alarm.timer
```
