"""打包配置（``packaging/table_splitter.spec``）的回归测试。

spec 在 PyInstaller 里就是一段被执行的普通 Python。它打印的中文只要控制台装不下
就会抛 ``UnicodeEncodeError`` —— GitHub 的 ``windows-latest`` 正是英文环境（cp1252），
自动打包正是在这一步失败（``character maps to <undefined>``）。

这里用桩替换 PyInstaller 注入的名字，直接在 cp1252 环境下执行 spec，
既复现了那个环境，又不需要真正安装 PyInstaller。

spec 里不包含 tkinter / ttkbootstrap / tkinterdnd2 相关的逻辑。下面除了
"能在窄编码控制台下跑完"之外，还有一组**静态检查**：确保 tk 那一套被排除、
PySide6 没有被整体 collect_all（那会让产物体积翻倍），以及 openpyxl 的收集没被误删。
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = PROJECT_ROOT / "packaging" / "table_splitter.spec"
INIT_PATH = PROJECT_ROOT / "universal_table_splitter" / "__init__.py"

#: 只保留"读版本 + 生成版本资源 + 打印"这条链路，PyInstaller 的构建函数用桩替代
_RUNNER = """
import pathlib

SPEC = pathlib.Path({spec!r})

{prelude}


class Dummy:
    def __getattr__(self, name):
        return Dummy()

    def __call__(self, *args, **kwargs):
        return Dummy()

    def __getitem__(self, key):
        return Dummy()


namespace = {{
    "SPECPATH": str(SPEC.parent),
    "DISTPATH": str(pathlib.Path("dist").resolve()),
    "HOMEPATH": str(pathlib.Path(".").resolve()),
    "WARNFILE": str(pathlib.Path("build/warn.txt").resolve()),
}}
for _name in ("Analysis", "PYZ", "EXE", "COLLECT"):
    namespace[_name] = Dummy()

exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), namespace)
print("SPEC_EXEC_OK", namespace["APP_VERSION"])
print("VERSION_FILE", namespace["VERSION_FILE"])
"""


def _run_spec(
    tmp_path: Path,
    io_encoding: str,
    prelude: str = "",
    env_overrides: dict | None = None,
) -> subprocess.CompletedProcess:
    """在指定标准流编码下执行 spec（cp1252 即英文 Windows / GitHub runner 的环境）。

    ``prelude`` 会在执行 spec **之前**运行，用来模拟"没装某个依赖"这类环境。

    ``stdin=DEVNULL`` 是必须的：spec 现在会在缺依赖时问用户要不要联网安装，
    测试里必须让它判定为"非交互"，否则会卡在等待输入上。
    """
    runner = tmp_path / "run_spec.py"
    runner.write_text(_RUNNER.format(spec=str(SPEC_PATH), prelude=prelude), encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": io_encoding}
    env.update(env_overrides or {})
    return subprocess.run(
        [sys.executable, str(runner)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
    )


def test_spec_runs_on_cp1252_console(tmp_path):
    """英文 Windows（cp1252）下 spec 必须能跑完——中文输出最容易在这里挂掉。"""
    result = _run_spec(tmp_path, "cp1252")

    assert result.returncode == 0, result.stderr
    assert "UnicodeEncodeError" not in result.stderr
    assert "SPEC_EXEC_OK" in result.stdout


def test_spec_reports_the_package_version(tmp_path):
    """spec 打印/写入的版本号必须直接来自包内 ``__version__``（唯一事实来源）。"""
    result = _run_spec(tmp_path, "cp1252")

    package_version = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)["\']', INIT_PATH.read_text(encoding="utf-8"), re.M
    ).group(1)
    reported = re.search(r"SPEC_EXEC_OK (\S+)", result.stdout).group(1)
    assert reported == package_version


def test_version_resource_is_written_as_utf8(tmp_path):
    """版本资源含中文名称，必须以 UTF-8(BOM) 落盘，exe 属性里才不会乱码。"""
    result = _run_spec(tmp_path, "cp1252")

    resource = Path(re.search(r"VERSION_FILE (.+)", result.stdout).group(1).strip())
    version = re.search(r"SPEC_EXEC_OK (\S+)", result.stdout).group(1)

    assert resource.exists()
    raw = resource.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM：PyInstaller 据此判定编码
    text = raw.decode("utf-8-sig")
    assert f"filevers=({version.replace('.', ', ')}" in text
    if not os.environ.get("UTS_APP_NAME"):  # 未用环境变量覆盖时才校验默认中文名
        assert "表格分割器" in text


def _analysis_kwargs() -> dict:
    """静态解析 spec 里 ``Analysis(...)`` 的关键字参数。

    比在子进程里跑一遍再想办法把参数捞出来简单得多，而且能精确断言 excludes。
    非字面量的值（``binaries=binaries`` 这种 Name 节点）解析不出来，直接跳过。
    """
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Analysis":
            resolved: dict = {}
            for keyword in node.keywords:
                if not keyword.arg:
                    continue
                try:
                    resolved[keyword.arg] = ast.literal_eval(keyword.value)
                except ValueError:
                    continue
            return resolved
    raise AssertionError("spec 里找不到 Analysis(...) 调用")


def _collected_packages() -> list[str]:
    """解析 ``for package in (...): collect_all(package)`` 里的包名列表。"""
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.iter, (ast.Tuple, ast.List)):
            continue
        try:
            names = [ast.literal_eval(element) for element in node.iter.elts]
        except ValueError:
            continue  # 不是字面量列表（例如 sys.stdout / sys.stderr 那种属性访问）
        if "openpyxl" in names:
            return names
    raise AssertionError("spec 里找不到 collect_all 的目标包列表")


def test_spec_excludes_the_tkinter_stack():
    """界面用 Qt，tk 相关的一切都不该被打进包里（省下 tcl/tk 运行库）。"""
    excludes = set(_analysis_kwargs()["excludes"])

    assert {"tkinter", "ttkbootstrap", "tkinterdnd2", "pandastable"} <= excludes


def test_spec_excludes_heavy_qt_modules():
    """PySide6 自带上百 MB 的模块，用不到的必须显式挡掉。"""
    excludes = set(_analysis_kwargs()["excludes"])

    assert "PySide6.QtWebEngineCore" in excludes
    assert "PySide6.QtQuick" in excludes
    assert "PySide6.QtMultimedia" in excludes


def test_spec_does_not_collect_all_of_pyside6():
    """``collect_all("PySide6")`` 会把整个 Qt 拖进来，产物直接翻倍。

    PyInstaller 自带的 PySide6 hook 会按实际 import 精确收集，不需要手动 collect_all。
    （注意：不能直接搜源码字符串——spec 的文档注释里就写着这行代码作为反例。）
    """
    packages = _collected_packages()

    assert "openpyxl" in packages  # openpyxl 仍然要整体收集
    assert not any(name.startswith("PySide6") for name in packages)


# --------------------------------------------------------- 运行时依赖完整性守卫

#: 让 ``is_available("xlrd")`` 返回 False，模拟"打包机上没装 xlrd"
_MISSING_XLRD = """
import importlib.util

