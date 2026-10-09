"""PySide6 界面层。

- ``app``：入口 ``main()``
- ``main_window``：主窗口装配与流程调度
- ``preview``：文件预览区
- ``worker``：后台线程（预检 / 执行）
- ``theme``：深色主题与全局 QSS
- ``widgets``：可复用控件
"""

from __future__ import annotations

__all__ = ["app", "main_window", "preview", "theme", "widgets", "worker"]
