"""Instala el hook de pre-commit de git: corre lint + formato + tests antes de
cada commit y lo aborta si algo falla.

Uso:  python scripts/install_hooks.py
"""

import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".git" / "hooks" / "pre-commit"

HOOK_BODY = r"""#!/bin/sh
# Pre-commit de RevisorEditorialPDF: aborta el commit si lint/formato/tests fallan.
# Generado por scripts/install_hooks.py
PY=python

echo "[pre-commit] ruff check..."
"$PY" -m ruff check . || exit 1
echo "[pre-commit] ruff format --check..."
"$PY" -m ruff format --check . || {
    echo "Formato pendiente. Ejecuta: $PY -m ruff format ."; exit 1; }
echo "[pre-commit] pytest..."
"$PY" -m pytest -q || exit 1
echo "[pre-commit] OK"
"""


def main() -> int:
    hooks_dir = HOOK.parent
    if not hooks_dir.exists():
        print(f"[ERROR] No existe {hooks_dir}. Corre 'git init' primero.")
        return 1
    HOOK.write_text(HOOK_BODY, encoding="utf-8", newline="\n")
    HOOK.chmod(HOOK.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"[OK] Hook instalado en {HOOK}")
    print("  Cada 'git commit' correra lint + formato + tests y se abortara si fallan.")
    print("  Para saltarlo puntualmente: git commit --no-verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
