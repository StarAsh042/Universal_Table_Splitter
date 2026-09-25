@echo off
setlocal EnableExtensions

rem ============================================================================
rem  通用表格分割器 - 打包脚本
rem  使用 PyInstaller 把项目及其全部依赖打成单个 exe，目标机器无需安装 Python
rem
rem  【编码说明 · 重要，改动前务必先读】
rem  本文件是 GBK(cp936) 编码 + CRLF 换行，并且脚本内**故意不调用 chcp**。
rem  原因：cmd.exe 按"当前控制台代码页"解码批处理文件，而 goto/call 按字节偏移跳转；
rem  如果在文件中途 chcp（例如 chcp 65001），先前算好的偏移会与新解码方式错位，
rem  cmd 就会从某一行中间继续解析，把注释/命令尾部当命令执行——实测会刷出一堆
rem  "is not recognized as an internal or external command"，并可能执行到意外片段。
rem  保持"文件编码 == 控制台代码页"即可彻底避免；中文 Windows 默认就是 936。
rem  请勿把本文件另存为 UTF-8，也不要加 chcp。
rem
rem  用法：
rem    packaging\build.bat                       打包，输出到 packaging\output\dist
rem    packaging\build.bat -o D:\发布            自定义输出目录
rem    packaging\build.bat -i assets\app.ico     指定图标
rem    packaging\build.bat -n 表格分割器          指定 exe 名称
rem    packaging\build.bat --dry-run             只打印将要执行的命令
rem    packaging\build.bat -h                    显示本帮助
rem
rem  选项：
rem    -o, --output-dir ^<目录^>   输出目录；相对路径基于**项目根目录**而不是当前目录
rem    -i, --icon ^<文件.ico^>     图标文件，必须是 ico 格式；默认用 assets\app.ico
rem    -n, --name ^<名称^>         生成的 exe 名称，默认 表格分割器
rem        --work-dir ^<目录^>     临时构建目录，默认 packaging\output\build
rem        --no-clean             复用上次构建缓存，重打包更快但可能残留旧文件
rem        --no-install           缺少 PyInstaller 或依赖时直接报错，不做交互式安装
rem        --open                 打包成功后自动打开输出目录
rem        --dry-run              只显示解析结果与将要执行的命令，不真正打包
rem    -h, --help                 显示本帮助
rem
rem  设计要点：
rem    1. 脚本可放在任意位置，从自身目录向上查找项目根目录（依据 pyproject.toml
rem       与 universal_table_splitter\__main__.py 同时存在），无需写死绝对路径；
rem    2. 所有相对路径都基于项目根目录解析，因此双击运行时不会把产物丢到
rem       C:\Windows\System32 之类的地方；
rem    3. 自动检测 Python 版本、运行时依赖与 PyInstaller，缺失时询问是否安装；
rem    4. 完整构建输出同时打印到控制台并写入 ^<输出目录^>\build.log，便于排查；
rem    5. 最终会校验产物是否真的生成，并打印大小，不会"看起来成功其实没产物"。
rem
rem  注意：首次打包约需 2-5 分钟；因为打包了 pandas 与 openpyxl，体积通常 60-150 MB。
rem        本文件必须保存为 UTF-8 无 BOM + CRLF 换行。
rem ============================================================================

rem 控制台代码页不是 936 时中文会显示成乱码（构建本身不受影响），这里用纯英文提示
set "CONSOLE_CP="
for /f "tokens=2 delims=:" %%A in ('chcp 2^>nul') do set "CONSOLE_CP=%%A"
if defined CONSOLE_CP set "CONSOLE_CP=%CONSOLE_CP: =%"
if defined CONSOLE_CP if not "%CONSOLE_CP%"=="936" echo [note] console code page is %CONSOLE_CP% instead of 936; Chinese messages may look garbled

rem ---- 规范化脚本所在目录 ----
for %%I in ("%~dp0.") do set "SCRIPT_DIR=%%~fI"

