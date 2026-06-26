@echo off
cd /d "%~dp0"
echo Limpiando cache...
rmdir /s /q __pycache__ 2>nul
rmdir /s /q build 2>nul
echo Compilando RevisorEditorialPDF...
python -m PyInstaller RevisorEditorialPDF.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR en la compilacion. Revisa el log arriba.
    pause
    exit /b 1
)
echo.
echo Copiando .exe al escritorio...
copy /y "dist\RevisorEditorialPDF.exe" "%USERPROFILE%\Desktop\RevisorEditorialPDF.exe"
echo.
echo LISTO. El exe actualizado esta en el Escritorio.
pause
