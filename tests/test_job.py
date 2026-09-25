"""任务编排测试：校验、预检、执行、取消、冲突策略与失败清理。"""

from __future__ import annotations

import errno
import threading
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from universal_table_splitter.core import writers as writers_module
from universal_table_splitter.core.job import (
    SplitJob,
    cleanup_files,
    collect_errors,
    preflight,
    run_split,
)
from universal_table_splitter.core.writers import ConflictPolicy, ExportSpec
from universal_table_splitter.errors import AppError, CanceledByUser

from .conftest import ROW_COUNT


def make_job(csv: Path, out: Path, **overrides) -> SplitJob:
    params = {
        "input_path": csv,
        "output_dir": out,
        "chunk_size": 3,
        "digits": 3,
        "export_format": "csv",
        "fidelity": True,
    }
    params.update(overrides)
    return SplitJob(**params)


# --------------------------------------------------------------------------- 校验


def test_collect_errors_accepts_valid_job(basic_csv, out_dir):
    assert collect_errors(make_job(basic_csv, out_dir)) == []


@pytest.mark.parametrize(
    ("overrides", "expected_key"),
    [
        ({"input_path": Path("does-not-exist.csv")}, "err.file_missing"),
        ({"chunk_size": 0}, "err.invalid_chunk_size"),
        ({"chunk_size": 10**9}, "err.invalid_chunk_size"),
        ({"digits": 0}, "err.invalid_number"),
        ({"digits": 11}, "err.invalid_number"),
        ({"export_format": "xls"}, "err.invalid_export_format"),
    ],
)
def test_collect_errors_reports_specific_problems(basic_csv, out_dir, overrides, expected_key):
    errors = collect_errors(make_job(basic_csv, out_dir, **overrides))
    assert [error.key for error in errors] == [expected_key]


def test_collect_errors_rejects_unsupported_extension(tmp_path, out_dir):
    path = tmp_path / "data.txt"
    path.write_text("x", encoding="utf-8")
    errors = collect_errors(make_job(path, out_dir))
    assert [error.key for error in errors] == ["err.invalid_file"]


def test_collect_errors_rejects_file_as_output_dir(basic_csv, tmp_path):
    file_as_dir = tmp_path / "not-a-dir"
    file_as_dir.write_text("x", encoding="utf-8")
    errors = collect_errors(make_job(basic_csv, file_as_dir))
    assert [error.key for error in errors] == ["err.output_not_dir"]


def test_output_path_through_a_file_is_rejected(basic_csv, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    errors = collect_errors(make_job(basic_csv, blocker / "sub" / "out"))
    assert [error.key for error in errors] == ["err.output_not_dir"]


# --------------------------------------------------------------------------- 执行


def test_run_split_writes_expected_files(basic_csv, out_dir):
    result = run_split(make_job(basic_csv, out_dir))
    assert [path.name for path in result.files] == [
        "artists_001.csv",
        "artists_002.csv",
        "artists_003.csv",
        "artists_004.csv",
    ]
    sizes = [len(pd.read_csv(path, dtype=str)) for path in result.files]
    assert sizes == [3, 3, 3, 1]
    assert result.rows == ROW_COUNT
    assert result.canceled is False
    assert not list(out_dir.glob(".*part*"))


def test_run_split_preserves_content_and_fidelity(basic_csv, out_dir):
    run_split(make_job(basic_csv, out_dir))
    merged = pd.concat(
        [pd.read_csv(path, dtype=str) for path in sorted(out_dir.glob("*.csv"))],
        ignore_index=True,
    )
    original = pd.read_csv(basic_csv, dtype=str)
    assert merged.equals(original)
    assert merged["id"].tolist()[0] == "001"
    assert merged["note"].tolist()[3] == "=1+1"  # 默认不转义


def test_output_dir_is_created_when_missing(basic_csv, tmp_path):
    target = tmp_path / "nested" / "deep"
    result = run_split(make_job(basic_csv, target))
    assert target.is_dir() and len(result.files) == 4


def test_progress_events_are_monotonic_and_finish_at_total(basic_csv, out_dir):
    seen: list[tuple[int, int]] = []
    run_split(
        make_job(basic_csv, out_dir),
        on_progress=lambda event: seen.append((event.index, event.rows_written)),
    )
    assert seen == sorted(seen)
    assert seen[-1][1] == ROW_COUNT
    assert seen[0][0] == 1


def test_escape_formulas_end_to_end(basic_csv, out_dir):
    run_split(make_job(basic_csv, out_dir, escape_formulas=True))
    merged = pd.concat(
        [pd.read_csv(path, dtype=str) for path in sorted(out_dir.glob("*.csv"))],
        ignore_index=True,
    )
    assert "'=1+1" in merged["note"].tolist()


def test_export_to_xlsx(basic_csv, out_dir):
    result = run_split(make_job(basic_csv, out_dir, export_format="xlsx"))
    assert all(path.suffix == ".xlsx" for path in result.files)
    assert len(pd.read_excel(result.files[0])) == 3


def test_single_chunk_when_size_exceeds_rows(basic_csv, out_dir):
    result = run_split(make_job(basic_csv, out_dir, chunk_size=1000))
    assert len(result.files) == 1
    assert result.files[0].name == "artists_001.csv"


def test_empty_table_raises(tmp_path, out_dir):
    empty = tmp_path / "empty.csv"
    empty.write_text("id,artist\n", encoding="utf-8")
    with pytest.raises(AppError) as info:
        run_split(make_job(empty, out_dir))
    assert info.value.key == "err.empty_table"


def test_missing_input_file_raises(tmp_path, out_dir):
    with pytest.raises(AppError) as info:
        run_split(make_job(tmp_path / "nope.csv", out_dir))
    assert info.value.key == "err.file_missing"


def test_write_failure_is_translated_and_leaves_no_temp(monkeypatch, basic_csv, out_dir):
    def boom(frame: pd.DataFrame, path: Path) -> None:
        Path(path).write_text("partial", encoding="utf-8")
        raise OSError(errno.EACCES, "denied")

    monkeypatch.setattr(writers_module, "EXPORT_FORMATS", {"csv": ExportSpec("csv", ".csv", boom)})
    with pytest.raises(AppError) as info:
        run_split(make_job(basic_csv, out_dir))
    assert info.value.key == "err.permission"
    assert list(out_dir.iterdir()) == []  # 目标文件与临时文件都不应留下


# --------------------------------------------------------------------------- 取消


def test_cancel_before_first_chunk(basic_csv, out_dir):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CanceledByUser) as info:
        run_split(make_job(basic_csv, out_dir), cancel=cancel)
    assert info.value.partial is not None
    assert info.value.partial.files == ()
    assert list(out_dir.iterdir()) == []


