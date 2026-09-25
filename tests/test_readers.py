"""读取层测试：编码回退、分隔符嗅探、保真模式、流式一致性、安全预检。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from universal_table_splitter.core import readers
from universal_table_splitter.core.readers import (
    ReadOptions,
    detect_encoding,
    list_sheets,
    open_table,
    sniff_delimiter,
    supported_extensions,
)
from universal_table_splitter.errors import AppError, CanceledByUser, FileFormatError

from .conftest import ROW_COUNT, ROWS


def _read_all(path: Path, options: ReadOptions, chunk_size: int = 3) -> pd.DataFrame:
    source = open_table(path, options)
    try:
        frames = list(source.iter_chunks(chunk_size))
    finally:
        source.close()
    return pd.concat(frames, ignore_index=True)


def test_detect_encoding_variants(basic_csv, gbk_csv, bom_csv, tmp_path):
    assert detect_encoding(basic_csv) == "utf-8"
    assert detect_encoding(gbk_csv) == "gb18030"
    assert detect_encoding(bom_csv) == "utf-8-sig"  # BOM 单独识别
    utf16 = tmp_path / "utf16.csv"
    utf16.write_text("id,name\n1,中文\n", encoding="utf-16")
    assert detect_encoding(utf16) == "utf-16"


def test_detect_encoding_falls_back_for_binary_garbage(tmp_path):
    path = tmp_path / "weird.csv"
    path.write_bytes(bytes(range(256)) * 4)
    # 不应抛异常，最终落到永不失败的兜底编码
    assert detect_encoding(path) in readers.DEFAULT_ENCODINGS


def test_sniff_delimiter_keeps_default_when_present():
    assert sniff_delimiter("a,b,c\n1,2,3\n", ",") == ","
    assert sniff_delimiter("a,b\tc\n", "\t") == "\t"


def test_sniff_delimiter_detects_semicolon_when_default_missing():
    assert sniff_delimiter("a;b;c\n1;2;3\n", ",") == ";"


def test_gbk_file_is_readable(gbk_csv):
    """原实现固定 UTF-8，读取 GBK 中文 CSV 会直接抛 UnicodeDecodeError。"""
    frame = _read_all(gbk_csv, ReadOptions(fidelity=True))
    assert len(frame) == ROW_COUNT
    assert "中文字段" in frame["artist"].tolist()


def test_fidelity_keeps_leading_zeros(basic_csv):
    frame = _read_all(basic_csv, ReadOptions(fidelity=True))
    assert frame["id"].tolist()[:3] == ["001", "002", "003"]
    assert frame["id"].dtype == object


def test_without_fidelity_leading_zeros_are_lost(basic_csv):
    """对照组：说明"保真模式"存在的必要性（默认开启）。"""
    frame = _read_all(basic_csv, ReadOptions(fidelity=False))
    assert frame["id"].tolist()[:3] == [1, 2, 3]


def test_semicolon_file_is_sniffed(semicolon_csv):
    frame = _read_all(semicolon_csv, ReadOptions(fidelity=True))
    assert list(frame.columns) == ["id", "artist", "count", "note"]
    assert len(frame) == ROW_COUNT


def test_tsv_file(tsv_file):
    frame = _read_all(tsv_file, ReadOptions(fidelity=True))
    assert len(frame) == ROW_COUNT


def test_streaming_and_buffered_reads_agree(basic_csv):
    buffered = _read_all(basic_csv, ReadOptions(fidelity=True))
    streamed = _read_all(basic_csv, ReadOptions(fidelity=True, force_stream=True))
    assert buffered.equals(streamed)


def test_streaming_reports_row_count(basic_csv):
    source = open_table(basic_csv, ReadOptions(force_stream=True))
    try:
        assert source.total_rows == ROW_COUNT
        assert source.streaming is True
    finally:
        source.close()


def test_buffered_mode_reports_streaming_flag_false(basic_csv):
    source = open_table(basic_csv, ReadOptions())
    try:
        assert source.streaming is False
        assert source.total_rows == ROW_COUNT
    finally:
        source.close()


def test_iter_chunks_respects_preset_cancel(basic_csv):
    import threading

    cancel = threading.Event()
    cancel.set()
    source = open_table(basic_csv, ReadOptions(force_stream=True))
    try:
        assert list(source.iter_chunks(3, cancel=cancel)) == []
    finally:
        source.close()


def test_counting_is_interruptible(tmp_path):
    """超大文件统计行数时也要能被取消，否则界面会长时间无响应。"""
    import threading

    path = tmp_path / "big.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("a,b\n")
        for index in range(readers.CANCEL_CHECK_INTERVAL * 2 + 100):
            handle.write(f"{index},x\n")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CanceledByUser):
        readers.count_delimited_rows(path, "utf-8", ",", cancel=cancel)


def test_xlsx_single_sheet(xlsx_single):
    frame = _read_all(xlsx_single, ReadOptions(fidelity=True))
    assert len(frame) == ROW_COUNT
    assert list(frame.columns) == ["id", "artist", "count", "note"]
    assert frame["id"].tolist()[:2] == ["001", "002"]


def test_xlsx_streams_without_loading_whole_file(xlsx_single):
    source = open_table(xlsx_single, ReadOptions())
    try:
        assert source.streaming is True
        assert source.total_rows == ROW_COUNT
    finally:
        source.close()


def test_list_sheets(xlsx_multi, basic_csv):
    assert list_sheets(xlsx_multi) == ("First", "Second")
    assert list_sheets(basic_csv) == ()  # 非 Excel 返回空，不抛异常


def test_multi_sheet_selection(xlsx_multi):
    """原实现只读第一个 sheet 且没有任何提示。"""
    second = _read_all(xlsx_multi, ReadOptions(sheet="Second"))
    assert second["artist"].tolist() == ["second-sheet"]
    first = _read_all(xlsx_multi, ReadOptions(sheet="First"))
    assert len(first) == ROW_COUNT


def test_missing_sheet_raises(xlsx_multi):
    with pytest.raises(AppError) as info:
        open_table(xlsx_multi, ReadOptions(sheet="Nope"))
    assert info.value.key == "err.sheet_not_found"


def test_json_records(json_file):
    frame = _read_all(json_file, ReadOptions(fidelity=True), chunk_size=4)
    assert len(frame) == ROW_COUNT
    assert "中文字段" in frame["artist"].tolist()


def test_json_lines(jsonl_file):
    frame = _read_all(jsonl_file, ReadOptions(fidelity=True), chunk_size=4)
    assert len(frame) == ROW_COUNT


def test_plain_json_with_lines_flag_falls_back(json_file):
    """误把普通 JSON 当成 JSON Lines 打开时，应自动兜底而不是报错。"""
    frame = _read_all(json_file, ReadOptions(fidelity=True), chunk_size=5)
    assert len(frame) == ROW_COUNT


def test_inflate_bomb_is_rejected(tmp_path):
    bomb = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (4 * 1024 * 1024))
    with pytest.raises(AppError) as info:
        readers._check_inflate_ratio(bomb, limit=10)
    assert info.value.key == "err.suspicious_file"


def test_full_load_size_limit(monkeypatch, json_file):
    monkeypatch.setattr(readers, "MAX_FULL_LOAD_BYTES", 10)
    with pytest.raises(AppError) as info:
        open_table(json_file, ReadOptions())
    assert info.value.key == "err.file_too_large"


def test_unsupported_extension(tmp_path):
    path = tmp_path / "data.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(FileFormatError):
        open_table(path, ReadOptions())


def test_supported_extensions_cover_documented_formats():
    extensions = supported_extensions()
    for ext in (".csv", ".tsv", ".xlsx", ".xls", ".json"):
        assert ext in extensions


def test_normalize_columns_handles_duplicates_and_blanks():
    columns = readers._normalize_columns(["a", "a", None, "  "])
    assert columns == ["a", "a.1", "Unnamed: 2", "Unnamed: 3"]


def test_stringify_matches_pandas_semantics():
    assert readers._stringify(None) == ""
    assert readers._stringify(1.0) == "1"
    assert readers._stringify(1.5) == "1.5"
    assert readers._stringify(True) == "True"


def test_rows_fixture_is_intact():
    """保证夹具本身与断言一致（避免测试数据被误改后断言静默失效）。"""
    assert len(ROWS) == ROW_COUNT == 10
