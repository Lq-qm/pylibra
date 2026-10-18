# pylibra 🎙️

**O pylibra é uma aplicação desktop de texto e voz**, organizada em **sessões** (abas), cada uma expondo um motor Python do projeto como ferramenta gráfica:

| Sessão | Motor | O que faz |
|---|---|---|
| 🎙️ **Narração** | [pyvox](pyvox/) | texto entra, voz sai — narração de textos com **Kokoro-82M** (TTS open-source, **100% CPU**) |
| 📚 **EPUB** | [pylibre](pylibre/) | lê um livro `.epub` e lista os capítulos (título, autores, contagem de palavras, prévia do texto) |

A sessão de narração é a interface gráfica do **pyvox** — um motor de narração que já vem com linha de comando e web (Gradio); o pylibra leva o mesmo motor para o desktop, com a experiência de um aplicativo:

- **progresso em tempo real** (chunk a chunk, no log da janela) enquanto a CPU sintetiza;
- **cancelamento a qualquer momento** — a síntese para no próximo chunk e o áudio parcial é mantido, já tocável;
- **player embutido** (play/pause, seek, volume) — não precisa de player externo;
- tudo em uma única janela, sem navegador nem terminal.

Em resumo: o pylibra é o **modo desktop dos motores** do projeto — hoje pyvox (narração) e pylibre (EPUB→texto); novas ferramentas entram como novas sessões.

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

**Sessão 🎙️ Narração (pyvox)**

- 📝 Colar texto no editor ou abrir `.txt`/`.md` (o nome do arquivo vira o nome da saída)
- 🌍 Narrar em 9 idiomas (pt-br, en-us, en-gb, es, fr-fr, hi, it, ja, zh)
- 🎤 Escolher **narrador automático / masculino / feminino** ou uma **voz exata**
  (`pf_dora`, `pm_alex`, …) — a lista é atualizada online (Hugging Face, em background,
  com fallback offline)
- 🎚️ Ajustar a velocidade da fala (0.5×–2.0×) e os núcleos de CPU usados
- 📦 Exportar em **WAV** ou **MP3** — os arquivos ficam em `saida/`, sem sobrescrever
- ⏹ Cancelar no meio (o áudio parcial continua tocável)
- ⌨️ `Ctrl+Enter` gera a narração; botão **📂** abre a pasta de saída

**Sessão 📚 EPUB (pylibre)**

- 📚 Escolher um arquivo `.epub` e ver **título + autores** (metadados do livro)
- 📑 **Lista de capítulos** na ordem de leitura (spine), com contagem de palavras
- 👀 **Prévia do texto** do capítulo selecionado
- ⚙️ Leitura em background (livros grandes não travam a interface)
- (por enquanto só leitura/listagem — a conversão em texto/áudio do livro vem a seguir)

## 📋 Requisitos

| Item | Obs. |
|---|---|
| Python 3.10+ | testado com 3.14 |
| `pyvox/` | motor de narração (repositório próprio, já na pasta) — sessão 🎙️ |
| `pyvox/.venv` | torch CPU + kokoro (veja `pyvox/README.md`) — só para a sessão de narração |
| `pylibre/` | motor EPUB→texto (repositório próprio, **clonar na pasta do projeto**) — sessão 📚 |
| PyQt6 | instalado no venv do pyvox (veja abaixo) |
| `en_core_web_sm` | modelo spacy do G2P em inglês (já instalado no venv) |
| pylibre | **zero dependências** — só biblioteca padrão do Python |
| opcional (para gerar MP3) | `ffmpeg` no sistema |

## 🚀 Como rodar

```bash
# 1) clonar o motor pylibre na pasta do projeto (uma vez só — repositório independente)
git clone <url-do-pylibre> pylibre

# 2) instalar o PyQt6 no venv do pyvox (uma vez só)
uv pip install --python pyvox/.venv/bin/python PyQt6

# 3) abrir a aplicação
./run.sh
# ou:
pyvox/.venv/bin/python main.py
```

> O **pylibre** é um repositório próprio (tem `.git`, `pyproject.toml` e README
> próprios) que vive dentro da pasta do projeto — por isso ele não aparece no
> git do pylibra. Sem ele, a sessão 📚 EPUB não funciona (o app abre, mas a
> aba EPUB falha ao importar o motor).

### Linha de comando (sem abrir a janela)

```bash
pyvox/.venv/bin/python main.py --speak "Olá, mundo!" \
    -l pt-br -g f -o olá.mp3     # → saida/olá.mp3 (voz pf_dora)
```

Mesmo motor e mesmas regras da UI (narrador/voz, colisão de saída, MP3 via
ffmpeg); o progresso aparece no terminal.

> A **1ª narração** baixa o modelo Kokoro-82M (~330 MB) e a voz escolhida do
> Hugging Face (cache em `~/.cache/huggingface`); nas seguintes o modelo fica
> em cache na memória do processo. Em rede lenta o download pode demorar —
> o progresso aparece no log e dá para cancelar.

## 📦 Release (PyInstaller)

O app pode ser empacotado como **executável standalone** (onedir) — sem venv,
sem `python` no PATH. O bundle já traz torch CPU, kokoro, misaki, spacy,
espeak-ng, os dados de G2P e os plugins do Qt (incluindo o player de áudio):

```bash
# build + selftest automático + tarball
./build-release.sh

# saídas:
#   dist/pylibra/                                  pasta executável
#   releases/pylibra-0.1.0-linux-x86_64.tar.gz     release (~480 MB)
```

Usar a release:

```bash
tar -xzf pylibra-0.1.0-linux-x86_64.tar.gz
./pylibra/pylibra          # abre a janela do app
```

