"""使用真实 30MB 数据集（``tests/data/danbooru_art_full.csv``）的集成测试。

数据集不进版本库（见 ``tests/data/README.md``）；文件缺失或用例被默认的
``-m "not slow"`` 过滤时会跳过。显式运行：

    pytest -m slow -v
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pytest

from universal_table_splitter.core.job import SplitJob, preflight, run_split
from universal_table_splitter.core.readers import ReadOptions, open_table

DATA_DIR = Path(__file__).resolve().parent / "data"
BIG_FILE = DATA_DIR / "danbooru_art_full.csv"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not BIG_FILE.exists(), reason=f"缺少 30MB 测试数据 {BIG_FILE}（见 tests/data/README.md）"
    ),
]

COLUMNS = ["artist", "trigger", "count", "url"]


@pytest.fixture(scope="module")
def source_frame() -> pd.DataFrame:
    return pd.read_csv(BIG_FILE, dtype=str, keep_default_na=False)


def test_source_shape(source_frame):
    assert list(source_frame.columns) == COLUMNS
    assert len(source_frame) == 419_789


def test_fidelity_read_preserves_every_cell(source_frame):
    """保真模式读到的内容必须与原始字节完全一致（逐单元格比对）。"""
    frame = pd.read_csv(BIG_FILE, dtype=str, keep_default_na=False)
    assert frame.equals(source_frame)
    assert frame["count"].dtype == object  # 没有被转成 int64


def test_streaming_read_is_memory_bounded():
    """流式路径不应把整表读进内存。"""
    import tracemalloc

    tracemalloc.start()
    source = open_table(BIG_FILE, ReadOptions(fidelity=True, force_stream=True))
    try:
        assert source.total_rows == 419_789
        peak_after_open = tracemalloc.get_traced_memory()[1]
        rows = 0
        for chunk in source.iter_chunks(50_000):
            rows += len(chunk)
        peak_total = tracemalloc.get_traced_memory()[1]
    finally:
        source.close()
        tracemalloc.stop()
    assert rows == 419_789
    # 峰值应远小于整表载入（实测整表约 130MB）；留足余量避免抖动
    assert peak_total < 400 * 1024 * 1024
    assert peak_after_open < 64 * 1024 * 1024


def test_split_roundtrip_is_lossless(tmp_path, source_frame):
    job = SplitJob(
        input_path=BIG_FILE,
        output_dir=tmp_path,
        chunk_size=100_000,
        digits=3,
        export_format="csv",
        fidelity=True,
    )
    report = preflight(job)
    assert report.total_rows == 419_789
    assert report.file_count == 5
    handle, report.handle = report.handle, None

    started = time.perf_counter()
    from dataclasses import replace

    result = run_split(replace(job, total_rows=report.total_rows), source=handle)
    elapsed = time.perf_counter() - started

    names = [path.name for path in result.files]
    assert names == [f"danbooru_art_full_{index:03d}.csv" for index in range(1, 6)]
    sizes = [len(pd.read_csv(path, dtype=str, keep_default_na=False)) for path in result.files]
    assert sizes == [100_000] * 4 + [19_789]
    assert sum(sizes) == 419_789

    merged = pd.concat(
        [pd.read_csv(path, dtype=str, keep_default_na=False) for path in result.files],
        ignore_index=True,
    )
    assert merged.equals(source_frame)  # 无损往返

    # 中文/特殊字符在 CSV 中应带 BOM，Excel 才不会乱码
    assert result.files[0].read_bytes().startswith(b"\xef\xbb\xbf")
    assert not list(tmp_path.glob(".*part*"))
    assert elapsed < 120, f"splitting took {elapsed:.1f}s"


def test_cancel_leaves_no_partial_files(tmp_path):
    import threading

    cancel = threading.Event()
    job = SplitJob(
        input_path=BIG_FILE,
        output_dir=tmp_path,
        chunk_size=50_000,
        digits=3,
        export_format="csv",
    )
    from universal_table_splitter.errors import CanceledByUser

    def on_progress(event) -> None:
        if event.index >= 2:
            cancel.set()

    with pytest.raises(CanceledByUser) as info:
        run_split(job, cancel=cancel, on_progress=on_progress)
    written = len(info.value.partial.files)
    assert 0 < written < 9
    assert len(list(tmp_path.glob("*.csv"))) == written
    assert not list(tmp_path.glob(".*part*"))
