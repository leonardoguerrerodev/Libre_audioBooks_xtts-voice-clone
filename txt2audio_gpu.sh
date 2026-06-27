#!/bin/bash
# txt2audio_gpu.sh — activa el venv y convierte un .txt en audio (.wav) con
# XTTS-v2 en la GPU, usando la voz clonada de voz_clonada/clonada.wav.
# Uso:  arrastra un .txt encima del .desktop, o:  ./txt2audio_gpu.sh archivo.txt

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
VENV="$SCRIPT_DIR/venv_xtts"
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
if [ ! -f "$SCRIPT_DIR/voz_clonada/clonada.wav" ]; then
    echo "Falta la voz clonada: voz_clonada/clonada.wav"
    echo "Genérala primero con:  voz_clonada/grabar_muestras.sh"
    read -p "Presiona Enter para cerrar..."
    exit 1
fi

OUT="${TXT%.*}.wav"

source "$VENV/bin/activate"
python "$SCRIPT_DIR/audiobook_xtts.py" "$TXT" "$OUT"
STATUS=$?

echo ""
if [ $STATUS -eq 0 ]; then
    echo "✓ Audio generado: $OUT"
else
    echo "✗ Hubo un error (código $STATUS)."
fi
read -p "Presiona Enter para cerrar..."
