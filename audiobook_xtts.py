#!/usr/bin/env python3
# audiobook_xtts.py — XTTS-v2 en GPU con voz CLONADA.
#
# Refinado para sonar lo más NATURAL posible:
#   - Calcula los "conditioning latents" UNA sola vez a partir de la(s)
#     muestra(s) de referencia (más consistencia y velocidad).
#   - Usa el API de bajo nivel de XTTS (model.inference) para exponer
#     todos los parámetros de prosodia (temperatura, penalizaciones, etc.).
#   - Normalización de texto y de audio de salida.
#
# Requisitos:
#   - torch/torchaudio con CUDA (cu124)
#   - coqui-tts                 (ver requirements-gpu.txt)
#
# Uso:  python audiobook_xtts.py entrada.txt salida.wav [voz_ref.wav]
#
# Todos los parámetros se pueden ajustar por variables de entorno (ver CONFIG).

import os
import re
import sys
import glob
import numpy as np
import soundfile as sf

# ── CONFIG ──────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("TTS_HOME", os.path.join(BASE_DIR, "models"))
VOZ_DIR    = os.path.join(BASE_DIR, "voz_clonada")
VOZ_REF    = os.path.join(VOZ_DIR, "clonada.wav")   # referencia por defecto
IDIOMA     = "es"
MODELO     = "tts_models/multilingual/multi-dataset/xtts_v2"
SR         = 24000        # sample rate de salida de XTTS-v2


