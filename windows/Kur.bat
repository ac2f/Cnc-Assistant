@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title CNC-Assistant - Kurulum

rem ======================================================================
rem  CNC-Assistant - Windows tek tik kurulum
rem
rem  Yaptiklari:
rem    1. Python'u bulur (yoksa nasil kurulacagini soyler)
rem    2. %LOCALAPPDATA%\CncAssistant altina ozel bir ortam (venv) kurar
rem    3. Programi ve bagimliliklarini oraya yukler
rem    4. Windows ACILISINA ekler (arka planda, pencere acmadan)
rem    5. Masaustune ve Baslat menusune kisayol koyar
rem    6. Simdi baslatip tarayiciyi acar
rem
rem  YONETICI YETKISI GEREKMEZ. Her sey kullanici klasorune kurulur.
rem  Kaldirmak icin: Kaldir.bat
rem ======================================================================

set "KAYNAK=%~dp0.."
set "HEDEF=%LOCALAPPDATA%\CncAssistant"
set "VENV=%HEDEF%\venv"
set "PORT=8000"
set "URL=http://127.0.0.1:%PORT%"

echo(
echo ======================================================================
echo   CNC-Assistant kurulumu
echo ======================================================================
echo(

rem --- 1) Python bul --------------------------------------------------
set "PY="
for %%C in ("py -3" "python" "python3") do (
    if not defined PY (
        %%~C -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
        if !errorlevel! equ 0 set "PY=%%~C"
    )
)

if not defined PY (
    echo [!] Python 3.8 veya ustu bulunamadi.
    echo(
    echo     Otomatik kurmayi deneyeyim mi? ^(internet gerekir^)
    choice /c EH /n /m "     [E]vet / [H]ayir: "
    if !errorlevel! equ 1 (
        echo     Python indiriliyor...
        winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
        if !errorlevel! neq 0 (
            echo(
            echo [!] Otomatik kurulum basarisiz.
            goto :PYTHON_YOK
        )
        echo     Python kuruldu. Bu pencereyi KAPATIP Kur.bat'i tekrar calistirin.
        echo     ^(Yeni kurulan Python'un goruunmesi icin gerekli^)
        pause
        exit /b 0
    )
    goto :PYTHON_YOK
)

for /f "delims=" %%V in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set "SURUM=%%V"
echo   [1/6] Python bulundu: %SURUM%

rem --- 2) Ortam (venv) -------------------------------------------------
if not exist "%HEDEF%" mkdir "%HEDEF%" >nul 2>&1
if exist "%VENV%\Scripts\python.exe" (
    echo   [2/6] Mevcut ortam kullanilacak
) else (
    echo   [2/6] Ozel ortam olusturuluyor...
    %PY% -m venv "%VENV%"
    if !errorlevel! neq 0 (
        echo(
        echo [!] Ortam olusturulamadi. Python kurulumunuz eksik olabilir.
        pause & exit /b 1
    )
)

rem --- 3) Program + bagimliliklar --------------------------------------
echo   [3/6] Program ve bagimliliklar yukleniyor ^(biraz surebilir^)...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VENV%\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check "%KAYNAK%" matplotlib
if !errorlevel! neq 0 (
    echo(
    echo [!] Yukleme basarisiz. Internet baglantinizi kontrol edin.
    pause & exit /b 1
)

rem --- 4) Kisayollar + otomatik baslatma -------------------------------
echo   [4/6] Kisayollar olusturuluyor...
set "PYW=%VENV%\Scripts\pythonw.exe"
set "BASLAT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "BASLATMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"

rem Sunucuyu pencere acmadan baslatan kisayol (acilista calisir)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w=New-Object -ComObject WScript.Shell;" ^
  "$s=$w.CreateShortcut('%BASLAT%\CNC-Assistant (sunucu).lnk');" ^
  "$s.TargetPath='%PYW%';" ^
  "$s.Arguments='-m cnc_assistant.cli --web --port %PORT%';" ^
  "$s.WorkingDirectory='%HEDEF%';" ^
  "$s.Description='CNC-Assistant web sunucusu (arka planda)';" ^
  "$s.WindowStyle=7; $s.Save()" >nul 2>&1

rem Masaustu + Baslat menusu: sunucu kapaliysa baslatir, sonra tarayiciyi acar
for %%T in ("%USERPROFILE%\Desktop\CNC-Assistant.lnk" "%BASLATMENU%\CNC-Assistant.lnk") do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$w=New-Object -ComObject WScript.Shell;" ^
    "$s=$w.CreateShortcut('%%~T');" ^
    "$s.TargetPath='%PYW%';" ^
    "$s.Arguments='-m cnc_assistant.cli --web --port %PORT% --tarayici-ac';" ^
    "$s.WorkingDirectory='%HEDEF%';" ^
    "$s.Description='CNC-Assistant web arayuzunu ac';" ^
    "$s.WindowStyle=7; $s.Save()" >nul 2>&1
)

rem --- 5) Simdi baslat -------------------------------------------------
echo   [5/6] Sunucu baslatiliyor...
start "" "%PYW%" -m cnc_assistant.cli --web --port %PORT%

rem Hazir olmasini bekle (en fazla ~10 sn)
set "HAZIR="
for /l %%i in (1,1,20) do (
    if not defined HAZIR (
        "%VENV%\Scripts\python.exe" -c "import urllib.request,sys;urllib.request.urlopen('%URL%/surum',timeout=1)" >nul 2>&1
        if !errorlevel! equ 0 set "HAZIR=1"
        if not defined HAZIR ping -n 2 127.0.0.1 >nul
    )
)

echo   [6/6] Tarayici aciliyor...
start "" "%URL%"

echo(
echo ======================================================================
if defined HAZIR (
  echo   KURULUM TAMAM
) else (
  echo   KURULUM TAMAM ^(sunucu biraz gec acilabilir^)
)
echo(
echo   Adres          : %URL%
echo   Acilista       : Windows ile birlikte otomatik baslar
echo   Kisayol        : Masaustunde "CNC-Assistant"
echo   Kaldirmak icin : windows\Kaldir.bat
echo ======================================================================
echo(
pause
exit /b 0

:PYTHON_YOK
echo(
echo   Lutfen Python 3.8+ kurun, sonra Kur.bat'i tekrar calistirin:
echo     https://www.python.org/downloads/
echo(
echo   ONEMLI: Kurulum ekraninda "Add Python to PATH" kutusunu ISARETLEYIN.
echo(
pause
exit /b 1
