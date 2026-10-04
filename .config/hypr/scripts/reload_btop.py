#!/usr/bin/env python3
"""Tell every running btop to re-read its (freshly generated) theme.

btop prints 24-bit colour taken from the theme file it read at startup, so it
ignores the terminal palette entirely. Its Ctrl+R binding reloads the config
from disk, which re-applies the theme — so the window keeps its place and its
history instead of being restarted.
"""
import json, os, subprocess, glob


def kitty(sock, *args):
    try:
        r = subprocess.run(["kitty", "@", "--to", f"unix:{sock}", *args],
                           capture_output=True, text=True, timeout=5)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def main():
    for sock in glob.glob("/tmp/kitty-*"):
        if not os.path.exists(sock):
            continue
        out = kitty(sock, "ls")
        if not out:
            continue
        try:
            osw = json.loads(out)
        except ValueError:
            continue
        for os_window in osw:
            for tab in os_window.get("tabs", []):
                for w in tab.get("windows", []):
                    procs = w.get("foreground_processes", [])
                    # Only when btop is the foreground process: sending keys to
                    # a shell prompt or an editor would be rude.
                    if not any(p.get("cmdline") and
                               os.path.basename(p["cmdline"][0]) == "btop"
                               for p in procs):
                        continue
                    kitty(sock, "send-key", "--match", f"id:{w['id']}", "ctrl+r")


if __name__ == "__main__":
    main()
