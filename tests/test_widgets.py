"""可复用控件测试。

拖放由 Qt 的 ``QMimeData.urls()`` 直接给出 ``QUrl``，不需要手写路径解析器
（那类解析器容易被 Windows 路径里的反斜杠坑到）。这组测试盯的是控件的对外契约。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog

from universal_table_splitter.ui.widgets import PathPicker, make_label, make_separator


@pytest.fixture
def picker(qapp):
    widget = PathPicker("输入文件", placeholder="拖入文件")
    yield widget
    widget.deleteLater()


def test_path_is_stripped(picker):
    picker.edit.setText("  C:\\data\\a.csv  ")
    assert picker.path() == "C:\\data\\a.csv"


def test_empty_path_returns_empty_string(picker):
    picker.edit.setText("   ")
    assert picker.path() == ""


def test_set_path_does_not_emit_path_changed(picker):
    """程序改值和用户改值必须能区分开。

    否则"载入上次的路径"会被当成用户操作，触发一次多余的预览读取。
    """
    seen: list[str] = []
    picker.pathChanged.connect(seen.append)

    picker.set_path("C:\\data\\a.csv")

    assert picker.path() == "C:\\data\\a.csv"
    assert seen == []


def test_set_path_is_noop_for_identical_value(picker):
    seen: list[str] = []
    picker.set_path("same.csv")
    picker.pathChanged.connect(seen.append)
    picker.set_path("same.csv")
    assert seen == []


def test_typing_emits_path_changed(picker):
    seen: list[str] = []
    picker.pathChanged.connect(seen.append)

    picker.edit.setText("a.csv")

    assert seen == ["a.csv"]


def test_set_enabled_toggles_edit_and_button(picker):
    picker.set_enabled(False)
    assert not picker.edit.isEnabled()
    assert not picker.browse_button.isEnabled()

    picker.set_enabled(True)
    assert picker.edit.isEnabled()
    assert picker.browse_button.isEnabled()


def test_texts_are_settable(picker):
    picker.set_title("T")
    picker.set_button_text("B")
    picker.set_placeholder("P")
    assert picker.title_label.text() == "T"
    assert picker.browse_button.text() == "B"
    assert picker.edit.placeholderText() == "P"


def test_browse_normalises_separators(picker, monkeypatch):
    """Qt 在 Windows 上统一返回正斜杠，写入前要转回反斜杠。

    否则同一个路径会在界面上显示成两种样子（手输是 ``\\``，点浏览是 ``/``）。
    """
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("C:/data/a.csv", ""))
    )
    seen: list[str] = []
    picker.pathChanged.connect(seen.append)

    picker.browse()

    assert picker.path() == str(Path("C:/data/a.csv"))
    assert seen == [picker.path()]


def test_browse_cancel_keeps_previous_value(picker, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    picker.set_path("keep.csv")

    picker.browse()

    assert picker.path() == "keep.csv"


def test_directory_mode_uses_directory_dialog(picker, monkeypatch):
    directory_picker = PathPicker("输出目录", select_dir=True)
    calls: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *a, **k: calls.append("dir") or "D:/out"),
    )

    directory_picker.browse()

    assert calls == ["dir"]
    assert directory_picker.path() == str(Path("D:/out"))
    directory_picker.deleteLater()


def test_make_label_applies_role(qapp):
    label = make_label("x", role="muted")
    assert label.text() == "x"
    assert label.property("role") == "muted"
    label.deleteLater()


def test_make_label_without_role_has_no_property(qapp):
    label = make_label("x")
    assert label.property("role") is None
    label.deleteLater()


def test_make_separator_is_one_pixel_high(qapp):
    line = make_separator()
    assert line.height() == 1
    assert line.property("role") == "separator"
    line.deleteLater()
