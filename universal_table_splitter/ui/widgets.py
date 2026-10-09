"""可复用控件。

``PathPicker`` 把"标签 + 输入框 + 浏览按钮"封装成一个整体，对外只暴露
``path()`` / ``set_path()`` 和 ``pathChanged`` 信号。旧的 ``FileSelector``
需要调用方自己记住 ``entry_state``（输入框 readonly、输出框 normal），
这里改成控件自己管理，调用方不用再关心。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)


def make_label(text: str = "", role: str = "", parent: QWidget | None = None) -> QLabel:
    """创建一个带语义标记的标签。

    ``role`` 会写进 Qt 的 ``class`` 属性，供 QSS 用 ``QLabel[role="muted"]`` 命中，
    这样"次要文字"的颜色只在一处定义。
    """
    label = QLabel(text, parent)
    if role:
        label.setProperty("role", role)
    return label


def make_separator(parent: QWidget | None = None) -> QFrame:
    """一条 1 像素的横向分隔线。"""
    line = QFrame(parent)
    line.setProperty("role", "separator")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


class PathPicker(QWidget):
    """路径选择控件：标签 + 输入框 + 浏览按钮。

    参数
    ----
    title:
        左侧标签文字。
    placeholder:
        输入框为空时的灰字提示。
    select_dir:
        ``True`` 时浏览按钮打开"选择目录"对话框，``False`` 时打开"选择文件"。
    file_filter:
        选择文件时的类型过滤，例如 ``"表格文件 (*.csv *.tsv *.xlsx)"``。
    """

    #: 路径被用户修改（手动输入或点浏览）时发出
    pathChanged = Signal(str)

    def __init__(
        self,
        title: str = "",
        *,
        placeholder: str = "",
        select_dir: bool = False,
        file_filter: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._select_dir = select_dir
        self._file_filter = file_filter
        self._last_dir = ""

        self.title_label = make_label(title)
        self.title_label.setFixedWidth(72)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit.textChanged.connect(self.pathChanged.emit)

        self.browse_button = QPushButton("浏览…")
        self.browse_button.setFixedWidth(80)
        self.browse_button.clicked.connect(self.browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.title_label)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.browse_button)

    # ---------------------------------------------------------------- 对外接口

    def path(self) -> str:
        """返回去掉首尾空白的路径字符串；为空时返回空串。"""
        return self.edit.text().strip()

    def set_path(self, value: str) -> None:
        """写入路径。不会触发 ``pathChanged``（避免"程序改值"被当成"用户改值"）。"""
        if value == self.edit.text():
            return
        blocked = self.edit.blockSignals(True)
        try:
            self.edit.setText(value)
        finally:
            self.edit.blockSignals(blocked)
        self.edit.setCursorPosition(len(value))

    def set_enabled(self, enabled: bool) -> None:
        self.edit.setEnabled(enabled)
        self.browse_button.setEnabled(enabled)

    def set_button_text(self, text: str) -> None:
        self.browse_button.setText(text)

    def set_placeholder(self, text: str) -> None:
        self.edit.setPlaceholderText(text)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    # ------------------------------------------------------------------ 内部

    def browse(self) -> None:
        """打开系统文件 / 目录选择对话框。"""
        start = self.path() or self._last_dir
        if self._select_dir:
            chosen = QFileDialog.getExistingDirectory(self, self.title_label.text(), start)
        else:
            chosen, _ = QFileDialog.getOpenFileName(
                self, self.title_label.text(), start, self._file_filter
            )
        if not chosen:
            return  # 用户取消
        # Qt 在 Windows 上统一返回正斜杠；转成 Path 再转回字符串，
        # 让它跟用户手动输入的反斜杠写法一致，否则同一个路径会显示成两种样子
        chosen = str(Path(chosen))
        self.set_path(chosen)
        self.pathChanged.emit(chosen)

    def set_last_dir(self, directory: str) -> None:
        """记住上次使用的目录，作为浏览对话框的起始位置。"""
        self._last_dir = directory