def _envf(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _envi(name, default):
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return int(default)


# Parámetros de prosodia (ajustables por entorno desde la GUI).
# Valores por defecto pensados para narración natural en español.
TEMPERATURE        = _envf("XTTS_TEMPERATURE", 0.75)   # 0.6 monótono · 0.9 expresivo
REPETITION_PENALTY = _envf("XTTS_REPETITION_PENALTY", 5.0)  # >2 evita "tartamudeo"
LENGTH_PENALTY     = _envf("XTTS_LENGTH_PENALTY", 1.0)
TOP_K              = _envi("XTTS_TOP_K", 50)
TOP_P              = _envf("XTTS_TOP_P", 0.85)
SPEED              = _envf("XTTS_SPEED", 1.0)           # 0.95 da sensación más calmada
# Tamaño máx. de cada fragmento de texto. Más corto = menos artefactos/
# alucinaciones (XTTS se degrada en frases largas); demasiado corto rompe la
# prosodia y se notan las costuras. Punto dulce ~150–220.
MAX_CHARS          = _envi("XTTS_MAX_CHARS", 180)
# 0 = analizar el audio COMPLETO (se calcula a partir de su duración real).
GPT_COND_LEN       = _envi("XTTS_GPT_COND_LEN", 0)
MAX_REF_LEN        = _envi("XTTS_MAX_REF_LEN", 0)
SOUND_NORM_REFS    = _envi("XTTS_SOUND_NORM_REFS", 1)  # normaliza loudness de la ref

PAUSA_ORACION = _envf("XTTS_PAUSA_ORACION", 0.22)
PAUSA_PARRAFO = _envf("XTTS_PAUSA_PARRAFO", 0.55)
# ────────────────────────────────────────────────────────────────────────


def _prog(phase, value, extra=""):
    """Marcador de progreso legible por la GUI:  @PROGRESS|fase|valor|extra"""
    print(f"@PROGRESS|{phase}|{value}|{extra}", flush=True)


def silencio(seg):
    return np.zeros(int(SR * seg), dtype=np.float32)


# ── Normalización de texto ──────────────────────────────────────────────
_REEMPLAZOS = {
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'", "—": ", ", "–": ", ", "…": "...",
    "\t": " ",
}


def limpiar_texto(t):
    """Suaviza el texto para que XTTS lo lea con prosodia más natural."""
    for a, b in _REEMPLAZOS.items():
        t = t.replace(a, b)
    t = re.sub(r"[ ]{2,}", " ", t)
    # une saltos de línea sueltos dentro de un párrafo (no dobles)
    t = re.sub(r"(?<!\n)\n(?!\n)", " ", t)
    return t.strip()


def split_sentences(text):
    """Divide en fragmentos <= MAX_CHARS respetando puntuación fuerte y comas."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks, buf = [], ''
    for s in raw:
        s = s.strip()
        if not s:
            continue
        if len(buf) + len(s) + 1 <= MAX_CHARS:
            buf = (buf + ' ' + s).strip()
        else:
            if buf:
                chunks.append(buf)
            if len(s) > MAX_CHARS:
                sub = ''
                for p in re.split(r'(?<=[,;:])\s+', s):
                    if len(sub) + len(p) + 1 <= MAX_CHARS:
                        sub = (sub + ' ' + p).strip()
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = p
                if sub:
                    chunks.append(sub)
                buf = ''
            else:
                buf = s
    if buf:
        chunks.append(buf)
    return chunks


def _refs_de(voz_ref):
    """Lista de wavs de referencia: el seleccionado + tomas extra del MISMO
    nombre base (p.ej. clonada.wav, clonada_2.wav) para enriquecer la
    prosodia sin mezclar voces distintas.
    """
    refs = [voz_ref]
    stem = os.path.splitext(os.path.basename(voz_ref))[0]
    for w in sorted(glob.glob(os.path.join(VOZ_DIR, f"{stem}_*.wav"))):
        if os.path.abspath(w) != os.path.abspath(voz_ref):
            refs.append(w)
    # variable de entorno opcional con rutas extra separadas por ":"
    extra = os.environ.get("XTTS_REF_EXTRA", "").strip()
    if extra:
        refs += [p for p in extra.split(":") if p and os.path.isfile(p)]
    return refs


def cargar_modelo(verbose=True):
    """Carga XTTS-v2 y devuelve (model, device). Reutilizable por el worker."""
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if verbose and device == "cpu":
        print("⚠ CUDA no disponible: se usará CPU (lento). Revisa torch+CUDA.")
    from TTS.api import TTS
    tts = TTS(MODELO).to(device)
    return tts.synthesizer.tts_model, device   # instancia Xtts (API bajo nivel)


def calc_latentes(model, refs, verbose=True):
    """Conditioning latents analizando TODO el audio de referencia."""
    dur_total = 0.0
    for r in refs:
        try:
            info = sf.info(r)
            dur_total += info.frames / float(info.samplerate)
        except Exception:
            pass
        if verbose:
            print(f"    - {r}")
    full = int(dur_total) + 1 if dur_total > 0 else 30
    cond_len = GPT_COND_LEN if GPT_COND_LEN > 0 else full
    ref_len  = MAX_REF_LEN if MAX_REF_LEN > 0 else full
    if verbose:
        print(f"• Analizando {dur_total:.1f}s de referencia "
              f"(cond_len={cond_len}s, ref_len={ref_len}s)")
    return model.get_conditioning_latents(
        audio_path=refs,
        gpt_cond_len=cond_len,
        max_ref_length=ref_len,
        sound_norm_refs=bool(SOUND_NORM_REFS),
    )


def params_actuales(overrides=None):
    """Parámetros de prosodia (defaults de entorno + overrides opcionales)."""
    p = dict(
        temperature=TEMPERATURE,
        length_penalty=LENGTH_PENALTY,
        repetition_penalty=REPETITION_PENALTY,
        top_k=TOP_K,
        top_p=TOP_P,
        speed=SPEED,
        enable_text_splitting=False,
    )
    if overrides:
        p.update({k: v for k, v in overrides.items() if v is not None})
    return p


def inferir(model, latents, texto, params):
    """Sintetiza un fragmento y devuelve el audio como np.float32."""
    gpt, spk = latents
    out = model.inference(
        text=texto, language=IDIOMA,
        gpt_cond_latent=gpt, speaker_embedding=spk, **params)
    return np.asarray(out["wav"], dtype=np.float32)


def normaliza_pico(audio):
    """Normalización de pico suave (evita clipping y nivela el volumen)."""
    peak = float(np.max(np.abs(audio))) or 1.0
    return (audio / peak) * 0.97


def generar(texto_path, output_path, voz_ref=None):
    voz_ref = voz_ref or VOZ_REF
    if not os.path.isfile(voz_ref):
        print(f"✗ No existe la voz de referencia: {voz_ref}")
        print("  Genérala primero con:  voz_clonada/grabar_muestras.sh")
        sys.exit(1)

    # ── Carga del modelo ───────────────────────────────────────────────
    _prog("load", 0.10, "importando torch")
    print("• Importando torch...")
    _prog("load", 0.55, "cargando modelo XTTS-v2")
    print("• Cargando modelo XTTS-v2 (puede tardar)...")
    model, device = cargar_modelo()
    print(f"• Dispositivo: {device}")

    # ── Conditioning latents (UNA sola vez) ────────────────────────────
    refs = _refs_de(voz_ref)
    _prog("load", 0.85, "analizando voz de referencia")
    print(f"• Voz de referencia ({len(refs)} muestra/s):")
    latents = calc_latentes(model, refs)
    _prog("load", 1.0, "modelo listo")
    params = params_actuales()
    print(f"• Prosodia: temp={TEMPERATURE} rep_pen={REPETITION_PENALTY} "
          f"top_k={TOP_K} top_p={TOP_P} speed={SPEED}")

    # ── Preparar fragmentos ────────────────────────────────────────────
    with open(texto_path, encoding='utf-8') as f:
        raw = limpiar_texto(f.read())
    parrafos = [p.strip() for p in raw.split('\n\n') if p.strip()]

    plan = []
    for pi, parrafo in enumerate(parrafos):
        chs = split_sentences(parrafo)
        for ci, ch in enumerate(chs):
            plan.append((pi, ci == len(chs) - 1, ch))
    total = len(plan)
    print(f"• {len(parrafos)} párrafo(s), {total} fragmento(s) en total")
    _prog("gen", 0, total)

    # ── Síntesis ───────────────────────────────────────────────────────
    audio_por_parrafo = {}
    for n, (pi, ultimo, chunk) in enumerate(plan, start=1):
        seg = inferir(model, latents, chunk, params)
        audio_por_parrafo.setdefault(pi, []).append(seg)
        if not ultimo:
            audio_por_parrafo[pi].append(silencio(PAUSA_ORACION))
        print(f"  fragmento {n}/{total}: {chunk[:55]}...")
        _prog("gen", n, total)

    audio_final = []
    for pi in range(len(parrafos)):
        if pi in audio_por_parrafo:
            audio_final.append(np.concatenate(audio_por_parrafo[pi]))
            if pi < len(parrafos) - 1:
                audio_final.append(silencio(PAUSA_PARRAFO))

    final = normaliza_pico(np.concatenate(audio_final))
    sf.write(output_path, final, SR)
    dur = len(final) / SR
    print(f"\n✓ Guardado: {output_path}  ({dur/60:.1f} min)")


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        print("Uso: python audiobook_xtts.py entrada.txt salida.wav [voz_ref.wav]")
        sys.exit(1)
    voz = sys.argv[3] if len(sys.argv) == 4 else None
    generar(sys.argv[1], sys.argv[2], voz)
