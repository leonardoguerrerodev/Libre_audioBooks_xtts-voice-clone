#!/usr/bin/env python3
# xtts_worker.py — Proceso XTTS-v2 RESIDENTE para previews rápidas.
#
# Carga el modelo UNA sola vez y se queda escuchando peticiones en stdin
# (una por línea, formato JSON). Así las pruebas de voz no recargan el
# modelo cada vez: la primera tarda (carga), las siguientes son casi
# instantáneas. Cachea los "latents" por voz (solo recalcula si cambias
# de muestra o si el .wav se modifica).
#
# Protocolo (stdout, líneas con prefijo):
#   @READY                  → modelo cargado, listo para peticiones
#   @DONE|<ruta.wav>        → petición completada
#   @ERR|<mensaje>          → error en la última petición
#
# Petición (stdin, JSON por línea):
#   {"text": "...", "voice": "/ruta.wav", "out": "/salida.wav",
#    "temperature": 0.8, "speed": 1.0, "repetition_penalty": 5.0, "top_p": 0.85}
#   {"cmd": "quit"}         → termina el worker

import os
import sys
import json

import numpy as np
import soundfile as sf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("TTS_HOME", os.path.join(BASE_DIR, "models"))
os.environ.setdefault("COQUI_TOS_AGREED", "1")

import audiobook_xtts as ax   # reutiliza la lógica de síntesis


def _say(marker):
    print(marker, flush=True)


def main():
    print("• Cargando modelo XTTS-v2 (worker residente)...", flush=True)
    model, device = ax.cargar_modelo()
    print(f"• Dispositivo: {device}", flush=True)
    _say("@READY")

    cache = {}   # voz_ref -> (mtime, latents)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            _say("@ERR|petición JSON inválida")
            continue
        if req.get("cmd") == "quit":
            break

        try:
            voz = req["voice"]
            texto = ax.limpiar_texto(req["text"])
            out = req["out"]
            if not os.path.isfile(voz):
                _say(f"@ERR|no existe la voz: {voz}")
                continue

            # latents cacheados por voz (recalcula si cambió el archivo)
            refs = ax._refs_de(voz)
            mtime = max(os.path.getmtime(r) for r in refs)
            key = voz
            if cache.get(key, (None,))[0] != mtime:
                print(f"• Analizando voz: {os.path.basename(voz)}", flush=True)
                cache[key] = (mtime, ax.calc_latentes(model, refs, verbose=False))
            latents = cache[key][1]

            params = ax.params_actuales({
                "temperature": req.get("temperature"),
                "speed": req.get("speed"),
                "repetition_penalty": req.get("repetition_penalty"),
                "top_p": req.get("top_p"),
            })

            # frase corta: un solo fragmento basta para la preview
            seg = ax.inferir(model, latents, texto, params)
            sf.write(out, ax.normaliza_pico(seg), ax.SR)
            _say(f"@DONE|{out}")
        except Exception as e:   # noqa: BLE001 — el worker no debe morir
            _say(f"@ERR|{e}")


if __name__ == "__main__":
    main()
