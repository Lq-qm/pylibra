"""Janela principal do pylibra — interface desktop dos motores pyvox (narração)
e pylibre (EPUB → texto), organizadas em sessões/abas."""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import pyvox  # motor — injetado via sys.path pelo main.py

from .audio_player import AudioPlayer
from .epub_panel import EpubPanel
from .worker import (
    AUTO,
    LANG_LABELS,
    SynthWorker,
    VoiceListWorker,
    audio_seconds_from_line,
    estimate_audio_seconds,
    estimate_warning,
    offline_voices,
    plan_output,
    progress_percent,
    resolve_voice,
)

ROOT = Path(__file__).resolve().parents[1]
SAIDA_DIR = ROOT / "saida"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pylibra — ferramentas de texto e voz (pyvox + pylibre)")
        self.resize(1100, 740)

        self.cancel_event = threading.Event()
        self._worker: SynthWorker | None = None
        self._voices_worker: VoiceListWorker | None = None
        self._voices_lang: str | None = None  # guarda a geração da busca de vozes
        self._file_stem: str | None = None    # nome do arquivo aberto (base da saída)
        self._model_loading = False           # "carregando…" (transitório; o resto vem do cache)

        self._epub = EpubPanel()
        self._build_ui()
        self._epub.set_model_hook(self._on_epub_model)
        self._set_lang(self._lang.currentData() or "pt-br")
        self._lang.currentIndexChanged.connect(
            lambda: self._set_lang(self._lang.currentData() or "pt-br"))
        self.statusBar().showMessage("pronto — cole um texto e clique em Gerar narração", 8000)

    # ------------------------------------------------------------- construção
    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(16)

        # ============================ coluna esquerda ========================
        left = QVBoxLayout()
        left.setSpacing(8)

        text_header = QHBoxLayout()
        text_header.addWidget(QLabel("<b>📄 Texto</b>"))
        text_header.addStretch(1)
        self._char_lbl = QLabel("0 caracteres")
        btn_open = QPushButton("Abrir .txt…")
        btn_clear = QPushButton("Limpar")
        btn_open.clicked.connect(self._on_open_file)
        btn_clear.clicked.connect(self._on_clear)
        text_header.addWidget(btn_open)
        text_header.addWidget(btn_clear)
        text_header.addWidget(self._char_lbl)
        left.addLayout(text_header)

        self._text = QTextEdit()
        self._text.setAcceptRichText(False)
        self._text.setPlaceholderText(
            "Cole o texto a narrar aqui…\n\n"
            "“Era uma noite de inverno, e a cidade dormia sob um silêncio profundo. "
            "Mas quem percebeu a primeira estrela?”")
        self._text.textChanged.connect(self._on_text_changed)
        left.addWidget(self._text, 3)

        # --- resultado: player + pasta de saída
        res_row = QHBoxLayout()
        res_row.addWidget(QLabel("<b>🎧 Resultado</b>"))
        res_row.addStretch(1)
        self._result_lbl = QLabel("ainda não gerou nada")
        self._result_lbl.setTextFormat(Qt.TextFormat.RichText)
        btn_folder = QPushButton("📂 Abrir pasta de saída")
        btn_folder.clicked.connect(self._on_open_folder)
        res_row.addWidget(btn_folder)
        res_row.addWidget(self._result_lbl)
        left.addLayout(res_row)

        self._player = AudioPlayer()
        self._player.error.connect(lambda msg: self._log(f"⚠️ player: {msg}"))
        left.addWidget(self._player)

        # --- progresso + log
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)  # percentual (denominador: estimativa de duração)
        self._progress.setFixedHeight(14)
        self._progress.setVisible(False)
        self._progress_est = 0.0  # segundos de áudio estimados para o texto atual
        left.addWidget(self._progress)

        self._progress_line = QLabel("")
        self._progress_line.setWordWrap(True)
        self._progress_line.setStyleSheet("color: #555;")
        left.addWidget(self._progress_line)

        left.addWidget(QLabel("<b>📋 Log</b>"))
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(3000)
        left.addWidget(self._log_view, 2)

        left_w = QWidget(central)
        left_w.setLayout(left)

        # ============================ coluna direita =========================
        right_w = QWidget(central)
        right = QVBoxLayout(right_w)
        right.setSpacing(8)
        right_w.setFixedWidth(330)

        right.addWidget(QLabel("<b>⚙️ Configurações</b>"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        # Idioma
        grid.addWidget(QLabel("Idioma"), 0, 0)
        self._lang = QComboBox()
        # pt-br primeiro (público-alvo), depois os demais em ordem alfabética
        order = [c for c in ("pt-br", *sorted(pyvox.LANGS)) if c in pyvox.LANGS]
        for code in order:
            self._lang.addItem(LANG_LABELS.get(code, code), code)
        self._lang.setCurrentIndex(self._lang.findData("pt-br"))
        grid.addWidget(self._lang, 0, 1)

        # Narrador (botões segmentados)
        grid.addWidget(QLabel("Narrador"), 1, 0)
        narr_box = QWidget()
        narr_lay = QHBoxLayout(narr_box)
        narr_lay.setContentsMargins(0, 0, 0, 0)
        narr_lay.setSpacing(4)
        self._narr_group = QButtonGroup(self)
        self._narr_group.setExclusive(True)
        self._narr_btns: dict[str, QPushButton] = {}
        for value, label, tip in (
            ("auto", "Automática", "voz padrão do idioma"),
            ("masculino", "Masculino", "narrador (se existir no idioma)"),
            ("feminino", "Feminino", "narradora (se existir no idioma)"),
        ):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setToolTip(tip)
            self._narr_group.addButton(b)
            self._narr_btns[value] = b
            narr_lay.addWidget(b, 1)
        self._narr_btns["auto"].setChecked(True)
        grid.addWidget(narr_box, 1, 1)

        # Voz exata
        grid.addWidget(QLabel("Voz"), 2, 0)
        voice_lay = QHBoxLayout()
        voice_lay.setSpacing(4)
        self._voice = QComboBox()
        self._voice.setToolTip("Voz exata do Kokoro-82M (deixe em “automática” para usar o narrador/padrão)")
        btn_voices = QPushButton("↻")
        btn_voices.setFixedWidth(30)
        btn_voices.setToolTip("Recarregar a lista de vozes (consulta o Hugging Face)")
        btn_voices.clicked.connect(lambda: self._refresh_voice_list(self._lang.currentData() or "pt-br"))
        voice_lay.addWidget(self._voice, 1)
        voice_lay.addWidget(btn_voices)
        voice_w = QWidget()
        voice_w.setLayout(voice_lay)
        grid.addWidget(voice_w, 2, 1)

        # Velocidade
        grid.addWidget(QLabel("Velocidade"), 3, 0)
        speed_box = QWidget()
        speed_lay = QHBoxLayout(speed_box)
        speed_lay.setContentsMargins(0, 0, 0, 0)
        speed_lay.setSpacing(8)
        self._speed = QSlider(Qt.Orientation.Horizontal)
        self._speed.setRange(50, 200)   # ×100
        self._speed.setValue(100)
        self._speed.setSingleStep(5)
        self._speed.setToolTip("Velocidade da fala (1.0 = natural)")
        self._speed_lbl = QLabel("1.00x")
        self._speed.valueChanged.connect(self._on_speed_changed)
        speed_lay.addWidget(self._speed, 1)
        speed_lay.addWidget(self._speed_lbl)
        grid.addWidget(speed_box, 3, 1)

        # Threads
        cpu = os.cpu_count() or 4
        grid.addWidget(QLabel("Threads"), 4, 0)
        threads_box = QWidget()
        threads_lay = QHBoxLayout(threads_box)
        threads_lay.setContentsMargins(0, 0, 0, 0)
        threads_lay.setSpacing(8)
        self._threads = QSlider(Qt.Orientation.Horizontal)
        self._threads.setRange(1, cpu)
        self._threads.setValue(cpu)
        self._threads.setToolTip("Núcleos de CPU dedicados ao torch")
        self._threads_lbl = QLabel(str(cpu))
        self._threads.valueChanged.connect(lambda v: self._threads_lbl.setText(str(v)))
        threads_lay.addWidget(self._threads, 1)
        threads_lay.addWidget(self._threads_lbl)
        grid.addWidget(threads_box, 4, 1)

        # Formato
        grid.addWidget(QLabel("Formato"), 5, 0)
        self._fmt = QComboBox()
        self._fmt.addItem("WAV (sem perdas)", "wav")
        self._fmt.addItem("MP3 (128 kbps)", "mp3")
        self._fmt.setToolTip("MP3 usa o ffmpeg do sistema via pydub")
        grid.addWidget(self._fmt, 5, 1)

        grid.setColumnStretch(1, 1)
        right.addLayout(grid)
        right.addSpacing(6)

        # Botões de ação
        self._btn_run = QPushButton("🎧  Gerar narração")
        self._btn_run.setObjectName("runBtn")
        self._btn_run.setFixedHeight(44)
        self._btn_run.setToolTip("Ctrl+Enter")
        self._btn_run.clicked.connect(self._on_run)
        right.addWidget(self._btn_run)

        self._btn_cancel = QPushButton("⏹ Cancelar síntese")
        self._btn_cancel.setToolTip("Interrompe no próximo chunk (o áudio parcial é mantido)")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._on_cancel)
        right.addWidget(self._btn_cancel)

        right.addStretch(1)

        hint = QLabel(
            "<span style='color:#666;'>💡 1ª geração baixa o modelo Kokoro-82M "
            "(~330 MB). Os arquivos ficam em <b>saida/</b> no projeto.</span>")
        hint.setWordWrap(True)
        right.addWidget(hint)

        # Montagem
        root.addWidget(left_w, 3)
        root.addWidget(right_w, 2)
        # ------------------------------------------------------- sessões (abas)
        tabs = QTabWidget(self)
        tabs.addTab(central, "🎙️ Narração (pyvox)")
        tabs.addTab(self._epub, "📚 EPUB (pylibre)")
        self.setCentralWidget(tabs)

        # Barra de status — estado do Kokoro-82M em memória (fonte: cache do pyvox)
        self._model_lbl = QLabel("")
        self._model_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._model_lbl.setToolTip(
            "Estado do modelo Kokoro-82M neste processo: uma instância por idioma, "
            "carregada na 1ª narração e reusada em todas as seguintes (inclusive na sessão EPUB).")
        self.statusBar().addPermanentWidget(self._model_lbl)
        self._update_model_lbl()

        # Atalho
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._on_run)

        # Estilo mínimo (botão principal)
        self.setStyleSheet(
            "QPushButton#runBtn { background: #4f46e5; color: white;"
            " font-weight: 600; font-size: 14px; border: none; border-radius: 8px; }"
            "QPushButton#runBtn:hover { background: #4338ca; }"
            "QPushButton#runBtn:disabled { background: #b6b3f2; }")

    # ------------------------------------------------------------------ voz/idioma
    def _set_lang(self, lang: str) -> None:
        code = pyvox.LANGS.get(lang, "p")
        self._fill_voices(offline_voices(code))
        self._refresh_voice_list(lang)

    def _fill_voices(self, voices: list[str]) -> None:
        current = self._voice.currentText()
        self._voice.blockSignals(True)
        self._voice.clear()
        self._voice.addItem(AUTO)
        for v in voices:
            self._voice.addItem(v)
        idx = self._voice.findText(current)
        self._voice.setCurrentIndex(max(0, idx))
        self._voice.blockSignals(False)

    def _refresh_voice_list(self, lang: str) -> None:
        """Busca online (Hugging Face) em background; mantém o offline na hora."""
        self._voices_lang = lang
        w = VoiceListWorker(lang, parent=self)
        w.done.connect(lambda voices: self._on_voice_list(lang, voices))
        w.done.connect(w.deleteLater)  # depois do handler acima (ordem de conexão)
        self._voices_worker = w
        w.start()

    def _on_voice_list(self, lang: str, voices: list[str]) -> None:
        if self._voices_lang != lang or self._lang.currentData() != lang:
            return  # resposta de uma geração antiga — ignora
        if not voices:
            return
        self._fill_voices(voices)
        self.statusBar().showMessage(f"vozes de {lang} atualizadas ({len(voices)})", 4000)

    # ------------------------------------------------------------------ helpers
    def _log(self, msg: str) -> None:
        self._log_view.appendPlainText(msg)

    def _narrator(self) -> str:
        return next(v for v, b in self._narr_btns.items() if b.isChecked())

    def _speed_value(self) -> float:
        return self._speed.value() / 100.0

    def _on_text_changed(self) -> None:
        n = len(self._text.toPlainText())
        self._char_lbl.setText(f"{n:,} caracteres")

    def _on_speed_changed(self, v: int) -> None:
        self._speed_lbl.setText(f"{v / 100.0:.2f}x")

    # ------------------------------------------------------------------ arquivos
    def _on_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir arquivo de texto", str(ROOT),
            "Textos (*.txt *.md *.text);;Todos os arquivos (*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            QMessageBox.critical(self, "pylibra", f"Não consegui ler o arquivo:\n{e}")
            return
        self._text.setPlainText(text)
        stem = re.sub(r"[\\/:*\"<>|\x00-\x1f]", " ", Path(path).stem)
        self._file_stem = re.sub(r"\s+", " ", stem).strip(" .") or "texto"
        self.statusBar().showMessage(f"carregado: {Path(path).name}", 6000)

    def _on_clear(self) -> None:
        self._text.clear()
        self._file_stem = None

    def _on_open_folder(self) -> None:
        SAIDA_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(SAIDA_DIR)))

    # ------------------------------------------------------------------ geração
    def _on_run(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        text = self._text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "pylibra",
                                "Cole um texto ou abra um arquivo .txt antes de gerar.")
            return

        lang = self._lang.currentData() or "pt-br"
        try:
            voice = resolve_voice(lang, self._narrator(), self._voice.currentText())
        except ValueError as e:
            QMessageBox.critical(self, "pylibra", str(e))
            return

        fmt = self._fmt.currentData() or "wav"
        base = self._file_stem or "texto"
        out_wav = plan_output(SAIDA_DIR, base, fmt)

        est = estimate_warning(text)
        if est:
            self.statusBar().showMessage(est, 10000)

        self.cancel_event.clear()
        self._log("")
        self._log("─" * 64)
        self._log(f"▶ iniciando — voz {voice} · {lang} · {self._speed_value():.2f}x · "
                  f"{len(text):,} chars · formato {fmt.upper()} → {out_wav.name}")
        # barra: 0–100 com denominador estimado (palavras × s/palavra); avança
        # com os segundos de áudio reais que o motor vai yieldando por chunk
        self._progress_est = estimate_audio_seconds(text)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._progress_line.setText("iniciando… (na 1ª vez o modelo ~330 MB é baixado)")
        self._result_lbl.setText("gerando…")
        self._set_running(True)

        self._worker = SynthWorker(
            text=text, lang=lang, voice=voice, speed=self._speed_value(),
            threads=self._threads.value(), output=out_wav, fmt=fmt,
            cancel=self.cancel_event, parent=self)
        self._worker.log_line.connect(self._on_log_line)
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_cancel(self) -> None:
        self.cancel_event.set()
        self._log("⏹ cancelamento solicitado — vai parar no próximo chunk…")
        self._btn_cancel.setEnabled(False)
        self._progress_line.setText("cancelando…")

    # ------------------------------------------------- estado do modelo (barra)
    @staticmethod
    def _model_langs() -> list[str]:
        """Idiomas com pipeline Kokoro em memória (cache real do pyvox)."""
        pipes = getattr(pyvox, "_PIPELINES", None) or {}
        reverse = {code: name for name, code in pyvox.LANGS.items()}
        return sorted(reverse.get(code, code) for code in pipes)

    def _update_model_lbl(self) -> None:
        if self._model_loading:
            self._model_lbl.setText(
                "<span style=\"color:#b45309;font-weight:600\">⏳ Kokoro-82M: carregando…</span>")
            return
        langs = self._model_langs()
        if langs:
            self._model_lbl.setText(
                "<span style=\"color:#15803d;font-weight:600\">✓ Kokoro-82M em memória"
                f" ({', '.join(langs)})</span>")
        else:
            self._model_lbl.setText(
                "<span style=\"color:#6b7280\">○ Kokoro-82M: não carregado "
                "(baixa na 1ª narração)</span>")

    def _on_epub_model(self, state: str) -> None:
        """Callback da sessão EPUB: 'loading' | 'ready'."""
        self._model_loading = (state == "loading")
        self._update_model_lbl()

    # ------------------------------------------------- sinais do worker
    def _on_log_line(self, msg: str) -> None:
        self._log(msg)
        self._progress_line.setText(msg)
        if "carregando modelo" in msg:
            self._model_loading = True
            self._update_model_lbl()
        elif "modelo pronto" in msg:
            self._model_loading = False
            self._update_model_lbl()

    def _on_progress(self, line: str) -> None:
        self._log(line)
        self._progress_line.setText(line)
        sec = audio_seconds_from_line(line)
        if sec is not None:
            self._progress.setValue(progress_percent(sec, self._progress_est))

    def _on_succeeded(self, stats: dict, path: str) -> None:
        self._progress.setValue(100)
        self._progress.setVisible(False)
        self._model_loading = False  # garante: se terminou, o modelo está em memória
        self._update_model_lbl()
        self._log(f"✅ pronto — {stats['audio_seconds']:.1f}s de áudio · {stats['chunks']} chunks · "
                  f"{stats['elapsed']:.1f}s de CPU (RTF {stats['rtf']:.2f})")
        self._log(f"📁 salvo em: {path}")
        self._result_lbl.setText(f"✔ {Path(path).name}")
        self._player.load(path, autoplay=True)
        self.statusBar().showMessage(
            f"✔ {stats['audio_seconds']:.1f}s de áudio gerado em {stats['elapsed']:.1f}s", 10000)

    def _on_cancelled(self, path: str) -> None:
        self._progress.setVisible(False)
        self._log("⏹ cancelado pelo usuário.")
        if Path(path).stat().st_size > 0:
            self._log(f"📁 áudio parcial mantido: {path}")
            self._result_lbl.setText(f"⏹ parcial: {Path(path).name}")
            self._player.load(path, autoplay=False)
        self.statusBar().showMessage("síntese cancelada", 8000)

    def _on_failed(self, msg: str) -> None:
        self._progress.setVisible(False)
        self._log(f"❌ {msg}")
        self._result_lbl.setText("erro na síntese")
        self.statusBar().showMessage("erro na síntese — veja o log", 10000)

    def _on_worker_finished(self) -> None:
        self._progress.setVisible(False)
        self._set_running(False)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    # ------------------------------------------------------------- habilitação
    def _set_running(self, running: bool) -> None:
        self._text.setReadOnly(running)
        self._lang.setEnabled(not running)
        self._voice.setEnabled(not running)
        for b in self._narr_btns.values():
            b.setEnabled(not running)
        self._speed.setEnabled(not running)
        self._threads.setEnabled(not running)
        self._fmt.setEnabled(not running)
        self._btn_run.setEnabled(not running)
        self._btn_cancel.setEnabled(running)

    # ------------------------------------------------------------------ saída
    @staticmethod
    def _thread_running(thread) -> bool:
        """isRunning() tolerante: o objeto C++ pode já ter sido deletado (deleteLater)."""
        if thread is None:
            return False
        try:
            return thread.isRunning()
        except RuntimeError:
            return False

    def closeEvent(self, ev) -> None:
        # worker EPUB (leitura): aguarda terminar — leitura é rápida e sem rede.
        # (wait() puro, sem bombear eventos: evita race com deleteLater de outros workers)
        epub_worker = getattr(self._epub, "_worker", None)
        if epub_worker is not None:
            try:
                if epub_worker.isRunning():
                    epub_worker.wait(3_000)
            except RuntimeError:
                pass  # C++ já deletado (deleteLater) — nada a fazer
        # worker de vozes (rede): aguarda pouco e mata se travado — evita
        # "QThread: Destroyed while thread is still running" ao sair
        if self._thread_running(self._voices_worker):
            if not self._voices_worker.wait(3_000):
                self._voices_worker.terminate()
                self._voices_worker.wait(1_000)
        if self._thread_running(self._worker):
            ret = QMessageBox.question(
                self, "pylibra",
                "A síntese está em andamento. Sair mesmo assim?\n"
                "(o cancelamento é acionado e o áudio parcial é mantido)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
            self.cancel_event.set()
            if not self._worker.wait(20_000):
                self._worker.terminate()
                self._worker.wait(5_000)
        # narração do livro (pylibre→pyvox): pergunta, cancela e aguarda
        if self._epub.book_busy():
            ret = QMessageBox.question(
                self, "pylibra",
                "A narração do livro está em andamento. Sair mesmo assim?\n"
                "(os capítulos já prontos são mantidos)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
            self._epub.cancel_book()
            if not self._epub.wait_book(20_000):
                pass  # cancel já pedido; encerra mesmo assim
        ev.accept()
