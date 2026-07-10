@echo off
REM Validacion de calidad para RevisorEditorialPDF en Windows.
setlocal
set PY=python

echo === ruff check (lint) ===
%PY% -m ruff check .
if errorlevel 1 goto :fail

echo === ruff format --check (formato) ===
%PY% -m ruff format --check .
if errorlevel 1 goto :fail

echo === pytest ===
%PY% -m pytest -q
if errorlevel 1 goto :fail

echo.
echo OK: lint + formato + tests pasaron.
exit /b 0

:fail
echo.
echo FALLO: corrige lo anterior antes de commitear (o ejecuta: %PY% -m ruff format .).
exit /b 1
