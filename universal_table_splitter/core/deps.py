"""可选依赖自检。

原实现只在用户跑到一半时才因缺少 openpyxl/xlwt 报错（且错误文案未本地化）。
这里在启动时一次性探测，缺失的能力在 UI 上提前说明。
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from ..errors import DependencyError


@dataclass(frozen=True)
class Dependency:
    module: str
    package: str
    feature_key: str
    required: bool = False


DEPENDENCIES: tuple[Dependency, ...] = (
    Dependency("pandas", "pandas", "dep.pandas", required=True),
    Dependency("openpyxl", "openpyxl", "dep.openpyxl"),
    Dependency("xlrd", "xlrd", "dep.xlrd"),
    Dependency("ttkbootstrap", "ttkbootstrap", "dep.ttkbootstrap"),
    Dependency("tkinterdnd2", "tkinterdnd2", "dep.tkinterdnd2"),
)


def is_available(module: str) -> bool:
    """不执行导入即可判断模块是否可用（避免引入导入副作用）。"""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # 父包缺失等异常情况
        return False


def missing_dependencies() -> tuple[Dependency, ...]:
    return tuple(dep for dep in DEPENDENCIES if not is_available(dep.module))


def ensure_required() -> None:
    """核心依赖缺失时立即给出可操作的提示。"""
    for dep in DEPENDENCIES:
        if dep.required and not is_available(dep.module):
            raise DependencyError(name=dep.module, hint=dep.package)
