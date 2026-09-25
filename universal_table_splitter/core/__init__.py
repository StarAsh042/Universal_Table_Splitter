"""与界面解耦的核心业务层。"""

from __future__ import annotations

from .job import Preflight, ProgressEvent, SplitJob, SplitResult, preflight, run_split
from .plan import (
    chunk_count,
    format_suffix,
    parse_chunk_size,
    parse_num_format,
    plan_chunks,
)
from .readers import open_table
from .writers import EXPORT_FORMATS, ConflictPolicy

__all__ = [
    "EXPORT_FORMATS",
    "ConflictPolicy",
    "Preflight",
    "ProgressEvent",
    "SplitJob",
    "SplitResult",
    "chunk_count",
    "format_suffix",
    "open_table",
    "parse_chunk_size",
    "parse_num_format",
    "plan_chunks",
    "preflight",
    "run_split",
]
