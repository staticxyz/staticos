#!/usr/bin/env python3
"""wa — отложенные сообщения WhatsApp из терминала (15.10.2026). Те же записи, что в окне
(wa app) и в Telegram (/wa); отправляет hubd в срок.

    wa                       очередь: что и когда уйдёт
    wa new                   новое: контакт (fzf), текст, когда — по шагам
    wa add КОМУ КОГДА ТЕКСТ  одной строкой: wa add мама "завтра в 9" "Доброе утро"
    wa list [all]            очередь (all — и отправленные/отменённые)
    wa history [N]           журнал: отправленные и отменённые (по умолчанию 30)
    wa clear                 очистить журнал насовсем (спросит y/n; очередь не трогает)
    wa stop                  остановить все запланированные (спросит y/n)
    wa resume                вернуть всё, что остановил последний stop
    wa show N                сообщение #N целиком
    wa time N КОГДА          перенести      wa text N ТЕКСТ   переписать
    wa now N                 отправить сейчас
    wa later N [минут]       отложить (по умолчанию на 60 мин)
    wa cancel N              отменить       wa back N         вернуть отменённое
    wa who [что]             найти контакт
    wa app                   окно
    wa lock                  забыть пароль сейчас (иначе помнится 15 минут)
  отправщик:  wa login [+номер] · wa status · wa ping · wa contacts · wa send КОМУ ТЕКСТ

КОГДА: «завтра в 9», «пт 18:30», «16.10 10:00», «через 2 часа», «в 20». ТЕКСТ «-» — из stdin.
Опоздало до часа (ноутбук спал) — уйдёт само; больше часа — hub спросит.
Вход — по паролю sudo, один раз на 15 минут (общий с окном).
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hub_auth  # noqa: E402
import hublib as H  # noqa: E402
import hubwa as W  # noqa: E402

RAW = ("login", "status", "contacts", "send", "ping")
B, D, R, G, Y, X = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"
if not sys.stdout.isatty():
    B = D = R = G = Y = X = ""
MARK = {"pending": "◷", "sending": "…", "ask": R + "⚠" + X, "sent": G + "✓" + X, "cancelled": D + "✕" + X}


def die(msg, code=1):
    print(R + msg + X, file=sys.stderr)
    sys.exit(code)


def line(m):
    ts = m["sent_at"] if m["status"] == "sent" else m["due"]
    s = "%s %s#%-3d%s %s%s%s · %s\n      %s%s%s" % (
        MARK.get(m["status"], "?"), D, m["id"], X, B, m["name"], X, W.when(ts), D, W.short(m["text"], 70), X)
    if m["status"] == "ask" or (m["status"] == "pending" and m["error"]):
        s += "\n      %s%s%s" % (Y, m["error"], X)
    return s


def show_list(c, full=False):
    rows = W.queue(c)
    if not W.linked():
        print(Y + "WhatsApp не привязан: wa login" + X)
    print(B + "Очередь" + X if rows else D + "Ничего не запланировано. wa new — новое." + X)
    for m in rows:
        print(line(m))
    if full:
        h = W.history(c, 20)
        if h:
            print("\n" + B + "История" + X)
            for m in h:
                print(line(m))


def need(c, n):
    try:
        m = W.get(c, int(n.lstrip("#")))
    except ValueError:
        m = None
    if m is None:
        die("нет сообщения #%s (wa list)" % n)
    return m


def pick(q=""):
    """Контакт: одно совпадение — сразу; иначе fzf (нет fzf — номером из списка)."""
    if q.casefold() in ("me", "я", "мне", "себе"):
        code, st = W.run_wa("status")
        if code or not isinstance(st, dict) or not st.get("jid"):
            die("WhatsApp не привязан: wa login", 3)
        me = st["jid"].split(":")[0]
        return {"jid": me + "@s.whatsapp.net", "name": "себе", "phone": "+" + me}
    allc = W.contacts(force=True)
    if not allc and not W.linked():
        die("WhatsApp не привязан: wa login", 3)
    ph = W.phone_of(q) if q else None
    if ph:
        x = next((c for c in allc if c["phone"] == ph), None)
        return x or {"jid": ph, "name": ph, "phone": ph}
    if q:
        found = W.search(q, 50)
        if len(found) == 1:
            return found[0]
        if not found:
            die("не нашёл «%s»" % q)
    else:
        found = allc
    if not sys.stdin.isatty():
        die("«%s»: подходит %d контактов — уточните имя или номер (wa who %s)" % (q, len(found), q))
    if shutil.which("fzf") and sys.stdin.isatty():
        lines = ["%s\t%s%s" % (x["name"], x["phone"], "" if x.get("book") else "  · профиль") for x in found]
        p = subprocess.run(["fzf", "--prompt", "Кому> ", "--query", q, "--height", "40%", "--reverse",
                            "--delimiter", "\t", "--with-nth", "1,2"], input="\n".join(lines),
                           capture_output=False, stdout=subprocess.PIPE, text=True)
        if p.returncode or not p.stdout.strip():
            die("отменено")
        name, phone = p.stdout.rstrip("\n").split("\t")[:2]
        phone = phone.split()[0]
        return next(x for x in found if x["phone"] == phone and x["name"] == name)
    for k, x in enumerate(found[:20], 1):
        print("%2d. %s %s%s%s" % (k, x["name"], D, x["phone"], X))
    k = input("Номер: ").strip()
    if not k.isdigit() or not 1 <= int(k) <= min(20, len(found)):
        die("отменено")
    return found[int(k) - 1]


def ask_due(prompt="Когда"):
    while True:
        s = input("%s (%s): " % (prompt, "завтра в 9 · пт 18:30 · 16.10 10:00 · через 2 часа")).strip()
        if not s:
            die("отменено")
        due, err = W.parse_due(s)
        if due:
            return due
        print(Y + err + X)


def read_text():
    print("Текст (закончить — пустая строка; Ctrl+C — отмена):")
    out = []
    while True:
        try:
            s = input()
        except EOFError:
            break
        if not s and out:
            break
        out.append(s)
    return "\n".join(out).strip()


def cmd_new(c, q=""):
    try:
        x = pick(q)
        print("Кому: %s%s%s %s" % (B, x["name"], X, x["phone"]))
        text = read_text()
        if not text:
            die("пустой текст")
        due = ask_due()
        print("\n%sКому:%s %s\n%sКогда:%s %s\n%s\n" % (B, X, x["name"], B, X, W.when(due), text))
        if input("Запланировать? [Y/n] ").strip().lower() not in ("", "y", "д", "да", "yes"):
            die("отменено")
    except KeyboardInterrupt:
        die("\nотменено")
    mid = W.add(c, x["jid"], x["name"], text, due, "cli")
    print(G + "✓ #%d уйдёт %s" % (mid, W.when(due)) + X)


def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return
    if a and a[0] == "lock":
        hub_auth.drop()
        print("✓ пароль забыт — следующий вход снова спросит")
        return
    if a and a[0] == "app":                 # окно спрашивает пароль само; из лаунчера терминала нет
        subprocess.Popen([sys.executable, os.path.join(HERE, "wa_app.py")], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    hub_auth.tty_gate()
    if a and a[0] in RAW:
        os.execv(W.BIN, [W.BIN] + a)
    c = H.connect()
    cmd, rest = (a[0], a[1:]) if a else ("list", [])
    try:
        if cmd in ("list", "ls", "l"):
            show_list(c, bool(rest and rest[0] in ("all", "-a", "все")))
        elif cmd in ("history", "hist", "журнал", "история"):
            n = int(rest[0]) if rest and rest[0].isdigit() else 30
            h = W.history(c, n, hidden=True)
            print(B + "Журнал" + X + D + " · всего %d" % W.history_count(c) + X if h else D + "Журнал пуст." + X)
            for m in h:
                print(line(m) + (D + "  · убрано из окна" + X if m["hidden"] else ""))
        elif cmd == "clear":
            n = W.history_count(c)
            if not n:
                print(D + "Журнал и так пуст." + X)
                return
            if not sys.stdin.isatty():
                die("wa clear — только из терминала (спрашивает подтверждение)")
            try:
                ok = input("Стереть журнал насовсем — %d записей (отправленные и отменённые; очередь не трогаю)? [y/N] "
                           % n).strip().lower() in ("y", "yes", "д", "да")
            except (KeyboardInterrupt, EOFError):
                ok = False
            if not ok:
                die("отменено")
            print(G + "✓ стёрто: %d" % W.clear_history(c) + X)
        elif cmd == "stop":
            n = W.pending_count(c)
            if not n:
                print(D + "Ничего не ждёт." + X)
                return
            if not sys.stdin.isatty():
                die("wa stop — только из терминала (спрашивает подтверждение)")
            try:
                ok = input("Остановить все запланированные — %d? Не стираю, вернуть: wa resume [y/N] "
                           % n).strip().lower() in ("y", "yes", "д", "да")
            except (KeyboardInterrupt, EOFError):
                ok = False
            if not ok:
                die("отменено")
            print(G + "✓ остановлено: %d (вернуть: wa resume)" % W.stop_all(c) + X)
        elif cmd == "resume":
            n = W.resume_all(c)
            print(G + "✓ снова ждут: %d" % n + X if n else D + "Возвращать нечего." + X)
        elif cmd in ("new", "n"):
            cmd_new(c, " ".join(rest))
        elif cmd == "add":
            if len(rest) < 3:
                die('wa add КОМУ КОГДА ТЕКСТ   (wa add мама "завтра в 9" "Доброе утро")')
            x = pick(rest[0])
            due, err = W.parse_due(rest[1])
            if not due:
                die(err)
            text = sys.stdin.read() if rest[2] == "-" else " ".join(rest[2:])
            mid = W.add(c, x["jid"], x["name"], text.strip(), due, "cli")
            print(G + "✓ #%d → %s, %s" % (mid, x["name"], W.when(due)) + X)
        elif cmd == "show" and rest:
            m = need(c, rest[0])
            print(line(m).split("\n")[0])
            print("\n" + m["text"])
        elif cmd == "time" and len(rest) > 1:
            m = need(c, rest[0])
            due, err = W.parse_due(" ".join(rest[1:]))
            if not due:
                die(err)
            print(G + "✓ уйдёт %s" % W.when(due) + X if W.edit(c, m["id"], due=due) else R + "уже не ждёт" + X)
        elif cmd == "text" and len(rest) > 1:
            m = need(c, rest[0])
            text = sys.stdin.read() if rest[1] == "-" else " ".join(rest[1:])
            print(G + "✓ переписано" + X if W.edit(c, m["id"], text=text.strip()) else R + "уже не ждёт" + X)
        elif cmd == "now" and rest:
            m = need(c, rest[0])
            if sys.stdin.isatty() and input("Отправить %s сейчас? [y/N] " % m["name"]).strip().lower() \
                    not in ("y", "д", "да", "yes"):
                die("отменено")
            print(G + "✓ уйдёт в ближайшие секунды" + X if W.send_now(c, m["id"]) else R + "уже не ждёт" + X)
        elif cmd == "later" and rest:
            m = need(c, rest[0])
            mins = int(rest[1]) if len(rest) > 1 and rest[1].isdigit() else 60
            if not 1 <= mins <= 60 * 24 * 30:
                die("минут: от 1 до 43200")
            print(G + "✓ уйдёт %s" % W.when(W.get(c, m["id"])["due"]) + X if W.postpone(c, m["id"], mins * 60)
                  else R + "уже не ждёт" + X)
        elif cmd in ("cancel", "rm", "del") and rest:
            m = need(c, rest[0])
            print(G + "✓ отменено (вернуть: wa back %d)" % m["id"] + X if W.cancel(c, m["id"])
                  else R + "уже не ждёт" + X)
        elif cmd == "back" and rest:
            m = need(c, rest[0])
            print(G + "✓ снова ждёт: %s" % W.when(m["due"]) + X if W.restore(c, m["id"]) else R + "не отменено" + X)
        elif cmd == "who":
            for x in W.search(" ".join(rest), 20):
                print("%s %s%s%s%s" % (x["name"], D, x["phone"], "" if x.get("book") else " · профиль", X))
        else:
            print(__doc__.strip())
            sys.exit(2)
    except ValueError as e:
        die("не записал: %s" % e)


if __name__ == "__main__":
    main()
