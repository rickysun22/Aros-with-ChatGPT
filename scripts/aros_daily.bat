@echo off
REM =====================================================================
REM AROS 每日运行启动器 (Phase 4.9 日级运行闭环)
REM
REM 用法:
REM   1) 直接双击本文件可手动跑一次;
REM   2) 由 Windows 任务计划程序每日收盘后自动调用 (见 WINDOWS_TASK.md)。
REM
REM 编辑点:
REM   把下面 PYTHON 改成你机器上的 python 解释器。推荐用虚拟环境:
REM     python -m venv .venv && .venv\Scripts\pip install -e .
REM   若依赖装在别处, 改成那边的 python.exe 绝对路径即可。
REM =====================================================================
setlocal
set "REPO=%~dp0.."
set "PYTHON=%REPO%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [ERROR] 未找到 python: %PYTHON%
    echo         请编辑本文件, 把 PYTHON 指向你的解释器(建议 venv)。
    pause
    exit /b 1
)

cd /d "%REPO%"
set "PYTHONPATH=%REPO%\src"

echo [%date% %time%] AROS 每日运行开始 (universe=all_a)
"%PYTHON%" main.py research alpha run --universe all_a
set "RC=%errorlevel%"
echo [%date% %time%] AROS 每日运行结束 (exit=%RC%)

endlocal
exit /b %RC%
