"""确保运行时依赖齐全；缺失时询问用户，确认后调用 pip 从网络安装。

被三处复用，避免各写一套判断：

- ``packaging/table_splitter.spec`` —— 打包前。防止"在缺依赖的机器上打出一个
  悄悄少了功能的 exe"。
- ``packaging/build.bat`` —— 打包流程的第六步。
- ``run.bat`` —— 源码启动前。让项目在别人的机器上也能一键跑起来。

行为约定
--------
- 依赖清单**从 ``core/deps.py`` 的源码解析**，不 import 那个模块（原因见
  ``read_registry`` 的文档）；内容仍与应用内"缺少可选依赖"提示同源，不另写一份；
- **默认先问再装**，绝不静默联网下载几十 MB；
- 非交互环境（CI、管道、stdin 被重定向）不提问，直接判定为"不安装"并失败，
  否则构建会卡死在等待输入上；
- 环境变量 ``UTS_NO_AUTO_INSTALL=1`` 时完全禁用自动安装，只校验并在缺失时失败。
  CI 与 ``build.bat --no-install`` 用这个保持严格，好让 ``pyproject.toml``
  漏写依赖这类问题当场暴露，而不是被自动补装掩盖。

退出码：``0`` = 依赖齐全（或已补齐）；``1`` = 仍有缺失。

直接运行：

    python packaging/ensure_deps.py                  # 缺什么问你要不要装
    python packaging/ensure_deps.py --no-ask         # 不问，直接装
    python packaging/ensure_deps.py --skip PySide6   # 不检查界面依赖（纯命令行场景）
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 依赖清单的唯一事实来源
REGISTRY_SOURCE = PROJECT_ROOT / "universal_table_splitter" / "core" / "deps.py"

#: 设为 1 / true / yes / on 时禁用自动安装，只做校验
NO_INSTALL_ENV = "UTS_NO_AUTO_INSTALL"

_TRUTHY = {"1", "true", "yes", "on"}


class Dependency(NamedTuple):
    """一条依赖：``module`` 是 import 名，``package`` 是 pip 包名（两者常不一致）。"""

    module: str
    package: str


def auto_install_disabled() -> bool:
    return os.environ.get(NO_INSTALL_ENV, "").strip().lower() in _TRUTHY


def _registry_literal(tree: ast.Module) -> ast.expr | None:
    """找出 ``DEPENDENCIES`` 被赋值成的那个表达式。

    两种写法都要认：``DEPENDENCIES = (...)`（``ast.Assign``）和
    ``DEPENDENCIES: tuple[Dependency, ...] = (...)`（``ast.AnnAssign``）。
    本项目用的是后者——只认 ``Assign`` 会直接漏掉。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(getattr(target, "id", "") == "DEPENDENCIES" for target in node.targets):
                return node.value
        elif isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "DEPENDENCIES":
            return node.value
    return None


def _parse_registry(source: str) -> tuple[Dependency, ...]:
    """从 ``core/deps.py`` 的源码里取出 ``DEPENDENCIES`` 元组。

    只认字面量写法（``Dependency("pandas", "pandas", "dep.pandas", required=True)``），
    这是该文件的既有风格；换成动态构造会在这里直接报错，而不是悄悄漏检。
    """
    value = _registry_literal(ast.parse(source))
    if value is None:
        raise SystemExit("[ensure_deps] FATAL 无法从 core/deps.py 解析出 DEPENDENCIES")
    if not isinstance(value, ast.Tuple):
        raise SystemExit(
            "[ensure_deps] FATAL core/deps.py 里的 DEPENDENCIES 不是字面量元组，无法解析"
        )

    entries: list[Dependency] = []
    for element in value.elts:
        if not isinstance(element, ast.Call) or len(element.args) < 2:
            raise SystemExit(
                "[ensure_deps] FATAL core/deps.py 里的 DEPENDENCIES 不是字面量写法，无法解析"
            )
        module = ast.literal_eval(element.args[0])
        package = ast.literal_eval(element.args[1])
        entries.append(Dependency(module, package))
    return tuple(entries)


def read_registry() -> tuple[Dependency, ...]:
    """读取依赖清单。

    **刻意不 ``import universal_table_splitter.core.deps``**：``core/__init__.py``
    会连带导入 ``job``，而 ``job`` 又 ``import pandas``——"机器上没装 pandas"
    恰恰是本脚本要处理的场景，真去 import 会当场 ModuleNotFoundError，
    形成"为了修缺依赖而必须先有依赖"的死锁（实测在干净 venv 里必现）。
    读源码文本则完全没有导入副作用。
    """
    return _parse_registry(REGISTRY_SOURCE.read_text(encoding="utf-8"))


def is_available(module: str) -> bool:
    """不执行导入即可判断模块是否可用。"""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # 父包缺失等异常情况
        return False


