"""Значки файлов, открытых в nvim, — общий справочник (21.10.2026).

Просьба: «иконки для .java, .php… на все популярные языки», «везде, где есть иконки».
Значки рисует md_icon.py (jarvis-nvim-<язык> в ~/.local/share/icons/hicolor, тёмная
плитка, рисунок в цвет обоев), а этот модуль только узнаёт язык по заголовку окна —
его берут нижняя панель (xpbar.py), Alt+Tab (alt_tab.py) и полосы стопки (stack_bars.py).

Заголовок nvim (autocmds.lua): «nvim A.md · B.java», текущий файл первым. Запущенный
до этого — от fish: «nvim АРГУМЕНТ ПАПКА» («nvim Junior\\ Рыцарь.md ~/D/P»).
"""
import os

PREFIX = "jarvis-nvim-"
TERMINALS = {"kitty", "foot", "alacritty", "org.wezfurlong.wezterm", "com.mitchellh.ghostty"}

EXT = {
    "md": "md", "markdown": "md",
    "java": "java",
    "py": "python", "pyw": "python", "pyi": "python",
    "php": "php",
    "rs": "rust",
    "go": "go",
    "rb": "ruby",
    "lua": "lua",
    "sh": "shell", "bash": "shell", "zsh": "shell", "fish": "shell",
    "kt": "kotlin", "kts": "kotlin",
    "c": "c", "h": "c",
    "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp", "hh": "cpp", "hxx": "cpp",
    "cs": "csharp",
    "html": "html", "htm": "html", "xml": "html", "svg": "html",
    "css": "css", "scss": "css", "sass": "css", "less": "css",
    "sql": "sql",
    "json": "json", "jsonc": "json",
    "yaml": "config", "yml": "config", "toml": "config", "ini": "config", "conf": "config",
    "kdl": "config", "cfg": "config",
    "js": "js", "mjs": "js", "cjs": "js", "jsx": "js",
    "ts": "ts", "tsx": "ts", "mts": "ts",
}
LANGS = sorted(set(EXT.values()))


def nvim_file(title):
    """Текущий файл nvim по заголовку окна или None (это не nvim)."""
    t = (title or "").strip()
    word, _sp, rest = t.partition(" ")
    if os.path.basename(word).lower() not in ("nvim", "vim") or not rest.strip():
        return None
    rest = rest.strip()
    if " · " in rest:
        return rest.split(" · ")[0]
    arg, _sp, cwd = rest.replace("\\ ", " ").rpartition(" ")
    return arg if arg and cwd.startswith(("~", "/")) else rest


def lang(name):
    _b, dot, ext = (name or "").rpartition(".")
    return EXT.get(ext.lower()) if dot else None


def icon(title, app_id=None):
    """Имя значка (jarvis-nvim-java…) для окна терминала с nvim или None."""
    if app_id is not None and app_id not in TERMINALS:
        return None
    lg = lang(nvim_file(title))
    return PREFIX + lg if lg else None
