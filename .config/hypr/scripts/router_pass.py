"""Сохранить пароль админки роутера для плашки «Сеть» (08.10.2026).

Пароль вводится скрыто и пишется в ~/.config/hypr/state/router-pass с правами 600,
чтобы не проходить через чат. Удалить: rm ~/.config/hypr/state/router-pass
"""
import getpass
import os

PATH = os.path.expanduser("~/.config/hypr/state/router-pass")
pw = getpass.getpass("Пароль админки роутера 192.168.0.1: ")
if not pw:
    raise SystemExit("Пусто — ничего не сохранено")
os.makedirs(os.path.dirname(PATH), exist_ok=True)
fd = os.open(PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(pw)
os.chmod(PATH, 0o600)
print("Сохранено:", PATH)
