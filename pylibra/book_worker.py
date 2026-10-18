"""Narração de livros EPUB — o pipeline pylibre → pyvox dentro do app.

O painel da sessão EPUB já leu o livro (título, capítulos, texto) via pylibre;
aqui cada capítulo escolhido é narrado pelo pyvox, gerando um arquivo por
capítulo em ``saida/<livro>/`` sem sobrescrever nada existente.

O modelo Kokoro é carregado uma única vez (cache do próprio pyvox por idioma),
mesmo com dezenas de capítulos.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

import pyvox  # motor — injetado via sys.path pelo main.py

from .worker import plan_output, resolve_voice


def slugify(text: str, max_len: int = 60) -> str:
    """Título de capítulo → nome de arquivo seguro."""
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", " ", s).strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s or "capitulo"


class BookSynthWorker(QThread):
    """Narra uma fila de capítulos em background.

    Sinais (entregues na thread de UI):
      chapter_started → (i, n, título)      — capítulo i de n começou
      chapter_done    → (i, n, caminho)     — capítulo i de n pronto
      log_line        → linha do motor (carregamento do modelo, etc.)
      progress        → linha de chunk com prefixo [i/n]
      succeeded       → [caminhos finais]   — todo o livro narrado
      cancelled       → [caminhos prontos]  — cancelado; o gerado até aqui é mantido
      failed          → mensagem de erro
    """

    chapter_started = pyqtSignal(int, int, str)
    chapter_done = pyqtSignal(int, int, str)
    log_line = pyqtSignal(str)
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(list)
    cancelled = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, *, chapters: list[tuple[int, str, str]], lang: str,
                 narrator: str, voice: str, speed: float, threads: int,
                 fmt: str, outdir: Path, parent=None):
        """``chapters``: lista de (índice-no-livro, título, texto) na ordem desejada."""
        super().__init__(parent)
        self.chapters = chapters
        self.lang = lang
        self.voice = resolve_voice(lang, narrator, voice)
        self.speed = float(speed)
        self.threads = int(threads)
        self.fmt = fmt
        self.outdir = Path(outdir)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        done: list[str] = []
        n = len(self.chapters)
        try:
            for i, (_idx, title, text) in enumerate(self.chapters, 1):
                if self._cancel.is_set():
                    break
                self.chapter_started.emit(i, n, title)
                base = f"{i:02d} - {slugify(title)}"
                wav = plan_output(self.outdir, base, self.fmt)

                stats: dict | None = None
                gen = pyvox.synthesize_stream(
                    text, self.lang, self.voice, self.speed,
                    str(wav), self.threads, log=self.log_line.emit)
                cancelled = False
                for item in gen:
                    if self._cancel.is_set():
                        cancelled = True
                        break
                    if isinstance(item, dict):
                        stats = item
                    else:
                        self.progress.emit(f"[{i:>2}/{n}] {item}")

                if cancelled:
                    try:
                        gen.close()
                    except Exception:  # noqa: BLE001
                        pass
                    partial = str(wav) if wav.exists() else None
                    if partial:
                        self.log_line.emit(
                            f"⏹ cancelado no capítulo {i}/{n} — áudio parcial mantido: {partial}")
                    else:
                        self.log_line.emit(f"⏹ cancelado no capítulo {i}/{n}")
                    self.cancelled.emit(done + ([partial] if partial else []))
                    return

                if stats is None:
                    raise RuntimeError(f"capítulo “{title}” terminou sem produzir áudio")

                final = wav
                if self.fmt.lower() == "mp3":
                    mp3 = wav.with_suffix(".mp3")
                    pyvox.encode_mp3(wav, mp3)
                    wav.unlink(missing_ok=True)  # remove o WAV intermediário
                    final = mp3

                done.append(str(final))
                self.chapter_done.emit(i, n, str(final))
            self.succeeded.emit(done)
        except Exception as e:  # noqa: BLE001 — reportado como mensagem na UI
            self.failed.emit(f"{type(e).__name__}: {e}")
