#!/bin/bash
# Lanza la GUI (Qt6) en Wayland nativo, sin XWayland.
DIR="$(dirname "$(readlink -f "$0")")"
export QT_QPA_PLATFORM=wayland
exec "$DIR/venv_xtts/bin/python" "$DIR/gui.py" "$@"
