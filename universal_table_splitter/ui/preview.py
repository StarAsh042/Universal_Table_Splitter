"""文件预览区。

旧界面选完文件后是一片空白，用户只能靠文件名猜自己选对没有。这里补上
"编码 / 总行数 / 列名 / 前若干行内容"，让选文件这件事变得可确认。

两个关键取舍：

1. **只在后台线程打开文件。** ``open_table`` 对小于 64 MB 的 CSV/TSV 会整表载入
   （见 ``core/readers.py`` 的 ``STREAM_READ_THRESHOLD_BYTES``），30 MB 的样本
   要花一两秒。放在界面线程里就是一次卡死。
2. **只取第一块，不遍历全表。** ``iter_chunks(PREVIEW_ROWS)`` 在流式模式下
   是真正的分块读，拿到第一块就 ``close()``，不会为了预览把整份数据读一遍。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.readers import ReadOptions, open_table
from ..errors import AppError, CanceledByUser
from ..i18n import tr
from .widgets import make_label

logger = logging.getLogger(__name__)

#: 预览展示的行数
PREVIEW_ROWS = 20
#: 预览最多展示的列数（宽表只显示前几列，避免横向滚动条拉不完）
PREVIEW_MAX_COLUMNS = 12
#: 单个单元格最多展示的字符数
CELL_MAX_CHARS = 120


class SourceLoader(QThread):
    """后台读取文件元信息与前若干行。

    发出的 ``loaded`` 携带一个普通 dict（不是数据源对象），
    因此接收方不需要关心文件句柄的释放——句柄在本线程内就已经关掉了。
    """

    #: 读取成功，携带预览数据 dict
    loaded = Signal(object)
    #: 读取失败，携带 AppError
    failed = Signal(object)
    #: 用户切走了文件，本次读取作废
    canceled = Signal()

    def __init__(self, path: Path, cancel: threading.Event, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._cancel = cancel

    def run(self) -> None:  # noqa: D102 - QThread 入口
        try:
            payload = self._load()
        except CanceledByUser:
            self.canceled.emit()
        except AppError as exc:
            self.failed.emit(exc)
        except BaseException as exc:  # noqa: BLE001 - 线程里必须兜住一切
            logger.exception("preview failed for %s", self._path)
            self.failed.emit(AppError("err.read_failed", message=str(exc)))
        else:
            self.loaded.emit(payload)

    def _load(self) -> dict:
        source = open_table(self._path, ReadOptions(fidelity=True), self._cancel)
        try:
            info = source.info
            frame = next(iter(source.iter_chunks(PREVIEW_ROWS)), None)
        finally:
            source.close()

        if self._cancel.is_set():
            raise CanceledByUser()

        columns: list[str] = []
        rows: list[list[str]] = []
        if frame is not None:
            columns = [str(name) for name in frame.columns]
            rows = [
                [_cell(value) for value in record]
                for record in frame.itertuples(index=False, name=None)
            ]

        return {
            "path": str(self._path),
            "ext": self._path.suffix.lower().lstrip("."),
            "encoding": info.encoding,
            "sheet": info.sheet,
            "total_rows": info.total_rows,
            "streaming": info.streaming,
            "columns": columns,
            "rows": rows,
        }


def _cell(value: object) -> str:
    """把单元格值转成适合展示的短字符串。"""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\t", " ")
    if len(text) > CELL_MAX_CHARS:
        text = text[: CELL_MAX_CHARS - 1] + "…"
    return text


class PreviewTable(QGroupBox):
    """文件预览面板：一行元信息 + 一张只读表格。

    三种状态（空 / 加载中 / 有数据或出错）用 ``QStackedLayout`` 切换，
    避免"加载中"和"表格"同时可见造成的闪烁。
    """

    #: 预览区状态：empty / loading / data / error。
    #: 主窗口与测试靠它判断"这一次读取是不是已经有结论了"——
    #: 只看 ``_preview_loader`` 不够，因为非法文件会在起线程之前就直接报错。
    EMPTY = "empty"
    LOADING = "loading"
    DATA = "data"
    ERROR = "error"

    def __init__(self, lang: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lang = lang
        self._payload: dict | None = None
        self._mode = self.EMPTY
        self._error = ""

        # ---- 元信息行：格式 + 其余说明 ----
        self.format_label = make_label("", role="value")
        self.meta_label = make_label("", role="muted")
        self.meta_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(10)
        meta_row.addWidget(self.format_label)
        meta_row.addWidget(self.meta_label, 1)

        # ---- 表格 ----
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(240)

        # ---- 提示页 ----
        self.hint_label = make_label("", role="muted")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setWordWrap(True)

        self._stack = QStackedLayout()
        self._stack.addWidget(self.hint_label)  # 0
        self._stack.addWidget(self.table)  # 1

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        body.addLayout(meta_row)
        body.addLayout(self._stack, 1)

        self.setLayout(body)
        self.retranslate()

    # ---------------------------------------------------------------- 语言

    @property
    def payload(self) -> dict | None:
        """当前已加载的预览数据；未加载或加载失败时为 ``None``。

        主窗口用它拿 ``total_rows`` 来实时预估输出文件数，避免重复读文件。
        """
        return self._payload

    @property
    def mode(self) -> str:
        """当前状态：``empty`` / ``loading`` / ``data`` / ``error``。"""
        return self._mode

    def set_language(self, lang: str) -> None:
        self._lang = lang
        self.retranslate()

    def retranslate(self) -> None:
        self.setTitle(tr("label.preview", self._lang))
        # 按当前状态重新渲染，而不是一律回到"空"——
        # 否则预览出错后切一次语言，错误信息就被"请选择文件"顶掉了
        if self._mode == self.DATA and self._payload is not None:
            self._render(self._payload)
        elif self._mode == self.LOADING:
            self._show_hint(tr("preview.loading", self._lang))
        elif self._mode == self.ERROR:
            self._show_hint(f"{tr('preview.unreadable', self._lang)}\n{self._error}")
        else:
            self._show_hint(tr("preview.empty", self._lang, rows=PREVIEW_ROWS))

    # ---------------------------------------------------------------- 状态

    def show_empty(self) -> None:
        self._payload = None
        self._error = ""
        self._mode = self.EMPTY
        self._show_hint(tr("preview.empty", self._lang, rows=PREVIEW_ROWS))

    def show_loading(self) -> None:
        self._payload = None
        self._error = ""
        self._mode = self.LOADING
        self._show_hint(tr("preview.loading", self._lang))

    def show_error(self, message: str) -> None:
        self._payload = None
        self._error = message
        self._mode = self.ERROR
        self._show_hint(f"{tr('preview.unreadable', self._lang)}\n{message}")

    def show_data(self, payload: dict) -> None:
        self._payload = payload
        self._error = ""
        self._mode = self.DATA
        self._render(payload)
        self._stack.setCurrentIndex(1)

    def _show_hint(self, text: str) -> None:
        """切到提示页（空 / 加载中 / 出错共用同一页）。"""
        self.format_label.clear()
        self.meta_label.clear()
        self.hint_label.setText(text)
        self._stack.setCurrentIndex(0)

    # ---------------------------------------------------------------- 渲染

    def _render(self, payload: dict) -> None:
        lang = self._lang
        self.format_label.setText(payload["ext"].upper() or "?")

        chips: list[str] = []
        encoding = payload.get("encoding")
        chips.append(
            tr("preview.encoding", lang, encoding=encoding)
            if encoding
            else tr("preview.encoding_unknown", lang)
        )

        total = payload.get("total_rows")
        chips.append(
            tr("preview.rows", lang, rows=f"{total:,}")
            if isinstance(total, int)
            else tr("preview.rows_unknown", lang)
        )

        chips.append(
            tr("preview.streaming", lang)
            if payload.get("streaming")
            else tr("preview.in_memory", lang)
        )

        sheet = payload.get("sheet")
        if sheet:
            chips.append(tr("preview.sheet", lang, sheet=sheet))

        columns: list[str] = payload.get("columns") or []
        if columns:
            chips.append(tr("preview.columns", lang, count=len(columns)))
        if len(columns) > PREVIEW_MAX_COLUMNS:
            chips.append(tr("preview.truncated", lang, shown=PREVIEW_MAX_COLUMNS))

        self.meta_label.setText("  ·  ".join(chips))

        shown_columns = columns[:PREVIEW_MAX_COLUMNS]
        rows = payload.get("rows") or []
        self.table.clear()
        self.table.setColumnCount(len(shown_columns))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(shown_columns)

        for row_index, record in enumerate(rows):
            for column_index in range(len(shown_columns)):
                value = record[column_index] if column_index < len(record) else ""
                self.table.setItem(row_index, column_index, QTableWidgetItem(value))

        # 列宽按内容自适应，但给个上限：太窄看不清，太宽会让表格出现横向滚动条
        self.table.resizeColumnsToContents()
        for column_index in range(self.table.columnCount()):
            width = self.table.columnWidth(column_index)
            self.table.setColumnWidth(column_index, max(72, min(width + 16, 180)))
