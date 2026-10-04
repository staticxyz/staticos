#!/usr/bin/env bash
# Переключатель окон — вся логика в window_switcher.py (см. его шапку).
exec python3 $HOME/.config/hypr/scripts/window_switcher.py "$@"
