@echo off
chcp 65001 >nul
REM =====================================================================
REM AROS Full A-Share Historical Backfill (run once on first deploy)
REM
REM Pulls daily bars for ~5300 stocks (from 2024-01-01) into local DB.
REM After this, daily runs only do incremental sync -- so run this ONCE.
REM
REM Takes 20-60 min depending on network. Run in foreground to watch.
REM Safe to re-run on failure (idempotent upsert, already-fetched skipped).
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

if not exist "%PYTHON%" (
    echo [ERROR] Python not found: %PYTHON%
    echo         Edit this file and set PYTHON to your interpreter path.
    pause
    exit /b 1
)

cd /d "%REPO%"
set "PYTHONPATH=%REPO%\src"

echo [%date% %time%] Starting full A-share backfill (all_a, from 2024-01-01) ...
"%PYTHON%" scripts/sync_universe.py all_a 2024-01-01
set "RC=%errorlevel%"
echo [%date% %time%] Backfill finished (exit=%RC%)

endlocal
if not %RC%==0 (
    echo.
    echo [NOTE] Backfill may have failed (exit=%RC%). Check errors above.
    echo       Common causes: network blocked, eastmoney rate-limit, missing deps.
    echo       Safe to re-run -- already-fetched data will be skipped.
)
echo.
echo Press any key to close this window...
pause >nul
exit /b %RC%
