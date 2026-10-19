#!/usr/bin/env python3
"""Второй ключ для удалённого доступа (15.10.2026). Просьба: «даже если бот взломают никто не
должен иметь возможность получить доступ к моему пк во первых, потом к моему whatsapp… я не
всегда дома, возможность управлять процессами удалённо у меня должна быть».

Telegram не сообщает боту ни устройство, ни IP — только ID владельца. Если украдут сам
аккаунт Telegram, ID не поможет. Поэтому опасное из Telegram (/pc, /away, /wa)
просит 6 цифр из приложения-аутентификатора на телефоне (TOTP, RFC 6238):
верный код открывает доступ на OPEN_SECS; один код — один раз; MAX_FAILS неверных подряд —
удалённый доступ заперт, пока не открыть с ноутбука (tfa unlock).

    tfa setup     создать ключ и показать QR для приложения (Aegis, Google Authenticator)
    tfa status    настроен ли, открыт ли, сколько ошибок
    tfa unlock    снять запрет после неверных кодов (только с ноутбука)
    tfa close     закрыть доступ сейчас
    tfa off       удалить ключ (защита выключена — не советую)

Ключ — ~/.config/hub/tfa.key (0600), состояние — ~/.config/hub/tfa.json (0600).
Пока ключа нет, боты работают как раньше, но предупреждают.
"""
import base64
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import struct
import subprocess
import sys
import time

CONF = os.environ.get("HUB_CONF") or os.path.expanduser("~/.config/hub")
KEY = os.path.join(CONF, "tfa.key")
STATE = os.path.join(CONF, "tfa.json")
LOCK = os.path.join(CONF, "tfa.lock")
OPEN_SECS = 15 * 60
# 15.10.2026, просьба: «для /pc можно… пусть просит код через неделю». Пульт ПК (/pc) после
# кода открыт PC_SECS; WhatsApp и охрана — по-прежнему OPEN_SECS.
PC_SECS = 7 * 24 * 3600
MAX_FAILS = 5
STEP = 30


def _secret():
    try:
        with open(KEY) as f:
            s = f.read().strip()
        return base64.b32decode(s + "=" * (-len(s) % 8)) if s else None
    except (OSError, ValueError):
        return None


def enabled():
    return _secret() is not None


def _code(key, counter):
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 15
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7fffffff) % 1000000)


class _Locked:
    """Состояние под замком файла: два бота — два процесса."""
    def __enter__(self):
        os.makedirs(CONF, mode=0o700, exist_ok=True)
        self.f = open(LOCK, "a")
        os.chmod(LOCK, 0o600)
        fcntl.flock(self.f, fcntl.LOCK_EX)
        try:
            with open(STATE) as f:
                self.st = json.load(f)
        except (OSError, ValueError):
            self.st = {}
        return self.st

    def __exit__(self, *exc):
        tmp = STATE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.st, f)
        os.replace(tmp, STATE)
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _read():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def is_open(scope=None):
    """Можно ли сейчас опасное из Telegram. Ключа нет — можно (как раньше).
    scope="pc" — пульт ПК: ему хватает недельного окна pc_until."""
    if not enabled():
        return True
    st = _read()
    if st.get("blocked"):
        return False
    t = time.time()
    return st.get("until", 0) > t or (scope == "pc" and st.get("pc_until", 0) > t)


def blocked():
    return enabled() and bool(_read().get("blocked"))


def left():
    """Сколько секунд ещё открыто."""
    return max(0, int(_read().get("until", 0) - time.time())) if enabled() else 0


def verify(code, who="tg"):
    """6 цифр → (ok, сообщение). Пробелы внутри можно («123 456»)."""
    key = _secret()
    if key is None:
        return False, "Второй ключ не настроен: на ноутбуке tfa setup"
    code = "".join(code.split())
    with _Locked() as st:
        if st.get("blocked"):
            return False, "Удалённый доступ заперт после %d неверных кодов. Открыть — только с ноутбука: tfa unlock" % MAX_FAILS
        now = int(time.time()) // STEP
        hit = None
        if len(code) == 6 and code.isdigit():
            for k in (now - 1, now, now + 1):
                if hmac.compare_digest(_code(key, k), code):
                    hit = k
        if hit is not None and hit > st.get("last", -1):
            st.update(last=hit, fails=0, until=time.time() + OPEN_SECS, pc_until=time.time() + PC_SECS)
            _journal("open %s" % who)
            return True, "🔓 Доступ открыт: пульт ПК — на %d дней, остальное — на %d минут." % (
                PC_SECS // 86400, OPEN_SECS // 60)
        st["fails"] = st.get("fails", 0) + 1
        if hit is not None:
            why = "этот код уже использован — дождитесь следующего"
        else:
            why = "неверный код"
        _journal("fail %s (%d)" % (who, st["fails"]))
        if st["fails"] >= MAX_FAILS:
            st.update(blocked=True, until=0, pc_until=0)
            _journal("blocked")
            _alarm()
            return False, "⛔ %d неверных кодов подряд. Удалённый доступ заперт; открыть — только с ноутбука: tfa unlock" % MAX_FAILS
        return False, "✗ %s. Осталось попыток: %d" % (why.capitalize(), MAX_FAILS - st["fails"])


def close():
    with _Locked() as st:
        st.update(until=0, pc_until=0)


def unlock():
    with _Locked() as st:
        st.update(blocked=False, fails=0)
    _journal("unlock pc")


def _journal(s):
    p = os.path.join(CONF, "tfa.log")
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), s))


