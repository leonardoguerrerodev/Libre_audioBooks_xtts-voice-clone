#!/bin/bash
# ============================================================================
#  install_backend.sh — Instala BAJO DEMANDA un motor de síntesis en su venv.
#
#  Uso:  ./install_backend.sh cpu     # Kokoro (voz fija, CPU)  → venv/
#        ./install_backend.sh gpu     # XTTS-v2 (voz clonada)   → venv_xtts/
#
#  Lo invoca la GUI al elegir el modelo de voz si ese backend aún no está
#  instalado. Crea el venv, instala el PyTorch correcto (índice +cpu o cu124)
#  y las dependencias del requirements correspondiente.
# ============================================================================

set -e
DIR="$(dirname "$(readlink -f "$0")")"
BACKEND="${1:-}"

case "$BACKEND" in
  cpu)
    VENV="venv"
    TORCH=(torch==2.12.1+cpu torchaudio==2.11.0+cpu)
    INDEX="https://download.pytorch.org/whl/cpu"
    REQ="requirements-cpu.txt"
    NOMBRE="CPU · Kokoro"
    ;;
  gpu)
    VENV="venv_xtts"
    TORCH=(torch==2.6.0+cu124 torchaudio==2.6.0+cu124)
    INDEX="https://download.pytorch.org/whl/cu124"
    REQ="requirements-gpu.txt"
    NOMBRE="GPU · XTTS-v2"
    ;;
  *)
    echo "Uso: $0 cpu|gpu"
    exit 2
    ;;
esac

PY="${PYTHON:-python3}"
VENV_DIR="$DIR/$VENV"

echo "==> Instalando backend $NOMBRE en $VENV/"
echo "==> Python base: $($PY --version 2>&1)"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "==> Creando entorno virtual: $VENV/"
  "$PY" -m venv "$VENV_DIR"
fi

VPY="$VENV_DIR/bin/python"
echo "==> Actualizando pip..."
"$VPY" -m pip install --upgrade pip

echo "==> Instalando PyTorch (${TORCH[*]})..."
"$VPY" -m pip install "${TORCH[@]}" --index-url "$INDEX"

echo "==> Instalando dependencias de $REQ..."
"$VPY" -m pip install -r "$DIR/$REQ"

echo "==> ✓ Backend $NOMBRE instalado correctamente en $VENV/"
