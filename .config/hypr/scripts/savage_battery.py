#!/usr/bin/env python3
import json
import subprocess
import glob
import sys
import os
import signal

PID_FILE = "/tmp/savage_mode.pid"
# FIFO, по которому бар (wb_persist.py battery) перерисовывает батарею сразу после щелчка
POKE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "wb-battery.poke")


def poke_bar():
    try:
        fd = os.open(POKE, os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, b"1")
        os.close(fd)
    except OSError:          # бара нет / FIFO ещё не создан — догонит опрос
        pass

def is_savage_active():
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        
        cmdline_path = f"/proc/{pid}/cmdline"
        if os.path.exists(cmdline_path):
            with open(cmdline_path, "rb") as f:
                cmdline = f.read().decode("utf-8", errors="ignore")
                if "systemd-inhibit" in cmdline and "24/7 mode" in cmdline:
                    return True
        
        os.remove(PID_FILE)
    except Exception:
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass
    return False

def toggle_savage():
    if is_savage_active():
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass
        subprocess.run(["pkill", "-f", "systemd-inhibit.*24/7 mode"], stderr=subprocess.DEVNULL)
        poke_bar()
        # Выключая Savage Mode, гасим и его спутника «не отключать экран»:
        # сам по себе он ничего не значит, а забытым однажды оставил бы
        # машину незапертой. См. scripts/screen_awake.py.
        try:
            subprocess.run(["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "screen_awake.py"), "off"],
                           capture_output=True)
        except Exception:
            pass
    else:
        proc = subprocess.Popen([
            "systemd-inhibit",
            "--what=idle",
            "--why=24/7 mode",
            "sleep", "infinity"
        ])
        with open(PID_FILE, "w") as f:
            f.write(str(proc.pid))
    poke_bar()

def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def battery():
    """Заряд, статус, питание от сети, лимит зарядки и оценка времени.

    Лимит — FlexiCharger ноутбука (драйвер tuxedo): при charge_type=Custom
    батарея заряжается до charge_control_end_threshold и снова начинает только
    ниже charge_control_start_threshold. Поэтому от сети заряд стоит на месте, а
    статус — «Not charging»: это не сбой, а бережный режим.
    """
    bats = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    if not bats:
        return None
    b = bats[0]
    cap = int(read(b + "/capacity", "0") or 0)
    status = read(b + "/status", "Unknown")
    ac = read("/sys/class/power_supply/AC/online")
    on_ac = ac == "1" if ac else status != "Discharging"
    limit = None
    if read(b + "/charge_type") == "Custom":
        try:
            limit = (int(read(b + "/charge_control_start_threshold")),
                     int(read(b + "/charge_control_end_threshold")))
        except ValueError:
            limit = None
    hours = None
    try:
        now, cur = int(read(b + "/charge_now")), int(read(b + "/current_now"))
        full = int(read(b + "/charge_full"))
        if cur > 0 and not on_ac:
            hours = now / cur
        elif cur > 0 and status == "Charging":
            hours = max(0, full * (limit[1] if limit else 100) / 100 - now) / cur
    except (ValueError, TypeError):
        pass
    return {"cap": cap, "status": status, "on_ac": on_ac, "limit": limit, "hours": hours}


def span(hours):
    m = int(round(hours * 60))
    return "%d ч %02d мин" % (m // 60, m % 60) if m >= 60 else "%d мин" % m


def get_battery_info():
    is_savage = is_savage_active()
    info = battery()
    if info is None:
        print(json.dumps({"text": "", "tooltip": "Батареи нет", "class": "normal"}))
        return
    cap, status, on_ac, limit = info["cap"], info["status"], info["on_ac"], info["limit"]
    mode = "savage" if is_savage else "normal"

    # Заряд батареи вместо шестерёнки (13.10.2026, просьба: «отобразим текущий заряд батареи…
    # если заряжается — соответствующая иконка, если нет — другая; Savage — значок светится
    # акцентом, как у caps lock»). Раньше (27.09) значком был режим: шестерёнка / спидометр.
    # Значок — горизонтальная батарейка Font Awesome (как на примере пользователя 13.10.2026:
    # «▭ 100%», лёжа), пять ступеней заливки. Зарядка и «от сети, на паузе» (лимит
    # FlexiCharger 60–70 %, а не сбой) — та же батарейка с маленькой молнией или вилкой
    # ВНУТРИ, из своего шрифта JarvisBattery (build_battery_font.py, 13.10.2026, просьба:
    # «верни иконку до этого и просто нарисуй маленькую иконку заряда внутри»). Раньше
    # молния/вилка стояли отдельными значками рядом (бэкап .bak-onefont).
    # Savage виден по цвету и свечению (класс savage в style.css), а не по форме.
    level = 0 if cap < 10 else 1 if cap < 35 else 2 if cap < 60 else 3 if cap < 90 else 4
    if status == "Charging":
        glyph = '<span font_family="JarvisBattery">%s</span>' % chr(0xE210 + level)
    elif on_ac:
        glyph = '<span font_family="JarvisBattery">%s</span>' % chr(0xE220 + level)
    else:
        glyph = "\uf244\uf243\uf242\uf241\uf240"[level]      # fa-battery-empty … -full
    # Рисунок FA шире своей ячейки (~17 px при ~10), обычный пробел почти весь уходит под
    # него — плюс узкий пробел, чтобы число не липло (13.10.2026).
    # Значок 16 px выше строки текста — число без rise вставало на 1 px ниже соседей
    # («RU», «70%», часы; замер по снимку бара 13.10.2026). rise 1 px (1024) — ровно.
    text = "<span line_height=\"0.7\" size=\"12288\">%s</span><span font_size='30%%'> </span> <span rise='1024'>%d%%</span>" % (glyph, cap)  # 16 px — крупнее текста, как на примере
    classes = [mode]
    # «Не отключать экран» включён — значок светится (класс awake, свечение в style.css).
    # пользователь, 02.10.2026: по одному спидометру не было видно, горит ли ещё и этот режим.
    awake = False
    if is_savage:
        try:
            import screen_awake
            awake = screen_awake.get()
        except Exception:
            awake = False
    if awake:
        classes.append("awake")
    if not on_ac and cap <= 10:
        classes.append("critical")
    elif not on_ac and cap <= 20:
        classes.append("low")

    # От сети, но не заряжается там, где должна: ниже порога включения (или
    # без лимита не до полного). Так было 27.09.2026 после полного разряда:
    # контроллер показывал 0% при 11,35 В и не заряжал.
    stalled = (on_ac and status != "Charging" and status != "Full"
               and (cap < limit[0] - 1 if limit else cap < 95))
    if status == "Charging":
        power = "заряжается" + (" до %d%%" % limit[1] if limit else "")
    elif not on_ac:
        power = "от батареи"
    elif stalled:
        power = ("от сети, но НЕ заряжается" +
                 (" (должна ниже %d%%)" % limit[0] if limit else "") +
                 " — сбой контроллера зарядки")
    elif limit and cap >= limit[0] - 1:
        power = "от сети, зарядка на паузе: лимит %d%%, продолжит ниже %d%%" % (limit[1], limit[0])
    elif status == "Full" or cap >= 99:
        power = "от сети, заряжена"
    else:
        power = "от сети, не заряжается"

    left = ""
    if info["hours"] is not None:
        left = (" · ещё ≈ %s" if not on_ac else
                " · до лимита ≈ %s" if limit else " · до полного ≈ %s") % span(info["hours"])
    tooltip = "Батарея: %d%%%s\nПитание: %s\nРежим: %s" % (
        cap, left, power, "Savage (24/7)" if is_savage else "Standard")
    if awake:
        tooltip += "\nЭкран: не гаснет и не блокируется"

    print(json.dumps({"text": text, "tooltip": tooltip, "class": classes}))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--toggle":
        toggle_savage()
    else:
        get_battery_info()
