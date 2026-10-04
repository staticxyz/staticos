#!/usr/bin/env python3
"""Catch Hyprland's "Application Not Responding" dialog and photograph the scene.

Hyprland shows the dialog after `misc:anr_missed_pings` unanswered Wayland
pings but logs nothing about it, and by the time a human looks the app has
usually recovered. This watches for the dialog process and, the moment it
appears, dumps the offending app's stacks plus the system state that might
explain the stall.

Needs kernel.yama.ptrace_scope=0 for the stack traces; everything else works
without it.
"""
import json, os, re, subprocess, sys, time
from datetime import datetime

OUT = os.path.expanduser("~/.local/state/anr-traps")
POLL = 2.0   # light touch: this scans /proc, and it must not add load
TEXT_RE = re.compile(r"An application (.+?) is not responding")


def sh(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"<{e}>"


def find_dialogs():
    """-> [(dialog_pid, subject)] for every live ANR dialog.

    There can be several at once, and an un-dismissed one sticks around for
    hours — so they all have to be walked, not just the first found.
    """
    found = []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            with open(f"/proc/{entry.name}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", "replace").replace("\0", " ")
        except OSError:
            continue
        if "hyprland-dialog" not in cmd or "Not Responding" not in cmd:
            continue
        m = TEXT_RE.search(cmd)
        found.append((int(entry.name), m.group(1).strip() if m else "?"))
    return found


def resolve_pid(subject):
    """The dialog says '<title> - <class>'; hyprctl knows the pid for a class."""
    cls = subject.rsplit(" - ", 1)[-1].strip()
    try:
        clients = json.loads(sh("hyprctl clients -j"))
    except Exception:
        return None, cls, []
    hits = [c for c in clients if c.get("class") == cls]
    return (hits[0].get("pid") if hits else None), cls, hits


def threads(pid):
    out = []
    try:
        tids = sorted(os.listdir(f"/proc/{pid}/task"), key=int)
    except OSError:
        return ["<нет доступа>"]
    for tid in tids:
        try:
            stat = open(f"/proc/{pid}/task/{tid}/stat").read()
            state = stat.split(") ", 1)[1].split()[0]
            name = stat.split("(", 1)[1].rsplit(")", 1)[0]
            wchan = open(f"/proc/{pid}/task/{tid}/wchan").read().strip()
        except OSError:
            continue
        out.append(f"  tid {tid:<8} {state}  {name:<18} wchan={wchan}")
    return out


def capture(subject):
    pid, cls, hits = resolve_pid(subject)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(OUT, f"anr-{ts}-{cls.replace('/', '_')}.txt")
    w = open(path, "w", encoding="utf-8")

    def sec(title, body):
        w.write(f"\n===== {title} =====\n{body}\n")

    w.write(f"ANR пойман: {datetime.now().isoformat(timespec='seconds')}\n")
    w.write(f"диалог говорит: {subject}\nclass={cls}  pid={pid}\n")

    if pid:
        sec("процесс", sh(f"ps -o pid,stat,%cpu,%mem,etime,wchan:32,cmd -p {pid}"))
        sec("потоки (state / wchan)", "\n".join(threads(pid)) or "<пусто>")
        sec("память процесса", sh(f"grep -E 'VmRSS|VmSwap|Threads|voluntary' /proc/{pid}/status"))
        # The decisive evidence for the GTK4/Vulkan freeze was here: a clock app
        # holding dozens of fds on the discrete GPU.
        sec("GPU-дескрипторы", sh(
            f"ls -l /proc/{pid}/fd 2>/dev/null | grep -oE '/dev/(dri/[a-z0-9]+|nvidia[a-z0-9-]*)' "
            f"| sort | uniq -c || echo '<нет>'"))
        sec("рендерер из окружения", sh(
            f"tr '\\0' '\\n' < /proc/{pid}/environ 2>/dev/null "
            f"| grep -E 'GSK_RENDERER|QT_QUICK_BACKEND|QSG_|LIBGL|__GLX|__NV|MESA' || echo '<не задано>'"))
        # The interesting one: where is it actually stuck.
        sec("стек (eu-stack)", sh(f"eu-stack -p {pid}", timeout=30))
        sec("D-Bus ping (жив ли вообще)",
            sh(f"timeout 5 gdbus call --session --dest $(busctl --user --list --no-legend 2>/dev/null "
               f"| awk '$2=={pid}{{print $1; exit}}') --object-path / "
               f"--method org.freedesktop.DBus.Peer.Ping"))
    else:
        sec("процесс", "pid по классу не нашёлся — окно уже закрыто?")

    sec("окно в hyprctl", json.dumps(hits, ensure_ascii=False, indent=2)[:4000])
    sec("нагрузка", sh("uptime", timeout=5))
    sec("память", sh("free -h; echo; swapon --show"))
    sec("PSI (cpu/io/memory)",
        sh("for f in cpu io memory; do echo \"--- $f\"; cat /proc/pressure/$f; done"))
    sec("топ по CPU", sh("ps -eo pid,%cpu,%mem,comm --sort=-%cpu | head -12"))
    sec("топ по памяти", sh("ps -eo pid,rss,%mem,comm --sort=-rss | head -8", timeout=5))
    w.close()
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    seen = set()
    print(f"anr_trap: слежу за ANR-диалогами, отчёты в {OUT}", flush=True)
    while True:
        dialogs = find_dialogs()
        live = {pid for pid, _ in dialogs}
        for pid, subject in dialogs:
            if pid in seen:
                continue
            seen.add(pid)
            try:
                print(f"anr_trap: поймал -> {capture(subject)}", flush=True)
            except Exception as e:
                print(f"anr_trap: сбой при снятии: {e}", flush=True)
        seen &= live          # forget dialogs the user has dismissed
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
