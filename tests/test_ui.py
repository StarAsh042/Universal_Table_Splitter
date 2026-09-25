"""界面层测试。

无头环境下会跳过（``pytest.importorskip`` + ``TclError`` 捕获）。
这些测试专门覆盖原实现中最危险的行为：
- 取消后仍然继续写文件、并且可以再开一个线程并发写同一批文件；
- 拖放含空格的路径被 ``str.split()`` 截断而静默失效；
- 运行中切换语言会把进度文本重置为"准备就绪"。
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from universal_table_splitter import __version__  # noqa: E402
from universal_table_splitter.settings import Settings  # noqa: E402
from universal_table_splitter.ui import app as app_module  # noqa: E402
from universal_table_splitter.ui.app import (  # noqa: E402
    AppState,
    UniversalSplitterApp,
    create_root,
)

from .conftest import ROW_COUNT  # noqa: E402


class FakeMessagebox:
    """把模态对话框替换成可断言的记录器（默认全部回答"是"）。"""

    def __init__(self, answer: bool = True) -> None:
        self.infos: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.questions: list[tuple[str, str]] = []
        self.answer = answer

    def showinfo(self, title, message, **kwargs):
        self.infos.append((str(title), str(message)))
        return "ok"

    def showerror(self, title, message, **kwargs):
        self.errors.append((str(title), str(message)))
        return "ok"

    def askyesno(self, title, message, **kwargs):
        self.questions.append((str(title), str(message)))
        return self.answer


def pump(root, predicate, timeout: float = 60.0) -> bool:
    """驱动 Tk 事件循环直到条件满足（等价于"用户等待"）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def ui(monkeypatch):
    try:
        root, dnd = create_root()
    except tk.TclError as exc:  # pragma: no cover - 无显示环境
        pytest.skip(f"no display available: {exc}")

    box = FakeMessagebox()
    # 界面测试聚焦逻辑：不引入 ttkbootstrap 的进程级单例样式，
    # 让 styled() 退化为"无样式创建"（样式本身的降级逻辑在 test_theme.py 单独覆盖）
    monkeypatch.setattr(app_module, "messagebox", box)
    monkeypatch.setattr(app_module, "create_style", lambda root, dark: None)
    monkeypatch.setattr(app_module, "styled", lambda factory, spec="", **kwargs: factory(**kwargs))
    monkeypatch.setattr(app_module, "apply_bootstyle", lambda widget, spec: None)
    monkeypatch.setattr(Settings, "save", lambda self, path=None: None, raising=False)

    app = UniversalSplitterApp(root, Settings(lang="cn"), dnd_enabled=dnd)
    try:
        yield app, box, root
    finally:
        app.closing = True
        with contextlib.suppress(tk.TclError):
            root.destroy()


def test_ui_builds_and_switches_language(ui):
    app, _, root = ui
    assert root.title() == f"通用表格分割器 v{__version__}"
    assert app.lang_btn.cget("text") == "切换英文"

    app.toggle_language()
    assert root.title() == f"Universal Table Splitter v{__version__}"
    assert app.lang_btn.cget("text") == "Switch to Chinese"
    assert app.size_label.cget("text") == "Rows per chunk"

    app.toggle_language()
    assert app.size_label.cget("text") == "每份行数"


def test_window_title_contains_version(ui):
    """标题栏必须带版本号，且切换语言后仍然保留（打包版靠它核对版本）。"""
    app, _, root = ui
    assert __version__ in root.title()
    app.toggle_language()
    assert __version__ in root.title()
    assert root.title().endswith(__version__)


def test_primary_button_text_follows_state(ui):
    app, _, _ = ui
    assert app.primary_btn.cget("text") == "开始分割"
    app._apply_state(AppState.RUNNING)
    assert app.primary_btn.cget("text") == "取消分割"
    app._apply_state(AppState.IDLE)
    assert app.primary_btn.cget("text") == "开始分割"


def test_language_switch_keeps_live_progress_text(ui):
    """原实现用一个永不成立的 ``startswith('Processing')`` 判断，
    导致运行中切换语言时进度被重置为"准备就绪"。"""
    app, _, _ = ui
    app._apply_state(AppState.RUNNING)
    app._set_status("status.running", current="1,000", total="419,789")
    app.toggle_language()
    assert app.status_var.get() == "1,000 / 419,789 rows"
    app.toggle_language()
    assert app.status_var.get() == "1,000 / 419,789 行"


