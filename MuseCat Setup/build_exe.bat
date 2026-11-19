@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0\.."

echo ==================================================
echo   MuseCat Auto Share - Windows .EXE Builder
echo ==================================================

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Please run run.bat once first.
    pause
    exit /b 1
)

echo [1/2] Installing/checking PyInstaller...
".venv\Scripts\python.exe" -m pip install pyinstaller -q
if errorlevel 1 (
    echo [ERROR] Could not install PyInstaller.
    pause
    exit /b 1
)

echo [2/2] Building standalone dist\MuseCatAutoShare.exe ...
".venv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "MuseCatAutoShare" ^
    --icon "assets\musecat_icon.ico" ^
    --add-data "assets\musecat_icon.ico;assets" ^
    --add-data "assets\musecat_icon_1024.png;assets" ^
    --add-data "Kurulum_Rehberi.html;." ^
    --add-data "Setup_Guide_EN.html;." ^
    --collect-all customtkinter ^
    main.py

if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo ==================================================
echo   DONE! Output: dist\MuseCatAutoShare.exe
echo   (Your personal data\ folder is NOT included.)
echo ==================================================
pause
endlocal