def find_missing(skip: tuple[str, ...] = ()) -> tuple[Dependency, ...]:
    """返回缺失的依赖。``skip`` 里的模块名不参与检查。"""
    return tuple(
        dep for dep in read_registry() if dep.module not in skip and not is_available(dep.module)
    )


def install_packages(packages, *, runner=subprocess.run) -> bool:
    """调用 pip 安装；以 pip 的退出码为准判断成功与否。

    ``runner`` 可注入，便于测试时替换掉真正的网络调用。
    """
    if not packages:
        return True
    command = [sys.executable, "-m", "pip", "install", *packages]
    print(f"[ensure_deps] 正在安装：{' '.join(command)}", flush=True)
    completed = runner(command)
    return completed.returncode == 0


def _is_interactive() -> bool:
    """判断能否安全地提问。

    被 CI 或其它程序调用时 stdin 可能是 None、已关闭或不是终端，
    此时 ``input()`` 会抛异常或永久阻塞，必须先识别出来。

    **不能只看 ``isatty()``**：Windows 上把 stdin 重定向到 NUL 设备时
    ``sys.stdin.isatty()`` 仍然返回 ``True``（NUL 被当成字符设备），于是会先打印
    一句 ``[Y/n]`` 再立刻收到 EOF——用户看到的是一次莫名其妙的提问，构建日志里
    也会多出一行看不懂的提示。所以这里额外用 ``GetConsoleMode`` 确认句柄真是控制台。
    """
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError):  # pragma: no cover - 取决于宿主环境
        return False

    if sys.platform != "win32":
        return True

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_ulong()
        # 管道 / NUL / 重定向的文件都不支持 GetConsoleMode，会返回 0
        return bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except Exception:  # pragma: no cover - 取决于宿主环境
        return False


def _print_manual_hint(missing) -> None:
    print("[ensure_deps] 请手动安装：")
    for dep in missing:
        print(f"    {sys.executable} -m pip install {dep.package}")


def _ask(missing) -> bool:
    names = "、".join(dep.package for dep in missing)
    print(f"[ensure_deps] 缺少运行时依赖：{names}")
    print("[ensure_deps] 需要从网络（PyPI）下载安装，可能几十 MB。")
    try:
        answer = input("[ensure_deps] 现在安装？[Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("", "y", "yes")


def ensure(*, ask: bool = True, skip: tuple[str, ...] = ()) -> int:
    """校验（必要时安装）运行时依赖。返回 0 表示齐全，1 表示仍有缺失。"""
    missing = find_missing(skip)
    if not missing:
        print("[ensure_deps] runtime dependencies OK")
        return 0

    # 机器可读标记保持纯 ASCII：英文 Windows 控制台是 cp1252，中文会被降级成 ?
    print(
        "[ensure_deps] FATAL missing-runtime-dependencies: " + ", ".join(d.module for d in missing)
    )

    if auto_install_disabled():
        print(f"[ensure_deps] auto-install disabled by {NO_INSTALL_ENV}")
        print(f"[ensure_deps] 已设置 {NO_INSTALL_ENV}，跳过自动安装")
        _print_manual_hint(missing)
        return 1

    if ask:
        # 只有"需要征求同意"时才关心环境是否可交互。
        # ask=False（--no-ask）表示调用方已经明确要求无人值守安装，
        # 此时再拿"非交互"去拦它，就等于把 --no-ask 变成了摆设。
        if not _is_interactive():
            print("[ensure_deps] non-interactive: skip auto-install")
            print("[ensure_deps] 非交互环境（CI / 管道 / 被其它程序调用），不提问也不自动安装")
            print("[ensure_deps] 确实需要无人值守安装，请显式加 --no-ask")
            _print_manual_hint(missing)
            return 1
        if not _ask(missing):
            _print_manual_hint(missing)
            return 1

    if not install_packages([dep.package for dep in missing]):
        print("[ensure_deps] pip 安装失败（网络不通或代理问题？）")
        _print_manual_hint(missing)
        return 1

    # 新装的包在全新的目录里，导入系统的缓存可能还是旧的
    importlib.invalidate_caches()

    remaining = find_missing(skip)
    if remaining:
        print("[ensure_deps] 安装后仍有缺失：" + ", ".join(d.module for d in remaining))
        _print_manual_hint(remaining)
        return 1

    print("[ensure_deps] 依赖已补齐")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验运行时依赖；缺失时询问后从网络安装。",
    )
    parser.add_argument(
        "--no-ask",
        action="store_true",
        help="不提问，直接安装缺失的依赖",
    )
    parser.add_argument(
        "--skip",
        default="",
        help="逗号分隔的模块名，跳过检查（例如纯命令行场景传 PySide6）",
    )
    args = parser.parse_args(argv)

    skip = tuple(name.strip() for name in args.skip.split(",") if name.strip())
    return ensure(ask=not args.no_ask, skip=skip)


if __name__ == "__main__":
    raise SystemExit(main())
