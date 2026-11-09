@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [Seunga Timer] python.exe was not found.
  pause
  exit /b 1
)

python desktop_gallery_final.py
pause
