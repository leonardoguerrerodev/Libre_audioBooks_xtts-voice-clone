#!/bin/bash
# ============================================================================
#  make_launchers.sh — Genera los lanzadores .desktop con la ruta REAL del
#  proyecto y los instala en el menú de aplicaciones.
#
#  Los .desktop del repo son plantillas con el marcador __APP_DIR__ (no llevan
#  rutas absolutas hardcodeadas). Este script lo sustituye por la carpeta donde
#  está el proyecto y copia los lanzadores a ~/.local/share/applications/.
#
#  Uso:  ./make_launchers.sh
# ============================================================================

set -e
APP_DIR="$(dirname "$(readlink -f "$0")")"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DEST"

# Plantillas (ruta relativa al proyecto)
TEMPLATES=(
  "xtts_gui.desktop"
  "txt2audio.desktop"
  "txt2audio_gpu.desktop"
  "ePub-TXT.desktop"
  "voz_clonada/a_wav.desktop"
)

echo "Proyecto: $APP_DIR"
echo "Instalando lanzadores en: $DEST"
for tpl in "${TEMPLATES[@]}"; do
  src="$APP_DIR/$tpl"
  [ -f "$src" ] || { echo "  ⚠ falta $tpl, se omite"; continue; }
  out="$DEST/$(basename "$tpl")"
  sed "s|__APP_DIR__|$APP_DIR|g" "$src" > "$out"
  chmod +x "$out"
  echo "  ✓ $(basename "$tpl")"
done

# Refrescar la base de datos de .desktop si la herramienta existe
command -v update-desktop-database >/dev/null && \
  update-desktop-database "$DEST" 2>/dev/null || true

echo "Hecho. Busca los lanzadores en tu menú de aplicaciones."
