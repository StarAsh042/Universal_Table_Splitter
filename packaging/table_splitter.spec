# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（替代 README 里那串带本机绝对路径的长命令）。

推荐用法（会自动处理依赖、图标、输出目录与日志）：
    packaging\\build.bat                     打包到 packaging\\output\\dist
    packaging\\build.bat -o D:\\发布 -i 图标.ico

直接使用本文件：
    pip install pyinstaller
    pyinstaller packaging/table_splitter.spec

产物：含 Python 与全部依赖的**单文件**可执行程序。

可通过环境变量覆盖两项设置（``build.bat`` 就是这么传参的，
因为 PyInstaller 在收到 .spec 文件时会忽略 --icon/--name 之类的命令行选项）：

    UTS_APP_NAME   产物名称，默认 表格分割器
    UTS_ICON       ico 图标路径；不设置时自动使用 assets/app.ico（若存在）

路径不写死到某台机器，需要整体收集的包由 ``collect_all`` 自动处理。

界面层用 PySide6，样式与拖放都由 Qt 提供：
- **不收集 ttkbootstrap / tkinterdnd2**：样式走 ui/theme.py 的全局 QSS，
  拖放走 Qt 原生能力，都不需要第三方运行库；
- **显式排除 tkinter**：省掉 tcl/tk 运行库（约 10 MB），也避免它被间接拉进来；
- **PySide6 交给 PyInstaller 自带的 hook 处理**：不要 ``collect_all("PySide6")``，
  那会把 QtWebEngine、Qt3D 之类的全部塞进去，产物直接翻倍。
"""

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

# 英文 Windows（含 GitHub 的 windows runner）控制台编码是 cp1252，直接 print 中文会抛
# UnicodeEncodeError 并让整个打包失败；先把标准流的编码错误策略改成"替换"，
# 中文控制台（cp936 / UTF-8）的输出不受任何影响。
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(errors="replace")
        except (ValueError, OSError):  # pragma: no cover - 流不可重配置时忽略
            pass

from PyInstaller.utils.hooks import collect_all

PROJECT_ROOT = Path(SPECPATH).resolve().parent
APP_NAME = os.environ.get("UTS_APP_NAME") or "表格分割器"
ENTRY_SCRIPT = str(PROJECT_ROOT / "splitter.py")


def read_app_version() -> str:
    """读取应用版本号，唯一来源是 ``universal_table_splitter/__init__.py``。

    优先直接导入那个薄模块（它只定义 ``__version__``，不会拉起 pandas/tkinter）；
    万一导入失败（路径或环境异常），再退化为正则读源码，确保打包脚本总能拿到版本。
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from universal_table_splitter import __version__

        return __version__
    except Exception:
        init_file = PROJECT_ROOT / "universal_table_splitter" / "__init__.py"
        pattern = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
        match = pattern.search(init_file.read_text(encoding="utf-8"))
        if not match:
            raise SystemExit(f"无法从 {init_file} 读取 __version__") from None
        return match.group(1)
    finally:
        sys.path.remove(str(PROJECT_ROOT))


