"""Tk 主界面。

与原实现的关键差异：
- **真实取消**：``threading.Event`` 贯穿预检与分块循环，取消后不再写任何文件；
- **禁止重入**：同一时刻只允许一个工作线程，杜绝并发写同一批文件；
- **参数与状态机**：``AppState`` 显式建模，不再用 ``hasattr(self, 'running')`` 打补丁；
- **控件引用**：所有需要在切换语言时更新的控件都持有引用；
- **状态文案可重渲染**：运行中切换语言不会丢失进度文本；
- **后台完成 I/O 与确认**：预检在子线程执行，界面不会因为统计大文件行数而假死；
- **结果可追溯**：完成后给出摘要并可一键打开输出目录。
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import replace
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .. import __version__
from ..config import (
    AUTHOR,
    CONFIRM_TIMEOUT_S,
    DEFAULT_LANG,
    GITHUB_URL,
    LARGE_JOB_FILE_THRESHOLD,
    QUEUE_POLL_MS,
    WINDOW_GEOMETRY,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from ..core.deps import missing_dependencies
from ..core.job import (
    SplitJob,
    SplitResult,
    cleanup_files,
    collect_errors,
    preflight,
    run_split,
)
from ..core.plan import guess_output_dir, parse_chunk_size, parse_num_format
from ..core.readers import (
    export_formats_for,
    is_supported,
    list_sheets,
    supported_extensions,
)
from ..core.writers import ConflictPolicy, export_formats
from ..errors import AppError, CanceledByUser
from ..i18n import LANGUAGES, render_error, tr
from ..logging_setup import log_file_path, setup_logging
from ..settings import Settings
from .theme import (
    accent_color,
    apply_bootstyle,
    create_style,
    detect_dark_mode,
    disable_ttkbootstrap,
    enable_dpi_awareness,
    styled,
)
from .widgets import build_file_selector, parse_drop_paths

logger = logging.getLogger(__name__)

EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xls"}


class AppState(Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    RUNNING = "running"
    CANCELLING = "cancelling"


class _ConfirmRequest:
    """工作线程向界面线程发起的提问；界面回答后放行。"""

    def __init__(self, kind: str, **ctx: Any) -> None:
        self.kind = kind
        self.ctx = ctx
        self.answer: bool | None = None
        self._event = threading.Event()

    def resolve(self, answer: bool) -> None:
        self.answer = answer
        self._event.set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


class UniversalSplitterApp:
    def __init__(
        self,
        root: tk.Misc,
        settings: Settings | None = None,
        dnd_enabled: bool = True,
    ) -> None:
        self.root = root
        self.settings = settings or Settings.load()
        self.lang = self.settings.lang if self.settings.lang in LANGUAGES else DEFAULT_LANG
        self.state = AppState.IDLE

        self.events: Queue[tuple[str, Any]] = Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.pending_confirm: _ConfirmRequest | None = None
        self.last_result: SplitResult | None = None
        self.output_is_auto = not bool(self.settings.last_output_dir)
        self.closing = False
        self.about_window: tk.Toplevel | None = None

        self._status_key = "status.ready"
        self._status_ctx: dict[str, Any] = {}

        self.style = create_style(root, detect_dark_mode())

        self._init_vars()
        self._build_ui()
        self._refresh_texts()
        self._apply_state(AppState.IDLE)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(QUEUE_POLL_MS, self._poll_events)

        if dnd_enabled:
            self._setup_dnd()
        else:
            self.root.after(200, self._notify_dnd_missing)
        self._check_optional_dependencies()

    # ------------------------------------------------------------------ 变量
    def _init_vars(self) -> None:
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value=self.settings.last_output_dir)
        self.size_var = tk.StringVar(value=str(self.settings.chunk_size))
        self.format_var = tk.StringVar(value=self.settings.num_format)
        self.export_var = tk.StringVar(value=self.settings.export_format)
        self.sheet_var = tk.StringVar()
        self.fidelity_var = tk.BooleanVar(value=self.settings.fidelity)
        self.escape_var = tk.BooleanVar(value=self.settings.escape_formulas)
        self.status_var = tk.StringVar()

    # -------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self._apply_geometry()
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)

        self.input_selector = build_file_selector(
            container, tr("btn.input"), self.choose_input, entry_state="readonly"
        )
        self.input_selector.entry.configure(textvariable=self.input_var)

        self.output_selector = build_file_selector(container, tr("btn.output"), self.choose_output)
        self.output_selector.entry.configure(textvariable=self.output_var)

        self.params_frame = ttk.LabelFrame(container, padding=10)
        self.params_frame.pack(fill="x", pady=(12, 6))
        params = self.params_frame
        params.columnconfigure(1, weight=1)
        params.columnconfigure(3, weight=1)

        self.size_label = ttk.Label(params)
        self.size_label.grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        self.size_entry = ttk.Entry(params, textvariable=self.size_var, width=12)
        self.size_entry.grid(row=0, column=1, sticky="ew", pady=4)

        self.format_label = ttk.Label(params)
        self.format_label.grid(row=0, column=2, sticky="w", padx=(16, 6), pady=4)
        self.format_entry = ttk.Entry(params, textvariable=self.format_var, width=12)
        self.format_entry.grid(row=0, column=3, sticky="ew", pady=4)

        self.export_label = ttk.Label(params)
        self.export_label.grid(row=1, column=0, sticky="w", padx=(0, 6), pady=4)
        self.export_combo = ttk.Combobox(
            params,
            textvariable=self.export_var,
            values=list(export_formats()),
            state="readonly",
            width=10,
        )
        self.export_combo.grid(row=1, column=1, sticky="ew", pady=4)

        self.sheet_label = ttk.Label(params)
        self.sheet_label.grid(row=1, column=2, sticky="w", padx=(16, 6), pady=4)
        self.sheet_combo = ttk.Combobox(
            params, textvariable=self.sheet_var, state="readonly", width=10
        )
        self.sheet_combo.grid(row=1, column=3, sticky="ew", pady=4)
        self.sheet_combo.grid_remove()
        self.sheet_label.grid_remove()

        self.format_hint = styled(ttk.Label, "secondary", master=params)
        self.format_hint.grid(row=2, column=0, columnspan=4, sticky="w", pady=(0, 2))

        # round-toggle 依赖 ttkbootstrap 用图片绘制的开关控件，在打包环境里可能注册失败；
        # 因此给出候选链：圆形开关 -> 平面工具按钮样式 -> 原生勾选框
        self.fidelity_check = styled(
            ttk.Checkbutton,
            "round-toggle|toolbutton",
            master=params,
            variable=self.fidelity_var,
        )
        self.fidelity_check.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.escape_check = styled(
            ttk.Checkbutton,
            "round-toggle|toolbutton",
            master=params,
            variable=self.escape_var,
        )
        self.escape_check.grid(row=4, column=0, columnspan=4, sticky="w")

        # 识别结果常驻展示（编码/行数/工作表），不会被进度文本覆盖
        self.info_label = styled(ttk.Label, "secondary", master=params)
        self.info_label.grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))

        self.progress = styled(
            ttk.Progressbar,
            "success",
            master=container,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            value=0,
        )
        self.progress.pack(fill="x", pady=(12, 4))
        self.status_label = ttk.Label(
            container, textvariable=self.status_var, anchor="w", justify="left"
        )
        self.status_label.pack(fill="x")

        actions = ttk.Frame(container)
        actions.pack(fill="x", pady=(12, 0))
        # 主按钮用彩色强调（沿用 1.0 的"绿色开始按钮"观感），运行中切换为危险色
        self.primary_btn = styled(
            ttk.Button, "success", master=actions, command=self.on_primary, width=16
        )
        self.primary_btn.pack(side="left")
        self.open_btn = styled(
            ttk.Button,
            "secondary-outline",
            master=actions,
            command=self.open_output_dir,
            state="disabled",
            width=16,
        )
        self.open_btn.pack(side="left", padx=(8, 0))

        bottom = ttk.Frame(container)
        bottom.pack(fill="x", side="bottom", pady=(16, 0))
        self.lang_btn = styled(ttk.Button, "link", master=bottom, command=self.toggle_language)
        self.lang_btn.pack(side="left")
        self.about_btn = styled(ttk.Button, "link", master=bottom, command=self.show_about)
        self.about_btn.pack(side="right")

        self._controls = (
            self.size_entry,
            self.format_entry,
            self.export_combo,
            self.sheet_combo,
            self.fidelity_check,
            self.escape_check,
        )

    def _refresh_texts(self) -> None:
        lang = self.lang
        # 标题栏带版本号：版本取自包内 __version__，与 pyproject 动态版本同源，
        # 因此从源码运行和打包成 exe 运行显示的版本完全一致
        self.root.title(
            tr(
                "app.title_with_version",
                lang,
                title=tr("app.title", lang),
                version=__version__,
            )
        )
        self.params_frame.configure(text=tr("label.params", lang))
        self.input_selector.set_button_text(tr("btn.input", lang))
        self.output_selector.set_button_text(tr("btn.output", lang))
        self.size_label.configure(text=tr("label.size", lang))
        self.format_label.configure(text=tr("label.num_format", lang))
        self.export_label.configure(text=tr("label.export", lang))
        self.sheet_label.configure(text=tr("label.sheet", lang))
        self.format_hint.configure(text=tr("hint.num_format", lang))
        self.fidelity_check.configure(text=tr("label.fidelity", lang))
        self.escape_check.configure(text=tr("label.escape_formulas", lang))
        self.open_btn.configure(text=tr("btn.open_output", lang))
        self.lang_btn.configure(text=tr("btn.lang", lang))
        self.about_btn.configure(text=tr("btn.about", lang))
        # 状态栏按"当前状态的 key"重渲染，因此运行中切换语言不会丢失进度
        self.status_var.set(tr(self._status_key, lang, **self._status_ctx))
        self._apply_state(self.state)

    def _set_status(self, key: str, **ctx: Any) -> None:
        self._status_key = key
        self._status_ctx = ctx
        self.status_var.set(tr(key, self.lang, **ctx))

    def _apply_state(self, state: AppState) -> None:
        self.state = state
        running = state in (AppState.SCANNING, AppState.RUNNING)
        if state is AppState.IDLE:
            self.primary_btn.configure(text=tr("btn.start", self.lang), state="normal")
            apply_bootstyle(self.primary_btn, "success")
        elif state is AppState.CANCELLING:
            self.primary_btn.configure(text=tr("btn.cancel", self.lang), state="disabled")
            apply_bootstyle(self.primary_btn, "danger")
        else:
            self.primary_btn.configure(text=tr("btn.cancel", self.lang), state="normal")
            apply_bootstyle(self.primary_btn, "danger")

        editable = not running and state is not AppState.CANCELLING
        for widget in self._controls:
            if not editable:
                widget.configure(state="disabled")
            elif widget in (self.export_combo, self.sheet_combo):
                widget.configure(state="readonly")
            else:
                widget.configure(state="normal")
        self.input_selector.set_enabled(editable)
        self.output_selector.set_enabled(editable)
        self.open_btn.configure(state="normal" if self._output_exists() else "disabled")
        if state is AppState.IDLE:
            self._freeze_progress()

    def _freeze_progress(self) -> None:
        """停止动画并切回确定型进度条，同时保留当前值（切换 mode 会重置 value）。"""
        try:
            current = float(self.progress["value"])
        except (TypeError, ValueError):  # pragma: no cover
            current = 0.0
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress["value"] = current

    def _output_exists(self) -> bool:
        raw = self.output_var.get().strip()
        return bool(raw) and Path(raw).is_dir()

    def _apply_geometry(self) -> None:
        """沿用上次的窗口尺寸，但始终居中，避免还原到屏幕外。"""
        stored = (self.settings.geometry or WINDOW_GEOMETRY).split("+")[0]
        try:
            width, height = (int(part) for part in stored.lower().split("x")[:2])
        except ValueError:
            width, height = 820, 600
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 3, 0)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

    # ---------------------------------------------------------------- 输入
    def choose_input(self) -> None:
        initial = self.settings.last_input_dir
        patterns = " ".join(f"*{ext}" for ext in supported_extensions())
        path = filedialog.askopenfilename(
            title=tr("btn.input", self.lang),
            initialdir=initial if initial and Path(initial).is_dir() else None,
            filetypes=[
                ("All Supported Files", patterns),
                ("CSV Files", "*.csv"),
                ("Excel Files", "*.xlsx *.xls *.xlsm"),
                ("TSV Files", "*.tsv"),
                ("JSON Files", "*.json *.jsonl"),
            ],
        )
        if path:
            self._apply_input_file(Path(path))

    def choose_output(self) -> None:
        path = filedialog.askdirectory(
            title=tr("btn.output", self.lang),
            initialdir=self.output_var.get() or None,
        )
        if path:
            self._set_output_dir(Path(path), auto=False)

    def _set_output_dir(self, path: Path, auto: bool) -> None:
        self.output_var.set(str(path))
        self.output_is_auto = auto

    def _apply_input_file(self, path: Path) -> None:
        """选择/拖入文件后的统一入口（原先在 choose_input 与 handle_drop 中重复实现）。"""
        if not path.is_file():
            self._report_error(AppError("err.not_a_file", path=str(path)))
            return
        if not is_supported(path):
            self._report_error(AppError("err.invalid_file"))
            return
        self.input_var.set(str(path))
        self.settings.last_input_dir = str(path.parent)
        if self.output_is_auto or not self.output_var.get().strip():
            self._set_output_dir(guess_output_dir(path), auto=True)
        self._refresh_export_formats(path)
        self._refresh_sheets(path)
        if self.state is AppState.IDLE:
            self._set_status("status.ready")

    def _refresh_export_formats(self, path: Path) -> None:
        formats = export_formats_for(path)
        self.export_combo.configure(values=list(formats))
        if self.export_var.get() not in formats:
            self.export_var.set(formats[0])

    def _refresh_sheets(self, path: Path) -> None:
        sheets: tuple[str, ...] = ()
        if path.suffix.lower() in EXCEL_SUFFIXES:
            sheets = list_sheets(path)
        if len(sheets) > 1:
            self.sheet_combo.configure(values=list(sheets))
            self.sheet_var.set(sheets[0])
            self.sheet_combo.grid()
            self.sheet_label.grid()
        else:
            self.sheet_var.set(sheets[0] if sheets else "")
            self.sheet_combo.grid_remove()
            self.sheet_label.grid_remove()

    # ---------------------------------------------------------------- 拖放
    def _setup_dnd(self) -> None:
        try:
            from tkinterdnd2 import DND_FILES

            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self.handle_drop)
        except Exception:
            logger.warning("drag and drop unavailable", exc_info=True)
            self.root.after(200, self._notify_dnd_missing)

    def handle_drop(self, event: Any) -> None:
        raw = getattr(event, "data", "") or ""
        paths = [Path(item) for item in parse_drop_paths(raw)]
        if not paths:
            logger.warning("cannot parse drop payload %r", raw)
            return
        target = paths[0]
        if target.is_dir():
            # 拖入文件夹时直接作为输出目录
            self._set_output_dir(target, auto=False)
            return
        self._apply_input_file(target)

    def _notify_dnd_missing(self) -> None:
        # 必须显式传 parent：ttkbootstrap 的对话框在 parent=None 时会额外创建一个
        # 可见的空 "tk" 窗口（已实测），传了 parent 就不会。
        messagebox.showinfo(
            tr("info.empty.title", self.lang),
            tr("info.dnd_missing.body", self.lang),
            parent=self.root,
        )

    def _check_optional_dependencies(self) -> None:
        # tkinterdnd2 有专门的提示，避免重复弹窗
        missing = [
            dep
            for dep in missing_dependencies()
            if not dep.required and dep.module != "tkinterdnd2"
        ]
        if not missing:
            return
        names = "\n".join(f"· {tr(dep.feature_key, self.lang)}" for dep in missing)
        self.root.after(
            400,
            lambda: messagebox.showinfo(
                tr("info.deps_missing.title", self.lang),
                tr("info.deps_missing.body", self.lang, names=names),
                parent=self.root,
            ),
        )

    # ---------------------------------------------------------------- 任务
    def on_primary(self) -> None:
        if self.state is AppState.RUNNING or self.state is AppState.SCANNING:
            self.cancel_operation()
        elif self.state is AppState.CANCELLING:
            return
        else:
            self.start_operation()

    def _collect_job(self) -> SplitJob:
        input_path = Path(self.input_var.get().strip())
        raw_output = self.output_var.get().strip()
        output_dir = Path(raw_output) if raw_output else guess_output_dir(input_path)
        return SplitJob(
            input_path=input_path,
            output_dir=output_dir,
            chunk_size=parse_chunk_size(self.size_var.get()),
            digits=parse_num_format(self.format_var.get()),
            export_format=self.export_var.get(),
            sheet=self.sheet_var.get().strip() or None,
            fidelity=bool(self.fidelity_var.get()),
            escape_formulas=bool(self.escape_var.get()),
        )

    def start_operation(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self._report_error(AppError("err.task_running"))
            return
        try:
            job = self._collect_job()
        except AppError as exc:
            self._report_error(exc)
            return
        errors = collect_errors(job)
        if errors:
            self._report_error(errors[0])
            return

        self.last_result = None
        self.cancel_event.clear()
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.info_label.configure(text="")
        self._set_status("status.scanning")
        self._apply_state(AppState.SCANNING)
        self.worker = threading.Thread(
            target=self._worker_main, args=(job,), name="splitter", daemon=True
        )
        self.worker.start()

    def cancel_operation(self) -> None:
        if self.state in (AppState.SCANNING, AppState.RUNNING):
            self.cancel_event.set()
            self._set_status("status.canceling")
            self._apply_state(AppState.CANCELLING)

    def _worker_main(self, job: SplitJob) -> None:
        """全部耗时工作都在这里；通过队列单向通知界面。"""
        try:
            report = preflight(job, cancel=self.cancel_event)
        except CanceledByUser as exc:
            self._post("canceled", exc.partial)
            return
        except AppError as exc:
            self._post("error", exc)
            return
        except Exception as exc:
            logger.exception("preflight failed")
            self._post("error", self._unexpected(exc))
            return

        self._post("source", report.source)

        if report.file_count > LARGE_JOB_FILE_THRESHOLD and not self._ask(
            "large_job",
            count=report.file_count,
            rows=f"{report.total_rows or 0:,}",
        ):
            report.close()
            self._post("canceled", None)
            return

        if report.conflicts:
            overwrite = self._ask("overwrite", count=len(report.conflicts))
            job = replace(
                job,
                conflict_policy=(ConflictPolicy.OVERWRITE if overwrite else ConflictPolicy.INDEX),
            )

        job = replace(job, total_rows=report.total_rows)
        handle, report.handle = report.handle, None
        try:
            result = run_split(
                job,
                on_progress=lambda event: self._post("progress", event),
                cancel=self.cancel_event,
                source=handle,
            )
        except CanceledByUser as exc:
            self._post("canceled", exc.partial)
            return
        except AppError as exc:
            self._post("error", exc)
            return
        except Exception as exc:
            logger.exception("split failed")
            self._post("error", self._unexpected(exc))
            return
        self._post("done", result)

    def _ask(self, kind: str, **ctx: Any) -> bool:
        request = _ConfirmRequest(kind, **ctx)
        self.pending_confirm = request
        self._post("confirm", request)
        if not request.wait(CONFIRM_TIMEOUT_S):
            logger.warning("confirmation timed out for %s", kind)
            return False
        self.pending_confirm = None
        return bool(request.answer)

    def _post(self, kind: str, payload: Any) -> None:
        self.events.put((kind, payload))

    # ------------------------------------------------------------ 事件循环
    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle_event(kind, payload)
        except Empty:
            pass
        except Exception:
            logger.exception("failed to handle UI event")
        finally:
            # 用 finally 保证轮询一定被续期（原实现在异常后永久停止刷新）
            if not self.closing:
                self.root.after(QUEUE_POLL_MS, self._poll_events)

    def _handle_event(self, kind: str, payload: Any) -> None:
        if kind == "progress":
            self._on_progress(payload)
        elif kind == "source":
            self._on_source(payload)
        elif kind == "confirm":
            self._on_confirm(payload)
        elif kind == "done":
            self._on_done(payload)
        elif kind == "canceled":
            self._on_canceled(payload)
        elif kind == "error":
            self._on_error(payload)

    def _on_source(self, source: Any) -> None:
        """把识别结果写进常驻信息栏（不占用状态栏，也不会被进度覆盖）。"""
        rows = getattr(source, "total_rows", None)
        encoding = getattr(source, "encoding", None)
        if encoding:
            text = tr(
                "status.detected",
                self.lang,
                encoding=encoding,
                rows=f"{rows:,}" if rows else "-",
            )
        elif rows:
            text = tr("status.detected_rows", self.lang, rows=f"{rows:,}")
        else:
            text = ""
        self.info_label.configure(text=text)

    def _on_progress(self, event: Any) -> None:
        if self.state is AppState.SCANNING:
            self._apply_state(AppState.RUNNING)
        total = event.total_rows
        if total:
            percent = min(int(event.rows_written * 100 / total), 100)
            self.progress.configure(mode="determinate", value=percent)
            self._set_status(
                "status.running",
                current=f"{event.rows_written:,}",
                total=f"{total:,}",
            )
        else:
            if str(self.progress.cget("mode")) != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start(60)
            self._set_status("status.running_unknown", current=f"{event.rows_written:,}")

    def _on_confirm(self, request: _ConfirmRequest) -> None:
        if request.kind == "large_job":
            answer = messagebox.askyesno(
                tr("confirm.large_job.title", self.lang),
                tr("confirm.large_job.body", self.lang, **request.ctx),
                parent=self.root,
            )
        elif request.kind == "overwrite":
            answer = messagebox.askyesno(
                tr("confirm.overwrite.title", self.lang),
                tr("confirm.overwrite.body", self.lang, **request.ctx),
                parent=self.root,
            )
        else:  # pragma: no cover - 未知提问类型时保守放行
            answer = True
        request.resolve(bool(answer))

    def _on_done(self, result: SplitResult) -> None:
        self.last_result = result
        self._apply_state(AppState.IDLE)
        self.progress["value"] = 100  # 完成后明确停在 100%，给用户"结束了"的反馈
        self._set_status(
            "status.summary",
            count=len(result.files),
            rows=f"{result.rows:,}",
            seconds=f"{result.elapsed_s:.1f}",
        )
        messagebox.showinfo(
            tr("summary.title", self.lang),
            tr(
                "summary.body",
                self.lang,
                count=len(result.files),
                rows=f"{result.rows:,}",
                dir=str(result.files[0].parent) if result.files else "-",
                seconds=f"{result.elapsed_s:.1f}",
            ),
            parent=self.root,
        )
        self._save_settings()

    def _on_canceled(self, partial: SplitResult | None) -> None:
        self._apply_state(AppState.IDLE)
        self._set_status("status.canceled")
        if partial and partial.files:
            remove = messagebox.askyesno(
                tr("confirm.cleanup.title", self.lang),
                tr("confirm.cleanup.body", self.lang, count=len(partial.files)),
                parent=self.root,
            )
            if remove:
                cleanup_files(partial.files)

    def _on_error(self, error: AppError) -> None:
        self._apply_state(AppState.IDLE)
        self._report_error(error)

    def _report_error(self, error: AppError) -> None:
        message = render_error(error, self.lang)
        self._set_status("status.error", message=message.splitlines()[0])
        messagebox.showerror(tr("app.title", self.lang), message, parent=self.root)

    def _unexpected(self, exc: BaseException) -> AppError:
        # 完整堆栈进日志，用户只看到一句可操作的话
        logger.exception("unexpected failure: %s", exc)
        return AppError("err.unexpected", path=str(log_file_path()))

    # ---------------------------------------------------------------- 其他
    def open_output_dir(self) -> None:
        raw = self.output_var.get().strip()
        path = Path(raw) if raw else None
        if path is None or not path.exists():
            self._report_error(AppError("err.output_not_dir", path=str(path)))
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            logger.warning("cannot open output dir", exc_info=True)
            self._report_error(AppError("err.read_failed", message=str(exc)))

    def toggle_language(self) -> None:
        self.lang = "en" if self.lang == "cn" else "cn"
        self.settings.lang = self.lang
        self._refresh_texts()
        if self.about_window is not None and self.about_window.winfo_exists():
            self.about_window.destroy()
            self.about_window = None
            self.show_about()

    def show_about(self) -> None:
        if self.about_window is not None and self.about_window.winfo_exists():
            self.about_window.lift()
            self.about_window.focus_force()
            return
        self.about_window = tk.Toplevel(self.root)
        window = self.about_window
        window.title(tr("about.title", self.lang))
        window.transient(self.root)
        window.resizable(False, False)
        window.geometry(
            f"+{self.root.winfo_x() + self.root.winfo_width() + 12}+{self.root.winfo_y()}"
        )

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        lines = [
            tr("about.version", self.lang, version=__version__),
            tr("about.author", self.lang, author=AUTHOR),
            tr("about.license", self.lang),
            tr("about.runtime", self.lang, python=_python_version(), pandas=_pandas_version()),
            "",
            tr("about.usage", self.lang),
            tr("about.step1", self.lang),
            tr("about.step2", self.lang),
            tr("about.step3", self.lang),
        ]
        for line in lines:
            ttk.Label(frame, text=line).pack(anchor="w")

        link_row = ttk.Frame(frame)
        link_row.pack(anchor="w", pady=(6, 0))
        ttk.Label(link_row, text=tr("about.github", self.lang)).pack(side="left")
        link = ttk.Label(
            link_row, text=GITHUB_URL, cursor="hand2", foreground=accent_color(self.style)
        )
        link.pack(side="left")
        link.bind("<Button-1>", lambda _event: self._open_url(GITHUB_URL))

        styled(
            ttk.Button,
            "secondary-outline",
            master=frame,
            text=tr("about.title", self.lang),
            command=self._close_about,
        ).pack(anchor="e", pady=(14, 0))

        window.protocol("WM_DELETE_WINDOW", self._close_about)

    def _close_about(self) -> None:
        if self.about_window is not None:
            self.about_window.destroy()
            self.about_window = None

    def _open_url(self, url: str) -> None:
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception:  # pragma: no cover
            logger.warning("cannot open %s", url, exc_info=True)

    def _save_settings(self) -> None:
        # 只保存"仍然合法"的参数，避免把非法输入记忆下来导致下次启动即报错
        with contextlib.suppress(AppError):
            self.settings.chunk_size = parse_chunk_size(self.size_var.get())
        raw_format = self.format_var.get().strip()
        with contextlib.suppress(AppError):
            parse_num_format(raw_format)
            self.settings.num_format = raw_format
        self.settings.export_format = self.export_var.get()
        self.settings.lang = self.lang
        self.settings.fidelity = bool(self.fidelity_var.get())
        self.settings.escape_formulas = bool(self.escape_var.get())
        self.settings.last_output_dir = self.output_var.get().strip()
        with contextlib.suppress(tk.TclError):
            self.settings.geometry = self.root.geometry()
        self.settings.save()

    def on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askyesno(
                tr("confirm.close.title", self.lang),
                tr("confirm.close.body", self.lang),
                parent=self.root,
            ):
                return
            self.cancel_event.set()
            if self.pending_confirm is not None:
                self.pending_confirm.resolve(False)
            self.worker.join(timeout=5.0)
        self.closing = True
        self._save_settings()
        self.root.destroy()


def _python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _pandas_version() -> str:
    try:
        import pandas

        return pandas.__version__
    except Exception:  # pragma: no cover
        return "?"


def release_partial_root(previous: tk.Misc | None) -> None:
    """销毁创建根窗口过程中多出来的半成品窗口。

    ``TkinterDnD.Tk()`` 会先建好窗口、再去加载 tkdnd 运行库；一旦加载失败
    （运行库缺失、Tcl 版本不匹配等），异常抛出时窗口已经存在了，用户会看到一个
    空白的 "tk" 窗口。这里对比创建前后的默认 root，把多出来的那个销毁掉。
    """
    current = getattr(tk, "_default_root", None)
    if current is not None and current is not previous:
        with contextlib.suppress(Exception):
            current.destroy()


def create_root() -> tuple[tk.Misc, bool]:
    """优先创建支持拖放的根窗口；tkinterdnd2 缺失或初始化失败时退化为普通窗口。"""
    previous = getattr(tk, "_default_root", None)
    try:
        from tkinterdnd2 import TkinterDnD

        return TkinterDnD.Tk(), True
    except Exception:
        logger.info("tkinterdnd2 unavailable, drag and drop disabled", exc_info=True)
        release_partial_root(previous)
        return tk.Tk(), False


def _build_app(root: tk.Misc, dnd_enabled: bool) -> UniversalSplitterApp:
    return UniversalSplitterApp(root, dnd_enabled=dnd_enabled)


def main() -> int:
    # DPI 感知必须在创建窗口之前设置
    enable_dpi_awareness()
    setup_logging()
    logger.info("starting %s v%s", "Universal Table Splitter", __version__)
    root, dnd_enabled = create_root()

    try:
        _build_app(root, dnd_enabled)
    except Exception:
        # 兜底：某些环境下（例如打包后自定义主题、缺失样式资源）ttkbootstrap
        # 会导致界面构建失败。界面美化属于增强项，这里禁用它后重建一次，
        # 保证用户至少能拿到可用的原生 ttk 界面，而不是一个打不开的程序。
        logger.exception("使用 ttkbootstrap 构建界面失败，尝试退回原生 ttk 重建")
        disable_ttkbootstrap("首次构建界面失败")
        with contextlib.suppress(tk.TclError):
            root.destroy()
        root, dnd_enabled = create_root()
        try:
            _build_app(root, dnd_enabled)
        except Exception:
            logger.exception("failed to build the interface")
            with contextlib.suppress(tk.TclError):
                messagebox.showerror(
                    "Universal Table Splitter",
                    tr("err.unexpected", DEFAULT_LANG, path=log_file_path()),
                    parent=root,
                )
                root.destroy()
            return 1

    root.mainloop()
    return 0
