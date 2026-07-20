@echo off
chcp 65001 >nul
REM =====================================================================
REM AROS 每日运行启动器 (Phase 4.9 日级运行闭环)
REM
REM 用法:
REM   1) 直接双击本文件可手动跑一次 (忽略时间检查);
REM   2) 由 Windows 任务计划程序每日收盘后自动调用;
REM   3) 由用户启动文件夹 VBS 守卫进程调用 (内置时间守卫)。
REM
REM 时间守卫: 非工作日 或 当前时间早于 18:00 则静默退出。
REM           手动双击时传 --force 跳过守卫。
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

REM ---------- 时间守卫: 非 --force 时检查 ----------
if not "%~1"=="--force" (
    REM 取今天是星期几 (1=周一 ... 7=周日)
    for /f %%d in ('powershell -NoProfile -Command "(Get-Date).DayOfWeek.value__"') do set DOW=%%d
    REM 周六(6)=周日(7) 直接退出
    if %DOW% gtr 5 (
        exit /b 0
    )
    REM 取当前小时, 早于 18 点则退出 (数据可能未就绪)
    for /f %%h in ('powershell -NoProfile -Command "(Get-Date).Hour"') do set HOUR=%%h
    if %HOUR% lss 18 (
        exit /b 0
    )
)

echo [%date% %time%] AROS 每日运行开始 (universe=all_a)
"%PYTHON%" main.py research alpha run --universe all_a
set "RC=%errorlevel%"
echo [%date% %time%] AROS 每日运行结束 (exit=%RC%)

endlocal
exit /b %RC%
