"""统一的异常体系。

设计要点：
- 业务异常只携带 **i18n key + 上下文**，不携带面向用户的自然语言文案，
  由 UI / CLI 层调用 ``i18n.tr`` 渲染，彻底消除"错误文案语言混杂"的问题。
- ``CanceledByUser`` 是控制流信号而非错误，单独继承 ``Exception``，
  并携带已产生的部分结果，便于上层询问是否清理。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .core.job import SplitResult


class AppError(Exception):
    """携带 i18n key 的业务异常。"""

    default_key = "err.unexpected"

    def __init__(self, key: str | None = None, **ctx: Any) -> None:
        self.key = key or self.default_key
        self.ctx = ctx
        super().__init__(f"{self.key} {ctx}" if ctx else self.key)

    def as_dict(self) -> dict[str, Any]:
        """序列化，便于跨线程通过队列传递。"""
        return {"key": self.key, "ctx": dict(self.ctx)}


class ValidationError(AppError):
    """参数校验失败。"""

    default_key = "err.invalid_params"


class FileFormatError(AppError):
    """输入文件格式不受支持或无法解析。"""

    default_key = "err.invalid_file"


class DependencyError(AppError):
    """缺少运行所需的可选依赖。"""

    default_key = "err.missing_dep"


class OutputError(AppError):
    """输出目录或写入过程出错。"""

    default_key = "err.output_not_writable"


class CanceledByUser(Exception):
    """用户中止任务；携带已经生成的输出，供上层决定是否清理。"""

    def __init__(self, partial: SplitResult | None = None) -> None:
        self.partial = partial
        super().__init__("canceled by user")
