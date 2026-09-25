@echo off
setlocal EnableExtensions

rem ============================================================================
rem  通用表格分割器 - 快速启动脚本
rem
rem  【编码说明 · 重要，改动前务必先读】
rem  本文件是 GBK(cp936) 编码 + CRLF 换行，并且脚本内**故意不调用 chcp**。
rem  原因：cmd.exe 按"当前控制台代码页"解码批处理文件，而 goto/call 按字节偏移跳转；
rem  如果在文件中途 chcp（例如 chcp 65001），先前算好的偏移就会与新解码方式错位，
rem  cmd 会从某一行中间继续解析，把注释/命令的尾部当命令执行——实测会刷出一堆
rem  "is not recognized as an internal or external command"，极端情况下甚至执行到
rem  意料之外的片段。保持"文件编码 == 控制台代码页"即可彻底避免。
rem  中文 Windows 控制台默认就是 936，因此这里什么都不用做。
rem  请勿把本文件另存为 UTF-8，也不要加 chcp。
rem
rem  用法：
rem    run.bat                            启动图形界面
rem    run.bat 表格.csv -o 输出 -n 5000    直接切分文件，参数原样透传给命令行
rem    run.bat -- --help                  查看程序自身的命令行参数
rem    run.bat --dry-run                  只显示解析结果，不真正启动
rem    run.bat -h                         显示本帮助
rem
rem  设计要点：
rem    1. 脚本可以放在任意位置：会从自身所在目录开始向上查找项目根目录
rem       （判断依据是同时存在 pyproject.toml 与 universal_table_splitter\__main__.py），
rem       因此脚本里不写任何绝对路径，也不依赖调用者当前所在目录；
rem    2. 解释器优先顺序：项目虚拟环境 .venv - py 启动器 - PATH 中的 python；
rem    3. 启动前校验 Python 版本、必需依赖与 tkinter，缺失时给出可复制的修复命令；
rem    4. 关键步骤写入日志，日志与程序自身日志放在同一目录，不会向项目里丢文件；
rem    5. 把 .csv 等文件直接拖到本脚本图标上，即可触发命令行切分。
rem ============================================================================

rem 控制台代码页不是 936 时中文会显示成乱码（命令本身仍然正常执行），这里用纯英文提示
set "CONSOLE_CP="
for /f "tokens=2 delims=:" %%A in ('chcp 2^>nul') do set "CONSOLE_CP=%%A"
if defined CONSOLE_CP set "CONSOLE_CP=%CONSOLE_CP: =%"
if defined CONSOLE_CP if not "%CONSOLE_CP%"=="936" echo [note] console code page is %CONSOLE_CP% instead of 936; Chinese messages may look garbled

rem ---- 日志位置：与程序自身日志同目录，避免污染项目文件夹 ----
set "LOG_DIR=%LOCALAPPDATA%\universal_table_splitter\logs"
if not defined LOCALAPPDATA set "LOG_DIR=%TEMP%\universal_table_splitter\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
set "LOG=%LOG_DIR%\launcher.log"

rem 日志超过 1MB 时清空重新累积，避免长期使用后无限膨胀
if exist "%LOG%" for %%I in ("%LOG%") do if %%~zI GTR 1048576 del "%LOG%" >nul 2>nul

rem ---- 规范化脚本所在目录：%~dp0 以反斜杠结尾，这里去掉 ----
for %%I in ("%~dp0.") do set "SCRIPT_DIR=%%~fI"

call :log "===== 启动脚本 ====="
call :log "脚本目录：%SCRIPT_DIR%"

rem ============================================================================
rem  第一步：解析参数
rem  本脚本的开关与程序参数共用一个命令行，遇到「--」之后不再解析
rem ============================================================================
set "DRY_RUN="
set "VERBOSE="
set "APP_ARGS="
set "PASSTHRU="

:parse_args
if "%~1"=="" goto :args_done
if defined PASSTHRU goto :collect_arg
if /i "%~1"=="--" ( set "PASSTHRU=1" & shift & goto :parse_args )
if /i "%~1"=="--dry-run" ( set "DRY_RUN=1" & shift & goto :parse_args )
if /i "%~1"=="-v" ( set "VERBOSE=1" & shift & goto :parse_args )
if /i "%~1"=="--verbose" ( set "VERBOSE=1" & shift & goto :parse_args )
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage
if /i "%~1"=="/?" goto :usage

:collect_arg
rem 统一加引号收集，含空格的文件路径不会被打散
set "APP_ARGS=%APP_ARGS% "%~1""
shift
goto :parse_args

:args_done

