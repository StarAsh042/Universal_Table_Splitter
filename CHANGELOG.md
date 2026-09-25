# 变更日志

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 结构，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.1.0] - 2026-09-23

一次以**健壮性与可维护性**为核心的重构。逐条对应 [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md)
中的评估结论；`P0/P1/P2` 为该报告中的问题编号。

### 修复（数据安全与功能性缺陷）

- **取消功能真正生效**（P0-1）：引入 `threading.Event` 协作式取消令牌，贯穿预检与分块循环；
  此前「取消」只改了一个布尔量，工作线程会继续写完全部文件。
- **杜绝并发写同一批文件**（P0-1）：同一时刻只允许一个工作线程，取消后再次点击不会再起第二个线程。
  此前取消后再点「开始分割」会与仍在运行的线程并发写同名文件，导致输出损坏。
- **取消不再被误报为成功**（P0-1）：迭代器遇到取消会静默停止产出，现在循环退出后会补判一次。
- **移除 `.xls` 导出**（P0-2）：pandas ≥ 2.0 已移除 `xlwt`，该选项必然抛
  `ValueError: No engine for filetype: 'xls'`。
- **修复拖放含空格/反斜杠路径静默失效**（P0-3）：不再使用会被 Tcl 转义的 `tk.splitlist`，
  改为自解析 payload；实测 `C:\plain\no\braces` 原先会被破坏成 `C:plain\no\x08races`。
- **新增编码回退**（P1-2）：BOM → UTF-8 → GB18030 → Big5 → CP1252 → Latin-1，
  GBK 中文 CSV 不再直接抛 `UnicodeDecodeError`。
- **CSV/TSV 导出写入 UTF-8 BOM**（P1-1）：Excel 打开中文不再乱码。
- **保真模式，默认开启**（P1-3）：按文本读取，保留前导零、长整数，避免整数列因空值变 `1.0`。
- **多工作表可选择**（P1-4）：`.xlsx` 含多个 sheet 时出现下拉框；此前只读第一个且无任何提示。
- **原子写入 + 失败清理**（P1-6）：先写 `.part` 再 `os.replace`，失败不留半成品。
- **编号格式语义修正并加上界**（P1-7）：该输入实为「位数」，原先写成 `f"{i:{num_format}}"` 是
  误导性用法（实测 `f"{5:001}"` 得到 `'5'`）；输入 `1000` 会生成 1000 字符的文件名并必然失败，
  现在限制为 1–10 位。README 中「使用 Python 格式字符串（如 `03d`）」的说法同步修正。
- **修复重复校验**（P2-1）：输入为空时会重复追加同一条错误。
- **非数字输入不再泄露 Python 异常**（P2-2）：`invalid literal for int() ...` 已替换为本地化提示。
- **进度不再越界**（P2-5）：末块不再显示 `3000/2500`；完成后进度条停在 100%。
- **空表显式提示**（P2-6）：不再默默「分割完成」却不产出文件。
- **修复事件轮询在异常后永久停止**（PERF-6）：改用 `finally` 保证续期。
- **修复运行中切换语言丢失进度**（2-11）：状态文案改为可重渲染。
- **界面不再因样式缺失而崩溃**：`ttk.Checkbutton(bootstyle="round-toggle")` 依赖主题里已注册的
  layout，在打包环境（实测 PyInstaller 产物）中可能缺失并抛
  `TclError: Layout Round.Toggle not found`，导致整个界面构建失败、程序打不开。
  现在 `styled()` 支持 `"候选1|候选2"` 逐级降级（圆形开关 → 平面工具按钮 → 原生 ttk）并记录告警；
  `main()` 另有一层兜底：首次构建失败会禁用 ttkbootstrap 后重建一次界面，保证程序总能启动。
  同时让 `create_style()` 的降级调用路径记录日志，避免"主题悄悄换了却查不到"。
- **修复打包版多出一个空白 "tk" 窗口**：ttkbootstrap 的对话框在 `parent=None` 时会额外创建一个
  可见窗口（已实测复现：`MessageDialog(parent=None)` 多出一个窗口，传 parent 则不会）。
  界面里 9 处 `messagebox` 调用现在全部显式传 `parent`。另外 `TkinterDnD.Tk()` 是先建窗口
  再加载 tkdnd 运行库，加载失败时也会残留空窗，`create_root()` 现在会回收这个半成品窗口。
