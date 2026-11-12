@echo off
setlocal
if not exist "%~dp0SeungaTimer.exe" (
  echo Run this check from the extracted Windows package beside SeungaTimer.exe.
  pause
  exit /b 2
)
echo Seunga Timer 2.1.5 - offline Korean IME input check
echo Close the older timer first. No API key, history or network request is used.
echo The test opens a separate temporary chat and types fixed test characters.
echo Select Korean IME and Hangul mode during the preparation countdown.
echo After the countdown, leave the keyboard and mouse alone until it finishes.
pause
set "SEUNGA_IME_REPORT=%TEMP%\SeungaTimer-2.1.5-ime-%RANDOM%-%RANDOM%.json"
start "" /wait "%~dp0SeungaTimer.exe" --ime-self-test "%SEUNGA_IME_REPORT%"
set "SEUNGA_IME_EXIT=%ERRORLEVEL%"
echo.
echo Exit code: %SEUNGA_IME_EXIT% (0=passed, 1=failed, 3=IME unavailable)
if exist "%SEUNGA_IME_REPORT%" (
  echo Local report: "%SEUNGA_IME_REPORT%"
) else (
  echo The report was not written. The input check is not verified.
)
pause
exit /b %SEUNGA_IME_EXIT%
