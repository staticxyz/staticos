#!/usr/bin/env python3
"""Push the matugen palette into every already-running terminal.

Kitty windows that were started before `listen_on` was configured have no
control socket, so the only way into them is the terminal's own OSC colour
escapes, written to the pty each window is attached to. This is what makes the
colours change without restarting anything.
"""
import os, sys, stat

CONF = os.path.expanduser("~/.cache/matugen/colors-kitty.conf")

# kitty.conf key -> OSC number
SINGLE = {
    "foreground": 10,
    "background": 11,
    "cursor": 12,
    "selection_background": 17,
    "selection_foreground": 19,
}


def read_palette(path):
    colors = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) == 2 and parts[1].startswith("#"):
                colors[parts[0]] = parts[1]
    return colors


def build_sequence(colors):
    out = []
    for name, osc in SINGLE.items():
        if name in colors:
            out.append(f"\033]{osc};{colors[name]}\033\\")
    for i in range(256):
        c = colors.get(f"color{i}")
        if c:
            out.append(f"\033]4;{i};{c}\033\\")
    return "".join(out).encode()


# Only these actually interpret OSC colour escapes. Anything else — an editor's
# embedded terminal, an Electron app holding a pty — may surface the raw escape
# string as text, which is how a wallpaper change once turned into a desktop
# notification full of "\033]10;#e3e1e9".
TERMINALS = {"kitty", "foot", "alacritty", "wezterm", "xterm", "konsole",
             "gnome-terminal-", "st", "urxvt"}
MAX_ANCESTRY = 12


def _comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def _ppid(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def _under_terminal(pid):
    """True when some ancestor of `pid` is a real terminal emulator."""
    seen = 0
    while pid > 1 and seen < MAX_ANCESTRY:
        if _comm(pid) in TERMINALS:
            return True
        pid = _ppid(pid)
        seen += 1
    return False


def own_ptys():
    uid = os.getuid()
    wanted = {}
    for name in os.listdir("/dev/pts"):
        if not name.isdigit():
            continue
        path = "/dev/pts/" + name
        try:
            st = os.stat(path)
        except OSError:
            continue
        # Only ptys this user owns — never write into someone else's terminal.
        if st.st_uid == uid and stat.S_ISCHR(st.st_mode):
            wanted[st.st_rdev] = path

    seen_devs = set()
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        # Controlling terminal from /proc/PID/stat, plus the three standard
        # descriptors as a fallback.
        #
        # stat has to come first: a process with elevated capabilities (btop
        # ships with cap_dac_read_search) has an unreadable /proc/PID/fd, so
        # the fd-only version silently skipped its window and it kept a stale
        # palette while every other terminal updated. tty_nr in stat uses the
        # same encoding as st_rdev and stays readable.
        devs = []
        try:
            data = open(f"/proc/{pid}/stat").read()
            devs.append(int(data[data.rindex(")") + 2:].split()[4]))
        except (OSError, ValueError, IndexError):
            pass
        for fd in (0, 1, 2):
            try:
                devs.append(os.stat(f"/proc/{pid}/fd/{fd}").st_rdev)
            except OSError:
                continue

        for dev in devs:
            if dev in wanted and dev not in seen_devs and _under_terminal(pid):
                seen_devs.add(dev)
                yield wanted[dev]
                break


def main():
    if not os.path.exists(CONF):
        return 0
    seq = build_sequence(read_palette(CONF))
    if not seq:
        return 0
    for path in own_ptys():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            os.write(fd, seq)
        except OSError:
            pass          # terminal gone or buffer full — nothing to do
        finally:
            os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
