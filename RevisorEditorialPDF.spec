# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
# 'costos' = módulo de estimación de costo IA (import diferido dentro de funciones,
# PyInstaller no lo detecta solo → declararlo explícitamente).
# Los SDK de IA (openai, google.generativeai, anthropic) también se importan
# de forma diferida dentro de cada clase de proveedor, así que hay que
# recogerlos explícitamente o el .exe falla al elegir ese proveedor.
hiddenimports = ['tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.scrolledtext', 'fitz', 'dotenv', 'requests', 'costos']
for _pkg in ('fitz', 'openai', 'google.generativeai', 'anthropic'):
    tmp_ret = collect_all(_pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Ver el comentario extenso en RevisorWebPDF.spec: los SDK de IA declaran
# integraciones opcionales que el análisis estático de PyInstaller sigue igual,
# y en este PC eso arrastraba torch/tensorflow/onnxruntime/scipy/pandas al
# ejecutable. Ninguna ruta de código de motor.py los importa.
EXCLUIR_PILA_ML = [
    'torch', 'torchvision', 'torchaudio', 'tensorflow', 'tensorboard',
    'onnxruntime', 'transformers', 'sentence_transformers', 'sklearn',
    'scipy', 'numba', 'llvmlite', 'matplotlib', 'pandas', 'openpyxl',
    'sympy', 'cv2', 'IPython', 'jupyter', 'notebook', 'nbformat', 'pytest',
]


a = Analysis(
    ['corrector_editorial.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUIR_PILA_ML,
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
    name='RevisorEditorialPDF',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