- **修复打包版丢失拖放**：`tkinterdnd2` 在 `app` 里是延迟导入，PyInstaller 静态分析收集不到，
  导致打包版总是提示"缺少可选依赖"并禁用拖放。spec 现在通过 `collect_all("tkinterdnd2")`
  连带收集其 `tkdnd` 运行库（`win-x64/*.dll`、`*.tcl`），打包版拖放已可用。
- **修复两个 .bat 被 cmd 错误解析**（隐藏很深、影响所有构建）：脚本里的 `chcp 65001` 会在
  文件中途改变解码方式，而 cmd 的 `goto`/`call` 用的是按旧代码页算出的字节偏移，于是它会
  从某一行中间继续解析，把注释/命令尾部当成命令执行——实测控制台会刷出 17 组
  `'…' is not recognized as an internal or external command`（从多字节字符中间截断）。
  这两个脚本已改为 **GBK(cp936) + CRLF 且不再调用 chcp**，做到"文件编码 == 控制台代码页"，
  偏移不再错位；构建日志的写入编码也统一为系统默认（GBK），不再出现同一文件两种编码。
  连续 20 次试运行 + 完整构建输出扫描均为 0 异常。
- **修复英文环境下中文输出导致的崩溃**（CI 实测）：GitHub 的 `windows-latest` 是英文环境，
  Python 标准流的编码是 cp1252，`print("应用版本 …")` 会抛 `UnicodeEncodeError` ——
  1.1.0 的自动打包正是在 `table_splitter.spec` 打印版本号那一行直接失败。
  现在 spec 与 `setup_logging()` 都会把标准流重配置为 `errors="replace"`
  （装不下的字符降级为 `?`，中文控制台 cp936 / UTF-8 的输出不受影响），
  英文 Windows 上运行 CLI 也不会再因为中文文案或中文路径而中断；
  工作流同时设置 `PYTHONUTF8=1`，让 CI 日志里的中文保持可读。

### 安全

- 读取 xlsx 前校验解压比，防御解压炸弹；JSON / `.xls` 增加体积上限。
- 可选「转义公式前缀」，阻断 Excel 公式注入（OWASP CSV Injection）。
- 不再静默覆盖同名文件：启动前告知冲突数量，可选择覆盖或加序号保留。
- 移除裸 `except:`；OS 错误（权限/磁盘满）翻译为可操作提示。
- 面向用户只显示友好文案，完整堆栈写入日志文件（轮转，保留 3 份）。

### 性能

- 预检与执行复用同一个已打开的数据源，避免重复读取（32 MB CSV 约省 1.3 s，大文件收益更明显）。
- 超过 64 MB 的 CSV/TSV 自动切换为**流式分块**，内存占用与文件体积无关。
- `.xlsx` 改用 openpyxl 只读流式迭代，不再整表载入。
- 进度回调按时间节流，避免海量分块时队列与 UI 线程被压垮。
- 保真模式读取实测比类型推断更快（1.6 s vs 2.9 s / 32 MB）。

### 变更

- **代码分层**：拆分为 `core`（业务，不依赖 tkinter）+ `ui`（界面）+ `i18n` + `settings`
  + `logging_setup` + `cli`。`splitter.py` 保留为兼容启动器，`python splitter.py` 与旧打包脚本无需改动。
- **依赖声明**：`pyproject.toml` 成为唯一事实来源，字段带上界；移除从未使用的 `python-dotenv`；
  `tkinterdnd2` 改为可选依赖；`pywin32` 加平台标记。
- **导出格式选项**：统一为 `csv / tsv / xlsx / json / html`，默认与输入同族
  （`.json` 输入默认导出 JSON，`.xlsx` 输入默认导出 XLSX）。
- **主题探测**：Windows 改读注册表 `AppsUseLightTheme`，补上 macOS 支持；
  此前用「标题栏颜色分量的蓝色通道」猜测深色模式，非 Windows 平台永远落到浅色。
- **DPI 感知**：`SetProcessDpiAwareness` 移到创建窗口之前（原先在窗口创建后才调用，等于没生效）。
- **`update_ui_text` 不再依赖 Tk 自动生成的控件名**（`children['!button']`），改为持有控件引用。
- **`AppState` 状态机**取代 `hasattr(self, 'running')` 补丁式状态管理。
- **i18n**：所有面向用户的字符串统一走 `tr()`，清除硬编码英文（如 `Chunk size must be positive`）。
- **打包**：新增 `packaging/table_splitter.spec`，不再需要在命令行里写死本机 `site-packages` 路径。

### 新增

