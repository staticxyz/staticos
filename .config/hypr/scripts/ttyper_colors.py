#!/usr/bin/env python3
"""ttyper в цветах обоев. 28.09.2026.

Собирает ~/.config/ttyper/config.toml из палитры matugen. ttyper принимает
24-битные цвета прямо в теме, поэтому подстраивается точно, а не «одним из
шестнадцати цветов терминала».

Роли выбраны по смыслу, а не по красоте:
  набранное верно  — обычный цвет текста, он не должен отвлекать;
  ошибки           — error из палитры (в тёмных темах это розово-красный);
  ненабранное      — приглушённый outline, чтобы впереди был виден путь,
                     но глаз цеплялся за текущее слово;
  текущее слово    — акцентом и жирным: это точка внимания;
  рамки и итоги    — акцент, как у остального рабочего стола.

Вызывается из theme_changer.sh. Уже запущенный ttyper цвета не перечитывает —
нужен перезапуск.
"""
import json
import os
import sys

COLORS = os.path.expanduser("~/.cache/matugen/colors.json")
OUT = os.path.expanduser("~/.config/ttyper/config.toml")

DEFAULT = {"primary": "#b4c5ff", "on_surface": "#e1e1ef", "error": "#ffb4ab",
           "outline": "#8e909c", "outline_variant": "#444651", "tertiary": "#d2bdf6"}


def main():
    try:
        with open(COLORS) as f:
            p = json.load(f)
    except (OSError, ValueError):
        p = {}
    c = {k: p.get(k, v) for k, v in DEFAULT.items()}

    body = f"""# СОБРАН АВТОМАТИЧЕСКИ скриптом ~/.config/hypr/scripts/ttyper_colors.py
# при каждой смене обоев. Правки здесь пропадут — правьте скрипт.

default_language = "english200"

[theme]
default = "none"
title = "{c['primary']};bold"

# Рамки — акцентом, но приглушённым: они обрамляют, а не тянут взгляд.
input_border = "{c['outline_variant']}"
prompt_border = "{c['outline_variant']}"
border_type = "rounded"

# Уже набранное верно — обычный текст, ошибки — цветом ошибки палитры,
# ещё не набранное — приглушённое.
prompt_correct = "{c['on_surface']}"
prompt_incorrect = "{c['error']};bold"
prompt_untyped = "{c['outline']}"

# Текущее слово — точка внимания, поэтому акцент и жирное начертание.
prompt_current_correct = "{c['primary']};bold"
prompt_current_incorrect = "{c['error']};bold"
prompt_current_untyped = "{c['tertiary']};bold"
prompt_cursor = "none;underlined"

# Итоги после заезда.
results_overview = "{c['primary']};bold"
results_overview_border = "{c['outline_variant']}"
results_worst_keys = "{c['error']};bold"
results_worst_keys_border = "{c['outline_variant']}"
results_chart = "{c['primary']}"
results_chart_x = "{c['primary']}"
results_chart_y = "{c['outline']};italic"
results_restart_prompt = "{c['outline']};italic"
"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(body)
    print(f"ttyper: акцент {c['primary']} → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