def test_cancel_after_first_chunk_stops_writing(basic_csv, out_dir):
    cancel = threading.Event()

    def on_progress(event) -> None:
        cancel.set()  # 一个分块写完后立即要求取消

    with pytest.raises(CanceledByUser) as info:
        run_split(make_job(basic_csv, out_dir), cancel=cancel, on_progress=on_progress)
    partial = info.value.partial
    assert partial is not None
    assert len(partial.files) == 1
    assert len(list(out_dir.glob("*.csv"))) == 1
    assert not list(out_dir.glob(".*part*"))


def test_cancel_is_not_reported_as_success(basic_csv, out_dir):
    """迭代器遇到取消会静默停止产出，必须在循环后补判，否则会误报成功。"""
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CanceledByUser):
        run_split(make_job(basic_csv, out_dir, chunk_size=1, force_stream=True), cancel=cancel)


# --------------------------------------------------------------------------- 冲突


def test_conflict_overwrite_policy(basic_csv, out_dir):
    stale = out_dir / "artists_001.csv"
    stale.write_text("stale\n", encoding="utf-8")
    result = run_split(make_job(basic_csv, out_dir))
    assert stale in result.files
    assert len(pd.read_csv(stale, dtype=str)) == 3


def test_conflict_index_policy(basic_csv, out_dir):
    stale = out_dir / "artists_001.csv"
    stale.write_text("stale\n", encoding="utf-8")
    result = run_split(make_job(basic_csv, out_dir, conflict_policy=ConflictPolicy.INDEX))
    names = [path.name for path in result.files]
    assert names[0] == "artists_001_1.csv"
    assert stale.read_text(encoding="utf-8") == "stale\n"


# --------------------------------------------------------------------------- 预检


def test_preflight_reports_rows_files_and_conflicts(basic_csv, out_dir):
    report = preflight(make_job(basic_csv, out_dir))
    try:
        assert report.total_rows == ROW_COUNT
        assert report.file_count == 4
        assert report.conflicts == ()
    finally:
        report.close()


def test_preflight_detects_existing_targets(basic_csv, out_dir):
    (out_dir / "artists_002.csv").write_text("x", encoding="utf-8")
    report = preflight(make_job(basic_csv, out_dir))
    try:
        assert [path.name for path in report.conflicts] == ["artists_002.csv"]
    finally:
        report.close()


def test_preflight_keeps_source_open_for_reuse(basic_csv, out_dir):
    report = preflight(make_job(basic_csv, out_dir))
    assert report.handle is not None
    job_with_total = replace(report.job, total_rows=report.total_rows)
    handle, report.handle = report.handle, None
    result = run_split(job_with_total, source=handle)
    assert len(result.files) == 4
    report.close()  # 所有权已转移，这里是空操作


def test_preflight_can_close_immediately(basic_csv, out_dir):
    report = preflight(make_job(basic_csv, out_dir), keep_open=False)
    assert report.handle is None
    report.close()


# --------------------------------------------------------------------------- 清理


def test_cleanup_files_removes_only_existing(tmp_path):
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_text("x", encoding="utf-8")
    assert cleanup_files([first, second, tmp_path / "missing.csv"]) == 1
    assert not first.exists()


def test_cleanup_is_idempotent(tmp_path):
    assert cleanup_files([tmp_path / "nope.csv"]) == 0
