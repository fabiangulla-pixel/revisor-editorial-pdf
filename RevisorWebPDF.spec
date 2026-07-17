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


a = Analysis(
    ["servidor_web.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
