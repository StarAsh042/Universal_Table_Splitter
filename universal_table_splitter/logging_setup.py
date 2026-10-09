"""日志初始化。

原项目导入了 ``logging`` 却从未使用，出错时只把裸异常字符串丢进状态栏，
既无法排查也无法审计。这里统一：用户看到友好文案，完整堆栈进日志文件。
"""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import sys
import threading
from pathlib import Path

from .settings import log_dir

LOG_FILE_NAME = "app.log"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3

_configured = False


def log_file_path() -> Path:
    return log_dir() / LOG_FILE_NAME


def make_console_encoding_safe() -> None:
    """让中文输出在"窄编码"控制台下也不至于让程序崩掉。

    英文 Windows 的控制台编码是 cp1252，此时 ``print("完成")`` 会抛
    ``UnicodeEncodeError`` —— CLI 会当场中断（本项目在 GitHub 的 windows
    runner 上真实踩过一次，打包脚本因此直接失败）。

    把这些流改成 ``errors="replace"``：装不下的字符降级成 ``?``，
    中文控制台（cp936 / UTF-8）的输出完全不受影响。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue  # 被替换成非文本流（如 GUI 环境下的 None）时跳过
        # 流已关闭或不可重配置时（例如已重定向）直接跳过，不影响主流程
        with contextlib.suppress(ValueError, OSError):
            reconfigure(errors="replace")


def setup_logging(
    level: int = logging.INFO,
    console_level: int = logging.WARNING,
    force: bool = False,
) -> Path:
    """配置根 logger，返回日志文件路径。重复调用是幂等的。

    文件里记录 INFO 及以上（便于排查），控制台默认只报 WARNING，
    避免 CLI 的常规输出被日志刷屏。
    """
    global _configured
    target = log_file_path()
    if _configured and not force:
        return target
    # 控制台日志里会出现中文，先确保窄编码控制台不会因此抛异常
    make_console_encoding_safe()
    if force:
        root = logging.getLogger()
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()

    handlers: list[logging.Handler] = []
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s")
        )
        handlers.append(file_handler)
    except OSError:
        # 日志目录不可写时退化为仅控制台输出，不影响主流程
        target = Path("<unavailable>")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(console_level)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    handlers.append(stream_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)
    _install_excepthooks()
    _configured = True
    return target


def _install_excepthooks() -> None:
    """把主线程与子线程的未捕获异常都写进日志。"""

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logging.getLogger("uncaught").critical(
            "uncaught exception", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _hook
    if hasattr(threading, "excepthook"):  # Python >= 3.8
        threading.excepthook = lambda args: _hook(  # type: ignore[assignment]
            args.exc_type, args.exc_value, args.exc_traceback
        )
