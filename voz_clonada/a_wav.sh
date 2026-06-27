#!/bin/bash
# ============================================================================
#  a_wav.sh — Convierte audio a .wav (mono, 24 kHz) limpio para XTTS-v2.
#
#  Uso:
#    ./a_wav.sh archivo.ogg                 → 1 archivo: lo convierte a .wav
#    ./a_wav.sh parte1.ogg parte2.ogg ...   → varios: los UNE en un solo .wav
#    (o arrastra los audios sobre  a_wav.desktop )
#
#  Con varios archivos se ordenan por su número (1, 2, 3...) y se concatenan
#  en una sola muestra continua — ideal para juntar tomas de una misma voz.
#  Formatos: ogg, mp3, m4a, flac, opus, aac, wav, etc.
# ============================================================================

set -u
SR=24000          # sample rate mono — el que usa el proyecto para XTTS

# Limpieza por toma (sin loudnorm: el volumen se nivela al final, una vez):
#   highpass=70 → quita retumbe de baja frecuencia
#   afftdn      → reductor de ruido de fondo suave
FILTROS_LIMPIEZA="highpass=f=70,afftdn=nf=-25"
#   loudnorm    → nivela el volumen SIN clipping (se aplica al resultado final)
LOUDNORM="loudnorm=I=-18:TP=-2:LRA=11"

B="\033[1m"; G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; N="\033[0m"

if ! command -v ffmpeg >/dev/null; then
    echo -e "${R}✗ ffmpeg no está instalado.${N}  Instálalo:  sudo dnf install ffmpeg"
    read -p "Presiona ENTER para cerrar..."
    exit 1
fi

if [ "$#" -eq 0 ]; then
    echo -e "${Y}Sin archivos.${N}  Uso: ./a_wav.sh audio1 [audio2 ...]"
    echo -e "  o arrastra los audios sobre  ${B}a_wav.desktop${N}"
    read -p "Presiona ENTER para cerrar..."
    exit 1
fi

# ── 1 SOLO ARCHIVO: conversión simple ───────────────────────────────────
if [ "$#" -eq 1 ]; then
    src="$1"
    if [ ! -f "$src" ]; then
        echo -e "${R}✗ No existe:${N} $src"
        read -p "Presiona ENTER para cerrar..."; exit 1
    fi
    dir="$(dirname "$src")"; base="$(basename "$src")"; stem="${base%.*}"
    dst="$dir/$stem.wav"
    echo -e "→ ${B}$base${N}  →  $stem.wav"
    if ffmpeg -hide_banner -loglevel error -y -i "$src" \
            -af "$FILTROS_LIMPIEZA,$LOUDNORM" -ar $SR -ac 1 -sample_fmt s16 "$dst"; then
        echo -e "  ${G}✓${N} $dst"
    else
        echo -e "  ${R}✗ Error al convertir${N} $src"
    fi
    echo ""
    read -p "Presiona ENTER para cerrar..."
    exit 0
fi

# ── VARIOS ARCHIVOS: ordenar por número y MERGEAR en uno solo ────────────
# Orden natural/versión: "scarlett1, scarlett2, scarlett10" en orden correcto,
# tolerando espacios y saltos de línea en las rutas.
mapfile -d '' SORTED < <(printf '%s\0' "$@" | sort -zV)

# Validar entradas
ENTRADAS=()
for src in "${SORTED[@]}"; do
    if [ -f "$src" ]; then
        ENTRADAS+=("$src")
    else
        echo -e "${R}✗ No existe (se omite):${N} $src"
    fi
done
if [ "${#ENTRADAS[@]}" -lt 2 ]; then
    echo -e "${R}✗ Se necesitan al menos 2 archivos válidos para unir.${N}"
    read -p "Presiona ENTER para cerrar..."; exit 1
fi

# Nombre de salida: stem del primero sin el número final  (scarlett1 → scarlett)
dir="$(dirname "${ENTRADAS[0]}")"
first_stem="$(basename "${ENTRADAS[0]}")"; first_stem="${first_stem%.*}"
out_stem="$(echo "$first_stem" | sed -E 's/[ _-]*[0-9]+$//')"
[ -z "$out_stem" ] && out_stem="voz_unida"
dst="$dir/$out_stem.wav"

echo -e "${B}Uniendo ${#ENTRADAS[@]} tomas en orden:${N}"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
listfile="$tmpdir/lista.txt"
: > "$listfile"

i=0; fail=0
for src in "${ENTRADAS[@]}"; do
    part="$(printf '%s/part_%03d.wav' "$tmpdir" "$i")"
    echo -e "  ${Y}$((i+1)).${N} $(basename "$src")"
    if ffmpeg -hide_banner -loglevel error -y -i "$src" \
            -af "$FILTROS_LIMPIEZA" -ar $SR -ac 1 -sample_fmt s16 "$part"; then
        printf "file '%s'\n" "$part" >> "$listfile"
    else
        echo -e "     ${R}✗ Error al procesar, se omite${N}"
        ((fail++))
    fi
    ((i++))
done

echo -e "→ ${B}$out_stem.wav${N}  (concatenando y nivelando volumen)"
if ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$listfile" \
        -af "$LOUDNORM" -ar $SR -ac 1 -sample_fmt s16 "$dst"; then
    echo -e "  ${G}✓${N} $dst"
else
    echo -e "  ${R}✗ Error al unir las tomas${N}"
fi

echo ""
echo -e "${G}Hecho.${N}  Para usarla como voz por defecto, renómbrala a clonada.wav"
read -p "Presiona ENTER para cerrar..."
