@echo off
cd /d "%~dp0"
echo Limpiando cache...
rmdir /s /q __pycache__ 2>nul
rmdir /s /q build 2>nul
echo Compilando RevisorEditorialPDF...
REM --clean: sin esto PyInstaller reutiliza analisis viejos y el .exe puede
REM salir con codigo de una version anterior (ya paso en este proyecto).
python -m PyInstaller RevisorEditorialPDF.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR en la compilacion. Revisa el log arriba.
    pause
    exit /b 1
)
echo.
echo Copiando .exe a los DOS destinos (Escritorio y Mis Apps)...
REM Se copia a los dos a proposito: cuando solo se actualizaba uno, la otra
REM copia quedaba semanas atrasada y era imposible saber cual se estaba usando.
copy /y "dist\RevisorEditorialPDF.exe" "%USERPROFILE%\Desktop\RevisorEditorialPDF.exe"
if not exist "%USERPROFILE%\Desktop\Mis Apps" mkdir "%USERPROFILE%\Desktop\Mis Apps"
copy /y "dist\RevisorEditorialPDF.exe" "%USERPROFILE%\Desktop\Mis Apps\RevisorEditorialPDF.exe"
echo.
echo LISTO. El exe actualizado esta en el Escritorio y en Mis Apps.
pause