_real_find_spec = importlib.util.find_spec


def _fake_find_spec(name, *args, **kwargs):
    if name == "xlrd":
        return None
    return _real_find_spec(name, *args, **kwargs)


importlib.util.find_spec = _fake_find_spec
"""


def test_spec_reports_runtime_dependencies_are_ok(tmp_path):
    """依赖齐全时构建正常通过，并留下可核对的记录。"""
    result = _run_spec(tmp_path, "cp1252", env_overrides={"UTS_NO_AUTO_INSTALL": "1"})

    assert result.returncode == 0, result.stderr
    assert "runtime dependencies OK" in result.stdout


def test_spec_aborts_when_a_runtime_dependency_is_missing(tmp_path):
    """缺运行时依赖、又不许自动安装时，必须让构建失败。

    一旦 spec 对缺失的依赖静默跳过，发布版就会少一块功能而无人察觉
    （比如漏掉 xlrd 就读不了 .xls）。

    CI 走的就是这条路径（``UTS_NO_AUTO_INSTALL=1``），好让 ``pyproject.toml``
    漏写依赖当场暴露，而不是被自动补装掩盖。
    """
    result = _run_spec(
        tmp_path,
        "cp1252",
        prelude=_MISSING_XLRD,
        env_overrides={"UTS_NO_AUTO_INSTALL": "1"},
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, "缺依赖时构建不应该成功"
    assert "FATAL missing-runtime-dependencies" in output
    assert "xlrd" in output
    assert "pip install xlrd" in output  # 报错要能直接照着修
    assert "SPEC_EXEC_OK" not in result.stdout  # 没走到最后的 Analysis


def test_spec_does_not_hang_when_dependency_is_missing(tmp_path):
    """缺依赖且处于非交互环境时，必须立刻失败而不是等用户输入。

    构建脚本卡在 ``input()`` 上是很难排查的故障：CI 会一直等到超时。
    """
    result = _run_spec(tmp_path, "cp1252", prelude=_MISSING_XLRD)

    assert result.returncode != 0
    assert "non-interactive: skip auto-install" in result.stdout
    assert "pip install xlrd" in result.stdout  # 走到了"给出人工安装命令"这一步


def test_spec_delegates_the_dependency_check_to_ensure_deps():
    """守卫逻辑必须复用 packaging/ensure_deps.py，不能自己再写一套。

    run.bat / build.bat 用的是同一个脚本，三处判断才能保证一致。
    """
    source = SPEC_PATH.read_text(encoding="utf-8")

    assert "def verify_runtime_dependencies" in source
    assert "verify_runtime_dependencies()" in source
    assert "ensure_deps.py" in source


def test_ensure_deps_reads_the_apps_own_dependency_registry():
    """清单必须来自 ``core/deps.py``，不能另写一份——否则两处迟早对不上。

    注意它是**读源码**而不是 import：``core/__init__.py`` 会连带导入 pandas，
    真去 import 会在"没装 pandas 的机器"上当场崩掉（那正是它要处理的场景）。
    解析结果与真实对象的一致性由 tests/test_ensure_deps.py 的对照用例保证。
    """
    source = (PROJECT_ROOT / "packaging" / "ensure_deps.py").read_text(encoding="utf-8")

    assert "REGISTRY_SOURCE" in source
    assert "core" in source and "deps.py" in source
