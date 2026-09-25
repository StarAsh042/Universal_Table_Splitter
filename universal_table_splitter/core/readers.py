"""输入读取层：编码探测、分隔符嗅探、按需流式分块。

关键设计：
1. **编码回退**：中文 CSV 大量是 GBK/GB18030，原实现固定 UTF-8 会直接抛
   ``UnicodeDecodeError``；这里按 BOM → UTF-8 → GB18030 → Big5 → Latin-1 依次探测。
2. **体量自适应**：小文件一次性载入（更快，实测 30MB 约 2.9s），大文件强制流式
   （内存有界，实测峰值不随文件增长）。
3. **容器嗅探**：按 magic bytes 判断 xlsx(zip)/xls(OLE2)，文件后缀写错也能读。
4. **安全**：xlsx 读取前检查解压比，防御解压炸弹；需要全量载入的格式有体积上限。
"""

from __future__ import annotations

import codecs
import csv
import logging
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable

import pandas as pd

from ..config import (
    CANCEL_CHECK_INTERVAL,
    MAX_FULL_LOAD_BYTES,
    MAX_INFLATE_RATIO,
    STREAM_READ_THRESHOLD_BYTES,
)
from ..errors import AppError, CanceledByUser, DependencyError, FileFormatError
from .deps import is_available
from .plan import chunk_bounds, human_size
from .writers import export_formats

logger = logging.getLogger(__name__)

DEFAULT_ENCODINGS: tuple[str, ...] = (
    "utf-8",  # 带 BOM 的 UTF-8 已在 detect_encoding 中单独识别为 utf-8-sig
    "gb18030",  # gbk / gb2312 的超集，覆盖绝大多数中文 CSV
    "big5",
    "cp1252",
    "latin-1",  # 永不失败的兜底
)

_SAMPLE_BYTES = 1 << 16
_CANDIDATE_SEPARATORS = ",;\t|"
_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


# --------------------------------------------------------------------------- 编码


def _read_sample_bytes(path: Path, size: int = _SAMPLE_BYTES) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)


def _can_decode(data: bytes, encoding: str) -> bool:
    """用增量解码器判断样本能否被该编码完整解析（容忍样本尾部被截断的多字节字符）。"""
    decoder = codecs.getincrementaldecoder(encoding)()
    try:
        decoder.decode(data)
    except UnicodeDecodeError:
        return False
    return True


def detect_encoding(path: Path, candidates: Sequence[str] = DEFAULT_ENCODINGS) -> str:
    """探测文本编码；全部失败时返回最后的兜底编码。"""
    data = _read_sample_bytes(path)
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    for encoding in candidates:
        if _can_decode(data, encoding):
            return encoding
    return candidates[-1]


def sniff_delimiter(sample: str, default: str) -> str:
    """嗅探分隔符：默认分隔符出现时不改变行为，仅在默认缺失时启用 csv.Sniffer。"""
    header = sample.splitlines()[0] if sample.splitlines() else ""
    if default and default in header:
        return default
    try:
        return csv.Sniffer().sniff(sample, delimiters=_CANDIDATE_SEPARATORS).delimiter
    except csv.Error:
        return default


def count_delimited_rows(
    path: Path,
    encoding: str,
    separator: str,
    cancel=None,
) -> int:
    """统计数据行数（不含表头），与 pandas 的 ``skip_blank_lines=True`` 行为对齐。

    使用 C 实现的 ``csv.reader``，32MB 文件约 1 秒，换来的是**可用的确定型进度条**。
    """
    rows = 0
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.reader(handle, delimiter=separator)
        for index, row in enumerate(reader):
            if index and row:  # 跳过表头与空行
                rows += 1
            due = index % CANCEL_CHECK_INTERVAL == 0
            if index and due and cancel is not None and cancel.is_set():
                raise CanceledByUser()
    return rows


# --------------------------------------------------------------------------- 选项


@dataclass(frozen=True)
class ReadOptions:
    """读取选项。

    ``fidelity=True`` 时以文本方式读取（``dtype=str`` + ``keep_default_na=False``），
    避免前导零丢失、长数字变科学计数法、整数列因空值变成 ``1.0`` 等静默失真。
    """

    fidelity: bool = True
    sheet: str | None = None
    force_stream: bool = False
    encodings: tuple[str, ...] = DEFAULT_ENCODINGS


def _fidelity_kwargs(fidelity: bool) -> dict[str, object]:
    return {"dtype": str, "keep_default_na": False} if fidelity else {}


# --------------------------------------------------------------------------- 数据源


@dataclass(frozen=True)
class SourceInfo:
    encoding: str | None = None
    sheet: str | None = None
    total_rows: int | None = None
    streaming: bool = False


