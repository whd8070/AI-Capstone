@echo off
setlocal
set "APP_DIR=%~dp0src\diffusion"
if not exist "%APP_DIR%\setup_windows.ps1" (
  echo [ERROR] Run this launcher from the cloned AI-Capstone repository.
  pause
  exit /b 1
)
pushd "%APP_DIR%"
if errorlevel 1 (
  echo [ERROR] Could not enter the application folder.
  pause
  exit /b 1
)
echo [AI-Capstone] Checking Windows environment...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\setup_windows.ps1"
if errorlevel 1 goto :failed
echo [AI-Capstone] Starting the local web app...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\run_web.ps1"
if errorlevel 1 goto :failed
popd
exit /b 0
:failed
echo.
echo [ERROR] See the message above. No global PowerShell policy was changed.
echo [ERROR] Check README.md and src\diffusion\README_KR_REPORT_WEB.md.
pause
popd
exit /b 1
