@echo off
REM =====================================================================
REM Register AROS as a Windows scheduled task
REM
REM Result: auto-runs aros_daily.bat every weekday at 18:30
REM   for full A-share daily screening.
REM 18:30 is safe after A-share market close (15:00) data ready.
REM =====================================================================

setlocal
set "BAT=%~dp0aros_daily.bat"
set "VBS=%~dp0_aros_launcher.vbs"

echo.
echo ====== AROS Task Scheduler Setup ======
echo.

REM ---------- Method 1: try schtasks (needs admin) ----------
echo [Step 1/2] Trying schtasks ...
schtasks /create /tn "AROS Daily Alpha" /tr "\"%BAT%\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 18:30 /f >nul 2>&1
if %errorlevel%==0 (
    echo.
    echo   [OK] Scheduled task created!
    echo       Name : AROS Daily Alpha
    echo       Time : Mon-Fri 18:30
    echo       Cmd  : "%BAT%"
    echo.
    echo   Manage with:
    echo     schtasks /query /tn "AROS Daily Alpha"
    echo     schtasks /delete /tn "AROS Daily Alpha" /f
    goto :done
)

echo.
echo   [SKIP] schtasks needs admin. Falling back to Method 2 (no admin) ...

REM ---------- Method 2: VBS silent launcher + Startup folder ----------
echo.
echo [Step 2/2] Creating VBS silent launcher ...

REM Generate VBS launcher (runs bat hidden)
(
echo Set WshShell = CreateObject("WScript.Shell"^)
echo WshShell.Run """" & Replace(WScript.ScriptFullName, "_aros_launcher.vbs", "aros_daily.bat") & """", 0, False
) > "%VBS%"

if not exist "%VBS%" (
    echo   [FAIL] Cannot write VBS file. Check directory permissions.
    goto :fail
)

REM Place in user Startup folder (auto-start on login + internal time guard)
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
copy /y "%VBS%" "%STARTUP%\_aros_daily.vbs" >nul 2>&1
if %errorlevel%==0 (
    echo.
    echo   [OK] Deployed via Startup folder!
    echo       Launcher : %STARTUP%\_aros_daily.vbs
    echo       Script   : "%BAT%"
    echo.
    echo   Note: This runs a background watchdog on every login,
    echo         which waits until weekday 18:30 to execute screening.
    echo         To remove, delete this file:
    echo           del "%STARTUP%\_aros_daily.vbs"
) else (
    echo.
    echo   [WARN] Cannot write to Startup folder. Manual steps:
    echo.
    echo   Method A - Task Scheduler GUI:
    echo     1. Win+R -> type taskschd.msc -> Enter
    echo     2. Right side "Create Basic Task" -> name: AROS Daily Alpha
    echo     3. Trigger: Daily, time 18:30
    echo     4. Action: Start program, path: "%BAT%"
    echo     5. Check "Run only when user is logged on" -> Finish
    echo.
    echo   Method B - Manual copy:
    echo     Copy "%VBS%"
    echo     To   C:\Users\<YOUR_USER>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\
    echo     Rename to _aros_daily.vbs
    goto :fail
)

goto :done

:fail
echo.
echo   Deployment incomplete. Please use manual steps above.

:done
echo.
pause
