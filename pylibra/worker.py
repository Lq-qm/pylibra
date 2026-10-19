"""Trabalho em background: síntese de voz (fora da thread de UI) e lista de vozes.

A síntese roda em ``QThread`` consumindo o generator ``pyvox.synthesize_stream``:
cada chunk yieldado vira um sinal Qt (progresso em tempo real no log da interface).
O cancelamento usa um ``threading.Event`` checado entre chunks (mesma semântica do
app Gradio do pyvox): interrompe no próximo chunk e mantém o áudio parcial.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

import pyvox  # motor — injetado via sys.path pelo main.py

AUTO = "automática"


LANG_LABELS: dict[str, str] = {
    "pt-br": "Português (Brasil)",
    "en-us": "Inglês (EUA)",
    "en-gb": "Inglês (UK)",
    "es": "Espanhol",
    "fr-fr": "Francês",
    "hi": "Hindi",
    "it": "Italiano",
    "ja": "Japonês",
    "zh": "Chinês (Mandarim)",
}


def offline_voices(code: str) -> list[str]:
    """Pool de vozes offline (padrões + narradores) filtrado pelo código do idioma."""
    pool = (set(pyvox.DEFAULT_VOICES.values())
            | {v for d in pyvox.NARRATOR_VOICES.values() for v in d.values()})
    return sorted(v for v in pool if v.startswith(code))


def resolve_voice(lang: str, narrator: str, voice: str) -> str:
    """Resolve a voz final: exata > narrador (m/f) > padrão do idioma.

    ``narrator``: "auto" | "masculino" | "feminino".
    Levanta ``ValueError`` com mensagem amigável se o idioma não tiver a voz pedida.
    """
    code = pyvox.LANGS[lang]
    if voice and voice != AUTO:
        return voice
    if narrator == "masculino":
        cands = pyvox.NARRATOR_VOICES.get(code, {})
        if "m" not in cands:
            raise ValueError(f"o idioma {lang} não tem voz masculina no Kokoro-82M — escolha uma voz exata")
        return cands["m"]
    if narrator == "feminino":
        cands = pyvox.NARRATOR_VOICES.get(code, {})
        if "f" not in cands:
            raise ValueError(f"o idioma {lang} não tem voz feminina no Kokoro-82M — escolha uma voz exata")
        return cands["f"]
    return pyvox.DEFAULT_VOICES[code]


def plan_output(saida: Path, base: str, fmt: str) -> Path:
    """Decide o caminho do arquivo final em ``saida/`` sem sobrescrever nada.

    Sempre devolve o caminho do **WAV intermediário** (a síntese grava em WAV e,
    se o formato pedido for MP3, converte depois). Evita colisões com sufixos
    ``_2, _3, …`` considerando também o WAV intermediário no caso do MP3.
    """
    saida.mkdir(parents=True, exist_ok=True)
    final_ext = ".mp3" if fmt.lower() == "mp3" else ".wav"
    cand = saida / f"{base}{final_ext}"
    i = 2
    while cand.exists() or (final_ext == ".mp3" and cand.with_suffix(".wav").exists()):
        cand = saida / f"{base}_{i}{final_ext}"
        i += 1
    return cand.with_suffix(".wav")


def estimate_warning(text: str) -> str | None:
    """Aviso grosseiro para textos longos (≈15 chars/s de fala, RTF ~0.25)."""
    n = len(text)
    if n < 20_000:
        return None
    est_audio = n / 15.0
    est_cpu = est_audio * 0.3
    return (f"texto longo ({n:,} chars) — estimativa: ~{est_audio / 60:.0f} min de áudio, "
            f"~{est_cpu / 60:.0f} min de CPU")


# ------------------------------------------------------------------ progresso
# O KPipeline não anuncia o total de chunks/duração antes de começar a gerar:
# cada linha de progresso traz só o acumulado real (“N.Ns de áudio”). Para a
# barra ter percentual, usamos uma estimativa de duração total (palavras ×
# segundos/palavra) como denominador — o numerador é o acumulado real.
_SECONDS_PER_WORD = 0.40            # ≈2,5 palavras/s (taxa típica do Kokoro)
_MIN_ESTIMATE_SECONDS = 1.0
_AUDIO_SECONDS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*s de áudio")


def estimate_audio_seconds(text: str) -> float:
    """Estima a duração total do áudio (s) a partir do texto (denominador da barra)."""
    words = len(text.split())
    return max(_MIN_ESTIMATE_SECONDS, words * _SECONDS_PER_WORD)


def audio_seconds_from_line(line: str) -> float | None:
    """Segundos de áudio acumulados em uma linha de progresso do pyvox
    (ex.: ``“[   12]    18.9s de áudio |  3.1s cpu | …”``).``"""
    m = _AUDIO_SECONDS_RE.search(line or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def progress_percent(audio_seconds: float | None, estimated_total: float) -> int:
    """Percentual 0–99 para exibição durante a síntese (100% só ao terminar)."""
    if not audio_seconds or estimated_total <= 0:
        return 0
    return max(0, min(99, int(audio_seconds / estimated_total * 100)))


class SynthWorker(QThread):
    """Roda ``pyvox.synthesize_stream`` fora da thread de UI.

    Sinais (entregues na thread de UI):
      log_line   → mensagens do motor (carregamento do modelo etc.)
      progress   → linha de progresso por chunk (ex.: ``[  12]  18.9s de áudio | …``)
      succeeded  → (stats: dict, caminho final: str)
      cancelled  → caminho do áudio parcial gerado
      failed     → mensagem de erro
    """

    log_line = pyqtSignal(str)
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(dict, str)
    cancelled = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, *, text: str, lang: str, voice: str, speed: float,
                 threads: int, output: Path, fmt: str, cancel: threading.Event,
                 parent=None):
        super().__init__(parent)
        self.text = text
        self.lang = lang
        self.voice = voice
        self.speed = float(speed)
        self.threads = int(threads)
        self.output = Path(output)
        self.fmt = fmt
        self._cancel = cancel

    def run(self) -> None:
        out = self.output
        try:
            stats: dict | None = None
            gen = pyvox.synthesize_stream(
                self.text, self.lang, self.voice, self.speed,
                str(out), self.threads, log=self.log_line.emit)

            cancelled = False
            for item in gen:
                if self._cancel.is_set():
                    cancelled = True
                    break
                if isinstance(item, dict):
                    stats = item
                else:
                    self.progress.emit(item)

            if cancelled:
                try:
                    gen.close()
                except Exception:  # noqa: BLE001
                    pass
                self.cancelled.emit(str(out))
                return

            if stats is None:
                self.failed.emit("a síntese terminou sem produzir áudio — o texto está vazio?")
                return

            final = out
            if self.fmt.lower() == "mp3":
                mp3 = out.with_suffix(".mp3")
                pyvox.encode_mp3(out, mp3)
                out.unlink(missing_ok=True)  # remove o WAV intermediário
                final = mp3

            self.succeeded.emit(stats, str(final))
        except Exception as e:  # noqa: BLE001 — reportado como mensagem na UI
            self.failed.emit(f"{type(e).__name__}: {e}")


class VoiceListWorker(QThread):
    """Busca as vozes do idioma no Hugging Face (com fallback offline no próprio pyvox)."""

    done = pyqtSignal(list)

    def __init__(self, lang: str, parent=None):
        super().__init__(parent)
        self.lang = lang

    def run(self) -> None:
        try:
            voices = pyvox.list_voices(pyvox.LANGS[self.lang])
        except Exception:  # noqa: BLE001
            voices = []
        self.done.emit(sorted(voices))
