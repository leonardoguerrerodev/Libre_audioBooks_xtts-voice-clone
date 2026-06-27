#!/usr/bin/env python3
# audiobook.py — Kokoro CPU, anti-artifacts config

import re
import sys
import random
import numpy as np
import soundfile as sf
from kokoro import KPipeline

# ── CONFIG ─────────────────────────────────────────────
LANG        = 'e'         # español
VOICE       = 'ef_dora'   # única voz española femenina Grade-A
SPEED       = 0.95        # ligeramente más lento → menos artefactos en CPU
SEED        = 42          # seed fijo → timbre consistente entre chunks
MAX_CHARS   = 180         # límite por chunk (debajo del umbral de artefactos)
SR          = 24000       # sample rate de Kokoro

PAUSA_ORACION  = 0.20     # segundos entre oraciones
PAUSA_PARRAFO  = 0.55     # segundos entre párrafos
FADE_MS        = 8        # fade-in/out en ms para suavizar uniones
# ───────────────────────────────────────────────────────

def set_seed(s):
    random.seed(s)
    np.random.seed(s)
    try:
        import torch; torch.manual_seed(s)
    except Exception:
        pass

def _prog(phase, value, extra=""):
    """Marcador de progreso legible por la GUI:  @PROGRESS|fase|valor|extra"""
    print(f"@PROGRESS|{phase}|{value}|{extra}", flush=True)


def silencio(seg):
    return np.zeros(int(SR * seg), dtype=np.float32)

def fade(audio, ms=FADE_MS):
    """fade-in y fade-out corto para eliminar clicks en uniones"""
    n = int(SR * ms / 1000)
    if len(audio) < n * 2:
        return audio
    ramp = np.linspace(0, 1, n)
    audio[:n]  *= ramp
    audio[-n:] *= ramp[::-1]
    return audio

def split_sentences(text):
    """
    Divide en oraciones respetando abreviaturas comunes en español.
    Nunca supera MAX_CHARS por chunk.
    """
    # normalizar em-dash → coma (Kokoro los ignora como límite)
    text = text.replace('—', ',').replace('–', ',')
    # dividir por puntuación fuerte
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = []
    buf = ''
    for s in raw:
        s = s.strip()
        if not s:
            continue
        if len(buf) + len(s) + 1 <= MAX_CHARS:
            buf = (buf + ' ' + s).strip()
        else:
            if buf:
                chunks.append(buf)
            # si una sola oración supera MAX_CHARS, dividir por coma
            if len(s) > MAX_CHARS:
                parts = re.split(r'(?<=,)\s+', s)
                sub = ''
                for p in parts:
                    if len(sub) + len(p) + 1 <= MAX_CHARS:
                        sub = (sub + ' ' + p).strip()
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = p
                if sub:
                    chunks.append(sub)
            else:
                buf = s
    if buf:
        chunks.append(buf)
    return chunks

def generar(texto_path, output_path):
    _prog("load", 0.20, "iniciando Kokoro")
    print("• Cargando pipeline Kokoro...")
    pipeline = KPipeline(lang_code=LANG)
    _prog("load", 1.0, "modelo listo")

    with open(texto_path, encoding='utf-8') as f:
        raw = f.read()

    parrafos = [p.strip() for p in raw.split('\n\n') if p.strip()]

    # plan de fragmentos para progreso determinista
    plan = []
    for pi, parrafo in enumerate(parrafos):
        chs = split_sentences(parrafo)
        for ci, ch in enumerate(chs):
            plan.append((pi, ci == len(chs) - 1, ch))
    total = len(plan)
    print(f"• {len(parrafos)} párrafo(s), {total} chunk(s) en total")
    _prog("gen", 0, total)

    audio_por_parrafo = {}
    for n, (pi, ultimo, chunk) in enumerate(plan, start=1):
        set_seed(SEED)   # seed fijo antes de CADA chunk
        segs = []
        for _, _, audio in pipeline(chunk, voice=VOICE, speed=SPEED):
            segs.append(audio)
        if segs:
            merged = fade(np.concatenate(segs))   # suavizar bordes
            audio_por_parrafo.setdefault(pi, []).append(merged)
            if not ultimo:
                audio_por_parrafo[pi].append(silencio(PAUSA_ORACION))
        print(f"  chunk {n}/{total}: {chunk[:55]}...")
        _prog("gen", n, total)

    audio_final = []
    for pi in range(len(parrafos)):
        if pi in audio_por_parrafo:
            audio_final.append(np.concatenate(audio_por_parrafo[pi]))
            if pi < len(parrafos) - 1:
                audio_final.append(silencio(PAUSA_PARRAFO))

    final = np.concatenate(audio_final)
    sf.write(output_path, final, SR)
    dur = len(final) / SR
    print(f"\n✓ Guardado: {output_path}  ({dur/60:.1f} min)")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Uso: python audiobook.py entrada.txt salida.wav")
        sys.exit(1)
    generar(sys.argv[1], sys.argv[2])
