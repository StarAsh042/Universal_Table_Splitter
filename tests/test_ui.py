"""主窗口测试。

Qt 这边驱动测试简单得多：信号是同步派发的，模态框用 ``QMessageBox.exec``
打桩就能拦住。

覆盖的重点是**出问题用户立刻能感觉到的那些行为**：
预览是否读对、预估文件数是否跟着参数变、能不能真的切出文件、
覆盖冲突有没有按用户选择处理、语言切换会不会丢进度文本。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from universal_table_splitter import __version__
from universal_table_splitter.settings import Settings
from universal_table_splitter.ui.main_window import MainWindow, UiState

from .conftest import ROW_COUNT


@pytest.fixture(autouse=True)
def no_modal(monkeypatch):
    """拦掉所有模态框。

    离屏/无头环境下 ``QMessageBox.exec()`` 会永久阻塞，测试直接挂死。
    这里改成"记录文案后立刻返回"，测试再按需断言。
    """
    shown: list[str] = []

    def fake_exec(self) -> int:
        shown.append(self.text())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return shown


@pytest.fixture
def window(qapp):
    win = MainWindow(Settings())
    qapp.processEvents()
    yield win
    # 收尾：确保没有线程还在跑，否则 Qt 会报 "QThread destroyed while running"
    win._preview_timer.stop()
    win._abort_preview()
    for worker in (win._preflight_worker, win._split_worker):
        if worker is not None and worker.isRunning():
            worker.wait(5000)
    win.deleteLater()
    qapp.processEvents()


def wait_until(qapp, predicate, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def load_input(qapp, window, path: Path) -> bool:
    """设置输入文件并等预览得出结论（成功或失败都算）。"""
    window.input_picker.set_path(str(path))
    window._on_input_changed(str(path))
    return wait_until(
        qapp,
        lambda: window.preview.mode in ("data", "error"),
        timeout=30,
    )


def run_split(qapp, window, out_dir: Path, chunk_size: int = 3) -> bool:
    window.output_picker.set_path(str(out_dir))
    window.size_edit.setText(str(chunk_size))
    window.start_operation()
    return wait_until(qapp, lambda: window._state is UiState.IDLE, timeout=90)


# --------------------------------------------------------------------- 基本装配


def test_window_builds_with_version_in_title(window):
    assert __version__ in window.windowTitle()


def test_initial_state_is_idle_and_startable(window):
    assert window._state is UiState.IDLE
    assert window.start_button.isEnabled()
    assert not window.cancel_button.isEnabled()
    assert window.status_label.text()  # 有"准备就绪"之类的初始文案


def test_language_switch_updates_visible_texts(window):
    chinese = window.input_picker.title_label.text()
    window.toggle_language()
    english = window.input_picker.title_label.text()

    assert chinese != english
    assert window.windowTitle().count(__version__) == 1  # 版本号不会被语言切换弄丢


def test_language_switch_keeps_result_summary(window, basic_csv, out_dir, qapp):
    """运行中/完成后切语言，不能把已经算出来的结果文案冲掉。"""
    assert load_input(qapp, window, basic_csv)
    assert run_split(qapp, window, out_dir)

    summary = window.detail_label.text()
    assert summary

    window.toggle_language()

    assert window.detail_label.text() == summary


# --------------------------------------------------------------------- 预览


def test_preview_reports_metadata(window, basic_csv, qapp):
    assert load_input(qapp, window, basic_csv)

    payload = window.preview.payload
    assert payload is not None
    assert payload["ext"] == "csv"
    assert payload["encoding"] == "utf-8"
    assert payload["total_rows"] == ROW_COUNT
    assert payload["columns"][:4] == ["id", "artist", "count", "note"]
    assert len(payload["rows"]) == ROW_COUNT


def test_preview_shows_table_not_hint(window, basic_csv, qapp):
    assert load_input(qapp, window, basic_csv)
    assert window.preview._stack.currentIndex() == 1
    assert window.preview.table.rowCount() == ROW_COUNT


def test_unsupported_file_reports_error(window, tmp_path, qapp):
    bogus = tmp_path / "notes.txt"
    bogus.write_text("hello", encoding="utf-8")

    assert load_input(qapp, window, bogus)

    assert window.preview.payload is None
    assert window.preview._stack.currentIndex() == 0
    assert window.preview.hint_label.text()


def test_clearing_input_resets_preview(window, basic_csv, qapp):
    assert load_input(qapp, window, basic_csv)
    assert window.preview.payload is not None

    window.input_picker.set_path("")
    window._on_input_changed("")
    assert wait_until(qapp, lambda: window.preview.payload is None, timeout=5)


def test_missing_file_reports_error(window, tmp_path, qapp):
    assert load_input(qapp, window, tmp_path / "nope.csv")
    assert window.preview.payload is None


# --------------------------------------------------------------------- 参数与预估


def test_plan_label_follows_chunk_size(window, basic_csv, qapp):
    assert load_input(qapp, window, basic_csv)

    window.size_edit.setText("4")
    assert "3" in window.plan_label.text()  # 10 行 / 每份 4 行 = 3 个文件

    window.size_edit.setText("100")
    assert "1" in window.plan_label.text()


def test_plan_label_is_unknown_without_rows(window):
    window.size_edit.setText("1000")
    assert window.plan_label.text()  # 没有预览时给出"无法预估"的说明而不是空白


def test_export_formats_follow_input_type(window, json_file, qapp):
    assert load_input(qapp, window, json_file)
    # JSON 输入的默认导出格式是 JSON 本身（与输入同族）
    assert window.export_combo.itemData(0) == "json"


def test_export_formats_include_csv_for_json(window, json_file, qapp):
    assert load_input(qapp, window, json_file)
    keys = {window.export_combo.itemData(i) for i in range(window.export_combo.count())}
    assert {"json", "csv", "xlsx"} <= keys


def test_multi_sheet_selector_appears_for_excel(window, xlsx_multi, qapp):
    assert load_input(qapp, window, xlsx_multi)

    assert not window.sheet_combo.isHidden()
    names = [window.sheet_combo.itemData(i) for i in range(window.sheet_combo.count())]
    assert "First" in names and "Second" in names


def test_sheet_selector_hidden_for_csv(window, basic_csv, qapp):
    assert load_input(qapp, window, basic_csv)
    assert window.sheet_combo.isHidden()


# --------------------------------------------------------------------- 执行


def test_end_to_end_split_through_ui(window, basic_csv, out_dir, qapp):
    assert load_input(qapp, window, basic_csv)

    assert run_split(qapp, window, out_dir, chunk_size=3)

    produced = sorted(p.name for p in out_dir.glob("*.csv"))
    assert produced == [
        "artists_001.csv",
        "artists_002.csv",
        "artists_003.csv",
        "artists_004.csv",
    ]
    assert window.progress_bar.value() == 100
    assert str(ROW_COUNT) in window.detail_label.text().replace(",", "")


def test_rows_are_not_lost_across_chunks(window, basic_csv, out_dir, qapp):
    import csv

    assert load_input(qapp, window, basic_csv)
    assert run_split(qapp, window, out_dir, chunk_size=3)

    total = 0
    for path in out_dir.glob("*.csv"):
        with path.open(encoding="utf-8", newline="") as handle:
            total += len(list(csv.reader(handle))) - 1  # 减去表头
    assert total == ROW_COUNT


def test_running_twice_is_stable(window, basic_csv, out_dir, qapp, monkeypatch):
    """第二次运行时输出目录里已有同名文件，选择"覆盖"后产物必须与第一次完全一致。"""
    monkeypatch.setattr(window, "_confirm", lambda *a, **k: True)  # 一律选"覆盖"
    assert load_input(qapp, window, basic_csv)

    assert run_split(qapp, window, out_dir, chunk_size=5)
    first = sorted(p.name for p in out_dir.glob("*.csv"))

    assert run_split(qapp, window, out_dir, chunk_size=5)
    second = sorted(p.name for p in out_dir.glob("*.csv"))

    assert first == second


def test_invalid_chunk_size_is_reported(window, basic_csv, out_dir, qapp, no_modal):
    assert load_input(qapp, window, basic_csv)
    window.output_picker.set_path(str(out_dir))
    window.size_edit.setText("0")  # 0 不是合法行数

    window.start_operation()
    qapp.processEvents()

    assert window._state is UiState.IDLE
    assert no_modal  # 弹了错误提示
    assert not list(out_dir.glob("*.csv"))


def test_start_is_ignored_while_busy(window, basic_csv, out_dir, qapp):
    """重入保护：运行中再点开始不能起第二个线程。"""
    assert load_input(qapp, window, basic_csv)
    window.output_picker.set_path(str(out_dir))

    window._set_state(UiState.RUNNING)
    window.start_operation()

    assert window._split_worker is None
    assert window._preflight_worker is None
    window._set_state(UiState.IDLE)


def test_controls_are_disabled_while_running(window, basic_csv, qapp):
    assert load_input(qapp, window, basic_csv)

    window._set_state(UiState.RUNNING)

    assert not window.input_picker.edit.isEnabled()
    assert not window.size_edit.isEnabled()
    assert not window.start_button.isEnabled()
    assert window.cancel_button.isEnabled()
    window._set_state(UiState.IDLE)


def test_cancel_sets_event_and_cancelling_state(window, basic_csv, qapp):
    assert load_input(qapp, window, basic_csv)
    window._set_state(UiState.RUNNING)

    window.cancel_operation()

    assert window._cancel.is_set()
    assert window._state is UiState.CANCELLING


def test_cancel_while_idle_does_nothing(window):
    window.cancel_operation()
    assert not window._cancel.is_set()
    assert window._state is UiState.IDLE


def test_overwrite_refusal_keeps_existing_file(window, basic_csv, out_dir, qapp, monkeypatch):
    """用户选择"保留并加序号"时，原文件必须原样不动。"""
    import csv

    assert load_input(qapp, window, basic_csv)

    existing = out_dir / "artists_001.csv"
    existing.write_text("sentinel\n", encoding="utf-8")
    monkeypatch.setattr(window, "_confirm", lambda *a, **k: False)

    assert run_split(qapp, window, out_dir, chunk_size=3)

    assert existing.read_text(encoding="utf-8") == "sentinel\n"
    assert len(list(out_dir.glob("*.csv"))) > 4  # 冲突的那一份换了名字
    with existing.open(encoding="utf-8") as handle:
        assert len(list(csv.reader(handle))) == 1


def test_open_output_dir_is_safe_when_missing(window):
    window.open_output_dir()  # 没有结果也没有输出目录，应该安静地什么都不做


def test_close_while_idle_is_accepted(window):
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_close_while_running_asks_first(window, basic_csv, qapp, monkeypatch):
    assert load_input(qapp, window, basic_csv)
    window._set_state(UiState.RUNNING)

    asked: list[str] = []
    monkeypatch.setattr(window, "_confirm", lambda kind, **kw: asked.append(kind) or False)

    event = QCloseEvent()
    window.closeEvent(event)

    assert asked == ["close"]
    assert not event.isAccepted()  # 用户选了"继续等待"，窗口不关
    window._cancel.clear()
    window._set_state(UiState.IDLE)


# --------------------------------------------------------------------- 设置持久化


def test_settings_are_saved_from_widgets(window, qapp):
    window.size_edit.setText("777")
    window.format_edit.setText("01")
    window.fidelity_check.setChecked(False)
    window.escape_check.setChecked(True)

    window._save_settings()

    reloaded = Settings.load()
    assert reloaded.chunk_size == 777
    assert reloaded.num_format == "01"
    assert reloaded.fidelity is False
    assert reloaded.escape_formulas is True
    assert reloaded.geometry.startswith(f"{window.width()}x{window.height()}")


def test_invalid_chunk_size_falls_back_to_previous_value(window, qapp):
    window._settings = Settings(chunk_size=1234)
    window.size_edit.setText("abc")  # 非法输入不该被写进设置

    window._save_settings()

    assert Settings.load().chunk_size == 1234


def test_language_is_persisted(window, qapp):
    window.toggle_language()
    window._save_settings()
    assert Settings.load().lang == window._lang


def test_geometry_round_trip(window, qapp):
    window._settings = Settings(geometry="1000x900+40+60")
    window._restore_settings()
    assert window.width() == 1000
    assert window.height() == 900


def test_broken_geometry_is_ignored(window, qapp):
    window._settings = Settings(geometry="not-a-geometry")
    window._restore_settings()  # 不应该抛异常
    assert window.width() > 0
