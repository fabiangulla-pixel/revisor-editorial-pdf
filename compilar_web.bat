@echo off
cd /d "%~dp0"
echo Limpiando cache...
rmdir /s /q __pycache__ 2>nul
rmdir /s /q build 2>nul
echo Compilando RevisorWebPDF...
python -m PyInstaller RevisorWebPDF.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR en la compilacion. Revisa el log arriba.
    pause
    exit /b 1
)
echo.
echo Copiando .exe a Desktop\Mis Apps...
if not exist "%USERPROFILE%\Desktop\Mis Apps" mkdir "%USERPROFILE%\Desktop\Mis Apps"
copy /y "dist\RevisorWebPDF.exe" "%USERPROFILE%\Desktop\Mis Apps\RevisorWebPDF.exe"
echo.
echo LISTO. El exe actualizado esta en Desktop\Mis Apps.
pause
