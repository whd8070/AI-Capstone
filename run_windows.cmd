@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%src\diffusion\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] Python environment missing. Run start_windows.cmd for first-time setup.
    pause
    exit /b 1
)
echo [AI-Capstone] Fast restart using existing .venv (no reinstall).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%src\diffusion\run_web.ps1"
if errorlevel 1 (
    echo [ERROR] Web startup failed. Check the message above.
    pause
    exit /b 1
)
exit /b 0
