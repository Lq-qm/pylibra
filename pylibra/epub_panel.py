"""Sessão EPUB do pylibra — lê o livro (pylibre) e narra os capítulos (pyvox).

Dois motores, uma sessão:
  • pylibre (pasta ``pylibre/`` do projeto, só stdlib) extrai título, autores
    e capítulos do .epub — roda em QThread para não travar a interface;
  • pyvox (Kokoro-82M, CPU) narra os capítulos escolhidos, um arquivo por
    capítulo em ``saida/<livro>/``, sem sobrescrever nada.

O modelo Kokoro é carregado uma única vez (cache do próprio pyvox por idioma).
"""
from __future__ import annotations

import zipfile
from pathlib import Path

# motor — injetado via sys.path pelo main.py
import pyvox

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pylibre.epub import read_book  # motor — injetado via sys.path pelo main.py

from .audio_player import AudioPlayer
from .book_worker import BookSynthWorker
from .worker import (
    LANG_LABELS,
    VoiceListWorker,
    audio_seconds_from_line,
    estimate_audio_seconds,
    offline_voices,
)

ROOT = Path(__file__).resolve().parents[1]
SAIDA_DIR = ROOT / "saida"


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
    """Abrir EPUB → título/autores → capítulos → prévia → narrar (pyvox)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: str | None = None
        self._worker: QThread | None = None
        self._worker_gen: int | None = None
        self._data: dict | None = None
        self._gen = 0  # descarta respostas de livros anteriores

        # narração do livro
        self._book_worker: BookSynthWorker | None = None
        self._voices_worker: VoiceListWorker | None = None
        self._voices_lang: str | None = None
        self._model_hook = None  # callback do app: "loading"|"ready" → barra de status
        # estado da barra de progresso do livro (definidos em _narrate_range)
        self._book_est: list[float] = []   # estimativa de duração (s) por capítulo
        self._book_n = 0                   # total de capítulos na fila
        self._book_i = 0                   # capítulo atual (1-based)

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

        # ============================================== narração (pyvox) ===
        narr = QLabel("<b>🎙️ Narrar com pyvox</b>")
        root.addWidget(narr)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        # Idioma
        grid.addWidget(QLabel("Idioma"), 0, 0)
        self._lang = QComboBox()
        order = [c for c in ("pt-br", *sorted(pyvox.LANGS)) if c in pyvox.LANGS]
        for code in order:
            self._lang.addItem(LANG_LABELS.get(code, code), code)
        self._lang.setCurrentIndex(self._lang.findData("pt-br"))
        grid.addWidget(self._lang, 0, 1)

        # Narrador (botões segmentados)
        grid.addWidget(QLabel("Narrador"), 0, 2)
        narr_box = QWidget()
        narr_lay = QHBoxLayout(narr_box)
        narr_lay.setContentsMargins(0, 0, 0, 0)
        narr_lay.setSpacing(4)
        self._narr_group = QButtonGroup(self)
        self._narr_group.setExclusive(True)
        self._narr_btns: dict[str, QPushButton] = {}
        for value, label in (("auto", "Auto"), ("masculino", "Masculino"),
                             ("feminino", "Feminino")):
            b = QPushButton(label)
            b.setCheckable(True)
            self._narr_group.addButton(b)
            self._narr_btns[value] = b
            narr_lay.addWidget(b, 1)
        self._narr_btns["auto"].setChecked(True)
        grid.addWidget(narr_box, 0, 3)

        # Voz + atualizar
        grid.addWidget(QLabel("Voz"), 1, 0)
        voice_lay = QHBoxLayout()
        voice_lay.setSpacing(4)
        self._voice = QComboBox()
        self._voice.addItem("automática")
        voice_lay.addWidget(self._voice, 1)
        self._btn_voices = QPushButton("↻")
        self._btn_voices.setFixedWidth(30)
        self._btn_voices.setToolTip("Atualizar lista de vozes (Hugging Face)")
        self._btn_voices.clicked.connect(lambda: self._refresh_voices())
        voice_lay.addWidget(self._btn_voices)
        grid.addLayout(voice_lay, 1, 1)

        # Velocidade
        grid.addWidget(QLabel("Velocidade"), 1, 2)
        speed_lay = QHBoxLayout()
        self._speed = QSlider(Qt.Orientation.Horizontal)
        self._speed.setRange(5, 20)
        self._speed.setValue(10)
        self._speed_lbl = QLabel("1.00x")
        self._speed.valueChanged.connect(
            lambda v: self._speed_lbl.setText(f"{v / 10:.2f}x"))
        speed_lay.addWidget(self._speed, 1)
        speed_lay.addWidget(self._speed_lbl)
        grid.addLayout(speed_lay, 1, 3)

        # Formato
        grid.addWidget(QLabel("Formato"), 2, 0)
        self._fmt = QComboBox()
        self._fmt.addItem("WAV", "wav")
        self._fmt.addItem("MP3", "mp3")
        grid.addWidget(self._fmt, 2, 1)

        root.addLayout(grid)

        # ------------------------------------------- ações + progresso
        actions = QHBoxLayout()
        self._btn_chap = QPushButton("🎙️ Narrar este capítulo")
        self._btn_chap.clicked.connect(lambda: self._narrate([self._current_idx()]))
        self._btn_all = QPushButton("📚 Narrar todos os capítulos")
        self._btn_all.clicked.connect(self._narrate_all)
        self._btn_cancel = QPushButton("⏹ Cancelar")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._on_cancel)
        actions.addWidget(self._btn_chap)
        actions.addWidget(self._btn_all)
        actions.addWidget(self._btn_cancel)
        actions.addStretch(1)
        self._book_progress = QProgressBar()
        self._book_progress.setRange(0, 100)  # contínuo: capítulos prontos + fração do atual
        self._book_progress.setValue(0)
        self._book_progress.setFixedWidth(160)
        self._book_progress.setFixedHeight(16)
        actions.addWidget(self._book_progress)
        self._prog_lbl = QLabel("")
        self._prog_lbl.setTextFormat(Qt.TextFormat.RichText)
        actions.addWidget(self._prog_lbl)
        root.addLayout(actions)

        # ---------------------------------------------------------------- log
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        self._log.setFixedHeight(100)
        root.addWidget(self._log)

        # --------------------------------------------------------------- player
        self._player = AudioPlayer()
        self._player.error.connect(lambda msg: self._log_append(f"⚠️ player: {msg}"))
        root.addWidget(self._player)

        # ----------------------------------------------------------- status
        self._status = QLabel("aguardando EPUB")
        self._status.setTextFormat(Qt.TextFormat.RichText)
        self._status.setStyleSheet("color: #555;")
        root.addWidget(self._status)

        self._fill_voices()

    # =================================================================== ações
    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir EPUB", str(Path.home()),
            "Livros EPUB (*.epub);;Arquivos EPUB (*.EPUB)")
        if not path:
            return
        self._open_file(path)

    def _open_file(self, path: str) -> None:
        """Abre o EPUB (usado pela UI e pelos testes)."""
        if self.book_busy():
            return  # narração em andamento — não troca de livro
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
        self._worker_gen = gen  # p/ os handlers descartarem respostas antigas

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
        self._data = data  # usado pelo _on_select (prévia) e pela narração
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
        self._data = None  # não deixar livro anterior "visível" para a narração
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

    def _current_idx(self) -> int | None:
        row = self._list.currentRow()
        if row < 0:
            return None
        item = self._list.item(row)
        idx = item.data(Qt.ItemDataRole.UserRole)
        return idx if isinstance(idx, int) else None

    # ------------------------------------------------------- vozes (pyvox)
    def _fill_voices(self, voices: list[str] | None = None) -> None:
        if voices is None:
            code = pyvox.LANGS.get(self._lang.currentData() or "pt-br", "p")
            voices = offline_voices(code)
        current = self._voice.currentText()
        self._voice.blockSignals(True)
        self._voice.clear()
        self._voice.addItem("automática")
        for v in voices:
            self._voice.addItem(v)
        self._voice.setCurrentIndex(max(0, self._voice.findText(current)))
        self._voice.blockSignals(False)

    def _refresh_voices(self) -> None:
        lang = self._lang.currentData() or "pt-br"
        self._voices_lang = lang
        w = VoiceListWorker(lang, parent=self)
        w.done.connect(lambda voices: self._on_voice_list(lang, voices))
        w.done.connect(w.deleteLater)
        self._voices_worker = w
        w.start()

    def _on_voice_list(self, lang: str, voices: list[str]) -> None:
        if self._voices_lang != lang or (self._lang.currentData() or "pt-br") != lang:
            return  # resposta de uma geração antiga — ignora
        if voices:
            self._fill_voices(voices)
            self._log_append(f"↻ {len(voices)} vozes disponíveis para "
                             f"{self._lang.currentData()}")

    def _set_narrator(self, value: str) -> None:
        for v, b in self._narr_btns.items():
            b.setChecked(v == value)

    # ------------------------------------------------------ narração do livro
    def _narrate(self, indices: list[int | None]) -> None:
        self._narrate_range([i for i in indices if isinstance(i, int)])

    def _narrate_all(self) -> None:
        n = self._list.count() if self._data else 0
        if n:
            self._narrate_range(list(range(n)))

    def _narrate_range(self, indices: list[int]) -> None:
        if self.book_busy():
            self._log_append("⚠️ já existe uma narração em andamento")
            return
        data = self._data
        if data is None or not self._path or not indices:
            self._set_status("⚠️ abra um EPUB e escolha ao menos um capítulo")
            return
        try:
            narrator = next(v for v, b in self._narr_btns.items() if b.isChecked())
        except StopIteration:
            narrator = "auto"
        voice = None if self._voice.currentText() == "automática" else self._voice.currentText()
        lang = self._lang.currentData() or "pt-br"
        chapters = [
            (idx, data["chapters"][idx]["title"], data["chapters"][idx]["text"])
            for idx in indices
        ]
        outdir = SAIDA_DIR / Path(self._path).stem
        n = len(chapters)
        self._log.clear()
        self._log_append(
            f"📚 narrando <b>{n}</b> capítulo(s) — voz {voice or narrator} · "
            f"{lang} · {self._speed.value() / 10:.2f}x · "
            f"{self._fmt.currentData().upper()} → {outdir}")
        # barra contínua: 100/n por capítulo; dentro do capítulo, avança com o
        # áudio real yieldado (est. de duração por capítulo como denominador)
        self._book_est = [estimate_audio_seconds(text) for (_i, _t, text) in chapters]
        self._book_n = n
        self._book_i = 0  # capítulo atual (1-based), atualizado em chapter_started
        self._book_progress.setRange(0, 100)
        self._book_progress.setValue(0)
        self._set_busy(True)

        w = BookSynthWorker(
            chapters=chapters, lang=lang, narrator=narrator, voice=voice,
            speed=self._speed.value() / 10, threads=0,
            fmt=self._fmt.currentData(), outdir=outdir, parent=self)
        w.chapter_started.connect(self._on_chapter_started)
        w.chapter_done.connect(self._on_chapter_done)
        w.log_line.connect(self._on_book_log)
        w.progress.connect(self._on_book_progress)
        w.succeeded.connect(self._on_book_done)
        w.cancelled.connect(self._on_book_cancelled)
        w.failed.connect(self._on_book_failed)
        w.finished.connect(w.deleteLater)
        w.start()
        self._book_worker = w

    def _on_chapter_started(self, i: int, n: int, title: str) -> None:
        self._book_i = i
        self._book_n = n
        self._update_book_progress(None)
        self._prog_lbl.setText(f"capítulo <b>{i}/{n}</b> — {title}")

    def _on_chapter_done(self, i: int, n: int, path: str) -> None:
        self._book_i = i
        self._book_n = n
        self._book_progress.setValue(min(99, int(i / n * 100)))
        self._log_append(f"✅ [{i}/{n}] → {path}")
        self._player.load(path, autoplay=False)
        self._prog_lbl.setText(
            f"capítulo <b>{i}/{n}</b> pronto — {Path(path).name}"
            + ("" if i == n else " · narrando próximo…"))

    def _on_book_progress(self, line: str) -> None:
        """Linha de chunk do motor: loga e avança a barra (capítulo atual + fração)."""
        self._log_append(line)
        self._update_book_progress(audio_seconds_from_line(line))

    def _update_book_progress(self, sec_atual: float | None) -> None:
        """Barra 0–100: (capítulos prontos + fração do atual) / total."""
        n = self._book_n or len(self._book_est)
        if not n:
            return
        i = max(1, min(self._book_i or 1, n))
        est = self._book_est[i - 1] if i <= len(self._book_est) else 0.0
        frac = min(1.0, sec_atual / est) if (sec_atual and est > 0) else 0.0
        self._book_progress.setValue(min(99, int((i - 1 + frac) / n * 100)))

    def _on_book_done(self, paths: list[str]) -> None:
        self._set_busy(False)
        self._book_progress.setValue(100)
        self._notify_model("ready")
        self._set_status(
            f"✓ livro narrado — <b>{len(paths)}</b> arquivo(s) em "
            f"<code>{self._outdir()}</code>")
        self._log_append(f"🏁 tudo pronto — {len(paths)} arquivo(s)")

    def _on_book_cancelled(self, paths: list[str]) -> None:
        self._set_busy(False)
        self._notify_model("ready")
        self._set_status(
            f"⏹ cancelado — <b>{len(paths)}</b> capítulo(s) pronto(s) em "
            f"<code>{self._outdir()}</code>")

    def _on_book_failed(self, msg: str) -> None:
        self._set_busy(False)
        self._notify_model("ready")
        self._set_status(f"❌ falha na narração — {msg}")
        self._log_append(f"❌ {msg}")

    def _on_book_log(self, msg: str) -> None:
        """Linha do motor: loga e repassa o estado do modelo ao app (barra de status)."""
        self._log_append(msg)
        if "carregando modelo" in msg:
            self._notify_model("loading")
        elif "modelo pronto" in msg:
            self._notify_model("ready")

    def _notify_model(self, state: str) -> None:
        if self._model_hook is not None:
            self._model_hook(state)

    def set_model_hook(self, fn) -> None:
        """Callback do app: ``fn('loading'|'ready')`` — mantém a barra de status
        sincronizada quando a narração do livro carrega o Kokoro-82M."""
        self._model_hook = fn

    def _on_cancel(self) -> None:
        if self._book_worker is not None:
            self._book_worker.cancel()
            self._log_append("⏹ cancelando (para no próximo chunk)…")

    def _set_busy(self, busy: bool) -> None:
        for w in (self._btn_chap, self._btn_all, self._btn_open):
            w.setEnabled(not busy)
        self._btn_cancel.setEnabled(busy)
        self._list.setEnabled(not busy)

    def _outdir(self) -> str:
        return str(SAIDA_DIR / Path(self._path).stem) if self._path else str(SAIDA_DIR)

    def _log_append(self, html: str) -> None:
        self._log.appendPlainText(html.replace("<b>", "").replace("</b>", ""))

    def _set_status(self, html: str) -> None:
        self._status.setText(html)

    # ------------------------------------------------------- estado (fechar)
    def book_busy(self) -> bool:
        w = self._book_worker
        if w is None:
            return False
        try:
            return w.isRunning()
        except RuntimeError:
            return False

    def cancel_book(self) -> None:
        if self._book_worker is not None:
            self._book_worker.cancel()

    def wait_book(self, timeout_ms: int = 20_000) -> bool:
        w = self._book_worker
        if w is None:
            return True
        try:
            return w.wait(timeout_ms)
        except RuntimeError:
            return True

    # -------------------------------------------------------------- para testes
    def chapters(self) -> list[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]

    def is_busy(self) -> bool:
        try:
            return self._worker is not None and self._worker.isRunning()
        except RuntimeError:
            return False

    def wait_done(self, timeout_ms: int = 15000) -> bool:
        """Espera (em testes) o worker de leitura terminar."""
        import time
        from PyQt6.QtCore import QCoreApplication
        t0 = time.monotonic()
        while self.is_busy() and time.monotonic() - t0 < timeout_ms / 1000:
            QCoreApplication.processEvents()
            time.sleep(0.02)
        QCoreApplication.processEvents()
        return not self.is_busy()



