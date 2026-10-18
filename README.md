# pylibra 🎙️

Aplicação desktop de **texto e voz**, organizada em **sessões** (abas), cada
uma expondo um motor Python do projeto como ferramenta gráfica. As sessões
ainda combinam os motores: a de EPUB lê o livro com o **pylibre** e narra os
capítulos com o **pyvox** (livro → texto → voz, numa janela só).

| Sessão | Motores | O que faz |
|---|---|---|
| 🎙️ **Narração** | [pyvox](pyvox/) | texto entra, voz sai — **Kokoro-82M** (TTS, **100% CPU**) |
| 📚 **EPUB** | [pylibre](pylibre/) + pyvox | lê `.epub`, lista os capítulos e **narra** os escolhidos (1 arquivo por capítulo) |

## ✨ O que dá para fazer

**🎙️ Narração (pyvox)**
- texto colado ou `.txt`/`.md`; 9 idiomas (pt-br, en-us, en-gb, es, fr-fr, hi, it, ja, zh)
- narrador **auto/masculino/feminino** ou voz exata (`pf_dora`, `pm_alex`, …) —
  lista atualizada online (Hugging Face) com fallback offline
- velocidade 0,5×–2,0×; progresso em tempo real (chunk a chunk); cancelar no meio
  (o áudio parcial é mantido e já tocável)
- player embutido; saída WAV/MP3 em `saida/`, **sem sobrescrever**; `Ctrl+Enter` narra

**📚 EPUB (pylibre + pyvox)**
- título + autores; capítulos na ordem de leitura (spine) com contagem de palavras; prévia do texto
- **narrar o capítulo selecionado ou todos** — um arquivo por capítulo em
  `saida/<livro>/` (`01 - Título.wav`), sem sobrescrever
- cancelar no meio (capítulos prontos + áudio parcial mantidos); player carrega
  cada capítulo pronto; modelo Kokoro carregado **uma vez só** para o livro

## 📋 Requisitos

| Item | Obs. |
|---|---|
| Python 3.10+ | testado com 3.14 (apenas no modo venv) |
| `pyvox/` + `pyvox/.venv` | motor de narração + ambiente (torch CPU, kokoro, PyQt6, spacy) |
| `pylibre/` | motor EPUB→texto — **repositório próprio, clonar na pasta do projeto** (zero dependências) |
| `ffmpeg` no sistema | **somente** para gerar MP3 |
| modelo Kokoro-82M (~330 MB) | baixado na 1ª narração → `~/.cache/huggingface/` |

> **Quais arquivos são realmente necessários** (e quais podem ser apagados):
> ver [docs/arquivos-necessarios.md](docs/arquivos-necessarios.md).

## 🚀 Como rodar

```bash
git clone <url-do-pylibre> pylibre    # 1) motor EPUB (repositório independente) — uma vez só
./run.sh                              # 2) abre a interface (usa o venv do pyvox)
```

### CLI (sem abrir a janela)

```bash
pyvox/.venv/bin/python main.py --speak "Olá, mundo!" -l pt-br -g f -o olá.mp3
pyvox/.venv/bin/python main.py --book livro.epub             # narra todos os capítulos
pyvox/.venv/bin/python main.py --book livro.epub -c 1,3 -g m -f mp3   # só caps. 1 e 3
pyvox/.venv/bin/python main.py --selftest                    # verifica motores + libs + UI
```

## 📦 Release standalone (sem venv, sem Python no PATH)

```bash
./build-release.sh     # onedir + tarball → releases/ (~480 MB)
./build-appimage.sh    # AppImage    → releases/ (~440 MB)
```

- usar: `./pylibra/pylibra` (tarball) ou o `.AppImage`; `--selftest` verifica tudo
- o bundle traz torch, kokoro, spacy, espeak-ng e os plugins do Qt; a 1ª narração
  ainda baixa o modelo do Hugging Face; MP3 continua pedindo `ffmpeg`
- se a execução direta do AppImage travar (AppImageLauncher/binfmt quebrados),
  use `./run-appimage.sh` — tenta direto e faz fallback para extração em cache

## 🗂️ Estrutura

```
pylibra/
├── main.py              # entrada: CLI + GUI; injeta os motores no sys.path
├── pylibra/             # o app (PyQt6)
│   ├── main_window.py   #   janela principal (abas de sessões)
│   ├── worker.py        #   thread de narração + vozes + saída sem colisão
│   ├── book_worker.py   #   thread de narração de livro (fila de capítulos)
│   ├── epub_panel.py    #   sessão EPUB (leitura + narração + player)
│   └── audio_player.py  #   widget player
├── pyvox/               # motor de narração (repo próprio; venv em pyvox/.venv)
├── pylibre/             # motor EPUB→texto (repo próprio; só stdlib)
├── tests/               # E2E com motor fake (e2e_fake.py, e2e_epub.py)
├── docs/                # arquivos-necessarios.md
├── pylibra.spec, AppRun, build-*.sh, run-appimage.sh, tools/   # builds de release
├── dist/, build/, releases/    # gerados
└── saida/               # áudios gerados
```

Como funciona por dentro: a síntese roda em **thread Qt** consumindo o
generator `pyvox.synthesize_stream`; cada chunk vira um **sinal Qt**
(progresso, sucesso, cancelamento, erro) — a interface nunca trava.

### Testes

```bash
pyvox/.venv/bin/python tests/e2e_fake.py   # narração: sucesso, mp3, cancelamento, falha
pyvox/.venv/bin/python tests/e2e_epub.py   # EPUB: leitura + narração do livro
pyvox/.venv/bin/python main.py --selftest  # motores + libs + UI (também no app congelado)
```
