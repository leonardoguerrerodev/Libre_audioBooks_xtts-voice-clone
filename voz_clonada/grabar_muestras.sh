#!/bin/bash
# ============================================================================
#  grabar_muestras.sh — Grabador guiado de muestras de voz para clonar con
#                       XTTS-v2.
#
#  Graba 3 muestras estratégicas (10s, 15s y 20s) con textos diseñados para
#  capturar la mayor variedad fonética y de entonación posible, y las une en
#  un único archivo de referencia:  clonada.wav
#
#  ── RECOMENDACIONES PARA UNA BUENA CLONACIÓN ───────────────────────────────
#   • Habitación SILENCIOSA: sin ventilador, TV, eco ni música de fondo.
#   • Micrófono a ~15-20 cm de la boca, fijo (no lo muevas mientras grabas).
#   • Habla con tu voz NATURAL, ritmo relajado, como si narraras un libro.
#   • No susurres ni grites: volumen de conversación normal y constante.
#   • Lee el texto completo SIN prisa; si te trabas, repite la muestra (opción r).
#   • Evita golpes en la mesa, respiraciones fuertes pegadas al micro y la "p"/"b"
#     explosiva (aléjate un poco o ponte de lado del micrófono).
#  ───────────────────────────────────────────────────────────────────────────
# ============================================================================

set -u
DIR="$(dirname "$(readlink -f "$0")")"
cd "$DIR" || exit 1

SR=24000          # sample rate (mono) — ideal para XTTS
SALIDA="clonada.wav"

# ── Colores ──────────────────────────────────────────────────────────────
B="\033[1m"; G="\033[1;32m"; Y="\033[1;33m"; C="\033[1;36m"; R="\033[1;31m"; N="\033[0m"

# ── Detección del grabador disponible ────────────────────────────────────
# Devuelve por la función REC: graba exactamente $1 segundos en $2
detectar_grabador() {
    if command -v ffmpeg >/dev/null && ffmpeg -hide_banner -f pulse -i default -t 0.1 \
            -ar $SR -ac 1 -y /tmp/_test_rec.wav >/dev/null 2>&1; then
        rm -f /tmp/_test_rec.wav
        echo "ffmpeg-pulse"; return
    fi
    if command -v arecord >/dev/null; then echo "arecord"; return; fi
    if command -v ffmpeg  >/dev/null; then echo "ffmpeg-pulse"; return; fi
    echo "ninguno"
}

GRABADOR="$(detectar_grabador)"
if [ "$GRABADOR" = "ninguno" ]; then
    echo -e "${R}No encontré un grabador de audio (ffmpeg/arecord).${N}"
    read -p "Enter para salir..."; exit 1
fi

# Lanza la grabación en segundo plano (no bloquea), guarda PID en REC_PID
iniciar_grabacion() {
    local dur="$1" out="$2"
    case "$GRABADOR" in
        ffmpeg-pulse)
            ffmpeg -hide_banner -loglevel error -y -f pulse -i default \
                   -t "$dur" -ar $SR -ac 1 "$out" >/dev/null 2>&1 &
            ;;
        arecord)
            arecord -q -d "$dur" -f S16_LE -r $SR -c 1 "$out" >/dev/null 2>&1 &
            ;;
    esac
    REC_PID=$!
}

# Cuenta regresiva visual sincronizada con la grabación
contador_visual() {
    local dur="$1"
    for ((s=dur; s>=1; s--)); do
        local llenos=$(( (dur - s) * 30 / dur ))
        local barra=""
        for ((i=0;i<30;i++)); do
            if (( i < llenos )); then barra+="█"; else barra+="·"; fi
        done
        printf "\r  ${G}● GRABANDO${N} [${barra}] ${B}%2d s${N} restantes " "$s"
        sleep 1
    done
    printf "\r  ${C}● procesando...${N}                                              \n"
}

# Graba una muestra: cuenta 3-2-1, graba $1 seg en $2, espera a que termine
grabar() {
    local dur="$1" out="$2"
    echo ""
    echo -ne "  Empezamos en ${Y}3${N}... "; sleep 0.8
    echo -ne "${Y}2${N}... ";               sleep 0.8
    echo -ne "${Y}1${N}... ";               sleep 0.8
    echo -e  "${G}¡YA!${N}"
    iniciar_grabacion "$dur" "$out"
    contador_visual "$dur"
    wait "$REC_PID" 2>/dev/null
}

# ── Textos estratégicos ──────────────────────────────────────────────────
# Pensados para cubrir todos los fonemas del español + variedad de entonación
# (afirmativa, interrogativa, exclamativa, números y ritmo pausado).
TXT1="El veloz murciélago hindú comía feliz cardillo y kiwi. La cigüeña tocaba el saxofón detrás del palenque de paja."
TXT2="¿Qué hora es exactamente? ¿Crees que llegaremos a tiempo al teatro? Jamás imaginé que un jueves cualquiera pudiera cambiarlo todo. Mira bien, escucha con calma y dime qué piensas tú."
TXT3="¡Increíble! Nunca había visto algo semejante. En mil novecientos noventa y nueve, treinta y siete viajeros cruzaron el río al amanecer. Habló despacio, con voz grave y serena, mientras la lluvia golpeaba el viejo tejado de zinc. Respira hondo: esto apenas comienza."

