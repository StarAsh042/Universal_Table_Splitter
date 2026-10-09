# 变更日志

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 结构，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-10-10

通用表格分割器首个版本：把一份大表格按行数切成若干小文件。

提供图形界面与命令行两套入口，两者共用同一套核心逻辑，行为与错误提示完全一致。
读取支持 CSV / TSV / Excel（`.xlsx` / `.xlsm` / `.xls`）/ JSON / JSON Lines，
导出支持 CSV / TSV / XLSX / JSON / HTML。

### 新增

- **文件预览区**：选完文件立刻显示格式、编码、总行数、列名与前 20 行。
  读取在后台线程完成，只取第一块数据，不会为了预览把整份文件读一遍。
- **进度条**：百分比 + 已写行数 / 总行数 + 当前正在写出的文件名。
- **预计输出文件数实时预估**：改「每份行数」时立刻更新，数据取自预览结果，不重复读文件。
- **原生拖放**：基于 Qt 的 `QMimeData`，不需要任何额外的运行库。
- **自动挑选中文字体**：Qt 在 Windows 上的默认字体（Segoe UI）不含中文字形，
  程序按「微软雅黑 → 苹方 → Noto Sans CJK」的顺序挑一个确定带中文字形的字体。
- **缺少可选依赖时在窗口内提示**，不弹模态框、不阻断进入主界面。
- **版本号贯穿显示**：窗口标题栏显示 `通用表格分割器 v1.0.0`（切换语言后保留），
  打包出的 exe 在「属性 → 详细信息」中也有 `FileVersion` / `ProductVersion`。
  三处（标题栏、exe 属性、包元数据）都取自 `universal_table_splitter/__init__.py`
  的 `__version__` 这一个来源，不存在"改了一处忘另一处"的可能。
- **命令行入口**（`table-splitter` / `python -m universal_table_splitter ...`），
  与图形界面共用核心逻辑，便于批处理与自动化。
- **`run.bat` 快速启动脚本**：自动向上定位项目根目录（依据 `pyproject.toml` + 包目录，
  脚本放哪都能用，不写死绝对路径）；解释器优先 `/.venv` → `py` → `python`；
  图形界面自动选 `pyw` / `pythonw` 以免留控制台窗口；启动前校验 Python 版本与依赖；
  支持把表格文件拖到脚本上直接切分、`--dry-run` 查看解析结果、`--` 之后透传参数；
  关键步骤写入 `%LOCALAPPDATA%\universal_table_splitter\logs\launcher.log`。
- **`packaging/build.bat` 打包脚本**：一条命令产出单文件 exe；支持自定义输出目录、
  图标、exe 名称、工作目录；所有相对路径基于项目根目录解析（双击运行也安全）；
  构建输出实时打印并写入 `<输出目录>\build.log`；结束前校验产物确实生成并打印大小。
- **打包前的依赖完整性校验**（`packaging/ensure_deps.py`）：缺任何一项运行时依赖都会
  中止构建，并列出缺什么、给出可直接复制的安装命令。挡的是"在缺依赖的机器上打出
  一个悄悄少了功能的 exe"。
- **缺依赖时自动从 PyPI 安装**：`run.bat`、`packaging/build.bat` 与打包 spec 三处共用
  同一份判断逻辑。默认先列出缺什么、再问你是否现在安装，不会静默联网下载；
  非交互环境（CI、管道、stdin 被重定向）不提问，直接判定为"不安装"并失败，
  避免构建卡死在等待输入上。
  - `UTS_NO_AUTO_INSTALL=1` 完全禁用自动安装，只校验并失败。
  - 依赖清单从 `core/deps.py` **读源码解析**而不是 import：`core/__init__.py` 会连带
    导入 pandas，真去 import 会在"没装 pandas 的机器"上当场崩溃。
- **自动打包与自动发布**（`.github/workflows/release.yml`）：推送 `v*` 标签时自动完成
  「打包 Windows 单文件 exe + wheel/sdist → 创建 Release 并附上全部产物与 SHA256 校验和」。
  发布前会校验标签与 `__version__` 一致，避免版本错配。