rem ============================================================================
rem  第二步：向上定位项目根目录
rem  必须「pyproject.toml」与「包目录」同时存在才算命中，避免误判外层项目
rem ============================================================================
set "ROOT="
call :find_root "%SCRIPT_DIR%"
if not defined ROOT goto :err_no_root
call :log "项目根目录：%ROOT%"

rem 让 Python 能找到仓库里的包，同时保留用户原有设置；不切换调用者目录
rem 不设置 PYTHONIOENCODING：Python 在 Windows 控制台走 WriteConsoleW，Unicode 直出，
rem 即使文件路径含 GBK 之外的字符也不会编码失败
if defined PYTHONPATH (set "PYTHONPATH=%ROOT%;%PYTHONPATH%") else (set "PYTHONPATH=%ROOT%")

rem ============================================================================
rem  第三步：定位 Python 解释器
rem ============================================================================
set "PYEXE="
set "PYVER="

if exist "%ROOT%\.venv\Scripts\python.exe" set "PYEXE=%ROOT%\.venv\Scripts\python.exe"
if not defined PYEXE (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYEXE=py"
        set "PYVER=-3"
    )
)
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE goto :err_no_python
call :log "Python 解释器：%PYEXE% %PYVER%"

rem ============================================================================
rem  第四步：环境校验
rem ============================================================================
"%PYEXE%" %PYVER% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if errorlevel 1 goto :err_python_version

"%PYEXE%" %PYVER% -c "import pandas" >nul 2>nul
if errorlevel 1 goto :err_missing_deps

if not defined APP_ARGS (
    rem 只有图形界面依赖 tkinter，命令行模式不需要
    "%PYEXE%" %PYVER% -c "import tkinter" >nul 2>nul
    if errorlevel 1 goto :err_no_tkinter
)

rem 可选依赖只提示不阻断，程序自身会降级并说明
"%PYEXE%" %PYVER% -c "import ttkbootstrap, openpyxl" >nul 2>nul
if errorlevel 1 call :log "提示：缺少 ttkbootstrap 或 openpyxl，界面将退回原生 ttk 且无法导出 xlsx"
"%PYEXE%" %PYVER% -c "import tkinterdnd2" >nul 2>nul
if errorlevel 1 call :log "提示：缺少 tkinterdnd2，无法拖放，可改用选择文件按钮"

rem 启动前先做一次导入自检：窗口程序启动失败时也能在控制台看到原因
"%PYEXE%" %PYVER% -c "import universal_table_splitter.ui.app" >nul 2>nul
if errorlevel 1 goto :err_import_failed

rem ============================================================================
rem  第五步：启动
rem ============================================================================
if defined APP_ARGS goto :run_cli
goto :run_gui

:run_gui
rem 找一个"无控制台"的解释器：pyw / pythonw / 虚拟环境里的 pythonw.exe
rem 找不到就退回普通解释器，功能不受影响，只是会多一个控制台窗口
set "PYW="
if /i "%PYEXE%"=="py" (
    where pyw >nul 2>nul
    if not errorlevel 1 set "PYW=pyw"
)
if /i "%PYEXE%"=="python" (
    where pythonw >nul 2>nul
    if not errorlevel 1 set "PYW=pythonw"
)
if exist "%ROOT%\.venv\Scripts\pythonw.exe" set "PYW=%ROOT%\.venv\Scripts\pythonw.exe"

if defined DRY_RUN (
    if defined PYW (call :log "解析结果：模式=图形界面，解释器=%PYW%") else (call :log "解析结果：模式=图形界面，解释器=%PYEXE% %PYVER%")
    call :log "解析结果：PYTHONPATH=%PYTHONPATH%"
    call :log "解析结果：将要启动 universal_table_splitter.ui.app"
    goto :end
)

call :log "启动图形界面"
if defined PYW (
    rem 优先用 pythonw：不留控制台窗口
    start "" "%PYW%" -m universal_table_splitter
) else (
    start "" "%PYEXE%" %PYVER% -m universal_table_splitter
)
if errorlevel 1 goto :err_launch
call :log "已请求启动，本窗口可以关闭"
goto :end

:run_cli
if defined DRY_RUN (
    call :log "解析结果：模式=命令行"
    call :log "解析结果：解释器=%PYEXE% %PYVER%"
    call :log "解析结果：PYTHONPATH=%PYTHONPATH%"
    call :log "解析结果：程序参数=%APP_ARGS%"
    goto :end
)

call :log "命令行模式，参数：%APP_ARGS%"
"%PYEXE%" %PYVER% -m universal_table_splitter %APP_ARGS%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :err_app_failed
call :log "执行完成，退出码 0"
goto :end

