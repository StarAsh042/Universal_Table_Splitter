"""写出层测试：注册表、编码/BOM、原子写入、公式转义、冲突策略。"""

from __future__ import annotations

import codecs
import errno
import json
from pathlib import Path

import pandas as pd
import pytest

from universal_table_splitter.core.writers import (
    EXPORT_FORMATS,
    ConflictPolicy,
    ExportSpec,
    escape_formula_cells,
    get_spec,
    resolve_conflict,
    translate_os_error,
    write_chunk,
)
from universal_table_splitter.errors import AppError


def test_xls_export_is_gone():
    """pandas >= 2.0 已移除 xlwt 写入引擎，导出 .xls 必然失败，因此必须删除该选项。"""
    assert "xls" not in EXPORT_FORMATS


@pytest.mark.parametrize("key", ["csv", "tsv", "xlsx", "json", "html"])
def test_all_documented_formats_can_be_written(key, tmp_path):
    frame = pd.DataFrame({"a": ["1", "2"], "b": ["中文", "x"]})
    target = write_chunk(frame, tmp_path / f"out{get_spec(key).ext}", get_spec(key))
    assert target.exists() and target.stat().st_size > 0


def test_csv_is_written_with_bom(tmp_path):
    """无 BOM 的 UTF-8 会让 Excel 把中文显示成乱码。"""
    target = write_chunk(pd.DataFrame({"名称": ["中文"]}), tmp_path / "a.csv", get_spec("csv"))
    assert target.read_bytes().startswith(codecs.BOM_UTF8)
    assert pd.read_csv(target, dtype=str)["名称"].tolist() == ["中文"]


def test_tsv_is_tab_separated(tmp_path):
    target = write_chunk(
        pd.DataFrame({"a": ["1"], "b": ["2"]}), tmp_path / "a.tsv", get_spec("tsv")
    )
    assert target.read_text(encoding="utf-8-sig").strip() == "a\tb\n1\t2"


def test_json_keeps_unicode_unescaped(tmp_path):
    target = write_chunk(pd.DataFrame({"名称": ["中文"]}), tmp_path / "a.json", get_spec("json"))
    raw = target.read_text(encoding="utf-8")
    assert "中文" in raw and "\\u4e2d" not in raw
    assert json.loads(raw) == [{"名称": "中文"}]


def test_html_escapes_cell_content(tmp_path):
    target = write_chunk(
        pd.DataFrame({"a": ["<script>alert(1)</script>"]}), tmp_path / "a.html", get_spec("html")
    )
    raw = target.read_text(encoding="utf-8")
    assert "<script>" not in raw
    assert "&lt;script&gt;" in raw


def test_atomic_write_leaves_no_temp_file_on_failure(tmp_path):
    def boom(frame: pd.DataFrame, path: Path) -> None:
        Path(path).write_text("partial", encoding="utf-8")
        raise RuntimeError("disk exploded")

    spec = ExportSpec("boom", ".csv", boom)
    with pytest.raises(RuntimeError):
        write_chunk(pd.DataFrame({"a": [1]}), tmp_path / "x.csv", spec)
    # 临时文件与目标文件都不应留下
    assert list(tmp_path.iterdir()) == []


def test_formula_escaping_is_opt_in(tmp_path):
    frame = pd.DataFrame({"note": ["=1+1", "safe", "@cmd"]})
    plain = write_chunk(frame, tmp_path / "plain.csv", get_spec("csv"))
    assert pd.read_csv(plain, dtype=str)["note"].tolist() == ["=1+1", "safe", "@cmd"]

    escaped = write_chunk(frame, tmp_path / "escaped.csv", get_spec("csv"), escape_formulas=True)
    assert pd.read_csv(escaped, dtype=str)["note"].tolist() == ["'=1+1", "safe", "'@cmd"]


def test_escape_formula_cells_skips_non_object_columns():
    frame = pd.DataFrame({"n": [1, 2], "s": ["=x", "y"]})
    result = escape_formula_cells(frame)
    assert result["n"].tolist() == [1, 2]
    assert result["s"].tolist() == ["'=x", "y"]


def test_escape_formula_cells_handles_empty_frame():
    frame = pd.DataFrame({"a": []})
    assert escape_formula_cells(frame).empty


def test_resolve_conflict_overwrite(tmp_path):
    target = tmp_path / "a.csv"
    target.write_text("old", encoding="utf-8")
    assert resolve_conflict(target, ConflictPolicy.OVERWRITE) == target


def test_resolve_conflict_index(tmp_path):
    target = tmp_path / "a.csv"
    target.write_text("old", encoding="utf-8")
    first = resolve_conflict(target, ConflictPolicy.INDEX)
    assert first.name == "a_1.csv"
    first.write_text("x", encoding="utf-8")
    assert resolve_conflict(target, ConflictPolicy.INDEX).name == "a_2.csv"


def test_resolve_conflict_when_absent(tmp_path):
    target = tmp_path / "a.csv"
    assert resolve_conflict(target, ConflictPolicy.INDEX) == target


def test_get_spec_rejects_unknown_format():
    with pytest.raises(AppError) as info:
        get_spec("xls")
    assert info.value.key == "err.invalid_export_format"


@pytest.mark.parametrize(
    ("errno_value", "expected_key"),
    [
        (errno.EACCES, "err.permission"),
        (errno.EPERM, "err.permission"),
        (errno.ENOSPC, "err.disk_full"),
        (errno.ENOENT, "err.write_failed"),
    ],
)
def test_translate_os_error(errno_value, expected_key, tmp_path):
    error = translate_os_error(OSError(errno_value, "boom"), tmp_path / "a.csv")
    assert error.key == expected_key
