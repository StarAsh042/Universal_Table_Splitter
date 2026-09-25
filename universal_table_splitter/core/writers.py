"""输出写出层：导出注册表、原子写入、公式注入防护。

修复的原始问题：
- ``EXPORT_FORMATS`` 用"方法名字符串 + getattr 反射"调度，重构不安全；
- ``.xls`` 导出在 pandas >= 2.0 下必然失败（``No engine for filetype: 'xls'``）；
- ``to_csv`` 默认写无 BOM 的 UTF-8，中文在 Excel 里显示为乱码；
- 直接写最终路径，写到一半失败会留下无法分辨的半成品文件。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Callable
from uuid import uuid4

import pandas as pd

from ..errors import AppError, OutputError
from .plan import build_output_name

logger = logging.getLogger(__name__)

#: Excel 会把以这些字符开头的单元格当作公式执行（OWASP CSV Injection）
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_MAX_CONFLICT_ATTEMPTS = 1_000


class ConflictPolicy(str, Enum):
    """同名输出文件的处理策略。"""

    OVERWRITE = "overwrite"
    INDEX = "index"


@dataclass(frozen=True)
class ExportSpec:
    key: str
    ext: str
    write: Callable[[pd.DataFrame, Path], None]
    text_based: bool = False

    def __call__(self, frame: pd.DataFrame, path: Path) -> None:
        self.write(frame, path)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    # utf-8-sig（带 BOM）才能让 Excel 正确识别中文
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _write_tsv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, sep="\t", encoding="utf-8-sig")


def _write_xlsx(frame: pd.DataFrame, path: Path) -> None:
    frame.to_excel(path, index=False, engine="openpyxl")


def _write_json(frame: pd.DataFrame, path: Path) -> None:
    # force_ascii=False：避免中文被写成 \uXXXX 转义
    frame.to_json(path, orient="records", force_ascii=False, indent=2)


def _write_html(frame: pd.DataFrame, path: Path) -> None:
    # escape=True（默认）：防止单元格内容注入 HTML/脚本
    frame.to_html(path, index=False, escape=True)


EXPORT_FORMATS: Mapping[str, ExportSpec] = MappingProxyType(
    {
        "csv": ExportSpec("csv", ".csv", _write_csv, text_based=True),
        "tsv": ExportSpec("tsv", ".tsv", _write_tsv, text_based=True),
        "xlsx": ExportSpec("xlsx", ".xlsx", _write_xlsx),
        "json": ExportSpec("json", ".json", _write_json),
        "html": ExportSpec("html", ".html", _write_html, text_based=True),
    }
)


def export_formats() -> tuple[str, ...]:
    return tuple(EXPORT_FORMATS)


def get_spec(key: str) -> ExportSpec:
    spec = EXPORT_FORMATS.get(key)
    if spec is None:
        raise AppError("err.invalid_export_format", fmt=key)
    return spec


def _is_formula_like(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_FORMULA_PREFIXES)


def escape_formula_cells(frame: pd.DataFrame) -> pd.DataFrame:
    """给可能被 Excel 当作公式的单元格加前导单引号。

    注意：这会**改变单元格内容**（Excel 中会看到多一个 ``'``），
    因此默认关闭，仅在用户显式勾选时启用。
    """
    if frame.empty:
        return frame
    result = frame.copy()
    for column in result.columns:
        series = result[column]
        if series.dtype != object:
            continue
        mask = series.map(_is_formula_like)
        if not bool(mask.any()):
            continue
        result[column] = series.where(~mask, series[mask].astype(str).radd("'"))
        logger.info("escaped %d formula-like cells in column %r", int(mask.sum()), column)
    return result


def resolve_conflict(target: Path, policy: ConflictPolicy) -> Path:
    """按策略处理同名文件：覆盖，或追加 ``_1``、``_2`` 序号保留原文件。"""
    if policy is ConflictPolicy.OVERWRITE or not target.exists():
        return target
    for index in range(1, _MAX_CONFLICT_ATTEMPTS):
        candidate = target.with_name(build_output_name(target.stem, "", target.suffix, index))
        if not candidate.exists():
            return candidate
    return target.with_name(build_output_name(target.stem, uuid4().hex[:8], target.suffix))


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - 清理失败不影响主异常
        logger.debug("failed to remove temp file %s", path, exc_info=True)


def write_chunk(
    frame: pd.DataFrame,
    target: Path,
    spec: ExportSpec,
    *,
    escape_formulas: bool = False,
) -> Path:
    """原子写入单个分块：先写临时文件再 ``os.replace``，失败时清理临时文件。

    临时文件名保留真实扩展名（``.xlsx`` 等），否则 pandas 无法推断写入引擎。
    """
    data = escape_formula_cells(frame) if escape_formulas else frame
    temp = target.with_name(f".{target.stem}.{uuid4().hex[:8]}.part{spec.ext}")
    try:
        spec(data, temp)
        os.replace(temp, target)
    except BaseException:
        _remove_quietly(temp)
        raise
    return target


def translate_os_error(exc: OSError, path: Path) -> OutputError:
    """把底层 OS 错误翻译成可本地化的业务异常。"""
    import errno

    if exc.errno in (errno.EACCES, errno.EPERM):
        return OutputError("err.permission", path=str(path))
    if exc.errno == errno.ENOSPC:
        return OutputError("err.disk_full", path=str(path))
    return OutputError("err.write_failed", message=exc.strerror or str(exc))