def verify_runtime_dependencies() -> None:
    """打包前校验运行时依赖；缺失时询问用户，确认后自动从 PyPI 安装。

    为什么必须挡住：``hiddenimports`` 里的 ``"xlrd"`` 是"软"的——打包机上没装
    xlrd 时它静默失效，exe 照样构建成功，但用户打开 .xls 才报错。代价是用户
    拿到一个缺功能的包却无人察觉。

    具体逻辑（校验 → 询问 → pip 安装 → 复验）在 ``packaging/ensure_deps.py`` 里，
    与 ``run.bat`` 共用一份，避免两处判断不一致。依赖清单则来自
    ``universal_table_splitter.core.deps.DEPENDENCIES``，与应用内提示同源。

    用文件路径显式加载而不是 ``import ensure_deps``：后者依赖 sys.path 里恰好有
    ``packaging/``，换个调用方式（比如 IDE 里直接跑 spec）就会失效。
    """
    spec = importlib.util.spec_from_file_location(
        "_uts_ensure_deps", PROJECT_ROOT / "packaging" / "ensure_deps.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - 文件一定存在
        raise SystemExit("[table_splitter.spec] FATAL cannot load packaging/ensure_deps.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if module.ensure() != 0:
        raise SystemExit(
            "[table_splitter.spec] FATAL missing-runtime-dependencies: "
            "打出来的 exe 会静默缺失对应功能，已中止构建。"
        )


def write_version_resource(version: str) -> Path:
    """生成 Windows 版本资源文件，使 exe 的“属性 → 详细信息”也显示版本号。

    PyInstaller 的 ``version=`` 只认这种 ``VSVersionInfo(...)`` 文本格式，
    因此这里根据 ``__version__`` 现场生成，避免手工维护第二份版本号。
    """
    parts = [part if part.isdigit() else "0" for part in version.split(".")]
    numbers = ", ".join((parts + ["0", "0", "0", "0"])[:4])
    # 语言/代码页 0804 = 简体中文，04b0 = Unicode；VarStruct 里的 1200 与之对应
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numbers}),
    prodvers=({numbers}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [StringStruct('CompanyName', 'StarAsh042'),
         StringStruct('FileDescription', '通用表格分割器 · 按行数把大表切成多个文件'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', '{APP_NAME}'),
         StringStruct('LegalCopyright', 'MIT License'),
         StringStruct('OriginalFilename', '{APP_NAME}.exe'),
         StringStruct('ProductName', '{APP_NAME}'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0804, 1200])])
  ]
)
"""
    target = Path(tempfile.gettempdir()) / "uts_version_info.txt"
    # 带 BOM 写出：PyInstaller 读取时会优先识别 BOM，中文才不会乱码
    target.write_text(content, encoding="utf-8-sig")
    return target


APP_VERSION = read_app_version()
VERSION_FILE = write_version_resource(APP_VERSION)
# spec 在 PyInstaller 里就是普通 Python，这行会直接出现在 build.log，便于核对打进去的版本
print(f"[table_splitter.spec] 应用版本 {APP_VERSION} / 名称 {APP_NAME}")

# 显式通过环境变量指定的图标必须存在，否则让 PyInstaller 直接报错（不静默降级）；
# 未指定时才回退到约定的 assets/app.ico，找不到就用 PyInstaller 默认图标。
_icon_env = os.environ.get("UTS_ICON")
if _icon_env:
    ICON = Path(_icon_env)
    if not ICON.is_file():
        raise SystemExit(f"UTS_ICON 指向的图标不存在：{ICON}")
else:
    _default_icon = PROJECT_ROOT / "assets" / "app.ico"
    ICON = _default_icon if _default_icon.is_file() else None

# 先验证依赖再干活：缺依赖的话后面收集再多文件也没意义，早失败早报错
verify_runtime_dependencies()

datas: list = []
binaries: list = []
hiddenimports: list = []

# openpyxl 有运行时动态导入，需要整体收集。
# PySide6 不在这里：PyInstaller 自带专门的 hook，会按实际 import 精确收集 Qt 模块
# 与插件（platforms / styles / imageformats）。用 collect_all 反而会把整个 Qt 拖进来。
for package in ("openpyxl",):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# pandas / xlrd 在打包后常见的漏收集项。
# xlrd 由 pandas 在运行时动态加载（pandas.io.excel._xlrd），静态分析看不到，
# 必须显式列出。上面 verify_runtime_dependencies() 已保证它确实装好了，
# 所以这里不会再出现"写了却静默失效"的情况。
hiddenimports += [
    "pandas._libs.tslibs.np_datetime",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.skiplist",
    "xlrd",
]

a = Analysis(  # noqa: F821 - 由 PyInstaller 注入
    [ENTRY_SCRIPT],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 科学计算与测试工具，运行时用不到
        "matplotlib",
        "scipy",
        "pytest",
        "IPython",
        # 界面用 Qt，tk 相关的一切都不需要（省下 tcl/tk 运行库约 10 MB）
        "tkinter",
        "ttkbootstrap",
        "tkinterdnd2",
        "pandastable",
        # 用不到的 Qt 大模块。PyInstaller 的 PySide6 hook 只会收集被 import 的部分，
        # 这里再挡一道，避免间接依赖把它们拖进来（QtWebEngine 单个就上百 MB）
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtDesigner",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtPositioning",
        "PySide6.QtWebSockets",
        "PySide6.QtWebChannel",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 窗口程序，不弹黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # ICON 在上方已归一化为「存在的 Path」或 None
    icon=str(ICON) if ICON else None,
    # Windows 版本资源：exe 属性里的 FileVersion/ProductVersion（非 Windows 平台会被忽略）
    version=str(VERSION_FILE),
)
