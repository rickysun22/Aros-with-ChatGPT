@echo off
chcp 65001 >nul
setlocal
set "REPO=%~dp0.."
if exist "%REPO%\.venv\Scripts\python.exe" (
    set "PYTHON=%REPO%\.venv\Scripts\python.exe"
) else (
    set "PYTHON=C:\Users\ricky.sun\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
)
echo [INFO] Running network diagnostic ...
"%PYTHON%" "%REPO%\scripts\aros_net_test.py"
endlocal
pause
exit /b 0
