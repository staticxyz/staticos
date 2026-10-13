#!/usr/bin/env python3
"""Вид KeePassXC в стиле системы — Default / Skeet / Beta (13.10.2026).

    keepassxc_style.py sync     пересобрать ~/.config/qt5ct/qss/jarvis.qss
    keepassxc_style.py check    совпадает ли файл с выбранным стилем; rc 1 — нет
    keepassxc_style.py off      пустой файл (KeePassXC — просто палитра обоев)

Просьба: «Я не вижу чтоб он был оформлен под стиль системы». Пакет на Qt5, запускается
обёрткой ~/.local/bin/keepassxc с QT_QPA_PLATFORMTHEME=qt5ct — а qt5ct сам накладывает
таблицу стилей из [Interface] stylesheets= в qt5ct.conf. qt5ct больше никто не читает
(остальные программы — qt6ct), так что таблица касается только KeePassXC. Стиль — монитора
MSI, если подключён, иначе ноутбука (как у Zen и микшеров):
  default — пустая таблица: Fusion в цветах обоев, как было;
  skeet   — квадратные углы, рамки в тёмную линию, полоска палитры над панелью
            инструментов, выделение — светлее поля с полоской акцента слева, как в Настройках;
  beta    — углы 6 px, рамки и выделение акцентом.
Новый вид — со следующего запуска KeePassXC (Qt5 не перечитывает QSS на лету).
Зовут: system_style.py set, theme_changer.sh (цвета обоев зашиты в таблицу).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
QSS = os.path.expanduser("~/.config/qt5ct/qss/jarvis.qss")
CONF = os.path.expanduser("~/.config/qt5ct/qt5ct.conf")
MONITORS = ("DP-4", "eDP-1")


def style():
    import system_style
    try:
        outs = system_style.outputs() or []
    except Exception:
        outs = []
    out = next((m for m in MONITORS if m in outs), outs[0] if outs else MONITORS[0])
    return system_style.style_of(out)


def mix(a, b, t):
    a, b = a.lstrip("#"), b.lstrip("#")
    return "#" + "".join("%02x" % round(int(a[i:i + 2], 16) * (1 - t) + int(b[i:i + 2], 16) * t)
                         for i in (0, 2, 4))


def palette():
    import start_menu
    import xpbar_colors
    c = start_menu.skeet_colors(xpbar_colors.colors())
    c["line1_on"] = mix(c["line1"], c["acc"], 0.45)
    return c


# Общий каркас; {r} — радиус, {edge} — цвет рамок полей и списков, {sel_edge} — полоска
# выделения слева, {stripe} — линия над панелью инструментов.
BASE = """/* стиль системы: {st} — файл пишет keepassxc_style.py, руками не править */
QMainWindow, QDialog {{ background: {bg}; }}
QWidget {{ color: {text}; selection-background-color: {field_l}; selection-color: {icon_on}; }}
QToolTip {{ background: {rail}; color: {text}; border: 1px solid {line1_on}; padding: 3px; }}

QToolBar {{ background: {rail}; border: none; border-top: 2px solid {stripe};
           border-bottom: 1px solid {line3}; padding: 2px; spacing: 2px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {r}px;
              padding: 3px; }}
QToolButton:hover {{ background: {field}; border-color: {line1}; }}
QToolButton:pressed, QToolButton:checked {{ background: {field_l}; border-color: {acc}; }}
/* кнопки с меню (замок, автоввод): своя часть со стрелкой — без чужой рамки Fusion */
QToolButton[popupMode="1"] {{ padding-right: 13px; }}
QToolButton::menu-button {{ background: transparent; border: none;
    border-left: 1px solid transparent; width: 12px; }}
QToolButton::menu-button:hover {{ background: {field}; border-left-color: {line1}; }}
QToolButton::menu-button:pressed {{ background: {field_l}; border-left-color: {acc}; }}
QToolButton::menu-indicator {{ subcontrol-origin: padding; subcontrol-position: bottom right;
    left: -1px; top: -1px; }}

