#!/usr/bin/env python3
"""hub — Telegram-слой. Без ИИ: команды, кнопки, быстрый текст. Только стандартная библиотека.

Bot ходит на HUB_TG_API (по умолчанию api.telegram.org) — для теста подставляется фейковый сервер.
Принимает сообщения только от владельца (config.json: owner). Пусто — отказ всем."""
import json
import mimetypes
import os
import socket
import subprocess
import tempfile
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import hublib as H
import hubpc
import tfa

API = os.environ.get("HUB_TG_API", "https://api.telegram.org")
# Запасной путь (13.10.2026): у провайдера адреса Bot API api.telegram.org открываются через
# раз (1 из 4), бот молчал. Сначала напрямую; не вышло — через Tor: 9050 — служба tor,
# 9150 — Tor Browser, пока он открыт. Удачный путь помнится ROUTE_TTL секунд.
TOR_PORTS = (9050, 9150)
DIRECT_CONNECT = 6          # сек на соединение напрямую, дальше — через Tor
ROUTE_TTL = 600


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _opener(port):
    if port is None:
        return urllib.request.build_opener()
    import socks
    import sockshandler
    return urllib.request.build_opener(
        sockshandler.SocksiPyHandler(socks.SOCKS5, "127.0.0.1", port, rdns=True))
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


BRAND = "HUB"                        # имя в шапках пультов


class Html(str):
    """Текст с разметкой HTML Telegram: send/edit ставят parse_mode."""


def esc(s):
    import html
    return html.escape(str(s), quote=False)


class Bot:
    def __init__(self, tok):
        self.base = "%s/bot%s/" % (API, tok)
        self.route, self.route_at = None, 0.0     # None — напрямую, число — порт Tor
        self.lock = threading.Lock()

    def routes(self):
        """Порядок путей: последний удачный первым, если ему меньше ROUTE_TTL."""
        tor = [p for p in TOR_PORTS if _port_open(p)] if API.startswith("https://api.telegram.org") else []
        order = [None] + tor
        with self.lock:
            if self.route in order and time.time() - self.route_at < ROUTE_TTL:
                order.remove(self.route)
                order.insert(0, self.route)
        return order

    def open(self, req, timeout):
        last = None
        order = self.routes()
        for port in order:
            if port is None and len(order) > 1:
                # Напрямую соединение висит до таймаута. Таймаут urllib действует и на чтение,
                # а длинный опрос getUpdates молчит до 25 с, поэтому соединение проверяем
                # отдельно, коротко, и только потом шлём запрос.
                try:
                    host = urllib.parse.urlsplit(req.full_url).hostname
                    socket.create_connection((host, 443), timeout=DIRECT_CONNECT).close()
                except OSError as e:
                    last = e
                    continue
            try:
                r = _opener(port).open(req, timeout=timeout if port is None else max(timeout, 30))
                with self.lock:
                    self.route, self.route_at = port, time.time()
                return r
            except urllib.error.HTTPError:
                raise
            except (urllib.error.URLError, OSError) as e:
                last = e
        raise last or urllib.error.URLError("нет пути до Telegram")

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
        with self.open(req, timeout) as r:
            j = json.loads(r.read())
        if not j.get("ok"):
            raise RuntimeError(j.get("description", "telegram error"))
        return j["result"]

    def send(self, chat, text, buttons=None):
        p = {"chat_id": chat, "text": text[:4000]}
        if isinstance(text, Html):
            p["parse_mode"] = "HTML"
        if buttons:
            p["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", p)

    def edit(self, chat, mid, text, buttons=None):
        p = {"chat_id": chat, "message_id": mid, "text": text[:4000],
             "reply_markup": {"inline_keyboard": buttons or []}}
        if isinstance(text, Html):
            p["parse_mode"] = "HTML"
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

def item_buttons(iid, rep=False):
    """rep — повторяющееся (14.10.2026): «Отметить» (срок → следующий раз) и «Закрыть цикл»."""
    return [[{"text": "✓ Отметить" if rep else "✓ Сделано", "callback_data": "d:%d" % iid},
             {"text": "⏰ +1ч", "callback_data": "s:%d:3600" % iid},
             {"text": "🌙 Завтра", "callback_data": "s:%d:tom" % iid}],
            [{"text": "+10 мин", "callback_data": "s:%d:600" % iid},
             {"text": "■ Закрыть цикл" if rep else "✗ Удалить", "callback_data": "x:%d" % iid}]]


def timer_presets():
    return [[{"text": l, "callback_data": "t:%d" % (m * 60)} for m, l in PRESETS[:3]],
            [{"text": l, "callback_data": "t:%d" % (m * 60)} for m, l in PRESETS[3:]]]


def timer_buttons(iid):
    """21.10.2026, просьба: слева «Добавить» (меню времени, своё тоже), справа «Обновить»
    (остаток сейчас), снизу «Стоп»."""
    return [[{"text": "+ Добавить", "callback_data": "ta:%d" % iid},
             {"text": "↻ Обновить", "callback_data": "tr:%d" % iid}],
            [{"text": "■ Стоп", "callback_data": "x:%d" % iid}]]


TIMER_ADD = [(60, "+1 мин"), (300, "+5 мин"), (600, "+10 мин"),
             (900, "+15 мин"), (1800, "+30 мин"), (3600, "+1 ч")]


def timer_add_menu(iid):
    return [[{"text": l, "callback_data": "tp:%d:%d" % (iid, v)} for v, l in TIMER_ADD[:3]],
            [{"text": l, "callback_data": "tp:%d:%d" % (iid, v)} for v, l in TIMER_ADD[3:]],
            [{"text": "✎ Своё", "callback_data": "tc:%d" % iid},
             {"text": "← Назад", "callback_data": "tr:%d" % iid}]]


def timer_add(c, iid, secs):
    """Прибавить к идущему таймеру (от срока, не от «сейчас»); вышедший — от «сейчас»."""
    it = H.get_item(c, iid)
    if it is None or it["status"] != "open":
        return None
    due = max(it["due"] or 0, H.now()) + int(secs)
    H.snooze(c, iid, until=due, source="tg")
    return due


def tomorrow_9():
    import datetime as dt
    d = dt.datetime.now().date() + dt.timedelta(days=1)
    return int(dt.datetime.combine(d, dt.time(9, 0)).timestamp())


def ack_pc(c, iid):
    """Любая реакция из Telegram гасит эскалацию и убирает висящее уведомление на ПК."""
    H.mark_seen(c, iid)


def item_text(it):
    when = H.when(it)
    return "🔔 %s%s\n(список: %s, #%d)" % (it["text"], "\n" + when if when else "", it["list"], it["id"])


# ───────────────────────────── живые сообщения ─────────────────────────────

