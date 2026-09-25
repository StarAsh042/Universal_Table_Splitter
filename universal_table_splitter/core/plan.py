"""纯函数：分块计划、编号生成与用户输入解析。

本模块**不依赖 pandas、tkinter 或文件系统**，因此可以被单元测试完整覆盖，
也是"核心逻辑与 UI 解耦"的关键一环。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ..config import (
    MAX_CHUNK_SIZE,
    MAX_NUM_DIGITS,
    MIN_CHUNK_SIZE,
    MIN_NUM_DIGITS,
)
from ..errors import ValidationError


def parse_chunk_size(text: str) -> int:
    """把用户输入解析成"每份行数"，非法输入抛出携带 i18n key 的异常。"""
    raw = (text or "").strip().replace(",", "").replace("，", "").replace(" ", "")
    if not raw:
        raise ValidationError("err.invalid_chunk_size", min=MIN_CHUNK_SIZE, max=MAX_CHUNK_SIZE)
    try:
        value = int(raw)
    except ValueError:
        raise ValidationError(
            "err.invalid_chunk_size", min=MIN_CHUNK_SIZE, max=MAX_CHUNK_SIZE
        ) from None
    if not (MIN_CHUNK_SIZE <= value <= MAX_CHUNK_SIZE):
        raise ValidationError("err.invalid_chunk_size", min=MIN_CHUNK_SIZE, max=MAX_CHUNK_SIZE)
    return value


def parse_num_format(text: str) -> int:
    """把"编号格式"输入解析为**编号位数**。

    原实现把该输入当作 Python 格式说明符塞进 ``f"{i:{num_format}}"``，
    实测 ``f"{5:001}"`` 得到的是 ``'5'``（误导性用法），真正生效的是 ``zfill``。
    这里把语义显式化为"位数"，并限制在 ``MIN_NUM_DIGITS``~``MAX_NUM_DIGITS``，
    避免出现超长文件名（原实现输入 ``1000`` 会生成 1000 字符的文件名）。
    """
    raw = (text or "").strip()
    if not raw or not raw.isascii() or not raw.isdigit():
        raise ValidationError("err.invalid_number", min=MIN_NUM_DIGITS, max=MAX_NUM_DIGITS)
    digits = len(raw)
    if not (MIN_NUM_DIGITS <= digits <= MAX_NUM_DIGITS):
        raise ValidationError("err.invalid_number", min=MIN_NUM_DIGITS, max=MAX_NUM_DIGITS)
    return digits


def format_suffix(index: int, digits: int) -> str:
    """生成分块编号：``index`` 从 1 开始，超出位数时自然增宽（999 -> 1000）。"""
    if index < 1:
        raise ValueError("index must be >= 1")
    if digits < 1:
        raise ValueError("digits must be >= 1")
    return str(index).zfill(digits)


def chunk_count(total: int, chunk_size: int) -> int:
    """按行数与每份行数计算输出文件数量。"""
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    if total <= 0:
        return 0
    return -(-total // chunk_size)


def chunk_bounds(total: int, chunk_size: int) -> Iterator[tuple[int, int]]:
    """依次产出 ``(start, stop)`` 左闭右开区间，末块不越界。"""
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    for start in range(0, max(total, 0), chunk_size):
        yield start, min(start + chunk_size, total)


def plan_chunks(total: int, chunk_size: int) -> list[tuple[int, int]]:
    """``chunk_bounds`` 的列表形式，便于断言与预检。"""
    return list(chunk_bounds(total, chunk_size))


def build_output_name(base: str, suffix: str, ext: str, index_suffix: int | None = None) -> str:
    """拼装输出文件名；``index_suffix`` 用于冲突时追加序号。

    ``base="art", suffix="001"`` -> ``art_001.csv``；
    ``base="art_001", suffix="", index_suffix=2`` -> ``art_001_2.csv``。
    """
    separator = "_" if suffix else ""
    extra = f"_{index_suffix}" if index_suffix else ""
    return f"{base}{separator}{suffix}{extra}{ext}"


def human_size(num_bytes: float) -> str:
    """把字节数格式化成人类可读的字符串。"""
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def guess_output_dir(input_path: Path) -> Path:
    """默认输出目录 = 输入文件所在目录。"""
    return input_path.parent if str(input_path.parent) else Path(".")
