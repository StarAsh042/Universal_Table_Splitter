"""Universal Table Splitter —— 通用表格分割器。

分层结构：
- ``core``：与界面无关的纯业务逻辑（计划分块、读取、写出），可被 CLI 与测试直接复用；
- ``ui``：Tk/ttkbootstrap 界面，只负责交互与渲染；
- ``i18n``：全部面向用户的文案。
"""

from __future__ import annotations

__version__ = "1.1.0"

__all__ = ["__version__"]
