@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title CNC-Assistant

rem ======================================================================
rem  Sunucuyu elle baslatir ve tarayiciyi acar.
rem  (Zaten calisiyorsa ikinci kopya ACILMAZ, sadece tarayici acilir.)
rem ======================================================================

set "VENV=%LOCALAPPDATA%\CncAssistant\venv"
set "PORT=8000"

if not exist "%VENV%\Scripts\pythonw.exe" (
    echo(
    echo [!] CNC-Assistant kurulu degil.
    echo     Once bu klasordeki Kur.bat dosyasini calistirin.
    echo(
    pause & exit /b 1
)

start "" "%VENV%\Scripts\pythonw.exe" -m cnc_assistant.cli --web --port %PORT% --tarayici-ac
exit /b 0
