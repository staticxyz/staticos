#!/usr/bin/env python3
"""Полоска правого микшера eww на своём мониторе (27.10.2026).

    eww_edge_watch.py          сторож (в хозяине staticOS): раз в 5 с
    eww_edge_watch.py check    полоска на месте? (0 — да)
    eww_edge_watch.py fix      пересоздать окна eww сейчас

Просьба: «опять пропал боковой микшер, он всегда пропадает, когда ты что-то правишь». Окно
volume-trigger (eww.yuck, :monitor '["MAG 255XF", 0]') eww в списке открытых держит, а
поверхность после «eww reload» или переподключения MSI (смена режима, сон, Savage) оказывается
на экране ноутбука или пропадает вовсе — правый край MSI не отзывается. barfix лечил это
вручную; теперь сторож сам: два замера подряд не на том мониторе → eww close/open.
Поверхности eww в niri — пространство имён «gtk-layer-shell» на слое Overlay.
Откат: убрать из ~/.config/hypr/state/staticos-host.json.
"""
import json
import os
import socket
import subprocess
import sys
import time

MSI = "MAG 255XF"
NS = "gtk-layer-shell"
OPEN = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "eww-vol.open")


def ipc(req):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(os.environ["NIRI_SOCKET"])
            s.sendall(json.dumps(req).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(1 << 16)
                if not chunk:
                    break
                buf += chunk
        return (json.loads(buf).get("Ok") or {}).get(req)
    except (OSError, KeyError, ValueError, AttributeError):
        return None


def eww_running():
    out = subprocess.run(["ps", "-u", str(os.getuid()), "-o", "comm="], capture_output=True,
                         text=True, timeout=3).stdout
    return "eww" in out.split()


def state():
    """None — не знаем (нет niri/eww); иначе (нужный монитор, мониторы с поверхностями eww)."""
    outs, layers = ipc("Outputs"), ipc("Layers")
    if not outs or layers is None:
        return None
    want = next((n for n, o in outs.items() if MSI in (o.get("model") or "")), None)
    have = [l["output"] for l in layers if l.get("namespace") == NS and l.get("layer") == "Overlay"]
    return want, have


def wrong(st):
    want, have = st
    if want is None:                       # без MSI eww берёт первый монитор — лишь бы была
        return not have
    return want not in have or any(o != want for o in have)


def fix():
    names = subprocess.run(["eww", "active-windows"], capture_output=True, text=True,
                           timeout=10).stdout
    wins = [ln.split(":")[0].strip() for ln in names.splitlines() if ln.strip()]
    if "volume-trigger" not in wins:
        wins.append("volume-trigger")
    for w in wins:
        subprocess.run(["eww", "close", w], capture_output=True, timeout=10)
        subprocess.run(["eww", "open", w], capture_output=True, timeout=10)
    return wins


def watch():
    bad, gave_up = 0, None
    while True:
        time.sleep(5)
        try:
            st = state()
            # шторка микшера открыта — это её поверхность, не трогаем
            if st is None or os.path.exists(OPEN) or not wrong(st) or not eww_running():
                bad, gave_up = 0, None
                continue
            if st == gave_up:              # пересоздание не помогло — ждём, пока что-то сменится
                continue
            bad += 1
            if bad >= 2:                   # 10 с подряд: «eww reload» успевает доделать своё
                wins = fix()
                print("eww_edge_watch: пересоздал %s (было %s)" % (", ".join(wins), st[1]),
                      flush=True)
                bad = 0
                time.sleep(10)
                after = state()
                if after is not None and wrong(after):
                    gave_up = after
        except Exception as e:             # сторож в хозяине: не падать из-за одного сбоя
            print("eww_edge_watch:", e, flush=True)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "watch"
    if arg == "watch":
        watch()
        return 0
    if arg == "fix":
        print("пересоздано:", ", ".join(fix()))
        return 0
    if arg == "check":
        st = state()
        if st is None:
            print(json.dumps({"ok": True, "note": "niri недоступен"}))
            return 0
        ok = not eww_running() or not wrong(st)
        print(json.dumps({"ok": ok, "want": st[0], "eww_on": st[1]}, ensure_ascii=False))
        return 0 if ok else 1
    print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
