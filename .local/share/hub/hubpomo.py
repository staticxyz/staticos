"""Помидор (pomo) в Telegram: пульт /pomo с кнопками — то же, что Clocker и Super+Ctrl+P на ПК.

29.10.2026, просьба: «запускать pomo как в ПК прямо в боте тг, с удобной менюшкой, полная
синхронизация». Состояние одно на всех — `~/.local/bin/pomo` (файл $XDG_RUNTIME_DIR/pomo/state
и журнал ~/.local/share/pomo/log.tsv): кнопки бота зовут ту же команду, что бар, Clocker и
меню на ПК, поэтому начатое на ПК видно в боте и наоборот. Пульт в Telegram hubd
перерисовывает сам (tg_sync — раз в тик, правка уходит, только когда текст другой: остаток
показан минутами), а конец отрезка, пока вы не за ПК, приходит сообщением (tg_tick).
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import lday  # noqa: E402 — день помидоров до отбоя (30.10.2026)

POMO = os.path.expanduser("~/.local/bin/pomo")
RUN = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "pomo")
STATE = os.path.join(RUN, "state")
TODAY = os.path.join(RUN, "today")
LOG = os.path.expanduser("~/.local/share/pomo/log.tsv")
CONF = os.path.expanduser("~/.config/pomo/config")
PANEL_KEY = "tg_pomo_panel"          # {"chat", "mid", "sig", "fail"} — пульт под присмотром
RECENT_KEY = "tg_pomo_recent"        # недавние «время задача» — кнопки pm:r:N ссылаются сюда
PRESETS = (15 * 60, 25 * 60, 45 * 60, 3600, 5400)
PHASE_RU = {"work": "Фокус", "short": "Перерыв", "long": "Длинный перерыв"}
PHASE_ICON = {"work": "🍅", "short": "☕", "long": "🛋"}


def _secs(v, default):
    """«25m», «1h30m», «90s», «25» (минуты) → секунды, как parse_dur в pomo."""
    v = (v or "").strip().strip("'\"").lower()
    if v.isdigit():
        return int(v) * 60
    t = 0
    for num, u in re.findall(r"(\d+)\s*([hms])", v):
        t += int(num) * {"h": 3600, "m": 60, "s": 1}[u]
    return t or default


def conf():
    out = {"WORK": "25m", "SHORT": "5m", "LONG": "15m", "ROUNDS": "4"}
    try:
        for line in open(CONF, encoding="utf-8"):
            m = re.match(r"\s*(WORK|SHORT|LONG|ROUNDS)=(\S+)", line)
            if m:
                out[m.group(1)] = m.group(2)
    except OSError:
        pass
    return {"work": _secs(out["WORK"], 1500), "short": _secs(out["SHORT"], 300),
            "long": _secs(out["LONG"], 900), "rounds": int(out["ROUNDS"]) if out["ROUNDS"].isdigit() else 4}


def state():
    s = {"phase": "idle", "started": 0, "duration": 0, "paused": 0, "round": 0, "began": 0,
         "next": "", "task": "", "custom": 0}
    try:
        for line in open(STATE, encoding="utf-8"):
            k, _, v = line.rstrip("\n").partition("=")
            if k in s and isinstance(s[k], int):
                s[k] = int(v) if v.lstrip("-").isdigit() else 0
            elif k in s:
                s[k] = v
    except OSError:
        pass
    now = int(time.time())
    if s["phase"] != "idle":
        s["rem"] = max(0, s["started"] + s["duration"] - (s["paused"] or now))
        s["end"] = (now + s["rem"]) if s["paused"] else s["started"] + s["duration"]
    return s


def today_stats():
    try:
        d, secs, cnt = open(TODAY, encoding="utf-8").read().split("\t")[:3]
        if d == lday.today().isoformat():
            return int(secs), int(cnt)
    except (OSError, ValueError):
        pass
    return 0, 0


def recent(n=4):
    """Недавние отрезки работы с задачей — как список меню Super+Ctrl+P (ask_items в pomo)."""
    out, seen = [], set()
    try:
        lines = open(LOG, encoding="utf-8").read().splitlines()[-300:]
    except OSError:
        return out
    for line in reversed(lines):
        p = line.split("\t")
        if len(p) >= 7 and p[2] == "work" and p[6].strip() and p[3].isdigit():
            key = (int(p[3]), p[6].strip())
            if key not in seen:
                seen.add(key)
                out.append(key)
                if len(out) >= n:
                    break
    return out


def run(*args):
    """pomo с аргументами; возвращает (ok, первая строка вывода)."""
    try:
        r = subprocess.run([POMO, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    out = (r.stdout or r.stderr or "").strip().splitlines()
    return r.returncode == 0, out[0] if out else ""


def dur(secs):
    h, m = secs // 3600, secs % 3600 // 60
    if h:
        return "%d ч %d мин" % (h, m) if m else "%d ч" % h
    return "%d мин" % m if m else "%d с" % secs


def dur_btn(secs):
    h, m = secs // 3600, secs % 3600 // 60
    return ("%dч%s" % (h, "%02d" % m if m else "")) if h else "%dм" % m


def _bar(frac, n=16):
    k = max(0, min(n, int(round(frac * n))))
    return "▰" * k + "▱" * (n - k)


def panel(c, note=None):
    import hubtg as T
    import hublib as H
    s, cf = state(), conf()
    tsec, tcnt = today_stats()
    out = ["<b>◆ %s · ПОМИДОР</b>" % T.BRAND]
    if note:
        out.append("<i>%s</i>" % T.esc(note))
    rows = []
    if s["phase"] == "idle":
        nxt = s["next"] or "work"
        out.append("<code>■ не запущен</code>")
        if s["task"]:
            out.append("задача: <b>%s</b>" % T.esc(s["task"]))
        if nxt != "work":
            out.append("дальше: %s %s" % (PHASE_RU.get(nxt, nxt).lower(), dur(cf[nxt])))
        go = "▶ Фокус %s" % dur(cf["work"]) + (" · %s" % s["task"][:24] if s["task"] else "")
        rows.append([T.btn(go, "pm:go")])
        rows.append([T.btn(dur_btn(d), "pm:d:%d" % d) for d in PRESETS])
        rec = recent()
        H.meta_set(c, RECENT_KEY, json.dumps(rec, ensure_ascii=False))
        for i, (d, task) in enumerate(rec):
            rows.append([T.btn("↻ %s · %s" % (dur_btn(d), task[:30]), "pm:r:%d" % i)])
        rows.append([T.btn("☕ Перерыв %s" % dur_btn(cf["short"]), "pm:bs"),
                     T.btn("🛋 Перерыв %s" % dur_btn(cf["long"]), "pm:bl")])
        rows.append([T.btn("✎ Своё время", "pm:new"), T.btn("📜 Сегодня", "pm:log")])
    else:
        ph = s["phase"]
        head = "%s %s" % ("⏸" if s["paused"] else PHASE_ICON.get(ph, "🍅"), PHASE_RU.get(ph, ph))
        if s["custom"]:
            head += " · свой отрезок"
        elif ph == "work":
            head += " · %d из %d" % (s["round"] % cf["rounds"] + 1, cf["rounds"])
        out.append("<b>%s</b>%s" % (head, " · на паузе" if s["paused"] else ""))
        if s["task"]:
            out.append("задача: <b>%s</b>" % T.esc(s["task"]))
        left = s["rem"]
        out.append("<code>осталось %s из %s</code>" % ("<1 мин" if 0 < left < 60 else dur(left - left % 60),
                                                        dur(s["duration"])))
        frac = 1 - left / s["duration"] if s["duration"] else 0
        out.append("<code>%s</code>%s" % (_bar(frac), "" if s["paused"] else "  до %s" % time.strftime(
            "%H:%M", time.localtime(s["end"]))))
        rows.append([T.btn("▶ Продолжить", "pm:res") if s["paused"] else T.btn("⏸ Пауза", "pm:pau"),
                     T.btn("⏭ Дальше", "pm:skip"), T.btn("■ Стоп", "pm:stop")])
        rows.append([T.btn("−5 мин", "pm:add:-5m"), T.btn("+5 мин", "pm:add:5m"), T.btn("+15 мин", "pm:add:15m")])
        rows.append([T.btn("✎ Задача", "pm:task"), T.btn("📜 Сегодня", "pm:log")])
    out.append("\nсегодня: %s · %d шт." % (dur(tsec) if tsec else "0 мин", tcnt))
    rows.append([T.btn("↻ Обновить", "pm:m")])
    return T.Html("\n".join(out)), rows


def log_view():
    import hubtg as T
    try:
        txt = subprocess.run([POMO, "log", "today"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        txt = str(e)
    return (T.Html("<b>◆ %s · ПОМИДОР · СЕГОДНЯ</b>\n<pre>%s</pre>" % (T.BRAND, T.esc(txt or "пусто")[:3500])),
            [[T.btn("« Помидор", "pm:m"), T.btn("↻ Обновить", "pm:log")]])


def ask(title, hint):
    import hubtg as T
    return T.Html("<b>◆ ПОМИДОР · %s</b>\n<i>%s</i>" % (title, hint)), [[T.btn("✕ Отмена", "pm:x")]]


def start_text(text):
    """«45m отчёт», «отчёт 45m», «45», «отчёт» — как меню на ПК: время — свой отрезок, иначе фокус."""
    w = text.split()
    if not w:
        return False, "Пусто, сэр."
    first_dur = bool(re.fullmatch(r"\d+([hmsчмс]\w*)*", w[0].lower()))
    if first_dur or (len(w) > 1 and re.fullmatch(r"\d+[hmsчмс]\w*", w[-1].lower())):
        return run(*w)
    return run("start", *w)


def command(c, cmd, arg):
    """/pomo [45m отчёт | pause | stop | …] — None, если команда не наша."""
    if cmd not in ("pomo", "помидор", "pm"):
        return None
    a = arg.strip()
    if not a:
        return panel(c)
    w = a.split()
    if w[0].lower() in ("log", "сегодня"):
        return log_view()
    if w[0].lower() in ("pause", "resume", "toggle", "skip", "next", "stop", "reset", "add", "task", "break"):
        ok, msg = run(*w)
    else:
        ok, msg = start_text(a)
    return panel(c, note=("✓ " if ok else "✗ ") + (msg or "готово"))


def tg_wait(c, op, text):
    """Ответ текстом после «✎ Своё время» / «✎ Задача»: (ok, ответ)."""
    t = text.strip()
    if op == "new":
        ok, msg = start_text(t)
        return ok, (panel(c, note="✓ " + msg) if ok else "Не понял, сэр: %s. Например «45m отчёт» или «отчёт»." % msg)
    if op == "task":
        ok, msg = run("task", *t.split())
        return ok, (panel(c, note="✓ Задача: " + t[:60]) if ok else msg)
    return False, "?"


ACTS = {"pau": ("pause",), "res": ("resume",), "skip": ("skip",), "stop": ("stop",),
        "bs": ("break", "short"), "bl": ("break", "long"), "go": ("start",)}


def tg_callback(c, bot, chat, mid, cb_id, rest):
    import hubtg as T
    import hublib as H
    a = rest.split(":")
    act, toast, res = a[0], "", None
    if act in ("m", "x"):
        if act == "x":
            T.wait_pop(c)
        res = panel(c)
    elif act in ACTS:
        ok, msg = run(*ACTS[act])
        toast = msg if ok else "✗ " + msg
        res = panel(c)
    elif act == "d" and len(a) > 1 and a[1].isdigit():
        task = state()["task"]
        ok, msg = run("%ds" % int(a[1]), *task.split())
        toast, res = msg, panel(c)
    elif act == "r" and len(a) > 1 and a[1].isdigit():
        try:
            d, task = json.loads(H.meta_get(c, RECENT_KEY, "[]") or "[]")[int(a[1])]
            ok, msg = run("%ds" % d, *task.split())
            toast = msg
        except (ValueError, IndexError, TypeError):
            toast = "Список устарел — обновил"
        res = panel(c)
    elif act == "add" and len(a) > 1:
        ok, msg = run("add", a[1])
        toast, res = msg, panel(c)
    elif act == "log":
        res = log_view()
    elif act in ("new", "task"):
        T.wait_set(c, "pm_" + act, None, chat, mid)
        res = ask("СВОЁ ВРЕМЯ", "Напишите время и задачу, сэр: «45m отчёт», «1ч30 java», «отчёт» — "
                  "фокус на обычные 25 мин.") if act == "new" else ask("ЗАДАЧА", "Как назвать текущий отрезок, сэр?")
    bot.answer(cb_id, toast[:190])
    if res:
        bot.edit(chat, mid, *res)
        tg_track(c, chat, mid, res[0] if act not in ("new", "task") else None)


def _key(s):
    return "%s:%s:%s" % (s["phase"], s["began"], s["started"])


def tg_track(c, chat, mid, text, note=None):
    """Пульт под присмотром hubd; text=None — на месте пульта теперь другое (лог, вопрос).
    note — подпись «Фокус окончен…»: держится, пока идёт тот же отрезок."""
    import hublib as H
    if text is not None and "· ПОМИДОР</b>" in str(text) and mid:
        H.meta_set(c, PANEL_KEY, json.dumps({"chat": chat, "mid": mid, "sig": str(text),
                                             "note": note, "nkey": _key(state()) if note else None},
                                            ensure_ascii=False))
        return
    try:
        cur = json.loads(H.meta_get(c, PANEL_KEY, "null") or "null")
    except ValueError:
        cur = None
    if cur and cur.get("mid") == mid:
        H.meta_set(c, PANEL_KEY, "null")


def tg_sync(c, bot):
    """hubd, каждый тик: состояние или минута остатка сменились — перерисовать пульт."""
    import hublib as H
    try:
        cur = json.loads(H.meta_get(c, PANEL_KEY, "null") or "null")
    except ValueError:
        return False
    if not cur:
        return False
    keep = cur.get("note") if cur.get("nkey") == _key(state()) else None
    res = panel(c, note=keep)
    if str(res[0]) == cur.get("sig"):
        return False
    if bot.edit(cur["chat"], cur["mid"], *res) is None:
        cur["fail"] = cur.get("fail", 0) + 1     # сеть или сообщение удалено: пять раз подряд — забыть
        H.meta_set(c, PANEL_KEY, "null" if cur["fail"] >= 5 else json.dumps(cur))
        return False
    cur["sig"], cur["fail"] = str(res[0]), 0
    H.meta_set(c, PANEL_KEY, json.dumps(cur, ensure_ascii=False))
    return True


_last = {"key": None}


def tg_tick(c, bot, at_pc):
    """hubd: отрезок кончился сам (не стоп/пропуск) — без вас у ПК сообщить в Telegram свежим
    пультом (старый перестаёт обновляться); у ПК звенит сам pomo, бот молчит."""
    import hubtg as T
    s = state()
    if s["phase"] != "idle" and not s["paused"] and s["rem"] <= 0:
        run("status", "brief")                  # pomo догоняет просроченный отрезок лениво
        s = state()
    key = (s["phase"], s["began"], s["started"])
    prev, _last["key"] = _last["key"], key
    if prev is None or prev == key or prev[0] == "idle" or at_pc:
        return False
    try:
        last = open(LOG, encoding="utf-8").read().splitlines()[-1].split("\t")
    except (OSError, IndexError):
        return False
    if len(last) < 6 or last[5] != "done" or last[0] != str(prev[1]):
        return False
    note = {"work": "🍅 Фокус окончен", "short": "☕ Перерыв окончен", "long": "🛋 Перерыв окончен"}.get(prev[0], "Отрезок окончен")
    if s["phase"] != "idle":
        note += " — дальше %s до %s" % (PHASE_RU.get(s["phase"], "").lower(), time.strftime("%H:%M", time.localtime(s["end"])))
    elif prev[0] != "work":
        note += " — пора за работу, сэр"
    chat = next(iter(T.owner_ids() or ()), None)
    if not chat:
        return False
    res = panel(c, note=note)
    r = bot.send(chat, *res)
    if r and r.get("message_id"):
        tg_track(c, chat, r["message_id"], res[0], note=note)
    return True