def test_drop_parses_braced_path_with_spaces(ui, tmp_path):
    """tkinterdnd2 会用花括号包裹含空格路径；原实现 ``event.data.split()`` 会截断。"""
    app, box, root = ui
    spaced = tmp_path / "with space"
    spaced.mkdir()
    target = spaced / "artists.csv"
    target.write_text("id\n001\n", encoding="utf-8")

    class Event:
        data = "{" + str(target) + "}"

    app.handle_drop(Event())
    assert app.input_var.get() == str(target)
    assert box.errors == []


def test_drop_folder_sets_output_dir(ui, tmp_path):
    app, _, _ = ui

    class Event:
        data = str(tmp_path)

    app.handle_drop(Event())
    assert app.output_var.get() == str(tmp_path)
    assert app.output_is_auto is False


def test_unsupported_file_is_reported(ui, tmp_path):
    app, box, _ = ui
    bad = tmp_path / "notes.txt"
    bad.write_text("hello", encoding="utf-8")
    app._apply_input_file(bad)
    assert box.errors  # 明确报错，而不是静默忽略


def test_input_file_autofills_output_and_formats(ui, basic_csv):
    app, _, _ = ui
    app.output_var.set("")
    app._apply_input_file(basic_csv)
    assert app.output_var.get() == str(basic_csv.parent)
    assert app.export_var.get() == "csv"
    assert "xlsx" in app.export_combo.cget("values")


def test_invalid_rows_reports_localised_error(ui, basic_csv):
    app, box, _ = ui
    app._apply_input_file(basic_csv)
    app.size_var.set("abc")
    app.start_operation()
    assert box.errors
    assert "每份行数" in box.errors[-1][1]


def test_start_operation_rejects_concurrent_worker(ui, basic_csv):
    """原实现里取消只把 running 置 False，用户再点一次就会并发写同一批文件。"""
    app, box, _ = ui
    app._apply_input_file(basic_csv)

    blocker = threading.Thread(target=lambda: time.sleep(0.6), daemon=True)
    blocker.start()
    app.worker = blocker
    app.start_operation()

    assert app.worker is blocker  # 没有启动第二个线程
    assert any("运行" in message for _, message in box.errors)


def test_end_to_end_split_through_ui(ui, basic_csv, tmp_path):
    app, _, root = ui
    out = tmp_path / "result"
    app._apply_input_file(basic_csv)
    app.output_var.set(str(out))
    app.size_var.set("3")
    app.format_var.set("001")

    app.start_operation()
    assert pump(root, lambda: app.last_result is not None and app.state is AppState.IDLE)

    files = sorted(out.glob("*.csv"))
    assert [path.name for path in files] == [
        "artists_001.csv",
        "artists_002.csv",
        "artists_003.csv",
        "artists_004.csv",
    ]
    assert app.last_result.rows == ROW_COUNT
    assert app.progress["value"] == 100
    assert not list(out.glob(".*part*"))
    assert app.primary_btn.cget("text") == "开始分割"


def test_cancel_immediately_writes_nothing(ui, basic_csv, tmp_path):
    app, _, root = ui
    out = tmp_path / "canceled"
    app._apply_input_file(basic_csv)
    app.output_var.set(str(out))
    app.size_var.set("1")

    app.start_operation()
    app.cancel_operation()  # 工作线程仍在统计阶段
    assert pump(root, lambda: app.state is AppState.IDLE)

    assert app.last_result is None
    assert "取消" in app.status_var.get()
    assert list(out.glob("*.csv")) == []


def test_run_twice_is_stable(ui, basic_csv, tmp_path):
    app, _, root = ui
    app._apply_input_file(basic_csv)
    app.size_var.set("4")
    for index in range(2):
        out = tmp_path / f"run{index}"
        app.output_var.set(str(out))
        app.start_operation()
        assert pump(root, lambda: app.last_result is not None and app.state is AppState.IDLE)
        assert len(list(out.glob("*.csv"))) == 3
        app.last_result = None