rem ---- 可选项默认值 ----
set "OUT_ARG="
set "WORK_ARG="
set "ICON_ARG="
set "APP_NAME="
set "DO_CLEAN=1"
set "ALLOW_INSTALL=1"
set "OPEN_AFTER="
set "DRY_RUN="
set "LOG="

call :log "===== 打包脚本 ====="
call :log "脚本目录：%SCRIPT_DIR%"

rem ============================================================================
rem  第一步：解析参数
rem ============================================================================
set "LAST_OPT="

:parse_args
if "%~1"=="" goto :args_done
set "LAST_OPT=%~1"
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage
if /i "%~1"=="/?" goto :usage
if /i "%~1"=="-o" goto :opt_output
if /i "%~1"=="--output-dir" goto :opt_output
if /i "%~1"=="-i" goto :opt_icon
if /i "%~1"=="--icon" goto :opt_icon
if /i "%~1"=="-n" goto :opt_name
if /i "%~1"=="--name" goto :opt_name
if /i "%~1"=="--work-dir" goto :opt_work
if /i "%~1"=="--no-clean" ( set "DO_CLEAN=" & shift & goto :parse_args )
if /i "%~1"=="--no-install" ( set "ALLOW_INSTALL=" & shift & goto :parse_args )
if /i "%~1"=="--open" ( set "OPEN_AFTER=1" & shift & goto :parse_args )
if /i "%~1"=="--dry-run" ( set "DRY_RUN=1" & shift & goto :parse_args )
goto :err_bad_option

:opt_output
if "%~2"=="" goto :err_missing_value
set "OUT_ARG=%~2"
shift
shift
goto :parse_args

:opt_icon
if "%~2"=="" goto :err_missing_value
set "ICON_ARG=%~2"
shift
shift
goto :parse_args

:opt_name
if "%~2"=="" goto :err_missing_value
set "APP_NAME=%~2"
shift
shift
goto :parse_args

:opt_work
if "%~2"=="" goto :err_missing_value
set "WORK_ARG=%~2"
shift
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

"%PYEXE%" %PYVER% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if errorlevel 1 goto :err_python_version

rem ============================================================================
rem  第四步：解析路径
rem  先切到项目根目录，这样用户传入的相对路径语义明确且安全（双击运行时
rem  当前目录可能是 C:\Windows\System32）
rem ============================================================================
pushd "%ROOT%" || goto :err_pushd

if not defined OUT_ARG set "OUT_ARG=packaging\output\dist"
if not defined WORK_ARG set "WORK_ARG=packaging\output\build"
if not defined APP_NAME set "APP_NAME=表格分割器"

for %%I in ("%OUT_ARG%") do set "OUT=%%~fI"
for %%I in ("%WORK_ARG%") do set "WORK=%%~fI"

set "SPEC=%ROOT%\packaging\table_splitter.spec"
set "LOG=%OUT%\build.log"

rem 日志超过 2MB 时清空，避免多次打包后无限膨胀
if exist "%LOG%" for %%I in ("%LOG%") do if %%~zI GTR 2097152 del "%LOG%" >nul 2>nul

rem 此时才知道日志位置，把上下文补记进日志文件
call :log "项目根目录：%ROOT%"
call :log "Python 解释器：%PYEXE% %PYVER%"
call :log "输出目录：%OUT%"
call :log "临时目录：%WORK%"
call :log "应用名称：%APP_NAME%"

rem ============================================================================
rem  第五步：校验输入
rem ============================================================================
if not exist "%SPEC%" goto :err_no_spec

