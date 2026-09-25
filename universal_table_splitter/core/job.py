"""任务编排：参数校验、预检、执行、进度回调与协作式取消。

这是核心层唯一的"入口函数" ``run_split``：不 import tkinter，
UI 与 CLI 都通过它驱动业务，因此可以被单元测试完整覆盖。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from ..config import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_EXPORT_FORMAT,
    MAX_CHUNK_SIZE,
    MAX_NUM_DIGITS,
    MIN_CHUNK_SIZE,
    MIN_NUM_DIGITS,
    PROGRESS_MIN_INTERVAL_S,
)
from ..errors import AppError, CanceledByUser, FileFormatError, OutputError, ValidationError
from .plan import build_output_name, chunk_count, format_suffix
from .readers import ReadOptions, SourceInfo, is_supported, open_table
from .writers import (
    EXPORT_FORMATS,
    ConflictPolicy,
    get_spec,
    resolve_conflict,
    translate_os_error,
    write_chunk,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SplitJob:
    """一次分割任务的完整描述。不可变，便于跨线程安全传递。"""

    input_path: Path
    output_dir: Path
    chunk_size: int = DEFAULT_CHUNK_SIZE
    digits: int = len("001")
    export_format: str = DEFAULT_EXPORT_FORMAT
    sheet: str | None = None
    fidelity: bool = True
    escape_formulas: bool = False
    conflict_policy: ConflictPolicy = ConflictPolicy.OVERWRITE
    total_rows: int | None = None
    force_stream: bool = False

    @property
    def base_name(self) -> str:
        return self.input_path.stem

    @property
    def read_options(self) -> ReadOptions:
        return ReadOptions(
            fidelity=self.fidelity,
            sheet=self.sheet,
            force_stream=self.force_stream,
        )

    def output_name(self, index: int) -> str:
        spec = get_spec(self.export_format)
        return build_output_name(self.base_name, format_suffix(index, self.digits), spec.ext)

    def output_path(self, index: int) -> Path:
        return self.output_dir / self.output_name(index)


@dataclass(frozen=True)
class ProgressEvent:
    index: int
    rows_written: int
    total_rows: int | None
    path: Path


@dataclass(frozen=True)
class SplitResult:
    files: tuple[Path, ...]
    rows: int
    elapsed_s: float
    canceled: bool = False
    source: SourceInfo | None = None


@dataclass
class Preflight:
    """执行前的预检结果，用于"文件数量"与"覆盖冲突"确认。

    ``handle`` 是预检阶段已经打开的数据源：把它交给 ``run_split``，
    可以避免"预检读一遍、执行再读一遍"的重复 I/O（对 30MB CSV 省掉约 3 秒，
    对需要全量载入的格式省掉一整次载入）。

    所有权约定：``handle`` 交给 ``run_split`` 后由 ``run_split`` 负责关闭；
    若决定不执行，必须显式调用 ``close()``。
    """

    job: SplitJob
    total_rows: int | None
    file_count: int
    conflicts: tuple[Path, ...]
    source: SourceInfo
    handle: object | None = None

    def close(self) -> None:
        """释放仍在手中的数据源。"""
        if self.handle is None:
            return
        handle, self.handle = self.handle, None
        closer = getattr(handle, "close", None)
        if callable(closer):
            closer()


# --------------------------------------------------------------------------- 校验


def _output_errors(output_dir: Path) -> list[AppError]:
    """校验输出目录：目录本身没问题时，退化为检查"最近的存在祖先"是否可写。

    这样既能接受 ``out/a/b`` 这种还不存在的多级目录（执行时会 ``mkdir(parents=True)``），
    也能提前拦住"路径中间夹着一个文件"这类必然失败的情况。
    """
    probe = output_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.is_dir():
        return [OutputError("err.output_not_dir", path=str(probe))]
    if not os.access(probe, os.W_OK):
        return [OutputError("err.output_not_writable", path=str(probe))]
    return []


def collect_errors(job: SplitJob, *, check_output: bool = True) -> list[AppError]:
    """纯校验：收集全部问题，不做任何 UI 副作用，便于测试与批量调用。"""
    errors: list[AppError] = []
    path = job.input_path
    if not str(path).strip():
        errors.append(FileFormatError("err.invalid_file"))
    elif not path.exists():
        errors.append(AppError("err.file_missing", path=str(path)))
    elif not path.is_file():
        errors.append(AppError("err.not_a_file", path=str(path)))
    elif not is_supported(path):
        errors.append(FileFormatError("err.invalid_file"))

    if not (MIN_CHUNK_SIZE <= job.chunk_size <= MAX_CHUNK_SIZE):
        errors.append(
            ValidationError("err.invalid_chunk_size", min=MIN_CHUNK_SIZE, max=MAX_CHUNK_SIZE)
        )
    if not (MIN_NUM_DIGITS <= job.digits <= MAX_NUM_DIGITS):
        errors.append(ValidationError("err.invalid_number", min=MIN_NUM_DIGITS, max=MAX_NUM_DIGITS))
    if job.export_format not in EXPORT_FORMATS:
        errors.append(AppError("err.invalid_export_format", fmt=job.export_format))
    if check_output:
        errors.extend(_output_errors(job.output_dir))
    return errors


def validate_job(job: SplitJob) -> None:
    errors = collect_errors(job)
    if errors:
        raise errors[0]


# --------------------------------------------------------------------------- 预检


def preflight(job: SplitJob, *, cancel=None, keep_open: bool = True) -> Preflight:
    """打开数据源统计行数，并算出输出文件数量与已存在的同名文件。

    默认保留已打开的数据源（``keep_open=True``），交给 ``run_split`` 复用，
    从而只读一遍文件。若调用方不打算继续执行，需要自行 ``close()``。
    """
    validate_job(job)
    source = open_table(job.input_path, job.read_options, cancel)
    try:
        info: SourceInfo = source.info
        total = info.total_rows
        conflicts: tuple[Path, ...] = ()
        file_count = 0
        if total is not None and total > 0:
            file_count = chunk_count(total, job.chunk_size)
            if job.conflict_policy is ConflictPolicy.OVERWRITE:
                conflicts = tuple(
                    path
                    for index in range(1, file_count + 1)
                    if (path := job.output_path(index)).exists()
                )
    except BaseException:
        source.close()
        raise
    if not keep_open:
        source.close()
        source = None  # type: ignore[assignment]
    return Preflight(
        job=job,
        total_rows=total,
        file_count=file_count,
        conflicts=conflicts,
        source=info,
        handle=source,
    )


# --------------------------------------------------------------------------- 执行


def run_split(
    job: SplitJob,
    *,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    cancel=None,
    source=None,
) -> SplitResult:
    """执行分割。

    - ``cancel``：任意带 ``is_set()`` 的对象（如 ``threading.Event``），
      在分块边界检查，命中即抛 ``CanceledByUser``（携带已完成的部分结果）；
    - ``source``：可选的已打开数据源（通常来自 ``Preflight.handle``），
      传入时由本函数负责关闭，避免重复读取；留空则自行打开；
    - 取消是**协作式**的：写入是原子的，因此不会留下半写的文件。
    """
    started = time.perf_counter()
    validate_job(job)
    spec = get_spec(job.export_format)
    try:
        job.output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise translate_os_error(exc, job.output_dir) from exc

    written: list[Path] = []
    rows = 0
    index = 0
    info: SourceInfo | None = None
    try:
        if source is None:
            source = open_table(job.input_path, job.read_options, cancel)
        info = source.info
        total = job.total_rows if job.total_rows is not None else info.total_rows
        last_emit = 0.0
        for chunk in source.iter_chunks(job.chunk_size, cancel=cancel):
            if cancel is not None and cancel.is_set():
                raise CanceledByUser(_partial(written, rows, started, info))
            index += 1
            target = resolve_conflict(job.output_path(index), job.conflict_policy)
            try:
                write_chunk(chunk, target, spec, escape_formulas=job.escape_formulas)
            except OSError as exc:
                raise translate_os_error(exc, target) from exc
            written.append(target)
            rows += len(chunk)
            now = time.perf_counter()
            if on_progress is not None and now - last_emit >= PROGRESS_MIN_INTERVAL_S:
                last_emit = now
                on_progress(ProgressEvent(index, rows, total, target))
        # 迭代器在检查到取消后会直接停止产出，因此循环退出后必须再判一次，
        # 否则"取消"会被当成"正常完成"，界面会报告成功。
        if cancel is not None and cancel.is_set():
            raise CanceledByUser(_partial(written, rows, started, info))
        if index == 0:
            raise AppError("err.empty_table")
        if on_progress is not None:
            on_progress(ProgressEvent(index, rows, total, written[-1]))
        logger.info("split finished: %d files, %d rows", len(written), rows)
        return SplitResult(tuple(written), rows, time.perf_counter() - started, False, info)
    except MemoryError as exc:
        logger.exception("out of memory while splitting")
        raise AppError("err.out_of_memory") from exc
    except UnicodeDecodeError as exc:
        raise AppError("err.encoding", path=str(job.input_path)) from exc
    except pd.errors.EmptyDataError as exc:
        raise AppError("err.empty_table") from exc
    except pd.errors.ParserError as exc:
        raise AppError("err.read_failed", message=str(exc)) from exc
    except OSError as exc:
        raise AppError("err.read_failed", message=exc.strerror or str(exc)) from exc
    finally:
        if source is not None:
            source.close()


def _partial(
    written: Sequence[Path], rows: int, started: float, info: SourceInfo | None
) -> SplitResult:
    return SplitResult(tuple(written), rows, time.perf_counter() - started, True, info)


def cleanup_files(paths: Sequence[Path]) -> int:
    """删除指定文件，返回实际删除的数量（用于清理未完成任务的产物）。"""
    removed = 0
    for path in paths:
        if not path.exists():
            continue
        try:
            path.unlink()
            removed += 1
            logger.info("removed partial output %s", path)
        except OSError:
            logger.warning("failed to remove %s", path, exc_info=True)
    return removed
