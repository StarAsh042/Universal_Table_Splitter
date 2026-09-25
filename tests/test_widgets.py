"""UI 辅助函数的纯逻辑测试（不需要创建窗口）。"""

from __future__ import annotations

from universal_table_splitter.ui.widgets import parse_drop_paths


def test_braced_path_with_spaces():
    assert parse_drop_paths("{C:/Program Files/a b/c.csv}") == ["C:/Program Files/a b/c.csv"]


def test_windows_backslashes_are_not_escaped():
    """``root.tk.splitlist`` 会把未加花括号的 Windows 路径当成 Tcl 转义序列处理，
    实测 ``C:\\plain\\no\\braces`` 会被破坏成 ``C:plain\\no\\x08races``。
    这里的解析器必须原样保留反斜杠。"""
    payload = r"C:\plain\no\braces\artists.csv"
    assert parse_drop_paths(payload) == [payload]


def test_windows_backslashes_in_braced_path():
    payload = r"{D:\GitHub\Universal_Table_Splitter\danbooru_art_full.csv}"
    assert parse_drop_paths(payload) == [
        r"D:\GitHub\Universal_Table_Splitter\danbooru_art_full.csv"
    ]


def test_multiple_mixed_paths():
    payload = r"{C:\a b\one.csv} {C:\two.csv} three.csv"
    assert parse_drop_paths(payload) == [r"C:\a b\one.csv", r"C:\two.csv", "three.csv"]


def test_single_unbraced_path():
    assert parse_drop_paths("data.csv") == ["data.csv"]


def test_empty_payload():
    assert parse_drop_paths("") == []
    assert parse_drop_paths("   ") == []


def test_consecutive_whitespace_is_collapsed():
    assert parse_drop_paths("a.csv \t\n b.csv") == ["a.csv", "b.csv"]
