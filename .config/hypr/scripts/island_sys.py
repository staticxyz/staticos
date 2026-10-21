#!/usr/bin/env python3
"""Состояния и действия системных страниц островка: «Центр», Wi-Fi, Bluetooth, Питание.

20.10.2026, просьба: «аналог Центра управления из waybar… Кофеин (ЛКМ), Кофеин + Таурин
(ПКМ) — одна кнопка; Ночной свет (ЛКМ), спектр по ПКМ; Баланс/Мощность (ЛКМ), Экономия
(ПКМ); круглая аватарка и ник как в «Пуске»; если влезает — система и uptime. Wi-Fi,
Bluetooth, Питание».

Без GTK: только опрос и команды — те же ручки, что у control_center.py (savage_battery,
screen_awake, night_mode.py, powerprofilesctl, nmcli, bluetoothctl, power_menu.py). Всё
здесь вызывается из потоков островка: опрос не держит цикл GTK.

    island_sys.py cc|wifi|bt|pill     состояние в JSON (для проверки)

Вечером 20.10.2026 (Пользователь): «Ещё…» — список прямо в островке, щелчок по сети только
открывает кнопки, как в плашке бара; питание — с подтверждением в островке (отсчёта
power_menu больше нет); свёрнутый «Центр» — Сторож, день недели, кофеин/таурин.
ISLAND_SYS_DRY=1 — команды питания только печатаются (проверка).
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PY = sys.executable
AVATAR = os.path.expanduser("~/.cache/avatar.png")
NAME_FILE = os.path.expanduser("~/.config/hypr/state/display-name")


def run(*args, timeout=4):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def spawn(argv):
    """Отдельным процессом через niri: островок может перезапуститься, запущенное — живёт."""
    subprocess.Popen(["niri", "msg", "action", "spawn", "--", *argv], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def script(name, *args):
    return (PY, os.path.join(HERE, name), *args)


# ── «Центр» ──────────────────────────────────────────────────────────────

def display_name():
    """Имя — как в «Пуске» (start_menu.header): state/display-name, иначе логин."""
    try:
        s = open(NAME_FILE).read().strip()
        if s:
            return s
    except OSError:
        pass
    import getpass
    return getpass.getuser()


def uptime():
    try:
        sec = int(float(open("/proc/uptime").read().split()[0]))
    except (OSError, ValueError):
        return ""
    d, rest = divmod(sec, 86400)
    h, m = rest // 3600, rest % 3600 // 60
    return ("%d д " % d if d else "") + ("%d ч " % h if h or d else "") + "%d мин" % m


_CPU = {"prev": None}


def cpu_pct():
    """Загрузка CPU между двумя опросами (первый раз — за 0,2 с)."""
    def read():
        v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
        return sum(v), v[3] + (v[4] if len(v) > 4 else 0)
    try:
        if _CPU["prev"] is None:
            _CPU["prev"] = read()
            time.sleep(0.2)
        t, i = read()
        pt, pi = _CPU["prev"]
        _CPU["prev"] = (t, i)
        return max(0, min(100, round(100 * (1 - (i - pi) / max(1, t - pt)))))
    except (OSError, ValueError):
        return None


def mem():
    """(занято, всего) в ГиБ."""
    try:
        m = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            m[k] = int(v.split()[0])
        return (m["MemTotal"] - m["MemAvailable"]) / 1048576, m["MemTotal"] / 1048576
    except (OSError, ValueError, KeyError):
        return None, None


def cpu_temp():
    import glob
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            if open(d + "/name").read().strip() in ("coretemp", "k10temp", "zenpower"):
                return int(open(d + "/temp1_input").read()) / 1000
        except (OSError, ValueError):
            continue
    return None


def power_profile():
    p = run("busctl", "get-property", "net.hadess.PowerProfiles", "/net/hadess/PowerProfiles",
            "net.hadess.PowerProfiles", "ActiveProfile").removeprefix("s ").strip('"')
    return p or None


def guard_on():
    """Сторож будильника на сегодня ещё впереди или идёт (wake_alarm.watch_for и не позже его
    «до»). Значок слева в свёрнутом «Центре»."""
    try:
        import datetime as dt
        import wake_alarm as wa
        w = wa.watch_for(wa.load(), dt.date.today())
        return bool(w) and time.strftime("%H:%M") < w["to"]
    except Exception:
        return False


def pill_state():
    """Свёрнутый «Центр»: только дешёвое — кофеин, таурин, Сторож."""
    import savage_battery
    import screen_awake
    caf = savage_battery.is_savage_active()
    return {"caffeine": caf, "taurine": bool(caf and screen_awake.get()), "guard": guard_on(), "t": time.time()}


def cc_state():
    import night_mode
    import savage_battery
    import screen_awake
    try:
        night, _t, warmth = night_mode.read_state()
    except Exception:
        night, warmth = False, None
    caf = savage_battery.is_savage_active()
    used, total = mem()
    return {"name": display_name(), "avatar": AVATAR if os.path.exists(AVATAR) else None,
            "uptime": uptime(), "cpu": cpu_pct(), "mem": used, "mem_total": total, "temp": cpu_temp(),
            "caffeine": caf, "taurine": bool(caf and screen_awake.get()),
            "night": bool(night), "warmth": int(warmth if warmth is not None else 65),
            "profile": power_profile(), "guard": guard_on(), "t": time.time()}


def caffeine(button, st):
    """ЛКМ — кофеин (Savage Mode) вкл/выкл; ПКМ — «Кофеин + Таурин» (ещё и экран не гаснет)
    вкл/выкл. ЛКМ по таурину оставляет обычный кофеин; ПКМ по нему гасит всё (21.10.2026, просьба: «полностью должна выключаться, вместе с Кофеин»)."""
    import savage_battery
    on = savage_battery.is_savage_active()
    if button == 1:
        if st.get("taurine"):                    # ЛКМ по таурину — назад к обычному кофеину
            run(*script("screen_awake.py", "off"))      # (21.10.2026, пользователь)
        elif on:
            run(*script("savage_battery.py", "--toggle"))       # гасит и таурин
        else:
            spawn(list(script("savage_battery.py", "--toggle")))
        return
    if st.get("taurine"):
        run(*script("screen_awake.py", "off"))
        if on:
            run(*script("savage_battery.py", "--toggle"))
    else:
        if not on:
            spawn(list(script("savage_battery.py", "--toggle")))   # systemd-inhibit — отдельной сессией
            time.sleep(0.5)
        run(*script("screen_awake.py", "on"))


def night(on):
    run(*script("night_mode.py", "on" if on else "off"), timeout=6)


def warmth(v):
    """Теплота 0..100 (night_mode: 6500 → 2800 K); заодно включает ночной свет."""
    run(*script("night_mode.py", "on", str(int(max(0, min(100, v))))), timeout=6)


def profile(button):
    """ЛКМ — «Баланс» ↔ «Мощность» (из «Экономии» — в «Баланс»); ПКМ — «Экономия» ↔ «Баланс»."""
    cur = power_profile()
    if button == 1:
        new = "performance" if cur == "balanced" else "balanced"
    else:
        new = "balanced" if cur == "power-saver" else "power-saver"
    run("powerprofilesctl", "set", new)


# ── Wi-Fi ────────────────────────────────────────────────────────────────

def nmcli(*args, timeout=8):
    try:
        r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def wifi_state(rescan=False):
    """Радио, видимые сети (обычно без пересканирования: опрос дешёвый; rescan — для «Ещё…»)
    и сохранённые профили. Разбор — как wifi_state() в control_center.py."""
    on = run("nmcli", "radio", "wifi") == "enabled"
    known = set()
    ok, out = nmcli("-t", "-f", "NAME,TYPE", "connection", "show")
    for line in out.splitlines() if ok else ():
        name, _, kind = line.rpartition(":")
        if kind == "802-11-wireless":
            known.add(name.replace("\\:", ":"))
    nets = {}
    if on:
        ok, out = nmcli("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan",
                        "yes" if rescan else "no", timeout=20 if rescan else 8)
        for line in out.splitlines() if ok else ():
            parts = [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]
            if len(parts) < 4 or not parts[1]:
                continue
            try:
                sig = int(parts[2])
            except ValueError:
                sig = 0
            ssid, use = parts[1], parts[0] == "*"
            cur = nets.get(ssid)
            if cur is None or sig > cur["signal"]:
                nets[ssid] = {"ssid": ssid, "signal": sig, "secured": bool(parts[3]) and parts[3] != "--",
                              "in_use": use or bool(cur and cur["in_use"]), "known": ssid in known}
            elif use:
                cur["in_use"] = True
    order = sorted(nets.values(), key=lambda n: (not n["in_use"], not n["known"], -n["signal"], n["ssid"].lower()))
    ip = ""
    if any(n["in_use"] for n in order):
        ok, out = nmcli("-t", "-f", "IP4.ADDRESS", "dev", "show", wifi_iface() or "")
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", out) if ok else None
        ip = m.group(1) if m else ""
    return {"on": on, "nets": order[:40], "ip": ip, "t": time.time()}


def wifi_iface():
    ok, out = nmcli("-t", "-f", "DEVICE,TYPE", "device")
    for line in out.splitlines() if ok else ():
        dev, _, kind = line.rpartition(":")
        if kind == "wifi":
            return dev
    return None


def wifi_power(on):
    run("nmcli", "radio", "wifi", "on" if on else "off")


def _why(out, fallback="не получилось"):
    line = (out or "").strip().splitlines()[-1:] or [fallback]
    return line[0].replace("Error: ", "")[:80]


def wifi_do(what, net, pw=""):
    """Кнопки сети, как в wifi_popup.py: connect (сохранённая — по профилю, новая — с паролем,
    открытая — так), disconnect, forget (удалить профиль). → (успех, текст)."""
    ssid = net["ssid"]
    if what == "disconnect":
        dev = wifi_iface()
        if not dev:
            return False, "не найден Wi-Fi адаптер"
        ok, out = nmcli("device", "disconnect", dev, timeout=15)
        return ok, "Отключено" if ok else _why(out)
    if what == "forget":
        ok, out = nmcli("connection", "delete", "id", ssid, timeout=15)
        return ok, "Сеть забыта" if ok else _why(out)
    if net.get("known"):
        ok, out = nmcli("connection", "up", "id", ssid, timeout=45)
    elif pw:
        ok, out = nmcli("device", "wifi", "connect", ssid, "password", pw, timeout=45)
    else:
        ok, out = nmcli("device", "wifi", "connect", ssid, timeout=45)
    return ok, "Подключено" if ok else _why(out)


# ── Bluetooth ────────────────────────────────────────────────────────────

def bt(*args, timeout=6):
    try:
        r = subprocess.run(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _devices(*flt):
    out = []
    for line in bt("devices", *flt).splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device":
            out.append((parts[1], parts[2]))
    return out


def bt_state(new=False):
    """Питание адаптера и сопряжённые устройства (new — и найденные поиском, для «Ещё…»).
    `bluetoothctl info` — только у подключённых (заряд, вид): опрос по всем сразу стоил по
    процессу на устройство каждые 3 с."""
    show = bt("show")
    powered = "Powered: yes" in show
    conn = {m for m, _n in _devices("Connected")} if powered else set()
    paired = _devices("Paired")
    pm = {m for m, _n in paired}
    found = [(m, n) for m, n in _devices() if m not in pm] if new and powered else []
    devs = []
    for mac, name in paired + found:
        d = {"mac": mac, "name": name, "conn": mac in conn, "kind": "", "batt": "", "pair": mac in pm}
        if d["conn"]:
            for l in bt("info", mac).splitlines():
                l = l.strip()
                if l.startswith("Icon:"):
                    d["kind"] = l.split(":", 1)[1].strip()
                elif l.startswith("Battery Percentage:") and "(" in l:
                    d["batt"] = l.split("(", 1)[1].rstrip(")").strip()
        devs.append(d)
    devs.sort(key=lambda d: (not d["conn"], not d["pair"], d["name"].lower()))
    return {"on": powered, "devs": devs[:40], "t": time.time()}


def radio_state():
    """Значки вкладок Wi-Fi и Bluetooth в карточке Skeet (20.10.2026, просьба: «покрасить, если
    включена, и чуть другим цветом, если ещё и подключена»): 0 — выкл, 1 — вкл, 2 — подключено.
    Без списков сетей и устройств — три лёгких вызова."""
    w = 0
    if run("nmcli", "radio", "wifi") == "enabled":
        w = 2 if "wifi:connected" in run("nmcli", "-t", "-f", "TYPE,STATE", "dev").splitlines() else 1
    b = 0
    if "Powered: yes" in bt("show"):
        b = 2 if _devices("Connected") else 1
    return {"wifi": w, "bt": b}


def bt_power(on):
    if on:
        run("rfkill", "unblock", "bluetooth")       # выключенный rfkill адаптер bluetoothctl не включит
    bt("power", "on" if on else "off")


def bt_scan(sec=12):
    """Поиск новых устройств (как «обновить» в плашке бара): держится sec секунд."""
    bt("--timeout", str(sec), "scan", "on", timeout=sec + 10)


def _bt_ok(out, word):
    low = out.lower()
    return word in low and "failed" not in low and "error" not in low


def bt_do(what, dev):
    """Кнопки устройства, как в bluetooth_popup.py: connect (новое — сначала pair и trust),
    disconnect, forget (remove). → (успех, текст)."""
    mac = dev["mac"]
    if what == "disconnect":
        out = bt("disconnect", mac, timeout=20)
        return _bt_ok(out, "successful"), "Отключено" if _bt_ok(out, "successful") else _why(out)
    if what == "forget":
        out = bt("remove", mac, timeout=15)
        ok = "removed" in out.lower() and "failed" not in out.lower()
        return ok, "Устройство забыто" if ok else _why(out)
    if not dev.get("pair", True):
        out = bt("pair", mac, timeout=40)
        if not _bt_ok(out, "successful"):
            return False, _why(out, "не сопряглось")
        bt("trust", mac, timeout=10)
    out = bt("connect", mac, timeout=30)
    return _bt_ok(out, "successful"), "Подключено" if _bt_ok(out, "successful") else _why(out)


# ── Питание ──────────────────────────────────────────────────────────────

POWER = (("lock", "Блокировка"), ("logout", "Выход"), None,
         ("suspend", "Сон"), ("reboot", "Перезагрузка"), ("shutdown", "Выключение"))


def power(what):
    """Блокировка — сразу (как Super+O); выход, сон, перезагрузка, выключение — уже после «Да»
    в островке: те же команды, что у power_menu.py (сон — с замком и вестью хабу), и звук XP
    перед выходом/выключением, как там."""
    if what == "lock":
        spawn([os.path.expanduser("~/.config/niri/scripts/shell-do"), "lock"])
        return
    if what not in ("logout", "suspend", "reboot", "shutdown"):
        return
    import shlex
    import power_menu
    cmd = power_menu.commands()[what]
    ev = {"logout": "logout", "reboot": "shutdown", "shutdown": "shutdown"}.get(what)
    snd = os.path.join(HERE, "ui_sound.py")
    if ev and os.path.exists(snd):
        cmd = ["sh", "-c", 'timeout 5 python3 "$0" play "$1" --wait; shift; exec "$@"', snd, ev] + cmd
    if os.environ.get("ISLAND_SYS_DRY"):
        print("DRY-RUN %s: %s" % (what, shlex.join(cmd)), flush=True)
        return
    spawn(cmd)


def avatar_png(size):
    """Круглая аватарка size×size (кэш): рисовать в островке готовой картинкой дешевле."""
    out = os.path.expanduser("~/.cache/jarvis/island-avatar-%d.png" % size)
    try:
        if os.path.getmtime(out) >= os.path.getmtime(AVATAR):
            return out
    except OSError:
        pass
    try:
        from PIL import Image, ImageDraw
        k = 4
        im = Image.open(AVATAR).convert("RGBA").resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size * k, size * k), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * k - 1, size * k - 1), fill=255)
        im.putalpha(mask.resize((size, size), Image.LANCZOS))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        im.save(out + ".tmp.png")
        os.replace(out + ".tmp.png", out)
        return out
    except Exception:
        return None


if __name__ == "__main__":
    what = (sys.argv[1:] or ["cc"])[0]
    st = {"cc": cc_state, "wifi": wifi_state, "bt": bt_state, "pill": pill_state}.get(what)
    if not st:
        print(__doc__)
        sys.exit(1)
    print(json.dumps(st(), ensure_ascii=False, indent=1))
