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

相比原始写法（``--hidden-import`` + ``--add-data="C:\\Python\\...\\ttkbootstrap;..."``）
的改进：路径不再写死到某台机器，ttkbootstrap 的**主题数据文件**由
``collect_all`` 自动收集，因此换主题（darkly / litera）不会因为缺文件而报错。
"""

import os
import re
import sys
import tempfile
from pathlib import Path

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
         StringStruct('LegalCopyright', 'GNU AGPL v3.0'),
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

datas: list = []
binaries: list = []
hiddenimports: list = []

# ttkbootstrap 的主题是 json 数据文件，openpyxl 有运行时动态导入，都需要整体收集
for package in ("ttkbootstrap", "openpyxl"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# tkinterdnd2 是可选依赖（拖放）。app 里是延迟导入，PyInstaller 静态分析看不到，
# 必须显式收集；否则打包版会因为找不到 tkdnd 运行库而禁用拖放。
# 它自带的 tkdnd 目录里有各平台的 .dll/.tcl，属于纯数据文件，同样要一并收集。
try:
    dnd_datas, dnd_binaries, dnd_hidden = collect_all("tkinterdnd2")
except Exception:  # 未安装该可选依赖时跳过
    pass
else:
    datas += dnd_datas
    binaries += dnd_binaries
    hiddenimports += dnd_hidden

# pandas / xlrd 在打包后常见的漏收集项
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
    excludes=["matplotlib", "scipy", "pytest", "IPython", "tkinter.test"],
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
