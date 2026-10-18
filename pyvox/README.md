# pyvox 🎙️

> CLI em Python que narra arquivos de texto (`.txt`) usando o motor **Kokoro TTS** ([Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)).

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Kokoro TTS](https://img.shields.io/badge/motor-Kokoro--82M-8A2BE2)](https://huggingface.co/hexgrad/Kokoro-82M)
[![Device](https://img.shields.io/badge/device-CPU-orange)](https://pytorch.org/)

## ✨ Funcionalidades

- 📖 Narra qualquer arquivo `.txt` (ou texto direto via `--text`)
- 🗣️ Motor **Kokoro-82M** com vozes em 9 idiomas (pt-br, en-us, en-gb, es, fr-fr, hi, it, ja, zh)
- 🎤 Narrador masculino / narradora feminina com `--narrador`
- ⚙️ **Somente CPU** por enquanto — sem GPU, sem CUDA
- 📊 Progresso em tempo real com tempo de áudio, tempo de CPU e RTF (razão tempo real)
- ▶️ Reprodução do resultado com `--play` (ffplay/mpv/aplay)
- 🎚️ Velocidade ajustável, múltiplas vozes por idioma, controle de threads

## 📋 Requisitos

| Item | Versão |
|---|---|
| Python | 3.10+ |
| gerenciador de pacotes | `uv` (ou `pip`) |
| disco | ~1 GB (venv) + ~330 MB (modelo, baixado na 1ª execução) |
| opcional (para `--play`) | `ffplay`, `mpv` ou `aplay` no `PATH` |

## 🚀 Instalação

```bash
# 1) Crie o ambiente virtual
uv venv .venv

# 2) PyTorch SOMENTE CPU (use o índice CPU para não baixar a build CUDA)
uv pip install -i https://download.pytorch.org/whl/cpu torch

# 3) Dependências do projeto
uv pip install -r requirements.txt
```

## 🌐 Interface web (Gradio)

```bash
.venv/bin/python app.py                  # abre em http://127.0.0.1:7860
.venv/bin/python app.py --port 8080
.venv/bin/python app.py --host 0.0.0.0   # acessível na rede local
.venv/bin/python app.py --share          # link público temporário (túnel Gradio)
```

O que a UI oferece:

- 📝 texto colado ou upload de `.txt`/`.md` (botão “carregar no editor”)
- 🌍 9 idiomas, com lista de vozes atualizada por idioma (Hugging Face + fallback offline)
- 🎤 narrador masculino / feminino, ou voz exata (`pf_dora`, `pm_alex`, …)
- 🎚️ velocidade, threads de CPU e limite de caracteres
- ⏳ progresso em tempo real (chunk a chunk, com RTF ao final)
- ▶️ player com autoplay + download; arquivos ficam salvos em `saida/`
- 📚 **batch (fila de `.txt`)**: envie vários arquivos e eles são convertidos **um a um, na ordem** (FIFO), com log de progresso por arquivo, pulo de arquivos vazios, lista de downloads e botão **Cancelar** (age no próximo chunk)

O modelo Kokoro fica em cache na memória do processo — o 1º clique baixa
(~330 MB), os seguintes são instantâneos. Para livros inteiros, prefira o CLI.

## 📖 Uso (CLI)

```bash
# Narrar um arquivo (padrão: pt-br, narradora pf_dora) → gera <arquivo>.wav
.venv/bin/python pyvox.py meu_texto.txt -o saida.wav

# Narrador masculino (pt-br: pm_alex)
.venv/bin/python pyvox.py meu_texto.txt --narrador masculino

# Narradora feminina + velocidade + tocar o resultado
.venv/bin/python pyvox.py meu_texto.txt --narrador feminino --speed 1.2 --play

# Escolher uma voz exata
.venv/bin/python pyvox.py meu_texto.txt --voice pm_santa

# Listar as vozes disponíveis para um idioma
.venv/bin/python pyvox.py --list-voices --lang pt-br

# Narra texto direto, sem arquivo
.venv/bin/python pyvox.py --text "Olá, mundo."

# Teste rápido: limita a síntese aos primeiros N caracteres
.venv/bin/python pyvox.py meu_texto.txt --max-chars 500
```

### Opções

| Opção | Descrição |
|---|---|
| `file` | arquivo `.txt` a narrar (opcional com `--text`) |
| `--text TEXT` | narra texto direto, sem arquivo |
| `-l, --lang` | idioma: `pt-br` (padrão), `en-us`, `en-gb`, `es`, `fr-fr`, `hi`, `it`, `ja`, `zh` |
| `-g, --narrador` | `m`/`masculino` (narrador) ou `f`/`feminino` (narradora) — pt-br: m=`pm_alex`, f=`pf_dora` |
| `-v, --voice` | voz exata a usar (ex.: `pf_dora`, `pm_alex` — veja `--list-voices`) |
| `-s, --speed` | velocidade da fala (`0.5` = metade, `1.5` = 50% mais rápido; padrão `1.0`) |
| `-o, --output` | arquivo `.wav` de saída (padrão: `<arquivo>.wav`) |
| `--threads N` | threads de CPU (padrão: todos os núcleos) |
| `--max-chars N` | limita a síntese aos N primeiros caracteres (útil para testes) |
| `--play` | toca o áudio ao final |
| `--list-voices` | lista as vozes do idioma e sai |

### Exemplo de saída

```
carregando modelo Kokoro-82M (pt-br, voz=pf_dora, cpu)…
modelo pronto em 1.3s
[  12]     18.9s de áudio |      4.8s cpu | “O comandante da União…”
✔ salva em saida.wav | 18.9s de áudio | 12 chunks | 4.8s de processamento | RTF 0.25
```

## ⚙️ Como funciona

```
.txt ──► segmentação (linhas + frases, ~400 chars)
         └─► G2P (texto → fonemas) via misaki
              └─► Kokoro-82M (CPU) gera áudio chunk a chunk (24 kHz)
                   └─► WAV gravado incrementalmente + progresso no terminal
```

1. O texto é dividido em segmentos (linhas, com chunking por sentenças).
2. O `KPipeline` converte cada segmento em fonemas (G2P) e sintetiza o áudio na CPU.
3. Os chunks (24 kHz, 16-bit PCM) são gravados incrementalmente no `.wav`, com progresso na linha de comando e RTF ao final.

## 🎤 Narradores por idioma

| Idioma | Narrador (m) | Narradora (f) |
|---|---|---|
| pt-br | `pm_alex` | `pf_dora` |
| en-us | `am_michael` | `af_heart` |
| en-gb | `bm_fable` | `bf_emma` |
| es | `em_alex` | `ef_dora` |
| fr-fr | — (não disponível) | `ff_siwis` |
| hi | `hm_omega` | `hf_alpha` |
| it | `im_nicola` | `if_sara` |
| ja | `jm_kumo` | `jf_alpha` |
| zh | `zm_yunjian` | `zf_xiaobei` |

Outras vozes por idioma existem — veja `--list-voices` e use `--voice`.

## 📝 Notas

- A **1ª execução** baixa o modelo (~330 MB) e a voz escolhida do Hugging Face (cache em `~/.cache/huggingface`).
- Textos longos em CPU podem demorar — use `--max-chars` para testar; `Ctrl+C` interrompe mantendo o áudio já gerado.
- Para GPU no futuro: basta trocar `device="cpu"` por `"cuda"` em `pyvox.py`.

