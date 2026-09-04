@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: IMPORT_ASSET_SHEET.cmd ^<sheet.png^> [options]
  echo First run creates a preview/contact sheet. After review, rerun with --install --approved.
  exit /b 2
)
python tools\import_asset_sheet.py %*
