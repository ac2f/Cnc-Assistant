@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title CNC-Assistant - Kaldir

rem ======================================================================
rem  CNC-Assistant kaldirma. Yonetici yetkisi gerekmez.
rem  Kesim dosyalariniza ve urettiginiz ciktilara DOKUNMAZ.
rem ======================================================================

set "HEDEF=%LOCALAPPDATA%\CncAssistant"
set "BASLAT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "BASLATMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"

echo(
echo ======================================================================
echo   CNC-Assistant kaldiriliyor
echo ======================================================================
echo(

rem YALNIZCA kendi sunucumuzu kapat. Komut satirinda 'cnc_assistant' gecen
rem python surecleri hedeflenir; kullanicinin diger Python programlarina
rem DOKUNULMAZ. (wmic yeni Windows surumlerinde kaldirildigi icin PowerShell.)
echo   [1/3] Calisan sunucu kapatiliyor...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" |" ^
  "Where-Object { $_.CommandLine -like '*cnc_assistant*' } |" ^
  "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo   [2/3] Kisayollar siliniyor...
del /q "%BASLAT%\CNC-Assistant (sunucu).lnk"  >nul 2>&1
del /q "%BASLATMENU%\CNC-Assistant.lnk"       >nul 2>&1
del /q "%USERPROFILE%\Desktop\CNC-Assistant.lnk" >nul 2>&1

echo   [3/3] Program dosyalari...
choice /c EH /n /m "        Kurulu ortam da silinsin mi? [E]vet / [H]ayir: "
if !errorlevel! equ 1 (
    rmdir /s /q "%HEDEF%" >nul 2>&1
    if exist "%HEDEF%" (
        echo        [!] Bazi dosyalar silinemedi ^(kullanimda olabilir^).
        echo            Bilgisayari yeniden baslatip tekrar deneyin.
    ) else (
        echo        Silindi.
    )
) else (
    echo        Birakildi: %HEDEF%
)

echo(
echo ======================================================================
echo   KALDIRILDI. Windows acilisinda artik baslamayacak.
echo ======================================================================
echo(
pause
