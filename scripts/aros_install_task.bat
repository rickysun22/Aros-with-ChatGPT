@echo off
REM =====================================================================
REM 注册 AROS 为 Windows 定时任务
REM
REM 效果: 每个工作日 18:30 自动调用 aros_daily.bat, 跑全 A 股日级筛选。
REM 18:30 是 A 股收盘(15:00)后数据就绪的安全时间。
REM =====================================================================

setlocal
set "BAT=%~dp0aros_daily.bat"
set "VBS=%~dp0_aros_launcher.vbs"

echo.
echo  ====== AROS 定时任务注册 ======
echo.

REM ---------- 方案 1: 尝试用 schtasks 创建 ----------
echo [步骤 1/2] 尝试创建计划任务 ...
schtasks /create /tn "AROS Daily Alpha" /tr "\"%BAT%\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 18:30 /f >nul 2>&1
if %errorlevel%==0 (
    echo.
    echo   [OK] 计划任务已创建!
    echo       名称 : AROS Daily Alpha
    echo       时间 : 每周一至周五 18:30
    echo       命令 : "%BAT%"
    echo.
    echo   管理命令:
    echo     schtasks /query /tn "AROS Daily Alpha"
    echo     schtasks /delete /tn "AROS Daily Alpha" /f
    goto :done
)

echo.
echo   [SKIP] schtasks 需要管理员权限, 当前账户没有。
echo         切换到方案 2 (无需管理员) ...

REM ---------- 方案 2: 用 VBS 静默启动器 + 用户启动文件夹 ----------
echo.
echo [步骤 2/2] 创建 VBS 静默启动器 ...

REM 生成 VBS 启动器 (隐藏窗口运行 bat)
(
echo Set WshShell = CreateObject("WScript.Shell"^)
echo WshShell.Run """" & Replace(WScript.ScriptFullName, "_aros_launcher.vbs", "aros_daily.bat") & """", 0, False
) > "%VBS%"

if not exist "%VBS%" (
    echo   [FAIL] 无法写入 VBS 文件。请检查目录权限。
    goto :fail
)

REM 放到用户启动文件夹 (开机自启 + 内部时间守卫)
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
copy /y "%VBS%" "%STARTUP%\_aros_daily.vbs" >nul 2>&1
if %errorlevel%==0 (
    echo.
    echo   [OK] 已用「用户启动文件夹」方案部署!
    echo       启动器 : %STARTUP%\_aros_daily.vbs
    echo       原始脚本 : "%BAT%"
    echo.
    echo   注意: 此方案会在每次登录时后台启动守卫进程,
    echo         守卫会等到工作日 18:30 才执行筛选。
    echo         如需删除, 删除下面文件即可:
    echo           del "%STARTUP%\_aros_daily.vbs"
) else (
    echo.
    echo   [WARN] 无法写入启动文件夹。手动操作:
    echo.
    echo   方法 A - 任务计划程序 ^(GUI^):
    echo     1. Win+R 输入 taskschd.msc 回车
    echo     2. 右侧「创建基本任务」→ 名称填 AROS Daily Alpha
    echo     3. 触发器选「每天」, 时间 18:30
    echo     4. 操作选「启动程序」, 程序填: "%BAT%"
    echo     5. 勾选「只在以下用户登录时运行」→ 完成
    echo.
    echo   方法 B - 手动复制文件:
    echo     复制 "%VBS%"
    echo     到   C:\Users\你的用户名\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\
    echo     并重命名为 _aros_daily.vbs
    goto :fail
)

goto :done

:fail
echo.
echo   部署未完成。请使用上方手动方法。

:done
echo.
pause
