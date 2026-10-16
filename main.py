#!/usr/bin/env python3
"""pylibra — interface desktop (PyQt6) do narrador pyvox (Kokoro-82M, CPU).

Uso:
    pyvox/.venv/bin/python main.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# O motor do pyvox vive na subpasta pyvox/ (módulo pyvox.py) — injeta no path
# ANTES de importar qualquer coisa do pacote pylibra.
sys.path.insert(0, str(ROOT / "pyvox"))

import pyvox  # noqa: E402  (valida cedo o motor — erro de import é amigável abaixo)

from PyQt6.QtWidgets import QApplication  # noqa: E402

from pylibra import __version__  # noqa: E402
from pylibra.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("pylibra")
    app.setOrganizationName("pylibra")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")  # aparência consistente entre plataformas

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ImportError as e:
        print(f"erro: dependência faltando ({e}).\n"
              "  instale com:  uv pip install --python pyvox/.venv/bin/python PyQt6",
              file=sys.stderr)
        sys.exit(1)
