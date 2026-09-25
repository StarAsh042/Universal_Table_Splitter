"""命令行入口。

复用 ``core`` 的同一套逻辑，因此 GUI 与 CLI 的行为、校验与错误文案完全一致。
这让本项目可以进入批处理/自动化流程，也让核心逻辑拥有了最直接的端到端测试手段。
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import DEFAULT_CHUNK_SIZE, DEFAULT_NUM_FORMAT
from .core.deps import ensure_required
from .core.job import SplitJob, cleanup_files, preflight, run_split
from .core.plan import guess_output_dir, parse_chunk_size, parse_num_format
from .core.readers import export_formats_for, is_supported, supported_extensions
from .core.writers import ConflictPolicy, export_formats
from .errors import AppError, CanceledByUser
from .i18n import SUPPORTED_LANGS, render_error, tr
from .logging_setup import setup_logging
from .settings import Settings


def build_parser(lang: str = "cn") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="table-splitter",
        description=tr("cli.description", lang),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", nargs="?", help=tr("cli.input", lang))
    parser.add_argument("-o", "--output", help=tr("cli.output", lang))
    parser.add_argument(
        "-n",
        "--rows",
        default=str(DEFAULT_CHUNK_SIZE),
        help=tr("cli.rows", lang),
    )
    parser.add_argument("-d", "--digits", default=DEFAULT_NUM_FORMAT, help=tr("cli.digits", lang))
    parser.add_argument(
        "-f",
        "--format",
        dest="export_format",
        choices=sorted(export_formats()),
        help=tr("cli.format", lang),
    )
    parser.add_argument("--sheet", help=tr("cli.sheet", lang))
    parser.add_argument("--no-fidelity", action="store_true", help=tr("cli.no_fidelity", lang))
    parser.add_argument(
        "--escape-formulas", action="store_true", help=tr("cli.escape_formulas", lang)
    )
    parser.add_argument(
        "--overwrite",
        choices=[policy.value for policy in ConflictPolicy],
        default=ConflictPolicy.OVERWRITE.value,
        help=tr("cli.overwrite", lang),
    )
    parser.add_argument("--stream", action="store_true", help=tr("cli.stream", lang))
    parser.add_argument(
        "--clean-partial",
        action="store_true",
        help="取消或失败时删除已生成的文件",
    )
    parser.add_argument(
        "--lang",
        choices=SUPPORTED_LANGS,
        default=Settings.load().lang,
        help=tr("cli.lang", lang),
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="只输出错误")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _build_job(args: argparse.Namespace) -> SplitJob:
    input_path = Path(str(args.input)).expanduser()
    if not input_path.exists():
        raise AppError("err.file_missing", path=str(input_path))
    if not is_supported(input_path):
        raise AppError(
            "err.invalid_file",
            exts=", ".join(supported_extensions()),
        )
    output_dir = Path(args.output).expanduser() if args.output else guess_output_dir(input_path)
    chunk_size = parse_chunk_size(args.rows)
    digits = parse_num_format(args.digits)
    export_format = args.export_format or export_formats_for(input_path)[0]
    return SplitJob(
        input_path=input_path,
        output_dir=output_dir,
        chunk_size=chunk_size,
        digits=digits,
        export_format=export_format,
        sheet=args.sheet,
        fidelity=not args.no_fidelity,
        escape_formulas=args.escape_formulas,
        conflict_policy=ConflictPolicy(args.overwrite),
        force_stream=args.stream,
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    # 先探测 lang 以决定帮助文本语言
    settings = Settings.load()
    pre_lang = settings.lang
    for index, token in enumerate(arguments):
        if token == "--lang" and index + 1 < len(arguments):
            pre_lang = arguments[index + 1]
    parser = build_parser(pre_lang)
    args = parser.parse_args(arguments)
    lang = args.lang
    log_file = setup_logging()

    try:
        ensure_required()
        job = _build_job(args)
    except AppError as exc:
        print(render_error(exc, lang), file=sys.stderr)
        return 2

    cancel = threading.Event()

    def _on_sigint(signum, frame):  # pragma: no cover - 依赖真实信号
        print("", file=sys.stderr)
        cancel.set()

    # 非主线程等场景无法安装信号处理器，忽略即可（此时用 Ctrl+C 会直接终止进程）
    with contextlib.suppress(ValueError, OSError):
        signal.signal(signal.SIGINT, _on_sigint)

    reporter = None if args.quiet else _ProgressReporter(lang)
    report = None

    try:
        report = preflight(job, cancel=cancel)
        if report.file_count > 1 and not args.quiet:
            print(tr("cli.files_planned", lang, count=report.file_count), file=sys.stderr)
        if report.conflicts and job.conflict_policy is ConflictPolicy.OVERWRITE and not args.quiet:
            print(
                tr("cli.overwrite_warning", lang, count=len(report.conflicts)),
                file=sys.stderr,
            )
        # 所有权转移给 run_split，避免二次读取
        handle, report.handle = report.handle, None
        result = run_split(
            job,
            on_progress=reporter.feed if reporter else None,
            cancel=cancel,
            source=handle,
        )
    except CanceledByUser as exc:
        partial = exc.partial
        count = len(partial.files) if partial else 0
        print(tr("cli.canceled", lang, count=count), file=sys.stderr)
        if args.clean_partial and partial:
            cleanup_files(partial.files)
        return 130
    except AppError as exc:
        print(render_error(exc, lang), file=sys.stderr)
        print(tr("cli.log_hint", lang, path=log_file), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - 兜底
        print(render_error(exc, lang), file=sys.stderr)
        print(tr("cli.log_hint", lang, path=log_file), file=sys.stderr)
        return 1
    finally:
        if report is not None:
            report.close()

    if reporter:
        reporter.finish()
    if not args.quiet:
        print(
            tr(
                "cli.done",
                lang,
                count=len(result.files),
                rows=f"{result.rows:,}",
                seconds=f"{result.elapsed_s:.1f}",
            )
        )
    return 0


class _ProgressReporter:
    """按 5% 步进输出进度，避免刷屏。"""

    def __init__(self, lang: str, step: int = 5) -> None:
        self.lang = lang
        self.step = step
        self._last = -step
        self._files = 0

    def feed(self, event) -> None:
        self._files = event.index
        if not event.total_rows:
            return
        percent = min(int(event.rows_written * 100 / event.total_rows), 100)
        if percent >= self._last + self.step:
            self._last = percent - percent % self.step
            print(
                tr(
                    "cli.progress",
                    self.lang,
                    percent=self._last,
                    rows=f"{event.rows_written:,}",
                    files=self._files,
                ),
                file=sys.stderr,
            )

    def finish(self) -> None:
        if self._last < 100:
            self._last = 100


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
