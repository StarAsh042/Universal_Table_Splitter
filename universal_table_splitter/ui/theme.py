"""深色主题：调色板与全局样式表。

选 Qt 的理由很简单：它的样式表是全局生效的，一份 QSS 同时覆盖控件、弹出菜单、
滚动条与表头，单控件的内边距、圆角、聚焦描边也都能改。这是界面观感统一的关键。

关于 DPI：Qt 6 默认就开启了高 DPI 缩放，因此这里不需要任何 DPI 相关代码。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

# --------------------------------------------------------------------------- 字体

#: 候选字体，按优先级排列。
#:
#: Qt 在 Windows 上的默认字体是 Segoe UI，它**不含中文字形**。Qt 虽然会在渲染时
#: 做字体回退，但在某些后端（离屏渲染、部分打包环境）回退不生效，界面会整片
#: 显示成方框。显式挑一个确定带中文字形的字体，比赌回退可靠。
_FONT_CANDIDATES = (
    "Microsoft YaHei UI",  # Windows 10+
    "Microsoft YaHei",  # Windows 7/8
    "PingFang SC",  # macOS
    "Noto Sans CJK SC",  # Linux
    "Source Han Sans SC",  # Linux
    "WenQuanYi Micro Hei",  # Linux
)


def pick_ui_font() -> QFont:
    """挑一个系统中确实存在、且带中文字形的界面字体。

    找不到任何候选时退回 Qt 默认字体（英文环境通常没问题）。
    """
    families = set(QFontDatabase.families())
    for name in _FONT_CANDIDATES:
        if name in families:
            return QFont(name, 10)
    return QFont()


# --------------------------------------------------------------------------- 调色板

#: 窗口底色
BG_WINDOW = "#1B1D21"
#: 卡片 / 分组框底色
BG_SURFACE = "#232529"
#: 输入框、下拉框底色
BG_INPUT = "#2C2F34"
#: 输入框悬停底色
BG_INPUT_HOVER = "#33373D"
#: 表头底色
BG_HEADER = "#2A2D33"

#: 常规边框
BORDER = "#3A3E45"
#: 聚焦边框
BORDER_FOCUS = "#4C8DFF"

#: 主文字
TEXT = "#E4E6EB"
#: 次要文字（提示、单位、说明）
TEXT_MUTED = "#8B919B"
#: 禁用文字
TEXT_DISABLED = "#5A5F68"

#: 主色（按钮、进度条、选中态）
ACCENT = "#4C8DFF"
ACCENT_HOVER = "#6BA1FF"
ACCENT_PRESSED = "#3A7AE8"
ACCENT_DISABLED = "#2F3A4D"

#: 语义色
SUCCESS = "#3FB950"
DANGER = "#F85149"
WARNING = "#D29922"


def build_stylesheet() -> str:
    """生成全局 QSS。"""
    return f"""
/* ------------------------------------------------------------------ 基础 */
QWidget {{
    background-color: {BG_WINDOW};
    color: {TEXT};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {BG_WINDOW};
}}

QToolTip {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 8px;
}}

/* ------------------------------------------------------------------ 分组框 */
QGroupBox {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 14px 14px 14px;
    font-weight: 600;
}}

/* 标题浮在分组框上方的留白里，所以背景必须透明——填底色会在窗口底色上
   糊出一块颜色略深的方块，比"压在边框线上"更难看 */
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 0 6px;
    background-color: transparent;
    color: {TEXT_MUTED};
    font-weight: 600;
}}

/* ------------------------------------------------------------------ 文字 */
QLabel {{
    background-color: transparent;
    color: {TEXT};
}}

QLabel[role="muted"] {{
    color: {TEXT_MUTED};
}}

QLabel[role="heading"] {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 600;
}}

QLabel[role="value"] {{
    color: {TEXT};
    font-weight: 600;
}}

/* 非阻断式警告：用于"缺少可选依赖"这类只需告知、不该弹窗打断的情况 */
QLabel[role="warning"] {{
    color: {WARNING};
}}

/* ------------------------------------------------------------------ 输入 */
QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}

QLineEdit:hover {{
    background-color: {BG_INPUT_HOVER};
}}

QLineEdit:focus {{
    border: 1px solid {BORDER_FOCUS};
    background-color: {BG_INPUT_HOVER};
}}

QLineEdit:read-only {{
    color: {TEXT_MUTED};
}}

QLineEdit:disabled {{
    color: {TEXT_DISABLED};
    background-color: {BG_SURFACE};
}}

QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    min-width: 80px;
}}

QComboBox:hover {{
    background-color: {BG_INPUT_HOVER};
}}

QComboBox:focus {{
    border: 1px solid {BORDER_FOCUS};
}}

QComboBox:disabled {{
    color: {TEXT_DISABLED};
    background-color: {BG_SURFACE};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_MUTED};
    margin-right: 8px;
}}

