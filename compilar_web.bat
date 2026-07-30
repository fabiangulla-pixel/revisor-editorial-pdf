@echo off
cd /d "%~dp0"
echo Limpiando cache...
rmdir /s /q __pycache__ 2>nul
rmdir /s /q build 2>nul
echo Compilando RevisorWebPDF...
REM --clean: sin esto PyInstaller reutiliza analisis viejos y el .exe puede
REM salir con codigo de una version anterior (ya paso en este proyecto).
python -m PyInstaller RevisorWebPDF.spec --clean --noconfirm
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
echo Actualizando el paquete para compartir (exe + perfil de estilo + LEEME)...
REM El .exe busca estilo_gulla.md a su lado cuando la unidad I: no existe
REM (ver motor.ruta_perfil_estilo): por eso viajan juntos.
set COMPARTIR=%USERPROFILE%\Desktop\Compartir - Revisor Web
if exist "%COMPARTIR%" copy /y "dist\RevisorWebPDF.exe" "%COMPARTIR%\RevisorWebPDF.exe"
echo.
echo LISTO. El exe actualizado esta en Mis Apps.
pause
