#!/usr/bin/env python3
"""Пароль перед входом в WhatsApp-отправщик (15.10.2026). Просьба: «перед входом на десктопе
или в терминальное приложение пусть спрашивает пароль sudo… в начале подтвердить один раз,
потом уже не спрашивать».

Пароль проверяет PAM, служба «sudo» (/etc/pam.d/sudo → system-auth; читаем, не меняем) —
тот же пароль, что у sudo, но прав root не даёт и sudo не вызывает. Верный пароль открывает
доступ на TICKET_SECS и окну, и терминалу (пропуск в $XDG_RUNTIME_DIR — tmpfs, пропадает при
выходе из сеанса). Окно само запирается после IDLE_SECS без дела.

faillock (deny=3, 10 мин) считает и эти ошибки: за один заход — не больше TRIES попыток и
не больше, чем осталось до блокировки, чтобы не запереть вход в систему.
Telegram пароль не спрашивает — там одноразовый код (tfa.py), он в истории бесполезен.
"""
import ctypes
import ctypes.util
import getpass
import os
import pwd
import subprocess
import sys
import time

SERVICE = "sudo"
TICKET = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid(), "hub-auth")
TICKET_SECS = 15 * 60
IDLE_SECS = 10 * 60
TRIES = 2
DENY = 3                                   # /etc/security/faillock.conf: deny по умолчанию
USER = pwd.getpwuid(os.getuid()).pw_name


def _boot():
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip()
    except OSError:
        return ""


def ticket_ok():
    try:
        st = os.stat(TICKET)
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            return False
        with open(TICKET) as f:
            boot, until = f.read().split()
        return boot == _boot() and time.time() < float(until) <= time.time() + TICKET_SECS + 5
    except (OSError, ValueError):
        return False


def grant():
    tmp = TICKET + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("%s %d\n" % (_boot(), time.time() + TICKET_SECS))
    os.replace(tmp, TICKET)


def drop():
    try:
        os.unlink(TICKET)
    except OSError:
        pass


FAIL_INTERVAL = 900                        # faillock.conf: fail_interval по умолчанию (15 мин)


def fail_times():
    """Моменты неверных паролей, которые faillock ещё считает (за fail_interval)."""
    try:
        out = subprocess.run(["faillock", "--user", USER], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    out_t = []
    for ln in out.splitlines():
        if ln[:2] == "20" and ln.rstrip().endswith("V"):
            try:
                out_t.append(time.mktime(time.strptime(ln[:19], "%Y-%m-%d %H:%M:%S")))
            except ValueError:
                pass
    return sorted(t for t in out_t if t > time.time() - FAIL_INTERVAL)


def fails_now():
    return len(fail_times())


def retry_at():
    """Когда старейшая ошибка выйдет из счёта и появится попытка (epoch) — или None."""
    t = fail_times()
    return t[0] + FAIL_INTERVAL if t else None


def tries_left():
    """Сколько можно ошибиться, не заперев вход в систему (оставляем одну про запас)."""
    return max(0, min(TRIES, DENY - 1 - fails_now()))


# ── PAM (ctypes, libpam.so.0) — как в jarvis_lock.py ─────────────────────────
PAM_SUCCESS, PAM_NEW_AUTHTOK_REQD, PAM_CONV_ERR, PAM_BUF_ERR = 0, 12, 19, 5
PAM_PROMPT_ECHO_OFF, PAM_PROMPT_ECHO_ON = 1, 2


class _Msg(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class _Resp(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]


_CONV = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.POINTER(_Msg)),
                         ctypes.POINTER(ctypes.POINTER(_Resp)), ctypes.c_void_p)


class _Conv(ctypes.Structure):
    _fields_ = [("conv", _CONV), ("appdata_ptr", ctypes.c_void_p)]


