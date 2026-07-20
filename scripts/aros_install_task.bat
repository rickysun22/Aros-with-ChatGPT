@echo off
REM =====================================================================
REM 注册 AROS 为 Windows 计划任务 (需「以管理员身份运行」本文件)
REM
REM 效果: 每个工作日 18:30 自动调用 aros_daily.bat, 跑全 A 股日级筛选。
REM 18:30 是 A 股收盘(15:00)后数据就绪的安全时间。
REM =====================================================================
setlocal
set "BAT=%~dp0aros_daily.bat"

schtasks /create /tn "AROS Daily Alpha" /tr "\"%BAT%\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 18:30 /f
if %errorlevel%==0 (
    echo [OK] 已创建计划任务 "AROS Daily Alpha" (工作日 18:30)。
    echo      用下面命令管理/删除:
    echo        schtasks /query  /tn "AROS Daily Alpha"
    echo        schtasks /delete /tn "AROS Daily Alpha" /f
) else (
    echo [FAIL] 创建失败。请右键本文件 -> 以管理员身份运行。
)
pause
