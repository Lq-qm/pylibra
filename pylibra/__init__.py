"""pylibra — interface desktop (PyQt6) para os motores pyvox e pylibre.

Os motores vivem em subpastas do projeto e são injetados no ``sys.path`` pelo
ponto de entrada ``main.py``:
  • ``pyvox/``   → narração (Kokoro-82M, CPU)
  • ``pylibre/`` → EPUB → texto (só stdlib)

As sessões da interface combinam os dois: a sessão EPUB lê o livro com o
pylibre e narra os capítulos com o pyvox.
"""
__version__ = "0.2.0"