_pam = ctypes.CDLL("libpam.so.0")
_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
_libc.calloc.restype = ctypes.c_void_p
_libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
_libc.malloc.restype = ctypes.c_void_p
_libc.malloc.argtypes = [ctypes.c_size_t]
_pam.pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(_Conv), ctypes.POINTER(ctypes.c_void_p)]
_pam.pam_start.restype = ctypes.c_int
for _f in ("pam_authenticate", "pam_acct_mgmt", "pam_end"):
    getattr(_pam, _f).argtypes = [ctypes.c_void_p, ctypes.c_int]
    getattr(_pam, _f).restype = ctypes.c_int


def _dup(data):
    n = len(data)
    p = _libc.malloc(n + 1)
    if not p:
        return None
    if n:
        view = (ctypes.c_char * n).from_buffer(data)
        ctypes.memmove(p, view, n)
        del view
    ctypes.memset(p + n, 0, 1)
    return p


def wipe(buf):
    if buf:
        view = (ctypes.c_char * len(buf)).from_buffer(buf)
        ctypes.memset(view, 0, len(buf))
        del view


def check(secret):
    """secret — bytearray (вызывающий затирает). True — пароль верный; тогда выдаём пропуск."""
    user_b = bytearray(USER.encode())

    def conv(n, msg, resp, _d):
        if n <= 0:
            return PAM_CONV_ERR
        arr = _libc.calloc(n, ctypes.sizeof(_Resp))
        if not arr:
            return PAM_BUF_ERR
        out = ctypes.cast(arr, ctypes.POINTER(_Resp))
        for i in range(n):
            st = msg[i].contents.msg_style
            if st == PAM_PROMPT_ECHO_OFF:
                out[i].resp = _dup(secret)
            elif st == PAM_PROMPT_ECHO_ON:
                out[i].resp = _dup(user_b)
        resp[0] = out
        return PAM_SUCCESS

    cb = _CONV(conv)
    pconv = _Conv(cb, None)
    h = ctypes.c_void_p()
    rc = _pam.pam_start(SERVICE.encode(), USER.encode(), ctypes.byref(pconv), ctypes.byref(h))
    if rc != PAM_SUCCESS:
        return False
    rc = _pam.pam_authenticate(h, 0)
    if rc == PAM_SUCCESS:
        rc = _pam.pam_acct_mgmt(h, 0)
    _pam.pam_end(h, rc)
    ok = rc in (PAM_SUCCESS, PAM_NEW_AUTHTOK_REQD)
    _journal("ok" if ok else "fail")
    if ok:
        grant()
    return ok


def _journal(s):
    p = os.path.expanduser("~/.config/hub/auth.log")
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("%s %s %s\n" % (time.strftime("%d.%m %H:%M:%S"), s, os.path.basename(sys.argv[0])))
    except OSError:
        pass


def tty_gate(what="WhatsApp"):
    """Терминал: пропуск есть — молча дальше; нет — пароль (getpass, без эха)."""
    if ticket_ok():
        return
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        sys.exit("%s: нужен пароль — запустите из терминала (или откройте окно и войдите)" % what)
    n = tries_left()
    if n <= 0:
        at = retry_at()
        sys.exit("Система не заблокирована — wa остановился сам: третья ошибка подряд заперла бы вход "
                 "на 10 минут. Новая попытка — %s." % (time.strftime("после %H:%M", time.localtime(at + 5))
                                                      if at else "через минуту"))
    for k in range(n):
        try:
            buf = bytearray(getpass.getpass("%s · пароль sudo: " % what).encode())
        except (KeyboardInterrupt, EOFError):
            sys.exit("\nотменено")
        try:
            if check(buf):
                return
        finally:
            wipe(buf)
        print("Неверно." + (" Осталось попыток: %d" % (n - k - 1) if k + 1 < n else ""), file=sys.stderr)
    sys.exit("Не вошли. Новые попытки — при следующем запуске (faillock: после 3 ошибок вход в систему "
             "запирается на 10 минут).")
