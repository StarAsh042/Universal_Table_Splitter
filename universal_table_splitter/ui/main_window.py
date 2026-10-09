"""主窗口。

把数据源、预览、参数、进度四块面板装配起来，并负责调度后台线程。

调度流程（对应 ``core.job`` 的两段式设计）：

    点击"开始分割"
        └─ PreflightWorker（后台）  打开文件、统计行数、算输出文件数与冲突
              └─ 主线程弹确认框（文件过多 / 同名覆盖）
                    └─ SplitWorker（后台）  逐块写出，进度用信号回传
                          └─ 主线程更新进度条 / 收尾

**所有跨线程通信都走 Signal。** 子线程绝不直接读写控件，这是 Qt 里最容易
踩、也最容易出现"随机崩溃"的坑。
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from dataclasses import replace
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import (
    AUTHOR,
    DEFAULT_LANG,
    GITHUB_URL,
    LARGE_JOB_FILE_THRESHOLD,
    MIN_CHUNK_SIZE,
    WINDOW_GEOMETRY,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from ..core.deps import missing_dependencies
from ..core.job import SplitJob, cleanup_files, collect_errors
from ..core.plan import chunk_count, guess_output_dir, parse_chunk_size, parse_num_format
from ..core.readers import (
    export_formats_for,
    is_supported,
    list_sheets,
    supported_extensions,
)
from ..core.writers import ConflictPolicy, export_formats
from ..errors import AppError
from ..i18n import SUPPORTED_LANGS, render_error, tr
from ..settings import Settings
from .preview import PreviewTable, SourceLoader
from .widgets import PathPicker, make_label, make_separator
from .worker import PreflightWorker, SplitWorker

logger = logging.getLogger(__name__)

#: 用户停止输入路径后，等这么久再开始读文件（避免每敲一个字符就打开一次文件）
PREVIEW_DEBOUNCE_MS = 350

_GEOMETRY_PATTERN = re.compile(r"^(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?$")


class UiState(Enum):
    """界面状态。控件可用性完全由它决定，避免各处零散地 setEnabled。"""

    IDLE = auto()
    PREVIEWING = auto()
    SCANNING = auto()
    RUNNING = auto()
    CANCELLING = auto()


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._lang = settings.lang if settings.lang in SUPPORTED_LANGS else DEFAULT_LANG
        self._state = UiState.IDLE

        self._cancel = threading.Event()
        self._preview_cancel = threading.Event()
        self._preview_loader: SourceLoader | None = None
        self._preflight_worker: PreflightWorker | None = None
        self._split_worker: SplitWorker | None = None
        self._active_job: SplitJob | None = None
        self._last_result = None

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._start_preview)

        self._build_ui()
        self._connect_signals()
        self._restore_settings()
        self.retranslate()
        self._refresh_export_formats()
        self._refresh_sheets()
        self._update_plan()
        self._set_state(UiState.IDLE)

        self.setAcceptDrops(True)
        # 依赖自检放在窗口显示之后，否则弹窗会挡在还没画出来的主窗口前面
        QTimer.singleShot(0, self._check_optional_dependencies)

    # ================================================================== 构建

    def _build_ui(self) -> None:
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        layout.addLayout(self._build_header())
        layout.addWidget(make_separator())
        layout.addWidget(self._build_source_group())
        layout.addWidget(self._build_preview_group(), 1)  # 唯一的伸展项：吃掉剩余高度
        layout.addWidget(self._build_params_group())
        layout.addWidget(self._build_progress_group())

        self.setCentralWidget(root)

    def _build_header(self) -> QHBoxLayout:
        self.title_label = make_label("", role="heading")

        self.lang_button = QPushButton()
        self.lang_button.setProperty("role", "ghost")
        self.lang_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_button.clicked.connect(self.toggle_language)

        self.about_button = QPushButton()
        self.about_button.setProperty("role", "ghost")
        self.about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_button.clicked.connect(self.show_about)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.lang_button)
        header.addWidget(self.about_button)
        return header

    def _build_source_group(self) -> QGroupBox:
        self.source_group = QGroupBox()
        filters = " ".join(f"*{ext}" for ext in supported_extensions())

        self.input_picker = PathPicker(file_filter=f"Table files ({filters})")
        self.output_picker = PathPicker(select_dir=True)
        self.output_hint = make_label("", role="muted")
        self.notice_label = make_label("", role="warning")
        self.notice_label.setWordWrap(True)
        self.notice_label.setVisible(False)

        body = QVBoxLayout()
        body.setSpacing(8)
        body.addWidget(self.input_picker)
        body.addWidget(self.output_picker)
        body.addWidget(self.output_hint)
        body.addWidget(self.notice_label)

        self.source_group.setLayout(body)
        return self.source_group

    def _build_preview_group(self) -> QGroupBox:
        self.preview = PreviewTable(self._lang)
        return self.preview

    def _build_params_group(self) -> QGroupBox:
        self.params_group = QGroupBox()

        self.size_edit = QLineEdit()
        self.size_edit.setFixedWidth(110)
        self.size_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.size_edit.setPlaceholderText(str(MIN_CHUNK_SIZE))

        self.format_edit = QLineEdit()
        self.format_edit.setFixedWidth(80)
        self.format_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.format_edit.setPlaceholderText("001")

        self.export_combo = QComboBox()
        self.export_combo.setMaximumWidth(140)
        self.export_combo.currentIndexChanged.connect(self._update_plan)

        self.sheet_combo = QComboBox()
        self.sheet_combo.setMaximumWidth(200)

        self.size_label = make_label()
        self.format_label = make_label()
        self.export_label = make_label()
        self.sheet_label = make_label()
        self.format_hint = make_label("", role="muted")

        self.fidelity_check = QCheckBox()
        self.escape_check = QCheckBox()
        self.plan_label = make_label("", role="value")

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.addWidget(self.size_label, 0, 0)
        grid.addWidget(self.size_edit, 0, 1)
        grid.addWidget(self.format_label, 0, 2)
        grid.addWidget(self.format_edit, 0, 3)
        grid.addWidget(self.export_label, 0, 4)
        grid.addWidget(self.export_combo, 0, 5)
        grid.addWidget(self.sheet_label, 0, 6)
        grid.addWidget(self.sheet_combo, 0, 7)
        grid.setColumnStretch(8, 1)
        grid.addWidget(self.format_hint, 1, 0, 1, 8)
        grid.addWidget(self.fidelity_check, 2, 0, 1, 8)
        grid.addWidget(self.escape_check, 3, 0, 1, 8)
        grid.addWidget(self.plan_label, 4, 0, 1, 8)

        self.params_group.setLayout(grid)
        return self.params_group

    def _build_progress_group(self) -> QGroupBox:
        self.progress_group = QGroupBox()

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.status_label = make_label()
        self.detail_label = make_label("", role="muted")
        self.detail_label.setWordWrap(True)

        self.open_output_button = QPushButton()
        self.open_output_button.setProperty("role", "ghost")
        self.open_output_button.clicked.connect(self.open_output_dir)

        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self.cancel_operation)

        self.start_button = QPushButton()
        self.start_button.setProperty("role", "primary")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self.start_operation)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(self.open_output_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.start_button)

        body = QVBoxLayout()
        body.setSpacing(10)
        body.addWidget(self.progress_bar)
        body.addWidget(self.status_label)
        body.addWidget(self.detail_label)
        body.addLayout(buttons)

        self.progress_group.setLayout(body)
        return self.progress_group

    def _connect_signals(self) -> None:
        self.input_picker.pathChanged.connect(self._on_input_changed)
        self.output_picker.pathChanged.connect(self._on_output_changed)
        self.size_edit.textChanged.connect(self._update_plan)
        self.format_edit.textChanged.connect(self._update_plan)
        self.sheet_combo.currentIndexChanged.connect(self._update_plan)

    # ================================================================== 文案

    def retranslate(self) -> None:
        """按当前语言刷新所有可见文字。"""
        lang = self._lang
        self.setWindowTitle(
            tr("app.title_with_version", lang, title=tr("app.title", lang), version=__version__)
        )
        self.title_label.setText(tr("app.title", lang))
        self.lang_button.setText(tr("btn.lang", lang))
        self.about_button.setText(tr("btn.about", lang))

        self.source_group.setTitle(tr("label.source", lang))
        self.input_picker.set_title(tr("label.input", lang))
        self.input_picker.set_button_text(tr("btn.browse", lang))
        self.input_picker.set_placeholder(tr("btn.input", lang))
        self.output_picker.set_title(tr("label.output", lang))
        self.output_picker.set_button_text(tr("btn.browse", lang))
        self.output_picker.set_placeholder(tr("btn.output", lang))
        self.output_hint.setText(tr("hint.output", lang))

        self.preview.set_language(lang)

        self.params_group.setTitle(tr("label.params", lang))
        self.size_label.setText(tr("label.size", lang))
        self.format_label.setText(tr("label.num_format", lang))
        self.export_label.setText(tr("label.export", lang))
        self.sheet_label.setText(tr("label.sheet", lang))
        self.format_hint.setText(tr("hint.num_format", lang))
        self.fidelity_check.setText(tr("label.fidelity", lang))
        self.escape_check.setText(tr("label.escape_formulas", lang))

        self.progress_group.setTitle(tr("label.progress", lang))
        self.open_output_button.setText(tr("btn.open_output", lang))
        self.cancel_button.setText(tr("btn.cancel", lang))
        self.start_button.setText(tr("btn.start", lang))

        if self._state is UiState.IDLE and not self.detail_label.text():
            self.status_label.setText(tr("status.ready", lang))

        self._update_plan()

    def toggle_language(self) -> None:
        index = SUPPORTED_LANGS.index(self._lang)
        self._lang = SUPPORTED_LANGS[(index + 1) % len(SUPPORTED_LANGS)]
        self.retranslate()

    # ================================================================== 设置

    def _restore_settings(self) -> None:
        self.size_edit.setText(str(self._settings.chunk_size))
        self.format_edit.setText(self._settings.num_format)
        self.fidelity_check.setChecked(bool(self._settings.fidelity))
        self.escape_check.setChecked(bool(self._settings.escape_formulas))
        self.input_picker.set_last_dir(self._settings.last_input_dir)
        self.output_picker.set_last_dir(self._settings.last_output_dir)

        match = _GEOMETRY_PATTERN.match(self._settings.geometry or WINDOW_GEOMETRY)
        if match:
            width, height, x, y = match.groups()
            self.resize(int(width), int(height))
            if x is not None and y is not None:
                self.move(int(x), int(y))

    def _collect_settings(self) -> Settings:
        try:
            chunk_size = parse_chunk_size(self.size_edit.text())
        except AppError:
            chunk_size = self._settings.chunk_size
        geometry = f"{self.width()}x{self.height()}+{self.x()}+{self.y()}"
        return replace(
            self._settings,
            chunk_size=chunk_size,
            num_format=self.format_edit.text().strip() or self._settings.num_format,
            export_format=self._current_export_format() or self._settings.export_format,
            lang=self._lang,
            fidelity=self.fidelity_check.isChecked(),
            escape_formulas=self.escape_check.isChecked(),
            last_input_dir=self._dir_of(self.input_picker.path()) or self._settings.last_input_dir,
            last_output_dir=self.output_picker.path() or self._settings.last_output_dir,
            geometry=geometry,
        )

    @staticmethod
    def _dir_of(raw_path: str) -> str:
        return str(Path(raw_path).parent) if raw_path else ""

    def _save_settings(self) -> None:
        self._settings = self._collect_settings()
        self._settings.save()

    # ================================================================== 数据源

    def _on_input_changed(self, _value: str) -> None:
        self._refresh_export_formats()
        self._refresh_sheets()
        self._preview_timer.start()  # 防抖：等用户停止输入再读文件

    def _on_output_changed(self, _value: str) -> None:
        self._update_plan()

    def _schedule_preview(self) -> None:
        self._preview_timer.start()

    def _current_export_format(self) -> str:
        data = self.export_combo.currentData()
        return str(data) if data else ""

    def _refresh_export_formats(self) -> None:
        """按输入文件类型重建导出格式列表（首项即默认值）。"""
        raw = self.input_picker.path()
        previous = self._current_export_format() or self._settings.export_format
        formats = export_formats_for(Path(raw)) if raw else export_formats()

        blocked = self.export_combo.blockSignals(True)
        try:
            self.export_combo.clear()
            for key in formats:
                self.export_combo.addItem(key.upper(), key)
            index = self.export_combo.findData(previous)
            self.export_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.export_combo.blockSignals(blocked)
        self._update_plan()

    def _refresh_sheets(self) -> None:
        """Excel 输入时列出工作表；其它格式隐藏该下拉框。"""
        raw = self.input_picker.path()
        names: tuple[str, ...] = ()
        if raw and Path(raw).suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
            try:
                names = list_sheets(Path(raw))
            except Exception:  # noqa: BLE001 - 列不出工作表不该阻断主流程
                logger.info("failed to list sheets for %s", raw, exc_info=True)

        blocked = self.sheet_combo.blockSignals(True)
        try:
            self.sheet_combo.clear()
            if names:
                self.sheet_combo.addItem("", None)
                for name in names:
                    self.sheet_combo.addItem(name, name)
        finally:
            self.sheet_combo.blockSignals(blocked)

        visible = bool(names)
        self.sheet_combo.setVisible(visible)
        self.sheet_label.setVisible(visible)

    def _current_sheet(self) -> str | None:
        if not self.sheet_combo.isVisible():
            return None
        data = self.sheet_combo.currentData()
        return str(data) if data else None

    # ================================================================== 预览

    def _start_preview(self) -> None:
        raw = self.input_picker.path()
        if not raw:
            self.preview.show_empty()
            return

        path = Path(raw)
        if not path.is_file() or not is_supported(path):
            self.preview.show_error(render_error(AppError("err.invalid_file"), self._lang))
            return

        self._abort_preview()
        # 每次预览都用独立的中止信号：共用 self._cancel 的话，
        # "切文件"和"取消分割"会互相干扰（一个 clear() 就把另一个的取消请求抹掉了）
        self._preview_cancel = threading.Event()
        self.preview.show_loading()

        self._preview_loader = SourceLoader(path, self._preview_cancel, self)
        self._preview_loader.loaded.connect(self._on_preview_loaded)
        self._preview_loader.failed.connect(self._on_preview_failed)
        self._preview_loader.start()

    def _abort_preview(self) -> None:
        """中止上一次预览读取，并等它真正退出，避免两个线程同时读同一个文件。"""
        if self._preview_loader is None:
            return
        loader, self._preview_loader = self._preview_loader, None
        self._preview_cancel.set()
        if loader.isRunning():
            loader.wait(3000)

    def _on_preview_loaded(self, payload: dict) -> None:
        self.preview.show_data(payload)
        self._update_plan()

    def _on_preview_failed(self, error: AppError) -> None:
        self.preview.show_error(render_error(error, self._lang))

    # ================================================================== 计划

    def _update_plan(self) -> None:
        """实时预估输出文件数。

        行数来自预览结果（已经读过一次文件），所以这里不需要再打开文件。
        """
        payload = self.preview.payload
        total = payload.get("total_rows") if payload else None

        try:
            chunk_size = parse_chunk_size(self.size_edit.text())
        except AppError:
            chunk_size = 0

        if not chunk_size or not isinstance(total, int) or total <= 0:
            self.plan_label.setText(tr("status.plan_unknown", self._lang))
            return
        count = chunk_count(total, chunk_size)
        self.plan_label.setText(tr("status.plan", self._lang, count=f"{count:,}"))

    # ================================================================== 执行

    def _collect_job(self) -> SplitJob:
        raw_input = self.input_picker.path()
        if not raw_input:
            raise AppError("err.invalid_file")
        input_path = Path(raw_input)

        raw_output = self.output_picker.path()
        output_dir = Path(raw_output) if raw_output else guess_output_dir(input_path)

        return SplitJob(
            input_path=input_path,
            output_dir=output_dir,
            chunk_size=parse_chunk_size(self.size_edit.text()),
            digits=parse_num_format(self.format_edit.text()),
            export_format=self._current_export_format(),
            sheet=self._current_sheet(),
            fidelity=self.fidelity_check.isChecked(),
            escape_formulas=self.escape_check.isChecked(),
        )

    def start_operation(self) -> None:
        if self._state is not UiState.IDLE:
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

        self._last_result = None
        self._cancel.clear()
        self.progress_bar.setRange(0, 0)  # 0/0 = 不确定进度的忙碌态
        self.detail_label.clear()
        self.status_label.setText(tr("status.scanning", self._lang))
        self._set_state(UiState.SCANNING)

        self._preflight_worker = PreflightWorker(job, self._cancel, self)
        self._preflight_worker.ready.connect(self._on_preflight_ready)
        self._preflight_worker.failed.connect(self._on_error)
        self._preflight_worker.canceled.connect(self._on_canceled)
        self._preflight_worker.start()

    def _on_preflight_ready(self, report) -> None:
        """预检完成。这里在主线程，可以安全地弹确认框。"""
        job = report.job

        if report.file_count > LARGE_JOB_FILE_THRESHOLD and not self._confirm(
            "large_job",
            count=f"{report.file_count:,}",
            rows=f"{(report.total_rows or 0):,}",
        ):
            report.close()  # 不执行就必须释放文件句柄
            self._on_canceled(None)
            return

        if report.conflicts:
            overwrite = self._confirm("overwrite", count=len(report.conflicts))
            job = replace(
                job,
                conflict_policy=(ConflictPolicy.OVERWRITE if overwrite else ConflictPolicy.INDEX),
            )

        job = replace(job, total_rows=report.total_rows)
        handle, report.handle = report.handle, None  # 所有权转交给 worker
        self._active_job = job

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setText(
            tr("status.running", self._lang, current="0", total=f"{(report.total_rows or 0):,}")
        )
        self._set_state(UiState.RUNNING)

        self._split_worker = SplitWorker(job, self._cancel, handle, self)
        self._split_worker.progress.connect(self._on_progress)
        self._split_worker.succeeded.connect(self._on_done)
        self._split_worker.failed.connect(self._on_error)
        self._split_worker.canceled.connect(self._on_canceled)
        self._split_worker.start()

    def cancel_operation(self) -> None:
        if self._state not in (UiState.SCANNING, UiState.RUNNING):
            return
        self._cancel.set()
        self.status_label.setText(tr("status.canceling", self._lang))
        self._set_state(UiState.CANCELLING)

    # ---------------------------------------------------------------- 回调

    def _on_progress(self, event) -> None:
        total = event.total_rows
        if isinstance(total, int) and total > 0:
            self.progress_bar.setValue(min(100, int(event.rows_written * 100 / total)))
            self.status_label.setText(
                tr(
                    "status.running",
                    self._lang,
                    current=f"{event.rows_written:,}",
                    total=f"{total:,}",
                )
            )
        else:
            self.progress_bar.setRange(0, 0)
            self.status_label.setText(
                tr("status.running_unknown", self._lang, current=f"{event.rows_written:,}")
            )
        self.detail_label.setText(tr("status.writing", self._lang, name=event.path.name))

    def _on_done(self, result) -> None:
        self._last_result = result
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.status_label.setText(tr("status.success", self._lang))
        self.detail_label.setText(
            tr(
                "status.summary",
                self._lang,
                count=len(result.files),
                rows=f"{result.rows:,}",
                seconds=f"{result.elapsed_s:.1f}",
            )
        )
        self._set_state(UiState.IDLE)
        self._save_settings()

    def _on_canceled(self, partial) -> None:
        self._last_result = partial
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setText(tr("status.canceled", self._lang))
        self.detail_label.clear()
        self._set_state(UiState.IDLE)

        if (
            partial is not None
            and partial.files
            and self._confirm("cleanup", count=len(partial.files))
        ):
            cleanup_files(partial.files)

    def _on_error(self, error: AppError) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.detail_label.clear()
        self._set_state(UiState.IDLE)
        self._report_error(error)

    def _report_error(self, error: AppError) -> None:
        message = render_error(error, self._lang)
        self.status_label.setText(tr("status.error", self._lang, message=message))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("app.title", self._lang))
        box.setText(message)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()

    # ---------------------------------------------------------------- 状态

    def _set_state(self, state: UiState) -> None:
        self._state = state
        busy = state is not UiState.IDLE

        self.input_picker.set_enabled(not busy)
        self.output_picker.set_enabled(not busy)
        self.size_edit.setEnabled(not busy)
        self.format_edit.setEnabled(not busy)
        self.export_combo.setEnabled(not busy)
        self.sheet_combo.setEnabled(not busy)
        self.fidelity_check.setEnabled(not busy)
        self.escape_check.setEnabled(not busy)

        self.start_button.setEnabled(state is UiState.IDLE)
        self.cancel_button.setEnabled(state in (UiState.SCANNING, UiState.RUNNING))
        self.cancel_button.setVisible(state is not UiState.IDLE)
        self.open_output_button.setVisible(not busy)

    # ---------------------------------------------------------------- 确认框

    def _confirm(self, kind: str, **ctx) -> bool:
        """弹出双按钮确认框，返回用户是否选择了"是"。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr(f"confirm.{kind}.title", self._lang))
        box.setText(tr(f"confirm.{kind}.body", self._lang, **ctx))
        yes = box.addButton(
            tr(f"confirm.{kind}.yes", self._lang), QMessageBox.ButtonRole.AcceptRole
        )
        no = box.addButton(tr(f"confirm.{kind}.no", self._lang), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no)
        box.exec()
        return box.clickedButton() is yes

    # ================================================================== 其它

    def _check_optional_dependencies(self) -> None:
        """缺少可选依赖时在窗口内提示，而不是弹一个必须点掉的对话框。

        缺 xlrd 只是读不了 .xls，为这点事在启动时弹模态框打断流程不划算，
        放在界面上让用户自己决定要不要管。
        """
        missing = missing_dependencies()
        if not missing:
            self.notice_label.setVisible(False)
            return
        names = "、".join(tr(dep.feature_key, self._lang) for dep in missing)
        body = tr("info.deps_missing.body", self._lang, names=names)
        self.notice_label.setText(" ".join(body.split("\n")))
        self.notice_label.setVisible(True)

    def open_output_dir(self) -> None:
        """在系统文件管理器里打开输出目录。

        优先用结果里的真实输出目录（用户可能没填输出目录，实际落在输入文件旁边）。
        """
        target: Path | None = None
        if self._last_result is not None and self._last_result.files:
            target = self._last_result.files[0].parent
        elif self._active_job is not None:
            target = self._active_job.output_dir
        else:
            raw = self.output_picker.path()
            target = Path(raw) if raw else None

        if target is None or not target.exists():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def show_about(self) -> None:
        lang = self._lang
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("about.title", lang))
        box.setText(
            "\n".join(
                [
                    tr("app.title", lang),
                    tr("about.version", lang, version=__version__),
                    tr("about.author", lang, author=AUTHOR),
                    tr("about.license", lang),
                    tr("about.runtime", lang, python=_python_version(), pandas=_pandas_version()),
                    "",
                    tr("about.usage", lang),
                    tr("about.step1", lang),
                    tr("about.step2", lang),
                    tr("about.step3", lang),
                    "",
                    f"{tr('about.github', lang)}{GITHUB_URL}",
                ]
            )
        )
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()

    # ---------------------------------------------------------------- 拖放

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._state is not UiState.IDLE:
            return
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and is_supported(path):
                self.input_picker.set_path(str(path))
                self._refresh_export_formats()
                self._refresh_sheets()
                self._schedule_preview()
                event.acceptProposedAction()
                return

    # ---------------------------------------------------------------- 关闭

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._state is not UiState.IDLE:
            if not self._confirm("close"):
                event.ignore()
                return
            self._cancel.set()

        self._preview_timer.stop()
        self._abort_preview()
        for worker in (self._preflight_worker, self._split_worker):
            if worker is not None and worker.isRunning():
                worker.wait(3000)

        self._save_settings()
        event.accept()


def _python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _pandas_version() -> str:
    try:
        import pandas

        return pandas.__version__
    except Exception:  # pragma: no cover - pandas 是硬依赖，正常不会失败
        return "?"


__all__ = ["MainWindow", "UiState"]
