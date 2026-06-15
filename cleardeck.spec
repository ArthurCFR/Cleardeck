# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Cleardeck (Windows).

Build with:
    pyinstaller cleardeck.spec --noconfirm --clean

Outputs:
    dist/Cleardeck/Cleardeck.exe   (windowless launcher)
    dist/Cleardeck/_internal/...   (Python runtime + bundled deps)

Notes:
    - `--onedir` mode (much faster startup than --onefile).
    - The CamemBERT-NER model is NOT bundled; it is downloaded at first run
      into %LOCALAPPDATA%\\Cleardeck\\models\\ by the launcher.
    - Frontend assets are copied next to the exe so backend/main.py can find
      them via Path(__file__).parent.parent / "frontend".
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# Heavy ML packages need full collection (data + hidden imports + binaries).
transformers_datas, transformers_binaries, transformers_hidden = collect_all("transformers")
tokenizers_datas, tokenizers_binaries, tokenizers_hidden = collect_all("tokenizers")
torch_datas, torch_binaries, torch_hidden = collect_all("torch")
huggingface_hub_datas, huggingface_hub_binaries, huggingface_hub_hidden = collect_all("huggingface_hub")

# NumPy / PIL need to be collected explicitly — PyInstaller's built-in hook
# is unreliable on Windows with NumPy 2.x (C-extensions fail to import at
# runtime if their compiled .pyd files aren't bundled alongside).
numpy_datas, numpy_binaries, numpy_hidden = collect_all("numpy")
pil_datas, pil_binaries, pil_hidden = collect_all("PIL")

# sentencepiece: the actual tokenizer used by CamemBERT-NER. transformers
# tries to read the sentencepiece.bpe.model file via this lib and falls
# back to tiktoken if it's missing — but the tiktoken fallback also fails
# because its plugin module tiktoken_ext isn't auto-discovered by
# PyInstaller. Both libs need to be bundled explicitly.
sentencepiece_datas, sentencepiece_binaries, sentencepiece_hidden = collect_all("sentencepiece")
tiktoken_datas, tiktoken_binaries, tiktoken_hidden = collect_all("tiktoken")
# tiktoken_ext is a namespace package that ships the encoding plugins
# (cl100k_base, etc.). It's not picked up by collect_all('tiktoken') and
# needs explicit submodule discovery.
tiktoken_ext_hidden = collect_submodules("tiktoken_ext")

# python-docx and python-pptx ship XML templates as package data.
docx_datas = collect_data_files("docx")
pptx_datas = collect_data_files("pptx")

datas = (
    transformers_datas
    + tokenizers_datas
    + torch_datas
    + huggingface_hub_datas
    + numpy_datas
    + pil_datas
    + sentencepiece_datas
    + tiktoken_datas
    + docx_datas
    + pptx_datas
    + [
        ("frontend", "frontend"),
        ("backend", "backend"),
    ]
)

binaries = (
    transformers_binaries
    + tokenizers_binaries
    + torch_binaries
    + huggingface_hub_binaries
    + numpy_binaries
    + pil_binaries
    + sentencepiece_binaries
    + tiktoken_binaries
)

hiddenimports = (
    transformers_hidden
    + tokenizers_hidden
    + torch_hidden
    + huggingface_hub_hidden
    + numpy_hidden
    + pil_hidden
    + sentencepiece_hidden
    + tiktoken_hidden
    + tiktoken_ext_hidden
    + [
        "backend.main",
        "backend.config",
        "backend.routers.projects",
        "backend.routers.anonymize",
        "backend.routers.deanonymize",
        "backend.engine.ai_detector",
        "backend.engine.anonymizer",
        "backend.engine.deanonymizer",
        "backend.engine.docx_handler",
        "backend.engine.pptx_handler",
        "backend.engine.image_handler",
        "backend.engine.entity_merger",
        "backend.engine.cross_run",
        "backend.services.project_setup",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
    ]
)

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Cut down on bundle size: drop optional / unused dev tooling.
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    # transformers (and other lazy-loading packages) walk the filesystem at
    # import time via os.scandir(). With the default PYZ archive,
    # __init__.pyc files are NOT physically on disk and the scan fails with
    # FileNotFoundError. noarchive=True forces every .pyc to live on disk
    # in its proper package hierarchy, which matches what __file__ resolves
    # to and lets the scan succeed.
    noarchive=True,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Cleardeck",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,             # windowless — logs go to %LOCALAPPDATA%\Cleardeck\logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                 # add a .ico path here if/when we have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Cleardeck",
)