class DelimitedSource:
    """CSV / TSV：小文件一次性载入，大文件流式分块。"""

    def __init__(
        self,
        path: Path,
        default_separator: str,
        options: ReadOptions,
        cancel=None,
    ) -> None:
        self.path = path
        self._options = options
        self.encoding: str | None = detect_encoding(path, options.encodings)
        sample = _read_sample_bytes(path).decode(self.encoding, errors="replace")
        self._separator = sniff_delimiter(sample, default_separator)
        self._kwargs = _fidelity_kwargs(options.fidelity)
        self.sheet: str | None = None
        self._frame: pd.DataFrame | None = None
        size = path.stat().st_size
        self.streaming = options.force_stream or size > STREAM_READ_THRESHOLD_BYTES
        if self.streaming:
            # 统计行数是流式模式下的必经步骤（用于确定型进度条），因此要能被打断
            self.total_rows: int | None = count_delimited_rows(
                path, self.encoding, self._separator, cancel=cancel
            )
        else:
            self._frame = pd.read_csv(
                path,
                sep=self._separator,
                encoding=self.encoding,
                **self._kwargs,  # type: ignore[arg-type]
            )
            self.total_rows = len(self._frame)
        logger.info(
            "opened %s (encoding=%s, sep=%r, streaming=%s, rows=%s)",
            path.name,
            self.encoding,
            self._separator,
            self.streaming,
            self.total_rows,
        )

    @property
    def info(self) -> SourceInfo:
        return SourceInfo(
            encoding=self.encoding,
            sheet=self.sheet,
            total_rows=self.total_rows,
            streaming=self.streaming,
        )

    def iter_chunks(self, size: int, cancel=None) -> Iterator[pd.DataFrame]:
        if self._frame is not None:
            for start, stop in chunk_bounds(len(self._frame), size):
                if cancel is not None and cancel.is_set():
                    return
                yield self._frame.iloc[start:stop]
            return
        reader = pd.read_csv(
            self.path,
            sep=self._separator,
            encoding=self.encoding,
            chunksize=size,
            **self._kwargs,  # type: ignore[arg-type]
        )
        for chunk in reader:
            if cancel is not None and cancel.is_set():
                return
            yield chunk

    def close(self) -> None:
        self._frame = None


class ExcelSource:
    """Excel：xlsx 走 openpyxl 只读流式（内存有界），xls 走 xlrd 全量载入。"""

    def __init__(self, path: Path, options: ReadOptions, cancel=None) -> None:
        self.path = path
        self._options = options
        self.encoding: str | None = None
        self.sheet: str | None = None
        self._frame: pd.DataFrame | None = None
        self._workbook = None
        self._worksheet = None
        container = _sniff_container(path)
        if container == "zip":
            self._open_zip(path, options)
        elif container == "ole2":
            self._open_legacy(path, options)
        else:
            raise FileFormatError("err.invalid_file")

    # -- 打开 -----------------------------------------------------------------
    def _open_zip(self, path: Path, options: ReadOptions) -> None:
        if not is_available("openpyxl"):
            raise DependencyError(name="openpyxl", hint="openpyxl")
        _check_inflate_ratio(path)
        import openpyxl

        try:
            self._workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except (zipfile.BadZipFile, OSError, KeyError, ValueError) as exc:
            raise FileFormatError("err.invalid_file") from exc
        names = tuple(self._workbook.sheetnames)
        if not names:
            raise AppError("err.no_sheets")
        name = _pick_sheet(names, options.sheet)
        self.sheet = name
        self._worksheet = self._workbook[name]
        max_row = getattr(self._worksheet, "max_row", None)
        self.total_rows: int | None = max(int(max_row) - 1, 0) if isinstance(max_row, int) else None
        self.streaming = True
        logger.info("opened %s (sheet=%s, rows=%s)", path.name, name, self.total_rows)

    def _open_legacy(self, path: Path, options: ReadOptions) -> None:
        if not is_available("xlrd"):
            raise DependencyError(name="xlrd", hint="xlrd")
        _ensure_full_load_size(path, "Excel .xls")
        sheet: str | int = options.sheet if options.sheet is not None else 0
        try:
            self._frame = pd.read_excel(
                path,
                sheet_name=sheet,
                **_fidelity_kwargs(options.fidelity),  # type: ignore[arg-type]
            )
        except ValueError as exc:
            if options.sheet is not None:
                raise AppError("err.sheet_not_found", sheet=options.sheet) from exc
            raise
        self.sheet = str(options.sheet) if options.sheet is not None else None
        self.total_rows = len(self._frame)
        self.streaming = False

    # -- 读取 -----------------------------------------------------------------
    @property
    def info(self) -> SourceInfo:
        return SourceInfo(
            encoding=self.encoding,
            sheet=self.sheet,
            total_rows=self.total_rows,
            streaming=self.streaming,
        )

    def iter_chunks(self, size: int, cancel=None) -> Iterator[pd.DataFrame]:
        if self._frame is not None:
            for start, stop in chunk_bounds(len(self._frame), size):
                if cancel is not None and cancel.is_set():
                    return
                yield self._frame.iloc[start:stop]
            return
        worksheet = self._worksheet
        if worksheet is None:  # pragma: no cover - 构造失败时不会走到这里
            return
        rows = worksheet.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            return
        columns = _normalize_columns(header)
        width = len(columns)
        fidelity = self._options.fidelity
        buffer: list[list[object]] = []
        for row in rows:
            if cancel is not None and cancel.is_set():
                return
            buffer.append([_stringify(v) if fidelity else v for v in _fit(row, width)])
            if len(buffer) >= size:
                yield pd.DataFrame(buffer, columns=columns)
                buffer = []
        if buffer:
            yield pd.DataFrame(buffer, columns=columns)

    def close(self) -> None:
        self._frame = None
        self._worksheet = None
        if self._workbook is not None:
            try:
                self._workbook.close()
            except Exception:  # pragma: no cover - 关闭失败不影响结果
                logger.debug("closing workbook failed", exc_info=True)
            self._workbook = None