def _alarm():
    try:
        subprocess.Popen(["notify-send", "-u", "critical", "-a", "HUB", "Удалённый доступ заперт",
                          "%d неверных кодов из Telegram подряд. Если это не вы — смените пароль Telegram "
                          "и завершите чужие сеансы. Открыть: tfa unlock" % MAX_FAILS],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


PROMPT = ("🔐 Нужен второй ключ: пришлите 6 цифр из приложения-аутентификатора "
          "(«staticOS · HUB»). Пульт ПК откроется на %d дней, остальное — на %d минут." % (
              PC_SECS // 86400, OPEN_SECS // 60))
NOT_SET = "⚠ Второй ключ не настроен — любой, кто получит ваш Telegram, сможет это сделать. На ноутбуке: tfa setup"


def looks_like_code(text):
    t = "".join((text or "").split())
    return len(t) == 6 and t.isdigit()


# ───────────────────────────── терминал ─────────────────────────────

def _setup():
    if enabled() and input("Ключ уже есть. Создать новый (старый в приложении перестанет работать)? [y/N] ") \
            .strip().lower() not in ("y", "д", "да"):
        return
    os.makedirs(CONF, mode=0o700, exist_ok=True)
    raw = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    tmp = KEY + ".new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(raw + "\n")
    uri = "otpauth://totp/staticOS:HUB?secret=%s&issuer=staticOS&digits=6&period=30" % raw
    print("Телефон: приложение-аутентификатор → «+» → «Сканировать QR»:\n")
    subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "2", uri])
    print("\nИли вручную: %s\n" % " ".join(raw[i:i + 4] for i in range(0, len(raw), 4)))
    key = base64.b32decode(raw + "=" * (-len(raw) % 8))
    for _ in range(3):
        c = "".join(input("Код из приложения (6 цифр): ").split())
        now = int(time.time()) // STEP
        if any(hmac.compare_digest(_code(key, k), c) for k in (now - 1, now, now + 1)):
            os.replace(tmp, KEY)
            with _Locked() as st:
                st.clear()
            _journal("setup")
            os.system("clear")  # QR и ключ не оставлять на экране
            print("✓ Второй ключ настроен (%s, 0600). Опасное из Telegram теперь просит код." % KEY)
            return
        print("Не совпало — проверьте время на телефоне и попробуйте ещё.")
    os.unlink(tmp)
    print("Не настроено: код так и не совпал.")


def main():
    a = sys.argv[1:] or ["status"]
    if a[0] == "setup":
        _setup()
    elif a[0] == "status":
        if not enabled():
            print("Второй ключ не настроен: tfa setup")
            return
        st = _read()
        print("настроен · %s · ошибок подряд %d" % (
            "⛔ заперт (tfa unlock)" if st.get("blocked") else
            ("открыт ещё %d мин" % (left() // 60 + 1) if is_open() else "закрыт"), st.get("fails", 0)))
        pc = int(st.get("pc_until", 0) - time.time())
        if pc > 0 and not st.get("blocked"):
            print("пульт ПК (/pc) открыт ещё %d ч" % (pc // 3600 + 1))
    elif a[0] == "unlock":
        if not sys.stdin.isatty():
            sys.exit("tfa unlock — только из терминала ноутбука")
        unlock()
        print("✓ Запрет снят. Код снова принимается.")
    elif a[0] == "close":
        close()
        print("✓ Закрыто.")
    elif a[0] == "off":
        if input("Удалить второй ключ? Защита выключится. [y/N] ").strip().lower() in ("y", "д", "да"):
            os.unlink(KEY)
            _journal("off")
            print("Удалён.")
    else:
        print(__doc__.strip())


if __name__ == "__main__":
    main()