rem 图标：命令行优先，其次 assets\app.ico；都没有就用 PyInstaller 默认图标
if defined ICON_ARG (
    for %%I in ("%ICON_ARG%") do set "ICON=%%~fI"
    if not exist "%ICON%" goto :err_icon_missing
    for %%I in ("%ICON%") do set "ICON_EXT=%%~xI"
    if /i not "%ICON_EXT%"==".ico" goto :err_icon_format
) else (
    set "ICON="
    if exist "%ROOT%\assets\app.ico" set "ICON=%ROOT%\assets\app.ico"
)
if defined ICON (call :log "图标文件：%ICON%") else (call :log "图标文件：未指定，使用 PyInstaller 默认图标")

"%PYEXE%" %PYVER% -c "import pandas, openpyxl" >nul 2>nul
if errorlevel 1 goto :err_missing_deps

rem ============================================================================
rem  第六步：确认 PyInstaller 可用
rem ============================================================================
"%PYEXE%" %PYVER% -m PyInstaller --version >nul 2>nul
if not errorlevel 1 goto :pyinstaller_ready

if not defined ALLOW_INSTALL goto :err_no_pyinstaller
echo.
echo 未检测到 PyInstaller，是否现在安装？大约需要下载 5 MB 左右。
set "ANS="
set /p "ANS=按回车安装，输入 n 跳过并退出："
if /i "%ANS%"=="n" goto :err_no_pyinstaller
call :log "正在安装 PyInstaller ..."
"%PYEXE%" %PYVER% -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err_install_failed
"%PYEXE%" %PYVER% -m PyInstaller --version >nul 2>nul
if errorlevel 1 goto :err_no_pyinstaller

:pyinstaller_ready
rem 通过临时文件取版本号，避免 for /f 遇到带空格的解释器路径时被拆坏
set "PI_VERSION=未知"
set "PI_VER_FILE=%TEMP%\uts_pi_version.txt"
"%PYEXE%" %PYVER% -m PyInstaller --version >"%PI_VER_FILE%" 2>nul
if exist "%PI_VER_FILE%" set /p PI_VERSION=<"%PI_VER_FILE%"
del "%PI_VER_FILE%" >nul 2>nul
call :log "PyInstaller 版本：%PI_VERSION%"

rem ============================================================================
rem  第七步：执行打包
rem ============================================================================
set "CLEAN_ARG="
if defined DO_CLEAN set "CLEAN_ARG=--clean"

rem 交给 spec 的两个可选项：图标与 exe 名称
set "UTS_ICON=%ICON%"
set "UTS_APP_NAME=%APP_NAME%"

set "BUILD_CMD=%PYEXE% %PYVER% -m PyInstaller --noconfirm %CLEAN_ARG% %SPEC% --distpath %OUT% --workpath %WORK% --log-level INFO"

if defined DRY_RUN (
    call :log "解析结果：模式=试运行，不执行打包"
    call :log "解析结果：%BUILD_CMD%"
    goto :end
)

if not exist "%OUT%" mkdir "%OUT%" >nul 2>nul
if not exist "%WORK%" mkdir "%WORK%" >nul 2>nul

call :log "开始打包，首次通常需要 2-5 分钟 ..."

rem PowerShell 可用时用 Tee-Object 实现"控制台实时输出 + 同步写日志"；
rem 路径里含单引号会让 PowerShell 的单引号字符串失效，此时退回纯重定向。
set "USE_PS="
where powershell >nul 2>nul
if not errorlevel 1 set "USE_PS=1"
if not "%OUT%"=="%OUT:'=%" set "USE_PS="
if not "%WORK%"=="%WORK:'=%" set "USE_PS="
if not "%SPEC%"=="%SPEC:'=%" set "USE_PS="
if not "%LOG%"=="%LOG:'=%" set "USE_PS="
if not "%PYEXE%"=="%PYEXE:'=%" set "USE_PS="

if defined USE_PS goto :build_with_ps
goto :build_plain

