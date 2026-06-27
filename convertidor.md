# instalar dependencias (solo una vez, dentro del venv)
pip install ebooklib beautifulsoup4 lxml

# convertir
python epub_to_tts.py libro2.epub
# → genera carpeta "libro2_txt/" automáticamente

# o especificar carpeta destino
python epub_to_tts.py libro2.epub /ruta/donde/quieras/