- **`docs/RELEASE.md`**：发布流程与 GitHub 侧一次性配置清单（`Splitter` 令牌的创建与权限、
  内置令牌权限设置、Release 触发条件、403 等常见问题排查）。
- 记忆上次使用的行数 / 编号 / 格式 / 输出目录；完成后给出摘要并可一键打开输出目录。
- 预估输出文件数超过 1000 时，启动前先确认。
- 全套 `pytest` 用例（含 5 个使用真实 30 MB 数据的慢速集成测试）+ `ruff` 静态检查
  + `pre-commit`（全部在本地执行，GitHub Actions 不跑测试）。

### 安全

- 读取 xlsx 前校验解压比，防御解压炸弹；JSON / `.xls` 增加体积上限。
- 可选「转义公式前缀」，阻断 Excel 公式注入（OWASP CSV Injection）。
- 不静默覆盖同名文件：启动前告知冲突数量，可选择覆盖或加序号保留。
- 移除裸 `except:`；OS 错误（权限、磁盘满）翻译为可操作提示。
- 面向用户只显示友好文案，完整堆栈写入日志文件（轮转，保留 3 份）。
- 标准流统一重配置为 `errors="replace"`，中文文案或中文路径不会让 CLI 在窄编码
  （英文 Windows 的 cp1252）下崩溃。

### 性能

- 预检与执行复用同一个已打开的数据源，避免重复读取。
- 超过 64 MB 的 CSV / TSV 自动切换为**流式分块**，内存占用与文件体积无关。
- `.xlsx` 用 openpyxl 只读流式迭代，不整表载入。
- 进度回调按时间节流，避免海量分块时队列与 UI 线程被压垮。
- 保真模式读取比类型推断更快（32 MB 实测 1.6 s vs 2.9 s）。

### 设计取舍

- **代码分层**：`core`（业务，不依赖 Qt）+ `ui`（界面）+ `i18n` + `settings`
  + `logging_setup` + `cli`。`splitter.py` 保留为兼容启动器，`python splitter.py` 可用。
- **业务层不依赖界面层**：`core` 里没有任何 Qt 引用，因此可以被 `pytest` 完整覆盖。
- **子线程不碰控件**：所有跨线程结果都通过 `Signal` 回主线程，这是 Qt 里唯一的线程安全边界。
- **错误只携带 i18n key**：`AppError("err.sheet_not_found", sheet="S2")`，文案由 UI / CLI 渲染。
- **取消是协作式的**：`threading.Event` 从预检一路传到分块循环，在块边界检查；
  同一时刻只允许一个任务。
- **依赖声明**：`pyproject.toml` 是唯一事实来源，字段带兼容上界；`pywin32` 加平台标记。
- **导出格式**统一为 `csv / tsv / xlsx / json / html`，默认与输入同族。
- **界面固定为深色主题**，不跟随系统深浅色设置，换来跨平台一致的观感；DPI 缩放交给 Qt 6。
- **打包**：单文件 exe 约 87 MB——PySide6 是完整的 Qt 运行时。spec 里排除了
  用不到的 Qt 大模块（QtWebEngine、Qt3D、QtQuick 等）以及可能被间接拉进来的
  `tkinter` / `pandastable`，并且不对 PySide6 使用 `collect_all`
  ——那会把整个 Qt 拖进来让产物翻倍。
- **两个 `.bat` 使用 GBK(cp936) + CRLF，且脚本内不调用 `chcp`**：cmd.exe 按"当前控制台
  代码页"解码批处理文件，而 `goto` / `call` 按字节偏移跳转；在文件中途 `chcp` 会让先前
  算好的偏移与新解码方式错位，cmd 会从某一行中间继续解析。保持"文件编码 == 控制台代码页"
  即可彻底避免。
- **发布只面向 Windows**：所有作业都跑在 `windows-latest` 上，不产出任何 Linux 制品。
- **发布令牌**用仓库 Secret `Splitter`（`${{ secrets.Splitter || secrets.GITHUB_TOKEN }}`），
  未配置时自动回退到内置令牌，并在日志里打印实际使用的来源。

### 不提供

- `.xls` 导出（`pandas` 2.x 已无法写出 `.xls`，只支持读取）。
- 容器镜像打包（项目不需要面向 Ubuntu / Linux 发布制品）。
