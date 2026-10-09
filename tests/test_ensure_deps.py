"""``packaging/ensure_deps.py`` 的单元测试。

这个脚本同时被打包（``table_splitter.spec``）和源码启动（``run.bat`` / ``build.bat``）
复用，它判断错了会导致两种**相反**的灾难：

- 该装的不装 → 用户拿到一个悄悄少了功能的 exe；
- 不该装的装了 → 构建过程静默联网下载几十 MB，或者 CI 卡在 ``input()`` 上直到超时。

所以下面把两条路径都钉死：联网安装只在"用户确认 + 交互环境 + 没被禁用"三者同时成立时才发生。
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENSURE_PATH = PROJECT_ROOT / "packaging" / "ensure_deps.py"


def _load_module():
    """按文件路径加载——``packaging/`` 不在包内，普通 import 找不到。"""
    spec = importlib.util.spec_from_file_location("_test_ensure_deps", ENSURE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ensure_deps = _load_module()


@pytest.fixture
def no_install_env(monkeypatch):
    """确保环境里没有 UTS_NO_AUTO_INSTALL，避免开发者本机设置影响测试。"""
    monkeypatch.delenv(ensure_deps.NO_INSTALL_ENV, raising=False)
    return ensure_deps.NO_INSTALL_ENV


def install_registry(monkeypatch, available: set, modules: tuple[str, ...]) -> set:
    """换成可控的假注册表；返回可变的 ``available`` 集合，测试里可以中途改。"""
    registry = tuple(ensure_deps.Dependency(name, name) for name in modules)

    monkeypatch.setattr(ensure_deps, "read_registry", lambda: registry)
    monkeypatch.setattr(ensure_deps, "is_available", lambda name: name in available)
    return available


def record_installs(monkeypatch, *, succeed: bool = True, on_install=None) -> list:
    """替换 install_packages，记录被安装的包名（默认不真的联网）。"""
    calls: list[list[str]] = []

    def fake_install(packages, **kwargs):
        calls.append(list(packages))
        if succeed and on_install is not None:
            on_install(packages)
        return succeed

    monkeypatch.setattr(ensure_deps, "install_packages", fake_install)
    return calls


def dep(module: str) -> ensure_deps.Dependency:
    return ensure_deps.Dependency(module, module)


# --------------------------------------------------------------------- 清单来源


def test_ensure_deps_never_imports_the_project_package():
    """脚本必须能在"连 pandas 都没装"的机器上跑起来，所以不能 import 自己的包。

    ``universal_table_splitter/core/__init__.py`` 会连带导入 ``job``，而 ``job``
    又 ``import pandas``——一旦 import 就当场 ModuleNotFoundError，形成
    "为了修缺依赖而必须先有依赖"的死锁。这个坑在干净 venv 里实测必现，
    所以用静态检查把"读源码、不导入"这条约定钉死。
    """
    tree = ast.parse(ENSURE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("universal_table_splitter"), node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("universal_table_splitter"), alias.name


def test_parsed_registry_matches_the_real_module():
    """解析结果必须和 ``core/deps.py`` 里真实的对象逐条一致。

    "读源码"这层间接一旦跑偏（比如有人改成动态构造），这里立刻报警。
    本测试环境里 pandas 是装好的，可以安全导入真实模块做对照。
    """
    from universal_table_splitter.core.deps import DEPENDENCIES

    parsed = [(d.module, d.package) for d in ensure_deps.read_registry()]
    actual = [(d.module, d.package) for d in DEPENDENCIES]
    assert parsed == actual


def test_parsed_registry_is_not_empty():
    assert len(ensure_deps.read_registry()) >= 3


def test_parse_rejects_a_dynamic_registry():
    """换成动态构造时必须明确报错，而不是悄悄漏检。"""
    with pytest.raises(SystemExit):
        ensure_deps._parse_registry("DEPENDENCIES = build_registry()\n")


def test_parse_rejects_entries_that_are_not_literal():
    with pytest.raises(SystemExit):
        ensure_deps._parse_registry("DEPENDENCIES = (make(name),)\n")


# --------------------------------------------------------------------- 查找缺失


def test_find_missing_is_empty_when_everything_is_installed(monkeypatch):
    install_registry(monkeypatch, {"pandas", "xlrd"}, ("pandas", "xlrd"))
    assert ensure_deps.find_missing() == ()


def test_find_missing_lists_absent_modules(monkeypatch):
    install_registry(monkeypatch, {"pandas"}, ("pandas", "xlrd"))
    missing = ensure_deps.find_missing()
    assert [d.module for d in missing] == ["xlrd"]


def test_find_missing_honours_skip(monkeypatch):
    """纯命令行场景不需要 PySide6，用 --skip 把它排除掉。"""
    install_registry(monkeypatch, set(), ("pandas", "PySide6"))
    missing = ensure_deps.find_missing(skip=("PySide6",))
    assert [d.module for d in missing] == ["pandas"]


def test_find_missing_reports_everything_in_a_clean_environment(monkeypatch):
    """干净环境（什么都没装）时要把四项全列出来，而不是只报第一个。"""
    install_registry(monkeypatch, set(), ("pandas", "PySide6", "openpyxl", "xlrd"))
    assert len(ensure_deps.find_missing()) == 4


def test_is_available_handles_unimportable_parent(monkeypatch):
    """``find_spec`` 对父包缺失的模块会抛 ImportError，必须当成"不可用"。"""

    def boom(name, *args, **kwargs):
        raise ImportError("no parent package")

    monkeypatch.setattr(ensure_deps.importlib.util, "find_spec", boom)
    assert ensure_deps.is_available("pandas") is False


# --------------------------------------------------------------------- 校验主流程


def test_ensure_succeeds_without_touching_the_network(monkeypatch, capsys):
    install_registry(monkeypatch, {"pandas"}, ("pandas",))
    calls = record_installs(monkeypatch)

    assert ensure_deps.ensure() == 0
    assert calls == []  # 什么都不缺，绝不该联网
    assert "runtime dependencies OK" in capsys.readouterr().out


def test_ensure_fails_when_auto_install_is_disabled(monkeypatch, capsys, no_install_env):
    """CI 走这条路：缺依赖就失败，让 pyproject.toml 的问题当场暴露。"""
    monkeypatch.setenv(no_install_env, "1")
    install_registry(monkeypatch, set(), ("pandas",))
    calls = record_installs(monkeypatch)

    assert ensure_deps.ensure() == 1
    assert calls == []  # 被禁用就不许装
    output = capsys.readouterr().out
    assert "auto-install disabled" in output
    assert "pip install pandas" in output


def test_ensure_fails_without_prompting_in_non_interactive_environment(
    monkeypatch, capsys, no_install_env
):
    """非交互环境不能提问：构建卡在 input() 上是极难排查的故障。"""
    install_registry(monkeypatch, set(), ("pandas",))
    calls = record_installs(monkeypatch)
    monkeypatch.setattr(ensure_deps, "_is_interactive", lambda: False)

    assert ensure_deps.ensure() == 1
    assert calls == []
    assert "non-interactive: skip auto-install" in capsys.readouterr().out


def test_ensure_installs_after_the_user_confirms(monkeypatch, capsys, no_install_env):
    available = install_registry(monkeypatch, set(), ("pandas", "xlrd"))
    calls = record_installs(monkeypatch, on_install=available.update)
    monkeypatch.setattr(ensure_deps, "_is_interactive", lambda: True)
    monkeypatch.setattr(ensure_deps, "_ask", lambda missing: True)

    assert ensure_deps.ensure() == 0
    assert calls == [["pandas", "xlrd"]]  # 一次装完，不是逐个装
    assert "依赖已补齐" in capsys.readouterr().out


def test_ensure_does_not_install_when_the_user_declines(monkeypatch, capsys, no_install_env):
    install_registry(monkeypatch, set(), ("pandas",))
    calls = record_installs(monkeypatch)
    monkeypatch.setattr(ensure_deps, "_is_interactive", lambda: True)
    monkeypatch.setattr(ensure_deps, "_ask", lambda missing: False)

    assert ensure_deps.ensure() == 1
    assert calls == []
    assert "pip install pandas" in capsys.readouterr().out


def test_ensure_installs_unattended_when_ask_is_false(monkeypatch, capsys, no_install_env):
    """``--no-ask`` 的语义就是"别问，直接装"，不能被"非交互"反过来拦住。"""
    available = install_registry(monkeypatch, set(), ("pandas",))
    calls = record_installs(monkeypatch, on_install=available.update)
    monkeypatch.setattr(ensure_deps, "_is_interactive", lambda: False)

    assert ensure_deps.ensure(ask=False) == 0
    assert calls == [["pandas"]]
    assert "依赖已补齐" in capsys.readouterr().out


def test_ensure_fails_when_pip_fails(monkeypatch, capsys, no_install_env):
    install_registry(monkeypatch, set(), ("pandas",))
    record_installs(monkeypatch, succeed=False)
    monkeypatch.setattr(ensure_deps, "_is_interactive", lambda: True)
    monkeypatch.setattr(ensure_deps, "_ask", lambda missing: True)

    assert ensure_deps.ensure() == 1
    assert "pip 安装失败" in capsys.readouterr().out


def test_ensure_fails_when_the_module_is_still_missing_after_install(
    monkeypatch, capsys, no_install_env
):
    """pip 返回 0 但模块还是导不进来（装错解释器、装了空壳包）——不能当成功。"""
    install_registry(monkeypatch, set(), ("pandas",))
    record_installs(monkeypatch)  # 不更新 available，模拟"装了却没用"
    monkeypatch.setattr(ensure_deps, "_is_interactive", lambda: True)
    monkeypatch.setattr(ensure_deps, "_ask", lambda missing: True)

    assert ensure_deps.ensure() == 1
    assert "安装后仍有缺失" in capsys.readouterr().out


# --------------------------------------------------------------------- 安装命令


def test_install_packages_targets_the_running_interpreter(capsys):
    """必须用当前解释器的 ``-m pip``，不能靠 PATH 上的 ``pip``。

    PATH 上的 pip 可能属于另一个 Python（本机就有两个），装完等于没装。
    """
    recorded: list[list[str]] = []

    class Completed:
        returncode = 0

    def runner(command):
        recorded.append(command)
        return Completed()

    assert ensure_deps.install_packages(["pandas", "xlrd"], runner=runner) is True
    assert recorded == [[sys.executable, "-m", "pip", "install", "pandas", "xlrd"]]


def test_install_packages_with_nothing_to_do_skips_pip():
    def runner(command):  # pragma: no cover - 不该被调用
        raise AssertionError("空列表不该调用 pip")

    assert ensure_deps.install_packages([], runner=runner) is True


# --------------------------------------------------------------------- 询问


@pytest.mark.parametrize("answer", ["", "y", "Y", "yes", "YES", " yes "])
def test_ask_treats_these_answers_as_yes(monkeypatch, answer):
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    assert ensure_deps._ask([dep("pandas")]) is True


@pytest.mark.parametrize("answer", ["n", "no", "N", "算了"])
def test_ask_treats_these_answers_as_no(monkeypatch, answer):
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    assert ensure_deps._ask([dep("pandas")]) is False


def test_ask_survives_closed_stdin(monkeypatch):
    """管道关闭 / Ctrl-C 时不能抛出去，只能当成"不装"。"""

    def boom(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", boom)
    assert ensure_deps._ask([dep("pandas")]) is False


# --------------------------------------------------------------------- 环境变量


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_auto_install_disabled_reads_truthy_values(monkeypatch, value):
    monkeypatch.setenv(ensure_deps.NO_INSTALL_ENV, value)
    assert ensure_deps.auto_install_disabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_auto_install_disabled_ignores_falsy_values(monkeypatch, value):
    monkeypatch.setenv(ensure_deps.NO_INSTALL_ENV, value)
    assert ensure_deps.auto_install_disabled() is False


# --------------------------------------------------------------------- 命令行入口


def test_main_forwards_skip_to_ensure(monkeypatch):
    seen: dict = {}

    def fake_ensure(*, ask=True, skip=()):
        seen["ask"] = ask
        seen["skip"] = skip
        return 0

    monkeypatch.setattr(ensure_deps, "ensure", fake_ensure)

    assert ensure_deps.main(["--skip", "PySide6,pandas"]) == 0
    assert seen == {"ask": True, "skip": ("PySide6", "pandas")}


def test_main_no_ask_flag(monkeypatch):
    seen: dict = {}

    def fake_ensure(*, ask=True, skip=()):
        seen["ask"] = ask
        return 0

    monkeypatch.setattr(ensure_deps, "ensure", fake_ensure)

    assert ensure_deps.main(["--no-ask"]) == 0
    assert seen["ask"] is False
