"""纯函数层测试：分块计划、编号生成、用户输入解析。"""

from __future__ import annotations

import pytest

from universal_table_splitter.core.plan import (
    build_output_name,
    chunk_bounds,
    chunk_count,
    format_suffix,
    human_size,
    parse_chunk_size,
    parse_num_format,
    plan_chunks,
)
from universal_table_splitter.errors import ValidationError


@pytest.mark.parametrize(
    ("total", "size", "expected"),
    [
        (2500, 1000, [(0, 1000), (1000, 2000), (2000, 2500)]),  # 末块不越界
        (2000, 1000, [(0, 1000), (1000, 2000)]),  # 整除
        (10, 1000, [(0, 10)]),  # 单块
        (1, 1, [(0, 1)]),
        (0, 1000, []),  # 空表
    ],
)
def test_plan_chunks(total, size, expected):
    assert plan_chunks(total, size) == expected


def test_chunk_bounds_is_lazy_and_never_exceeds_total():
    assert all(stop <= 2500 for _, stop in chunk_bounds(2500, 700))
    assert list(chunk_bounds(2500, 700)) == [(0, 700), (700, 1400), (1400, 2100), (2100, 2500)]


@pytest.mark.parametrize("size", [0, -1])
def test_plan_chunks_rejects_non_positive_size(size):
    with pytest.raises(ValueError):
        plan_chunks(100, size)
    with pytest.raises(ValueError):
        chunk_count(100, size)


def test_chunk_count():
    assert chunk_count(419_789, 1000) == 420
    assert chunk_count(0, 1000) == 0
    assert chunk_count(1000, 1000) == 1


def test_format_suffix_pads_and_grows():
    assert format_suffix(1, 3) == "001"
    assert format_suffix(999, 3) == "999"
    assert format_suffix(1000, 3) == "1000"  # 超出位数自然增宽，不报错
    assert format_suffix(7, 1) == "7"


@pytest.mark.parametrize("index", [0, -1])
def test_format_suffix_rejects_invalid_index(index):
    with pytest.raises(ValueError):
        format_suffix(index, 3)


def test_build_output_name_avoids_double_separator():
    assert build_output_name("art", "001", ".csv") == "art_001.csv"
    assert build_output_name("art_001", "", ".csv", 2) == "art_001_2.csv"


@pytest.mark.parametrize("text", ["1000", " 1000 ", "1,000", "1"])
def test_parse_chunk_size_accepts_common_inputs(text):
    assert parse_chunk_size(text) == int(text.replace(",", "").strip())


@pytest.mark.parametrize("text", ["", "abc", "0", "-5", "1.5", "1000001"])
def test_parse_chunk_size_rejects_invalid(text):
    with pytest.raises(ValidationError) as info:
        parse_chunk_size(text)
    assert info.value.key == "err.invalid_chunk_size"


def test_parse_num_format_returns_digit_count():
    assert parse_num_format("001") == 3
    assert parse_num_format("1") == 1
    assert parse_num_format("0000000000") == 10


@pytest.mark.parametrize("text", ["", "03d", "abc", "0" * 11, "１２３", "1 2"])
def test_parse_num_format_rejects_invalid(text):
    with pytest.raises(ValidationError) as info:
        parse_num_format(text)
    assert info.value.key == "err.invalid_number"


def test_parse_num_format_rejects_pathological_length():
    """原始实现允许输入 ``1000``，会生成 1000 字符的文件名并必然写入失败。"""
    with pytest.raises(ValidationError):
        parse_num_format("1" + "0" * 999)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 B"), (512, "512 B"), (2048, "2.0 KB"), (5 * 1024 * 1024, "5.0 MB")],
)
def test_human_size(value, expected):
    assert human_size(value) == expected
