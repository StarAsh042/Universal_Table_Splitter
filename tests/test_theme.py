"""深色主题测试。

这组测试盯住的主题风险：QSS 是 f-string 拼出来的，少写一对花括号就会生成非法
样式表——Qt 遇到非法 QSS 不会报错，只会静默地不应用部分规则，界面就会莫名其妙地
"部分生效"。下面的用例专门盯住这一点。
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import QStyleFactory

from universal_table_splitter.ui import theme


def test_stylesheet_braces_are_balanced():
    """f-string 里没转义的花括号会生成非法 QSS。

    这里比对花括号数量：相等不代表一定合法，但不等**一定**是漏了转义。
    """
    qss = theme.build_stylesheet()
    assert qss.count("{") == qss.count("}")
    assert qss.count("{") > 20  # 规则数量下限，防止样式表被清空


def test_stylesheet_contains_expected_selectors():
    qss = theme.build_stylesheet()
    for selector in ("QLineEdit", "QPushButton", "QComboBox", "QProgressBar", "QHeaderView"):
        assert selector in qss


def test_stylesheet_has_no_unresolved_placeholder():
    """拼错的变量名会原样留在字符串里（例如 ``{BG_WINDW}``）。"""
    import re

    leftovers = re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", theme.build_stylesheet())
    assert leftovers == []


def test_palette_constants_are_hex_colours():
    for name in dir(theme):
        if name.isupper() and not name.startswith("_"):
            value = getattr(theme, name)
            if isinstance(value, str):
                assert value.startswith("#") and len(value) == 7, f"{name}={value!r}"


def test_pick_ui_font_returns_a_font(qapp):
    font = theme.pick_ui_font()
    assert isinstance(font, QFont)
    assert font.pointSize() > 0


def test_apply_dark_theme_configures_the_application(qapp):
    theme.apply_dark_theme(qapp)

    assert qapp.styleSheet() == theme.build_stylesheet()
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == theme.BG_WINDOW.lower()
    assert qapp.palette().color(QPalette.ColorRole.Text).name() == theme.TEXT.lower()


def test_fusion_style_is_available():
    """``apply_dark_theme`` 用 Fusion 打底。

    为什么不直接断言 ``qapp.style()``：一旦设了样式表，Qt 会把当前风格包进
    ``QStyleSheetStyle``，拿不到底层风格的类名。所以这里退一步，确认 Fusion
    确实存在于本机 Qt 构建里——不存在的话 ``setStyle("Fusion")`` 会静默失败，
    界面会退回 Windows 原生风格，圆角和内边距规则全部失效。
    """
    available = list(QStyleFactory.keys())
    assert "Fusion" in available


def test_disabled_text_colour_is_dimmed(qapp):
    """禁用态必须比正常态暗，否则用户分不清哪些控件不能用。"""
    theme.apply_dark_theme(qapp)  # qapp 是会话级的，这里显式保证主题已应用
    palette = qapp.palette()
    disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    normal = palette.color(QPalette.ColorRole.Text)
    assert disabled.lightness() < normal.lightness()