- **版本号贯穿显示**：窗口标题栏现在是 `通用表格分割器 v1.1.0`（切换语言后同样保留），
  打包出的 exe 在「属性 → 详细信息」中也有 `FileVersion` / `ProductVersion`。
  三处（标题栏、exe 属性、包元数据）都取自 `universal_table_splitter/__init__.py` 的
  `__version__` 这一个来源：`pyproject.toml` 用动态版本引用它，打包 spec 也直接读它并
  现场生成 `VSVersionInfo` 版本资源，因此不存在"改了一处忘另一处"的可能。
- **`run.bat` 快速启动脚本**：自动向上定位项目根目录（依据 `pyproject.toml` + 包目录，
  脚本放哪都能用，不写死绝对路径）；解释器优先 `/.venv` → `py` → `python`；
  图形界面自动选 `pyw`/`pythonw` 以免留控制台窗口；启动前校验 Python 版本、
  pandas 与 tkinter；支持把表格文件拖到脚本上直接切分、`--dry-run` 查看解析结果、
  `--` 之后透传参数；关键步骤写入 `%LOCALAPPDATA%\universal_table_splitter\logs\launcher.log`
  （超过 1 MB 自动重置），出错时打印日志尾部并在双击场景下暂停。
- **`packaging/build.bat` 打包脚本**：一条命令产出单文件 exe；支持 `-o/--output-dir`
  自定义输出目录、`-i/--icon` 指定图标、`-n/--name` 指定名称、`--work-dir`、`--no-clean`、
  `--no-install`、`--open`、`--dry-run`；所有相对路径基于项目根目录解析（双击运行也安全）；
  自动检查/安装 PyInstaller 与运行时依赖；构建输出实时打印并写入 `<输出目录>\build.log`；
  结束前校验产物确实生成并打印大小，失败时按原因分类提示并打印日志尾部。
- `packaging/table_splitter.spec` 支持通过环境变量 `UTS_ICON` / `UTS_APP_NAME` 覆盖图标与名称
  （PyInstaller 在读入 spec 后会忽略 `--icon`/`--name` 命令行选项，脚本因此改用环境变量）。
- CLI 入口（`table-splitter` / `python -m universal_table_splitter ...`），与 GUI 共用核心逻辑，
  支持批处理与自动化。
- 记忆上次使用的行数/编号/格式/目录；完成后给出摘要并可一键打开输出目录。
- 预估输出文件数超过 1000 时启动前确认。
- 启动时自检可选依赖，缺失的能力提前说明而非运行中报错。
- 211 个 `pytest` 用例（含 5 个使用真实 30 MB 数据的慢速集成测试）+ `ruff` 静态检查
  + `pre-commit`（全部在本地执行，GitHub Actions 不跑测试）。
- **自动打包与自动发布**：`.github/workflows/release.yml` 在推送 `v*` 标签时自动完成
  「打包 Windows 单文件 exe + wheel/sdist → 创建 Release 并附上全部产物与 SHA256 校验和」；
  发布前会校验标签与 `__version__` 一致，避免出现「Release 标 v1.2.0、exe 内嵌版本还是 1.1.0」的错配。
  原有的 CI 测试矩阵（三平台 × Python 3.9–3.12）按需求移除。
- **发布流程只面向 Windows**：所有作业统一使用 `windows-latest`，
  不在 Ubuntu / Linux 上打包，也不产出任何 Linux 制品。
- **发布令牌改用仓库 Secret `Splitter`**：`${{ secrets.Splitter || secrets.GITHUB_TOKEN }}`，
  已配置则优先使用、未配置自动回退，并在日志中打印实际使用的令牌来源。
- `docs/RELEASE.md`：发布流程与 GitHub 侧一次性配置清单（`Splitter` 令牌的创建与权限、
  内置令牌权限设置、Release 触发条件、403 等常见问题排查）。

### 移除

- `.xls` 导出（pandas 2.x 已无法写出）。
- 未使用的 `SplitStrategy` / `get_splitter` 空实现，以及未使用的 `logging`、`lru_cache` 导入。
- README 中失效的 `html5lib` / `xlsxwriter` 安装指引（代码并不需要它们）。
- 容器镜像打包（`Dockerfile` / `.dockerignore` 与对应的 CI 作业）：项目不需要面向 Ubuntu /
  Linux 发布制品。

## [1.0.0] - 2024

- 初版：Tk 界面、按行数分割、多格式导出、双语、主题适配、拖放。