DURS=(10 15 20)
TXTS=("$TXT1" "$TXT2" "$TXT3")
ARCHS=("muestra_1_10s.wav" "muestra_2_15s.wav" "muestra_3_20s.wav")
NOTAS=("Entonación NEUTRA y clara (lectura normal)." \
       "Marca bien las PREGUNTAS: sube el tono al final de cada '¿...?'" \
       "Pon EMOCIÓN: la exclamación con energía, los números con calma.")

# ── Intro ────────────────────────────────────────────────────────────────
clear
echo -e "${C}╔════════════════════════════════════════════════════════════╗${N}"
echo -e "${C}║       GRABACIÓN DE MUESTRAS DE VOZ  ·  XTTS-v2 clon         ║${N}"
echo -e "${C}╚════════════════════════════════════════════════════════════╝${N}"
echo ""
echo -e "  Vamos a grabar ${B}3 muestras${N} (10s, 15s y 20s) y unirlas en"
echo -e "  ${B}${SALIDA}${N} para clonar tu voz."
echo ""
echo -e "  ${Y}Recomendaciones:${N}"
echo -e "   • Habitación en silencio, micro a ~15-20 cm, fijo."
echo -e "   • Voz natural y constante, ritmo de narrador, sin prisa."
echo -e "   • Si te trabas, podrás repetir la muestra al terminar."
echo ""
echo -e "  Grabador detectado: ${G}${GRABADOR}${N}"
echo ""
read -p "  Presiona ENTER cuando estés listo para empezar... "

# ── Bucle de grabación ───────────────────────────────────────────────────
for idx in 0 1 2; do
    dur="${DURS[$idx]}"; txt="${TXTS[$idx]}"; out="${ARCHS[$idx]}"; nota="${NOTAS[$idx]}"
    while true; do
        clear
        echo -e "${C}──────────────────────────────────────────────────────────────${N}"
        echo -e "  ${B}MUESTRA $((idx+1)) de 3${N}   ·   duración: ${B}${dur} segundos${N}"
        echo -e "${C}──────────────────────────────────────────────────────────────${N}"
        echo ""
        echo -e "  ${Y}» $nota${N}"
        echo ""
        echo -e "  ${B}LEE ESTE TEXTO en voz alta:${N}"
        echo ""
        echo -e "  ${C}┌────────────────────────────────────────────────────────┐${N}"
        # imprime el texto con sangría, ajustado a ~56 columnas
        echo "$txt" | fold -s -w 54 | while IFS= read -r linea; do
            printf "  ${C}│${N} %-54s ${C}│${N}\n" "$linea"
        done
        echo -e "  ${C}└────────────────────────────────────────────────────────┘${N}"
        echo ""
        echo -e "  Consejo: lee TODO el recuadro a ritmo pausado; está medido"
        echo -e "  para encajar en ~${dur}s. Si sobra audio, no pasa nada."
        echo ""
        read -p "  Presiona ENTER para COMENZAR A GRABAR... "
        grabar "$dur" "$out"

        echo ""
        echo -e "  ${G}✓ Muestra guardada:${N} $out"
        # reproducir para revisar
        if command -v paplay >/dev/null;  then REPRO="paplay";
        elif command -v ffplay >/dev/null; then REPRO="ffplay -autoexit -nodisp -loglevel error";
        elif command -v aplay >/dev/null;  then REPRO="aplay -q";
        else REPRO=""; fi
        if [ -n "$REPRO" ]; then
            echo -ne "  ¿Reproducir para revisar? [Enter=sí / n=no] "
            read -r resp
            [ "$resp" != "n" ] && $REPRO "$out" >/dev/null 2>&1
        fi
        echo ""
        echo -ne "  ¿Te gustó? [Enter=continuar / ${Y}r${N}=repetir esta muestra] "
        read -r resp
        [ "$resp" = "r" ] || break
    done
done

# ── Unir las 3 muestras en clonada.wav ───────────────────────────────────
echo ""
echo -e "${C}──────────────────────────────────────────────────────────────${N}"
echo -e "  Uniendo las 3 muestras en ${B}${SALIDA}${N} ..."
if command -v sox >/dev/null; then
    sox "${ARCHS[@]}" "$SALIDA" 2>/dev/null
elif command -v ffmpeg >/dev/null; then
    printf "file '%s'\n" "${ARCHS[@]}" > _lista.txt
    ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i _lista.txt \
           -ar $SR -ac 1 "$SALIDA"
    rm -f _lista.txt
fi

if [ -f "$SALIDA" ]; then
    echo -e "  ${G}✓ Listo:${N} $DIR/$SALIDA"
    echo -e "    (~45 s de referencia, listo para XTTS-v2)"
else
    echo -e "  ${R}✗ No se pudo crear $SALIDA — revisa que sox o ffmpeg estén instalados.${N}"
fi
echo ""
read -p "  Presiona ENTER para cerrar..."
