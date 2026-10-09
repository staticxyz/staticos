#!/usr/bin/env python3
"""hub — Telegram-слой. Без ИИ: команды, кнопки, быстрый текст. Только стандартная библиотека.

Bot ходит на HUB_TG_API (по умолчанию api.telegram.org) — для теста подставляется фейковый сервер.
Принимает сообщения только от владельца (config.json: owner). Пусто — отказ всем."""
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import hublib as H
import hubpc

API = os.environ.get("HUB_TG_API", "https://api.telegram.org")
PRESETS = [(5, "5м"), (10, "10м"), (15, "15м"), (25, "25м"), (45, "45м"), (60, "1ч")]
CONFIRM_TTL = 60


def token():
    try:
        for line in open(os.path.join(H.CONF, "env"), encoding="utf-8"):
            if line.startswith("TOKEN="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return os.environ.get("HUB_TOKEN", "")


class Bot:
    def __init__(self, tok):
        self.base = "%s/bot%s/" % (API, tok)

    def call(self, method, params=None, files=None, timeout=40):
        params = params or {}
        if files:
            b = uuid.uuid4().hex
            body = b""
            for k, v in params.items():
                body += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                         % (b, k, v if isinstance(v, str) else json.dumps(v))).encode()
            for k, path in files.items():
                mt = mimetypes.guess_type(path)[0] or "application/octet-stream"
                body += ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                         'Content-Type: %s\r\n\r\n' % (b, k, os.path.basename(path), mt)).encode()
                body += open(path, "rb").read() + b"\r\n"
            body += ("--%s--\r\n" % b).encode()
            req = urllib.request.Request(self.base + method, body,
                                         {"Content-Type": "multipart/form-data; boundary=" + b})
        else:
            data = json.dumps(params).encode()
            req = urllib.request.Request(self.base + method, data, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read())
        if not j.get("ok"):
            raise RuntimeError(j.get("description", "telegram error"))
        return j["result"]

    def send(self, chat, text, buttons=None):
        p = {"chat_id": chat, "text": text[:4000]}
        if buttons:
            p["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", p)

    def edit(self, chat, mid, text, buttons=None):
        p = {"chat_id": chat, "message_id": mid, "text": text[:4000],
             "reply_markup": {"inline_keyboard": buttons or []}}
        try:
            return self.call("editMessageText", p)
        except (RuntimeError, urllib.error.URLError):
            return None

    def photo(self, chat, path, caption=""):
        return self.call("sendPhoto", {"chat_id": chat, "caption": caption}, {"photo": path})

    def answer(self, cb_id, text=""):
        try:
            self.call("answerCallbackQuery", {"callback_query_id": cb_id, "text": text[:190]})
        except (RuntimeError, urllib.error.URLError):
            pass


# ───────────────────────────── кнопки ─────────────────────────────

def item_buttons(iid):
    return [[{"text": "✓ Сделано", "callback_data": "d:%d" % iid},
             {"text": "⏰ +1ч", "callback_data": "s:%d:3600" % iid},
             {"text": "🌙 Завтра", "callback_data": "s:%d:tom" % iid}],
            [{"text": "+10 мин", "callback_data": "s:%d:600" % iid},
             {"text": "✗ Удалить", "callback_data": "x:%d" % iid}]]


def timer_presets():
    return [[{"text": l, "callback_data": "t:%d" % (m * 60)} for m, l in PRESETS[:3]],
            [{"text": l, "callback_data": "t:%d" % (m * 60)} for m, l in PRESETS[3:]]]


def timer_buttons(iid):
    return [[{"text": "■ Стоп", "callback_data": "x:%d" % iid},
             {"text": "+5 мин", "callback_data": "s:%d:300" % iid}]]


def tomorrow_9():
    import datetime as dt
    d = dt.datetime.now().date() + dt.timedelta(days=1)
    return int(dt.datetime.combine(d, dt.time(9, 0)).timestamp())


def ack_pc(c, iid):
    """Любая реакция из Telegram гасит эскалацию и убирает висящее уведомление на ПК."""
    H.mark_seen(c, iid)


def item_text(it):
    when = H.fmt_when(it["due"])
    return "🔔 %s%s\n(список: %s, #%d)" % (it["text"], "\n" + when if when else "", it["list"], it["id"])


