#!/usr/bin/env python3
"""Живая лупа: Super+Alt+колесо → зум самого niri (сборка niri-zoom, PR #3246).

  live_zoom.py in | out | reset

Шаг ×1.25 (сам считает, чтобы не нужен был блок zoom{} в конфиге), до ×10,
у ×1 — ровно 1. Экран при зуме живой, вид идёт за курсором (cursor-follow).
Если композитор зума не умеет (обычный niri 26.04 или ещё не перезаходили) —
старая застывшая лупа magnifier.py. 04.11.2026.
"""
import json
import os
import subprocess
import sys

STEP, MAX = 1.25, 10.0
HERE = os.path.dirname(os.path.abspath(__file__))


def niri(*args, ok_fail=False):
    r = subprocess.run(["niri", "msg", *args], capture_output=True, text=True, timeout=3)
    if r.returncode and not ok_fail:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout


def fallback(cmd):
    os.execvp("python3", ["python3", os.path.join(HERE, "magnifier.py"),
                          {"reset": "close"}.get(cmd, cmd)])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "in"
    if cmd not in ("in", "out", "reset"):
        print(__doc__.strip())
        return 2
    try:
        out = json.loads(niri("-j", "focused-output"))["name"]
        state = json.loads(niri("-j", "zoom-state")).get(out)
    except Exception:
        state = None
    if not state:
        fallback(cmd)
    level = float(state.get("level", 1.0))
    if cmd == "reset":
        new = 1.0
    elif cmd == "in":
        new = min(MAX, level * STEP)
    else:
        new = level / STEP
        if new < 1.08:
            new = 1.0
    if abs(new - level) < 1e-3:
        return 0
    locked = state.get("is_locked")
    if locked:                    # с замком set-zoom-level niri пропускает
        niri("action", "toggle-zoom-lock", out)
    niri("action", "set-zoom-level", f"{new:.4f}", out)
    if locked and new > 1.0:
        niri("action", "toggle-zoom-lock", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
