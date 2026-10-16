# pylibra 🎙️

**O pylibra é uma aplicação desktop de narração de textos**: você cola um texto (ou abre um `.txt`), escolhe o idioma, a voz e o ritmo — e recebe um arquivo de áudio pronto, que toca no player embutido da própria janela.

É a **interface gráfica (PyQt6) do [pyvox](pyvox/)**, um motor de narração que usa o **Kokoro-82M**, um TTS open-source de alta qualidade rodando **100% em CPU** (sem GPU). O pyvox já vem com interface de linha de comando e web (Gradio); o pylibra leva o mesmo motor para o desktop, com a experiência de um aplicativo:

- **progresso em tempo real** (chunk a chunk, no log da janela) enquanto a CPU sintetiza;
- **cancelamento a qualquer momento** — a síntese para no próximo chunk e o áudio parcial é mantido, já tocável;
- **player embutido** (play/pause, seek, volume) — não precisa de player externo;
- tudo em uma única janela, sem navegador nem terminal.

Em resumo: **texto entra, voz sai** — o pylibra é o "modo desktop" do pyvox.

```
┌────────────────────────────────────────────────────────────────────────┐
│  📄 Texto                      │  ⚙️ Configurações                     │
│  ┌──────────────────────────┐  │  Idioma      [Português (Brasil)]     │
│  │  Cole o texto a narrar…  │  │  Narrador    [Aut][Masculino][Femin.] │
│  └──────────────────────────┘  │  Voz         [automática ▾] [↻]       │
│  [Abrir .txt] [Limpar]         │  Velocidade  [────●───] 1.00x        │
│                                │  Threads     [───●────] 8           │
│  🎧 Resultado                  │  Formato     [WAV ▾]                  │
│  [▶] 0:12 ────●───── 1:38 🔊   │  ┌──────────────────────────┐        │
│                                │  │   🎧  Gerar narração     │        │
│  [progresso indeterminado]     │  └──────────────────────────┘        │
│  📋 Log (chunk a chunk)        │  [⏹ Cancelar síntese]               │
└────────────────────────────────────────────────────────────────────────┘
```

## ✨ O que dá para fazer

- 📝 Colar texto no editor ou abrir `.txt`/`.md` (o nome do arquivo vira o nome da saída)
- 🌍 Narrar em 9 idiomas (pt-br, en-us, en-gb, es, fr-fr, hi, it, ja, zh)
- 🎤 Escolher **narrador automático / masculino / feminino** ou uma **voz exata**
  (`pf_dora`, `pm_alex`, …) — a lista é atualizada online (Hugging Face, em background,
  com fallback offline)
- 🎚️ Ajustar a velocidade da fala (0.5×–2.0×) e os núcleos de CPU usados
- 📦 Exportar em **WAV** ou **MP3** — os arquivos ficam em `saida/`, sem sobrescrever
- ⏹ Cancelar no meio (o áudio parcial continua tocável)
- ⌨️ `Ctrl+Enter` gera a narração; botão **📂** abre a pasta de saída

## 📋 Requisitos

| Item | Obs. |
|---|---|
| Python 3.10+ | testado com 3.14 |
| `pyvox/.venv` | já tem torch CPU + kokoro (veja `pyvox/README.md`) |
| PyQt6 | instalado no venv do pyvox (veja abaixo) |
| opcional (para gerar MP3) | `ffmpeg` no sistema |

## 🚀 Como rodar

```bash
# 1) instalar o PyQt6 no venv do pyvox (uma vez só)
uv pip install --python pyvox/.venv/bin/python PyQt6

# 2) abrir a aplicação
./run.sh
# ou:
pyvox/.venv/bin/python main.py
```

> A **1ª narração** baixa o modelo Kokoro-82M (~330 MB) e a voz escolhida do
> Hugging Face (cache em `~/.cache/huggingface`); nas seguintes o modelo fica
> em cache na memória do processo. Em rede lenta o download pode demorar —
> o progresso aparece no log e dá para cancelar.

## 🗂️ Estrutura do projeto

```
pylibra/
├── main.py              # entrada: injeta o motor pyvox no sys.path e sobe o Qt
├── pylibra/
│   ├── worker.py        # SynthWorker (QThread) + resolução de voz + saída sem colisão
│   ├── audio_player.py  # widget player (QMediaPlayer/QAudioOutput)
│   └── main_window.py   # UI principal
├── tests/
│   └── e2e_fake.py      # E2E do pipeline Qt com motor fake (sem baixar modelo)
├── pyvox/               # motor (CLI + web Gradio) — importado como módulo `pyvox`
└── saida/               # arquivos gerados
```

Como funciona por dentro, em uma frase: a síntese roda em uma **thread Qt**
consumindo o generator `pyvox.synthesize_stream`, e cada chunk yieldado vira um
**sinal Qt** (progresso, sucesso, cancelamento, erro) — a interface nunca trava,
nem durante o carregamento do modelo.

### Testes

```bash
pyvox/.venv/bin/python tests/e2e_fake.py   # sucesso, mp3, cancelamento, falha (motor fake)
```
