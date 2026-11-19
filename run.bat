@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

cd /d "%~dp0"

echo ==================================================
echo   MuseCat Auto Share - Yayinci Klip Otomasyonu
echo ==================================================

where python >nul 2>nul
if errorlevel 1 (
    echo [HATA] Python bulunamadi! Lutfen Python 3.10+ kurun ve PATH'e ekleyin.
    echo Indirme adresi: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Sanal ortam ^(.venv^) olusturuluyor...
    python -m venv .venv
    if errorlevel 1 (
        echo [HATA] Sanal ortam olusturulamadi.
        pause
        exit /b 1
    )
)

echo [2/3] Gerekli paketler kontrol ediliyor...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo [HATA] Paket kurulumu sirasinda hata olustu.
    pause
    exit /b 1
)

echo [3/3] MuseCat Auto Share baslatiliyor...
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 (
    echo.
    echo [UYARI] Uygulama hata kodu ile kapandi ^(%errorlevel%^).
    pause
)

endlocal
