@echo off
setlocal
cd /d "%~dp0"

rem Review data is isolated from the normal KyungheeAssistant installation.
if defined LOCALAPPDATA (
  set "APPDATA=%LOCALAPPDATA%\KyungheeTimer_AI_Review"
) else (
  set "APPDATA=%TEMP%\KyungheeTimer_AI_Review"
)

where pythonw >nul 2>nul
if errorlevel 1 (
  echo [Seunga AI Review] Python 3.12+ is required.
  echo Run: python -m pip install -r requirements.txt
  pause
  exit /b 1
)

start "" pythonw desktop_ai_review.py
exit /b 0
