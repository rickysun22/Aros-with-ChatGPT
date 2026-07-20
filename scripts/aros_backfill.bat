@echo off
chcp 65001 >nul
REM =====================================================================
REM AROS 一次性全 A 股历史回填 (首次部署必跑)
REM
REM 把全市场 (~5300 只) 的日线历史 (默认自 2024-01-01) 拉取并写入本地库。
REM 后续每日运行只做增量同步, 因此这一步只需跑一次。
REM
REM 耗时: 取决于网络, 通常 20~60 分钟。建议在命令行前台运行并观察进度。
REM 若中途失败, 重跑即可 —— 写入是幂等 upsert, 已拉取的不会重复。
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
    echo [ERROR] 未找到 python: %PYTHON%
    echo         请编辑本文件, 把 PYTHON 指向你的解释器(建议 venv)。
    pause
    exit /b 1
)

cd /d "%REPO%"
set "PYTHONPATH=%REPO%\src"

echo [%date% %time%] 开始全 A 股历史回填 (all_a, 自 2024-01-01) ...
"%PYTHON%" scripts/sync_universe.py all_a 2024-01-01
set "RC=%errorlevel%"
echo [%date% %time%] 回填结束 (exit=%RC%)

endlocal
if not %RC%==0 (
    echo.
    echo [提示] 回填似乎出错了 (exit=%RC%)。检查上面的报错信息。
    echo        常见原因: 网络不通 / 东财被限流 / python 依赖缺失。
    echo        重跑即可, 已拉取的数据不会重复 (幂等 upsert)。
)
echo.
echo 按任意键关闭本窗口...
pause >nul
exit /b %RC%
