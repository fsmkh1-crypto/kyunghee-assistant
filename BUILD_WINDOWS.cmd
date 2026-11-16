@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Windows Python 3.12 or newer was not found.
  echo Install 64-bit Python with Tcl/Tk and pip, then run this file again.
  exit /b 2
)
python "%~dp0tools\build_windows.py" %*
exit /b %errorlevel%