class JsonSource:
    """JSON / JSON Lines：需要完整解析，因此带体积上限。"""

    def __init__(self, path: Path, options: ReadOptions, cancel=None, lines: bool = False) -> None:
        self.path = path
        self._options = options
        self.encoding: str | None = detect_encoding(path, options.encodings)
        self.sheet: str | None = None
        self.streaming = False
        self._frame = _read_json(path, options, self.encoding, lines)
        self.total_rows = len(self._frame)

    @property
    def info(self) -> SourceInfo:
        return SourceInfo(
            encoding=self.encoding,
            sheet=self.sheet,
            total_rows=self.total_rows,
            streaming=self.streaming,
        )

    def iter_chunks(self, size: int, cancel=None) -> Iterator[pd.DataFrame]:
        assert self._frame is not None
        for start, stop in chunk_bounds(len(self._frame), size):
            if cancel is not None and cancel.is_set():
                return
            yield self._frame.iloc[start:stop]

    def close(self) -> None:
        self._frame = None


# --------------------------------------------------------------------------- 辅助


def _sniff_container(path: Path) -> str:
    """按 magic bytes 判断容器类型，容忍后缀写错的常见情况。"""
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError as exc:
        raise AppError("err.read_failed", message=str(exc)) from exc
    if head.startswith(_ZIP_MAGIC):
        return "zip"
    if head.startswith(_OLE2_MAGIC):
        return "ole2"
    return "unknown"


def _check_inflate_ratio(path: Path, limit: int = MAX_INFLATE_RATIO) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            inflated = sum(item.file_size for item in archive.infolist())
    except (zipfile.BadZipFile, OSError) as exc:
        raise FileFormatError("err.invalid_file") from exc
    compressed = max(path.stat().st_size, 1)
    ratio = inflated / compressed
    if ratio > limit:
        logger.warning("suspicious inflate ratio %.0fx for %s", ratio, path.name)
        raise AppError("err.suspicious_file", ratio=f"{ratio:.0f}")


def _ensure_full_load_size(path: Path, label: str) -> None:
    size = path.stat().st_size
    if size > MAX_FULL_LOAD_BYTES:
        raise AppError(
            "err.file_too_large",
            fmt=label,
            size=human_size(size),
            limit=human_size(MAX_FULL_LOAD_BYTES),
        )


def _pick_sheet(names: Sequence[str], requested: str | None) -> str:
    if requested is None:
        return names[0]
    if requested in names:
        return requested
    raise AppError("err.sheet_not_found", sheet=requested)


def _normalize_columns(header: Sequence[object]) -> list[str]:
    """对齐 pandas 的列名规则：空列名补 ``Unnamed: i``，重名追加序号。"""
    seen: dict[str, int] = {}
    columns: list[str] = []
    for index, value in enumerate(header):
        name = "" if value is None else str(value).strip()
        if not name:
            name = f"Unnamed: {index}"
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        columns.append(name)
    return columns


def _fit(row: Sequence[object], width: int) -> Sequence[object]:
    """把参差不齐的行补齐/截断到表头宽度，避免 DataFrame 构造失败。"""
    row = tuple(row)
    if len(row) == width:
        return row
    if len(row) < width:
        return row + (None,) * (width - len(row))
    return row[:width]