rem ============================================================================
rem  子过程
rem ============================================================================

:find_root
rem 入参 %1 = 起始目录；成功时设置 ROOT，失败时保持为空
set "DIR=%~1"
:find_root_loop
if exist "%DIR%\pyproject.toml" (
    if exist "%DIR%\universal_table_splitter\__main__.py" (
        set "ROOT=%DIR%"
        goto :eof
    )
)
for %%I in ("%DIR%\..") do set "PARENT=%%~fI"
if /i "%PARENT%"=="%DIR%" goto :eof
set "DIR=%PARENT%"
goto :find_root_loop

:log
rem 关键步骤：同时输出到控制台和日志文件
echo %~1
>>"%LOG%" echo [%DATE% %TIME%] %~1
goto :eof

:tail_log
rem 出错时打印日志末尾，方便双击运行的用户直接看到原因
where powershell >nul 2>nul
if errorlevel 1 (
    echo 详细日志见：%LOG%
    goto :eof
)
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 20 -Encoding UTF8" 2>nul
echo 详细日志见：%LOG%
goto :eof

:pause_if_interactive
rem 只有双击运行时才暂停，避免在终端里使用时多按一次回车
echo %CMDCMDLINE% | find /i "%~nx0" >nul
if not errorlevel 1 pause
goto :eof

:usage
echo.
echo 通用表格分割器 - 快速启动脚本
echo.
echo 用法：
echo   run.bat                            启动图形界面
echo   run.bat 表格.csv -o 输出 -n 5000    直接切分文件
echo   run.bat -- --help                  查看程序自身的命令行参数
echo.
echo 脚本开关：
echo   --dry-run      只显示解析到的项目根目录与将要执行的动作，不真正启动
echo   -v, --verbose  保留参数，关键步骤本身都会记录日志
echo   -h, --help     显示本帮助
echo.
echo 解释器优先级：项目 .venv - py 启动器 - PATH 中的 python
echo 日志文件：%LOG%
echo.
goto :end

rem ============================================================================
rem  错误处理：统一记录日志、打印日志尾部，双击运行时暂停
rem ============================================================================

:err_no_root
call :log "错误：未能从 %SCRIPT_DIR% 开始向上找到项目根目录"
call :log "      判断依据是同时存在 pyproject.toml 与 universal_table_splitter\__main__.py"
call :tail_log
call :pause_if_interactive
endlocal & exit /b 2

:err_no_python
call :log "错误：未找到 Python 解释器"
call :log "      请安装 Python 3.9 或更高版本，安装时勾选 Add python.exe to PATH"
call :log "      下载地址：https://www.python.org/downloads/windows/"
call :tail_log
call :pause_if_interactive
endlocal & exit /b 2

:err_python_version
call :log "错误：Python 版本过低，本项目需要 3.9 或更高版本"
call :log "      当前版本："
"%PYEXE%" %PYVER% -c "import sys; print(sys.version)" 2>nul
call :tail_log
call :pause_if_interactive
endlocal & exit /b 2

:err_missing_deps
call :log "错误：缺少必需依赖 pandas"
call :log "      可执行以下任一命令安装，注意把 %ROOT% 换成实际路径："
call :log "        %PYEXE% %PYVER% -m pip install -e %ROOT%"
call :log "        %PYEXE% %PYVER% -m pip install -r %ROOT%\requirements.txt"
call :tail_log
call :pause_if_interactive
endlocal & exit /b 2

:err_no_tkinter
call :log "错误：当前 Python 缺少 tkinter，无法启动图形界面"
call :log "      Windows 与 macOS 官方安装包自带；Linux 请安装 python3-tk"
call :log "      也可以改用命令行：run.bat 文件.csv -o 输出目录"
call :tail_log
call :pause_if_interactive
endlocal & exit /b 2

:err_import_failed
call :log "错误：导入 universal_table_splitter.ui.app 失败"
call :log "      请确认项目文件完整，或手工执行下面的命令查看完整报错："
call :log "        %PYEXE% %PYVER% -c import universal_table_splitter.ui.app"
call :tail_log
call :pause_if_interactive
endlocal & exit /b 2

:err_launch
call :log "错误：启动进程失败，退出码 %ERRORLEVEL%"
call :tail_log
call :pause_if_interactive
endlocal & exit /b 1

:err_app_failed
call :log "错误：程序以非 0 退出码结束：%RC%"
call :log "      程序自身日志：%LOCALAPPDATA%\universal_table_splitter\logs\app.log"
call :tail_log
call :pause_if_interactive
endlocal & exit /b %RC%

:end
endlocal
exit /b 0