QMenuBar {{ background: {rail}; border-bottom: 1px solid {line3}; }}
QMenuBar::item {{ background: transparent; padding: 3px 8px; }}
QMenuBar::item:selected {{ background: {field}; color: {icon_on}; }}
QMenu {{ background: {bg}; border: 1px solid {line1_on}; padding: 2px; }}
QMenu::item {{ padding: 4px 18px 4px 22px; border-left: 2px solid transparent; }}
QMenu::item:selected {{ background: {field_l}; color: {icon_on}; border-left-color: {acc}; }}
QMenu::item:disabled {{ color: {text_dim}; }}
QMenu::separator {{ height: 1px; background: {line2}; margin: 3px 6px; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDateTimeEdit {{
    background: {field}; border: 1px solid {line3}; border-radius: {r}px; padding: 3px 4px;
    selection-background-color: {acc_d}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus,
QDateTimeEdit:focus {{ border-color: {acc}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {text_dim}; background: {bg}; }}
QComboBox QAbstractItemView {{ background: {bg}; border: 1px solid {line1_on};
    selection-background-color: {field_l}; outline: 0; }}

QPushButton {{ background: {field}; border: 1px solid {line1}; border-radius: {r}px;
              padding: 4px 12px; min-height: 16px; }}
QPushButton:hover {{ background: {field_l}; border-color: {line1_on}; }}
QPushButton:pressed, QPushButton:checked {{ background: {acc_d}; border-color: {acc}; }}
QPushButton:default {{ border-color: {acc}; }}
QPushButton:disabled {{ color: {text_dim}; border-color: {line2}; }}

QTreeView, QTableView, QListView, QListWidget, QTreeWidget {{
    background: {field}; alternate-background-color: {bg}; border: 1px solid {edge};
    border-radius: {r}px; outline: 0; }}
QTreeView::item, QListView::item {{ padding: 2px; border-left: 2px solid transparent; }}
QTableView::item {{ padding: 2px; }}
QTreeView::item:hover, QTableView::item:hover, QListView::item:hover {{ background: {field_l}; }}
QTreeView::item:selected, QListView::item:selected {{
    background: {field_l}; color: {icon_on}; border-left-color: {sel_edge}; }}
QTableView::item:selected {{ background: {field_l}; color: {icon_on};
    border-top: 1px solid {line1_on}; border-bottom: 1px solid {line1_on}; }}
QHeaderView::section {{ background: {rail}; color: {text_dim}; border: none;
    border-right: 1px solid {line2}; border-bottom: 1px solid {line3}; padding: 3px 6px; }}
QHeaderView::section:hover {{ color: {text}; }}

QTabWidget::pane {{ border: 1px solid {edge}; border-radius: {r}px; top: -1px; }}
QTabBar::tab {{ background: {rail}; color: {text_dim}; border: 1px solid {line3};
    padding: 4px 12px; margin-right: 1px; }}
QTabBar::tab:selected {{ background: {field}; color: {icon_on}; border-top: 2px solid {acc}; }}
QTabBar::tab:hover:!selected {{ color: {text}; }}

QGroupBox {{ border: 1px solid {edge}; border-radius: {r}px; margin-top: 12px;
    padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {acc_l}; }}

QCheckBox::indicator, QRadioButton::indicator {{ width: 11px; height: 11px;
    background: {field}; border: 1px solid {line1}; }}
QRadioButton::indicator {{ border-radius: 6px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {acc};
    border-color: {acc_l}; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {acc}; }}

QScrollBar:vertical {{ background: {bg}; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: {bg}; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {line1}; border-radius: {r}px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {acc_d}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QProgressBar {{ background: {field}; border: 1px solid {line3}; border-radius: {r}px;
    text-align: center; }}
QProgressBar::chunk {{ background: {acc}; }}
QSplitter::handle {{ background: {line2}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}
QStatusBar {{ background: {rail}; border-top: 1px solid {line3}; color: {text_dim}; }}
"""


def build(st):
    if st not in ("skeet", "beta"):
        return "/* стиль системы: %s — KeePassXC как есть (палитра обоев) */\n" % st
    c = palette()
    if st == "skeet":
        stripe = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {acc}, stop:0.5 {tertiary}, "
                  "stop:1 {secondary})").format(**c)
        return BASE.format(st=st, r=0, edge=c["line3"], sel_edge=c["acc"], stripe=stripe, **c)
    return BASE.format(st=st, r=6, edge=c["acc_d"], sel_edge=c["acc"], stripe=c["acc"], **c)


def ensure_conf():
    """Строка stylesheets= в [Interface] qt5ct.conf указывает на нашу таблицу."""
    try:
        lines = open(CONF, encoding="utf-8").read().splitlines()
    except OSError:
        return False
    want = "stylesheets=" + QSS
    if want in lines:
        return True
    lines = [l for l in lines if not l.startswith("stylesheets=")]
    if "[Interface]" not in lines:
        lines += ["", "[Interface]"]
    lines.insert(lines.index("[Interface]") + 1, want)
    tmp = CONF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, CONF)
    return True


def write(text):
    os.makedirs(os.path.dirname(QSS), exist_ok=True)
    try:
        old = open(QSS, encoding="utf-8").read()
    except OSError:
        old = None
    if text != old:
        tmp = QSS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, QSS)
    return 0 if ensure_conf() else 1


def main(a):
    if a == ["sync"]:
        return write(build(style()))
    if a == ["off"]:
        return write(build("default"))
    if a == ["check"]:
        st = style()
        try:
            ok = open(QSS, encoding="utf-8").read() == build(st)
        except OSError:
            ok = False
        try:
            conf = ("stylesheets=" + QSS) in open(CONF, encoding="utf-8").read().splitlines()
        except OSError:
            conf = False
        print(json.dumps({"style": st, "qss_ok": ok, "conf_ok": conf}))
        return 0 if ok and conf else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
