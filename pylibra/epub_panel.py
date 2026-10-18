"""Sessão EPUB do pylibra — lê e lista os capítulos de um .epub via pylibre.

O motor pylibre (pasta ``pylibre/`` do projeto) usa só a biblioteca padrão;
aqui ele roda em uma QThread para a interface não travar em livros grandes.

Por enquanto a sessão apenas LÊ e LISTA os capítulos (+ prévia do texto);
a conversão em texto/áudio virá nas próximas sessões.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

# motor — injetado via sys.path pelo main.py
from pylibre.epub import read_book


class EpubWorker(QThread):
    """Lê um EPUB em background (mesmo padrão do SynthWorker do pyvox).

    Sinais (entregues na thread de UI):
      succeeded → {title, authors, chapters: [{title, words, text}], total_words}
      failed    → mensagem de erro
    """

    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, *, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self) -> None:
        try:
            with zipfile.ZipFile(self.path) as zf:
                book = read_book(zf)
        except Exception as exc:  # EPUB inválido, zip corrompido, sem capítulos…
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        chapters = [
            {
                "title": c.title or "(sem título)",
                "words": len(c.text.split()),
                "text": c.text,
            }
            for c in book.chapters
        ]
        self.succeeded.emit({
            "title": book.title or "(sem título)",
            "authors": list(book.authors),
            "chapters": chapters,
            "total_words": sum(c["words"] for c in chapters),
        })


class EpubPanel(QWidget):
    """Abas de trabalho: abrir EPUB → título/autores → lista de capítulos → prévia."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: str | None = None
        self._worker: QThread | None = None
        self._worker_gen: int | None = None
        self._data: dict | None = None
        self._gen = 0  # descarta respostas de livros anteriores

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(10)

        # --------------------------------------------------- arquivo + meta
        top = QHBoxLayout()
        self._btn_open = QPushButton("📚 Escolher EPUB…")
        self._btn_open.clicked.connect(self._on_open)
        top.addWidget(self._btn_open)
        self._path_lbl = QLabel("nenhum arquivo aberto")
        self._path_lbl.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self._path_lbl, 1)
        self._meta_lbl = QLabel("")
        self._meta_lbl.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self._meta_lbl)
        root.addLayout(top)

        # -------------------------------------------------- lista + prévia
        split = QSplitter(Qt.Orientation.Horizontal)

        self._list = QListWidget()
        self._list.setWordWrap(False)
        self._list.itemSelectionChanged.connect(self._on_select)
        split.addWidget(self._list)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText(
            "Escolha um capítulo à esquerda para ver o texto extraído…")
        split.addWidget(self._preview)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

        # ----------------------------------------------------------- status
        self._status = QLabel("aguardando EPUB")
        self._status.setTextFormat(Qt.TextFormat.RichText)
        self._status.setStyleSheet("color: #555;")
        root.addWidget(self._status)

    # ------------------------------------------------------------------ ações
    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir EPUB", str(Path.home()),
            "Livros EPUB (*.epub);;Arquivos EPUB (*.EPUB)")
        if not path:
            return
        self._open_file(path)

    def _open_file(self, path: str) -> None:
        """Abre o EPUB (usado pela UI e pelos testes)."""
        if not Path(path).is_file():
            self._set_status(f"⚠️ arquivo não encontrado: {path}")
            return
        self._gen += 1
        gen = self._gen
        self._path = path
        name = Path(path).name
        self._path_lbl.setText(f"<b>{name}</b>")
        self._meta_lbl.setText("")
        self._list.clear()
        self._preview.clear()
        self._btn_open.setEnabled(False)
        self._set_status(f"lendo <b>{name}</b>…")

        worker = EpubWorker(path=path, parent=self)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self._worker = worker

        # guarda a geração no worker p/ o handler comparar
        self._worker_gen = gen

    def _on_success(self, data: dict) -> None:
        if getattr(self, "_worker_gen", 0) != self._gen:
            return  # resposta de uma geração antiga — ignora
        chapters = data["chapters"]
        self._list.clear()
        for i, c in enumerate(chapters, 1):
            item = QListWidgetItem(f"{i}.  {c['title']}   —   {c['words']:,} palavras")
            item.setData(Qt.ItemDataRole.UserRole, i - 1)
            self._list.addItem(item)
        self._meta_lbl.setText(
            f"<b>{data['title']}</b>" + (f" · {', '.join(data['authors'])}"
                                         if data["authors"] else ""))
        self._data = data  # usado pelo _on_select (prévia)
        self._set_status(
            f"✓ <b>{len(chapters)}</b> capítulos · "
            f"<b>{data['total_words']:,}</b> palavras no total")
        if self._list.count():
            self._list.setCurrentRow(0)
        self._btn_open.setEnabled(True)

    def _on_failed(self, msg: str) -> None:
        if getattr(self, "_worker_gen", 0) != self._gen:
            return
        self._list.clear()
        self._preview.clear()
        self._btn_open.setEnabled(True)
        self._set_status(f"❌ falha ao ler o EPUB — {msg}")

    def _on_select(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        data = getattr(self, "_data", None)
        if data is not None and isinstance(idx, int) and 0 <= idx < len(data["chapters"]):
            self._preview.setPlainText(data["chapters"][idx]["text"])

    def _set_status(self, html: str) -> None:
        self._status.setText(html)

    # -------------------------------------------------------------- para testes
    def chapters(self) -> list[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def wait_done(self, timeout_ms: int = 15000) -> bool:
        """Espera (em testes) o worker terminar."""
        import time
        t0 = time.monotonic()
        while self.is_busy() and time.monotonic() - t0 < timeout_ms / 1000:
            self.window().processEvents()
            time.sleep(0.02)
        self.window().processEvents()
        return not self.is_busy()
