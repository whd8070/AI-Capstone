@echo off
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%bootstrap_windows.ps1" (
  echo [ERROR] bootstrap_windows.ps1 is missing. Download the latest repository files.
  pause
  exit /b 1
)
echo [AI-Capstone] Checking Git, Python 3.11 and user PATH...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%bootstrap_windows.ps1"
if errorlevel 1 goto :failed
exit /b 0
:failed
echo.
echo [ERROR] Setup or web startup failed. Please check the message above.
echo [ERROR] Existing project files were not intentionally deleted.
pause
exit /b 1