:build_with_ps
rem 追加一行分隔，便于在日志里定位本次构建
>>"%LOG%" echo.
>>"%LOG%" echo ========== 构建开始 %DATE% %TIME% ==========
rem 实时输出 + 写日志：Tee-Object 把输出同时送控制台并收集到变量，
rem 再用 .NET 的「系统默认编码」追加写文件——与上面 cmd 的 >> 写入保持一致
rem （中文系统即 GBK），也不会像 Tee-Object -FilePath 那样写成 UTF-16 造成同一文件两种编码。
rem 注意：Windows PowerShell 5.1 的 Tee-Object 没有 -Encoding 参数，所以不能直接用 -FilePath。
rem 也不改 [Console]::OutputEncoding：它默认就是控制台代码页，与 Python 的输出编码一致。
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $ErrorActionPreference='Continue'; & '%PYEXE%' %PYVER% -m PyInstaller --noconfirm %CLEAN_ARG% '%SPEC%' --distpath '%OUT%' --workpath '%WORK%' --log-level INFO 2>&1 | Tee-Object -Variable buildOut; $code = $LASTEXITCODE; if ($code -eq $null) { $code = 1 }; [IO.File]::AppendAllText('%LOG%', (($buildOut | Out-String) + [Environment]::NewLine), [Text.Encoding]::Default); exit $code }"
set "RC=%ERRORLEVEL%"
goto :after_build

:build_plain
call :log "提示：未使用 PowerShell 实时输出，构建过程只写入日志文件"
>>"%LOG%" echo.
>>"%LOG%" echo ========== 构建开始 %DATE% %TIME% ==========
"%PYEXE%" %PYVER% -m PyInstaller --noconfirm %CLEAN_ARG% "%SPEC%" --distpath "%OUT%" --workpath "%WORK%" --log-level INFO >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
goto :after_build

:after_build
rem ============================================================================
rem  第八步：校验产物
rem ============================================================================
if not "%RC%"=="0" goto :err_build_failed

set "EXE=%OUT%\%APP_NAME%.exe"
if exist "%EXE%" goto :artifact_ok

rem 兜底：万一 --distpath 未生效，产物会落在默认的 dist 目录
if exist "%ROOT%\dist\%APP_NAME%.exe" goto :err_wrong_distpath
goto :err_no_artifact

:artifact_ok
for %%I in ("%EXE%") do set "EXE_SIZE=%%~zI"
set /a "EXE_MB=%EXE_SIZE%/1048576"
echo.
call :log "打包成功"
call :log "产物：%EXE%"
call :log "大小：约 %EXE_MB% MB"
call :log "日志：%LOG%"
call :log "提示：该 exe 已包含 Python 与全部依赖，可直接拷贝到其它 Windows 机器运行"

if defined OPEN_AFTER start "" "%OUT%"
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
rem 日志位置确定前只打印到控制台，确定后同时写文件
echo %~1
if defined LOG >>"%LOG%" echo [%DATE% %TIME%] %~1
goto :eof

:tail_log
rem 出错时打印日志末尾，方便双击运行的用户直接看到原因
if not defined LOG (
    echo 提示：日志文件尚未创建
    goto :eof
)
where powershell >nul 2>nul
if errorlevel 1 (
    echo 详细日志见：%LOG%
    goto :eof
)
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 30" 2>nul
echo 详细日志见：%LOG%
goto :eof

:pause_if_interactive
rem 只有双击运行时才暂停，避免在终端里使用时多按一次回车
echo %CMDCMDLINE% | find /i "%~nx0" >nul
if not errorlevel 1 pause
goto :eof

:usage
echo.
echo 通用表格分割器 - 打包脚本
echo.
echo 用法：packaging\build.bat [选项]
echo.
echo   -o, --output-dir ^<目录^>   输出目录，默认 packaging\output\dist
echo                            相对路径基于项目根目录
echo   -i, --icon ^<文件.ico^>     图标文件，默认 assets\app.ico
echo   -n, --name ^<名称^>         生成的 exe 名称，默认 表格分割器
echo       --work-dir ^<目录^>     临时构建目录，默认 packaging\output\build
echo       --no-clean             复用构建缓存，重打包更快
echo       --no-install           缺少 PyInstaller 时直接报错
echo       --open                 打包成功后打开输出目录
echo       --dry-run              只显示将要执行的命令
echo   -h, --help                 显示本帮助
echo.
echo 说明：产物是单文件 exe，已内置 Python 与全部依赖，约 60-150 MB。
echo.
goto :end

