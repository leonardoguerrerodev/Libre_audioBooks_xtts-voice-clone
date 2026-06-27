#!/bin/bash
# Lanza la GUI (Qt6) en Wayland nativo, sin XWayland.
# Usa el primer entorno que tenga PySide6 instalado:
#   venv_gui (entorno base recomendado) → venv_xtts → venv
DIR="$(dirname "$(readlink -f "$0")")"
export QT_QPA_PLATFORM=wayland

PY=""
for V in venv_gui venv_xtts venv; do
    CAND="$DIR/$V/bin/python"
    if [ -x "$CAND" ] && "$CAND" -c 'import PySide6' >/dev/null 2>&1; then
        PY="$CAND"; break
    fi
done

if [ -z "$PY" ]; then
    echo "✗ No encuentro un entorno con PySide6."
    echo "  Crea el entorno base de la GUI:"
    echo "      python3 -m venv venv_gui"
    echo "      venv_gui/bin/pip install -r requirements-gui.txt"
    read -p "Presiona ENTER para cerrar..."
    exit 1
fi

exec "$PY" "$DIR/gui.py" "$@"
