@echo off
setlocal
cd /d "%~dp0"

where pythonw >nul 2>nul
if errorlevel 1 (
  echo [Kyunghee Assistant] pythonw.exe was not found.
  echo Install Python 3.12+ and run: python -m pip install -r requirements.txt
  pause
  exit /b 1
)

start "" pythonw app.py
exit /b 0