rem ============================================================================
rem  错误处理：统一记录日志、打印日志尾部，双击运行时暂停
rem ============================================================================

:err_bad_option
call :log "错误：无法识别的选项 %LAST_OPT%"
call :log "      用 packaging\build.bat -h 查看全部选项"
call :pause_if_interactive
endlocal & exit /b 2

:err_missing_value
call :log "错误：选项 %LAST_OPT% 缺少取值"
call :log "      例如：-o packaging\output\dist"
call :pause_if_interactive
endlocal & exit /b 2

:err_no_root
call :log "错误：未能从 %SCRIPT_DIR% 开始向上找到项目根目录"
call :log "      判断依据是同时存在 pyproject.toml 与 universal_table_splitter\__main__.py"
call :pause_if_interactive
endlocal & exit /b 2

:err_no_python
call :log "错误：未找到 Python 解释器"
call :log "      请安装 Python 3.9 或更高版本，安装时勾选 Add python.exe to PATH"
call :pause_if_interactive
endlocal & exit /b 2

:err_python_version
call :log "错误：Python 版本过低，本项目需要 3.9 或更高版本"
"%PYEXE%" %PYVER% -c "import sys; print(sys.version)" 2>nul
call :pause_if_interactive
endlocal & exit /b 2

:err_pushd
call :log "错误：无法切换到项目根目录 %ROOT%"
call :pause_if_interactive
endlocal & exit /b 2

:err_no_spec
call :log "错误：找不到打包配置 %SPEC%"
call :log "      请确认 packaging\table_splitter.spec 存在"
call :pause_if_interactive
endlocal & exit /b 2

:err_icon_missing
call :log "错误：图标文件不存在：%ICON%"
call :pause_if_interactive
endlocal & exit /b 2

:err_icon_format
call :log "错误：图标必须是 .ico 格式，当前是 %ICON_EXT%"
call :log "      可用在线工具或 Pillow 把 png 转成 ico：pip install pillow"
call :pause_if_interactive
endlocal & exit /b 2

:err_missing_deps
call :log "错误：缺少打包所需的运行时依赖，无法收集文件"
call :log "      请先安装依赖：%PYEXE% %PYVER% -m pip install -e %ROOT%"
call :pause_if_interactive
endlocal & exit /b 2

:err_no_pyinstaller
call :log "错误：未安装 PyInstaller"
call :log "      请执行：%PYEXE% %PYVER% -m pip install pyinstaller"
call :pause_if_interactive
endlocal & exit /b 2

:err_install_failed
call :log "错误：PyInstaller 安装失败，请检查网络或代理设置"
call :tail_log
call :pause_if_interactive
endlocal & exit /b 2

:err_build_failed
call :log "错误：打包失败，退出码 %RC%"
call :log "      常见原因：网络代理导致 pip 失败、磁盘空间不足、杀毒软件拦截临时文件"
call :tail_log
call :pause_if_interactive
endlocal & exit /b 1

:err_wrong_distpath
call :log "错误：产物没有出现在指定的输出目录，而是落在了 %ROOT%\dist"
call :log "      请检查 PyInstaller 版本是否过旧，或改用默认输出目录重试"
call :pause_if_interactive
endlocal & exit /b 1

:err_no_artifact
call :log "错误：构建过程返回成功，但没有找到产物 %EXE%"
call :log "      请把日志文件提供给开发者排查"
call :tail_log
call :pause_if_interactive
endlocal & exit /b 1

:end
popd 2>nul
endlocal
exit /b 0