def test_overwrite_confirmation_uses_index_policy(ui, basic_csv, tmp_path, monkeypatch):
    app, box, root = ui
    out = tmp_path / "conflict"
    out.mkdir()
    (out / "artists_001.csv").write_text("stale\n", encoding="utf-8")

    app._apply_input_file(basic_csv)
    app.output_var.set(str(out))
    app.size_var.set("3")
    box.answer = False  # 用户在"是否覆盖"上选择"否"

    app.start_operation()
    assert pump(root, lambda: app.state is AppState.IDLE and app.last_result is not None)

    assert (out / "artists_001.csv").read_text(encoding="utf-8") == "stale\n"
    assert (out / "artists_001_1.csv").exists()


def test_about_window_is_reused(ui):
    app, _, _ = ui
    app.show_about()
    first = app.about_window
    assert first is not None
    app.show_about()  # 再次点击应聚焦而不是关闭
    assert app.about_window is first
    app._close_about()
    assert app.about_window is None


def test_open_output_dir_reports_missing_directory(ui):
    app, box, _ = ui
    app.output_var.set(str(Path("does-not-exist-dir")))
    app.open_output_dir()
    assert box.errors


def test_settings_are_persisted_from_widgets(ui):
    app, _, _ = ui
    app.size_var.set("777")
    app.format_var.set("0000")
    app.export_var.set("json")
    app.fidelity_var.set(False)
    app._save_settings()
    assert app.settings.chunk_size == 777
    assert app.settings.num_format == "0000"
    assert app.settings.export_format == "json"
    assert app.settings.fidelity is False


def test_invalid_settings_are_not_persisted(ui):
    app, _, _ = ui
    app.size_var.set("nope")
    app.format_var.set("03d")
    app._save_settings()
    assert app.settings.chunk_size == 1000  # 保留原值
    assert app.settings.num_format == "001"


def test_multi_sheet_selector_appears(ui, xlsx_multi):
    app, _, _ = ui
    app._apply_input_file(xlsx_multi)
    assert app.sheet_var.get() == "First"
    assert app.sheet_combo.winfo_ismapped() or app.sheet_combo.grid_info()


def test_close_while_idle_does_not_ask(ui):
    app, box, _ = ui
    app.on_close()
    assert box.questions == []


def test_release_partial_root_destroys_extra_window(monkeypatch):
    """``TkinterDnD.Tk()`` 先建窗口、再加载 tkdnd；加载失败会留下空白 "tk" 窗口。

    这里不真的创建 Tk（同一进程内反复建/销毁多个 Tk 解释器会让测试进程崩溃），
    只验证回收逻辑本身。
    """
    destroyed: list[str] = []

    class FakeRoot:
        def destroy(self) -> None:
            destroyed.append("destroyed")

    extra = FakeRoot()
    monkeypatch.setattr(app_module.tk, "_default_root", extra)

    app_module.release_partial_root(object())  # 创建前的 root 不是它 -> 回收
    assert destroyed == ["destroyed"]

    app_module.release_partial_root(extra)  # 就是原来那个 -> 不能动
    assert destroyed == ["destroyed"]

    monkeypatch.setattr(app_module.tk, "_default_root", None)  # 没有 root -> 安全
    app_module.release_partial_root(object())
    assert destroyed == ["destroyed"]


def test_release_partial_root_survives_destroy_error(monkeypatch):
    class BrokenRoot:
        def destroy(self) -> None:
            raise RuntimeError("窗口已经没了")

    monkeypatch.setattr(app_module.tk, "_default_root", BrokenRoot())
    app_module.release_partial_root(object())  # 不应抛出


def test_cleanup_dialog_on_cancel(ui, basic_csv, tmp_path):
    app, box, root = ui
    out = tmp_path / "cleanup"
    app._apply_input_file(basic_csv)
    app.output_var.set(str(out))
    app.start_operation()
    app.cancel_operation()
    assert pump(root, lambda: app.state is AppState.IDLE)
    # 没有生成任何文件时不应该询问是否清理
    assert not any("删除" in title or "Remove" in title for title, _ in box.questions)
