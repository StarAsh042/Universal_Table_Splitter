"""打包配置（``packaging/table_splitter.spec``）的回归测试。

spec 在 PyInstaller 里就是一段被执行的普通 Python。它打印的中文只要控制台装不下
就会抛 ``UnicodeEncodeError`` —— GitHub 的 ``windows-latest`` 正是英文环境（cp1252），
1.1.0 的自动打包就在这一步失败过（``character maps to <undefined>``）。

这里用桩替换 PyInstaller 注入的名字，直接在 cp1252 环境下执行 spec，
既复现了那个环境，又不需要真正安装 PyInstaller。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


def _run_spec(tmp_path: Path, io_encoding: str, prelude: str = "") -> subprocess.CompletedProcess:
    """在指定标准流编码下执行 spec（cp1252 即英文 Windows / GitHub runner 的环境）。

    ``prelude`` 会在执行 spec **之前**运行，用来模拟"没装 tkinterdnd2"或
    "collect_all 收不到文件"这类环境。
    """
    runner = tmp_path / "run_spec.py"
    runner.write_text(_RUNNER.format(spec=str(SPEC_PATH), prelude=prelude), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(runner)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": io_encoding},
        cwd=tmp_path,
    )


def test_spec_runs_on_cp1252_console(tmp_path):
    """英文 Windows（cp1252）下 spec 必须能跑完——1.1.0 的打包就是在这里挂的。"""
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


#: 让 ``import tkinterdnd2`` 直接失败（sys.modules 里置 None 会抛 ImportError）
_NO_DND_EXTRA = """
import sys
sys.modules["tkinterdnd2"] = None
"""

#: 装了 tkinterdnd2，但 collect_all 一个文件都收不到
_EMPTY_COLLECT = """
import PyInstaller.utils.hooks as hooks
hooks.collect_all = lambda name: ([], [], [])
"""


def test_spec_warns_but_continues_when_dnd_extra_is_missing(tmp_path):
    """没装 [dnd] extra 时只告警并继续构建——1.1.0 发布版就是这么少了拖放而无人察觉。"""
    result = _run_spec(tmp_path, "cp1252", prelude=_NO_DND_EXTRA)

    assert result.returncode == 0, result.stderr
    assert "WARNING: tkinterdnd2 not installed" in result.stdout
    assert "SPEC_EXEC_OK" in result.stdout


def test_spec_refuses_to_build_when_tkdnd_is_not_collected(tmp_path):
    """装了依赖却收不到任何 tkdnd 文件时必须让构建失败，不能发出缺功能的包。"""
    pytest.importorskip("tkinterdnd2")  # 该分支要求真的能 import 成功
    result = _run_spec(tmp_path, "cp1252", prelude=_EMPTY_COLLECT)

    assert result.returncode != 0
    assert "refusing to build a bundle without drag and drop" in (result.stderr + result.stdout)
