# voz_clonada

Carpeta de la voz de referencia para clonar con **XTTS-v2**.

## Archivos
- `grabar_muestras.sh` — grabador guiado. Graba 3 muestras (10s, 15s, 20s) con
  textos estratégicos y las une en `clonada.wav`.
- `clonada.wav` — **ruta fija** que usa `audiobook_xtts.py` como voz de referencia.
- `muestra_1_10s.wav`, `muestra_2_15s.wav`, `muestra_3_20s.wav` — muestras crudas.

## Cómo grabar tu voz
```bash
cd "$(dirname "$0")"        # o entra a la carpeta del proyecto
./voz_clonada/grabar_muestras.sh
```
El script te muestra cada texto, espera a que pulses ENTER para empezar a grabar,
y te enseña una cuenta regresiva mientras graba. Al final crea `clonada.wav`.

## Consejos para mejor clonación
- Habitación en silencio, micro fijo a ~15-20 cm.
- Voz natural y constante, ritmo de narrador, sin prisa.
- Si una toma sale mal, pulsa `r` para repetirla.
- Más adelante puedes regrabar cuando quieras; solo sobrescribe `clonada.wav`.