def hm(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def sig_of(it):
    return "%s|%s|%s" % (it["status"], it["due"], it["text"])


# Чем остановили таймер (журнал hub, events.data у drop) → по-человечески.
STOP_HOW = {"widget close": "крестиком", "widget clear": "«Очистить стол»",
            "widget preset": "сменилась раскладка виджетов (пресет)", "widget click": "щелчком по виджету",
            "widget replay": "запущен заново (REPLAY)", "widget new": "заменён новым (NEW)",
            "widget pause": "пауза щелчком по timer.exe", "tg": "из Telegram", "clocker": "в Clocker",
            "clocker pause": "пауза в Clocker", "clocker delete": "удалён в Clocker", "pc": "закрыли уведомление на ПК",
            # 23.10.2026, просьба: «что значит пропал? пусть пишет конкретную причину»
            "lost": "сбой: процесс виджетов на ПК не работал 90 с (упал или выключен)",
            "lost conf": "на столе 90 с не было виджета с этим таймером — осиротевшая запись: "
                         "таймер с тем же названием перезапустили, старая осталась без виджета"}
_stop_c = [None]


def stop_info(it):
    """(когда закрыт, как) по последнему drop в журнале hub; нет записи — время правки пункта."""
    try:
        if _stop_c[0] is None:
            _stop_c[0] = H.connect()
        r = _stop_c[0].execute("SELECT ts, data FROM events WHERE kind='drop' AND item_id=? "
                               "ORDER BY id DESC LIMIT 1", (it["id"],)).fetchone()
        if r:
            return r["ts"], r["data"]
    except Exception:
        pass
    return it["updated_at"] or H.now(), ""


def stopped_text(it):
    """23.10.2026, просьба: если таймер упал, сбой или пресеты сменились — писать, что закрыт,
    сколько оставалось, когда закрыт и во сколько должен был закончиться."""
    ts, how = stop_info(it)
    head = "⏸ Таймер на паузе" if how in ("widget pause", "clocker pause") else "■ Таймер закрыт"
    lines = ["%s: %s" % (head, it["text"]), "в %s%s" % (hm(ts), " · " + STOP_HOW[how] if how in STOP_HOW else "")]
    if it["due"] and it["due"] > ts:
        lines.append("оставалось %s, закончился бы в %s" % (H.fmt_secs(it["due"] - ts), hm(it["due"])))
    return "\n".join(lines)


def bare(it):
    """« · без виджета»: в Clocker снята галочка «Создать виджет» (23.10.2026) — звонит сам hub."""
    try:
        if _stop_c[0] is None:
            _stop_c[0] = H.connect()
        return " · без виджета" if it["id"] in H.timer_nowidget(_stop_c[0]) else ""
    except Exception:
        return ""


def render(it):
    """Текст и кнопки сообщения по ТЕКУЩЕМУ состоянию пункта: сообщение не врёт, что идёт/пришло."""
    if it is None:
        return "Пункт удалён.", None
    t = it["text"]
    over = it["due"] is not None and it["due"] <= H.now()
    if it["kind"] == "timer":
        if it["status"] != "open":
            # 21.10.2026: «Время вышло» в 12:38 после «Стоп» с ПК в 12:55 переписывалось в
            # «Таймер остановлен» — по чату казалось, что таймер не звенел. Отзвеневший помнит время.
            if it["fired_pc"] and it["due"]:
                return "⏱ Время вышло в %s: %s\n■ остановлен в %s" % (
                    hm(it["due"]), t, hm(it["updated_at"] or H.now())), None
            return stopped_text(it), None
        if over:
            return "⏱ Время вышло: %s" % t, [[{"text": "+5 мин", "callback_data": "s:%d:300" % it["id"]},
                                              {"text": "■ Стоп", "callback_data": "x:%d" % it["id"]}]]
        # Остаток на момент отправки/правки (16.10.2026, пользователь): в тексте таймера — полный срок
        # («Таймер 3 ч 59 мин»), а сколько осталось, было не видно. Каждый тик не правим: sig без остатка.
        return "⏱ Идёт: %s\nосталось %s — до %s%s" % (t, H.fmt_secs(it["due"] - H.now()), hm(it["due"]), bare(it)), \
            timer_buttons(it["id"])
    if it["status"] == "done":
        return "✓ Сделано: %s" % t, None
    if it["status"] == "dropped":
        return ("■ Цикл закрыт: %s" if it["repeat"] else "✗ Удалено: %s") % t, None
    if it["due"] is None:
        return "Записано в «%s» без срока: %s" % (it["list"], t), [[
            {"text": "✓ Сделано", "callback_data": "d:%d" % it["id"]},
            {"text": "✗ Удалить", "callback_data": "x:%d" % it["id"]}]]
    if over:
        return "🔔 Пришло: %s\n(было на %s)" % (t, H.when(it)), item_buttons(it["id"], bool(it["repeat"]))
    return "⏳ Ждёт: %s — %s" % (t, H.when(it)), item_buttons(it["id"], bool(it["repeat"]))


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

# 14.10.2026: справка короче и по разделам; в меню — 6 команд, остальные работают молча
HELP_TEXT = Html(
    "<b>◆ " + BRAND + " · СПРАВКА</b>\n"
    "<i>Пишите как человеку, сэр, — разберу. Голосовые тоже.</i>\n"
    "\n<b>■ ЗАДАЧИ</b>\n"
    "<code>купить хлеб       </code> новая задача\n"
    "<code>завтра в 10 звонок</code> со сроком\n"
    "<code>Покупки: хлеб     </code> в свой список\n"
    "/tasks — пульт: добавить, изменить, удалить, важность\n"
    "\n<b>■ ТАЙМЕРЫ</b>\n"
    "<code>25 чай            </code> таймер на 25 мин\n"
    "/timer — длительности и идущие\n"
    "\n<b>■ СЛОВАРЬ</b>\n"
    "<code>/w cat = кот      </code> новое слово\n"
    "/words — повторить, список\n"
    "\n<b>■ WHATSAPP</b>\n"
    "/wa — отложенные сообщения: кому, текст, когда\n"
    "\n<b>■ ПК И ДОМ</b>\n"
    "/pc — состояние, окна, скрин, звук, сон\n"
    "/alarm — будильник и Сторож\n"
    "/log — журнал файлом: сон, пробуждения, что сработало\n"
    "/away — охрана: «Ухожу» запирает экран и следит\n"
    "\n<b>■ ЗАЩИТА</b>\n"
    "ПК, охрана и WhatsApp просят 6 цифр из аутентификатора\n"
    "/code 123456 — открыть на 15 мин · /lock — закрыть\n"
    "\n<i>Все команды — /help all</i>")

# 14.10.2026, просьба: «/help all — посмотреть абсолютно все команды. Просто help — компактная
# версия, базовый минимум, без дублей». Здесь — всё, с синонимами.
HELP_ALL = Html(
    "<b>◆ " + BRAND + " · ВСЕ КОМАНДЫ</b>\n"
    "<i>Через «·» — синонимы. N — номер из пульта задач, #74 — номер пункта в базе.</i>\n"
    "\n<b>■ ЗАДАЧИ</b>\n"
    "<code>текст              </code> новая задача (срок и «Список:» понимаю)\n"
    "<code>/tasks · /ls · /l · /reminders</code> пульт, все задачи\n"
    "<code>/tasks Покупки     </code> пульт одного списка\n"
    "<code>/today             </code> пульт: только сегодня\n"
    "<code>/lists             </code> списки и сколько в них открыто\n"
    "<code>/add · /a текст    </code> записать задачу\n"
    "<code>/done · /d N       </code> сделано\n"
    "<code>/snooze · /s N 30м </code> отложить (по умолчанию на 1 ч)\n"
    "<code>/edit N текст      </code> переписать (срок в тексте тоже)\n"
    "<code>/del · /rm N       </code> удалить\n"
    "\n<b>■ ТАЙМЕРЫ</b>\n"
    "<code>25 чай             </code> таймер на 25 мин\n"
    "<code>/timer · /t · /timers</code> пульт таймеров, «Свой таймер»\n"
    "<code>/timer 1ч30 стирка </code> таймер с названием\n"
    "<code>/stop              </code> остановить все таймеры\n"
    "\n<b>■ СЛОВАРЬ</b>\n"
    "<code>/w cat = кот       </code> новое слово\n"
    "<code>/words · /dictionary [поиск]</code> пульт словаря\n"
    "<code>/quiz · /повторить · /словарь</code> повторение\n"
    "<code>/delword · /wdel 7 </code> удалить слово по номеру из /words\n"
    "\n<b>■ WHATSAPP</b>\n"
    "<code>/wa                </code> пульт: очередь, «Новое сообщение»\n"
    "<code>/wa мама           </code> сразу к выбору контакта\n"
    "<code>/wa N              </code> сообщение N из пульта\n"
    "<code>/wa история        </code> журнал: отправленные и отменённые\n"
    "<code>/wa clear          </code> очистить журнал (спросит «да/нет»)\n"
    "<code>/wa stop           </code> остановить все запланированные (/wa resume — вернуть)\n"
    "<i>Опоздало до часа — уйдёт само; больше — спрошу.</i>\n"
    "\n<b>■ ЗАЩИТА</b>\n"
    "<code>/code 123456       </code> второй ключ: ПК, охрана, WhatsApp — 15 мин\n"
    "<code>/lock              </code> закрыть доступ сейчас\n"
    "<i>5 неверных кодов — заперто до tfa unlock на ноутбуке. Запереть экран и включить охрану можно без кода.</i>\n"
    "\n<b>■ ОХРАНА</b>\n"
    "<code>/away              </code> пульт охраны\n"
    "<code>/away on · off     </code> включить · выключить\n"
    "<code>/away photo        </code> снимок с камеры\n"
    "<code>/away rec [сек]    </code> видео (10 с)\n"
    "<code>/away mic [сек]    </code> звук (30 с, до 10 мин)\n"
    "<code>/away stop         </code> прервать запись — пришлю, что успел\n"
    "\n<b>■ ПК</b>\n"
    "<code>/pc                </code> пульт ПК\n"
    "<code>/pc apps           </code> окна (закрыть кнопкой)\n"
    "<code>/pc shot           </code> снимок экрана\n"
    "<code>/pc vol 40         </code> громкость\n"
    "<code>/pc mute · unmute  </code> звук\n"
    "<code>/pc lock · dark · light</code> замок · погасить · включить экраны\n"
    "<code>/pc close N        </code> закрыть окно N из /pc apps\n"
    "<code>/pc sleep · reboot · off</code> сон · перезагрузка · выключение\n"
    "\n<b>■ БУДИЛЬНИК</b>\n"
    "<code>/alarm             </code> пульт будильника и Сторожа\n"
    "<code>/alarm off ПРИЧИНА </code> аварийно выключить\n"
    "<code>/alarm on          </code> включить\n"
    "\n<b>■ ЖУРНАЛ</b>\n"
    "<code>/log               </code> файл за 14 дней: сон, пробуждения (плановые тоже), сработавшее, задачи, WhatsApp, охрана\n"
    "<code>/log 3             </code> только за 3 дня\n"
    "<i>Старше 2 недель записи удаляются сами. О сне и пробуждении бот больше не пишет — смотрите /log.</i>\n"
    "\n<b>■ ПРОЧЕЕ</b>\n"
    "<code>/help              </code> коротко\n"
    "<code>/help all          </code> эта страница\n"
    "<i>Голосовые понимаю как текст.</i>")

MENU = [("away", "охрана — ухожу из дома"), ("tasks", "пульт задач"), ("timer", "таймеры"), ("words", "словарь"),
        ("wa", "WhatsApp: отложенные"), ("pc", "управление ПК"), ("alarm", "будильник"),
        ("log", "журнал: сон, пробуждения"), ("help", "справка")]


# 13.10.2026, просьба: «аварийно добавить команду боту на выключение будильника (и на вкл)…
# должен выключать и Сторожа на этот день. Если я его выключаю — значит, я не дома».
WAKE = os.path.expanduser("~/.config/hypr/scripts/wake_alarm.py")


# 14.10.2026, просьба: «хаб основной, первый запасной» — проверки будильника и Сторожа
# приходят от этого бота, и ответ на пример ловится здесь. Сверяет сам будильник
# (wake_alarm.py tg-code): 0 — принят, 1 — не тот, 2 — проверки нет (сообщение обычное).
# Кодом считается только ответ из цифр и знаков примера — «напомни через 15 минут» не он.
WAKE_CODE_CHARS = set("0123456789 =+-−×xх*·:.,")


def wake_code(text):
    t = text.strip()
    if not t or not any(ch.isdigit() for ch in t) or not set(t.lower()) <= WAKE_CODE_CHARS:
        return None
    try:
        r = subprocess.run([sys.executable, WAKE, "tg-code", t], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode in (0, 1) and r.stdout.strip():
        return r.stdout.strip()
    return None


def _get_guard():
    import hubguard
    return hubguard.active_guard


NO_GUARD = "Служба охраны не на связи, сэр (hubd не запущен)."


def _away_photo():
    g = _get_guard()
    if not g:
        return NO_GUARD
    path, err = g.take_photo()
    if err:
        return "Камера: %s" % err
    threading.Thread(target=lambda: (g.send_file(path, "📷 Снимок с камеры", "photo"),), daemon=True).start()
    return "📷 Снимаю — пришлю ниже."


def _away_rec(secs):
    g = _get_guard()
    if not g:
        return NO_GUARD

    def do():
        path, err = g.record_video(secs)
        if err:
            g.say("Видео: %s" % err)
        else:
            g.send_file(path, "📹 Видео с камеры (%dс)" % secs, "video")
    threading.Thread(target=do, daemon=True).start()
    return "📹 Пишу видео %d с — пришлю ниже." % secs


# 14.10.2026, просьба: «в чем разница между звук и слушать, это же одно и тоже».
# Так и было: обе писали файл, «Слушать» — лишь 5 мин с остановкой. Теперь одна
# запись: любую длину можно прервать «■ Стоп», присылается записанное до остановки.
# listen оставлен синонимом mic (старые кнопки и команды).

def _away_mic(secs):
    g = _get_guard()
    if not g:
        return NO_GUARD
    path, err = g.start_mic_stream(secs)
    if err:
        return "Микрофон: %s" % err
    t0 = time.time()

    def wait_and_send():
        if g._mic_proc:
            g._mic_proc.wait()
        got = max(1, round(time.time() - t0))
        if os.path.exists(path) and os.path.getsize(path) > 0:
            g.send_file(path, "🎤 Запись микрофона (%dс)" % min(got, secs), "voice")
        else:
            g.say("Запись не удалась.")
    threading.Thread(target=wait_and_send, daemon=True).start()
    return "🎤 Пишу звук %s — пришлю ниже. Раньше — «■ Стоп запись»." % _dur_ru(secs)


_away_listen = _away_mic


def _dur_ru(secs):
    return "%d мин" % (secs // 60) if secs >= 60 and secs % 60 == 0 else "%d с" % secs


def _away_stop():
    g = _get_guard()
    if not g:
        return NO_GUARD
    g.stop_mic()
    g.stop_cam()
    return "■ Запись остановлена."


# 14.10.2026, просьба: «/away тоже оформи красивым и понятным. Это самая наверно часто
# используемая команда». Панель как у будильника: состояние, что слежу, кнопки.
# Главная кнопка, когда выключена, — «Ухожу»: запереть экран и включить охрану разом.
# Охрану поднимает цикл hubd (TICK 2 с) по meta away — здесь только флаг.

def _away_set(c, on):
    H.meta_set(c, "away", 1 if on else 0)
    H.meta_set(c, "away_since", H.now() if on else 0)


def _lock_screen():
    """Запереть экран; True — замок поднялся."""
    import hubguard
    if hubguard.locked():
        return True
    hubpc.run("lock", "")
    for _ in range(10):                  # замок поднимается не сразу; ждём, чтобы охрана
        if hubguard.locked():            # не прислала «экран заблокирован» как событие
            return True
        time.sleep(0.3)
    return False


def away_panel(c, note=None):
    import hubguard
    on = H.meta_get(c, "away", "0") == "1"
    lk = hubguard.locked()
    g = hubguard.active_guard
    since = int(H.meta_get(c, "away_since", 0) or 0)
    state = "● ВКЛЮЧЕНА" + (" с %s" % hm(since) if on and since else "") if on else "○ ВЫКЛЮЧЕНА"
    out = ["<b>◆ %s · ОХРАНА</b>" % BRAND,
           "<code>%s · экран %s</code>" % (state, "🔒 заперт" if lk else "🔓 открыт")]
    if note:
        out.append("<i>%s</i>" % note)
    out.append("")
    if on:
        if not (g and g.threads):
            out.append("<i>Поднимаю охрану — пара секунд, сэр. Нажмите ↻.</i>")
        elif g.session:
            out.append("⚠ <b>Кто-то за ПК</b> — последнее касание в %s." %
                       time.strftime("%H:%M:%S", time.localtime(g.last_input)))
        else:
            out.append("<i>Тихо, сэр. Слежу.</i>")
        out.append("<b>■ ПРИШЛЮ</b>\n"
                   "· первое касание — сразу, со снимком экрана\n"
                   "· дальше раз в минуту журнал по порядку:\n"
                   "  текст, сочетания клавиш, клики, окна\n"
                   "· снятие замка и неверный пароль")
        if not lk:
            out.append("\n<i>Экран не заперт — лучше запереть.</i>")
        top = [] if lk else [btn("🔒 Экран блокировки", "k:glk")]
        top.append(btn("○ Выключить", "k:goff"))
        rows = [top]
    else:
        out.append("<i>Уходите — нажмите «Ухожу», сэр: запру экран и начну следить.</i>\n"
                   "Камера и микрофон работают и без охраны.")
        rows = [[btn("🛡 Ухожу: замок + охрана", "k:gonl")],
                [btn("● Только охрана", "k:gon")] + ([] if lk else [btn("🔒 Экран блокировки", "k:glk")])]
    busy = g and ((g._mic_proc and g._mic_proc.poll() is None) or (g._cam_proc and g._cam_proc.poll() is None))
    rows += [[btn("📷 Снимок", "k:gph"), btn("📹 Видео 10с", "k:grec:10"), btn("📹 30с", "k:grec:30")],
             [btn("🎤 Звук 30с", "k:gmic:30"), btn("🎤 2 мин", "k:gmic:120"), btn("🎤 5 мин", "k:gmic:300")]]
    if busy:
        rows.append([btn("■ Стоп запись", "k:gst")])
    rows.append([btn("📜 Журнал", "k:glog"), btn("↻ Обновить", "k:gr")])
    return Html("\n".join(out)), rows


# ───────────────────────────── пульт задач ─────────────────────────────
# 14.10.2026, просьба: «будто удалённый центр управления», «полное управление» кнопками —
# добавить, изменить, удалить, важность; вид «общий» (по срокам) и «списком» (по важности,
# как v в hub_app). Номера 1..N запоминаются: /done 3 — третий пункт последнего пульта.

NUMS_KEY = "tg_nums"                 # номера последнего пульта: N → id пункта
VIEW_KEY = "tg_view"                 # {"per": all|today, "mode": time|prio, "arg": список}
WAIT_KEY = "tg_wait"                 # ждём текст после кнопки: {"op", "id", "chat", "mid", "ts"}
WAIT_TTL = 15 * 60
PRIO_MARK = {2: "🔴", 1: "🟡", 0: ""}
PRIO_HEAD = {2: "🔴 HIGH", 1: "🟡 MID", 0: "⚪ DEFAULT"}
PRIO_BTN = {2: "🔴 High", 1: "🟡 Mid", 0: "⚪ Default"}
REPEAT_RU = {"daily": "каждый день", "weekly": "каждую неделю", "monthly": "каждый месяц"}


def btn(text, data):
    return {"text": text, "callback_data": data}


def order_open(rows):
    """Ручной порядок как в hub_app.order_open: сперва pos (Alt+j/k), без pos — по сроку."""
    out = sorted((r for r in rows if r["pos"] is not None), key=lambda r: (r["pos"], r["id"]))
    for r in sorted((r for r in rows if r["pos"] is None), key=lambda r: (not r["due"], r["id"])):
        if r["due"]:
            out.insert(max((n + 1 for n, x in enumerate(out) if x["due"]), default=0), r)
        else:
            out.append(r)
    return out


def _jget(c, key, default):
    try:
        v = json.loads(H.meta_get(c, key) or "null")
    except ValueError:
        v = None
    return default if v is None else v


def view_get(c):
    v = {"per": "all", "mode": "time", "arg": ""}
    v.update(_jget(c, VIEW_KEY, {}))
    return v


def _buckets(its):
    """[(заголовок, [пункты])] — по сроку: просрочено, сегодня, завтра, позже, без срока.
    Внутри дат — по времени, без срока — ручной порядок Alt+j/k."""
    import datetime as dt
    today = dt.date.today()
    now = H.now()
    b = {k: [] for k in ("over", "today", "tom", "later", "none")}
    for it in order_open(its):
        if not it["due"]:
            b["none"].append(it)
            continue
        d = dt.datetime.fromtimestamp(it["due"]).date()
        b["over" if H.overdue(it, now) else "today" if d == today else
          "tom" if d == today + dt.timedelta(days=1) else "later"].append(it)
    for k in ("over", "today", "tom", "later"):
        b[k].sort(key=lambda r: (r["due"], r["id"]))
    names = (("over", "▲ ПРОСРОЧЕНО"), ("today", "■ СЕГОДНЯ"), ("tom", "▶ ЗАВТРА"),
             ("later", "▷ ПОЗЖЕ"), ("none", "○ БЕЗ СРОКА"))
    return [(title, b[k]) for k, title in names if b[k]]


def _when_short(it):
    """Срок для колонки слева: «14:14», «пт 10:00», «21.10»."""
    import datetime as dt
    d = dt.datetime.fromtimestamp(it["due"])
    delta = (d.date() - dt.date.today()).days
    hm = "" if H.is_allday(it) else d.strftime("%H:%M")       # «только дата» — без времени
    if delta in (0, 1):
        return hm
    if 1 < delta < 7:
        return ("%s %s" % (H.RU_DOW[d.weekday()], hm)).strip()
    return d.strftime("%d.%m")


def _line(it, n, show_list, show_prio):
    when = (" " + _when_short(it)) if it["due"] else ""
    mark = PRIO_MARK[it["prio"] or 0] if show_prio else ""
    tag = " <i>· %s</i>" % esc(it["list"]) if show_list and it["list"] != H.DEFAULT_LIST else ""
    return "<code>%02d%s</code> %s%s%s%s" % (n, when, mark + " " if mark else "", esc(it["text"]),
                                            " ↻" if it["repeat"] else "", tag)


def console(c, note=None, pick=None, **change):
    """Пульт задач → (Html, кнопки). change — per/mode/arg (запоминаются в meta);
    note — строка ассистента вместо «Открыто N»; pick — "edit"/"del": вместо кнопок номера."""
    import datetime as dt
    v = view_get(c)
    v.update({k: x for k, x in change.items() if x is not None})
    H.meta_set(c, VIEW_KEY, json.dumps(v, ensure_ascii=False))
    its = H.items(c, v["arg"] or None, "open", "task")
    if v["arg"] and not its and not H.items(c, v["arg"], None, "task", 1):
        v["arg"] = ""                                   # такого списка нет — показываем всё
        H.meta_set(c, VIEW_KEY, json.dumps(v, ensure_ascii=False))
        its = H.items(c, None, "open", "task")
    if v["per"] == "today":
        end = int(dt.datetime.combine(dt.date.today() + dt.timedelta(days=1), dt.time(0)).timestamp())
        its = [i for i in its if i["due"] and i["due"] < end]
    if v["mode"] == "prio":
        ordered = order_open(its)
        groups = [(PRIO_HEAD[p], [i for i in ordered if (i["prio"] or 0) == p]) for p in (2, 1, 0)]
        groups = [g for g in groups if g[1]]
    else:
        groups = _buckets(its)
    now = dt.datetime.now()
    head = "ЗАДАЧИ" + (" · СЕГОДНЯ" if v["per"] == "today" else "") + (" · " + v["arg"].upper() if v["arg"] else "")
    out = ["<b>◆ %s · %s</b>" % (BRAND, esc(head)),
           "<code>%s %s · %s · %s</code>" % (now.strftime("%d.%m"), H.RU_DOW[now.weekday()],
                                            now.strftime("%H:%M"), "списком" if v["mode"] == "prio" else "общий")]
    over = sum(1 for i in its if H.overdue(i))
    if note:
        out.append("<i>%s</i>" % note)
    elif not its:
        out.append("<i>%s</i>" % ("На сегодня ничего, сэр." if v["per"] == "today" else "Пусто, сэр. Всё сделано."))
    else:
        out.append("<i>Открыто %d%s, сэр.</i>" % (len(its), (", просрочено %d" % over) if over else ""))
    ids = []
    for title, grp in groups:
        out.append("\n<b>%s</b>" % title)
        for it in grp:
            ids.append(it["id"])
            out.append(_line(it, len(ids), not v["arg"], v["mode"] != "prio"))
    H.meta_set(c, NUMS_KEY, json.dumps(ids))
    if pick and ids:
        out.append("\n<i>%s Нажмите номер.</i>" % ("Какую изменить?" if pick == "edit" else "Какую удалить?"))
        key = "k:o:%d" if pick == "edit" else "k:x:%d"
        nums = [btn(("%d" if pick == "edit" else "✗ %d") % (n + 1), key % iid) for n, iid in enumerate(ids[:48])]
        rows = [nums[i:i + 6] for i in range(0, len(nums), 6)]
        return Html("\n".join(out)), rows + [[btn("← Назад", "k:b")]]
    rows = [[btn("↻ Обновить", "k:r"),
             btn("☰ Все", "k:per:all") if v["per"] == "today" else btn("■ Сегодня", "k:per:today"),
             btn("◷ Общий", "k:mode:time") if v["mode"] == "prio" else btn("≡ Списком", "k:mode:prio")],
            [btn("＋ Добавить", "k:a")]]
    if ids:
        rows[1] += [btn("✎ Изменить", "k:pe"), btn("✗ Удалить", "k:pd")]
    return Html("\n".join(out)), rows


def card(c, iid, note=None, confirm_del=False):
    """Карточка пункта: срок, важность, повтор; кнопки — всё управление пунктом."""
    it = H.get_item(c, iid)
    if it is None or it["status"] != "open":
        return console(c, note="Этой задачи уже нет в открытых, сэр.")
    ids = _jget(c, NUMS_KEY, [])
    num = " %02d" % (ids.index(iid) + 1) if iid in ids else ""
    pr = it["prio"] or 0
    out = ["<b>◆ ЗАДАЧА%s</b>" % num, "<b>%s</b>" % esc(it["text"]), ""]
    over = H.overdue(it)
    out.append("<code>срок     </code> %s%s" % (H.when(it) if it["due"] else "без срока",
                                               " · просрочено" if over else ""))
    out.append("<code>важность </code> %s" % PRIO_BTN[pr])
    if it["repeat"]:
        out.append("<code>повтор   </code> %s" % REPEAT_RU.get(it["repeat"], it["repeat"]))
    if it["list"] != H.DEFAULT_LIST:
        out.append("<code>список   </code> %s" % esc(it["list"]))
    if confirm_del:
        out.append("\n<i>Удалить эту задачу, сэр?</i>")
        return Html("\n".join(out)), [[btn("✗ Да, удалить", "k:X:%d" % iid), btn("Отмена", "k:o:%d" % iid)]]
    if note:
        out.append("\n<i>%s</i>" % note)
    i = it["id"]
    rows = [[btn("✓ Сделано", "k:d:%d" % i), btn("✎ Текст", "k:t:%d" % i), btn("✗ Удалить", "k:x:%d" % i)],
            [btn(("● " if p == pr else "") + PRIO_BTN[p], "k:p:%d:%d" % (i, p)) for p in (2, 1, 0)],
            [btn("+1 ч", "k:u:%d:h" % i), btn("Вечер 19:00", "k:u:%d:eve" % i), btn("Завтра 9:00", "k:u:%d:tom" % i)],
            [btn("◷ Свой срок", "k:u:%d:ask" % i), btn("∅ Без срока", "k:u:%d:none" % i)],
            [btn("← К списку", "k:b")]]
    return Html("\n".join(out)), rows


def due_preset(key):
    import datetime as dt
    now = dt.datetime.now()
    if key == "h":
        return H.now() + 3600
    if key == "eve":
        d = dt.datetime.combine(now.date(), dt.time(19, 0))
        return int((d if d > now else d + dt.timedelta(days=1)).timestamp())
    if key == "tom":
        return tomorrow_9()
    return None


# ───────────────────────────── второй ключ ─────────────────────────────

# 15.10.2026, просьба: «даже если бот взломают никто не должен иметь доступ к моему пк, потом к
# whatsapp… я не всегда дома». Telegram не даёт боту ни устройство, ни IP — только ID, а он не
# спасёт, если украдут сам аккаунт. Поэтому ПК, охрана и WhatsApp просят код TOTP (tfa.py).
# Без кода можно только то, что делает безопаснее: запереть экран, погасить, включить охрану.
TFA_KEY = "tfa_pending"              # {"cmd": "/pc …" | None, "ts"} — ждём 6 цифр
TFA_TTL = 300
TFA_K = {"pr", "pa", "pv", "psh", "pq", "py", "pw", "pwq", "pwx",
         "gme", "glog", "gr", "goff", "gph", "grec", "gmic", "glis", "gst"}


def tfa_need(c, replay=None, scope=None):
    """None — можно; иначе (текст, кнопки): просьба прислать код. scope="pc" — недельное окно."""
    if tfa.is_open(scope):
        return None
    if tfa.blocked():
        return ("⛔ Удалённый доступ заперт после неверных кодов. Открыть — только с ноутбука: "
                "tfa unlock"), None
    H.meta_set(c, TFA_KEY, json.dumps({"cmd": replay, "ts": H.now()}))
    return tfa.PROMPT, [[btn("✕ Отмена", "k:tfx")]]


def tfa_gate_cb(c, bot, chat, cb_id, scope=None):
    """Для кнопок: True — нельзя (код уже спрошен)."""
    g = tfa_need(c, scope=scope)
    if g is None:
        return False
    bot.answer(cb_id, "Нужен код")
    bot.send(chat, *g)
    return True


def tfa_take(c, bot, chat, msg_id, text):
    """6 цифр в ответ на просьбу кода (или /code 123456). True — сообщение съедено."""
    if not tfa.looks_like_code(text):
        return False
    # 17.10.2026, просьба: «когда я пишу код… он записал это в задачи». Код пришёл без
    # просьбы (просьба старше 5 мин или Telegram прислал сообщение повторно после
    # перезапуска hub — offset пишется после обработки). 6 цифр задачей не бывают никогда.
    pend = _jget(c, TFA_KEY, None)
    if not (pend and H.now() - pend.get("ts", 0) < TFA_TTL):
        pend = {}
    try:
        bot.call("deleteMessage", {"chat_id": chat, "message_id": msg_id})   # код не хранить в чате
    except Exception:
        pass
    if not pend and tfa.is_open():
        bot.send(chat, "🔓 Доступ уже открыт — код не нужен, сэр.")
        return True
    ok, note = tfa.verify(text, "hub")
    if ok:
        H.meta_set(c, TFA_KEY, "null")
    bot.send(chat, note)
    if ok:
        if pend.get("cmd"):
            send_pc_result(bot, chat, reply_for_text(c, pend["cmd"], bot, chat))
        else:
            bot.send(chat, "Нажмите кнопку ещё раз, сэр.")
    elif tfa.blocked():
        H.meta_set(c, TFA_KEY, "null")
    return True


def wait_set(c, op, iid=None, chat=None, mid=None):
    H.meta_set(c, WAIT_KEY, json.dumps({"op": op, "id": iid, "chat": chat, "mid": mid, "ts": H.now()}))


def wait_pop(c):
    w = _jget(c, WAIT_KEY, None)
    if w:
        H.meta_set(c, WAIT_KEY, "null")
    return w if w and H.now() - w.get("ts", 0) < WAIT_TTL else None


def prompt(title, hint):
    return Html("<b>◆ %s</b>\n<i>%s</i>" % (title, hint)), [[btn("✕ Отмена", "k:c")]]


def wait_take(c, bot, chat, text):
    """Текст после кнопки «Добавить» / «Текст» / «Свой срок» / «Выключить будильник».
    Пульт переезжает вниз, под ответ: старое сообщение удаляется, новое — свежее."""
    w = wait_pop(c)
    if not w:
        return False
    if text.startswith("/"):
        return False                                    # команда — передумал, ожидание снято
    op, iid = w["op"], w.get("id")
    if op == "add":
        new, due = H.add_smart(c, text, "tg")
        it = H.get_item(c, new)
        res = console(c, note="✓ Записал, сэр: %s%s" % (esc(it["text"]), (" — " + H.fmt_when(due)) if due else ""))
    elif op == "text":
        clean, due, _ = H.parse_when(text)
        H.edit(c, iid, clean or text, due if due else "keep", source="tg")
        res = card(c, iid, note="✓ Переписал, сэр.")
    elif op == "due":
        _, due, _ = H.parse_when(text)
        if not due:
            wait_set(c, "due", iid, w.get("chat"), w.get("mid"))
            bot.send(chat, "Не понял срок, сэр. Например: «завтра в 18», «в пт 10:00», «через 2 часа».")
            return True
        H.edit(c, iid, None, due, source="tg")
        res = card(c, iid, note="✓ Новый срок: %s" % H.fmt_when(due))
    elif op == "alarm_off":
        res = alarm_panel("off " + text)
    elif op.startswith("wa_"):
        import hubwa
        res = tfa_need(c) or hubwa.tg_wait(c, op, iid, text)
        if res is None:
            return False
    elif op == "tadd":                                # «✎ Своё» у идущего таймера
        secs = H.parse_duration(text)
        if not secs or secs > 7 * 86400:
            wait_set(c, "tadd", iid, w.get("chat"), w.get("mid"))
            bot.send(chat, "Не понял время, сэр. Например: «7», «1 ч 20», «90 сек».")
            return True
        if timer_add(c, iid, secs) is None:
            bot.send(chat, "Таймер уже остановлен, сэр.")
            return True
        # Сообщение таймера переезжает вниз, под ответ, и остаётся под присмотром
        if w.get("mid"):
            c.execute("DELETE FROM tgmsgs WHERE chat=? AND mid=?", (w["chat"], w["mid"]))
        res = render(H.get_item(c, iid))
        res = ("✓ +%s, сэр.\n%s" % (H.fmt_secs(secs), res[0]), res[1])
        if w.get("mid"):
            try:
                bot.call("deleteMessage", {"chat_id": w["chat"], "message_id": w["mid"]})
            except Exception:
                pass
        r = bot.send(chat, *res)
        track(c, iid, chat, r["message_id"])
        c.execute("UPDATE tgmsgs SET sig=? WHERE chat=? AND mid=?",     # «✓ +…» не стирать сразу
                  (sig_of(H.get_item(c, iid)), chat, r["message_id"]))
        return True
    elif op == "tname":
        H.meta_set(c, TNAME_KEY, text.strip()[:60])
        res = timer_picker(c, iid or 0, note="✓ Название: %s" % esc(text.strip()[:60]))
    else:
        return False
    if w.get("mid"):
        try:
            bot.call("deleteMessage", {"chat_id": w["chat"], "message_id": w["mid"]})
        except Exception:
            pass
    bot.send(chat, *res)
    return True


def k_callback(c, bot, chat, mid, cb_id, rest):
    """Кнопки пульта: k:<действие>[:<id>[:<значение>]]."""
    a = rest.split(":")
    act = a[0]
    iid = int(a[1]) if len(a) > 1 and a[1].isdigit() else None
    toast, res = "", None
    if act in TFA_K and not (act == "pa" and len(a) > 1 and a[1] in ("lock", "dark")):
        if tfa_gate_cb(c, bot, chat, cb_id, "pc" if act[0] in "pg" else None):   # p* пульт ПК, g* охрана
            return
    if act == "r":
        res = console(c)
    elif act == "per":
        res = console(c, per=a[1])
    elif act == "mode":
        res = console(c, mode=a[1])
    elif act == "b":
        H.meta_set(c, WAIT_KEY, "null")
        res = console(c)
    elif act in ("pe", "pd"):
        res = console(c, pick="edit" if act == "pe" else "del")
    elif act == "a":
        wait_set(c, "add", None, chat, mid)
        res = prompt("НОВАЯ ЗАДАЧА", "Напишите задачу, сэр. Можно со сроком и списком:\n"
                     "«завтра в 10 позвонить», «Покупки: хлеб». Голосом тоже.")
    elif act == "c":
        H.meta_set(c, WAIT_KEY, "null")
        res = console(c, note="Отменено, сэр.")
    elif act == "o":
        res = card(c, iid)
    elif act == "d":
        it = H.get_item(c, iid)
        H.done(c, iid, "tg")
        it2 = H.get_item(c, iid)
        if it2 is not None and it2["repeat"] and it2["status"] == "open":
            res = console(c, note="✓ Отмечено, сэр. Следующий раз: %s" % H.when(it2))
        else:
            res = console(c, note="✓ Сделано, сэр: %s" % esc(it["text"] if it else ""))
        toast = "Готово"
    elif act == "t":
        it = H.get_item(c, iid)
        wait_set(c, "text", iid, chat, mid)
        res = prompt("ТЕКСТ ЗАДАЧИ", "Сейчас: «%s»\nПришлите новый текст, сэр. Срок в нём тоже поймаю."
                     % esc(it["text"] if it else ""))
    elif act == "x":
        res = card(c, iid, confirm_del=True)
    elif act == "X":
        it = H.get_item(c, iid)
        H.drop(c, iid, "tg")
        res = console(c, note="✗ Удалено, сэр: %s" % esc(it["text"] if it else ""))
        toast = "Удалено"
    elif act == "p":
        H.set_prio(c, iid, int(a[2]), "tg")
        res = card(c, iid, note="✓ Важность: %s" % PRIO_BTN[int(a[2])])
    elif act == "u":
        key = a[2]
        if key == "ask":
            wait_set(c, "due", iid, chat, mid)
            res = prompt("СРОК", "Когда, сэр? «завтра в 18», «в пт 10:00», «через 2 часа».")
        else:
            due = due_preset(key)
            H.edit(c, iid, None, due, source="tg")
            res = card(c, iid, note="✓ %s" % ("Новый срок: " + H.fmt_when(due) if due else "Срок снят."))
    elif act == "ts":                                   # таймеры: стоп все
        for it in H.items(c, None, "open", "timer"):
            H.drop(c, it["id"], "tg")
        res = timer_panel(c)
        toast = "Остановлено"
    elif act == "tr":
        res = timer_panel(c)
    elif act == "th":
        res = timer_history(c)
    elif act == "al":
        res = alarm_panel("")
    elif act == "aon":
        res = alarm_panel("on")
    elif act == "aoff":
        wait_set(c, "alarm_off", None, chat, mid)
        res = prompt("БУДИЛЬНИК · АВАРИЙНО",
                     "Почему, сэр? Одной фразой — уйдёт в журнал.\n"
                     "Будильник выключится до «Включить», Сторож — на сегодня, звонок замолчит.")
    elif act == "tc":
        res = timer_picker(c, iid or 0)
    elif act == "tn":
        wait_set(c, "tname", iid or 0, chat, mid)
        res = prompt("НАЗВАНИЕ ТАЙМЕРА", "Как назвать, сэр? Например: «чай», «стирка».")
    elif act == "tgo":
        name = H.meta_get(c, TNAME_KEY, "") or ""
        H.meta_set(c, TNAME_KEY, "")
        text, b2 = start_timer_reply(c, iid, name)
        r = bot.send(chat, text, b2)
        if r:
            track(c, _last_item, chat, r["message_id"])
        res = timer_panel(c, note="▶ Запущен: %s%s" % (_hm_dur(iid), (" · " + esc(name)) if name else ""))
        toast = "Таймер запущен"
    elif act == "pr":
        res = pc_panel(c)
    elif act == "pa":                                   # звук, экраны, замок — сразу
        text, _ = hubpc.run(a[1], "")
        H.log(c, "pc", None, a[1])
        if a[1] == "lock":
            for _ in range(10):
                import hubguard
                if hubguard.locked():
                    break
                time.sleep(0.3)
        res = pc_panel(c, "✓ " + text)
        toast = text[:190]
    elif act == "pv":
        d = hubpc.info()
        v = max(0, min(100, (d["vol"] or 0) + int(a[1])))
        text, _ = hubpc.run("vol", str(v))
        if d["muted"]:
            hubpc.run("unmute", "")
        res = pc_panel(c)
        toast = text
    elif act == "psh":
        bot.answer(cb_id, "Снимаю экран")
        send_pc_result(bot, chat, hubpc.run("shot", ""))
        return
    elif act == "pq":
        res = pc_panel(c, ask=a[1])
    elif act == "py":
        if a[1] not in PC_DANGER or H.now() - int(a[2]) > CONFIRM_TTL:
            res = pc_panel(c, "Подтверждение истекло, сэр.")
        else:
            bot.answer(cb_id, "Выполняю")
            bot.edit(chat, mid, *pc_panel(c, "%s — выполняю, сэр." % PC_DANGER[a[1]])[:1])
            H.log(c, "pc", None, a[1])
            hubpc.run(a[1], "")
            return
    elif act == "pw":
        res = pc_windows(c)
    elif act == "pwq":
        res = pc_windows(c, ask=iid)
    elif act == "pwx":
        text = hubpc.close_id(iid)
        H.log(c, "pc", None, "close %d" % iid)
        time.sleep(0.5)
        res = pc_windows(c, "✓ " + esc(text))
    elif act == "gme":                                  # «Это я» под «экран разблокирован»
        _away_set(c, False)
        bot.answer(cb_id, "Охрана выключена")
        bot.call("editMessageReplyMarkup", {"chat_id": chat, "message_id": mid,
                                            "reply_markup": {"inline_keyboard": []}})
        bot.send(chat, *away_panel(c, "Охрана выключена. С возвращением, сэр."))
        return
    elif act == "glog":
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard-log",
                            time.strftime("%Y-%m-%d") + ".log")
        if os.path.exists(path) and os.path.getsize(path):
            bot.answer(cb_id, "Отправляю журнал")
            bot.call("sendDocument", {"chat_id": chat, "caption": "📜 Журнал охраны за сегодня"},
                     {"document": path})
            return
        toast = "Сегодня журнал пуст"
        res = away_panel(c, "Сегодня журнал охраны пуст, сэр.")
    elif act in ("gr", "gon", "gonl", "goff", "glk", "gph", "grec", "gmic", "glis", "gst"):
        note = None
        secs = int(a[1]) if len(a) > 1 and a[1].isdigit() else None
        if act == "gon":
            _away_set(c, True)
            note, toast = "Охрана включена, сэр.", "Охрана включена"
        elif act == "gonl":
            ok = _lock_screen()
            _away_set(c, True)
            note = ("Экран заперт, охрана включена. Хорошей дороги, сэр." if ok else
                    "Охрана включена, но экран запереть не удалось, сэр.")
            toast = "Охрана включена"
        elif act == "goff":
            _away_set(c, False)
            note, toast = "Охрана выключена. С возвращением, сэр.", "Выключено"
        elif act == "glk":
            note = "🔒 Экран заперт." if _lock_screen() else "Запереть экран не удалось, сэр."
        elif act != "gr":
            note = {"gph": _away_photo, "grec": lambda: _away_rec(secs or 10),
                    "gmic": lambda: _away_mic(secs or 30), "glis": lambda: _away_listen(secs or 300),
                    "gst": _away_stop}[act]()
            toast = note[:190]
        res = away_panel(c, note)
    elif act == "wq":
        bot.answer(cb_id)
        bot.send(chat, *quiz_next(c, 5))
        return
    elif act == "wl":
        res = words_panel(c, full=True)
    bot.answer(cb_id, toast)
    if res:
        bot.edit(chat, mid, *res)


def timer_panel(c, note=None):
    its = H.items(c, None, "open", "timer")
    out = ["<b>◆ %s · ТАЙМЕРЫ</b>" % BRAND]
    if note:
        out.append("<i>%s</i>" % note)
    for i in its:
        out.append("<code>⏱ до %s</code> %s <i>· осталось %s%s</i>" % (
            hm(i["due"]), esc(i["text"]), H.fmt_secs(max(0, i["due"] - H.now())), bare(i)))
    if not its and not note:
        out.append("<i>Сейчас ни один не идёт, сэр.</i>")
    out.append("\n<i>Нажмите длительность или напишите «25 чай».</i>")
    rows = timer_presets()
    rows.append([btn("⏱ Свой таймер", "k:tc:0")])
    rows.append([btn("↻ Обновить", "k:tr"), btn("📜 История", "k:th")] +
                ([btn("■ Стоп все", "k:ts")] if its else []))
    return Html("\n".join(out)), rows


# 21.10.2026, просьба: «не хватает кнопки История — последние 5 таймеров, если я не замечу
# какой-то таймер или он пропадёт… где и когда он был выключен». Всё берётся из events
# (add/drop/done/snooze с источником), сам таймер — из items.
T_FROM = {"island": "с островка", "widget": "с виджета", "tg": "из Telegram", "pc": "с ПК", "clocker": "из Clocker",
          "cli": "командой"}
T_BY = {"island": "на островке", "widget": "виджетом", "tg": "в Telegram", "clocker": "в Clocker",
        "pc": "на ПК", "cli": "командой"}
# виджет timer.exe на рабочем столе (таймеру из Telegram он создаётся сам) пишет, чем остановлен
T_CLOCKER = {"pause": "паузой в Clocker", "delete": "удалением в Clocker"}
T_WIDGET = {"click": "щелчком по виджету timer.exe", "close": "крестиком виджета timer.exe",
            "pause": "паузой в виджете timer.exe", "replay": "повтором (REPLAY) в виджете timer.exe",
            "new": "новым таймером (NEW) в виджете timer.exe"}


def _t_by(data):
    src, _sp, how = (data or "").partition(" ")
    if src == "widget":
        return T_WIDGET.get(how, "виджетом timer.exe на рабочем столе")
    if src == "clocker" and how:
        return T_CLOCKER.get(how, T_BY["clocker"])
    return T_BY.get(src, src)


def _t_day(ts):
    import datetime as dt
    d = dt.date.fromtimestamp(ts)
    td = dt.date.today()
    return "сегодня" if d == td else "вчера" if d == td - dt.timedelta(days=1) else d.strftime("%d.%m")


def timer_history(c, n=5):
    its = c.execute("SELECT * FROM items WHERE kind='timer' ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    out = ["<b>◆ %s · ТАЙМЕРЫ · ИСТОРИЯ</b>" % BRAND]
    if not its:
        out.append("<i>Таймеров ещё не было, сэр.</i>")
    t = H.now()
    for it in its:
        ev = c.execute("SELECT kind, data, ts FROM events WHERE item_id=? ORDER BY id", (it["id"],)).fetchall()
        add = next((e for e in ev if e["kind"] == "add"), None)
        start = add["ts"] if add else it["created"]
        src = (add["data"] if add else it["source"]) or ""
        due = it["due"] or start
        snz = sum(1 for e in ev if e["kind"] == "snooze")
        out.append("\n⏱ <b>%s</b> — %s" % (esc(it["text"]), _t_day(start)))
        out.append("<code>%s → %s</code> · %s%s%s" % (hm(start), hm(due), T_FROM.get(src, src),
                                                     " · отложен ×%d" % snz if snz else "", bare(it)))
        end = next((e for e in reversed(ev) if e["kind"] in ("drop", "done")), None)
        if it["status"] == "open":
            out.append("▶ идёт, осталось %s" % H.fmt_secs(due - t) if due > t else
                       "🔔 <b>звенит с %s, не остановлен</b>" % hm(due))
        elif end:
            by = _t_by(end["data"])
            if end["ts"] >= due:
                late = end["ts"] - due
                out.append("■ прозвенел в %s, остановлен в %s %s%s" % (
                    hm(due), hm(end["ts"]), by, ", спустя %s" % H.fmt_secs(late) if late >= 60 else ""))
            else:
                out.append("■ остановлен заранее в %s %s, оставалось %s" % (
                    hm(end["ts"]), by, H.fmt_secs(due - end["ts"])))
        else:
            out.append("■ остановлен (когда — в журнале нет)")
    return Html("\n".join(out)), [[btn("« Таймеры", "k:tr"), btn("↻ Обновить", "k:th")]]


# 14.10.2026, просьба: «добавь кнопку Свой таймер, и там будет интерфейс выбора времени».
# Время живёт в самих кнопках (k:tc:СЕКУНДЫ), название — в meta tg_tname до запуска.
TNAME_KEY = "tg_tname"
TIMER_MAX = 24 * 3600


def _hm_dur(secs):
    h, m = secs // 3600, secs % 3600 // 60
    return ("%d ч %02d мин" % (h, m)) if h else "%d мин" % m


def timer_picker(c, secs, note=None):
    secs = max(0, min(TIMER_MAX, secs))
    name = H.meta_get(c, TNAME_KEY, "") or ""
    out = ["<b>◆ %s · СВОЙ ТАЙМЕР</b>" % BRAND,
           "<code>⏱ %s</code>" % (_hm_dur(secs) if secs else "0 мин"),
           "<code>название: %s</code>" % (esc(name) if name else "—")]
    if note:
        out.append("<i>%s</i>" % note)
    out.append("\n<i>Наберите время кнопками, сэр.</i>")

    def step(d, label):
        return btn(label, "k:tc:%d" % max(0, min(TIMER_MAX, secs + d)))
    rows = [[step(3600, "+1ч"), step(600, "+10м"), step(300, "+5м"), step(60, "+1м")],
            [step(-3600, "−1ч"), step(-600, "−10м"), step(-300, "−5м"), step(-60, "−1м")],
            [btn("✎ Название", "k:tn:%d" % secs), btn("✕ Сброс", "k:tc:0")]]
    if secs:
        rows.append([btn("▶ Запустить · %s" % _hm_dur(secs), "k:tgo:%d" % secs)])
    rows.append([btn("← Таймеры", "k:tr")])
    return Html("\n".join(out)), rows


def words_panel(c, query=None, full=False):
    st = H.word_stats(c)
    out = ["<b>◆ %s · СЛОВАРЬ</b>" % BRAND,
           "<code>слов %d · к повтору %d · выучено %d</code>" % (st["total"], st["due"], st["known"])]
    if full or query:
        ws = H.words(c, query or None, 30)
        out.append("")
        out += ["<code>#%-3d</code> %s — %s" % (w["id"], esc(w["term"]), esc(w["translation"])) for w in ws]
        if not ws:
            out.append("<i>Ничего не нашёл, сэр.</i>")
    out.append("\n<i>Добавить: /w cat = кот · удалить: /delword 7</i>")
    rows = [[btn("▶ Повторить", "k:wq"), btn("☰ Список", "k:wl")]]
    return Html("\n".join(out)), rows


def _alarm_run(argv):
    try:
        r = subprocess.run([sys.executable, WAKE] + argv, capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def alarm_panel(arg):
    """Будильник пультом (14.10.2026, просьба «оформи красиво, с кнопками»).
    Разбирает вывод wake_alarm.py status; сам будильник не трогает, кроме on/off аварийно."""
    import datetime as dt
    import re
    a = arg.split(None, 1)
    sub = a[0].lower() if a else ""
    note = None
    if sub in ("off", "выкл"):
        reason = a[1].strip() if len(a) > 1 else ""
        if len(reason) < 3:
            note = "Нужна причина, сэр: /alarm off ночую у родителей — или кнопка ниже."
        else:
            rc, out = _alarm_run(["emergency", "off", "--reason", reason, "--via", "tg"])
            note = ("Будильник выключен, Сторож снят на сегодня, сэр." if rc == 0
                    else "Не вышло, сэр: " + esc(out))
    elif sub in ("on", "вкл"):
        rc, out = _alarm_run(["emergency", "on", "--via", "tg"])
        note = "Будильник включён, Сторож снова на посту, сэр." if rc == 0 else "Не вышло, сэр: " + esc(out)
    elif sub not in ("", "status"):
        note = "Не понял, сэр. /alarm off ПРИЧИНА · /alarm on"
    rc, out = _alarm_run(["status"])
    if rc:
        return Html("<b>◆ " + BRAND + " · БУДИЛЬНИК</b>\n<i>Не вышло прочитать, сэр:</i>\n<code>%s</code>" % esc(out)), \
            [[btn("↻ Обновить", "k:al")]]
    lines = out.splitlines()
    on = any(l.startswith("будильник:") and "включён" in l for l in lines)
    deflt = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("по умолчанию:")), "")
    today = dt.date.today()

    def day_word(d):
        k = (d - today).days
        return "сегодня" if k == 0 else "завтра" if k == 1 else "%s %s" % (H.RU_DOW[d.weekday()], d.strftime("%d.%m"))

    def to_date(dd, mm):
        d = dt.date(today.year, int(mm), int(dd))
        return d.replace(year=d.year + 1) if (today - d).days > 180 else d

    nxt = next((l for l in lines if l.startswith("ближайший звонок:")), "")
    m = re.search(r"(\d\d)\.(\d\d) (\d\d:\d\d)", nxt)
    every = ""
    plan = []
    for l in lines:
        p = re.match(r"^\s+(\d\d)\.(\d\d) \S+\s+(\S+)\s+(.*)$", l)
        if not p:
            continue
        d = to_date(p.group(1), p.group(2))
        w = re.match(r"Сторож (\S+)–(\S+), каждые (\d+) мин(.*)", p.group(4))
        if w:
            every = w.group(3)
        label = "%s %s" % (H.RU_DOW[d.weekday()], d.strftime("%d.%m"))
        plan.append("<code>%s  %-5s</code> %s" % (
            label, p.group(3), ("⛨ Сторож до %s%s" % (w.group(2), " · на дату" if w.group(4).strip() else ""))
            if w else "<i>без Сторожа</i>"))
    out = ["<b>◆ %s · БУДИЛЬНИК</b>" % BRAND,
           "<code>%s%s</code>" % ("● ВКЛЮЧЁН" if on else "○ ВЫКЛЮЧЕН", " · по умолч. " + deflt if deflt else "")]
    if note:
        out.append("<i>%s</i>" % note)
    elif m:
        out.append("<i>Ближайший звонок — %s, %s, сэр.</i>" % (day_word(to_date(m.group(1), m.group(2))), m.group(3)))
    else:
        out.append("<i>Звонков впереди нет, сэр.</i>")
    if plan:
        out += ["\n<b>■ ПЛАН</b>"] + plan
    if every:
        out.append("\n<i>Сторож: после звонка проверки «не спите?» каждые %s мин.</i>" % every)
    rows = [[btn("↻ Обновить", "k:al"),
             btn("⏻ Аварийно выключить", "k:aoff") if on else btn("⏻ Включить", "k:aon")]]
    return Html("\n".join(out)), rows


def item_ref(c, s):
    """Номер из последнего списка (/ls, /today) → id пункта; «#74» — сам id.
    Нет списка или номер вне его — None."""
    s = (s or "").strip()
    if s.startswith("#"):
        return parse_id(s)
    if not s.isdigit():
        return None
    try:
        ids = json.loads(H.meta_get(c, NUMS_KEY) or "[]")
    except ValueError:
        ids = []
    n = int(s)
    return ids[n - 1] if 1 <= n <= len(ids) else None


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
        return (HELP_ALL if arg.strip().lower() in ("all", "все", "всё") else HELP_TEXT), None
    if cmd in ("tasks", "ls", "l", "reminders"):
        return console(c, per="all", arg=arg)
    if cmd == "today":
        return console(c, per="today", arg="")
    if cmd == "lists":
        ls = [l for l in H.lists(c) if l["open"] > 0]
        return "\n".join("%s — %d" % (l["name"], l["open"]) for l in ls) or "Открытых пунктов нигде нет.", None
    if cmd in ("add", "a"):
        if not arg:
            return "Что записать? /add текст", None
        return reply_for_text(c, arg)
    if cmd in ("done", "d"):
        iid = item_ref(c, arg)
        if iid is None:
            return "Номер пункта из списка /ls: /done 3", None
        ok = H.done(c, iid, "tg")
        return ("Готово, сэр." if ok else "Не нашёл открытый пункт №%s." % iid), None
    if cmd in ("snooze", "s"):
        a = arg.split(None, 1)
        iid = item_ref(c, a[0]) if a else None
        secs = H.parse_duration(a[1]) if len(a) > 1 else 3600
        if iid is None or not secs:
            return "Пример: /snooze 3 30м", None
        ok = H.snooze(c, iid, secs, source="tg")
        return ("Отложил на %s." % H.fmt_secs(secs) if ok else "Не нашёл пункт."), None
    if cmd in ("del", "rm"):
        iid = item_ref(c, arg)
        return ("Удалил." if iid is not None and H.drop(c, iid, "tg") else "Не нашёл пункт."), None
    if cmd == "edit":
        a = arg.split(None, 1)
        iid = item_ref(c, a[0]) if a else None
        if iid is None or len(a) < 2:
            return "Пример: /edit 3 новый текст", None
        cur = H.get_item(c, iid)
        if cur is None or cur["status"] == "dropped":
            return "Не нашёл пункт.", None
        clean, due, _ = H.parse_when(a[1])
        ok = H.edit(c, iid, clean or a[1], due if due else "keep", source="tg")
        return ("Исправил." if ok else "Не нашёл пункт."), None
    if cmd in ("t", "timer", "timers"):
        if not arg:
            return timer_panel(c)
        a = arg.split(None, 1)
        d = H.parse_duration(a[0])
        if not d:
            return "Не понял время. Пример: /timer 25 чай, /timer 1ч30", None
        return start_timer_reply(c, d, a[1] if len(a) > 1 else "")
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
        return words_panel(c, arg, full=True)   # список сразу (20.10.2026, просьба: «вбив /words, сразу не вижу список»)
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
    if cmd in ("code", "unlock", "код"):
        if not tfa.enabled():
            return tfa.NOT_SET, None
        ok, note = tfa.verify(arg, "hub")
        return note, None
    if cmd in ("lock", "закрыть"):
        tfa.close()
        H.meta_set(c, TFA_KEY, "null")
        return "🔒 Удалённый доступ закрыт. Открыть — /code и 6 цифр.", None
    if cmd in ("pc", "wa", "log") or (cmd == "away" and arg.lower().split()[:1] not in (["on"], ["вкл"], ["1"])):
        # 17.10.2026, просьба: /away — как /pc, код раз в неделю
        g = tfa_need(c, "/%s %s" % (cmd, arg), "pc" if cmd in ("pc", "away", "log") else None)
        if g:
            return g
    if cmd == "wa":
        import hubwa
        return hubwa.tg_command(c, arg)
    if cmd == "pc":
        return pc_command(c, arg)
    if cmd == "alarm":
        return alarm_panel(arg)
    if cmd == "log":
        return log_file(c, arg)
    if cmd == "away":
        a = arg.lower().split()
        sub = a[0] if a else ""
        secs = int(a[1]) if len(a) > 1 and a[1].isdigit() else None
        if sub in ("on", "вкл", "1"):
            _away_set(c, True)
            return away_panel(c, "Охрана включена, сэр.")
        if sub in ("off", "выкл", "0"):
            _away_set(c, False)
            return away_panel(c, "Охрана выключена. С возвращением, сэр.")
        if sub == "photo":
            return away_panel(c, _away_photo())
        if sub == "rec":
            return away_panel(c, _away_rec(secs or 10))
        if sub == "mic":
            return away_panel(c, _away_mic(secs or 30))
        if sub == "listen":
            return away_panel(c, _away_listen(secs or 300))
        if sub == "stop":
            return away_panel(c, _away_stop())
        return away_panel(c)
    if cmd == "stop":
        n = 0
        for it in H.items(c, None, "open", "timer"):
            n += H.drop(c, it["id"], "tg")
        return ("Остановлено таймеров: %d." % n) if n else "Таймеров нет.", None
    return "Не знаю такой команды. /help", None


def log_file(c, arg=""):
    """/log [дней] — журнал хаба файлом: сон и пробуждения (плановые тоже), что сработало,
    действия с задачами, WhatsApp, охрана (21.10.2026). Старше 14 дней журнал стирает сам."""
    a = arg.strip().split()
    days = max(1, min(H.JOURNAL_DAYS, int(a[0]))) if a and a[0].isdigit() else H.JOURNAL_DAYS
    text, summary = H.log_report(c, days, os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard-log"))
    d = tempfile.mkdtemp(prefix="hub-log-")
    path = os.path.join(d, "hub-log-%s.txt" % time.strftime("%Y-%m-%d_%H%M"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return "📜 " + summary, {"document": path}


# ───────────────────────────── квиз ─────────────────────────────

def quiz_next(c, left):
    ws = H.due_words(c, 1)
    if not ws:
        return "Повторять нечего, сэр.", None
    w = ws[0]
    return ("Слово: %s\n(осталось в серии: %d)" % (w["term"], left),
            [[{"text": "Показать перевод", "callback_data": "q:%d:%d" % (w["id"], left)}]])


# ───────────────────────────── ПК ─────────────────────────────

# 14.10.2026, просьба: «/pc оформи тоже красиво». Панель как у охраны: сверху состояние,
# ниже кнопки группами. Подтверждение — только сон/перезагрузка/выключение и закрытие окна,
# прямо в панели (k:py…, 60 с). Запереть и погасить экраны — сразу: кнопка подписана ясно.
# Текстовые /pc vol 40, /pc close N, /pc shot работают как раньше.
PC_DANGER = {"sleep": "⏾ Сон", "reboot": "⟳ Перезагрузка", "off": "⏻ Выключение"}


def _dur(sec):
    h, m = int(sec // 3600), int(sec % 3600 // 60)
    return ("%dд %dч" % (h // 24, h % 24)) if h >= 24 else ("%dч %02dм" % (h, m) if h else "%dм" % m)


def pc_panel(c, note=None, ask=None):
    import hubguard
    d = hubpc.info()
    lk = hubguard.locked()
    out = ["<b>◆ %s · ПК</b>" % BRAND,
           "<code>● в сети %s · экран %s</code>" % (_dur(d["up"]), "🔒 заперт" if lk else "🔓 открыт"),
           "<code>экраны %s</code>" % {"on": "🌕 включены", "off": "🌑 выключены",
                                       "dim": "🌗 приглушены (простой)"}.get(d["screens"], d["screens"])]
    bat = ""
    if d["bat"] is not None:
        bat = " · 🔋 %d%%%s" % (d["bat"], " ⚡" if d["charging"] else "")
    out.append("<code>память %.1f/%.0f ГиБ · нагрузка %.1f%s</code>" % (d["mem_used"], d["mem_total"], d["load"], bat))
    vol = "—" if d["vol"] is None else ("🔇 выкл" if d["muted"] else "🔊 %d%%" % d["vol"])
    out.append("<code>звук %s · окон %d · в фокусе %s</code>" % (vol, len(d["windows"]), esc(d["focus"])))
    if note:
        out.append("<i>%s</i>" % note)
    if ask:
        out.append("\n<b>%s — точно, сэр?</b> Подтвердите в течение минуты." % PC_DANGER[ask])
        return Html("\n".join(out)), [[btn("Да, %s" % PC_DANGER[ask].split(" ", 1)[1].lower(),
                                           "k:py:%s:%d" % (ask, H.now())), btn("✕ Отмена", "k:pr")]]
    rows = [[btn("🖥 Скрин", "k:psh"), btn("▣ Окна", "k:pw"), btn("↻ Обновить", "k:pr")],
            [btn("🔊 Включить звук", "k:pa:unmute") if d["muted"] else btn("🔇 Без звука", "k:pa:mute"),
             btn("− 10", "k:pv:-10"), btn("+ 10", "k:pv:10")],
            # 17.10.2026: видна одна кнопка — по состоянию экранов
            [btn("🌑 Погасить экраны", "k:pa:dark") if d["screens"] == "on"
             else btn("🌕 Включить экраны", "k:pa:light")],
            ([] if lk else [btn("🔒 Экран блокировки", "k:pa:lock")]) + [btn("🛡 Охрана", "k:gr")],
            [btn("⏾ Сон", "k:pq:sleep"), btn("⟳ Перезагрузка", "k:pq:reboot"), btn("⏻ Выключить", "k:pq:off")]]
    return Html("\n".join(out)), rows


def pc_windows(c, note=None, ask=None):
    ws = hubpc.windows()
    out = ["<b>◆ %s · ОКНА</b>" % BRAND, "<code>открыто %d</code>" % len(ws)]
    if note:
        out.append("<i>%s</i>" % note)
    out.append("")
    for i, w in enumerate(ws[:30], 1):
        title = (w.get("title") or "").strip()
        if len(title) > 40:
            title = title[:39] + "…"
        out.append("<code>%02d</code> %s%s <i>%s</i>" % (
            i, "▶ " if w.get("is_focused") else "", esc(w.get("app_id") or "?"), esc(title)))
    if ask is not None:
        w = next((x for x in ws if x["id"] == ask), None)
        if w:
            out.append("\n<b>Закрыть %s — точно, сэр?</b> Несохранённое пропадёт." % esc(w.get("app_id") or "?"))
            return Html("\n".join(out)), [[btn("✕ Закрыть", "k:pwx:%d" % ask), btn("← Назад", "k:pw")]]
    out.append("\n<i>Нажмите номер, чтобы закрыть окно.</i>")
    nums = [btn("✕ %02d" % i, "k:pwq:%d" % w["id"]) for i, w in enumerate(ws[:30], 1)]
    rows = [nums[i:i + 5] for i in range(0, len(nums), 5)]
    rows.append([btn("↻ Обновить", "k:pw"), btn("← ПК", "k:pr")])
    return Html("\n".join(out)), rows


def pc_command(c, arg):
    a = arg.split(None, 1)
    if not a or a[0].lower() == "status":
        return pc_panel(c)
    if a[0].lower() in ("apps", "windows", "окна"):
        return pc_windows(c)
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
    if data == "k:tfx":
        H.meta_set(c, TFA_KEY, "null")
        bot.answer(cb_id, "Отменено")
        bot.edit(chat, mid, "Отменено.")
        return
    if k in ("w", "p", "pc") and tfa_gate_cb(c, bot, chat, cb_id, None if k == "w" else "pc"):
        return
    if k == "n":
        bot.answer(cb_id, "Отменено")
        bot.edit(chat, mid, "Отменено.")
        return
    if k == "k":                                    # пульт задач, таймеров, будильника
        k_callback(c, bot, chat, mid, cb_id, rest)
        return
    if k == "w":                                    # WhatsApp: /wa
        if tfa_gate_cb(c, bot, chat, cb_id):        # 15.10: старые кнопки пульта — тоже только с кодом
            return
        import hubwa
        hubwa.tg_callback(c, bot, chat, mid, cb_id, rest)
        return
    if k == "v":                                    # старые кнопки пульта (до 14.10 вечера)
        k_callback(c, bot, chat, mid, cb_id, "r")
        return
    if k in ("ta", "tr", "tp", "tc"):                # кнопки идущего таймера (21.10.2026)
        iid, _, v = rest.partition(":")
        iid = int(iid)
        # Взять под присмотр, только если ещё не: track() обнуляет sig, и следующий тик демона
        # (sync_messages) перерисовывал сообщение — меню «Добавить» мигало и пропадало (21.10.2026)
        it = H.get_item(c, iid)
        if chat and mid and not c.execute("SELECT 1 FROM tgmsgs WHERE chat=? AND mid=?", (chat, mid)).fetchone():
            track(c, iid, chat, mid)
            if it is not None:                          # и сразу с подписью — тик не перерисует
                c.execute("UPDATE tgmsgs SET sig=? WHERE chat=? AND mid=?", (sig_of(it) + (
                    "|over" if it["due"] and it["due"] <= H.now() else ""), chat, mid))
        if k == "tp":
            due = timer_add(c, iid, int(v))
            bot.answer(cb_id, "+%s · до %s" % (H.fmt_secs(int(v)), hm(due)) if due else "Таймер уже остановлен")
            sync_messages(c, bot)                       # срок сменился — сообщение перерисует само
            return
        elif k == "ta":
            bot.answer(cb_id)
            if it is not None and it["status"] == "open":
                text, _ = render(it)
                bot.edit(chat, mid, text + "\n\nСколько добавить, сэр?", timer_add_menu(iid))
                return
        elif k == "tc":
            bot.answer(cb_id)
            if it is not None and it["status"] == "open":
                wait_set(c, "tadd", iid, chat, mid)
                bot.edit(chat, mid, "⏱ %s — сколько добавить?\nНапишите: «7», «1 ч 20», «90 сек»." % it["text"],
                         [[{"text": "← Назад", "callback_data": "tr:%d" % iid}]])
                return
        if k == "tr":
            w = _jget(c, WAIT_KEY, None)
            if w and w.get("op") == "tadd" and w.get("id") == iid:   # «← Назад» из «Своё»
                H.meta_set(c, WAIT_KEY, "null")
            if data.startswith("tr:"):
                bot.answer(cb_id, ("осталось " + H.fmt_secs(it["due"] - H.now()))
                           if it is not None and it["status"] == "open" and it["due"] > H.now() else "")
            text, b = render(it)
            bot.edit(chat, mid, text, b)
        return
    if k in ("d", "s", "x") and chat and mid:
        track(c, int(rest.split(":")[0]), chat, mid)     # осиротевшее сообщение снова под присмотром
    if k == "d":
        H.done(c, int(rest), "tg")
        it = H.get_item(c, int(rest))
        if it is not None and it["repeat"] and it["status"] == "open":
            bot.answer(cb_id, "Отмечено. Следующий раз: %s" % H.when(it))
        else:
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
        it = H.get_item(c, int(rest))
        H.drop(c, int(rest), "tg")
        bot.answer(cb_id, "Цикл закрыт" if it is not None and it["repeat"] else "Остановлено")
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
    if isinstance(extra, dict) and extra.get("document"):     # /log — файлом
        path = extra["document"]
        try:
            return bot.call("sendDocument", {"chat_id": chat, "caption": text[:1000]}, {"document": path})
        finally:
            os.unlink(path)
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
    if tfa_take(c, bot, chat, m.get("message_id"), text):
        return
    if text.split(None, 1)[0].split("@")[0].lower() in ("/code", "/unlock", "/код"):
        try:
            bot.call("deleteMessage", {"chat_id": chat, "message_id": m.get("message_id")})
        except Exception:
            pass
    elif not tfa.enabled() and H.meta_get(c, "tfa_warn_day") != time.strftime("%F"):
        H.meta_set(c, "tfa_warn_day", time.strftime("%F"))
        bot.send(chat, tfa.NOT_SET)
    code = wake_code(text)
    if code:
        bot.send(chat, code)
        return
    try:
        if wait_take(c, bot, chat, text):
            return
    except Exception as e:
        bot.send(chat, "Ошибка: %s" % e)
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
        with bot.open(urllib.request.Request(bot.base.replace("/bot", "/file/bot") + info["file_path"]), 60) as r, \
                open(ogg, "wb") as f:
            f.write(r.read())
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
    try:                                            # меню команд — коротко, см. MENU
        bot.call("setMyCommands", {"commands": [{"command": k, "description": d} for k, d in MENU]})
    except Exception:
        pass
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
                m = bot.send(ch, Html(p["text"]) if p.get("html") else p["text"], p.get("buttons"))
                if p.get("item") and m:
                    track(c, p["item"], ch, m["message_id"])
            c.execute("UPDATE outbox SET sent_at=? WHERE id=?", (H.now(), r["id"]))
        except Exception:
            c.execute("UPDATE outbox SET tries=tries+1 WHERE id=?", (r["id"],))
            break


def enqueue(c, text, buttons=None, item=None, html=False):
    c.execute("INSERT INTO outbox(created,payload) VALUES(?,?)",
              (H.now(), json.dumps({"text": text, "buttons": buttons, "item": item, "html": html},
                                   ensure_ascii=False)))
