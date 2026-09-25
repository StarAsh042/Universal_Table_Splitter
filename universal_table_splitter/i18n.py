"""国际化文案表。

约定：
- key 使用 ``模块.用途`` 的点号分层，扁平字典，避免多层嵌套查找；
- 文案中的占位符使用 ``str.format`` 的 ``{name}`` 形式（不要出现裸花括号）；
- 任何面向用户的字符串都必须走这里，不允许在业务代码里硬编码自然语言。
"""

from __future__ import annotations

from typing import Any

from .config import DEFAULT_LANG

LANGUAGES: dict[str, dict[str, str]] = {
    "cn": {
        # ---- 窗口与按钮 ----
        "app.title": "通用表格分割器",
        # 标题栏：版本号来自 __init__.py 的 __version__，保证界面与打包产物一致
        "app.title_with_version": "{title} v{version}",
        "btn.input": "选择输入文件（支持拖放）",
        "btn.output": "选择输出目录（可选）",
        "btn.start": "开始分割",
        "btn.cancel": "取消分割",
        "btn.about": "关于",
        "btn.lang": "切换英文",
        "btn.open_output": "打开输出目录",
        # ---- 参数区 ----
        "label.params": "分割参数",
        "label.size": "每份行数",
        "label.num_format": "编号格式",
        "label.export": "导出格式",
        "label.sheet": "工作表",
        "label.fidelity": "保真模式（按文本读取，保留前导零与长数字）",
        "label.escape_formulas": "转义公式前缀（防止 Excel 公式注入，会加前导单引号）",
        "hint.num_format": "位数，例如 001 生成 001、002、003",
        "hint.output": "留空则使用输入文件所在目录",
        # ---- 状态栏 ----
        "status.ready": "准备就绪",
        "status.scanning": "正在统计行数…",
        "status.running": "{current} / {total} 行",
        "status.running_unknown": "已写入 {current} 行",
        "status.success": "分割完成",
        "status.canceled": "操作已取消",
        "status.canceling": "正在取消…",
        "status.summary": "完成：{count} 个文件，{rows} 行，耗时 {seconds} 秒",
        "status.error": "出错：{message}",
        "status.detected": "已识别：{encoding} 编码，共 {rows} 行",
        "status.detected_rows": "已识别：共 {rows} 行",
        # ---- 可选依赖 ----
        "dep.pandas": "核心数据引擎（pandas）",
        "dep.openpyxl": "Excel .xlsx 读写（openpyxl）",
        "dep.xlrd": "旧版 Excel .xls 读取（xlrd）",
        "dep.ttkbootstrap": "主题化界面（ttkbootstrap）",
        "dep.tkinterdnd2": "拖放支持（tkinterdnd2）",
        # ---- 结果摘要 ----
        "summary.title": "分割完成",
        "summary.body": "已生成 {count} 个文件，共 {rows} 行。\n输出目录：{dir}\n耗时：{seconds} 秒",
        # ---- 确认对话框 ----
        "confirm.large_job.title": "输出文件较多",
        "confirm.large_job.body": "按当前参数将生成 {count} 个文件（共 {rows} 行）。\n文件过多会明显变慢，是否继续？",
        "confirm.large_job.yes": "继续",
        "confirm.large_job.no": "取消",
        "confirm.overwrite.title": "文件已存在",
        "confirm.overwrite.body": "输出目录中已存在 {count} 个同名文件。\n是＝覆盖，否＝自动追加序号并保留原文件。",
        "confirm.overwrite.yes": "覆盖",
        "confirm.overwrite.no": "保留并加序号",
        "confirm.close.title": "任务进行中",
        "confirm.close.body": "分割任务尚未完成，确定要退出吗？",
        "confirm.cleanup.title": "清理未完成文件",
        "confirm.cleanup.body": "任务未完成，本次已生成 {count} 个文件。\n是否删除它们？",
        "info.empty.title": "提示",
        "info.dnd_missing.body": "缺少可选依赖 tkinterdnd2，拖放功能不可用。\n安装后可启用：pip install tkinterdnd2\n\n仍可使用“选择输入文件”按钮。",
        "info.deps_missing.title": "缺少可选依赖",
        "info.deps_missing.body": "以下功能将不可用：\n{names}",
        # ---- 错误 ----
        "err.invalid_params": "参数不完整",
        "err.invalid_file": "不支持的文件格式，请选择 CSV / Excel / JSON / TSV 文件",
        "err.file_missing": "文件不存在：{path}",
        "err.not_a_file": "不是有效的文件：{path}",
        "err.invalid_number": "编号格式需为 {min}-{max} 位数字（例如 001）",
        "err.invalid_chunk_size": "每份行数需为 {min}-{max} 之间的整数",
        "err.output_not_dir": "输出路径不是目录：{path}",
        "err.output_not_writable": "输出目录不可写：{path}",
        "err.invalid_export_format": "不支持的导出格式：{fmt}",
        "err.missing_dep": "缺少依赖库 {name}，请执行：pip install {hint}",
        "err.encoding": "无法识别 {path} 的文本编码，请另存为 UTF-8 或 GBK 后重试",
        "err.empty_table": "输入文件中没有数据行，未生成任何文件",
        "err.no_sheets": "工作簿中没有可用的工作表",
        "err.sheet_not_found": "找不到工作表：{sheet}",
        "err.file_too_large": "{fmt} 需要完整载入内存，当前文件 {size} 超过上限 {limit}。\n建议先另存为 CSV/TSV 再分割。",
        "err.suspicious_file": "文件解压后体积异常（{ratio} 倍），已中止读取以保护内存",
        "err.out_of_memory": "内存不足，请改用 CSV/TSV 流式读取或缩小文件",
        "err.permission": "没有访问权限：{path}",
        "err.disk_full": "磁盘空间不足，无法写入：{path}",
        "err.read_failed": "读取文件失败：{message}",
        "err.write_failed": "写入文件失败：{message}",
        "err.json_parse": "JSON 解析失败，请确认文件是记录数组或 JSON Lines 格式",
        "err.task_running": "已有任务正在运行，请先取消",
        "err.unexpected": "发生未预期的错误，详情见日志：{path}",
        "err.canceled_by_user": "已取消本次操作",
        "err.sheet_required": "该工作簿包含多个工作表，请选择要分割的工作表",
        # ---- 关于 ----
        "about.title": "关于",
        "about.version": "版本：{version}",
        "about.author": "作者：{author}",
        "about.github": "GitHub：",
        "about.license": "许可证：AGPL-3.0",
        "about.runtime": "运行环境：Python {python} · pandas {pandas}",
        "about.usage": "使用说明：",
        "about.step1": "1. 选择或拖入要分割的文件",
        "about.step2": "2. 设置每份行数与编号格式",
        "about.step3": "3. 点击开始分割，运行中可随时取消",
        # ---- CLI ----
        "cli.description": "通用表格分割器：把大表格按行数切成多个小文件",
        "cli.input": "输入文件（CSV / Excel / JSON / TSV）",
        "cli.output": "输出目录（默认与输入文件同目录）",
        "cli.rows": "每个文件的份数行数",
        "cli.digits": "编号位数，例如 3 生成 001、002",
        "cli.format": "导出格式",
        "cli.sheet": "工作表名称（Excel 多工作表时使用）",
        "cli.no_fidelity": "关闭保真模式，允许 pandas 自动推断类型",
        "cli.escape_formulas": "转义以 = + - @ 开头的单元格，防止 Excel 公式注入",
        "cli.overwrite": "同名文件处理：overwrite 覆盖 / index 追加序号",
        "cli.stream": "强制流式读取（内存有界，适合超大文件）",
        "cli.lang": "输出语言",
        "cli.done": "完成：生成 {count} 个文件，共 {rows} 行，耗时 {seconds} 秒",
        "cli.progress": "进度 {percent}%（{rows} 行，{files} 个文件）",
        "cli.canceled": "已取消，已生成 {count} 个文件",
        "cli.files_planned": "将生成 {count} 个文件",
        "cli.overwrite_warning": "警告：{count} 个同名文件将被覆盖",
        "cli.log_hint": "日志：{path}",
    },
    "en": {
        "app.title": "Universal Table Splitter",
        "app.title_with_version": "{title} v{version}",
        "btn.input": "Select Input File (Drag and Drop Supported)",
        "btn.output": "Select Output Directory (Optional)",
        "btn.start": "Start Splitting",
        "btn.cancel": "Cancel",
        "btn.about": "About",
        "btn.lang": "Switch to Chinese",
        "btn.open_output": "Open Output Folder",
        "label.params": "Split Settings",
        "label.size": "Rows per chunk",
        "label.num_format": "Number format",
        "label.export": "Export format",
        "label.sheet": "Worksheet",
        "label.fidelity": "Fidelity mode (read as text, keep leading zeros)",
        "label.escape_formulas": "Escape formula prefixes (blocks Excel formula injection; adds a leading apostrophe)",
        "hint.num_format": "Digit count, e.g. 001 produces 001, 002, 003",
        "hint.output": "Empty means the input file's folder",
        "status.ready": "Ready",
        "status.scanning": "Counting rows…",
        "status.running": "{current} / {total} rows",
        "status.running_unknown": "{current} rows written",
        "status.success": "Splitting completed",
        "status.canceled": "Operation canceled",
        "status.canceling": "Canceling…",
        "status.summary": "Done: {count} files, {rows} rows in {seconds}s",
        "status.error": "Error: {message}",
        "status.detected": "Detected: {encoding} encoding, {rows} rows",
        "status.detected_rows": "Detected: {rows} rows",
        "dep.pandas": "Core data engine (pandas)",
        "dep.openpyxl": "Excel .xlsx read/write (openpyxl)",
        "dep.xlrd": "Legacy Excel .xls reading (xlrd)",
        "dep.ttkbootstrap": "Themed UI (ttkbootstrap)",
        "dep.tkinterdnd2": "Drag and drop (tkinterdnd2)",
        "summary.title": "Splitting completed",
        "summary.body": "Created {count} files with {rows} rows in total.\nOutput: {dir}\nElapsed: {seconds}s",
        "confirm.large_job.title": "Many output files",
        "confirm.large_job.body": "These settings will create {count} files ({rows} rows in total).\nThis can be slow. Continue?",
        "confirm.large_job.yes": "Continue",
        "confirm.large_job.no": "Cancel",
        "confirm.overwrite.title": "Files already exist",
        "confirm.overwrite.body": "{count} target files already exist in the output folder.\nYes = overwrite, No = append an index and keep the originals.",
        "confirm.overwrite.yes": "Overwrite",
        "confirm.overwrite.no": "Keep and index",
        "confirm.close.title": "Task in progress",
        "confirm.close.body": "Splitting has not finished. Quit anyway?",
        "confirm.cleanup.title": "Remove unfinished files",
        "confirm.cleanup.body": "The task did not finish and {count} files were created.\nDelete them?",
        "info.empty.title": "Notice",
        "info.dnd_missing.body": 'Optional dependency tkinterdnd2 is missing, so drag and drop is disabled.\nInstall it with: pip install tkinterdnd2\n\nYou can still use the "Select Input File" button.',
        "info.deps_missing.title": "Missing optional dependencies",
        "info.deps_missing.body": "These features will be unavailable:\n{names}",
        "err.invalid_params": "Incomplete parameters",
        "err.invalid_file": "Unsupported file format, please pick a CSV / Excel / JSON / TSV file",
        "err.file_missing": "File not found: {path}",
        "err.not_a_file": "Not a valid file: {path}",
        "err.invalid_number": "Number format must be {min}-{max} digits (e.g. 001)",
        "err.invalid_chunk_size": "Rows per chunk must be an integer between {min} and {max}",
        "err.output_not_dir": "Output path is not a directory: {path}",
        "err.output_not_writable": "Output directory is not writable: {path}",
        "err.invalid_export_format": "Unsupported export format: {fmt}",
        "err.missing_dep": "Missing dependency {name}, please run: pip install {hint}",
        "err.encoding": "Cannot detect the text encoding of {path}, please re-save it as UTF-8 or GBK",
        "err.empty_table": "The input file has no data rows, nothing was written",
        "err.no_sheets": "The workbook contains no usable worksheet",
        "err.sheet_not_found": "Worksheet not found: {sheet}",
        "err.file_too_large": "{fmt} must be loaded into memory and {size} exceeds the limit {limit}.\nConsider saving it as CSV/TSV first.",
        "err.suspicious_file": "Unusually high decompression ratio ({ratio}x); aborted to protect memory",
        "err.out_of_memory": "Out of memory, please use CSV/TSV streaming or a smaller file",
        "err.permission": "Access denied: {path}",
        "err.disk_full": "Not enough disk space to write: {path}",
        "err.read_failed": "Failed to read the file: {message}",
        "err.write_failed": "Failed to write the file: {message}",
        "err.json_parse": "JSON parsing failed; expected an array of records or JSON Lines",
        "err.task_running": "A task is already running, please cancel it first",
        "err.unexpected": "Unexpected error, see the log for details: {path}",
        "err.canceled_by_user": "Operation canceled",
        "err.sheet_required": "This workbook has multiple worksheets, please choose one",
        "about.title": "About",
        "about.version": "Version: {version}",
        "about.author": "Author: {author}",
        "about.github": "GitHub: ",
        "about.license": "License: AGPL-3.0",
        "about.runtime": "Runtime: Python {python} · pandas {pandas}",
        "about.usage": "Usage:",
        "about.step1": "1. Choose or drop the file to split",
        "about.step2": "2. Set rows per chunk and the number format",
        "about.step3": "3. Click Start; you can cancel at any time",
        "cli.description": "Universal Table Splitter: cut a large table into smaller files",
        "cli.input": "Input file (CSV / Excel / JSON / TSV)",
        "cli.output": "Output directory (defaults to the input folder)",
        "cli.rows": "Rows per output file",
        "cli.digits": "Number of digits, e.g. 3 produces 001, 002",
        "cli.format": "Export format",
        "cli.sheet": "Worksheet name (for multi-sheet Excel files)",
        "cli.no_fidelity": "Disable fidelity mode and let pandas infer dtypes",
        "cli.escape_formulas": "Escape cells starting with = + - @ to block Excel formula injection",
        "cli.overwrite": "Existing files: overwrite or index",
        "cli.stream": "Force streaming reads (bounded memory, for huge files)",
        "cli.lang": "Output language",
        "cli.done": "Done: {count} files, {rows} rows, {seconds}s",
        "cli.progress": "Progress {percent}% ({rows} rows, {files} files)",
        "cli.canceled": "Canceled after writing {count} files",
        "cli.files_planned": "{count} files will be created",
        "cli.overwrite_warning": "warning: {count} existing file(s) will be overwritten",
        "cli.log_hint": "log: {path}",
    },
}

SUPPORTED_LANGS: tuple[str, ...] = tuple(LANGUAGES)


def tr(key: str, lang: str = DEFAULT_LANG, **ctx: Any) -> str:
    """按 key 取文案；缺失时回退到中文，再回退到 key 本身。"""
    table = LANGUAGES.get(lang) or LANGUAGES[DEFAULT_LANG]
    template = table.get(key)
    if template is None:
        template = LANGUAGES[DEFAULT_LANG].get(key)
    if template is None:
        return key
    if not ctx:
        return template
    try:
        return template.format(**ctx)
    except (KeyError, IndexError, ValueError):
        # 文案缺参数时不要把异常抛到 UI 上
        return template


def render_error(error: Any, lang: str = DEFAULT_LANG) -> str:
    """把 ``AppError``（或任意异常）渲染成一句话。"""
    from .errors import AppError

    if isinstance(error, AppError):
        return tr(error.key, lang, **error.ctx)
    return str(error)