def _stringify(value: object) -> str:
    """把单元格值转成与 ``pandas.astype(str)`` 一致的文本形式。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _read_json(path: Path, options: ReadOptions, encoding: str, lines: bool) -> pd.DataFrame:
    _ensure_full_load_size(path, "JSON")
    kwargs: dict[str, object] = {"encoding": encoding}
    if options.fidelity:
        kwargs["dtype"] = str
        kwargs["convert_dates"] = False
    try:
        return pd.read_json(path, lines=lines, **kwargs)  # type: ignore[arg-type]
    except ValueError as exc:
        if not lines:
            # JSON Lines（每行一个对象）是流式导出的常见形态，自动兜底
            try:
                return pd.read_json(path, lines=True, **kwargs)  # type: ignore[arg-type]
            except ValueError:
                pass
        raise AppError("err.json_parse") from exc


# --------------------------------------------------------------------------- 注册表


@dataclass(frozen=True)
class InputFormat:
    key: str
    extensions: tuple[str, ...]
    export_formats: tuple[str, ...]
    opener: Callable[..., object]


def _open_csv(path: Path, options: ReadOptions, cancel=None) -> DelimitedSource:
    return DelimitedSource(path, ",", options, cancel)


def _open_tsv(path: Path, options: ReadOptions, cancel=None) -> DelimitedSource:
    return DelimitedSource(path, "\t", options, cancel)


def _open_excel(path: Path, options: ReadOptions, cancel=None) -> ExcelSource:
    return ExcelSource(path, options, cancel)


def _open_json(path: Path, options: ReadOptions, cancel=None) -> JsonSource:
    return JsonSource(path, options, cancel, lines=False)


def _open_json_lines(path: Path, options: ReadOptions, cancel=None) -> JsonSource:
    return JsonSource(path, options, cancel, lines=True)


def _exports(*preferred: str) -> tuple[str, ...]:
    """候选导出格式：优先保留与输入同族/更自然的格式，其余按固定顺序补齐。

    列表的**首项**同时也是 CLI 未显式指定 ``--format`` 时的默认值，
    因此 ``.json`` 输入默认导出 ``.json``、``.xlsx`` 输入默认导出 ``.xlsx``。
    """
    ordered = tuple(dict.fromkeys(preferred))
    return ordered + tuple(fmt for fmt in export_formats() if fmt not in ordered)


_CSV_EXPORTS = _exports("csv", "xlsx", "tsv", "json", "html")
_TSV_EXPORTS = _exports("tsv", "csv", "xlsx", "json", "html")
_EXCEL_EXPORTS = _exports("xlsx", "csv", "tsv", "json", "html")
_JSON_EXPORTS = _exports("json", "csv", "xlsx", "tsv", "html")

INPUT_FORMATS: Mapping[str, InputFormat] = MappingProxyType(
    {
        ".csv": InputFormat("csv", (".csv",), _CSV_EXPORTS, _open_csv),
        ".tsv": InputFormat("tsv", (".tsv",), _TSV_EXPORTS, _open_tsv),
        ".xlsx": InputFormat("xlsx", (".xlsx", ".xlsm"), _EXCEL_EXPORTS, _open_excel),
        # .xls 无法再写出 .xls（pandas 2.x 已移除 xlwt），因此默认导出 .xlsx
        ".xls": InputFormat("xls", (".xls",), _EXCEL_EXPORTS, _open_excel),
        ".json": InputFormat("json", (".json",), _JSON_EXPORTS, _open_json),
        ".jsonl": InputFormat("jsonl", (".jsonl",), _JSON_EXPORTS, _open_json_lines),
    }
)


def supported_extensions() -> tuple[str, ...]:
    return tuple(INPUT_FORMATS)


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in INPUT_FORMATS


def export_formats_for(path: Path) -> tuple[str, ...]:
    """该输入文件可选的导出格式（首项即默认值）；未知扩展名时返回全部格式。"""
    spec = INPUT_FORMATS.get(path.suffix.lower())
    return spec.export_formats if spec else export_formats()


def open_table(path: Path, options: ReadOptions, cancel=None) -> object:
    """按扩展名打开数据源；不支持的类型抛出 ``FileFormatError``。"""
    spec = INPUT_FORMATS.get(path.suffix.lower())
    if spec is None:
        raise FileFormatError("err.invalid_file")
    return spec.opener(path, options, cancel)


def list_sheets(path: Path) -> tuple[str, ...]:
    """探测工作表名称；非 Excel 或探测失败时返回空元组（不抛异常，供 UI 预填）。"""
    container = "unknown"
    try:
        container = _sniff_container(path)
    except AppError:
        return ()
    if container == "zip":
        if not is_available("openpyxl"):
            return ()
        import openpyxl

        try:
            workbook = openpyxl.load_workbook(path, read_only=True)
        except Exception:
            logger.debug("probe sheets failed", exc_info=True)
            return ()
        try:
            return tuple(workbook.sheetnames)
        finally:
            workbook.close()
    if container == "ole2":
        if not is_available("xlrd"):
            return ()
        try:
            with pd.ExcelFile(path) as book:
                return tuple(str(name) for name in book.sheet_names)
        except Exception:
            logger.debug("probe sheets failed", exc_info=True)
            return ()
    return ()
