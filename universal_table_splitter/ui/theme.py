"""主题探测与 DPI 感知。

修复的原始问题：
- ``SetProcessDpiAwareness`` 在窗口创建**之后**才调用，等于没生效；
- 用 ``DwmGetColorizationColor`` 的蓝色分量判断深色模式，与"应用深色模式"无关；
- 非 Windows 平台永远落到浅色主题（README 却宣称跨平台自适配）；
- 裸 ``except:`` 吞掉一切异常，无法排查。
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import subprocess
import sys
import tkinter as tk
from tkinter import TclError
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:  # ttkbootstrap 是可选增强：缺失时退化为原生 ttk，界面依旧可用
    from ttkbootstrap import Style
except Exception:  # pragma: no cover - 取决于运行环境
    Style = None  # type: ignore[assignment]

HAS_TTKB = Style is not None

DARK_THEME = "darkly"
LIGHT_THEME = "litera"
FALLBACK_ACCENT = "#1f6feb"


def enable_dpi_awareness() -> None:
    """必须在创建任何窗口之前调用，否则高分屏下窗口会被系统拉伸导致模糊。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            logger.debug("DPI awareness unavailable", exc_info=True)


def detect_dark_mode() -> bool:
    """按平台读取"应用外观"设置。"""
    if sys.platform == "win32":
        return _windows_dark_mode()
    if sys.platform == "darwin":
        return _macos_dark_mode()
    return False


def _windows_dark_mode() -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except (OSError, ValueError, ImportError):
        logger.debug("cannot read Windows theme, defaulting to light", exc_info=True)
        return False


def _macos_dark_mode() -> bool:
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("cannot read macOS theme", exc_info=True)
        return False
    return "dark" in result.stdout.lower()


def create_style(root: tk.Misc, dark: bool) -> object | None:
    """创建 ttkbootstrap 主题；不可用时返回 ``None``（调用方退化为原生 ttk）。

    ttkbootstrap 不同版本的关键字不同，因此按 ``theme`` -> ``themename`` -> 空参
    依次尝试。**降级路径会记录日志**：一旦悄悄走到备选调用方式，主题可能不是
    期望的那一个，排查时必须能从日志里看出来。
    """
    if not HAS_TTKB or Style is None:
        return None
    theme = DARK_THEME if dark else LIGHT_THEME
    for index, kwargs in enumerate(({"theme": theme}, {"themename": theme}, {})):
        try:
            style = Style(**kwargs)  # type: ignore[arg-type]
        except TypeError:
            logger.debug("Style(%r) 不被支持，尝试下一种调用方式", kwargs)
            continue
        except Exception:  # pragma: no cover - 主题数据损坏等
            logger.warning("ttkbootstrap 主题 %s 创建失败，改用原生 ttk", theme, exc_info=True)
            return None
        if index:
            logger.warning(
                "ttkbootstrap 走了降级调用 %r，实际主题可能不是 %s，界面配色可能与预期不同",
                kwargs,
                theme,
            )
        return style
    logger.warning("ttkbootstrap 无法初始化，改用原生 ttk")
    return None


def bootstyle(*values: str) -> dict[str, str]:
    """ttkbootstrap 存在时返回 ``{'bootstyle': ...}``，否则返回空字典。

    这样同一份界面代码既能在有 ttkbootstrap 时获得配色，也能在缺失时正常渲染。
    """
    if not HAS_TTKB or not values:
        return {}
    return {"bootstyle": " ".join(values)}


def styled(factory: Callable[..., Any], spec: str = "", **kwargs: Any) -> Any:
    """创建 ttk 控件并套用 bootstyle，样式不可用时逐级降级。

    ``spec`` 可以是 ``"a|b|c"`` 形式：按顺序尝试，第一个能用就用它。
    为什么需要它：ttkbootstrap 的部分 bootstyle（如 ``round-toggle``）依赖主题里
    已注册好的 layout 与图片资源，在 PyInstaller 打包环境或自定义主题下可能缺失，
    此时 ``ttk.Checkbutton(bootstyle="round-toggle")`` 会抛
    ``TclError: Layout Round.Toggle not found``。界面美观属于增强项，
    绝不能因此让整个程序启动失败——所以这里逐级降级，最后退回原生 ttk。
    """
    candidates = [part.strip() for part in spec.split("|") if part.strip()]
    if not candidates or not HAS_TTKB:
        return factory(**kwargs)
    for candidate in candidates:
        try:
            return factory(**bootstyle(candidate), **kwargs)
        except TclError:
            logger.warning("bootstyle %r 不可用，尝试下一个候选", candidate, exc_info=True)
    return factory(**kwargs)


def accent_color(style: object | None) -> str:
    colors = getattr(style, "colors", None)
    return getattr(colors, "info", FALLBACK_ACCENT) if colors else FALLBACK_ACCENT


def apply_bootstyle(widget: Any, spec: str) -> None:
    """运行期替换控件样式（例如主按钮在"开始/取消"之间切换配色）。

    样式不可用时静默保留原样：这只是外观，绝不该影响功能。
    """
    if not HAS_TTKB or not spec:
        return
    with contextlib.suppress(TclError):
        widget.configure(bootstyle=spec)


def disable_ttkbootstrap(reason: str = "") -> None:
    """运行期关闭 ttkbootstrap 增强。

    作为最后一道保险：万一在某个环境下用 ttkbootstrap 构建界面失败，
    调用方可以在重建界面前调用本函数，让界面退回原生 ttk 继续可用。
    """
    global HAS_TTKB
    if HAS_TTKB:
        logger.warning("已禁用 ttkbootstrap 增强：%s", reason or "未知原因")
    HAS_TTKB = False