# ───────────────────────────── живые сообщения ─────────────────────────────

def hm(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def sig_of(it):
    return "%s|%s|%s" % (it["status"], it["due"], it["text"])


def render(it):
    """Текст и кнопки сообщения по ТЕКУЩЕМУ состоянию пункта: сообщение не врёт, что идёт/пришло."""
    if it is None:
        return "Пункт удалён.", None
    t = it["text"]
    over = it["due"] is not None and it["due"] <= H.now()
    if it["kind"] == "timer":
        if it["status"] != "open":
            return "■ Таймер остановлен: %s" % t, None
        if over:
            return "⏱ Время вышло: %s" % t, [[{"text": "+5 мин", "callback_data": "s:%d:300" % it["id"]},
                                              {"text": "■ Стоп", "callback_data": "x:%d" % it["id"]}]]
        return "⏱ Идёт: %s — до %s" % (t, hm(it["due"])), timer_buttons(it["id"])
    if it["status"] == "done":
        return "✓ Сделано: %s" % t, None
    if it["status"] == "dropped":
        return "✗ Удалено: %s" % t, None
    if it["due"] is None:
        return "Записано в «%s» без срока: %s" % (it["list"], t), [[
            {"text": "✓ Сделано", "callback_data": "d:%d" % it["id"]},
            {"text": "✗ Удалить", "callback_data": "x:%d" % it["id"]}]]
    if over:
        return "🔔 Пришло: %s\n(было на %s)" % (t, H.fmt_when(it["due"])), item_buttons(it["id"])
    return "⏳ Ждёт: %s — %s" % (t, H.fmt_when(it["due"])), item_buttons(it["id"])


def track(c, iid, chat, mid):
    c.execute("INSERT OR REPLACE INTO tgmsgs(item_id,chat,mid,sig,created) VALUES(?,?,?,?,?)",
              (iid, chat, mid, "", H.now()))


def sync_messages(c, bot):
    """Подгоняет все отслеженные сообщения под состояние пунктов; зовёт демон каждый тик."""
    rows = c.execute("SELECT * FROM tgmsgs WHERE created>? ORDER BY created", (H.now() - 3 * 86400,)).fetchall()
    for r in rows:
        it = H.get_item(c, r["item_id"])
        sg = sig_of(it) + ("|over" if it and it["due"] and it["due"] <= H.now() else "") if it else "gone"
        if sg == r["sig"]:
            continue
        text, btn = render(it)
        bot.edit(r["chat"], r["mid"], text, btn)
        c.execute("UPDATE tgmsgs SET sig=? WHERE chat=? AND mid=?", (sg, r["chat"], r["mid"]))


# ───────────────────────────── текст ─────────────────────────────

HELP_TEXT = (
    "Так тоже работает, сэр, без команд:\n"
    "• любой текст — новая запись («завтра в 10 позвонить», «Покупки: хлеб»)\n"
    "• «25 чай» — быстрый таймер на 25 минут с названием «чай»\n"
    "• голосовое сообщение — распознаю и обработаю как текст\n"
    "• кнопки под напоминаниями и таймерами нажимаются сами, без команд\n"
    "\n"
    "Команды:\n"
    "/reminders [список] (то же: /ls) — открытые пункты, всё или один список. Пример: /reminders Покупки\n"
    "/today — что по сроку сегодня\n"
    "/lists — списки и сколько в каждом открыто\n"
    "/add текст — новая запись, то же что просто текстом. Пример: /add купить хлеб\n"
    "/done N — отметить пункт выполненным. Пример: /done 12\n"
    "/snooze N срок — отложить пункт на время. Пример: /snooze 12 30м\n"
    "/del N — удалить пункт. Пример: /del 12\n"
    "/edit N текст — переписать пункт и/или срок. Пример: /edit 12 позвонить завтра в 18\n"
    "/t срок [текст] — запустить таймер; без аргументов — кнопки-пресеты. Пример: /t 25 чай\n"
    "/timers — какие таймеры сейчас идут\n"
    "/stop — остановить разом все таймеры\n"
    "/w слово = перевод — добавить слово в словарь. Пример: /w cat = кот\n"
    "/dictionary [запрос] (то же: /words) — список слов (с номерами) и статистика по словарю\n"
    "/delword N (то же: /wdel) — удалить слово из словаря. Пример: /delword 7\n"
    "/quiz [N] (то же: /повторить, /словарь) — прогнать словарь по Лейтнеру: слово → "
    "«Показать перевод» → «Знал»/«Не знал». Пример: /quiz 10\n"
    "/pc [действие] — управление ПК: статус, окна, скрин, звук, блок, сон, выключение; "
    "без аргумента — кнопки. Пример: /pc vol 40\n"
    "/away on|off — охрана в отсутствие: сообщу о клавиатуре/мыши, новых окнах, "
    "снятии блокировки и неверном пароле. Пример: /away on\n")


def cmd_ls(c, arg):
    its = H.items(c, arg or None, "open", "task")
    if not its:
        return "Пусто, сэр."
    out, last = [], None
    for it in its[:60]:
        if it["list"] != last and not arg:
            out.append("\n— %s —" % it["list"])
            last = it["list"]
        out.append(H.fmt_item(it))
    return "\n".join(out).strip()


def cmd_today(c):
    import datetime as dt
    end = int(dt.datetime.combine(dt.date.today() + dt.timedelta(days=1), dt.time(0)).timestamp())
    its = [i for i in H.items(c, None, "open") if i["due"] and i["due"] < end]
    return "\n".join(H.fmt_item(i) for i in its) or "На сегодня ничего, сэр."


def parse_id(s):
    s = (s or "").strip().lstrip("#")
    return int(s) if s.isdigit() else None


_last_item = None


def reply_for_text(c, text, bot=None, chat=None):
    """Возвращает (текст, кнопки) для обычного сообщения."""
    t = text.strip()
    parts = t.split(None, 1)
    if t.startswith("/"):
        cmd = parts[0][1:].split("@")[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        return command(c, cmd, arg, bot, chat)
    # «25 чай», «25м чай» — таймер
    if parts and H.parse_duration(parts[0]) and len(parts[0]) <= 6 and not parts[0].isalpha():
        d = H.parse_duration(parts[0])
        if d and d <= 86400 and (len(parts) == 1 or not parts[1][0].isdigit()):
            return start_timer_reply(c, d, parts[1] if len(parts) > 1 else "")
    global _last_item
    iid, due = H.add_smart(c, t, "tg")
    _last_item = iid
    return render(H.get_item(c, iid))


def start_timer_reply(c, secs, name=""):
    global _last_item
    iid, due = H.start_timer(c, secs, name, "tg")
    _last_item = iid
    return render(H.get_item(c, iid))


def command(c, cmd, arg, bot=None, chat=None):
    if cmd in ("start", "help", "h"):
        return HELP_TEXT, None
    if cmd in ("ls", "l", "reminders"):
        return cmd_ls(c, arg), None
    if cmd == "today":
        return cmd_today(c), None
    if cmd == "lists":
        ls = [l for l in H.lists(c) if l["open"] > 0]
        return "\n".join("%s — %d" % (l["name"], l["open"]) for l in ls) or "Открытых пунктов нигде нет.", None
    if cmd in ("add", "a"):
        if not arg:
            return "Что записать? /add текст", None
        return reply_for_text(c, arg)
    if cmd in ("done", "d"):
        iid = parse_id(arg)
        if iid is None:
            return "Номер пункта: /done 12", None
        ok = H.done(c, iid, "tg")
        return ("Готово, сэр." if ok else "Не нашёл открытый пункт №%s." % iid), None
    if cmd in ("snooze", "s"):
        a = arg.split(None, 1)
        iid = parse_id(a[0]) if a else None
        secs = H.parse_duration(a[1]) if len(a) > 1 else 3600
        if iid is None or not secs:
            return "Пример: /snooze 12 30м", None
        ok = H.snooze(c, iid, secs, source="tg")
        return ("Отложил на %s." % H.fmt_secs(secs) if ok else "Не нашёл пункт."), None
    if cmd in ("del", "rm"):
        iid = parse_id(arg)
        return ("Удалил." if iid is not None and H.drop(c, iid, "tg") else "Не нашёл пункт."), None
    if cmd == "edit":
        a = arg.split(None, 1)
        iid = parse_id(a[0]) if a else None
        if iid is None or len(a) < 2:
            return "Пример: /edit 12 новый текст", None
        cur = H.get_item(c, iid)
        if cur is None or cur["status"] == "dropped":
            return "Не нашёл пункт.", None
        clean, due, _ = H.parse_when(a[1])
        ok = H.edit(c, iid, clean or a[1], due if due else "keep", source="tg")
        return ("Исправил." if ok else "Не нашёл пункт."), None
    if cmd in ("t", "timer"):
        if not arg:
            return "Таймер — нажмите длительность или напишите «/t 25 чай»:", timer_presets()
        a = arg.split(None, 1)
        d = H.parse_duration(a[0])
        if not d:
            return "Не понял время. Пример: /t 25 чай, /t 1ч30", None
        return start_timer_reply(c, d, a[1] if len(a) > 1 else "")
    if cmd == "timers":
        its = H.items(c, None, "open", "timer")
        if not its:
            return "Таймеров нет.", None
        return "\n".join("⏱ #%d %s — осталось %s" % (i["id"], i["text"], H.fmt_secs(max(0, i["due"] - H.now())))
                         for i in its), None
    if cmd == "w":
        for sep in ("=", " — ", " - ", ":"):
            if sep in arg:
                term, tr = [x.strip() for x in arg.split(sep, 1)]
                break
        else:
            return "Формат: /w слово = перевод", None
        wid, new = H.add_word(c, term, tr)
        return ("Добавил: %s — %s" if new else "Обновил: %s — %s") % (term, tr), None
    if cmd in ("words", "dictionary"):
        ws = H.words(c, arg or None, 30)
        st = H.word_stats(c)
        head = "Слов: %d, к повторению: %d, выучено: %d\n" % (st["total"], st["due"], st["known"])
        return head + "\n".join("#%d %s — %s" % (w["id"], w["term"], w["translation"]) for w in ws), None
    if cmd in ("delword", "wdel"):
        wid = parse_id(arg)
        if wid is None:
            return "Номер слова: /delword 7 (номера — из /words)", None
        w = H.find_word_by_id(c, wid)
        if not w:
            return "Не нашёл слово №%s." % wid, None
        H.del_word(c, wid)
        return "Удалил: %s — %s" % (w["term"], w["translation"]), None
    if cmd in ("quiz", "повторить", "словарь"):
        n = int(arg) if arg.isdigit() else 5
        return quiz_next(c, n)
    if cmd == "pc":
        return pc_command(c, arg)
    if cmd == "away":
        a = arg.lower()
        if a in ("on", "вкл", "1"):
            H.meta_set(c, "away", 1)
            import hubguard
            lk = hubguard.locked()
            return ("Охрана включена, сэр. Сообщу о касании клавиатуры и мыши (со снимком экрана), "
                    "новых окнах, снятии блокировки и неверном пароле.\nЭкран сейчас %s.%s\nВыключить: /away off"
                    % ("заблокирован" if lk else "НЕ заблокирован",
                       "" if lk else " Заблокировать: /pc lock")), None
        if a in ("off", "выкл", "0"):
            H.meta_set(c, "away", 0)
            return "Охрана выключена. С возвращением, сэр.", None
        return "Охрана: %s. /away on — включить, /away off — выключить." % (
            "включена" if H.meta_get(c, "away", "0") == "1" else "выключена"), None
    if cmd == "stop":
        n = 0
        for it in H.items(c, None, "open", "timer"):
            n += H.drop(c, it["id"], "tg")
        return ("Остановлено таймеров: %d." % n) if n else "Таймеров нет.", None
    return "Не знаю такой команды. /help", None


# ───────────────────────────── квиз ─────────────────────────────

def quiz_next(c, left):
    ws = H.due_words(c, 1)
    if not ws:
        return "Повторять нечего, сэр.", None
    w = ws[0]
    return ("Слово: %s\n(осталось в серии: %d)" % (w["term"], left),
            [[{"text": "Показать перевод", "callback_data": "q:%d:%d" % (w["id"], left)}]])


# ───────────────────────────── ПК ─────────────────────────────

def pc_command(c, arg):
    a = arg.split(None, 1)
    if not a:
        rows = [[{"text": "Состояние", "callback_data": "p:status"}, {"text": "Окна", "callback_data": "p:apps"},
                 {"text": "Скрин", "callback_data": "p:shot"}],
                [{"text": "Mute", "callback_data": "p:mute"}, {"text": "Unmute", "callback_data": "p:unmute"},
                 {"text": "Блок", "callback_data": "p:lock"}],
                [{"text": "Мониторы off", "callback_data": "p:dark"}, {"text": "Сон", "callback_data": "p:sleep"}],
                [{"text": "Перезагрузка", "callback_data": "p:reboot"}, {"text": "Выключить", "callback_data": "p:off"}]]
        return "Управление ПК. Опасные действия спросят подтверждение.\n/pc vol 40 · /pc close N", rows
    return pc_do(c, a[0].lower(), a[1] if len(a) > 1 else "", confirmed=False)


def pc_do(c, action, arg, confirmed):
    lvl = hubpc.LEVEL.get(action)
    if lvl is None:
        return "Такого действия нет. /pc", None
    if lvl >= 1 and not confirmed:
        stamp = H.now()
        data = "pc:%s:%s:%d" % (action, arg, stamp)
        return ("Подтвердите: %s %s (60 секунд)" % (action, arg)).strip(), [[
            {"text": "Да, выполнить", "callback_data": data[:64]},
            {"text": "Отмена", "callback_data": "n:0"}]]
    text, png = hubpc.run(action, arg)
    H.log(c, "pc", None, "%s %s" % (action, arg))
    return text, png


# ───────────────────────────── кнопки (callback) ─────────────────────────────

def handle_callback(c, bot, chat, mid, cb_id, data):
    k, _, rest = data.partition(":")
    if k == "n":
        bot.answer(cb_id, "Отменено")
        bot.edit(chat, mid, "Отменено.")
        return
    if k in ("d", "s", "x") and chat and mid:
        track(c, int(rest.split(":")[0]), chat, mid)     # осиротевшее сообщение снова под присмотром
    if k == "d":
        H.done(c, int(rest), "tg")
        bot.answer(cb_id, "Готово")
        sync_messages(c, bot)
    elif k == "s":
        iid, _, v = rest.partition(":")
        if v == "tom":
            H.snooze(c, int(iid), until=tomorrow_9(), source="tg")
            bot.answer(cb_id, "Отложено на завтра, 09:00")
        else:
            H.snooze(c, int(iid), int(v), source="tg")
            bot.answer(cb_id, "Отложено на %s" % H.fmt_secs(int(v)))
        sync_messages(c, bot)
    elif k == "x":
        H.drop(c, int(rest), "tg")
        bot.answer(cb_id, "Остановлено")
        sync_messages(c, bot)
    elif k == "t":
        text, btn = start_timer_reply(c, int(rest))
        bot.answer(cb_id, "Таймер запущен")
        r = bot.send(chat, text, btn)
        track(c, _last_item, chat, r["message_id"])
        sync_messages(c, bot)
    elif k == "q":
        wid, _, left = rest.partition(":")
        w = c.execute("SELECT * FROM words WHERE id=?", (int(wid),)).fetchone()
        bot.answer(cb_id)
        if w:
            bot.edit(chat, mid, "%s — %s" % (w["term"], w["translation"]), [[
                {"text": "✓ Знал", "callback_data": "y:%s:%s" % (wid, left)},
                {"text": "✗ Не знал", "callback_data": "m:%s:%s" % (wid, left)}]])
    elif k in ("y", "m"):
        wid, _, left = rest.partition(":")
        H.review(c, int(wid), k == "y")
        bot.answer(cb_id, "Верно" if k == "y" else "Повторим")
        left = int(left) - 1
        if left > 0:
            text, btn = quiz_next(c, left)
            bot.edit(chat, mid, text, btn)
        else:
            bot.edit(chat, mid, "Серия окончена, сэр.")
    elif k == "p":
        bot.answer(cb_id)
        res = pc_do(c, rest, "", confirmed=False)
        send_pc_result(bot, chat, res)
    elif k == "pc":
        action, arg, stamp = rest.split(":")[0], rest.split(":")[1], rest.split(":")[-1]
        if H.now() - int(stamp or 0) > CONFIRM_TTL:
            bot.answer(cb_id, "Подтверждение истекло")
            bot.edit(chat, mid, "Подтверждение истекло.")
            return
        bot.answer(cb_id, "Выполняю")
        bot.edit(chat, mid, "Выполняю: %s" % action)
        send_pc_result(bot, chat, pc_do(c, action, arg, confirmed=True))


def send_pc_result(bot, chat, res):
    text, extra = res
    if isinstance(extra, str) and os.path.exists(extra):
        try:
            return bot.photo(chat, extra, text)
        finally:
            os.unlink(extra)
    return bot.send(chat, text, extra)


# ───────────────────────────── цикл ─────────────────────────────

def owner_ids():
    o = H.cfg("owner")
    if isinstance(o, (list, tuple)):
        return {int(x) for x in o}
    return {int(o)} if o else set()


def process_update(c, bot, up):
    if "callback_query" in up:
        q = up["callback_query"]
        if q["from"]["id"] not in owner_ids():
            return
        m = q.get("message") or {}
        try:
            handle_callback(c, bot, m.get("chat", {}).get("id"), m.get("message_id"), q["id"], q.get("data", ""))
        except Exception as e:                      # одна кнопка не должна ронять цикл
            bot.answer(q["id"], "Ошибка: %s" % e)
        return
    m = up.get("message")
    if not m or m.get("from", {}).get("id") not in owner_ids():
        return
    chat = m["chat"]["id"]
    text = m.get("text") or ""
    if not text and m.get("voice"):
        text = transcribe(bot, m["voice"]) or ""
        if not text:
            bot.send(chat, "Не удалось разобрать голос, сэр.")
            return
        bot.send(chat, "Услышал: " + text)
    if not text:
        return
    global _last_item
    _last_item = None
    try:
        res = reply_for_text(c, text, bot, chat)
    except Exception as e:
        bot.send(chat, "Ошибка: %s" % e)
        return
    sent = send_pc_result(bot, chat, res)
    if _last_item and sent:
        track(c, _last_item, chat, sent["message_id"])


def transcribe(bot, voice):
    asr = os.path.expanduser("~/.config/hypr/scripts/voice_asr.py")
    if not os.path.exists(asr):
        return None
    import subprocess
    import tempfile
    try:
        info = bot.call("getFile", {"file_id": voice["file_id"]})
        d = tempfile.mkdtemp()
        ogg, wav = os.path.join(d, "v.ogg"), os.path.join(d, "v.wav")
        urllib.request.urlretrieve(bot.base.replace("/bot", "/file/bot") + info["file_path"], ogg)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", ogg, "-ar", "16000", "-ac", "1", wav], timeout=30)
        return subprocess.run(["python3", asr, wav], capture_output=True, text=True, timeout=120).stdout.strip()
    except Exception:
        return None


def poll_loop(stop, log=print):
    """Блокирующий цикл getUpdates; вызывается из потока демона."""
    tok = token()
    if not tok:
        return
    bot = Bot(tok)
    c = H.connect()
    offset = int(H.meta_get(c, "tg_offset", 0))
    fails = 0
    while not stop.is_set():
        try:
            ups = bot.call("getUpdates", {"offset": offset, "timeout": 25, "allowed_updates":
                                          ["message", "callback_query"]}, timeout=40)
            fails = 0
            for up in ups:
                offset = up["update_id"] + 1
                process_update(c, bot, up)
                H.meta_set(c, "tg_offset", offset)
        except urllib.error.HTTPError as e:
            fails += 1
            log("tg http %s" % e.code)
            stop.wait(min(60, 3 * fails) if e.code != 409 else 30)
        except Exception as e:
            fails += 1
            stop.wait(min(60, 2 * fails))


def flush_outbox(c, bot):
    """Отправляет накопленное (напоминания, дайджест). Не блокирует при сбое сети."""
    chats = owner_ids()
    if not chats:
        return
    for r in c.execute("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id LIMIT 20").fetchall():
        p = json.loads(r["payload"])
        try:
            for ch in chats:
                m = bot.send(ch, p["text"], p.get("buttons"))
                if p.get("item") and m:
                    track(c, p["item"], ch, m["message_id"])
            c.execute("UPDATE outbox SET sent_at=? WHERE id=?", (H.now(), r["id"]))
        except Exception:
            c.execute("UPDATE outbox SET tries=tries+1 WHERE id=?", (r["id"],))
            break


def enqueue(c, text, buttons=None, item=None):
    c.execute("INSERT INTO outbox(created,payload) VALUES(?,?)",
              (H.now(), json.dumps({"text": text, "buttons": buttons, "item": item}, ensure_ascii=False)))
