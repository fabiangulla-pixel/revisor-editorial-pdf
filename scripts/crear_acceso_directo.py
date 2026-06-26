#!/usr/bin/env python3
"""Crea el acceso directo en el Escritorio con ícono personalizado."""

import os
import sys
from pathlib import Path


def crear_acceso_directo():
    # Rutas
    script_dir = Path(__file__).parent
    programa = script_dir / "corrector_editorial.py"
    icono = script_dir / "corrector_editorial.ico"
    python_exe = sys.executable

    # Escritorio del usuario actual
    escritorio = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
    if not escritorio.exists():
        # Fallback para OneDrive Desktop
        escritorio = Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "Escritorio"
    if not escritorio.exists():
        escritorio = Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "Desktop"
    if not escritorio.exists():
        print(f"No se encontró el Escritorio en {escritorio}")
        return

    acceso = escritorio / "Corrector Editorial PDF.lnk"

    # Crear .lnk con win32com
    try:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(acceso))
        shortcut.TargetPath = str(python_exe)
        shortcut.Arguments = f'"{programa}"'
        shortcut.WorkingDirectory = str(script_dir)
        shortcut.IconLocation = str(icono)
        shortcut.Description = "Corrector Editorial PDF — Gulla Editorial Tools"
        shortcut.WindowStyle = 1  # Normal window
        shortcut.Save()
        print(f"Acceso directo creado: {acceso}")
        return
    except ImportError:
        pass

    # Fallback: crear con PowerShell si win32com no está disponible
    ps_script = f"""
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{acceso}")
$Shortcut.TargetPath = "{python_exe}"
$Shortcut.Arguments = '"{programa}"'
$Shortcut.WorkingDirectory = "{script_dir}"
$Shortcut.IconLocation = "{icono}"
$Shortcut.Description = "Corrector Editorial PDF — Gulla Editorial Tools"
$Shortcut.WindowStyle = 1
$Shortcut.Save()
Write-Host "Acceso directo creado: {acceso}"
"""
    import subprocess

    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"Acceso directo creado: {acceso}")
        print(result.stdout)
    else:
        print(f"Error PowerShell: {result.stderr}")


if __name__ == "__main__":
    crear_acceso_directo()
