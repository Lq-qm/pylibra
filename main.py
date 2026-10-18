#!/usr/bin/env python3
"""pylibra — interface desktop (PyQt6) do narrador pyvox (Kokoro-82M, CPU).

Uso:
    pyvox/.venv/bin/python main.py                 # abre a janela do app
    pyvox/.venv/bin/python main.py --speak "texto" # narra pela linha de comando
    pyvox/.venv/bin/python main.py --selftest      # verifica motor + libs + UI
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Os motores vivem em subpastas do projeto:
#   pyvox/   → módulo pyvox.py (narração, Kokoro-82M)
#   pylibre/ → pacote pylibre (EPUB → texto, só stdlib)
# Injeta no path ANTES de importar qualquer coisa do pacote pylibra.
sys.path.insert(0, str(ROOT / "pylibre"))
sys.path.insert(0, str(ROOT / "pyvox"))

import pyvox    # noqa: E402  (valida cedo o motor — erro de import é amigável abaixo)
import pylibre  # noqa: E402

from PyQt6.QtWidgets import QApplication  # noqa: E402

from pylibra import __version__  # noqa: E402
from pylibra.main_window import MainWindow  # noqa: E402


def selftest() -> int:
    """Verifica o aplicativo congelado: motor, libs nativas e UI. (main.py --selftest)"""
    import traceback
    from pathlib import Path

    import torch
    import kokoro
    import misaki.en
    import misaki.espeak
    import espeakng_loader
    import spacy

    def say(msg: str) -> None:
        print(msg, flush=True)

    from pylibra.worker import plan_output, resolve_voice

    ok = True
    try:
        lib = espeakng_loader.load_library()
        if lib is None:
            raise RuntimeError("load_library() retornou None")
        data = Path(espeakng_loader.get_data_path())
        if not data.exists():
            raise RuntimeError(f"dados do espeak ausentes: {data}")
        say(f"espeak-ng ok (lib carregada, dados em {data})")
    except Exception:
        ok = False
        traceback.print_exc(limit=5)

    try:
        assert "pt-br" in pyvox.LANGS
        assert resolve_voice("pt-br", "feminino", None) == "pf_dora"
        assert resolve_voice("pt-br", "masculino", None) == "pm_alex"
        assert resolve_voice("en-us", "auto", None) == "af_heart"
        voices = pyvox.list_voices("p")  # rede ou fallback offline
        assert "pf_dora" in voices, voices
        p = plan_output(Path("/tmp/pylibra-selftest"), "teste", "mp3")
        assert p.name == "teste.wav"  # plan_output devolve o WAV intermediário
        say(f"motor pyvox ok (LANGS, {len(voices)} vozes pt, resolve_voice, plan_output)")
    except Exception:
        ok = False
        traceback.print_exc(limit=5)

    try:
        import tempfile
        import zipfile

        from pylibre.epub import read_book
        # EPUB mínimo em memória — valida o motor pylibre sem depender de livro real
        epub = Path(tempfile.mkdtemp()) / "selftest.epub"
        with zipfile.ZipFile(epub, "w") as zf:
            zf.writestr("META-INF/container.xml", """
              <container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\" version=\"1.0\">
                <rootfiles><rootfile full-path=\"OEBPS/content.opf\"
                  media-type=\"application/oebps-package+xml\"/></rootfiles>
              </container>""")
            zf.writestr("OEBPS/content.opf", """
              <package xmlns=\"http://www.idpf.org/2007/opf\" version=\"2.0\">
                <metadata>
                  <dc:creator xmlns:dc=\"http://purl.org/dc/elements/1.1/\">Autor de Teste</dc:creator>
                  <dc:title xmlns:dc=\"http://purl.org/dc/elements/1.1/\">Livro de Teste</dc:title>
                </metadata>
                <manifest>
                  <item id=\"c1\" href=\"c1.xhtml\" media-type=\"application/xhtml+xml\"/>
                  <item id=\"c2\" href=\"c2.xhtml\" media-type=\"application/xhtml+xml\"/>
                </manifest>
                <spine><itemref idref=\"c1\"/><itemref idref=\"c2\"/></spine>
              </package>""")
            zf.writestr("OEBPS/c1.xhtml", """
              <html xmlns=\"http://www.w3.org/1999/xhtml\"><head><title>Primeiro</title></head>
              <body><p>Texto do primeiro capítulo.</p></body></html>""")
            zf.writestr("OEBPS/c2.xhtml", """
              <html xmlns=\"http://www.w3.org/1999/xhtml\"><head><title>Segundo</title></head>
              <body><p>Texto do segundo capítulo.</p></body></html>""")
        with zipfile.ZipFile(epub) as zf:
            book = read_book(zf)
        assert book.title == "Livro de Teste", book.title
        assert book.authors == ["Autor de Teste"], book.authors
        assert [c.title for c in book.chapters] == ["Primeiro", "Segundo"], book.chapters
        epub.unlink()
        say(f"motor pylibre ok (pylibre {pylibre.__version__} — EPUB mínimo: "
            f"{len(book.chapters)} capítulos, metadados, ordem do spine)")
    except Exception:
        ok = False
        traceback.print_exc(limit=5)

    win = None
    try:
        win = MainWindow()
        win.show()
        say("UI ok (MainWindow construído)")
    except Exception:
        ok = False
        traceback.print_exc(limit=5)

    say(f"torch {torch.__version__} | kokoro {getattr(kokoro, '__version__', '?')} | "
        f"spacy {spacy.__version__}")
    if win is not None:
        win.close()  # encerra workers (ex.: busca de vozes na rede) antes de sair
    say("SELFTEST " + ("OK" if ok else "FALHOU"))
    return 0 if ok else 1


def speak_cli(argv: list[str]) -> int:
    """Modo CLI headless: pylibra --speak "texto" [opções].

    Usa o MESMO caminho da UI (resolve_voice + plan_output + pyvox.synthesize_stream
    + pyvox.encode_mp3) e grava em ``saida/" — útil para scripts e automação.
    """
    import argparse
    from pylibra.worker import plan_output, resolve_voice

    p = argparse.ArgumentParser(
        prog="pylibra --speak",
        description="Narra um texto pela linha de comando (mesmo motor e regras da UI).",
    )
    p.add_argument("text", help="texto a narrar")
    p.add_argument("-l", "--lang", default="pt-br", choices=sorted(pyvox.LANGS),
                   help="idioma (padrão: pt-br)")
    p.add_argument("-g", "--narrador", default=None,
                   choices=["auto", "m", "f", "masculino", "feminino"],
                   help="narrador (padrão: auto = voz padrão do idioma)")
    p.add_argument("-v", "--voice", default=None,
                   help="voz exata (ex.: pf_dora) — sobrepõe --narrador")
    p.add_argument("-s", "--speed", type=float, default=1.0, help="velocidade (padrão: 1.0)")
    p.add_argument("-t", "--threads", type=int, default=None,
                   help="threads de CPU (padrão: todos os núcleos)")
    p.add_argument("-o", "--output", default=None,
                   help="nome base da saída; .mp3 pede MP3 (padrão: saida/narração.wav)")
    a = p.parse_args(argv)

    narrator = {"m": "masculino", "f": "feminino",
                "masculino": "masculino", "feminino": "feminino"}.get(a.narrador)
    voice = resolve_voice(a.lang, narrator or "auto", a.voice)

    base = Path(a.output).stem if a.output else "narração"
    fmt = "mp3" if (a.output and Path(a.output).suffix.lower() == ".mp3") else "wav"
    wav = plan_output(Path("saida"), base, fmt)
    saida_final = wav.with_suffix(".mp3" if fmt == "mp3" else ".wav")
    print(f"voz={voice} idioma={a.lang} velocidade={a.speed} → {saida_final}", flush=True)

    try:
        stats: dict | None = None
        gen = pyvox.synthesize_stream(
            a.text, a.lang, voice, a.speed, str(wav),
            a.threads or 0, log=lambda line: print(line, flush=True))
        for item in gen:
            if isinstance(item, dict):
                stats = item
        if stats is None:
            print("erro: a síntese terminou sem produzir áudio — o texto está vazio?",
                  file=sys.stderr)
            return 1
        final = wav
        if fmt == "mp3":
            mp3 = wav.with_suffix(".mp3")
            pyvox.encode_mp3(wav, mp3)
            wav.unlink(missing_ok=True)  # remove o WAV intermediário
            final = mp3
        rtf = stats.get("rtf")
        extra = f", RTF {rtf:.2f}" if rtf else ""
        print(f"ok: {final} ({stats.get('audio_seconds', 0):.1f}s de áudio, "
              f"{stats.get('chunks', 0)} chunks{extra})", flush=True)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"erro: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


def main() -> int:
    if "--selftest" in sys.argv:
        app = QApplication(sys.argv[1:])
        return selftest()

    if "--speak" in sys.argv:
        i = sys.argv.index("--speak")
        return speak_cli(sys.argv[i + 1:])

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
        print(f"erro: dependência faltando: {e}\n"
              "  no venv:  uv pip install --python pyvox/.venv/bin/python -r requirements.txt\n"
              "  no app congelado: use a pasta dist/pylibra gerada pelo PyInstaller",
              file=sys.stderr)
        sys.exit(1)
