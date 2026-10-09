# Copyright (C) 2024 StarAsh042
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""向后兼容的启动入口。

早期版本的全部实现都在这个文件里；重构后代码分层到 ``universal_table_splitter``
包中（``core`` 业务层 + ``ui`` 界面层），本文件保留为薄封装，因此既有的
``python splitter.py`` 用法与打包脚本无需改动。

等价的其他入口：
- ``python -m universal_table_splitter``            启动界面
- ``python -m universal_table_splitter --help``     使用命令行
- ``table-splitter``（安装后）                       命令行
"""

from __future__ import annotations

from universal_table_splitter.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
