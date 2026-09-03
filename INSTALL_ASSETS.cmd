@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found.
  pause
  exit /b 1
)
python install_asset_pack.py
