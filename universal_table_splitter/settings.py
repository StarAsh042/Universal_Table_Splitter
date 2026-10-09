"""跨平台的配置目录定位与用户偏好持久化。

偏好文件损坏或字段缺失时一律回退到默认值，绝不因为"记不住上次设置"而崩溃。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .config import (
    APP_SLUG,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_EXPORT_FORMAT,
    DEFAULT_LANG,
    DEFAULT_NUM_FORMAT,
    WINDOW_GEOMETRY,
)


def _windows_appdata(env: str, fallback: str) -> Path:
    base = os.environ.get(env)
    return Path(base) if base else Path.home() / fallback


def config_dir() -> Path:
    """用户配置目录（各平台惯例位置）。"""
    if sys.platform == "win32":
        return _windows_appdata("APPDATA", "AppData/Roaming") / APP_SLUG
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_SLUG
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / APP_SLUG


def log_dir() -> Path:
    """日志目录。"""
    if sys.platform == "win32":
        return _windows_appdata("LOCALAPPDATA", "AppData/Local") / APP_SLUG / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / APP_SLUG
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / APP_SLUG / "logs"


def settings_path() -> Path:
    return config_dir() / "settings.json"


@dataclass
class Settings:
    """记忆用户上次使用的参数，避免每次重新输入。"""

    chunk_size: int = DEFAULT_CHUNK_SIZE
    num_format: str = DEFAULT_NUM_FORMAT
    export_format: str = DEFAULT_EXPORT_FORMAT
    lang: str = DEFAULT_LANG
    fidelity: bool = True
    escape_formulas: bool = False
    last_input_dir: str = ""
    last_output_dir: str = ""
    geometry: str = WINDOW_GEOMETRY

    # ------------------------------------------------------------------ 读写
    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        target = path or settings_path()
        defaults = cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return defaults
        if not isinstance(raw, dict):
            return defaults
        kwargs: dict[str, Any] = {}
        for field in fields(cls):
            if field.name in raw:
                kwargs[field.name] = _coerce(raw[field.name], getattr(defaults, field.name))
        try:
            return cls(**kwargs)
        except TypeError:  # pragma: no cover - 理论上不会发生
            return defaults

    def save(self, path: Path | None = None) -> None:
        target = path or settings_path()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, target)
        except OSError:
            # 记不住设置不是致命错误，静默忽略
            pass


def _coerce(value: Any, default: Any) -> Any:
    """按默认值的类型做宽松转换，失败则回退默认值。"""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    return default
