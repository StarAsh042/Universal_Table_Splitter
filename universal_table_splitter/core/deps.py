"""可选依赖自检。

在启动时一次性探测，缺失的能力在 UI 上提前说明——而不是等用户跑到一半才
因缺少 openpyxl 之类的依赖报错。
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
    # 界面层用 PySide6：样式由 ui/theme.py 的全局 QSS 提供，拖放用 Qt 原生能力，
    # 因此不需要 ttkbootstrap / tkinterdnd2 这类第三方运行库。
    # 注意这里**不能**标成 required：cli.py 会调用 ensure_required()，
    # 标了会让"没装 PySide6 的纯命令行用户"直接跑不起来。
    Dependency("PySide6", "PySide6", "dep.pyside6"),
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
