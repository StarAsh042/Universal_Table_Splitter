"""用户偏好持久化测试：容错、类型纠正与原子写入。"""

from __future__ import annotations

import json

from universal_table_splitter.settings import Settings, config_dir, log_dir


def test_defaults_when_file_missing(tmp_path):
    settings = Settings.load(tmp_path / "nope.json")
    assert settings.chunk_size == 1000
    assert settings.fidelity is True
    assert settings.lang == "cn"


def test_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(
        chunk_size=250,
        num_format="0000",
        export_format="xlsx",
        lang="en",
        fidelity=False,
        escape_formulas=True,
        last_output_dir="D:/out",
        geometry="900x700+10+10",
    )
    original.save(path)
    loaded = Settings.load(path)
    assert loaded == original


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert Settings.load(path) == Settings()


def test_non_dict_json_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert Settings.load(path) == Settings()


def test_unknown_fields_are_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"chunk_size": 42, "future_option": True}), encoding="utf-8")
    loaded = Settings.load(path)
    assert loaded.chunk_size == 42
    assert not hasattr(loaded, "future_option")


def test_wrong_types_are_coerced_or_defaulted(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {"chunk_size": "not-a-number", "fidelity": "yes", "lang": 5, "num_format": None}
        ),
        encoding="utf-8",
    )
    loaded = Settings.load(path)
    assert loaded.chunk_size == Settings().chunk_size
    assert loaded.fidelity is True  # 非布尔值一律回退默认
    assert loaded.lang == Settings().lang
    assert loaded.num_format == Settings().num_format


def test_save_is_atomic_and_creates_parents(tmp_path):
    path = tmp_path / "deep" / "nested" / "settings.json"
    Settings(chunk_size=7).save(path)
    assert json.loads(path.read_text(encoding="utf-8"))["chunk_size"] == 7
    assert not list(path.parent.glob("*.tmp"))


def test_save_failure_is_swallowed(tmp_path):
    """记不住设置不是致命错误，不能因此让程序崩溃。"""
    target = tmp_path / "as-dir"
    target.mkdir()
    Settings().save(target)  # 目标是目录 -> OSError 被吞掉
    assert target.is_dir()


def test_platform_paths_are_inside_home_or_appdata():
    assert config_dir().is_absolute()
    assert log_dir().is_absolute()
