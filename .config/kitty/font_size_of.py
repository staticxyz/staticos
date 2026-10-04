# 24.09.2026. Отдаёт кегль шрифта OS-окна kitty — для dashboard save
# (запомнить масштаб, выставленный Ctrl+Shift+−/+). Вызов:
#   kitty @ --to unix:/tmp/kitty-PID kitten font_size_of.py /tmp/файл
# Кегль пишется в файл и возвращается строкой.
from kittens.tui.handler import result_handler


def main(args):
    pass


@result_handler(no_ui=True)
def handle_result(args, answer, target_window_id, boss):
    from kitty.fast_data_types import os_window_font_size
    w = boss.window_id_map.get(target_window_id)
    wid = w.os_window_id if w else next(iter(boss.os_window_map))
    sz = os_window_font_size(wid)
    if len(args) > 1:
        with open(args[1], "w") as f:
            f.write("%g" % sz)
    return "%g" % sz
