#!/usr/bin/env python3
"""Merge matugen's colour groups into ~/.config/kdeglobals.

kdeglobals also holds fonts, locale, click behaviour and other KDE-wide
settings, so it must never be replaced wholesale. KDE apps are told to re-read
the file right after this runs, so the write is atomic: they must never see a
half-written config.
"""
import os, sys, tempfile

HOME = os.path.expanduser("~")
SRC = os.path.join(HOME, ".cache/matugen/kdeglobals-colors")
DST = os.path.join(HOME, ".config/kdeglobals")


def parse(path):
    """-> (ordered list of group names, {group: {key: line}})"""
    order, groups, cur = [], {}, None
    if not os.path.exists(path):
        return order, groups
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line.startswith("[") and line.endswith("]"):
            cur = line
            if cur not in groups:
                order.append(cur)
                groups[cur] = {}
        elif cur is not None and "=" in line:
            groups[cur][line.split("=", 1)[0].strip()] = line
        elif cur is None and line.strip():
            pass  # stray comment before the first group
    return order, groups


def main():
    if not os.path.exists(SRC):
        return 0
    src_order, src_groups = parse(SRC)
    dst_order, dst_groups = parse(DST)

    for g in src_order:
        if g not in dst_groups:
            dst_order.append(g)
            dst_groups[g] = {}
        dst_groups[g].update(src_groups[g])

    out = []
    for g in dst_order:
        out.append(g)
        out.extend(dst_groups[g].values())
        out.append("")

    d = os.path.dirname(DST)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".kdeglobals-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(out).rstrip("\n") + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, DST)          # atomic
    except Exception:
        os.path.exists(tmp) and os.unlink(tmp)
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
