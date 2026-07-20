@echo off
chcp 65001 >nul
setlocal
set "REPO=%~dp0.."
if exist "%REPO%\.venv\Scripts\python.exe" (
    set "PYTHON=%REPO%\.venv\Scripts\python.exe"
) else (
    set "PYTHON=C:\Users\ricky.sun\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
)
echo [INFO] Probing EastMoney push2his (make sure system proxy is OFF) ...
"%PYTHON%" "%REPO%\scripts\aros_probe_eastmoney.py"
set "RC=%errorlevel%"
if %RC%==0 (
    echo [RESULT] EastMoney OK - you can run aros_backfill.bat safely.
) else (
    echo [RESULT] EastMoney NOT reachable - keep Sina fallback, or check network/proxy.
)
endlocal
pause
exit /b %RC%
