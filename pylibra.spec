# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller do pylibra (onedir).

Build:
    pyvox/.venv/bin/python -m PyInstaller --noconfirm pylibra.spec

Saída:
    dist/pylibra/pylibra   (executável; pasta contém todas as libs)

Verificação pós-build:
    QT_QPA_PLATFORM=offscreen dist/pylibra/pylibra --selftest
"""
from PyInstaller.utils.hooks import collect_all, copy_metadata

hiddenimports: list[str] = []
binaries: list = []
datas: list = []

# Pacotes com libs nativas ou arquivos de dados — coletar por completo.
# (torch/spacy/phonemizer/misaki/espeakng trazem .so e diretórios de dados
# que a análise estática não pega sozinha.)
for pkg in (
    "torch",
    "kokoro",
    "misaki",
    "espeakng_loader",   # libespeak-ng.so + espeak-ng-data (G2P de pt/es/fr/…)
    "phonemizer",        # phonemizer-fork (G2P en + fallback)
    "segments",          # cadeia do phonemizer (dados JSON)
    "csvw",
    "language_tags",     # dados JSON (índices de subtags)
    "spacy",             # G2P en (misaki.en)
    "en_core_web_sm",    # modelo spacy do G2P en
    "thinc",
    "blis",
    "preshed",
    "cymem",
    "murmurhash",
    "catalogue",
    "spacy_legacy",
    "spacy_loggers",
    "tokenizers",
    "safetensors",
    "soundfile",
    "loguru",
    "pydub",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Metadados (dist-info) para importlib.metadata em runtime (transformers,
# huggingface_hub, spacy etc. consultam versões/metadata em tempo de execução).
for pkg in (
    "transformers",
    "huggingface_hub",
    "tokenizers",
    "torch",
    "kokoro",
    "misaki",
    "spacy",
    "en_core_web_sm",
    "phonemizer-fork",  # nome da distribuição (o módulo é `phonemizer`)
    "safetensors",
):
    try:
        datas += copy_metadata(pkg)
    except Exception as e:  # noqa: BLE001
        print(f"aviso: copy_metadata({pkg}) falhou: {e}")

a = Analysis(
    ["main.py"],
    # pathex: raiz (pacote pylibra) + pasta pyvox (módulo pyvox.py do motor)
    # + pasta pylibre (pacote pylibre/ — EPUB→texto, só stdlib).
    # `import pyvox` resolve para o módulo pyvox/pyvox.py (módulo comum vence
    # o diretório-namespaco homônimo na raiz, semântica PEP 420).
    pathex=[".", "pyvox", "pylibre"],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "pyvox",
        "pylibra",
        "pylibra.worker",
        "pylibra.audio_player",
        "pylibra.main_window",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "gradio",          # app web do pyvox — não faz parte do desktop
        "tkinter",
        "pytest",
        "IPython",
        "torch.testing",
        "torch.utils.benchmark",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pylibra",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="pylibra",
)
