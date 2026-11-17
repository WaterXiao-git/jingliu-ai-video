@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\setup.ps1" %*
if errorlevel 1 (
  echo.
  echo Setup stopped. See the message above.
)
pause
