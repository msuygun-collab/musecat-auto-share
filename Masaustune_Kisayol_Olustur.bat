@echo off
chcp 65001 >nul
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$desktop = [Environment]::GetFolderPath('Desktop'); " ^
  "$sc = $ws.CreateShortcut((Join-Path $desktop 'MuseCat Auto Share.lnk')); " ^
  "$sc.TargetPath = 'wscript.exe'; " ^
  "$sc.Arguments = '\"' + (Join-Path '%~dp0' 'MuseCat Auto Share.vbs') + '\"'; " ^
  "$sc.WorkingDirectory = '%~dp0'; " ^
  "$sc.IconLocation = (Join-Path '%~dp0' 'assets\musecat_icon.ico'); " ^
  "$sc.Description = 'MuseCat Auto Share - Yayinci Klip Otomasyonu'; " ^
  "$sc.Save();"

echo.
echo [TAMAM] Masaustune MuseCat logolu kisayol olusturuldu!
echo Artik CMD penceresi acilmadan tek tikla baslatabilirsiniz.
pause
