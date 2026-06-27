cat > ~/Documentos/\!GitHub/\!XTTS/epub2tts.sh << 'EOF'
#!/bin/bash

EPUB="$1"
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
VENV="$SCRIPT_DIR/venv"

if [ -z "$EPUB" ]; then
    echo "Arrastra un epub encima de este script."
    read -p "Presiona Enter para cerrar..."
    exit 1
fi

source "$VENV/bin/activate"
python "$SCRIPT_DIR/epub_to_tts.py" "$EPUB"

echo ""
echo "Listo. Presiona Enter para cerrar..."
read
EOF

chmod +x ~/Documentos/\!GitHub/\!XTTS/epub2tts.sh
