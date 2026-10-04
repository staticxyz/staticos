#!/bin/bash
if [ "$1" = "cancel" ]; then
    pkill -f "vol_timer.sh wait" 2>/dev/null
elif [ "$1" = "wait" ]; then
    pkill -f "vol_timer.sh wait" 2>/dev/null
    sleep 2
    eww close volume-sidebar 2>/dev/null
fi