Verificar a instalação (motor, libs nativas, dados do espeak, UI):

```bash
pylibra/pylibra --selftest
```

Observações da release:
- a **1ª narração** baixa o Kokoro-82M (~330 MB) do Hugging Face, como no modo venv;
- gerar **MP3** continua exigindo `ffmpeg` no sistema (o player de áudio, não);
- o PyInstaller usa `pylibra.spec` (coleta explícita de `torch`, `misaki`,
  `espeakng_loader`, `phonemizer`, `spacy` + `en_core_web_sm` e afins);
- o motor é embutido como o módulo `pyvox/pyvox.py` (não o diretório `pyvox/`).

### AppImage

Também há uma release **AppImage** (padrão de distribuição Linux, com ícone,
`.desktop` e `AppRun` integrados):

```bash
./build-appimage.sh
# → releases/pylibra-0.1.0-linux-x86_64.AppImage (~440 MB)
```

Usar:

```bash
./pylibra-0.1.0-linux-x86_64.AppImage            # desktop (duplo clique ou terminal)
./pylibra-0.1.0-linux-x86_64.AppImage --selftest # verificar a instalação
```

- requer **FUSE** no sistema (presente em praticamente todos os desktops);
  em sistemas sem FUSE o runtime extrai sozinho — ou extraia à mão:
  `./pylibra-…AppImage --appimage-extract && ./squashfs-root/AppRun`;
- o `build-appimage.sh` valida a release por extração + `AppRun --selftest`
  (funciona mesmo sem FUSE); as ferramentas (`linuxdeploy` + plugin) ficam em
  `tools/` e são baixadas automaticamente na 1ª vez;
- **detalhe importante**: o AppImage precisa de um `AppRun` na raiz do payload
  (o runtime faz `execv(AppRun)`; sem ele: `execv error: No such file or
  directory`, exit 127). O build usa `linuxdeploy --custom-apprun AppRun`
  (arquivo `AppRun` na raiz do repo) — o linuxdeploy 1-alpha só gera o AppRun
  sozinho quando o executável é um *arquivo real* em `usr/bin/`, o que o
  layout onedir do PyInstaller não atende.

#### Se a execução direta travar (AppImageLauncher quebrado)

Sistemas com **AppImageLauncher** (ex.: esta máquina) interceptam toda
execução de `.AppImage` via binfmt. Se o launcher/GUI estiver mal instalado
(daemon `appimagelauncherd` sem sessão funcional), a execução **trava** ou
falha — e os avisos `QFont::fromString` no terminal vêm do Qt do launcher,
não do pylibra. Soluções, da mais simples:

```bash
# 1) use o helper — tenta direto e, se travar, extrai (em cache) e executa:
./run-appimage.sh            # abre a UI
./run-appimage.sh --speak "Olá!" -o teste.mp3

# 2) ou extraia manualmente:
./pylibra-…AppImage --appimage-extract && ./squashfs-root/AppRun

# 3) ou use a release onedir (tarball), que roda direto em qualquer lugar
```

Para consertar o próprio sistema (requer root/permissões do usuário):
desregistrar os handlers binfmt
(`echo -1 | sudo tee /proc/sys/fs/binfmt_misc/appimage-type1 /proc/sys/fs/binfmt_misc/appimage-type2`)
ou deixar o AppImageLauncher funcional (`systemctl --user status appimagelauncherd`).

## 🗂️ Estrutura do projeto

```
pylibra/
├── main.py              # entrada: injeta os motores (pyvox, pylibre) no sys.path e sobe o Qt
├── pylibra/
│   ├── worker.py        # SynthWorker (QThread) + resolução de voz + saída sem colisão
│   ├── audio_player.py  # widget player (QMediaPlayer/QAudioOutput)
│   ├── epub_panel.py    # sessão EPUB: EpubWorker (QThread) + painel de capítulos (pylibre)
│   └── main_window.py   # UI principal — QTabWidget com as sessões (Narração, EPUB)
├── pylibre/             # motor EPUB→texto (REPO INDEPENDENTE, clonado aqui; só stdlib)
├── pyvox/               # motor de narração (Kokoro-82M; CLI + web Gradio)
├── tests/
│   ├── e2e_fake.py      # E2E da narração com motor fake (sem baixar modelo)
│   └── e2e_epub.py      # E2E da sessão EPUB (abrir livro → capítulos → prévia → falha)
├── pylibra.spec         # spec do PyInstaller (coleta de libs nativas/dados)
├── AppRun               # entrypoint do AppImage (copiado p/ o payload via --custom-apprun)
├── build-release.sh     # build + selftest + tarball da release
├── build-appimage.sh    # build + selftest + AppImage da release
├── run-appimage.sh      # roda o AppImage com fallback (extração em cache) se o launcher travar
├── tools/               # linuxdeploy + plugin appimage (binários, baixados)
├── dist/                # build onedir (gerado)
├── releases/            # tarballs/AppImages de release (gerados)
└── saida/               # arquivos gerados
```

Como funciona por dentro, em uma frase: a síntese roda em uma **thread Qt**
consumindo o generator `pyvox.synthesize_stream`, e cada chunk yieldado vira um
**sinal Qt** (progresso, sucesso, cancelamento, erro) — a interface nunca trava,
nem durante o carregamento do modelo.

### Testes

```bash
pyvox/.venv/bin/python tests/e2e_fake.py   # narração: sucesso, mp3, cancelamento, falha (motor fake)
pyvox/.venv/bin/python tests/e2e_epub.py   # EPUB: abrir livro → capítulos → prévia → falha
pyvox/.venv/bin/python main.py --selftest # motores (pyvox + pylibre) + libs nativas + UI (também no app congelado)
```
