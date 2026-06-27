#!/usr/bin/env python3
"""
epub_to_tts.py — Convierte un epub a archivos .txt limpios para TTS/audiolibro.

Uso:
    python epub_to_tts.py libro.epub [carpeta_salida]

Requiere:
    pip install ebooklib beautifulsoup4 lxml
"""

import sys
import os
import re
import warnings

try:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
except ImportError:
    print("Instala dependencias: pip install ebooklib beautifulsoup4 lxml")
    sys.exit(1)

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ── CONFIG ─────────────────────────────────────────────────────────────────────
MIN_CHAPTER_LENGTH = 500   # chars mínimos para considerar un item capítulo

# Títulos a ignorar aunque superen el mínimo
SKIP_TITLES = {
    'cubierta', 'portada', 'cover', 'sinopsis', 'personajes',
    'sobre el autor', 'dedicatoria', 'titulo', 'título',
    'créditos', 'creditos', 'copyright', 'colofón', 'colofon',
    'mapa', 'map', 'índice', 'indice', 'tabla de contenidos',
}

# Patrones de sección/parte que se saltan
SKIP_TITLE_PATTERN = re.compile(
    r'^(primera|segunda|tercera|cuarta|quinta|sexta|séptima|octava|novena|décima'
    r'|parte|section|book|libro)\s',
    re.IGNORECASE
)

# ── LIMPIEZA DE TEXTO ──────────────────────────────────────────────────────────

def clean_text(raw_html: bytes) -> str:
    soup = BeautifulSoup(raw_html, 'lxml')
    for tag in soup(['script', 'style', 'img', 'figure', 'figcaption']):
        tag.decompose()
    text = soup.get_text(separator=' ')
    text = re.sub(r'\r\n|\r', '\n', text)
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('—', ' ').replace('–', ' ')
    text = text.replace('…', '.').replace('...', '.')
    text = re.sub(r'[«»""\'""()\[\]{}]', '', text)
    text = text.replace(':', ' ').replace(';', ',')
    text = re.sub(r'[*/_|\\@#^~`<>=+]', ' ', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r',{2,}', ',', text)
    text = re.sub(r'\s+([.,!?])', r'\1', text)
    text = re.sub(r'([.,!?])([^\s\d])', r'\1 \2', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def strip_chapter_header(text: str, title: str) -> str:
    """Elimina el título del capítulo si aparece repetido al inicio del texto."""
    # limpiar el título para comparar
    title_clean = re.sub(r'[^a-záéíóúüñA-ZÁÉÍÓÚÜÑ0-9\s]', '', title).strip()
    title_words = title_clean.split()
    if not title_words:
        return text

    # buscar si el texto empieza con palabras del título
    text_start = text[:min(200, len(text))]
    pattern = r'^\s*' + r'\s+'.join(re.escape(w) for w in title_words[:4])
    m = re.match(pattern, text_start, re.IGNORECASE)
    if m:
        text = text[m.end():].strip()

    # también quitar número de capítulo al inicio si quedó
    text = re.sub(r'^\d+\s+', '', text).strip()
    return text


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[«»""\'""()\[\]{};:*?<>|/\\]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:80]


# ── EXTRAER TOC → mapa href:título ────────────────────────────────────────────

def extract_toc_map(book) -> dict:
    """Recorre el TOC del epub y devuelve {href_base: título}."""
    toc_map = {}

    def walk(items):
        for item in items:
            if isinstance(item, tuple):
                section, children = item
                href = section.href.split('#')[0]
                toc_map[href] = section.title
                walk(children)
            elif hasattr(item, 'href'):
                href = item.href.split('#')[0]
                toc_map[href] = item.title

    walk(book.toc)
    return toc_map


def should_skip(title: str, text_len: int) -> bool:
    if text_len < MIN_CHAPTER_LENGTH:
        return True
    t = title.lower().strip()
    if t in SKIP_TITLES:
        return True
    if SKIP_TITLE_PATTERN.match(t):
        return True
    # partes numeradas: "PRIMERA PARTE", "PARTE I", etc.
    if re.match(r'^(parte|part)\s', t, re.IGNORECASE):
        return True
    if re.match(r'^[IVXLC]+\s*$', title.strip()):  # numeración romana sola
        return True
    return False


def build_filename(title: str) -> str:
    """Convierte el título del TOC en nombre de archivo."""
    title = sanitize_filename(title)
    # "1 Menzoberranzan" → "Cap 1 Menzoberranzan"
    m = re.match(r'^(\d+)\s+(.*)', title)
    if m:
        return f"Cap {m.group(1)} {m.group(2)}.txt"
    return f"{title}.txt"


# ── MAIN ───────────────────────────────────────────────────────────────────────

def process_epub(epub_path: str, out_dir: str):
    print(f"Leyendo: {epub_path}")
    book = epub.read_epub(epub_path)

    meta_title  = book.get_metadata('DC', 'title')
    meta_author = book.get_metadata('DC', 'creator')
    print(f"Título: {meta_title[0][0] if meta_title else '?'}")
    print(f"Autor:  {meta_author[0][0] if meta_author else '?'}")

    os.makedirs(out_dir, exist_ok=True)
    print(f"Salida: {out_dir}\n")

    # construir mapa TOC: {nombre_archivo_xhtml: título_limpio}
    toc_map = extract_toc_map(book)

    generated = []
    skipped   = []
    used_names = set()

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        item_name = item.get_name()
        raw = item.get_content()

        # obtener título desde TOC
        title = toc_map.get(item_name, '').strip()

        # fallback: heading HTML
        if not title:
            soup = BeautifulSoup(raw, 'lxml')
            for tag in ['h1', 'h2', 'h3', 'h4']:
                h = soup.find(tag)
                if h:
                    title = h.get_text(separator=' ', strip=True).strip()
                    break

        # sin título → saltar
        if not title:
            skipped.append(f"  SKIP (sin título): {item_name}")
            continue

        # limpiar el título (quitar comillas, caracteres raros)
        title = re.sub(r'[«»""\'""()]', '', title).strip()
        title = re.sub(r'\s+', ' ', title)

        # limpiar texto
        cleaned = clean_text(raw)

        # decidir si saltar
        if should_skip(title, len(cleaned)):
            skipped.append(f"  SKIP ({title!r}, {len(cleaned)} chars): {item_name}")
            continue

        # eliminar encabezado repetido al inicio del texto
        cleaned = strip_chapter_header(cleaned, title)

        if not cleaned:
            skipped.append(f"  SKIP (vacío post-limpieza): {item_name}")
            continue

        # construir nombre de archivo
        fname = build_filename(title)

        # evitar duplicados
        base, ext = os.path.splitext(fname)
        counter = 1
        while fname in used_names:
            fname = f"{base} ({counter}){ext}"
            counter += 1
        used_names.add(fname)

        fpath = os.path.join(out_dir, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(cleaned)

        generated.append(fname)
        print(f"  ✓ {fname}  ({len(cleaned):,} chars)")

    print(f"\n{'='*50}")
    print(f"Generados: {len(generated)} archivos")
    if skipped:
        print(f"Omitidos:  {len(skipped)}")
        for s in skipped:
            print(s)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    epub_path = sys.argv[1]
    if not os.path.exists(epub_path):
        print(f"Error: no existe {epub_path}")
        sys.exit(1)

    default_out = os.path.splitext(os.path.basename(epub_path))[0] + '_txt'
    out_dir = sys.argv[2] if len(sys.argv) > 2 else default_out

    process_epub(epub_path, out_dir)
