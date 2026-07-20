@echo off
chcp 65001 >nul
REM =====================================================================
REM AROS Daily Runner (Phase 4.9 daily closed loop)
REM
REM Usage:
REM   1) Double-click to run manually (bypasses time check);
REM   2) Called by Windows Task Scheduler daily after market close;
REM   3) Called by Startup folder VBS watchdog (has built-in time guard).
REM
REM Time guard: exits silently on weekends or before 18:00.
REM            Pass --force to skip guard when running manually.
REM =====================================================================

setlocal
set "REPO=%~dp0.."
REM Try project .venv first, fall back to managed environment
if exist "%REPO%\.venv\Scripts\python.exe" (
    set "PYTHON=%REPO%\.venv\Scripts\python.exe"
) else (
    set "PYTHON=C:\Users\ricky.sun\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
)

echo [INFO] Using python: %PYTHON%

cd /d "%REPO%"
set "PYTHONPATH=%REPO%\src"
REM Bypass system proxy for EastMoney
set "NO_PROXY=push2.eastmoney.com,push2his.eastmoney.com,quote.eastmoney.com"
set "no_proxy=%NO_PROXY%"

REM ---------- time guard: check unless --force ----------
if not "%~1"=="--force" (
    REM get day of week (1=Mon ... 7=Sun)
    for /f %%d in ('powershell -NoProfile -Command "(Get-Date).DayOfWeek.value__"') do set DOW=%%d
    REM Saturday(6) Sunday(7) -> exit
    if %DOW% gtr 5 (
        exit /b 0
    )
    REM get current hour, exit if before 18:00 (data may not be ready)
    for /f %%h in ('powershell -NoProfile -Command "(Get-Date).Hour"') do set HOUR=%%h
    if %HOUR% lss 18 (
        exit /b 0
    )
)

echo [%date% %time%] AROS daily run starting (universe=all_a)
"%PYTHON%" main.py research alpha run --universe all_a
set "RC=%errorlevel%"
echo [%date% %time%] AROS daily run finished (exit=%RC%)

endlocal
exit /b %RC%
