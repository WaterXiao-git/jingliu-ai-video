@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" if exist "%~dp0.runtime\runtime.json" (
  start "" powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0deploy\launch.ps1"
  exit /b 0
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\setup.ps1" %*
if errorlevel 1 (
  echo.
  echo Setup stopped. See the message above.
)
pause
