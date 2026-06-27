#!/bin/bash
# txt2audio.sh — activa el venv y convierte un .txt en audio (.wav) con Kokoro.
# Uso:  arrastra un archivo .txt encima del .desktop, o:
#       ./txt2audio.sh archivo.txt

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
VENV="$SCRIPT_DIR/venv"
TXT="$1"

if [ -z "$TXT" ]; then
    echo "Arrastra un archivo .txt encima de este script (o pásalo como argumento)."
    read -p "Presiona Enter para cerrar..."
    exit 1
fi

if [ ! -f "$TXT" ]; then
    echo "No existe el archivo: $TXT"
    read -p "Presiona Enter para cerrar..."
    exit 1
fi

# salida .wav junto al .txt, mismo nombre base
OUT="${TXT%.*}.wav"

source "$VENV/bin/activate"
python "$SCRIPT_DIR/audiobook.py" "$TXT" "$OUT"
STATUS=$?

echo ""
if [ $STATUS -eq 0 ]; then
    echo "✓ Audio generado: $OUT"
else
    echo "✗ Hubo un error (código $STATUS)."
fi
read -p "Presiona Enter para cerrar..."
