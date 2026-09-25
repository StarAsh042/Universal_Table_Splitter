"""版本号单一来源测试。

版本号要同时出现在三处：标题栏、exe 的属性信息、包元数据。
只要 ``__init__.py`` 是唯一来源，这三处就不会各说各话——本文件把这套约定钉住。
"""

from __future__ import annotations

import re
from pathlib import Path

from universal_table_splitter import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_version_format():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_pyproject_takes_version_from_package():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = { attr = "universal_table_splitter.__version__" }' in text


def test_build_spec_reads_the_same_source():
    """打包脚本必须从包里读版本，并生成 Windows 版本资源。"""
    text = (REPO_ROOT / "packaging" / "table_splitter.spec").read_text(encoding="utf-8")
    assert "from universal_table_splitter import __version__" in text
    assert "VSVersionInfo" in text  # 版本资源内容
    assert "version=str(VERSION_FILE)" in text  # 传给 EXE


def test_package_init_stays_import_light():
    """``__init__.py`` 必须保持轻薄：打包脚本会直接导入它来读取版本号。"""
    text = (REPO_ROOT / "universal_table_splitter" / "__init__.py").read_text(encoding="utf-8")
    assert "import pandas" not in text
    assert "import tkinter" not in text
