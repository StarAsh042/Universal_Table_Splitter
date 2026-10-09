# Copyright (c) 2026 StarAsh042
#
# Released under the MIT License. See the LICENSE file for the full text.

"""启动入口：``python splitter.py``。

本文件只做一件事——调用界面层的 ``main()``。等价的其他入口：
- ``python -m universal_table_splitter``            启动界面
- ``python -m universal_table_splitter --help``     使用命令行
- ``table-splitter``（安装后）                       命令行
"""

from __future__ import annotations

from universal_table_splitter.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
