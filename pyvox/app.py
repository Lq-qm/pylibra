#!/usr/bin/env python3
"""pyvox web — interface gráfica (Gradio) do narrador pyvox (Kokoro-82M, CPU).

Uso:
    .venv/bin/python app.py                      # abre em http://127.0.0.1:7860
    .venv/bin/python app.py --port 8080
    .venv/bin/python app.py --host 0.0.0.0       # acessível na rede local
    .venv/bin/python app.py --share              # link público temporário (túnel Gradio)

A interface reutiliza o motor do pyvox.py (mesmo cache de modelo, mesma
qualidade do áudio). O primeiro clique baixa o modelo (~330 MB) e depois
ele fica em cache na memória do processo.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import threading
from pathlib import Path

import gradio as gr

import pyvox

# --------------------------------------------------------------------------- #
# Lógica de apoio
# --------------------------------------------------------------------------- #
SaidaDir = Path(__file__).resolve().parent / "saida"

NARRATOR_LABELS = ["automática (padrão)", "masculino", "feminino"]

# Coluna única centralizada (largura máxima ~740px)
CSS = """
#pyvox-col {
    max-width: 1180px;
    width: 100%;
    margin-left: auto;
    margin-right: auto;
}
"""


def _voices_for(lang: str) -> list[str]:
    """Vozes do idioma (Hugging Face com fallback offline), sempre com 'automática'."""
    try:
        return ["automática"] + pyvox.list_voices(pyvox.LANGS[lang])
    except Exception:
        pool = set(pyvox.DEFAULT_VOICES.values())
        return ["automática"] + sorted(v for v in pool if v.startswith(pyvox.LANGS[lang]))


def resolve_voice(lang: str, narrator: str, voice: str) -> str:
    """Resolve a voz final: exata > narrador (m/f) > padrão do idioma."""
    code = pyvox.LANGS[lang]
    if voice and voice != "automática":
        return voice
    if narrator == "masculino":
        cands = pyvox.NARRATOR_VOICES.get(code, {})
        if "m" in cands:
            return cands["m"]
        raise ValueError(f"o idioma **{lang}** não tem voz masculina no Kokoro-82M — "
                         "escolha uma voz exata")
    if narrator == "feminino":
        cands = pyvox.NARRATOR_VOICES.get(code, {})
        if "f" in cands:
            return cands["f"]
        raise ValueError(f"o idioma **{lang}** não tem voz feminina no Kokoro-82M — "
                         "escolha uma voz exata")
    return pyvox.DEFAULT_VOICES[code]


def _base_name(name: str) -> str:
    """Base de saída a partir do nome do arquivo de entrada (preserva espaços/acentos).

    Ex.: ``"nome do arquivo de entrada.txt"`` → ``"nome do arquivo de entrada"``.
    """
    stem = Path(name).stem
    stem = re.sub(r"[\\/:*\"<>|\x00-\x1f]", " ", stem)   # só remove caracteres ilegais
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    return stem or "texto"


def _unique_out(base: str) -> Path:
    """Caminho em saida/ com o nome base; sufixa _2, _3… se já existir (não sobrescreve)."""
    SaidaDir.mkdir(parents=True, exist_ok=True)
    cand = SaidaDir / f"{base}.wav"
    i = 2
    while cand.exists():
        cand = SaidaDir / f"{base}_{i}.wav"
        i += 1
    return cand


def _estimate(text: str) -> str | None:
    """Aviso grosseiro de duração para textos longos (≈15 chars/s de fala, RTF ~0.25)."""
    n = len(text)
    if n < 20_000:
        return None
    est_audio = n / 15.0
    est_cpu = est_audio * 0.3
    return (f"⚠️ **texto longo** ({n:,} chars) — estimativa: "
            f"~{est_audio / 60:.0f} min de áudio, ~{est_cpu / 60:.0f} min de CPU. "
            "Considere `--max-chars` via CLI para testes.")


# --------------------------------------------------------------------------- #
# Geração (generator → progresso em tempo real no Gradio)
# --------------------------------------------------------------------------- #
def generate(file_in, text: str, lang: str, narrator: str, voice: str,
             speed: float, threads: int, fmt: str = "wav"):
    fpath = getattr(file_in, "path", None) or (
        file_in.get("path") if isinstance(file_in, dict) else file_in)
    text = (text or "").strip()
    if not text and fpath:
        # editor vazio + arquivo enviado → lê o conteúdo do arquivo
        try:
            text = Path(fpath).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            pass
    if not text:
        yield "⚠️ informe um texto (cole ou envie um `.txt`).", None
        return

    try:
        voice_name = resolve_voice(lang, narrator, voice)
    except ValueError as e:
        yield f"⚠️ {e}", None
        return

    est = _estimate(text)
    if est:
        yield est, None

    # Nome da saída = nome do arquivo de entrada (ex.: livro.txt → livro.wav)
    base = _base_name(fpath) if fpath else "texto"
    out = _unique_out(base)
    status0 = f"🎙️ iniciando síntese — voz **{voice_name}**, {lang}, " \
              f"velocidade {speed:.2f}x → `{out.name}`…"
    yield status0, None

    try:
        stats: dict | None = None
        for item in pyvox.synthesize_stream(text, lang, voice_name, float(speed),
                                            str(out), threads=int(threads or 0)):
            if isinstance(item, dict):
                stats = item
            else:
                yield f"🎙️ {item}", None

        assert stats is not None
        if (fmt or "wav").lower() == "mp3":
            mp3 = out.with_suffix(".mp3")
            pyvox.encode_mp3(out, mp3)
            out.unlink()  # remove o WAV intermediário
            out = mp3
        status = (
            f"✅ **pronto!** {stats['audio_seconds']:.1f}s de áudio · "
            f"{stats['chunks']} chunks · {stats['elapsed']:.1f}s de processamento "
            f"(RTF {stats['rtf']:.2f})\n\n"
            f"salvo em `{out}`"
        )
        yield status, str(out)
    except KeyboardInterrupt:
        yield "⛔ interrompido — o áudio parcial ficou salvo em `" + str(out) + "`.", str(out)
    except Exception as e:
        yield f"❌ erro na síntese: {e}", None


# --------------------------------------------------------------------------- #
# Batch — fila de vários .txt
# --------------------------------------------------------------------------- #
CANCEL = threading.Event()  # sinal de cancelamento checado entre chunks


def _batch_item(f):
    """Extrai (nome, texto) de um arquivo enviado; None se ilegível/vazio."""
    path = getattr(f, "path", None) or (f.get("path") if isinstance(f, dict) else f)
    if not path:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text:
        return None
    return Path(path).name, text


def batch_generate(files, lang: str, narrator: str, voice: str,
                   speed: float, threads: float, fmt: str = "wav"):
    """Processa vários .txt em Fila (FIFO): um a um, com log e downloads."""
    if not files:
        yield "⚠️ envie pelo menos 1 arquivo `.txt`.", None
        return
    files = files if isinstance(files, list) else [files]

    try:
        voice_name = resolve_voice(lang, narrator, voice)
    except ValueError as e:
        yield f"⚠️ {e}", None
        return

    total = len(files)
    CANCEL.clear()

    done: list[str] = []
    skipped = failed = 0
    log = [f"📚 **fila:** {total} arquivo(s) · voz **{voice_name}** · {lang} · "
           f"{speed:.2f}x", ""]
    yield "\n".join(log), None

    for idx, f in enumerate(files, 1):
        if CANCEL.is_set():
            log.append("⛔ **cancelado** pelo usuário — parando a fila.")
            break

        item = _batch_item(f)
        if item is None:
            skipped += 1
            log.append(f"[{idx}/{total}] ⏭️ ilegível ou vazio — ignorado.")
            yield "\n".join(log), (done or None)
            continue

        name, text = item
        out = _unique_out(_base_name(name))
        line = f"[{idx}/{total}] ▶️ `{name}` — {len(text):,} chars…"
        log.append(line)
        yield "\n".join(log), (done or None)

        try:
            stats = None
            for chunk in pyvox.synthesize_stream(text, lang, voice_name, float(speed),
                                                 str(out), threads=int(threads or 0)):
                if CANCEL.is_set():
                    log[-1] = f"[{idx}/{total}] ⛔ `{name}` — cancelado (parcial: `{out.name}`)"
                    raise KeyboardInterrupt
                if isinstance(chunk, dict):
                    stats = chunk
                else:
                    log[-1] = f"[{idx}/{total}] ▶️ `{name}` — {chunk}"
                yield "\n".join(log), (done or None)

            assert stats is not None
            if (fmt or "wav").lower() == "mp3":
                mp3 = out.with_suffix(".mp3")
                pyvox.encode_mp3(out, mp3)
                out.unlink()  # remove o WAV intermediário
                out = mp3
            done.append(str(out))
            log[-1] = (f"[{idx}/{total}] ✅ `{name}` — {stats['audio_seconds']:.1f}s de áudio · "
                       f"{stats['chunks']} chunks · RTF {stats['rtf']:.2f} → `{out.name}`")
        except KeyboardInterrupt:
            if not CANCEL.is_set():
                log[-1] = f"[{idx}/{total}] ⛔ `{name}` — interrompido."
            failed += 1
        except Exception as e:
            failed += 1
            log[-1] = f"[{idx}/{total}] ❌ `{name}` — {e}"
        log.append("")
        yield "\n".join(log), (done or None)

    resumo = (f"**resumo:** {len(done)} ok · {skipped} ignorado(s) · "
              f"{failed} falha(s) — arquivos em `saida/`")
    log.append(resumo)
    yield "\n".join(log), (done or None)


def cancel_batch() -> str:
    CANCEL.set()
    return "⏹ cancelando após o chunk atual…"


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
def build_demo() -> gr.Blocks:
    lang_options = sorted(pyvox.LANGS)
    cpu = os.cpu_count() or 4

    with gr.Blocks(title="pyvox — narrador de textos") as demo:
        gr.Markdown(
            "# 🎙️ pyvox\n"
            "Narra textos com o motor **Kokoro-82M** (CPU). "
            "Cole um texto, envie um `.txt`, escolha a voz e clique em **Gerar**."
        )

        with gr.Column(elem_id="pyvox-col"):
            with gr.Row(equal_height=True):
                # ---------------------- COLUNA: ARQUIVO ÚNICO ----------------- #
                with gr.Column(scale=1, min_width=440):
                    gr.Markdown("### 📄 Arquivo único")
                    text_box = gr.Textbox(
                        label="Texto",
                        placeholder=(
                            "Cole seu texto aqui…\n\n"
                            "“Era uma noite de inverno, e a cidade dormia sob um "
                            "silêncio profundo. Mas quem percebeu a primeira estrela?”"
                        ),
                        lines=4,
                    )
                    file_in = gr.File(label="ou envie um arquivo .txt",
                                      file_types=[".txt", ".md"],
                                      file_count="single", height=160)
                    with gr.Row():
                        lang = gr.Dropdown(lang_options, value="pt-br",
                                           label="Idioma", scale=1)
                        narrator = gr.Radio(NARRATOR_LABELS, value=NARRATOR_LABELS[0],
                                            label="Narrador", scale=2)
                    voice = gr.Dropdown(["automática"], value="automática",
                                        label="Voz exata (opcional)")
                    fmt = gr.Dropdown(["wav", "mp3"], value="wav",
                                      label="Formato da saída (.wav / .mp3)")
                    with gr.Row():
                        speed = gr.Slider(0.5, 2.0, value=1.0, step=0.05,
                                          label="Velocidade (1.0 = natural)")
                        threads = gr.Slider(1, max(4, cpu), value=cpu, step=1,
                                            label="Threads de CPU")
                    btn = gr.Button("🎧 Gerar narração", variant="primary")

                    status = gr.Markdown("aguardando…")
                    audio = gr.Audio(type="filepath", label="Áudio", autoplay=True)

                # ------------------ COLUNA: VÁRIOS ARQUIVOS (FILA) ----------- #
                with gr.Column(scale=1, min_width=440):
                    gr.Markdown("### 📚 Vários arquivos (fila)")
                    batch_files = gr.File(label="Arquivos .txt (seleção múltipla)",
                                          file_types=[".txt", ".md"], file_count="multiple",
                                          height=160)
                    with gr.Row():
                        b_lang = gr.Dropdown(lang_options, value="pt-br",
                                             label="Idioma", scale=1)
                        b_narrator = gr.Radio(NARRATOR_LABELS, value=NARRATOR_LABELS[0],
                                              label="Narrador", scale=2)
                    b_voice = gr.Dropdown(["automática"], value="automática",
                                          label="Voz exata (opcional)")
                    b_fmt = gr.Dropdown(["wav", "mp3"], value="wav",
                                        label="Formato da saída (.wav / .mp3)")
                    with gr.Row():
                        b_speed = gr.Slider(0.5, 2.0, value=1.0, step=0.05,
                                            label="Velocidade (1.0 = natural)")
                        b_threads = gr.Slider(1, max(4, cpu), value=cpu, step=1,
                                              label="Threads de CPU")
                    with gr.Row():
                        b_run = gr.Button("▶️ Processar fila", variant="primary", scale=2)
                        b_cancel = gr.Button("⏹ Cancelar", scale=1)
                    b_status = gr.Markdown("fila vazia — envie arquivos e clique em **Processar fila**.")
                    b_downloads = gr.File(label="Resultados (clique para baixar)",
                                          file_count="multiple")
        gr.Markdown(
            "<details><summary>💡 dicas</summary><br>"
            "• O **primeiro clique** baixa o modelo Kokoro-82M (~330 MB) — depois fica em cache.<br>"
            "• Vozes pt-br: `pf_dora` (narradora), `pm_alex` (narrador), `pm_santa`, `pf_emma`…<br>"
            "• Textos muito longos (livros): prefira o CLI `pyvox.py` — a web serve melhor trechos.<br>"
            "• Os arquivos ficam salvos na pasta `saida/` do projeto.<br>"
            "</details>"
        )

        # Vozes disponíveis mudam com o idioma
        lang.change(fn=lambda l: gr.Dropdown(choices=_voices_for(l), value="automática"),
                    inputs=[lang], outputs=[voice])
        b_lang.change(fn=lambda l: gr.Dropdown(choices=_voices_for(l), value="automática"),
                      inputs=[b_lang], outputs=[b_voice])

        btn.click(
            fn=generate,
            inputs=[file_in, text_box, lang, narrator, voice, speed, threads, fmt],
            outputs=[status, audio],
        )

        b_run.click(
            fn=batch_generate,
            inputs=[batch_files, b_lang, b_narrator, b_voice, b_speed, b_threads, b_fmt],
            outputs=[b_status, b_downloads],
        )
        b_cancel.click(fn=cancel_batch, outputs=[b_status])

    return demo


def main() -> None:
    p = argparse.ArgumentParser(description="Interface web (Gradio) do pyvox")
    p.add_argument("--host", default="127.0.0.1",
                   help="interface de rede (padrão: 127.0.0.1; use 0.0.0.0 p/ rede local)")
    p.add_argument("--port", type=int, default=7860, help="porta (padrão: 7860)")
    p.add_argument("--share", action="store_true",
                   help="cria link público temporário via túnel do Gradio")
    args = p.parse_args()

    # Verificação amigável de porta ocupada (evita o traceback do Gradio)
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((args.host, args.port))
        except OSError:
            sys.exit(
                f"erro: a porta {args.port} já está em uso em {args.host}.\n"
                f"  • Se o pyvox-web já está rodando, basta abrir "
                f"http://{args.host}:{args.port} no navegador.\n"
                f"  • Para usar outra porta: .venv/bin/python app.py --port {args.port + 1}"
            )

    demo = build_demo()
    demo.queue(default_concurrency_limit=1, api_open=False)  # 1 síntese por vez (CPU)
    demo.launch(server_name=args.host, server_port=args.port,
                theme=gr.themes.Soft(), css=CSS,
                share=args.share, inbrowser=False)


if __name__ == "__main__":
    main()
