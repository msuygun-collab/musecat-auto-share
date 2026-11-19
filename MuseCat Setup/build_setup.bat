@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0\.."

echo ==================================================
echo   MuseCat Auto Share - Windows Setup Builder
echo ==================================================

if not exist "dist\MuseCatAutoShare.exe" (
    echo [1/2] MuseCatAutoShare.exe bulunamadi, once derleniyor...
    call "MuseCat Setup\build_exe.bat"
    if not exist "dist\MuseCatAutoShare.exe" (
        echo [HATA] dist\MuseCatAutoShare.exe olusturulamadi.
        pause
        exit /b 1
    )
)

set "ISCC="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
    echo [BILGI] Inno Setup 6 kurulu degil. Winget ile kuruluyor...
    winget install --id JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)

if "%ISCC%"=="" (
    echo [HATA] Inno Setup 6 bulunamadi. https://jrsoftware.org/isdl.php adresinden kurabilirsiniz.
    pause
    exit /b 1
)

echo [2/2] MuseCatAutoShare_Setup.exe olusturuluyor...
"%ISCC%" "MuseCat Setup\MuseCatAutoShare_Setup.iss"
if errorlevel 1 (
    echo [HATA] Setup olusturma basarisiz oldu.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo   TAMAM! Setup dosyasi hazir: MuseCat Setup\MuseCatAutoShare_Setup.exe
echo ==================================================
pause
endlocal
