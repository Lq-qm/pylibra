"""Player de áudio (QtMultimedia) com play/pause, seek, volume e tempos."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)


def _fmt(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60:d}:{s % 60:02d}"


class AudioPlayer(QWidget):
    """[▶] 0:12 ──────●──────── 1:38  🔊 [───●───]

    Sinais:
      error → mensagem de erro do backend de áudio (ex.: sem dispositivo)
    """

    error = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._output = QAudioOutput(self)
        self._player.setAudioOutput(self._output)
        self._path: str | None = None

        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedWidth(42)
        self._play_btn.setToolTip("Tocar / pausar")
        self._pos_lbl = QLabel("0:00")
        self._dur_lbl = QLabel("/ 0:00")
        self._seek = QSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 0)
        self._seek.setSingleStep(1000)
        self._seek.setTracking(False)
        self._seek.setToolTip("Arrastar para navegar")
        self._vol = QSlider(Qt.Orientation.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(100)
        self._vol.setFixedWidth(90)
        self._vol.setToolTip("Volume")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._play_btn)
        lay.addWidget(self._pos_lbl)
        lay.addWidget(self._seek, 1)
        lay.addWidget(self._dur_lbl)
        lay.addWidget(QLabel("🔊"))
        lay.addWidget(self._vol)

        self._play_btn.clicked.connect(self.toggle_play)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.errorOccurred.connect(self._on_error)
        self._vol.valueChanged.connect(lambda v: self._output.setVolume(v / 100.0))

        self.setEnabled(False)

    # ------------------------------------------------------------------ API
    @property
    def path(self) -> str | None:
        return self._path

    def load(self, path: str, autoplay: bool = True) -> None:
        """Carrega um arquivo local (wav/mp3) e (opcionalmente) começa a tocar."""
        self._path = path
        self._player.setSource(QUrl.fromLocalFile(path))
        self.setEnabled(True)
        self._pos_lbl.setText("0:00")
        self._dur_lbl.setText("/ 0:00")
        self._seek.setRange(0, 0)
        self._play_btn.setText("▶")
        if autoplay:
            self._player.play()

    def stop(self) -> None:
        self._player.stop()

    def toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    # ------------------------------------------------------------- callbacks
    def _on_state(self, state: QMediaPlayer.PlaybackState) -> None:
        self._play_btn.setText("⏸" if state == QMediaPlayer.PlaybackState.PlayingState else "▶")

    def _on_position(self, ms: int) -> None:
        if not self._seek.isSliderDown():
            self._seek.blockSignals(True)
            self._seek.setValue(int(ms))
            self._seek.blockSignals(False)
        self._pos_lbl.setText(_fmt(ms))

    def _on_duration(self, ms: int) -> None:
        self._dur_lbl.setText("/ " + _fmt(ms))
        if ms > 0:
            self._seek.setRange(0, int(ms))

    def _on_error(self, err: QMediaPlayer.Error) -> None:
        # PyQt6 emite o enum QMediaPlayer.Error; a mensagem vem da player
        msg = self._player.errorString() or str(err)
        self._on_state(QMediaPlayer.PlaybackState.StoppedState)
        self.error.emit(msg)
