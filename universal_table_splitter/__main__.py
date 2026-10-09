"""``python -m universal_table_splitter`` 入口。

无参数时启动 GUI；带参数时走 CLI，方便在终端里快速批量分割。
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1:
        from .cli import main as cli_main

        return cli_main(sys.argv[1:])
    from .ui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
