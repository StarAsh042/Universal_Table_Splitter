"""主题与 DPI 探测测试（不需要创建窗口）。"""

from __future__ import annotations

import sys
from tkinter import TclError

from universal_table_splitter.ui import theme


def test_detect_dark_mode_returns_bool():
    assert isinstance(theme.detect_dark_mode(), bool)


def test_enable_dpi_awareness_never_raises():
    theme.enable_dpi_awareness()  # 非 Windows 平台直接返回，Windows 上失败也要静默
    theme.enable_dpi_awareness()  # 幂等


def test_bootstyle_degrades_gracefully():
    assert isinstance(theme.bootstyle("success"), dict)
    assert theme.bootstyle() == {}
    if not theme.HAS_TTKB:
        assert theme.bootstyle("success") == {}


def test_accent_color_has_fallback():
    assert theme.accent_color(None).startswith("#")


def test_styled_passes_bootstyle_through(monkeypatch):
    monkeypatch.setattr(theme, "HAS_TTKB", True)
    seen: list[dict] = []

    def factory(**kwargs):
        seen.append(kwargs)
        return "widget"

    assert theme.styled(factory, "secondary", text="x") == "widget"
    assert seen == [{"bootstyle": "secondary", "text": "x"}]


def test_styled_falls_back_when_bootstyle_layout_missing(monkeypatch):
    """打包环境或自定义主题下 ``round-toggle`` 的 layout 可能缺失，
    此时必须退回原生 ttk，而不是让界面构建整体失败。"""
    monkeypatch.setattr(theme, "HAS_TTKB", True)
    seen: list[dict] = []

    def factory(**kwargs):
        seen.append(kwargs)
        if "bootstyle" in kwargs:
            raise TclError("Layout Round.Toggle not found")
        return "plain-widget"

    assert theme.styled(factory, "round-toggle", text="x") == "plain-widget"
    assert seen == [{"bootstyle": "round-toggle", "text": "x"}, {"text": "x"}]


def test_styled_tries_candidates_in_order(monkeypatch):
    """``a|b|c`` 形式：按顺序尝试，用第一个可用的。"""
    monkeypatch.setattr(theme, "HAS_TTKB", True)
    seen: list[dict] = []

    def factory(**kwargs):
        seen.append(kwargs)
        if kwargs.get("bootstyle") == "round-toggle":
            raise TclError("Layout Round.Toggle not found")
        return "ok"

    assert theme.styled(factory, "round-toggle|toolbutton", text="x") == "ok"
    assert seen == [
        {"bootstyle": "round-toggle", "text": "x"},
        {"bootstyle": "toolbutton", "text": "x"},
    ]


def test_styled_without_bootstyle_values(monkeypatch):
    monkeypatch.setattr(theme, "HAS_TTKB", True)
    assert theme.styled(dict, text="x") == {"text": "x"}
    assert theme.styled(dict, "", text="x") == {"text": "x"}
    assert theme.styled(dict, "|", text="x") == {"text": "x"}


def test_apply_bootstyle_is_safe(monkeypatch):
    class Widget:
        def __init__(self):
            self.calls = []

        def configure(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("bootstyle") == "boom":
                raise TclError("no such style")

    widget = Widget()
    monkeypatch.setattr(theme, "HAS_TTKB", True)
    theme.apply_bootstyle(widget, "success")
    theme.apply_bootstyle(widget, "boom")  # 失败也不能抛出去
    theme.apply_bootstyle(widget, "")
    assert widget.calls == [{"bootstyle": "success"}, {"bootstyle": "boom"}]


def test_disable_ttkbootstrap_turns_off_enhancement(monkeypatch):
    monkeypatch.setattr(theme, "HAS_TTKB", True)
    assert theme.bootstyle("link") == {"bootstyle": "link"}
    theme.disable_ttkbootstrap("测试")
    assert theme.bootstyle("link") == {}
    assert theme.create_style(object(), dark=True) is None
    monkeypatch.setattr(theme, "HAS_TTKB", True)  # 还原，避免影响其它用例


def test_create_style_returns_none_without_ttkbootstrap(monkeypatch):
    monkeypatch.setattr(theme, "HAS_TTKB", False)
    assert theme.create_style(object(), dark=False) is None


def test_dark_mode_reads_windows_registry(monkeypatch):
    if sys.platform != "win32":  # pragma: no cover - 平台相关
        return
    import winreg
    from unittest import mock

    fake_value = 0  # 0 = 深色
    query_value = mock.patch.object(winreg, "QueryValueEx", return_value=(fake_value, 4))
    open_key = mock.patch.object(winreg, "OpenKey", return_value=mock.MagicMock())
    with open_key, query_value:
        assert theme._windows_dark_mode() is True


def test_dark_mode_survives_registry_error(monkeypatch):
    if sys.platform != "win32":  # pragma: no cover - 平台相关
        return
    import winreg

    def boom(*args, **kwargs):
        raise OSError("no such key")

    monkeypatch.setattr(winreg, "OpenKey", boom)
    assert theme._windows_dark_mode() is False