/* 下拉弹出层：不单独设样式会变成系统浅色，非常突兀 */
QComboBox QAbstractItemView {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    outline: none;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
    padding: 4px;
}}

/* ------------------------------------------------------------------ 按钮 */
QPushButton {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 16px;
    min-height: 16px;
}}

QPushButton:hover {{
    background-color: {BG_INPUT_HOVER};
    border-color: {TEXT_DISABLED};
}}

QPushButton:pressed {{
    background-color: {BG_SURFACE};
}}

QPushButton:disabled {{
    color: {TEXT_DISABLED};
    background-color: {BG_SURFACE};
    border-color: {BORDER};
}}

/* 主按钮：旧界面那个深蓝按钮在深色底上几乎看不见，这里提亮并去掉边框 */
QPushButton[role="primary"] {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border: none;
    font-weight: 600;
    padding: 8px 24px;
}}

QPushButton[role="primary"]:hover {{
    background-color: {ACCENT_HOVER};
}}

QPushButton[role="primary"]:pressed {{
    background-color: {ACCENT_PRESSED};
}}

QPushButton[role="primary"]:disabled {{
    background-color: {ACCENT_DISABLED};
    color: {TEXT_DISABLED};
}}

/* 次要按钮：低调的文字按钮，用于"切换语言""关于"这类 */
QPushButton[role="ghost"] {{
    background-color: transparent;
    border: none;
    color: {TEXT_MUTED};
    padding: 6px 10px;
}}

QPushButton[role="ghost"]:hover {{
    color: {TEXT};
    background-color: {BG_INPUT};
    border-radius: 6px;
}}

/* ------------------------------------------------------------------ 复选 */
QCheckBox {{
    background-color: transparent;
    color: {TEXT};
    padding: 4px 0;
    spacing: 8px;
}}

QCheckBox:disabled {{
    color: {TEXT_DISABLED};
}}

QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 2px solid {TEXT_DISABLED};
    background-color: transparent;
}}

QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}

QCheckBox::indicator:checked {{
    border-color: {ACCENT};
    background-color: {ACCENT};
}}

/* ------------------------------------------------------------------ 单选 */
QRadioButton {{
    background-color: transparent;
    color: {TEXT};
    padding: 4px 0;
    spacing: 8px;
}}

QRadioButton:disabled {{
    color: {TEXT_DISABLED};
}}

QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 9px;
    border: 2px solid {TEXT_DISABLED};
    background-color: transparent;
}}

QRadioButton::indicator:hover {{
    border-color: {ACCENT};
}}

QRadioButton::indicator:checked {{
    border: 4px solid {ACCENT};
    background-color: {BG_WINDOW};
}}

/* ------------------------------------------------------------------ 进度条 */
QProgressBar {{
    background-color: {BG_INPUT};
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 6px;
}}

/* ------------------------------------------------------------------ 表格 */
QTableWidget, QTableView {{
    background-color: {BG_INPUT};
    alternate-background-color: {BG_SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
    outline: none;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}

QTableWidget::item, QTableView::item {{
    padding: 4px 8px;
    border: none;
}}

QHeaderView {{
    background-color: {BG_HEADER};
    border: none;
}}

QHeaderView::section {{
    background-color: {BG_HEADER};
    color: {TEXT_MUTED};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    font-weight: 600;
}}

QTableCornerButton::section {{
    background-color: {BG_HEADER};
    border: none;
}}

/* ------------------------------------------------------------------ 滚动条 */
QScrollBar:vertical {{
    background-color: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {TEXT_DISABLED};
}}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 10px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background-color: {BORDER};
    border-radius: 5px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {TEXT_DISABLED};
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QScrollBar::add-page, QScrollBar::sub-page {{
    background-color: transparent;
}}

/* ------------------------------------------------------------------ 分隔线 */
QFrame[role="separator"] {{
    background-color: {BORDER};
    border: none;
    max-height: 1px;
}}

/* ------------------------------------------------------------------ 弹窗 */
QMessageBox {{
    background-color: {BG_SURFACE};
}}

QMessageBox QLabel {{
    color: {TEXT};
    background-color: transparent;
}}

QMessageBox QPushButton {{
    min-width: 72px;
}}
"""


def _build_palette() -> QPalette:
    """构造 QPalette。

    只负责 QSS 覆盖不到的部分：占位文字、禁用态文字、工具提示底色等。
    """
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_WINDOW))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_INPUT))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_SURFACE))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG_INPUT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_INPUT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXT_DISABLED))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(TEXT_DISABLED)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(TEXT_DISABLED)
    )
    return palette


def apply_dark_theme(app: QApplication) -> None:
    """把深色主题应用到整个应用。

    用 Fusion 风格打底：它完全由 Qt 自己绘制，不像 Windows 原生风格那样
    会忽略一半的 QSS 规则（尤其是圆角和内边距）。
    """
    app.setStyle("Fusion")
    app.setFont(pick_ui_font())
    app.setPalette(_build_palette())
    app.setStyleSheet(build_stylesheet())
