"""界面层入口。

对外只暴露 ``main() -> int``：``splitter.py``（开发时直接运行）与
``__main__.py``（``python -m universal_table_splitter``）都依赖这个签名，
保持一致可以让这两个文件一行都不用改。

这里没有"主题加载失败就退回原生控件重建窗口"的降级分支：QSS 是纯字符串，
不存在"样式资源缺失导致界面打不开"的情况。
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from .. import __version__
from ..config import APP_NAME, APP_SLUG
from ..logging_setup import setup_logging
from ..settings import Settings
from .main_window import MainWindow
from .theme import apply_dark_theme

logger = logging.getLogger(__name__)


def main() -> int:
    """启动图形界面，返回进程退出码。"""
    setup_logging()
    logger.info("starting %s v%s", APP_NAME, __version__)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_SLUG)
    app.setApplicationVersion(__version__)
    apply_dark_theme(app)

    window = MainWindow(Settings.load())
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
