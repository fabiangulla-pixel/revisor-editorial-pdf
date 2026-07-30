# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [("web", "web")]
binaries = []
# 'costos' = módulo de estimación de costo IA (import diferido dentro de funciones,
# PyInstaller no lo detecta solo → declararlo explícitamente).
# Los SDK de IA (openai, google.generativeai, anthropic) también se importan
# de forma diferida dentro de cada clase de proveedor en motor.py, así que hay
# que recogerlos explícitamente o el .exe falla al elegir ese proveedor.
# Sin tkinter: servidor_web.py solo depende de motor.py, que no lo importa.
hiddenimports = ["fitz", "dotenv", "requests", "costos"]
for _pkg in ("fitz", "openai", "google.generativeai", "anthropic"):
    tmp_ret = collect_all(_pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

# Los SDK de IA declaran integraciones OPCIONALES (numpy/pandas para
# embeddings, backends de ML) que PyInstaller sigue igual porque el análisis es
# estático: no distingue una rama perezosa de una que se usa. Como este PC
# tiene instalada toda la pila científica, el .exe acababa arrastrando torch,
# tensorflow, onnxruntime, scipy, pandas y numba — 647 MB para una app que solo
# manda texto por HTTP y escribe PDF. Nada de esto se importa en ninguna ruta
# de código de motor.py; excluirlo es lo que hace que el ejecutable se pueda
# compartir por correo o Drive sin sufrir.
EXCLUIR_PILA_ML = [
    "torch",
    "torchvision",
    "torchaudio",
    "tensorflow",
    "tensorboard",
    "onnxruntime",
    "transformers",
    "sentence_transformers",
    "sklearn",
    "scipy",
    "numba",
    "llvmlite",
    "matplotlib",
    "pandas",
    "openpyxl",
    "sympy",
    "cv2",
    "IPython",
    "jupyter",
    "notebook",
    "nbformat",
    "pytest",
]


a = Analysis(
    ["servidor_web.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUIR_PILA_ML + ["tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="RevisorWebPDF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
